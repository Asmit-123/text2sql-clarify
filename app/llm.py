"""Provider-agnostic structured-output client.

OpenAI, Groq and Gemini all expose OpenAI-compatible chat endpoints, so one client covers them.
Native "parse" helpers differ per provider, so we use JSON mode + Pydantic validation + a repair loop,
which behaves the same everywhere.
"""
import json
import logging
import re
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=6)

    def structured(self, system: str, user: str, model_cls: type[T], max_repairs: int = 2) -> T:
        schema = json.dumps(model_cls.model_json_schema())
        messages = [
            {"role": "system", "content": f"{system}\n\nReturn ONLY one JSON object valid against this JSON Schema "
                                           f"(no prose, no markdown):\n{schema}"},
            {"role": "user", "content": user},
        ]
        last_error = ""
        for attempt in range(max_repairs + 1):
            resp = self.client.chat.completions.create(
                model=self.settings.model, messages=messages, temperature=0,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            try:
                return model_cls.model_validate_json(_strip_fences(raw))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                log.warning("structured output invalid (attempt %d): %s", attempt + 1, last_error[:300])
                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"That JSON failed validation:\n{last_error}\nReturn corrected JSON only."},
                ]
        raise StructuredOutputError(f"{model_cls.__name__} failed validation after retries: {last_error[:300]}")


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text
