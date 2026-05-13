"""Tests for the v0.4.0 render annotation for multi-model consensus findings."""
from datetime import datetime, timezone

from pr_reviewer.render import render_markdown
from pr_reviewer.schema import Finding, Report, RunMetadata


def _make_md_report(findings):
    return Report(
        metadata=RunMetadata(
            branch="b", base_ref="master",
            commit_head="a" * 40, commit_base="b" * 40,
            started_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
            duration_seconds=1.0, model="a,b", tokens_input=10, tokens_output=5,
            models=["a", "b"],
        ),
        rules_loaded=[],
        findings=findings,
    )


def test_render_includes_agreement_for_multi_model_finding():
    f = Finding(
        category="bug", severity="high",
        file="src/x.py", line_start=1, line_end=1,
        title="t", description="d", evidence="e",
        agreement_count=2, agreed_by=["a", "b"],
    )
    md = render_markdown(_make_md_report([f]))
    assert "Agreement" in md
    assert "2/2" in md
    assert "a, b" in md or "a,b" in md


def test_render_skips_agreement_for_single_model_finding():
    f = Finding(
        category="bug", severity="high",
        file="src/x.py", line_start=1, line_end=1,
        title="t", description="d", evidence="e",
    )
    md = render_markdown(_make_md_report([f]))
    assert "Agreement" not in md
