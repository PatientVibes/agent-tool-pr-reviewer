"""Multi-model + verifier smoke (G5 multi-model portion)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_reviewer import cli
from pr_reviewer.schema import Finding, Report, RunMetadata
from pr_reviewer.verifier import VerdictBatch, VerdictItem


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "verifier_findings.json"


@pytest.fixture
def canned():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _make_metadata(model):
    return RunMetadata(
        branch="feature/x", base_ref="main",
        commit_head="abc123", commit_base="def456",
        started_at=datetime.now(timezone.utc), duration_seconds=0.1,
        model=model, tokens_input=100, tokens_output=50,
    )


def _make_reviewer_report(canned, model):
    findings = [Finding.model_validate(f) for f in canned["canned_reviewer_findings"]]
    return Report(metadata=_make_metadata(model), rules_loaded=[], findings=findings)


def _make_verifier_batch_drops_self_withdrawal():
    """After consensus merge + deterministic gate, 2 bug survivors remain.
    merge_reports orders them: [0]='Clean finding', [1]='AttributeError on None'.
    Drop [1] via SELF_WITHDRAWAL; keep [0] with no_condition_fired."""
    return VerdictBatch(verdicts=[
        VerdictItem(
            finding_index=0, keep=True,
            reason="no_condition_fired",
        ),
        VerdictItem(
            finding_index=1, keep=False,
            reason="SELF_WITHDRAWAL: 'on reflection this is fine'",
        ),
    ])


def _install_multi_model_fakes(monkeypatch, canned):
    """Three reviewer fakes + one verifier fake. Each reviewer returns the
    SAME canned report so consensus merges them into one finding per cluster."""

    async def _run_reviewer(prompt):
        result = MagicMock()
        result.output = _make_reviewer_report(canned, model="fake-rv-shared")
        usage_mock = MagicMock()
        usage_mock.input_tokens = 100
        usage_mock.output_tokens = 50
        result.usage = MagicMock(return_value=usage_mock)
        return result

    async def _run_verifier(prompt):
        result = MagicMock()
        result.output = _make_verifier_batch_drops_self_withdrawal()
        usage_mock = MagicMock()
        usage_mock.input_tokens = 1200
        usage_mock.output_tokens = 400
        result.usage = MagicMock(return_value=usage_mock)
        return result

    def _fake_build_agent(model, *, output_type, system_prompt):
        agent = MagicMock()
        if output_type is VerdictBatch:
            agent.run = AsyncMock(side_effect=_run_verifier)
        else:
            agent.run = AsyncMock(side_effect=_run_reviewer)
        return agent

    monkeypatch.setattr("pr_reviewer.cli.build_agent", _fake_build_agent)
    monkeypatch.setattr("pr_reviewer.agent.build_agent", _fake_build_agent)
    monkeypatch.setattr("pr_reviewer.verifier.build_agent", _fake_build_agent)


def _install_diff_fakes(monkeypatch, canned, tmp_path):
    diff_text = canned["diff_text"]
    monkeypatch.setattr("pr_reviewer.cli.resolve_base_ref", lambda repo, explicit=None: "main")
    monkeypatch.setattr("pr_reviewer.cli.extract_diff", lambda repo, base: diff_text)
    monkeypatch.setattr("pr_reviewer.cli.filter_diff", lambda diff, spec: (diff, []))
    monkeypatch.setattr("pr_reviewer.cli.head_sha", lambda repo: "abc1234567890")
    monkeypatch.setattr("pr_reviewer.cli.merge_base", lambda repo, base: "def4567890123")
    monkeypatch.setattr("pr_reviewer.cli.current_branch", lambda repo: "feature/x")
    monkeypatch.chdir(tmp_path)


def test_multi_model_with_verifier_drops_and_sidecar(monkeypatch, tmp_path, canned, capsys):
    """Verifier runs on the merged-and-filtered consensus output. dropped-by-verifier.json
    is written alongside findings.json."""
    _install_multi_model_fakes(monkeypatch, canned)
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    out_dir = tmp_path / "out"
    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--models", "fake-a,fake-b,fake-c",
        "--consensus", "2",
        "--verifier", "fake-verifier",
        "--out", str(out_dir),
        "--budget", "100000",
    ])
    assert exit_code == 0
    findings_data = json.loads((out_dir / "findings.json").read_text())
    titles = [f["title"] for f in findings_data["findings"]]
    assert titles == ["Clean finding"]
    assert findings_data["metadata"]["verifier_model"] == "fake-verifier"
    assert findings_data["metadata"]["models"] == ["fake-a", "fake-b", "fake-c"]

    sidecar = json.loads((out_dir / "dropped-by-verifier.json").read_text())
    assert len(sidecar) == 3

    err = capsys.readouterr().err
    assert "[verifier]" in err
    assert "Convergence:" in err  # v0.4.0 consensus summary still emits


def test_multi_model_without_verifier_unchanged(monkeypatch, tmp_path, canned, capsys):
    """G6 multi-model variant: no --verifier means no sidecar and verifier_model=None."""
    _install_multi_model_fakes(monkeypatch, canned)
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    out_dir = tmp_path / "out"
    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--models", "fake-a,fake-b,fake-c",
        "--consensus", "2",
        "--out", str(out_dir),
        "--budget", "100000",
    ])
    assert exit_code == 1
    findings_data = json.loads((out_dir / "findings.json").read_text())
    assert findings_data["metadata"]["verifier_model"] is None
    assert not (out_dir / "dropped-by-verifier.json").exists()

    err = capsys.readouterr().err
    assert "[verifier]" not in err
