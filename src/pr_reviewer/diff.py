import subprocess
from pathlib import Path


class BaseRefError(RuntimeError):
    """Could not determine a usable base ref."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise BaseRefError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_base_ref(repo: Path, explicit: str | None) -> str:
    """1) explicit, 2) origin/HEAD short, 3) main, 4) master, 5) raise."""
    if explicit:
        return explicit
    try:
        head = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        if head.startswith("origin/"):
            return head.removeprefix("origin/")
    except BaseRefError:
        pass
    for candidate in ("main", "master"):
        try:
            _git(repo, "rev-parse", "--verify", candidate)
            return candidate
        except BaseRefError:
            continue
    raise BaseRefError(
        "Could not determine base ref. Pass --base <ref> explicitly."
    )


def extract_diff(repo: Path, base: str) -> str:
    return _git(repo, "diff", f"{base}...HEAD")


def head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def merge_base(repo: Path, base: str) -> str:
    return _git(repo, "merge-base", "HEAD", base).strip()


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
