# agent-tool-pr-reviewer

CLI that reviews the current branch's diff against a base ref using a single Pydantic AI call. Emits typed `findings.json` + a human-readable `review-output.md` under `<repo>/.ai-review/runs/<timestamp>/`.

Pairs with the `pr-review` skill in the `agent-skills` marketplace plugin.

## Install (dev)

```
uv tool install --editable D:/agent-tool-pr-reviewer
```

## Usage

```
agent-tool-pr-reviewer review
agent-tool-pr-reviewer rules list
```

Set `ANTHROPIC_API_KEY` (or the appropriate env var for the model passed via `--model`).

See `D:/ai-agents/docs/superpowers/specs/2026-05-07-agent-tool-pr-reviewer-design.md` for full design.
