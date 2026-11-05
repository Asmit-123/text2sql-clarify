"""All structured-output contracts live here. Every LLM call is validated against one of these."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class AmbiguityType(str, Enum):
    NONE = "none"
    VAGUE_METRIC = "vague_metric"          # "best", "top", "active", "underperforming"
    VAGUE_TIME = "vague_time"              # "recent", "lately"
    UNKNOWN_TERM = "unknown_term"          # business term with no schema counterpart ("region")
    VAGUE_THRESHOLD = "vague_threshold"    # "big", "low"
    MISSING_SCOPE = "missing_scope"        # which rows count (cancelled orders? returned?)


class AmbiguityAnalysis(BaseModel):
    reasoning: str = Field(description="1-3 sentences: could multiple materially different SQL queries answer this?")
    is_ambiguous: bool
    ambiguity_type: AmbiguityType = AmbiguityType.NONE
    clarification_question: Optional[str] = Field(default=None, description="ONE short closed question. Required if ambiguous.")
    options: list[str] = Field(default_factory=list, description="2-4 concrete answers grounded in the schema. Required if ambiguous.")
    assumptions: list[str] = Field(default_factory=list, description="Minor defaults you will assume if NOT ambiguous.")
    
    @field_validator("options", "assumptions", mode="before")
    @classmethod
    def _null_to_empty_list(cls, v):
        return [] if v is None else v

    @field_validator("ambiguity_type", mode="before")
    @classmethod
    def _null_to_none_type(cls, v):
        return AmbiguityType.NONE if v is None else v

    @model_validator(mode="after")
    def _consistency(self) -> "AmbiguityAnalysis":
        if self.is_ambiguous:
            if not self.clarification_question:
                raise ValueError("clarification_question is required when is_ambiguous is true")
            if len(self.options) < 2:
                raise ValueError("provide 2-4 options when is_ambiguous is true")
            self.options = self.options[:4]
        else:
            self.clarification_question, self.options = None, []
            self.ambiguity_type = AmbiguityType.NONE
        return self


class SQLResult(BaseModel):
    sql: str = Field(description="A single read-only PostgreSQL SELECT statement.")
    explanation: str = Field(description="At most two sentences explaining what the query does and any assumption made.")
    tables_used: list[str] = Field(default_factory=list)

    @field_validator("sql")
    @classmethod
    def _clean_sql(cls, v: str) -> str:
        v = v.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip().rstrip(";").strip()
        if not v:
            raise ValueError("sql must not be empty")
        return v


class EngineResponse(BaseModel):
    status: Literal["needs_clarification", "answered", "error"]
    session_id: str
    clarification_question: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    sql: Optional[str] = None
    explanation: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    error: Optional[str] = None
    clarification_rounds: int = 0
