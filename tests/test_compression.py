"""Tests for past results compression."""

from src.compression.past_results import (
    compress_past_results,
    format_results_verbatim,
    format_failures_compact,
    summarize_rounds,
    summarize_global,
)


class TestCompressPastResults:
    def test_empty_results(self):
        result = compress_past_results([], current_depth=1)
        assert "No previous" in result

    def test_single_round_verbatim(self, sample_results_multi_round):
        results = [r for r in sample_results_multi_round if r["round_number"] == 1]
        compressed = compress_past_results(results, current_depth=2)
        assert "TC-001" in compressed
        assert "TC-002" in compressed

    def test_failures_always_preserved(self, sample_results_multi_round):
        compressed = compress_past_results(
            sample_results_multi_round,
            current_depth=4,
            token_budget=5000,
        )
        # FAIL results from older rounds should be present
        assert "TC-002" in compressed  # Failed in round 1
        assert "TC-005" in compressed  # Failed in round 3

    def test_budget_enforcement(self, sample_results_multi_round):
        # Very tight budget should still produce output
        compressed = compress_past_results(
            sample_results_multi_round,
            current_depth=4,
            token_budget=50,
        )
        assert len(compressed) > 0


class TestFormatResultsVerbatim:
    def test_no_results(self):
        assert "No results" in format_results_verbatim([])

    def test_includes_test_id_and_status(self):
        results = [{
            "test_id": "TC-001", "status": "PASS",
            "tested_surface": "homepage",
            "observations": "Page loaded",
            "discovered_elements": ["nav"],
            "retry_count": 0,
        }]
        text = format_results_verbatim(results)
        assert "TC-001" in text
        assert "PASS" in text
        assert "homepage" in text


class TestFormatFailuresCompact:
    def test_no_failures(self):
        assert format_failures_compact([]) == "None"

    def test_truncates_long_observations(self):
        failures = [{
            "test_id": "TC-001",
            "tested_surface": "search",
            "observations": "x" * 300,
        }]
        text = format_failures_compact(failures)
        assert len(text) < 300


class TestSummarizeRounds:
    def test_groups_by_round(self, sample_results_multi_round):
        summaries = summarize_rounds(sample_results_multi_round)
        assert len(summaries) == 3  # Rounds 1, 2, 3


class TestSummarizeGlobal:
    def test_empty(self):
        assert "No historical" in summarize_global([])

    def test_includes_stats(self, sample_results_multi_round):
        text = summarize_global(sample_results_multi_round)
        assert "passed" in text
        assert "failed" in text
