from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from api.jobs import job_manager
from api.schemas import CustomArticleRequest, PackageArticlesRequest, RunDailyRequest, UiSettings
from src.config import get_settings
from src.orchestrator import DailyOrchestrator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DOCS_DIR = PROJECT_ROOT / "docs"
UI_SETTINGS_PATH = WORKSPACE_DIR / "ui_settings.json"

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    "run_defaults": {
        "limit_per_keyword": 3,
        "score_top": 30,
        "research_top": 3,
        "article_top": 3,
        "review_threshold": 80,
        "cooldown_days": 30,
        "ignore_history": False,
        "allow_recent_fallback": False,
        "prefer_growth_projects": True,
    },
    "discovery": {
        "daily_keywords": [
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
    },
    "frontend": {
        "default_language": "zh",
    },
}

SNAPSHOT_FILES = {
    "discovery": "workspace/snapshots/discovery_latest.json",
    "score": "workspace/snapshots/score_latest.json",
    "selection": "workspace/snapshots/selection_latest.json",
    "research": "workspace/snapshots/research_latest.json",
    "angles": "workspace/snapshots/angles_latest.json",
    "content_plan": "workspace/snapshots/content_plan_latest.json",
    "articles": "workspace/snapshots/articles_latest.json",
    "reviews": "workspace/snapshots/reviews_latest.json",
    "humanization": "workspace/snapshots/humanization_latest.json",
    "publish_polish": "workspace/snapshots/publish_polish_latest.json",
    "article_quality": "workspace/snapshots/article_quality_latest.json",
    "final_articles": "workspace/snapshots/final_articles_latest.json",
    "article_packages": "workspace/snapshots/article_packages_latest.json",
}

REPORT_FILES = {
    "daily_report": "daily_report.md",
    "score_report": "score_report.md",
    "research_notes": "research_notes.md",
    "topic_angles": "topic_angles.md",
    "content_plan": "content_plan.md",
    "article_drafts": "article_drafts.md",
    "articles_index": "articles_index.md",
    "review_report": "review_report.md",
    "humanization_report": "humanization_report.md",
    "publish_polish_report": "publish_polish_report.md",
    "article_quality_report": "article_quality_report.md",
    "final_articles_index": "final_articles_index.md",
    "article_packages": "article_packages.md",
}

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

PIPELINE_STAGES = [
    "discover",
    "score",
    "select-projects",
    "research-selected",
    "angles",
    "plan-content",
    "write-articles",
    "review-articles",
    "package-articles",
]

CUSTOM_ARTICLE_STAGES = [
    "parse_repo",
    "research",
    "parse_direction",
    "analyze_style_reference",
    "plan_content",
    "write_article",
    "review",
    "humanize",
    "polish",
    "originality",
    "article_quality",
    "package",
    "done",
]

app = FastAPI(title="GitHubRadarAgent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):517[0-9]",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def safe_project_path(relative_path: str | Path) -> Path:
    candidate = (PROJECT_ROOT / relative_path).resolve()
    allowed_roots = [WORKSPACE_DIR.resolve(), OUTPUTS_DIR.resolve(), DOCS_DIR.resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="Path is outside allowed project directories.")
    return candidate


def read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"JSON file not found: {_relative_path(path)}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"JSON file is invalid: {_relative_path(path)} ({exc.msg})",
        )


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Text file not found: {_relative_path(path)}")


def _validate_output_date(date: str) -> str:
    if not DATE_PATTERN.fullmatch(date):
        raise HTTPException(status_code=400, detail="Invalid output date. Expected YYYY-MM-DD.")
    return date


def _validate_safe_name(safe_name: str) -> str:
    if not SAFE_NAME_PATTERN.fullmatch(safe_name):
        raise HTTPException(status_code=400, detail="Invalid safe_name.")
    return safe_name


def _safe_output_path(*parts: str | Path) -> Path:
    candidate = (OUTPUTS_DIR / Path(*parts)).resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if candidate != outputs_root and outputs_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Path is outside outputs directory.")
    return candidate


def _output_date_dir(date: str) -> Path:
    _validate_output_date(date)
    return _safe_output_path(date)


def _markdown_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    except FileNotFoundError:
        return ""
    return ""


def _output_file_item(path: Path, base_dir: Path | None = None) -> dict[str, Any]:
    safe_name = path.stem
    return {
        "safe_name": safe_name,
        "filename": path.name,
        "path": _relative_path(path),
        "title": _markdown_title(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def _article_items(date_dir: Path, folder: str) -> list[dict[str, Any]]:
    articles_dir = (date_dir / folder).resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if not (articles_dir == outputs_root or outputs_root in articles_dir.parents) or not articles_dir.exists():
        return []
    return [_output_file_item(path, articles_dir) for path in sorted(articles_dir.glob("*.md"), key=lambda item: item.name)]


def _package_items(date_dir: Path) -> list[dict[str, Any]]:
    assets_dir = (date_dir / "assets").resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if not (assets_dir == outputs_root or outputs_root in assets_dir.parents) or not assets_dir.exists():
        return []
    items = []
    for package_dir in sorted([path for path in assets_dir.iterdir() if path.is_dir()], key=lambda item: item.name):
        path = package_dir / "packaged_article.md"
        if not path.exists():
            continue
        items.append(
            {
                "safe_name": package_dir.name,
                "filename": path.name,
                "path": _relative_path(path),
                "title": _markdown_title(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return items


def _asset_items(date_dir: Path) -> list[dict[str, Any]]:
    assets_dir = (date_dir / "assets").resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if not (assets_dir == outputs_root or outputs_root in assets_dir.parents) or not assets_dir.exists():
        return []
    items = []
    for path in sorted(assets_dir.glob("*/*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        items.append(
            {
                "safe_name": path.parent.name,
                "filename": path.name,
                "path": _relative_path(path),
                "asset_type": path.suffix.lstrip(".") or "file",
                "size_bytes": path.stat().st_size,
            }
        )
    return items


def _report_items(date_dir: Path) -> list[dict[str, Any]]:
    items = []
    for report_name, filename in REPORT_FILES.items():
        path = date_dir / filename
        items.append(
            {
                "name": report_name,
                "filename": filename,
                "path": _relative_path(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
        )
    return items


def _read_output_markdown(path: Path) -> str:
    resolved = path.resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if resolved == outputs_root or outputs_root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Path is outside outputs directory.")
    if resolved.suffix != ".md":
        raise HTTPException(status_code=400, detail="Only Markdown files can be read.")
    return read_text_file(resolved)


def _safe_workspace_or_outputs_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    candidate = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    allowed_roots = [WORKSPACE_DIR.resolve(), OUTPUTS_DIR.resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="Path is outside workspace or outputs directory.")
    return candidate


def _read_workspace_or_outputs_markdown(path_value: str | Path) -> tuple[str, Path]:
    path = _safe_workspace_or_outputs_path(path_value)
    if path.suffix != ".md":
        raise HTTPException(status_code=400, detail="Only Markdown files can be read.")
    return read_text_file(path), path


def _custom_article_snapshot_path() -> Path:
    return _safe_workspace_or_outputs_path("workspace/snapshots/custom_article_latest.json")


def _load_custom_article_latest() -> dict[str, Any]:
    path = _custom_article_snapshot_path()
    if not path.exists():
        return {
            "exists": False,
            "status": "empty",
            "message": "No custom article has been generated yet.",
        }
    payload = read_json_file(path)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Custom article snapshot must be a JSON object.")
    if not isinstance(payload.get("originality_report"), dict):
        payload["originality_report"] = {
            "checked": False,
            "passed": True,
            "similarity_score": 0.0,
            "max_common_sequence_length": 0,
            "copied_sentence_count": 0,
            "structure_similarity": 0.0,
            "issues": [],
            "rewrite_attempted": False,
            "rewrite_mode": "none",
            "summary": "未提供参考文章，本次未执行相似度检查",
        }
    payload.setdefault("originality_checked", bool(payload["originality_report"].get("checked")))
    payload.setdefault("originality_passed", bool(payload["originality_report"].get("passed", True)))
    if not isinstance(payload.get("article_quality_report"), dict):
        final_article = payload.get("final_article") if isinstance(payload.get("final_article"), dict) else {}
        payload["article_quality_report"] = (
            final_article.get("article_quality_report")
            if isinstance(final_article.get("article_quality_report"), dict)
            else None
        )
    payload.setdefault("quality_score", (payload.get("article_quality_report") or {}).get("total_score", 0.0))
    payload.setdefault("quality_publish_ready", bool((payload.get("article_quality_report") or {}).get("publish_ready", False)))
    if not payload.get("package_path") and payload.get("packaged_article_path"):
        payload["package_path"] = payload.get("packaged_article_path")
    payload.setdefault("packaged_article_available", bool(payload.get("package_path")))
    payload.setdefault("selected_readme_images", [])
    payload.setdefault("asset_count", len(payload.get("selected_readme_images") or []))
    return {"exists": True, "snapshot_path": _relative_path(path), **payload}


def _custom_article_markdown_response(path_key: str, empty_message: str) -> dict[str, Any]:
    latest = _load_custom_article_latest()
    if not latest.get("exists"):
        return {"exists": False, "content_markdown": "", "path": None, "message": empty_message}
    path_value = latest.get(path_key)
    if not path_value:
        return {"exists": False, "content_markdown": "", "path": None, "message": empty_message}
    content, path = _read_workspace_or_outputs_markdown(str(path_value))
    return {
        "exists": True,
        "full_name": latest.get("full_name"),
        "status": latest.get("status"),
        "content_markdown": content,
        "path": _relative_path(path),
    }


def _custom_article_markdown_path(safe_name: str) -> Path:
    _validate_safe_name(safe_name)
    latest = _load_custom_article_latest()
    latest_safe_name = str(latest.get("full_name") or "").replace("/", "__")
    latest_path = latest.get("output_markdown_path")
    if latest.get("exists") and latest_safe_name == safe_name and latest_path:
        try:
            path = _safe_workspace_or_outputs_path(str(latest_path))
            if path.exists() and path.suffix == ".md":
                return path
        except HTTPException:
            pass

    if OUTPUTS_DIR.exists():
        candidates = sorted(
            OUTPUTS_DIR.glob(f"*/custom_articles/{safe_name}.md"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        outputs_root = OUTPUTS_DIR.resolve()
        for candidate in candidates:
            resolved = candidate.resolve()
            if outputs_root == resolved or outputs_root in resolved.parents:
                return resolved

    raise HTTPException(status_code=404, detail=f"Custom article not found: {safe_name}")


def _custom_article_payloads() -> list[dict[str, Any]]:
    snapshots_dir = WORKSPACE_DIR / "snapshots"
    payloads: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    paths: list[Path] = []
    latest_path = snapshots_dir / "custom_article_latest.json"
    if latest_path.exists():
        paths.append(latest_path)
    if snapshots_dir.exists():
        paths.extend(sorted(snapshots_dir.glob("*-custom-article-*.json"), key=lambda path: path.stat().st_mtime, reverse=True))

    for path in paths:
        try:
            payload = read_json_file(path)
        except HTTPException:
            continue
        if not isinstance(payload, dict) or payload.get("status") not in {None, "success"}:
            continue
        markdown_path = str(payload.get("output_markdown_path") or "")
        key = markdown_path or f"{payload.get('full_name')}:{payload.get('generated_at')}"
        if key in seen_paths:
            continue
        seen_paths.add(key)
        payloads.append(payload)

    if OUTPUTS_DIR.exists():
        for path in sorted(OUTPUTS_DIR.glob("*/custom_articles/*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.stem.endswith("_report"):
                continue
            resolved = path.resolve()
            if OUTPUTS_DIR.resolve() == resolved or OUTPUTS_DIR.resolve() in resolved.parents:
                key = _relative_path(resolved)
                if key not in seen_paths:
                    seen_paths.add(key)
                    safe_name = path.stem
                    payloads.append(
                        {
                            "status": "success",
                            "full_name": safe_name.replace("__", "/", 1),
                            "title": _markdown_title(path),
                            "output_markdown_path": key,
                            "generated_at": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") + "Z",
                        }
                    )
    return payloads


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _package_response(packages: list[Any]) -> dict[str, Any]:
    package_items = [_model_dump(package) for package in packages]
    return {
        "status": "success",
        "total_count": len(package_items),
        "package_count": len(package_items),
        "packages": package_items,
    }


def _deep_merge_settings(payload: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_UI_SETTINGS))
    for section in ("run_defaults", "discovery", "frontend"):
        if isinstance(payload.get(section), dict):
            merged[section].update(payload[section])
    return merged


def _parse_ui_settings(payload: dict[str, Any]) -> UiSettings:
    try:
        if hasattr(UiSettings, "model_validate"):
            return UiSettings.model_validate(payload)  # type: ignore[attr-defined]
        return UiSettings.parse_obj(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json()))


def load_ui_settings() -> tuple[UiSettings, bool]:
    if not UI_SETTINGS_PATH.exists():
        return _parse_ui_settings(DEFAULT_UI_SETTINGS), False
    payload = read_json_file(UI_SETTINGS_PATH)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="workspace/ui_settings.json must contain a JSON object.")
    return _parse_ui_settings(_deep_merge_settings(payload)), True


def save_ui_settings(settings: UiSettings) -> UiSettings:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    UI_SETTINGS_PATH.write_text(
        json.dumps(_model_dump(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return settings


def _resolved_run_daily_params(request: RunDailyRequest) -> dict[str, Any]:
    ui_settings, ui_settings_exists = load_ui_settings()
    run_defaults = _model_dump(ui_settings.run_defaults)
    payload = _model_dump(request)

    params = {
        key: payload[key] if payload.get(key) is not None else run_defaults[key]
        for key in (
            "limit_per_keyword",
            "score_top",
            "research_top",
            "article_top",
            "review_threshold",
            "cooldown_days",
            "ignore_history",
            "allow_recent_fallback",
            "prefer_growth_projects",
        )
    }
    if payload.get("daily_keywords"):
        params["daily_keywords"] = payload["daily_keywords"]
    elif ui_settings_exists:
        params["daily_keywords"] = ui_settings.discovery.daily_keywords
    else:
        params["daily_keywords"] = get_settings().daily_keywords
    return params


def _read_optional_json(relative_path: str) -> Any | None:
    path = safe_project_path(relative_path)
    if not path.exists():
        return None
    return read_json_file(path)


def latest_output_date() -> str | None:
    latest_run = _read_optional_json("workspace/runs/latest_run.json")
    if isinstance(latest_run, dict) and latest_run.get("date"):
        return str(latest_run["date"])

    if not OUTPUTS_DIR.exists():
        return None

    date_dirs = [path for path in OUTPUTS_DIR.iterdir() if path.is_dir()]
    if not date_dirs:
        return None
    return max(date_dirs, key=lambda path: path.stat().st_mtime).name


def _score_ranking(score_payload: dict[str, Any] | None, limit: int | None = None) -> list[dict[str, Any]]:
    scores = []
    if isinstance(score_payload, dict):
        scores = score_payload.get("scores") or []
    if not isinstance(scores, list):
        return []
    return scores[:limit] if limit is not None else scores


def _final_articles_payload(final_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    articles = []
    if isinstance(final_payload, dict):
        articles = final_payload.get("articles") or []
    return articles if isinstance(articles, list) else []


def _review_summary(reviews_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(reviews_payload, dict):
        return {"total_count": 0, "pass_count": 0, "pass_rate": "0%", "reviews": []}

    reviews = reviews_payload.get("reviews") or []
    if not isinstance(reviews, list):
        reviews = []
    pass_count = sum(1 for review in reviews if isinstance(review, dict) and review.get("pass_review"))
    total_count = len(reviews)
    pass_rate = f"{round(pass_count / total_count * 100):.0f}%" if total_count else "0%"
    return {
        "total_count": total_count,
        "pass_count": pass_count,
        "pass_rate": pass_rate,
        "pass_threshold": reviews_payload.get("pass_threshold"),
        "llm_available": reviews_payload.get("llm_available"),
        "used_llm": reviews_payload.get("used_llm"),
        "warnings": reviews_payload.get("warnings", []),
        "reviews": reviews,
    }


def _pipeline_from_run(run_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    stages_by_name = {}
    if isinstance(run_payload, dict):
        for stage in run_payload.get("stages") or []:
            if isinstance(stage, dict) and stage.get("name"):
                stages_by_name[stage["name"]] = stage

    pipeline = []
    for name in PIPELINE_STAGES:
        stage = stages_by_name.get(name, {})
        pipeline.append(
            {
                "name": name,
                "status": stage.get("status", "unknown"),
                "message": stage.get("message", ""),
                "error": stage.get("error"),
                "started_at": stage.get("started_at"),
                "finished_at": stage.get("finished_at"),
            }
        )
    return pipeline


def _duration(started_at: str | None, finished_at: str | None) -> str:
    if not started_at or not finished_at:
        return "unknown"
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    return f"{max(0.0, (finish - start).total_seconds()):.1f}s"


def _safe_name(full_name: str) -> str:
    return full_name.replace("/", "__")


def _article_markdown_path(safe_name: str, source: str | None = None) -> Path:
    if source == "custom":
        return _custom_article_markdown_path(safe_name)

    run_date = latest_output_date()
    if run_date:
        path = safe_project_path(Path("outputs") / run_date / "final_articles" / f"{safe_name}.md")
        if path.exists():
            return path

    if OUTPUTS_DIR.exists():
        candidates = sorted(
            OUTPUTS_DIR.glob(f"*/final_articles/{safe_name}.md"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            if OUTPUTS_DIR.resolve() == resolved or OUTPUTS_DIR.resolve() in resolved.parents:
                return resolved

    if source is None:
        try:
            return _custom_article_markdown_path(safe_name)
        except HTTPException:
            pass

    raise HTTPException(status_code=404, detail=f"Final article not found: {safe_name}")


def _custom_article_package_path(safe_name: str) -> Path:
    _validate_safe_name(safe_name)
    latest = _load_custom_article_latest()
    latest_safe_name = str(latest.get("full_name") or "").replace("/", "__")
    package_path = latest.get("package_path") or latest.get("packaged_article_path")
    if latest.get("exists") and latest_safe_name == safe_name and package_path:
        try:
            path = _safe_workspace_or_outputs_path(str(package_path))
            if path.exists() and path.suffix == ".md":
                return path
        except HTTPException:
            pass

    if OUTPUTS_DIR.exists():
        candidates = sorted(
            OUTPUTS_DIR.glob(f"*/assets/{safe_name}/packaged_article.md"),
            key=lambda path: path.parts[-4] if len(path.parts) >= 4 else "",
            reverse=True,
        )
        outputs_root = OUTPUTS_DIR.resolve()
        for candidate in candidates:
            resolved = candidate.resolve()
            if outputs_root == resolved or outputs_root in resolved.parents:
                return resolved

    raise HTTPException(status_code=404, detail=f"Custom packaged article not found: {safe_name}")


def _package_markdown_path(safe_name: str, source: str | None = None) -> Path:
    _validate_safe_name(safe_name)
    if source == "custom":
        return _custom_article_package_path(safe_name)
    if source is None:
        try:
            return _custom_article_package_path(safe_name)
        except HTTPException:
            pass

    run_date = latest_output_date()
    if run_date:
        path = safe_project_path(Path("outputs") / run_date / "assets" / safe_name / "packaged_article.md")
        if path.exists():
            return path

    if OUTPUTS_DIR.exists():
        candidates = sorted(
            OUTPUTS_DIR.glob(f"*/assets/{safe_name}/packaged_article.md"),
            key=lambda path: path.parts[-4] if len(path.parts) >= 4 else "",
            reverse=True,
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            if OUTPUTS_DIR.resolve() == resolved or OUTPUTS_DIR.resolve() in resolved.parents:
                return resolved

    raise HTTPException(status_code=404, detail=f"Packaged article not found: {safe_name}")


def _article_list_item(article: dict[str, Any]) -> dict[str, Any]:
    full_name = str(article.get("full_name") or "")
    safe_name = _safe_name(full_name) if full_name else ""
    local_path = None
    try:
        if safe_name:
            path = _article_markdown_path(safe_name)
            local_path = _relative_path(path)
    except HTTPException:
        local_path = None
    packaged_path = None
    try:
        if safe_name:
            packaged_path = _relative_path(_package_markdown_path(safe_name))
    except HTTPException:
        packaged_path = None

    review = article.get("review") if isinstance(article.get("review"), dict) else {}
    humanization_report = (
        article.get("humanization_report")
        if isinstance(article.get("humanization_report"), dict)
        else {}
    )
    article_quality_report = (
        article.get("article_quality_report")
        if isinstance(article.get("article_quality_report"), dict)
        else {}
    )
    return {
        "full_name": full_name,
        "repo_full_name": full_name,
        "safe_name": safe_name,
        "source": "daily",
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "word_count": article.get("word_count", 0),
        "review_score": review.get("total_score"),
        "pass_review": review.get("pass_review"),
        "html_url": article.get("html_url", ""),
        "local_markdown_path": local_path,
        "markdown_path": local_path,
        "packaged_article_path": packaged_path,
        "package_path": packaged_path,
        "packaged_article_available": bool(packaged_path),
        "generation_mode": article.get("generation_mode"),
        "content_plan_used": article.get("content_plan_used"),
        "narrative_pattern": article.get("narrative_pattern"),
        "title_style": article.get("title_style"),
        "humanized": article.get("humanized", False),
        "humanization_mode": article.get("humanization_mode"),
        "publish_ready": article.get("publish_ready", False),
        "publish_polish_mode": article.get("publish_polish_mode"),
        "article_quality_report": article_quality_report or None,
        "quality_score": article.get("quality_score", article_quality_report.get("total_score")),
        "quality_publish_ready": article.get("quality_publish_ready", article_quality_report.get("publish_ready", False)),
        "ai_smell_score": humanization_report.get("ai_smell_score"),
        "template_risk": humanization_report.get("template_risk"),
        "localization_score": humanization_report.get("localization_score"),
        "readme_similarity_risk": humanization_report.get("readme_similarity_risk"),
        "asset_count": article.get("asset_count", 0),
    }


def _custom_article_list_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    full_name = str(payload.get("full_name") or "")
    if not full_name:
        return None
    safe_name = _safe_name(full_name)
    final_article = payload.get("final_article") if isinstance(payload.get("final_article"), dict) else {}
    markdown_path = payload.get("output_markdown_path")
    if not markdown_path:
        try:
            markdown_path = _relative_path(_custom_article_markdown_path(safe_name))
        except HTTPException:
            markdown_path = None
    package_path = payload.get("package_path") or payload.get("packaged_article_path")
    if not package_path:
        try:
            package_path = _relative_path(_package_markdown_path(safe_name))
        except HTTPException:
            package_path = None
    title = payload.get("title") or final_article.get("title") or ""
    if not title and markdown_path:
        try:
            title = _markdown_title(_safe_workspace_or_outputs_path(str(markdown_path)))
        except HTTPException:
            title = ""
    review = final_article.get("review") if isinstance(final_article.get("review"), dict) else {}
    humanization_report = (
        final_article.get("humanization_report")
        if isinstance(final_article.get("humanization_report"), dict)
        else payload.get("humanization_report")
        if isinstance(payload.get("humanization_report"), dict)
        else {}
    )
    article_quality_report = (
        final_article.get("article_quality_report")
        if isinstance(final_article.get("article_quality_report"), dict)
        else payload.get("article_quality_report")
        if isinstance(payload.get("article_quality_report"), dict)
        else {}
    )
    return {
        "full_name": full_name,
        "repo_full_name": full_name,
        "safe_name": safe_name,
        "source": "custom",
        "title": title,
        "summary": payload.get("summary") or final_article.get("summary", ""),
        "word_count": final_article.get("word_count", 0),
        "review_score": review.get("total_score"),
        "pass_review": review.get("pass_review"),
        "html_url": payload.get("normalized_repo_url") or final_article.get("html_url") or f"https://github.com/{full_name}",
        "local_markdown_path": markdown_path,
        "markdown_path": markdown_path,
        "packaged_article_path": package_path,
        "package_path": package_path,
        "packaged_article_available": bool(payload.get("packaged_article_available") or package_path),
        "generation_mode": final_article.get("generation_mode"),
        "content_plan_used": final_article.get("content_plan_used"),
        "narrative_pattern": final_article.get("narrative_pattern"),
        "title_style": final_article.get("title_style"),
        "humanized": final_article.get("humanized", False),
        "humanization_mode": final_article.get("humanization_mode"),
        "publish_ready": final_article.get("publish_ready", False),
        "publish_polish_mode": final_article.get("publish_polish_mode"),
        "article_quality_report": article_quality_report or None,
        "quality_score": payload.get("quality_score", final_article.get("quality_score", article_quality_report.get("total_score"))),
        "quality_publish_ready": payload.get(
            "quality_publish_ready",
            final_article.get("quality_publish_ready", article_quality_report.get("publish_ready", False)),
        ),
        "ai_smell_score": humanization_report.get("ai_smell_score"),
        "template_risk": humanization_report.get("template_risk"),
        "localization_score": humanization_report.get("localization_score"),
        "readme_similarity_risk": humanization_report.get("readme_similarity_risk"),
        "generated_at": payload.get("generated_at"),
        "selected_readme_images": payload.get("selected_readme_images") or [],
        "asset_count": payload.get("asset_count", 0),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "project": "GitHubRadarAgent",
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "paths": {
            "workspace": _relative_path(WORKSPACE_DIR),
            "outputs": _relative_path(OUTPUTS_DIR),
        },
    }


@app.get("/api/config/status")
def config_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "github_token_configured": bool(settings.github_personal_access_token),
        "llm_configured": bool(settings.openai_api_key and settings.openai_model),
        "output_dir": "outputs",
        "workspace_dir": "workspace",
        "daily_keywords": settings.daily_keywords,
    }


@app.get("/api/settings")
def get_ui_settings() -> dict[str, Any]:
    settings, exists = load_ui_settings()
    return {
        "settings": _model_dump(settings),
        "source": "workspace/ui_settings.json",
        "exists": exists,
    }


@app.put("/api/settings")
def update_ui_settings(settings: UiSettings) -> dict[str, Any]:
    saved = save_ui_settings(settings)
    return {
        "settings": _model_dump(saved),
        "source": "workspace/ui_settings.json",
        "exists": True,
    }


@app.post("/api/settings/reset")
def reset_ui_settings() -> dict[str, Any]:
    settings = _parse_ui_settings(DEFAULT_UI_SETTINGS)
    saved = save_ui_settings(settings)
    return {
        "settings": _model_dump(saved),
        "source": "workspace/ui_settings.json",
        "exists": True,
    }


@app.get("/api/runs/latest")
def latest_run() -> dict[str, Any]:
    path = safe_project_path("workspace/runs/latest_run.json")
    if not path.exists():
        return {"exists": False, "message": "No run has been executed yet."}
    payload = read_json_file(path)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Latest run JSON must be an object.")
    return {"exists": True, **payload}


@app.get("/api/runs")
def runs() -> dict[str, Any]:
    runs_dir = safe_project_path("workspace/runs")
    if not runs_dir.exists():
        return {"runs": []}

    run_items = []
    for path in sorted(runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name == "latest_run.json":
            continue
        payload = read_json_file(path)
        if not isinstance(payload, dict):
            continue
        run_items.append(
            {
                "run_id": payload.get("run_id", path.stem),
                "date": payload.get("date"),
                "status": payload.get("status"),
                "started_at": payload.get("started_at"),
                "finished_at": payload.get("finished_at"),
                "file": _relative_path(path),
            }
        )
    return {"runs": run_items}


@app.get("/api/snapshots/{name}")
def snapshot(name: str) -> Any:
    relative_path = SNAPSHOT_FILES.get(name)
    if relative_path is None:
        allowed = ", ".join(sorted(SNAPSHOT_FILES))
        raise HTTPException(status_code=404, detail=f"Unknown snapshot '{name}'. Allowed: {allowed}")
    path = safe_project_path(relative_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {_relative_path(path)}")
    return read_json_file(path)


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    settings = get_settings()
    latest = _read_optional_json("workspace/runs/latest_run.json")
    discovery = _read_optional_json("workspace/snapshots/discovery_latest.json")
    score = _read_optional_json("workspace/snapshots/score_latest.json")
    final = _read_optional_json("workspace/snapshots/final_articles_latest.json")
    reviews = _read_optional_json("workspace/snapshots/reviews_latest.json")
    article_quality = _read_optional_json("workspace/snapshots/article_quality_latest.json")
    selection = _read_optional_json("workspace/snapshots/selection_latest.json")

    candidates = discovery.get("candidates", []) if isinstance(discovery, dict) else []
    score_ranking = _score_ranking(score, limit=10)
    final_articles = [_article_list_item(article) for article in _final_articles_payload(final)]
    review_summary = _review_summary(reviews)

    run_info = {
        "run_id": latest.get("run_id") if isinstance(latest, dict) else None,
        "status": latest.get("status", "unknown") if isinstance(latest, dict) else "unknown",
        "duration": _duration(
            latest.get("started_at") if isinstance(latest, dict) else None,
            latest.get("finished_at") if isinstance(latest, dict) else None,
        ),
        "output": latest.get("output_dir") if isinstance(latest, dict) else None,
    }

    return {
        "health": {
            "github_token_configured": bool(settings.github_personal_access_token),
            "llm_configured": bool(settings.openai_api_key and settings.openai_model),
            "last_run_status": run_info["status"],
        },
        "stats": {
            "today_candidates": len(candidates) if isinstance(candidates, list) else 0,
            "top_scored_projects": len(score_ranking),
            "final_articles": len(final_articles),
            "review_pass_rate": review_summary["pass_rate"],
            "average_quality_score": article_quality.get("average_score", 0.0)
            if isinstance(article_quality, dict)
            else 0.0,
        },
        "run_info": run_info,
        "pipeline": _pipeline_from_run(latest if isinstance(latest, dict) else None),
        "score_ranking": score_ranking,
        "final_articles": final_articles,
        "review_summary": review_summary,
        "selection_summary": selection if isinstance(selection, dict) else None,
    }


@app.get("/api/articles/final")
def final_articles() -> dict[str, Any]:
    payload = _read_optional_json("workspace/snapshots/final_articles_latest.json")
    articles = [_article_list_item(article) for article in _final_articles_payload(payload)]
    custom_articles = [
        item
        for item in (_custom_article_list_item(payload) for payload in _custom_article_payloads())
        if item is not None
    ]
    articles.extend(custom_articles)
    return {"articles": articles}


@app.get("/api/articles/final/{safe_name}")
def final_article(safe_name: str, source: Any = None) -> dict[str, Any]:
    if "/" in safe_name or "\\" in safe_name or ".." in safe_name:
        raise HTTPException(status_code=400, detail="Invalid article safe_name.")
    if source not in {None, "daily", "custom"}:
        raise HTTPException(status_code=400, detail="Invalid article source.")
    path = _article_markdown_path(safe_name, source=source)
    return {
        "safe_name": safe_name,
        "source": source or "daily",
        "content_markdown": read_text_file(path),
        "path": _relative_path(path),
    }


@app.post("/api/articles/package")
def package_articles(request: PackageArticlesRequest) -> dict[str, Any]:
    payload = _model_dump(request)
    try:
        os.chdir(PROJECT_ROOT)
        packages = DailyOrchestrator().package_articles(
            top=payload.get("top"),
            safe_names=payload.get("safe_names") or None,
            full_names=payload.get("full_names") or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Article packaging failed: {type(exc).__name__}: {exc}")
    return _package_response(packages)


@app.post("/api/articles/package/async")
def package_articles_async(request: PackageArticlesRequest) -> dict[str, Any]:
    payload = _model_dump(request)
    params = {
        "top": payload.get("top"),
        "safe_names": payload.get("safe_names") or [],
        "full_names": payload.get("full_names") or [],
    }
    job_id = job_manager.create_job(params, stages=["package-articles"])

    def task() -> Any:
        os.chdir(PROJECT_ROOT)
        job_manager.add_event(
            job_id,
            {
                "type": "run_started",
                "message": "Article packaging started.",
                "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            },
        )
        job_manager.add_event(
            job_id,
            {
                "type": "stage_started",
                "stage": "package-articles",
                "message": "Generating article packages.",
                "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            },
        )
        try:
            packages = DailyOrchestrator().package_articles(
                top=params["top"],
                safe_names=params["safe_names"] or None,
                full_names=params["full_names"] or None,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            job_manager.add_event(
                job_id,
                {
                    "type": "stage_failed",
                    "stage": "package-articles",
                    "message": "Article packaging failed.",
                    "error": error,
                    "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                },
            )
            job_manager.add_event(
                job_id,
                {
                    "type": "run_failed",
                    "message": "Article packaging failed.",
                    "error": error,
                    "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                },
            )
            raise
        response = _package_response(packages)
        job_manager.add_event(
            job_id,
            {
                "type": "stage_succeeded",
                "stage": "package-articles",
                "message": f"Generated {response['total_count']} article packages.",
                "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            },
        )
        job_manager.add_event(
            job_id,
            {
                "type": "run_succeeded",
                "message": "Article packaging completed.",
                "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "result": {
                    "status": "success",
                    "package_count": response["total_count"],
                },
            },
        )
        return response

    job_manager.start_job(job_id, task)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/reports/{report_name}")
def report(report_name: str) -> dict[str, Any]:
    filename = REPORT_FILES.get(report_name)
    if filename is None:
        allowed = ", ".join(sorted(REPORT_FILES))
        raise HTTPException(status_code=404, detail=f"Unknown report '{report_name}'. Allowed: {allowed}")

    run_date = latest_output_date()
    if not run_date:
        raise HTTPException(status_code=404, detail="No output date is available yet.")

    path = safe_project_path(Path("outputs") / run_date / filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {_relative_path(path)}")

    return {
        "report_name": report_name,
        "content_markdown": read_text_file(path),
        "path": _relative_path(path),
    }


@app.get("/api/outputs")
def outputs() -> dict[str, Any]:
    if not OUTPUTS_DIR.exists():
        return {"dates": []}

    date_items = []
    for date_dir in sorted(OUTPUTS_DIR.iterdir(), key=lambda item: item.name, reverse=True):
        if not date_dir.is_dir() or not DATE_PATTERN.fullmatch(date_dir.name):
            continue
        reports = sorted(path.name for path in date_dir.glob("*.md") if path.name in REPORT_FILES.values())
        articles = _article_items(date_dir, "articles")
        final_articles = _article_items(date_dir, "final_articles")
        packages = _package_items(date_dir)
        assets = _asset_items(date_dir)
        date_items.append(
            {
                "date": date_dir.name,
                "path": _relative_path(date_dir),
                "reports": reports,
                "final_articles_count": len(final_articles),
                "articles_count": len(articles),
                "packages_count": len(packages),
                "assets_count": len(assets),
            }
        )
    return {"dates": date_items}


@app.get("/api/outputs/{date}")
def output_date(date: str) -> dict[str, Any]:
    date_dir = _output_date_dir(date)
    if not date_dir.exists() or not date_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Output date not found: {date}")

    return {
        "date": date,
        "reports": _report_items(date_dir),
        "articles": _article_items(date_dir, "articles"),
        "final_articles": _article_items(date_dir, "final_articles"),
        "packages": _package_items(date_dir),
        "assets": _asset_items(date_dir),
    }


@app.get("/api/outputs/{date}/reports/{report_name}")
def output_report(date: str, report_name: str) -> dict[str, Any]:
    filename = REPORT_FILES.get(report_name)
    if filename is None:
        allowed = ", ".join(sorted(REPORT_FILES))
        raise HTTPException(status_code=404, detail=f"Unknown report '{report_name}'. Allowed: {allowed}")

    date_dir = _output_date_dir(date)
    path = (date_dir / filename).resolve()
    return {
        "date": date,
        "report_name": report_name,
        "filename": filename,
        "content_markdown": _read_output_markdown(path),
        "path": _relative_path(path),
    }


@app.get("/api/outputs/{date}/final-articles/{safe_name}")
def output_final_article(date: str, safe_name: str) -> dict[str, Any]:
    _validate_safe_name(safe_name)
    path = (_output_date_dir(date) / "final_articles" / f"{safe_name}.md").resolve()
    return {
        "date": date,
        "safe_name": safe_name,
        "content_markdown": _read_output_markdown(path),
        "path": _relative_path(path),
    }


@app.get("/api/articles/package/{safe_name}")
def packaged_article(safe_name: str, source: Any = None) -> dict[str, Any]:
    if "/" in safe_name or "\\" in safe_name or ".." in safe_name:
        raise HTTPException(status_code=400, detail="Invalid article safe_name.")
    if source not in {None, "daily", "custom"}:
        raise HTTPException(status_code=400, detail="Invalid article source.")
    path = _package_markdown_path(safe_name, source=source)
    return {
        "safe_name": safe_name,
        "source": source or "daily",
        "content_markdown": read_text_file(path),
        "path": _relative_path(path),
    }


@app.post("/api/custom-articles/async")
def custom_article_async(request: CustomArticleRequest) -> dict[str, Any]:
    payload = _model_dump(request)
    params = {
        "repo_url": payload["repo_url"],
        "direction": payload.get("direction") or "",
        "reference_text_count": len(payload.get("reference_texts") or []),
        "reference_source_names": payload.get("reference_source_names") or [],
    }
    job_id = job_manager.create_job(params, stages=CUSTOM_ARTICLE_STAGES)

    def task() -> Any:
        os.chdir(PROJECT_ROOT)
        return DailyOrchestrator().write_custom_article(
            repo_url=payload["repo_url"],
            direction_text=payload.get("direction") or None,
            reference_texts=payload.get("reference_texts") or [],
            reference_source_names=payload.get("reference_source_names") or [],
            progress_callback=lambda event: job_manager.add_event(job_id, event),
        )

    job_manager.start_job(job_id, task)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/custom-articles/latest")
def latest_custom_article() -> dict[str, Any]:
    return _load_custom_article_latest()


@app.get("/api/custom-articles/latest/content")
def latest_custom_article_content() -> dict[str, Any]:
    return _custom_article_markdown_response(
        "output_markdown_path",
        "No custom article Markdown has been generated yet.",
    )


@app.get("/api/custom-articles/latest/report")
def latest_custom_article_report() -> dict[str, Any]:
    return _custom_article_markdown_response(
        "report_path",
        "No custom article report has been generated yet.",
    )


@app.get("/api/custom-articles/latest/package")
def latest_custom_article_package() -> dict[str, Any]:
    return _custom_article_markdown_response(
        "package_path",
        "No custom article package has been generated yet.",
    )


@app.get("/api/outputs/{date}/packages/{safe_name}")
def output_packaged_article(date: str, safe_name: str) -> dict[str, Any]:
    _validate_safe_name(safe_name)
    path = (_output_date_dir(date) / "assets" / safe_name / "packaged_article.md").resolve()
    return {
        "date": date,
        "safe_name": safe_name,
        "content_markdown": _read_output_markdown(path),
        "path": _relative_path(path),
    }


@app.get("/api/outputs/{date}/assets/{safe_name}/{filename}")
def output_asset(date: str, safe_name: str, filename: str) -> FileResponse:
    _validate_safe_name(safe_name)
    if not SAFE_NAME_PATTERN.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid asset filename.")
    path = (_output_date_dir(date) / "assets" / safe_name / filename).resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if path == outputs_root or outputs_root not in path.parents:
        raise HTTPException(status_code=400, detail="Path is outside outputs directory.")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Asset not found: {_relative_path(path)}")
    return FileResponse(path)


@app.get("/api/outputs/{date}/articles/{safe_name}")
def output_article(date: str, safe_name: str) -> dict[str, Any]:
    _validate_safe_name(safe_name)
    path = (_output_date_dir(date) / "articles" / f"{safe_name}.md").resolve()
    return {
        "date": date,
        "safe_name": safe_name,
        "content_markdown": _read_output_markdown(path),
        "path": _relative_path(path),
    }


@app.post("/api/run-daily")
def run_daily(request: RunDailyRequest) -> dict[str, Any]:
    params = _resolved_run_daily_params(request)
    try:
        os.chdir(PROJECT_ROOT)
        run = DailyOrchestrator().run_daily(
            limit_per_keyword=params["limit_per_keyword"],
            score_top=params["score_top"],
            research_top=params["research_top"],
            article_top=params["article_top"],
            review_threshold=params["review_threshold"],
            cooldown_days=params["cooldown_days"],
            ignore_history=params["ignore_history"],
            allow_recent_fallback=params["allow_recent_fallback"],
            prefer_growth_projects=params["prefer_growth_projects"],
            daily_keywords=params["daily_keywords"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily run failed: {type(exc).__name__}: {exc}")

    return _model_dump(run)


@app.post("/api/run-daily/async")
def run_daily_async(request: RunDailyRequest) -> dict[str, Any]:
    params = _resolved_run_daily_params(request)
    job_id = job_manager.create_job(params)

    def task() -> Any:
        os.chdir(PROJECT_ROOT)
        return DailyOrchestrator().run_daily(
            limit_per_keyword=params["limit_per_keyword"],
            score_top=params["score_top"],
            research_top=params["research_top"],
            article_top=params["article_top"],
            review_threshold=params["review_threshold"],
            cooldown_days=params["cooldown_days"],
            ignore_history=params["ignore_history"],
            allow_recent_fallback=params["allow_recent_fallback"],
            prefer_growth_projects=params["prefer_growth_projects"],
            daily_keywords=params["daily_keywords"],
            progress_callback=lambda event: job_manager.add_event(job_id, event),
        )

    job_manager.start_job(job_id, task)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs")
def jobs() -> dict[str, Any]:
    return {"jobs": job_manager.list_jobs()}


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    payload = job_manager.get_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return payload


def _sse_message(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    if job_manager.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    def stream():
        index = 0
        while True:
            events, current_job = job_manager.wait_for_events(job_id, index, timeout=15.0)
            if current_job is None:
                yield _sse_message("error", {"status": "failed", "error": "Job is no longer available."})
                break

            for event in events:
                index += 1
                yield _sse_message("progress", event)
                if event.get("type") == "run_succeeded":
                    yield _sse_message("done", {"status": "success"})
                    return
                if event.get("type") == "run_failed":
                    yield _sse_message("error", {"status": "failed", "error": event.get("error") or event.get("message")})
                    return

            if not events:
                if current_job.get("status") == "success":
                    yield _sse_message("done", {"status": "success"})
                    return
                if current_job.get("status") == "failed":
                    yield _sse_message("error", {"status": "failed", "error": current_job.get("error")})
                    return
                yield ": keep-alive\n\n"
                time.sleep(0.1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
