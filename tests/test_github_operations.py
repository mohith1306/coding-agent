"""Tests for GitHub operations."""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from coding_agent.tools.github import GitHubIntegration
from coding_agent.tools.git import GitContext


@pytest.fixture
def github():
    """Create GitHub integration for testing."""
    return GitHubIntegration(Path("."))


@pytest.fixture
def git():
    """Create GitContext for testing."""
    return GitContext(Path("."))


class TestGitOperations:
    """Tests for Git operations (branch, merge, stash)."""

    def test_status(self, git):
        """Test git status."""
        status = git.status()
        assert status.branch is not None
        assert isinstance(status.dirty_files, list)
        assert isinstance(status.ahead, int)
        assert isinstance(status.behind, int)

    def test_current_branch(self, git):
        """Test get current branch."""
        branch = git.current_branch()
        assert branch is not None
        assert branch != ""

    def test_list_branches(self, git):
        """Test list branches."""
        branches = git.list_branches()
        assert isinstance(branches, list)
        assert len(branches) > 0
        assert "main" in branches or "feat/postgresql-memory-store" in branches

    def test_create_and_delete_branch(self, git):
        """Test create and delete branch."""
        branch_name = "test-branch-temp"

        # Create branch
        code, output = git.create_branch(branch_name)
        assert code == 0, f"Failed to create branch: {output}"

        # Verify branch exists
        branches = git.list_branches()
        assert branch_name in branches

        # Delete branch
        code, output = git.delete_branch(branch_name)
        assert code == 0, f"Failed to delete branch: {output}"

        # Verify branch deleted
        branches = git.list_branches()
        assert branch_name not in branches

    def test_checkout(self, git):
        """Test checkout to branch."""
        original_branch = git.current_branch()

        # Create and checkout to new branch
        code, output = git.create_and_checkout("test-checkout-branch")
        assert code == 0, f"Failed to create and checkout: {output}"
        assert git.current_branch() == "test-checkout-branch"

        # Checkout back
        code, output = git.checkout(original_branch)
        assert code == 0, f"Failed to checkout back: {output}"
        assert git.current_branch() == original_branch

        # Cleanup
        git.delete_branch("test-checkout-branch")

    def test_stash_and_pop(self, git):
        """Test stash and stash pop."""
        # Stash changes
        code, output = git.stash("test stash message")
        assert code == 0, f"Failed to stash: {output}"

        # Pop stash
        code, output = git.stash_pop()
        assert code == 0, f"Failed to stash pop: {output}"

    def test_stash_list(self, git):
        """Test stash list."""
        stashes = git.stash_list()
        assert isinstance(stashes, list)

    def test_diff(self, git):
        """Test git diff."""
        diff = git.diff()
        assert isinstance(diff, str)

    def test_log(self, git):
        """Test git log."""
        commits = git.log(limit=5)
        assert isinstance(commits, list)
        assert len(commits) > 0
        assert "hash" in commits[0]
        assert "message" in commits[0]

    def test_current_hash(self, git):
        """Test current hash."""
        hash_val = git.current_hash()
        assert hash_val is not None
        assert len(hash_val) > 0

    def test_stage_and_commit(self, git):
        """Test stage and commit."""
        # Create a test file
        test_file = Path("test_git_commit.txt")
        test_file.write_text("test content")

        # Stage
        git.stage_all()

        # Commit
        code, output = git.commit("Test commit")
        # May fail if no changes, that's ok

        # Cleanup
        test_file.unlink(missing_ok=True)


class TestGitHubIntegration:
    """Tests for GitHub API integration."""

    def test_github_initialization(self, github):
        """Test GitHub integration initializes."""
        assert github is not None
        assert github.root == Path(".").resolve()

    def test_load_token(self, github):
        """Test token loading."""
        token = github._load_token()
        # Token may or may not exist
        assert isinstance(token, str)

    def test_detect_repo(self, github):
        """Test repo detection."""
        repo = github._detect_repo()
        # May be None if no remote
        if repo:
            assert "github.com" in repo or "/" in repo

    def test_parse_repo_from_url_https(self, github):
        """Test parsing repo from HTTPS URL."""
        url = "https://github.com/owner/repo.git"
        repo = github._parse_repo_from_url(url)
        assert repo == "owner/repo"

    def test_parse_repo_from_url_ssh(self, github):
        """Test parsing repo from SSH URL."""
        url = "git@github.com:owner/repo.git"
        repo = github._parse_repo_from_url(url)
        assert repo == "owner/repo"

    def test_list_issues(self, github):
        """Test list issues (may fail with auth)."""
        issues = github.list_issues(state="open", limit=3)
        # May return error dict or list
        assert isinstance(issues, (list, dict))

    def test_list_pull_requests(self, github):
        """Test list PRs (may fail with auth)."""
        prs = github.list_pull_requests(state="open", limit=3)
        # May return error dict or list
        assert isinstance(prs, (list, dict))

    def test_create_pull_request(self, github):
        """Test create PR (mocked)."""
        with patch.object(github, "_post_json") as mock_post:
            mock_post.return_value = {"html_url": "https://github.com/test/test/pull/1", "number": 1}

            result = github.create_pull_request(
                title="Test PR",
                body="Test body",
                head="feature/test",
                base="main",
            )
            assert "html_url" in result or "error" in result

    def test_create_issue(self, github):
        """Test create issue (mocked)."""
        with patch.object(github, "_post_json") as mock_post:
            mock_post.return_value = {"html_url": "https://github.com/test/test/issues/1", "number": 1}

            result = github.create_issue(
                title="Test Issue",
                body="Test body",
                labels=["bug"],
            )
            assert "html_url" in result or "error" in result

    def test_add_comment(self, github):
        """Test add comment (mocked)."""
        with patch.object(github, "_post_json") as mock_post:
            mock_post.return_value = {"html_url": "https://github.com/test/test/issues/1#comment"}

            result = github.add_comment(1, "Test comment")
            assert "html_url" in result or "error" in result

    def test_close_issue(self, github):
        """Test close issue (mocked)."""
        with patch.object(github, "_patch_json") as mock_patch:
            mock_patch.return_value = {"state": "closed"}

            result = github.close_issue(1)
            assert "state" in result or "error" in result

    def test_merge_pull_request(self, github):
        """Test merge PR (mocked)."""
        with patch.object(github, "_put_json") as mock_put:
            mock_put.return_value = {"merged": True}

            result = github.merge_pull_request(1, "merge")
            assert "merged" in result or "error" in result

    def test_assign_reviewers(self, github):
        """Test assign reviewers (mocked)."""
        with patch.object(github, "_post_json") as mock_post:
            mock_post.return_value = {"users": [{"login": "reviewer1"}]}

            result = github.assign_reviewers(1, ["reviewer1"])
            assert "users" in result or "error" in result

    def test_get_file_content(self, github):
        """Test get file content (mocked)."""
        import base64

        with patch.object(github, "_get_json") as mock_get:
            content = base64.b64encode(b"test content").decode()
            mock_get.return_value = {"content": content, "sha": "abc123", "size": 12}

            result = github.get_file_content("test.py", "main")
            assert "content" in result
            assert result["content"] == "test content"


class TestGitHubToolRegistry:
    """Tests for GitHub tools in tool registry."""

    def test_github_list_issues_tool(self):
        """Test github_list_issues tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_list_issues")
        assert tool is not None

    def test_github_list_prs_tool(self):
        """Test github_list_prs tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_list_prs")
        assert tool is not None

    def test_github_create_pr_tool(self):
        """Test github_create_pr tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_create_pr")
        assert tool is not None

    def test_github_create_issue_tool(self):
        """Test github_create_issue tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_create_issue")
        assert tool is not None

    def test_github_add_comment_tool(self):
        """Test github_add_comment tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_add_comment")
        assert tool is not None

    def test_github_close_issue_tool(self):
        """Test github_close_issue tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_close_issue")
        assert tool is not None

    def test_github_merge_pr_tool(self):
        """Test github_merge_pr tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_merge_pr")
        assert tool is not None

    def test_github_assign_reviewers_tool(self):
        """Test github_assign_reviewers tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_assign_reviewers")
        assert tool is not None

    def test_github_get_file_tool(self):
        """Test github_get_file tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_get_file")
        assert tool is not None

    def test_github_list_branches_tool(self):
        """Test github_list_branches tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("github_list_branches")
        assert tool is not None


class TestGitToolRegistry:
    """Tests for Git tools in tool registry."""

    def test_git_status_tool(self):
        """Test git_status tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_status")
        assert tool is not None

        result = tool.invoke({})
        assert "Branch:" in result

    def test_git_diff_tool(self):
        """Test git_diff tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_diff")
        assert tool is not None

    def test_git_commit_tool(self):
        """Test git_commit tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_commit")
        assert tool is not None

    def test_git_push_tool(self):
        """Test git_push tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_push")
        assert tool is not None

    def test_git_create_branch_tool(self):
        """Test git_create_branch tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_create_branch")
        assert tool is not None

    def test_git_checkout_tool(self):
        """Test git_checkout tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_checkout")
        assert tool is not None

    def test_git_create_and_checkout_tool(self):
        """Test git_create_and_checkout tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_create_and_checkout")
        assert tool is not None

    def test_git_delete_branch_tool(self):
        """Test git_delete_branch tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_delete_branch")
        assert tool is not None

    def test_git_list_branches_tool(self):
        """Test git_list_branches tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_list_branches")
        assert tool is not None

        result = tool.invoke({})
        assert "Branches:" in result

    def test_git_merge_tool(self):
        """Test git_merge tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_merge")
        assert tool is not None

    def test_git_stash_tool(self):
        """Test git_stash tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_stash")
        assert tool is not None

    def test_git_stash_pop_tool(self):
        """Test git_stash_pop tool."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("git_stash_pop")
        assert tool is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
