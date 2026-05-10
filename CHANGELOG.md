# Changelog

## 0.2.2 — 2026-05-09

### Changed

- **Default `--model` is now `openrouter:google/gemini-2.5-pro`** (was `anthropic:claude-sonnet-4-6`). Earned by two trials totalling 16 distinct models across 39 successful runs on chorus-sqlserver PRs: Gemini 2.5 Pro caught both real bugs at ~$0.06/run while Sonnet 4.6 missed the `:r` bug. README's new "Recommended models" section captures the full preference order (Gemini > Kimi K2.6 > DeepSeek V3.1) and the rationale.
- The default now requires `OPENROUTER_API_KEY` instead of `ANTHROPIC_API_KEY`. Environment-variable docs reordered accordingly.

### Note

This is **user-visible behavior change** — fresh installs that don't pass `--model` will fail with a missing-`OPENROUTER_API_KEY` error instead of contacting Anthropic by default. Existing users with `ANTHROPIC_API_KEY` set can preserve old behavior by passing `--model anthropic:claude-sonnet-4-6` explicitly.

## 0.2.1 — 2026-05-09

### Fixed

- OpenRouter responses with `service_tier: "standard"` (or any value outside the openai SDK's `Literal["auto", "default", "flex", "scale", "priority"]`) no longer fail pydantic-ai's strict re-validation in `_process_response`. The `openrouter:*` resolver now returns a tolerant `OpenAIChatModel` subclass that drops unknown service_tier values before delegating to super. Earned by phase-2-fix gemini failing 3/3 retries on this validation; root-caused to pydantic-ai 0.8.x at `models/openai.py:471` re-validating an openai-SDK `model_construct`-built response.

### Added

- `_coerce_service_tier` helper + `_TolerantOpenRouterChatModel` subclass in `pr_reviewer.agent`. 5 tests covering the helper's coerce/preserve/none/end-to-end paths plus a wiring sanity check on `resolve_model`.

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
