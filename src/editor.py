from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import ArticleDraft, ArticleReview, FinalArticle, RepoResearchNote, TopicAngle


class EditorService:
    """Review and revise WeChat-style GitHub recommendation articles."""

    HIGH_RISK_WORDS = ["最强", "第一", "彻底取代", "颠覆", "必火", "全网"]
    REQUIRED_SECTIONS = [
        "开头",
        "这个项目是什么",
        "为什么值得关注",
        "核心亮点",
        "适合谁",
        "上手",
        "小结",
        "参考链接",
    ]

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        pass_threshold: float = 80,
    ) -> None:
        self.llm_service = llm_service
        self.pass_threshold = pass_threshold
        self.used_llm_review = False
        self.used_llm_revision = False
        self.warnings: list[str] = []

    def review_articles(
        self,
        drafts: list[ArticleDraft],
        research_notes: list[RepoResearchNote],
        angles: list[TopicAngle],
    ) -> list[ArticleReview]:
        notes_by_name = {note.full_name: note for note in research_notes}
        angles_by_name = {angle.full_name: angle for angle in angles}
        return [
            self.review_article(
                draft=draft,
                note=notes_by_name.get(draft.full_name or draft.repo_full_name or ""),
                angle=angles_by_name.get(draft.full_name or draft.repo_full_name or ""),
            )
            for draft in drafts
        ]

    def review_article(
        self,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> ArticleReview:
        if self.llm_service is not None and self.llm_service.is_available():
            llm_review = self._review_article_with_llm(draft, note, angle)
            if llm_review is not None:
                self.used_llm_review = True
                return llm_review

        return self._fallback_review(draft, note, angle)

    def revise_articles(
        self,
        drafts: list[ArticleDraft],
        reviews: list[ArticleReview],
        research_notes: list[RepoResearchNote],
        angles: list[TopicAngle],
    ) -> list[FinalArticle]:
        notes_by_name = {note.full_name: note for note in research_notes}
        angles_by_name = {angle.full_name: angle for angle in angles}
        reviews_by_name = {review.full_name: review for review in reviews}
        finals: list[FinalArticle] = []

        for draft in drafts:
            name = draft.full_name or draft.repo_full_name or ""
            review = reviews_by_name.get(name)
            if review is None:
                review = self.review_article(draft, notes_by_name.get(name), angles_by_name.get(name))
            finals.append(
                self.revise_article(
                    draft=draft,
                    review=review,
                    note=notes_by_name.get(name),
                    angle=angles_by_name.get(name),
                )
            )

        return finals

    def revise_article(
        self,
        draft: ArticleDraft,
        review: ArticleReview,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> FinalArticle:
        if review.pass_review:
            return self._final_from_draft(draft, review, "unchanged")

        if self.llm_service is not None and self.llm_service.is_available():
            llm_final = self._revise_article_with_llm(draft, review, note, angle)
            if llm_final is not None:
                self.used_llm_revision = True
                return llm_final

        return self._fallback_revision(draft, review, note, angle)

    def _review_article_with_llm(
        self,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> Optional[ArticleReview]:
        content = self.llm_service.chat(
            system_prompt=self._review_system_prompt(),
            user_prompt=self._review_user_prompt(draft, note, angle),
            temperature=0.2,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            review = ArticleReview(
                full_name=draft.full_name or draft.repo_full_name or (note.full_name if note else ""),
                title=draft.title,
                total_score=self._clamp_score(payload.get("total_score"), 0, 100),
                factual_score=self._clamp_score(payload.get("factual_score"), 0, 30),
                title_score=self._clamp_score(payload.get("title_score"), 0, 20),
                structure_score=self._clamp_score(payload.get("structure_score"), 0, 20),
                readability_score=self._clamp_score(payload.get("readability_score"), 0, 15),
                completeness_score=self._clamp_score(payload.get("completeness_score"), 0, 15),
                strengths=self._string_list(payload.get("strengths")),
                issues=self._string_list(payload.get("issues")),
                revision_suggestions=self._string_list(payload.get("revision_suggestions")),
                pass_review=bool(payload.get("pass_review")),
                review_mode="llm",
            )
            review.total_score = self._normalize_total_score(review)
            review.pass_review = review.total_score >= self.pass_threshold
            return review
        except Exception as exc:
            self.warnings.append(
                f"LLM review JSON parse failed for {draft.full_name or draft.repo_full_name}, fallback used: {exc}"
            )
            return None

    def _revise_article_with_llm(
        self,
        draft: ArticleDraft,
        review: ArticleReview,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> Optional[FinalArticle]:
        content = self.llm_service.chat(
            system_prompt=self._revision_system_prompt(),
            user_prompt=self._revision_user_prompt(draft, review, note, angle),
            temperature=0.45,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            source_links = self._dedupe(
                self._string_list(payload.get("source_links"))
                + draft.source_links
                + (angle.source_links if angle else [])
                + (note.source_links if note else [])
                + ([draft.html_url or note.html_url] if draft.html_url or note else [])
            )
            factual_warnings = self._dedupe(
                self._string_list(payload.get("factual_warnings"))
                + draft.factual_warnings
                + (angle.factual_warnings if angle else [])
                + (note.risks if note else [])
            )
            content_markdown = str(payload.get("content_markdown") or draft.content_markdown).strip()
            title = str(payload.get("title") or draft.title).strip()
            content_markdown = self._ensure_final_markdown(
                title=title,
                content_markdown=content_markdown,
                source_links=source_links,
                factual_warnings=factual_warnings,
                content_plan_used=draft.content_plan_used,
            )
            return FinalArticle(
                full_name=review.full_name,
                html_url=draft.html_url or (note.html_url if note else ""),
                title=title,
                summary=self._truncate(str(payload.get("summary") or draft.summary), 220),
                content_markdown=content_markdown,
                cover_prompt=str(payload.get("cover_prompt") or draft.cover_prompt or (angle.cover_prompt if angle else "")),
                source_links=source_links,
            factual_warnings=factual_warnings,
            review=review,
            revision_mode="llm",
            word_count=self._count_text(content_markdown),
            generation_mode=draft.generation_mode,
            content_plan_used=draft.content_plan_used,
            narrative_pattern=draft.narrative_pattern,
            title_style=draft.title_style,
            article_style_notes=draft.article_style_notes,
            source_fact_ids=draft.source_fact_ids,
            writer_persona=draft.writer_persona,
            top_selling_points_used=draft.top_selling_points_used,
            practical_scenarios_used=draft.practical_scenarios_used,
        )
        except Exception as exc:
            self.warnings.append(
                f"LLM revision JSON parse failed for {review.full_name}, fallback used: {exc}"
            )
            return None

    def _fallback_review(
        self,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> ArticleReview:
        text = f"{draft.title}\n{draft.summary}\n{draft.content_markdown}"
        issues: list[str] = []
        suggestions: list[str] = []
        strengths: list[str] = []

        factual_score = 30.0
        title_score = 20.0
        structure_score = 20.0
        readability_score = 15.0
        completeness_score = 15.0

        high_risk_words = [word for word in self.HIGH_RISK_WORDS if word in text]
        if high_risk_words:
            factual_score -= 6
            title_score -= 5
            issues.append(f"存在可能无法验证或过度营销的高风险词：{', '.join(high_risk_words)}")
            suggestions.append("替换绝对化、夸张化表述，改成基于 GitHub 资料的克制描述。")

        links = self._dedupe(draft.source_links + ([draft.html_url] if draft.html_url else []))
        github_links = [link for link in links if "github.com" in link]
        if not links:
            factual_score -= 8
            completeness_score -= 4
            issues.append("source_links 为空，缺少可核验来源。")
            suggestions.append("至少补充 GitHub 仓库链接；content_plan 文章正文保留项目地址即可。")
        elif not github_links:
            factual_score -= 5
            issues.append("参考链接中未识别到 GitHub 链接。")
            suggestions.append("补充项目 GitHub 仓库链接作为核心来源。")
        else:
            strengths.append("保留了 GitHub 等参考链接，便于读者核验。")

        if draft.content_plan_used:
            if "项目地址：" not in draft.content_markdown and not any(link in draft.content_markdown for link in github_links):
                factual_score -= 4
                structure_score -= 3
                completeness_score -= 3
                issues.append("正文缺少项目地址。")
                suggestions.append("文末保留一行项目地址，不新增参考链接长列表。")
        elif "参考链接" not in draft.content_markdown:
            factual_score -= 4
            structure_score -= 3
            completeness_score -= 3
            issues.append("正文缺少参考链接小节。")
            suggestions.append("在文末增加“参考链接”小节并列出来源。")

        if draft.content_plan_used:
            strengths.append("content_plan 文章可在元数据中保留事实风险，正文避免阅读提醒和报告腔。")
        elif draft.factual_warnings:
            strengths.append("包含事实风险或采用提醒。")
        else:
            factual_score -= 3
            completeness_score -= 3
            issues.append("缺少事实风险或阅读提醒。")
            suggestions.append("补充阅读提醒，说明文章仅基于当前调研资料，不替代实际测试。")

        missing_sections = self._missing_sections(
            draft.content_markdown,
            content_plan_used=draft.content_plan_used,
        )
        if missing_sections:
            deduction = min(12, len(missing_sections) * 2)
            structure_score -= deduction
            completeness_score -= min(8, len(missing_sections) * 1.5)
            issues.append(f"结构不完整，缺少或未明确呈现：{', '.join(missing_sections)}")
            if draft.content_plan_used:
                suggestions.append("保持自然段落推进，但要补足问题、能力、适合场景，并在文末保留项目地址。")
            else:
                suggestions.append("补齐开头、项目介绍、关注理由、核心亮点、适合人群、上手方式、小结和参考链接。")
        else:
            strengths.append("文章结构覆盖公众号推荐文的关键小节。")

        word_count = draft.word_count or self._count_text(draft.content_markdown)
        if word_count < 700:
            readability_score -= 3
            completeness_score -= 4
            issues.append(f"正文偏短，当前字数估算约 {word_count}。")
            suggestions.append("适当扩展项目定位、亮点、适合人群和采用提醒。")
        elif word_count > 2500:
            readability_score -= 2
            issues.append(f"正文偏长，当前字数估算约 {word_count}，公众号阅读负担较高。")
            suggestions.append("压缩重复背景和过细技术描述，保留读者判断所需信息。")
        else:
            strengths.append("篇幅基本适合公众号阅读。")

        if not draft.title or len(draft.title.strip()) < 8:
            title_score -= 6
            issues.append("标题信息量不足。")
            suggestions.append("标题应包含项目名和推荐角度。")
        if len(draft.title) > 42:
            title_score -= 3
            issues.append("标题偏长，移动端展示可能不够利落。")
            suggestions.append("压缩标题，突出项目名和核心读者收益。")

        if not any(marker in draft.content_markdown for marker in ["##", "- ", "。"]):
            readability_score -= 6
            issues.append("正文排版不清晰，缺少小节或列表。")
            suggestions.append("使用二级标题和短段落提升公众号可读性。")

        basic_info_terms = [
            note.full_name if note else draft.full_name,
            str(note.stars) if note and note.stars else "",
            note.language if note and note.language else "",
        ]
        if not any(term and term in draft.content_markdown for term in basic_info_terms):
            completeness_score -= 3
            issues.append("项目基本信息呈现不足。")
            suggestions.append("补充仓库名、主要语言、stars/forks 或 README 摘要中的可验证信息。")

        factual_score = max(0.0, factual_score)
        title_score = max(0.0, title_score)
        structure_score = max(0.0, structure_score)
        readability_score = max(0.0, readability_score)
        completeness_score = max(0.0, completeness_score)
        total_score = factual_score + title_score + structure_score + readability_score + completeness_score

        if not strengths:
            strengths.append("已生成可评审的文章初稿。")
        if not issues:
            issues.append("未发现明显硬伤，可继续人工精修标题和表达。")
        if not suggestions:
            suggestions.append("保持现有结构，发布前人工复核关键事实和链接。")

        return ArticleReview(
            full_name=draft.full_name or draft.repo_full_name or (note.full_name if note else ""),
            title=draft.title,
            total_score=round(total_score, 2),
            factual_score=round(factual_score, 2),
            title_score=round(title_score, 2),
            structure_score=round(structure_score, 2),
            readability_score=round(readability_score, 2),
            completeness_score=round(completeness_score, 2),
            strengths=self._dedupe(strengths),
            issues=self._dedupe(issues),
            revision_suggestions=self._dedupe(suggestions),
            pass_review=total_score >= self.pass_threshold,
            review_mode="fallback",
        )

    def _fallback_revision(
        self,
        draft: ArticleDraft,
        review: ArticleReview,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> FinalArticle:
        title = self._moderate_title(draft.title, note, angle)
        content = draft.content_markdown.strip()
        content = self._replace_high_risk_words(content)
        source_links = self._dedupe(
            draft.source_links
            + (angle.source_links if angle else [])
            + (note.source_links if note else [])
            + ([draft.html_url or note.html_url] if draft.html_url or note else [])
        )
        factual_warnings = self._dedupe(
            draft.factual_warnings
            + (angle.factual_warnings if angle else [])
            + (note.risks if note else [])
        )
        if not factual_warnings:
            factual_warnings = ["本文仅基于当前 GitHub 资料、调研笔记和文章初稿整理，采用前请继续核验 README、license、issues 与实际测试结果。"]

        if not content:
            content = self._minimal_article(title, draft, note, angle, source_links, factual_warnings)
        if not self._has_h1(content):
            content = f"# {title}\n\n{content}"
        content = self._ensure_missing_sections(content, draft, note, angle)
        content = self._ensure_final_markdown(
            title=title,
            content_markdown=content,
            source_links=source_links,
            factual_warnings=factual_warnings,
            content_plan_used=draft.content_plan_used,
        )
        summary = draft.summary or self._fallback_summary(draft, note, angle)

        return FinalArticle(
            full_name=review.full_name,
            html_url=draft.html_url or (note.html_url if note else ""),
            title=title,
            summary=self._truncate(summary, 220),
            content_markdown=content,
            cover_prompt=draft.cover_prompt or (angle.cover_prompt if angle else ""),
            source_links=source_links,
            factual_warnings=factual_warnings,
            review=review,
            revision_mode="fallback",
            word_count=self._count_text(content),
            generation_mode=draft.generation_mode,
            content_plan_used=draft.content_plan_used,
            narrative_pattern=draft.narrative_pattern,
            title_style=draft.title_style,
            article_style_notes=draft.article_style_notes,
            source_fact_ids=draft.source_fact_ids,
            writer_persona=draft.writer_persona,
            top_selling_points_used=draft.top_selling_points_used,
            practical_scenarios_used=draft.practical_scenarios_used,
        )

    def _final_from_draft(
        self,
        draft: ArticleDraft,
        review: ArticleReview,
        revision_mode: str,
    ) -> FinalArticle:
        content = self._ensure_final_markdown(
            title=draft.title,
            content_markdown=draft.content_markdown,
            source_links=draft.source_links,
            factual_warnings=draft.factual_warnings,
            content_plan_used=draft.content_plan_used,
        )
        return FinalArticle(
            full_name=review.full_name,
            html_url=draft.html_url,
            title=draft.title,
            summary=draft.summary,
            content_markdown=content,
            cover_prompt=draft.cover_prompt,
            source_links=draft.source_links,
            factual_warnings=draft.factual_warnings,
            review=review,
            revision_mode=revision_mode,
            word_count=self._count_text(content),
            generation_mode=draft.generation_mode,
            content_plan_used=draft.content_plan_used,
            narrative_pattern=draft.narrative_pattern,
            title_style=draft.title_style,
            article_style_notes=draft.article_style_notes,
            source_fact_ids=draft.source_fact_ids,
            writer_persona=draft.writer_persona,
            top_selling_points_used=draft.top_selling_points_used,
            practical_scenarios_used=draft.practical_scenarios_used,
        )

    def _review_system_prompt(self) -> str:
        return (
            "你是一位严格的技术公众号编辑。你要评审一篇 GitHub 开源项目推荐文章。"
            "你的任务不是夸奖文章，而是检查事实是否可靠、标题是否过度、结构是否完整、"
            "读者是否容易理解。你必须基于给定资料评审，不得引入外部事实。只输出严格 JSON。"
        )

    def _review_user_prompt(
        self,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> str:
        payload = {
            "article_draft": self._model_dump(draft),
            "repo_research_note": self._model_dump(note) if note else None,
            "topic_angle": self._model_dump(angle) if angle else None,
            "scoring_rule": {
                "total": 100,
                "factual_score": 30,
                "title_score": 20,
                "structure_score": 20,
                "readability_score": 15,
                "completeness_score": 15,
                "pass_threshold": self.pass_threshold,
            },
            "required_sections": [
                "content_plan_used=true 时不强制旧二级标题，但必须覆盖：项目解决的问题、能力、适合谁、具体使用场景，并在文末保留一个项目地址。不要要求参考链接小节。"
                if draft.content_plan_used
                else "开头、项目是什么、为什么值得关注、核心亮点、适合谁、上手方式、小结、参考链接"
            ],
        }
        return (
            "请评审以下公众号文章初稿，严格输出 JSON object，字段为："
            "total_score, factual_score, title_score, structure_score, readability_score, "
            "completeness_score, strengths, issues, revision_suggestions, pass_review。"
            "分数必须符合：事实 30、标题 20、结构 20、可读性 15、完整度 15，总分 100。"
            "重点检查是否只基于资料、是否保留可核验来源元数据、是否有夸张无法验证表述、结构是否完整。"
            "如果 article_draft.content_plan_used=true，不要因为没有固定旧二级标题而扣结构分。资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _revision_system_prompt(self) -> str:
        return (
            "你是一位技术公众号资深编辑。你要根据评审意见优化 GitHub 开源项目推荐文章。"
            "只能基于给定 research、angle 和 article draft 改写，不得新增无法验证事实。"
            "content_plan 文章正文只保留项目地址，不要新增参考链接长列表；旧路径文章保留参考链接。"
            "保持公众号推荐风格，避免夸大。只输出严格 JSON。"
        )

    def _revision_user_prompt(
        self,
        draft: ArticleDraft,
        review: ArticleReview,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> str:
        payload = {
            "article_draft": self._model_dump(draft),
            "review": self._model_dump(review),
            "repo_research_note": self._model_dump(note) if note else None,
            "topic_angle": self._model_dump(angle) if angle else None,
        }
        if draft.content_plan_used:
            structure_rule = (
                "content_markdown 必须是 Markdown，但不要改回固定旧小节模板。保持自然段落或少量自然小标题，"
                "覆盖项目解决的问题、它能做什么、适合谁、具体使用场景，并在文末只保留一个项目地址。不要写参考链接列表或阅读提醒。"
            )
        else:
            structure_rule = (
                "content_markdown 必须是 Markdown，包含开头、这个项目是什么、为什么值得关注、核心亮点、"
                "适合谁、如何快速了解或上手、小结、参考链接。"
            )
        return (
            "请根据 review.revision_suggestions 生成优化后的终稿。严格输出 JSON object，字段为："
            "title, summary, content_markdown, cover_prompt, source_links, factual_warnings。"
            f"{structure_rule}不得新增资料中没有的事实，不得编造安装命令、"
            "性能数据、融资、用户量或排名。必须保留 source_links，至少包含 GitHub 仓库链接。资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _ensure_missing_sections(
        self,
        content: str,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> str:
        missing = self._missing_sections(content, content_plan_used=draft.content_plan_used)
        if not missing:
            return content.strip() + "\n"

        if draft.content_plan_used:
            additions: list[str] = []
            if "问题、能力和适用场景" in missing:
                project_name = self._project_name(draft, note, angle)
                additions.append(
                    f"**更适合的使用场景：** {project_name} 适合作为技术选型前的候选项目继续验证，重点看它是否匹配当前团队的问题、集成方式和维护预期。"
                )
            if "项目地址" in missing:
                repo_url = draft.html_url or (note.html_url if note else "")
                if repo_url:
                    additions.append(f"项目地址：{repo_url}")
            if additions:
                content = f"{content.rstrip()}\n\n" + "\n\n".join(additions)
            return content.strip() + "\n"

        project_name = self._project_name(draft, note, angle)
        additions: list[str] = []
        for section in missing:
            if section == "开头":
                additions.append(
                    f"## 开头钩子\n\n如果你正在关注 GitHub 上的 AI / Agent 开源项目，{project_name} 值得放进候选清单里做进一步核验。"
                )
            elif section == "这个项目是什么":
                description = note.description if note and note.description else draft.summary
                additions.append(
                    f"## 这个项目是什么\n\n{project_name} 对应 GitHub 仓库 [{draft.full_name or (note.full_name if note else project_name)}]({draft.html_url or (note.html_url if note else '')})。根据现有资料，它的定位可以概括为：{description or '一个开源技术项目'}。"
                )
            elif section == "为什么值得关注":
                stars = f"目前调研资料记录约 {note.stars} stars。" if note and note.stars else ""
                additions.append(
                    f"## 为什么值得关注\n\n{stars}本文建议把它作为技术雷达候选项，继续从 README、release 和 issue 中核验实际适配度。"
                )
            elif section == "核心亮点":
                points = (angle.selling_points if angle else []) or (note.readme_key_points if note else [])
                additions.append("## 核心亮点\n\n" + "\n".join(self._markdown_bullets(points[:5])))
            elif section == "适合谁":
                readers = (angle.target_readers if angle else []) or ["AI 开发者", "开源项目关注者"]
                additions.append("## 适合谁\n\n" + "\n".join(self._markdown_bullets(readers)))
            elif section == "上手":
                repo_link = draft.html_url or (note.html_url if note else "")
                additions.append(
                    f"## 如何快速了解或上手\n\n建议先打开 GitHub 仓库：{repo_link or project_name}，从 README、文档入口、release 和 open issues 开始核验。除非资料中明确给出命令，否则不要仅凭二手摘要复制安装命令。"
                )
            elif section == "小结":
                additions.append(
                    f"## 小结\n\n{project_name} 更适合作为一个可继续调研的开源项目线索。发布或采用前，仍建议回到 GitHub 原始资料复核关键事实。"
                )
            elif section == "参考链接":
                continue
        if additions:
            content = f"{content.rstrip()}\n\n" + "\n\n".join(additions)
        return content.strip() + "\n"

    def _ensure_final_markdown(
        self,
        title: str,
        content_markdown: str,
        source_links: list[str],
        factual_warnings: list[str],
        content_plan_used: bool = False,
    ) -> str:
        content = content_markdown.strip()
        if not self._has_h1(content):
            content = f"# {title}\n\n{content}"
        if content_plan_used:
            repo_links = [link.rstrip("/") for link in source_links if "github.com" in link]
            repo_url = repo_links[0] if repo_links else ""
            content = re.sub(r"\n*项目地址：\s*https?://\S+\s*$", "", content, flags=re.MULTILINE).strip()
            if repo_url:
                content = f"{content.rstrip()}\n\n项目地址：{repo_url}"
            return content.strip() + "\n"
        if factual_warnings and "阅读提醒" not in content and "事实风险" not in content:
            warning_lines = "\n".join(self._markdown_bullets(factual_warnings))
            if "## 小结" in content:
                content = content.replace("## 小结", f"## 阅读提醒\n\n{warning_lines}\n\n## 小结", 1)
            else:
                content = f"{content.rstrip()}\n\n## 阅读提醒\n\n{warning_lines}"
        if source_links and "参考链接" not in content:
            link_lines = "\n".join(self._markdown_bullets(source_links))
            content = f"{content.rstrip()}\n\n## 参考链接\n\n{link_lines}"
        elif source_links:
            existing_missing = [link for link in source_links if link not in content]
            if existing_missing:
                link_lines = "\n".join(self._markdown_bullets(existing_missing))
                content = f"{content.rstrip()}\n\n{link_lines}"
        return content.strip() + "\n"

    def _minimal_article(
        self,
        title: str,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
        source_links: list[str],
        factual_warnings: list[str],
    ) -> str:
        project_name = self._project_name(draft, note, angle)
        summary = draft.summary or (note.readme_summary if note else "") or (angle.one_liner if angle else "")
        lines = [
            f"# {title}",
            "",
            "## 开头钩子",
            "",
            f"如果你正在关注 GitHub 上的开源 AI 项目，{project_name} 可以作为今天的一个观察样本。",
            "",
            "## 这个项目是什么",
            "",
            summary or "现有资料显示，这是一个需要继续回到 GitHub 仓库核验的开源项目。",
            "",
            "## 为什么值得关注",
            "",
            "它进入候选清单的原因来自当前调研资料，而不是额外推断。",
            "",
            "## 核心亮点",
            "",
        ]
        lines.extend(self._markdown_bullets((angle.selling_points if angle else []) or (note.readme_key_points if note else [])))
        lines.extend(["", "## 适合谁", ""])
        lines.extend(self._markdown_bullets((angle.target_readers if angle else []) or ["开源项目关注者"]))
        lines.extend(
            [
                "",
                "## 如何快速了解或上手",
                "",
                f"建议先阅读 GitHub 仓库和 README：{draft.html_url or (note.html_url if note else '')}",
                "",
                "## 阅读提醒",
                "",
            ]
        )
        lines.extend(self._markdown_bullets(factual_warnings))
        lines.extend(["", "## 小结", "", f"{project_name} 值得继续调研，但采用前仍需要结合 README、license、issues 和实际测试判断。", "", "## 参考链接", ""])
        lines.extend(self._markdown_bullets(source_links))
        return "\n".join(lines).strip() + "\n"

    def _missing_sections(self, content: str, content_plan_used: bool = False) -> list[str]:
        if content_plan_used:
            missing: list[str] = []
            if "项目地址：" not in content:
                missing.append("项目地址")
            capability_markers = ["能做", "能力", "场景", "适合", "解决", "问题"]
            if not any(marker in content for marker in capability_markers):
                missing.append("问题、能力和适用场景")
            return missing

        aliases = {
            "开头": ["开头", "开头钩子"],
            "这个项目是什么": ["这个项目是什么", "项目是什么"],
            "为什么值得关注": ["为什么值得关注", "值得关注"],
            "核心亮点": ["核心亮点", "亮点"],
            "适合谁": ["适合谁", "适合人群"],
            "上手": ["如何快速了解或上手", "上手", "快速了解"],
            "小结": ["小结", "总结"],
            "参考链接": ["参考链接", "来源链接"],
        }
        missing: list[str] = []
        for section, terms in aliases.items():
            if not any(term in content for term in terms):
                missing.append(section)
        return missing

    def _moderate_title(
        self,
        title: str,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> str:
        clean_title = self._replace_high_risk_words(title).strip()
        if clean_title != title:
            project_name = (angle.project_name if angle else "") or (note.full_name.split("/")[-1] if note else "")
            return f"值得关注的 GitHub 开源项目：{project_name or clean_title}"
        if len(clean_title) > 42:
            project_name = (angle.project_name if angle else "") or (note.full_name.split("/")[-1] if note else clean_title[:20])
            return f"值得关注的 GitHub 开源项目：{project_name}"
        return clean_title or "值得关注的 GitHub 开源项目"

    def _replace_high_risk_words(self, text: str) -> str:
        replacements = {
            "最强": "值得关注",
            "第一": "较受关注",
            "彻底取代": "在部分场景中辅助",
            "颠覆": "改变",
            "必火": "值得观察",
            "全网": "社区中",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text

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

    def _normalize_total_score(self, review: ArticleReview) -> float:
        total = (
            review.factual_score
            + review.title_score
            + review.structure_score
            + review.readability_score
            + review.completeness_score
        )
        if abs(total - review.total_score) > 3:
            return round(total, 2)
        return round(review.total_score, 2)

    def _clamp_score(self, value: Any, min_value: float, max_value: float) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = max_value
        return round(max(min_value, min(max_value, score)), 2)

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
            normalized = str(value).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _markdown_bullets(self, values: list[str]) -> list[str]:
        clean_values = [str(value).strip() for value in values if str(value).strip()]
        if not clean_values:
            return ["- 暂无可验证信息"]
        return [f"- {value}" for value in clean_values]

    def _has_h1(self, content: str) -> bool:
        return bool(re.search(r"^#\s+[^#\s].*$", content.strip(), flags=re.MULTILINE))

    def _count_text(self, value: str) -> int:
        return len(re.sub(r"\s+", "", value or ""))

    def _truncate(self, value: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _fallback_summary(
        self,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> str:
        project_name = self._project_name(draft, note, angle)
        description = (note.description if note else "") or (angle.one_liner if angle else "") or draft.title
        return f"{project_name} 是一个 GitHub 开源项目。本文基于当前调研资料评审并整理终稿，重点保留可核验事实、参考链接和采用提醒。{description}"

    def _project_name(
        self,
        draft: ArticleDraft,
        note: Optional[RepoResearchNote],
        angle: Optional[TopicAngle],
    ) -> str:
        if angle and angle.project_name:
            return angle.project_name
        full_name = (note.full_name if note else "") or draft.full_name or draft.repo_full_name or ""
        return full_name.split("/")[-1] if full_name else "该项目"

    def _model_dump(self, model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        if hasattr(model, "dict"):
            return model.dict()
        return dict(model)
