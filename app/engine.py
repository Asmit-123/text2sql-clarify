"""Orchestrator: state manager -> ambiguity detector -> SQL generator -> validator -> executor."""
import logging
import uuid
from typing import Optional

from .ambiguity import AmbiguityDetector
from .config import Settings
from .db import execute_query
from .llm import LLMClient
from .models import EngineResponse
from .schema_introspect import SchemaProvider
from .sql_generator import SQLGenerator
from .state import ConversationState, InMemoryStateStore, Phase, StateStore
from .validator import UnsafeSQLError, validate_sql

log = logging.getLogger(__name__)


class Text2SQLEngine:
    def __init__(self, settings: Optional[Settings] = None, llm: Optional[LLMClient] = None,
                 store: Optional[StateStore] = None, schema: Optional[SchemaProvider] = None,
                 enable_clarification: bool = True):
        self.settings = settings or Settings()
        self.llm = llm or LLMClient(self.settings)
        self.store = store or InMemoryStateStore(self.settings.session_ttl_seconds)
        self.schema = schema or SchemaProvider(self.settings)
        self.detector = AmbiguityDetector(self.llm)
        self.generator = SQLGenerator(self.llm)
        self.enable_clarification = enable_clarification   # False = baseline mode for evaluation

    # ------------------------------------------------------------------ public API
    def ask(self, session_id: Optional[str], message: str) -> EngineResponse:
        session_id = session_id or uuid.uuid4().hex
        state = self.store.get(session_id)
        if state and state.phase == Phase.AWAITING_CLARIFICATION:
            state.answer(message)                              # message is the reply to our question
        else:
            state = ConversationState(session_id=session_id, original_question=message)
        return self._advance(state)

    # ------------------------------------------------------------------ internals
    def _advance(self, state: ConversationState) -> EngineResponse:
        try:
            schema_ctx = self.schema.get_context()
            intent = state.resolved_intent()
            assumptions: list[str] = []

            if self.enable_clarification:
                analysis = self.detector.analyze(intent, schema_ctx)
                log.info("ambiguity: %s (%s)", analysis.is_ambiguous, analysis.reasoning)
                if analysis.is_ambiguous and state.rounds < self.settings.max_clarification_rounds:
                    state.ask(analysis.clarification_question, analysis.options)
                    self.store.save(state)
                    return EngineResponse(status="needs_clarification", session_id=state.session_id,
                                          clarification_question=analysis.clarification_question,
                                          options=analysis.options, clarification_rounds=state.rounds)
                assumptions = analysis.assumptions
                if analysis.is_ambiguous:   # round budget exhausted: proceed, but make the guess explicit
                    assumptions.append("The user did not resolve the remaining ambiguity; pick the most common interpretation.")

            response = self._generate_and_execute(state, intent, schema_ctx, assumptions)
        except Exception as exc:  # noqa: BLE001 - surface any failure as a structured response
            log.exception("engine failure")
            response = EngineResponse(status="error", session_id=state.session_id, error=f"{type(exc).__name__}: {exc}",
                                      clarification_rounds=state.rounds)
        self.store.delete(state.session_id)     # conversation turn finished (answered or failed)
        return response

    def _generate_and_execute(self, state, intent, schema_ctx, assumptions) -> EngineResponse:
        prev_sql, error = None, None
        for attempt in range(self.settings.max_sql_attempts):
            result = self.generator.generate(intent, schema_ctx, assumptions, prev_sql, error)
            try:
                validate_sql(result.sql, self.schema.tables)
                columns, rows = execute_query(self.settings, result.sql)
            except UnsafeSQLError as exc:
                prev_sql, error = result.sql, f"Rejected by safety validator: {exc}"
            except Exception as exc:  # database error -> let the model self-correct once
                prev_sql, error = result.sql, str(exc).splitlines()[0]
            else:
                return EngineResponse(status="answered", session_id=state.session_id, sql=result.sql,
                                      explanation=result.explanation, columns=columns,
                                      rows=[list(r) for r in rows], clarification_rounds=state.rounds)
            log.warning("sql attempt %d failed: %s", attempt + 1, error)
        return EngineResponse(status="error", session_id=state.session_id, sql=prev_sql, error=error,
                              clarification_rounds=state.rounds)
