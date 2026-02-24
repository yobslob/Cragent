"""
CLI entry point for the Autonomous Testing Agent.

Usage:
    python run.py --url "https://example.com"
    python run.py --url "https://myapp.com" --instructions "Focus on login flow"
    python run.py --url "https://amazon.in" --max-depth 10 --max-concurrency 5
"""

import argparse
import asyncio
import sys
import urllib.request
import urllib.error
from uuid import uuid4

from dotenv import load_dotenv

from src.config import load_config
from src.graph import build_graph
from src.hitl.cli import run_with_cli_hitl, print_startup_banner, print_completion_summary
from src.security.redaction import RedactingCallbackHandler


def _check_ollama(base_url: str, model: str) -> None:
    """
    Verify Ollama is reachable before starting the graph.

    Prints a warning (not a fatal error) so the agent can still attempt
    to run — some models load slowly and may respond after the initial check.
    """
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/tags",
            headers={"Accept": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", str(e))
        print(f"\n  WARNING: Cannot reach Ollama at {base_url}")
        print(f"  Reason: {reason}")
        print(f"  Make sure Ollama is running:  ollama serve")
        print(f"  Make sure the model is pulled: ollama pull {model}\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="LLM-Powered Autonomous Website Testing Agent"
    )
    parser.add_argument(
        "--url", required=True,
        help="Target URL to test (e.g., https://example.com)"
    )
    parser.add_argument(
        "--instructions", default=None,
        help="Testing scope instructions (e.g., 'Focus on checkout flow')"
    )
    parser.add_argument(
        "--max-depth", type=int, default=None,
        help="Max planning rounds (default: 5)"
    )
    parser.add_argument(
        "--max-concurrency", type=int, default=None,
        help="Max parallel browser contexts (default: 3)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="Test cases per round (default: 5)"
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config.yaml file"
    )
    parser.add_argument(
        "--headless", action="store_true", default=None,
        help="Run browsers in headless mode (default)"
    )
    parser.add_argument(
        "--no-headless", action="store_true", default=None,
        help="Run browsers with visible UI (for debugging)"
    )

    return parser.parse_args()


async def main():
    # Load environment variables
    load_dotenv()

    args = parse_args()

    # Build CLI overrides dict
    cli_overrides = {
        "target_url": args.url,
    }
    if args.instructions:
        cli_overrides["testing_instructions"] = args.instructions
    if args.max_depth is not None:
        cli_overrides["max_depth"] = args.max_depth
    if args.max_concurrency is not None:
        cli_overrides["max_concurrency"] = args.max_concurrency
    if args.batch_size is not None:
        cli_overrides["batch_size"] = args.batch_size
    if args.no_headless:
        cli_overrides["headless"] = False
    elif args.headless:
        cli_overrides["headless"] = True

    # Load config (3-layer merge)
    config = load_config(yaml_path=args.config, cli_args=cli_overrides)

    # Print startup banner
    print_startup_banner(config.target_url, config)

    # Verify Ollama is reachable (fast-fail check before any graph nodes run)
    for model in {config.primary_model, config.fallback_model}:
        if model.startswith("ollama/"):
            _check_ollama(config.ollama_base_url, model.split("/", 1)[1])
            break

    # Build graph
    graph = build_graph(config)

    # Construct initial state
    initial_state = {
        "target_url": config.target_url,
        "current_url": config.target_url,
        "a11y_tree": "",
        "tasks_to_execute": [],
        "past_results": [],
        "current_depth": 1,
        "max_depth": config.max_depth,
        "max_retries": config.max_retries,
        "status": "planning",
        "evaluator_decision": {
            "decision": "CONTINUE_TESTING",
            "next_url": None,
            "focus_areas": [],
            "reasoning": "",
        },
        "testing_instructions": config.testing_instructions,
        "chat_history": [],
        "pending_message": "",
        "user_provided_context": "",
        "captcha_state_registry": {},
        "blocked_url": "",
        "credentials": {},
        "shared_auth_state": None,
        "max_concurrency": config.max_concurrency,
    }

    # Runtime config
    callbacks = []
    if config.credential_redaction_enabled:
        callbacks.append(RedactingCallbackHandler())

    runtime_config = {
        "configurable": {"thread_id": str(uuid4())},
        "max_concurrency": config.max_concurrency,
        "recursion_limit": config.max_graph_iterations,
        "callbacks": callbacks,
    }

    # Run with HITL support
    try:
        result = await run_with_cli_hitl(graph, initial_state, runtime_config)
        print_completion_summary(result if isinstance(result, dict) else initial_state)
    except KeyboardInterrupt:
        print("\n\nRun interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
