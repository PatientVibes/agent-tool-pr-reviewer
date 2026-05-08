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
            )


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
                ),
            ],
        )
        payload = report.model_dump_json()
        round_trip = Report.model_validate_json(payload)
        assert round_trip == report
