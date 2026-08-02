import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from coding_agent.agent import CONFIRMATION_MARKER, CodingAgent
from coding_agent.memory import MemoryStore


logger = logging.getLogger(__name__)

app = FastAPI(title="Coding Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parents[2]
WORKSPACES = ROOT / "web" / "workspaces"
WORKSPACES.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_sessions: dict[str, tuple[CodingAgent, MemoryStore]] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = ""
    confirmed: bool = False


class ChatResponse(BaseModel):
    session_id: str
    response: str
    requires_confirmation: bool
    action: str = ""
    target: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(request: ChatRequest) -> ChatResponse:
    agent, session_id = _get_agent(request.session_id)
    try:
        response_text = agent.handle(request.message, confirmed=request.confirmed)
    except Exception as error:
        logger.exception("Agent failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(error))

    if response_text.startswith(CONFIRMATION_MARKER):
        action, target = _parse_confirmation(response_text)
        return ChatResponse(
            session_id=session_id,
            response=response_text,
            requires_confirmation=True,
            action=action,
            target=target,
        )

    return ChatResponse(
        session_id=session_id,
        response=response_text,
        requires_confirmation=False,
    )


def _get_agent(session_id: str) -> tuple[CodingAgent, str]:
    if not session_id:
        session_id = str(uuid.uuid4())

    with _lock:
        if session_id not in _sessions:
            workspace = WORKSPACES / session_id
            workspace.mkdir(parents=True, exist_ok=True)
            try:
                memory = MemoryStore()
            except RuntimeError:
                memory = None
            agent = CodingAgent(memory=memory, root=workspace)
            _sessions[session_id] = (agent, memory)
        return _sessions[session_id][0], session_id


def _parse_confirmation(response_text: str) -> tuple[str, str]:
    action = ""
    target = ""
    for line in response_text.splitlines():
        if line.startswith("Action:"):
            action = line.split(":", 1)[1].strip()
        elif line.startswith("Target:"):
            target = line.split(":", 1)[1].strip()
    return action, target


@app.exception_handler(HTTPException)
def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


static_dir = ROOT / "web" / "frontend" / "dist"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
