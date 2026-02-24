"""
AgentState schema, TypedDicts, Pydantic models, and reducers.

Defines the data contract shared between all graph nodes.
"""

from typing import TypedDict, Literal, Optional, Annotated
from pydantic import BaseModel, Field
from langgraph.graph import add_messages


# ---------------------------------------------------------------------------
# TypedDict schemas (used by LangGraph state)
# ---------------------------------------------------------------------------

class TestCase(TypedDict):
    test_id: str
    description: str
    category: str
    priority: int
    target_url: str
    steps: list[str]
    expected_outcome: str
    failure_criteria: str
    is_destructive: bool
    requires_auth: bool
    setup_steps: list[str]
    conflict_group: Optional[str]


class TestResult(TypedDict):
    test_id: str
    status: Literal["PASS", "FAIL", "BLOCKED_CAPTCHA"]
    tested_surface: str
    target_url: str
    observations: str
    discovered_elements: list[str]
    retry_count: int
    round_number: int


class EvaluatorDecision(TypedDict):
    decision: Literal["CONTINUE_TESTING", "TESTING_COMPLETE", "RE_AUTHENTICATE"]
    next_url: Optional[str]
    focus_areas: list[str]
    reasoning: str


# ---------------------------------------------------------------------------
# Pydantic models (used for LLM structured output parsing & validation)
# ---------------------------------------------------------------------------

class TestCaseModel(BaseModel):
    test_id: str
    description: str
    category: str = Field(
        description="One of: navigation, forms, search, auth, e-commerce, accessibility, content"
    )
    priority: int = Field(ge=1, le=4, description="1=highest, 4=lowest")
    target_url: str
    steps: list[str]
    expected_outcome: str
    failure_criteria: str
    is_destructive: bool = False
    requires_auth: bool = False
    setup_steps: list[str] = Field(default_factory=list)
    conflict_group: Optional[str] = None

    def to_dict(self) -> TestCase:
        return TestCase(**self.model_dump())


class TestResultModel(BaseModel):
    test_id: str
    status: Literal["PASS", "FAIL", "BLOCKED_CAPTCHA"]
    tested_surface: str = ""
    target_url: str = ""
    observations: str = ""
    discovered_elements: list[str] = Field(default_factory=list)
    retry_count: int = 0
    round_number: int = 0

    def to_dict(self) -> TestResult:
        return TestResult(**self.model_dump())


class EvaluatorDecisionModel(BaseModel):
    decision: Literal["CONTINUE_TESTING", "TESTING_COMPLETE", "RE_AUTHENTICATE"]
    next_url: Optional[str] = None
    focus_areas: list[str] = Field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> EvaluatorDecision:
        return EvaluatorDecision(**self.model_dump())


class PlannerOutput(BaseModel):
    """Structured output expected from the Planner LLM."""
    reasoning: str = Field(description="Brief reasoning about what to test and why")
    test_cases: list[TestCaseModel] = Field(description="List of test cases to execute")


# ---------------------------------------------------------------------------
# Reducers
# ---------------------------------------------------------------------------

def dedup_results_reducer(
    existing: list[TestResult], new: list[TestResult]
) -> list[TestResult]:
    """
    Append-with-deduplication reducer for past_results.

    Prevents duplicate TestResult entries when a graph checkpoint
    is resumed or a node retries. Deduplicates by (test_id, round_number)
    composite key.
    """
    seen = {(r["test_id"], r["round_number"]) for r in existing}
    merged = list(existing)
    for result in new:
        key = (result["test_id"], result["round_number"])
        if key not in seen:
            seen.add(key)
            merged.append(result)
    return merged


# ---------------------------------------------------------------------------
# AgentState — the shared state object passed between all graph nodes
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    # Core Fields
    target_url: str
    current_url: str
    a11y_tree: str
    tasks_to_execute: list[TestCase]
    past_results: Annotated[list[TestResult], dedup_results_reducer]
    current_depth: int
    max_depth: int
    max_retries: int
    status: Literal[
        "planning", "executing", "evaluating",
        "awaiting_user_input", "blocked_captcha", "done"
    ]

    # Evaluator Output
    evaluator_decision: EvaluatorDecision

    # Human-in-the-Loop Fields
    testing_instructions: str
    chat_history: Annotated[list[dict], add_messages]
    pending_message: str
    user_provided_context: str

    # Bot Defense Fields
    captcha_state_registry: dict[str, str]
    blocked_url: str

    # Authentication
    credentials: dict
    shared_auth_state: Optional[str]

    # Concurrency Control
    max_concurrency: int
