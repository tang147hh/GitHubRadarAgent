from __future__ import annotations

import json
import secrets
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .agent_models import AgentTool, AgentToolCall, AgentToolResult
from .config import get_settings
from .news_article_planner import NewsArticlePlannerService
from .news_article_polisher import NewsArticlePolisherService
from .news_article_quality import NewsArticleQualityEvaluator
from .news_article_writer import NewsArticleWriterService
from .news_collector import NewsCollectorService
from .news_detail_service import NewsDetailService
from .news_digest_polisher import NewsDigestPolisherService
from .news_digest_quality import NewsDigestQualityEvaluator
from .news_digest_writer import NewsDigestWriterService
from .news_event_builder import NewsEventBuilderService
from .news_scorer import NewsScoringService
from .news_selection_service import NewsSelectionService
from .orchestrator import DailyOrchestrator


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today() -> str:
    return datetime.now().date().isoformat()


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


def _json_dump(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, indent=2)


def _date_from(value: str | None) -> str:
    return (value or _today())[:10] if value else _today()


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
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


def _existing_artifacts(paths: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        if Path(path).exists():
            result.append(path)
    return result


def _handler_result(
    result_summary: str,
    artifacts: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "result_summary": result_summary,
        "artifacts": artifacts or [],
        "payload": payload or {},
        "warnings": warnings or [],
    }


def _model_copy(model: Any, update: dict[str, Any]) -> Any:
    if hasattr(model, "model_copy"):
        return model.model_copy(update=update)
    return model.copy(update=update)


class ToolRegistry:
    def __init__(self, storage_dir: Path | None = None) -> None:
        settings = get_settings()
        self.storage_dir = storage_dir or settings.workspace_dir / "agent_tool_calls"
        self._tools: dict[str, AgentTool] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, tool: AgentTool, handler: ToolHandler) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Agent tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent tool: {name}") from exc

    def list_tools(self, skill_name: str | None = None) -> list[AgentTool]:
        tools = sorted(self._tools.values(), key=lambda tool: tool.name)
        if skill_name:
            tools = [tool for tool in tools if tool.skill_name == skill_name]
        return tools

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> AgentToolResult:
        arguments = arguments or {}
        call_id = self._make_call_id()
        created_at = _utc_now()
        started_at = created_at
        call = AgentToolCall(call_id=call_id, tool_name=name, arguments=arguments, created_at=created_at)

        try:
            tool = self.get(name)
            handler = self._handlers[name]
            raw_result = handler(arguments)
            finished_at = _utc_now()
            result = AgentToolResult(
                call_id=call_id,
                tool_name=name,
                success=True,
                started_at=started_at,
                finished_at=finished_at,
                result_summary=str(raw_result.get("result_summary") or f"{name} completed."),
                artifacts=_clean_list(raw_result.get("artifacts")),
                payload=_jsonable(raw_result.get("payload") or {}),
                error=None,
                warnings=_clean_list(raw_result.get("warnings")),
            )
        except Exception as exc:
            finished_at = _utc_now()
            tool = self._tools.get(name)
            result = AgentToolResult(
                call_id=call_id,
                tool_name=name,
                success=False,
                started_at=started_at,
                finished_at=finished_at,
                result_summary=f"{name} failed.",
                artifacts=[],
                payload={},
                error=f"{type(exc).__name__}: {exc}",
                warnings=[traceback.format_exc(limit=8)],
            )

        self._save_call(call=call, tool=tool, result=result)
        return result

    def _make_call_id(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"toolcall_{stamp}_{secrets.token_hex(2)}"

    def _save_call(self, call: AgentToolCall, tool: AgentTool | None, result: AgentToolResult) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "call": _jsonable(call),
            "tool": _jsonable(tool) if tool is not None else None,
            "result": _jsonable(result),
        }
        call_path = self.storage_dir / f"{call.call_id}.json"
        latest_path = self.storage_dir / "latest_tool_call.json"
        call_path.write_text(_json_dump(payload) + "\n", encoding="utf-8")
        latest_path.write_text(_json_dump(payload) + "\n", encoding="utf-8")


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    _register_github_tools(registry)
    _register_news_tools(registry)
    return registry


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _summary_output_schema() -> dict[str, Any]:
    return _schema(
        {
            "result_summary": {"type": "string"},
            "artifacts": {"type": "array", "items": {"type": "string"}},
            "payload": {"type": "object"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        }
    )


def _latest_selected_repos() -> list[str]:
    selection_path = get_settings().workspace_dir / "snapshots" / "selection_latest.json"
    if not selection_path.exists():
        return []
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    selected = payload.get("selected_repos") or payload.get("selection", {}).get("selected_repos")
    return _clean_list(selected)


def _register_github_tools(registry: ToolRegistry) -> None:
    skill_name = "github-project-article"
    output_schema = _summary_output_schema()

    def register(name: str, description: str, input_schema: dict[str, Any], side_effects: list[str], handler: ToolHandler, tags: list[str]) -> None:
        registry.register(
            AgentTool(
                name=name,
                skill_name=skill_name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                side_effects=side_effects,
                requires_confirmation=False,
                tags=tags,
            ),
            handler,
        )

    register(
        "github.discover_projects",
        "Discover GitHub repository candidates for the configured or provided keywords.",
        _schema(
            {
                "limit_per_keyword": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                "keywords": {"type": "array", "items": {"type": "string"}},
            }
        ),
        ["writes workspace/snapshots/discovery_latest.json", "writes outputs/YYYY-MM-DD/discovery artifacts"],
        _github_discover,
        ["github", "discovery", "read_api", "writes_workspace"],
    )
    register(
        "github.score_projects",
        "Score latest discovered GitHub repositories and keep the top candidates.",
        _schema({"top": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100}}),
        ["writes workspace/snapshots/score_latest.json", "writes outputs/YYYY-MM-DD/score_report.md"],
        _github_score,
        ["github", "scoring", "writes_workspace"],
    )
    register(
        "github.select_projects",
        "Select projects for article writing from the latest score snapshot.",
        _schema(
            {
                "article_top": {"type": "integer", "default": 3, "minimum": 1, "maximum": 20},
                "cooldown_days": {"type": "integer", "default": 30, "minimum": 0, "maximum": 365},
                "ignore_history": {"type": "boolean", "default": False},
                "allow_recent_fallback": {"type": "boolean", "default": False},
                "prefer_growth_projects": {"type": "boolean"},
            }
        ),
        ["writes workspace/snapshots/selection_latest.json", "reads/writes workspace/article_history.json"],
        _github_select,
        ["github", "selection", "writes_workspace"],
    )
    register(
        "github.research_selected",
        "Research selected GitHub repositories from arguments or the latest selection snapshot.",
        _schema({"selected_repo_full_names": {"type": "array", "items": {"type": "string"}}}),
        ["writes workspace/snapshots/research_latest.json", "writes outputs/YYYY-MM-DD/research_notes.md"],
        _github_research_selected,
        ["github", "research", "read_api", "writes_workspace"],
    )
    register(
        "github.plan_content",
        "Build content planning artifacts for researched GitHub projects.",
        _schema(
            {
                "top": {"type": "integer", "default": 3, "minimum": 1, "maximum": 20},
                "selected_repo_full_names": {"type": "array", "items": {"type": "string"}},
            }
        ),
        ["writes workspace/snapshots/content_plan_latest.json", "writes outputs/YYYY-MM-DD/content_plan.md"],
        _github_plan_content,
        ["github", "planning", "writes_outputs"],
    )
    register(
        "github.write_articles",
        "Write GitHub project recommendation article drafts from latest planning/research snapshots.",
        _schema(
            {
                "top": {"type": "integer", "default": 3, "minimum": 1, "maximum": 20},
                "selected_repo_full_names": {"type": "array", "items": {"type": "string"}},
            }
        ),
        ["writes workspace/snapshots/articles_latest.json", "writes outputs/YYYY-MM-DD/article_drafts.md"],
        _github_write_articles,
        ["github", "writing", "writes_outputs"],
    )
    register(
        "github.review_articles",
        "Review and revise latest GitHub project article drafts.",
        _schema(
            {
                "top": {"type": "integer", "default": 3, "minimum": 1, "maximum": 20},
                "threshold": {"type": "number", "default": 80, "minimum": 0, "maximum": 100},
                "selected_repo_full_names": {"type": "array", "items": {"type": "string"}},
            }
        ),
        ["writes workspace/snapshots/final_articles_latest.json", "writes outputs/YYYY-MM-DD/final_articles/"],
        _github_review_articles,
        ["github", "review", "writes_outputs"],
    )
    register(
        "github.package_articles",
        "Package reviewed GitHub project articles with publish-ready Markdown and assets.",
        _schema(
            {
                "top": {"type": "integer", "default": 3, "minimum": 1, "maximum": 50},
                "safe_names": {"type": "array", "items": {"type": "string"}},
                "full_names": {"type": "array", "items": {"type": "string"}},
            }
        ),
        ["writes outputs/YYYY-MM-DD/article_packages/", "may write workspace/snapshots/article_packages_latest.json"],
        _github_package_articles,
        ["github", "package", "writes_outputs"],
    )
    register(
        "github.write_custom_article",
        "Write one complete GitHub project article for a specified repository URL.",
        _schema(
            {
                "repo_url": {"type": "string"},
                "direction_text": {"type": "string"},
                "direction": {"type": "string"},
                "reference_texts": {"type": "array", "items": {"type": "string"}},
                "reference_source_names": {"type": "array", "items": {"type": "string"}},
                "reference": {"type": "string"},
            },
            required=["repo_url"],
        ),
        ["writes workspace/snapshots/custom_article_latest.json", "writes outputs/YYYY-MM-DD/custom_articles/"],
        _github_write_custom_article,
        ["github", "custom_article", "writing", "writes_outputs"],
    )


def _register_news_tools(registry: ToolRegistry) -> None:
    skill_name = "ai-news-article"
    output_schema = _summary_output_schema()

    def register(name: str, description: str, input_schema: dict[str, Any], side_effects: list[str], handler: ToolHandler, tags: list[str]) -> None:
        registry.register(
            AgentTool(
                name=name,
                skill_name=skill_name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                side_effects=side_effects,
                requires_confirmation=False,
                tags=tags,
            ),
            handler,
        )

    register(
        "news.collect",
        "Collect, normalize, dedupe, and optionally translate AI news.",
        _schema(
            {
                "hours": {"type": "integer", "default": 24, "minimum": 1, "maximum": 336},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
                "sources": {"type": "array", "items": {"type": "string"}},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "include_fulltext": {"type": "boolean", "default": False},
                "translate": {"type": "boolean", "default": True},
                "translate_limit": {"type": "integer", "default": 50, "minimum": 0, "maximum": 500},
            }
        ),
        ["writes workspace/news/news_latest.json", "writes workspace/snapshots/news_latest.json", "writes outputs/YYYY-MM-DD/news_collection_report.md"],
        _news_collect,
        ["news", "collection", "read_network", "writes_workspace"],
    )
    register(
        "news.score",
        "Score latest collected AI news for editorial value and sections.",
        _schema(
            {
                "top": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                "min_score": {"type": "number", "default": 60, "minimum": 0, "maximum": 100},
            }
        ),
        ["writes workspace/news/news_scores_latest.json", "writes workspace/snapshots/news_scores_latest.json", "writes outputs/YYYY-MM-DD/news_scores_report.md"],
        _news_score,
        ["news", "scoring", "writes_workspace"],
    )
    register(
        "news.build_events",
        "Merge latest scored AI news into event cards.",
        _schema(
            {
                "top": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                "min_score": {"type": "number", "default": 60, "minimum": 0, "maximum": 100},
                "similarity_threshold": {"type": "number", "default": 0.55, "minimum": 0.35, "maximum": 0.9},
            }
        ),
        ["writes workspace/news/news_events_latest.json", "writes workspace/snapshots/news_events_latest.json", "writes outputs/YYYY-MM-DD/news_events_report.md"],
        _news_build_events,
        ["news", "events", "writes_workspace"],
    )
    register(
        "news.fetch_detail",
        "Fetch and cache article detail for one news item.",
        _schema(
            {
                "news_id": {"type": "string"},
                "refresh": {"type": "boolean", "default": False},
            },
            required=["news_id"],
        ),
        ["writes workspace/news/news_articles/{news_id}.json"],
        _news_fetch_detail,
        ["news", "detail", "read_network", "writes_workspace"],
    )
    register(
        "news.select",
        "Save selected AI news context for article planning.",
        _schema(
            {
                "news_ids": {"type": "array", "items": {"type": "string"}},
                "primary_news_id": {"type": "string"},
                "direction_text": {"type": "string"},
                "direction": {"type": "string"},
            },
            required=["news_ids"],
        ),
        ["writes workspace/news/selections/{selection_id}.json", "writes workspace/news/selections/latest_selection.json"],
        _news_select,
        ["news", "selection", "writes_workspace"],
    )
    register(
        "news.plan_article",
        "Plan a WeChat-style article from the latest or specified AI news selection.",
        _schema(
            {
                "selection_id": {"type": "string"},
                "latest": {"type": "boolean", "default": True},
            }
        ),
        ["writes workspace/news/news_article_plan_latest.json", "writes workspace/news/plans/{plan_id}.json", "writes outputs/YYYY-MM-DD/news_article_plan.md"],
        _news_plan_article,
        ["news", "planning", "writes_outputs"],
    )
    register(
        "news.write_article",
        "Write one AI news article from the latest or specified plan.",
        _schema(
            {
                "plan_id": {"type": "string"},
                "latest": {"type": "boolean", "default": True},
            }
        ),
        ["writes workspace/news/news_article_latest.json", "writes workspace/news/articles/{article_id}.json", "writes outputs/YYYY-MM-DD/news_articles/"],
        _news_write_article,
        ["news", "writing", "writes_outputs"],
    )
    register(
        "news.review_article",
        "Review, optionally polish, and package the latest or specified AI news article.",
        _schema(
            {
                "article_id": {"type": "string"},
                "latest": {"type": "boolean", "default": True},
                "threshold": {"type": "number", "default": 80, "minimum": 0, "maximum": 100},
                "polish": {"type": "boolean", "default": True},
            }
        ),
        ["writes workspace/news/news_article_review_latest.json", "writes outputs/YYYY-MM-DD/news_articles/{article_id}_package.md"],
        _news_review_article,
        ["news", "review", "writes_outputs"],
    )
    register(
        "news.write_digest",
        "Write an AI news digest from latest event cards.",
        _schema(
            {
                "top": {"type": "integer", "default": 12, "minimum": 1, "maximum": 50},
                "date": {"type": "string"},
            }
        ),
        ["writes workspace/news/news_digest_latest.json", "writes outputs/YYYY-MM-DD/ai_news_digest.md"],
        _news_write_digest,
        ["news", "digest", "writing", "writes_outputs"],
    )
    register(
        "news.review_digest",
        "Review, optionally polish, and package the latest AI news digest.",
        _schema(
            {
                "threshold": {"type": "number", "default": 80, "minimum": 0, "maximum": 100},
                "polish": {"type": "boolean", "default": True},
            }
        ),
        ["writes workspace/news/news_digest_review_latest.json", "writes outputs/YYYY-MM-DD/news_digest_package/"],
        _news_review_digest,
        ["news", "digest", "review", "writes_outputs"],
    )


def _github_discover(arguments: dict[str, Any]) -> dict[str, Any]:
    candidates = DailyOrchestrator().discover(
        limit_per_keyword=int(arguments.get("limit_per_keyword") or 10),
        keywords=_clean_list(arguments.get("keywords")) or None,
    )
    return _handler_result(
        f"Discovered {len(candidates)} GitHub repository candidates.",
        _existing_artifacts(["workspace/snapshots/discovery_latest.json"]),
        {"candidate_count": len(candidates), "repositories": [item.full_name for item in candidates[:20]]},
    )


def _github_score(arguments: dict[str, Any]) -> dict[str, Any]:
    scores = DailyOrchestrator().score(top=int(arguments.get("top") or 10))
    return _handler_result(
        f"Scored {len(scores)} GitHub repositories.",
        _existing_artifacts(["workspace/snapshots/score_latest.json", f"outputs/{_today()}/score_report.md"]),
        {"score_count": len(scores), "repositories": [item.full_name for item in scores[:20]]},
    )


def _github_select(arguments: dict[str, Any]) -> dict[str, Any]:
    summary = DailyOrchestrator().select_article_projects(
        article_top=int(arguments.get("article_top") or 3),
        cooldown_days=int(arguments.get("cooldown_days") if arguments.get("cooldown_days") is not None else 30),
        ignore_history=bool(arguments.get("ignore_history", False)),
        allow_recent_fallback=bool(arguments.get("allow_recent_fallback", False)),
        prefer_growth_projects=arguments.get("prefer_growth_projects"),
    )
    selected = _clean_list((summary or {}).get("selected_repos"))
    return _handler_result(
        f"Selected {len(selected)} GitHub projects for article writing.",
        _existing_artifacts(["workspace/snapshots/selection_latest.json"]),
        {"selected_count": len(selected), "selected_repos": selected, "candidate_count": (summary or {}).get("candidate_count", 0)},
        _clean_list((summary or {}).get("warnings")),
    )


def _github_research_selected(arguments: dict[str, Any]) -> dict[str, Any]:
    selected = _clean_list(arguments.get("selected_repo_full_names")) or _latest_selected_repos()
    notes = DailyOrchestrator().research_selected(selected_repo_full_names=selected)
    return _handler_result(
        f"Researched {len(notes)} selected GitHub projects.",
        _existing_artifacts(["workspace/snapshots/research_latest.json", f"outputs/{_today()}/research_notes.md"]),
        {"note_count": len(notes), "selected_repo_full_names": selected, "repositories": [item.full_name for item in notes]},
    )


def _github_plan_content(arguments: dict[str, Any]) -> dict[str, Any]:
    selected = _clean_list(arguments.get("selected_repo_full_names")) or None
    plans = DailyOrchestrator().plan_content(top=int(arguments.get("top") or 3), selected_repo_full_names=selected)
    return _handler_result(
        f"Generated {len(plans)} GitHub content planning artifacts.",
        _existing_artifacts(["workspace/snapshots/content_plan_latest.json", f"outputs/{_today()}/content_plan.md"]),
        {"plan_count": len(plans), "repositories": [str(item.get("repo_full_name") or item.get("full_name") or "") for item in plans[:20]]},
    )


def _github_write_articles(arguments: dict[str, Any]) -> dict[str, Any]:
    selected = _clean_list(arguments.get("selected_repo_full_names")) or None
    drafts = DailyOrchestrator().write_articles(top=int(arguments.get("top") or 3), selected_repo_full_names=selected)
    return _handler_result(
        f"Wrote {len(drafts)} GitHub article drafts.",
        _existing_artifacts(["workspace/snapshots/articles_latest.json", f"outputs/{_today()}/article_drafts.md"]),
        {"draft_count": len(drafts), "repositories": [item.repo_full_name for item in drafts], "titles": [item.title for item in drafts]},
    )


def _github_review_articles(arguments: dict[str, Any]) -> dict[str, Any]:
    selected = _clean_list(arguments.get("selected_repo_full_names")) or None
    articles = DailyOrchestrator().review_articles(
        top=int(arguments.get("top") or 3),
        threshold=float(arguments.get("threshold") if arguments.get("threshold") is not None else 80),
        selected_repo_full_names=selected,
    )
    return _handler_result(
        f"Reviewed {len(articles)} GitHub final articles.",
        _existing_artifacts(["workspace/snapshots/final_articles_latest.json", f"outputs/{_today()}/final_articles_index.md"]),
        {"article_count": len(articles), "repositories": [item.repo_full_name for item in articles], "titles": [item.title for item in articles]},
    )


def _github_package_articles(arguments: dict[str, Any]) -> dict[str, Any]:
    packages = DailyOrchestrator().package_articles(
        top=int(arguments.get("top") or 3) if arguments.get("top") is not None else None,
        safe_names=_clean_list(arguments.get("safe_names")) or None,
        full_names=_clean_list(arguments.get("full_names")) or None,
    )
    artifacts = [package.packaged_article_path for package in packages if package.packaged_article_path]
    artifacts.extend(["workspace/snapshots/article_packages_latest.json"])
    return _handler_result(
        f"Packaged {len(packages)} GitHub articles.",
        _existing_artifacts(artifacts),
        {
            "package_count": len(packages),
            "packages": [
                {
                    "full_name": package.full_name,
                    "package_dir": package.package_dir,
                    "packaged_article_path": package.packaged_article_path,
                }
                for package in packages
            ],
        },
    )


def _github_write_custom_article(arguments: dict[str, Any]) -> dict[str, Any]:
    repo_url = str(arguments.get("repo_url") or "").strip()
    if not repo_url:
        raise ValueError("repo_url is required.")
    direction_text = arguments.get("direction_text") or arguments.get("direction")
    reference_texts = _clean_list(arguments.get("reference_texts"))
    if arguments.get("reference"):
        reference_texts.append(str(arguments["reference"]))
    result = DailyOrchestrator().write_custom_article(
        repo_url=repo_url,
        direction_text=str(direction_text).strip() if direction_text else None,
        reference_texts=reference_texts,
        reference_source_names=_clean_list(arguments.get("reference_source_names")) or None,
    )
    artifacts = _existing_artifacts(
        [
            "workspace/snapshots/custom_article_latest.json",
            str(result.get("markdown_path") or result.get("output_markdown_path") or ""),
            str(result.get("report_path") or ""),
            str(result.get("package_path") or ""),
        ]
    )
    return _handler_result(
        f"Wrote custom GitHub article for {result.get('full_name') or repo_url}.",
        artifacts,
        {
            "full_name": result.get("full_name"),
            "title": result.get("title"),
            "generation_mode": result.get("generation_mode"),
            "markdown_path": result.get("markdown_path") or result.get("output_markdown_path"),
            "report_path": result.get("report_path"),
            "package_path": result.get("package_path"),
        },
        _clean_list(result.get("warnings")),
    )


def _news_collect(arguments: dict[str, Any]) -> dict[str, Any]:
    result = NewsCollectorService().collect(
        hours=int(arguments.get("hours") or 24),
        limit=int(arguments.get("limit") or 100),
        sources=_clean_list(arguments.get("sources")) or None,
        keywords=_clean_list(arguments.get("keywords")) or None,
        include_fulltext=bool(arguments.get("include_fulltext", False)),
        translate=bool(arguments.get("translate", True)),
        translate_limit=int(arguments.get("translate_limit") if arguments.get("translate_limit") is not None else 50),
    )
    generated_date = _date_from(result.generated_at)
    return _handler_result(
        f"Collected {result.total_count} AI news items; {result.fresh_count} are within {result.window_hours}h.",
        _existing_artifacts(
            [
                "workspace/news/news_latest.json",
                "workspace/snapshots/news_latest.json",
                f"outputs/{generated_date}/news_collection_report.md",
            ]
        ),
        {
            "total_count": result.total_count,
            "fresh_count": result.fresh_count,
            "window_hours": result.window_hours,
            "source_counts": result.source_counts,
            "availability_counts": result.availability_counts,
            "news_ids": [item.id for item in result.items[:30]],
        },
        result.warnings,
    )


def _news_score(arguments: dict[str, Any]) -> dict[str, Any]:
    result = NewsScoringService().score_latest(
        top=int(arguments.get("top") or 20),
        min_score=float(arguments.get("min_score") if arguments.get("min_score") is not None else 60),
    )
    generated_date = _date_from(result.generated_at)
    return _handler_result(
        f"Scored {result.total_count} AI news items; recommended {result.recommended_count}.",
        _existing_artifacts(
            [
                "workspace/news/news_scores_latest.json",
                "workspace/snapshots/news_scores_latest.json",
                f"outputs/{generated_date}/news_scores_report.md",
            ]
        ),
        {
            "total_count": result.total_count,
            "recommended_count": result.recommended_count,
            "section_counts": result.section_counts,
            "recommended_news_ids": [item.news_id for item in result.scores if item.recommended][:30],
        },
        result.warnings,
    )


def _news_build_events(arguments: dict[str, Any]) -> dict[str, Any]:
    result = NewsEventBuilderService().build_latest(
        top=int(arguments.get("top") or 20),
        min_score=float(arguments.get("min_score") if arguments.get("min_score") is not None else 60),
        similarity_threshold=float(arguments.get("similarity_threshold") if arguments.get("similarity_threshold") is not None else 0.55),
    )
    generated_date = _date_from(result.generated_at)
    return _handler_result(
        f"Built {result.event_count} AI news events; recommended {result.recommended_event_count}.",
        _existing_artifacts(
            [
                "workspace/news/news_events_latest.json",
                "workspace/snapshots/news_events_latest.json",
                f"outputs/{generated_date}/news_events_report.md",
            ]
        ),
        {
            "event_count": result.event_count,
            "recommended_event_count": result.recommended_event_count,
            "event_ids": [item.event_id for item in result.events[:30]],
        },
        result.warnings,
    )


def _news_fetch_detail(arguments: dict[str, Any]) -> dict[str, Any]:
    news_id = str(arguments.get("news_id") or "").strip()
    if not news_id:
        raise ValueError("news_id is required.")
    service = NewsDetailService()
    detail = service.get_detail(news_id=news_id, refresh=bool(arguments.get("refresh", False)))
    cache_path = service.cache_path_for(news_id).as_posix()
    return _handler_result(
        f"Fetched detail for news item {detail.news_id}: {detail.content_availability}.",
        _existing_artifacts([cache_path]),
        {
            "news_id": detail.news_id,
            "title": detail.title_zh or detail.title,
            "content_availability": detail.content_availability,
            "extraction_status": detail.extraction_status,
            "word_count": detail.word_count,
            "cache_path": cache_path,
        },
        _clean_list([detail.extraction_error] if detail.extraction_error else []),
    )


def _news_select(arguments: dict[str, Any]) -> dict[str, Any]:
    news_ids = _clean_list(arguments.get("news_ids"))
    if not news_ids:
        raise ValueError("news_ids is required.")
    direction_text = arguments.get("direction_text") or arguments.get("direction")
    service = NewsSelectionService()
    context = service.build_selection(
        news_ids=news_ids,
        primary_news_id=str(arguments.get("primary_news_id")).strip() if arguments.get("primary_news_id") else None,
        direction_text=str(direction_text).strip() if direction_text else None,
    )
    context = service.save_selection(context)
    return _handler_result(
        f"Saved AI news selection {context.selection_id} with {len(context.items)} items.",
        _existing_artifacts(
            [
                f"workspace/news/selections/{context.selection_id}.json",
                "workspace/news/selections/latest_selection.json",
            ]
        ),
        {
            "selection_id": context.selection_id,
            "primary_news_id": context.primary_news_id,
            "news_ids": [item.news_id for item in context.items],
        },
        context.warnings,
    )


def _news_plan_article(arguments: dict[str, Any]) -> dict[str, Any]:
    selection_id = str(arguments.get("selection_id") or "").strip() or None
    service = NewsArticlePlannerService()
    plan = service.plan_by_selection_id(selection_id) if selection_id else service.plan_latest()
    generated_date = _date_from(plan.generated_at)
    return _handler_result(
        f"Generated AI news article plan {plan.plan_id}.",
        _existing_artifacts(
            [
                "workspace/news/news_article_plan_latest.json",
                f"workspace/news/plans/{plan.plan_id}.json",
                "workspace/snapshots/news_article_plan_latest.json",
                f"outputs/{generated_date}/news_article_plan.md",
            ]
        ),
        {
            "plan_id": plan.plan_id,
            "selection_id": plan.selection_id,
            "primary_news_id": plan.primary_news_id,
            "recommended_title": plan.recommended_title,
            "generation_mode": plan.generation_mode,
        },
        plan.warnings,
    )


def _news_write_article(arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = str(arguments.get("plan_id") or "").strip() or None
    service = NewsArticleWriterService()
    article = service.write_by_plan_id(plan_id) if plan_id else service.write_latest()
    generated_date = _date_from(article.generated_at)
    return _handler_result(
        f"Wrote AI news article {article.article_id}.",
        _existing_artifacts(
            [
                "workspace/news/news_article_latest.json",
                f"workspace/news/articles/{article.article_id}.json",
                "workspace/snapshots/news_article_latest.json",
                f"outputs/{generated_date}/news_articles/{article.article_id}.md",
                f"outputs/{generated_date}/news_articles/{article.article_id}_report.md",
            ]
        ),
        {
            "article_id": article.article_id,
            "plan_id": article.plan_id,
            "selection_id": article.selection_id,
            "primary_news_id": article.primary_news_id,
            "title": article.title,
            "word_count": article.word_count,
            "generation_mode": article.generation_mode,
            "publish_ready": article.publish_ready,
        },
        article.warnings,
    )


def _news_review_article(arguments: dict[str, Any]) -> dict[str, Any]:
    evaluator = NewsArticleQualityEvaluator()
    polisher = NewsArticlePolisherService()
    article_id = str(arguments.get("article_id") or "").strip() or None
    article = evaluator.load_article(article_id) if article_id else evaluator.load_latest_article()
    plan, selection, details = evaluator.load_context_for_article(article)
    threshold = float(arguments.get("threshold") if arguments.get("threshold") is not None else 80)
    report = evaluator.evaluate(article, plan, selection, details, threshold=threshold)
    if bool(arguments.get("polish", True)):
        article = polisher.polish_article(article, report)
        if article.publish_polished:
            report = evaluator.evaluate(article, plan, selection, details, threshold=threshold)
            article = _model_copy(
                article,
                {
                    "quality_report": report,
                    "quality_score": report.total_score,
                    "quality_publish_ready": report.publish_ready,
                    "publish_ready": report.publish_ready,
                },
            )
    else:
        article = polisher.attach_quality(article, report)
    article = polisher.generate_package(article, report)
    polisher.save_article(article)
    evaluator.save_report(article, report)
    generated_date = _date_from(article.generated_at)
    return _handler_result(
        f"Reviewed AI news article {article.article_id}; score {report.total_score:.1f}.",
        _existing_artifacts(
            [
                "workspace/news/news_article_review_latest.json",
                "workspace/snapshots/news_article_review_latest.json",
                f"outputs/{generated_date}/news_articles/{article.article_id}_quality_report.md",
                f"outputs/{generated_date}/news_articles/{article.article_id}_publish.md",
                f"outputs/{generated_date}/news_articles/{article.article_id}_package.md",
            ]
        ),
        {
            "article_id": article.article_id,
            "title": article.title,
            "quality_score": report.total_score,
            "publish_ready": report.publish_ready,
            "publish_polished": article.publish_polished,
            "issue_count": len(report.issues),
            "package_path": article.publish_package_path,
        },
        article.warnings + [issue.description for issue in report.issues[:5] if issue.severity == "high"],
    )


def _news_write_digest(arguments: dict[str, Any]) -> dict[str, Any]:
    result = NewsDigestWriterService().write_latest(
        top=int(arguments.get("top") or 12),
        date=str(arguments.get("date")).strip() if arguments.get("date") else None,
    )
    return _handler_result(
        f"Wrote AI news digest with {result.event_count} events.",
        _existing_artifacts(
            [
                "workspace/news/news_digest_latest.json",
                "workspace/snapshots/news_digest_latest.json",
                f"outputs/{result.date}/ai_news_digest.md",
            ]
        ),
        {
            "date": result.date,
            "event_count": result.event_count,
            "generation_mode": result.generation_mode,
            "publish_ready": result.publish_ready,
        },
        result.warnings,
    )


def _news_review_digest(arguments: dict[str, Any]) -> dict[str, Any]:
    evaluator = NewsDigestQualityEvaluator()
    polisher = NewsDigestPolisherService()
    article = evaluator.load_latest_digest()
    events_result = evaluator.load_latest_events()
    threshold = float(arguments.get("threshold") if arguments.get("threshold") is not None else 80)
    report = evaluator.evaluate(article, events_result, threshold=threshold)
    if bool(arguments.get("polish", True)):
        article = polisher.polish_article(article, report)
        if article.polished:
            report = evaluator.evaluate(article, events_result, threshold=threshold)
            article = _model_copy(
                article,
                {
                    "quality_report": report,
                    "quality_score": report.total_score,
                    "publish_ready": report.publish_ready,
                },
            )
    else:
        article = polisher.attach_quality(article, report)
    article = polisher.generate_package(article, report)
    polisher.save_article(article)
    evaluator.save_report(article, report)
    package_path = article.package_path or f"outputs/{article.date}/news_digest_package/packaged_ai_news_digest.md"
    return _handler_result(
        f"Reviewed AI news digest for {article.date}; score {report.total_score:.1f}.",
        _existing_artifacts(
            [
                "workspace/news/news_digest_review_latest.json",
                "workspace/snapshots/news_digest_review_latest.json",
                f"outputs/{article.date}/ai_news_digest_review.md",
                f"outputs/{article.date}/ai_news_digest.md",
                package_path,
                f"outputs/{article.date}/news_digest_package/assets.json",
            ]
        ),
        {
            "date": article.date,
            "quality_score": report.total_score,
            "publish_ready": report.publish_ready,
            "polished": article.polished,
            "issue_count": len(report.issues),
            "package_path": package_path,
        },
        article.warnings + [issue.description for issue in report.issues[:5] if issue.severity == "high"],
    )
