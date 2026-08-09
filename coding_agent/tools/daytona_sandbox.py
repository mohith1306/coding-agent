import logging
import os
from pathlib import Path
from typing import Optional

from .terminal import BLOCKED_PREFIXES, DEFAULT_TIMEOUT_SECONDS, MAX_OUTPUT_CHARS

logger = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
}


class DaytonaSandbox:
    """Runs commands inside a remote Daytona sandbox with the same interface as TerminalSandbox."""

    def __init__(
        self,
        root: Path,
        api_key: Optional[str] = None,
        max_output_chars: int = MAX_OUTPUT_CHARS,
    ) -> None:
        self.root = root.resolve()
        self._api_key = api_key
        self._client = None
        self._sandbox = None
        self._work_dir = None
        self._uploaded: dict[str, tuple[int, int]] = {}
        self._max_output_chars = max_output_chars
        self._load_dotenv(self.root / ".env")
        self._load_dotenv(Path.cwd() / ".env")
        if not api_key and not os.getenv("DAYTONA_API_KEY"):
            raise RuntimeError("DAYTONA_API_KEY is not set")
        try:
            import daytona  # noqa: F401
        except ImportError as error:
            raise RuntimeError("daytona SDK is not installed") from error

    # -- lifecycle ----------------------------------------------------------

    def _ensure_sandbox(self) -> None:
        if self._sandbox is not None:
            return
        from daytona import CreateSandboxFromSnapshotParams, Daytona

        self._client = Daytona()
        params = CreateSandboxFromSnapshotParams(
            language="python",
            auto_stop_interval=5,
            auto_delete_interval=1440,
        )
        self._sandbox = self._client.create(params, timeout=60)
        self._work_dir = self._sandbox.get_work_dir() or "/workspace"
        logger.info("Daytona sandbox created (%s), work dir=%s", self._sandbox.id, self._work_dir)

    def close(self) -> None:
        if self._sandbox is not None and self._client is not None:
            try:
                self._client.delete(self._sandbox)
            except Exception as error:
                logger.warning("Failed to delete Daytona sandbox: %s", error)
            self._sandbox = None

    # -- sync ---------------------------------------------------------------

    def _sync(self) -> None:
        self._ensure_sandbox()
        for path in self._iter_files():
            rel = str(path.relative_to(self.root))
            try:
                stat = path.stat()
            except OSError:
                continue
            sig = (stat.st_mtime_ns, stat.st_size)
            if self._uploaded.get(rel) == sig:
                continue
            try:
                self._sandbox.fs.upload_file(str(path), rel)
            except Exception as error:
                logger.warning("Upload failed for %s: %s", rel, error)
                continue
            self._uploaded[rel] = sig
        logger.info("Synced %d files to sandbox", len(self._uploaded))

    def _iter_files(self):
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root))
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if rel.startswith(".") or "/." in rel:
                continue
            yield path

    # -- execution ----------------------------------------------------------

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
        command = command.strip()
        if not command:
            return "Error: empty command."

        block_reason = self._check_blocked(command)
        if block_reason:
            logger.warning("Blocked command: %s", command)
            return block_reason

        logger.info("$ (sandbox) %s (timeout=%ss)", command, timeout)
        try:
            self._sync()
            response = self._sandbox.process.exec(command, cwd=self._work_dir, timeout=timeout)
        except Exception as error:
            logger.warning("Sandbox command failed: %s", command)
            return f"Failed to run in sandbox: {self._safe(error)}"

        output = (response.result or "").strip()
        if not output:
            output = "(no output)"
        if len(output) > self._max_output_chars:
            output = output[: self._max_output_chars] + "\n\n[Output truncated]"

        logger.info("$ (sandbox) %s → exit %s", command, getattr(response, "exit_code", "unknown"))
        return f"Exit code: {getattr(response, 'exit_code', 'unknown')}\n{output}"

    # -- helpers ------------------------------------------------------------

    def _check_blocked(self, command: str) -> Optional[str]:
        lowered = command.lower()
        for prefix in BLOCKED_PREFIXES:
            if lowered.startswith(prefix):
                return f"Blocked: command `{command}` is not allowed in the sandbox."
        return None

    @staticmethod
    def _safe(error: Exception) -> str:
        try:
            return str(error)[:500]
        except Exception:
            return "unknown error"

    @staticmethod
    def _load_dotenv(path: Path) -> None:
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
