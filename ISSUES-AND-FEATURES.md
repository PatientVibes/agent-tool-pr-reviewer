# Issues & Features — agent-tool-pr-reviewer

The single source of truth for what this tool does, what it deliberately does
not, and its known limits. Version history is in [`CHANGELOG.md`](CHANGELOG.md);
usage is in [`README.md`](README.md).

## Features (shipped)

| Feature | Notes |
|---|---|
| Single-model review | One Pydantic AI call over `git diff --merge-base`; default `openrouter:moonshotai/kimi-k3`, override with `--model`. |
| Typed output | `findings.json` (Pydantic-validated `Report`) + `review-output.md`, under `.ai-review/runs/<ts>/`. |
| Project rules | `.ai-review/<rule_id>.md` files (frontmatter `description:` + prose body) become `project_rule` findings with a `rule_id`. |
| File exclusion | `.pr-review-ignore` (gitignore syntax) + repeatable `--exclude <glob>`; Layer-1 (pre-LLM) drop + Layer-2 (post-LLM) defense. |
| Date-FP guard | Deterministic filter dropping "future date / typo" findings whose evidence has a recent ISO date AND description has a future-date keyword. `--no-date-guard` to disable. |
| Verifier pass | Optional `--verifier <model>` Layer-3 filter: deterministic evidence-verbatim + file-in-diff gates, plus an LLM judge for self-withdrawal / speculation / scope-drift. `default` = the review model; pass a different model for cross-family checking. Off by default. |
| Tool-use precheck | Probes the resolved model(s) for structured-tool-call support before dispatch; exits 2 on a known/likely-incompatible model. `--skip-precheck` to bypass. Denylist in `compat.py`. |
| Budget guard | `--budget` (default 80k tokens); over-budget prompts exit 2 rather than truncate. |

## Known issues / limitations

- **Single point of failure.** With one model, there is no second opinion by
  default. Mitigation: run `--verifier <a-different-model>` when a cross-family
  check matters. (This is the deliberate trade for dropping the consensus basket,
  which failed *silently*; a single model failing is at least loud.)
- **Bug-category false positives.** `bug` findings (no `rule_id`) historically had
  a higher FP rate than `project_rule` findings, especially claims about external
  tooling (CLI flag validity, library defaults) or patterns inferred from
  asymmetry. Consumers should surface the `evidence` quote verbatim so a human can
  spot a hallucination. The date-FP guard catches one specific class; the rest is
  on the caller to triage.
- **Local branch only.** No GitHub PR fetch — reviews `HEAD` vs a base ref in the
  current checkout.
- **No auto-chunking.** An over-budget diff is refused (exit 2), not split.
- **All rules apply to all files.** No per-rule `applies_to` globbing yet.

## Deferred / out of scope

- Multi-model consensus — **retired in 0.6.0** (see CHANGELOG); not coming back
  without an owner decision.
- GitHub PR mode (`--pr <num>`, `gh` integration).
- Security findings — use Anthropic's `/security-review` instead.
- API/contract-breaking-change, doc-drift, and test-coverage finding categories.
- Auto-chunking for oversized diffs.
- Per-rule scoping (glob `applies_to`).
- Dollar-cost estimation in output.
- MCP server wrapping the same logic.
- Auto-apply of suggested fixes (`--fix`).

## Ideas / candidate work

- A lightweight, opt-in *second* model strictly as a verifier default (cross-family)
  rather than a voting basket — keeps the "one reviewer" model while restoring an
  independent check for those who want it.
- Per-rule `applies_to` globbing.
- GitHub PR mode behind `--pr`.
