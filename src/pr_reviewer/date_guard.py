"""Deterministic post-LLM filter that drops "future date / typo" model false positives.

Pipeline position: between the model's report (after the Layer-2 scope filter)
and the verifier. Drops are final; the verifier never re-evaluates a
guard-dropped finding.

Detection: two-signal AND gate.
  1. evidence contains an ISO-8601 date in (today - 730 days, today)
  2. description (case-insensitive) contains a phrase from KEYWORD_ALLOWLIST

Both required → drop. Either alone → keep. Fail-open on any parse exception.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from pr_reviewer.schema import Finding


DATE_GUARD_RECENT_WINDOW_DAYS = 730
"""How far back from today the FP risk band extends. ~2 years covers the
training-cutoff lag for current frontier models. Ancient dates (pre-1979 etc.)
pass through untouched."""

KEYWORD_ALLOWLIST: tuple[str, ...] = (
    "future date",
    "future-date",
    "date in the future",
    "likely a typo",
    "appears to be a typo",
)
"""Empirical phrases observed in May 2026 date-FP corpus. Case-insensitive
substring match against finding.description. Tuned to avoid false-firing on
non-date 'should be N' bug findings (deliberately omits 'should be 20')."""

ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
"""Match ISO-8601 dates in evidence; lookarounds prevent partial matches on
longer numeric sequences (e.g. version strings like 1234-56-78-90)."""


@dataclass
class DateGuardDecision:
    """One sidecar entry per dropped finding."""
    finding: Finding
    matched_keyword: str
    matched_date: date


def is_date_fp(finding: Finding, today: date) -> DateGuardDecision | None:
    """Return a DateGuardDecision if BOTH signals fire, else None (keep).

    Fail-open: any exception during date parsing returns None and logs to stderr.
    """
    description_lower = finding.description.lower()
    matched_keyword: str | None = None
    for phrase in KEYWORD_ALLOWLIST:
        if phrase in description_lower:
            matched_keyword = phrase
            break
    if matched_keyword is None:
        return None

    cutoff = today - timedelta(days=DATE_GUARD_RECENT_WINDOW_DAYS)
    matched_date: date | None = None
    for m in ISO_DATE_RE.finditer(finding.evidence):
        try:
            parsed = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            # malformed date (month 13, day 99, etc.); fail-open
            continue
        if cutoff < parsed < today:
            matched_date = parsed
            break
    if matched_date is None:
        return None

    return DateGuardDecision(
        finding=finding,
        matched_keyword=matched_keyword,
        matched_date=matched_date,
    )


def run_date_guard(
    findings: list[Finding],
    today: date | None = None,
) -> tuple[list[Finding], list[DateGuardDecision]]:
    """Partition findings into (survivors, drops). Default today=date.today()."""
    if today is None:
        today = date.today()
    survivors: list[Finding] = []
    drops: list[DateGuardDecision] = []
    for f in findings:
        try:
            decision = is_date_fp(f, today)
        except Exception as exc:
            print(f"[date_guard] warning: unexpected exception on finding: {exc!r}", file=sys.stderr)
            survivors.append(f)
            continue
        if decision is None:
            survivors.append(f)
        else:
            drops.append(decision)
    return survivors, drops


def serialize_date_guard_decisions(decisions: list[DateGuardDecision]) -> str:
    """Render a DateGuardDecision list as the dropped-by-date-guard.json payload.

    Returns a JSON string ready to write to disk. Used by cli.py to write
    <run_dir>/dropped-by-date-guard.json. Mirrors verifier.serialize_decisions.
    """
    payload = [
        {
            "finding": d.finding.model_dump(mode="json"),
            "drop_reason": "model_knowledge_cutoff",
            "matched_keyword": d.matched_keyword,
            "matched_date": d.matched_date.isoformat(),
        }
        for d in decisions
    ]
    return json.dumps(payload, indent=2)
