"""G6/G7/G8 CLI smoke tests for v0.5.1 tool-use precheck."""
from __future__ import annotations

from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_reviewer import cli
from pr_reviewer.compat import ProbeItem, ProbeResult
from pr_reviewer.schema import Report
from tests.conftest import make_run_metadata


ProbeOutcome = Literal["OK", "NO_TOOL_SUPPORT", "AUTH_FAIL", "OTHER"]


def _make_reviewer_report() -> Report:
    return Report(
        metadata=make_run_metadata(),
        rules_loaded=[],
        findings=[],
    )


def _install_diff_fakes(monkeypatch, tmp_path):
    """Replace git-touching functions with canned versions."""
    diff_text = "diff --git a/src/foo.py b/src/foo.py\n+    pass\n"
    monkeypatch.setattr("pr_reviewer.cli.resolve_base_ref", lambda repo, explicit=None: "main")
    monkeypatch.setattr("pr_reviewer.cli.extract_diff", lambda repo, base: diff_text)
    monkeypatch.setattr("pr_reviewer.cli.filter_diff", lambda diff, spec: (diff, []))
    monkeypatch.setattr("pr_reviewer.cli.head_sha", lambda repo: "abc1234567890")
    monkeypatch.setattr("pr_reviewer.cli.merge_base", lambda repo, base: "def4567890123")
    monkeypatch.setattr("pr_reviewer.cli.current_branch", lambda repo: "feature/x")
    monkeypatch.chdir(tmp_path)


def _install_dual_purpose_fakes(
    monkeypatch,
    probe_outcome: ProbeOutcome = "OK",
    reviewer_called_ref: list | None = None,
):
    """Replace build_agent with a fake that handles BOTH the precheck probe call
    (output_type=ProbeResult) AND the reviewer call (output_type=Report)
    deterministically per the given probe_outcome.

    probe_outcome: "OK" | "NO_TOOL_SUPPORT" | "AUTH_FAIL" | "OTHER"

    reviewer_called_ref: if provided (an empty list), it gets appended to on every
                        reviewer call so the test can assert whether the reviewer
                        was invoked.
    """
    def _fake_build_agent(model, *, output_type, system_prompt):
        fake = MagicMock()

        if output_type is ProbeResult:
            async def _probe_run(prompt):
                if probe_outcome == "NO_TOOL_SUPPORT":
                    raise RuntimeError(
                        'Status 404: {"error":{"message":"No endpoints found that support tool use."}}'
                    )
                if probe_outcome == "AUTH_FAIL":
                    raise RuntimeError("401 Unauthorized: invalid API key")
                if probe_outcome == "OTHER":
                    raise TimeoutError("connection timed out")
                # OK
                result = MagicMock()
                result.output = ProbeResult(items=[ProbeItem(id=1)])
                return result
            fake.run = AsyncMock(side_effect=_probe_run)
        else:
            # Reviewer or verifier call
            async def _reviewer_run(prompt):
                if reviewer_called_ref is not None:
                    reviewer_called_ref.append(model)
                result = MagicMock()
                result.output = _make_reviewer_report()
                usage_mock = MagicMock()
                usage_mock.input_tokens = 100
                usage_mock.output_tokens = 50
                result.usage = MagicMock(return_value=usage_mock)
                return result
            fake.run = AsyncMock(side_effect=_reviewer_run)
        return fake

    monkeypatch.setattr("pr_reviewer.cli.build_agent", _fake_build_agent)
    monkeypatch.setattr("pr_reviewer.compat.build_agent", _fake_build_agent)


def test_single_model_bad_model_exits_2_before_reviewer(monkeypatch, tmp_path, capsys):
    """G6/G8: A denylisted single model exits 2 BEFORE the reviewer is invoked."""
    reviewer_calls: list = []
    _install_dual_purpose_fakes(monkeypatch, probe_outcome="OK", reviewer_called_ref=reviewer_calls)
    _install_diff_fakes(monkeypatch, tmp_path)

    exit_code = cli.main([
        "review",
        "--model", "openrouter:meta-llama/llama-4-maverick",
        "--out", str(tmp_path / "out"),
        "--budget", "100000",
    ])
    assert exit_code == 2
    assert reviewer_calls == []  # reviewer never invoked
    err = capsys.readouterr().err
    assert "[precheck]" in err
    assert "DENIED" in err
    assert "openrouter:meta-llama/llama-4-maverick" in err


def test_bad_verifier_model_exits_2_even_when_reviewer_is_good(monkeypatch, tmp_path, capsys):
    """G8: --verifier of a denylisted model exits 2; reviewer is never invoked
    even though it would have been compatible."""
    reviewer_calls: list = []
    _install_dual_purpose_fakes(monkeypatch, probe_outcome="OK", reviewer_called_ref=reviewer_calls)
    _install_diff_fakes(monkeypatch, tmp_path)

    exit_code = cli.main([
        "review",
        "--model", "openrouter:google/gemini-2.5-pro",
        "--verifier", "openrouter:meta-llama/llama-4-maverick",
        "--out", str(tmp_path / "out"),
        "--budget", "100000",
    ])
    assert exit_code == 2
    assert reviewer_calls == []
    err = capsys.readouterr().err
    assert "DENIED" in err
    assert "openrouter:meta-llama/llama-4-maverick" in err


def test_skip_precheck_bypasses_and_invokes_reviewer(monkeypatch, tmp_path, capsys):
    """G6: --skip-precheck means the bad model goes through anyway; reviewer is
    invoked (it will fail in the real world but for the test the fake succeeds)."""
    reviewer_calls: list = []
    _install_dual_purpose_fakes(monkeypatch, probe_outcome="OK", reviewer_called_ref=reviewer_calls)
    _install_diff_fakes(monkeypatch, tmp_path)

    exit_code = cli.main([
        "review",
        "--model", "openrouter:meta-llama/llama-4-maverick",
        "--skip-precheck",
        "--out", str(tmp_path / "out"),
        "--budget", "100000",
    ])
    # Reviewer was invoked (fake succeeds → exit 0 for no-findings)
    assert reviewer_calls == ["openrouter:meta-llama/llama-4-maverick"]
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "[precheck]" not in err  # no precheck stderr at all


def test_precheck_ok_dispatches_reviewer(monkeypatch, tmp_path, capsys):
    """Happy path: probe returns OK and the reviewer is invoked normally; the
    [precheck] OK line appears on stderr; exit 0 since the canned reviewer
    report has zero findings."""
    reviewer_calls: list = []
    _install_dual_purpose_fakes(monkeypatch, probe_outcome="OK", reviewer_called_ref=reviewer_calls)
    _install_diff_fakes(monkeypatch, tmp_path)

    exit_code = cli.main([
        "review",
        "--model", "openrouter:google/gemini-2.5-pro",
        "--out", str(tmp_path / "out"),
        "--budget", "100000",
    ])
    assert exit_code == 0
    assert reviewer_calls == ["openrouter:google/gemini-2.5-pro"]
    err = capsys.readouterr().err
    assert "[precheck]" in err
    assert "OK" in err
    assert "DENIED" not in err


def test_other_outcome_warns_and_continues(monkeypatch, tmp_path, capsys):
    """G7: OTHER probe outcome (network blip) -> stderr warning + review proceeds."""
    reviewer_calls: list = []
    _install_dual_purpose_fakes(
        monkeypatch, probe_outcome="OTHER", reviewer_called_ref=reviewer_calls,
    )
    _install_diff_fakes(monkeypatch, tmp_path)

    exit_code = cli.main([
        "review",
        "--model", "openrouter:google/gemini-2.5-pro",
        "--out", str(tmp_path / "out"),
        "--budget", "100000",
    ])
    # Reviewer invoked despite precheck failing OTHER
    assert reviewer_calls == ["openrouter:google/gemini-2.5-pro"]
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "[precheck]" in err
    assert "warning" in err.lower()
