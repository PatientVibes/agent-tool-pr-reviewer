import os
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.usage import RunUsage

from pr_reviewer.schema import Report

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion

_OutputT = TypeVar("_OutputT", bound=BaseModel)


# The openai SDK pins service_tier to a Literal that doesn't include all values
# OpenRouter's proxy may return (e.g. "standard" when routing to non-OpenAI
# backends). Pydantic-ai's _process_response re-validates the openai-SDK-built
# response and raises on unknown values; we strip them first.
_ALLOWED_SERVICE_TIERS = frozenset({None, "auto", "default", "flex", "scale", "priority"})


def _coerce_service_tier(response: "ChatCompletion") -> None:
    """Drop service_tier if it's outside the openai SDK's allowed Literal.

    Mutates `response` in place. Safe no-op if the value is already None or
    one of the accepted tiers.
    """
    if response.service_tier not in _ALLOWED_SERVICE_TIERS:
        response.service_tier = None


def _tolerant_openrouter_chat_model_cls():
    """Return the OpenAIChatModel subclass that sanitizes service_tier.

    Built on first call and cached on the function object so the openai extra
    stays optional for callers that don't use openrouter:* models.
    """
    cached = getattr(_tolerant_openrouter_chat_model_cls, "_cls", None)
    if cached is not None:
        return cached
    from openai.types.chat import ChatCompletion
    from pydantic_ai.models.openai import OpenAIChatModel

    class _TolerantOpenRouterChatModel(OpenAIChatModel):
        def _process_response(self, response):
            if isinstance(response, ChatCompletion):
                _coerce_service_tier(response)
            return super()._process_response(response)

    _tolerant_openrouter_chat_model_cls._cls = _TolerantOpenRouterChatModel
    return _TolerantOpenRouterChatModel


def __getattr__(name):
    """Expose _TolerantOpenRouterChatModel as a module attribute on first access."""
    if name == "_TolerantOpenRouterChatModel":
        return _tolerant_openrouter_chat_model_cls()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
        from pydantic_ai.providers.openrouter import OpenRouterProvider
        cls = _tolerant_openrouter_chat_model_cls()
        return cls(model_name, provider=OpenRouterProvider(api_key=api_key))
    return spec  # str passthrough; Pydantic AI will parse the provider prefix


def build_agent(
    model: "KnownModelName | Model | str",
    *,
    output_type: type[_OutputT],
    system_prompt: str,
) -> Agent[None, _OutputT]:
    """Build a pydantic-ai Agent with the given model, output_type, and system_prompt.

    Both `output_type` and `system_prompt` are required (no defaults) because the
    two vary together: a `Report` output_type pairs with the reviewer's
    `prompt.SYSTEM_PROMPT`; a `VerdictBatch` output_type pairs with the verifier's
    `verifier.SYSTEM_PROMPT`. Having defaults would silently bind the wrong prompt
    to the wrong output type.
    """
    return Agent(
        model=resolve_model(model),
        output_type=output_type,
        system_prompt=system_prompt,
    )


async def run_review(agent: Agent[None, Report], user_prompt: str) -> tuple[Report, RunUsage]:
    result = await agent.run(user_prompt)
    # result.usage() is a method on AgentRunResult (pydantic-ai 0.8.x)
    return result.output, result.usage()
