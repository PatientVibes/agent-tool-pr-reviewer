"""Tests for the v0.4.0 multi-model consensus module."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pr_reviewer.consensus import (
    DEFAULT_BASKET,
    PerModelResult,
    _evidence_overlap,
    _findings_match,
    _jaccard_3gram,
    merge_reports,
    resolve_models_arg,
)
from pr_reviewer.schema import Finding, ModelUsage, Report, RunMetadata


FIXTURES = Path(__file__).parent / "fixtures"


def _load_corpus() -> dict:
    return json.loads((FIXTURES / "multi_model_findings.json").read_text(encoding="utf-8"))


def _make_finding(**overrides) -> Finding:
    base = dict(
        category="bug", severity="medium",
        file="src/x.py", line_start=1, line_end=1,
        title="t", description="d", evidence="e",
    )
    base.update(overrides)
    return Finding(**base)


def _make_report(findings: list[Finding], model: str = "test-model") -> Report:
    metadata = RunMetadata(
        branch="b", base_ref="master",
        commit_head="a" * 40, commit_base="b" * 40,
        started_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        duration_seconds=1.0,
        model=model, tokens_input=10, tokens_output=5,
    )
    return Report(metadata=metadata, rules_loaded=[], findings=findings)


class TestJaccard3Gram:
    def test_identical_strings_score_1(self):
        assert _jaccard_3gram("hello world", "hello world") == 1.0

    def test_disjoint_strings_score_0(self):
        assert _jaccard_3gram("abc def", "xyz pqr") == 0.0

    def test_async_await_phrasings_clear_threshold(self):
        # Paraphrasings of the same bug: assert the algorithm clears the 0.3
        # threshold on titles that share substantial 3-gram overlap.
        # (NB: the corpus convergent_3of3 titles do NOT clear 0.3 — they match
        # via the evidence-overlap fallback, which is by design.)
        a = "Missing await keyword on commit"
        b = "Missing await on async commit"
        score = _jaccard_3gram(a, b)
        assert score >= 0.3, f"expected >= 0.3 for same-bug phrasings, got {score}"

    def test_unrelated_titles_below_threshold(self):
        a = "Off-by-one in loop bound"
        b = "Hardcoded timeout value"
        score = _jaccard_3gram(a, b)
        assert score < 0.3, f"expected < 0.3 for different bugs, got {score}"


class TestEvidenceOverlap:
    def test_identical_evidence_overlaps(self):
        assert _evidence_overlap("foo bar", "foo bar") is True

    def test_substring_overlaps_either_direction(self):
        assert _evidence_overlap("session.commit()", "    session.commit()") is True
        assert _evidence_overlap("    session.commit()", "session.commit()") is True

    def test_disjoint_evidence_does_not_overlap(self):
        assert _evidence_overlap("foo()", "bar()") is False


class TestFindingsMatch:
    def test_same_file_overlapping_lines_similar_title_matches(self):
        a = _make_finding(file="src/x.py", line_start=10, line_end=12, title="Missing await on commit")
        b = _make_finding(file="src/x.py", line_start=11, line_end=11, title="Async commit not awaited")
        assert _findings_match(a, b) is True

    def test_same_file_overlapping_lines_evidence_overlap_matches(self):
        a = _make_finding(file="src/x.py", line_start=10, line_end=12, title="Unrelated A", evidence="session.commit()")
        b = _make_finding(file="src/x.py", line_start=10, line_end=10, title="Different B", evidence="    session.commit()")
        assert _findings_match(a, b) is True

    def test_different_files_dont_match(self):
        a = _make_finding(file="src/x.py", line_start=10, line_end=10)
        b = _make_finding(file="src/y.py", line_start=10, line_end=10)
        assert _findings_match(a, b) is False

    def test_same_file_disjoint_lines_dont_match(self):
        a = _make_finding(file="src/x.py", line_start=10, line_end=12, title="Same title here", evidence="foo")
        b = _make_finding(file="src/x.py", line_start=20, line_end=22, title="Same title here", evidence="bar")
        assert _findings_match(a, b) is False

    def test_exactly_one_line_overlap_matches(self):
        a = _make_finding(file="src/x.py", line_start=10, line_end=12, title="Missing await on commit")
        b = _make_finding(file="src/x.py", line_start=12, line_end=14, title="Async commit not awaited")
        assert _findings_match(a, b) is True

    def test_project_rule_same_rule_id_matches_across_lines(self):
        a = Finding(
            category="project_rule", severity="low",
            file="src/x.py", line_start=10, line_end=10,
            rule_id="no-bare-fences", title="t1", description="d1", evidence="```",
        )
        b = Finding(
            category="project_rule", severity="low",
            file="src/x.py", line_start=80, line_end=80,
            rule_id="no-bare-fences", title="t2", description="d2", evidence="```",
        )
        assert _findings_match(a, b) is True

    def test_project_rule_different_rule_id_dont_match(self):
        a = Finding(
            category="project_rule", severity="low",
            file="src/x.py", line_start=10, line_end=10,
            rule_id="rule-a", title="t1", description="d1", evidence="```",
        )
        b = Finding(
            category="project_rule", severity="low",
            file="src/x.py", line_start=10, line_end=10,
            rule_id="rule-b", title="t2", description="d2", evidence="```",
        )
        assert _findings_match(a, b) is False

    def test_mixed_category_same_file_dont_match(self):
        a = _make_finding(category="bug", file="src/x.py", line_start=10, line_end=10)
        b = Finding(
            category="project_rule", severity="low",
            file="src/x.py", line_start=10, line_end=10,
            rule_id="rule-a", title="t", description="d", evidence="e",
        )
        assert _findings_match(a, b) is False

    def test_unrelated_bugs_same_file_same_line_dont_match(self):
        a = _make_finding(
            file="src/x.py", line_start=20, line_end=22,
            title="Off-by-one in loop bound",
            evidence="for i in range(n):",
        )
        b = _make_finding(
            file="src/x.py", line_start=21, line_end=21,
            title="Hardcoded timeout value",
            evidence="timeout=30",
        )
        assert _findings_match(a, b) is False


class TestResolveModelsArg:
    def test_default_keyword_expands_to_basket(self):
        result = resolve_models_arg("default")
        assert tuple(result) == DEFAULT_BASKET

    def test_default_keyword_case_insensitive(self):
        assert resolve_models_arg("DEFAULT") == list(DEFAULT_BASKET)
        assert resolve_models_arg("Default") == list(DEFAULT_BASKET)

    def test_explicit_list_parsed(self):
        result = resolve_models_arg("openrouter:a/b,openrouter:c/d")
        assert result == ["openrouter:a/b", "openrouter:c/d"]

    def test_whitespace_around_commas_stripped(self):
        assert resolve_models_arg(" a , b ,c ") == ["a", "b", "c"]

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            resolve_models_arg("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            resolve_models_arg("   ")

    def test_trailing_comma_raises(self):
        with pytest.raises(ValueError):
            resolve_models_arg("a,b,")

    def test_default_mixed_with_explicit_raises(self):
        with pytest.raises(ValueError, match="cannot be mixed"):
            resolve_models_arg("default,openrouter:x/y")


def _result_from_corpus_pair(model: str, finding_dict: dict) -> PerModelResult:
    """Helper: build a PerModelResult around one finding."""
    f = Finding(**finding_dict)
    return PerModelResult(
        model=model,
        report=_make_report([f], model=model),
        tokens_input=10, tokens_output=5,
        error_message=None,
    )


class TestMergeReports:
    def test_three_models_full_agreement_merges_to_one_finding(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["convergent_3of3"]]
        merged, uncorroborated = merge_reports(results, consensus_threshold=2)
        assert len(merged.findings) == 1
        kept = merged.findings[0]
        assert kept.agreement_count == 3
        assert sorted(kept.agreed_by) == ["model-a", "model-b", "model-c"]
        assert kept.severity == "blocker"
        assert kept.category == "bug"
        assert "[model-a]:" in kept.description
        assert "[model-b]:" in kept.description
        assert "[model-c]:" in kept.description
        assert uncorroborated == []

    def test_two_of_three_clears_threshold_two(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["convergent_2of3"]]
        results.append(PerModelResult(
            model="model-c",
            report=_make_report([], model="model-c"),
            tokens_input=10, tokens_output=5, error_message=None,
        ))
        merged, uncorroborated = merge_reports(results, consensus_threshold=2)
        assert len(merged.findings) == 1
        assert merged.findings[0].agreement_count == 2

    def test_singleton_dropped_at_threshold_two(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["singleton_should_drop_at_threshold_2"]]
        for m in ("model-b", "model-c"):
            results.append(PerModelResult(
                model=m,
                report=_make_report([], model=m),
                tokens_input=10, tokens_output=5, error_message=None,
            ))
        merged, uncorroborated = merge_reports(results, consensus_threshold=2)
        assert merged.findings == []
        assert len(uncorroborated) == 1
        assert uncorroborated[0].title == "Variable name shadows builtin"

    def test_threshold_one_keeps_singletons(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["singleton_should_drop_at_threshold_2"]]
        merged, uncorroborated = merge_reports(results, consensus_threshold=1)
        assert len(merged.findings) == 1
        assert uncorroborated == []

    def test_threshold_three_drops_two_of_three(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["convergent_2of3"]]
        results.append(PerModelResult(
            model="model-c",
            report=_make_report([], model="model-c"),
            tokens_input=10, tokens_output=5, error_message=None,
        ))
        merged, uncorroborated = merge_reports(results, consensus_threshold=3)
        assert merged.findings == []
        assert len(uncorroborated) == 1

    def test_project_rule_cross_line_merge(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["project_rule_cross_line_match"]]
        merged, _ = merge_reports(results, consensus_threshold=2)
        assert len(merged.findings) == 1
        assert merged.findings[0].rule_id == "no-bare-fences"
        assert merged.findings[0].agreement_count == 2

    def test_different_bugs_same_file_stay_separate(self):
        corpus = _load_corpus()
        results = [_result_from_corpus_pair(item["model"], item["finding"]) for item in corpus["different_bugs_same_file_dont_merge"]]
        merged, uncorroborated = merge_reports(results, consensus_threshold=1)
        assert len(merged.findings) == 2

    def test_partial_failure_one_of_three_errored(self):
        results = [
            _result_from_corpus_pair("model-a", _load_corpus()["convergent_2of3"][0]["finding"]),
            _result_from_corpus_pair("model-b", _load_corpus()["convergent_2of3"][1]["finding"]),
            PerModelResult(
                model="model-c",
                report=None, tokens_input=0, tokens_output=0,
                error_message="TimeoutError: dispatch exceeded 1800s",
            ),
        ]
        merged, _ = merge_reports(results, consensus_threshold=2)
        assert merged.findings[0].agreement_count == 2
        assert merged.metadata.per_model_usage["model-c"].errored is True
        assert "TimeoutError" in merged.metadata.per_model_usage["model-c"].error_message
        assert merged.metadata.models == ["model-a", "model-b", "model-c"]

    def test_zero_of_three_succeeded_raises(self):
        results = [
            PerModelResult(model=m, report=None, tokens_input=0, tokens_output=0, error_message="err")
            for m in ("a", "b", "c")
        ]
        with pytest.raises(RuntimeError, match="all .* failed"):
            merge_reports(results, consensus_threshold=2)

    def test_description_truncated_at_cap(self):
        long_desc = "x" * 800
        results = []
        for m in ("a", "b", "c"):
            f = _make_finding(
                file="src/x.py", line_start=1, line_end=1,
                title="Same title same title same title",
                description=long_desc,
                evidence="evidence text",
            )
            results.append(PerModelResult(
                model=m, report=_make_report([f], model=m),
                tokens_input=10, tokens_output=5, error_message=None,
            ))
        merged, _ = merge_reports(results, consensus_threshold=2)
        assert len(merged.findings[0].description) <= 1500
        assert "(truncated)" in merged.findings[0].description

    def test_token_totals_summed_across_models(self):
        results = [
            PerModelResult(
                model=f"m{i}", report=_make_report([], model=f"m{i}"),
                tokens_input=100, tokens_output=50, error_message=None,
            )
            for i in range(3)
        ]
        merged, _ = merge_reports(results, consensus_threshold=1)
        assert merged.metadata.tokens_input == 300
        assert merged.metadata.tokens_output == 150
        assert merged.metadata.model == "m0,m1,m2"
