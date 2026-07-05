from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .llm_service import LLMService
from .models import FinalArticle, OriginalityIssue, OriginalityReport


@dataclass
class OriginalityGuardResult:
    final_article: FinalArticle
    originality_report: OriginalityReport


class OriginalityGuardService:
    """Protect style-reference workflows from copying wording or structure."""

    MAX_MATCHED_TEXT_LENGTH = 36
    TITLE_RATIO_THRESHOLD = 0.72
    SIMILARITY_THRESHOLD = 0.18
    COMMON_SEQUENCE_THRESHOLD = 28
    COPIED_SENTENCE_THRESHOLD = 1
    STRUCTURE_THRESHOLD = 0.82

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.used_fallback_rewrite = False
        self.warnings: list[str] = []

    def guard(
        self,
        final_article: FinalArticle,
        reference_texts: list[str] | None,
        style_reference_profile: Any = None,
        custom_direction: Any = None,
    ) -> OriginalityGuardResult:
        references = [self._clean_text(text) for text in (reference_texts or []) if self._clean_text(text)]
        if not references:
            report = OriginalityReport(
                checked=False,
                passed=True,
                summary="未提供参考文章，本次未执行相似度检查",
            )
            return OriginalityGuardResult(
                final_article=self._attach_report(final_article, report),
                originality_report=report,
            )

        report = self.inspect(final_article, references)
        if report.passed:
            return OriginalityGuardResult(
                final_article=self._attach_report(final_article, report),
                originality_report=report,
            )

        rewritten = self._rewrite_once(final_article, report, references, style_reference_profile, custom_direction)
        second_report = self.inspect(rewritten, references)
        second_report.rewrite_attempted = True
        second_report.rewrite_mode = "llm" if self.used_llm else "heuristic"
        if not second_report.passed:
            second_report.summary = (
                f"已自动改写一次，但仍有 {len(second_report.issues)} 个相似度风险，建议发布前人工复核。"
            )
        else:
            second_report.summary = "已执行一次相似度保护改写，复检通过。"

        return OriginalityGuardResult(
            final_article=self._attach_report(rewritten, second_report),
            originality_report=second_report,
        )

    def inspect(self, final_article: FinalArticle, reference_texts: list[str]) -> OriginalityReport:
        article_text = self._article_body(final_article)
        article_sentences = self._sentences(article_text)
        reference_sentences = [
            sentence
            for reference_text in reference_texts
            for sentence in self._sentences(reference_text)
        ]
        issues: list[OriginalityIssue] = []

        title_issue = self._title_issue(final_article.title, reference_texts)
        if title_issue is not None:
            issues.append(title_issue)

        max_common_sequence = 0
        for reference_text in reference_texts:
            max_common_sequence = max(
                max_common_sequence,
                self._max_common_sequence_length(article_text, reference_text),
            )
        if max_common_sequence >= self.COMMON_SEQUENCE_THRESHOLD:
            issues.append(
                OriginalityIssue(
                    issue_type="common_sequence",
                    severity="high" if max_common_sequence >= 48 else "medium",
                    description=f"发现较长连续相同文本片段，最长约 {max_common_sequence} 个字符。",
                    recommendation="改写相似段落，保留项目信息但更换表达顺序和句式。",
                )
            )

        copied_sentences = self._copied_sentences(article_sentences, reference_sentences)
        for sentence in copied_sentences[:3]:
            issues.append(
                OriginalityIssue(
                    issue_type="copied_sentence",
                    severity="high",
                    description="发现与参考文章完整或近完整重复的句子。",
                    matched_text=self._short_match(sentence),
                    recommendation="删除或重写该句，避免复用参考文章原句。",
                )
            )

        structure_similarity = self._max_structure_similarity(article_text, reference_texts)
        if structure_similarity >= self.STRUCTURE_THRESHOLD:
            issues.append(
                OriginalityIssue(
                    issue_type="structure_similarity",
                    severity="medium",
                    description=f"段落数量或段落长度节奏与参考文章较接近（{structure_similarity:.2f}）。",
                    recommendation="调整段落推进顺序、合并或拆分段落，避免复用参考文章结构。",
                )
            )

        unique_expressions = self._unique_expressions(reference_texts)
        reused_expressions = [
            expression
            for expression in unique_expressions
            if self._compact(expression) and self._compact(expression) in self._compact(article_text)
        ]
        for expression in reused_expressions[:4]:
            issues.append(
                OriginalityIssue(
                    issue_type="unique_expression",
                    severity="medium",
                    description="参考文章中的独特表达被复用。",
                    matched_text=self._short_match(expression),
                    recommendation="保留抽象风格，替换具体措辞、比喻或固定搭配。",
                )
            )

        similarity_score = self._similarity_score(article_text, " ".join(reference_texts), copied_sentences, max_common_sequence, structure_similarity)
        if similarity_score >= self.SIMILARITY_THRESHOLD and not any(issue.issue_type == "overall_similarity" for issue in issues):
            issues.append(
                OriginalityIssue(
                    issue_type="overall_similarity",
                    severity="medium",
                    description=f"整体相似度风险偏高（{similarity_score:.2f}）。",
                    recommendation="改写高相似段落，避免复制原句和结构。",
                )
            )

        passed = not any(issue.severity == "high" for issue in issues) and similarity_score < self.SIMILARITY_THRESHOLD
        if structure_similarity >= 0.9 and copied_sentences:
            passed = False

        return OriginalityReport(
            checked=True,
            passed=passed,
            similarity_score=round(similarity_score, 4),
            max_common_sequence_length=max_common_sequence,
            copied_sentence_count=len(copied_sentences),
            structure_similarity=round(structure_similarity, 4),
            issues=issues,
            rewrite_attempted=False,
            rewrite_mode="none",
            summary=(
                "原创性检查通过：参考文章仅作为风格画像使用，未发现明显复制原句或结构。"
                if passed
                else f"原创性检查发现 {len(issues)} 个相似度风险，已准备执行一次保护性改写。"
            ),
        )

    def _rewrite_once(
        self,
        article: FinalArticle,
        report: OriginalityReport,
        reference_texts: list[str],
        style_reference_profile: Any,
        custom_direction: Any,
    ) -> FinalArticle:
        if self.llm_service is not None and self.llm_service.is_available():
            rewritten = self._rewrite_with_llm(article, report, style_reference_profile, custom_direction)
            if rewritten is not None:
                return rewritten
        self.used_fallback_rewrite = True
        return self._fallback_rewrite(article, report, reference_texts)

    def _rewrite_with_llm(
        self,
        article: FinalArticle,
        report: OriginalityReport,
        style_reference_profile: Any,
        custom_direction: Any,
    ) -> FinalArticle | None:
        system_prompt = (
            "你是中文技术公众号编辑，负责原创性检查后的保护性改写。"
            "只保留项目事实、用户方向和抽象风格，不复制参考文章原句、标题、段落结构或独特表达。"
            "不要输出解释，只输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "task": "rewrite_for_originality",
                "requirements": [
                    "保留 GitHub 项目事实、项目地址和用户方向",
                    "保留 style_reference_profile 的抽象语气、节奏和读者关系",
                    "改掉相似标题、相似句子、相似段落推进和独特表达",
                    "文末只保留一个 GitHub 项目地址",
                    "不要出现“参考文章”“仿写”“根据 README”“阅读提示”",
                ],
                "title": article.title,
                "content_markdown": article.content_markdown,
                "style_reference_profile": self._safe_payload(style_reference_profile),
                "custom_direction": self._safe_payload(custom_direction),
                "issues": [self._safe_payload(issue) for issue in report.issues],
                "output_schema": {
                    "title": "string",
                    "summary": "string",
                    "content_markdown": "string",
                },
            },
            ensure_ascii=False,
        )
        raw = self.llm_service.chat(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.45)
        if raw.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(raw)
            return None
        try:
            payload = self._parse_json_object(raw)
            title = str(payload.get("title") or article.title).strip()
            summary = str(payload.get("summary") or article.summary).strip()
            content_markdown = str(payload.get("content_markdown") or "").strip()
            if not content_markdown:
                raise ValueError("empty rewritten content_markdown")
            self.used_llm = True
            return article.copy(
                update={
                    "title": title,
                    "summary": summary,
                    "content_markdown": content_markdown + "\n",
                    "word_count": len(re.sub(r"\s+", "", content_markdown)),
                }
            )
        except Exception as exc:
            self.warnings.append(f"LLM originality rewrite failed, fallback used: {exc}")
            return None

    def _fallback_rewrite(
        self,
        article: FinalArticle,
        report: OriginalityReport,
        reference_texts: list[str],
    ) -> FinalArticle:
        content = article.content_markdown
        title = article.title
        reference_titles = [self._extract_title(text) for text in reference_texts]
        if any(reference_title and self._similar_ratio(title, reference_title) >= self.TITLE_RATIO_THRESHOLD for reference_title in reference_titles):
            project_name = article.full_name.split("/")[-1]
            title = f"{project_name} 放进日常开发里，顺不顺手？"
            content = self._replace_first_heading(content, title)

        reference_sentences = [
            sentence
            for reference_text in reference_texts
            for sentence in self._sentences(reference_text)
        ]
        for sentence in reference_sentences:
            if len(self._compact(sentence)) < 14:
                continue
            content = content.replace(sentence, self._generic_rewrite_sentence(sentence, article.full_name))

        for expression in self._unique_expressions(reference_texts):
            compact_expression = self._compact(expression)
            if len(compact_expression) < 8:
                continue
            content = content.replace(expression, "换个更贴近日常开发的说法")

        content = self._reshape_paragraphs(content)
        content = re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"
        return article.copy(
            update={
                "title": title,
                "content_markdown": content,
                "word_count": len(re.sub(r"\s+", "", content)),
            }
        )

    def _title_issue(self, title: str, reference_texts: list[str]) -> OriginalityIssue | None:
        for reference_text in reference_texts:
            reference_title = self._extract_title(reference_text)
            if not reference_title:
                continue
            ratio = self._similar_ratio(title, reference_title)
            if ratio >= self.TITLE_RATIO_THRESHOLD:
                return OriginalityIssue(
                    issue_type="title_similarity",
                    severity="high" if ratio >= 0.86 else "medium",
                    description=f"标题与参考文章标题过近（{ratio:.2f}）。",
                    matched_text=self._short_match(reference_title),
                    recommendation="重写标题，只保留用户方向中的口吻偏好，不复用参考标题表达。",
                )
        return None

    def _similarity_score(
        self,
        article_text: str,
        reference_text: str,
        copied_sentences: list[str],
        max_common_sequence: int,
        structure_similarity: float,
    ) -> float:
        article_tokens = set(self._tokens(article_text))
        reference_tokens = set(self._tokens(reference_text))
        token_overlap = len(article_tokens & reference_tokens) / max(1, len(article_tokens | reference_tokens))
        common_risk = min(1.0, max_common_sequence / 100.0)
        sentence_risk = min(1.0, len(copied_sentences) / 3.0)
        return min(1.0, token_overlap * 0.42 + common_risk * 0.24 + sentence_risk * 0.24 + structure_similarity * 0.10)

    def _copied_sentences(self, article_sentences: list[str], reference_sentences: list[str]) -> list[str]:
        copied: list[str] = []
        reference_compact = {self._compact(sentence): sentence for sentence in reference_sentences if len(self._compact(sentence)) >= 16}
        for sentence in article_sentences:
            compact_sentence = self._compact(sentence)
            if len(compact_sentence) < 16:
                continue
            if compact_sentence in reference_compact:
                copied.append(sentence)
                continue
            if any(self._similar_ratio(compact_sentence, reference) >= 0.94 for reference in reference_compact):
                copied.append(sentence)
        return self._dedupe(copied)

    def _max_common_sequence_length(self, article_text: str, reference_text: str) -> int:
        article_compact = self._compact(article_text)
        reference_compact = self._compact(reference_text)
        matcher = SequenceMatcher(None, article_compact, reference_compact, autojunk=False)
        return max((match.size for match in matcher.get_matching_blocks()), default=0)

    def _max_structure_similarity(self, article_text: str, reference_texts: list[str]) -> float:
        article_lengths = self._paragraph_lengths(article_text)
        if not article_lengths:
            return 0.0
        return max((self._structure_similarity(article_lengths, self._paragraph_lengths(text)) for text in reference_texts), default=0.0)

    def _structure_similarity(self, left: list[int], right: list[int]) -> float:
        if not left or not right:
            return 0.0
        count_score = 1.0 - min(1.0, abs(len(left) - len(right)) / max(len(left), len(right)))
        size = max(len(left), len(right))
        padded_left = left + [0] * (size - len(left))
        padded_right = right + [0] * (size - len(right))
        distance = sum(abs(a - b) for a, b in zip(padded_left, padded_right))
        baseline = sum(max(a, b, 1) for a, b in zip(padded_left, padded_right))
        length_score = 1.0 - min(1.0, distance / max(1, baseline))
        return max(0.0, min(1.0, count_score * 0.45 + length_score * 0.55))

    def _unique_expressions(self, reference_texts: list[str]) -> list[str]:
        expressions: list[str] = []
        for text in reference_texts:
            for quoted in re.findall(r"[“\"'《]([^”\"'》]{6,24})[”\"'》]", text):
                expressions.append(quoted.strip())
            for phrase in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{4,12}[，,、][\u4e00-\u9fffA-Za-z0-9]{4,12}", text):
                expressions.append(phrase.strip())
            for phrase in re.findall(r"[\u4e00-\u9fff]{2,6}一样[\u4e00-\u9fff]{2,10}", text):
                expressions.append(phrase.strip())
        return self._dedupe([item for item in expressions if len(self._compact(item)) >= 8])[:30]

    def _article_body(self, article: FinalArticle) -> str:
        return "\n".join([article.title, article.summary, article.content_markdown])

    def _sentences(self, text: str) -> list[str]:
        clean = re.sub(r"```.*?```", "", text or "", flags=re.DOTALL)
        clean = re.sub(r"^#+\s*", "", clean, flags=re.MULTILINE)
        parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", clean)
        return [part.strip() for part in parts if len(self._compact(part)) >= 10]

    def _tokens(self, text: str) -> list[str]:
        lower = (text or "").lower()
        english_tokens = re.findall(r"[a-z0-9_+-]{2,}", lower)
        chinese_bigrams = [
            chunk[index : index + 2]
            for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lower)
            for index in range(max(0, len(chunk) - 1))
        ]
        return english_tokens + chinese_bigrams

    def _paragraph_lengths(self, text: str) -> list[int]:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", text or "")
            if len(self._compact(paragraph)) >= 12 and not paragraph.strip().startswith("项目地址")
        ]
        return [len(self._compact(paragraph)) for paragraph in paragraphs[:20]]

    def _extract_title(self, text: str) -> str:
        for line in (text or "").splitlines():
            clean = line.strip()
            if not clean:
                continue
            clean = re.sub(r"^#+\s*", "", clean).strip()
            if len(clean) <= 80:
                return clean
        return ""

    def _replace_first_heading(self, markdown: str, title: str) -> str:
        lines = markdown.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("#"):
                lines[index] = f"# {title}"
                return "\n".join(lines) + "\n"
        return f"# {title}\n\n{markdown.strip()}\n"

    def _reshape_paragraphs(self, markdown: str) -> str:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", markdown.strip()) if paragraph.strip()]
        if len(paragraphs) < 5:
            return markdown
        reshaped: list[str] = []
        for index, paragraph in enumerate(paragraphs):
            if index % 4 == 2 and len(self._compact(paragraph)) > 120 and "。" in paragraph:
                head, tail = paragraph.split("。", 1)
                reshaped.extend([head.strip() + "。", tail.strip()])
            elif index % 5 == 3 and reshaped and not paragraph.startswith("#"):
                reshaped[-1] = f"{reshaped[-1]}\n{paragraph}"
            else:
                reshaped.append(paragraph)
        return "\n\n".join(part for part in reshaped if part.strip())

    def _generic_rewrite_sentence(self, sentence: str, full_name: str) -> str:
        project_name = full_name.split("/")[-1]
        if re.search(r"[\u4e00-\u9fff]", sentence):
            return f"换到 {project_name} 这个项目上，更值得写的是它在真实开发流程里的实际作用。"
        return f"For {project_name}, the more useful angle is how it fits into everyday development work."

    def _attach_report(self, article: FinalArticle, report: OriginalityReport) -> FinalArticle:
        return article.copy(
            update={
                "originality_report": report,
                "originality_checked": report.checked,
                "originality_passed": report.passed,
            }
        )

    def _safe_payload(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "dict"):
            return value.dict()
        if isinstance(value, dict):
            return value
        if isinstance(value, (list, tuple)):
            return [self._safe_payload(item) for item in value]
        return str(value)

    def _parse_json_object(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)

    def _clean_text(self, text: str) -> str:
        return str(text or "").strip()

    def _compact(self, text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).lower()

    def _short_match(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(compact) <= self.MAX_MATCHED_TEXT_LENGTH:
            return compact
        return compact[: self.MAX_MATCHED_TEXT_LENGTH].rstrip() + "..."

    def _similar_ratio(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, self._compact(left), self._compact(right), autojunk=False).ratio()

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value).strip()
            key = self._compact(normalized)
            if not normalized or key in seen:
                continue
            seen.add(key)
            result.append(normalized)
        return result
