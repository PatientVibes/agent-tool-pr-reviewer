"""Unit tests for pr_reviewer.compat — denylist, live-probe classification, batch aggregation."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_reviewer.compat import (
    KNOWN_INCOMPATIBLE,
    PrecheckOutcome,
    ProbeItem,
    ProbeResult,
    _classify_exception,
    _flatten_exception_message,
    precheck_and_exit_if_bad,
    precheck_model,
    precheck_models,
)


# ---------- _flatten_exception_message ----------


def test_flatten_exception_message_single():
    """A bare exception flattens to its lowercased str."""
    exc = RuntimeError("Boom")
    assert _flatten_exception_message(exc) == "boom"


def test_flatten_exception_message_walks_cause_chain():
    """exc.__cause__ chain is followed; each level's str is included in lowercased output."""
    inner = ValueError("inner: no endpoints found that support tool use")
    middle = RuntimeError("middle: pydantic-ai validation failed")
    middle.__cause__ = inner
    outer = RuntimeError("outer: agent.run failed")
    outer.__cause__ = middle

    flattened = _flatten_exception_message(outer)
    assert "outer: agent.run failed" in flattened
    assert "middle: pydantic-ai validation failed" in flattened
    assert "inner: no endpoints found that support tool use" in flattened


# ---------- _classify_exception ----------


def test_classify_no_tool_support_direct():
    """Direct exception with the OpenRouter phrasing -> NO_TOOL_SUPPORT."""
    exc = RuntimeError(
        'Status 404: {"error":{"message":"No endpoints found that support tool use."}}'
    )
    outcome, reason = _classify_exception(exc)
    assert outcome == "NO_TOOL_SUPPORT"
    assert "tool" in reason.lower() or "function" in reason.lower()


def test_classify_no_tool_support_via_cause_chain():
    """The OpenRouter error wrapped in a pydantic-ai exception still classifies
    correctly because _flatten_exception_message walks __cause__."""
    inner = RuntimeError("404 No endpoints found that support function calling")
    wrapper = RuntimeError("pydantic-ai validation failed")
    wrapper.__cause__ = inner

    outcome, _ = _classify_exception(wrapper)
    assert outcome == "NO_TOOL_SUPPORT"


def test_classify_auth_fail_401():
    """401 status -> AUTH_FAIL."""
    exc = RuntimeError("Status 401: unauthorized")
    outcome, reason = _classify_exception(exc)
    assert outcome == "AUTH_FAIL"
    assert "key" in reason.lower()


def test_classify_other_for_generic_error():
    """Anything that doesn't match the tool-use or auth patterns -> OTHER (fail-open)."""
    exc = RuntimeError("connection reset by peer")
    outcome, reason = _classify_exception(exc)
    assert outcome == "OTHER"
    assert "RuntimeError" in reason


# ---------- precheck_model ----------


@pytest.mark.asyncio
async def test_precheck_model_denylist_short_circuits(monkeypatch):
    """A model on KNOWN_INCOMPATIBLE returns DENIED without ever calling build_agent."""
    sentinel_called = []

    def _should_not_be_called(*args, **kwargs):
        sentinel_called.append(True)
        raise RuntimeError("build_agent should not have been called for a denylisted model")

    monkeypatch.setattr("pr_reviewer.compat.build_agent", _should_not_be_called)

    outcome, reason = await precheck_model("openrouter:meta-llama/llama-4-maverick")
    assert outcome == "DENIED"
    assert "KNOWN_INCOMPATIBLE" in reason or "denied" in reason.lower() or "denylist" in reason.lower()
    assert sentinel_called == []  # build_agent never invoked


@pytest.mark.asyncio
async def test_precheck_model_live_probe_ok(monkeypatch):
    """A non-denylisted model whose probe call returns a valid ProbeResult -> OK."""
    async def _fake_run(prompt):
        result = MagicMock()
        result.output = ProbeResult(items=[ProbeItem(id=1)])
        return result

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(side_effect=_fake_run)
    monkeypatch.setattr(
        "pr_reviewer.compat.build_agent",
        lambda model, *, output_type, system_prompt: fake_agent,
    )

    outcome, _ = await precheck_model("openrouter:google/gemini-2.5-pro")
    assert outcome == "OK"


@pytest.mark.asyncio
async def test_precheck_model_no_tool_support_via_exception(monkeypatch):
    """A probe call that raises with OpenRouter's tool-use error -> NO_TOOL_SUPPORT."""
    async def _fake_run(prompt):
        raise RuntimeError(
            'Status 404: {"error":{"message":"No endpoints found that support tool use."}}'
        )

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(side_effect=_fake_run)
    monkeypatch.setattr(
        "pr_reviewer.compat.build_agent",
        lambda model, *, output_type, system_prompt: fake_agent,
    )

    outcome, _ = await precheck_model("openrouter:some/new-bad-model")
    assert outcome == "NO_TOOL_SUPPORT"


@pytest.mark.asyncio
async def test_precheck_model_auth_fail(monkeypatch):
    """A probe call that raises with a 401 -> AUTH_FAIL."""
    async def _fake_run(prompt):
        raise RuntimeError("401 Unauthorized: invalid API key")

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(side_effect=_fake_run)
    monkeypatch.setattr(
        "pr_reviewer.compat.build_agent",
        lambda model, *, output_type, system_prompt: fake_agent,
    )

    outcome, _ = await precheck_model("openrouter:google/gemini-2.5-pro")
    assert outcome == "AUTH_FAIL"


@pytest.mark.asyncio
async def test_precheck_model_other_for_unmatched_exception(monkeypatch):
    """A generic exception (network blip etc.) -> OTHER (fail-open category)."""
    async def _fake_run(prompt):
        raise TimeoutError("connection timed out")

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(side_effect=_fake_run)
    monkeypatch.setattr(
        "pr_reviewer.compat.build_agent",
        lambda model, *, output_type, system_prompt: fake_agent,
    )

    outcome, _ = await precheck_model("openrouter:google/gemini-2.5-pro")
    assert outcome == "OTHER"


# ---------- precheck_models ----------


@pytest.mark.asyncio
async def test_precheck_models_aggregates_in_order(monkeypatch):
    """Batch returns a dict mapping each input spec to its (outcome, detail).
    Inputs include: one denied, one OK, one auth_fail. Insertion order preserved."""

    def _fake_build_agent(model, *, output_type, system_prompt):
        fake = MagicMock()
        async def _run(prompt):
            if model == "openrouter:will-401":
                raise RuntimeError("401 unauthorized")
            result = MagicMock()
            result.output = ProbeResult(items=[ProbeItem(id=1)])
            return result
        fake.run = AsyncMock(side_effect=_run)
        return fake

    monkeypatch.setattr("pr_reviewer.compat.build_agent", _fake_build_agent)

    specs = [
        "openrouter:meta-llama/llama-4-maverick",  # DENIED via denylist
        "openrouter:google/gemini-2.5-pro",         # OK via fake
        "openrouter:will-401",                       # AUTH_FAIL via fake
    ]
    results = await precheck_models(specs)

    # Insertion order preserved
    assert list(results.keys()) == specs
    assert results["openrouter:meta-llama/llama-4-maverick"][0] == "DENIED"
    assert results["openrouter:google/gemini-2.5-pro"][0] == "OK"
    assert results["openrouter:will-401"][0] == "AUTH_FAIL"


@pytest.mark.asyncio
async def test_precheck_models_dedups_input():
    """Duplicate input specs are de-duplicated before probing; result dict still
    contains every unique spec exactly once."""
    specs = [
        "openrouter:meta-llama/llama-4-maverick",
        "openrouter:meta-llama/llama-4-maverick",  # duplicate
    ]
    results = await precheck_models(specs)
    assert len(results) == 1
    assert results["openrouter:meta-llama/llama-4-maverick"][0] == "DENIED"


# ---------- precheck_and_exit_if_bad ----------


@pytest.mark.asyncio
async def test_precheck_and_exit_if_bad_exits_2_on_denied(monkeypatch, capsys):
    """Any DENIED in the batch -> returns 2."""
    code = await precheck_and_exit_if_bad(["openrouter:meta-llama/llama-4-maverick"])
    assert code == 2
    err = capsys.readouterr().err
    assert "[precheck]" in err
    assert "DENIED" in err


@pytest.mark.asyncio
async def test_precheck_and_exit_if_bad_returns_none_on_all_ok(monkeypatch, capsys):
    """All OK -> returns None; stderr shows one OK line per model."""
    def _fake_build_agent(model, *, output_type, system_prompt):
        fake = MagicMock()
        async def _run(prompt):
            result = MagicMock()
            result.output = ProbeResult(items=[ProbeItem(id=1)])
            return result
        fake.run = AsyncMock(side_effect=_run)
        return fake

    monkeypatch.setattr("pr_reviewer.compat.build_agent", _fake_build_agent)

    code = await precheck_and_exit_if_bad([
        "openrouter:google/gemini-2.5-pro",
        "openrouter:anthropic/claude-sonnet-4-6",
    ])
    assert code is None
    err = capsys.readouterr().err
    assert err.count("[precheck]") == 2
    assert "OK" in err


@pytest.mark.asyncio
async def test_precheck_and_exit_if_bad_warns_but_continues_on_other(monkeypatch, capsys):
    """OTHER outcome -> warn to stderr but return None (fail-open)."""
    def _fake_build_agent(model, *, output_type, system_prompt):
        fake = MagicMock()
        async def _run(prompt):
            raise TimeoutError("connection reset")
        fake.run = AsyncMock(side_effect=_run)
        return fake

    monkeypatch.setattr("pr_reviewer.compat.build_agent", _fake_build_agent)

    code = await precheck_and_exit_if_bad(["openrouter:google/gemini-2.5-pro"])
    assert code is None
    err = capsys.readouterr().err
    assert "[precheck]" in err
    assert "warning" in err.lower()
