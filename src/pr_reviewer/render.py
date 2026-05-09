from pr_reviewer.schema import Finding, Report, Severity


_SEVERITY_ORDER: tuple[Severity, ...] = ("blocker", "high", "medium", "low")
_SEVERITY_HEADERS = {"blocker": "Blocker", "high": "High", "medium": "Medium", "low": "Low"}


def render_markdown(report: Report) -> str:
    md = report.metadata
    head_short, base_short = md.commit_head[:12], md.commit_base[:12]
    started = md.started_at.isoformat()
    duration = f"{md.duration_seconds:.2f}s"

    lines: list[str] = []
    lines.append(f"# PR Review — {md.branch} vs {md.base_ref}")
    lines.append("")
    lines.append(f"**Commit:** `{head_short}` (HEAD) ← `{base_short}` ({md.base_ref})")
    lines.append(f"**Generated:** {started} · **Model:** {md.model} · **Duration:** {duration}")
    lines.append("")

    if not report.findings:
        lines.append("_No findings._")
        lines.append("")
        lines.append("---")
        lines.append("")
    else:
        lines.append("## Summary")
        lines.append("")
        lines.append("| Severity | Bugs | Rule violations | Total |")
        lines.append("|---|---|---|---|")
        for sev in _SEVERITY_ORDER:
            bugs = sum(1 for f in report.findings if f.severity == sev and f.category == "bug")
            rules = sum(1 for f in report.findings if f.severity == sev and f.category == "project_rule")
            label = sev.ljust(7)
            lines.append(f"| {label} | {bugs} | {rules} | {bugs + rules} |")
        lines.append("")
        if report.rules_loaded:
            rules_inline = ", ".join(f"`{r}`" for r in report.rules_loaded)
            lines.append(f"Rules loaded: {rules_inline}")
            lines.append("")
        for sev in _SEVERITY_ORDER:
            bucket = [f for f in report.findings if f.severity == sev]
            if not bucket:
                continue
            lines.append(f"## {_SEVERITY_HEADERS[sev]}")
            lines.append("")
            for f in bucket:
                lines.extend(_render_finding(f))
        # The last _render_finding leaves a trailing "---", "" that serves as the
        # separator before the footer — so we do NOT emit another "---" here.

    lines.append(f"_Tokens: in={md.tokens_input}, out={md.tokens_output}_")
    lines.append("")
    return "\n".join(lines)


def _render_finding(f: Finding) -> list[str]:
    out: list[str] = []
    out.append(f"### `{f.file}:{f.line_start}-{f.line_end}` — {f.title}")
    out.append("")
    out.append("**Evidence:**")
    out.append("")
    out.append("````diff")
    out.extend(f.evidence.splitlines() or [f.evidence])
    out.append("````")
    out.append("")
    if f.category == "project_rule":
        out.append(f"**Category:** project_rule (`{f.rule_id}`)")
    else:
        out.append("**Category:** bug")
    out.append("")
    out.append(f.description.strip())
    out.append("")
    if f.suggested_fix:
        out.append("**Suggested fix:**")
        out.append("")
        for line in f.suggested_fix.splitlines() or [f.suggested_fix]:
            out.append(f"> {line}")
        out.append("")
    out.append("---")
    out.append("")
    return out
