import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .context import AgentContext
from .tools.terminal import TerminalSandbox


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    message: str


class Verifier:
    def __init__(self, root: Optional[Path] = None, terminal: Optional[TerminalSandbox] = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.terminal = terminal or TerminalSandbox(self.root)

    def verify_file(self, path: Path, context: Optional[AgentContext] = None) -> str:
        parts = []
        if path.suffix == ".py":
            parts.append(self._verify_python(path))
        else:
            parts.append("File written successfully.")

        if context is not None:
            project_check = self._run_project_checks(context)
            if project_check:
                parts.append(project_check)

        return "\n".join(parts)

    def _run_project_checks(self, context: AgentContext) -> str:
        checks = []

        if context.has_lint_config:
            lint_cmd = self._lint_command(context.language)
            if lint_cmd:
                checks.append(("lint", lint_cmd, 20))

        if context.has_test_config:
            test_cmd = self._test_command(context.language)
            if test_cmd:
                checks.append(("test", test_cmd, 60))

        if not checks:
            return ""

        results = []
        for label, command, timeout in checks:
            result = self.terminal.run(command, timeout=timeout)
            passed = result.startswith("Exit code: 0")
            results.append(f"{'PASS' if passed else 'FAIL'} {label}: {command}")

        return "\n".join(results)

    def _lint_command(self, language: str) -> Optional[str]:
        if language == "python":
            return "python3 -m ruff check ."
        if language == "javascript":
            return "npx eslint ."
        if language == "typescript":
            return "npx eslint ."
        return None

    def _test_command(self, language: str) -> Optional[str]:
        if language == "python":
            return "python3 -m pytest"
        if language == "javascript":
            return "npm test"
        if language == "typescript":
            return "npm test"
        if language == "rust":
            return "cargo test"
        if language == "go":
            return "go test ./..."
        if language == "ruby":
            return "bundle exec rspec"
        return None

    def _verify_python(self, path: Path) -> str:
        abs_path = path.resolve()
        if not abs_path.is_file():
            return "File does not exist. Could not verify."

        rel_path = str(abs_path.relative_to(self.root))
        result = subprocess.run(
            [sys.executable, "-m", "compileall", str(abs_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return f"Verified `{rel_path}`: compiles clean."
        else:
            errors = result.stderr[:500] or result.stdout[:500]
            return f"Warning: `{rel_path}` has issues:\n{errors}"
