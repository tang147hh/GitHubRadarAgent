from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.config import get_settings
from src.models import NewsDetailResult, NewsItem, NewsSelectionContext, NewsSelectionItem
from src.news_collector import utc_now_iso


SAFE_NEWS_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SAFE_SELECTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
MAX_SELECTION_ITEMS = 5


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_cls: Any, payload: Any) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls.parse_obj(payload)


class NewsSelectionService:
    def __init__(self, workspace_dir: Path | None = None) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.news_dir = self.workspace_dir / "news"
        self.latest_path = self.news_dir / "news_latest.json"
        self.articles_dir = self.news_dir / "news_articles"
        self.selections_dir = self.news_dir / "selections"
        self.latest_selection_path = self.selections_dir / "latest_selection.json"

    def build_selection(
        self,
        news_ids: list[str],
        primary_news_id: str | None,
        direction_text: str | None = None,
    ) -> NewsSelectionContext:
        cleaned_ids = self._clean_news_ids(news_ids)
        if not cleaned_ids:
            raise ValueError("news_ids must contain at least one news item.")
        if len(cleaned_ids) > MAX_SELECTION_ITEMS:
            raise ValueError(f"At most {MAX_SELECTION_ITEMS} news items can be selected.")

        primary_id = self._validate_news_id(primary_news_id or cleaned_ids[0])
        if primary_id not in cleaned_ids:
            raise ValueError("primary_news_id must be one of news_ids.")

        latest_items = self._load_latest_items()
        missing_ids = [news_id for news_id in cleaned_ids if news_id not in latest_items]
        if missing_ids:
            raise ValueError(f"News item not found: {', '.join(missing_ids)}")

        warnings: list[str] = []
        selection_items: list[NewsSelectionItem] = []
        for news_id in cleaned_ids:
            item = latest_items[news_id]
            availability = item.content_availability or "metadata_only"
            cached_availability = self._cached_content_availability(news_id, warnings)
            if cached_availability:
                availability = cached_availability
            selection_items.append(
                NewsSelectionItem(
                    news_id=item.id,
                    title=item.title or "",
                    title_zh=item.title_zh,
                    url=item.url or "",
                    source=item.source or "",
                    source_type=item.source_type or "",
                    published_at=item.published_at,
                    content_availability=availability,
                    role="primary" if item.id == primary_id else "supporting",
                )
            )

        now = utc_now_iso()
        selection_id = f"news-selection-{now.replace(':', '').replace('.', '')}-{uuid4().hex[:8]}"
        return NewsSelectionContext(
            selection_id=selection_id,
            created_at=now,
            updated_at=now,
            primary_news_id=primary_id,
            items=selection_items,
            direction_text=(direction_text or "").strip() or None,
            notes=[
                "Selected AI news context for the next WeChat article planning step.",
                "Multiple items are preserved as source material only; no article is generated in this step.",
            ],
            warnings=warnings,
        )

    def save_selection(self, context: NewsSelectionContext) -> NewsSelectionContext:
        if not context.selection_id:
            raise ValueError("selection_id is required.")
        self._validate_selection_id(context.selection_id)
        context.updated_at = utc_now_iso()

        self.selections_dir.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(_model_dump(context), ensure_ascii=False, indent=2) + "\n"
        self.selection_path_for(context.selection_id).write_text(serialized, encoding="utf-8")
        self.latest_selection_path.write_text(serialized, encoding="utf-8")
        return context

    def load_latest_selection(self) -> NewsSelectionContext:
        return self._load_selection_path(self.latest_selection_path)

    def load_selection(self, selection_id: str) -> NewsSelectionContext:
        safe_id = self._validate_selection_id(selection_id)
        return self._load_selection_path(self.selection_path_for(safe_id))

    def selection_path_for(self, selection_id: str) -> Path:
        safe_id = self._validate_selection_id(selection_id)
        candidate = (self.selections_dir / f"{safe_id}.json").resolve()
        root = self.selections_dir.resolve()
        if candidate.parent != root:
            raise ValueError("Invalid selection_id.")
        return candidate

    def _load_selection_path(self, path: Path) -> NewsSelectionContext:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No news selection found. Please save a selection first.")
        if not isinstance(payload, dict):
            raise ValueError("News selection JSON must contain an object.")
        return _model_validate(NewsSelectionContext, payload)

    def _load_latest_items(self) -> dict[str, NewsItem]:
        try:
            payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No news collection found. Please run collect-news first.")
        if not isinstance(payload, dict):
            raise ValueError("workspace/news/news_latest.json must contain a JSON object.")
        raw_items = payload.get("items") or []
        if not isinstance(raw_items, list):
            raise ValueError("workspace/news/news_latest.json items must be a list.")

        items: dict[str, NewsItem] = {}
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item = _model_validate(NewsItem, raw_item)
            if item.id:
                items[item.id] = item
        return items

    def _cached_content_availability(self, news_id: str, warnings: list[str]) -> str | None:
        path = self._article_cache_path(news_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            detail = _model_validate(NewsDetailResult, payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"Could not read detail cache for {news_id}: {type(exc).__name__}: {exc}")
            return None
        return detail.content_availability or None

    def _article_cache_path(self, news_id: str) -> Path:
        safe_id = self._validate_news_id(news_id)
        candidate = (self.articles_dir / f"{safe_id}.json").resolve()
        root = self.articles_dir.resolve()
        if candidate.parent != root:
            raise ValueError("Invalid news_id.")
        return candidate

    def _clean_news_ids(self, news_ids: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for news_id in news_ids:
            safe_id = self._validate_news_id(news_id)
            if safe_id in seen:
                continue
            seen.add(safe_id)
            cleaned.append(safe_id)
        return cleaned

    def _validate_news_id(self, news_id: str | None) -> str:
        safe_id = str(news_id or "").strip()
        if not SAFE_NEWS_ID_PATTERN.fullmatch(safe_id):
            raise ValueError("Invalid news_id.")
        return safe_id

    def _validate_selection_id(self, selection_id: str | None) -> str:
        safe_id = str(selection_id or "").strip()
        if not SAFE_SELECTION_ID_PATTERN.fullmatch(safe_id):
            raise ValueError("Invalid selection_id.")
        return safe_id
