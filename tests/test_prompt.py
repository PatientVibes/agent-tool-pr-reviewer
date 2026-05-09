from pr_reviewer.prompt import SYSTEM_PROMPT, build_user_prompt
from pr_reviewer.rules import Rule


def test_system_prompt_lists_both_categories():
    assert "bug" in SYSTEM_PROMPT
    assert "project_rule" in SYSTEM_PROMPT


def test_system_prompt_states_out_of_scope_categories():
    for excluded in ("security", "style", "formatting", "documentation", "test coverage"):
        assert excluded.lower() in SYSTEM_PROMPT.lower()


def test_system_prompt_specifies_severity_rubric():
    for s in ("blocker", "high", "medium", "low"):
        assert s in SYSTEM_PROMPT


def test_system_prompt_constrains_rule_id_per_category():
    assert "rule_id" in SYSTEM_PROMPT


def test_user_prompt_includes_diff_and_rule_bodies():
    rules = [
        Rule(rule_id="no-class-components", description="No classes.", body="prose"),
        Rule(rule_id="prefer-pure-functions", description="Prefer pure.", body="more prose"),
    ]
    diff = "diff --git a/x b/x\n+hello\n"
    out = build_user_prompt(
        diff=diff, rules=rules, branch="feature/x",
        base_ref="main", commit_head="a" * 40, commit_base="b" * 40,
    )
    assert "no-class-components" in out
    assert "prefer-pure-functions" in out
    assert "No classes." in out
    assert "prose" in out
    assert "diff --git" in out
    assert "feature/x" in out
    # short SHAs
    assert "a" * 12 in out
    assert "b" * 12 in out


def test_user_prompt_orders_rules_alphabetically():
    rules = [
        Rule(rule_id="zzz-late", description="d", body="b"),
        Rule(rule_id="aaa-early", description="d", body="b"),
    ]
    out = build_user_prompt(
        diff="d", rules=rules, branch="b", base_ref="m",
        commit_head="0"*40, commit_base="0"*40,
    )
    assert out.index("aaa-early") < out.index("zzz-late")


def test_user_prompt_handles_empty_rules():
    out = build_user_prompt(
        diff="diff", rules=[], branch="b", base_ref="main",
        commit_head="a"*40, commit_base="b"*40,
    )
    assert "diff" in out
    # No rules section content beyond the header (or the section is omitted entirely)


def test_system_prompt_excludes_external_tool_syntax():
    assert "External tool" in SYSTEM_PROMPT
    assert "invalid flag" in SYSTEM_PROMPT


def test_system_prompt_excludes_speculative_consequences():
    assert "Speculative downstream" in SYSTEM_PROMPT
    assert "extrapolation" in SYSTEM_PROMPT.lower()


def test_system_prompt_blocker_hedging_guard():
    for word in ("might", "may", "could", "potentially", "likely", "probably", "possibly"):
        assert word in SYSTEM_PROMPT


def test_system_prompt_evidence_constraint():
    assert "evidence" in SYSTEM_PROMPT
    assert "verbatim" in SYSTEM_PROMPT
    assert "paraphrase" in SYSTEM_PROMPT
