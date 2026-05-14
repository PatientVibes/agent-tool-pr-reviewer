"""Verifier pass — Layer 3 precision filter on top of consensus + scope filter.

Two-stage pipeline:

1. Deterministic gate (zero-token): drop findings whose `evidence` is not a
   verbatim substring of the diff text, or whose `file` is not in the diff's
   changed-files set. Pure-Python; no LLM call.

2. LLM judge (one batched call): on `bug` category survivors, invoke the
   verifier Agent with a numbered list of findings and the diff. Returns a
   VerdictBatch with `{keep, reason}` per finding. Drop findings where
   `keep=False`. `project_rule` findings skip this stage and pass through.

Drop-only verdicts in v0.5.0. Fail-open behavior on any LLM error: keep all
survivors, log the error to stderr, set `RunMetadata.verifier_model` to record
the attempted model.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from pr_reviewer.agent import build_agent
from pr_reviewer.schema import Category, Finding


DEFAULT_VERIFIER_MODEL = "openrouter:anthropic/claude-sonnet-4-6"
"""Sugar resolved by --verifier default. Cross-family from the Gemini-led
consensus basket (bias resistance). Same OPENROUTER_API_KEY as the reviewer."""


class VerdictItem(BaseModel):
    """One per surviving bug-category finding, indexed by position in the verifier's user prompt."""
    finding_index: int = Field(ge=0)
    keep: bool
    reason: str = Field(min_length=1, max_length=300)


class VerdictBatch(BaseModel):
    """The verifier Agent's output_type. The verifier returns exactly N
    VerdictItems for N input findings, indexed 0 through N-1."""
    verdicts: list[VerdictItem]


@dataclass
class VerifierDecision:
    """Sidecar entry for one dropped finding. Serialized to dropped-by-verifier.json."""
    finding: Finding
    drop_reason: str
    drop_stage: Literal["deterministic", "judge"]


@dataclass
class VerifierUsage:
    """Token usage from the (single) LLM judge call. Zero when judge skipped or errored."""
    tokens_input: int
    tokens_output: int


SYSTEM_PROMPT = """\
You are a verifier for code-review findings emitted by another LLM. The user provides N findings and the unified diff those findings reference. Your job is to decide, per finding, whether to keep it or drop it.

# Default behavior

Default to keep=True. Drops require exactly one of the three conditions below to fire. Each `reason` field must be one short sentence (max 300 chars) naming the condition and citing what triggered it. If the finding is clean, set keep=True with reason="no_condition_fired".

# Drop conditions

1. SELF_WITHDRAWAL — the description contains language that contradicts or cancels the finding. Examples: "this annotation is withdrawn", "actually no issue here", "on reflection this is fine", "never mind", "disregard this", "scratch that", "ignore this finding". The reviewer's own reasoning negated the finding mid-text.

2. SPECULATION_AT_HIGH_OR_BLOCKER — severity is exactly "high" or "blocker" AND the description hedges the consequence with words like "might", "may", "could", "would", "potentially", "likely", "probably", or "possibly". At "medium" or "low" severity, hedged consequences are acceptable; at "high" or "blocker", the consequence must be stated concretely. Do NOT fire this condition for medium or low severity findings.

3. SCOPE_DRIFT — the finding describes code that is not present in the diff. The diff is ground truth. If you cannot point to a `+`-prefixed line, a `-`-prefixed line, or a context line in the diff that the finding's description refers to, the finding is hallucinated and must be dropped. A finding whose `file` is in the diff but whose `description` references functions/blocks not visible in the diff slice is also SCOPE_DRIFT.

# Output contract

Return a VerdictBatch with one VerdictItem per finding, in input order, keyed by `finding_index` (0 through N-1). Every input finding must have exactly one verdict; do not skip any. Do not invent verdicts for findings beyond the supplied list.
"""


def resolve_verifier_arg(s: str | None) -> str | None:
    """Resolve the --verifier CLI argument.

    - None -> None (no verifier)
    - 'default' (case-insensitive) -> DEFAULT_VERIFIER_MODEL
    - Empty / whitespace-only -> ValueError
    - Anything else -> the stripped string (passthrough to pydantic-ai)
    """
    if s is None:
        return None
    stripped = s.strip()
    if not stripped:
        raise ValueError("--verifier requires a non-empty value")
    if stripped.lower() == "default":
        return DEFAULT_VERIFIER_MODEL
    return stripped


def deterministic_check(
    finding: Finding,
    diff_text: str,
    changed_files: set[str],
) -> tuple[bool, str] | None:
    """Run the two zero-token deterministic checks on a single finding.

    Returns:
      - None if the finding passes both checks (will go to the LLM judge if bug,
        or pass through if project_rule).
      - (False, reason) if the finding should be dropped.

    Order:
      1. `finding.file` in `changed_files` (extracted from `+++ b/<path>` lines).
         Catches file paths the model invented or references outside the diff.
      2. `finding.evidence.strip()` is a substring of `diff_text`.
         Catches paraphrased / prefix-stripped quotes. The strip is one-sided
         (evidence only, NOT diff) — handles benign leading/trailing whitespace
         padding without weakening the verbatim guarantee against the diff body.
    """
    if finding.file not in changed_files:
        return (
            False,
            f"file '{finding.file}' not in diff's changed-files set "
            f"(deterministic gate: SCOPE_DRIFT precursor)",
        )
    evidence = finding.evidence.strip()
    if evidence not in diff_text:
        return (
            False,
            "evidence quote is not a verbatim substring of the diff "
            "(deterministic gate: evidence-mismatch precursor)",
        )
    return None


def _validate_verdict_batch(
    batch: VerdictBatch, expected_count: int,
) -> tuple[bool, str]:
    """Validate the verifier's batch shape against the survivor count.

    Returns (True, '') on pass; (False, reason) on any structural problem:
      - len(batch.verdicts) != expected_count
      - any finding_index < 0 or >= expected_count
      - duplicate finding_index across verdicts

    Caller fails open (keeps all survivors) when this returns False.
    """
    n = len(batch.verdicts)
    if n != expected_count:
        return (False, f"verdict count mismatch: got {n}, expected {expected_count}")
    seen: set[int] = set()
    for v in batch.verdicts:
        if v.finding_index < 0 or v.finding_index >= expected_count:
            return (False, f"verdict finding_index {v.finding_index} out of range [0, {expected_count})")
        if v.finding_index in seen:
            return (False, f"duplicate verdict finding_index {v.finding_index}")
        seen.add(v.finding_index)
    return (True, "")


def _build_verifier_user_prompt(diff_text: str, findings: list[Finding]) -> str:
    """Assemble the verifier's user prompt: diff in a code fence, then a numbered
    list of findings the verifier must judge.

    Caller must filter to bug-category findings before calling — project_rule
    findings skip the LLM judge entirely in v0.5.0.
    """
    parts: list[str] = []
    parts.append("## Diff\n")
    parts.append("```diff")
    parts.append(diff_text.rstrip())
    parts.append("```\n")
    parts.append("## Findings\n")
    if not findings:
        parts.append("(0 total findings)")
    else:
        for i, f in enumerate(findings):
            parts.append(
                f"[{i}] severity={f.severity} | {f.category} | "
                f"{f.file}:{f.line_start}-{f.line_end}"
            )
            parts.append(f"    title: {f.title}")
            parts.append(f"    description: {f.description}")
            parts.append(f"    evidence: {f.evidence}")
            parts.append("")
        parts.append(f"({len(findings)} total findings)")
    parts.append("")
    parts.append(
        f"Return a VerdictBatch with one VerdictItem per finding, "
        f"indexed 0 through {len(findings) - 1 if findings else 0}."
    )
    return "\n".join(parts)


async def run_verifier_pass(
    *,
    verifier_model: str,
    diff_text: str,
    kept_findings: list[Finding],
    budget: int,
) -> tuple[list[Finding], list[VerifierDecision], VerifierUsage]:
    """Apply the verifier's two stages to kept_findings.

    Args:
      verifier_model: the resolved model spec (passed through resolve_verifier_arg).
      diff_text: the same diff the reviewer saw (post Layer-2 scope filter).
      kept_findings: findings that survived consensus + Layer-2 filter.
      budget: same --budget ceiling as the reviewer; verifier prompt is checked
              against it before the LLM call.

    Returns:
      (post_verifier_kept, dropped_with_reasons, usage).

    Behavior:
      - Stage 3a (deterministic): run deterministic_check on every finding.
        Drops go to `dropped_with_reasons` with drop_stage="deterministic".
      - Stage 3b (LLM judge): on bug-category survivors, build the verifier
        Agent and make one batched LLM call. Drops go to `dropped_with_reasons`
        with drop_stage="judge". `project_rule` survivors pass through Stage 3b
        unchanged (deterministic gate already applied).
      - On any judge-stage exception (timeout, validation error, malformed
        batch), the function fails open: all stage-3a survivors are kept,
        the exception is logged to stderr, usage tokens are 0 (or the partial
        token count if the call returned before raising).
    """
    from pr_reviewer.diff import extract_changed_files

    changed_files = extract_changed_files(diff_text)

    # Stage 3a: deterministic
    stage_a_kept: list[Finding] = []
    dropped: list[VerifierDecision] = []
    for f in kept_findings:
        check_result = deterministic_check(f, diff_text, changed_files)
        if check_result is None:
            stage_a_kept.append(f)
        else:
            _keep, reason = check_result
            dropped.append(VerifierDecision(
                finding=f, drop_reason=reason, drop_stage="deterministic",
            ))

    print(
        f"[verifier] deterministic gate: {len(kept_findings)} findings in, "
        f"{len(stage_a_kept)} survived ({len(dropped)} dropped: deterministic)",
        file=sys.stderr,
    )

    # Stage 3b: LLM judge — only on bug-category survivors
    bug_survivors = [f for f in stage_a_kept if f.category == "bug"]
    rule_survivors = [f for f in stage_a_kept if f.category == "project_rule"]

    if not bug_survivors:
        print(
            f"[verifier] judge: skipped (0 bug-category survivors; "
            f"project_rule findings pass through)",
            file=sys.stderr,
        )
        return (stage_a_kept, dropped, VerifierUsage(tokens_input=0, tokens_output=0))

    user_prompt = _build_verifier_user_prompt(diff_text, bug_survivors)
    # Crude budget check — same heuristic as cli.py:_estimate_tokens
    if max(1, len(user_prompt) // 4) > budget:
        print(
            f"[verifier] errored: verifier prompt exceeds --budget {budget} tokens; "
            f"kept all {len(stage_a_kept)} findings without verification",
            file=sys.stderr,
        )
        return (stage_a_kept, dropped, VerifierUsage(tokens_input=0, tokens_output=0))

    # Build the verifier agent + run judge
    try:
        agent = build_agent(
            verifier_model,
            output_type=VerdictBatch,
            system_prompt=SYSTEM_PROMPT,
        )
        result = await agent.run(user_prompt)
        batch: VerdictBatch = result.output
        usage_obj = result.usage()
        tokens_in = getattr(usage_obj, "input_tokens", 0) or 0
        tokens_out = getattr(usage_obj, "output_tokens", 0) or 0
    except Exception as exc:
        print(
            f"[verifier] errored: {type(exc).__name__}: {exc}; "
            f"kept all {len(stage_a_kept)} findings without verification",
            file=sys.stderr,
        )
        return (stage_a_kept, dropped, VerifierUsage(tokens_input=0, tokens_output=0))

    print(
        f"[verifier] judge complete: {tokens_in} in / {tokens_out} out",
        file=sys.stderr,
    )

    # Validate batch shape
    ok, reason = _validate_verdict_batch(batch, expected_count=len(bug_survivors))
    if not ok:
        print(
            f"[verifier] errored: malformed VerdictBatch: {reason}; "
            f"kept all {len(stage_a_kept)} findings without verification",
            file=sys.stderr,
        )
        return (
            stage_a_kept, dropped,
            VerifierUsage(tokens_input=tokens_in, tokens_output=tokens_out),
        )

    # Apply verdicts to bug_survivors
    index_to_verdict = {v.finding_index: v for v in batch.verdicts}
    stage_b_kept_bugs: list[Finding] = []
    n_self_withdrawal = 0
    n_speculation = 0
    n_scope_drift = 0
    n_other = 0
    for i, f in enumerate(bug_survivors):
        v = index_to_verdict[i]
        if v.keep:
            stage_b_kept_bugs.append(f)
        else:
            dropped.append(VerifierDecision(
                finding=f, drop_reason=v.reason, drop_stage="judge",
            ))
            up = v.reason.upper()
            if "SELF_WITHDRAWAL" in up:
                n_self_withdrawal += 1
            elif "SPECULATION" in up:
                n_speculation += 1
            elif "SCOPE_DRIFT" in up:
                n_scope_drift += 1
            else:
                n_other += 1

    final_kept = stage_b_kept_bugs + rule_survivors
    n_judge_in = len(bug_survivors)
    n_judge_dropped = n_judge_in - len(stage_b_kept_bugs)
    print(
        f"[verifier] judge: {n_judge_in} in, {len(stage_b_kept_bugs)} kept, "
        f"{n_judge_dropped} dropped "
        f"({n_self_withdrawal} SELF_WITHDRAWAL, "
        f"{n_speculation} SPECULATION_AT_HIGH_OR_BLOCKER, "
        f"{n_scope_drift} SCOPE_DRIFT"
        + (f", {n_other} other" if n_other else "") + ")",
        file=sys.stderr,
    )

    return (final_kept, dropped, VerifierUsage(tokens_input=tokens_in, tokens_output=tokens_out))


def serialize_decisions(decisions: list[VerifierDecision]) -> str:
    """Render a VerifierDecision list as the dropped-by-verifier.json payload.

    Returns a JSON string ready to write to disk. Used by cli.py's
    _apply_verifier_pass helper.
    """
    return json.dumps(
        [
            {
                "finding": d.finding.model_dump(),
                "drop_reason": d.drop_reason,
                "drop_stage": d.drop_stage,
            }
            for d in decisions
        ],
        indent=2,
        default=str,
    )
