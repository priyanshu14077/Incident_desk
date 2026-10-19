"""Structured outputs the agents must produce. Report is added in M2."""

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["log_analyst", "metrics_analyst", "change_auditor"]


class Evidence(BaseModel):
    source: str = Field(description="File the evidence came from, e.g. changes.json")
    ts: str = Field(description="Time of the evidence, HH:MM:SS")
    detail: str = Field(description="What the record shows, quoted or summarised")


class Finding(BaseModel):
    """One specialist's contribution to the evidence board (FR-4)."""

    agent: AgentName
    summary: str
    evidence: list[Evidence] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
