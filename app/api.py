"""HTTP surface:  uvicorn app.api:app --reload
POST /ask {"session_id": "abc", "message": "show me the best customers"}  ->  EngineResponse
If status == needs_clarification, POST again with the SAME session_id and the user's answer."""
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from .engine import Text2SQLEngine
from .models import EngineResponse

app = FastAPI(title="Text-to-SQL with Clarification Engine")
engine = Text2SQLEngine()


class AskRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


@app.post("/ask", response_model=EngineResponse)
def ask(req: AskRequest) -> EngineResponse:
    return engine.ask(req.session_id, req.message)
