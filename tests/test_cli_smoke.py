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
        "evidence": "+stub line",
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


# ---------------------------------------------------------------------------
# G5: end-to-end CLI smoke with mocked LLM call.
#
# Mocks the agent's LLM call (via TestModel.custom_output_args) so we exercise
# the full CLI wiring — diff filter (Layer-1) + finding filter (Layer-2) +
# stderr logging — without network I/O.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_filters_diff_and_drops_findings(
    tmp_git_repo: Path, monkeypatch, capsys, tmp_path
):
    """Layer-1 strips excluded chunks from the diff, Layer-2 drops findings
    that reference excluded paths, and both actions log to stderr."""
    # Branch off main with both a kept file AND an excluded file so the diff
    # contains both chunks. Layer-1 must remove the excluded chunk.
    import subprocess as sp
    sp.run(
        ["git", "checkout", "-b", "feature/x"],
        cwd=tmp_git_repo, check=True, capture_output=True,
    )
    (tmp_git_repo / "src").mkdir(exist_ok=True)
    (tmp_git_repo / "src" / "keep.py").write_text(
        "def hi(): return 1\n", encoding="utf-8",
    )
    (tmp_git_repo / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    (tmp_git_repo / "tests" / "fixtures" / "generated.sql").write_text(
        "SELECT 99;\n", encoding="utf-8",
    )
    sp.run(["git", "add", "."], cwd=tmp_git_repo, check=True, capture_output=True)
    sp.run(
        ["git", "commit", "-m", "feature change"],
        cwd=tmp_git_repo, check=True, capture_output=True,
    )

    # .pr-review-ignore at repo root excludes generated SQL fixtures.
    (tmp_git_repo / ".pr-review-ignore").write_text(
        "tests/fixtures/*.sql\n", encoding="utf-8",
    )

    # The mocked LLM returns one finding for a kept path and one for an
    # excluded path. Layer-2 must drop the excluded one.
    report_dict = _empty_report_dict()
    report_dict["findings"] = [
        {
            "category": "bug", "severity": "high",
            "file": "tests/fixtures/generated.sql",
            "line_start": 1, "line_end": 1,
            "title": "should be dropped",
            "description": "this should be dropped by Layer 2",
            "evidence": "-SELECT 1;",
        },
        {
            "category": "bug", "severity": "low",
            "file": "src/keep.py",
            "line_start": 1, "line_end": 1,
            "title": "should survive",
            "description": "this should survive",
            "evidence": "-def hi(): pass",
        },
    ]

    out_dir = tmp_path / "out"
    monkeypatch.chdir(tmp_git_repo)
    exit_code = await run_review_command(
        base=None, budget=80000, rules_dir=None, out=out_dir,
        model=_stub_test_model(report_dict),
        exclude=[],
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Filtered" in captured.err
    assert "tests/fixtures/generated.sql" in captured.err
    assert (
        "Dropped finding for excluded path: tests/fixtures/generated.sql"
        in captured.err
    )

    findings_path = out_dir / "findings.json"
    assert findings_path.exists()
    findings_data = json.loads(findings_path.read_text(encoding="utf-8"))
    paths_in_output = [f["file"] for f in findings_data["findings"]]
    assert "tests/fixtures/generated.sql" not in paths_in_output
    assert "src/keep.py" in paths_in_output


@pytest.mark.asyncio
async def test_cli_no_exclude_is_noop(
    tmp_git_repo: Path, monkeypatch, capsys, tmp_path
):
    """Without .pr-review-ignore and without --exclude, CLI behaves like v0.2.2:
    no diff filtering, no finding drops, no stderr logging from the filters."""
    import subprocess as sp
    sp.run(
        ["git", "checkout", "-b", "feature/x"],
        cwd=tmp_git_repo, check=True, capture_output=True,
    )
    (tmp_git_repo / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    (tmp_git_repo / "tests" / "fixtures" / "generated.sql").write_text(
        "SELECT 99;\n", encoding="utf-8",
    )
    sp.run(["git", "add", "."], cwd=tmp_git_repo, check=True, capture_output=True)
    sp.run(
        ["git", "commit", "-m", "add fixture"],
        cwd=tmp_git_repo, check=True, capture_output=True,
    )

    report_dict = _empty_report_dict()
    report_dict["findings"] = [
        {
            "category": "bug", "severity": "low",
            "file": "tests/fixtures/generated.sql",
            "line_start": 1, "line_end": 1,
            "title": "should pass through",
            "description": "should now pass through",
            "evidence": "+SELECT 99;",
        },
    ]

    out_dir = tmp_path / "out"
    monkeypatch.chdir(tmp_git_repo)
    exit_code = await run_review_command(
        base=None, budget=80000, rules_dir=None, out=out_dir,
        model=_stub_test_model(report_dict),
        exclude=[],
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Filtered" not in captured.err
    assert "Dropped finding" not in captured.err

    findings_data = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
    paths_in_output = [f["file"] for f in findings_data["findings"]]
    assert "tests/fixtures/generated.sql" in paths_in_output
