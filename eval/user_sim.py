"""Simulated user that answers clarification questions casually, like a real person."""
from pydantic import BaseModel

from app.llm import LLMClient


class UserReply(BaseModel):
    reply: str


SYSTEM = """You role-play a busy business user talking to a data assistant. You asked a vague question earlier and you
have a hidden intent describing what you really wanted. The assistant now asks a clarification question.

Reply in ONE short, casual sentence, the way a real person types in a chat box.
- Answer the question that was asked, in your own words; do not copy an option word for word.
- Mention extra details from your hidden intent only if they fit naturally in the same sentence.
- If none of the options match your intent, say what you actually mean.
Never mention that you are role-playing."""


class SimulatedUser:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def reply(self, case: dict, question: str, options: list[str]) -> str:
        intent = case.get("clarification_answer", "No strong preference; whatever is most standard.")
        user = (f"Your original question: {case['question']}\n"
                f"Your hidden intent: {intent}\n\n"
                f"The assistant asks: {question}\n"
                f"Options it offered: {options}")
        return self.llm.structured(SYSTEM, user, UserReply).reply