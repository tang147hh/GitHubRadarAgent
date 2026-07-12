from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_models import AgentPlanStep, AgentRecoveryAction, AgentRun, AgentToolResult
from .agent_planner import AgentPlanner
from .agent_reflector import AgentReflector
from .agent_tools import ToolRegistry, build_default_tool_registry
from .config import get_settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"agentrun_{stamp}_{secrets.token_hex(2)}"


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _jsonable(value: Any) -> Any:
    value = _model_dump(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class AgentRuntime:
    def __init__(
        self,
        *,
        planner: AgentPlanner | None = None,
        registry: ToolRegistry | None = None,
        reflector: AgentReflector | None = None,
        storage_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self.planner = planner or AgentPlanner()
        self.registry = registry or build_default_tool_registry()
        self.reflector = reflector or AgentReflector()
        self.storage_dir = storage_dir or settings.workspace_dir / "agent_runs"

    @property
    def latest_path(self) -> Path:
        return self.storage_dir / "latest_agent_run.json"

    def create_run(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        *,
        max_recovery_count: int = 3,
        reflection_enabled: bool = True,
        auto_approve: bool = False,
    ) -> AgentRun:
        clean_goal = (goal or "").strip()
        if not clean_goal:
            raise ValueError("goal is required.")
        plan = self.planner.plan(clean_goal, context=context)
        run = AgentRun(
            run_id=_make_run_id(),
            goal=clean_goal,
            skill_name=plan.skill_name,
            status="planned",
            created_at=_utc_now(),
            plan=plan,
            warnings=list(plan.warnings),
            max_recovery_count=max(0, int(max_recovery_count)),
            reflection_enabled=reflection_enabled,
            auto_approve=auto_approve,
        )
        self.save_run(run)
        return run

    def execute_run(self, run_id: str) -> AgentRun:
        run = self.load_run(run_id)
        if not run.plan.steps:
            run.status = "needs_input"
            run.finished_at = _utc_now()
            run.error = "unknown_goal"
            if "unknown_goal" not in run.warnings:
                run.warnings.append("unknown_goal")
            run.observations.append("Agent 需要更明确的目标，才能选择 Skill 和工具。")
            self.save_run(run)
            return run

        run.status = "running"
        run.started_at = run.started_at or _utc_now()
        run.finished_at = None
        run.error = None
        self.save_run(run)

        index = 0
        while index < len(run.plan.steps):
            step = run.plan.steps[index]
            if step.status in {"succeeded", "skipped"}:
                index += 1
                continue
            tool = self.registry.get(step.tool_name) if hasattr(self.registry, "get") else None
            if tool is not None and tool.requires_confirmation and not run.auto_approve and step.status != "approved":
                return self._pause_for_approval(run, step, tool.description, tool.side_effects)
            step.status = "running"
            run.current_step_id = step.step_id
            self.save_run(run)

            result = self.registry.call(step.tool_name, step.arguments)
            step.tool_call_id = result.call_id
            step.artifacts = list(result.artifacts)
            step.error = result.error
            step.observation = self._observation_for_result(result)
            run.observations.append(step.observation)
            run.artifacts = self._merge_artifacts(run.artifacts, result.artifacts)
            run.warnings = self._merge_warnings(run.warnings, result.warnings)

            if result.success:
                self._apply_result_payload_to_plan(run, step, result, run.plan.steps[index + 1 :])
                step.status = "succeeded"
            else:
                step.status = "failed"

            if not run.reflection_enabled:
                if not result.success:
                    return self._fail_run(run, step, result.error or result.result_summary)
                self.save_run(run)
                index += 1
                continue

            reflection = self.reflector.reflect(run, step, result)
            run.reflections.append(reflection)
            run.observations.extend(reflection.observations[1:])
            run.warnings = self._merge_warnings(run.warnings, reflection.issues)

            if reflection.status == "unrecoverable":
                return self._fail_run(run, step, result.error or reflection.decision)

            if reflection.status == "needs_recovery":
                stop_requested = self._apply_recovery_actions(run, step, reflection.recovery_actions)
                if stop_requested:
                    return self._fail_run(run, step, reflection.decision)
            elif not result.success:
                step.status = "skipped"
                step.observation = f"{step.observation} {reflection.decision}"

            self.save_run(run)
            index += 1

        run.status = "succeeded"
        run.current_step_id = None
        self._clear_pending_approval(run)
        run.finished_at = _utc_now()
        self.save_run(run)
        return run

    def run_goal(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        *,
        max_recovery_count: int = 3,
        reflection_enabled: bool = True,
        auto_approve: bool = False,
    ) -> AgentRun:
        run = self.create_run(
            goal,
            context=context,
            max_recovery_count=max_recovery_count,
            reflection_enabled=reflection_enabled,
            auto_approve=auto_approve,
        )
        return self.execute_run(run.run_id)

    def approve_run(self, run_id: str, *, approved: bool, notes: str | None = None) -> AgentRun:
        run = self.load_run(run_id)
        step_id = run.pending_approval_step_id
        if run.status != "needs_input" or not step_id:
            raise ValueError("当前 Agent 运行没有等待审批的步骤。")
        step = next((item for item in run.plan.steps if item.step_id == step_id), None)
        if step is None or step.status != "waiting_approval":
            raise ValueError("等待审批的步骤不存在或已不再等待。")

        clean_notes = (notes or "").strip() or None
        run.approval_history.append(
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "approved": approved,
                "notes": clean_notes,
                "decided_at": _utc_now(),
            }
        )
        if approved:
            step.status = "approved"
            step.error = None
            step.observation = "工具执行已获批准，可以继续运行。"
            run.status = "running"
            run.error = None
            self._clear_pending_approval(run)
        else:
            step.status = "rejected"
            step.error = clean_notes or "用户已拒绝执行该工具。"
            step.observation = "用户已拒绝执行该工具。"
            run.status = "failed"
            run.error = step.error
            run.finished_at = _utc_now()
            run.current_step_id = step.step_id
            self._clear_pending_approval(run)
        self.save_run(run)
        return run

    def resume_run(self, run_id: str) -> AgentRun:
        run = self.load_run(run_id)
        if run.status == "needs_input" and run.pending_approval_step_id:
            raise ValueError("继续运行前，请先批准或拒绝当前等待审批的步骤。")
        if run.status in {"succeeded", "failed"}:
            raise ValueError(f"状态为 {run.status} 的 Agent 运行不能继续执行。")
        return self.execute_run(run_id)

    def _pause_for_approval(
        self,
        run: AgentRun,
        step: AgentPlanStep,
        description: str,
        side_effects: list[str],
    ) -> AgentRun:
        effects = "；".join(self._localize_side_effect(item) for item in side_effects) if side_effects else "生成工作区产物"
        step.status = "waiting_approval"
        step.observation = "正在等待用户批准执行该工具。"
        run.status = "needs_input"
        run.current_step_id = step.step_id
        run.pending_approval_step_id = step.step_id
        reason = (step.reason or description).strip().rstrip(".。")
        run.approval_prompt = (
            f"即将执行工具 {step.tool_name}。执行原因：{reason}。"
            f"预计产生的影响或产物：{effects}。"
        )
        run.approval_options = ["approve", "reject"]
        run.finished_at = None
        self.save_run(run)
        return run

    def _clear_pending_approval(self, run: AgentRun) -> None:
        run.pending_approval_step_id = None
        run.approval_prompt = None
        run.approval_options = []

    def _localize_side_effect(self, value: str) -> str:
        text = str(value or "").strip()
        replacements = (
            ("reads/writes ", "读取并写入 "),
            ("may write ", "可能写入 "),
            ("writes ", "写入 "),
            ("reads ", "读取 "),
        )
        for source, target in replacements:
            if text.startswith(source):
                return target + text[len(source) :]
        return text

    def _fail_run(self, run: AgentRun, step: AgentPlanStep, error: str) -> AgentRun:
        run.status = "failed"
        run.error = error
        run.finished_at = _utc_now()
        run.current_step_id = step.step_id
        self.save_run(run)
        return run

    def _apply_recovery_actions(
        self,
        run: AgentRun,
        current_step: AgentPlanStep,
        actions: list[AgentRecoveryAction],
    ) -> bool:
        insert_offset = 1
        current_index = run.plan.steps.index(current_step)
        for action in actions:
            if action.action_type == "stop_run":
                return True
            if action.action_type == "update_step_args":
                for target in run.plan.steps[current_index + 1 :]:
                    if action.tool_name and target.tool_name != action.tool_name:
                        continue
                    target.arguments.update(action.arguments)
                    break
                continue
            if action.action_type == "skip_step":
                target_id = str(action.arguments.get("step_id") or "")
                for target in run.plan.steps[current_index + 1 :]:
                    if (target_id and target.step_id == target_id) or (action.tool_name and target.tool_name == action.tool_name):
                        target.status = "skipped"
                        target.observation = action.reason
                        break
                continue
            if action.action_type != "insert_step" or not action.tool_name:
                continue
            if run.recovery_count >= run.max_recovery_count:
                run.warnings = self._merge_warnings(run.warnings, ["max_recovery_count_reached"])
                continue

            run.recovery_count += 1
            recovery_number = run.recovery_count
            primary_arguments = dict(action.arguments)
            follow_up_steps = primary_arguments.pop("follow_up_steps", [])
            new_steps = [(action.tool_name, primary_arguments, action.reason)]
            if isinstance(follow_up_steps, list):
                for item in follow_up_steps:
                    if not isinstance(item, dict) or not item.get("tool_name"):
                        continue
                    new_steps.append(
                        (
                            str(item["tool_name"]),
                            dict(item.get("arguments") or {}),
                            f"恢复动作 {action.action_id} 的后续步骤。",
                        )
                    )
            for sequence, (tool_name, arguments, reason) in enumerate(new_steps, start=1):
                tool_slug = tool_name.replace(".", "_")
                suffix = "" if sequence == 1 else f"_{sequence:02d}"
                recovery_step = AgentPlanStep(
                    step_id=f"recovery_{recovery_number}_{tool_slug}{suffix}",
                    tool_name=tool_name,
                    arguments=arguments,
                    reason=reason,
                )
                run.plan.steps.insert(current_index + insert_offset, recovery_step)
                insert_offset += 1
            current_step.observation = f"{current_step.observation} Recovery inserted: {action.reason}"
        return False

    def load_run(self, run_id: str) -> AgentRun:
        run_path = self.storage_dir / f"{run_id}.json"
        if not run_path.exists():
            raise FileNotFoundError(f"未找到 Agent 运行记录：{run_id}")
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        return AgentRun(**payload)

    def load_latest_run(self) -> AgentRun:
        if not self.latest_path.exists():
            raise FileNotFoundError("未找到最近一次 Agent 运行记录。")
        payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        return AgentRun(**payload)

    def save_run(self, run: AgentRun) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_jsonable(run), ensure_ascii=False, indent=2)
        run_path = self.storage_dir / f"{run.run_id}.json"
        run_path.write_text(payload + "\n", encoding="utf-8")
        self.latest_path.write_text(payload + "\n", encoding="utf-8")

    def _observation_for_result(self, result: AgentToolResult) -> str:
        status = "成功" if result.success else "失败"
        summary = (result.result_summary or "").strip().rstrip(".")
        return f"{result.tool_name} 执行{status}：{summary}。"

    def _merge_artifacts(self, existing: list[str], new_items: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for item in [*existing, *new_items]:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
        return merged

    def _merge_warnings(self, existing: list[str], new_items: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for item in [*existing, *new_items]:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
        return merged

    def _apply_result_payload_to_plan(
        self,
        run: AgentRun,
        step: Any,
        result: AgentToolResult,
        remaining_steps: list[Any],
    ) -> None:
        payload = result.payload if isinstance(result.payload, dict) else {}
        if result.tool_name == "github.select_projects":
            selected = self._clean_strings(payload.get("selected_repos"))
            if selected:
                self._set_argument_if_missing(
                    remaining_steps,
                    {"github.research_selected", "github.plan_content", "github.write_articles", "github.review_articles"},
                    "selected_repo_full_names",
                    selected,
                )
                self._set_argument_if_missing(remaining_steps, {"github.package_articles"}, "full_names", selected)
                step.observation = f"{step.observation} Selected: {', '.join(selected)}."
                if run.observations:
                    run.observations[-1] = step.observation

    def _set_argument_if_missing(
        self,
        steps: list[Any],
        tool_names: set[str],
        argument_name: str,
        value: Any,
    ) -> None:
        for step in steps:
            if step.tool_name not in tool_names:
                continue
            current = step.arguments.get(argument_name)
            if current:
                continue
            step.arguments[argument_name] = value

    def _clean_strings(self, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned
