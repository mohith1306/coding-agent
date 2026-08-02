import json
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class GitHubIntegration:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.token = self._load_token()
        self.repo = self._detect_repo()

    def available(self) -> bool:
        return bool(self.token) and self.repo is not None

    def list_issues(self, state: str = "open", limit: int = 10) -> list[dict[str, str]]:
        if not self.available():
            return [{"error": "GitHub token is not set or no git remote found. Add GITHUB_TOKEN to .env."}]

        query = urllib.parse.urlencode({"state": state, "per_page": limit})
        url = f"https://api.github.com/repos/{self.repo}/issues?{query}"
        issues = self._get_json(url)

        if isinstance(issues, list):
            return [
                {
                    "number": str(issue.get("number", "")),
                    "title": issue.get("title", ""),
                    "state": issue.get("state", ""),
                    "labels": ", ".join(label.get("name", "") for label in issue.get("labels", [])),
                }
                for issue in issues
                if "pull_request" not in issue
            ]
        return issues

    def list_pull_requests(self, state: str = "open", limit: int = 10) -> list[dict[str, str]]:
        if not self.available():
            return [{"error": "GitHub token is not set or no git remote found. Add GITHUB_TOKEN to .env."}]

        query = urllib.parse.urlencode({"state": state, "per_page": limit})
        url = f"https://api.github.com/repos/{self.repo}/pulls?{query}"
        prs = self._get_json(url)

        if isinstance(prs, list):
            return [
                {
                    "number": str(pr.get("number", "")),
                    "title": pr.get("title", ""),
                    "state": pr.get("state", ""),
                    "branch": pr.get("head", {}).get("ref", ""),
                }
                for pr in prs
            ]
        return prs

    def _get_json(self, url: str) -> object:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "CodingAgent/0.1",
            },
            method="GET",
        )

        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            return [{"error": f"GitHub API error {error.code}: {body[:300]}"}]
        except Exception as error:
            return [{"error": f"Failed to reach GitHub API: {error}"}]

    def _load_token(self) -> str:
        dotenv_path = self.root / ".env"
        if dotenv_path.is_file():
            for line in dotenv_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == "GITHUB_TOKEN":
                    return value.strip().strip('"').strip("'")
        return os.getenv("GITHUB_TOKEN", "")

    def _detect_repo(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.root,
            )
            url = result.stdout.strip()
            if not url:
                return None
            return self._parse_repo_from_url(url)
        except Exception:
            return None

    def _parse_repo_from_url(self, url: str) -> Optional[str]:
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]

        if "github.com" in url:
            if url.startswith("git@"):
                parts = url.split("github.com:")[1].split("/")
                return f"{parts[0]}/{parts[1]}"
            if url.startswith("https://") or url.startswith("http://"):
                parts = url.split("github.com/")[1].split("/")
                return f"{parts[0]}/{parts[1]}"

        return None
