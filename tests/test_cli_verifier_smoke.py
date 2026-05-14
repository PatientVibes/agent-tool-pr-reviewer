"""G5/G7/G8 smoke tests — single-model + verifier path with monkeypatched build_agent."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_reviewer import cli
from pr_reviewer.schema import Finding, Report
from pr_reviewer.verifier import VerdictBatch, VerdictItem
from tests.conftest import make_run_metadata


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "verifier_findings.json"


@pytest.fixture
def canned():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _make_reviewer_report(canned) -> Report:
    findings = [Finding.model_validate(f) for f in canned["canned_reviewer_findings"]]
    return Report(
        metadata=make_run_metadata(),
        rules_loaded=[],
        findings=findings,
    )


def _make_verifier_batch_dropping_self_withdrawal() -> VerdictBatch:
    """The judge sees 2 bug survivors after the deterministic gate:
      [0] AttributeError on None (self-withdrawing)
      [1] Clean finding (magic number 42)
    Drops [0] via SELF_WITHDRAWAL; keeps [1] with no_condition_fired."""
    return VerdictBatch(verdicts=[
        VerdictItem(
            finding_index=0,
            keep=False,
            reason="SELF_WITHDRAWAL: description ends with 'on reflection this is fine'",
        ),
        VerdictItem(
            finding_index=1,
            keep=True,
            reason="no_condition_fired",
        ),
    ])


def _install_fakes(monkeypatch, canned, verifier_batch):
    """Replace build_agent so reviewer calls return the canned Report and
    verifier calls return the supplied VerdictBatch (or raise an exception
    if `verifier_batch` is an Exception instance)."""
    reviewer_report = _make_reviewer_report(canned)

    async def _run_reviewer(prompt):
        result = MagicMock()
        result.output = reviewer_report
        usage_mock = MagicMock()
        usage_mock.input_tokens = 100
        usage_mock.output_tokens = 50
        result.usage = MagicMock(return_value=usage_mock)
        return result

    async def _run_verifier(prompt):
        if isinstance(verifier_batch, Exception):
            raise verifier_batch
        result = MagicMock()
        result.output = verifier_batch
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
    """Replace git-touching functions with canned versions."""
    diff_text = canned["diff_text"]
    monkeypatch.setattr("pr_reviewer.cli.resolve_base_ref", lambda repo, explicit=None: "main")
    monkeypatch.setattr("pr_reviewer.cli.extract_diff", lambda repo, base: diff_text)
    monkeypatch.setattr("pr_reviewer.cli.filter_diff", lambda diff, spec: (diff, []))
    monkeypatch.setattr("pr_reviewer.cli.head_sha", lambda repo: "abc1234567890")
    monkeypatch.setattr("pr_reviewer.cli.merge_base", lambda repo, base: "def4567890123")
    monkeypatch.setattr("pr_reviewer.cli.current_branch", lambda repo: "feature/x")
    monkeypatch.chdir(tmp_path)


def test_single_model_verifier_drops_self_withdrawal_and_deterministic_fails(
    monkeypatch, tmp_path, canned, capsys,
):
    """G5 + G8: single-model + --verifier. Reviewer emits 4 findings; deterministic
    gate drops 2 (paraphrased evidence, file not in diff); judge drops the
    self-withdrawing AttributeError finding; the clean 'Magic number 42' finding
    survives."""
    _install_fakes(monkeypatch, canned, _make_verifier_batch_dropping_self_withdrawal())
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    out_dir = tmp_path / "out"
    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--model", "fake-reviewer",
        "--verifier", "fake-verifier",
        "--out", str(out_dir),
        "--budget", "100000",
    ])

    assert exit_code == 0
    findings_data = json.loads((out_dir / "findings.json").read_text())
    titles = [f["title"] for f in findings_data["findings"]]
    assert titles == ["Clean finding"]
    assert findings_data["metadata"]["verifier_model"] == "fake-verifier"

    dropped_path = out_dir / "dropped-by-verifier.json"
    assert dropped_path.exists()
    dropped_data = json.loads(dropped_path.read_text())
    assert len(dropped_data) == 3
    stage_by_title = {d["finding"]["title"]: d["drop_stage"] for d in dropped_data}
    assert stage_by_title["AttributeError on None"] == "judge"
    assert stage_by_title["Paraphrased evidence"] == "deterministic"
    assert stage_by_title["File not in diff"] == "deterministic"

    err = capsys.readouterr().err
    assert "[verifier] starting fake-verifier" in err
    assert "[verifier] deterministic gate:" in err
    assert "[verifier] judge complete:" in err
    assert "[verifier] judge:" in err


def test_single_model_no_verifier_unchanged_output(monkeypatch, tmp_path, canned, capsys):
    """G6: invocation without --verifier produces no sidecar; verifier_model=None;
    no [verifier] stderr lines. AttributeError blocker survives -> exit 1."""
    _install_fakes(monkeypatch, canned, None)
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    out_dir = tmp_path / "out"
    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--model", "fake-reviewer",
        "--out", str(out_dir),
        "--budget", "100000",
    ])
    assert exit_code == 1
    findings_data = json.loads((out_dir / "findings.json").read_text())
    assert findings_data["metadata"]["verifier_model"] is None
    assert len(findings_data["findings"]) == 4
    assert not (out_dir / "dropped-by-verifier.json").exists()

    err = capsys.readouterr().err
    assert "[verifier]" not in err


def test_verifier_fails_open_on_exception(monkeypatch, tmp_path, canned, capsys):
    """G7(b): Agent.run raises -> all stage-3a survivors kept; verifier_model set;
    exit 1 because the AttributeError blocker survives."""
    _install_fakes(monkeypatch, canned, RuntimeError("boom"))
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    out_dir = tmp_path / "out"
    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--model", "fake-reviewer",
        "--verifier", "fake-verifier",
        "--out", str(out_dir),
        "--budget", "100000",
    ])

    findings_data = json.loads((out_dir / "findings.json").read_text())
    assert findings_data["metadata"]["verifier_model"] == "fake-verifier"
    # 2 stage-3a survivors kept (AttributeError + Clean); paraphrased + file-not-in-diff dropped deterministically.
    assert len(findings_data["findings"]) == 2
    err = capsys.readouterr().err
    assert "[verifier] errored:" in err
    assert "RuntimeError" in err
    assert exit_code == 1


def test_verifier_fails_open_on_malformed_batch(monkeypatch, tmp_path, canned, capsys):
    """G7(c): malformed VerdictBatch (count mismatch) -> fail open. 2 bug
    survivors expected; batch has 0 verdicts."""
    bad_batch = VerdictBatch(verdicts=[])
    _install_fakes(monkeypatch, canned, bad_batch)
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    out_dir = tmp_path / "out"
    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--model", "fake-reviewer",
        "--verifier", "fake-verifier",
        "--out", str(out_dir),
        "--budget", "100000",
    ])

    findings_data = json.loads((out_dir / "findings.json").read_text())
    assert findings_data["metadata"]["verifier_model"] == "fake-verifier"
    assert len(findings_data["findings"]) == 2
    err = capsys.readouterr().err
    assert "malformed VerdictBatch" in err
    assert exit_code == 1


def test_verifier_arg_resolution_failure_exit_2_before_review(monkeypatch, tmp_path, canned, capsys):
    """G7(a): bad --verifier value -> exit 2 BEFORE running reviewer. '   '
    triggers ValueError in resolve_verifier_arg."""
    _install_fakes(monkeypatch, canned, None)
    _install_diff_fakes(monkeypatch, canned, tmp_path)

    exit_code = cli.main([
        "review",
        "--skip-precheck",
        "--model", "fake-reviewer",
        "--verifier", "   ",
        "--out", str(tmp_path / "out"),
    ])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error: --verifier:" in err
