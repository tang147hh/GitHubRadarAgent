from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config import get_settings
from src.interaction_metrics import strip_interaction_metric_text, without_interaction_metric_values
from src.models import NewsCollectionResult, NewsItem, NewsScore, NewsScoringResult
from src.news_collector import parse_datetime, utc_now_iso


CATEGORY_SECTION_MAP = {
    "major_event": "今日大事件",
    "model_product": "模型与产品",
    "open_source": "开源与工具",
    "research_paper": "论文与研究",
    "developer_tool": "开源与工具",
    "funding_business": "商业与监管",
    "policy_regulation": "商业与监管",
    "community_discussion": "开发者社区",
    "tutorial_resource": "开发者社区",
    "noise": "暂不推荐",
}

SECTION_LIMITS = {
    "今日大事件": 5,
    "模型与产品": 6,
    "开源与工具": 6,
    "论文与研究": 5,
    "开发者社区": 5,
    "商业与监管": 4,
}

RELEVANCE_KEYWORDS = [
    "OpenAI",
    "Anthropic",
    "DeepSeek",
    "Google DeepMind",
    "NVIDIA",
    "LLM",
    "AI agent",
    "MCP",
    "RAG",
    "model release",
    "API",
    "open source",
    "benchmark",
    "regulation",
    "Claude",
    "GPT",
    "Gemini",
    "Llama",
]

MAJOR_EVENT_TERMS = [
    "breakthrough",
    "launches",
    "released",
    "announces",
    "unveils",
    "重大",
    "发布",
    "推出",
    "首个",
]
MODEL_PRODUCT_TERMS = [
    "model",
    "api",
    "gpt",
    "claude",
    "gemini",
    "deepseek",
    "llama",
    "mistral",
    "copilot",
    "chatgpt",
    "模型",
    "产品",
]
OPEN_SOURCE_TERMS = ["github", "open source", "repo", "repository", "oss", "开源", "仓库"]
DEVELOPER_TOOL_TERMS = ["sdk", "cli", "developer", "tool", "mcp", "rag", "agent framework", "工具", "开发者"]
POLICY_TERMS = ["regulation", "policy", "law", "lawsuit", "eu ai act", "china", "copyright", "监管", "政策", "诉讼"]
BUSINESS_TERMS = ["funding", "acquisition", "revenue", "startup", "raises", "valuation", "ipo", "融资", "收购", "营收"]
COMMUNITY_TERMS = ["ask hn", "show hn", "hacker news", "discussion", "社区", "开发者"]
TUTORIAL_TERMS = ["tutorial", "guide", "how to", "course", "learn", "教程", "指南"]
NOISE_TERMS = [
    "hiring",
    "we're hiring",
    "job",
    "jobs",
    "sponsored",
    "advertorial",
    "coupon",
    "招聘",
    "广告",
]
QUESTION_PREFIXES = ("ask hn:", "tell hn:", "why ", "how do ", "how can ", "what are ", "is there ")


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


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.casefold()
    return [term for term in terms if term.casefold() in lowered]


def _short_text(value: str, max_length: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    return cleaned[:max_length].rstrip()


def _safe_markdown_cell(value: str) -> str:
    return (value or "-").replace("|", "\\|").replace("\n", " ")


class NewsScoringService:
    """Score collected AI news with deterministic editorial rules."""

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

    def score_latest(self, top: int = 20, min_score: float = 60.0) -> NewsScoringResult:
        return self.score_collection(self.load_latest_collection(), top=top, min_score=min_score)

    def score_collection(self, collection: NewsCollectionResult, top: int = 20, min_score: float = 60.0) -> NewsScoringResult:
        top = max(1, min(int(top or 20), 100))
        min_score = _clamp(float(min_score), 0.0, 100.0)
        warnings = list(collection.warnings or [])

        scores = [self.score_item(item) for item in collection.items]
        scores.sort(key=lambda score: score.total_score, reverse=True)
        self._apply_recommendations(scores, top=top, min_score=min_score, warnings=warnings)

        category_counts = Counter(score.category for score in scores)
        section_counts = Counter(score.recommended_section for score in scores if score.recommended)
        result = NewsScoringResult(
            generated_at=utc_now_iso(),
            total_count=len(scores),
            recommended_count=sum(1 for score in scores if score.recommended),
            category_counts=dict(sorted(category_counts.items())),
            section_counts=dict(sorted(section_counts.items())),
            scores=scores,
            warnings=warnings,
        )
        self.save_result(result)
        return result

    def score_item(self, item: NewsItem) -> NewsScore:
        text = strip_interaction_metric_text(self._combined_text(item))
        category = self._classify(item, text)
        reasons: list[str] = []
        warnings: list[str] = []

        freshness_score = self._freshness_score(item, reasons, warnings)
        source_score = self._source_score(item, reasons)
        relevance_score, keyword_hits = self._relevance_score(item, text, reasons)
        discussion_score = self._discussion_score(item, reasons)
        writing_value_score = self._writing_value_score(item, text, category, reasons)
        importance_score = self._importance_score(item, text, category, keyword_hits, reasons)
        noise_penalty = self._noise_penalty(item, text, category, warnings)

        total_score = (
            freshness_score * 0.16
            + source_score * 0.14
            + relevance_score * 0.22
            + discussion_score * 0.12
            + writing_value_score * 0.22
            + importance_score * 0.14
            - noise_penalty
        )
        if category == "noise":
            total_score = min(total_score, 42.0)
        total_score = round(_clamp(total_score), 2)

        keywords = self._merge_keywords(item, keyword_hits)
        return NewsScore(
            news_id=item.id,
            title=item.title,
            title_zh=item.title_zh,
            url=item.url,
            source=item.source,
            source_type=item.source_type,
            category=category,
            importance_score=round(importance_score, 2),
            freshness_score=round(freshness_score, 2),
            source_score=round(source_score, 2),
            relevance_score=round(relevance_score, 2),
            discussion_score=round(discussion_score, 2),
            writing_value_score=round(writing_value_score, 2),
            total_score=total_score,
            recommended=False,
            recommended_section=CATEGORY_SECTION_MAP.get(category, "暂不推荐"),
            reasons=without_interaction_metric_values(reasons)[:8],
            warnings=warnings[:5],
            keywords=keywords[:12],
        )

    def save_result(self, result: NewsScoringResult) -> None:
        generated_date = datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(result), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_scores_latest.json").write_text(payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news-scores.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_scores_latest.json").write_text(payload, encoding="utf-8")
        (output_date_dir / "news_scores_report.md").write_text(self.render_report(result), encoding="utf-8")

    def render_report(self, result: NewsScoringResult) -> str:
        recommended = [score for score in result.scores if score.recommended]
        noise_examples = [score for score in result.scores if not score.recommended or score.category == "noise"][:10]
        lines = [
            "# AI News Scores Report",
            "",
            f"- 评分时间: {result.generated_at}",
            f"- 总新闻数: {result.total_count}",
            f"- 推荐新闻数: {result.recommended_count}",
            "",
            "## 分类统计",
            "",
        ]
        if result.category_counts:
            lines.extend(f"- {category}: {count}" for category, count in sorted(result.category_counts.items()))
        else:
            lines.append("- none: 0")

        lines.extend(["", "## 栏目统计", ""])
        if result.section_counts:
            lines.extend(f"- {section}: {count}" for section, count in sorted(result.section_counts.items()))
        else:
            lines.append("- none: 0")

        lines.extend(
            [
                "",
                "## Top 推荐新闻",
                "",
                "| 中文标题 | 来源 | 分类 | 推荐栏目 | total_score | reasons | URL |",
                "| --- | --- | --- | --- | ---: | --- | --- |",
            ]
        )
        if recommended:
            for score in recommended:
                title = score.title_zh or score.title
                reasons = "；".join(score.reasons[:3])
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _safe_markdown_cell(title),
                            _safe_markdown_cell(score.source),
                            _safe_markdown_cell(score.category),
                            _safe_markdown_cell(score.recommended_section),
                            f"{score.total_score:.2f}",
                            _safe_markdown_cell(reasons),
                            _safe_markdown_cell(score.url),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("| - | - | - | - | 0 | - | - |")

        lines.extend(["", "## 噪音 / 不推荐示例", ""])
        if noise_examples:
            for index, score in enumerate(noise_examples, start=1):
                title = score.title_zh or score.title
                warning_text = "；".join(score.warnings or score.reasons[:2])
                lines.append(
                    f"{index}. {title} | {score.source} | {score.category} | "
                    f"{score.total_score:.2f} | {warning_text or '未达到推荐阈值'}"
                )
        else:
            lines.append("- 无")

        lines.extend(["", "## Warnings", ""])
        if result.warnings:
            lines.extend(f"- {warning}" for warning in result.warnings)
        else:
            lines.append("- 无")
        return "\n".join(lines).rstrip() + "\n"

    def _combined_text(self, item: NewsItem) -> str:
        parts = [
            item.title,
            item.title_zh or "",
            item.summary or "",
            item.summary_zh or "",
            item.content_text or "",
            " ".join(item.topics or []),
            " ".join(item.keywords or []),
            item.source or "",
            item.source_type or "",
            item.url or "",
        ]
        return " ".join(part for part in parts if part)

    def _classify(self, item: NewsItem, text: str) -> str:
        lowered_title = (item.title or "").casefold().strip()
        lowered_url = (item.url or "").casefold()
        if self._is_noise(item, text):
            return "noise"
        if item.source_type == "arxiv":
            return "research_paper"
        if self._is_hn_source(item) and (_contains_any(text, COMMUNITY_TERMS) or lowered_title.startswith(QUESTION_PREFIXES)):
            return "community_discussion"
        if _contains_any(text, POLICY_TERMS):
            return "policy_regulation"
        if _contains_any(text, BUSINESS_TERMS):
            return "funding_business"
        if _contains_any(text, ["paper", "arxiv", "research", "benchmark", "论文", "研究"]):
            return "research_paper"
        if _contains_any(text, OPEN_SOURCE_TERMS) or "github.com" in lowered_url:
            if _contains_any(text, DEVELOPER_TOOL_TERMS):
                return "developer_tool"
            return "open_source"
        if _contains_any(text, MODEL_PRODUCT_TERMS):
            return "model_product"
        if _contains_any(text, DEVELOPER_TOOL_TERMS):
            return "developer_tool"
        if _contains_any(text, COMMUNITY_TERMS):
            return "community_discussion"
        if _contains_any(text, TUTORIAL_TERMS):
            return "tutorial_resource"
        if _contains_any(text, MAJOR_EVENT_TERMS) and _contains_any(text, RELEVANCE_KEYWORDS):
            return "major_event"
        return "noise" if self._weak_ai_relation(item, text) else "community_discussion"

    def _freshness_score(self, item: NewsItem, reasons: list[str], warnings: list[str]) -> float:
        freshness = item.freshness or ""
        if freshness == "today":
            reasons.append("今日发布，时效性强")
            return 96.0
        if freshness == "last_24h":
            reasons.append("24 小时内新闻")
            return 88.0
        if freshness == "last_72h":
            reasons.append("72 小时内仍有跟进价值")
            return 62.0
        if freshness == "older":
            warnings.append("发布时间较旧")
            return 30.0

        published = parse_datetime(item.published_at)
        if published:
            age_hours = max(0.0, (datetime.now(published.tzinfo) - published).total_seconds() / 3600)
            if age_hours <= 24:
                reasons.append("发布时间在 24 小时内")
                return 84.0
            if age_hours <= 72:
                reasons.append("发布时间在 72 小时内")
                return 60.0
        warnings.append("发布时间未知，时效性扣分")
        return 24.0

    def _source_score(self, item: NewsItem, reasons: list[str]) -> float:
        source_type = (item.source_type or "").casefold()
        source = (item.source or "").casefold()
        domain = urlparse(item.url or "").netloc.casefold()
        score_by_type = {
            "official_rss": 88.0,
            "arxiv": 82.0,
            "hackernews": 72.0,
            "community_discussion": 68.0,
            "gdelt": 58.0,
            "rsshub": 56.0,
        }
        score = score_by_type.get(source_type, 45.0)
        if source_type == "official_rss":
            reasons.append("来自官方 RSS 源")
        elif source_type == "arxiv":
            reasons.append("来自论文源 arXiv")
        elif source_type in {"hackernews", "community_discussion"}:
            reasons.append("来自 Hacker News 开发者社区来源")
        elif source_type == "gdelt":
            reasons.append("来自 GDELT 全球媒体检索")
        if any(name in f"{source} {domain}" for name in ("openai", "anthropic", "deepmind", "nvidia", "microsoft", "google")):
            score += 8.0
            reasons.append("来源/域名具有较高权威性")
        return _clamp(score)

    def _relevance_score(self, item: NewsItem, text: str, reasons: list[str]) -> tuple[float, list[str]]:
        hits = _matched_terms(text, RELEVANCE_KEYWORDS)
        existing_hits = list(item.keywords or [])
        merged_hits = []
        for keyword in [*hits, *existing_hits]:
            if keyword and keyword.casefold() not in {value.casefold() for value in merged_hits}:
                merged_hits.append(keyword)
        score = 18.0 + min(68.0, len(merged_hits) * 9.0)
        if any(term.casefold() in text.casefold() for term in ("ai", "llm", "agent", "模型", "人工智能")):
            score += 10.0
        if merged_hits:
            reasons.append(f"命中 AI 关键词: {', '.join(merged_hits[:5])}")
        return _clamp(score), merged_hits

    def _discussion_score(self, item: NewsItem, reasons: list[str]) -> float:
        if not self._is_hn_source(item):
            return 0.0
        reasons.append("开发者社区来源，仅作低权重来源信号")
        return 18.0

    def _writing_value_score(self, item: NewsItem, text: str, category: str, reasons: list[str]) -> float:
        score = 24.0
        signals = [
            ("产品发布", ["launch", "release", "announce", "unveil", "发布", "推出"]),
            ("开源项目", OPEN_SOURCE_TERMS),
            ("重大模型更新", ["model", "gpt", "claude", "gemini", "deepseek", "llama", "模型"]),
            ("开发者影响", DEVELOPER_TOOL_TERMS),
            ("行业争议", ["controversy", "lawsuit", "regulation", "ban", "copyright", "争议", "监管"]),
            ("实用工具", ["tool", "sdk", "cli", "api", "workflow", "工具"]),
        ]
        matched_labels = []
        for label, terms in signals:
            if _contains_any(text, terms):
                matched_labels.append(label)
                score += 11.0
        if category in {"major_event", "model_product", "open_source", "developer_tool", "policy_regulation"}:
            score += 10.0
        if matched_labels:
            reasons.append(f"具备公众号选题信号: {'、'.join(matched_labels[:4])}")
        if len((item.summary_zh or item.summary or "").strip()) >= 80:
            score += 5.0
        return _clamp(score)

    def _importance_score(
        self,
        item: NewsItem,
        text: str,
        category: str,
        keyword_hits: list[str],
        reasons: list[str],
    ) -> float:
        score = 25.0 + len(keyword_hits) * 5.0
        if category == "major_event":
            score += 28.0
        elif category in {"model_product", "policy_regulation"}:
            score += 18.0
        elif category in {"open_source", "developer_tool", "research_paper"}:
            score += 12.0
        if _contains_any(text, MAJOR_EVENT_TERMS):
            score += 10.0
            reasons.append("标题/摘要包含发布或重大进展信号")
        return _clamp(score)

    def _noise_penalty(self, item: NewsItem, text: str, category: str, warnings: list[str]) -> float:
        penalty = 0.0
        title = (item.title or "").strip()
        lowered_title = title.casefold()
        if _contains_any(text, NOISE_TERMS):
            penalty += 28.0
            warnings.append("疑似招聘、广告或营销内容")
        if len(title) < 18 and len((item.summary or "").strip()) < 40:
            penalty += 14.0
            warnings.append("标题和摘要信息量偏低")
        if lowered_title.startswith(QUESTION_PREFIXES) and self._is_hn_source(item):
            penalty += 10.0
            warnings.append("论坛提问帖，需人工判断信息增量")
        if self._weak_ai_relation(item, text):
            penalty += 24.0
            warnings.append("与 AI 主题相关性较弱")
        if category == "noise":
            penalty += 18.0
        return penalty

    def _apply_recommendations(
        self,
        scores: list[NewsScore],
        top: int,
        min_score: float,
        warnings: list[str],
    ) -> None:
        threshold = min_score
        selected = self._select_recommended(scores, top=top, threshold=threshold)
        if len(selected) < min(5, top):
            threshold = min(50.0, min_score)
            selected = self._select_recommended(scores, top=top, threshold=threshold)
            warnings.append("推荐数量偏少，已将评分阈值降至 50 进行补位。")

        selected_ids = {score.news_id for score in selected}
        for score in scores:
            score.recommended = score.news_id in selected_ids
            if not score.recommended:
                score.recommended_section = "暂不推荐"
        scores.sort(key=lambda score: (score.recommended, score.total_score), reverse=True)

    def _select_recommended(self, scores: list[NewsScore], top: int, threshold: float) -> list[NewsScore]:
        selected: list[NewsScore] = []
        per_section_counts: dict[str, int] = defaultdict(int)
        for score in scores:
            if len(selected) >= top:
                break
            if score.category == "noise" or score.total_score < threshold:
                continue
            section = CATEGORY_SECTION_MAP.get(score.category, "暂不推荐")
            if section == "暂不推荐":
                continue
            limit = SECTION_LIMITS.get(section, 4)
            if per_section_counts[section] >= limit:
                continue
            score.recommended_section = section
            selected.append(score)
            per_section_counts[section] += 1

        if len(selected) < top:
            selected_ids = {score.news_id for score in selected}
            for score in scores:
                if len(selected) >= top:
                    break
                if score.news_id in selected_ids or score.category == "noise" or score.total_score < threshold:
                    continue
                score.recommended_section = CATEGORY_SECTION_MAP.get(score.category, "暂不推荐")
                if score.recommended_section == "暂不推荐":
                    continue
                selected.append(score)
                selected_ids.add(score.news_id)
        return selected

    def _is_noise(self, item: NewsItem, text: str) -> bool:
        return _contains_any(text, NOISE_TERMS) or self._weak_ai_relation(item, text) and item.source_type == "gdelt"

    def _is_hn_source(self, item: NewsItem) -> bool:
        source_type = (item.source_type or "").casefold()
        source = (item.source or "").casefold()
        return source_type in {"hackernews", "community_discussion"} or "hacker news" in source

    def _weak_ai_relation(self, item: NewsItem, text: str) -> bool:
        lowered = text.casefold()
        ai_terms = ["ai", "artificial intelligence", "llm", "agent", "model", "openai", "模型", "人工智能"]
        if any(term in lowered for term in ai_terms):
            return False
        return not item.keywords

    def _merge_keywords(self, item: NewsItem, hits: list[str]) -> list[str]:
        merged: list[str] = []
        for keyword in [*(item.keywords or []), *hits, *(item.topics or [])]:
            cleaned = _short_text(str(keyword), max_length=80)
            if cleaned and cleaned.casefold() not in {value.casefold() for value in merged}:
                merged.append(cleaned)
        return merged
