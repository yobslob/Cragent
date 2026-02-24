"""
Shared pytest fixtures for the test suite.
"""

import pytest

from src.config import Config
from src.state import TestCase, TestResult, AgentState


@pytest.fixture
def sample_config():
    """Return a Config with test-friendly defaults."""
    return Config(
        target_url="https://example.com",
        max_depth=2,
        batch_size=3,
        max_retries=2,
        max_concurrency=1,
        headless=True,
        primary_model="gpt-4o-mini",
        fallback_model="gpt-4o-mini",
        evaluator_model="gpt-4o-mini",
        synthesizer_model="gpt-4o-mini",
        node_inactivity_timeout_seconds=30,
        node_absolute_timeout_seconds=60,
        graph_timeout_seconds=120,
    )


@pytest.fixture
def sample_test_case() -> TestCase:
    """Return a minimal valid TestCase."""
    return TestCase(
        test_id="TC-001",
        description="Verify homepage loads",
        category="navigation",
        priority=1,
        target_url="https://example.com",
        steps=["Navigate to https://example.com", "Verify page loads"],
        expected_outcome="Page loads with interactive elements",
        failure_criteria="Page fails to load",
        is_destructive=False,
        requires_auth=False,
        setup_steps=[],
        conflict_group=None,
    )


@pytest.fixture
def sample_test_result() -> TestResult:
    """Return a minimal valid TestResult."""
    return TestResult(
        test_id="TC-001",
        status="PASS",
        tested_surface="https://example.com",
        target_url="https://example.com",
        observations="Page loaded successfully with navigation links",
        discovered_elements=["search bar", "navigation menu"],
        retry_count=0,
        round_number=1,
    )


@pytest.fixture
def sample_agent_state(sample_test_case) -> dict:
    """Return a minimal valid AgentState dict."""
    return {
        "target_url": "https://example.com",
        "current_url": "https://example.com",
        "a11y_tree": "",
        "tasks_to_execute": [sample_test_case],
        "past_results": [],
        "current_depth": 1,
        "max_depth": 5,
        "max_retries": 3,
        "status": "planning",
        "evaluator_decision": {
            "decision": "CONTINUE_TESTING",
            "next_url": None,
            "focus_areas": [],
            "reasoning": "",
        },
        "testing_instructions": "",
        "chat_history": [],
        "pending_message": "",
        "user_provided_context": "",
        "captcha_state_registry": {},
        "blocked_url": "",
        "credentials": {},
        "shared_auth_state": None,
        "max_concurrency": 3,
    }


@pytest.fixture
def sample_results_multi_round() -> list[TestResult]:
    """Return test results spanning multiple rounds."""
    return [
        TestResult(
            test_id="TC-001", status="PASS", tested_surface="homepage",
            target_url="https://example.com", observations="Page loaded",
            discovered_elements=["nav"], retry_count=0, round_number=1,
        ),
        TestResult(
            test_id="TC-002", status="FAIL", tested_surface="search",
            target_url="https://example.com/search", observations="Search returned no results",
            discovered_elements=[], retry_count=2, round_number=1,
        ),
        TestResult(
            test_id="TC-003", status="PASS", tested_surface="about",
            target_url="https://example.com/about", observations="About page loaded",
            discovered_elements=["contact form"], retry_count=0, round_number=2,
        ),
        TestResult(
            test_id="TC-004", status="BLOCKED_CAPTCHA", tested_surface="login",
            target_url="https://example.com/login",
            observations="BLOCKED_CAPTCHA: Detected reCAPTCHA",
            discovered_elements=[], retry_count=0, round_number=2,
        ),
        TestResult(
            test_id="TC-005", status="FAIL", tested_surface="contact",
            target_url="https://example.com/contact",
            observations="Form submission failed with validation error",
            discovered_elements=["error message"], retry_count=1, round_number=3,
        ),
    ]
