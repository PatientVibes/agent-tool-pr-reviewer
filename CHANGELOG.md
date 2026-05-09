# Changelog

## 0.2.0 — 2026-05-08

### Breaking

- `findings.json` schema bumped from `"1"` to `"2"`.
- `Finding` now requires a non-empty `evidence: str` (max 500 chars). Old `findings.json` files from 0.1.0 will not validate under 0.2.0 readers.

### Added

- `Finding.evidence` — required verbatim quote from the diff that grounds each finding.
- System prompt: explicit "Out of scope" exclusions for external-tool / CLI / library syntax claims and speculative downstream consequences.
- Hedging-word guard on `blocker` severity (must state consequence without "might", "may", "could", "potentially", "likely", "probably", "possibly").
- Renderer surfaces `evidence` as a 4-backtick fenced code block (`diff` language tag) immediately after the finding title, before the category. 4-backtick fence prevents collisions with internal triple-backticks (markdown-file diffs).
- Test coverage for evidence validation, prompt content, and triple-backtick collision in evidence rendering. Suite grew from 54 to 63 tests.

### Changed

- `RunMetadata.schema_version`: `Literal["1"]` → `Literal["2"]`. Default updates accordingly.

### Earned by

Phase-1 trial (2026-05-08): 4 models on a single chorus-sqlserver Docker/Flyway diff produced 4 findings, 0 true positives. Two failure modes named: external-tool-hallucination and speculative-downstream-consequences. See `D:/ai-agents/docs/superpowers/specs/2026-05-08-pr-reviewer-evidence-and-prompt-tightening-design.md`.

## 0.1.0 — 2026-05-07

Initial release. Local-branch reviewer with deterministic narrowing → single Pydantic AI call → typed Report. Categories: `bug`, `project_rule`. Pairs with the `pr-review` skill in the `agent-skills` marketplace.
