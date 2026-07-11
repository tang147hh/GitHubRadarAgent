from __future__ import annotations

import hashlib
import html
import json
import os
import re
import string
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from src.config import get_settings
from src.models import NewsCollectionResult, NewsItem
from src.news_sources import (
    DEFAULT_NEWS_KEYWORDS,
    DEFAULT_RSS_SOURCES,
    DEFAULT_SOURCE_GROUPS,
    RSSHUB_ROUTES,
    SOURCE_ALIASES,
    RssSource,
)
from src.news_translator import NewsTranslatorService


try:
    import feedparser
except ImportError:  # pragma: no cover - dependency can be installed after bootstrap
    feedparser = None


try:
    import trafilatura
except ImportError:  # pragma: no cover - full-text extraction is optional
    trafilatura = None


HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
PUNCT_TRANSLATION = str.maketrans("", "", string.punctuation)
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref"}
AI_CATEGORIES = ("cs.AI", "cs.CL", "cs.LG")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _clean_text(value: Any, max_length: int = 8000) -> str:
    text = html.unescape(str(value or ""))
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = SPACE_PATTERN.sub(" ", text).strip()
    return text[:max_length].strip()


def _safe_id(*parts: str) -> str:
    raw = "|".join(part for part in parts if part)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _entry_value(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _published_from_entry(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        value = _entry_value(entry, key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated", "created"):
        parsed = parse_datetime(_entry_value(entry, key))
        if parsed:
            return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d{14}", text):
            try:
                dt = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        else:
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(text)
                except (TypeError, ValueError, IndexError, OverflowError):
                    return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_QUERY_KEYS and not key.startswith(TRACKING_QUERY_PREFIXES)
    ]
    path = parsed.path.rstrip("/") or parsed.path
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(query), ""))


def duplicate_key_for(title: str, url: str) -> str:
    parsed = urlparse(normalize_url(url))
    title_key = (title or "").lower().translate(PUNCT_TRANSLATION)
    title_key = SPACE_PATTERN.sub(" ", title_key).strip()
    title_key = " ".join(title_key.split()[:18])
    return f"{parsed.netloc}:{title_key}" if title_key else normalize_url(url)


class NewsCollectorService:
    def __init__(
        self,
        workspace_dir: Path | None = None,
        output_dir: Path | None = None,
        rsshub_base_url: str | None = None,
        request_timeout: float = 12.0,
    ) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir
        self.rsshub_base_url = (rsshub_base_url if rsshub_base_url is not None else settings.rsshub_base_url) or ""
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "GitHubRadarAgent/1.0 (+https://github.com/tang147hh/GitHubRadarAgent)",
                "Accept": "application/rss+xml, application/atom+xml, application/json, text/html;q=0.8, */*;q=0.5",
            }
        )

    def collect(
        self,
        hours: int = 24,
        limit: int = 100,
        sources: list[str] | None = None,
        keywords: list[str] | None = None,
        include_fulltext: bool = False,
        translate: bool = True,
        translate_limit: int = 50,
    ) -> NewsCollectionResult:
        hours = max(1, min(int(hours or 24), 24 * 14))
        limit = max(1, min(int(limit or 100), 500))
        warnings: list[str] = []
        source_groups = self._normalize_sources(sources)
        keyword_values = self._normalize_keywords(keywords)
        items: list[NewsItem] = []

        if "official" in source_groups:
            items.extend(self.collect_rss_sources(DEFAULT_RSS_SOURCES, keyword_values, include_fulltext, warnings))
        if "rsshub" in source_groups:
            if self.rsshub_base_url:
                items.extend(self.collect_rss_sources(self._rsshub_sources(), keyword_values, include_fulltext, warnings))
            else:
                warnings.append("RSSHub skipped: RSSHUB_BASE_URL is not configured.")
        if "hn" in source_groups:
            items.extend(self.collect_hackernews(hours, limit, keyword_values, warnings))
        if "arxiv" in source_groups:
            items.extend(self.collect_arxiv(limit, keyword_values, warnings))
        if "gdelt" in source_groups:
            items.extend(self.collect_gdelt(hours, limit, keyword_values, warnings))

        for item in items:
            item.freshness = self.classify_freshness(item.published_at)
            item.duplicate_key = item.duplicate_key or duplicate_key_for(item.title, item.url)
            item.raw_score = item.raw_score or self._score_item(item)

        deduped = self.dedupe_items(items)
        window_items = [item for item in deduped if self._is_within_window(item.published_at, hours) or item.freshness == "unknown"]
        if not window_items and deduped:
            warnings.append(f"No items matched the last {hours} hours; returning older latest items for diagnostics.")
            window_items = deduped

        ranked = sorted(window_items, key=self._sort_key, reverse=True)[:limit]
        if translate:
            ranked = NewsTranslatorService().translate_items(ranked, limit=translate_limit)
        else:
            for item in ranked:
                item.title_zh = item.title
                item.summary_zh = item.summary
                item.translation_status = "skipped"
                item.translation_error = None
        source_counts = Counter(item.source_type for item in ranked)
        availability_counts = Counter(item.content_availability for item in ranked)
        fresh_count = sum(1 for item in ranked if self._is_within_window(item.published_at, hours))

        result = NewsCollectionResult(
            generated_at=utc_now_iso(),
            window_hours=hours,
            total_count=len(ranked),
            fresh_count=fresh_count,
            sources=sorted({item.source for item in ranked}),
            source_counts=dict(source_counts),
            availability_counts=dict(availability_counts),
            items=ranked,
            warnings=warnings,
        )
        self.save_result(result)
        return result

    def collect_rss_sources(
        self,
        sources: Iterable[RssSource],
        keywords: list[str],
        include_fulltext: bool,
        warnings: list[str],
    ) -> list[NewsItem]:
        if feedparser is None:
            warnings.append("RSS skipped: feedparser is not installed.")
            return []

        items: list[NewsItem] = []
        for source in sources:
            try:
                response = self.session.get(source.url, timeout=self.request_timeout)
                response.raise_for_status()
                parsed = feedparser.parse(response.content)
            except Exception as exc:
                warnings.append(f"{source.name} RSS failed: {type(exc).__name__}: {exc}")
                continue

            if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", []):
                warnings.append(f"{source.name} RSS parse failed.")
                continue

            for entry in getattr(parsed, "entries", [])[:50]:
                title = _clean_text(_entry_value(entry, "title"), max_length=500)
                url = normalize_url(_entry_value(entry, "link") or _entry_value(entry, "id") or "")
                if not title or not url:
                    continue
                summary = _clean_text(_entry_value(entry, "summary") or _entry_value(entry, "description"), max_length=2000)
                content_text = None
                availability = "summary_only" if summary else "metadata_only"
                if include_fulltext:
                    content_text = self.extract_article_text(url, warnings)
                    if content_text:
                        availability = "full_text"
                    elif summary:
                        availability = "summary_only"
                topics = list(source.topics)
                matched_keywords = self._matched_keywords(f"{title} {summary}", keywords)
                items.append(
                    NewsItem(
                        id=_safe_id(source.name, title, url),
                        title=title,
                        url=url,
                        source=source.name,
                        source_type=source.source_type,
                        published_at=_published_from_entry(entry),
                        fetched_at=utc_now_iso(),
                        summary=summary,
                        content_text=content_text,
                        content_availability=availability,
                        language=_entry_value(entry, "language"),
                        topics=topics,
                        keywords=matched_keywords,
                        raw_score=0.0,
                        duplicate_key=duplicate_key_for(title, url),
                    )
                )
        return items

    def collect_hackernews(
        self,
        hours: int,
        limit: int,
        keywords: list[str],
        warnings: list[str],
    ) -> list[NewsItem]:
        cutoff = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
        items: list[NewsItem] = []
        per_keyword = max(5, min(25, limit // max(1, len(keywords)) + 5))
        for keyword in keywords:
            try:
                response = self.session.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={
                        "query": keyword,
                        "tags": "story",
                        "numericFilters": f"created_at_i>{cutoff}",
                        "hitsPerPage": per_keyword,
                    },
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                warnings.append(f"Hacker News search failed for '{keyword}': {type(exc).__name__}: {exc}")
                continue

            for hit in payload.get("hits", []):
                title = _clean_text(hit.get("title") or hit.get("story_title"), max_length=500)
                story_id = str(hit.get("objectID") or "")
                url = normalize_url(hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}")
                if not title or not url:
                    continue
                points = float(hit.get("points") or 0)
                comments = float(hit.get("num_comments") or 0)
                summary = f"Hacker News discussion. points={int(points)}, comments={int(comments)}"
                items.append(
                    NewsItem(
                        id=_safe_id("hn", story_id, title, url),
                        title=title,
                        url=url,
                        source="Hacker News",
                        source_type="hackernews",
                        published_at=parse_datetime(hit.get("created_at")).isoformat(timespec="seconds").replace("+00:00", "Z")
                        if parse_datetime(hit.get("created_at"))
                        else None,
                        fetched_at=utc_now_iso(),
                        summary=summary,
                        content_availability="summary_only",
                        language="en",
                        topics=["community", "discussion"],
                        keywords=[keyword],
                        raw_score=points + comments * 0.5,
                        duplicate_key=duplicate_key_for(title, url),
                    )
                )
        return items

    def collect_arxiv(self, limit: int, keywords: list[str], warnings: list[str]) -> list[NewsItem]:
        if feedparser is None:
            warnings.append("arXiv skipped: feedparser is not installed.")
            return []
        query = " OR ".join(f"cat:{category}" for category in AI_CATEGORIES)
        try:
            response = self.session.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": query,
                    "start": 0,
                    "max_results": max(10, min(limit, 100)),
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception as exc:
            warnings.append(f"arXiv collection failed: {type(exc).__name__}: {exc}")
            return []

        items: list[NewsItem] = []
        for entry in getattr(parsed, "entries", [])[:limit]:
            title = _clean_text(_entry_value(entry, "title"), max_length=500)
            url = normalize_url(_entry_value(entry, "link") or _entry_value(entry, "id") or "")
            if not title or not url:
                continue
            summary = _clean_text(_entry_value(entry, "summary"), max_length=3000)
            authors = [
                _clean_text(author.get("name"), max_length=100)
                for author in (_entry_value(entry, "authors", []) or [])
                if isinstance(author, dict) and author.get("name")
            ]
            keyword_matches = self._matched_keywords(f"{title} {summary}", keywords)
            if authors:
                summary = f"Authors: {', '.join(authors[:8])}. {summary}".strip()
            items.append(
                NewsItem(
                    id=_safe_id("arxiv", title, url),
                    title=title,
                    url=url,
                    source="arXiv",
                    source_type="arxiv",
                    published_at=_published_from_entry(entry),
                    fetched_at=utc_now_iso(),
                    summary=summary,
                    content_availability="summary_only" if summary else "metadata_only",
                    language="en",
                    topics=["paper", "research"],
                    keywords=keyword_matches,
                    raw_score=15.0 + len(keyword_matches) * 2.0,
                    duplicate_key=duplicate_key_for(title, url),
                )
            )
        return items

    def collect_gdelt(self, hours: int, limit: int, keywords: list[str], warnings: list[str]) -> list[NewsItem]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        query = " OR ".join(f'"{keyword}"' if " " in keyword else keyword for keyword in keywords[:12])
        try:
            response = self.session.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": max(10, min(limit, 250)),
                    "sort": "HybridRel",
                    "startdatetime": start.strftime("%Y%m%d%H%M%S"),
                    "enddatetime": end.strftime("%Y%m%d%H%M%S"),
                },
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            warnings.append(f"GDELT collection failed: {type(exc).__name__}: {exc}")
            return []

        items: list[NewsItem] = []
        for article in payload.get("articles", [])[:limit]:
            title = _clean_text(article.get("title"), max_length=500)
            url = normalize_url(article.get("url") or "")
            if not title or not url:
                continue
            domain = _clean_text(article.get("domain"), max_length=120) or urlparse(url).netloc
            language = article.get("language")
            matched_keywords = self._matched_keywords(title, keywords) or self._matched_keywords(url, keywords)
            items.append(
                NewsItem(
                    id=_safe_id("gdelt", title, url),
                    title=title,
                    url=url,
                    source=domain,
                    source_type="gdelt",
                    published_at=parse_datetime(article.get("seendate")).isoformat(timespec="seconds").replace("+00:00", "Z")
                    if parse_datetime(article.get("seendate"))
                    else None,
                    fetched_at=utc_now_iso(),
                    summary=_clean_text(article.get("sourcecountry"), max_length=200),
                    content_availability="metadata_only",
                    language=str(language) if language else None,
                    topics=["global-media", "industry"],
                    keywords=matched_keywords,
                    raw_score=10.0 + len(matched_keywords) * 3.0,
                    duplicate_key=duplicate_key_for(title, url),
                )
            )
        return items

    def extract_article_text(self, url: str, warnings: list[str] | None = None) -> str | None:
        if trafilatura is None:
            if warnings is not None and "Full-text extraction skipped: trafilatura is not installed." not in warnings:
                warnings.append("Full-text extraction skipped: trafilatura is not installed.")
            return None
        try:
            response = self.session.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            extracted = trafilatura.extract(response.text, url=url, include_comments=False, include_tables=False)
        except Exception:
            return None
        text = _clean_text(extracted, max_length=120_000)
        return text or None

    def dedupe_items(self, items: list[NewsItem]) -> list[NewsItem]:
        deduped: list[NewsItem] = []
        seen_urls: set[str] = set()
        seen_keys: set[str] = set()
        for item in sorted(items, key=self._sort_key, reverse=True):
            normalized_url = normalize_url(item.url)
            key = item.duplicate_key or duplicate_key_for(item.title, item.url)
            if normalized_url and normalized_url in seen_urls:
                continue
            if key and key in seen_keys:
                continue
            if self._has_similar_title(item, deduped):
                continue
            seen_urls.add(normalized_url)
            seen_keys.add(key)
            deduped.append(item)
        return deduped

    def classify_freshness(self, published_at: str | None) -> str:
        published = parse_datetime(published_at)
        if not published:
            return "unknown"
        now = datetime.now(timezone.utc)
        if published.astimezone().date() == now.astimezone().date():
            return "today"
        delta = now - published
        if delta <= timedelta(hours=24):
            return "last_24h"
        if delta <= timedelta(hours=72):
            return "last_72h"
        return "older"

    def save_result(self, result: NewsCollectionResult) -> None:
        generated_date = datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(result), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_latest.json").write_text(payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_latest.json").write_text(payload, encoding="utf-8")
        (output_date_dir / "news_collection_report.md").write_text(self.render_report(result), encoding="utf-8")

    def render_report(self, result: NewsCollectionResult) -> str:
        lines = [
            "# AI News Collection Report",
            "",
            f"- 采集时间: {result.generated_at}",
            f"- 时间窗口: 最近 {result.window_hours} 小时",
            f"- 总新闻数: {result.total_count}",
            f"- 窗口内新闻数: {result.fresh_count}",
            "",
            "## 各来源数量",
            "",
        ]
        if result.source_counts:
            for source_type, count in sorted(result.source_counts.items()):
                lines.append(f"- {source_type}: {count}")
        else:
            lines.append("- none: 0")

        lines.extend(["", "## 正文可用性", ""])
        if result.availability_counts:
            for availability, count in sorted(result.availability_counts.items()):
                lines.append(f"- {availability}: {count}")
        else:
            lines.append("- none: 0")

        translation_counts = Counter(item.translation_status or "skipped" for item in result.items)
        lines.extend(["", "## 翻译统计", ""])
        for status in ("translated", "skipped", "failed", "source_is_chinese"):
            lines.append(f"- {status}: {translation_counts.get(status, 0)}")

        lines.extend(["", "## Warnings", ""])
        if result.warnings:
            lines.extend(f"- {warning}" for warning in result.warnings)
        else:
            lines.append("- 无")

        lines.extend(["", "## Top 新闻列表", ""])
        for index, item in enumerate(result.items[:30], start=1):
            title_zh = (item.title_zh or item.title or "-").strip()
            original_title = (item.title or "").strip()
            summary = (item.summary_zh or item.summary or "")[:180].replace("\n", " ").strip()
            lines.extend(
                [
                    f"### {index}. {title_zh}",
                    "",
                    f"- 来源: {item.source} ({item.source_type})",
                    f"- 发布时间: {item.published_at or 'unknown'}",
                    f"- freshness: {item.freshness}",
                    f"- content_availability: {item.content_availability}",
                    f"- translation_status: {item.translation_status}",
                    f"- 原文链接: {item.url}",
                ]
            )
            if original_title and original_title != title_zh:
                lines.append(f"- 原文标题: {original_title}")
            if summary:
                lines.append(f"- 摘要: {summary}")
            if item.translation_error:
                lines.append(f"- 翻译错误: {item.translation_error}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _rsshub_sources(self) -> list[RssSource]:
        base = self.rsshub_base_url.rstrip("/")
        return [
            RssSource(source.name, f"{base}/{source.url.lstrip('/')}", source_type="rsshub", topics=source.topics)
            for source in RSSHUB_ROUTES
        ]

    def _normalize_sources(self, sources: list[str] | None) -> list[str]:
        configured = [item.strip().lower() for item in (sources or []) if str(item).strip()]
        if not configured:
            configured = list(DEFAULT_SOURCE_GROUPS)
            if self.rsshub_base_url:
                configured.append("rsshub")
        normalized: list[str] = []
        for item in configured:
            mapped = SOURCE_ALIASES.get(item)
            if mapped and mapped not in normalized:
                normalized.append(mapped)
        return normalized or list(DEFAULT_SOURCE_GROUPS)

    def _normalize_keywords(self, keywords: list[str] | None) -> list[str]:
        env_keywords = get_settings().news_keywords
        values = keywords or env_keywords or DEFAULT_NEWS_KEYWORDS
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            keyword = str(item or "").strip()
            if not keyword:
                continue
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(keyword[:80])
        return cleaned or list(DEFAULT_NEWS_KEYWORDS)

    def _matched_keywords(self, text: str, keywords: list[str]) -> list[str]:
        lowered = (text or "").casefold()
        return [keyword for keyword in keywords if keyword.casefold() in lowered]

    def _is_within_window(self, published_at: str | None, hours: int) -> bool:
        published = parse_datetime(published_at)
        if not published:
            return False
        return datetime.now(timezone.utc) - published <= timedelta(hours=hours)

    def _score_item(self, item: NewsItem) -> float:
        score = 10.0
        if item.freshness == "today":
            score += 20
        elif item.freshness == "last_24h":
            score += 15
        elif item.freshness == "last_72h":
            score += 8
        score += len(item.keywords) * 2.0
        if item.content_availability == "full_text":
            score += 5
        elif item.content_availability == "summary_only":
            score += 2
        if item.source_type in {"official_rss", "arxiv"}:
            score += 3
        return score

    def _sort_key(self, item: NewsItem) -> tuple[float, float]:
        published = parse_datetime(item.published_at)
        timestamp = published.timestamp() if published else 0.0
        return (float(item.raw_score or 0.0), timestamp)

    def _has_similar_title(self, item: NewsItem, existing_items: list[NewsItem]) -> bool:
        current = duplicate_key_for(item.title, item.url).split(":", 1)[-1]
        if not current:
            return False
        current_words = set(current.split())
        for existing in existing_items:
            other = duplicate_key_for(existing.title, existing.url).split(":", 1)[-1]
            other_words = set(other.split())
            if not current_words or not other_words:
                continue
            overlap = len(current_words & other_words) / max(len(current_words), len(other_words))
            if overlap >= 0.88:
                return True
        return False
