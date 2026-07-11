from __future__ import annotations

import json
import re
from typing import Any

from src.config import get_settings
from src.llm_service import LLMService
from src.models import NewsItem


CHINESE_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _contains_chinese(value: str | None) -> bool:
    return bool(value and CHINESE_PATTERN.search(value))


def _short_error(exc: Exception | str, max_length: int = 180) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:max_length] or "translation failed"


def _extract_json_payload(value: str) -> Any:
    text = (value or "").strip()
    block_match = JSON_BLOCK_PATTERN.search(text)
    if block_match:
        text = block_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class NewsTranslatorService:
    """Translate only news titles and summaries for Chinese display."""

    def __init__(self, llm: LLMService | None = None, batch_size: int = 10) -> None:
        settings = get_settings()
        self.llm = llm or LLMService(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )
        self.batch_size = max(1, min(batch_size, 20))

    def translate_items(self, items: list[NewsItem], limit: int = 50) -> list[NewsItem]:
        translate_limit = max(0, int(limit or 0))
        candidates: list[NewsItem] = []

        for item in items:
            item.translation_error = None
            if self._source_is_chinese(item):
                self._mark_source_is_chinese(item)
                continue
            candidates.append(item)

        if translate_limit <= 0 or not self.llm.is_available():
            for item in candidates:
                self._mark_skipped(item)
            return items

        to_translate = candidates[:translate_limit]
        for item in candidates[translate_limit:]:
            self._mark_skipped(item)

        for start in range(0, len(to_translate), self.batch_size):
            batch = to_translate[start : start + self.batch_size]
            try:
                self._translate_batch(batch)
            except Exception:
                for item in batch:
                    self._translate_single_with_fallback(item)
        return items

    def _source_is_chinese(self, item: NewsItem) -> bool:
        return _contains_chinese(item.title) or _contains_chinese(item.summary)

    def _mark_source_is_chinese(self, item: NewsItem) -> None:
        item.title_zh = item.title
        item.summary_zh = item.summary
        item.translation_status = "source_is_chinese"
        item.translation_error = None

    def _mark_skipped(self, item: NewsItem) -> None:
        item.title_zh = item.title
        item.summary_zh = item.summary
        item.translation_status = "skipped"
        item.translation_error = None

    def _mark_failed(self, item: NewsItem, error: Exception | str) -> None:
        item.title_zh = item.title
        item.summary_zh = item.summary
        item.translation_status = "failed"
        item.translation_error = _short_error(error)

    def _system_prompt(self) -> str:
        return (
            "你是严谨的 AI 新闻翻译助手。只把新闻标题和摘要翻译成简体中文。"
            "保持事实准确和信息密度，不要改写成夸张标题，不要添加原文没有的信息。"
            "不要翻译正文，不要输出解释，只输出 JSON。"
        )

    def _translate_batch(self, items: list[NewsItem]) -> None:
        payload = [
            {
                "id": item.id,
                "title": item.title,
                "summary": item.summary,
            }
            for item in items
        ]
        user_prompt = (
            "请翻译下面 JSON 数组中每条新闻的 title 和 summary。"
            "返回 JSON 数组，每个对象必须包含 id、title_zh、summary_zh。"
            "summary 为空时 summary_zh 返回空字符串。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        response = self.llm.chat(self._system_prompt(), user_prompt, temperature=0.1)
        if response.startswith(LLMService.WARNING_PREFIX):
            raise RuntimeError(response)

        parsed = _extract_json_payload(response)
        if not isinstance(parsed, list):
            raise ValueError("translation response must be a JSON array")

        by_id = {str(entry.get("id")): entry for entry in parsed if isinstance(entry, dict)}
        missing_ids: list[str] = []
        for item in items:
            translated = by_id.get(item.id)
            if not translated:
                missing_ids.append(item.id)
                continue
            self._apply_translation(item, translated)
        if missing_ids:
            raise ValueError(f"missing translations: {', '.join(missing_ids[:3])}")

    def _translate_single_with_fallback(self, item: NewsItem) -> None:
        payload = {"id": item.id, "title": item.title, "summary": item.summary}
        user_prompt = (
            "请翻译下面单条新闻的 title 和 summary。"
            "返回一个 JSON 对象，必须包含 id、title_zh、summary_zh。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = self.llm.chat(self._system_prompt(), user_prompt, temperature=0.1)
            if response.startswith(LLMService.WARNING_PREFIX):
                raise RuntimeError(response)
            parsed = _extract_json_payload(response)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            if not isinstance(parsed, dict):
                raise ValueError("translation response must be a JSON object")
            self._apply_translation(item, parsed)
        except Exception as exc:
            self._mark_failed(item, exc)

    def _apply_translation(self, item: NewsItem, translated: dict[str, Any]) -> None:
        title_zh = str(translated.get("title_zh") or "").strip()
        summary_zh = str(translated.get("summary_zh") or "").strip()
        if not title_zh:
            raise ValueError("translated title is empty")
        item.title_zh = title_zh
        item.summary_zh = summary_zh if item.summary else ""
        item.translation_status = "translated"
        item.translation_error = None
