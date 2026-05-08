import json
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from pr_reviewer.cli import build_parser, run_review_command, run_rules_list_command


def _stub_test_model(report_dict: dict) -> TestModel:
    return TestModel(custom_output_args=report_dict)


def _empty_report_dict() -> dict:
    return {
        "metadata": {
            "branch": "feature/x", "base_ref": "main",
            "commit_head": "a"*40, "commit_base": "b"*40,
            "started_at": "2026-05-07T14:32:19+00:00",
            "duration_seconds": 0.0,
            "model": "test", "tokens_input": 1, "tokens_output": 1,
        },
        "rules_loaded": ["no-class-components"],
        "findings": [],
    }


@pytest.mark.asyncio
async def test_review_writes_findings_json_and_markdown(
    tmp_git_repo: Path, make_branch_with_change, monkeypatch
):
    rules_dir = tmp_git_repo / ".ai-review"
    rules_dir.mkdir()
    (rules_dir / "no-class-components.md").write_text(
        "---\ndescription: no classes\n---\n\nbody\n", encoding="utf-8",
    )
    make_branch_with_change("feature/x", "x.py", "print('x')\n")

    monkeypatch.chdir(tmp_git_repo)
    exit_code = await run_review_command(
        base=None, budget=80000, rules_dir=None, out=None,
        model=_stub_test_model(_empty_report_dict()),
    )
    assert exit_code == 0

    pointer = (tmp_git_repo / ".ai-review" / "runs" / "latest.txt").read_text(encoding="utf-8").strip()
    run_dir = tmp_git_repo / ".ai-review" / "runs" / pointer
    findings = json.loads((run_dir / "findings.json").read_text(encoding="utf-8"))
    assert findings["findings"] == []
    assert (run_dir / "review-output.md").is_file()


@pytest.mark.asyncio
async def test_review_returns_2_when_budget_exceeded(
    tmp_git_repo: Path, make_branch_with_change, monkeypatch, capsys
):
    make_branch_with_change("feature/x", "x.py", "print('x')\n")
    monkeypatch.chdir(tmp_git_repo)
    exit_code = await run_review_command(
        base=None, budget=1, rules_dir=None, out=None,
        model=_stub_test_model(_empty_report_dict()),
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "budget" in err.lower()


@pytest.mark.asyncio
async def test_review_returns_2_on_malformed_rule(
    tmp_git_repo: Path, make_branch_with_change, monkeypatch, capsys
):
    rules_dir = tmp_git_repo / ".ai-review"
    rules_dir.mkdir()
    (rules_dir / "bad.md").write_text("no frontmatter here", encoding="utf-8")
    make_branch_with_change("feature/x", "x.py", "print('x')\n")

    monkeypatch.chdir(tmp_git_repo)
    exit_code = await run_review_command(
        base=None, budget=80000, rules_dir=None, out=None,
        model=_stub_test_model(_empty_report_dict()),
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "frontmatter" in err.lower()


@pytest.mark.asyncio
async def test_review_returns_1_when_blocker_present(
    tmp_git_repo: Path, make_branch_with_change, monkeypatch
):
    make_branch_with_change("feature/x", "x.py", "print('x')\n")
    monkeypatch.chdir(tmp_git_repo)
    report_dict = _empty_report_dict()
    report_dict["findings"] = [{
        "category": "bug", "severity": "blocker",
        "file": "x.py", "line_start": 1, "line_end": 1,
        "title": "stub", "description": "stub blocker",
    }]
    exit_code = await run_review_command(
        base=None, budget=80000, rules_dir=None, out=None,
        model=_stub_test_model(report_dict),
    )
    assert exit_code == 1


def test_rules_list_prints_discovered_rules(tmp_git_repo: Path, monkeypatch, capsys):
    rules_dir = tmp_git_repo / ".ai-review"
    rules_dir.mkdir()
    (rules_dir / "rule-a.md").write_text(
        "---\ndescription: A description.\n---\n\nbody\n", encoding="utf-8",
    )
    monkeypatch.chdir(tmp_git_repo)
    exit_code = run_rules_list_command()
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "rule-a" in out
    assert "A description." in out


def test_build_parser_supports_review_and_rules_list():
    parser = build_parser()
    args = parser.parse_args(["review"])
    assert args.command == "review"
    args = parser.parse_args(["rules", "list"])
    assert args.command == "rules"
    assert args.rules_command == "list"
