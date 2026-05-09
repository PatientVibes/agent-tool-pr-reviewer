import pytest
from pydantic_ai.models.test import TestModel

from pr_reviewer.agent import ModelResolutionError, build_agent, resolve_model, run_review
from pr_reviewer.schema import Finding, Report, RunMetadata


def _stub_test_model(report_dict: dict) -> TestModel:
    """Build a TestModel that yields report_dict as the structured output.

    Pydantic AI 0.8.x uses `custom_output_args`. Older versions used
    `custom_result_args`. We pin to the current name; if a future version
    renames again, the TypeError surfaces clearly at the call site rather
    than being silently masked by a fallback loop.
    """
    return TestModel(custom_output_args=report_dict)


@pytest.mark.asyncio
async def test_run_review_returns_report_with_test_model():
    test_model = _stub_test_model({
        "metadata": {
            "branch": "feature/x", "base_ref": "main",
            "commit_head": "a" * 40, "commit_base": "b" * 40,
            "started_at": "2026-05-07T14:32:19+00:00",
            "duration_seconds": 0.0,
            "model": "test", "tokens_input": 0, "tokens_output": 0,
        },
        "rules_loaded": [],
        "findings": [],
    })
    agent = build_agent(model=test_model)
    report, usage = await run_review(agent, user_prompt="diff goes here")
    assert isinstance(report, Report)
    assert report.findings == []


class TestResolveModel:
    def test_passthrough_for_native_provider_string(self):
        assert resolve_model("anthropic:claude-sonnet-4-6") == "anthropic:claude-sonnet-4-6"

    def test_passthrough_for_model_instance(self):
        m = TestModel()
        assert resolve_model(m) is m

    def test_openrouter_without_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ModelResolutionError, match="OPENROUTER_API_KEY"):
            resolve_model("openrouter:anthropic/claude-sonnet-4")

    def test_openrouter_with_empty_model_raises(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        with pytest.raises(ModelResolutionError, match="requires a model name"):
            resolve_model("openrouter:")

    def test_openrouter_with_api_key_returns_openai_chat_model(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        from pydantic_ai.models.openai import OpenAIChatModel
        result = resolve_model("openrouter:anthropic/claude-sonnet-4")
        assert isinstance(result, OpenAIChatModel)
