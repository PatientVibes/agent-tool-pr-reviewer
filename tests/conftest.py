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
