from __future__ import annotations

from typing import Any, Optional

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
