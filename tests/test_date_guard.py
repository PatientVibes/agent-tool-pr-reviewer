"""Unit tests for src/pr_reviewer/date_guard.py — two-signal AND-gated date-FP filter."""
from __future__ import annotations

import json
from datetime import date

import pytest

from pr_reviewer.date_guard import (
    DATE_GUARD_RECENT_WINDOW_DAYS,
    DateGuardDecision,
    KEYWORD_ALLOWLIST,
    is_date_fp,
    run_date_guard,
    serialize_date_guard_decisions,
)
from pr_reviewer.schema import Finding


TODAY = date(2026, 5, 14)


def _finding(*, evidence: str, description: str, severity: str = "low") -> Finding:
    return Finding(
        category="bug",
        severity=severity,
        file="src/foo.py",
        line_start=1,
        line_end=1,
        title="t",
        description=description,
        evidence=evidence,
    )


# --- Both signals fire → drop (parametrized over the 5 keyword phrases) ---

@pytest.mark.parametrize("phrase", list(KEYWORD_ALLOWLIST))
def test_both_signals_drop(phrase):
    f = _finding(
        evidence="The doc references 2026-05-09 which looks suspicious.",
        description=f"This is a {phrase} that should be corrected.",
    )
    decision = is_date_fp(f, TODAY)
    assert decision is not None
    assert decision.matched_keyword == phrase
    assert decision.matched_date == date(2026, 5, 9)


# --- Single-signal cases → keep ---

def test_date_signal_only_no_keyword():
    f = _finding(
        evidence="The 2026-05-09 release shipped successfully.",
        description="This commit hash is wrong.",
    )
    assert is_date_fp(f, TODAY) is None


def test_keyword_signal_only_no_date():
    f = _finding(
        evidence="The constant retry_limit is too small.",
        description="This is likely a typo in the constant name.",
    )
    assert is_date_fp(f, TODAY) is None


# --- Edge cases on the date signal ---

def test_date_in_future_keep():
    """Date > today → keep. Model may be correctly flagging a real future-date typo."""
    f = _finding(
        evidence="The doc references 2027-01-01 which is in the future.",
        description="This is likely a typo — 2027 is not a real date.",
    )
    assert is_date_fp(f, TODAY) is None


def test_date_too_old_keep():
    """Date < today - 730 days → keep. Ancient dates aren't in the FP risk band."""
    f = _finding(
        evidence="The 1979-01-01 epoch reference is wrong.",
        description="This looks like a future date typo.",
    )
    assert is_date_fp(f, TODAY) is None


def test_malformed_date_keep_no_crash():
    """Fail-open on parse exceptions."""
    f = _finding(
        evidence="The 2026-13-99 date is impossible.",
        description="This is a future date typo.",
    )
    assert is_date_fp(f, TODAY) is None


def test_multi_date_evidence_drop_if_any_in_window():
    """If one date is in window and signals fire, drop. (The other date being out-of-window doesn't save it.)"""
    f = _finding(
        evidence="Both 1979-01-01 and 2026-05-09 appear in this doc.",
        description="This is likely a typo for an earlier year.",
    )
    decision = is_date_fp(f, TODAY)
    assert decision is not None
    assert decision.matched_date == date(2026, 5, 9)


def test_case_insensitive_keyword():
    f = _finding(
        evidence="The doc references 2026-05-09 which is suspicious.",
        description="This is LIKELY A TYPO that should be fixed.",
    )
    decision = is_date_fp(f, TODAY)
    assert decision is not None
    assert decision.matched_keyword == "likely a typo"


def test_empty_evidence_keep():
    f = _finding(evidence=" ", description="This is a future date typo.")
    assert is_date_fp(f, TODAY) is None


def test_empty_description_keep():
    f = _finding(evidence="The 2026-05-09 date is present.", description=" ")
    assert is_date_fp(f, TODAY) is None


# --- Asymmetric evidence/description cases ---

def test_evidence_without_date_keeps_even_with_keyword():
    """The date signal is read from EVIDENCE, not the description. Evidence with
    no ISO date → the guard cannot fire, even when the description carries a
    future-date keyword. Pins that the two signals are AND-ed on the right fields.
    """
    f = _finding(
        evidence="This is a very long evidence string without any ISO date in it at all whatsoever for the test.",
        description="This is a future date typo. Date 2026-05-09 looks wrong.",
    )
    # No date in evidence → date signal fails → keep.
    assert is_date_fp(f, TODAY) is None


def test_evidence_date_plus_description_keyword_drops():
    """Mirror case: evidence has the recent ISO date and the description has the
    keyword — the drop fires."""
    f = _finding(
        evidence="The longest evidence string also happens to mention 2026-05-09 prominently.",
        description="Generic concern. This is a future date.",
    )
    decision = is_date_fp(f, TODAY)
    assert decision is not None


# --- run_date_guard partition ---

def test_run_date_guard_partitions():
    fp = _finding(
        evidence="Doc references 2026-05-09.",
        description="This is a future date typo.",
    )
    real_bug = _finding(
        evidence="x = None\nx.foo()  # AttributeError",
        description="Null dereference here.",
    )
    survivors, drops = run_date_guard([fp, real_bug], TODAY)
    assert survivors == [real_bug]
    assert len(drops) == 1
    assert drops[0].finding == fp


# --- serialize_date_guard_decisions schema check ---

def test_serialize_date_guard_decisions_schema():
    fp = _finding(
        evidence="Doc references 2026-05-09.",
        description="This is a future date typo.",
    )
    decision = is_date_fp(fp, TODAY)
    assert decision is not None
    payload_json = serialize_date_guard_decisions([decision])

    data = json.loads(payload_json)
    assert isinstance(data, list)
    assert len(data) == 1
    entry = data[0]
    assert entry["drop_reason"] == "model_knowledge_cutoff"
    assert entry["matched_keyword"] == "future date"
    assert entry["matched_date"] == "2026-05-09"
    # finding round-trips through Pydantic JSON
    assert entry["finding"]["evidence"] == fp.evidence
    assert entry["finding"]["description"] == fp.description


# --- Window constant invariant ---

def test_window_constant():
    assert DATE_GUARD_RECENT_WINDOW_DAYS == 730
