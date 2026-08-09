import io
import logging
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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


@app.get("/api/sessions/{session_id}/files")
def list_workspace_files(session_id: str):
    workspace = WORKSPACES / session_id
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="No workspace for this session yet.")

    def walk(directory: Path) -> list[dict]:
        entries = []
        for path in sorted(directory.iterdir()):
            if path.name == ".git":
                continue
            if path.is_dir():
                entries.append({
                    "name": path.name,
                    "type": "directory",
                    "children": walk(path),
                })
            else:
                entries.append({
                    "name": path.name,
                    "type": "file",
                    "size": path.stat().st_size,
                })
        return entries

    return {"session_id": session_id, "tree": walk(workspace)}


@app.get("/api/sessions/{session_id}/files/{file_path:path}")
def read_workspace_file(session_id: str, file_path: str):
    workspace = (WORKSPACES / session_id).resolve()
    target = (workspace / file_path).resolve()
    if not str(target).startswith(str(workspace)) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return {"path": file_path, "content": target.read_text(errors="replace")}


@app.get("/api/sessions/{session_id}/download")
def download_workspace(session_id: str):
    workspace = WORKSPACES / session_id
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="No workspace for this session yet.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(workspace.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(workspace))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.zip"'},
    )


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
