"""Deterministic match-and-merge over per-model Reports for multi-model consensus.

Two-stage matching: file + line-range overlap (hard key), then title 3-gram
Jaccard >= 0.3 OR evidence substring containment (soft confirm). project_rule
findings get a special relaxed match on (file, rule_id) regardless of line.

Pure Python over the existing pydantic Finding / Report schema. No network, no
LLM, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pr_reviewer.schema import (
    Category, Finding, ModelUsage, Report, RunMetadata, Severity,
)


DEFAULT_BASKET: tuple[str, ...] = (
    "openrouter:google/gemini-2.5-pro",
    "openrouter:moonshotai/kimi-k2.6",
    "openrouter:deepseek/deepseek-chat-v3.1",
)

JACCARD_THRESHOLD = 0.3
MAX_MERGED_DESCRIPTION_CHARS = 1500


@dataclass
class PerModelResult:
    """One model's outcome from the parallel dispatch.

    On success: report and usage are set; error_message is None.
    On failure: report is None; usage may be None; error_message is the
    exception's repr().
    """
    model: str
    report: Report | None
    tokens_input: int
    tokens_output: int
    error_message: str | None


def resolve_models_arg(s: str) -> list[str]:
    """Expand a --models argument into an ordered list of model strings.

    Accepts a comma-separated list. The literal 'default' (case-insensitive)
    expands to DEFAULT_BASKET. Mixed 'default,<other>' is rejected for v0.4.0
    (YAGNI; the basket is curated). Whitespace around commas is stripped.

    Raises ValueError on empty input or empty post-split entries.
    """
    if not s or not s.strip():
        raise ValueError("--models requires a non-empty value")
    parts = [p.strip() for p in s.split(",")]
    if any(p == "" for p in parts):
        raise ValueError("--models has an empty entry (check for trailing comma)")
    lower = [p.lower() for p in parts]
    has_default = "default" in lower
    if has_default and len(parts) > 1:
        raise ValueError(
            "--models 'default' cannot be mixed with explicit models in v0.4.0; "
            "list models explicitly or use 'default' alone"
        )
    if has_default:
        return list(DEFAULT_BASKET)
    return parts


def _three_grams(s: str) -> set[str]:
    """Lowercased character 3-grams of `s`. Returns empty set for len(s) < 3."""
    s = s.lower()
    if len(s) < 3:
        return set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _jaccard_3gram(a: str, b: str) -> float:
    """Jaccard similarity over lowercased character 3-grams.

    Returns 0.0 if both strings are too short to produce 3-grams. Returns 1.0
    if both produce identical non-empty grams.
    """
    ga = _three_grams(a)
    gb = _three_grams(b)
    if not ga or not gb:
        return 0.0
    intersect = ga & gb
    union = ga | gb
    return len(intersect) / len(union)


def _evidence_overlap(e1: str, e2: str) -> bool:
    """True iff one evidence string is a (stripped) substring of the other."""
    s1 = e1.strip()
    s2 = e2.strip()
    if not s1 or not s2:
        return False
    return s1 in s2 or s2 in s1


def _line_ranges_overlap(a: Finding, b: Finding) -> bool:
    """True iff [a.line_start, a.line_end] and [b.line_start, b.line_end] share >= 1 line."""
    return a.line_start <= b.line_end and b.line_start <= a.line_end


def _findings_match(a: Finding, b: Finding) -> bool:
    """Decide whether two findings describe the same underlying issue.

    Algorithm:
      1. Different files -> no match.
      2. project_rule special case: same (file, rule_id) -> match regardless of line.
      3. Bugs: line ranges must overlap by >= 1 line AND either title Jaccard
         >= 0.3 OR evidence substring containment.
    """
    if a.file != b.file:
        return False
    if a.category == "project_rule" and b.category == "project_rule":
        if a.rule_id is not None and a.rule_id == b.rule_id:
            return True
        return False
    if a.category != b.category:
        return False
    if not _line_ranges_overlap(a, b):
        return False
    if _jaccard_3gram(a.title, b.title) >= JACCARD_THRESHOLD:
        return True
    if _evidence_overlap(a.evidence, b.evidence):
        return True
    return False


_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "blocker")


def _max_severity(severities: Iterable[Severity]) -> Severity:
    return max(severities, key=lambda s: _SEVERITY_ORDER.index(s))


def _category_bug_wins(categories: Iterable[Category]) -> Category:
    return "bug" if "bug" in categories else "project_rule"


def _merge_group(group: list[tuple[str, Finding]]) -> Finding:
    """Collapse a cluster of (model_name, finding) tuples into one Finding.

    Merge policy (per spec):
      - severity: max of the cluster
      - category: bug wins over project_rule
      - title: longest title (proxy for most-specific)
      - description: concatenated, "[<model>]: <desc>" per source, separated by " \\n\\n"; truncated at MAX_MERGED_DESCRIPTION_CHARS
      - evidence: longest verbatim quote in the cluster
      - suggested_fix: concatenated like description; None if all None
      - rule_id: first non-None rule_id (project_rule groups should all agree)
      - agreement_count = len(cluster); agreed_by = sorted model names
    """
    findings = [f for _m, f in group]
    severity = _max_severity(f.severity for f in findings)
    category = _category_bug_wins(f.category for f in findings)
    longest_title = max(findings, key=lambda f: len(f.title)).title
    longest_evidence = max(findings, key=lambda f: len(f.evidence)).evidence
    desc_parts = [f"[{m}]: {f.description}" for m, f in group]
    merged_desc = "\n\n".join(desc_parts)
    if len(merged_desc) > MAX_MERGED_DESCRIPTION_CHARS:
        merged_desc = merged_desc[:MAX_MERGED_DESCRIPTION_CHARS - len("...(truncated)")] + "...(truncated)"
    fix_parts = [f"[{m}]: {f.suggested_fix}" for m, f in group if f.suggested_fix]
    merged_fix = "\n\n".join(fix_parts) if fix_parts else None
    rule_id = next((f.rule_id for f in findings if f.rule_id is not None), None)
    canonical = findings[0]
    return Finding(
        category=category,
        severity=severity,
        file=canonical.file,
        line_start=canonical.line_start,
        line_end=canonical.line_end,
        rule_id=rule_id,
        title=longest_title,
        description=merged_desc,
        evidence=longest_evidence[:500],
        suggested_fix=merged_fix,
        agreement_count=len(group),
        agreed_by=sorted(m for m, _ in group),
    )


def _cluster_findings(
    all_findings: list[tuple[str, Finding]],
) -> list[list[tuple[str, Finding]]]:
    """Greedy union-find clustering: each finding joins the first compatible cluster.

    Deterministic order: input is pre-sorted by (file, line_start, line_end, model_name)
    BEFORE this is called. Match decision uses _findings_match.
    """
    clusters: list[list[tuple[str, Finding]]] = []
    for item in all_findings:
        _m, f = item
        joined = False
        for cluster in clusters:
            if any(_findings_match(f, existing) for _, existing in cluster):
                cluster.append(item)
                joined = True
                break
        if not joined:
            clusters.append([item])
    return clusters


def merge_reports(
    per_model: list[PerModelResult],
    consensus_threshold: int,
) -> tuple[Report, list[Finding]]:
    """Merge N per-model results into one consensus Report.

    Args:
      per_model: ordered list; the list order is preserved in metadata.models.
      consensus_threshold: minimum cluster size to be kept in merged.findings.

    Returns:
      (merged_report, uncorroborated_findings). uncorroborated is the list of
      below-threshold merged findings (one Finding per below-threshold cluster).

    Raises:
      RuntimeError if zero models succeeded.
    """
    succeeded = [r for r in per_model if r.report is not None]
    if not succeeded:
        raise RuntimeError(
            f"all {len(per_model)} model(s) failed: "
            + "; ".join(f"{r.model}={r.error_message}" for r in per_model)
        )

    flat: list[tuple[str, Finding]] = []
    for r in succeeded:
        for f in r.report.findings:
            flat.append((r.model, f))
    flat.sort(key=lambda item: (item[1].file, item[1].line_start, item[1].line_end, item[0]))

    clusters = _cluster_findings(flat)
    above_threshold: list[Finding] = []
    below_threshold: list[Finding] = []
    for cluster in clusters:
        unique_models = {m for m, _ in cluster}
        merged = _merge_group(cluster)
        if len(unique_models) >= consensus_threshold:
            above_threshold.append(merged)
        else:
            below_threshold.append(merged)

    template = succeeded[0].report.metadata
    per_model_usage = {
        r.model: ModelUsage(
            tokens_input=r.tokens_input,
            tokens_output=r.tokens_output,
            errored=(r.report is None),
            error_message=r.error_message,
        )
        for r in per_model
    }
    total_in = sum(r.tokens_input for r in per_model)
    total_out = sum(r.tokens_output for r in per_model)
    models_in_order = [r.model for r in per_model]
    merged_metadata = RunMetadata(
        branch=template.branch,
        base_ref=template.base_ref,
        commit_head=template.commit_head,
        commit_base=template.commit_base,
        started_at=template.started_at,
        duration_seconds=template.duration_seconds,
        model=",".join(models_in_order),
        tokens_input=total_in,
        tokens_output=total_out,
        models=models_in_order,
        per_model_usage=per_model_usage,
    )

    rules_loaded = sorted({r for sr in succeeded for r in sr.report.rules_loaded})

    merged_report = Report(
        metadata=merged_metadata,
        rules_loaded=rules_loaded,
        findings=above_threshold,
    )
    return merged_report, below_threshold
