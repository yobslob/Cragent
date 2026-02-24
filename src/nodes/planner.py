"""
Planner node — the strategic intelligence that generates test plans.

Fetches the A11y tree, reviews past results, and produces a structured
batch of test cases for the Executors to carry out.
"""

import json

from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt

from src.config import Config
from src.state import AgentState, TestCaseModel, PlannerOutput
from src.prompts import PLANNER_SYSTEM_PROMPT
from src.compression.past_results import compress_past_results
from src.security.vault import CredentialVault
from src.llm.factory import create_llm
from src.llm.retry import call_llm_with_fallback
from src.tools.planner_tools import create_planner_tools


def _build_planner_message(state: AgentState, vault: CredentialVault) -> str:
    """Construct the user message for the Planner LLM."""
    parts = []

    parts.append(f"Target URL: {state.get('target_url', '')}")
    parts.append(f"Current URL to test: {state.get('current_url', state.get('target_url', ''))}")
    parts.append(
        f"Round: {state.get('current_depth', 1)} of {state.get('max_depth', 5)}"
    )

    instructions = state.get("testing_instructions", "")
    if instructions:
        parts.append(f"\nUser Instructions:\n{instructions}")

    # Credential availability (not values)
    domains = vault.get_available_domains()
    if domains:
        parts.append(
            f"\nCredentials available for: {', '.join(domains)}. "
            "Use {{vault:username}} and {{vault:password}} in test steps."
        )

    # Compressed past results
    past_results = state.get("past_results", [])
    if past_results:
        current_depth = state.get("current_depth", 1)
        token_budget = 2000  # Could come from config
        compressed = compress_past_results(past_results, current_depth, token_budget)
        parts.append(f"\nPast Results:\n{compressed}")
    else:
        parts.append("\nThis is the first testing round. No past results yet.")

    # User-provided context from HITL interrupts
    user_context = state.get("user_provided_context", "")
    if user_context:
        parts.append(f"\nAdditional context from user:\n{user_context}")

    return "\n".join(parts)


def _parse_test_cases(llm_output: str) -> list[dict]:
    """
    Parse the Planner LLM's output into a list of TestCase dicts.

    Tries structured JSON parsing first, falls back to extracting JSON from text.
    """
    # Try to find JSON array in the output
    text = llm_output.strip()

    # Look for JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            raw_cases = json.loads(text[start:end + 1])
            validated = []
            for case in raw_cases:
                try:
                    model = TestCaseModel(**case)
                    validated.append(model.to_dict())
                except Exception:
                    # Skip malformed individual cases
                    continue
            if validated:
                return validated
        except json.JSONDecodeError:
            pass

    # Try parsing the entire output as JSON
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [TestCaseModel(**c).to_dict() for c in data]
        if isinstance(data, dict) and "test_cases" in data:
            return [TestCaseModel(**c).to_dict() for c in data["test_cases"]]
    except (json.JSONDecodeError, Exception):
        pass

    return []


async def planner_node(state: AgentState, config: Config) -> dict:
    """
    Planner node: generates a batch of test cases.

    1. Builds prompt with current URL, past results, instructions
    2. Creates react agent with fetch_accessibility_tree tool
    3. LLM calls the tool during reasoning
    4. Parses structured output into TestCase list
    5. Returns tasks_to_execute for fan-out to Executors
    """
    vault = CredentialVault(state.get("credentials"))

    # Create LLM
    llm = create_llm(
        config.primary_model,
        config.temperature,
        ollama_base_url=config.ollama_base_url,
        ollama_num_ctx=config.ollama_num_ctx,
    )
    fallback_llm = create_llm(
        config.fallback_model,
        config.temperature,
        ollama_base_url=config.ollama_base_url,
        ollama_num_ctx=config.ollama_num_ctx,
    )

    # Create tools
    planner_tools = create_planner_tools(config)

    # Build the react agent
    agent = create_react_agent(
        llm,
        tools=planner_tools,
        prompt=PLANNER_SYSTEM_PROMPT,
    )

    # Construct the input message
    user_message = _build_planner_message(state, vault)

    # Invoke the agent
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_message}]}
        )

        # Extract the last assistant message
        messages = result.get("messages", [])
        last_message = ""
        for msg in reversed(messages):
            content = msg.content if hasattr(msg, "content") else str(msg)
            if content:
                last_message = content
                break

        # Parse test cases
        test_cases = _parse_test_cases(last_message)

        if not test_cases:
            # Retry once with explicit schema reminder
            retry_msg = (
                "Your previous response could not be parsed into test cases. "
                "Please respond with a valid JSON array of test case objects. "
                "Each object must have: test_id, description, category, priority, "
                "target_url, steps, expected_outcome, failure_criteria, "
                "is_destructive, requires_auth, setup_steps, conflict_group."
            )
            result = await agent.ainvoke(
                {"messages": [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": last_message},
                    {"role": "user", "content": retry_msg},
                ]}
            )
            messages = result.get("messages", [])
            for msg in reversed(messages):
                content = msg.content if hasattr(msg, "content") else str(msg)
                if content:
                    last_message = content
                    break
            test_cases = _parse_test_cases(last_message)

        if not test_cases:
            # Generate a minimal fallback test case
            test_cases = [{
                "test_id": "TC-FALLBACK-001",
                "description": "Verify page loads and has interactive elements",
                "category": "navigation",
                "priority": 1,
                "target_url": state.get("current_url", state.get("target_url", "")),
                "steps": [
                    f"Navigate to {state.get('current_url', state.get('target_url', ''))}",
                    "Check that the page loads and has interactive elements",
                ],
                "expected_outcome": "Page loads with interactive elements visible",
                "failure_criteria": "Page fails to load or has no interactive elements",
                "is_destructive": False,
                "requires_auth": False,
                "setup_steps": [],
                "conflict_group": None,
            }]

        return {
            "tasks_to_execute": test_cases,
            "status": "executing",
        }

    except Exception as e:
        # If the planner completely fails, return a minimal test set
        return {
            "tasks_to_execute": [{
                "test_id": "TC-ERROR-001",
                "description": f"Planner error: {str(e)[:100]}",
                "category": "navigation",
                "priority": 1,
                "target_url": state.get("current_url", state.get("target_url", "")),
                "steps": [
                    f"Navigate to {state.get('current_url', state.get('target_url', ''))}",
                    "Verify page loads",
                ],
                "expected_outcome": "Page loads successfully",
                "failure_criteria": "Page fails to load",
                "is_destructive": False,
                "requires_auth": False,
                "setup_steps": [],
                "conflict_group": None,
            }],
            "status": "executing",
        }
