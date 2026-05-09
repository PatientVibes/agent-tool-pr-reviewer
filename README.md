# agent-tool-pr-reviewer

CLI that reviews the current git branch's diff against a base ref using a single Pydantic AI call. Emits a typed `findings.json` plus a human-readable `review-output.md` under `<repo>/.ai-review/runs/<timestamp>/`.

Pairs with the [`pr-review`](../../agent-skills/plugins/pr-review-tools/skills/pr-review/SKILL.md) skill in the `agent-skills` Claude Code plugin marketplace, which runs this CLI and surfaces blocker/high findings to the user.

## Install

```bash
uv tool install --editable D:/agent-tool-pr-reviewer
```

Verify:

```bash
agent-tool-pr-reviewer --version    # 0.2.1
```

The default model is `anthropic:claude-sonnet-4-6`, which expects `ANTHROPIC_API_KEY` in the environment.

## Quick start

From inside any repo with at least one rule file:

```bash
mkdir .ai-review
cat > .ai-review/no-bare-fences.md <<'EOF'
---
description: All fenced markdown code blocks must specify a language.
---

# no-bare-fences

Reason: bare ``` blocks render unstyled and lose semantic info.
EOF

git checkout -b feature/x
# make some changes ...
git commit -am "test"

agent-tool-pr-reviewer review
```

Output goes to `.ai-review/runs/<UTC-timestamp>/`. Read `findings.json` for the typed contract or `review-output.md` for a quick human read.

## How it works

```
git diff --merge-base   →   .ai-review/*.md   →   single Pydantic AI call   →   typed Report
                                                                              ↓
                                                            findings.json + review-output.md
```

Deterministic everywhere except the one LLM call. The schema is the contract — every finding has a stable `category` (`bug` or `project_rule`), a `severity` (`blocker | high | medium | low`), a file/line range, an `evidence` quote (verbatim diff lines, 1–500 chars), and (for `project_rule`) a `rule_id` matching the `.md` filename of the violated rule.

See `D:/ai-agents/docs/superpowers/specs/2026-05-07-agent-tool-pr-reviewer-design.md` for full design rationale.

## CLI reference

### `review`

Reviews HEAD against the resolved base ref.

| Flag | Default | Notes |
|---|---|---|
| `--base <ref>` | auto-detect | `git symbolic-ref refs/remotes/origin/HEAD` → `main` → `master` → fail |
| `--budget <tokens>` | `80000` | Refuses with exit 2 if the assembled prompt exceeds this. Heuristic: ~4 chars/token. |
| `--rules-dir <path>` | walk up from cwd | First `.ai-review/` directory found before hitting `.git/` or filesystem root |
| `--out <path>` | `<repo>/.ai-review/runs/<ts>/` | When set, suppresses `latest.txt` write |
| `--model <model-string>` | `anthropic:claude-sonnet-4-6` | Any Pydantic AI model string (`openai:gpt-4o`, `ollama:llama3.1`, etc.) OR `openrouter:<model>` to route through OpenRouter (see Configuration) |

### `rules list`

Prints discovered rules (`<rule_id>\t<description>`) without making any LLM call. Useful for sanity-checking which rules will be applied.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Review completed; no `blocker` findings |
| `1` | Review completed; one or more `blocker` findings present |
| `2` | Configuration error: base ref unresolvable, budget exceeded, malformed rule frontmatter, missing API key, etc. |

## Rule file format

Rules live in `<repo>/.ai-review/<rule-id>.md` (flat, no subdirectories). The filename — minus `.md` — is the `rule_id`. Each file:

```markdown
---
description: One-line summary used by `rules list` and surfaced to the model.
---

# rule-id-here

Free-form prose: explain why, give examples, anti-examples, edge cases.
The model receives the full body verbatim.
```

The frontmatter `description:` field is **required** — the CLI exits 2 with a clear message on missing or non-string descriptions. Subdirectories of `.ai-review/` (notably `runs/`) are skipped during discovery.

## Output layout

```
<repo>/.ai-review/
  <rule>.md                      ← committed; rules
  runs/                          ← gitignored; one subdir per run
    2026-05-08T03-55-23Z/
      findings.json              ← typed Report (Pydantic-validated)
      review-output.md           ← human-readable rendering
    latest.txt                   ← single line: basename of the freshest run
```

`findings.json` round-trips through `pr_reviewer.schema.Report.model_validate_json` cleanly; downstream consumers (e.g., the `pr-review` skill) can rely on the schema without defensive re-validation.

## Configuration

| Env var | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | when using the default model | Pydantic AI's default for the `anthropic:` provider |
| `OPENAI_API_KEY` | when using `--model openai:...` | |
| `OPENROUTER_API_KEY` | when using `--model openrouter:...` | OpenRouter routes to many providers (Anthropic, OpenAI, Google, etc.) under one key |
| (other provider keys) | as needed | See [Pydantic AI provider docs](https://ai.pydantic.dev/models/) |

No config file in v1. Everything is via flags + env.

### Using OpenRouter

`--model openrouter:<model-name>` wraps an `OpenAIChatModel` with Pydantic AI's `OpenRouterProvider`. Model names follow OpenRouter's slash convention:

```bash
agent-tool-pr-reviewer review --model openrouter:anthropic/claude-sonnet-4
agent-tool-pr-reviewer review --model openrouter:openai/gpt-4o
agent-tool-pr-reviewer review --model openrouter:google/gemini-2.5-pro
```

A single `OPENROUTER_API_KEY` covers all of them. The model name shows up in `findings.json`'s `metadata.model` exactly as you typed it (e.g., `openrouter:anthropic/claude-sonnet-4`), so runs across providers stay distinguishable.

## Troubleshooting

**`UnicodeDecodeError: 'charmap' codec ...` on Windows.** Already fixed in v0.1.0 — `_git` forces `encoding="utf-8"` for subprocess output. If you see it on a non-Windows platform, file an issue.

**`ImportError: Please install anthropic to use the Anthropic model`.** The `anthropic` SDK lower-bound floats; recent 0.100+ versions removed types that pydantic-ai 0.8.x still imports. The pin in `pyproject.toml` (`anthropic>=0.61,<0.70`) addresses this. Run `uv tool install --editable . --reinstall` after pulling.

**`error: Could not determine base ref. Pass --base <ref> explicitly.`** Your repo has no `origin/HEAD`, no `main`, and no `master` branch. Pass `--base <whatever-your-default-is>`.

**`error: prompt exceeds --budget N tokens.`** The diff is too big. Either split the PR, or pass `--budget` with a higher value if you trust your model's context window.

## Calibration notes

**Phase-1 trial (2026-05-08, v0.1.0)**: 4 models (Claude Sonnet 4.6, GPT-5, Gemini 2.5 Pro, DeepSeek V3.1) via OpenRouter on a single Docker/Flyway diff in chorus-sqlserver. 4 findings, 0 true positives. Two failure modes named: external-tool-hallucination (GPT-5 confidently flagged a valid `sqlcmd -No` flag as invalid) and speculative-downstream-consequences (GPT-5 chained "X fails → Y fails → Z blocked" without grounding). v0.2.0's required `evidence` field, system-prompt exclusions, and hedging-word guard on blockers are the targeted response.

**Bug-vs-rule FP rate**: in phase-1, `bug`-category findings (no `rule_id`) had a higher false-positive rate than `project_rule` findings. The skill body's calibration note recommends surfacing the evidence quote prominently and asking the user to verify before acting on bug findings. Re-evaluate this once phase-2+ data accumulates.

## What's NOT in v1

Deferred deliberately:

- **GitHub PR mode** (`--pr <num>`, `gh` integration) — local branch only.
- **Verifier / evaluator-optimizer pass** — single LLM call, no second-pass grounding.
- **Security findings** — covered by Anthropic's `/security-review` slash command. Out of scope here.
- **API/contract-breaking-change, doc-drift, test-coverage categories.**
- **Auto-chunking for oversized diffs** — refuse with exit 2.
- **Per-rule scoping** (glob `applies_to`) — all rules apply to all changed files.
- **Token cost estimation in dollars.**
- **MCP server wrapping the same logic.**
- **Auto-apply for suggested fixes** (`--fix` mode).

See the spec's "Out of scope" section for the full list.

## Development

```bash
cd D:/agent-tool-pr-reviewer
uv sync --extra dev
uv run pytest -v
```

63 tests across 8 modules: schema, paths, rules, diff, prompt, render, agent, CLI smoke. Tests use Pydantic AI's `TestModel` for deterministic LLM stubbing.

## Architecture

Small, focused modules in `src/pr_reviewer/`:

| Module | Responsibility |
|---|---|
| `schema.py` | `Finding`, `RunMetadata`, `Report` Pydantic models |
| `diff.py` | git subprocess wrappers (`resolve_base_ref`, `extract_diff`, SHAs) |
| `rules.py` | `.ai-review/` walk-up discovery + frontmatter parsing |
| `prompt.py` | system prompt + user prompt builder |
| `render.py` | `Report` → `review-output.md` |
| `paths.py` | run dir naming + `latest.txt` pointer |
| `agent.py` | Pydantic AI agent construction |
| `cli.py` | argparse, subcommand dispatch, exit codes |

Implementation plan: `D:/ai-agents/docs/superpowers/plans/2026-05-07-agent-tool-pr-reviewer.md`.
