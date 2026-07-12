from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

from .agent_models import AgentPlan, AgentPlanStep


GITHUB_PROJECT_SKILL = "github-project-article"
AI_NEWS_SKILL = "ai-news-article"

GITHUB_REPO_URL_RE = re.compile(
    r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?(?:[^\s，。；、]*)?",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{secrets.token_hex(2)}"


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase.lower() in text for phrase in phrases)


class AgentPlanner:
    def plan(self, goal: str, context: dict[str, Any] | None = None) -> AgentPlan:
        context = context or {}
        clean_goal = (goal or "").strip()
        goal_text = clean_goal.lower()
        warnings: list[str] = []

        repo_url = self._parse_repo_url(clean_goal)
        if repo_url or "github.com" in goal_text:
            if not repo_url:
                warnings.append("github_url_not_parsed")
            return self._build_plan(
                skill_name=GITHUB_PROJECT_SKILL,
                goal=clean_goal,
                steps=[
                    (
                        "github.write_custom_article",
                        {
                            "repo_url": repo_url or "",
                            "direction_text": clean_goal,
                        },
                        "目标中包含 GitHub 仓库地址，因此生成一篇指定项目文章。",
                    )
                ],
                context=context,
                warnings=warnings,
            )

        if _contains_any(goal_text, ["ai 新闻", "新闻日报", "ai 圈新闻", "今日 ai"]):
            return self._build_plan(
                skill_name=AI_NEWS_SKILL,
                goal=clean_goal,
                steps=[
                    (
                        "news.collect",
                        {"hours": 24, "limit": 50, "translate": True, "translate_limit": 50},
                        "采集最近 24 小时的 AI 新闻。",
                    ),
                    (
                        "news.score",
                        {"top": 30, "min_score": 50},
                        "为已采集新闻评分并保留最有价值的候选内容。",
                    ),
                    (
                        "news.build_events",
                        {"top": 20, "min_score": 50},
                        "将相关新闻合并为事件卡片，供新闻摘要写作使用。",
                    ),
                    (
                        "news.write_digest",
                        {"top": 12},
                        "根据事件卡片撰写公众号风格的 AI 新闻摘要。",
                    ),
                    (
                        "news.review_digest",
                        {"threshold": 80, "polish": True},
                        "评审并润色新闻摘要，使其达到发布要求。",
                    ),
                ],
                context=context,
            )

        if _contains_any(goal_text, ["开源项目", "github 项目", "项目日报", "自动发现"]):
            return self._build_plan(
                skill_name=GITHUB_PROJECT_SKILL,
                goal=clean_goal,
                steps=[
                    (
                        "github.discover_projects",
                        {"limit_per_keyword": 3},
                        "发现 GitHub 候选项目。",
                    ),
                    (
                        "github.score_projects",
                        {"top": 30},
                        "为已发现的 GitHub 项目评分。",
                    ),
                    (
                        "github.select_projects",
                        {"article_top": 3, "cooldown_days": 30, "allow_recent_fallback": False},
                        "选择三个项目用于文章写作。",
                    ),
                    (
                        "github.research_selected",
                        {},
                        "调研已选择的 GitHub 项目。",
                    ),
                    (
                        "github.plan_content",
                        {"top": 3},
                        "为已选择的项目制定内容计划。",
                    ),
                    (
                        "github.write_articles",
                        {"top": 3},
                        "撰写三篇文章初稿。",
                    ),
                    (
                        "github.review_articles",
                        {"top": 3, "threshold": 80},
                        "评审并修改文章初稿。",
                    ),
                    (
                        "github.package_articles",
                        {"top": 3},
                        "打包可发布的文章与素材。",
                    ),
                ],
                context=context,
            )

        return self._build_plan(
            skill_name="",
            goal=clean_goal,
            steps=[],
            context=context,
            warnings=["unknown_goal"],
        )

    def _build_plan(
        self,
        *,
        skill_name: str,
        goal: str,
        steps: list[tuple[str, dict[str, Any], str]],
        context: dict[str, Any],
        warnings: list[str] | None = None,
    ) -> AgentPlan:
        argument_overrides = context.get("tool_arguments") if isinstance(context.get("tool_arguments"), dict) else {}
        plan_steps: list[AgentPlanStep] = []
        for index, (tool_name, arguments, reason) in enumerate(steps, start=1):
            merged_arguments = dict(arguments)
            override = argument_overrides.get(tool_name) if isinstance(argument_overrides, dict) else None
            if isinstance(override, dict):
                merged_arguments.update(override)
            plan_steps.append(
                AgentPlanStep(
                    step_id=f"step_{index:02d}",
                    tool_name=tool_name,
                    arguments=merged_arguments,
                    reason=reason,
                )
            )
        return AgentPlan(
            plan_id=_make_id("plan"),
            skill_name=skill_name,
            goal=goal,
            steps=plan_steps,
            generated_at=_utc_now(),
            generation_mode="deterministic",
            warnings=warnings or [],
        )

    def _parse_repo_url(self, goal: str) -> str | None:
        match = GITHUB_REPO_URL_RE.search(goal)
        if not match:
            return None
        return match.group(0).rstrip(".,，。)")
