from pathlib import Path


class FileTools:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def search(self, root: Path, pattern: str) -> list[Path]:
        safe_root = self._resolve_safe_path(root)
        return sorted(path for path in safe_root.rglob(pattern) if path.is_file())

    def read_text(self, path: Path) -> str:
        safe_path = self._resolve_safe_path(path)

        if not safe_path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        return safe_path.read_text(encoding="utf-8")

    def exists(self, path: Path) -> bool:
        safe_path = self._resolve_safe_path(path)
        return safe_path.exists()

    def write_text(self, path: Path, content: str) -> None:
        safe_path = self._resolve_safe_path(path)
        safe_path.write_text(content, encoding="utf-8")

    def _resolve_safe_path(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.root / path
        resolved = candidate.resolve()

        if resolved != self.root and self.root not in resolved.parents:
            raise PermissionError(f"Path is outside the workspace: {path}")

        return resolved
