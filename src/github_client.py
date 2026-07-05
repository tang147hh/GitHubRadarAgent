from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .models import RepoCandidate


class GitHubClient:
    """Small GitHub REST API client for repository discovery."""

    API_BASE_URL = "https://api.github.com"
    SEARCH_REPOSITORIES_URL = "https://api.github.com/search/repositories"

    def __init__(self, token: str | None = None, max_retries: int = 3, retry_delay_seconds: float = 1.0) -> None:
        self.token = token
        self.max_retries = max(1, max_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.session = requests.Session()

    def search_repositories(
        self,
        query: str,
        limit: int = 10,
        sort: str | None = "stars",
        order: str = "desc",
        page: int = 1,
    ) -> List[RepoCandidate]:
        if limit <= 0:
            return []

        per_page = min(limit, 50)
        params = {
            "q": query,
            "order": order,
            "per_page": per_page,
            "page": max(1, page),
        }
        if sort:
            params["sort"] = sort

        response = self._get(self.SEARCH_REPOSITORIES_URL, params=params)
        payload = response.json()
        items = payload.get("items", [])
        return [self._repo_from_item(item) for item in items[:per_page]]

    def get_repository(self, full_name: str) -> RepoCandidate:
        response = self._get(f"{self.API_BASE_URL}/repos/{full_name}")
        return self._repo_from_item(response.json())

    def get_owner_profile(self, owner: str) -> dict | None:
        response = self._get(f"{self.API_BASE_URL}/users/{owner}", allow_not_found=True)
        if response is None:
            return None
        return response.json()

    def get_readme(self, full_name: str) -> str | None:
        response = self._get(f"{self.API_BASE_URL}/repos/{full_name}/readme", allow_not_found=True)
        if response is None:
            return None

        payload = response.json()
        content = payload.get("content")
        if not content:
            return None

        encoding = (payload.get("encoding") or "").lower()
        if encoding != "base64":
            return content

        try:
            decoded = base64.b64decode(content, validate=False)
        except (ValueError, TypeError):
            return None
        return decoded.decode("utf-8", errors="replace")

    def get_releases(self, full_name: str, limit: int = 3) -> list[dict]:
        if limit <= 0:
            return []

        response = self._get(
            f"{self.API_BASE_URL}/repos/{full_name}/releases",
            params={"per_page": limit},
        )
        releases = response.json()
        return [
            {
                "tag_name": release.get("tag_name"),
                "name": release.get("name"),
                "published_at": release.get("published_at"),
                "html_url": release.get("html_url"),
                "body": self._summarize_text(release.get("body") or "", limit=500),
            }
            for release in releases[:limit]
        ]

    def get_open_issues(self, full_name: str, limit: int = 5) -> list[dict]:
        if limit <= 0:
            return []

        response = self._get(
            f"{self.API_BASE_URL}/repos/{full_name}/issues",
            params={"state": "open", "per_page": limit},
        )
        issues = response.json()
        return [
            {
                "title": issue.get("title"),
                "html_url": issue.get("html_url"),
                "created_at": issue.get("created_at"),
                "comments": issue.get("comments") or 0,
            }
            for issue in issues
            if "pull_request" not in issue
        ][:limit]

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> requests.Response | None:
        last_error: requests.exceptions.RequestException | None = None
        response: requests.Response | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=20,
                )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                self._sleep_before_retry(attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                self._sleep_before_retry(attempt, response=response)
                continue
            break

        if response is None:
            detail = f"{last_error}" if last_error else "unknown network error"
            raise RuntimeError(
                f"GitHub API network error while requesting {url} after {self.max_retries} attempts: {detail}"
            ) from last_error

        if allow_not_found and response.status_code == 404:
            return None

        if response.status_code >= 400:
            self._raise_http_error(response)

        return response

    def _sleep_before_retry(self, attempt: int, response: requests.Response | None = None) -> None:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        delay = self.retry_delay_seconds * (2 ** max(0, attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        if delay > 0:
            time.sleep(min(delay, 8.0))

    def _raise_http_error(self, response: requests.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_at = response.headers.get("X-RateLimit-Reset")
        response_text = response.text

        lower_response_text = response_text.lower()
        is_rate_limited = (
            response.status_code == 429
            or (response.status_code == 403 and remaining == "0")
            or "rate limit" in lower_response_text
        )

        if is_rate_limited:
            reset_message = ""
            if reset_at:
                try:
                    reset_dt = datetime.fromtimestamp(int(reset_at), tz=timezone.utc)
                    reset_message = f" Rate limit resets at {reset_dt.isoformat()}."
                except ValueError:
                    reset_message = f" Rate limit reset timestamp: {reset_at}."
            raise RuntimeError(
                "GitHub API rate limit exceeded."
                f"{reset_message} Configure GITHUB_PERSONAL_ACCESS_TOKEN for a higher limit."
                f" HTTP {response.status_code}: {response_text}"
            )

        raise RuntimeError(f"GitHub API request failed with HTTP {response.status_code}: {response_text}")

    def _repo_from_item(self, item: Dict[str, Any]) -> RepoCandidate:
        owner_payload = item.get("owner") or {}
        license_payload = item.get("license") or {}
        html_url = item.get("html_url") or ""

        return RepoCandidate(
            full_name=item.get("full_name") or "",
            name=item.get("name") or "",
            owner=owner_payload.get("login") or "",
            html_url=html_url,
            url=html_url,
            description=item.get("description"),
            stars=item.get("stargazers_count") or 0,
            stargazers_count=item.get("stargazers_count"),
            watchers_count=item.get("watchers_count"),
            forks=item.get("forks_count") or 0,
            open_issues=item.get("open_issues_count"),
            language=item.get("language"),
            topics=item.get("topics") or [],
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
            pushed_at=item.get("pushed_at"),
            default_branch=item.get("default_branch"),
            license_name=license_payload.get("name"),
            homepage=item.get("homepage"),
        )

    def _summarize_text(self, value: str, limit: int) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."
