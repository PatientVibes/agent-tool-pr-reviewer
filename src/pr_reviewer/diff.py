import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git subprocess command failed."""


class BaseRefError(GitError):
    """Could not determine a usable base ref via fallback resolution."""


def _git(repo: Path, *args: str) -> str:
    # encoding="utf-8" is required on Windows. Without it, subprocess defaults
    # to the OS code page (cp1252), which crashes on UTF-8 output like em-dashes
    # in commit messages or diff content. errors="replace" keeps a single bad
    # byte from killing the whole review.
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_base_ref(repo: Path, explicit: str | None) -> str:
    """1) explicit, 2) origin/HEAD short, 3) main, 4) master, 5) raise."""
    if explicit:
        return explicit
    try:
        head = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        if head.startswith("origin/"):
            return head.removeprefix("origin/")
    except GitError:
        pass
    for candidate in ("main", "master"):
        try:
            _git(repo, "rev-parse", "--verify", candidate)
            return candidate
        except GitError:
            continue
    raise BaseRefError(
        "Could not determine base ref. Pass --base <ref> explicitly."
    )


def extract_diff(repo: Path, base: str) -> str:
    # Three-dot syntax: symmetric-difference shorthand. Diffs from the
    # merge-base of `base` and HEAD up to HEAD — i.e., what THIS branch
    # added, ignoring commits made on `base` after the branch point.
    # Do NOT change to two dots without re-checking the spec.
    return _git(repo, "diff", f"{base}...HEAD")


def head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def merge_base(repo: Path, base: str) -> str:
    return _git(repo, "merge-base", "HEAD", base).strip()


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
