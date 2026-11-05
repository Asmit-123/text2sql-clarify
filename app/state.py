"""Conversational state manager.

The state is a plain Pydantic model, so it is trivially serialisable (swap InMemoryStateStore for a Redis/Postgres
store implementing the same 3 methods when you go multi-process).
"""
import threading
import time
from enum import Enum
from typing import Optional, Protocol

from pydantic import BaseModel, Field


class Phase(str, Enum):
    AWAITING_CLARIFICATION = "awaiting_clarification"
    RESOLVING = "resolving"


class Exchange(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    answer: Optional[str] = None


class ConversationState(BaseModel):
    session_id: str
    original_question: str
    phase: Phase = Phase.RESOLVING
    exchanges: list[Exchange] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)

    @property
    def rounds(self) -> int:
        return len(self.exchanges)

    def ask(self, question: str, options: list[str]) -> None:
        self.exchanges.append(Exchange(question=question, options=options))
        self.phase = Phase.AWAITING_CLARIFICATION
        self.updated_at = time.time()

    def answer(self, text: str) -> None:
        self.exchanges[-1].answer = text
        self.phase = Phase.RESOLVING
        self.updated_at = time.time()

    def resolved_intent(self) -> str:
        """Original question + every clarification Q/A, as one authoritative block for downstream prompts."""
        parts = [f"User question: {self.original_question}"]
        answered = [e for e in self.exchanges if e.answer]
        if answered:
            parts.append("Clarifications (authoritative, provided by the user):")
            parts += [f"- Q: {e.question}\n  A: {e.answer}" for e in answered]
        return "\n".join(parts)


class StateStore(Protocol):
    def get(self, session_id: str) -> Optional[ConversationState]: ...
    def save(self, state: ConversationState) -> None: ...
    def delete(self, session_id: str) -> None: ...


class InMemoryStateStore:
    def __init__(self, ttl_seconds: int = 1800):
        self._data: dict[str, ConversationState] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get(self, session_id: str) -> Optional[ConversationState]:
        with self._lock:
            st = self._data.get(session_id)
            if st and time.time() - st.updated_at > self._ttl:
                del self._data[session_id]
                return None
            return st

    def save(self, state: ConversationState) -> None:
        with self._lock:
            self._data[state.session_id] = state

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)
