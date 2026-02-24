"""Tests for state schema, models, and reducers."""

from src.state import (
    TestCaseModel,
    TestResultModel,
    EvaluatorDecisionModel,
    dedup_results_reducer,
)


class TestDedupResultsReducer:
    def test_appends_new_results(self):
        existing = [
            {"test_id": "TC-001", "round_number": 1, "status": "PASS",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ]
        new = [
            {"test_id": "TC-002", "round_number": 1, "status": "FAIL",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ]
        result = dedup_results_reducer(existing, new)
        assert len(result) == 2
        assert result[1]["test_id"] == "TC-002"

    def test_deduplicates_by_test_id_and_round(self):
        existing = [
            {"test_id": "TC-001", "round_number": 1, "status": "PASS",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ]
        duplicate = [
            {"test_id": "TC-001", "round_number": 1, "status": "FAIL",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ]
        result = dedup_results_reducer(existing, duplicate)
        assert len(result) == 1
        assert result[0]["status"] == "PASS"  # Keeps existing, ignores duplicate

    def test_same_test_id_different_rounds(self):
        existing = [
            {"test_id": "TC-001", "round_number": 1, "status": "PASS",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ]
        new = [
            {"test_id": "TC-001", "round_number": 2, "status": "FAIL",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ]
        result = dedup_results_reducer(existing, new)
        assert len(result) == 2

    def test_empty_existing(self):
        result = dedup_results_reducer([], [
            {"test_id": "TC-001", "round_number": 1, "status": "PASS",
             "tested_surface": "", "target_url": "", "observations": "",
             "discovered_elements": [], "retry_count": 0},
        ])
        assert len(result) == 1


class TestPydanticModels:
    def test_test_case_model_valid(self):
        model = TestCaseModel(
            test_id="TC-001",
            description="Test homepage",
            category="navigation",
            priority=1,
            target_url="https://example.com",
            steps=["Navigate to URL"],
            expected_outcome="Page loads",
            failure_criteria="Page fails",
        )
        assert model.test_id == "TC-001"
        assert model.is_destructive is False  # Default
        assert model.conflict_group is None   # Default

    def test_test_case_model_to_dict(self):
        model = TestCaseModel(
            test_id="TC-001", description="Test", category="navigation",
            priority=1, target_url="https://example.com",
            steps=["Step 1"], expected_outcome="OK", failure_criteria="Fail",
        )
        d = model.to_dict()
        assert d["test_id"] == "TC-001"
        assert isinstance(d, dict)

    def test_test_result_model_valid_statuses(self):
        for status in ["PASS", "FAIL", "BLOCKED_CAPTCHA"]:
            model = TestResultModel(test_id="TC-001", status=status)
            assert model.status == status

    def test_evaluator_decision_model_valid_decisions(self):
        for decision in ["CONTINUE_TESTING", "TESTING_COMPLETE", "RE_AUTHENTICATE"]:
            model = EvaluatorDecisionModel(decision=decision)
            assert model.decision == decision

    def test_evaluator_decision_to_dict(self):
        model = EvaluatorDecisionModel(
            decision="CONTINUE_TESTING",
            next_url="https://example.com/cart",
            focus_areas=["checkout"],
            reasoning="Need to test cart",
        )
        d = model.to_dict()
        assert d["decision"] == "CONTINUE_TESTING"
        assert d["next_url"] == "https://example.com/cart"
