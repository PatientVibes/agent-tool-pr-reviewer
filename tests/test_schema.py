import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pr_reviewer.schema import Finding, Report, RunMetadata


class TestFinding:
    def test_bug_without_rule_id_is_valid(self):
        f = Finding(
            category="bug",
            severity="high",
            file="src/x.py",
            line_start=10,
            line_end=12,
            title="off-by-one in loop bound",
            description="loop runs N+1 times because <=",
            evidence="+    return x.foo",
        )
        assert f.rule_id is None

    def test_bug_with_rule_id_raises(self):
        with pytest.raises(ValidationError, match="must not have rule_id"):
            Finding(
                category="bug",
                severity="high",
                file="src/x.py",
                line_start=1,
                line_end=1,
                rule_id="some-rule",
                title="t",
                description="d",
                evidence="+    return x.foo",
            )

    def test_project_rule_with_rule_id_is_valid(self):
        f = Finding(
            category="project_rule",
            severity="medium",
            file="src/components/X.tsx",
            line_start=1,
            line_end=20,
            rule_id="no-class-components",
            title="class component used",
            description="convert to functional",
            evidence="+class X extends Component {",
        )
        assert f.rule_id == "no-class-components"

    def test_project_rule_without_rule_id_raises(self):
        with pytest.raises(ValidationError, match="require rule_id"):
            Finding(
                category="project_rule",
                severity="medium",
                file="x",
                line_start=1,
                line_end=1,
                title="t",
                description="d",
                evidence="+class X extends Component {",
            )

    def test_line_end_before_line_start_raises(self):
        with pytest.raises(ValidationError, match="line_end must be >= line_start"):
            Finding(
                category="bug",
                severity="low",
                file="x.py",
                line_start=10,
                line_end=5,
                title="t",
                description="d",
                evidence="+stub",
            )

    def test_evidence_empty_raises(self):
        with pytest.raises(ValidationError):
            Finding(
                category="bug",
                severity="low",
                file="x.py",
                line_start=1,
                line_end=1,
                title="t",
                description="d",
                evidence="",
            )

    def test_evidence_too_long_raises(self):
        with pytest.raises(ValidationError):
            Finding(
                category="bug",
                severity="low",
                file="x.py",
                line_start=1,
                line_end=1,
                title="t",
                description="d",
                evidence="x" * 501,
            )

    def test_evidence_at_min_length_accepted(self):
        f = Finding(
            category="bug", severity="low", file="x.py",
            line_start=1, line_end=1, title="t", description="d",
            evidence="+",
        )
        assert f.evidence == "+"

    def test_evidence_at_max_length_accepted(self):
        f = Finding(
            category="bug", severity="low", file="x.py",
            line_start=1, line_end=1, title="t", description="d",
            evidence="x" * 500,
        )
        assert len(f.evidence) == 500


class TestReport:
    def test_round_trip_through_json(self):
        report = Report(
            metadata=RunMetadata(
                branch="feature/x",
                base_ref="main",
                commit_head="a" * 40,
                commit_base="b" * 40,
                started_at=datetime(2026, 5, 7, 14, 32, 19, tzinfo=timezone.utc),
                duration_seconds=3.21,
                model="anthropic:claude-sonnet-4-6",
                tokens_input=1234,
                tokens_output=567,
            ),
            rules_loaded=["no-class-components", "prefer-pure-functions"],
            findings=[
                Finding(
                    category="bug",
                    severity="blocker",
                    file="src/x.py",
                    line_start=42,
                    line_end=42,
                    title="null deref",
                    description="x may be None here",
                    evidence="+    return x.foo  # could be None",
                ),
            ],
        )
        payload = report.model_dump_json()
        round_trip = Report.model_validate_json(payload)
        assert round_trip == report
