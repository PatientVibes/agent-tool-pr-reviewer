# CLAUDE.md — agent-tool-pr-reviewer

Agent instructions for working in this repo. Human-facing usage lives in
[`README.md`](README.md); the roadmap and known limits live in
[`ISSUES-AND-FEATURES.md`](ISSUES-AND-FEATURES.md).

## What this is

A single-model AI PR reviewer. It diffs HEAD against a base ref, sends the diff
+ the repo's `.ai-review/*.md` rules through **one** Pydantic AI call, and writes
a typed `findings.json` + `review-output.md`. Everything except that one LLM call
is deterministic.

**One model, on purpose.** The reviewer runs Kimi K3
(`openrouter:moonshotai/kimi-k3`) by default. It used to run a 3-model consensus
basket (Gemini + Kimi K2.6 + DeepSeek); that was removed in 0.6.0 because the
basket kept degrading (dead/erroring endpoints) and silently reported a
single surviving model as a "consensus". Do **not** reintroduce a model basket
without a deliberate decision from the owner — precision is the job of the
deterministic filters and the optional `--verifier` pass, not cross-model voting.

## Rules for changes here

1. **Deterministic-first.** Only `agent.py` / `verifier.py` make LLM calls. Every
   other module is pure and unit-tested with Pydantic AI's `TestModel` — tests
   never hit the network. Keep it that way.
2. **The schema is the contract.** `schema.py`'s `Report` is what downstream
   consumers (the `pr-review` skill) rely on. Additive-optional fields keep
   `schema_version` at `"3"`; a shape change that removes/renames a non-optional
   field is a schema bump — say so in the CHANGELOG.
3. **Fail loud on config, fail open on flakiness.** Config errors (bad base ref,
   over budget, denylisted model, missing key) exit 2 before burning tokens; an
   ambiguous precheck/verifier hiccup warns and proceeds.
4. **Never invent evidence.** A `Finding.evidence` quote must be verbatim from the
   diff; the verifier's deterministic gate enforces this. Don't relax it.

## Model config lives in exactly two constants

- `cli.py` → `DEFAULT_MODEL` (the review model).
- `verifier.py` → `DEFAULT_VERIFIER_MODEL` (what `--verifier default` resolves to).

Denylisted (tool-use-incompatible) model IDs are in `compat.py` → `KNOWN_INCOMPATIBLE`.

## Commands

```bash
cd D:/agent-tool-pr-reviewer
uv sync --extra dev          # first run / after dep changes
uv run pytest -q             # full suite (156 tests, offline)
uv run agent-tool-pr-reviewer review --help
```

Install as a tool: `uv tool install --editable D:/agent-tool-pr-reviewer`.
Needs `OPENROUTER_API_KEY` for any `openrouter:` model (the default).

## Layout

`src/pr_reviewer/`: `schema.py` (models) · `diff.py` (git wrappers) · `rules.py`
(`.ai-review/` discovery) · `prompt.py` · `agent.py` (Pydantic AI construction) ·
`compat.py` (tool-use precheck + denylist) · `date_guard.py` (deterministic
future-date FP filter) · `verifier.py` (optional Layer-3 pass) · `render.py`
(`Report` → markdown) · `paths.py` · `cli.py` (argparse + dispatch).
