from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Rule:
    rule_id: str
    description: str
    body: str


def find_rules_dir(start: Path) -> Path | None:
    """Walk up from `start` looking for `.ai-review/`. Stop at the first match,
    a directory containing `.git`, or the filesystem root."""
    current = start.resolve()
    while True:
        candidate = current / ".ai-review"
        if candidate.is_dir():
            return candidate
        if (current / ".git").exists():
            return None
        if current.parent == current:
            return None
        current = current.parent


def load_rules(rules_dir: Path) -> list[Rule]:
    """Load all flat `*.md` files from rules_dir. Subdirectories ignored."""
    rules: list[Rule] = []
    for path in sorted(rules_dir.glob("*.md")):
        if not path.is_file():
            continue
        rules.append(_parse_rule_file(path))
    return rules


def _parse_rule_file(path: Path) -> Rule:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise ValueError(f"{path}: malformed frontmatter (missing closing '---')")
    _, frontmatter, body = parts
    meta = yaml.safe_load(frontmatter) or {}
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(
            f"{path}: missing or invalid required frontmatter field 'description' "
            "(must be a non-empty string)"
        )
    return Rule(rule_id=path.stem, description=description.strip(), body=body.lstrip("\n"))
