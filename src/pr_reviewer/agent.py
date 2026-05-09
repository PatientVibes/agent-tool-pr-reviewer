import os

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.usage import RunUsage

from pr_reviewer.prompt import SYSTEM_PROMPT
from pr_reviewer.schema import Report


class ModelResolutionError(RuntimeError):
    """Could not turn a CLI model string into a usable Pydantic AI model."""


def resolve_model(spec: "str | Model") -> "KnownModelName | Model":
    """Translate a CLI `--model` value into something Agent() accepts.

    Pydantic AI native strings like `anthropic:claude-sonnet-4-6` pass through
    untouched. The `openrouter:<model>` prefix is special-cased: we wrap an
    OpenAIChatModel with the OpenRouterProvider so a single `OPENROUTER_API_KEY`
    can route to any model OpenRouter supports (Anthropic, OpenAI, Google, etc.).
    """
    if not isinstance(spec, str):
        return spec
    if spec.startswith("openrouter:"):
        model_name = spec.split(":", 1)[1]
        if not model_name:
            raise ModelResolutionError(
                "openrouter: prefix requires a model name "
                "(e.g. openrouter:anthropic/claude-sonnet-4)"
            )
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ModelResolutionError(
                "OPENROUTER_API_KEY is not set. Export it before using an "
                "openrouter: model."
            )
        # Imports are deferred so users without the openai extra installed
        # only hit the import error if they actually request openrouter.
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider
        return OpenAIChatModel(model_name, provider=OpenRouterProvider(api_key=api_key))
    return spec  # str passthrough; Pydantic AI will parse the provider prefix


def build_agent(model: "KnownModelName | Model | str") -> Agent[None, Report]:
    return Agent(
        model=resolve_model(model),
        output_type=Report,
        system_prompt=SYSTEM_PROMPT,
    )


async def run_review(agent: Agent[None, Report], user_prompt: str) -> tuple[Report, RunUsage]:
    result = await agent.run(user_prompt)
    # result.usage() is a method on AgentRunResult (pydantic-ai 0.8.x)
    return result.output, result.usage()
