from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import CustomArticleDirection


class DirectionParserService:
    """Parse free-form custom article direction into writing constraints."""

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.used_fallback = False
        self.warnings: list[str] = []

    def parse(self, direction_text: str | None) -> CustomArticleDirection:
        raw_text = (direction_text or "").strip()
        if not raw_text:
            return CustomArticleDirection()

        if self.llm_service is not None and self.llm_service.is_available():
            parsed = self._parse_with_llm(raw_text)
            if parsed is not None:
                self.used_llm = True
                return parsed

        self.used_fallback = True
        return self._fallback_parse(raw_text)

    def _parse_with_llm(self, raw_text: str) -> CustomArticleDirection | None:
        content = self.llm_service.chat(
            system_prompt=(
                "你是中文技术文章的写作方向解析器。请把用户的自然语言写作要求解析成结构化约束。"
                "只抽取用户明确表达或强烈暗示的要求，不要补充不存在的限制。输出严格 JSON。"
            ),
            user_prompt=(
                "请输出 JSON object，字段为：raw_text, target_reader, writing_perspective, core_angle, "
                "must_include, avoid_topics, tone_preferences, title_preferences, content_preferences。\n"
                "字段解释：target_reader 是面向谁；writing_perspective 是叙述视角；core_angle 是核心选题角度；"
                "must_include 是必须强调的内容；avoid_topics 是不要写/少写/避免的内容；"
                "tone_preferences 是语气偏好；title_preferences 是标题偏好；content_preferences 是内容组织偏好。"
                "列表字段必须是字符串数组；没有就给空数组；不要输出 Markdown。用户输入如下：\n"
                f"{raw_text}"
            ),
            temperature=0.1,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None
        try:
            payload = self._extract_json_object(content)
            payload["raw_text"] = raw_text
            for key in ("target_reader", "writing_perspective", "core_angle"):
                payload[key] = self._scalar_text(payload.get(key))
            for key in (
                "must_include",
                "avoid_topics",
                "tone_preferences",
                "title_preferences",
                "content_preferences",
            ):
                payload[key] = self._string_list(payload.get(key))
            return self._parse_direction(payload)
        except Exception as exc:
            self.warnings.append(f"LLM direction JSON parse failed, fallback used: {exc}")
            return None

    def _fallback_parse(self, raw_text: str) -> CustomArticleDirection:
        clauses = self._split_clauses(raw_text)
        target_reader = self._target_reader(raw_text, clauses)
        writing_perspective = self._writing_perspective(raw_text, clauses)
        avoid_topics = self._dedupe(
            self._matching_clauses(clauses, ["不要", "别写", "少写", "避免", "不要太像", "不应", "不能"])
        )
        focus_clauses = self._matching_clauses(clauses, ["重点", "突出", "主要写", "核心", "围绕", "强调"])
        title_preferences = self._matching_clauses(clauses, ["标题", "题目"])
        tone_preferences = self._tone_preferences(raw_text, clauses)
        content_preferences = self._content_preferences(raw_text, clauses)

        core_angle = self._first_non_empty(focus_clauses)
        if not core_angle:
            core_angle = self._first_non_empty(
                self._matching_clauses(clauses, ["切入", "出发", "视角", "体验", "爽点", "优势"])
            )

        must_include = self._dedupe(focus_clauses)
        if core_angle and core_angle not in must_include:
            must_include.insert(0, core_angle)

        return CustomArticleDirection(
            raw_text=raw_text,
            target_reader=target_reader,
            writing_perspective=writing_perspective,
            core_angle=core_angle,
            must_include=must_include,
            avoid_topics=avoid_topics,
            tone_preferences=tone_preferences,
            title_preferences=title_preferences,
            content_preferences=content_preferences,
        )

    def _target_reader(self, raw_text: str, clauses: list[str]) -> str | None:
        for pattern in [
            r"面向([^，。；;,.]{2,40}?(?:开发者|程序员|用户|使用者|同学|团队))",
            r"适合([^，。；;,.]{2,40}?(?:开发者|程序员|用户|使用者|同学|团队))",
            r"写给([^，。；;,.]{2,40}?(?:开发者|程序员|用户|使用者|同学|团队))",
        ]:
            match = re.search(pattern, raw_text)
            if match:
                return self._clean_text(match.group(1))
        reader_terms = [
            ("Python 后端开发者", "Python 后端开发者"),
            ("命令行用户", "命令行用户"),
            ("CLI 用户", "命令行用户"),
            ("程序员", "程序员"),
            ("开发者", "开发者"),
            ("使用者", "实际使用者"),
            ("用户", "实际用户"),
        ]
        for marker, value in reader_terms:
            if marker in raw_text:
                return value
        return self._first_non_empty(self._matching_clauses(clauses, ["面向", "适合", "写给"]))

    def _writing_perspective(self, raw_text: str, clauses: list[str]) -> str | None:
        perspective_markers = [
            ("程序员日常使用体验", "程序员日常使用体验"),
            ("日常使用体验", "日常使用体验"),
            ("使用者视角", "使用者视角"),
            ("用户视角", "用户视角"),
            ("朋友圈", "朋友推荐工具的视角"),
            ("命令行用户", "命令行用户视角"),
            ("开发者", "开发者视角"),
            ("程序员", "程序员视角"),
        ]
        for marker, value in perspective_markers:
            if marker in raw_text:
                return value
        return self._first_non_empty(self._matching_clauses(clauses, ["视角", "体验", "出发", "切入"]))

    def _tone_preferences(self, raw_text: str, clauses: list[str]) -> list[str]:
        values = self._matching_clauses(
            clauses,
            ["轻松", "口语", "朋友圈", "不要太严谨", "自然", "克制", "标题不要夸张", "不要夸张"],
        )
        if "标题口语" in raw_text and not any("口语" in item for item in values):
            values.append("标题和正文都更口语一点")
        return self._dedupe(values)

    def _content_preferences(self, raw_text: str, clauses: list[str]) -> list[str]:
        values = self._matching_clauses(
            clauses,
            ["不要太像教程", "不要写成教程", "不要教程", "少写技术实现", "多写", "少写", "不要堆", "功能列表", "爽点"],
        )
        if "教程" in raw_text and not any("教程" in item for item in values):
            values.append("不要写成步骤化教程")
        if "README" in raw_text and not any("README" in item for item in values):
            values.append("不要堆 README 功能")
        return self._dedupe(values)

    def _split_clauses(self, text: str) -> list[str]:
        parts = re.split(r"[，。；;,.！!？?\n]+", text)
        return [self._clean_text(part) for part in parts if self._clean_text(part)]

    def _matching_clauses(self, clauses: list[str], markers: list[str]) -> list[str]:
        return [clause for clause in clauses if any(marker in clause for marker in markers)]

    def _first_non_empty(self, values: list[str]) -> str | None:
        for value in values:
            clean = self._clean_text(value)
            if clean:
                return clean
        return None

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        text = content.strip()
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if code_block:
            text = code_block.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start : end + 1]
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM output is not a JSON object")
        return payload

    def _parse_direction(self, payload: dict[str, Any]) -> CustomArticleDirection:
        if hasattr(CustomArticleDirection, "model_validate"):
            return CustomArticleDirection.model_validate(payload)
        return CustomArticleDirection.parse_obj(payload)

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _scalar_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple, set)):
            values = [str(item).strip() for item in value if str(item).strip()]
            return values[0] if values else None
        text = str(value).strip()
        return text or None

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = self._clean_text(value)
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()
