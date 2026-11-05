import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# provider -> (base_url, api-key env var, default model). Model names change often: override with LLM_MODEL.
PROVIDERS = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.0-flash"),
}


@dataclass
class Settings:
    provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "groq").lower())
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shop"))
    max_clarification_rounds: int = 2
    max_sql_attempts: int = 2          # generation -> execution error -> self-correct
    row_limit: int = 100
    statement_timeout_ms: int = 5000
    session_ttl_seconds: int = 1800

    @property
    def base_url(self) -> str:
        return PROVIDERS[self.provider][0]

    @property
    def api_key(self) -> str:
        key = os.getenv(PROVIDERS[self.provider][1], "")
        if not key:
            raise RuntimeError(f"Set {PROVIDERS[self.provider][1]} for provider '{self.provider}'")
        return key

    @property
    def model(self) -> str:
        return os.getenv("LLM_MODEL") or PROVIDERS[self.provider][2]
