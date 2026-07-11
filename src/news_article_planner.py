from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.config import get_settings
from src.llm_service import LLMService
from src.models import NewsArticlePlan, NewsDetailResult, NewsItem, NewsSelectionContext
from src.news_collector import utc_now_iso


JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
SAFE_PLAN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,180}$")


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


def _clean_text(value: str | None, max_length: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip(" ，。；,.") + "..."


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


class NewsArticlePlannerService:
    """Plan one WeChat article from a saved AI news selection."""

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
        self.articles_dir = self.news_dir / "news_articles"
        self.selections_dir = self.news_dir / "selections"
        self.plans_dir = self.news_dir / "plans"
        self.snapshots_dir = self.workspace_dir / "snapshots"
        self.latest_news_path = self.news_dir / "news_latest.json"
        self.latest_selection_path = self.selections_dir / "latest_selection.json"
        self.latest_plan_path = self.news_dir / "news_article_plan_latest.json"
        self.latest_snapshot_path = self.snapshots_dir / "news_article_plan_latest.json"
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

    def plan_latest(self) -> NewsArticlePlan:
        return self.plan_from_selection(self.load_latest_selection())

    def plan_by_selection_id(self, selection_id: str) -> NewsArticlePlan:
        return self.plan_from_selection(self.load_selection(selection_id))

    def plan_from_selection(
        self,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult] | None = None,
    ) -> NewsArticlePlan:
        if not selection.items:
            raise ValueError("No news selection found. Please save a selection first.")
        if not selection.primary_news_id:
            selection.primary_news_id = selection.items[0].news_id

        loaded_details = details or self.load_details_for_selection(selection)
        detail_by_id = {detail.news_id: detail for detail in loaded_details if detail.news_id}
        primary_detail = detail_by_id.get(selection.primary_news_id)
        if primary_detail is None:
            raise ValueError(f"Primary news detail not found: {selection.primary_news_id}")

        warnings = _unique([*(selection.warnings or [])])
        if primary_detail.content_availability != "full_text":
            warnings.append("主新闻全文不可用，策划基于摘要和标题。")

        plan = self._plan_with_llm(selection, loaded_details, warnings)
        if plan is None:
            plan = self._fallback_plan(selection, loaded_details, warnings)

        plan.plan_id = plan.plan_id or self._new_plan_id()
        plan.selection_id = selection.selection_id
        plan.generated_at = plan.generated_at or utc_now_iso()
        plan.primary_news_id = selection.primary_news_id
        plan.source_urls = _unique(plan.source_urls or [detail.url for detail in loaded_details])
        plan.should_avoid = _unique(
            [
                *(plan.should_avoid or []),
                "不要搬运原文或大段英文原文。",
                "不要写没有来源支撑的判断。",
                "不要夸大技术、商业或监管影响。",
                "不要使用空泛的 AI 报告腔。",
            ]
        )
        plan.factual_boundaries = _unique(plan.factual_boundaries or self._default_boundaries(primary_detail))
        plan.warnings = _unique([*warnings, *(plan.warnings or [])])
        plan.generation_mode = plan.generation_mode if plan.generation_mode in {"llm", "fallback"} else "fallback"
        self.save_plan(plan)
        return plan

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

    def save_plan(self, plan: NewsArticlePlan) -> None:
        plan_id = self._validate_id(plan.plan_id, "plan_id")
        generated_date = self._plan_date(plan)
        output_date_dir = self.output_dir / generated_date
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(plan), ensure_ascii=False, indent=2) + "\n"
        self.latest_plan_path.write_text(payload, encoding="utf-8")
        (self.plans_dir / f"{plan_id}.json").write_text(payload, encoding="utf-8")
        self.latest_snapshot_path.write_text(payload, encoding="utf-8")
        (output_date_dir / "news_article_plan.md").write_text(self.to_markdown(plan), encoding="utf-8")

    def to_markdown(self, plan: NewsArticlePlan) -> str:
        lines = [
            "# AI 新闻文章策划",
            "",
            f"- Plan ID: {plan.plan_id or '-'}",
            f"- Selection ID: {plan.selection_id or '-'}",
            f"- Primary News ID: {plan.primary_news_id or '-'}",
            f"- Generated at: {plan.generated_at or '-'}",
            f"- Generation mode: {plan.generation_mode or '-'}",
            "",
            f"## 推荐标题",
            "",
            plan.recommended_title or "-",
            "",
            "## 标题候选",
            "",
            *self._markdown_list(plan.title_candidates),
            "",
            "## 核心角度",
            "",
            plan.core_angle or "-",
            "",
            "## 开头钩子",
            "",
            plan.lead_hook or "-",
            "",
            "## 事件摘要",
            "",
            plan.event_summary or "-",
            "",
        ]
        sections = [
            ("关键事实", plan.key_facts),
            ("背景信息", plan.background_context),
            ("为什么重要", plan.why_it_matters),
            ("读者收获", plan.reader_takeaways),
            ("开发者影响", plan.developer_impact),
            ("行业影响", plan.industry_impact),
            ("文章结构建议", plan.article_structure),
            ("必须包含", plan.must_include),
            ("应避免", plan.should_avoid),
            ("事实边界", plan.factual_boundaries),
            ("来源链接", plan.source_urls),
            ("Warnings", plan.warnings),
        ]
        for title, values in sections:
            lines.extend([f"## {title}", "", *self._markdown_list(values), ""])
        lines.extend(["## 写作风格", "", plan.writing_style or "-", ""])
        return "\n".join(lines).rstrip() + "\n"

    def _plan_with_llm(
        self,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult],
        warnings: list[str],
    ) -> NewsArticlePlan | None:
        if not self.llm.is_available():
            warnings.append("LLM unavailable: OPENAI_API_KEY or OPENAI_MODEL is not configured.")
            return None

        response = self.llm.chat(self._system_prompt(), self._user_prompt(selection, details), temperature=0.2)
        if response.startswith(LLMService.WARNING_PREFIX):
            warnings.append(response)
            return None
        try:
            payload = _extract_json_payload(response)
            if not isinstance(payload, dict):
                raise ValueError("LLM plan response must be a JSON object.")
            plan = _model_validate(NewsArticlePlan, payload)
            plan.generation_mode = "llm"
            return plan
        except Exception as exc:
            warnings.append(f"LLM plan response could not be parsed; fallback used: {type(exc).__name__}: {exc}")
            return None

    def _fallback_plan(
        self,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult],
        warnings: list[str],
    ) -> NewsArticlePlan:
        detail_by_id = {detail.news_id: detail for detail in details}
        primary = detail_by_id.get(selection.primary_news_id) or details[0]
        supporting = [detail for detail in details if detail.news_id != primary.news_id]
        title = primary.title_zh or primary.title or "这条 AI 新闻为什么值得关注"
        event_summary = self._best_summary(primary)
        key_facts = self._facts_from_details([primary], limit=5)
        support_facts = self._facts_from_details(supporting, limit=4)
        direction = (selection.direction_text or "").strip()

        core_angle = (
            direction
            if direction
            else f"从 AI 使用者和开发者视角，看“{_clean_text(title, 80)}”背后的产品变化、能力边界和后续观察点。"
        )
        title_candidates = _unique(
            [
                f"{_clean_text(title, 28)}：AI 圈真正该关注什么",
                f"从开发者视角看：{_clean_text(title, 32)}",
                f"{_clean_text(title, 34)}，对 AI 使用者意味着什么",
            ]
        )

        return NewsArticlePlan(
            plan_id=self._new_plan_id(),
            selection_id=selection.selection_id,
            generated_at=utc_now_iso(),
            primary_news_id=selection.primary_news_id,
            title_candidates=title_candidates,
            recommended_title=title_candidates[0] if title_candidates else _clean_text(title, 60),
            core_angle=core_angle,
            lead_hook=f"不要只看标题里最热闹的词，先看这件事具体改变了谁的使用方式、开发方式或判断依据：{_clean_text(title, 90)}。",
            event_summary=event_summary or f"主新闻报道了“{title}”。当前策划基于已保存的标题、摘要和可用正文，不补写未确认细节。",
            key_facts=key_facts or [f"主新闻标题：{title}", f"主新闻来源：{primary.source or '-'}", f"原文链接：{primary.url or '-'}"],
            background_context=_unique(
                [
                    "补充说明该事件发生在 AI 产品、模型能力、开发工具或行业规则持续变化的背景下。",
                    "如果正文没有给出历史脉络，只能用公开常识做低强度背景，不写成已证实因果。",
                    *support_facts,
                ]
            )[:6],
            why_it_matters=[
                "它可能影响 AI 使用者判断一个新功能、新模型或新规则是否值得尝试。",
                "它为开发者提供了观察接口、工作流、成本、可靠性或生态变化的入口。",
                "它能帮助读者区分已发生事实、官方表述和市场/社区推测。",
            ],
            reader_takeaways=[
                "读完后应知道这件事具体发生了什么。",
                "读者应能判断自己是否需要关注、试用、观望或规避相关变化。",
                "读者应看到哪些信息仍缺官方确认或量化证据。",
            ],
            developer_impact=[
                "关注是否涉及 API、SDK、模型能力、价格、兼容性、部署方式或工程工作流。",
                "如果新闻没有给出技术细节，文章只能提出观察问题，不能写成确定结论。",
            ],
            industry_impact=[
                "可讨论对竞争格局、生态协作或监管认知的潜在影响，但需标注为观察而非定论。",
                "没有量化数据时，不推断市场份额、收入或长期商业胜负。",
            ],
            article_structure=[
                "先用一段话交代核心事件和来源。",
                "拆出 3-5 条可核验事实。",
                "解释这件事对使用者、开发者和行业观察分别意味着什么。",
                "最后列出仍需等待确认的信息和后续跟进点。",
            ],
            must_include=_unique(
                [
                    "主新闻来源、发布时间和原文链接。",
                    "主新闻已确认的标题、摘要或正文事实。",
                    "写作方向中要求关注的角度。" if direction else "",
                    "补充新闻只能作为旁证或背景，不要盖过主新闻。",
                ]
            ),
            should_avoid=[
                "不要搬运原文或大段英文原文。",
                "不要写没有来源支撑的判断。",
                "不要夸大影响。",
                "不要使用空泛的 AI 报告腔。",
            ],
            source_urls=_unique([detail.url for detail in details]),
            factual_boundaries=self._default_boundaries(primary),
            writing_style="中文公众号写法：信息密度高、判断克制、少用套话；先事实，后分析，再给读者可执行的观察点。",
            warnings=warnings,
            generation_mode="fallback",
        )

    def _system_prompt(self) -> str:
        return (
            "你是严谨的中文 AI 新闻文章策划编辑。你的任务是生成写作前策划，不写最终文章。"
            "只能基于给定新闻详情、摘要、标题和链接做判断；不能虚构官方确认、数据、融资、商业影响或技术能力。"
            "主新闻决定核心事件，supporting 新闻只能作为补充来源。"
            "标题不要标题党，core_angle 必须具体说明为什么值得 AI 圈关注。"
            "只输出 JSON 对象，不输出 Markdown 或解释。"
        )

    def _user_prompt(self, selection: NewsSelectionContext, details: list[NewsDetailResult]) -> str:
        items = []
        for detail in details:
            role = "primary" if detail.news_id == selection.primary_news_id else "supporting"
            body = detail.content_text or detail.content_preview or detail.summary_zh or detail.summary or ""
            items.append(
                {
                    "role": role,
                    "news_id": detail.news_id,
                    "title": detail.title,
                    "title_zh": detail.title_zh,
                    "summary": detail.summary,
                    "summary_zh": detail.summary_zh,
                    "url": detail.url,
                    "source": detail.source,
                    "published_at": detail.published_at,
                    "content_availability": detail.content_availability,
                    "content_excerpt": _clean_text(body, 5000),
                }
            )
        schema = {
            "title_candidates": ["3-6 个克制的中文标题"],
            "recommended_title": "推荐标题",
            "core_angle": "具体写清这件事为什么值得 AI 圈关注",
            "lead_hook": "开头钩子",
            "event_summary": "事件摘要",
            "key_facts": ["必须来自新闻内容或摘要"],
            "background_context": ["需要补充的背景"],
            "why_it_matters": ["为什么重要"],
            "reader_takeaways": ["读者收获"],
            "developer_impact": ["开发者影响"],
            "industry_impact": ["行业影响"],
            "article_structure": ["文章结构建议"],
            "must_include": ["必须包含"],
            "should_avoid": ["应避免"],
            "source_urls": ["来源链接"],
            "factual_boundaries": ["不能乱写的地方"],
            "writing_style": "写作风格建议",
            "warnings": ["策划警告"],
        }
        return (
            "请根据 selection 和 news_details 生成新闻文章策划 JSON。\n\n"
            f"selection={json.dumps(_model_dump(selection), ensure_ascii=False)}\n\n"
            f"news_details={json.dumps(items, ensure_ascii=False)}\n\n"
            "返回字段必须与这个 schema 对齐：\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )

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
            raise FileNotFoundError("No news article plan found. Please generate one first.")
        if not isinstance(payload, dict):
            raise ValueError("News article plan JSON must contain an object.")
        return _model_validate(NewsArticlePlan, payload)

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
        path = self.articles_dir / f"{safe_id}.json"
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
        summary_text = (item.summary_zh or item.summary or "").strip()
        availability = "full_text" if text else "summary_only" if summary_text else item.content_availability or "metadata_only"
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
            content_preview=text[:4000].rstrip() if text else summary_text,
            content_availability=availability,
            extraction_status="cached" if text else "skipped",
            word_count=len(re.findall(r"\w+", text or "", flags=re.UNICODE)),
            original_language=item.language,
        )

    def _best_summary(self, detail: NewsDetailResult) -> str:
        return _clean_text(
            detail.summary_zh
            or detail.summary
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
            summary = detail.summary_zh or detail.summary
            if summary:
                facts.append(_clean_text(summary, 220))
            if detail.published_at:
                facts.append(f"发布时间：{detail.published_at}")
        return _unique(facts)[:limit]

    def _default_boundaries(self, primary: NewsDetailResult) -> list[str]:
        boundaries = [
            "没有官方确认的信息不能写成事实。",
            "社区讨论、媒体解读或二手来源要标注为讨论/解读。",
            "没有量化数据时，不能推断市场份额、收入或用户规模变化。",
            "不能从单条新闻直接推断长期商业影响。",
        ]
        if primary.content_availability != "full_text":
            boundaries.append("主新闻全文不可用，不能补写正文中可能存在但当前未看到的细节。")
        return boundaries

    def _markdown_list(self, values: list[str]) -> list[str]:
        cleaned = _unique(values)
        if not cleaned:
            return ["- -"]
        return [f"- {value}" for value in cleaned]

    def _new_plan_id(self) -> str:
        now = utc_now_iso().replace(":", "").replace(".", "")
        return f"news-plan-{now}-{uuid4().hex[:8]}"

    def _plan_date(self, plan: NewsArticlePlan) -> str:
        value = plan.generated_at or utc_now_iso()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return datetime.now().date().isoformat()

    def _validate_id(self, value: str | None, field_name: str) -> str:
        safe_id = str(value or "").strip()
        if not SAFE_PLAN_ID_PATTERN.fullmatch(safe_id):
            raise ValueError(f"Invalid {field_name}.")
        return safe_id
