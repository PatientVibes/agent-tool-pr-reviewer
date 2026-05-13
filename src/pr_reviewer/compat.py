"""Tool-use compatibility precheck — Layer 0 in the precision stack.

Some OpenRouter model IDs get routed to provider backends that do not support
function/tool calling. Pydantic-AI's structured-output (output_type=...) requires
tools, so those routings fail with `404 — "No endpoints found that support tool
use."` mid-Agent.run. This module catches that failure class BEFORE the reviewer
dispatch loop burns a real call.

Hybrid mechanism:
  1. Static `KNOWN_INCOMPATIBLE` denylist — zero tokens for the curated bad IDs.
  2. Live probe via `Agent.run("ping")` with `output_type=ProbeResult` — catches
     newly-discovered bad routings without code changes.

Default ON; --skip-precheck opts out. Fail-open on ambiguous probe errors.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Literal

from pydantic import BaseModel

from pr_reviewer.agent import build_agent


KNOWN_INCOMPATIBLE: frozenset[str] = frozenset({
    "openrouter:meta-llama/llama-4-maverick",
    "openrouter:deepseek/deepseek-r1-distill-qwen-32b",
})
"""Static denylist of model specs that have been observed routing to backends
without function/tool calling support. Grows over time as new bad routings are
discovered. Match is case-sensitive and exact on the full model spec."""


PrecheckOutcome = Literal["OK", "DENIED", "NO_TOOL_SUPPORT", "AUTH_FAIL", "OTHER"]


class ProbeItem(BaseModel):
    """One nested element inside ProbeResult. Exists so the probe exercises
    `list[BaseModel]` (the same shape Report.findings has — a list of nested
    pydantic models). Some OpenRouter routings handle flat outputs but trip on
    nested-list outputs; a flat probe shape would yield false-OKs against them."""
    id: int


class ProbeResult(BaseModel):
    """Output_type for the live probe. The nested list-of-pydantic shape mirrors
    Report's structure so the probe classifies models the same way the real
    reviewer call would."""
    items: list[ProbeItem]


_PROBE_SYSTEM_PROMPT = """\
You are a tool-use compatibility probe. Respond with a ProbeResult whose
`items` list contains exactly one ProbeItem with id=1. Do not perform any
reasoning or analysis. This call exists solely to confirm the model supports
structured tool-call output with a nested list-of-pydantic shape."""


_NO_TOOL_SUPPORT_REQUIRED = "no endpoints"
"""Substring required for NO_TOOL_SUPPORT classification. Matched against the
case-folded flattened exception message."""

_NO_TOOL_SUPPORT_ANY_OF: tuple[str, ...] = ("tool", "function")
"""At least one of these substrings must also appear for NO_TOOL_SUPPORT."""

_AUTH_PATTERNS: tuple[str, ...] = (
    "401",
    "unauthorized",
    "invalid api key",
    "api key is not set",
)
"""Substrings that classify a probe failure as AUTH_FAIL. Matched against the
case-folded flattened exception message."""


def _flatten_exception_message(exc: BaseException) -> str:
    """Walk the exc.__cause__ and exc.__context__ chain, concatenating every
    level's str(exc) into one lowercase string.

    Used by pattern matching so wrapped exceptions (pydantic-ai wrapping httpx
    wrapping the OpenRouter response, for example) still expose the original
    error text to the substring checks.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return " ".join(parts).lower()


def _classify_exception(exc: BaseException) -> tuple[PrecheckOutcome, str]:
    """Map a probe-call exception to a (PrecheckOutcome, reason_text) tuple.

    Order of checks:
      1. NO_TOOL_SUPPORT: "no endpoints" + ("tool" OR "function") in flattened msg
      2. AUTH_FAIL: any of the auth substrings in flattened msg
      3. OTHER: anything else (fail-open)
    """
    flattened = _flatten_exception_message(exc)
    if _NO_TOOL_SUPPORT_REQUIRED in flattened and any(
        s in flattened for s in _NO_TOOL_SUPPORT_ANY_OF
    ):
        return (
            "NO_TOOL_SUPPORT",
            'OpenRouter returned an error indicating no backend on this model\'s '
            'provider routing supports function/tool calls. The model exists '
            'but cannot satisfy pydantic-ai structured-output. Pick a different model.',
        )
    if any(p in flattened for p in _AUTH_PATTERNS):
        return (
            "AUTH_FAIL",
            "OPENROUTER_API_KEY is invalid, expired, or unset. Check the key and retry.",
        )
    return (
        "OTHER",
        f"probe error ({type(exc).__name__}: {exc})",
    )


async def precheck_model(model_spec: str) -> tuple[PrecheckOutcome, str]:
    """Run the tool-use compatibility precheck for a single resolved model spec.

    Algorithm:
      1. If model_spec in KNOWN_INCOMPATIBLE -> ("DENIED", reason) WITHOUT calling build_agent.
      2. Otherwise, build a probe Agent with output_type=ProbeResult and call Agent.run("ping").
      3. On success (result.output is a valid ProbeResult) -> ("OK", "").
      4. On exception, classify via _classify_exception (walks __cause__ chain).

    Returns (outcome, detail_text). detail_text is human-readable, suitable for stderr.
    """
    if model_spec in KNOWN_INCOMPATIBLE:
        return (
            "DENIED",
            "listed in KNOWN_INCOMPATIBLE — OpenRouter routes this model to "
            "backends without tool-call support. Pick a different model or "
            "a different provider.",
        )

    try:
        agent = build_agent(
            model_spec,
            output_type=ProbeResult,
            system_prompt=_PROBE_SYSTEM_PROMPT,
        )
        result = await agent.run("ping")
        output = result.output
    except Exception as exc:
        return _classify_exception(exc)

    if not isinstance(output, ProbeResult):
        return (
            "OTHER",
            f"probe returned unexpected output type {type(output).__name__}",
        )
    if not output.items:
        return (
            "OTHER",
            "probe returned an empty ProbeResult.items list",
        )
    return ("OK", "")


async def precheck_models(
    model_specs: list[str],
) -> dict[str, tuple[PrecheckOutcome, str]]:
    """Precheck N models in parallel via asyncio.gather.

    Args:
      model_specs: ordered list. Duplicates are de-duplicated before probing
                   to avoid wasted probe calls.

    Returns:
      dict mapping each unique input spec to its (outcome, detail). Insertion
      order is preserved across the de-dup so stderr printing is deterministic.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for spec in model_specs:
        if spec not in seen:
            seen.add(spec)
            unique.append(spec)

    results = await asyncio.gather(*(precheck_model(spec) for spec in unique))
    return dict(zip(unique, results))


async def precheck_and_exit_if_bad(
    model_specs: list[str],
) -> int | None:
    """CLI integration helper. Calls precheck_models, prints one stderr line
    per result, returns 2 if ANY result is DENIED / NO_TOOL_SUPPORT / AUTH_FAIL,
    otherwise None.

    OTHER outcomes trigger a stderr warning line but do NOT cause exit 2
    (fail-open policy; matches v0.5.0 verifier).
    """
    results = await precheck_models(model_specs)

    bad_outcomes = ("DENIED", "NO_TOOL_SUPPORT", "AUTH_FAIL")
    any_bad = False
    for spec, (outcome, detail) in results.items():
        if outcome == "OK":
            print(f"[precheck] {spec} OK", file=sys.stderr)
        elif outcome == "OTHER":
            print(
                f"[precheck] warning: could not probe {spec} ({detail}); "
                f"continuing without precheck",
                file=sys.stderr,
            )
        else:
            print(
                f"[precheck] {spec} {outcome}: {detail}",
                file=sys.stderr,
            )
            if outcome in bad_outcomes:
                any_bad = True

    return 2 if any_bad else None
