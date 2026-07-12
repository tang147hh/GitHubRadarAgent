from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from src.config import get_settings
from src.models import NewsDetailResult, NewsImageCandidate, NewsItem
from src.news_collector import _clean_text, utc_now_iso


try:
    import trafilatura
except ImportError:  # pragma: no cover - dependency can be installed after bootstrap
    trafilatura = None


SAFE_NEWS_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
CONTENT_PREVIEW_LIMIT = 4000


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_cls: Any, payload: Any) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls.parse_obj(payload)


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _is_http_url(value: str | None) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _clean_url(value: str | None, base_url: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    resolved = urljoin(base_url, raw)
    return resolved if _is_http_url(resolved) else ""


class _ImageCandidateParser(HTMLParser):
    META_KEYS = {
        "og:image",
        "og:image:url",
        "og:image:secure_url",
        "twitter:image",
        "twitter:image:src",
    }

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.candidates: list[NewsImageCandidate] = []
        self._seen: set[str] = set()
        self._meta_alt: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): (value or "").strip() for key, value in attrs if key}
        tag_lower = tag.lower()
        if tag_lower == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").lower()
            content = attr_map.get("content") or ""
            if key in {"og:image:alt", "twitter:image:alt"} and content:
                self._meta_alt[key.split(":")[0]] = content
                return
            if key in self.META_KEYS:
                source_type = "twitter:image" if key.startswith("twitter") else "og:image"
                self._add(content, source_type=source_type, alt=self._meta_alt.get("twitter" if key.startswith("twitter") else "og"))
            return
        if tag_lower == "link":
            rel = attr_map.get("rel", "").lower()
            if "image_src" in rel or "preload" in rel and attr_map.get("as", "").lower() == "image":
                self._add(attr_map.get("href") or "", source_type="link:image_src", alt=None)
            return
        if tag_lower == "img":
            src = attr_map.get("src") or attr_map.get("data-src") or attr_map.get("data-original") or ""
            alt = attr_map.get("alt") or attr_map.get("title") or None
            self._add(src, source_type="body:first_image", alt=alt)

    def _add(self, value: str, source_type: str, alt: str | None) -> None:
        url = _clean_url(value, self.base_url)
        if not url:
            return
        key = url.casefold()
        if key in self._seen:
            return
        self._seen.add(key)
        self.candidates.append(
            NewsImageCandidate(
                url=url,
                source_url=self.base_url,
                alt=(alt or "").strip() or None,
                source_type=source_type,
            )
        )


class NewsDetailService:
    def __init__(
        self,
        workspace_dir: Path | None = None,
        request_timeout: float = 15.0,
    ) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.news_dir = self.workspace_dir / "news"
        self.articles_dir = self.news_dir / "news_articles"
        self.latest_path = self.news_dir / "news_latest.json"
        self.snapshots_latest_path = self.workspace_dir / "snapshots" / "news_latest.json"
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "GitHubRadarAgent/1.0 (+https://github.com/tang147hh/GitHubRadarAgent)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def get_detail(self, news_id: str, refresh: bool = False) -> NewsDetailResult:
        safe_id = self._validate_news_id(news_id)
        item = self._find_item(safe_id)
        cache_path = self.cache_path_for(safe_id)

        if cache_path.exists() and not refresh:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                detail = _model_validate(NewsDetailResult, payload)
                if detail.content_text or detail.cover_image_url or detail.image_candidates:
                    return detail
                return self._from_item(
                    item,
                    detail.extraction_status or "failed",
                    detail.extraction_error,
                    detail.content_text,
                )
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        if item.content_text and not refresh:
            detail = self._from_item(item, "cached", None, item.content_text)
            self._save_cache(detail)
            return detail

        extraction_error: str | None = None
        extracted_text: str | None = None
        image_candidates: list[NewsImageCandidate] = []
        extraction_status = "skipped"
        if not item.url:
            extraction_error = "Missing article URL."
            extraction_status = "failed"
        elif trafilatura is None:
            extraction_error = "trafilatura is not installed."
            extraction_status = "failed"
            try:
                response = self.session.get(item.url, timeout=self.request_timeout)
                response.raise_for_status()
                image_candidates = self._extract_image_candidates(response.text, item.url)
            except requests.RequestException as exc:
                extraction_error = f"{extraction_error} Image metadata fetch failed: {type(exc).__name__}: {exc}"
        else:
            extraction_status = "failed"
            try:
                response = self.session.get(item.url, timeout=self.request_timeout)
                response.raise_for_status()
                image_candidates = self._extract_image_candidates(response.text, item.url)
                extracted = trafilatura.extract(
                    response.text,
                    url=item.url,
                    include_comments=False,
                    include_tables=False,
                )
                extracted_text = _clean_text(extracted, max_length=120_000) or None
                if extracted_text:
                    extraction_status = "refreshed"
                    extraction_error = None
                else:
                    extraction_error = "No readable article body was extracted."
            except requests.RequestException as exc:
                extraction_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # pragma: no cover - trafilatura internals vary
                extraction_error = f"{type(exc).__name__}: {exc}"

        detail = self._from_item(
            item,
            extraction_status=extraction_status,
            extraction_error=extraction_error,
            content_text=extracted_text or item.content_text,
            image_candidates=image_candidates,
        )
        self._save_cache(detail)
        if extraction_status == "refreshed" and extracted_text:
            self._sync_latest_item(safe_id, extracted_text)
        return detail

    def cache_path_for(self, news_id: str) -> Path:
        safe_id = self._validate_news_id(news_id)
        candidate = (self.articles_dir / f"{safe_id}.json").resolve()
        root = self.articles_dir.resolve()
        if candidate.parent != root:
            raise ValueError("Invalid news_id.")
        return candidate

    def _validate_news_id(self, news_id: str) -> str:
        safe_id = str(news_id or "").strip()
        if not SAFE_NEWS_ID_PATTERN.fullmatch(safe_id):
            raise ValueError("Invalid news_id.")
        return safe_id

    def _load_latest_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No news collection found. Please run collect-news first.")
        if not isinstance(payload, dict):
            raise ValueError("workspace/news/news_latest.json must contain a JSON object.")
        if not isinstance(payload.get("items"), list):
            payload["items"] = []
        return payload

    def _find_item(self, news_id: str) -> NewsItem:
        payload = self._load_latest_payload()
        for raw_item in payload.get("items") or []:
            if not isinstance(raw_item, dict) or str(raw_item.get("id") or "") != news_id:
                continue
            return _model_validate(NewsItem, raw_item)
        raise KeyError(news_id)

    def _from_item(
        self,
        item: NewsItem,
        extraction_status: str,
        extraction_error: str | None,
        content_text: str | None,
        image_candidates: list[NewsImageCandidate] | None = None,
    ) -> NewsDetailResult:
        text = (content_text or "").strip() or None
        summary_text = (item.summary_zh or item.summary or "").strip()
        if text:
            availability = "full_text"
            preview = text[:CONTENT_PREVIEW_LIMIT].rstrip()
        elif summary_text:
            availability = "summary_only"
            preview = summary_text
        else:
            availability = "metadata_only"
            preview = ""

        candidates = self._dedupe_image_candidates(image_candidates or [])
        cover = candidates[0] if candidates else None
        return NewsDetailResult(
            news_id=item.id,
            title=item.title or "",
            title_zh=item.title_zh,
            summary=item.summary or "",
            summary_zh=item.summary_zh,
            url=item.url or "",
            source=item.source or "",
            source_type=item.source_type or "",
            published_at=item.published_at,
            fetched_at=item.fetched_at or utc_now_iso(),
            freshness=item.freshness or "unknown",
            content_text=text,
            content_preview=preview,
            content_availability=availability,
            extraction_status=extraction_status,
            extraction_error=extraction_error,
            word_count=_word_count(text),
            original_language=item.language,
            cover_image_url=cover.url if cover else None,
            cover_image_source_url=cover.source_url if cover else None,
            cover_image_alt=cover.alt if cover else None,
            cover_image_status="found" if cover else "missing",
            image_candidates=candidates,
        )

    def _extract_image_candidates(self, html: str, base_url: str) -> list[NewsImageCandidate]:
        if not html or not base_url:
            return []
        parser = _ImageCandidateParser(base_url)
        try:
            parser.feed(html[:1_000_000])
        except Exception:
            return parser.candidates
        return self._dedupe_image_candidates(parser.candidates)

    def _dedupe_image_candidates(self, candidates: list[NewsImageCandidate]) -> list[NewsImageCandidate]:
        seen: set[str] = set()
        cleaned: list[NewsImageCandidate] = []
        for candidate in candidates:
            url = _clean_url(candidate.url, candidate.source_url or "")
            if not url:
                continue
            key = url.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                NewsImageCandidate(
                    url=url,
                    source_url=candidate.source_url or url,
                    alt=(candidate.alt or "").strip() or None,
                    source_type=candidate.source_type or "unknown",
                )
            )
        return cleaned

    def _save_cache(self, detail: NewsDetailResult) -> None:
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_path_for(detail.news_id)
        path.write_text(json.dumps(_model_dump(detail), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _sync_latest_item(self, news_id: str, content_text: str) -> None:
        try:
            payload = self._load_latest_payload()
        except (FileNotFoundError, ValueError):
            return

        changed = False
        for raw_item in payload.get("items") or []:
            if isinstance(raw_item, dict) and str(raw_item.get("id") or "") == news_id:
                raw_item["content_text"] = content_text
                raw_item["content_availability"] = "full_text"
                changed = True
                break
        if not changed:
            return

        self.news_dir.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self.latest_path.write_text(serialized, encoding="utf-8")
        if self.snapshots_latest_path.exists():
            self.snapshots_latest_path.write_text(serialized, encoding="utf-8")
