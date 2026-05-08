from pathlib import Path

import pytest

from pr_reviewer.rules import find_rules_dir, load_rules, Rule


class TestFindRulesDir:
    def test_finds_dir_at_cwd(self, sample_rules_dir: Path):
        repo_root = sample_rules_dir.parent
        assert find_rules_dir(repo_root) == sample_rules_dir

    def test_walks_up_from_subdirectory(self, sample_rules_dir: Path):
        repo_root = sample_rules_dir.parent
        deep = repo_root / "src" / "components"
        deep.mkdir(parents=True)
        assert find_rules_dir(deep) == sample_rules_dir

    def test_returns_none_when_not_found(self, tmp_path: Path):
        assert find_rules_dir(tmp_path) is None

    def test_stops_at_git_repo_root(self, tmp_path: Path):
        # rules dir is OUTSIDE the repo; must not walk past .git
        outer_rules = tmp_path / ".ai-review"
        outer_rules.mkdir()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        deep = repo / "src"
        deep.mkdir()
        assert find_rules_dir(deep) is None


class TestLoadRules:
    def test_loads_flat_md_files(self, sample_rules_dir: Path):
        rules = load_rules(sample_rules_dir)
        ids = sorted(r.rule_id for r in rules)
        assert ids == ["no-class-components", "prefer-pure-functions"]

    def test_skips_subdirectories(self, sample_rules_dir: Path):
        rules = load_rules(sample_rules_dir)
        for r in rules:
            assert "old-run" not in r.rule_id

    def test_parses_description_from_frontmatter(self, sample_rules_dir: Path):
        rules = {r.rule_id: r for r in load_rules(sample_rules_dir)}
        assert "functional" in rules["no-class-components"].description.lower()

    def test_body_excludes_frontmatter(self, sample_rules_dir: Path):
        rules = {r.rule_id: r for r in load_rules(sample_rules_dir)}
        assert "---" not in rules["no-class-components"].body.split("\n")[0]
        assert "Reason:" in rules["no-class-components"].body

    def test_missing_description_raises(self, tmp_path: Path):
        (tmp_path / ".ai-review").mkdir()
        rules_dir = tmp_path / ".ai-review"
        (rules_dir / "broken.md").write_text("no frontmatter here", encoding="utf-8")
        with pytest.raises(ValueError, match="missing YAML frontmatter"):
            load_rules(rules_dir)

    def test_frontmatter_without_description_raises(self, tmp_path: Path):
        (tmp_path / ".ai-review").mkdir()
        rules_dir = tmp_path / ".ai-review"
        (rules_dir / "no-desc.md").write_text(
            "---\ntags: [lint]\n---\n\nbody here\n", encoding="utf-8",
        )
        with pytest.raises(ValueError, match="'description'"):
            load_rules(rules_dir)

    def test_non_string_description_raises(self, tmp_path: Path):
        (tmp_path / ".ai-review").mkdir()
        rules_dir = tmp_path / ".ai-review"
        (rules_dir / "bad-type.md").write_text(
            "---\ndescription:\n  - a\n  - b\n---\n\nbody\n", encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-empty string"):
            load_rules(rules_dir)

    def test_crlf_line_endings_handled(self, tmp_path: Path):
        (tmp_path / ".ai-review").mkdir()
        rules_dir = tmp_path / ".ai-review"
        (rules_dir / "crlf.md").write_bytes(
            b"---\r\ndescription: A description.\r\n---\r\n\r\nbody text\r\n",
        )
        rules = load_rules(rules_dir)
        assert len(rules) == 1
        assert rules[0].description == "A description."
