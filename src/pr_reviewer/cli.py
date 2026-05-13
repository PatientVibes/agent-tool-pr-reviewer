from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pathspec

from pr_reviewer import __version__
from pr_reviewer.agent import build_agent, run_review
from pr_reviewer.consensus import (
    DEFAULT_BASKET, PerModelResult, merge_reports, resolve_models_arg,
)
from pr_reviewer.diff import (
    BaseRefError, current_branch, extract_diff, filter_diff, head_sha, merge_base,
    resolve_base_ref,
)
from pr_reviewer.paths import prepare_run_dir, write_latest_pointer
from pr_reviewer.prompt import SYSTEM_PROMPT, build_user_prompt
from pr_reviewer.render import render_markdown
from pr_reviewer.rules import find_rules_dir, load_rules
from pr_reviewer.schema import Report, RunMetadata


PER_MODEL_TIMEOUT_SECONDS = 1800  # 30 minutes — Kimi observed 22 min worst case in trials


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-tool-pr-reviewer")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Review HEAD vs base ref")
    review.add_argument("--base", default=None)
    review.add_argument("--budget", type=int, default=80000)
    review.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help=(
            "Exclude files matching GLOB from review (gitignore-style syntax). "
            "Repeatable: --exclude '*.lock' --exclude 'vendored/**'. "
            "Additive to patterns in <repo>/.pr-review-ignore if present."
        ),
    )
    review.add_argument("--rules-dir", type=Path, default=None)
    review.add_argument("--out", type=Path, default=None)
    review.add_argument("--model", default=None)
    review.add_argument(
        "--models",
        default=None,
        metavar="LIST",
        help=(
            "Comma-separated list of model strings for multi-model consensus mode. "
            "The literal 'default' expands to the curated 3-model basket. "
            "Mutually exclusive with --model."
        ),
    )
    review.add_argument(
        "--consensus",
        type=int,
        default=2,
        metavar="N",
        help=(
            "Minimum number of models that must flag a finding for it to survive. "
            "Default 2 (majority for the default 3-model basket)."
        ),
    )
    review.add_argument(
        "--include-uncorroborated",
        action="store_true",
        default=False,
        help=(
            "Write below-threshold findings to <run-dir>/uncorroborated.json "
            "alongside findings.json. Default off (precision play)."
        ),
    )

    rules = sub.add_parser("rules", help="Rules subcommands")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_sub.add_parser("list", help="List discovered rules")

    return p


def _estimate_tokens(text: str) -> int:
    """Rough heuristic: ~4 chars per token. Replaceable with tiktoken later."""
    return max(1, len(text) // 4)


def _load_exclude_spec(repo: Path, cli_excludes: list[str]) -> pathspec.PathSpec:
    """Build a combined PathSpec from .pr-review-ignore (repo root) + --exclude CLI args."""
    patterns: list[str] = []
    ignore_file = repo / ".pr-review-ignore"
    if ignore_file.exists():
        patterns.extend(
            line for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    patterns.extend(cli_excludes)
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


# ----- Single-model path (unchanged behavior) -----

async def run_review_command(
    *, base: str | None, budget: int, rules_dir: Path | None, out: Path | None,
    model: Any, exclude: list[str] | None = None,
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
    exclude_spec = _load_exclude_spec(repo, list(exclude or []))
    diff, excluded_paths = filter_diff(diff, exclude_spec)
    if excluded_paths:
        print(
            f"Filtered {len(excluded_paths)} file(s) from diff: "
            f"{', '.join(excluded_paths)}",
            file=sys.stderr,
        )
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

    agent = build_agent(model, output_type=Report, system_prompt=SYSTEM_PROMPT)
    report, usage = await run_review(agent, user_prompt)

    # Layer-2 finding filter: defense-in-depth against a model that returns
    # findings for paths we asked it to ignore (e.g. context-aware findings
    # that reference an excluded path's content).
    kept_findings = []
    for finding in report.findings:
        if exclude_spec.match_file(finding.file):
            print(
                f"Dropped finding for excluded path: {finding.file}",
                file=sys.stderr,
            )
        else:
            kept_findings.append(finding)

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
        findings=kept_findings,
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


# ----- Multi-model path (NEW) -----

async def _dispatch_one_model(
    model_spec: str, user_prompt: str,
) -> PerModelResult:
    """Run one model end-to-end with a 30-min timeout; capture exception on failure.

    asyncio.wait_for wraps the agent call so a hung model doesn't block the
    gather. TimeoutError is captured into PerModelResult.error_message like
    any other exception — partial-failure handling drops the model from
    consensus but the run continues.
    """
    try:
        agent = build_agent(model_spec, output_type=Report, system_prompt=SYSTEM_PROMPT)
        report, usage = await asyncio.wait_for(
            run_review(agent, user_prompt),
            timeout=PER_MODEL_TIMEOUT_SECONDS,
        )
        return PerModelResult(
            model=model_spec,
            report=report,
            tokens_input=getattr(usage, "input_tokens", 0) or 0,
            tokens_output=getattr(usage, "output_tokens", 0) or 0,
            error_message=None,
        )
    except asyncio.TimeoutError:
        return PerModelResult(
            model=model_spec, report=None,
            tokens_input=0, tokens_output=0,
            error_message=f"TimeoutError: exceeded {PER_MODEL_TIMEOUT_SECONDS}s per-model cap",
        )
    except Exception as exc:
        return PerModelResult(
            model=model_spec, report=None,
            tokens_input=0, tokens_output=0,
            error_message=f"{type(exc).__name__}: {exc}",
        )


async def run_multi_model_review_command(
    *, base: str | None, budget: int, rules_dir: Path | None, out: Path | None,
    models: list[str], consensus_threshold: int, include_uncorroborated: bool,
    exclude: list[str] | None = None,
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
    exclude_spec = _load_exclude_spec(repo, list(exclude or []))
    diff, excluded_paths = filter_diff(diff, exclude_spec)
    if excluded_paths:
        # Print ONCE — the filter runs before per-model dispatch.
        print(
            f"Filtered {len(excluded_paths)} file(s) from diff: "
            f"{', '.join(excluded_paths)}",
            file=sys.stderr,
        )
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

    # Dispatch
    n = len(models)
    for i, m in enumerate(models, start=1):
        print(f"[consensus] starting {m} ({i}/{n})", file=sys.stderr)

    tasks = [
        asyncio.create_task(_dispatch_one_model(m, user_prompt), name=m)
        for m in models
    ]
    per_model_results = await asyncio.gather(*tasks)

    for r in per_model_results:
        if r.report is not None:
            print(
                f"[consensus] {r.model} complete: "
                f"{r.tokens_input} in / {r.tokens_output} out",
                file=sys.stderr,
            )
        else:
            print(
                f"[consensus] {r.model} errored: {r.error_message}",
                file=sys.stderr,
            )

    # Merge
    try:
        merged_report, uncorroborated = merge_reports(per_model_results, consensus_threshold)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Layer-2 finding filter post-merge (defense-in-depth)
    kept_findings = []
    for finding in merged_report.findings:
        if exclude_spec.match_file(finding.file):
            print(f"Dropped finding for excluded path: {finding.file}", file=sys.stderr)
        else:
            kept_findings.append(finding)

    # Override metadata with run-level values
    duration = time.perf_counter() - t0
    merged_metadata = merged_report.metadata.model_copy(update={
        "branch": branch, "base_ref": base_ref,
        "commit_head": head, "commit_base": mb,
        "started_at": started_at, "duration_seconds": duration,
    })
    sealed_report = Report(
        metadata=merged_metadata,
        rules_loaded=[r.rule_id for r in rules],
        findings=kept_findings,
    )

    # Stderr summary
    n_succ = sum(1 for r in per_model_results if r.report is not None)
    print("", file=sys.stderr)
    print(
        f"Multi-model consensus ({n_succ}/{n} succeeded, threshold >= {consensus_threshold}):",
        file=sys.stderr,
    )
    width = max(len(r.model) for r in per_model_results) if per_model_results else 0
    for r in per_model_results:
        if r.report is not None:
            print(
                f"  {r.model:<{width}}    {r.tokens_input} in / {r.tokens_output} out",
                file=sys.stderr,
            )
        else:
            print(
                f"  {r.model:<{width}}    ERRORED: {r.error_message}",
                file=sys.stderr,
            )
    n_keep = len(sealed_report.findings)
    n_drop = len(uncorroborated)
    print(
        f"\nConvergence: {n_keep} findings kept; {n_drop} uncorroborated"
        + (" dropped." if not include_uncorroborated else " written to uncorroborated.json."),
        file=sys.stderr,
    )

    # Write outputs
    run_dir = prepare_run_dir(repo_root=repo, started_at=started_at, override=out)
    (run_dir / "findings.json").write_text(
        sealed_report.model_dump_json(indent=2), encoding="utf-8",
    )
    (run_dir / "review-output.md").write_text(
        render_markdown(sealed_report), encoding="utf-8",
    )
    if include_uncorroborated:
        (run_dir / "uncorroborated.json").write_text(
            json.dumps([f.model_dump() for f in uncorroborated], indent=2, default=str),
            encoding="utf-8",
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
        # Mutex check
        if args.model is not None and args.models is not None:
            print(
                "error: --model and --models are mutually exclusive",
                file=sys.stderr,
            )
            return 2
        if args.models is not None:
            try:
                resolved_models = resolve_models_arg(args.models)
            except ValueError as exc:
                print(f"error: --models: {exc}", file=sys.stderr)
                return 2
            return asyncio.run(run_multi_model_review_command(
                base=args.base, budget=args.budget, rules_dir=args.rules_dir,
                out=args.out, models=resolved_models,
                consensus_threshold=args.consensus,
                include_uncorroborated=args.include_uncorroborated,
                exclude=args.exclude,
            ))
        # Single-model path (default if neither flag): use the existing default
        single_model = args.model or "openrouter:google/gemini-2.5-pro"
        return asyncio.run(run_review_command(
            base=args.base, budget=args.budget, rules_dir=args.rules_dir,
            out=args.out, model=single_model, exclude=args.exclude,
        ))
    if args.command == "rules" and args.rules_command == "list":
        return run_rules_list_command()
    return 2


if __name__ == "__main__":
    sys.exit(main())
