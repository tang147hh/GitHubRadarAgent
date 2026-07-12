from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from src.models import ContentIndex, ContentItem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
INDEX_PATH = WORKSPACE_DIR / "content" / "content_index_latest.json"
SNAPSHOT_PATH = WORKSPACE_DIR / "snapshots" / "content_index_latest.json"
CONTENT_TYPES = (
    "github_article",
    "github_custom_article",
    "ai_news_article",
    "ai_news_digest",
    "agent_artifact",
    "manual_edit",
)
PUBLISHING_CONTENT_TYPES = frozenset(
    {"github_article", "github_custom_article", "ai_news_article", "ai_news_digest", "agent_artifact"}
)


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _validate_index(data: dict[str, Any]) -> ContentIndex:
    if hasattr(ContentIndex, "model_validate"):
        return ContentIndex.model_validate(data)
    return ContentIndex.parse_obj(data)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _first_heading(path: Path, fallback: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^#\s+(.+?)\s*$", line)
            if match:
                return match.group(1).strip()
    except OSError:
        pass
    return fallback.replace("__", "/").replace("_", " ")


def _word_count(path: Path) -> Optional[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text))
    return chinese + words


class ContentIndexService:
    def __init__(self, project_root: Path | str = PROJECT_ROOT):
        self.project_root = Path(project_root).resolve()
        self.outputs_dir = self.project_root / "outputs"
        self.workspace_dir = self.project_root / "workspace"
        self.index_path = self.workspace_dir / "content" / "content_index_latest.json"
        self.snapshot_path = self.workspace_dir / "snapshots" / "content_index_latest.json"
        self.report_path: Optional[Path] = None

    def build_index(
        self,
        date: Optional[str] = None,
        include_agent_artifacts: bool = True,
    ) -> ContentIndex:
        if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("date must use YYYY-MM-DD format")

        items: dict[str, ContentItem] = {}
        warnings: list[str] = []
        metadata = self._load_metadata()
        output_dirs = self._output_dirs(date)

        self._scan_github(output_dirs, items, metadata)
        self._scan_news_articles(output_dirs, items, metadata)
        self._scan_news_digests(output_dirs, items, metadata)
        if include_agent_artifacts:
            self._scan_agent_runs(items, date)
        self._scan_manual_edits(output_dirs, items)

        for item in items.values():
            self._apply_readiness(item)

        sorted_items = sorted(
            items.values(),
            key=lambda item: (item.updated_at or item.created_at or item.date, item.title),
            reverse=True,
        )
        counts = Counter(item.content_type for item in sorted_items)
        type_counts = {kind: counts.get(kind, 0) for kind in CONTENT_TYPES}
        publishing_items = [item for item in sorted_items if item.content_type in PUBLISHING_CONTENT_TYPES]
        readiness_counts = self.publishing_summary(publishing_items)
        index = ContentIndex(
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            total_count=len(sorted_items),
            type_counts=type_counts,
            items=sorted_items,
            warnings=warnings,
            **readiness_counts,
        )
        self.save_index(index, report_date=date)
        return index

    def load_latest_index(self) -> Optional[ContentIndex]:
        data = _read_json(self.index_path)
        if not isinstance(data, dict):
            return None
        try:
            return _validate_index(data)
        except Exception:
            return None

    def save_index(self, index: ContentIndex, report_date: Optional[str] = None) -> tuple[Path, Path]:
        payload = json.dumps(_dump_model(index), ensure_ascii=False, indent=2)
        for path in (self.index_path, self.snapshot_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        target_date = report_date or datetime.now().date().isoformat()
        self.report_path = self.outputs_dir / target_date / "content_index_report.md"
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(self._render_report(index), encoding="utf-8")
        return self.index_path, self.report_path

    def find_item(self, content_id: str) -> Optional[ContentItem]:
        index = self.load_latest_index()
        if not index:
            return None
        return next((item for item in index.items if item.content_id == content_id), None)

    def read_markdown(self, content_id: str, variant: str = "source") -> tuple[str, str]:
        variants = {
            "source": "markdown_path",
            "publish": "publish_path",
            "package": "package_path",
            "report": "report_path",
            "manual": "manual_edit_path",
        }
        field = variants.get(variant)
        if not field:
            raise ValueError(f"Unsupported variant: {variant}")
        item = self.find_item(content_id)
        if not item:
            raise KeyError(content_id)
        stored_path = getattr(item, field)
        if not stored_path:
            raise FileNotFoundError(f"{variant} variant is not available")
        path = self._safe_path(stored_path)
        if not path.is_file():
            raise FileNotFoundError(f"Indexed {variant} file no longer exists")
        return path.read_text(encoding="utf-8"), self._relative(path)

    def read_report(self) -> tuple[str, str]:
        index = self.load_latest_index()
        if not index:
            index = self.build_index()
        date = index.generated_at[:10]
        candidates = [self.outputs_dir / date / "content_index_report.md"]
        candidates.extend(sorted(self.outputs_dir.glob("*/content_index_report.md"), reverse=True))
        for path in candidates:
            if path.is_file():
                safe = self._safe_path(path)
                return safe.read_text(encoding="utf-8"), self._relative(safe)
        raise FileNotFoundError("Content index report is not available")

    def build_publishing_desk(self, rebuild: bool = False) -> dict[str, Any]:
        stored_payload = _read_json(self.index_path) if not rebuild else None
        index = self.build_index() if rebuild else self.load_latest_index()
        if index is None:
            index = self.build_index()
        elif not isinstance(stored_payload, dict) or "ready_count" not in stored_payload:
            index = self.build_index()
        items = [item for item in index.items if item.content_type in PUBLISHING_CONTENT_TYPES]
        return {
            "generated_at": index.generated_at,
            "summary": self.publishing_summary(items),
            "items": [_dump_model(item) for item in items],
            "warnings": list(index.warnings),
        }

    @staticmethod
    def publishing_summary(items: Iterable[ContentItem]) -> dict[str, int]:
        rows = list(items)
        return {
            "ready_count": sum(item.readiness_status == "ready" for item in rows),
            "needs_package_count": sum(bool(item.markdown_path or item.publish_path) and not item.package_path for item in rows),
            "quality_low_count": sum(item.quality_score is not None and item.quality_score < 80 for item in rows),
            "needs_review_count": sum(item.quality_score is None or not item.report_path for item in rows),
            "manual_edit_count": sum(item.has_manual_edit for item in rows),
            "packaged_count": sum(bool(item.package_path) for item in rows),
        }

    def export_publish_markdown(self, content_id: str) -> dict[str, Any]:
        item = self.find_item(content_id)
        if item is None or item.content_type not in PUBLISHING_CONTENT_TYPES:
            raise KeyError(content_id)
        for variant, field in (
            ("manual", "manual_edit_path"),
            ("publish", "publish_path"),
            ("package", "package_path"),
            ("source", "markdown_path"),
        ):
            if getattr(item, field):
                content, path = self.read_markdown(content_id, variant)
                return {
                    "content_id": content_id,
                    "title": item.title,
                    "variant": variant,
                    "content": content,
                    "path": path,
                    "source_urls": list(item.source_urls),
                    "has_package": bool(item.package_path),
                    "warnings": list(item.warnings),
                }
        raise FileNotFoundError("No publishable Markdown variant is available")

    @staticmethod
    def _apply_readiness(item: ContentItem) -> None:
        has_content = bool(item.markdown_path or item.publish_path)
        has_package = bool(item.package_path)
        quality_low = item.quality_score is not None and item.quality_score < 80
        needs_review = item.quality_score is None or not item.report_path
        meaningful_warnings = [warning for warning in item.warnings if "package generated from manual edit" not in warning.lower()]
        high_warning = any(
            re.search(r"\b(high|critical|fatal|severe)\b|严重|高风险|致命", warning, re.IGNORECASE)
            for warning in meaningful_warnings
        )

        reasons: list[str] = []
        actions: list[str] = []
        if not has_content:
            reasons.append("Article Markdown is missing")
            actions.append("Generate or restore article content")
        if has_content and not has_package:
            reasons.append("Publishing package is missing")
            actions.append("Generate a publishing package")
        if quality_low:
            reasons.append(f"Quality score {item.quality_score:g} is below 80")
            actions.extend(["Review the quality report", "Create a manual edit"])
        if item.quality_score is None:
            reasons.append("Quality score is missing")
        if not item.report_path:
            reasons.append("Quality report is missing")
        if needs_review:
            actions.append("Run content quality evaluation")
        if meaningful_warnings:
            reasons.append(f"{len(meaningful_warnings)} warning(s) require attention")
            actions.append("Review warnings and edit the article")

        if item.publish_ready and has_content and has_package and not high_warning:
            status = "ready"
        elif not has_content:
            status = "missing_content"
        elif quality_low:
            status = "quality_low"
        elif not has_package:
            status = "needs_package"
        elif needs_review:
            status = "needs_review"
        elif meaningful_warnings:
            status = "needs_manual_edit"
        elif reasons:
            status = "unknown"
        else:
            status = "unknown"
            reasons.append("Publishing readiness cannot be determined")
            actions.append("Review content metadata")

        item.readiness_status = status
        item.readiness_reasons = list(dict.fromkeys(reasons))
        item.next_actions = list(dict.fromkeys(actions))

    def _output_dirs(self, date: Optional[str]) -> list[Path]:
        if date:
            path = self.outputs_dir / date
            return [path] if path.is_dir() else []
        return sorted((path for path in self.outputs_dir.glob("????-??-??") if path.is_dir()))

    def _load_metadata(self) -> dict[str, Any]:
        final = _read_json(self.workspace_dir / "snapshots" / "final_articles_latest.json") or {}
        custom = _read_json(self.workspace_dir / "snapshots" / "custom_article_latest.json") or {}
        articles: dict[str, dict[str, Any]] = {}
        for path in (self.workspace_dir / "news" / "articles").glob("*.json"):
            data = _read_json(path)
            if isinstance(data, dict) and data.get("article_id"):
                articles[str(data["article_id"])] = data
        latest_article = _read_json(self.workspace_dir / "news" / "news_article_latest.json")
        if isinstance(latest_article, dict) and latest_article.get("article_id"):
            articles[str(latest_article["article_id"])] = latest_article
        return {"final": final, "custom": custom, "news_articles": articles}

    def _scan_github(self, output_dirs: Iterable[Path], items: dict[str, ContentItem], metadata: dict[str, Any]) -> None:
        final_meta = {
            str(article.get("full_name", "")).replace("/", "__").lower(): article
            for article in metadata.get("final", {}).get("articles", [])
            if isinstance(article, dict)
        }
        custom_data = metadata.get("custom", {})
        custom_safe = str(custom_data.get("full_name", "")).replace("/", "__").lower()
        for day_dir in output_dirs:
            date = day_dir.name
            for kind, folder, content_type in (
                ("final", "final_articles", "github_article"),
                ("custom", "custom_articles", "github_custom_article"),
            ):
                for path in sorted((day_dir / folder).glob("*.md")):
                    if path.stem.endswith("_report"):
                        continue
                    safe_name = path.stem
                    data = final_meta.get(safe_name.lower(), {}) if kind == "final" else (
                        custom_data if safe_name.lower() == custom_safe else {}
                    )
                    full_name = data.get("full_name") or safe_name.replace("__", "/")
                    final_article = data.get("final_article") if isinstance(data.get("final_article"), dict) else {}
                    title = data.get("title") or final_article.get("title") or _first_heading(path, safe_name)
                    package = day_dir / "assets" / safe_name / "packaged_article.md"
                    report = day_dir / folder / f"{safe_name}_report.md"
                    quality = data.get("quality_score")
                    if quality is None:
                        quality = (data.get("article_quality_report") or {}).get("total_score")
                    publish_ready = bool(data.get("quality_publish_ready", data.get("publish_ready", False)))
                    item = ContentItem(
                        content_id=self._content_id(content_type, date, full_name),
                        title=title,
                        content_type=content_type,
                        source="github",
                        source_id=full_name,
                        safe_name=safe_name,
                        date=date,
                        created_at=data.get("generated_at"),
                        updated_at=data.get("generated_at") or self._mtime(path),
                        status="packaged" if package.is_file() else ("publish_ready" if publish_ready else "draft"),
                        quality_score=quality,
                        publish_ready=publish_ready,
                        markdown_path=self._relative(path),
                        package_path=self._relative(package) if package.is_file() else None,
                        report_path=self._relative(report) if report.is_file() else None,
                        source_urls=list(data.get("source_links") or final_article.get("source_links") or []),
                        repo_full_name=full_name,
                        generation_mode=data.get("generation_mode") or final_article.get("generation_mode"),
                        word_count=data.get("word_count") or final_article.get("word_count") or _word_count(path),
                        tags=["github", "custom" if kind == "custom" else "daily"],
                        warnings=list(data.get("warnings") or []),
                    )
                    items[item.content_id] = item

    def _scan_news_articles(self, output_dirs: Iterable[Path], items: dict[str, ContentItem], metadata: dict[str, Any]) -> None:
        article_meta = metadata.get("news_articles", {})
        for day_dir in output_dirs:
            folder = day_dir / "news_articles"
            for path in sorted(folder.glob("*.md")):
                stem = path.stem
                if stem.endswith(("_publish", "_package", "_report", "_quality_report")):
                    continue
                data = article_meta.get(stem, {})
                publish = folder / f"{stem}_publish.md"
                package = folder / f"{stem}_package.md"
                report = folder / f"{stem}_report.md"
                quality_report = folder / f"{stem}_quality_report.md"
                publish_ready = bool(data.get("quality_publish_ready", data.get("publish_ready", publish.is_file())))
                quality = data.get("quality_score")
                if quality is None:
                    quality = (data.get("quality_report") or {}).get("total_score")
                item = ContentItem(
                    content_id=self._content_id("ai_news_article", day_dir.name, stem),
                    title=data.get("title") or _first_heading(path, stem),
                    content_type="ai_news_article",
                    source="ai_news",
                    source_id=stem,
                    safe_name=stem,
                    date=day_dir.name,
                    created_at=data.get("generated_at"),
                    updated_at=data.get("generated_at") or self._mtime(path),
                    status="packaged" if package.is_file() else ("publish_ready" if publish_ready else "draft"),
                    quality_score=quality,
                    publish_ready=publish_ready,
                    markdown_path=self._relative(path),
                    publish_path=self._relative(publish) if publish.is_file() else None,
                    package_path=self._relative(package) if package.is_file() else None,
                    report_path=self._relative(quality_report if quality_report.is_file() else report) if (quality_report.is_file() or report.is_file()) else None,
                    source_urls=list(data.get("source_urls") or []),
                    news_ids=list(data.get("source_news_ids") or ([data["primary_news_id"]] if data.get("primary_news_id") else [])),
                    generation_mode=data.get("generation_mode"),
                    word_count=data.get("word_count") or _word_count(path),
                    tags=["ai_news", "article"],
                    warnings=list(data.get("warnings") or []),
                )
                items[item.content_id] = item

    def _scan_news_digests(self, output_dirs: Iterable[Path], items: dict[str, ContentItem], metadata: dict[str, Any]) -> None:
        latest = _read_json(self.workspace_dir / "news" / "news_digest_latest.json") or {}
        for day_dir in output_dirs:
            path = day_dir / "ai_news_digest.md"
            if not path.is_file():
                continue
            data = latest if latest.get("date") == day_dir.name else {}
            package = day_dir / "news_digest_package" / "packaged_ai_news_digest.md"
            report = day_dir / "ai_news_digest_review.md"
            quality = (data.get("quality_report") or {}).get("total_score")
            publish_ready = bool((data.get("quality_report") or {}).get("publish_ready", data.get("publish_ready", package.is_file())))
            item = ContentItem(
                content_id=self._content_id("ai_news_digest", day_dir.name, day_dir.name),
                title=data.get("title") or _first_heading(path, "AI News Digest"),
                content_type="ai_news_digest",
                source="ai_news",
                source_id=day_dir.name,
                safe_name="ai_news_digest",
                date=day_dir.name,
                updated_at=self._mtime(path),
                status="packaged" if package.is_file() else ("publish_ready" if publish_ready else "draft"),
                quality_score=quality,
                publish_ready=publish_ready,
                markdown_path=self._relative(path),
                package_path=self._relative(package) if package.is_file() else None,
                report_path=self._relative(report) if report.is_file() else None,
                source_urls=list(data.get("source_urls") or []),
                news_ids=list(data.get("source_event_ids") or []),
                generation_mode=data.get("generation_mode"),
                word_count=data.get("word_count") or _word_count(path),
                tags=["ai_news", "digest"],
                warnings=list(data.get("warnings") or []),
            )
            items[item.content_id] = item

    def _scan_manual_edits(self, output_dirs: Iterable[Path], items: dict[str, ContentItem]) -> None:
        candidates: list[tuple[Path, str]] = []
        for day_dir in output_dirs:
            candidates.extend((path, day_dir.name) for path in (day_dir / "manual_edits").glob("*.md"))
        for path in (self.workspace_dir / "manual_edits").glob("*.md"):
            candidates.append((path, self._date_from_mtime(path)))
        for path, date in candidates:
            item = ContentItem(
                content_id=self._content_id("manual_edit", date, path.stem),
                title=_first_heading(path, path.stem),
                content_type="manual_edit",
                source="manual",
                source_id=path.stem,
                safe_name=path.stem,
                date=date,
                updated_at=self._mtime(path),
                status="draft",
                markdown_path=self._relative(path),
                word_count=_word_count(path),
                tags=["manual"],
            )
            items[item.content_id] = item

        manual_dir = self.workspace_dir / "manual_edits"
        for metadata_path in sorted(manual_dir.glob("*.json")):
            data = _read_json(metadata_path)
            records = data.get("items", []) if isinstance(data, dict) and isinstance(data.get("items"), list) else [data]
            for record in records:
                if not isinstance(record, dict):
                    continue
                original_content_id = record.get("content_id")
                original = items.get(str(original_content_id)) if original_content_id else None
                if original is not None:
                    stored_path = record.get("manual_edit_path") or record.get("markdown_path") or record.get("path")
                    if stored_path:
                        try:
                            resolved = self._safe_path(str(stored_path))
                            if resolved.is_file():
                                original.manual_edit_path = self._relative(resolved)
                                original.has_manual_edit = True
                                original.manual_edit_updated_at = record.get("saved_at") or record.get("updated_at") or self._mtime(resolved)
                        except ValueError:
                            original.warnings.append("Manual edit path is outside allowed content roots")
                    manual_package = record.get("package_from_manual_path")
                    if manual_package:
                        try:
                            package_path = self._safe_path(str(manual_package))
                            if package_path.is_file():
                                original.package_path = self._relative(package_path)
                                original.status = "packaged"
                                marker = "Package generated from manual edit"
                                if marker not in original.warnings:
                                    original.warnings.append(marker)
                        except ValueError:
                            original.warnings.append("Manual package path is outside allowed content roots")
                    continue
                source_id = str(record.get("source_id") or record.get("safe_name") or record.get("id") or metadata_path.stem)
                date = str(record.get("date") or record.get("updated_at") or record.get("created_at") or "")[:10]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                    date = self._date_from_mtime(metadata_path)
                content_id = self._content_id("manual_edit", date, source_id)
                if content_id in items:
                    continue
                stored_path = record.get("markdown_path") or record.get("path")
                markdown_path: Optional[str] = None
                item_warnings = list(record.get("warnings") or [])
                if stored_path:
                    try:
                        resolved = self._safe_path(str(stored_path))
                        markdown_path = self._relative(resolved)
                        if not resolved.is_file():
                            item_warnings.append(f"Markdown path does not exist: {markdown_path}")
                    except ValueError:
                        item_warnings.append("Markdown path is outside allowed content roots")
                item = ContentItem(
                    content_id=content_id,
                    title=str(record.get("title") or source_id.replace("_", " ")),
                    content_type="manual_edit",
                    source="manual",
                    source_id=source_id,
                    safe_name=record.get("safe_name") or source_id,
                    date=date,
                    created_at=record.get("created_at"),
                    updated_at=record.get("updated_at") or self._mtime(metadata_path),
                    status=str(record.get("status") or "draft"),
                    quality_score=record.get("quality_score"),
                    publish_ready=bool(record.get("publish_ready", False)),
                    markdown_path=markdown_path,
                    source_urls=list(record.get("source_urls") or []),
                    tags=list(record.get("tags") or ["manual"]),
                    warnings=item_warnings,
                )
                items[item.content_id] = item

    def _scan_agent_runs(self, items: dict[str, ContentItem], date: Optional[str]) -> None:
        path_to_item: dict[Path, ContentItem] = {}
        for item in items.values():
            for field in ("markdown_path", "publish_path", "package_path", "report_path"):
                value = getattr(item, field)
                if value:
                    try:
                        path_to_item[self._safe_path(value)] = item
                    except ValueError:
                        continue

        run_paths = sorted(
            (self.workspace_dir / "agent_runs").glob("*.json"),
            key=lambda path: (path.name == "latest_agent_run.json", path.name),
            reverse=True,
        )
        seen_runs: set[str] = set()
        for run_path in run_paths:
            run = _read_json(run_path)
            if not isinstance(run, dict):
                continue
            run_id = str(run.get("run_id") or run_path.stem)
            if run_id in seen_runs:
                continue
            seen_runs.add(run_id)
            run_date = str(run.get("created_at") or "")[:10] or self._date_from_mtime(run_path)
            if date and run_date != date:
                continue
            for artifact in run.get("artifacts") or []:
                try:
                    artifact_path = self._safe_path(str(artifact))
                except ValueError:
                    continue
                linked = path_to_item.get(artifact_path)
                if linked:
                    linked.agent_run_id = linked.agent_run_id or run_id
                    if "agent" not in linked.tags:
                        linked.tags.append("agent")
                    continue
                if not self._looks_like_article(artifact_path):
                    continue
                artifact_date = self._date_from_output_path(artifact_path) or run_date
                item = ContentItem(
                    content_id=self._content_id("agent_artifact", artifact_date, f"{run_id}:{self._relative(artifact_path)}"),
                    title=_first_heading(artifact_path, artifact_path.stem),
                    content_type="agent_artifact",
                    source="agent",
                    source_id=run_id,
                    safe_name=artifact_path.stem,
                    date=artifact_date,
                    created_at=run.get("created_at"),
                    updated_at=run.get("finished_at") or run.get("started_at") or self._mtime(artifact_path),
                    status="unknown" if run.get("status") != "succeeded" else "draft",
                    markdown_path=self._relative(artifact_path),
                    agent_run_id=run_id,
                    generation_mode=(run.get("plan") or {}).get("generation_mode"),
                    word_count=_word_count(artifact_path),
                    tags=["agent", str(run.get("skill_name") or "artifact")],
                    warnings=list(run.get("warnings") or []),
                )
                items[item.content_id] = item
                path_to_item[artifact_path] = item

    def _looks_like_article(self, path: Path) -> bool:
        if path.suffix.lower() != ".md" or not path.is_file():
            return False
        lowered = path.stem.lower()
        if any(token in lowered for token in ("report", "review", "index", "plan", "notes")):
            return False
        return (_word_count(path) or 0) >= 100

    def _safe_path(self, value: Path | str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        resolved = path.resolve()
        allowed = (self.outputs_dir.resolve(), self.workspace_dir.resolve())
        if not any(resolved == root or root in resolved.parents for root in allowed):
            raise ValueError("Path is outside allowed content roots")
        return resolved

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.project_root).as_posix()

    @staticmethod
    def _content_id(content_type: str, date: str, source_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", source_id).strip("-").lower()[:72] or "content"
        digest = hashlib.sha1(f"{content_type}:{date}:{source_id}".encode("utf-8")).hexdigest()[:8]
        return f"{content_type}:{date}:{slug}:{digest}"

    @staticmethod
    def _mtime(path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _date_from_mtime(path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()

    def _date_from_output_path(self, path: Path) -> Optional[str]:
        try:
            relative = path.relative_to(self.outputs_dir)
        except ValueError:
            return None
        return relative.parts[0] if relative.parts and re.fullmatch(r"\d{4}-\d{2}-\d{2}", relative.parts[0]) else None

    @staticmethod
    def _render_report(index: ContentIndex) -> str:
        lines = [
            "# Content Index Report",
            "",
            f"Generated at: {index.generated_at}",
            f"Total content: {index.total_count}",
            "",
            "## Type counts",
            "",
        ]
        lines.extend(f"- {kind}: {count}" for kind, count in index.type_counts.items())
        lines.extend([
            "",
            "## Publishing readiness",
            "",
            f"- ready: {index.ready_count}",
            f"- needs package: {index.needs_package_count}",
            f"- quality low: {index.quality_low_count}",
            f"- needs review: {index.needs_review_count}",
            f"- manual edits: {index.manual_edit_count}",
            f"- packaged: {index.packaged_count}",
            "",
            "## Items",
            "",
            "| Date | Type | Status | Readiness | Title | Content ID |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for item in index.items:
            title = item.title.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {item.date} | {item.content_type} | {item.status} | {item.readiness_status} | {title} | `{item.content_id}` |"
            )
        if index.warnings:
            lines.extend(["", "## Warnings", ""])
            lines.extend(f"- {warning}" for warning in index.warnings)
        return "\n".join(lines) + "\n"
