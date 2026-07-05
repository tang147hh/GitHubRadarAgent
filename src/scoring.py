from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from .models import RepoCandidate, RepoScore


class ScoringService:
    """Deterministic heuristic scoring for discovered GitHub repositories."""

    STRONG_RELEVANCE_KEYWORDS = [
        "agent",
        "agents",
        "llm",
        "mcp",
        "rag",
        "ai",
        "openai",
        "langchain",
        "workflow",
        "automation",
        "multi-agent",
        "multiagent",
    ]
    TRENDING_TECH_KEYWORDS = [
        "agentic",
        "ai-agent",
        "ai-agents",
        "claude",
        "codex",
        "deep-research",
        "genai",
        "gpt",
        "langgraph",
        "mcp-client",
        "mcp-server",
        "orchestration",
        "rag",
        "self-hosted",
        "workflow-automation",
    ]
    TOOL_VALUE_KEYWORDS = [
        "cli",
        "tool",
        "productivity",
        "automation",
        "self-hosted",
        "self hosted",
        "extension",
        "terminal",
        "workflow",
        "developer tools",
        "developer-tool",
        "devtools",
        "devtool",
        "obsidian",
        "chrome",
    ]

    def score_candidates(self, candidates: list[RepoCandidate]) -> list[RepoScore]:
        scores = [self.score_candidate(candidate) for candidate in candidates]
        return sorted(scores, key=lambda score: score.total_score, reverse=True)

    def score_candidate(self, candidate: RepoCandidate) -> RepoScore:
        reasons: list[str] = []
        warnings: list[str] = []

        growth_score = self._score_growth(candidate, reasons)
        velocity_score = self._score_velocity(candidate, reasons)
        freshness_score = self._score_freshness(candidate, reasons, warnings)
        relevance_score = self._score_relevance(candidate, reasons)
        quality_score = self._score_quality(candidate, reasons, warnings)
        activity_score = self._score_activity(candidate, reasons, warnings)
        communication_score = self._score_communication(candidate, relevance_score, reasons)

        total_score = (
            growth_score
            + velocity_score
            + freshness_score
            + relevance_score
            + quality_score
            + activity_score
            + communication_score
        )

        return RepoScore(
            full_name=candidate.full_name,
            html_url=candidate.html_url,
            total_score=round(total_score, 2),
            growth_score=round(growth_score, 2),
            velocity_score=round(velocity_score, 2),
            freshness_score=round(freshness_score, 2),
            relevance_score=round(relevance_score, 2),
            quality_score=round(quality_score, 2),
            activity_score=round(activity_score, 2),
            communication_score=round(communication_score, 2),
            discovery_reason=candidate.discovery_reason,
            reasons=reasons,
            warnings=warnings,
        )

    def _score_growth(self, candidate: RepoCandidate, reasons: list[str]) -> float:
        stars = candidate.stars or 0
        forks = candidate.forks or 0

        if stars >= 50000:
            score = 18.0
            reasons.append("Star 规模超过 50000")
        elif stars >= 10000:
            score = 16.0
            reasons.append("Star 规模超过 10000")
        elif stars >= 5000:
            score = 14.0
            reasons.append("Star 规模超过 5000")
        elif stars >= 1000:
            score = 11.0
            reasons.append("Star 规模超过 1000")
        elif stars >= 300:
            score = 8.0
            reasons.append("Star 规模超过 300")
        elif stars >= 50:
            score = 5.0
            reasons.append("Star 规模超过 50")
        else:
            score = 2.0

        fork_bonus = 0.0
        if forks >= 10000:
            fork_bonus = 1.0
        elif forks >= 3000:
            fork_bonus = 0.8
        elif forks >= 1000:
            fork_bonus = 0.6
        elif forks >= 100:
            fork_bonus = 0.4

        if fork_bonus:
            reasons.append(f"Fork 数达到 {forks}")

        return min(18.0, score + fork_bonus)

    def _score_velocity(self, candidate: RepoCandidate, reasons: list[str]) -> float:
        stars = candidate.stars or candidate.stargazers_count or 0
        created_at = self._parse_github_datetime(candidate.created_at)
        discovery_reason = (candidate.discovery_reason or "").lower()
        score = 0.0

        if "recent_active" in discovery_reason or "recent_growth" in discovery_reason:
            score += 2.5
            reasons.append("近期活跃候选")
        if "newly_created" in discovery_reason:
            score += 2.5
            reasons.append("近期创建候选")
        if "practical_tool" in discovery_reason or "active_tooling" in discovery_reason:
            score += 1.0
            reasons.append("活跃工具候选")

        if created_at is None:
            if stars >= 1000:
                score += 2.0
            return min(17.0, score)

        age_days = max(1, (self._reference_date() - created_at).days)
        stars_per_day = stars / age_days

        if age_days <= 180 and stars >= 500:
            score += 6.0
            reasons.append("创建时间较新且 Star 密度较高")
        elif age_days <= 365 and stars >= 1000:
            score += 5.0
            reasons.append("一年内创建且 Star 密度较高")
        elif age_days <= 730 and stars >= 2000:
            score += 3.0

        if stars_per_day >= 20:
            score += 6.0
            reasons.append(f"平均 Star 增长密度约 {stars_per_day:.1f}/天")
        elif stars_per_day >= 8:
            score += 4.0
            reasons.append(f"平均 Star 增长密度约 {stars_per_day:.1f}/天")
        elif stars_per_day >= 2:
            score += 2.0

        if age_days <= 180 and 100 <= stars < 500:
            score += 2.0
            reasons.append("新项目已获得早期关注")

        return min(17.0, score)

    def _score_freshness(
        self,
        candidate: RepoCandidate,
        reasons: list[str],
        warnings: list[str],
    ) -> float:
        latest_timestamp = candidate.pushed_at or candidate.updated_at
        latest_date = self._parse_github_datetime(latest_timestamp)

        if latest_date is None:
            warnings.append("缺少新鲜度时间戳")
            return 1.0

        days = max(0, (self._reference_date() - latest_date).days)
        if days <= 7:
            reasons.append("最近 7 天仍活跃")
            return 10.0
        if days <= 30:
            reasons.append("最近 30 天仍活跃")
            return 8.0
        if days <= 90:
            reasons.append("最近 90 天仍活跃")
            return 5.0
        if days <= 180:
            return 3.0
        return 1.0

    def _score_relevance(self, candidate: RepoCandidate, reasons: list[str]) -> float:
        text = self._keyword_text(candidate)
        ai_matched = self._matched_keywords(text, self.STRONG_RELEVANCE_KEYWORDS)
        tool_matched = self._matched_keywords(text, self.TOOL_VALUE_KEYWORDS)

        ai_score = min(25.0, 3.0 + len(ai_matched) * 3.0)
        if any(keyword in ai_matched for keyword in ("agent", "agents", "multi-agent", "multiagent")):
            ai_score += 3.0
        if any(keyword in ai_matched for keyword in ("llm", "mcp", "rag", "openai", "langchain")):
            ai_score += 2.0

        tool_score = min(25.0, 5.0 + len(tool_matched) * 3.0)
        if any(keyword in tool_matched for keyword in ("cli", "terminal", "developer tools", "devtools", "chrome", "extension")):
            tool_score += 3.0
        if any(keyword in tool_matched for keyword in ("automation", "workflow", "productivity", "self-hosted", "self hosted")):
            tool_score += 2.0

        score = min(22.0, max(ai_score, tool_score))
        if ai_matched:
            reasons.append(f"AI/Agent 关键词命中 {len(ai_matched)} 个：{', '.join(ai_matched[:6])}")
        if tool_matched:
            reasons.append(f"实用工具关键词命中 {len(tool_matched)} 个：{', '.join(tool_matched[:6])}")

        return score

    def _score_quality(
        self,
        candidate: RepoCandidate,
        reasons: list[str],
        warnings: list[str],
    ) -> float:
        score = 0.0
        description = (candidate.description or "").strip()
        topics = candidate.topics or []
        stars = candidate.stars or 0
        forks = candidate.forks or 0
        open_issues = candidate.open_issues or 0

        if description:
            score += 4.0
            reasons.append("description 完整")
        else:
            warnings.append("description 为空")

        if len(topics) >= 8:
            score += 4.0
            reasons.append("topics 数量丰富")
        elif len(topics) >= 3:
            score += 3.0
            reasons.append("topics 数量不少于 3 个")
        elif topics:
            score += 1.0

        if candidate.license_name:
            score += 4.0
            reasons.append("包含 license")
        else:
            warnings.append("缺少 license")

        if forks > 0:
            stars_per_fork = stars / forks
            if 3 <= stars_per_fork <= 20:
                score += 4.0
                reasons.append("stars/forks 比例健康")
            elif 1 <= stars_per_fork < 3 or 20 < stars_per_fork <= 40:
                score += 2.0
        elif stars >= 50:
            score += 1.0

        if open_issues > 1000:
            score -= 3.0
            warnings.append("open issues 较多")
        elif open_issues > 300:
            score -= 1.5
            warnings.append("open issues 偏多")
        elif open_issues <= 100:
            score += 2.0
            reasons.append("open issues 控制较好")
        else:
            score += 1.0

        return max(0.0, min(18.0, score))

    def _score_activity(
        self,
        candidate: RepoCandidate,
        reasons: list[str],
        warnings: list[str],
    ) -> float:
        latest_timestamp = candidate.pushed_at or candidate.updated_at
        latest_date = self._parse_github_datetime(latest_timestamp)

        if latest_date is None:
            warnings.append("缺少 pushed_at/updated_at")
            return 1.0

        days = max(0, (self._reference_date() - latest_date).days)

        if days <= 30:
            reasons.append("最近 30 天有更新")
            return 10.0
        if days <= 90:
            reasons.append("最近 90 天有更新")
            return 8.0
        if days <= 180:
            reasons.append("最近 180 天有更新")
            return 5.0
        if days <= 365:
            warnings.append("最近更新超过 180 天")
            return 3.0

        warnings.append("最近更新超过 365 天")
        return 1.0

    def _score_communication(
        self,
        candidate: RepoCandidate,
        relevance_score: float,
        reasons: list[str],
    ) -> float:
        score = 0.0
        description = (candidate.description or "").strip()
        repo_name = candidate.name or candidate.full_name.split("/")[-1]
        topics = [topic.lower() for topic in candidate.topics or []]
        topic_text = " ".join(topics)

        if 30 <= len(description) <= 160:
            score += 4.0
            reasons.append("description 简洁明确")
        elif description:
            score += 2.0
        if self._description_explains_use(description):
            score += 2.0
            reasons.append("description 能直接说明用途")

        name_words = re.split(r"[-_\s]+", repo_name)
        if 1 <= len([word for word in name_words if word]) <= 3 and len(repo_name) <= 32:
            score += 3.0
            reasons.append("项目名称容易理解")
        elif len(repo_name) <= 48:
            score += 1.5

        trending_matches = self._matched_keywords(topic_text, self.TRENDING_TECH_KEYWORDS)
        if trending_matches:
            score += min(4.0, len(trending_matches) * 1.5)
            reasons.append(f"包含传播友好的技术词：{', '.join(trending_matches[:4])}")

        tool_matches = self._matched_keywords(" ".join([topic_text, description.lower()]), self.TOOL_VALUE_KEYWORDS)
        if tool_matches:
            score += min(4.0, len(tool_matches) * 1.25)
            reasons.append(f"包含实用工具传播词：{', '.join(tool_matches[:4])}")

        if (candidate.stars or 0) >= 10000 and relevance_score >= 18:
            score += 4.0
            reasons.append("高 star 且 AI 相关度高")
        elif (candidate.stars or 0) >= 1000 and relevance_score >= 15:
            score += 2.0
        elif (
            (candidate.stars or 0) < 1000
            and relevance_score >= 12
            and description
            and self._parse_github_datetime(candidate.pushed_at or candidate.updated_at) is not None
        ):
            score += 1.5
            reasons.append("star 不高但定位清晰且近期可继续跟踪")

        return min(5.0, score / 3.0)

    def _keyword_text(self, candidate: RepoCandidate) -> str:
        values = [
            candidate.full_name,
            candidate.description or "",
            candidate.language or "",
            " ".join(candidate.topics or []),
        ]
        return " ".join(values).lower()

    def _matched_keywords(self, text: str, keywords: Iterable[str]) -> list[str]:
        matched: list[str] = []
        normalized_text = text.lower()
        for keyword in keywords:
            normalized_keyword = keyword.lower()
            pattern = re.escape(normalized_keyword).replace("\\-", "[-_\\s]?")
            if len(normalized_keyword) <= 2 and normalized_keyword.isalnum():
                pattern = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
            if re.search(pattern, normalized_text):
                matched.append(keyword)
        return matched

    def _description_explains_use(self, description: str) -> bool:
        if not description:
            return False
        lowered = description.lower()
        action_words = [
            "build",
            "create",
            "generate",
            "manage",
            "automate",
            "monitor",
            "debug",
            "test",
            "deploy",
            "search",
            "convert",
            "sync",
            "用于",
            "帮助",
            "自动",
            "管理",
            "生成",
        ]
        return len(description.strip()) >= 20 and any(word in lowered for word in action_words)

    def _parse_github_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    def _reference_date(self) -> datetime:
        return datetime.now(timezone.utc)
