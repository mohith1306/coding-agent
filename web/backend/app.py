import io
import logging
import time
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
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from coding_agent.agent import CONFIRMATION_MARKER, CodingAgent
from coding_agent.memory import MemoryStore


logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


setup_logging()

app = FastAPI(title="Coding Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        if path != "/health":
            logger.info("→ %s %s", method, path)
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if path != "/health":
            logger.info("← %s %s → %s (%d ms)", method, path, response.status_code, elapsed_ms)
        return response


app.add_middleware(RequestLoggingMiddleware)

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


class SaveFileRequest(BaseModel):
    content: str


class RunFileRequest(BaseModel):
    file_path: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_workspace_path(session_id: str, file_path: str) -> Path:
    workspace = (WORKSPACES / session_id).resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="No workspace for this session yet.")
    target = (workspace / file_path).resolve()
    if target != workspace and workspace not in target.parents:
        raise HTTPException(status_code=403, detail="Path is outside the workspace.")
    return target


@app.get("/api/sessions/{session_id}/files")
def list_workspace_files(session_id: str):
    workspace = WORKSPACES / session_id
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="No workspace for this session yet.")

    logger.info("Listing workspace files for session %s", session_id)

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
    logger.info("Reading file %s (session %s)", file_path, session_id)
    return {"path": file_path, "content": target.read_text(errors="replace")}


@app.put("/api/sessions/{session_id}/files/{file_path:path}")
def save_workspace_file(session_id: str, file_path: str, request: SaveFileRequest):
    target = _resolve_workspace_path(session_id, file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(request.content, encoding="utf-8")
    size = target.stat().st_size
    logger.info("Saved file %s (%d bytes, session %s)", file_path, size, session_id)
    return {"path": file_path, "size": size}


@app.delete("/api/sessions/{session_id}/files/{file_path:path}")
def delete_workspace_file(session_id: str, file_path: str):
    target = _resolve_workspace_path(session_id, file_path)
    if target.is_file():
        target.unlink()
    elif target.is_dir():
        if any(target.iterdir()):
            raise HTTPException(status_code=400, detail="Directory is not empty.")
        target.rmdir()
    else:
        raise HTTPException(status_code=404, detail="Not found.")
    logger.info("Deleted %s (session %s)", file_path, session_id)
    return {"deleted": file_path}


@app.post("/api/sessions/{session_id}/run")
def run_python_file(session_id: str, request: RunFileRequest):
    target = _resolve_workspace_path(session_id, request.file_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.suffix != ".py":
        raise HTTPException(status_code=400, detail="Only Python files can be executed for now.")

    agent, _ = _get_agent(session_id)
    logger.info("Running %s (session %s)", request.file_path, session_id)
    try:
        workspace = (WORKSPACES / session_id).resolve()
        relative = str(target.relative_to(workspace))
        result = agent.terminal.run(f"python3 {relative}", timeout=60)
    except Exception as error:
        logger.exception("Run failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(error))
    logger.info("Run %s finished (session %s)", request.file_path, session_id)
    return {"path": request.file_path, "result": result}


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


@app.post("/api/sessions/{session_id}")
def create_session(session_id: str):
    agent, resolved = _get_agent(session_id)
    workspace = WORKSPACES / resolved
    logger.info("Ensured session %s (workspace %s)", resolved, workspace)
    return {"session_id": resolved, "workspace": str(workspace)}


@app.post("/api/chat")
def chat(request: ChatRequest) -> ChatResponse:
    agent, session_id = _get_agent(request.session_id)
    flag = "confirmed" if request.confirmed else "unconfirmed"
    logger.info("Chat [%s] session=%s: %.200s", flag, session_id, request.message)
    try:
        response_text = agent.handle(request.message, confirmed=request.confirmed)
    except Exception as error:
        logger.exception("Agent failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(error))

    if response_text.startswith(CONFIRMATION_MARKER):
        action, target = _parse_confirmation(response_text)
        logger.info("Chat session=%s awaiting confirmation: action=%s target=%s", session_id, action, target)
        return ChatResponse(
            session_id=session_id,
            response=response_text,
            requires_confirmation=True,
            action=action,
            target=target,
        )

    logger.info("Chat session=%s completed (%.400s)", session_id, response_text.replace("\n", " "))
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
            logger.info("Created new session %s (workspace %s)", session_id, workspace)
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
