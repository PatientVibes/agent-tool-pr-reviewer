"""Unit tests for pr_reviewer.verifier and pr_reviewer.diff.extract_changed_files.

Phase 2 of v0.5.0 lands extract_changed_files (in diff.py); the rest of this
file is filled in by Phase 3 once verifier.py exists.
"""
from __future__ import annotations

import pytest

from pr_reviewer.diff import extract_changed_files


# ---------- extract_changed_files ----------

ADDED_FILE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/foo.py
@@ -0,0 +1,3 @@
+def foo():
+    return 1
+
"""

MODIFIED_FILE_DIFF = """\
diff --git a/src/bar.py b/src/bar.py
index abc..def 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -10,3 +10,4 @@ def bar():
     x = 1
     y = 2
+    z = 3
     return x + y
"""

DELETED_FILE_DIFF = """\
diff --git a/src/baz.py b/src/baz.py
deleted file mode 100644
index abc..0000000
--- a/src/baz.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def baz():
-    return 0
-
"""

MULTIPLE_FILES_DIFF = ADDED_FILE_DIFF + "\n" + MODIFIED_FILE_DIFF + "\n" + DELETED_FILE_DIFF


def test_extract_changed_files_added():
    assert extract_changed_files(ADDED_FILE_DIFF) == {"src/foo.py"}


def test_extract_changed_files_modified():
    assert extract_changed_files(MODIFIED_FILE_DIFF) == {"src/bar.py"}


def test_extract_changed_files_deleted_ignored():
    """Deleted files have `+++ /dev/null` and should NOT appear in the set
    — the verifier only checks findings against post-change file paths."""
    assert extract_changed_files(DELETED_FILE_DIFF) == set()


def test_extract_changed_files_multiple():
    """A combined diff lists every post-change file path (added + modified)."""
    result = extract_changed_files(MULTIPLE_FILES_DIFF)
    assert result == {"src/foo.py", "src/bar.py"}
    assert "src/baz.py" not in result


# ---------- resolve_verifier_arg ----------

from pr_reviewer.verifier import (
    DEFAULT_VERIFIER_MODEL,
    resolve_verifier_arg,
)


def test_resolve_verifier_arg_none_passthrough():
    """None → None (no verifier; default behavior)."""
    assert resolve_verifier_arg(None) is None


def test_resolve_verifier_arg_default_keyword():
    """'default' (case-insensitive) expands to DEFAULT_VERIFIER_MODEL."""
    assert resolve_verifier_arg("default") == DEFAULT_VERIFIER_MODEL
    assert resolve_verifier_arg("DEFAULT") == DEFAULT_VERIFIER_MODEL
    assert resolve_verifier_arg("Default") == DEFAULT_VERIFIER_MODEL


def test_resolve_verifier_arg_explicit_passthrough():
    """Any other non-empty string returns as-is (no validation here)."""
    assert resolve_verifier_arg("openrouter:google/gemini-2.5-flash") == "openrouter:google/gemini-2.5-flash"
    assert resolve_verifier_arg("  anthropic:claude-sonnet-4-6  ") == "anthropic:claude-sonnet-4-6"


def test_resolve_verifier_arg_empty_raises():
    """Empty / whitespace-only string is rejected — argparse should not reach this
    with --verifier unless user passed '' or whitespace explicitly."""
    with pytest.raises(ValueError, match="non-empty"):
        resolve_verifier_arg("")
    with pytest.raises(ValueError, match="non-empty"):
        resolve_verifier_arg("   ")


# ---------- deterministic_check ----------

from pr_reviewer.verifier import deterministic_check
from pr_reviewer.schema import Finding


def _make_finding(
    *,
    file: str = "src/foo.py",
    evidence: str = "+    return 1",
    category: str = "bug",
    rule_id: str | None = None,
    severity: str = "high",
) -> Finding:
    """Test helper — minimum-valid Finding."""
    return Finding(
        category=category,
        severity=severity,
        file=file,
        line_start=1,
        line_end=1,
        rule_id=rule_id,
        title="t",
        description="d",
        evidence=evidence,
    )


SIMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -0,0 +1,3 @@
+def foo():
+    return 1
+
"""


def test_deterministic_check_pass():
    """File in changed set + evidence verbatim in diff -> None (passes)."""
    finding = _make_finding(file="src/foo.py", evidence="+    return 1")
    result = deterministic_check(finding, SIMPLE_DIFF, {"src/foo.py"})
    assert result is None


def test_deterministic_check_file_not_in_set():
    """File not in changed-files set -> drop with scope-drift reason."""
    finding = _make_finding(file="src/bar.py", evidence="+    return 1")
    result = deterministic_check(finding, SIMPLE_DIFF, {"src/foo.py"})
    assert result is not None
    keep, reason = result
    assert keep is False
    assert "src/bar.py" in reason
    assert "changed" in reason.lower() or "diff" in reason.lower()


def test_deterministic_check_evidence_not_in_diff():
    """Evidence quote is paraphrased (not a verbatim substring of diff) -> drop."""
    finding = _make_finding(file="src/foo.py", evidence="returns the number 1 from foo")
    result = deterministic_check(finding, SIMPLE_DIFF, {"src/foo.py"})
    assert result is not None
    keep, reason = result
    assert keep is False
    assert "verbatim" in reason.lower() or "substring" in reason.lower()


def test_deterministic_check_whitespace_padded_full_line_passes():
    """Models occasionally pad evidence with leading/trailing whitespace. The
    deterministic gate strips the evidence side (not the diff) before checking.
    `strip(evidence) == "+    return 1"` which IS a verbatim substring of the
    diff — pass."""
    finding = _make_finding(file="src/foo.py", evidence="\n+    return 1\n")
    result = deterministic_check(finding, SIMPLE_DIFF, {"src/foo.py"})
    assert result is None


def test_deterministic_check_prefix_stripped_evidence_passes_via_substring_leniency():
    """R2(b) documentation: when a model strips the diff prefix ('+', '-', ' ')
    from evidence, Python's `in` substring check is permissive enough that the
    stripped evidence is still a substring of the diff body. v0.5.0 does NOT
    treat this as a deterministic-gate failure — the LLM judge may catch it as
    SCOPE_DRIFT if the finding's content is hallucinated. The v0.5.x fallback
    (de-prefixed diff re-check) would tighten this only if real-world data
    shows the leniency is too loose."""
    finding = _make_finding(file="src/foo.py", evidence="    return 1")
    result = deterministic_check(finding, SIMPLE_DIFF, {"src/foo.py"})
    # "    return 1" (no '+') is a substring of "+    return 1" in the diff —
    # the check passes despite the prefix being stripped.
    assert result is None


# ---------- _validate_verdict_batch ----------

from pr_reviewer.verifier import _validate_verdict_batch, VerdictBatch, VerdictItem


def test_validate_verdict_batch_well_formed():
    """N verdicts indexed 0..N-1, no duplicates -> (True, '')."""
    batch = VerdictBatch(verdicts=[
        VerdictItem(finding_index=0, keep=True, reason="no_condition_fired"),
        VerdictItem(finding_index=1, keep=False, reason="SELF_WITHDRAWAL: ..."),
        VerdictItem(finding_index=2, keep=True, reason="no_condition_fired"),
    ])
    ok, reason = _validate_verdict_batch(batch, expected_count=3)
    assert ok is True
    assert reason == ""


def test_validate_verdict_batch_count_mismatch():
    """N verdicts != expected_count -> (False, reason)."""
    batch = VerdictBatch(verdicts=[
        VerdictItem(finding_index=0, keep=True, reason="ok"),
        VerdictItem(finding_index=1, keep=True, reason="ok"),
    ])
    ok, reason = _validate_verdict_batch(batch, expected_count=3)
    assert ok is False
    assert "count" in reason.lower() or "expected 3" in reason


def test_validate_verdict_batch_out_of_range_index():
    """A verdict whose finding_index >= expected_count -> (False, reason)."""
    batch = VerdictBatch(verdicts=[
        VerdictItem(finding_index=0, keep=True, reason="ok"),
        VerdictItem(finding_index=5, keep=True, reason="ok"),
    ])
    ok, reason = _validate_verdict_batch(batch, expected_count=2)
    assert ok is False
    assert "range" in reason.lower() or "index 5" in reason


def test_validate_verdict_batch_duplicate_index():
    """Two verdicts with the same finding_index -> (False, reason)."""
    batch = VerdictBatch(verdicts=[
        VerdictItem(finding_index=0, keep=True, reason="ok"),
        VerdictItem(finding_index=0, keep=False, reason="..."),
    ])
    ok, reason = _validate_verdict_batch(batch, expected_count=2)
    assert ok is False
    assert "duplicate" in reason.lower() or "0" in reason


# ---------- _build_verifier_user_prompt ----------

from pr_reviewer.verifier import _build_verifier_user_prompt


def test_build_verifier_user_prompt_includes_diff_and_findings():
    """The verifier's user prompt has two sections: '## Diff' (raw diff in a
    code fence) and '## Findings' (numbered list with severity, category,
    file:line-range, title, description, evidence)."""
    diff_text = "diff --git a/src/foo.py b/src/foo.py\n+    return 1"
    findings = [
        _make_finding(file="src/foo.py", evidence="+    return 1", severity="high"),
    ]
    prompt = _build_verifier_user_prompt(diff_text, findings)

    assert "## Diff" in prompt
    assert "```diff" in prompt
    assert "diff --git a/src/foo.py" in prompt
    assert "## Findings" in prompt
    assert "[0]" in prompt
    assert "severity=high" in prompt
    assert "src/foo.py:1-1" in prompt or "src/foo.py" in prompt
    assert "Return a VerdictBatch" in prompt or "0 through" in prompt


def test_build_verifier_user_prompt_zero_findings_still_valid():
    """An empty findings list still produces a structurally-valid prompt; the
    verifier returns an empty VerdictBatch in that case."""
    prompt = _build_verifier_user_prompt("(no diff)", [])
    assert "## Findings" in prompt
    assert "0 total findings" in prompt or "(N total" not in prompt


# ---------- run_verifier_pass: all-project_rule path ----------

from pr_reviewer.verifier import run_verifier_pass


async def test_run_verifier_pass_all_project_rule_skips_judge(monkeypatch, capsys):
    """All inputs are project_rule findings that pass the deterministic gate.

    Expected:
      - judge stage is skipped (project_rule findings don't go through the LLM judge)
      - all findings returned as kept, dropped is empty, usage is 0/0
      - build_agent is never called (proof the judge stage was actually skipped,
        not just keep-all by coincidence)
      - the '[verifier] judge: skipped (0 bug-category survivors; ...)' line emits
    """
    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "build_agent must not be called when all survivors are project_rule"
        )
    monkeypatch.setattr("pr_reviewer.verifier.build_agent", _fail_if_called)

    findings = [
        _make_finding(
            file="src/foo.py", evidence="+def foo():",
            category="project_rule", rule_id="prefer-pure-functions",
        ),
        _make_finding(
            file="src/foo.py", evidence="+    return 1",
            category="project_rule", rule_id="explicit-return",
        ),
    ]

    kept, dropped, usage = await run_verifier_pass(
        verifier_model="never-called",
        diff_text=SIMPLE_DIFF,
        kept_findings=findings,
        budget=100000,
    )

    assert kept == findings
    assert dropped == []
    assert usage.tokens_input == 0
    assert usage.tokens_output == 0
    err = capsys.readouterr().err
    assert "[verifier] judge: skipped" in err
    assert "0 bug-category survivors" in err
