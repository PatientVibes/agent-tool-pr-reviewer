import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def sample_rules_dir(tmp_path: Path) -> Path:
    rules = tmp_path / ".ai-review"
    rules.mkdir()
    (rules / "no-class-components.md").write_text(
        "---\n"
        "description: All React components must be functional. No class components.\n"
        "---\n\n"
        "# no-class-components\n\n"
        "Reason: standardizing on hooks for testability.\n",
        encoding="utf-8",
    )
    (rules / "prefer-pure-functions.md").write_text(
        "---\n"
        "description: Prefer pure functions over stateful helpers in utils/.\n"
        "---\n\n"
        "# prefer-pure-functions\n\n"
        "Body text.\n",
        encoding="utf-8",
    )
    # An unrelated subdirectory we should NOT pick up
    (rules / "runs").mkdir()
    (rules / "runs" / "old-run.md").write_text("ignored", encoding="utf-8")
    # A file missing required frontmatter — used in a separate test
    return rules


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Initializes a git repo with one commit on `main`. Configures user identity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


@pytest.fixture
def make_branch_with_change(tmp_git_repo: Path) -> Callable[[str, str, str], str]:
    """Returns a function that creates a branch, modifies a file, and commits.
    Returns the new branch's HEAD SHA."""
    def _factory(branch: str, filename: str, contents: str) -> str:
        _run(["git", "checkout", "-b", branch], tmp_git_repo)
        (tmp_git_repo / filename).write_text(contents, encoding="utf-8")
        _run(["git", "add", "."], tmp_git_repo)
        _run(["git", "commit", "-m", f"add {filename}"], tmp_git_repo)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_git_repo,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    return _factory
