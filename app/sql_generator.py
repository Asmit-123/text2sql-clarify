"""Layer 3: generate SQL under a strict Pydantic contract."""
from typing import Optional

from .llm import LLMClient
from .models import SQLResult

SYSTEM = """You are an expert PostgreSQL analyst. Translate the request into ONE read-only SELECT statement.

Rules:
- Use only the tables and columns in the schema. Qualify columns with table aliases when joining.
- Treat clarifications and listed assumptions as binding requirements.
- If something is still underspecified, choose the single most common-sense interpretation and state it in `explanation`.
- Apply a LIMIT only when the request asks for top-N / a count of rows. Do not invent LIMITs otherwise.
- Use ROUND(x::numeric, 2) only if the request mentions rounding. Never modify data. No semicolons, no comments."""


class SQLGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def generate(self, intent: str, schema_context: str, assumptions: Optional[list[str]] = None,
                 previous_sql: Optional[str] = None, error: Optional[str] = None) -> SQLResult:
        user = f"DATABASE SCHEMA:\n{schema_context}\n\nREQUEST:\n{intent}"
        if assumptions:
            user += "\n\nASSUMPTIONS TO APPLY:\n" + "\n".join(f"- {a}" for a in assumptions)
        if previous_sql and error:
            user += f"\n\nYour previous attempt failed.\nSQL: {previous_sql}\nError: {error}\nFix it."
        return self.llm.structured(SYSTEM, user, SQLResult)
