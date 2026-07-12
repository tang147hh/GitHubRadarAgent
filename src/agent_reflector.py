from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from .agent_models import (
    AgentPlanStep,
    AgentRecoveryAction,
    AgentReflection,
    AgentRun,
    AgentToolResult,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class AgentReflector:
    """Deterministic post-step checks and bounded recovery decisions."""

    def reflect(self, run: AgentRun, step: AgentPlanStep, tool_result: AgentToolResult) -> AgentReflection:
        observations = [tool_result.result_summary]
        observations.extend(f"警告：{warning}" for warning in self._warnings(tool_result))
        issues: list[str] = []
        actions: list[AgentRecoveryAction] = []
        decision = "结果已通过确定性反思检查。"
        status = "pass"

        if not tool_result.success:
            return self._reflect_failure(run, step, tool_result, observations)

        payload = tool_result.payload if isinstance(tool_result.payload, dict) else {}
        tool_name = tool_result.tool_name

        if tool_name == "news.collect":
            total_count = self._int(payload.get("total_count"))
            fresh_count = self._int(payload.get("fresh_count"))
            if total_count < 10 or fresh_count < 5:
                issues.append(f"新闻数量不足（总数={total_count}，新鲜内容={fresh_count}）。")
                if int(step.arguments.get("hours") or 24) < 72 or int(step.arguments.get("limit") or 0) < 100:
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "hours": 72, "limit": 100}, "将采集窗口扩大到 72 小时，并至少采集 100 条内容。"))
                    decision = "扩大时间窗口并提高数量上限后重新采集新闻。"

        elif tool_name == "news.score":
            count = self._int(payload.get("recommended_count"))
            if count < 5:
                issues.append(f"只有 {count} 条新闻达到推荐阈值。")
                if float(step.arguments.get("min_score", 60)) > 40:
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "min_score": 40}, "将推荐阈值降低到 40。"))
                    decision = "使用 min_score=40 重新为新闻评分。"

        elif tool_name == "news.build_events":
            count = self._int(payload.get("recommended_event_count"))
            if count < 5:
                issues.append(f"只构建了 {count} 个推荐新闻事件。")
                if float(step.arguments.get("min_score", 60)) > 40:
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "min_score": 40}, "将事件阈值降低到 40。"))
                    decision = "使用 min_score=40 重新构建新闻事件。"

        elif tool_name == "news.fetch_detail":
            availability = str(payload.get("content_availability") or "unknown")
            if availability != "full_text":
                observations.append("目前只有摘要或元数据；后续写作不能暗示已读取完整正文。")
                decision = "继续使用摘要和元数据，并明确说明证据范围限制。"

        elif tool_name == "news.write_article":
            word_count = self._int(payload.get("word_count"))
            publish_ready = payload.get("publish_ready")
            if publish_ready is False or (word_count and word_count < 800):
                issues.append(f"文章尚未达到发布要求或篇幅过短（字数={word_count}）。")
                actions.append(self._insert(run, step, "news.review_article", {"latest": True, "polish": True, "threshold": 80}, "评审并润色尚未完成的文章。"))
                decision = "插入文章评审与润色步骤。"

        elif tool_name == "news.review_article":
            score = self._float(payload.get("quality_score"))
            if score < 80:
                issues.append(f"文章质量得分 {score:.1f} 低于 80。")
                if not self._is_recovery(step):
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "latest": True, "polish": True, "threshold": 80}, "按 80 分阈值再次润色并评审文章。"))
                    decision = "启用润色后再次评审文章。"

        elif tool_name == "news.review_digest":
            score = self._float(payload.get("quality_score"))
            if score < 80 or payload.get("publish_ready") is False:
                issues.append(f"新闻摘要质量得分 {score:.1f} 低于 80，或尚未达到发布要求。")
                if not self._is_recovery(step):
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "polish": True, "threshold": 80}, "按 80 分阈值再次润色并评审新闻摘要。"))
                    decision = "启用润色后再次评审新闻摘要。"

        elif tool_name == "news.write_digest":
            count = self._int(payload.get("event_count"))
            if count < 3:
                issues.append(f"新闻摘要只包含 {count} 个事件。")
                if not self._is_recovery(step):
                    arguments = {
                        "hours": 72,
                        "limit": 100,
                        "translate": True,
                        "translate_limit": 50,
                        "follow_up_steps": [
                            {"tool_name": "news.score", "arguments": {"top": 30, "min_score": 40}},
                            {"tool_name": "news.build_events", "arguments": {"top": 20, "min_score": 40}},
                            {"tool_name": "news.write_digest", "arguments": dict(step.arguments)},
                        ],
                    }
                    actions.append(self._insert(run, step, "news.collect", arguments, "使用更长时间窗口和更低阈值重新构建新闻摘要。"))
                    decision = "插入一次有次数限制的新闻摘要恢复流程。"

        elif tool_name == "github.discover_projects":
            count = self._int(payload.get("candidate_count"))
            article_top = self._article_top(run)
            if count < max(10, article_top):
                issues.append(f"只发现了 {count} 个 GitHub 候选项目。")
                current_limit = int(step.arguments.get("limit_per_keyword") or 3)
                if current_limit < 8:
                    next_limit = 5 if current_limit < 5 else 8
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "limit_per_keyword": next_limit}, f"将每个关键词的发现数量上限提高到 {next_limit}。"))
                    decision = f"使用 limit_per_keyword={next_limit} 重新发现项目。"

        elif tool_name == "github.score_projects":
            count = self._int(payload.get("score_count"))
            if count < self._article_top(run):
                issues.append(f"只有 {count} 个项目完成评分，最终生成的文章可能少于预期。")
                decision = "使用现有已评分项目继续执行。"

        elif tool_name == "github.select_projects":
            count = self._int(payload.get("selected_count"))
            article_top = int(step.arguments.get("article_top") or self._article_top(run))
            if count < article_top:
                issues.append(f"计划选择 {article_top} 个项目，实际选择了 {count} 个。")
                if self._goal_forbids_repeats(run.goal):
                    observations.append("目标明确要求不重复，因此继续禁用近期项目补位。")
                    decision = "为遵守不重复约束，使用较少项目继续执行。"
                elif not bool(step.arguments.get("allow_recent_fallback")):
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "allow_recent_fallback": True}, "允许使用近期项目补足缺少的文章名额。"))
                    decision = "启用近期项目补位后重新选择项目。"

        elif tool_name == "github.research_selected":
            requested = self._strings(payload.get("selected_repo_full_names"))
            researched = self._int(payload.get("note_count"))
            if requested and researched < len(requested):
                issues.append(f"请求调研 {len(requested)} 个项目，成功完成 {researched} 个。")
                decision = "使用已成功调研的项目继续执行。"

        elif tool_name == "github.write_articles":
            count = self._int(payload.get("draft_count"))
            requested = int(step.arguments.get("top") or self._article_top(run))
            available = len(self._strings(step.arguments.get("selected_repo_full_names"))) or count
            if count < requested:
                issues.append(f"计划生成 {requested} 篇 GitHub 文章，实际生成了 {count} 篇。")
                retry_top = min(requested, available)
                if retry_top > 0 and retry_top != requested and not self._is_recovery(step):
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "top": retry_top}, "按照实际可用的已调研项目数量重新写作。"))
                    decision = f"使用 top={retry_top} 重新撰写文章。"
                else:
                    decision = "使用已生成的文章继续执行。"

        elif tool_name == "github.review_articles":
            quality_score = self._float(payload.get("minimum_quality_score"), default=100)
            ready_count = self._int(payload.get("publish_ready_count"), default=self._int(payload.get("article_count")))
            article_count = self._int(payload.get("article_count"))
            if quality_score < 80 or ready_count < article_count:
                issues.append(f"已评审文章未达到质量阈值（最低分={quality_score:.1f}，可发布={ready_count}/{article_count}）。")
                if not self._is_recovery(step):
                    actions.append(self._insert(run, step, tool_name, {**step.arguments, "threshold": 80}, "按 80 分阈值再次评审质量不足的 GitHub 文章。"))
                    decision = "按 80 分阈值再次评审 GitHub 文章。"

        elif tool_name == "github.package_articles":
            packages = payload.get("packages") if isinstance(payload.get("packages"), list) else []
            missing = not packages or any(not item.get("packaged_article_path") for item in packages if isinstance(item, dict))
            if missing:
                issues.append("一个或多个 GitHub 文章发布包路径缺失。")
                if not self._is_recovery(step):
                    actions.append(self._insert(run, step, tool_name, dict(step.arguments), "由于发布包产物缺失，重新执行一次文章打包。"))
                    decision = "重新执行一次 GitHub 文章打包。"

        if actions:
            if run.recovery_count >= run.max_recovery_count:
                observations.append("恢复次数已用完，不再插入额外步骤。")
                issues.append("max_recovery_count_reached")
                actions = []
                decision = "已达到最大恢复次数，不再执行恢复步骤并继续运行。"
            else:
                status = "needs_recovery"

        return self._reflection(run, step, status, observations, issues, actions, decision)

    def _reflect_failure(self, run: AgentRun, step: AgentPlanStep, result: AgentToolResult, observations: list[str]) -> AgentReflection:
        error = str(result.error or result.result_summary or "unknown error")
        lowered = error.lower()
        invalid_markers = ("valueerror", "required", "invalid", "missing", "keyerror", "unknown agent tool")
        network_markers = ("rate limit", "429", "timeout", "timed out", "connection", "network", "502", "503")
        repo_url = str(step.arguments.get("repo_url") or "")
        invalid_custom_url = step.tool_name == "github.write_custom_article" and not re.match(
            r"^https?://github\.com/[^/\s]+/[^/\s]+/?$", repo_url, re.IGNORECASE
        )
        if invalid_custom_url or any(marker in lowered for marker in invalid_markers):
            return self._reflection(run, step, "unrecoverable", observations, [error], [], "工具输入不合法或缺少必要输入，停止本次运行。")
        if any(marker in lowered for marker in network_markers):
            if self._has_prior_snapshot(run, step.tool_name):
                observations.append("存在可用的历史快照，因此可以降级继续运行。")
                return self._reflection(run, step, "pass", observations, [error], [], "网络或限流失败后复用现有快照。")
            if run.recovery_count < run.max_recovery_count and not self._is_recovery(step):
                action = self._insert(run, step, step.tool_name, dict(step.arguments), "对暂时性的网络或限流失败重试一次。")
                return self._reflection(run, step, "needs_recovery", observations, [error], [action], "对暂时性的工具失败重试一次。")
        return self._reflection(run, step, "unrecoverable", observations, [error], [], "工具失败且没有确定性的恢复路径，停止本次运行。")

    def _reflection(self, run: AgentRun, step: AgentPlanStep, status: str, observations: list[str], issues: list[str], actions: list[AgentRecoveryAction], decision: str) -> AgentReflection:
        return AgentReflection(
            reflection_id=f"reflection_{len(run.reflections) + 1:02d}_{step.step_id}",
            run_id=run.run_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            created_at=_utc_now(),
            status=status,
            observations=self._unique(observations),
            issues=self._unique(issues),
            recovery_actions=actions,
            decision=decision,
        )

    def _insert(self, run: AgentRun, step: AgentPlanStep, tool_name: str, arguments: dict[str, Any], reason: str) -> AgentRecoveryAction:
        return AgentRecoveryAction(
            action_id=f"action_{len(run.reflections) + 1:02d}_{len(step.step_id)}_{tool_name.replace('.', '_')}",
            action_type="insert_step",
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
            inserted_after_step_id=step.step_id,
        )

    def _warnings(self, result: AgentToolResult) -> list[str]:
        warnings = list(result.warnings)
        payload_warnings = result.payload.get("warnings") if isinstance(result.payload, dict) else None
        if isinstance(payload_warnings, list):
            warnings.extend(str(item) for item in payload_warnings)
        elif payload_warnings:
            warnings.append(str(payload_warnings))
        return self._unique(warnings)

    def _article_top(self, run: AgentRun) -> int:
        for step in run.plan.steps:
            if step.tool_name == "github.select_projects":
                return int(step.arguments.get("article_top") or 3)
        return 3

    def _goal_forbids_repeats(self, goal: str) -> bool:
        lowered = goal.lower()
        return any(phrase in lowered for phrase in ("不重复", "不要重复", "不得重复", "no repeat", "without repeats", "no duplicates"))

    def _has_prior_snapshot(self, run: AgentRun, tool_name: str) -> bool:
        keyword = tool_name.split(".", 1)[-1].replace("_projects", "").replace("_articles", "")
        return any(keyword in artifact for artifact in run.artifacts)

    def _is_recovery(self, step: AgentPlanStep) -> bool:
        return step.step_id.startswith("recovery_")

    def _int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _strings(self, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
