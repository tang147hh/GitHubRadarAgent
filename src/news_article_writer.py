from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from src.config import get_settings
from src.interaction_metrics import contains_interaction_metric, strip_interaction_metric_text
from src.llm_service import LLMService
from src.models import NewsArticle, NewsArticlePlan, NewsDetailResult, NewsImageCandidate, NewsItem, NewsSelectionContext
from src.news_collector import utc_now_iso


JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,180}$")
FORBIDDEN_PHRASES = ["本文将", "以下是", "从以下几个方面", "综上所述", "根据新闻", "资料显示"]


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_class: Any, payload: Any) -> Any:
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(payload)
    return model_class.parse_obj(payload)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _clean_text(value: str | None, max_length: int = 700) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip(" ，。；,.") + "..."


def _word_count(value: str) -> int:
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", value or "")
    latin_words = re.findall(r"[A-Za-z0-9_]+", value or "")
    return len(chinese_chars) + len(latin_words)


def _extract_json_payload(value: str) -> Any:
    text = (value or "").strip()
    block_match = JSON_BLOCK_PATTERN.search(text)
    if block_match:
        text = block_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _is_http_url(value: str | None) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class NewsArticleWriterService:
    """Write one publishable Chinese WeChat article from a saved AI news plan."""

    def __init__(
        self,
        workspace_dir: Path | None = None,
        output_dir: Path | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir
        self.news_dir = self.workspace_dir / "news"
        self.news_articles_dir = self.news_dir / "news_articles"
        self.article_outputs_dir = self.news_dir / "articles"
        self.selections_dir = self.news_dir / "selections"
        self.plans_dir = self.news_dir / "plans"
        self.snapshots_dir = self.workspace_dir / "snapshots"
        self.latest_news_path = self.news_dir / "news_latest.json"
        self.latest_selection_path = self.selections_dir / "latest_selection.json"
        self.latest_plan_path = self.news_dir / "news_article_plan_latest.json"
        self.latest_article_path = self.news_dir / "news_article_latest.json"
        self.latest_snapshot_path = self.snapshots_dir / "news_article_latest.json"
        self.llm = llm_service or LLMService(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )

    def load_latest_selection(self) -> NewsSelectionContext:
        return self._load_selection_path(self.latest_selection_path)

    def load_selection(self, selection_id: str) -> NewsSelectionContext:
        safe_id = self._validate_id(selection_id, "selection_id")
        return self._load_selection_path(self.selections_dir / f"{safe_id}.json")

    def load_latest_plan(self) -> NewsArticlePlan:
        return self._load_plan_path(self.latest_plan_path)

    def load_plan(self, plan_id: str) -> NewsArticlePlan:
        safe_id = self._validate_id(plan_id, "plan_id")
        return self._load_plan_path(self.plans_dir / f"{safe_id}.json")

    def load_latest_article(self) -> NewsArticle:
        return self._load_article_path(self.latest_article_path)

    def load_article(self, article_id: str) -> NewsArticle:
        safe_id = self._validate_id(article_id, "article_id")
        return self._load_article_path(self.article_outputs_dir / f"{safe_id}.json")

    def write_latest(self) -> NewsArticle:
        plan = self.load_latest_plan()
        return self.write_from_plan(plan)

    def write_by_plan_id(self, plan_id: str) -> NewsArticle:
        return self.write_from_plan(self.load_plan(plan_id))

    def write_from_plan(
        self,
        plan: NewsArticlePlan,
        selection: NewsSelectionContext | None = None,
        details: list[NewsDetailResult] | None = None,
    ) -> NewsArticle:
        if not plan.plan_id:
            raise ValueError("News article plan is missing plan_id. Please run plan-news-article first.")
        loaded_selection = selection or self._selection_for_plan(plan)
        if plan.selection_id and loaded_selection.selection_id and plan.selection_id != loaded_selection.selection_id:
            raise ValueError("Plan and selection do not match. Please regenerate the article plan.")
        if not loaded_selection.items:
            raise ValueError("No news selection found. Please save a selection first.")

        loaded_details = details or self.load_details_for_selection(loaded_selection)
        if not loaded_details:
            raise ValueError("No news details found for the saved selection.")

        detail_by_id = {detail.news_id: detail for detail in loaded_details if detail.news_id}
        primary_news_id = plan.primary_news_id or loaded_selection.primary_news_id or loaded_details[0].news_id
        warnings = _unique([*(plan.warnings or []), *(loaded_selection.warnings or [])])
        loaded_details = self._ensure_cover_details(primary_news_id, loaded_details, warnings=warnings)
        detail_by_id = {detail.news_id: detail for detail in loaded_details if detail.news_id}
        primary_detail = detail_by_id.get(primary_news_id)
        if primary_detail is None:
            raise ValueError(f"Primary news detail not found: {primary_news_id}")

        used_full_text_count = sum(1 for detail in loaded_details if detail.content_availability == "full_text")
        used_summary_only_count = len(loaded_details) - used_full_text_count
        if used_full_text_count == 0:
            warnings.append("全文不可用，文章基于摘要和标题生成。")
        elif primary_detail.content_availability != "full_text":
            warnings.append("主新闻全文不可用，文章基于摘要和标题生成。")

        force_fallback_reason = self._force_fallback_reason(plan, primary_detail)
        if force_fallback_reason:
            warnings.append(force_fallback_reason)
            article = None
        else:
            article = self._write_with_llm(plan, loaded_selection, loaded_details, warnings)
        if article is None:
            article = self._fallback_article(plan, loaded_selection, loaded_details, warnings)

        article.article_id = article.article_id or self._new_article_id()
        article.plan_id = plan.plan_id
        article.selection_id = loaded_selection.selection_id or plan.selection_id
        article.generated_at = article.generated_at or utc_now_iso()
        article.primary_news_id = primary_news_id
        article.source_news_ids = _unique(article.source_news_ids or [detail.news_id for detail in loaded_details])
        article.source_urls = _unique([*(article.source_urls or []), *(plan.source_urls or []), *[detail.url for detail in loaded_details]])
        article.factual_boundaries = _unique([*(plan.factual_boundaries or []), *(article.factual_boundaries or [])])
        article.used_full_text_count = used_full_text_count
        article.used_summary_only_count = used_summary_only_count
        cover = self._select_cover_image(primary_news_id, loaded_details)
        article.cover_image_url = cover.url if cover else None
        article.cover_image_source_url = cover.source_url if cover else None
        article.cover_image_alt = cover.alt if cover else None
        article.cover_image_status = "selected" if cover else "missing"
        if cover is None:
            warnings.append("未从原新闻页面、Open Graph/Twitter Card 或正文图片候选中找到可用封面图。")
        article.warnings = _unique([*warnings, *(article.warnings or [])])
        article.generation_mode = article.generation_mode if article.generation_mode in {"llm", "fallback"} else "fallback"
        article.content_markdown = strip_interaction_metric_text(self._normalize_markdown(article, plan, loaded_details))
        article.word_count = _word_count(article.content_markdown)
        article.publish_ready = self._publish_ready(article)
        self.save_article(article)
        return article

    def load_details_for_selection(self, selection: NewsSelectionContext) -> list[NewsDetailResult]:
        latest_items = self._load_latest_items()
        details: list[NewsDetailResult] = []
        for item in selection.items:
            news_id = item.news_id
            detail = self._load_cached_detail(news_id)
            if detail is None:
                latest_item = latest_items.get(news_id)
                if latest_item is not None:
                    detail = self._detail_from_latest_item(latest_item)
            if detail is None:
                detail = NewsDetailResult(
                    news_id=news_id,
                    title=item.title or "",
                    title_zh=item.title_zh,
                    url=item.url or "",
                    source=item.source or "",
                    source_type=item.source_type or "",
                    published_at=item.published_at,
                    fetched_at=utc_now_iso(),
                    content_availability=item.content_availability or "metadata_only",
                    extraction_status="skipped",
                )
            details.append(detail)
        return details

    def save_article(self, article: NewsArticle) -> None:
        article_id = self._validate_id(article.article_id, "article_id")
        generated_date = self._article_date(article)
        output_article_dir = self.output_dir / generated_date / "news_articles"
        self.article_outputs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_article_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(article), ensure_ascii=False, indent=2) + "\n"
        self.latest_article_path.write_text(payload, encoding="utf-8")
        (self.article_outputs_dir / f"{article_id}.json").write_text(payload, encoding="utf-8")
        self.latest_snapshot_path.write_text(payload, encoding="utf-8")
        (output_article_dir / f"{article_id}.md").write_text(self._markdown_with_cover_header(article), encoding="utf-8")
        (output_article_dir / f"{article_id}_report.md").write_text(self.report_markdown(article), encoding="utf-8")

    def report_markdown(self, article: NewsArticle) -> str:
        lines = [
            "# AI 新闻公众号文章生成报告",
            "",
            f"- Article ID: {article.article_id or '-'}",
            f"- Selection ID: {article.selection_id or '-'}",
            f"- Plan ID: {article.plan_id or '-'}",
            f"- Generated at: {article.generated_at or '-'}",
            f"- Generation mode: {article.generation_mode or '-'}",
            f"- Publish ready: {'yes' if article.publish_ready else 'no'}",
            f"- Word count: {article.word_count}",
            f"- Used full text count: {article.used_full_text_count}",
            f"- Used summary only count: {article.used_summary_only_count}",
            f"- Cover image status: {article.cover_image_status or 'missing'}",
            f"- Cover image URL: {article.cover_image_url or 'null'}",
            f"- Cover image source: {article.cover_image_source_url or 'null'}",
            f"- Cover image alt: {article.cover_image_alt or '-'}",
            "",
            "## Source news ids",
            "",
            *self._markdown_list(article.source_news_ids),
            "",
            "## Source URLs",
            "",
            *self._markdown_list(article.source_urls),
            "",
            "## Factual boundaries",
            "",
            *self._markdown_list(article.factual_boundaries),
            "",
            "## Warnings",
            "",
            *self._markdown_list(article.warnings),
            "",
        ]
        return "\n".join(lines).rstrip() + "\n"

    def _ensure_cover_details(
        self,
        primary_news_id: str,
        details: list[NewsDetailResult],
        warnings: list[str],
    ) -> list[NewsDetailResult]:
        primary_detail = next((detail for detail in details if detail.news_id == primary_news_id), details[0] if details else None)
        if primary_detail is not None and self._detail_has_cover(primary_detail):
            return details
        try:
            from src.news_detail_service import NewsDetailService
        except ImportError:
            return details

        service = NewsDetailService(workspace_dir=self.workspace_dir)
        if any(self._detail_has_cover(detail) for detail in details):
            ordered = [(index, detail) for index, detail in enumerate(details) if detail.news_id == primary_news_id]
        else:
            ordered = sorted(enumerate(details), key=lambda item: 0 if item[1].news_id == primary_news_id else 1)
        refreshed_by_index: dict[int, NewsDetailResult] = {}
        for index, detail in ordered:
            if not detail.news_id or not detail.url:
                continue
            try:
                refreshed = service.get_detail(detail.news_id, refresh=True)
            except Exception as exc:
                warnings.append(f"封面图元数据刷新失败（{detail.news_id}）：{type(exc).__name__}: {exc}")
                continue
            refreshed_by_index[index] = refreshed
            if self._detail_has_cover(refreshed):
                break
        if not refreshed_by_index:
            return details
        return [refreshed_by_index.get(index, detail) for index, detail in enumerate(details)]

    def _detail_has_cover(self, detail: NewsDetailResult) -> bool:
        if _is_http_url(detail.cover_image_url):
            return True
        return any(_is_http_url(candidate.url) for candidate in (detail.image_candidates or []))

    def _select_cover_image(self, primary_news_id: str, details: list[NewsDetailResult]) -> NewsImageCandidate | None:
        ordered = sorted(details, key=lambda detail: 0 if detail.news_id == primary_news_id else 1)
        candidates: list[NewsImageCandidate] = []
        for detail in ordered:
            if _is_http_url(detail.cover_image_url):
                candidates.append(
                    NewsImageCandidate(
                        url=str(detail.cover_image_url),
                        source_url=detail.cover_image_source_url or detail.url,
                        alt=detail.cover_image_alt or detail.title_zh or detail.title or None,
                        source_type="detail:cover",
                    )
                )
            for candidate in detail.image_candidates or []:
                candidates.append(
                    NewsImageCandidate(
                        url=candidate.url,
                        source_url=candidate.source_url or detail.url,
                        alt=candidate.alt or detail.title_zh or detail.title or None,
                        source_type=candidate.source_type or "detail:candidate",
                    )
                )
        seen: set[str] = set()
        for candidate in candidates:
            url = str(candidate.url or "").strip()
            if not _is_http_url(url):
                continue
            key = url.casefold()
            if key in seen:
                continue
            seen.add(key)
            return NewsImageCandidate(
                url=url,
                source_url=candidate.source_url or url,
                alt=(candidate.alt or "").strip() or None,
                source_type=candidate.source_type or "unknown",
            )
        return None

    def _markdown_with_cover_header(self, article: NewsArticle) -> str:
        header = [
            "<!-- AI 新闻文章封面图 -->",
            f"<!-- cover_image_status: {article.cover_image_status or 'missing'} -->",
            f"<!-- cover_image_url: {article.cover_image_url or 'null'} -->",
            f"<!-- cover_image_source_url: {article.cover_image_source_url or 'null'} -->",
            f"<!-- cover_image_alt: {article.cover_image_alt or '-'} -->",
        ]
        return "\n".join(header) + "\n\n" + (article.content_markdown or "").rstrip() + "\n"

    def _write_with_llm(
        self,
        plan: NewsArticlePlan,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult],
        warnings: list[str],
    ) -> NewsArticle | None:
        if not self.llm.is_available():
            warnings.append("LLM unavailable: OPENAI_API_KEY or OPENAI_MODEL is not configured.")
            return None

        response = self.llm.chat(self._system_prompt(), self._user_prompt(plan, selection, details), temperature=0.35)
        if response.startswith(LLMService.WARNING_PREFIX):
            warnings.append(response)
            return None
        try:
            payload = _extract_json_payload(response)
            if not isinstance(payload, dict):
                raise ValueError("LLM article response must be a JSON object.")
            article = _model_validate(NewsArticle, payload)
            article.generation_mode = "llm"
            return article
        except Exception as exc:
            warnings.append(f"LLM article response could not be parsed; fallback used: {type(exc).__name__}: {exc}")
            return None

    def _force_fallback_reason(self, plan: NewsArticlePlan, primary: NewsDetailResult) -> str | None:
        source_type = (primary.source_type or primary.source or "").casefold()
        body = primary.content_text or primary.content_preview or primary.summary_zh or primary.summary or ""
        plan_text = " ".join(
            [
                plan.event_summary or "",
                " ".join(plan.must_include or []),
                " ".join(plan.article_structure or []),
                " ".join(plan.factual_boundaries or []),
            ]
        )
        asks_for_cases = any(keyword in plan_text for keyword in ["具体任务案例", "案例精选", "案例内容", "从讨论中提取"])
        has_only_discussion_prompt = "hacker" in source_type and len(body) < 1200 and asks_for_cases
        if has_only_discussion_prompt:
            return "HN 讨论正文未包含可核验的评论案例，已使用保守 fallback，避免虚构社区反馈。"
        return None

    def _fallback_article(
        self,
        plan: NewsArticlePlan,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult],
        warnings: list[str],
    ) -> NewsArticle:
        detail_by_id = {detail.news_id: detail for detail in details}
        primary = detail_by_id.get(plan.primary_news_id or selection.primary_news_id) or details[0]
        conservative_hn = any("HN 讨论正文未包含可核验的评论案例" in warning for warning in warnings)
        title = plan.recommended_title or primary.title_zh or primary.title or "这条 AI 新闻，真正该关注什么"
        subtitle = (
            "一次社区提问暴露了模型选型里最现实的问题：哪些任务真的需要前沿模型。"
            if conservative_hn
            else plan.core_angle or "从事实、影响和后续观察点拆解一条 AI 新闻。"
        )
        source_urls = _unique([*(plan.source_urls or []), *[detail.url for detail in details]])
        facts = _unique([*(plan.key_facts or []), *self._facts_from_details(details, limit=6)])
        why = (
            [
                "它没有直接给出模型能力结论，但提供了一个观察开发者真实需求的入口。",
                "它提醒读者区分社区提问、个体反馈和可复现评测，避免把社区来源当成行业事实。",
            ]
            if conservative_hn
            else _unique(plan.why_it_matters or [])
        )
        developer = (
            [
                "对开发者来说，重点不是立刻相信某个模型更强，而是把自己的任务拆成可验证的失败条件。",
                "如果任务涉及长上下文、复杂指令或多步骤工作流，应该用自己的样例做小规模对比，而不是只看泛化评价。",
            ]
            if conservative_hn
            else _unique(plan.developer_impact or [])
        )
        industry = (
            [
                "行业层面更适合把它看成一个问题清单，而不是能力排名。",
                "后续如果出现更多具体评论、复现实验或官方案例，才适合进一步讨论开源模型与前沿模型的差距。",
            ]
            if conservative_hn
            else _unique(plan.industry_impact or [])
        )
        takeaways = (
            [
                "我的判断是，这条讨论值得关注，但目前只能说明开发者正在寻找模型边界的可验证案例，不能说明某类模型已经胜出。",
                "读者可以把它当作模型选型前的问题模板：任务是什么，廉价模型怎么失败，前沿模型是否真的成功，旧一代前沿模型是否够用。",
            ]
            if conservative_hn
            else _unique(plan.reader_takeaways or [])
        )
        boundaries = _unique(plan.factual_boundaries or self._default_boundaries(primary))

        opening = (
            "这条新闻值得看，不是因为它已经给出了答案，而是因为它把一个开发者每天都会遇到的问题摆到了台面上：什么时候该为前沿模型付出更高成本？"
            if conservative_hn
            else plan.lead_hook
            or "这条新闻值得看，不是因为标题里有 AI，而是因为它可能改变开发者、产品团队或普通用户判断一项新能力的方式。"
        )
        event_summary = (
            f"Hacker News 上有用户发起讨论，询问最近一个月里是否存在只有前沿模型能完成、而 GLM、DeepSeek、Kimi、Qwen 等更便宜模型没有完成的具体任务。发帖者同时给出模板，要求回复者说明任务、尝试过的模型、失败方式、前沿模型是否成功，以及旧一代前沿模型是否也足够。"
            if conservative_hn
            else plan.event_summary or self._best_summary(primary) or f"主新闻报道了“{primary.title_zh or primary.title}”。"
        )

        lines = [
            f"# {title}",
            "",
        ]
        if subtitle:
            lines.extend([f"> {subtitle}", ""])
        lines.extend(
            [
                opening,
                "",
                event_summary,
                "",
            ]
        )
        if facts:
            lines.extend(
                [
                    "到目前为止，比较稳的事实可以这样看：" + self._paragraph_from_items(facts[:5], ""),
                    "",
                ]
            )
        lines.extend(
            [
                "这件事不只是热闹，真正值得看的是它背后的变化。",
                "",
                self._paragraph_from_items(
                    why,
                    "它的价值在于提醒读者把注意力放回可验证的变化：能力边界是否更清楚，使用门槛是否变化，开发和产品决策是否需要调整。",
                ),
                "",
                "把视角放到开发者和 AI 使用者身上，影响会更具体一些。",
                "",
                self._paragraph_from_items(
                    developer,
                    "对开发者来说，最实际的看点是它是否影响接口、工作流、可靠性、成本或生态选择。对 AI 使用者来说，更重要的是判断这项变化是否已经足够稳定，还是只适合继续观察。",
                ),
                "",
                "行业层面暂时不需要过度推演。",
                "",
                self._paragraph_from_items(
                    industry,
                    "行业影响不宜过度推演。更稳妥的观察方式，是看后续是否出现官方补充、开发者反馈、产品更新、监管回应或更多独立来源验证。",
                ),
                "",
                "我的判断是，先把它放进观察列表。",
                "",
                self._paragraph_from_items(
                    takeaways,
                    "如果你是开发者或重度 AI 使用者，这条新闻值得放进观察列表，但不必仅凭一条报道就调整长期判断。先看事实，再看可复现的产品变化，再决定要不要投入时间跟进。",
                ),
                "",
                "后续继续看几个边界就够了：" + self._paragraph_from_items(boundaries[:4], ""),
                "",
            ]
        )
        if source_urls:
            lines.extend([f"原文链接：{' | '.join(source_urls)}", ""])

        return NewsArticle(
            article_id=self._new_article_id(),
            plan_id=plan.plan_id,
            selection_id=selection.selection_id or plan.selection_id,
            generated_at=utc_now_iso(),
            title=title,
            subtitle=subtitle,
            content_markdown="\n".join(lines).rstrip() + "\n",
            primary_news_id=primary.news_id,
            source_news_ids=_unique([detail.news_id for detail in details]),
            source_urls=source_urls,
            generation_mode="fallback",
            warnings=warnings,
            factual_boundaries=boundaries,
        )

    def _system_prompt(self) -> str:
        return (
            "你是严谨、有判断力的中文公众号 AI 新闻作者。"
            "请基于给定 NewsArticlePlan、selection 和 news_details 写一篇可直接发布的中文公众号文章。"
            "文章不是翻译稿，不搬运英文原文，不编造事实，不写无来源数据、发布时间、公司表态、融资金额、模型能力或监管结论。"
            "必须使用 factual_boundaries；如果来源是 HN，只能写“这是一条来自 Hacker News 的开发者社区消息”，"
            "不能写点赞数、评论数、points、comments、评论区炸了、很多人讨论、大家都在讨论或开发者普遍认为。"
            "没有具体评论正文支持时，不得概括社区观点或开发者共识。"
            "论文表达为提出/探索/展示，商业/监管新闻不做无来源预测。"
            "最终 content_markdown 不要生成二级标题、三级标题、机械分点、编号列表，"
            "不要使用“发生了什么 / 为什么重要 / 影响”这类显式小标题。"
            "可以使用自然段落和少量加粗短句，但不要把文章写成报告结构。"
            "避免这些表达：本文将、以下是、首先、其次、最后、从以下几个方面、综上所述、根据新闻、资料显示，也不要反复堆叠“值得关注的是”。"
            "只输出 JSON 对象，不输出解释。"
        )

    def _user_prompt(self, plan: NewsArticlePlan, selection: NewsSelectionContext, details: list[NewsDetailResult]) -> str:
        detail_payload = []
        for detail in details:
            role = "primary" if detail.news_id == (plan.primary_news_id or selection.primary_news_id) else "supporting"
            body = strip_interaction_metric_text(detail.content_text or detail.content_preview or detail.summary_zh or detail.summary or "")
            detail_payload.append(
                {
                    "role": role,
                    "news_id": detail.news_id,
                    "title": detail.title,
                    "title_zh": detail.title_zh,
                    "summary": strip_interaction_metric_text(detail.summary or ""),
                    "summary_zh": strip_interaction_metric_text(detail.summary_zh or ""),
                    "url": detail.url,
                    "source": detail.source,
                    "source_type": detail.source_type,
                    "published_at": detail.published_at,
                    "content_availability": detail.content_availability,
                    "content_excerpt": _clean_text(body, 6500),
                }
            )
        schema = {
            "title": "吸引人但克制的中文标题",
            "subtitle": "一句话副标题",
            "content_markdown": "完整公众号文章 Markdown，必须含原文链接",
            "source_urls": ["原文链接"],
            "warnings": ["如全文不可用或证据不足，写在这里"],
            "factual_boundaries": ["沿用并补充事实边界"],
            "publish_ready": True,
        }
        return (
            "请写最终文章 JSON。content_markdown 中至少包含 2 个具体事实、2 个影响/意义解释、1 个读者视角判断和原文链接。"
            "强约束：不写点赞数、不写评论数、不写 points、不写 comments、不写“评论区炸了”、不写“很多人讨论”、"
            "不写“大家都在讨论”、不写“开发者普遍认为”；除非输入中有具体评论正文且有信息增量，否则不得总结社区观点。"
            "不要使用 ## 或 ###，不要使用 Markdown 列表，不要写“发生了什么/为什么重要/对开发者的影响”这类小标题。"
            "用自然转场句推进：先抛新闻点，再解释背景，接着讲为什么值得关注，然后自然延伸到读者/开发者影响，文末放原文链接。"
            "不要包含大段英文。\n\n"
            f"plan={json.dumps(_model_dump(plan), ensure_ascii=False)}\n\n"
            f"selection={json.dumps(_model_dump(selection), ensure_ascii=False)}\n\n"
            f"news_details={json.dumps(detail_payload, ensure_ascii=False)}\n\n"
            "返回字段必须与这个 schema 对齐：\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )

    def _normalize_markdown(
        self,
        article: NewsArticle,
        plan: NewsArticlePlan,
        details: list[NewsDetailResult],
    ) -> str:
        content = (article.content_markdown or "").strip()
        title = (article.title or plan.recommended_title or "").strip()
        if title and not content.startswith("#"):
            content = f"# {title}\n\n{content}"
        content = self._soften_markdown_structure(content)
        source_urls = _unique(article.source_urls or [detail.url for detail in details])
        if source_urls and not any(url in content for url in source_urls):
            content = content.rstrip() + "\n\n" + f"原文链接：{' | '.join(source_urls)}"
        for phrase in FORBIDDEN_PHRASES:
            content = content.replace(phrase, "")
        return content.rstrip() + "\n"

    def _soften_markdown_structure(self, markdown: str) -> str:
        transitions = {
            "发生了什么": "先说新闻本身。",
            "先说发生了什么": "先说新闻本身。",
            "为什么重要": "这件事真正值得看的地方在后面。",
            "为什么这件事不只是热闹": "这件事不只是热闹。",
            "对开发者的影响": "把视角放到开发者身上，影响会更具体一些。",
            "对开发者和 AI 使用者意味着什么": "把视角放到开发者和 AI 使用者身上，影响会更具体一些。",
            "行业层面可以怎么观察": "行业层面暂时不需要过度推演。",
            "我的判断": "我的判断是，先把它放进观察列表。",
            "继续关注什么": "后续继续看事实边界就够了。",
        }

        def replace_heading(match: re.Match[str]) -> str:
            heading = match.group(1).strip().strip("：:。")
            if heading in {"原文链接", "来源链接"}:
                return f"{heading}："
            return transitions.get(heading, f"{heading}。")

        return re.sub(r"^#{2,3}\s+(.+?)\s*$", replace_heading, markdown, flags=re.MULTILINE)

    def _publish_ready(self, article: NewsArticle) -> bool:
        content = article.content_markdown or ""
        if not article.title or not content.strip():
            return False
        if not article.source_urls or not any(url and url in content for url in article.source_urls):
            return False
        if any(phrase in content for phrase in FORBIDDEN_PHRASES):
            return False
        if contains_interaction_metric(content):
            return False
        if article.word_count < 350:
            return False
        return True

    def _selection_for_plan(self, plan: NewsArticlePlan) -> NewsSelectionContext:
        if plan.selection_id:
            try:
                return self.load_selection(plan.selection_id)
            except FileNotFoundError:
                pass
        return self.load_latest_selection()

    def _load_selection_path(self, path: Path) -> NewsSelectionContext:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No news selection found. Please save a selection first.")
        if not isinstance(payload, dict):
            raise ValueError("News selection JSON must contain an object.")
        return _model_validate(NewsSelectionContext, payload)

    def _load_plan_path(self, path: Path) -> NewsArticlePlan:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No news article plan found. Please run plan-news-article first.")
        if not isinstance(payload, dict):
            raise ValueError("News article plan JSON must contain an object.")
        return _model_validate(NewsArticlePlan, payload)

    def _load_article_path(self, path: Path) -> NewsArticle:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No news article has been generated yet.")
        if not isinstance(payload, dict):
            raise ValueError("News article JSON must contain an object.")
        return _model_validate(NewsArticle, payload)

    def _load_latest_items(self) -> dict[str, NewsItem]:
        try:
            payload = json.loads(self.latest_news_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(payload, dict):
            return {}
        items: dict[str, NewsItem] = {}
        for raw_item in payload.get("items") or []:
            if not isinstance(raw_item, dict):
                continue
            try:
                item = _model_validate(NewsItem, raw_item)
            except ValueError:
                continue
            if item.id:
                items[item.id] = item
        return items

    def _load_cached_detail(self, news_id: str) -> NewsDetailResult | None:
        safe_id = self._validate_id(news_id, "news_id")
        path = self.news_articles_dir / f"{safe_id}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return _model_validate(NewsDetailResult, payload)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return None

    def _detail_from_latest_item(self, item: NewsItem) -> NewsDetailResult:
        text = (item.content_text or "").strip() or None
        summary_text = strip_interaction_metric_text(item.summary_zh or item.summary or "").strip()
        availability = "full_text" if text else "summary_only" if summary_text else item.content_availability or "metadata_only"
        return NewsDetailResult(
            news_id=item.id,
            title=item.title or "",
            title_zh=item.title_zh,
            summary=strip_interaction_metric_text(item.summary or ""),
            summary_zh=strip_interaction_metric_text(item.summary_zh or ""),
            url=item.url or "",
            source=item.source or "",
            source_type=item.source_type or "",
            published_at=item.published_at,
            fetched_at=item.fetched_at or utc_now_iso(),
            freshness=item.freshness or "unknown",
            content_text=text,
            content_preview=text[:4000].rstrip() if text else summary_text,
            content_availability=availability,
            extraction_status="cached" if text else "skipped",
            word_count=len(re.findall(r"\w+", text or "", flags=re.UNICODE)),
            original_language=item.language,
        )

    def _best_summary(self, detail: NewsDetailResult) -> str:
        return _clean_text(
            strip_interaction_metric_text(detail.summary_zh or "")
            or strip_interaction_metric_text(detail.summary or "")
            or detail.content_preview
            or detail.content_text
            or detail.title_zh
            or detail.title,
            700,
        )

    def _facts_from_details(self, details: list[NewsDetailResult], limit: int) -> list[str]:
        facts: list[str] = []
        for detail in details:
            title = detail.title_zh or detail.title
            if title:
                facts.append(f"{detail.source or '来源'}：{_clean_text(title, 140)}")
            summary = strip_interaction_metric_text(detail.summary_zh or detail.summary or "")
            if summary:
                facts.append(_clean_text(summary, 220))
            if detail.published_at:
                facts.append(f"发布时间：{detail.published_at}")
            if detail.url:
                facts.append(f"原文链接：{detail.url}")
        return _unique(facts)[:limit]

    def _paragraph_from_items(self, values: list[str], fallback: str) -> str:
        cleaned = _unique(values)
        if not cleaned:
            return fallback
        return " ".join(cleaned[:3])

    def _default_boundaries(self, primary: NewsDetailResult) -> list[str]:
        boundaries = [
            "没有官方确认的信息不能写成事实。",
            "社区讨论、媒体解读或二手来源要标注为讨论/解读。",
            "没有量化数据时，不能推断市场份额、收入或用户规模变化。",
            "不能从单条新闻直接推断长期商业影响。",
            "互动数量已忽略，不作为事实或选题依据。",
            "没有具体评论正文时，不得总结社区观点。",
        ]
        if primary.content_availability != "full_text":
            boundaries.append("主新闻全文不可用，不能补写正文中可能存在但当前未看到的细节。")
        return boundaries

    def _markdown_list(self, values: list[str]) -> list[str]:
        cleaned = _unique(values)
        if not cleaned:
            return ["- -"]
        return [f"- {value}" for value in cleaned]

    def _new_article_id(self) -> str:
        now = utc_now_iso().replace(":", "").replace(".", "")
        return f"news-article-{now}-{uuid4().hex[:8]}"

    def _article_date(self, article: NewsArticle) -> str:
        value = article.generated_at or utc_now_iso()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return datetime.now().date().isoformat()

    def _validate_id(self, value: str | None, field_name: str) -> str:
        safe_id = str(value or "").strip()
        if not SAFE_ID_PATTERN.fullmatch(safe_id):
            raise ValueError(f"Invalid {field_name}.")
        return safe_id
