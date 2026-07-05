from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Optional

from .llm_service import LLMService
from .models import (
    ArticleDraft,
    FinalArticle,
    HumanizationIssue,
    HumanizationReport,
    RepoResearchNote,
)


class HumanizationEditorService:
    """Detect and reduce AI-template smell in finalized Chinese articles."""

    AI_PHRASES = [
        "值得关注的是",
        "总的来说",
        "综上",
        "通过本文",
        "不仅如此",
        "不仅可以",
        "不仅能够",
        "不仅……还",
        "无疑",
        "可以帮助开发者",
        "降低门槛",
        "提升效率",
        "对于开发者来说",
        "对于团队来说",
        "如果你正在寻找",
        "它的核心价值在于",
        "这使得",
        "便于",
        "生态",
        "赋能",
    ]
    TITLE_TEMPLATES = [
        "GitHub 上这个",
        "发现一个",
        "stars",
        "Stars",
        "README 里",
        "值得收藏",
        "值得顺手点开",
        "值得放进工具箱",
        "一次看完",
    ]
    LEGACY_SECTIONS = [
        "这个项目是什么",
        "为什么值得关注",
        "核心亮点",
        "适合谁",
        "如何快速了解",
        "小结",
    ]
    LOCAL_CONTEXT_TERMS = [
        "国内团队",
        "个人开发者",
        "自部署",
        "微信",
        "飞书",
        "知识库",
        "本地部署",
        "私有化",
        "成本",
        "内网",
        "团队协作",
        "企业微信",
        "钉钉",
    ]
    ABSTRACT_TERMS = ["能力", "价值", "效率", "体验", "生态", "场景", "流程", "赋能"]

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        pass_threshold: float = 75,
    ) -> None:
        self.llm_service = llm_service
        self.pass_threshold = pass_threshold
        self.used_llm = False
        self.used_fallback_rewrite = False
        self.warnings: list[str] = []

    def inspect_article(
        self,
        final_article: FinalArticle,
        draft: Optional[ArticleDraft] = None,
        note: Optional[RepoResearchNote] = None,
        content_plan: Optional[dict] = None,
    ) -> HumanizationReport:
        text = f"{final_article.title}\n{final_article.summary}\n{final_article.content_markdown}"
        issues: list[HumanizationIssue] = []
        rewrite_suggestions: list[str] = []

        ai_hits = self._phrase_hits(text, self.AI_PHRASES)
        ai_smell_score = 100.0
        if len(ai_hits) >= 3:
            severity = "high" if len(ai_hits) >= 7 else "medium"
            ai_smell_score -= min(36, len(ai_hits) * 4)
            issues.append(
                HumanizationIssue(
                    category="ai_smell",
                    severity=severity,
                    text="、".join(ai_hits[:8]),
                    suggestion="减少套话和抽象判断，改成更具体的技术观察或使用场景。",
                )
            )
            rewrite_suggestions.append("压缩“值得关注/提升效率/降低门槛”一类泛化表达。")

        title_hits = [pattern for pattern in self.TITLE_TEMPLATES if pattern in final_article.title]
        template_risk = 0.0
        if title_hits:
            template_risk += 35
            issues.append(
                HumanizationIssue(
                    category="title_template",
                    severity="medium",
                    text=final_article.title,
                    suggestion="标题保留项目名和具体问题，避开“发现一个 X stars 项目”套路。",
                )
            )
            rewrite_suggestions.append("换一个更像技术分享者口吻的标题。")

        legacy_sections = self._section_hits(final_article.content_markdown, self.LEGACY_SECTIONS)
        if len(legacy_sections) >= 4:
            template_risk += min(45, len(legacy_sections) * 8)
            issues.append(
                HumanizationIssue(
                    category="over_structured",
                    severity="high" if len(legacy_sections) >= 5 else "medium",
                    text="、".join(legacy_sections),
                    suggestion="减少固定二级标题，用自然段或更贴合项目的问题式小标题推进。",
                )
            )
            rewrite_suggestions.append("弱化旧模板小节，避免文章像提纲。")

        structure_issue = self._inspect_structure(final_article.content_markdown)
        if structure_issue is not None:
            template_risk += 20
            issues.append(structure_issue)
            rewrite_suggestions.append("把过密列表或过均匀段落改成自然段。")

        share_style_issues = self._inspect_wechat_share_style(final_article.content_markdown, content_plan)
        if share_style_issues:
            issues.extend(share_style_issues)
            rewrite_suggestions.append("补足具体效果、使用例子和功能收益解释，保留有依据的轻口语判断。")

        body_for_similarity = self._content_without_reference_sections(final_article.content_markdown)
        readme_risk, readme_issues = self._inspect_readme_similarity(final_article, note, body_for_similarity)
        issues.extend(readme_issues)
        if readme_issues:
            rewrite_suggestions.append("改写与 README 相近的句子，避免直接搬运原句。")

        localization_score, localization_issues = self._inspect_localization(text)
        issues.extend(localization_issues)
        if localization_issues:
            rewrite_suggestions.append("补一点中文开发者真实语境，例如自部署、私有化、知识库、协作或成本约束。")

        ai_smell_score = self._clamp(ai_smell_score, 0, 100)
        template_risk = self._clamp(template_risk, 0, 100)
        readme_risk = self._clamp(readme_risk, 0, 100)
        localization_score = self._clamp(localization_score, 0, 100)
        pass_humanization = (
            ai_smell_score >= self.pass_threshold
            and localization_score >= 55
            and template_risk <= 55
            and readme_risk <= 55
            and not any(issue.severity == "high" for issue in issues)
        )

        if not rewrite_suggestions and pass_humanization:
            rewrite_suggestions.append("当前文章没有明显 AI 模板味，发布前保留人工事实复核即可。")

        return HumanizationReport(
            full_name=final_article.full_name,
            ai_smell_score=round(ai_smell_score, 2),
            readme_similarity_risk=round(readme_risk, 2),
            template_risk=round(template_risk, 2),
            localization_score=round(localization_score, 2),
            issues=self._dedupe_issues(issues),
            rewrite_suggestions=self._dedupe(rewrite_suggestions),
            pass_humanization=pass_humanization,
            mode="heuristic",
        )

    def humanize_article(
        self,
        final_article: FinalArticle,
        report: HumanizationReport,
        draft: Optional[ArticleDraft] = None,
        note: Optional[RepoResearchNote] = None,
        content_plan: Optional[dict] = None,
    ) -> FinalArticle:
        if report.pass_humanization:
            already_processed = final_article.humanized or final_article.humanization_report is not None
            final_article.humanization_report = report
            final_article.humanization_mode = final_article.humanization_mode or report.mode
            final_article.humanized = already_processed
            return final_article

        if self.llm_service is not None and self.llm_service.is_available():
            llm_article = self._humanize_with_llm(final_article, report, draft, note, content_plan)
            if llm_article is not None:
                self.used_llm = True
                return llm_article

        self.used_fallback_rewrite = True
        return self._fallback_humanize(final_article, report, draft, note, content_plan)

    def process_articles(
        self,
        final_articles: list[FinalArticle],
        drafts: list[ArticleDraft],
        notes: list[RepoResearchNote],
        content_plans: list[dict] | None,
    ) -> list[FinalArticle]:
        drafts_by_name = {draft.full_name or draft.repo_full_name or "": draft for draft in drafts}
        notes_by_name = {note.full_name: note for note in notes}
        plans_by_name = {
            str(plan.get("full_name") or ""): plan
            for plan in (content_plans or [])
            if isinstance(plan, dict)
        }
        humanized: list[FinalArticle] = []
        for article in final_articles:
            draft = drafts_by_name.get(article.full_name)
            note = notes_by_name.get(article.full_name)
            content_plan = plans_by_name.get(article.full_name)
            report = self.inspect_article(article, draft, note, content_plan)
            humanized.append(self.humanize_article(article, report, draft, note, content_plan))
        return humanized

    def _humanize_with_llm(
        self,
        final_article: FinalArticle,
        report: HumanizationReport,
        draft: Optional[ArticleDraft],
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> Optional[FinalArticle]:
        content = self.llm_service.chat(
            system_prompt=self._humanization_system_prompt(),
            user_prompt=self._humanization_user_prompt(final_article, report, draft, note, content_plan),
            temperature=0.45,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            source_links = self._dedupe(
                self._string_list(payload.get("source_links"))
                + final_article.source_links
                + ([final_article.html_url] if final_article.html_url else [])
                + (note.source_links if note else [])
            )
            factual_warnings = self._dedupe(
                self._string_list(payload.get("factual_warnings")) + final_article.factual_warnings
            )
            title = str(payload.get("title") or final_article.title).strip()
            summary = self._truncate(str(payload.get("summary") or final_article.summary).strip(), 220)
            content_markdown = str(payload.get("content_markdown") or final_article.content_markdown).strip()
            content_markdown = self._ensure_final_markdown(title, content_markdown, source_links, factual_warnings)
            updated_report = self.inspect_article(
                final_article.copy(update={"title": title, "summary": summary, "content_markdown": content_markdown})
                if hasattr(final_article, "copy")
                else final_article,
                draft,
                note,
                content_plan,
            )
            updated_report.mode = "llm"
            if not updated_report.rewrite_suggestions:
                updated_report.rewrite_suggestions = self._string_list(payload.get("rewrite_notes"))
            updated = final_article.copy(
                update={
                    "title": title,
                    "summary": summary,
                    "content_markdown": content_markdown,
                    "source_links": source_links,
                    "factual_warnings": factual_warnings,
                    "word_count": self._count_text(content_markdown),
                    "humanization_report": updated_report,
                    "humanization_mode": "llm",
                    "humanized": True,
                }
            )
            return updated
        except Exception as exc:
            self.warnings.append(f"LLM humanization JSON parse failed for {final_article.full_name}: {exc}")
            return None

    def _fallback_humanize(
        self,
        final_article: FinalArticle,
        report: HumanizationReport,
        draft: Optional[ArticleDraft],
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> FinalArticle:
        project_name = self._project_name(final_article, note, content_plan)
        title = final_article.title.strip()
        if self._title_is_template(title):
            title = self._fallback_title(project_name, note, content_plan)

        content = final_article.content_markdown.strip()
        content = self._replace_ai_phrases(content)
        content = self._soften_legacy_headings(content)
        content = self._merge_dense_bullets(content)
        content = self._ensure_local_context(content, project_name)
        content = self._ensure_final_markdown(title, content, final_article.source_links, final_article.factual_warnings)
        summary = self._replace_ai_phrases(final_article.summary or "")

        updated = final_article.copy(
            update={
                "title": title,
                "summary": self._truncate(summary or final_article.summary, 220),
                "content_markdown": content,
                "word_count": self._count_text(content),
                "humanization_mode": "heuristic",
                "humanized": True,
            }
        )
        updated_report = self.inspect_article(updated, draft, note, content_plan)
        updated_report.mode = "mixed" if report.mode == "llm" else "heuristic"
        if not updated_report.rewrite_suggestions:
            updated_report.rewrite_suggestions = report.rewrite_suggestions
        updated.humanization_report = updated_report
        return updated

    def _inspect_readme_similarity(
        self,
        final_article: FinalArticle,
        note: Optional[RepoResearchNote],
        article_body: Optional[str] = None,
    ) -> tuple[float, list[HumanizationIssue]]:
        if note is None:
            return 0.0, []
        readme_parts = [note.readme_summary] + list(note.readme_key_points)
        readme_parts = [part.strip() for part in readme_parts if part and part.strip()]
        if not readme_parts:
            return 0.0, []

        issues: list[HumanizationIssue] = []
        risk = 0.0
        sentences = self._split_sentences(article_body or final_article.content_markdown)
        for sentence in sentences:
            if self._looks_like_link_line(sentence):
                continue
            normalized_sentence = self._normalize_text(sentence)
            if len(normalized_sentence) < 18:
                continue
            if self._english_long_sentence(sentence):
                risk += 18
                issues.append(
                    HumanizationIssue(
                        category="stiff_translation",
                        severity="medium",
                        text=sentence[:120],
                        suggestion="把英文长句转成中文读者能直接理解的表达，必要时拆短。",
                    )
                )
            for part in readme_parts:
                normalized_part = self._normalize_text(part)
                if len(normalized_part) < 18:
                    continue
                longest = self._longest_common_substring(normalized_sentence, normalized_part)
                ratio = SequenceMatcher(None, normalized_sentence, normalized_part).ratio()
                overlap = self._token_overlap(normalized_sentence, normalized_part)
                if longest >= 20 or (ratio >= 0.72 and overlap >= 0.45):
                    risk += 28 if longest >= 20 else 18
                    issues.append(
                        HumanizationIssue(
                            category="readme_copy",
                            severity="high" if longest >= 28 else "medium",
                            text=sentence[:140],
                            suggestion="保留事实，但换成自己的中文解释，不直接复用 README 原句。",
                        )
                    )
                    break
        return min(risk, 100.0), self._dedupe_issues(issues)

    def _inspect_structure(self, markdown: str) -> Optional[HumanizationIssue]:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", markdown)
            if paragraph.strip() and not paragraph.strip().startswith("#")
        ]
        if len(paragraphs) >= 5:
            lengths = [self._count_text(paragraph) for paragraph in paragraphs if self._count_text(paragraph) >= 20]
            if len(lengths) >= 5:
                avg = sum(lengths) / len(lengths)
                variance = sum((length - avg) ** 2 for length in lengths) / len(lengths)
                if avg and (variance ** 0.5) / avg < 0.28:
                    return HumanizationIssue(
                        category="over_structured",
                        severity="medium",
                        text="多个段落长度过于接近",
                        suggestion="让段落长短有起伏，重点段落展开，过渡段落收短。",
                    )

        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        bullet_count = sum(1 for line in lines if line.startswith(("- ", "* ", "1. ")))
        body_line_count = max(1, sum(1 for line in lines if not line.startswith("#")))
        if body_line_count >= 10 and bullet_count / body_line_count > 0.45:
            return HumanizationIssue(
                category="over_structured",
                severity="medium",
                text="列表占比偏高",
                suggestion="把部分列表合并成解释性自然段，保留真正需要扫读的条目。",
            )
        return None

    def _inspect_localization(self, text: str) -> tuple[float, list[HumanizationIssue]]:
        local_hits = [term for term in self.LOCAL_CONTEXT_TERMS if term in text]
        abstract_hits = [term for term in self.ABSTRACT_TERMS if text.count(term) >= 3]
        score = 58.0 + min(32, len(local_hits) * 8)
        if not local_hits:
            score -= 18
        if len(abstract_hits) >= 3:
            score -= 12
        issues: list[HumanizationIssue] = []
        if score < 55:
            issues.append(
                HumanizationIssue(
                    category="weak_localization",
                    severity="medium",
                    text="缺少明确中文开发者使用语境",
                    suggestion="加入国内团队、个人开发者、自部署、私有化、协作工具或成本约束等具体语境。",
                )
            )
        return score, issues

    def _humanization_system_prompt(self) -> str:
        return (
            "你是一位中文技术公众号资深编辑。你的任务是把一篇已经完成事实核查的开源项目分享稿"
            "改得更像真人写的技术分享，而不是 AI 模板稿或 README 搬运。你不能新增未验证事实，"
            "不能删掉必要来源链接。你要减少模板化表达、机械翻译、固定小标题和总结腔，"
            "让文章更自然、更有中文读者语境。只输出严格 JSON。"
        )

    def _humanization_user_prompt(
        self,
        final_article: FinalArticle,
        report: HumanizationReport,
        draft: Optional[ArticleDraft],
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> str:
        payload = {
            "final_article": self._model_dump(final_article),
            "humanization_report": self._model_dump(report),
            "article_draft": self._model_dump(draft) if draft else None,
            "content_plan": content_plan,
            "custom_article_direction": self._custom_direction(content_plan),
            "style_reference_profile": self._style_reference_profile(content_plan),
            "style_reference_rules": (content_plan or {}).get("style_reference_rules") if content_plan else {},
            "project_insight": (content_plan or {}).get("insight") if content_plan else None,
            "project_impact": (content_plan or {}).get("impact") if content_plan else None,
            "editorial_brief": (content_plan or {}).get("brief") if content_plan else None,
            "facts": (content_plan or {}).get("facts") if content_plan else [],
            "readme_avoid_reference": {
                "readme_summary": note.readme_summary if note else "",
                "readme_key_points": note.readme_key_points if note else [],
            },
        }
        return (
            "请做去 AI 味二次编辑，严格输出 JSON object，字段为："
            "title, summary, content_markdown, factual_warnings, source_links, rewrite_notes。\n"
            "要求：保留事实来源；不编造作者背景；不直接复制 README 原句；"
            "不使用固定旧二级标题；标题避免“发现一个 X star 项目”套路；"
            "风格像一个懂技术的人分享项目；可以使用自然段、短句、少量加粗，不必使用二级标题。"
            "不要删短已经讲清楚项目作用、效果、具体提升的段落；如果文章只有“提升效率/降低成本/改善体验”这类空话，"
            "请用 project_impact 的 concrete_outcomes 或 usage_examples 改成具体场景表达。"
            "不要把有依据的轻口语判断全部改回严肃表达；可以保留“这个点挺实用/有点东西/适合花一个下午玩玩”等自然表达，"
            "但前后必须有具体效果或例子支撑。"
            "必须遵守 custom_article_direction：不要把用户指定的轻松/口语语气改回审稿腔；"
            "不要删除 must_include 指定的重点；avoid_topics 指定避免的内容不要重新写回来。"
            "如果有 style_reference_profile，只保留风格画像中的语气、节奏、读者关系、开头方式和标题倾向；"
            "如发现复制参考文章原句、标题、独特比喻、段落结构，或出现“参考文章中提到”“仿写”“仿照某文”等字样，必须改写为原创表达。"
            "资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _replace_ai_phrases(self, text: str) -> str:
        replacements = {
            "值得关注的是": "更实际的一点是",
            "总的来说，": "",
            "总的来说": "",
            "综上，": "",
            "综上": "",
            "通过本文，": "",
            "通过本文": "",
            "如果你正在寻找": "如果你的场景里刚好有",
            "它的核心价值在于": "它真正解决的是",
            "无疑": "可能",
            "可以帮助开发者": "能让开发者",
            "降低门槛": "少踩一些前期配置的坑",
            "提升效率": "少花一些重复整理的时间",
            "这使得": "这样一来",
            "便于": "更方便",
            "赋能": "支持",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"对于([^，。]{2,24})来说，?", r"\1如果要用它，", text)
        return text

    def _inspect_wechat_share_style(
        self,
        markdown: str,
        content_plan: Optional[dict],
    ) -> list[HumanizationIssue]:
        issues: list[HumanizationIssue] = []
        pattern = (content_plan or {}).get("wechat_pattern") or {}
        required_effects = self._string_list(pattern.get("required_effect_points") if isinstance(pattern, dict) else [])
        required_examples = self._string_list(pattern.get("required_examples") if isinstance(pattern, dict) else [])
        effect_count = self._pattern_match_count(markdown, required_effects, fallback_markers=["解决", "变化", "结果", "省掉", "减少", "整理", "判断", "上下文"])
        example_count = self._pattern_match_count(markdown, required_examples, fallback_markers=["比如", "例如", "可以是", "具体一点", "写代码前", "任务中断", "临时想法"])
        if effect_count < 2:
            issues.append(
                HumanizationIssue(
                    category="weak_effect_detail",
                    severity="medium",
                    text="具体效果展开不足",
                    suggestion="至少自然展开两个项目带来的具体变化。",
                )
            )
        if example_count < 2:
            issues.append(
                HumanizationIssue(
                    category="weak_examples",
                    severity="medium",
                    text="具体使用例子不足",
                    suggestion="至少补两个真实场景例子，而不是只说提升效率。",
                )
            )
        if self._feature_dump_without_benefit(markdown):
            issues.append(
                HumanizationIssue(
                    category="feature_without_benefit",
                    severity="medium",
                    text="功能点偏罗列",
                    suggestion="每个重点功能都补一句它解决什么麻烦、用户看到什么变化。",
                )
            )
        if any(marker in markdown for marker in ["本文将", "从以下几个方面", "资料显示", "根据 README", "具有较高参考价值"]):
            issues.append(
                HumanizationIssue(
                    category="report_tone",
                    severity="medium",
                    text="仍有报告腔或审稿腔",
                    suggestion="改成项目分享口吻，删掉元叙述和资料口吻。",
                )
            )
        return issues

    def _pattern_match_count(
        self,
        markdown: str,
        patterns: list[str],
        fallback_markers: list[str],
    ) -> int:
        compact = re.sub(r"\s+", "", markdown)
        matched = 0
        for pattern in patterns[:6]:
            keywords = self._keywords(pattern)
            if keywords and sum(1 for keyword in keywords if keyword in compact) >= min(2, len(keywords)):
                matched += 1
        marker_hits = sum(1 for marker in fallback_markers if marker in markdown)
        return max(matched, min(marker_hits, 4))

    def _feature_dump_without_benefit(self, markdown: str) -> bool:
        structure_issue = self._inspect_structure(markdown)
        if structure_issue is None or structure_issue.category != "over_structured":
            return False
        benefit_markers = ["解决", "麻烦", "变化", "省掉", "减少", "看到", "不用", "更容易", "具体"]
        return sum(1 for marker in benefit_markers if marker in markdown) < 3

    def _keywords(self, value: str) -> list[str]:
        text = re.sub(r"\s+", "", str(value or "").lower())
        keywords: list[str] = []
        for token in re.findall(r"[a-z0-9_+-]{3,}", text):
            keywords.append(token)
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            for part in re.split(r"[，。；、的和与及里把为是能让成在]+", chunk):
                if len(part) >= 2 and part not in {"这个", "项目", "用户", "可以", "一个", "实际", "使用"}:
                    keywords.append(part[:8])
        return self._dedupe(keywords)[:5]

    def _content_without_reference_sections(self, markdown: str) -> str:
        return re.split(r"^\s*##\s*(参考链接|来源链接)\s*$", markdown, maxsplit=1, flags=re.MULTILINE)[0]

    def _looks_like_link_line(self, text: str) -> bool:
        stripped = text.strip()
        if "http://" in stripped or "https://" in stripped:
            return True
        return bool(re.fullmatch(r"[-*]\s*\S+", stripped)) and "/" in stripped

    def _soften_legacy_headings(self, markdown: str) -> str:
        replacements = {
            "## 这个项目是什么": "## 先说它解决什么问题",
            "## 为什么值得关注": "## 我会重点看这几点",
            "## 核心亮点": "## 真正有用的地方",
            "## 适合谁": "## 哪些人可能用得上",
            "## 如何快速了解或上手": "## 上手前先看哪里",
            "## 如何快速了解": "## 上手前先看哪里",
            "## 小结": "## 最后留一个判断",
        }
        for source, target in replacements.items():
            markdown = markdown.replace(source, target)
        return markdown

    def _merge_dense_bullets(self, markdown: str) -> str:
        blocks = re.split(r"(\n\s*\n)", markdown)
        output: list[str] = []
        for block in blocks:
            lines = block.splitlines()
            bullet_lines = [line.strip()[2:].strip() for line in lines if line.strip().startswith(("- ", "* "))]
            if len(bullet_lines) >= 4:
                lead = "；".join(item.rstrip("。；;") for item in bullet_lines[:3])
                rest = lines[len(bullet_lines):]
                merged = f"{lead}。"
                if rest:
                    merged = f"{merged}\n" + "\n".join(rest)
                output.append(merged)
            else:
                output.append(block)
        return "".join(output)

    def _ensure_local_context(self, markdown: str, project_name: str) -> str:
        if any(term in markdown for term in self.LOCAL_CONTEXT_TERMS):
            return markdown
        addition = (
            f"放到中文开发者的日常语境里看，{project_name} 更适合作为一个候选工具先小范围试用："
            "比如个人项目先验证成本和维护节奏，团队场景再看它能不能接进现有知识库、协作工具或私有化环境。"
        )
        if "## 阅读提醒" in markdown:
            return markdown.replace("## 阅读提醒", f"{addition}\n\n## 阅读提醒", 1)
        if "## 参考链接" in markdown:
            return markdown.replace("## 参考链接", f"{addition}\n\n## 参考链接", 1)
        return f"{markdown.rstrip()}\n\n{addition}"

    def _ensure_final_markdown(
        self,
        title: str,
        content_markdown: str,
        source_links: list[str],
        factual_warnings: list[str],
    ) -> str:
        content = content_markdown.strip()
        if not re.search(r"^\s*#\s+", content, flags=re.MULTILINE):
            content = f"# {title}\n\n{content}"
        else:
            content = re.sub(r"^\s*#\s+.*$", f"# {title}", content, count=1, flags=re.MULTILINE)
        if factual_warnings and "阅读提醒" not in content and "事实风险" not in content:
            content = f"{content.rstrip()}\n\n## 阅读提醒\n\n" + "\n".join(f"- {item}" for item in factual_warnings)
        if source_links and "参考链接" not in content and "来源链接" not in content:
            content = f"{content.rstrip()}\n\n## 参考链接\n\n" + "\n".join(f"- {link}" for link in source_links)
        elif source_links:
            missing = [link for link in source_links if link not in content]
            if missing:
                content = self._append_missing_links_to_reference_section(content, missing)
        return content.strip() + "\n"

    def _append_missing_links_to_reference_section(self, markdown: str, missing_links: list[str]) -> str:
        additions = "\n".join(f"- {link}" for link in missing_links)
        reference_match = re.search(
            r"(^\s*##\s*(?:参考链接|来源链接)\s*$)",
            markdown,
            flags=re.MULTILINE,
        )
        if reference_match is None:
            return f"{markdown.rstrip()}\n\n## 参考链接\n\n{additions}"

        next_heading = re.search(
            r"^\s*##\s+",
            markdown[reference_match.end() :],
            flags=re.MULTILINE,
        )
        if next_heading is None:
            return f"{markdown.rstrip()}\n{additions}"

        insert_at = reference_match.end() + next_heading.start()
        before = markdown[:insert_at].rstrip()
        after = markdown[insert_at:].lstrip("\n")
        return f"{before}\n{additions}\n\n{after}"

    def _fallback_title(
        self,
        project_name: str,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> str:
        project_kind = str((content_plan or {}).get("project_kind") or (note.project_kind if note else "") or "").replace("_", " ")
        wechat_pattern = (content_plan or {}).get("wechat_pattern") or {}
        formula = str(wechat_pattern.get("title_formula") or "").strip() if isinstance(wechat_pattern, dict) else ""
        if formula and "标题" not in formula and "不要" not in formula:
            title = formula.replace("XXX", project_name).replace("A + B = C", f"{project_name} + 工作流 = 具体效果")
            title = re.sub(r"一周狂揽\s*", "", title)
            return self._truncate(title, 42)
        if project_kind:
            return f"{project_name}：把一个具体的 {project_kind} 需求做成了开源工具"
        return f"{project_name} 解决的这个小问题，可能正好是你需要的"

    def _title_is_template(self, title: str) -> bool:
        return any(pattern in title for pattern in self.TITLE_TEMPLATES) or bool(re.search(r"\d+[,.]?\d*\s*(stars|Stars|star)", title))

    def _project_name(
        self,
        final_article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> str:
        insight = (content_plan or {}).get("insight") or {}
        if isinstance(insight, dict) and insight.get("project_name"):
            return str(insight["project_name"])
        full_name = final_article.full_name or (note.full_name if note else "")
        return full_name.split("/")[-1] if full_name else "这个项目"

    def _section_hits(self, markdown: str, sections: list[str]) -> list[str]:
        headings = re.findall(r"^\s*#{2,3}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
        return [section for section in sections if any(section in heading for heading in headings)]

    def _phrase_hits(self, text: str, phrases: list[str]) -> list[str]:
        hits: list[str] = []
        for phrase in phrases:
            count = text.count(phrase)
            if count >= 1:
                hits.extend([phrase] * min(count, 3))
        pattern_hits = [
            ("不仅……还……", r"不仅[^。！？；\n]{0,40}还"),
            ("对于……来说", r"对于[^。！？；\n]{2,40}来说"),
        ]
        for label, pattern in pattern_hits:
            count = len(re.findall(pattern, text))
            if count >= 1:
                hits.extend([label] * min(count, 3))
        return hits

    def _split_sentences(self, text: str) -> list[str]:
        compact = re.sub(r"\s+", " ", text)
        return [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", compact) if part.strip()]

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text.lower())

    def _english_long_sentence(self, sentence: str) -> bool:
        english_words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", sentence)
        return len(english_words) >= 12 and len(sentence) >= 90

    def _longest_common_substring(self, a: str, b: str) -> int:
        if not a or not b:
            return 0
        previous = [0] * (len(b) + 1)
        best = 0
        for char_a in a:
            current = [0] * (len(b) + 1)
            for index_b, char_b in enumerate(b, start=1):
                if char_a == char_b:
                    current[index_b] = previous[index_b - 1] + 1
                    best = max(best, current[index_b])
            previous = current
        return best

    def _token_overlap(self, a: str, b: str) -> float:
        tokens_a = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9_+-]{2,}", a))
        tokens_b = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9_+-]{2,}", b))
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b)))

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

    def _count_text(self, text: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text))

    def _truncate(self, text: str, limit: int) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _clamp(self, value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = str(value).strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _dedupe_issues(self, issues: list[HumanizationIssue]) -> list[HumanizationIssue]:
        seen: set[tuple[str, str]] = set()
        result: list[HumanizationIssue] = []
        for issue in issues:
            key = (issue.category, issue.text)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result

    def _model_dump(self, model: Any) -> dict:
        if model is None:
            return {}
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        if hasattr(model, "dict"):
            return model.dict()
        if isinstance(model, dict):
            return model
        return {}

    def _custom_direction(self, content_plan: Optional[dict]) -> dict[str, Any]:
        if not content_plan:
            return {}
        direction = content_plan.get("custom_direction") or content_plan.get("parsed_direction") or {}
        return direction if isinstance(direction, dict) else {}

    def _style_reference_profile(self, content_plan: Optional[dict]) -> dict[str, Any]:
        profile = (content_plan or {}).get("style_reference_profile") or {}
        if isinstance(profile, dict) and int(profile.get("raw_count") or 0) > 0:
            return profile
        return {}
