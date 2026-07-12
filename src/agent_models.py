from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AgentTool(BaseModel):
    name: str
    skill_name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    tags: list[str] = Field(default_factory=list)


class AgentToolCall(BaseModel):
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AgentToolResult(BaseModel):
    call_id: str
    tool_name: str
    success: bool
    started_at: str
    finished_at: str
    result_summary: str
    artifacts: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class AgentPlanStep(BaseModel):
    step_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    status: Literal[
        "pending",
        "running",
        "waiting_approval",
        "approved",
        "rejected",
        "succeeded",
        "failed",
        "skipped",
    ] = "pending"
    tool_call_id: Optional[str] = None
    observation: str = ""
    artifacts: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class AgentPlan(BaseModel):
    plan_id: str
    skill_name: str
    goal: str
    steps: list[AgentPlanStep] = Field(default_factory=list)
    generated_at: str
    generation_mode: str = "deterministic"
    warnings: list[str] = Field(default_factory=list)


class AgentRecoveryAction(BaseModel):
    action_id: str
    action_type: Literal["insert_step", "update_step_args", "skip_step", "stop_run"]
    tool_name: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    inserted_after_step_id: Optional[str] = None


class AgentReflection(BaseModel):
    reflection_id: str
    run_id: str
    step_id: str
    tool_name: str
    created_at: str
    status: Literal["pass", "needs_recovery", "unrecoverable"]
    observations: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    recovery_actions: list[AgentRecoveryAction] = Field(default_factory=list)
    decision: str


class AgentRun(BaseModel):
    run_id: str
    goal: str
    skill_name: str
    status: Literal["planned", "running", "needs_input", "succeeded", "failed"] = "planned"
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    current_step_id: Optional[str] = None
    plan: AgentPlan
    observations: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    reflections: list[AgentReflection] = Field(default_factory=list)
    recovery_count: int = Field(default=0, ge=0)
    max_recovery_count: int = Field(default=3, ge=0)
    reflection_enabled: bool = True
    auto_approve: bool = False
    pending_approval_step_id: Optional[str] = None
    approval_prompt: Optional[str] = None
    approval_options: list[str] = Field(default_factory=list)
    approval_history: list[dict[str, Any]] = Field(default_factory=list)
