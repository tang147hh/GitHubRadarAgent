from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - allows bootstrap before dependencies are installed
    load_dotenv = None


class Settings(BaseModel):
    output_dir: Path = Field(default=Path("outputs"))
    workspace_dir: Path = Field(default=Path("workspace"))
    daily_keywords: List[str] = Field(
        default_factory=lambda: [
            "ai agent",
            "llm agent",
            "mcp",
            "rag",
            "multi-agent",
            "workflow automation",
            "developer tools",
            "productivity tool",
            "cli tool",
            "self-hosted",
            "automation tool",
            "chrome extension",
            "terminal tool",
        ]
    )
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    github_personal_access_token: Optional[str] = None
    tavily_api_key: Optional[str] = None
    prefer_growth_projects: bool = True


def _split_keywords(value: Optional[str]) -> List[str]:
    if not value:
        return Settings().daily_keywords
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if load_dotenv is not None:
        load_dotenv()

    return Settings(
        output_dir=Path(os.getenv("OUTPUT_DIR", "outputs")),
        workspace_dir=Path(os.getenv("WORKSPACE_DIR", "workspace")),
        daily_keywords=_split_keywords(os.getenv("DAILY_KEYWORDS")),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        openai_model=os.getenv("OPENAI_MODEL") or None,
        github_personal_access_token=os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or None,
        tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
        prefer_growth_projects=os.getenv("PREFER_GROWTH_PROJECTS", "true").strip().lower() not in {"0", "false", "no"},
    )
