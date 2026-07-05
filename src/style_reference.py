from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import StyleReferenceProfile


class StyleReferenceService:
    """Analyze user-provided reference articles into a safe style-only profile."""

    PLAGIARISM_MARKERS = [
        "仿写",
        "洗稿",
        "照着写",
        "照搬",
        "不要被识别出抄袭",
        "规避抄袭",
        "躲避检测",
        "绕过检测",
    ]

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.used_fallback = False
        self.warnings: list[str] = []

    def analyze(
        self,
        reference_texts: list[str] | None,
        source_names: list[str] | None = None,
    ) -> StyleReferenceProfile:
        texts = [self._clean_text(text) for text in (reference_texts or []) if self._clean_text(text)]
        names = self._source_names(source_names or [], len(texts))
        if not texts:
            return StyleReferenceProfile()

        if self.llm_service is not None and self.llm_service.is_available():
            parsed = self._analyze_with_llm(texts, names)
            if parsed is not None:
                self.used_llm = True
                return parsed

        self.used_fallback = True
        return self._fallback_analyze(texts, names)

    def _analyze_with_llm(self, texts: list[str], names: list[str]) -> StyleReferenceProfile | None:
        source_payload = [
            {
                "source_name": name,
                "excerpt_for_style_analysis_only": self._truncate(text, 4500),
            }
            for name, text in zip(names, texts)
        ]
        content = self.llm_service.chat(
            system_prompt=(
                "你是中文技术文章风格分析器。你的任务是从参考文章中提取可迁移的风格画像，"
                "只能分析语气、节奏、读者关系、开头方式、标题倾向、句式和结构倾向。"
                "严禁复述、复制、改写参考文章的原句、标题、独特比喻、段落顺序或核心表达。"
                "如果输入要求贴近原文或复用表达，必须转化为原创风格参考规则。"
                "输出严格 JSON，不要输出 Markdown。"
            ),
            user_prompt=(
                "请输出 JSON object，字段为：raw_count, source_names, tone_traits, pacing_traits, "
                "opening_patterns, transition_patterns, title_patterns, sentence_style, reader_relationship, "
                "structure_tendencies, do_not_copy, originality_rules, summary。\n"
                "要求：列表字段必须是字符串数组；summary 只概括风格画像，不包含参考文章原文、原标题或具体论点；"
                "do_not_copy 必须明确禁止复制原句、标题、独特比喻、段落结构和核心表达；"
                "originality_rules 必须明确最终文章围绕当前 GitHub 项目重新组织，参考文章只决定怎么写，不决定写什么。\n"
                f"参考材料如下：\n{json.dumps(source_payload, ensure_ascii=False, indent=2)}"
            ),
            temperature=0.1,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            payload["raw_count"] = len(texts)
            payload["source_names"] = names
            for key in (
                "tone_traits",
                "pacing_traits",
                "opening_patterns",
                "transition_patterns",
                "title_patterns",
                "sentence_style",
                "structure_tendencies",
                "do_not_copy",
                "originality_rules",
            ):
                payload[key] = self._string_list(payload.get(key))
            payload["reader_relationship"] = self._scalar_text(payload.get("reader_relationship"))
            payload["summary"] = self._clean_summary(payload.get("summary"))
            self._ensure_safety_rules(payload, texts)
            return self._parse_profile(payload)
        except Exception as exc:
            self.warnings.append(f"LLM style reference JSON parse failed, fallback used: {exc}")
            return None

    def _fallback_analyze(self, texts: list[str], names: list[str]) -> StyleReferenceProfile:
        combined = "\n\n".join(texts)
        paragraphs = self._paragraphs(combined)
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        headings = [self._clean_heading(line) for line in lines if self._clean_heading(line)]
        first_paragraph = paragraphs[0] if paragraphs else ""
        avg_sentence_length = self._avg_sentence_length(combined)
        avg_paragraph_length = sum(len(p) for p in paragraphs) / max(len(paragraphs), 1)

        tone_traits: list[str] = []
        if self._contains_any(combined, ["我", "你", "咱", "其实", "说白了", "顺手", "有点"]):
            tone_traits.append("偏口语，像个人经验分享，不端着讲概念")
        if self._contains_any(combined, ["代码", "命令", "开发", "工程", "API", "CLI", "GitHub", "README"]):
            tone_traits.append("技术分享语气，解释工具价值时会落到开发者场景")
        if self._contains_any(combined, ["体验", "用起来", "试了一下", "日常", "顺滑", "麻烦"]):
            tone_traits.append("偏使用体验，不只介绍功能名")
        if self._contains_any(combined, ["为什么", "怎么", "步骤", "先", "再", "最后"]):
            tone_traits.append("带一点教程感，但适合改成轻量解释")
        if self._contains_any(combined, ["测评", "对比", "优点", "缺点", "值得", "不适合"]):
            tone_traits.append("带测评判断，常给出适合/不适合的边界")
        if self._contains_any(combined, ["那天", "后来", "突然", "场景", "问题是"]):
            tone_traits.append("有故事化切入，先给场景再带出观点")
        if not tone_traits:
            tone_traits.append("克制说明型语气，优先把信息讲清楚")

        pacing_traits = []
        pacing_traits.append("短段落推进" if avg_paragraph_length <= 140 else "段落信息密度较高")
        pacing_traits.append("句子偏短，适合快节奏阅读" if avg_sentence_length <= 32 else "句子较长，适合解释型展开")
        if self._list_density(lines) > 0.22:
            pacing_traits.append("清单式信息组织明显")
        else:
            pacing_traits.append("更依赖自然段串联，而不是密集列表")

        opening_patterns = []
        if re.search(r"[？?]", first_paragraph):
            opening_patterns.append("开头常用问题或反问制造进入感")
        if self._contains_any(first_paragraph, ["最近", "有时候", "如果你", "当你", "日常"]):
            opening_patterns.append("从具体日常场景切入")
        if self._contains_any(first_paragraph, ["我", "试", "用", "遇到"]):
            opening_patterns.append("用第一人称经验开场")
        if not opening_patterns:
            opening_patterns.append("先给判断，再解释为什么值得继续看")

        transition_patterns = []
        for marker in ["不过", "但", "所以", "换句话说", "更实际", "真正", "接下来"]:
            if marker in combined:
                transition_patterns.append(f"常用“{marker}”做自然转折")
        transition_patterns = transition_patterns[:6] or ["段落之间用轻量转折，不强行上纲上线"]

        title_patterns = []
        if any(re.search(r"[？?]", heading) for heading in headings):
            title_patterns.append("标题/小标题可用问题式表达")
        if any(self._contains_any(heading, ["我", "你", "为什么", "怎么", "不是"]) for heading in headings):
            title_patterns.append("标题偏口语判断，不像论文题目")
        if any(len(heading) <= 18 for heading in headings):
            title_patterns.append("标题倾向短句，保留悬念或态度")
        if not title_patterns:
            title_patterns.append("标题直接点出使用场景和读者收益")

        sentence_style = [
            "短句和中长句交替" if 24 <= avg_sentence_length <= 48 else ("短句较多" if avg_sentence_length < 24 else "解释型长句较多"),
            "允许少量第一人称和第二人称，增强陪伴感" if self._contains_any(combined, ["我", "你"]) else "更偏第三人称说明",
        ]

        structure_tendencies = []
        if self._list_density(lines) > 0.22:
            structure_tendencies.append("清单式拆点明显，但最终文章不要照搬原清单顺序")
        if len(headings) >= 3:
            structure_tendencies.append("会用小标题分层，但小标题数量应控制")
        if self._contains_any(combined, ["故事", "场景", "问题", "后来"]):
            structure_tendencies.append("倾向按场景 -> 判断 -> 解释推进")
        if not structure_tendencies:
            structure_tendencies.append("自然段推进，重点少而集中")

        reader_relationship = (
            "像同事或朋友分享经验，和读者站在同一侧"
            if self._contains_any(combined, ["你", "咱", "我们"])
            else "像有经验的技术同学做克制推荐"
        )
        do_not_copy = self._base_do_not_copy()
        originality_rules = self._base_originality_rules()
        if self._contains_plagiarism_marker(combined):
            originality_rules.insert(0, "已将非原创复述类表达转化为原创风格参考：只学习风格，不复制内容。")

        summary = "；".join(
            [
                tone_traits[0],
                pacing_traits[0],
                opening_patterns[0],
                reader_relationship,
            ]
        )
        return StyleReferenceProfile(
            raw_count=len(texts),
            source_names=names,
            tone_traits=self._dedupe(tone_traits),
            pacing_traits=self._dedupe(pacing_traits),
            opening_patterns=self._dedupe(opening_patterns),
            transition_patterns=self._dedupe(transition_patterns),
            title_patterns=self._dedupe(title_patterns),
            sentence_style=self._dedupe(sentence_style),
            reader_relationship=reader_relationship,
            structure_tendencies=self._dedupe(structure_tendencies),
            do_not_copy=do_not_copy,
            originality_rules=originality_rules,
            summary=summary,
        )

    def _ensure_safety_rules(self, payload: dict[str, Any], texts: list[str]) -> None:
        do_not_copy = self._dedupe(self._string_list(payload.get("do_not_copy")) + self._base_do_not_copy())
        originality_rules = self._dedupe(
            self._string_list(payload.get("originality_rules")) + self._base_originality_rules()
        )
        if self._contains_plagiarism_marker("\n".join(texts)):
            originality_rules.insert(0, "已将非原创复述类表达转化为原创风格参考：只学习风格，不复制内容。")
        payload["do_not_copy"] = do_not_copy
        payload["originality_rules"] = self._dedupe(originality_rules)

    def _base_do_not_copy(self) -> list[str]:
        return [
            "不要复制参考文章原句或近似改写原句。",
            "不要复用参考文章标题、独特比喻、标志性表达。",
            "不要照搬参考文章段落顺序、论证结构或核心表达。",
        ]

    def _base_originality_rules(self) -> list[str]:
        return [
            "参考文章只决定语气、节奏、读者关系、开头方式和标题倾向。",
            "最终文章必须围绕当前 GitHub 项目事实、ProjectAppeal 和用户 direction 重新组织。",
            "direction 决定写什么；style reference 只决定怎么写。",
        ]

    def _source_names(self, source_names: list[str], count: int) -> list[str]:
        cleaned = [self._clean_text(name) for name in source_names if self._clean_text(name)]
        while len(cleaned) < count:
            cleaned.append(f"reference_text_{len(cleaned) + 1}")
        return cleaned[:count]

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

    def _parse_profile(self, payload: dict[str, Any]) -> StyleReferenceProfile:
        if hasattr(StyleReferenceProfile, "model_validate"):
            return StyleReferenceProfile.model_validate(payload)
        return StyleReferenceProfile.parse_obj(payload)

    def _paragraphs(self, text: str) -> list[str]:
        return [self._clean_text(part) for part in re.split(r"\n\s*\n+", text) if self._clean_text(part)]

    def _avg_sentence_length(self, text: str) -> float:
        sentences = [part.strip() for part in re.split(r"[。！？!?；;]\s*", text) if part.strip()]
        if not sentences:
            return float(len(text))
        return sum(len(sentence) for sentence in sentences) / max(len(sentences), 1)

    def _list_density(self, lines: list[str]) -> float:
        if not lines:
            return 0.0
        list_lines = [line for line in lines if re.match(r"^(\s*[-*+]|\s*\d+[.)、]|#{1,6}\s+)", line)]
        return len(list_lines) / len(lines)

    def _clean_heading(self, line: str) -> str:
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            return self._clean_text(match.group(1))
        return ""

    def _contains_plagiarism_marker(self, text: str) -> bool:
        return self._contains_any(text, self.PLAGIARISM_MARKERS)

    def _contains_any(self, text: str, markers: list[str]) -> bool:
        return any(marker in text for marker in markers)

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [self._clean_text(item) for item in value if self._clean_text(item)]
        text = self._clean_text(value)
        return [text] if text else []

    def _scalar_text(self, value: Any) -> str | None:
        values = self._string_list(value)
        return values[0] if values else None

    def _clean_summary(self, value: Any) -> str:
        summary = self._clean_text(value)
        return self._truncate(summary, 260)

    def _clean_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _truncate(self, value: str, limit: int) -> str:
        text = self._clean_text(value)
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = self._clean_text(value)
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result
