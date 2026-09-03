"""GitHub integration with full API support (read + write operations)."""

import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class GitHubIntegration:
    """Full GitHub API integration with read and write operations.
    
    Supported operations:
    - Read: list_issues, list_pull_requests, get_file_content, get_repo_info
    - Write: create_pull_request, create_issue, add_comment, close_issue,
             assign_reviewers, merge_pull_request
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.token = self._load_token()
        self.repo = self._detect_repo()

    def available(self) -> bool:
        """Check if GitHub integration is available."""
        return bool(self.token) and self.repo is not None

    # ==================== READ OPERATIONS ====================

    def list_issues(self, state: str = "open", limit: int = 10) -> list[dict[str, str]]:
        """List issues in the repository."""
        if not self.available():
            return [{"error": "GitHub token is not set or no git remote found."}]

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
                    "created_at": issue.get("created_at", ""),
                    "url": issue.get("html_url", ""),
                }
                for issue in issues
                if "pull_request" not in issue
            ]
        return issues

    def list_pull_requests(self, state: str = "open", limit: int = 10) -> list[dict[str, str]]:
        """List pull requests in the repository."""
        if not self.available():
            return [{"error": "GitHub token is not set or no git remote found."}]

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
                    "base": pr.get("base", {}).get("ref", ""),
                    "url": pr.get("html_url", ""),
                    "mergeable": pr.get("mergeable"),
                }
                for pr in prs
            ]
        return prs

    def get_file_content(self, path: str, ref: str = "main") -> dict[str, str]:
        """Get file content from the repository."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        encoded_path = urllib.parse.quote(path, safe="")
        url = f"https://api.github.com/repos/{self.repo}/contents/{encoded_path}?ref={ref}"
        result = self._get_json(url)

        if isinstance(result, dict) and "content" in result:
            import base64
            content = base64.b64decode(result["content"]).decode("utf-8")
            return {
                "path": path,
                "content": content,
                "sha": result.get("sha", ""),
                "size": result.get("size", 0),
            }
        return result

    def get_repo_info(self) -> dict[str, str]:
        """Get repository information."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}"
        return self._get_json(url)

    def get_issue(self, issue_number: int) -> dict[str, str]:
        """Get a single issue by number."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}
        url = f"https://api.github.com/repos/{self.repo}/issues/{issue_number}"
        result = self._get_json(url)
        if isinstance(result, dict) and "error" not in result:
            return {
                "number": str(result.get("number", "")),
                "title": result.get("title", ""),
                "state": result.get("state", ""),
                "body": result.get("body", ""),
                "labels": ", ".join(label.get("name", "") for label in result.get("labels", [])),
                "created_at": result.get("created_at", ""),
                "url": result.get("html_url", ""),
            }
        return result if isinstance(result, dict) else {"error": str(result)}

    def list_branches(self) -> list[dict[str, str]]:
        """List all branches in the repository (follows pagination)."""
        if not self.available():
            return [{"error": "GitHub token is not set or no git remote found."}]

        all_branches: list[dict[str, str]] = []
        page = 1
        per_page = 100
        while True:
            query = urllib.parse.urlencode({"per_page": per_page, "page": page})
            url = f"https://api.github.com/repos/{self.repo}/branches?{query}"
            branches = self._get_json(url)
            if not isinstance(branches, list) or not branches:
                if isinstance(branches, list):
                    break
                return branches  # error dict
            for branch in branches:
                all_branches.append({
                    "name": branch.get("name", ""),
                    "sha": branch.get("commit", {}).get("sha", ""),
                })
            if len(branches) < per_page:
                break
            page += 1
        return all_branches

    # ==================== WRITE OPERATIONS ====================

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, str]:
        """Create a new pull request."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        return self._post_json(url, payload)

    def create_issue(
        self,
        title: str,
        body: str = "",
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None,
    ) -> dict[str, str]:
        """Create a new issue."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}/issues"
        payload = {
            "title": title,
            "body": body,
        }
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return self._post_json(url, payload)

    def add_comment(self, issue_number: int, body: str) -> dict[str, str]:
        """Add a comment to an issue or pull request."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}/issues/{issue_number}/comments"
        payload = {"body": body}
        return self._post_json(url, payload)

    def close_issue(self, issue_number: int) -> dict[str, str]:
        """Close an issue."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}/issues/{issue_number}"
        payload = {"state": "closed"}
        return self._patch_json(url, payload)

    def assign_reviewers(self, pr_number: int, reviewers: list[str]) -> dict[str, str]:
        """Assign reviewers to a pull request."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}/pulls/{pr_number}/requested_reviewers"
        payload = {"reviewers": reviewers}
        return self._post_json(url, payload)

    def merge_pull_request(
        self,
        pr_number: int,
        merge_method: str = "merge",
    ) -> dict[str, str]:
        """Merge a pull request."""
        if not self.available():
            return {"error": "GitHub token is not set or no git remote found."}

        url = f"https://api.github.com/repos/{self.repo}/pulls/{pr_number}/merge"
        payload = {"merge_method": merge_method}
        return self._put_json(url, payload)

    # ==================== PRIVATE METHODS ====================

    def _get_json(self, url: str) -> object:
        """Make a GET request to GitHub API."""
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "CodingAgent/0.2",
            },
            method="GET",
        )
        return self._execute_request(request)

    def _post_json(self, url: str, payload: dict) -> dict:
        """Make a POST request to GitHub API."""
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "CodingAgent/0.2",
            },
            method="POST",
        )
        return self._execute_request(request)

    def _patch_json(self, url: str, payload: dict) -> dict:
        """Make a PATCH request to GitHub API."""
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "CodingAgent/0.2",
            },
            method="PATCH",
        )
        return self._execute_request(request)

    def _put_json(self, url: str, payload: dict) -> dict:
        """Make a PUT request to GitHub API."""
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "CodingAgent/0.2",
            },
            method="PUT",
        )
        return self._execute_request(request)

    def _execute_request(self, request: Request) -> object:
        """Execute an HTTP request and return JSON response."""
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            return {"error": f"GitHub API error {error.code}: {body[:500]}"}
        except Exception as error:
            return {"error": f"Failed to reach GitHub API: {error}"}

    def _load_token(self) -> str:
        """Load GitHub token from .env file or environment."""
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
        """Detect repository from git remote URL."""
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
        """Parse owner/repo from git remote URL."""
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
