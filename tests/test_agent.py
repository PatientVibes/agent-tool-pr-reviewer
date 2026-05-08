import pytest
from pydantic_ai.models.test import TestModel

from pr_reviewer.agent import build_agent, run_review
from pr_reviewer.schema import Finding, Report, RunMetadata


def _stub_test_model(report_dict: dict) -> TestModel:
    """Build a TestModel that yields report_dict as the structured output.
    Pydantic AI has used both `custom_output_args` and `custom_result_args` for
    this kwarg across versions — try both before failing."""
    for kwarg in ("custom_output_args", "custom_result_args"):
        try:
            return TestModel(**{kwarg: report_dict})
        except TypeError:
            continue
    raise RuntimeError(
        "TestModel does not accept custom_output_args or custom_result_args. "
        "Check the installed pydantic-ai version's TestModel signature."
    )


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
