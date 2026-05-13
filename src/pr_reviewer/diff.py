import subprocess
from pathlib import Path

import pathspec


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


def _extract_dest_path(header_line: str) -> str | None:
    """Extract the b-side path from a 'diff --git a/<a> b/<b>' header.

    Uses rpartition on ' b/' so the LAST occurrence wins — handles the edge
    case where a-path or b-path might contain ' b/' substrings (rare).
    Returns None if the line doesn't match the expected shape.
    """
    body = header_line.removeprefix("diff --git ").rstrip()
    if " b/" not in body:
        return None
    a_part, _, b_part = body.rpartition(" b/")
    if not a_part.startswith("a/"):
        return None
    return b_part


def parse_chunks(diff: str) -> list[tuple[str, str]]:
    """Split a git diff into (dest_path, chunk_text) tuples.

    Extracts dest_path from the 'diff --git a/<a> b/<b>' header line, which is
    ALWAYS present exactly once per chunk regardless of chunk type (modification,
    addition, deletion, rename, binary, or mode-only). For rename chunks, the
    'rename to <Y>' line overrides with the destination — this handles the case
    where 'rename to <Y>' explicitly names the post-rename path.

    chunk_text preserves the full original bytes including the trailing newline
    so concatenating all chunks reconstructs the input diff exactly.
    """
    chunks: list[tuple[str, str]] = []
    current_lines: list[str] = []
    current_dest: str | None = None

    def flush() -> None:
        if current_dest is not None:
            chunks.append((current_dest, "".join(current_lines)))

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            current_lines = [line]
            current_dest = _extract_dest_path(line)
        elif line.startswith("rename to "):
            current_lines.append(line)
            current_dest = line.removeprefix("rename to ").rstrip()
        else:
            current_lines.append(line)

    flush()
    return chunks


def filter_diff(
    diff: str,
    spec: pathspec.PathSpec,
) -> tuple[str, list[str]]:
    """Filter a git diff by dropping chunks whose dest path matches `spec`.

    Returns (filtered_diff, excluded_paths). When `spec` matches no patterns
    (empty), the input diff is returned unchanged and excluded_paths is [].

    Path-matching uses pathspec's gitwildmatch (gitignore-style) semantics:
    - `*` matches within a single path segment
    - `**` matches any number of segments
    - Leading `/` anchors to repo root
    - Leading `!` re-includes a file matched by a prior pattern
    """
    chunks = parse_chunks(diff)
    kept: list[str] = []
    excluded: list[str] = []
    for path, body in chunks:
        if spec.match_file(path):
            excluded.append(path)
        else:
            kept.append(body)
    return "".join(kept), excluded
