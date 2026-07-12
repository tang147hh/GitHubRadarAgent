from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent_models import AgentPlan, AgentPlanStep, AgentRun, AgentTool, AgentToolResult
from src.agent_reflector import AgentReflector
from src.agent_runtime import AgentRuntime


def result(tool_name: str, payload: dict, *, success: bool = True) -> AgentToolResult:
    return AgentToolResult(
        call_id=f"call_{tool_name}",
        tool_name=tool_name,
        success=success,
        started_at="2026-07-12T00:00:00Z",
        finished_at="2026-07-12T00:00:01Z",
        result_summary=f"{tool_name} completed",
        payload=payload,
    )


def make_run(step: AgentPlanStep, *, goal: str = "AI 新闻", max_recovery_count: int = 3) -> AgentRun:
    plan = AgentPlan(
        plan_id="plan_test",
        skill_name="ai-news-article",
        goal=goal,
        steps=[step],
        generated_at="2026-07-12T00:00:00Z",
    )
    return AgentRun(
        run_id="run_test",
        goal=goal,
        skill_name=plan.skill_name,
        created_at="2026-07-12T00:00:00Z",
        plan=plan,
        max_recovery_count=max_recovery_count,
    )


class FakePlanner:
    def plan(self, goal: str, context=None) -> AgentPlan:
        return AgentPlan(
            plan_id="plan_fake",
            skill_name="ai-news-article",
            goal=goal,
            steps=[AgentPlanStep(step_id="step_01", tool_name="news.collect", arguments={"hours": 24, "limit": 3})],
            generated_at="2026-07-12T00:00:00Z",
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool_name: str, arguments: dict) -> AgentToolResult:
        self.calls.append((tool_name, dict(arguments)))
        if len(self.calls) == 1:
            return result(tool_name, {"total_count": 3, "fresh_count": 2})
        return result(tool_name, {"total_count": 30, "fresh_count": 20})


class ConfirmationRegistry(FakeRegistry):
    def get(self, name: str) -> AgentTool:
        return AgentTool(
            name=name,
            skill_name="ai-news-article",
            description="Write an article.",
            side_effects=["writes outputs/article.md"],
            requires_confirmation=True,
        )


class AgentReflectorTests(unittest.TestCase):
    def test_news_collect_expands_window(self) -> None:
        step = AgentPlanStep(step_id="step_01", tool_name="news.collect", arguments={"hours": 24, "limit": 3})
        reflection = AgentReflector().reflect(make_run(step), step, result("news.collect", {"total_count": 3, "fresh_count": 2}))
        self.assertEqual(reflection.status, "needs_recovery")
        self.assertEqual(reflection.recovery_actions[0].arguments["hours"], 72)
        self.assertEqual(reflection.recovery_actions[0].arguments["limit"], 100)

    def test_recovery_budget_prevents_insertion(self) -> None:
        step = AgentPlanStep(step_id="step_01", tool_name="news.score", arguments={"min_score": 50})
        run = make_run(step, max_recovery_count=1)
        run.recovery_count = 1
        reflection = AgentReflector().reflect(run, step, result("news.score", {"recommended_count": 1}))
        self.assertEqual(reflection.status, "pass")
        self.assertEqual(reflection.recovery_actions, [])
        self.assertIn("max_recovery_count_reached", reflection.issues)

    def test_no_repeat_goal_disables_recent_fallback(self) -> None:
        step = AgentPlanStep(
            step_id="step_03",
            tool_name="github.select_projects",
            arguments={"article_top": 3, "allow_recent_fallback": False},
        )
        run = make_run(step, goal="生成 3 篇 GitHub 文章，不重复以前项目")
        reflection = AgentReflector().reflect(run, step, result("github.select_projects", {"selected_count": 1}))
        self.assertEqual(reflection.status, "pass")
        self.assertEqual(reflection.recovery_actions, [])
        self.assertIn("不重复", reflection.decision)

    def test_low_quality_article_inserts_polish_review(self) -> None:
        step = AgentPlanStep(step_id="step_05", tool_name="news.review_article", arguments={"threshold": 80})
        reflection = AgentReflector().reflect(make_run(step), step, result("news.review_article", {"quality_score": 62, "publish_ready": False}))
        self.assertEqual(reflection.status, "needs_recovery")
        self.assertTrue(reflection.recovery_actions[0].arguments["polish"])

    def test_github_candidate_shortage_expands_discovery(self) -> None:
        step = AgentPlanStep(step_id="step_01", tool_name="github.discover_projects", arguments={"limit_per_keyword": 3})
        reflection = AgentReflector().reflect(make_run(step), step, result("github.discover_projects", {"candidate_count": 4}))
        self.assertEqual(reflection.status, "needs_recovery")
        self.assertEqual(reflection.recovery_actions[0].arguments["limit_per_keyword"], 5)

    def test_missing_github_package_is_retried_once(self) -> None:
        step = AgentPlanStep(step_id="step_08", tool_name="github.package_articles", arguments={"top": 3})
        reflection = AgentReflector().reflect(make_run(step), step, result("github.package_articles", {"packages": []}))
        self.assertEqual(reflection.status, "needs_recovery")
        recovery_step = AgentPlanStep(step_id="recovery_1_github_package_articles", tool_name=step.tool_name, arguments=step.arguments)
        second = AgentReflector().reflect(make_run(recovery_step), recovery_step, result("github.package_articles", {"packages": []}))
        self.assertEqual(second.status, "pass")


class AgentRuntimeReflectionTests(unittest.TestCase):
    def test_runtime_inserts_and_executes_recovery_step(self) -> None:
        registry = FakeRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = AgentRuntime(planner=FakePlanner(), registry=registry, storage_dir=Path(temp_dir))
            run = runtime.run_goal("AI 新闻", max_recovery_count=3)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.recovery_count, 1)
        self.assertEqual(len(run.reflections), 2)
        self.assertEqual(run.plan.steps[1].step_id, "recovery_1_news_collect")
        self.assertEqual(registry.calls[1][1]["hours"], 72)

    def test_runtime_can_disable_reflection(self) -> None:
        registry = FakeRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = AgentRuntime(planner=FakePlanner(), registry=registry, storage_dir=Path(temp_dir))
            run = runtime.run_goal("AI 新闻", reflection_enabled=False)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.reflections, [])
        self.assertEqual(run.recovery_count, 0)
        self.assertEqual(len(registry.calls), 1)

    def test_runtime_waits_for_approval_then_resumes(self) -> None:
        registry = ConfirmationRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = AgentRuntime(planner=FakePlanner(), registry=registry, storage_dir=Path(temp_dir))
            waiting = runtime.run_goal("AI 新闻", reflection_enabled=False, auto_approve=False)
            self.assertEqual(waiting.status, "needs_input")
            self.assertEqual(waiting.plan.steps[0].status, "waiting_approval")
            self.assertEqual(registry.calls, [])
            approved = runtime.approve_run(waiting.run_id, approved=True, notes="continue")
            self.assertEqual(approved.plan.steps[0].status, "approved")
            completed = runtime.resume_run(waiting.run_id)
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(len(registry.calls), 1)
        self.assertTrue(completed.approval_history[0]["approved"])

    def test_runtime_rejection_fails_without_tool_call(self) -> None:
        registry = ConfirmationRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = AgentRuntime(planner=FakePlanner(), registry=registry, storage_dir=Path(temp_dir))
            waiting = runtime.run_goal("AI 新闻", reflection_enabled=False, auto_approve=False)
            rejected = runtime.approve_run(waiting.run_id, approved=False, notes="stop here")
        self.assertEqual(rejected.status, "failed")
        self.assertEqual(rejected.plan.steps[0].status, "rejected")
        self.assertEqual(rejected.error, "stop here")
        self.assertEqual(registry.calls, [])


if __name__ == "__main__":
    unittest.main()
