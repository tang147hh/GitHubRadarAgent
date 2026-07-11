from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.llm_service import LLMService
from src.models import NewsDigestArticle, NewsDigestSection, NewsEventCard, NewsEventResult
from src.news_collector import utc_now_iso
from src.news_scorer import CATEGORY_SECTION_MAP


SECTION_ORDER = [
    "今日大事件",
    "模型与产品",
    "开源与工具",
    "论文与研究",
    "开发者社区",
    "商业与监管",
    "值得继续跟进",
]

SECTION_LIMITS = {
    "今日大事件": 2,
    "模型与产品": 3,
    "开源与工具": 3,
    "论文与研究": 3,
    "开发者社区": 3,
    "商业与监管": 2,
    "值得继续跟进": 3,
}

FOLLOW_UP_SECTION = "值得继续跟进"


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_class: Any, payload: dict[str, Any]) -> Any:
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(payload)
    return model_class.parse_obj(payload)


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


def _clean_text(value: str, max_length: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip(" ，。；,.") + "..."


def _markdown_link(url: str) -> str:
    cleaned = str(url or "").strip()
    return cleaned if cleaned else "-"


class NewsDigestWriterService:
    """Write a Chinese AI news digest from merged event cards."""

    def __init__(
        self,
        workspace_dir: Path | None = None,
        output_dir: Path | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir
        self.llm = llm_service or LLMService(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )

    def load_latest_events(self) -> NewsEventResult:
        path = self.workspace_dir / "news" / "news_events_latest.json"
        if not path.exists():
            raise FileNotFoundError(
                "workspace/news/news_events_latest.json not found. Please run collect-news, score-news, and build-news-events first."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workspace/news/news_events_latest.json must contain a JSON object.")
        return _model_validate(NewsEventResult, payload)

    def write_latest(self, top: int = 12, date: str | None = None) -> NewsDigestArticle:
        return self.write_digest(self.load_latest_events(), top=top, date=date)

    def write_digest(self, events_result: NewsEventResult, top: int = 12, date: str | None = None) -> NewsDigestArticle:
        top = max(1, min(int(top or 12), 50))
        digest_date = (date or datetime.now().date().isoformat()).strip()
        selected = self._select_events(events_result, top=top)
        warnings = [*(events_result.warnings or [])]

        if not selected:
            warnings.append("No usable news events were found for digest writing.")
            article = self._fallback_article([], digest_date, warnings)
            self.save_article(article)
            return article

        article = self._write_with_llm(selected, digest_date, warnings)
        if article is None:
            article = self._fallback_article(selected, digest_date, warnings)

        selected_events = [event for section_events in selected.values() for event in section_events]
        article.event_count = len(selected_events)
        article.source_event_ids = [event.event_id for event in selected_events]
        article.source_urls = _unique([url for event in selected_events for url in [*(event.urls or []), event.primary_url]])
        article.sections = [section for section in SECTION_ORDER if selected.get(section)]
        article.section_details = [
            NewsDigestSection(
                section_name=section,
                event_ids=[event.event_id for event in selected[section]],
                summary=f"{section}收录 {len(selected[section])} 条事件。",
            )
            for section in article.sections
        ]
        article.date = digest_date
        missing_urls = [url for url in article.source_urls if url and url not in article.content_markdown]
        if missing_urls:
            article.content_markdown = self._append_missing_sources(article.content_markdown, missing_urls)
            article.warnings = _unique(
                [
                    *(article.warnings or []),
                    f"Digest omitted {len(missing_urls)} source URLs; appended them to the source list.",
                ]
            )
        article.word_count = self._word_count(article.content_markdown)
        article.quality_notes = self._quality_notes(article, selected)
        self.save_article(article)
        return article

    def save_article(self, article: NewsDigestArticle) -> None:
        generated_date = article.date or datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(article), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_digest_latest.json").write_text(payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news-digest.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_digest_latest.json").write_text(payload, encoding="utf-8")
        (output_date_dir / "ai_news_digest.md").write_text(article.content_markdown.rstrip() + "\n", encoding="utf-8")

    def _select_events(self, events_result: NewsEventResult, top: int) -> dict[str, list[NewsEventCard]]:
        candidates = [event for event in events_result.events if self._usable_event(event)]
        candidates.sort(
            key=lambda event: (
                1 if event.recommended_section != "暂不推荐" else 0,
                float(event.total_score or 0),
                float(event.source_count or 0),
                event.latest_published_at or event.published_at or "",
            ),
            reverse=True,
        )

        selected: dict[str, list[NewsEventCard]] = defaultdict(list)
        used_ids: set[str] = set()
        for event in candidates:
            if len(used_ids) >= top:
                break
            section = self._target_section(event)
            if not section:
                continue
            if len(selected[section]) >= SECTION_LIMITS.get(section, 3):
                section = FOLLOW_UP_SECTION
            if len(selected[section]) >= SECTION_LIMITS[FOLLOW_UP_SECTION]:
                continue
            event_id = event.event_id or event.primary_url
            if not event_id or event_id in used_ids:
                continue
            selected[section].append(event)
            used_ids.add(event_id)

        return {section: selected[section] for section in SECTION_ORDER if selected.get(section)}

    def _usable_event(self, event: NewsEventCard) -> bool:
        if not (event.event_title_zh or event.event_title):
            return False
        if not (event.primary_url or event.urls):
            return False
        if event.category == "noise" and event.recommended_section == "暂不推荐" and float(event.total_score or 0) < 55:
            return False
        return True

    def _target_section(self, event: NewsEventCard) -> str:
        if event.recommended_section and event.recommended_section != "暂不推荐":
            return event.recommended_section
        mapped = CATEGORY_SECTION_MAP.get(event.category, "")
        if mapped and mapped != "暂不推荐":
            return mapped
        if float(event.total_score or 0) >= 55:
            return FOLLOW_UP_SECTION
        return ""

    def _write_with_llm(
        self,
        selected: dict[str, list[NewsEventCard]],
        digest_date: str,
        warnings: list[str],
    ) -> NewsDigestArticle | None:
        event_payload = self._event_payload(selected)
        system_prompt = (
            "你是中文 AI 圈日报编辑，写作目标是适合公众号发布的新闻日报。"
            "语气信息密度高、口语适度、克制，不写报告腔，不标题党。"
            "只能依据给定事件卡写作；不要伪造数据、不要扩展没有证据的结论。"
            "社区讨论必须写成社区讨论或开发者反馈；论文只用提出、探索、展示等稳妥表达；商业和监管不做无依据判断。"
            "不要大段搬运原文摘要，不要使用“根据外媒报道”这类空泛套话。"
        )
        user_prompt = (
            f"请根据下面的 NewsEventCard，写一篇 {digest_date} 的中文《今日 AI 圈新闻日报》。\n"
            "要求：输出严格 JSON，不要 Markdown 代码围栏；字段为 title、subtitle、content_markdown、quality_notes。\n"
            "content_markdown 结构：# 标题；开头 2-3 段；按栏目用二级标题；每条新闻包含三级标题、1-2 段中文解读、原文链接；结尾包含“今日观察 / 值得继续关注”。\n"
            "每条新闻先说发生了什么，再说为什么值得关注，最后给原文链接。必须保留对应事件里的至少一个原文 URL。\n"
            "栏目为空就跳过，不要重复事件。\n\n"
            f"事件卡 JSON：\n{json.dumps(event_payload, ensure_ascii=False, indent=2)}"
        )
        content = self.llm.chat(system_prompt, user_prompt, temperature=0.45)
        if content.startswith(LLMService.WARNING_PREFIX):
            warnings.append(content.replace(LLMService.WARNING_PREFIX, "").strip())
            return None

        try:
            payload = self._parse_llm_json(content)
        except ValueError as exc:
            warnings.append(f"LLM digest JSON parse failed: {exc}")
            return None

        markdown = str(payload.get("content_markdown") or "").strip()
        if not markdown:
            warnings.append("LLM digest response did not include content_markdown.")
            return None

        return NewsDigestArticle(
            title=str(payload.get("title") or self._title_for_date(digest_date)).strip(),
            subtitle=str(payload.get("subtitle") or "从事件卡片整理出的今日 AI 圈重点。").strip(),
            date=digest_date,
            content_markdown=self._normalize_markdown(markdown, digest_date),
            generation_mode="llm",
            warnings=_unique(warnings),
            quality_notes=[str(item).strip() for item in payload.get("quality_notes", []) if str(item).strip()]
            if isinstance(payload.get("quality_notes"), list)
            else [],
        )

    def _fallback_article(
        self,
        selected: dict[str, list[NewsEventCard]] | list[Any],
        digest_date: str,
        warnings: list[str],
    ) -> NewsDigestArticle:
        grouped = selected if isinstance(selected, dict) else {}
        article_title = self._title_for_date(digest_date)
        subtitle = "从事件卡片整理出的简版 AI 圈日报。"
        lines = [
            f"# {article_title}",
            "",
            f"> {subtitle}",
            "",
            f"今天的 AI 新闻重点来自已经合并过的事件卡片。我们优先挑选推荐事件和高分事件，保留原文链接，只做中文梳理和简短解读。",
            "",
            "下面不是链接列表，而是一份适合继续编辑发布的日报底稿：每条先说明发生了什么，再说明为什么值得关注。",
            "",
        ]

        if not grouped:
            lines.extend(
                [
                    "## 值得继续跟进",
                    "",
                    "暂无可用于写作的事件卡片。请先完成新闻采集、评分和事件卡片构建。",
                    "",
                ]
            )

        for section in SECTION_ORDER:
            events = grouped.get(section, [])
            if not events:
                continue
            lines.extend([f"## {section}", ""])
            for event in events:
                event_title = event.event_title_zh or event.event_title or "未命名事件"
                summary = self._fallback_summary(event)
                attention = self._fallback_attention(event)
                lines.extend(
                    [
                        f"### {event_title}",
                        "",
                        summary,
                        "",
                        attention,
                        "",
                        f"原文链接：{_markdown_link(event.primary_url or (event.urls[0] if event.urls else ''))}",
                        "",
                    ]
                )

        lines.extend(
            [
                "## 今日观察 / 值得继续关注",
                "",
                self._closing_observation(grouped),
                "",
            ]
        )

        return NewsDigestArticle(
            title=article_title,
            subtitle=subtitle,
            date=digest_date,
            content_markdown="\n".join(lines).rstrip() + "\n",
            generation_mode="fallback",
            warnings=_unique(warnings),
            quality_notes=["LLM 不可用或输出不可解析，已使用模板生成简版日报。"],
        )

    def _fallback_summary(self, event: NewsEventCard) -> str:
        title = event.event_title_zh or event.event_title
        summary = _clean_text(event.event_summary_zh or event.event_summary or title, 220)
        if event.category == "community_discussion":
            return f"社区里正在讨论「{title}」。从事件卡片看，讨论焦点大致是：{summary}"
        if event.category == "research_paper":
            return f"这条研究动态围绕「{title}」展开。事件卡片显示，相关工作主要在提出、探索或展示新的方法与结果：{summary}"
        return f"这条消息的核心是「{title}」。从事件卡片看，主要变化可以概括为：{summary}"

    def _fallback_attention(self, event: NewsEventCard) -> str:
        reasons = "；".join((event.reasons or [])[:2])
        source_note = f"目前覆盖 {event.source_count or len(event.sources or []) or 1} 个来源"
        if event.category == "policy_regulation":
            return f"值得关注的是，它可能影响后续产品合规或行业预期，但现在只能以原始来源信息为准。{source_note}。{reasons}"
        if event.category == "funding_business":
            return f"值得关注的是，它反映了 AI 商业化和资本动作的一个新信号，但不宜据此推导超出来源的信息。{source_note}。{reasons}"
        if event.category == "research_paper":
            return f"值得关注的是，这类研究可能为模型、工具或评测方向提供新线索，但结论仍需要更多验证。{source_note}。{reasons}"
        if event.category == "community_discussion":
            return f"值得关注的是，开发者反馈往往能提前暴露真实使用场景里的痛点，不过它仍然是社区讨论，不等同于已确认事实。{source_note}。{reasons}"
        return f"值得关注的是，它和模型能力、产品体验或开发者工作流有关，后续是否落地还要继续看官方更新和用户反馈。{source_note}。{reasons}"

    def _closing_observation(self, grouped: dict[str, list[NewsEventCard]]) -> str:
        sections = [section for section in SECTION_ORDER if grouped.get(section)]
        if not sections:
            return "今天还没有足够可靠的事件卡片支撑日报写作。建议先补齐采集、评分和事件合并流程。"
        total = sum(len(events) for events in grouped.values())
        return f"今天共选入 {total} 条事件，重点集中在{'、'.join(sections[:4])}。后续可以继续跟进多来源验证、官方更新以及开发者真实反馈，避免只被单条新闻标题牵着走。"

    def _event_payload(self, selected: dict[str, list[NewsEventCard]]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for section in SECTION_ORDER:
            for event in selected.get(section, []):
                urls = _unique([*(event.urls or []), event.primary_url])
                payload.append(
                    {
                        "section": section,
                        "event_id": event.event_id,
                        "title": event.event_title_zh or event.event_title,
                        "original_title": event.event_title,
                        "summary": _clean_text(event.event_summary_zh or event.event_summary, 500),
                        "category": event.category,
                        "score": event.total_score,
                        "source_count": event.source_count,
                        "sources": event.sources[:6],
                        "urls": urls[:6],
                        "primary_url": event.primary_url,
                        "reasons": event.reasons[:5],
                        "warnings": event.warnings[:5],
                        "published_at": event.published_at,
                        "latest_published_at": event.latest_published_at,
                    }
                )
        return payload

    def _parse_llm_json(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("response did not contain a JSON object")
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("response JSON must be an object")
        return payload

    def _append_missing_sources(self, markdown: str, urls: list[str]) -> str:
        lines = [markdown.rstrip(), "", "### 补充原文链接", ""]
        lines.extend(f"- {url}" for url in urls)
        return "\n".join(lines).rstrip() + "\n"

    def _normalize_markdown(self, markdown: str, digest_date: str) -> str:
        cleaned = markdown.strip()
        if not cleaned.startswith("# "):
            cleaned = f"# {self._title_for_date(digest_date)}\n\n{cleaned}"
        return cleaned.rstrip() + "\n"

    def _quality_notes(self, article: NewsDigestArticle, selected: dict[str, list[NewsEventCard]]) -> list[str]:
        notes = list(article.quality_notes or [])
        markdown = article.content_markdown or ""
        urls = article.source_urls or []
        if urls and all(url in markdown for url in urls):
            notes.append("已保留所选事件的原文链接。")
        if not self._looks_like_large_english_copy(markdown):
            notes.append("未发现大段英文原文搬运。")
        if selected:
            notes.append("每个事件仅在一个栏目出现。")
        return _unique(notes)

    def _looks_like_large_english_copy(self, markdown: str) -> bool:
        paragraphs = [line.strip() for line in markdown.splitlines() if len(line.strip()) >= 180]
        for paragraph in paragraphs:
            letters = sum(1 for char in paragraph if char.isascii() and char.isalpha())
            chinese = sum(1 for char in paragraph if "\u4e00" <= char <= "\u9fff")
            if letters > chinese * 2 and letters > 120:
                return True
        return False

    def _word_count(self, markdown: str) -> int:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", markdown or ""))
        words = len(re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", markdown or ""))
        return chinese_chars + words

    def _title_for_date(self, digest_date: str) -> str:
        return f"{digest_date} 今日 AI 圈新闻日报"
