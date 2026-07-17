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
from src.news_sources import FUN_STORY_KEYWORDS, INDUSTRY_KEYWORDS, POLICY_KEYWORDS, RESEARCH_KEYWORDS, TREND_KEYWORDS


CATEGORY_SECTION_MAP = {
    "policy_regulation": "政策与监管",
    "trend_industry": "趋势观察",
    "official_product": "大厂与产品",
    "research_breakthrough": "研究前沿",
    "fun_story": "AI 趣事",
    "developer_tool": "开发者社区",
    "open_source": "开发者社区",
    "community_discussion": "开发者社区",
    "noise": "暂不推荐",
}
SECTION_LIMITS = {
    "政策与监管": 6,
    "趋势观察": 6,
    "大厂与产品": 6,
    "产业动态": 6,
    "研究前沿": 5,
    "AI 趣事": 5,
    "开发者社区": 3,
}
PRIORITY_SECTIONS = ["政策与监管", "趋势观察", "大厂与产品", "产业动态", "研究前沿", "AI 趣事"]

AI_TERMS = [
    "artificial intelligence", " ai ", "llm", "openai", "anthropic", "deepmind", "nvidia", "claude", "gpt",
    "gemini", "llama", "model", "inference", "agent", "copilot", "multimodal", "robotics", "人工智能", "模型",
    "推理", "智能体", "多模态",
]
OFFICIAL_PRODUCT_TERMS = [
    "launch", "release", "announce", "unveil", "product", "platform", "model", "api", "copilot", "发布", "推出", "产品", "模型",
]
DEVELOPER_TOOL_TERMS = ["sdk", "cli", "developer tool", "framework", "api", "mcp", "rag", "开发工具", "框架"]
OPEN_SOURCE_TERMS = ["open source", "github", "repository", "repo", "开源", "仓库"]
NOISE_TERMS = [
    "hiring", "we're hiring", "job opening", "sponsored", "advertorial", "coupon", "limited offer", "招聘", "广告", "优惠券", "软文",
]
QUESTION_PREFIXES = ("ask hn:", "tell hn:", "why ", "how do ", "how can ", "what are ", "is there ")
POLICY_CLASSIFICATION_TERMS = [
    "AI regulation", "AI policy", "AI Act", "copyright", "lawsuit", "national security", "data privacy",
    "government", "regulator", "compliance", "监管", "政策", "版权", "诉讼", "合规",
]
FUN_CLASSIFICATION_TERMS = [
    "weird", "funny", "viral", "surprising", "accidentally", "strange", "bizarre", "unexpected",
    "趣事", "翻车", "意外", "爆火", "离谱", "有意思",
]


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _model_validate(model_class: Any, payload: dict[str, Any]) -> Any:
    return model_class.model_validate(payload) if hasattr(model_class, "model_validate") else model_class.parse_obj(payload)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _matches(text: str, terms: list[str]) -> list[str]:
    lowered = text.casefold()
    matches: list[str] = []
    for term in terms:
        needle = term.casefold()
        if re.fullmatch(r"[a-z0-9][a-z0-9 ._-]*", needle):
            pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
            if re.search(pattern, lowered):
                matches.append(term)
        elif needle in lowered:
            matches.append(term)
    return matches


def _contains(text: str, terms: list[str]) -> bool:
    return bool(_matches(text, terms))


def _safe_markdown_cell(value: str) -> str:
    return (value or "-").replace("|", "\\|").replace("\n", " ")


class NewsScoringService:
    """Score AI news using editorial value and source quality only."""

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
        min_score = _clamp(float(min_score))
        warnings = list(collection.warnings or [])
        scores = [self.score_item(item) for item in collection.items]
        scores.sort(key=lambda score: score.total_score, reverse=True)
        self._apply_recommendations(scores, top, min_score, warnings)
        result = NewsScoringResult(
            generated_at=utc_now_iso(),
            total_count=len(scores),
            recommended_count=sum(1 for score in scores if score.recommended),
            source_category_counts=dict(sorted(Counter(score.source_category for score in scores).items())),
            category_counts=dict(sorted(Counter(score.category for score in scores).items())),
            section_counts=dict(sorted(Counter(score.recommended_section for score in scores if score.recommended).items())),
            scores=scores,
            warnings=warnings,
        )
        self.save_result(result)
        return result

    def score_item(self, item: NewsItem) -> NewsScore:
        text = strip_interaction_metric_text(self._combined_text(item))
        category = self._classify(item, text)
        section = self._section_for(category, text)
        policy = self._dimension_score(text, POLICY_KEYWORDS, 25.0, 11.0, item.editorial_category == "policy_regulation")
        trend = self._dimension_score(
            text, TREND_KEYWORDS, 25.0, 10.0, item.editorial_category == "trend_industry" or item.source_category == "official_product"
        )
        industry = self._dimension_score(text, INDUSTRY_KEYWORDS, 25.0, 10.0, item.source_category == "trend_industry")
        public_interest = self._dimension_score(text, FUN_STORY_KEYWORDS, 22.0, 12.0, item.editorial_category == "fun_story")
        source_reliability = self._source_reliability(item)
        freshness, freshness_reason, freshness_warning = self._freshness(item)
        ai_relevance, ai_hits = self._ai_relevance(item, text)
        writing_value = self._writing_value(item, category, policy, trend, industry, public_interest)
        noise_penalty = self._noise_penalty(item, text, category)

        total = (
            policy * 0.15
            + trend * 0.15
            + industry * 0.14
            + public_interest * 0.10
            + source_reliability * 0.12
            + freshness * 0.10
            + ai_relevance * 0.12
            + writing_value * 0.12
            - noise_penalty
        )
        if category == "noise":
            total = min(total, 35.0)
        reasons = self._reasons(item, section, policy, trend, industry, public_interest, writing_value, freshness_reason)
        warnings = [warning for warning in [freshness_warning, self._noise_warning(item, text)] if warning]
        importance = max(policy, trend, industry, public_interest, writing_value)
        keywords = self._merge_keywords(item, ai_hits + _matches(text, POLICY_KEYWORDS + TREND_KEYWORDS + FUN_STORY_KEYWORDS + INDUSTRY_KEYWORDS))
        return NewsScore(
            news_id=item.id,
            title=item.title,
            title_zh=item.title_zh,
            url=item.url,
            source=item.source,
            source_type=item.source_type,
            source_category=item.source_category or "noise",
            editorial_category=item.editorial_category or item.source_category or "noise",
            category=category,
            importance_score=round(importance, 2),
            policy_value_score=round(policy, 2),
            trend_value_score=round(trend, 2),
            industry_impact_score=round(industry, 2),
            public_interest_score=round(public_interest, 2),
            source_reliability_score=round(source_reliability, 2),
            freshness_score=round(freshness, 2),
            ai_relevance_score=round(ai_relevance, 2),
            writing_value_score=round(writing_value, 2),
            total_score=round(_clamp(total), 2),
            recommended=False,
            recommended_section=section,
            reasons=without_interaction_metric_values(reasons)[:6],
            warnings=warnings[:4],
            keywords=keywords[:16],
        )

    def save_result(self, result: NewsScoringResult) -> None:
        generated_date = datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        for directory in (news_dir, snapshots_dir, output_date_dir):
            directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_model_dump(result), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_scores_latest.json").write_text(payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news-scores.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_scores_latest.json").write_text(payload, encoding="utf-8")
        (output_date_dir / "news_scores_report.md").write_text(self.render_report(result), encoding="utf-8")

    def render_report(self, result: NewsScoringResult) -> str:
        recommended = [score for score in result.scores if score.recommended]
        lines = [
            "# AI News Scores Report", "", f"- 评分时间: {result.generated_at}", f"- 总新闻数: {result.total_count}",
            f"- 推荐新闻数: {result.recommended_count}", "- 互动数量已被忽略，不参与评分。", "", "## source_category 统计", "",
        ]
        lines.extend(f"- {category}: {count}" for category, count in result.source_category_counts.items())
        lines.extend(["", "## category 统计", ""])
        lines.extend(f"- {category}: {count}" for category, count in result.category_counts.items())
        lines.extend(["", "## 栏目统计", ""])
        lines.extend(f"- {section}: {count}" for section, count in result.section_counts.items())
        lines.extend(["", "## Top 推荐新闻", "", "| 中文标题 | 来源 | source_category | 分类 | 推荐栏目 | 总分 | 推荐理由 | URL |", "| --- | --- | --- | --- | --- | ---: | --- | --- |"])
        if recommended:
            for score in recommended:
                lines.append("| " + " | ".join([
                    _safe_markdown_cell(score.title_zh or score.title), _safe_markdown_cell(score.source),
                    _safe_markdown_cell(score.source_category), _safe_markdown_cell(score.category),
                    _safe_markdown_cell(score.recommended_section), f"{score.total_score:.2f}",
                    _safe_markdown_cell("；".join(score.reasons[:3])), _safe_markdown_cell(score.url),
                ]) + " |")
        else:
            lines.append("| - | - | - | - | - | 0 | - | - |")

        group_specs = [
            ("政策 Top 新闻", lambda score: score.category == "policy_regulation"),
            ("趋势 Top 新闻", lambda score: score.recommended_section == "趋势观察"),
            ("趣事 Top 新闻", lambda score: score.category == "fun_story"),
            ("产业 Top 新闻", lambda score: score.recommended_section == "产业动态"),
        ]
        for heading, predicate in group_specs:
            lines.extend(["", f"## {heading}", ""])
            matches = [score for score in result.scores if predicate(score)][:5]
            lines.extend(
                f"{index}. {score.title_zh or score.title} | {score.source} | {score.total_score:.2f} | {score.url}"
                for index, score in enumerate(matches, 1)
            )
            if not matches:
                lines.append("- 本轮暂无匹配新闻")

        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result.warnings) if result.warnings else lines.append("- 无")
        return "\n".join(lines).rstrip() + "\n"

    def _combined_text(self, item: NewsItem) -> str:
        return " ".join(filter(None, [
            item.title, item.title_zh or "", item.summary or "", item.summary_zh or "", item.content_text or "",
            " ".join(item.topics or []), " ".join(item.keywords or []), item.source or "", item.url or "",
        ]))

    def _classify(self, item: NewsItem, text: str) -> str:
        title = (item.title or "").casefold().strip()
        if self._is_noise(item, text):
            return "noise"
        if item.editorial_category == "policy_regulation" and _contains(text, POLICY_CLASSIFICATION_TERMS):
            return "policy_regulation"
        if _contains(text, POLICY_CLASSIFICATION_TERMS):
            return "policy_regulation"
        if _contains(text, FUN_CLASSIFICATION_TERMS):
            return "fun_story"
        if item.source_type == "arxiv" or item.editorial_category == "research_breakthrough" or _contains(text, RESEARCH_KEYWORDS):
            return "research_breakthrough"
        if item.source_category == "official_product" and _contains(text, OFFICIAL_PRODUCT_TERMS):
            return "official_product"
        if _contains(text, OPEN_SOURCE_TERMS):
            return "developer_tool" if _contains(text, DEVELOPER_TOOL_TERMS) else "open_source"
        if item.source_category == "developer_community" or title.startswith(QUESTION_PREFIXES):
            return "community_discussion"
        if _contains(text, TREND_KEYWORDS + INDUSTRY_KEYWORDS) or item.editorial_category == "trend_industry":
            return "trend_industry"
        if item.source_category == "official_product":
            return "official_product"
        return "noise" if self._weak_ai_relation(item, text) else "trend_industry"

    def _section_for(self, category: str, text: str) -> str:
        if category == "trend_industry" and _contains(text, INDUSTRY_KEYWORDS):
            return "产业动态"
        return CATEGORY_SECTION_MAP.get(category, "暂不推荐")

    def _dimension_score(self, text: str, terms: list[str], base: float, per_hit: float, category_bonus: bool) -> float:
        score = base + min(65.0, len(_matches(text, terms)) * per_hit)
        if category_bonus:
            score += 22.0
        return _clamp(score)

    def _source_reliability(self, item: NewsItem) -> float:
        by_category = {
            "official_product": 94.0, "policy_regulation": 86.0, "research_breakthrough": 88.0,
            "trend_industry": 76.0, "fun_story": 66.0, "developer_community": 42.0, "noise": 25.0,
        }
        score = by_category.get(item.source_category or "noise", 45.0)
        domain = urlparse(item.url or "").netloc.casefold()
        if any(name in domain for name in ("openai.com", "anthropic.com", "deepmind.google", "microsoft.com", "nvidia.com", "mit.edu", "stanford.edu", "nist.gov", "europa.eu", "oecd.ai")):
            score += 5.0
        return _clamp(score)

    def _freshness(self, item: NewsItem) -> tuple[float, str, str]:
        values = {"today": (96.0, "今日发布，时效性强", ""), "last_24h": (88.0, "24 小时内发布", ""), "last_72h": (68.0, "72 小时内发布", ""), "older": (30.0, "", "发布时间较旧")}
        if item.freshness in values:
            return values[item.freshness]
        published = parse_datetime(item.published_at)
        if published:
            age_hours = max(0.0, (datetime.now(published.tzinfo) - published).total_seconds() / 3600)
            if age_hours <= 24:
                return 86.0, "24 小时内发布", ""
            if age_hours <= 72:
                return 66.0, "72 小时内发布", ""
        return 24.0, "", "发布时间未知，时效性扣分"

    def _ai_relevance(self, item: NewsItem, text: str) -> tuple[float, list[str]]:
        hits = _matches(text, AI_TERMS)
        score = 24.0 + min(66.0, len(hits) * 9.0) + min(10.0, len(item.keywords or []) * 2.0)
        return _clamp(score), hits

    def _writing_value(self, item: NewsItem, category: str, policy: float, trend: float, industry: float, public: float) -> float:
        score = 34.0 + max(policy, trend, industry, public) * 0.5
        if category in {"policy_regulation", "trend_industry", "official_product", "research_breakthrough", "fun_story"}:
            score += 12.0
        if len((item.summary_zh or item.summary or "").strip()) >= 80:
            score += 8.0
        if item.content_availability == "full_text":
            score += 8.0
        return _clamp(score)

    def _reasons(self, item: NewsItem, section: str, policy: float, trend: float, industry: float, public: float, writing: float, freshness_reason: str) -> list[str]:
        reasons: list[str] = []
        if item.source_category == "official_product":
            reasons.append("来自官方来源")
        if policy >= 55:
            reasons.append("涉及 AI 监管/政策变化")
        if trend >= 55:
            reasons.append("具备趋势观察价值")
        if industry >= 55:
            reasons.append("有清晰产业影响")
        if public >= 55:
            reasons.append("适合做轻量趣事选题")
        if writing >= 65:
            reasons.append("适合写成简报条目")
        if freshness_reason:
            reasons.append(freshness_reason)
        if section == "研究前沿" and "适合写成简报条目" not in reasons:
            reasons.append("研究进展具备产业观察价值")
        return reasons

    def _noise_penalty(self, item: NewsItem, text: str, category: str) -> float:
        penalty = 0.0
        if _contains(text, NOISE_TERMS):
            penalty += 35.0
        if len((item.title or "").strip()) < 18 and len((item.summary or "").strip()) < 40:
            penalty += 15.0
        if self._weak_ai_relation(item, text):
            penalty += 28.0
        if category == "noise":
            penalty += 18.0
        if item.source_category == "developer_community":
            penalty += 8.0
        return penalty

    def _noise_warning(self, item: NewsItem, text: str) -> str:
        if _contains(text, NOISE_TERMS):
            return "疑似招聘、广告或低信息量推广"
        if self._weak_ai_relation(item, text):
            return "与 AI 主题相关性较弱"
        return ""

    def _apply_recommendations(self, scores: list[NewsScore], top: int, min_score: float, warnings: list[str]) -> None:
        selected = self._select_recommended(scores, top, min_score)
        if len(selected) < min(5, top):
            selected = self._select_recommended(scores, top, min(50.0, min_score))
            warnings.append("推荐数量偏少，已将评分阈值降至 50 进行补位。")
        selected_ids = {score.news_id for score in selected}
        for score in scores:
            score.recommended = score.news_id in selected_ids
            if not score.recommended:
                score.recommended_section = "暂不推荐"
        scores.sort(key=lambda score: (score.recommended, score.total_score), reverse=True)

    def _select_recommended(self, scores: list[NewsScore], top: int, threshold: float) -> list[NewsScore]:
        eligible = [score for score in scores if score.category != "noise" and score.total_score >= threshold]
        selected: list[NewsScore] = []
        counts: dict[str, int] = defaultdict(int)
        for section in PRIORITY_SECTIONS:
            candidate = next((score for score in eligible if score.recommended_section == section and score not in selected), None)
            if candidate and len(selected) < top:
                selected.append(candidate)
                counts[section] += 1
        for score in eligible:
            if len(selected) >= top:
                break
            section = score.recommended_section
            if score in selected or section == "暂不推荐" or counts[section] >= SECTION_LIMITS.get(section, 4):
                continue
            selected.append(score)
            counts[section] += 1
        return selected

    def _is_noise(self, item: NewsItem, text: str) -> bool:
        return _contains(text, NOISE_TERMS) or (self._weak_ai_relation(item, text) and item.source_type == "gdelt")

    def _weak_ai_relation(self, item: NewsItem, text: str) -> bool:
        return not _contains(text, AI_TERMS) and not item.keywords

    def _merge_keywords(self, item: NewsItem, hits: list[str]) -> list[str]:
        merged: list[str] = []
        for keyword in [*(item.keywords or []), *hits, *(item.topics or [])]:
            cleaned = re.sub(r"\s+", " ", str(keyword or "")).strip()[:80]
            if cleaned and cleaned.casefold() not in {value.casefold() for value in merged}:
                merged.append(cleaned)
        return merged
