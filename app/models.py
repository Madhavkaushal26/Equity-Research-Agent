"""Stable public request and structured research response contracts."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CatalystItem(StrictModel):
    title: str
    impact_summary: str
    metric_or_evidence: str
    source_id: int


class SourceCitation(StrictModel):
    doc_id: int
    ticker: str
    doc_type: str
    filed_at: str
    source_url: str
    excerpt: str


class ResearchBrief(StrictModel):
    query_intent: str
    executive_summary: str
    bull_catalysts: list[CatalystItem]
    bear_risks: list[CatalystItem]
    cited_sources: list[SourceCitation]
    confidence_score: float = Field(ge=0.0, le=1.0)


class ChatRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=20000)
    ticker_filter: Optional[str] = Field(default=None, min_length=1, max_length=16)

    @field_validator("session_id", "message", "ticker_filter")
    @classmethod
    def reject_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value


class ChatResponse(StrictModel):
    session_id: str
    brief: ResearchBrief
    user_profile: dict
