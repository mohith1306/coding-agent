import asyncio
import io
import json
import logging
import os
import queue
import signal
import subprocess
import sys
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

# Allow `uvicorn app:app` when launched from web/backend as well as the repo root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.agent import CONFIRMATION_MARKER, CodingAgent
from coding_agent.events import reset_event_sink, set_event_sink
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
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
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

WORKSPACES = ROOT / "web" / "workspaces"
WORKSPACES.mkdir(parents=True, exist_ok=True)

dotenv_path = ROOT / ".env"
if dotenv_path.is_file():
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not os.environ.get(key, "").strip()):
            os.environ[key] = value

PROJECT_MARKERS = (
    ".git",
    ".hg",
    ".svn",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "composer.json",
    "Cargo.lock",
    "Gemfile",
)

# Directories scanned for candidate projects when the user opens the picker.
PROJECT_SCAN_DIRS = [
    Path.home(),
    Path.home() / "dev",
    Path.home() / "projects",
    Path.home() / "code",
    Path.home() / "src",
    Path.home() / "workspace",
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Developer",
]

_lock = threading.Lock()
_sessions: dict[str, tuple[CodingAgent, MemoryStore]] = {}
_running_procs: dict[str, subprocess.Popen] = {}


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


def _is_project(dir_path: Path) -> bool:
    try:
        return any((dir_path / marker).exists() for marker in PROJECT_MARKERS)
    except OSError:
        return False


def _scan_projects(max_depth: int = 2, max_results: int = 200) -> list[dict]:
    """Find git repos / project dirs under common dev locations.

    Projects are de-duplicated (a nested repo under a scanned parent is kept,
    but a scanned parent that itself is a project shadows its own parent dir).
    """
    found: dict[str, Path] = {}
    visited: set[Path] = set()

    def walk(base: Path, depth: int) -> None:
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except (OSError, PermissionError):
            return
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".git"}:
                continue
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            if _is_project(entry):
                found[entry.name] = resolved
            elif depth < max_depth:
                walk(entry, depth + 1)
            if len(found) >= max_results:
                return

    for base in PROJECT_SCAN_DIRS:
        if base.is_dir():
            walk(base, 0)

    # Fallback: the repo's own directory is a project.
    if ROOT.is_dir() and str(ROOT.resolve()) not in {str(p.resolve()) for p in found.values()}:
        if _is_project(ROOT):
            found[ROOT.name] = ROOT.resolve()

    projects = []
    for name in sorted(found):
        projects.append({"name": name, "path": str(found[name])})
    return projects[:max_results]


@app.get("/api/projects")
def list_projects() -> dict:
    return {
        "projects": _scan_projects(),
        "cwd": str(Path.cwd()),
        "scan_dirs": [str(p) for p in PROJECT_SCAN_DIRS if p.is_dir()],
    }


@app.get("/api/projects/browse")
def browse_projects(path: str = "") -> dict:
    """List the subdirectories of a folder so the UI can browse for a project."""
    raw = path.strip() or str(Path.home())
    current = Path(raw).expanduser().resolve()
    if not current.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {raw}")

    children = []
    for entry in sorted(current.iterdir(), key=lambda p: (p.name.startswith("."), p.name.lower())):
        if not entry.is_dir():
            continue
        if entry.name in {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}:
            continue
        try:
            is_project = _is_project(entry)
        except OSError:
            is_project = False
        children.append({
            "name": entry.name,
            "path": str(entry.resolve()),
            "type": "directory",
            "is_project": is_project,
        })

    parent = str(current.parent) if current.parent != current else None
    return {
        "path": str(current),
        "name": current.name,
        "parent": parent,
        "dirs": children,
    }


@app.post("/api/projects/open")
def open_project(request: ChatRequest) -> dict:
    """Resolve a user-supplied path into a valid project root."""
    raw = request.message.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Provide a project path.")
    candidate = Path(raw).expanduser().resolve()
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {raw}")
    if not _is_project(candidate):
        raise HTTPException(status_code=400, detail=f"No project detected at {raw} (no .git, package.json, requirements.txt, etc.).")
    return {"name": candidate.name, "path": str(candidate)}


def _resolve_workspace_path(session_id: str, file_path: str) -> Path:
    workspace = _session_workspace(session_id).resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="No workspace for this session yet.")
    target = (workspace / file_path).resolve()
    if target != workspace and workspace not in target.parents:
        raise HTTPException(status_code=403, detail="Path is outside the workspace.")
    return target


@app.get("/api/sessions/{session_id}/files")
def list_workspace_files(session_id: str):
    workspace = _session_workspace(session_id)
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="No workspace for this session yet.")

    logger.info("Listing workspace files for session %s", session_id)

    def walk(directory: Path) -> list[dict]:
        entries = []
        for path in sorted(directory.iterdir()):
            if path.name in {".git", "node_modules", "__pycache__", ".venv", "venv"}:
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

    return {"session_id": session_id, "root": str(workspace), "tree": walk(workspace)}


@app.get("/api/sessions/{session_id}/files/{file_path:path}")
def read_workspace_file(session_id: str, file_path: str):
    workspace = _session_workspace(session_id).resolve()
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
async def run_python_file_stream(session_id: str, request: RunFileRequest):
    target = _resolve_workspace_path(session_id, request.file_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.suffix != ".py":
        raise HTTPException(status_code=400, detail="Only Python files can be executed for now.")

    with _lock:
        if session_id in _running_procs:
            raise HTTPException(status_code=409, detail="A process is already running in this session.")

    logger.info("Running %s (stream, session %s)", request.file_path, session_id)
    events: queue.Queue = queue.Queue(maxsize=2000)

    def worker() -> None:
        proc = None
        try:
            proc = subprocess.Popen(
                ["python3", str(target)],
                cwd=target.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            with _lock:
                _running_procs[session_id] = proc
            for raw in proc.stdout:
                _queue_put(events, {"type": "output", "text": raw})
        except Exception as error:
            logger.exception("Run failed for session %s", session_id)
            _queue_put(events, {"type": "error", "message": str(error)})
        finally:
            if proc is not None:
                try:
                    exit_code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    exit_code = proc.wait()
            else:
                exit_code = -1
            with _lock:
                _running_procs.pop(session_id, None)
            _queue_put(events, {"type": "exit", "code": exit_code})
            _queue_put(events, None)

    threading.Thread(target=worker, daemon=True).start()
    return _sse_response(events)


@app.post("/api/sessions/{session_id}/stop")
def stop_run(session_id: str):
    with _lock:
        proc = _running_procs.pop(session_id, None)
    if proc is None or proc.poll() is not None:
        return {"stopped": False}

    logger.info("Stopping process for session %s", session_id)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    return {"stopped": True}


@app.get("/api/sessions/{session_id}/download")
def download_workspace(session_id: str):
    workspace = _session_workspace(session_id)
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
def create_session(session_id: str, request: Optional[ChatRequest] = None):
    root: Optional[Path] = None
    if request is not None and request.message.strip():
        raw = request.message.strip()
        candidate = Path(raw).expanduser().resolve()
        if not candidate.is_dir():
            raise HTTPException(status_code=400, detail=f"Not a directory: {raw}")
        if not _is_project(candidate):
            raise HTTPException(status_code=400, detail=f"No project detected at {raw}.")
        root = candidate
    agent, resolved = _get_agent(session_id, root=root)
    workspace = _session_workspace(resolved)
    logger.info("Ensured session %s (workspace %s)", resolved, workspace)
    return {"session_id": resolved, "workspace": str(workspace)}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """Release a session: close its terminal (freeing any Daytona sandbox)."""
    with _lock:
        agent, _ = _sessions.pop(session_id, (None, None))
    if agent is None:
        return {"deleted": False}
    try:
        agent.terminal.close()
    except Exception as error:
        logger.warning("Failed to close terminal for session %s: %s", session_id, error)
    logger.info("Deleted session %s", session_id)
    return {"deleted": True}


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


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    agent, session_id = _get_agent(request.session_id)
    flag = "confirmed" if request.confirmed else "unconfirmed"
    logger.info("Chat stream [%s] session=%s: %.200s", flag, session_id, request.message)
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        token = set_event_sink(events.put)
        try:
            response_text = agent.handle(request.message, confirmed=request.confirmed)
            if response_text.startswith(CONFIRMATION_MARKER):
                action, target = _parse_confirmation(response_text)
                events.put({"type": "confirmation", "action": action, "target": target, "response": response_text})
            else:
                events.put({"type": "done", "response": response_text})
        except Exception as error:
            logger.exception("Agent stream failed for session %s", session_id)
            events.put({"type": "error", "message": str(error)})
        finally:
            reset_event_sink(token)
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    return _sse_response(events)


def _queue_put(events: queue.Queue, item: Optional[dict]) -> None:
    try:
        events.put_nowait(item)
    except queue.Full:
        pass


def _sse_response(events: queue.Queue) -> StreamingResponse:
    async def event_generator():
        while True:
            try:
                item = await asyncio.to_thread(events.get, True, 0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _get_agent(session_id: str, root: Optional[Path] = None) -> tuple[CodingAgent, str]:
    if not session_id:
        session_id = str(uuid.uuid4())

    with _lock:
        if session_id not in _sessions:
            if root is None:
                workspace = WORKSPACES / session_id
                workspace.mkdir(parents=True, exist_ok=True)
            else:
                workspace = root
                if not workspace.is_dir():
                    raise HTTPException(status_code=400, detail=f"Not a directory: {workspace}")
            try:
                memory = MemoryStore()
            except RuntimeError:
                memory = None
            agent = CodingAgent(memory=memory, root=workspace)
            _sessions[session_id] = (agent, memory)
            logger.info("Created new session %s (workspace %s)", session_id, workspace)
        return _sessions[session_id][0], session_id


def _session_workspace(session_id: str) -> Path:
    """The directory the session's agent operates on (project root or sandbox)."""
    with _lock:
        if session_id in _sessions:
            return _sessions[session_id][0].root
    return WORKSPACES / session_id


def _close_all_sessions() -> None:
    with _lock:
        session_ids = list(_sessions.keys())
        for session_id in session_ids:
            agent, _ = _sessions.pop(session_id, (None, None))
            if agent is not None:
                try:
                    agent.terminal.close()
                except Exception as error:
                    logger.warning("Failed to close terminal for session %s: %s", session_id, error)


@app.on_event("shutdown")
def shutdown_hook() -> None:
    logger.info("Shutting down; closing %d session(s)", len(_sessions))
    _close_all_sessions()


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
