"""FixProposal doubles as both the return type this module exposes and the
JSON schema handed to Gemini's response_schema param — the SDK converts a
Pydantic BaseModel into a JSON schema automatically, so the model's raw
output and this class stay guaranteed in sync.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FixProposal(BaseModel):
    root_cause: str = Field(description="One or two sentences on what actually caused the failure.")
    confidence: Literal["low", "medium", "high"] = Field(
        description="How confident the model is in this root cause given the evidence provided."
    )
    reasoning: str = Field(
        description="What signals led to this conclusion — cite the specific reason code, log line, or config value observed."
    )
    recommended_change_summary: str = Field(
        description="Plain-English description of the fix, e.g. 'increase memory limit from 50Mi to 200Mi'."
    )
    proposed_yaml_patch: str = Field(
        description="A minimal YAML snippet showing only the fields that should change, not a full manifest."
    )
    risk_notes: str = Field(
        description="Anything a human reviewer should double check before merging this — tradeoffs, assumptions, or what happens if the root cause guess is wrong."
    )