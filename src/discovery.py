from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from .github_client import GitHubClient
from .models import RepoCandidate


class DiscoveryService:
    def __init__(self, github_client: GitHubClient, keywords: List[str]) -> None:
        self.github_client = github_client
        self.keywords = keywords
        self.warnings: list[str] = []

    def discover(self, limit_per_keyword: int = 10) -> List[RepoCandidate]:
        candidates_by_full_name: dict[str, RepoCandidate] = {}
        today = datetime.now(timezone.utc).date()
        recent_push_since = (today - timedelta(days=30)).isoformat()
        recent_created_since = (today - timedelta(days=180)).isoformat()
        tooling_keywords = ["developer tools", "productivity tool", "cli tool", "browser extension", "terminal tool"]
        tooling_keyword_keys = {keyword.casefold() for keyword in tooling_keywords}

        for keyword in self._expanded_keywords(tooling_keywords):
            is_tooling_keyword = keyword.casefold() in tooling_keyword_keys
            discovery_queries = [
                {
                    "query": f"{keyword} stars:>50 pushed:>2025-01-01",
                    "reason": "baseline",
                    "sorts": ["stars", None],
                },
                {
                    "query": f"{keyword} stars:50..10000 pushed:>{recent_push_since}",
                    "reason": "recent_active",
                    "sorts": ["updated", None],
                },
                {
                    "query": f"{keyword} stars:50..10000 created:>{recent_created_since}",
                    "reason": "newly_created",
                    "sorts": ["updated", "stars", None],
                },
            ]
            if is_tooling_keyword:
                discovery_queries.append(
                    {
                        "query": f"{keyword} stars:50..10000 pushed:>{recent_push_since}",
                        "reason": "practical_tool",
                        "sorts": [None, "updated"],
                    }
                )

            for discovery_query in discovery_queries:
                for sort in discovery_query["sorts"]:
                    try:
                        results = self.github_client.search_repositories(
                            discovery_query["query"],
                            limit=limit_per_keyword,
                            sort=sort,
                            order="desc",
                        )
                    except RuntimeError as exc:
                        self.warnings.append(
                            f"Discovery query failed for {discovery_query['reason']} "
                            f"({discovery_query['query']}, sort={sort or 'best_match'}): {exc}"
                        )
                        if candidates_by_full_name:
                            return list(candidates_by_full_name.values())
                        raise

                    reason = discovery_query["reason"]
                    for candidate in results:
                        if not candidate.full_name:
                            continue
                        candidate.discovery_reason = reason
                        existing = candidates_by_full_name.get(candidate.full_name)
                        if existing is None:
                            candidates_by_full_name[candidate.full_name] = candidate
                            continue
                        existing.discovery_reason = self._merge_discovery_reason(
                            existing.discovery_reason,
                            reason,
                        )

        return list(candidates_by_full_name.values())

    def _merge_discovery_reason(self, current: str | None, new_reason: str) -> str:
        reasons = [reason.strip() for reason in (current or "").split(",") if reason.strip()]
        if new_reason not in reasons:
            reasons.append(new_reason)
        return ",".join(reasons)

    def _expanded_keywords(self, extra_keywords: list[str]) -> list[str]:
        seen: set[str] = set()
        expanded: list[str] = []
        for keyword in [*self.keywords, *extra_keywords]:
            normalized = keyword.strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            expanded.append(normalized)
        return expanded
