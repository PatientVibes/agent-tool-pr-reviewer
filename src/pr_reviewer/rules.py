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
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing YAML frontmatter")
    try:
        _, frontmatter, body = text.split("---\n", 2)
    except ValueError as exc:
        raise ValueError(f"{path}: malformed frontmatter") from exc
    meta = yaml.safe_load(frontmatter) or {}
    description = meta.get("description")
    if not description:
        raise ValueError(f"{path}: missing required frontmatter field 'description'")
    return Rule(rule_id=path.stem, description=description.strip(), body=body.lstrip("\n"))
