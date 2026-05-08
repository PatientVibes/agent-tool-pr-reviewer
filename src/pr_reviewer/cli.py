from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pr_reviewer import __version__
from pr_reviewer.agent import build_agent, run_review
from pr_reviewer.diff import (
    BaseRefError, current_branch, extract_diff, head_sha, merge_base, resolve_base_ref,
)
from pr_reviewer.paths import prepare_run_dir, write_latest_pointer
from pr_reviewer.prompt import build_user_prompt
from pr_reviewer.render import render_markdown
from pr_reviewer.rules import find_rules_dir, load_rules
from pr_reviewer.schema import Report, RunMetadata


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-tool-pr-reviewer")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Review HEAD vs base ref")
    review.add_argument("--base", default=None)
    review.add_argument("--budget", type=int, default=80000)
    review.add_argument("--rules-dir", type=Path, default=None)
    review.add_argument("--out", type=Path, default=None)
    review.add_argument("--model", default="anthropic:claude-sonnet-4-6")

    rules = sub.add_parser("rules", help="Rules subcommands")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_sub.add_parser("list", help="List discovered rules")

    return p


def _estimate_tokens(text: str) -> int:
    """Rough heuristic: ~4 chars per token. Replaceable with tiktoken later."""
    return max(1, len(text) // 4)


async def run_review_command(
    *, base: str | None, budget: int, rules_dir: Path | None, out: Path | None,
    model: Any,
) -> int:
    repo = Path.cwd()
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    try:
        base_ref = resolve_base_ref(repo, explicit=base)
    except BaseRefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rules_path = rules_dir or find_rules_dir(repo)
    try:
        rules = load_rules(rules_path) if rules_path else []
    except ValueError as exc:
        print(f"error: malformed rule frontmatter: {exc}", file=sys.stderr)
        return 2

    diff = extract_diff(repo, base=base_ref)
    head, mb = head_sha(repo), merge_base(repo, base_ref)
    branch = current_branch(repo)

    user_prompt = build_user_prompt(
        diff=diff, rules=rules, branch=branch, base_ref=base_ref,
        commit_head=head, commit_base=mb,
    )

    if _estimate_tokens(user_prompt) > budget:
        print(
            f"error: prompt exceeds --budget {budget} tokens. "
            "Split the PR or pass a higher --budget.",
            file=sys.stderr,
        )
        return 2

    agent = build_agent(model)
    report, usage = await run_review(agent, user_prompt)

    duration = time.perf_counter() - t0
    metadata = RunMetadata(
        branch=branch, base_ref=base_ref,
        commit_head=head, commit_base=mb,
        started_at=started_at, duration_seconds=duration,
        model=str(model) if not isinstance(model, str) else model,
        tokens_input=getattr(usage, "input_tokens", 0) or 0,
        tokens_output=getattr(usage, "output_tokens", 0) or 0,
    )
    # rules_loaded is determined deterministically from disk, NOT trusted from
    # the LLM. The model may hallucinate rule_ids; the CLI is the source of
    # truth for what rules were actually available during the run.
    sealed_report = Report(
        metadata=metadata,
        rules_loaded=[r.rule_id for r in rules],
        findings=report.findings,
    )

    run_dir = prepare_run_dir(repo_root=repo, started_at=started_at, override=out)
    (run_dir / "findings.json").write_text(
        sealed_report.model_dump_json(indent=2), encoding="utf-8",
    )
    (run_dir / "review-output.md").write_text(
        render_markdown(sealed_report), encoding="utf-8",
    )
    if out is None:
        write_latest_pointer(run_dir.parent, run_dir)

    print(str(run_dir))
    return 1 if any(f.severity == "blocker" for f in sealed_report.findings) else 0


def run_rules_list_command() -> int:
    repo = Path.cwd()
    rules_path = find_rules_dir(repo)
    if not rules_path:
        print("no .ai-review/ found", file=sys.stderr)
        return 2
    for rule in load_rules(rules_path):
        print(f"{rule.rule_id}\t{rule.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "review":
        return asyncio.run(run_review_command(
            base=args.base, budget=args.budget, rules_dir=args.rules_dir,
            out=args.out, model=args.model,
        ))
    if args.command == "rules" and args.rules_command == "list":
        return run_rules_list_command()
    return 2


if __name__ == "__main__":
    sys.exit(main())
