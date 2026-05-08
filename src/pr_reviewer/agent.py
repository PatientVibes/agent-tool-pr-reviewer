from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model

from pr_reviewer.prompt import SYSTEM_PROMPT
from pr_reviewer.schema import Report


def build_agent(model: "KnownModelName | Model | str") -> Agent[None, Report]:
    return Agent(
        model=model,
        output_type=Report,
        system_prompt=SYSTEM_PROMPT,
    )


async def run_review(agent: Agent[None, Report], user_prompt: str) -> tuple[Report, Any]:
    result = await agent.run(user_prompt)
    # result.usage() is a method on AgentRunResult (pydantic-ai 0.8.x)
    return result.output, result.usage()
