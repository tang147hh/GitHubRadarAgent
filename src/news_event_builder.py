from __future__ import annotations

import hashlib
import json
import re
import string
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config import get_settings
from src.models import NewsCollectionResult, NewsEventCard, NewsEventResult, NewsItem, NewsScore, NewsScoringResult
from src.news_collector import normalize_url, parse_datetime, utc_now_iso
from src.news_scorer import CATEGORY_SECTION_MAP


GENERIC_TERMS = {
    "ai",
    "new",
    "news",
    "launch",
    "launches",
    "launched",
    "release",
    "released",
    "releases",
    "update",
    "updates",
    "updated",
    "announce",
    "announces",
    "announced",
    "unveil",
    "unveils",
    "show",
    "show hn",
    "ask hn",
    "tell hn",
    "hacker",
    "news",
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "about",
    "over",
    "under",
    "after",
    "before",
    "using",
    "based",
    "this",
    "that",
    "have",
    "has",
    "will",
    "can",
    "how",
    "why",
    "what",
    "are",
    "is",
    "in",
    "on",
    "to",
    "of",
    "a",
    "an",
    "发布",
    "推出",
    "更新",
    "新闻",
    "最新",
    "新的",
    "宣布",
    "上线",
    "人工智能",
}

ENTITY_TERMS = [
    "OpenAI",
    "Anthropic",
    "DeepSeek",
    "Google DeepMind",
    "Google",
    "Gemini",
    "Claude",
    "ChatGPT",
    "GPT",
    "NVIDIA",
    "Meta",
    "Microsoft",
    "Mistral",
    "Llama",
    "Hugging Face",
    "MCP",
    "RAG",
    "Agent",
    "GitHub",
    "arXiv",
]

AVAILABILITY_RANK = {
    "metadata_only": 0,
    "summary_only": 1,
    "full_text": 2,
    "mixed": 1,
}

FRESHNESS_BONUS = {
    "today": 4.0,
    "last_24h": 3.0,
    "last_72h": 1.0,
    "older": -2.0,
    "unknown": -1.0,
}

FRESHNESS_RANK = {
    "today": 4,
    "last_24h": 3,
    "last_72h": 2,
    "older": 1,
    "unknown": 0,
}

OFFICIAL_HINTS = (
    "openai",
    "anthropic",
    "deepmind",
    "google",
    "nvidia",
    "microsoft",
    "meta",
    "mistral",
    "huggingface",
    "deepseek",
)

PUNCT_TRANSLATION = str.maketrans("", "", string.punctuation)
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._/-]*|[\u4e00-\u9fff]{2,}")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_class: Any, payload: dict[str, Any]) -> Any:
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(payload)
    return model_class.parse_obj(payload)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _safe_markdown_cell(value: str) -> str:
    return (value or "-").replace("|", "\\|").replace("\n", " ")


def _short_text(value: str, max_length: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    return cleaned[:max_length].rstrip()


class NewsEventBuilderService:
    """Merge scored news items into conservative event cards."""

    def __init__(self, workspace_dir: Path | None = None, output_dir: Path | None = None) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir

    def load_latest_collection(self) -> NewsCollectionResult:
        path = self.workspace_dir / "news" / "news_latest.json"
        if not path.exists():
            raise FileNotFoundError("workspace/news/news_latest.json not found. Please run collect-news first.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workspace/news/news_latest.json must contain a JSON object.")
        return _model_validate(NewsCollectionResult, payload)

    def load_latest_scores(self) -> NewsScoringResult:
        path = self.workspace_dir / "news" / "news_scores_latest.json"
        if not path.exists():
            raise FileNotFoundError("workspace/news/news_scores_latest.json not found. Please run score-news first.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workspace/news/news_scores_latest.json must contain a JSON object.")
        return _model_validate(NewsScoringResult, payload)

    def build_latest(
        self,
        top: int = 20,
        min_score: float = 60.0,
        similarity_threshold: float = 0.55,
    ) -> NewsEventResult:
        return self.build_events(
            self.load_latest_collection(),
            self.load_latest_scores(),
            top=top,
            min_score=min_score,
            similarity_threshold=similarity_threshold,
        )

    def build_events(
        self,
        collection: NewsCollectionResult,
        scoring: NewsScoringResult,
        top: int = 20,
        min_score: float = 60.0,
        similarity_threshold: float = 0.55,
    ) -> NewsEventResult:
        top = max(1, min(int(top or 20), 100))
        min_score = _clamp(float(min_score), 0.0, 100.0)
        similarity_threshold = _clamp(float(similarity_threshold), 0.35, 0.9)
        warnings = [*(collection.warnings or []), *(scoring.warnings or [])]

        scores_by_id = {score.news_id: score for score in scoring.scores}
        candidates: list[tuple[NewsItem, NewsScore]] = []
        for item in collection.items:
            score = scores_by_id.get(item.id)
            if score is None:
                warnings.append(f"News item has no score and was skipped: {item.title or item.id}")
                continue
            candidates.append((item, score))

        candidates.sort(
            key=lambda pair: (
                pair[1].total_score,
                self._timestamp(pair[0].published_at),
                AVAILABILITY_RANK.get(pair[0].content_availability, 0),
            ),
            reverse=True,
        )

        clusters: list[list[tuple[NewsItem, NewsScore]]] = []
        cluster_reasons: list[list[str]] = []
        for pair in candidates:
            best_index = -1
            best_similarity = 0.0
            best_reason = ""
            for index, cluster in enumerate(clusters):
                similarity, reason = self._cluster_similarity(pair, cluster, similarity_threshold)
                if similarity > best_similarity:
                    best_index = index
                    best_similarity = similarity
                    best_reason = reason
            if best_index >= 0 and best_similarity >= similarity_threshold:
                clusters[best_index].append(pair)
                if best_reason:
                    cluster_reasons[best_index].append(best_reason)
            else:
                clusters.append([pair])
                cluster_reasons.append([])

        events = [self._build_event(cluster, cluster_reasons[index], min_score) for index, cluster in enumerate(clusters)]
        events.sort(key=lambda event: (event.total_score, event.source_count, self._timestamp(event.latest_published_at)), reverse=True)
        self._apply_recommendation_limit(events, top=top, min_score=min_score)

        category_counts = Counter(event.category for event in events)
        section_counts = Counter(event.recommended_section for event in events if event.recommended_section != "暂不推荐")
        result = NewsEventResult(
            generated_at=utc_now_iso(),
            total_news_count=len(collection.items),
            event_count=len(events),
            recommended_event_count=sum(1 for event in events if event.recommended_section != "暂不推荐"),
            section_counts=dict(sorted(section_counts.items())),
            category_counts=dict(sorted(category_counts.items())),
            events=events,
            warnings=_unique(warnings)[:80],
        )
        self.save_result(result)
        return result

    def save_result(self, result: NewsEventResult) -> None:
        generated_date = datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(result), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_events_latest.json").write_text(payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news-events.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_events_latest.json").write_text(payload, encoding="utf-8")
        (output_date_dir / "news_events_report.md").write_text(self.render_report(result), encoding="utf-8")

    def render_report(self, result: NewsEventResult) -> str:
        recommended = [event for event in result.events if event.recommended_section != "暂不推荐"]
        multi_source = [event for event in result.events if event.source_count >= 2]
        single_recommended = [event for event in recommended if event.source_count == 1]

        lines = [
            "# AI News Events Report",
            "",
            f"- 生成时间: {result.generated_at}",
            f"- 总新闻数: {result.total_news_count}",
            f"- 合并后事件数: {result.event_count}",
            f"- 推荐事件数: {result.recommended_event_count}",
            "",
            "## 分类统计",
            "",
        ]
        lines.extend(f"- {category}: {count}" for category, count in sorted(result.category_counts.items())) if result.category_counts else lines.append("- none: 0")
        lines.extend(["", "## 栏目统计", ""])
        lines.extend(f"- {section}: {count}" for section, count in sorted(result.section_counts.items())) if result.section_counts else lines.append("- none: 0")

        lines.extend(
            [
                "",
                "## Top 事件",
                "",
                "| 中文事件标题 | 推荐栏目 | 来源数量 | 分数 | 主来源 | freshness | reasons | primary_url |",
                "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        if recommended:
            for event in recommended:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _safe_markdown_cell(event.event_title_zh or event.event_title),
                            _safe_markdown_cell(event.recommended_section),
                            str(event.source_count),
                            f"{event.total_score:.2f}",
                            _safe_markdown_cell(event.primary_source),
                            _safe_markdown_cell(event.freshness),
                            _safe_markdown_cell("；".join(event.reasons[:3])),
                            _safe_markdown_cell(event.primary_url),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("| - | - | 0 | 0 | - | - | - | - |")

        lines.extend(["", "## 多来源事件", ""])
        if multi_source:
            for index, event in enumerate(multi_source, start=1):
                lines.append(
                    f"{index}. {event.event_title_zh or event.event_title} | "
                    f"sources={event.source_count} | score={event.total_score:.2f} | "
                    f"{', '.join(event.sources)}"
                )
        else:
            lines.append("- 无")

        lines.extend(["", "## 未合并但推荐的单来源事件", ""])
        if single_recommended:
            for index, event in enumerate(single_recommended, start=1):
                lines.append(
                    f"{index}. {event.event_title_zh or event.event_title} | "
                    f"{event.recommended_section} | score={event.total_score:.2f} | {event.primary_url}"
                )
        else:
            lines.append("- 无")

        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result.warnings) if result.warnings else lines.append("- 无")
        return "\n".join(lines).rstrip() + "\n"

    def _cluster_similarity(
        self,
        candidate: tuple[NewsItem, NewsScore],
        cluster: list[tuple[NewsItem, NewsScore]],
        threshold: float,
    ) -> tuple[float, str]:
        similarities = [self._pair_similarity(candidate, existing, threshold) for existing in cluster]
        return max(similarities, key=lambda item: item[0]) if similarities else (0.0, "")

    def _pair_similarity(
        self,
        left: tuple[NewsItem, NewsScore],
        right: tuple[NewsItem, NewsScore],
        threshold: float,
    ) -> tuple[float, str]:
        left_item, left_score = left
        right_item, right_score = right
        left_url = normalize_url(left_item.url or left_score.url or "")
        right_url = normalize_url(right_item.url or right_score.url or "")
        if left_url and right_url and left_url == right_url:
            return 1.0, "URL 规范化后相同"

        left_repo = self._github_repo(left_item.url) or self._github_repo(left_item.title)
        right_repo = self._github_repo(right_item.url) or self._github_repo(right_item.title)
        if left_repo and left_repo == right_repo:
            return 0.94, f"指向同一 GitHub 项目 {left_repo}"

        left_arxiv = self._arxiv_id(left_item.url)
        right_arxiv = self._arxiv_id(right_item.url)
        if left_arxiv and left_arxiv == right_arxiv:
            return 0.96, f"指向同一 arXiv 论文 {left_arxiv}"

        left_title_key = self._normalized_title(left_item.title)
        right_title_key = self._normalized_title(right_item.title)
        if left_title_key and left_title_key == right_title_key:
            return 0.93, "标题规范化后相同"

        left_keywords = self._keywords(left_item, left_score)
        right_keywords = self._keywords(right_item, right_score)
        if len(left_keywords) < 3 or len(right_keywords) < 3:
            return 0.0, ""

        overlap = left_keywords & right_keywords
        union = left_keywords | right_keywords
        jaccard = len(overlap) / len(union) if union else 0.0
        shared_entities = overlap & self._entity_tokens()
        if len(overlap) >= 3 and jaccard >= threshold:
            return jaccard, f"标题/关键词重叠: {', '.join(sorted(overlap)[:5])}"
        if len(overlap) >= 4 and jaccard >= max(0.42, threshold - 0.1) and shared_entities:
            return max(jaccard, threshold), f"实体与关键词重叠: {', '.join(sorted(overlap)[:5])}"
        if left_item.source_type == right_item.source_type and len(overlap) >= 5 and jaccard >= max(0.48, threshold - 0.05):
            return max(jaccard, threshold), "同一来源类型下疑似重复内容"
        return jaccard, ""

    def _build_event(
        self,
        cluster: list[tuple[NewsItem, NewsScore]],
        merge_reasons: list[str],
        min_score: float,
    ) -> NewsEventCard:
        primary_item, primary_score = max(cluster, key=self._primary_sort_key)
        sources = _unique([item.source for item, _score in cluster])
        source_types = _unique([item.source_type for item, _score in cluster])
        urls = _unique([item.url or score.url for item, score in cluster])
        related_titles = _unique([item.title_zh or item.title or score.title_zh or score.title for item, score in cluster])
        related_news_ids = _unique([score.news_id or item.id for item, score in cluster])
        keywords = _unique([keyword for item, score in cluster for keyword in sorted(self._keywords(item, score))])[:16]
        availability = self._cluster_availability([item.content_availability for item, _score in cluster])
        published_values = [item.published_at for item, _score in cluster if item.published_at]
        latest_item = max((item for item, _score in cluster), key=lambda item: self._timestamp(item.published_at), default=primary_item)
        earliest = min(published_values, key=self._timestamp) if published_values else None
        latest = max(published_values, key=self._timestamp) if published_values else None
        category = self._event_category([score for _item, score in cluster], primary_score)
        score = self._event_score(cluster, primary_score, source_types, sources, latest_item.freshness)
        section = CATEGORY_SECTION_MAP.get(category, "暂不推荐")
        if score < min_score or category == "noise":
            section = "暂不推荐"

        reasons = _unique(
            [
                *merge_reasons,
                *(primary_score.reasons or [])[:3],
                f"合并 {len(cluster)} 条新闻，覆盖 {len(sources)} 个来源",
            ]
        )
        if len(sources) >= 2:
            reasons.append("多来源交叉报道，事件可信度和写作价值提升")
        if any(self._is_official(item, score) for item, score in cluster):
            reasons.append("包含官方或权威来源")

        warnings = _unique([warning for _item, score in cluster for warning in score.warnings])[:8]
        event_title = primary_item.title or primary_score.title
        event_title_zh = primary_item.title_zh or primary_score.title_zh or event_title
        event_summary = self._merge_summary(cluster, zh=False)
        event_summary_zh = self._merge_summary(cluster, zh=True)
        event_id = self._event_id(primary_item, related_news_ids, urls)

        return NewsEventCard(
            event_id=event_id,
            event_title=event_title,
            event_title_zh=event_title_zh,
            event_summary=event_summary,
            event_summary_zh=event_summary_zh or event_summary,
            category=category,
            recommended_section=section,
            total_score=round(score, 2),
            importance_score=round(max(score.importance_score for _item, score in cluster), 2),
            freshness_score=round(max(score.freshness_score for _item, score in cluster), 2),
            source_count=len(sources),
            sources=sources,
            source_types=source_types,
            urls=urls,
            primary_url=primary_item.url or primary_score.url,
            primary_source=primary_item.source or primary_score.source,
            published_at=earliest,
            latest_published_at=latest,
            freshness=latest_item.freshness or primary_item.freshness or "unknown",
            keywords=keywords,
            related_news_ids=related_news_ids,
            related_titles=related_titles,
            reasons=reasons[:8],
            warnings=warnings,
            content_availability=availability,
        )

    def _apply_recommendation_limit(self, events: list[NewsEventCard], top: int, min_score: float) -> None:
        recommended = [event for event in events if event.recommended_section != "暂不推荐" and event.total_score >= min_score]
        allowed_ids = {event.event_id for event in recommended[:top]}
        for event in events:
            if event.event_id not in allowed_ids:
                event.recommended_section = "暂不推荐"

    def _primary_sort_key(self, pair: tuple[NewsItem, NewsScore]) -> tuple[int, float, float, int]:
        item, score = pair
        return (
            1 if self._is_official(item, score) else 0,
            score.total_score,
            self._timestamp(item.published_at),
            AVAILABILITY_RANK.get(item.content_availability, 0),
        )

    def _event_score(
        self,
        cluster: list[tuple[NewsItem, NewsScore]],
        primary_score: NewsScore,
        source_types: list[str],
        sources: list[str],
        freshness: str,
    ) -> float:
        score = float(primary_score.total_score or 0.0)
        score += min(14.0, max(0, len(sources) - 1) * 4.0 + max(0, len(cluster) - 1) * 1.2)
        if any(self._is_official(item, news_score) for item, news_score in cluster):
            score += 6.0
        cross_types = {"official_rss", "hackernews", "gdelt", "arxiv", "rsshub"} & {source_type.casefold() for source_type in source_types}
        if len(cross_types) >= 2:
            score += 5.0
        if {"hackernews", "official_rss"} <= cross_types or {"arxiv", "hackernews"} <= cross_types:
            score += 3.0
        score += FRESHNESS_BONUS.get(freshness or "unknown", -1.0)
        if all(news_score.category == "noise" or news_score.total_score < 45 for _item, news_score in cluster):
            score = min(score, 49.0)
        return _clamp(score)

    def _event_category(self, scores: list[NewsScore], primary_score: NewsScore) -> str:
        weighted: Counter[str] = Counter()
        for score in scores:
            weighted[score.category] += max(1, int(round(score.total_score)))
        if weighted:
            return weighted.most_common(1)[0][0]
        return primary_score.category

    def _cluster_availability(self, values: list[str]) -> str:
        cleaned = {value or "metadata_only" for value in values}
        if len(cleaned) == 1:
            return next(iter(cleaned))
        return "mixed"

    def _merge_summary(self, cluster: list[tuple[NewsItem, NewsScore]], zh: bool) -> str:
        parts: list[str] = []
        for item, _score in sorted(cluster, key=self._primary_sort_key, reverse=True):
            summary = item.summary_zh if zh else item.summary
            if not summary and zh:
                summary = item.summary
            cleaned = _short_text(summary or "", max_length=220)
            if cleaned and cleaned.casefold() not in {part.casefold() for part in parts}:
                parts.append(cleaned)
            if len(parts) >= 3:
                break
        return " ".join(parts)[:700].rstrip()

    def _keywords(self, item: NewsItem, score: NewsScore) -> set[str]:
        text = " ".join(
            [
                item.title or "",
                item.title_zh or "",
                score.title or "",
                score.title_zh or "",
                item.summary or "",
                item.summary_zh or "",
                " ".join(item.keywords or []),
                " ".join(score.keywords or []),
                " ".join(item.topics or []),
                item.url or "",
            ]
        )
        values: set[str] = set()
        lowered = text.casefold()
        for entity in ENTITY_TERMS:
            if entity.casefold() in lowered:
                values.add(entity.casefold())
        repo = self._github_repo(item.url) or self._github_repo(text)
        if repo:
            values.add(repo.casefold())
            values.add(repo.split("/")[-1].casefold())
        for token in TOKEN_PATTERN.findall(text):
            cleaned = token.strip().strip("-_/").translate(PUNCT_TRANSLATION).casefold()
            if not cleaned or cleaned in GENERIC_TERMS:
                continue
            if cleaned.startswith(("http", "www")):
                continue
            if len(cleaned) < 3 and not re.search(r"[\u4e00-\u9fff]", cleaned):
                continue
            values.add(cleaned)
        return values

    def _entity_tokens(self) -> set[str]:
        return {entity.casefold() for entity in ENTITY_TERMS}

    def _github_repo(self, value: str | None) -> str:
        text = value or ""
        match = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".").casefold()
        return ""

    def _arxiv_id(self, url: str | None) -> str:
        parsed = urlparse(url or "")
        match = re.search(r"/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", parsed.path)
        return match.group(1) if match else ""

    def _normalized_title(self, title: str | None) -> str:
        cleaned = (title or "").casefold()
        cleaned = re.sub(r"^(show|ask|tell)\s+hn:\s*", "", cleaned)
        cleaned = cleaned.translate(PUNCT_TRANSLATION)
        tokens = [token for token in cleaned.split() if token not in GENERIC_TERMS]
        return " ".join(tokens[:18])

    def _is_official(self, item: NewsItem, score: NewsScore) -> bool:
        source_type = (item.source_type or score.source_type or "").casefold()
        if source_type == "official_rss":
            return True
        combined = f"{item.source} {score.source} {urlparse(item.url or score.url or '').netloc}".casefold()
        return any(hint in combined for hint in OFFICIAL_HINTS)

    def _timestamp(self, value: str | None) -> float:
        parsed = parse_datetime(value)
        return parsed.timestamp() if parsed else 0.0

    def _event_id(self, primary: NewsItem, related_news_ids: list[str], urls: list[str]) -> str:
        raw = "|".join([primary.title or "", *sorted(related_news_ids), *sorted(urls)])
        return f"evt_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"
