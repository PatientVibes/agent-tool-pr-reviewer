"""Tests for the v0.4.0 schema bump: ModelUsage submodel + optional multi-model fields."""
from datetime import datetime, timezone

import pytest

from pr_reviewer.schema import Finding, ModelUsage, Report, RunMetadata


def _make_metadata(**overrides) -> RunMetadata:
    base = dict(
        branch="feature/x",
        base_ref="master",
        commit_head="a" * 40,
        commit_base="b" * 40,
        started_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        duration_seconds=1.5,
        model="openrouter:google/gemini-2.5-pro",
        tokens_input=100,
        tokens_output=50,
    )
    base.update(overrides)
    return RunMetadata(**base)


class TestSchemaVersionBump:
    def test_default_schema_version_is_3(self):
        md = _make_metadata()
        assert md.schema_version == "3"

    def test_v2_string_rejected_for_schema_version(self):
        # Literal["3"] enforces; v2 inputs must fail validation
        with pytest.raises(Exception):
            _make_metadata(schema_version="2")


class TestModelUsage:
    def test_minimal_construction(self):
        u = ModelUsage(tokens_input=10, tokens_output=20)
        assert u.errored is False
        assert u.error_message is None

    def test_errored_with_message(self):
        u = ModelUsage(
            tokens_input=0, tokens_output=0,
            errored=True, error_message="timeout after 1800s",
        )
        assert u.errored is True
        assert u.error_message == "timeout after 1800s"


class TestFindingAgreementFields:
    def test_single_model_finding_has_null_agreement(self):
        f = Finding(
            category="bug", severity="medium",
            file="src/x.py", line_start=1, line_end=1,
            title="x", description="y", evidence="z",
        )
        assert f.agreement_count is None
        assert f.agreed_by is None

    def test_multi_model_finding_records_agreement(self):
        f = Finding(
            category="bug", severity="medium",
            file="src/x.py", line_start=1, line_end=1,
            title="x", description="y", evidence="z",
            agreement_count=2,
            agreed_by=["openrouter:google/gemini-2.5-pro", "openrouter:moonshotai/kimi-k2.6"],
        )
        assert f.agreement_count == 2
        assert len(f.agreed_by) == 2


class TestRunMetadataMultiModel:
    def test_single_model_metadata_has_null_per_model_fields(self):
        md = _make_metadata()
        assert md.models is None
        assert md.per_model_usage is None

    def test_multi_model_metadata_populated(self):
        md = _make_metadata(
            model="a,b,c",
            tokens_input=300, tokens_output=150,
            models=["a", "b", "c"],
            per_model_usage={
                "a": ModelUsage(tokens_input=100, tokens_output=50),
                "b": ModelUsage(tokens_input=100, tokens_output=50),
                "c": ModelUsage(tokens_input=100, tokens_output=50, errored=False),
            },
        )
        assert md.models == ["a", "b", "c"]
        assert md.per_model_usage["c"].errored is False


class TestReportRoundtrip:
    def test_v3_report_dump_and_load_single_model(self):
        # G6: single-model Report roundtrip — new fields are null and survive
        report = Report(
            metadata=_make_metadata(),
            rules_loaded=["rule-a"],
            findings=[Finding(
                category="bug", severity="low",
                file="src/x.py", line_start=1, line_end=1,
                title="t", description="d", evidence="e",
            )],
        )
        roundtripped = Report.model_validate_json(report.model_dump_json())
        assert roundtripped.metadata.schema_version == "3"
        assert roundtripped.metadata.models is None
        assert roundtripped.metadata.per_model_usage is None
        assert all(f.agreement_count is None for f in roundtripped.findings)
        assert all(f.agreed_by is None for f in roundtripped.findings)
