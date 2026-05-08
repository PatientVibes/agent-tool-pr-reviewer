from pathlib import Path

import pytest

from pr_reviewer.diff import (
    BaseRefError,
    current_branch,
    extract_diff,
    head_sha,
    merge_base,
    resolve_base_ref,
)


def test_resolve_base_ref_uses_explicit_when_given(tmp_git_repo: Path):
    assert resolve_base_ref(tmp_git_repo, explicit="main") == "main"


def test_resolve_base_ref_falls_back_to_main(tmp_git_repo: Path):
    assert resolve_base_ref(tmp_git_repo, explicit=None) == "main"


def test_resolve_base_ref_raises_when_unresolvable(tmp_path: Path):
    # Bare directory, not a git repo
    with pytest.raises(BaseRefError):
        resolve_base_ref(tmp_path, explicit=None)


def test_extract_diff_returns_unified_diff(tmp_git_repo: Path, make_branch_with_change):
    make_branch_with_change("feature/x", "feature.py", "print('hi')\n")
    diff = extract_diff(tmp_git_repo, base="main")
    assert "diff --git" in diff
    assert "feature.py" in diff
    assert "+print('hi')" in diff


def test_head_sha_returns_40_char_hex(tmp_git_repo: Path):
    sha = head_sha(tmp_git_repo)
    assert len(sha) == 40
    int(sha, 16)  # valid hex


def test_merge_base_matches_main_when_branch_is_descendant(tmp_git_repo: Path, make_branch_with_change):
    make_branch_with_change("feature/x", "f.py", "x\n")
    base_sha = merge_base(tmp_git_repo, "main")
    # The merge-base of feature/x and main is the initial commit on main.
    import subprocess
    main_sha = subprocess.run(
        ["git", "rev-parse", "main"], cwd=tmp_git_repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert base_sha == main_sha


def test_current_branch_after_checkout(tmp_git_repo: Path, make_branch_with_change):
    make_branch_with_change("feature/x", "f.py", "x\n")
    assert current_branch(tmp_git_repo) == "feature/x"
