from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str
    full_name: str
    html_url: str


class GitHubUrlParseError(ValueError):
    """Raised when a user supplied GitHub repository reference is invalid."""


def parse_github_repo_url(value: str) -> GitHubRepoRef:
    """Parse a GitHub repository URL or owner/repo string."""
    raw = (value or "").strip()
    if not raw:
        raise GitHubUrlParseError(
            "GitHub 项目地址不能为空。支持格式：https://github.com/owner/repo、github.com/owner/repo 或 owner/repo。"
        )

    normalized = raw.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]

    if normalized.startswith(("http://", "https://")):
        parsed = urlparse(normalized)
        if parsed.netloc.lower() != "github.com":
            raise GitHubUrlParseError(f"仅支持 github.com 仓库地址，当前输入域名是：{parsed.netloc or '-'}")
        path = parsed.path.strip("/")
        if parsed.query or parsed.fragment:
            raise GitHubUrlParseError("GitHub 仓库地址不要包含 query 或 fragment，请只传项目主页地址。")
    elif normalized.lower().startswith("github.com/"):
        path = normalized.split("/", 1)[1].strip("/")
    else:
        path = normalized.strip("/")

    parts = [part for part in path.split("/") if part]
    if len(parts) != 2:
        raise GitHubUrlParseError(
            "无法解析 GitHub 仓库地址。支持格式：https://github.com/owner/repo、github.com/owner/repo 或 owner/repo。"
        )

    owner, repo = parts
    if not _valid_github_path_part(owner) or not _valid_github_path_part(repo):
        raise GitHubUrlParseError(
            f"GitHub owner/repo 格式不合法：{owner}/{repo}。owner 和 repo 只能包含字母、数字、点、下划线与短横线。"
        )

    full_name = f"{owner}/{repo}"
    return GitHubRepoRef(
        owner=owner,
        repo=repo,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
    )


def _valid_github_path_part(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", value or ""))
