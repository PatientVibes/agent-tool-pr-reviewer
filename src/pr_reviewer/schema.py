from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Severity = Literal["blocker", "high", "medium", "low"]
Category = Literal["bug", "project_rule"]


class ModelUsage(BaseModel):
    """Per-model token usage and error state in a multi-model consensus run.

    Populated once per model in the basket. `errored=True` means the model's
    agent call failed (timeout, validation, rate limit, network); `error_message`
    captures the exception's `repr()` for postmortem.
    """
    tokens_input: int
    tokens_output: int
    errored: bool = False
    error_message: str | None = None


class Finding(BaseModel):
    category: Category
    severity: Severity
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    rule_id: str | None = None
    title: str
    description: str
    evidence: str = Field(min_length=1, max_length=500)
    suggested_fix: str | None = None
    agreement_count: int | None = None
    agreed_by: list[str] | None = None

    @model_validator(mode="after")
    def _rule_id_matches_category(self) -> "Finding":
        if self.category == "project_rule" and self.rule_id is None:
            raise ValueError("project_rule findings require rule_id")
        if self.category == "bug" and self.rule_id is not None:
            raise ValueError("bug findings must not have rule_id")
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class RunMetadata(BaseModel):
    schema_version: Literal["3"] = "3"
    branch: str
    base_ref: str
    commit_head: str
    commit_base: str
    started_at: datetime
    duration_seconds: float
    model: str
    tokens_input: int
    tokens_output: int
    models: list[str] | None = None
    per_model_usage: dict[str, ModelUsage] | None = None
    verifier_model: str | None = None


class Report(BaseModel):
    metadata: RunMetadata
    rules_loaded: list[str]
    findings: list[Finding]
