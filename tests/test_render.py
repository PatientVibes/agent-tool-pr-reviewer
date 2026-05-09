from datetime import datetime, timezone
from pathlib import Path

from pr_reviewer.render import render_markdown
from pr_reviewer.schema import Finding, Report, RunMetadata


GOLDEN_DIR = Path(__file__).parent / "golden"


def _metadata(duration: float = 1.5, tin: int = 100, tout: int = 20) -> RunMetadata:
    return RunMetadata(
        branch="feature/x",
        base_ref="main",
        commit_head="a" * 40,
        commit_base="b" * 40,
        started_at=datetime(2026, 5, 7, 14, 32, 19, tzinfo=timezone.utc),
        duration_seconds=duration,
        model="anthropic:claude-sonnet-4-6",
        tokens_input=tin,
        tokens_output=tout,
    )


def test_renders_empty_report_matches_golden():
    report = Report(metadata=_metadata(), rules_loaded=[], findings=[])
    expected = (GOLDEN_DIR / "empty_report.md").read_text(encoding="utf-8")
    assert render_markdown(report) == expected


def test_renders_sample_report_matches_golden():
    report = Report(
        metadata=_metadata(duration=3.21, tin=1234, tout=567),
        rules_loaded=["no-class-components", "prefer-pure-functions"],
        findings=[
            Finding(
                category="bug", severity="blocker",
                file="src/x.py", line_start=42, line_end=42,
                title="null deref", description="x may be None here.",
                evidence="+    return user_data.name",
            ),
            Finding(
                category="project_rule", severity="high",
                file="src/components/X.tsx", line_start=1, line_end=20,
                rule_id="no-class-components",
                title="class component used",
                description="Convert to functional.",
                suggested_fix="use hooks",
                evidence="+class UserProfile extends React.Component {\n+  render() {\n+    return <div>...</div>;\n+  }\n+}",
            ),
        ],
    )
    expected = (GOLDEN_DIR / "sample_report.md").read_text(encoding="utf-8")
    assert render_markdown(report) == expected
