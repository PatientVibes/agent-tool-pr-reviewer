# Changelog

## 0.4.0 — 2026-05-13

### Added

- `--models <list>` flag: run N models in parallel and keep only convergent findings (Tier 2 #2). The literal `default` expands to the curated 3-model basket (Gemini 2.5 Pro + Kimi K2.6 + DeepSeek V3.1).
- `--consensus N` flag: minimum models that must flag a finding to survive. Default `2`.
- `--include-uncorroborated` flag: writes below-threshold findings to `uncorroborated.json` for trial debugging.
- New `consensus.py` module with deterministic match-and-merge (file + line-overlap hard key, title 3-gram Jaccard ≥ 0.3 OR evidence containment soft confirm, project-rule cross-line via `(file, rule_id)`).
- `Finding.agreement_count` + `Finding.agreed_by` optional fields.
- `RunMetadata.models` + `RunMetadata.per_model_usage` optional fields; new `ModelUsage` submodel.
- 30-minute per-model timeout (via `asyncio.wait_for`). Partial-failure tolerated: 1 of N failing models doesn't abort the run; 0 of N raises.

### Changed

- Schema version bumped `2` → `3`. Strictly additive — all new fields are optional and default to `None`. v2 consumers (e.g. the `pr-review` skill) continue to work without modification.
- Single-model output adds the four new optional fields serialized as `null`; consumer-visible behavior unchanged.

### Notes

- `--model` and `--models` are mutually exclusive.
- All N models run in parallel; one model's failure is tolerated as long as ≥1 succeeds.
- `.pr-review-ignore` / `--exclude` apply once before dispatch — N models see the same filtered diff.

## 0.3.0 — 2026-05-13

### Added

- **Scope filter for generated/vendored files.** Two-layer deterministic filter that drops excluded files from the diff before the LLM sees them, plus post-hoc finding-drop as defense in depth. Addresses Tier 2 issue #1 — the highest-recurring FP class across both v0.1.0 and v0.2.0 model trials (every model in trial 1 + 5 of 8 new models in trial 2 hit scope-misalignment).
  - **`.pr-review-ignore`** file at repo root, gitignore-style syntax (via `pathspec` library). Recognized when present; absent files leave behavior unchanged.
  - **`--exclude <glob>`** CLI flag on the `review` subcommand, repeatable, additive to `.pr-review-ignore` patterns.
  - Stderr logs `Filtered N file(s) from diff: ...` summary when filtering is active and `Dropped finding for excluded path: <path>` per Layer-2 drop.
- New dependency: `pathspec>=0.12,<1`.

### Compatibility

- No behavior change when no `.pr-review-ignore` is present AND no `--exclude` flag is passed. `findings.json` schema unchanged. The agent prompt and orchestration are untouched.

### Spec / plan

- Spec: `docs/superpowers/specs/2026-05-13-pr-reviewer-v0.3.0-scope-filter-design.md` in the `ai-agents` catalog.
- GitHub issue: [#1 — Tier 2 #1 Scope filter](https://github.com/PatientVibes/agent-tool-pr-reviewer/issues/1).

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
