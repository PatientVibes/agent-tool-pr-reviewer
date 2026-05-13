"""Tests for the v0.3.0 scope filter — diff parsing + pathspec-based file filtering."""
from pathlib import Path

import pathspec
import pytest

from pr_reviewer.diff import parse_chunks, filter_diff


FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseChunks:
    def test_parses_three_modification_chunks(self):
        diff = _load_fixture("sample-diff-modifications.diff")
        chunks = parse_chunks(diff)
        assert len(chunks) == 3
        paths = [path for path, _body in chunks]
        assert paths == [
            "src/keep_me.py",
            "tests/fixtures/generated.sql",
            "docs/keep_me.md",
        ]

    def test_each_chunk_body_starts_with_diff_git_marker(self):
        diff = _load_fixture("sample-diff-modifications.diff")
        chunks = parse_chunks(diff)
        for _path, body in chunks:
            assert body.startswith("diff --git ")

    def test_concatenating_chunks_reconstructs_input(self):
        diff = _load_fixture("sample-diff-modifications.diff")
        chunks = parse_chunks(diff)
        reconstructed = "".join(body for _path, body in chunks)
        assert reconstructed == diff


class TestParseChunksEdgeCases:
    def test_rename_chunk_uses_destination_path(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        chunks = parse_chunks(diff)
        rename_path, rename_body = chunks[0]
        assert rename_path == "new_name.py"
        assert "rename from old_name.py" in rename_body
        assert "rename to new_name.py" in rename_body

    def test_binary_chunk_extracts_path_from_header(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        chunks = parse_chunks(diff)
        binary = [(p, b) for p, b in chunks if "Binary files" in b]
        assert len(binary) == 1
        assert binary[0][0] == "bin.dat"

    def test_mode_only_chunk_extracts_path_from_header(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        chunks = parse_chunks(diff)
        mode_only = [(p, b) for p, b in chunks if "old mode" in b]
        assert len(mode_only) == 1
        assert mode_only[0][0] == "exec_me.sh"

    def test_addition_chunk_extracts_dest_path(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        chunks = parse_chunks(diff)
        added = [(p, b) for p, b in chunks if "new file mode 100644" in b and "--- /dev/null" in b]
        assert len(added) == 1
        assert added[0][0] == "added.txt"

    def test_deletion_chunk_extracts_path_from_header(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        chunks = parse_chunks(diff)
        deleted = [(p, b) for p, b in chunks if "deleted file mode 100644" in b]
        assert len(deleted) == 1
        assert deleted[0][0] == "deleted.txt"

    def test_all_five_edge_case_chunks_parsed(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        chunks = parse_chunks(diff)
        assert len(chunks) == 5
        paths = [p for p, _ in chunks]
        assert paths == ["new_name.py", "added.txt", "deleted.txt", "bin.dat", "exec_me.sh"]


def _spec_from_patterns(patterns: list[str]) -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


class TestFilterDiff:
    def test_empty_spec_returns_input_unchanged(self):
        """G6: empty-spec passthrough — no patterns means filter_diff is a no-op."""
        diff = _load_fixture("sample-diff-modifications.diff")
        empty_spec = _spec_from_patterns([])
        filtered, excluded = filter_diff(diff, empty_spec)
        assert filtered == diff
        assert excluded == []

    def test_excluded_chunk_removed_from_output(self):
        diff = _load_fixture("sample-diff-modifications.diff")
        spec = _spec_from_patterns(["tests/fixtures/*.sql"])
        filtered, excluded = filter_diff(diff, spec)
        assert "tests/fixtures/generated.sql" not in filtered
        assert "src/keep_me.py" in filtered
        assert "docs/keep_me.md" in filtered
        assert excluded == ["tests/fixtures/generated.sql"]

    def test_excluded_chunks_are_full_chunks_not_partial(self):
        """Filtering drops entire diff hunks, not just lines."""
        diff = _load_fixture("sample-diff-modifications.diff")
        spec = _spec_from_patterns(["tests/fixtures/*.sql"])
        filtered, _ = filter_diff(diff, spec)
        assert "index 1111111..2222222" not in filtered
        assert "SELECT 99" not in filtered

    def test_multiple_excludes_drop_multiple_chunks(self):
        diff = _load_fixture("sample-diff-edge-cases.diff")
        spec = _spec_from_patterns(["*.dat", "added.txt"])
        filtered, excluded = filter_diff(diff, spec)
        assert "bin.dat" not in filtered
        assert "added.txt" not in filtered
        assert "new_name.py" in filtered
        assert set(excluded) == {"bin.dat", "added.txt"}

    def test_gitignore_negation_re_includes(self):
        """! re-includes a file that a prior pattern excluded."""
        diff = _load_fixture("sample-diff-modifications.diff")
        spec = _spec_from_patterns([
            "tests/fixtures/*.sql",
            "!tests/fixtures/generated.sql",
        ])
        filtered, excluded = filter_diff(diff, spec)
        assert "tests/fixtures/generated.sql" in filtered
        assert excluded == []

    def test_filter_with_anchored_pattern(self):
        diff = _load_fixture("sample-diff-modifications.diff")
        # Leading / anchors to repo root — should NOT match nested paths
        spec = _spec_from_patterns(["/generated.sql"])
        filtered, excluded = filter_diff(diff, spec)
        assert "tests/fixtures/generated.sql" in filtered
        assert excluded == []
