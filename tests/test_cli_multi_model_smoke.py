"""End-to-end smoke for the v0.4.0 --models multi-model dispatch path.

Monkeypatches build_agent so no LLM is called; canned Reports flow through the
real CLI machinery (argparse, asyncio.gather, consensus.merge_reports, render,
write).
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_reviewer import cli
from pr_reviewer.schema import Finding, Report, RunMetadata


def _make_report(model: str, findings: list[Finding]) -> Report:
    return Report(
        metadata=RunMetadata(
            branch="b", base_ref="master",
            commit_head="a" * 40, commit_base="b" * 40,
            started_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
            duration_seconds=1.0,
            model=model, tokens_input=100, tokens_output=50,
        ),
        rules_loaded=[],
        findings=findings,
    )


def _git_init_fixture_repo(repo: Path, extra_files: dict[str, str] | None = None):
    """Initialise a minimal git repo with one commit on master and one on a feature branch."""
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "master"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello world\n", encoding="utf-8")
    if extra_files:
        for rel, content in extra_files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=repo, check=True)


def _make_canned_agent(report: Report):
    """Return a MagicMock-Agent whose .run(prompt) is an AsyncMock yielding `report`."""
    agent = MagicMock()
    result_obj = MagicMock()
    result_obj.output = report
    usage_obj = MagicMock()
    usage_obj.input_tokens = report.metadata.tokens_input
    usage_obj.output_tokens = report.metadata.tokens_output
    result_obj.usage = lambda: usage_obj
    agent.run = AsyncMock(return_value=result_obj)
    return agent


def _build_canned_agents_dispatch(per_model: dict[str, list[Finding]]):
    """Returns a fake build_agent function that yields the right canned report per model string."""
    def fake_build_agent(model_spec, *, output_type=None, system_prompt=None):
        """Test fake — accepts the new kwargs but ignores them; reviewer-only context."""
        report = _make_report(model_spec, per_model.get(model_spec, []))
        return _make_canned_agent(report)
    return fake_build_agent


@pytest.fixture
def fixture_repo(tmp_path, monkeypatch):
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    rules_dir = repo / ".ai-review"
    rules_dir.mkdir()
    (rules_dir / "demo-rule.md").write_text(
        "---\ndescription: demo\n---\n# demo-rule\n",
        encoding="utf-8",
    )
    _git_init_fixture_repo(repo)
    monkeypatch.chdir(repo)
    return repo


def test_multi_model_smoke_consensus_2of3(fixture_repo, monkeypatch, capsys):
    # Three models, two flag the same finding (consensus reached)
    convergent = Finding(
        category="bug", severity="high",
        file="README.md", line_start=1, line_end=1,
        title="Missing punctuation", description="period missing",
        evidence="hello world",
    )
    # Use a non-overlapping evidence string AND a title whose 3-gram Jaccard
    # vs the convergent finding's title is below 0.3 so the singleton stays
    # isolated. (evidence "xyz" cannot substring-match "hello world".)
    singleton = Finding(
        category="bug", severity="low",
        file="README.md", line_start=1, line_end=1,
        title="Unrelated styling nitpick",
        description="totally different bug",
        evidence="xyz",
    )
    per_model_findings = {
        "fake-a": [convergent],
        "fake-b": [Finding(**{**convergent.model_dump(), "title": "Need terminating dot"})],
        "fake-c": [singleton],
    }
    monkeypatch.setattr(
        "pr_reviewer.cli.build_agent",
        _build_canned_agents_dispatch(per_model_findings),
    )

    out_dir = fixture_repo / "out"
    exit_code = cli.main([
        "review",
        "--models", "fake-a,fake-b,fake-c",
        "--out", str(out_dir),
    ])
    assert exit_code == 0  # no blocker
    findings_json = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
    # G5(a): agreement annotation present on converged finding
    assert len(findings_json["findings"]) == 1
    f = findings_json["findings"][0]
    assert f["agreement_count"] == 2
    assert sorted(f["agreed_by"]) == ["fake-a", "fake-b"]
    # G5(b): stderr summary table line present
    err = capsys.readouterr().err
    assert "Multi-model consensus" in err
    assert "fake-a" in err and "fake-b" in err and "fake-c" in err
    # G5(c): uncorroborated.json absent without flag
    assert not (out_dir / "uncorroborated.json").exists()


def test_multi_model_smoke_include_uncorroborated_writes_file(fixture_repo, monkeypatch, capsys):
    singleton = Finding(
        category="bug", severity="low",
        file="README.md", line_start=1, line_end=1,
        title="One-off observation",
        description="only one model saw this",
        evidence="hello world",
    )
    monkeypatch.setattr(
        "pr_reviewer.cli.build_agent",
        _build_canned_agents_dispatch({"fake-a": [singleton], "fake-b": [], "fake-c": []}),
    )
    out_dir = fixture_repo / "out2"
    exit_code = cli.main([
        "review",
        "--models", "fake-a,fake-b,fake-c",
        "--include-uncorroborated",
        "--out", str(out_dir),
    ])
    assert exit_code == 0
    # G5(c, positive case): uncorroborated.json written with the singleton
    assert (out_dir / "uncorroborated.json").exists()
    unc = json.loads((out_dir / "uncorroborated.json").read_text(encoding="utf-8"))
    assert len(unc) == 1
    assert unc[0]["title"] == "One-off observation"


def test_multi_model_smoke_scope_filter_runs_once(fixture_repo, monkeypatch, capsys):
    # G5(e): --models + --exclude. The filter should run ONCE before parallel
    # dispatch. Assertion: stderr contains exactly one "Filtered N file(s)" line.
    gen_dir = fixture_repo / "generated"
    gen_dir.mkdir()
    (gen_dir / "out.sql").write_text("SELECT 1;\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=fixture_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add generated"], cwd=fixture_repo, check=True)

    convergent = Finding(
        category="bug", severity="medium",
        file="README.md", line_start=1, line_end=1,
        title="Real bug", description="d", evidence="hello world",
    )
    hallucinated = Finding(
        category="bug", severity="low",
        file="generated/out.sql", line_start=1, line_end=1,
        title="Should be Layer-2 filtered", description="d", evidence="SELECT 1;",
    )
    monkeypatch.setattr(
        "pr_reviewer.cli.build_agent",
        _build_canned_agents_dispatch({
            "fake-a": [convergent, hallucinated],
            "fake-b": [convergent, hallucinated],
            "fake-c": [convergent],
        }),
    )

    out_dir = fixture_repo / "out3"
    exit_code = cli.main([
        "review",
        "--models", "fake-a,fake-b,fake-c",
        "--exclude", "generated/**",
        "--out", str(out_dir),
    ])
    assert exit_code == 0
    err = capsys.readouterr().err
    # Filter runs once, not three times
    filter_lines = [line for line in err.splitlines() if "Filtered" in line and "file(s)" in line]
    assert len(filter_lines) == 1, f"expected exactly one Filtered line, got: {filter_lines}"
    findings_json = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
    assert all(f["file"] != "generated/out.sql" for f in findings_json["findings"])


def test_model_and_models_flags_mutually_exclusive(fixture_repo, capsys):
    exit_code = cli.main([
        "review",
        "--model", "openrouter:foo/bar",
        "--models", "fake-a,fake-b",
    ])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err.lower()
