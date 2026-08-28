# Changelog

## 0.6.0 — 2026-08-28

**Single-model reviewer (Kimi K3).** Removed multi-model consensus entirely. The 3-model basket (Gemini 2.5 Pro + Kimi K2.6 + DeepSeek V3.1, keep-if-≥2) kept degrading in practice — Gemini's OpenRouter endpoint returned `finish_reason: error`, DeepSeek returned near-empty responses — so "consensus" silently collapsed to whichever one model still answered, and a clean single-model pass was reported as a 3-model agreement. One dependable model, honestly reported, replaces it. **Breaking.**

- **CHANGED**: the review runs a single model. Default is now `openrouter:moonshotai/kimi-k3` (was `openrouter:google/gemini-2.5-pro`). Override with `--model`.
- **REMOVED**: `--models`, `--consensus`, `--include-uncorroborated` flags; the `consensus.py` module (`DEFAULT_BASKET`, `resolve_models_arg`, `merge_reports`, `PerModelResult`); `run_multi_model_review_command` / `_dispatch_one_model`; the 30-min per-model timeout; the `[consensus] …` / `Multi-model consensus (n/n …)` / `Convergence:` stderr output; the `uncorroborated.json` sidecar.
- **REMOVED (schema)**: `ModelUsage` submodel; `RunMetadata.models`, `RunMetadata.per_model_usage`; `Finding.agreement_count`, `Finding.agreed_by`; the `**Agreement:** N/M` render block. `schema_version` stays `"3"` — the removed fields were all optional (nullable), so a `"3"` report without them is still schema-valid.
- **CHANGED**: `--verifier default` now resolves to the review model (Kimi K3) — a self-consistency pass. Pass an explicit `--verifier <other-model>` for a genuine cross-family second opinion. The verifier itself is unchanged and still off by default.
- **DOCS**: README rewritten for single-model; added `CLAUDE.md` and `ISSUES-AND-FEATURES.md`; removed stale `.venv-broken-901/` / `.smoke/`; `.gitignore` now anchors `.venv*/`.
- **Tests**: removed the consensus/multi-model suites (`test_consensus.py`, `test_cli_multi_model_smoke.py`, `test_cli_verifier_multi_model_smoke.py`, `test_schema_v3.py`, `test_render_v3.py`) and the one multi-model precheck case. Total: 156 tests, all green.

## 0.5.3 — 2026-05-14

**Feature: date-FP guard.** New deterministic post-LLM filter drops "future date / typo" findings whose evidence contains an ISO date in `(today - 730 days, today)` AND whose description contains a known future-date/typo keyword. Eliminates the Gemini training-cutoff false-positive class without paying `--verifier default`'s ~$0.05/run.

- **NEW**: `src/pr_reviewer/date_guard.py` module (~120 LOC). Public API: `DATE_GUARD_RECENT_WINDOW_DAYS = 730`; `KEYWORD_ALLOWLIST` (5 empirical phrases: `"future date"`, `"future-date"`, `"date in the future"`, `"likely a typo"`, `"appears to be a typo"`); `ISO_DATE_RE` with anti-partial-match lookarounds; `DateGuardDecision` dataclass; `is_date_fp(finding, today)`; `run_date_guard(findings, today=None)`; `serialize_date_guard_decisions(decisions) -> str` (matches `verifier.serialize_decisions` str-return pattern).
- **NEW**: `--no-date-guard` CLI flag (default `False`; opt-out, mirrors `--skip-precheck` style). Skips the guard call entirely; no sidecar written when set.
- **NEW**: `RunMetadata.date_guard_dropped: int = 0` field (additive-optional, `schema_version` stays `"3"` per the v0.5.0 `verifier_model` precedent).
- **Pipeline**: guard runs BEFORE the verifier; drops are final. Both single-model (`run_review_command`) and consensus (`run_multi_model_review_command`) paths wired. In consensus mode, the guard sees one pass on the merged `Report.findings`, not per-model. `--include-uncorroborated`'s `uncorroborated.json` passes through unfiltered by design.
- **Sidecar**: `<run_dir>/dropped-by-date-guard.json` written when drops > 0. Schema: `[{finding: {...full Finding...}, drop_reason: "model_knowledge_cutoff", matched_keyword: "...", matched_date: "ISO-8601"}]`.
- **Render**: stdout summary grows a conditional `_Date-FP guard: dropped N_` footer row when N > 0; omitted at zero.
- **Tests**: 23 new (5 parametrized + 14 named in `tests/test_date_guard.py`; 2 in `tests/test_render.py`; 2 single-model smoke + 1 multi-model smoke in `tests/test_cli_smoke.py` and `tests/test_cli_multi_model_smoke.py`). Total: 210 tests.
- **Known FN**: `consensus._merge_group` keeps `longest_evidence` and concatenates descriptions. If the longest-evidence sibling lacks the ISO date but a shorter sibling had it, the merged finding loses the date signal — the guard misses (intentional FN, pinned by `test_asymmetric_merge_fn_pinned`). Revisit in v0.5.4+ if real-world data shows this class is meaningful.
- **Co-plan**: Gemini 2.5-pro was rate-limited at planning time; opencode → Kimi K2.6 ran the critique pass. 2 CRITICAL + 4 IMPORTANT findings (step ordering, `"should be 20"` too broad, constraint phrasing, asymmetric-merge FN, multi-model smoke gap, render-test gap) all addressed before implementation began.
- **Spec**: [`2026-05-14-pr-reviewer-v0.5.3-date-fp-guard-design.md`](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/specs/2026-05-14-pr-reviewer-v0.5.3-date-fp-guard-design.md). **Plan**: [`2026-05-14-pr-reviewer-v0.5.3-date-fp-guard.md`](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/plans/2026-05-14-pr-reviewer-v0.5.3-date-fp-guard.md).

## 0.5.2 — 2026-05-14

NIT cleanup release — no behavior changes, no API changes.

- **Cleanup**: removed redundant `from pathlib import Path` inside `_apply_verifier_pass` in `cli.py` (already imported at module scope).
- **Cleanup**: removed unused `asdict` import in `verifier.py` (serialization uses manual dict construction in `serialize_decisions`).
- **Refactor**: dropped the one-use `use_multi_model` flag in `cli.py:main()`; the dispatch site now reads `len(resolved_review_models) > 1` directly.
- **Tests**: extracted duplicated `_make_metadata` / `_make_run_metadata` helpers from `test_cli_precheck_smoke.py`, `test_cli_verifier_smoke.py`, and `test_cli_verifier_multi_model_smoke.py` into a single `make_run_metadata` factory in `tests/conftest.py`.
- **Tests**: added `test_precheck_ok_dispatches_reviewer` — the missing happy-path test (probe returns OK → reviewer dispatches; `[precheck] ... OK` line emits).
- **Tests**: added `test_run_verifier_pass_all_project_rule_skips_judge` — end-to-end coverage of the zero-bug-survivors path through `run_verifier_pass`. Asserts `build_agent` is never called (proof the judge stage was actually skipped, not just keep-all by coincidence).
- **Tests**: tightened `probe_outcome: str` to `Literal["OK", "NO_TOOL_SUPPORT", "AUTH_FAIL", "OTHER"]` in `_install_dual_purpose_fakes` for static-analysis catch on typos.
- **Tests**: 186 total (was 184 at v0.5.1).

## 0.5.1 — 2026-05-14

- **NEW**: tool-use compatibility precheck (Layer 0) — every `review` invocation probes each resolved model (reviewer + consensus basket + verifier) before dispatching the real review. Detected incompatibilities exit 2 with an actionable error.
- **NEW**: `--skip-precheck` flag for opt-out (e.g., when the probe itself is flaky or you want to deliberately test a known-borderline model).
- **NEW**: `KNOWN_INCOMPATIBLE` denylist in `src/pr_reviewer/compat.py` seeded with `openrouter:meta-llama/llama-4-maverick` and `openrouter:deepseek/deepseek-r1-distill-qwen-32b` (zero-token short-circuit). Unknown models get a live probe via `Agent.run("ping")` with a nested `ProbeResult` output type that mirrors `Report.findings: list[Finding]`.
- **Refactor**: `cli.py:main()` now hoists model resolution out of the `if/else` dispatch branches so the precheck sees the full resolved list. Two sequential `asyncio.run` calls (precheck, then dispatch) — pydantic-ai supports this.
- **Behavior**: classification is `OK` / `DENIED` / `NO_TOOL_SUPPORT` / `AUTH_FAIL` / `OTHER`. The first three trigger exit 2; `OTHER` fails-open with a stderr warning (matches v0.5.0 verifier's philosophy).
- **Tests**: 21 new tests (16 unit in `test_compat.py` + 5 CLI smoke in `test_cli_precheck_smoke.py`); 11 existing `cli.main([...])` invocations updated with `--skip-precheck` so their reviewer-only fakes aren't validated as `ProbeResult`. 184 total.
- **Closes**: Tier 2 #5 — the last remaining Tier-2 issue on this repo.

## 0.5.0 — 2026-05-14

- **NEW**: `--verifier MODEL` flag — Layer-3 precision filter (deterministic gate + LLM judge) runs after consensus + scope filter. Drops findings on evidence-not-verbatim, file-not-in-diff, self-withdrawal, speculation-at-high+blocker, or scope-drift. Off by default. Sugar `--verifier default` expands to `openrouter:anthropic/claude-sonnet-4-6` (cross-family bias resistance; same OpenRouter API key).
- **NEW**: `dropped-by-verifier.json` sidecar written when verifier drops findings; entries include `drop_stage` (`deterministic` or `judge`) and `drop_reason`.
- **Schema**: `RunMetadata.verifier_model: str | None = None` added (optional). `schema_version` stays `"3"` — additive optional fields don't bump.
- **Refactor**: `build_agent(model, output_type, system_prompt)` — both `output_type` and `system_prompt` now required keyword arguments. Existing callers in `cli.py` and `test_agent.py` pass them explicitly. The two must vary together (a `Report` output type pairs with the reviewer's prompt; a `VerdictBatch` pairs with the verifier's).
- **Behavior**: `project_rule` findings skip the LLM judge stage (deterministic gate still applies). Drop-only verdicts; no downgrade or rewrite in v0.5.0. Fail-open on any judge-stage exception: keep all stage-3a survivors, log `[verifier] errored: ...`, set `RunMetadata.verifier_model` to record the attempt.
- **Tests**: 27 new tests (15 unit + 5 single-model smoke + 2 multi-model smoke + 1 schema roundtrip + 4 extract_changed_files); 163 total.

## 0.4.1 — 2026-05-13

### Changed

- **Widened hedging-word guard** (Tier 2 #4). The system prompt's hedging-word check now (a) applies at `high` severity in addition to `blocker`, and (b) adds `can` and `would` to the guarded-words list. Catches the "X can crash if Y is Z" speculative-consequence pattern observed in trial 1 gpt-5 phase-3 that slipped past the blocker-only / 7-word guard at medium severity. Pure precision improvement, no API or schema change.

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
