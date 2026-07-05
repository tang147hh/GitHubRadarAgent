from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import ArticleDraft, RepoResearchNote, TopicAngle, WriterPersona


class ArticleWriterService:
    """Generate WeChat-style Markdown article drafts from angles and research notes."""

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.warnings: list[str] = []

    def write_articles(
        self,
        angles: list[TopicAngle],
        research_notes: list[RepoResearchNote],
        top: int = 3,
        content_plans: list[dict] | None = None,
    ) -> list[ArticleDraft]:
        notes_by_name = {note.full_name: note for note in research_notes}
        plans_by_name = {
            str(plan.get("full_name") or ""): plan
            for plan in (content_plans or [])
            if isinstance(plan, dict)
        }
        drafts: list[ArticleDraft] = []

        for angle in angles[: max(0, top)]:
            note = notes_by_name.get(angle.full_name)
            if note is None:
                self.warnings.append(f"Research note not found for {angle.full_name}, skipped.")
                continue
            drafts.append(self.write_article(angle, note, plans_by_name.get(angle.full_name)))

        return drafts

    def write_article(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict | None = None,
    ) -> ArticleDraft:
        if content_plan:
            if self.llm_service is not None and self.llm_service.is_available():
                llm_draft = self._write_article_with_content_plan_llm(angle, note, content_plan)
                if llm_draft is not None:
                    self.used_llm = True
                    return llm_draft
            return self._fallback_article_from_content_plan(angle, note, content_plan)

        if self.llm_service is not None and self.llm_service.is_available():
            llm_draft = self._write_article_with_llm(angle, note)
            if llm_draft is not None:
                self.used_llm = True
                return llm_draft

        return self._fallback_article(angle, note)

    def _write_article_with_content_plan_llm(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> Optional[ArticleDraft]:
        content = self.llm_service.chat(
            system_prompt=self._content_plan_system_prompt(),
            user_prompt=self._content_plan_user_prompt(angle, note, content_plan),
            temperature=0.62,
        )
        draft = self._draft_from_content_plan_llm_content(content, angle, note, content_plan)
        if draft is None:
            return None
        style_issues = self._content_plan_style_issue_notes(draft.content_markdown)
        if style_issues:
            rewritten = self._rewrite_content_plan_article_with_llm(draft, angle, note, content_plan, style_issues)
            if rewritten is not None:
                draft = rewritten
            else:
                draft.article_style_notes = self._dedupe(draft.article_style_notes + style_issues)
        if draft.word_count > 1750:
            compressed = self._compress_content_plan_article_with_llm(draft, angle, note, content_plan)
            if compressed is not None:
                return compressed
            self.warnings.append(
                f"LLM content-plan article for {note.full_name} exceeded target length, fallback used."
            )
            return None
        return draft

    def _write_article_with_llm(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
    ) -> Optional[ArticleDraft]:
        content = self.llm_service.chat(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(angle, note),
            temperature=0.65,
        )
        draft = self._draft_from_llm_content(content, angle, note)
        if draft is None:
            return None
        if draft.word_count > 1650:
            compressed = self._compress_article_with_llm(draft, angle, note)
            if compressed is not None:
                return compressed
            self.warnings.append(
                f"LLM article for {note.full_name} exceeded target length, fallback used."
            )
            return None
        return draft

    def _draft_from_llm_content(
        self,
        content: str,
        angle: TopicAngle,
        note: RepoResearchNote,
    ) -> Optional[ArticleDraft]:
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            source_links = self._dedupe(
                [str(link) for link in payload.get("source_links", [])]
                + angle.source_links
                + note.source_links
                + [note.html_url]
            )
            factual_warnings = self._dedupe(
                [str(item) for item in payload.get("factual_warnings", [])]
                + angle.factual_warnings
                + note.risks
            )
            draft = ArticleDraft(
                full_name=note.full_name,
                repo_full_name=note.full_name,
                html_url=note.html_url,
                title=str(payload.get("title") or self._first_title(angle)),
                title_candidates=angle.title_candidates,
                summary=self._truncate(str(payload.get("summary") or ""), 220),
                content_markdown=str(payload.get("content_markdown") or "").strip(),
                cover_prompt=str(payload.get("cover_prompt") or angle.cover_prompt),
                source_links=source_links,
                factual_warnings=factual_warnings,
                word_count=0,
                generation_mode="llm",
            )
            draft = self._ensure_article_completeness(draft, angle, note)
            draft.word_count = self._count_text(draft.content_markdown)
            return draft
        except Exception as exc:
            self.warnings.append(f"LLM JSON parse failed for {note.full_name}, fallback used: {exc}")
            return None

    def _draft_from_content_plan_llm_content(
        self,
        content: str,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> Optional[ArticleDraft]:
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            brief = self._plan_brief(content_plan)
            title = self._select_title_from_brief(brief, str(payload.get("title") or self._first_title(angle)), content_plan, note)
            source_links = self._dedupe(
                [str(link) for link in payload.get("source_links", [])]
                + self._plan_source_links(content_plan)
                + angle.source_links
                + note.source_links
                + [note.html_url]
            )
            factual_warnings = self._dedupe(
                [str(item) for item in payload.get("factual_warnings", [])]
                + self._plan_warnings(content_plan)
                + angle.factual_warnings
                + note.risks
            )
            draft = ArticleDraft(
                full_name=note.full_name,
                repo_full_name=note.full_name,
                html_url=note.html_url,
                title=title,
                title_candidates=self._brief_title_candidates(brief) or angle.title_candidates,
                summary=self._truncate(str(payload.get("summary") or ""), 220),
                content_markdown=str(payload.get("content_markdown") or "").strip(),
                cover_prompt=str(payload.get("cover_prompt") or angle.cover_prompt),
                source_links=source_links,
                factual_warnings=factual_warnings,
                word_count=0,
                generation_mode="llm_content_plan",
                content_plan_used=True,
                narrative_pattern=self._narrative_pattern(brief),
                title_style=self._title_style(brief),
                article_style_notes=self._string_list(payload.get("article_style_notes")) + self._style_notes(content_plan),
                source_fact_ids=self._fact_ids(payload.get("source_fact_ids"), content_plan),
                writer_persona=self._writer_persona(content_plan),
                top_selling_points_used=self._points_used(
                    payload.get("top_selling_points_used"),
                    self._field(self._plan_appeal(content_plan), "top_selling_points"),
                ),
                practical_scenarios_used=self._points_used(
                    payload.get("practical_scenarios_used"),
                    self._field(self._plan_appeal(content_plan), "practical_scenarios"),
                ),
            )
            draft = self._ensure_content_plan_article_completeness(draft, angle, note, content_plan)
            draft.word_count = self._count_text(draft.content_markdown)
            return draft
        except Exception as exc:
            self.warnings.append(f"LLM content-plan JSON parse failed for {note.full_name}, fallback used: {exc}")
            return None

    def _compress_article_with_llm(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
    ) -> Optional[ArticleDraft]:
        content = self.llm_service.chat(
            system_prompt=self._system_prompt(),
            user_prompt=self._compression_prompt(draft, angle, note),
            temperature=0.35,
        )
        compressed = self._draft_from_llm_content(content, angle, note)
        if compressed is None:
            return None
        if compressed.word_count > 1650:
            self.warnings.append(
                f"LLM compressed article for {note.full_name} is still too long: {compressed.word_count}."
            )
            return None
        return compressed

    def _compress_content_plan_article_with_llm(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> Optional[ArticleDraft]:
        content = self.llm_service.chat(
            system_prompt=self._content_plan_system_prompt(),
            user_prompt=self._content_plan_compression_prompt(draft, angle, note, content_plan),
            temperature=0.32,
        )
        compressed = self._draft_from_content_plan_llm_content(content, angle, note, content_plan)
        if compressed is None:
            return None
        if compressed.word_count > 1750:
            self.warnings.append(
                f"LLM compressed content-plan article for {note.full_name} is still too long: {compressed.word_count}."
            )
            return None
        return compressed

    def _rewrite_content_plan_article_with_llm(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
        style_issues: list[str],
    ) -> Optional[ArticleDraft]:
        content = self.llm_service.chat(
            system_prompt=self._content_plan_system_prompt(),
            user_prompt=self._content_plan_style_rewrite_prompt(draft, angle, note, content_plan, style_issues),
            temperature=0.42,
        )
        rewritten = self._draft_from_content_plan_llm_content(content, angle, note, content_plan)
        if rewritten is None:
            return None
        remaining = self._content_plan_style_issue_notes(rewritten.content_markdown)
        rewritten.article_style_notes = self._dedupe(
            rewritten.article_style_notes
            + [f"style_rewrite_triggered: {issue}" for issue in style_issues]
            + [f"style_issue_remaining: {issue}" for issue in remaining]
        )
        return rewritten

    def _fallback_article(self, angle: TopicAngle, note: RepoResearchNote) -> ArticleDraft:
        title = self._first_title(angle)
        source_links = self._dedupe(angle.source_links + note.source_links + [note.html_url])
        factual_warnings = self._dedupe(angle.factual_warnings + note.risks)
        project_name = angle.project_name or self._project_name(note)
        readme_summary = self._truncate(
            self._clean_text(note.readme_summary) or angle.one_liner or note.description or "",
            220,
        )
        description = self._truncate(
            self._clean_text(note.description or angle.one_liner or readme_summary),
            180,
        )

        why_points = self._dedupe(
            [
                f"GitHub stars 约 {note.stars}，forks 约 {note.forks}，已有较高开源关注度。"
                if note.stars
                else "",
                f"仓库主要语言为 {note.language}。" if note.language else "",
                f"Topics 覆盖 {', '.join(note.topics[:6])}。" if note.topics else "",
                f"最近 push 时间为 {note.pushed_at}，可作为活跃度参考。" if note.pushed_at else "",
                f"最近 release：{self._release_title(note.releases[0])}。"
                if note.releases
                else "",
            ]
        )
        highlight_points = self._limit_items(
            self._dedupe(angle.selling_points + note.readme_key_points),
            limit=4,
            item_limit=120,
        )
        if len(highlight_points) < 4:
            highlight_points.extend(self._limit_items(why_points, 4 - len(highlight_points), 100))
        readers = (angle.target_readers or ["AI 开发者", "开源项目关注者"])[:4]
        pain_points = self._limit_items(angle.reader_pain_points, limit=3, item_limit=100)
        warnings = self._limit_items(factual_warnings, limit=4, item_limit=140)

        lines = [
            f"# {title}",
            "",
            "## 开头钩子",
            "",
            self._truncate(
                angle.opening_hook
                or f"如果你最近在看 GitHub 上的 AI / Agent 开源项目，{project_name} 值得放进候选清单里认真研究。",
                220,
            ),
            "",
            "## 这个项目是什么",
            "",
            (
                f"{project_name} 是 GitHub 仓库 [{note.full_name}]({note.html_url}) 中的开源项目。"
                f"根据仓库描述，它的定位是：{description or '一个开源技术项目'}。"
            ),
            "",
            (
                f"从 README 摘要看，项目重点围绕：{readme_summary} "
                "这里需要注意，本文只基于当前调研资料做初步推荐，不额外推断 README 没有说明的能力。"
            ),
            "",
            "## 为什么值得关注",
            "",
        ]
        lines.extend(self._markdown_bullets(why_points))
        lines.extend(
            [
                "",
                (
                    f"这篇文章选择的推荐角度是：{angle.selected_angle}。"
                    "它适合先作为技术雷达中的候选项，而不是直接根据热度做采用决策。"
                ),
                "",
                "## 核心亮点",
                "",
            ]
        )
        lines.extend(self._markdown_bullets(highlight_points))
        lines.extend(["", "## 适合谁", ""])
        for reader in readers:
            lines.append(f"- {reader}：适合先从 README、release 和 issues 判断是否贴合自己的场景。")
        if pain_points:
            lines.extend(["", "它尤其对应这些常见需求："])
            lines.extend(self._markdown_bullets(pain_points))
        lines.extend(
            [
                "",
                "## 如何快速了解或上手",
                "",
                f"第一步建议直接打开 GitHub 仓库：[{note.full_name}]({note.html_url})，先看 README 的项目定位、Quick start 或文档入口。",
            ]
        )
        if note.releases:
            lines.append("如果你关心近期变化，可以查看 releases 页面。")
        if note.open_issues:
            lines.append(
                "如果你准备投入使用，也建议浏览 open issues，先确认是否存在与你场景相关的问题。"
            )
        lines.append("除非 README 已经明确给出安装命令，否则不要仅凭二手摘要复制命令上生产环境。")
        lines.extend(
            [
                "",
                "## 小结",
                "",
                (
                    f"{project_name} 的推荐价值在于：它把 {angle.one_liner or description or '项目能力'} "
                    "放在一个可公开追踪的 GitHub 仓库里，便于开发者从 README、release 和 issue 中继续核验。"
                    "如果你的需求与上面的读者场景相近，可以把它加入调研清单；如果涉及生产使用，仍建议结合 license、维护状态和实际测试结果再做判断。"
                ),
                "",
            ]
        )
        if factual_warnings:
            lines.extend(["当前需要留意的事实风险："])
            lines.extend(self._markdown_bullets(warnings))
            lines.append("")
        lines.extend(["## 参考链接", ""])
        lines.extend(self._markdown_bullets(source_links))
        content_markdown = "\n".join(lines).strip() + "\n"

        summary = self._fallback_summary(angle, note, description, readme_summary)
        return ArticleDraft(
            full_name=note.full_name,
            repo_full_name=note.full_name,
            html_url=note.html_url,
            title=title,
            title_candidates=angle.title_candidates,
            summary=summary,
            content_markdown=content_markdown,
            cover_prompt=angle.cover_prompt,
            source_links=source_links,
            factual_warnings=factual_warnings,
            word_count=self._count_text(content_markdown),
            generation_mode="fallback",
        )

    def _fallback_article_from_content_plan(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> ArticleDraft:
        appeal = self._plan_appeal(content_plan)
        if appeal:
            return self._fallback_article_from_project_appeal(angle, note, content_plan)
        return self._fallback_article_from_content_plan_legacy(angle, note, content_plan)

    def _fallback_article_from_project_appeal(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> ArticleDraft:
        brief = self._plan_brief(content_plan)
        insight = self._plan_insight(content_plan)
        appeal = self._plan_appeal(content_plan)
        impact = self._plan_impact(content_plan)
        custom_direction = self._custom_direction(content_plan)
        style_profile = self._style_reference_profile(content_plan)
        wechat_pattern = self._plan_wechat_pattern(content_plan)
        title = self._select_title_from_brief(brief, self._first_title(angle), content_plan, note)
        title = self._style_reference_title(title, style_profile, self._project_name(note))
        source_links = self._dedupe(
            self._plan_source_links(content_plan) + angle.source_links + note.source_links + [note.html_url]
        )
        factual_warnings = self._dedupe(
            self._plan_warnings(content_plan) + angle.factual_warnings + note.risks
        )
        project_name = (
            self._clean_text(self._field(appeal, "project_name", ""))
            or angle.project_name
            or self._project_name(note)
        )
        top_selling_points = self._string_list(self._field(appeal, "top_selling_points"))[:3]
        practical_scenarios = self._string_list(self._field(appeal, "practical_scenarios"))[:3]
        feature_advantages = self._feature_advantage_items(appeal)
        impact_outcomes = self._string_list(self._field(impact, "concrete_outcomes"))[:3]
        impact_examples = self._string_list(self._field(impact, "usage_examples"))[:3]
        standout_points = self._string_list(self._field(insight, "standout_points"))[:3]
        use_cases = self._string_list(self._field(insight, "use_cases"))[:3]
        primary_hook = self._clean_text(self._field(appeal, "primary_hook", ""))
        appeal_summary = self._clean_text(self._field(appeal, "appeal_summary", ""))
        problem = (
            self._brief_text(insight, "problem_solved")
            or self._brief_text(brief, "recommended_angle")
            or angle.one_liner
            or note.description
            or "一个具体的开发效率问题"
        )
        scenario = (
            practical_scenarios[0]
            if practical_scenarios
            else (use_cases[0] if use_cases else "评估开源工具、搭建开发工作流或给团队找候选方案")
        )
        pattern_hook = self._clean_text(self._field(wechat_pattern, "lead_hook", ""))
        intro = pattern_hook or primary_hook or (
            f"有时候点开一个开源项目，不是因为它的 star 数多夸张，而是它刚好撞上你手头的麻烦。"
            f"如果你最近也在做{scenario}，{project_name} 值得顺手打开看一眼。"
        )
        if custom_direction.get("writing_perspective") and custom_direction.get("core_angle"):
            intro = (
                f"从{custom_direction['writing_perspective']}看，{project_name} 最先打动人的地方不是参数表，"
                f"而是{custom_direction['core_angle']}。"
            )
        intro = self._style_reference_intro(intro, style_profile, project_name, scenario)
        intro = self._trim_project_definition_intro(intro, project_name)

        pattern_effect_points = self._string_list(self._field(wechat_pattern, "required_effect_points"))[:3]
        pattern_examples = self._string_list(self._field(wechat_pattern, "required_examples"))[:3]
        focus_points = self._dedupe(top_selling_points + standout_points + pattern_effect_points + angle.selling_points)[:3]
        if not focus_points:
            focus_points = [self._brief_text(insight, "core_value") or problem]
        advantage_paragraphs = self._advantage_paragraphs(
            project_name=project_name,
            focus_points=focus_points[:3],
            feature_advantages=feature_advantages,
            practical_scenarios=practical_scenarios,
        )
        lines = [
            f"# {title}",
            "",
            self._truncate(intro, 260),
            "",
            self._truncate(
                appeal_summary
                or f"我会把 {project_name} 当成一个项目分享来看：它的重点不是把功能铺满，而是围绕“{problem}”给出一个可以点开验证的开源实现。",
                260,
            ),
            "",
        ]
        if practical_scenarios:
            lines.append(
                "比较容易产生使用冲动的场景，是"
                + "；".join(self._limit_items(practical_scenarios, 2, 70))
                + "。这类时候读者在意的不是功能名有多少，而是它能不能少一点重复搭建和来回切换。"
            )
            lines.append("")

        impact_paragraphs = self._impact_paragraphs(project_name, impact, pattern_examples)
        if impact_paragraphs:
            lines.extend(impact_paragraphs)
            lines.append("")

        if advantage_paragraphs:
            if len(advantage_paragraphs) >= 2:
                lines.extend(["## 我会先看这几处", ""])
            for paragraph in advantage_paragraphs:
                lines.extend([paragraph, ""])

        if len(practical_scenarios) > 2:
            lines.extend(
                [
                    f"换句话说，它适合先放进“{practical_scenarios[2]}”这类待验证场景里，而不是一上来就当成万能方案。",
                    "",
                ]
            )

        if pattern_examples:
            lines.extend(self._wechat_example_paragraphs(project_name, pattern_examples, wechat_pattern))
            if lines[-1] != "":
                lines.append("")

        author_note = self._valuable_author_note(content_plan)
        if author_note:
            lines.extend([author_note, ""])

        takeaway = self._brief_text(brief, "reader_takeaway")
        if takeaway:
            lines.extend([f"我的判断是：{takeaway}", ""])
        else:
            lines.extend(
                [
                    f"所以这篇不打算把 {project_name} 写成教程。更合理的打开方式，是把它当作一个值得试读代码和文档的候选项目：如果你的场景和上面几处吻合，再继续往下看实现细节。",
                    "",
                ]
            )

        repo_url = self._repo_url(note)
        lines.append(f"项目地址：{repo_url}")
        content_markdown = "\n".join(lines).strip() + "\n"
        writer_persona = self._writer_persona(content_plan)
        style_notes = self._dedupe(
            self._style_notes(content_plan)
            + self._direction_style_notes(custom_direction)
            + ["使用者视角 Writer：围绕 ProjectAppeal 的 2-3 个主卖点写成项目分享"]
            + ["已接入 ProjectImpact：正文需要展开项目作用、效果和具体提升"]
            + [f"WechatArticlePattern：{self._field(wechat_pattern, 'pattern_type', '-')}/{self._field(wechat_pattern, 'opening_strategy', '-')}"]
            + [f"效果结果：{item}" for item in impact_outcomes[:2]]
            + [f"使用例子：{item}" for item in impact_examples[:2]]
            + self._content_plan_style_issue_notes(content_markdown)
        )
        draft = ArticleDraft(
            full_name=note.full_name,
            repo_full_name=note.full_name,
            html_url=note.html_url,
            title=title,
            title_candidates=self._brief_title_candidates(brief) or angle.title_candidates,
            summary=self._truncate(
                f"{project_name} 更适合从 {scenario} 这类场景切入，重点看 {self._truncate('、'.join(focus_points[:2]), 90)}。",
                220,
            ),
            content_markdown=content_markdown,
            cover_prompt=angle.cover_prompt,
            source_links=source_links,
            factual_warnings=factual_warnings,
            word_count=self._count_text(content_markdown),
            generation_mode="fallback_content_plan",
            content_plan_used=True,
            narrative_pattern=self._narrative_pattern(brief),
            title_style=self._title_style(brief),
            article_style_notes=style_notes,
            source_fact_ids=list(range(1, min(len(self._plan_facts(content_plan)), 8) + 1)),
            writer_persona=writer_persona,
            top_selling_points_used=focus_points[:3],
            practical_scenarios_used=practical_scenarios,
        )
        return self._ensure_content_plan_article_completeness(draft, angle, note, content_plan)

    def _fallback_article_from_content_plan_legacy(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> ArticleDraft:
        brief = self._plan_brief(content_plan)
        insight = self._plan_insight(content_plan)
        appeal = self._plan_appeal(content_plan)
        title = self._select_title_from_brief(brief, self._first_title(angle), content_plan, note)
        source_links = self._dedupe(
            self._plan_source_links(content_plan) + angle.source_links + note.source_links + [note.html_url]
        )
        factual_warnings = self._dedupe(
            self._plan_warnings(content_plan) + angle.factual_warnings + note.risks
        )
        project_name = angle.project_name or self._project_name(note)
        paragraph_plan = self._brief_list(brief, "paragraph_plan") or self._brief_list(brief, "suggested_structure")
        facts = self._publishable_fact_claims(content_plan)
        must_include = self._brief_list(brief, "must_include")
        use_cases = self._string_list(self._field(insight, "use_cases"))[:4]
        standout_points = self._string_list(self._field(insight, "standout_points"))[:5]
        top_selling_points = self._string_list(self._field(appeal, "top_selling_points"))[:3]
        practical_scenarios = self._string_list(self._field(appeal, "practical_scenarios"))[:3]
        feature_advantages = self._feature_advantage_lines(appeal)[:5]
        primary_hook = self._clean_text(self._field(appeal, "primary_hook", ""))
        appeal_summary = self._clean_text(self._field(appeal, "appeal_summary", ""))
        adoption_notes = self._string_list(self._field(insight, "adoption_notes"))[:4]
        author_note = self._author_note(content_plan)
        scenario = (
            self._brief_text(brief, "target_reader")
            or "、".join(self._string_list(self._field(insight, "ideal_users"))[:2])
            or ", ".join(angle.target_readers[:2])
            or "正在评估开源工具的技术团队"
        )
        problem = (
            self._brief_text(brief, "recommended_angle")
            or self._brief_text(insight, "problem_solved")
            or self._brief_text(insight, "core_value")
            or angle.selected_angle
            or angle.one_liner
            or note.description
        )
        reader_takeaway = self._brief_text(brief, "reader_takeaway") or "先判断它是否值得进入你的技术调研清单。"
        opening = primary_hook or self._opening_paragraph(brief, angle, project_name, problem)

        lines = [
            f"# {title}",
            "",
            self._truncate(opening, 240),
            "",
            appeal_summary
            or f"{project_name} 值得被单独拿出来看，不是因为它适合被写成热闹的项目摘要，而是因为它解决的问题比较清楚：{self._truncate(self._brief_text(insight, 'problem_solved') or problem, 180)}",
            "",
            "它最适合被放进这些场景里观察：",
            "",
        ]
        scene_points = self._dedupe(practical_scenarios + use_cases + angle.reader_pain_points + must_include)[:4]
        lines.extend(self._markdown_bullets(scene_points or [f"{scenario} 可以把它作为候选方案继续验证。"]))
        lines.extend(["", "真正值得先看的，是这两三点：", ""])
        highlight_points = self._dedupe(
            top_selling_points
            + feature_advantages
            + standout_points
            + angle.selling_points
            + facts
            + note.readme_key_points
        )
        lines.extend(self._markdown_bullets(self._limit_items(highlight_points, 4, 170)))
        if author_note:
            lines.extend(["", author_note])
        if paragraph_plan:
            natural_plan = "；".join(self._limit_items(paragraph_plan, 3, 60))
            lines.extend(["", f"如果要进一步评估，可以按这个脉络看：{natural_plan}。"])
        lines.extend(
            [
                "",
                f"如果你是{scenario}，这篇分享的重点不是把所有功能都讲一遍，而是帮你快速判断：{reader_takeaway}",
                "",
                f"读完之后，最自然的下一步是点开 {project_name} 的项目页，看它的实现方式和你的场景是否对得上。",
                "",
            ]
        )
        if factual_warnings:
            lines.extend(["使用前可以顺手留意：", ""])
            lines.extend(self._markdown_bullets(self._limit_items(adoption_notes + factual_warnings, 4, 150)))
        else:
            lines.extend(["使用前可以顺手留意：", ""])
            lines.extend(self._markdown_bullets(adoption_notes or ["采用前仍建议确认 license、维护状态、issue 反馈和实际集成成本。"]))
        lines.extend(["", "参考链接：", ""])
        lines.extend(self._markdown_bullets(self._article_reference_links(source_links)))

        content_markdown = "\n".join(lines).strip() + "\n"
        draft = ArticleDraft(
            full_name=note.full_name,
            repo_full_name=note.full_name,
            html_url=note.html_url,
            title=title,
            title_candidates=self._brief_title_candidates(brief) or angle.title_candidates,
            summary=self._truncate(
                f"{project_name} 面向 {scenario}，重点解决 {problem}。{reader_takeaway}",
                220,
            ),
            content_markdown=content_markdown,
            cover_prompt=angle.cover_prompt,
            source_links=source_links,
            factual_warnings=factual_warnings,
            word_count=self._count_text(content_markdown),
            generation_mode="fallback_content_plan",
            content_plan_used=True,
            narrative_pattern=self._narrative_pattern(brief),
            title_style=self._title_style(brief),
            article_style_notes=self._style_notes(content_plan),
            source_fact_ids=list(range(1, min(len(self._plan_facts(content_plan)), 8) + 1)),
        )
        return self._ensure_content_plan_article_completeness(draft, angle, note, content_plan)

    def _system_prompt(self) -> str:
        return (
            "你是一位技术公众号作者，擅长写 GitHub 开源项目推荐文章。你的任务是把一个真实"
            "开源项目写成有吸引力、可读、克制、不夸大的公众号文章。你必须严格基于给定资料，"
            "不得编造项目功能、用户数据、融资信息、性能数据或作者背景。所有事实判断都要能从"
            "资料中找到依据。只输出严格 JSON，其中 content_markdown 字段为 Markdown 正文。"
        )

    def _content_plan_system_prompt(self) -> str:
        return (
            "你是一名中文技术公众号作者，也是一名经常折腾开源项目的程序员。你写的不是 README 摘要，"
            "不是项目说明书，也不是教程。你要像一个真实使用者/程序员一样，把这个项目为什么有意思、"
            "优势在哪里、适合什么场景讲给读者听。文章要有判断、有节奏、有具体场景，但不能编造事实。\n\n"
            "必须遵守：\n"
            "- 不要写成教程，不要逐步教安装和使用\n"
            "- 不要罗列所有功能\n"
            "- 不要固定使用“这个项目是什么 / 核心亮点 / 适合谁 / 小结”\n"
            "- 不要写“根据 README”\n"
            "- 不要堆参考链接\n"
            "- 不要写阅读提醒\n"
            "- 不要写“数据可能变化、需注明截止日期”\n"
            "- 不要展开普通作者的资料卡\n"
            "- 可以有轻微主观判断，但必须来自事实卡和项目理解\n"
            "- 文章目标是让读者产生兴趣并愿意点开项目地址\n\n"
            "只输出严格 JSON，字段为：title, summary, content_markdown, cover_prompt, source_links, "
            "factual_warnings, article_style_notes, source_fact_ids, top_selling_points_used, practical_scenarios_used。"
        )

    def _user_prompt(self, angle: TopicAngle, note: RepoResearchNote) -> str:
        source_payload = {
            "project_basic_info": {
                "full_name": note.full_name,
                "description": note.description,
            },
            "github_link": note.html_url,
            "stars": note.stars,
            "forks": note.forks,
            "language": note.language,
            "topics": note.topics,
            "license": note.license_name,
            "pushed_at": note.pushed_at,
            "readme_summary": note.readme_summary,
            "readme_key_points": note.readme_key_points,
            "releases": note.releases,
            "open_issues": note.open_issues,
            "risks": note.risks,
            "selected_angle": angle.selected_angle,
            "one_liner": angle.one_liner,
            "target_readers": angle.target_readers,
            "reader_pain_points": angle.reader_pain_points,
            "selling_points": angle.selling_points,
            "title_candidates": [
                self._model_dump_title(candidate) for candidate in angle.title_candidates
            ],
            "opening_hook": angle.opening_hook,
            "article_outline": angle.article_outline,
            "source_links": self._dedupe(angle.source_links + note.source_links + [note.html_url]),
        }
        return (
            "请基于以下资料生成一篇公众号爆款推荐文章初稿。必须严格输出 JSON object，字段为："
            "title, summary, content_markdown, cover_prompt, source_links, factual_warnings。"
            "标题使用 title_candidates 中最适合的一个，可轻微改写。正文 content_markdown 使用 Markdown，"
            "约 900-1300 中文字，写成“项目种草 + 使用场景 + 具体效果 + 轻口语判断”的项目分享。"
            "不要固定使用“开头钩子/这个项目是什么/核心亮点/适合谁/小结/参考链接”这类小节；"
            "重点展开至少 2 个具体效果或使用例子，每个重点功能都要写清解决什么麻烦、用户看到什么变化。"
            "结尾只保留项目地址，不堆参考链接。"
            "不要写“本文由 AI 生成”。不要使用无法验证的夸张表述，如“全网最强”“彻底颠覆”“必将取代”。"
            "不要写“根据 README”“资料显示”“本文将从以下几个方面”“综上”。"
            "不要编造安装命令，除非 README 关键点中明确出现。资料如下：\n"
            f"{json.dumps(source_payload, ensure_ascii=False, indent=2)}"
        )

    def _content_plan_user_prompt(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> str:
        brief = self._plan_brief(content_plan)
        appeal = self._plan_appeal(content_plan)
        impact = self._plan_impact(content_plan)
        narrative_strategy = self._field(brief, "narrative_strategy")
        title_strategy = self._field(brief, "title_strategy")
        writer_persona = self._writer_persona(content_plan)
        custom_direction = self._custom_direction(content_plan)
        style_reference_profile = self._style_reference_profile(content_plan)
        wechat_pattern = self._plan_wechat_pattern(content_plan)
        payload = {
            "repo_research_note": self._note_payload(note),
            "topic_angle": self._angle_payload(angle),
            "custom_article_direction": custom_direction,
            "style_reference_profile": style_reference_profile,
            "style_reference_rules": self._field(content_plan, "style_reference_rules") or {},
            "fact_cards": self._plan_facts(content_plan),
            "project_insight": self._plan_insight(content_plan),
            "project_appeal": appeal,
            "project_appeal_focus": {
                "primary_hook": self._field(appeal, "primary_hook"),
                "top_selling_points": self._field(appeal, "top_selling_points"),
                "feature_advantages": self._field(appeal, "feature_advantages"),
                "practical_scenarios": self._field(appeal, "practical_scenarios"),
            },
            "project_impact": impact,
            "project_impact_focus": {
                "core_effect": self._field(impact, "core_effect"),
                "concrete_outcomes": self._field(impact, "concrete_outcomes"),
                "usage_examples": self._field(impact, "usage_examples"),
                "user_benefits": self._field(impact, "user_benefits"),
                "measurable_signals": self._field(impact, "measurable_signals"),
                "article_expansion_points": self._field(impact, "article_expansion_points"),
                "weak_or_unknown_effects": self._field(impact, "weak_or_unknown_effects"),
            },
            "wechat_article_pattern": wechat_pattern,
            "wechat_pattern_usage": {
                "role": "决定公众号项目分享的表达方式和叙事节奏，不是固定小标题模板",
                "pattern_type_structure_hint": {
                    "concept_practice": "理念/趋势 -> 项目落地 -> 使用效果 -> 适合谁",
                    "hot_project": "热度/来头 -> 项目价值 -> 核心功能效果 -> 作者判断",
                    "demo_scene": "痛点 -> 具体 demo -> 功能特性 -> 适合场景",
                    "practical_tool": "日常麻烦 -> 工具怎么解决 -> 用起来爽在哪里 -> 项目地址",
                    "platform_workbench": "覆盖哪些工作流 -> 核心模块 -> 实际使用收益 -> 注意点",
                },
            },
            "editorial_brief": brief,
            "narrative_strategy": narrative_strategy,
            "title_strategy": title_strategy,
            "writer_persona": self._model_dump(writer_persona),
            "author_profile": self._field(content_plan, "author_profile"),
            "project_links": self._field(content_plan, "project_links"),
            "project_kind": self._field(content_plan, "project_kind"),
            "tool_use_cases": self._field(content_plan, "tool_use_cases") or [],
        }
        return (
            "请基于以下内容中间产物生成一篇中文技术公众号项目分享文章。\n\n"
            "写作要求：\n"
            "0. 用户方向优先级最高：如果 custom_article_direction 里有 target_reader、writing_perspective、core_angle、"
            "must_include、avoid_topics、tone_preferences、title_preferences、content_preferences，必须优先遵守；"
            "avoid_topics 里明确不要写/少写的内容不要出现在标题、小标题和主体展开中。\n"
            "0.1 如果存在 style_reference_profile：它只决定怎么写，不能决定写什么。只能参考语气、节奏、读者关系、"
            "开头方式、转场习惯和标题倾向；禁止复制参考文章原句、标题、独特比喻、段落结构、段落顺序或核心表达。"
            "最终文章必须围绕当前 GitHub 项目事实、ProjectAppeal、ProjectImpact 和用户 direction 重新组织。"
            "不要出现“参考文章中提到”“仿照某文”“仿写”等字样。\n"
            "1. 标题：优先使用 title_strategy 或 project_appeal 中最自然的标题方向，不使用旧模板，不以 star 数作为标题主卖点。\n"
            "2. 开头：优先使用 project_appeal.primary_hook。可以用程序员日常场景、痛点、使用冲动、工具发现感切入，不要第一段就堆项目定义。\n"
            "3. 正文：只重点写 2-3 个 project_appeal.top_selling_points；每个优势都要解释为什么读者会在意。可以穿插 practical_scenarios，"
            "但不要写完整教程，不要把 feature_advantages 原样列表化，不罗列所有功能。\n"
            "3.0 必须使用 wechat_article_pattern：pattern_type 决定文章的自然推进方式，opening_strategy 决定开头钩子，"
            "lead_hook 和 key_storyline 决定叙事节奏；required_effect_points 和 required_examples 必须自然展开。"
            "这些不是固定二级标题，不要把 pattern_type_structure_hint 原样写成小标题。\n"
            "3.1 必须使用 project_impact：正文至少有一段专门展开项目作用、效果或具体提升，但不要固定写成二级标题。"
            "如果 project_impact.concrete_outcomes 或 usage_examples 不为空，必须自然展开至少 2 个，不要只写“提升效率/降低成本/改善体验”。"
            "每个重点功能都要写清：功能是什么、解决什么麻烦、用户看到什么效果。"
            "对于投资/分析类项目，要具体写它在信息整理、投资逻辑梳理、报告生成、辅助判断上的效果；不要硬编收益率、投资结论或量化数据。"
            "即使输入资料出现收益率、买入/持有/卖出示例，也不要把它写成文章卖点；只写信息整理、分析框架、辅助判断和人工复核。"
            "不要写“我试了一下/我跑了一下/亲测”这类第一人称体验，除非输入资料明确提供了你的实际测试记录。"
            "不要编造或复述示例输出中的买入/持有/卖出比例、公司结论或收益率；如果需要举例，只能写成工作流层面的假设场景。"
            "对于工作流/AI 助手类项目，要用具体例子说明提升发生在哪里，例如写代码前整理上下文、多工具间保持任务连续、把临时想法转成可执行计划。\n"
            "4. 作者/组织：只有在 author_profile 明显有价值时轻描淡写；普通个人作者默认不写，不写 bio 原文。\n"
            "5. 结尾：自然收束，只保留一个项目地址。不要写参考链接列表，不写阅读提醒，不写风险提示小节，不写“数据截止日期”。\n\n"
            "允许轻口语判断，例如 wechat_article_pattern.allowed_colloquial_phrases 中的表达，但前后必须有具体依据，不能空夸。"
            "必须避开 wechat_article_pattern.banned_phrases。\n\n"
            "形式要求：正文可以没有二级标题；如果使用小标题，最多 0-2 个自然小标题。文章目标是项目分享，不是教程、不是功能说明、不是事实审查报告。"
            "字数建议 900-1600 中文字。如果没有足够事实，不要硬写。\n\n"
            "输出严格 JSON：title, summary, content_markdown, cover_prompt, source_links, factual_warnings, "
            "article_style_notes, source_fact_ids, top_selling_points_used, practical_scenarios_used。资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _content_plan_compression_prompt(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> str:
        payload = {
            "repo_research_note": self._note_payload(note),
            "topic_angle": self._angle_payload(angle),
            "custom_article_direction": self._custom_direction(content_plan),
            "style_reference_profile": self._style_reference_profile(content_plan),
            "style_reference_rules": self._field(content_plan, "style_reference_rules") or {},
            "wechat_article_pattern": self._plan_wechat_pattern(content_plan),
            "content_plan": content_plan,
            "current_title": draft.title,
            "current_summary": draft.summary,
            "current_content_markdown": draft.content_markdown,
            "source_links": draft.source_links,
            "factual_warnings": draft.factual_warnings,
        }
        return (
            "请把下面这篇中文技术公众号开源项目分享压缩到约 900-1600 中文字。保持自然表达，"
            "继续遵循 paragraph_plan、project_appeal.top_selling_points 和 project_impact.concrete_outcomes，不要改回固定小节模板，不要新增事实。"
            "继续遵循 wechat_article_pattern 的 pattern_type、lead_hook、required_effect_points 和 required_examples，"
            "保留程序员/使用者视角，不要变成教程、功能清单或事实审查报告；正文结尾只保留一个项目地址。"
            "不要写“本文由 AI 生成”。不要删除已经自然呈现的项目优势、读者兴趣点、项目作用和具体提升。"
            "如果正文已经展开 project_impact 的效果段落，压缩时保留至少两个具体结果或使用例子。"
            "必须继续遵守 custom_article_direction，尤其是 must_include、avoid_topics、tone_preferences 和 title_preferences。"
            "如果有 style_reference_profile，只保留其语气、节奏、读者关系和标题倾向；不得复制参考文章的句子、标题、独特比喻或结构。"
            "输出严格 JSON：title, summary, content_markdown, cover_prompt, source_links, factual_warnings, "
            "article_style_notes, source_fact_ids, top_selling_points_used, practical_scenarios_used。资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _content_plan_style_rewrite_prompt(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
        style_issues: list[str],
    ) -> str:
        payload = {
            "repo_research_note": self._note_payload(note),
            "topic_angle": self._angle_payload(angle),
            "content_plan": content_plan,
            "custom_article_direction": self._custom_direction(content_plan),
            "style_reference_profile": self._style_reference_profile(content_plan),
            "style_reference_rules": self._field(content_plan, "style_reference_rules") or {},
            "wechat_article_pattern": self._plan_wechat_pattern(content_plan),
            "writer_persona": self._model_dump(self._writer_persona(content_plan)),
            "style_issues": style_issues,
            "current_title": draft.title,
            "current_summary": draft.summary,
            "current_content_markdown": draft.content_markdown,
        }
        return (
            "请把当前文章重写成程序员/使用者视角的项目分享，只能使用给定资料，不新增事实。"
            "重点修复 style_issues：去掉教程化步骤、功能堆砌、报告腔、参考链接列表、阅读提醒和风险提示小节。"
            "重写时必须保留 wechat_article_pattern 的项目分享节奏：开头有钩子，先讲为什么值得看，再讲作用、效果和具体场景。"
            "保留 2-3 个 ProjectAppeal.top_selling_points，并解释读者为什么会在意；穿插 practical_scenarios，但不要写上手教程。"
            "保留或补足 ProjectImpact 的作用/效果/具体提升表达：至少自然展开两个 concrete_outcomes 或 usage_examples，不要只写“提升效率”。"
            "必须遵守 custom_article_direction：用户要求保留的重点不能删，用户要求避免的内容不要换个说法再写回来。"
            "如果有 style_reference_profile，只学习风格画像中的语气、节奏、开头方式和读者关系；"
            "禁止复制参考文章内容、原句、标题、独特比喻、段落顺序或核心表达，不要在正文提参考文章。"
            "结尾只保留一行项目地址。输出严格 JSON：title, summary, content_markdown, cover_prompt, source_links, "
            "factual_warnings, article_style_notes, source_fact_ids, top_selling_points_used, practical_scenarios_used。资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _compression_prompt(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
    ) -> str:
        source_links = self._dedupe(angle.source_links + note.source_links + [note.html_url])
        payload = {
            "full_name": note.full_name,
            "github_link": note.html_url,
            "title_candidates": [
                self._model_dump_title(candidate) for candidate in angle.title_candidates
            ],
            "source_links": source_links,
            "factual_warnings": self._dedupe(angle.factual_warnings + note.risks),
            "current_title": draft.title,
            "current_summary": draft.summary,
            "current_content_markdown": draft.content_markdown,
        }
        return (
            "请把下面这篇公众号开源项目推荐文章压缩到约 900-1300 中文字。"
            "必须保留 Markdown，但不要改回固定小节模板。"
            "只能删减和合并表达，不得添加新事实；正文结尾只保留项目地址。"
            "保留至少两个具体效果或使用例子，不要只说提升效率。"
            "严格输出 JSON object，字段为：title, summary, content_markdown, cover_prompt, "
            "source_links, factual_warnings。资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _ensure_article_completeness(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
    ) -> ArticleDraft:
        if not draft.content_markdown:
            return self._fallback_article(angle, note)
        if not self._has_h1_title(draft.content_markdown):
            draft.content_markdown = f"# {draft.title}\n\n{draft.content_markdown.strip()}\n"
        if note.html_url not in draft.source_links:
            draft.source_links.append(note.html_url)
        draft.content_markdown = self._cleanup_content_plan_style(draft.content_markdown, note)
        draft.content_markdown = self._ensure_project_address(draft.content_markdown, note.html_url)
        if not draft.summary:
            draft.summary = self._fallback_summary(angle, note, note.description or "", note.readme_summary)
        if not draft.cover_prompt:
            draft.cover_prompt = angle.cover_prompt
        return draft

    def _ensure_content_plan_article_completeness(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
        content_plan: dict,
    ) -> ArticleDraft:
        if not draft.content_markdown:
            return self._fallback_article_from_content_plan(angle, note, content_plan)
        if self._is_banned_title(draft.title) or self._generic_wechat_title(draft.title):
            draft.title = self._select_title_from_brief(self._plan_brief(content_plan), self._first_title(angle), content_plan, note)
        if not self._has_h1_title(draft.content_markdown):
            draft.content_markdown = f"# {draft.title}\n\n{draft.content_markdown.strip()}\n"
        else:
            draft.content_markdown = re.sub(r"^\s*#\s+.*$", f"# {draft.title}", draft.content_markdown, count=1, flags=re.MULTILINE)
        if note.html_url not in draft.source_links:
            draft.source_links.append(note.html_url)
        draft.source_links = self._dedupe(draft.source_links)
        draft.factual_warnings = self._dedupe(draft.factual_warnings)
        draft.content_markdown = self._sanitize_content_plan_markdown(draft.content_markdown)
        draft.content_markdown = self._cleanup_content_plan_style(draft.content_markdown, note)
        draft.content_markdown = self._ensure_impact_signal(draft.content_markdown, content_plan)
        draft.content_markdown = self._ensure_project_address(draft.content_markdown, note.html_url)
        style_issues = self._content_plan_style_issue_notes(draft.content_markdown)
        if style_issues:
            draft.article_style_notes = self._dedupe(draft.article_style_notes + style_issues)
        if not draft.summary:
            project_name = angle.project_name or self._project_name(note)
            brief = self._plan_brief(content_plan)
            draft.summary = self._truncate(
                f"{project_name} 的推荐角度是 {self._brief_text(brief, 'recommended_angle') or angle.selected_angle or note.description}。",
                220,
            )
        if not draft.cover_prompt:
            draft.cover_prompt = angle.cover_prompt
        if draft.writer_persona is None:
            draft.writer_persona = self._writer_persona(content_plan)
        appeal = self._plan_appeal(content_plan)
        if not draft.top_selling_points_used:
            draft.top_selling_points_used = self._string_list(self._field(appeal, "top_selling_points"))[:3]
        if not draft.practical_scenarios_used:
            draft.practical_scenarios_used = self._string_list(self._field(appeal, "practical_scenarios"))[:3]
        draft.article_style_notes = self._dedupe(draft.article_style_notes)
        draft.source_fact_ids = list(dict.fromkeys(draft.source_fact_ids))
        draft.word_count = self._count_text(draft.content_markdown)
        return draft

    def _generic_wechat_title(self, title: str) -> bool:
        compact = re.sub(r"\s+", "", title)
        return any(fragment in compact for fragment in ["值得顺手点开", "值得放进工具箱", "值得关注"])

    def _repair_missing_sections(
        self,
        draft: ArticleDraft,
        angle: TopicAngle,
        note: RepoResearchNote,
        missing_sections: list[str],
    ) -> ArticleDraft:
        fallback = self._fallback_article(angle, note)
        repaired = draft.content_markdown.strip()
        if not self._has_h1_title(repaired):
            repaired = f"# {draft.title}\n\n{repaired}"

        if "开头钩子" in missing_sections:
            repaired = self._insert_opening_hook_heading(repaired, draft.title)
            missing_sections = [section for section in missing_sections if section != "开头钩子"]

        for section in missing_sections:
            fallback_section = self._extract_markdown_section(fallback.content_markdown, section)
            if fallback_section:
                repaired = f"{repaired.rstrip()}\n\n{fallback_section.strip()}"

        draft.content_markdown = repaired.rstrip() + "\n"
        draft.source_links = self._dedupe(draft.source_links + fallback.source_links)
        draft.factual_warnings = self._dedupe(draft.factual_warnings + fallback.factual_warnings)
        draft.content_markdown = self._normalize_opening_headings(draft.content_markdown)
        return draft

    def _insert_opening_hook_heading(self, markdown: str, title: str) -> str:
        first_section = re.search(r"^##\s+", markdown, flags=re.MULTILINE)
        if not first_section:
            return f"# {title}\n\n## 开头钩子\n\n{markdown.lstrip('#').strip()}"

        intro = markdown[: first_section.start()].strip()
        rest = markdown[first_section.start() :].strip()
        if re.match(r"^##\s+开头(?!钩子).*$", rest, flags=re.MULTILINE):
            rest = re.sub(
                r"^##\s+开头(?!钩子).*$",
                "## 开头钩子",
                rest,
                count=1,
                flags=re.MULTILINE,
            )
            heading = intro or f"# {title}"
            return f"{heading}\n\n{rest}\n"
        lines = intro.splitlines()
        if lines and lines[0].startswith("#"):
            heading = lines[0].strip()
            lead = "\n".join(lines[1:]).strip()
        else:
            heading = f"# {title}"
            lead = intro
        if not lead:
            return f"{heading}\n\n## 开头钩子\n\n{rest}\n"
        return f"{heading}\n\n## 开头钩子\n\n{lead}\n\n{rest}\n"

    def _has_h1_title(self, markdown: str) -> bool:
        return bool(re.search(r"^#\s+[^#\s].*$", markdown.strip(), flags=re.MULTILINE))

    def _normalize_opening_headings(self, markdown: str) -> str:
        lines = markdown.strip().splitlines()
        normalized: list[str] = []
        seen_opening = False
        skip_blank_after_duplicate = False
        for line in lines:
            if self._is_opening_heading(line):
                if not seen_opening:
                    normalized.append("## 开头钩子")
                    seen_opening = True
                skip_blank_after_duplicate = True
                continue
            if skip_blank_after_duplicate and not line.strip():
                continue
            skip_blank_after_duplicate = False
            normalized.append(line)

        text = "\n".join(normalized)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    def _is_opening_heading(self, line: str) -> bool:
        return bool(re.match(r"^##\s+开头(?:钩子)?(?:[:：].*)?\s*$", line.strip()))

    def _extract_markdown_section(self, markdown: str, section_name: str) -> str:
        pattern = rf"(^##\s+{re.escape(section_name)}\s*$.*?)(?=^##\s+|\Z)"
        match = re.search(pattern, markdown, flags=re.MULTILINE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def _required_sections(self) -> list[str]:
        return [
            "开头钩子",
            "这个项目是什么",
            "为什么值得关注",
            "核心亮点",
            "适合谁",
            "如何快速了解或上手",
            "小结",
            "参考链接",
        ]

    def _ensure_reference_links(self, markdown: str, source_links: list[str]) -> str:
        links = self._dedupe(source_links)
        if not links:
            return markdown.strip() + "\n"

        content = markdown.rstrip()
        if "## 参考链接" not in content and "参考链接" not in content:
            link_lines = "\n".join(f"- {link}" for link in links)
            return f"{content}\n\n## 参考链接\n\n{link_lines}\n"

        missing_links = [link for link in links if link not in content]
        if not missing_links:
            return f"{content}\n"

        link_lines = "\n".join(f"- {link}" for link in missing_links)
        return f"{content}\n{link_lines}\n"

    def _sanitize_content_plan_markdown(self, markdown: str) -> str:
        text = markdown.strip()
        fixed_headings = {
            "这个项目是什么": "先看它解决的问题",
            "为什么值得关注": "为什么我会把它放进候选清单",
            "核心亮点": "真正值得看的是这几点",
            "适合谁": "更适合这些场景",
            "小结": "采用前的最后判断",
        }
        for old, new in fixed_headings.items():
            text = re.sub(rf"^##\s+{re.escape(old)}\s*$", f"## {new}", text, flags=re.MULTILINE)
        readme_count = text.count("根据 README")
        if readme_count > 1:
            first = True

            def replace_readme(match: re.Match[str]) -> str:
                nonlocal first
                if first:
                    first = False
                    return match.group(0)
                return "从现有资料看"

            text = re.sub("根据 README", replace_readme, text)
        text = text.replace("根据 README", "从项目资料看")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    def _cleanup_content_plan_style(self, markdown: str, note: RepoResearchNote) -> str:
        lines = markdown.strip().splitlines()
        cleaned: list[str] = []
        skip_section = False
        removed_project_address = False
        review_headings = {
            "参考链接",
            "来源链接",
            "阅读提醒",
            "风险提示",
            "当前需要留意的事实风险",
            "使用前注意事项",
            "如何快速了解或上手",
        }
        for line in lines:
            stripped = line.strip()
            heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
            if heading_match:
                heading = heading_match.group(1).strip()
                if heading in review_headings:
                    skip_section = True
                    continue
                skip_section = False
            if skip_section:
                continue
            if stripped.startswith("项目地址："):
                if removed_project_address:
                    continue
                removed_project_address = True
                cleaned.append(f"项目地址：{self._repo_url(note)}")
                continue
            if "数据截止日期" in stripped or "需注明" in stripped or "以官方为准" in stripped:
                continue
            if re.match(r"^\s*-\s+https?://", line):
                continue
            cleaned.append(line)
        text = "\n".join(cleaned).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    def _ensure_project_address(self, markdown: str, repo_url: str) -> str:
        clean_url = str(repo_url or "").strip().rstrip("/")
        content = re.sub(r"\n*项目地址：\s*https?://\S+\s*$", "", markdown.strip(), flags=re.MULTILINE).strip()
        if not clean_url:
            return content + "\n"
        return f"{content}\n\n项目地址：{clean_url}\n"

    def _content_plan_style_issue_notes(self, markdown: str) -> list[str]:
        issues: list[str] = []
        if self._looks_like_tutorial(markdown):
            issues.append("style_check: 教程化步骤偏多，已要求改成项目分享")
        if self._looks_like_feature_dump(markdown):
            issues.append("style_check: 连续列表偏多，已要求减少功能堆砌")
        if self._looks_like_report(markdown):
            issues.append("style_check: 报告腔/审稿提示残留，已要求清理")
        return issues

    def _looks_like_tutorial(self, markdown: str) -> bool:
        text = markdown.lower()
        markers = [
            "第一步",
            "第二步",
            "第三步",
            "安装",
            "配置",
            "运行命令",
            "quick start",
            "quickstart",
            "pip install",
            "npm install",
            "docker run",
            "使用步骤",
        ]
        hits = sum(1 for marker in markers if marker in text)
        numbered_steps = len(re.findall(r"^\s*\d+[.)、]\s+", markdown, flags=re.MULTILINE))
        code_commands = len(re.findall(r"```(?:bash|shell|sh)?|^\s{0,3}(?:pip|npm|pnpm|yarn|docker|uv|python)\s+", markdown, flags=re.MULTILINE | re.IGNORECASE))
        return hits >= 3 or numbered_steps >= 4 or code_commands >= 3

    def _looks_like_feature_dump(self, markdown: str) -> bool:
        consecutive = 0
        max_consecutive = 0
        bullet_count = 0
        paragraph_count = 0
        for line in markdown.splitlines():
            stripped = line.strip()
            if re.match(r"^[-*+]\s+", stripped):
                bullet_count += 1
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0
                if stripped and not stripped.startswith("#"):
                    paragraph_count += 1
        return max_consecutive > 6 or (bullet_count >= 10 and bullet_count > paragraph_count)

    def _looks_like_report(self, markdown: str) -> bool:
        markers = [
            "阅读提醒",
            "风险提示",
            "参考链接",
            "数据截止日期",
            "需注明",
            "以官方为准",
            "可能随时间变化",
            "当前需要留意的事实风险",
            "事实风险",
        ]
        hits = sum(1 for marker in markers if marker in markdown)
        return hits >= 2 or any(marker in markdown for marker in ["阅读提醒", "参考链接", "数据截止日期"])

    def _writer_persona(self, content_plan: dict) -> WriterPersona:
        brief = self._plan_brief(content_plan)
        existing = self._field(brief, "writer_persona")
        if isinstance(existing, WriterPersona):
            return existing
        if isinstance(existing, dict):
            try:
                return WriterPersona(**existing)
            except Exception:
                pass
        return WriterPersona(
            persona="programmer",
            voice="像一个经常折腾开发工具的程序员",
            article_goal="激发读者兴趣，解释项目优势，帮读者判断要不要点开",
            do=[
                "用真实使用场景或工具发现感开头",
                "只展开 2-3 个最值得看的项目优势",
                "解释读者为什么会在意这些优势",
                "结尾自然引导读者点开项目地址",
            ],
            dont=[
                "不要写完整教程",
                "不要罗列所有功能",
                "不要写参考链接列表或阅读提醒",
                "不要把普通作者资料卡展开成段落",
            ],
        )

    def _plan_wechat_pattern(self, content_plan: dict | None) -> dict[str, Any]:
        pattern = self._field(content_plan or {}, "wechat_pattern")
        if isinstance(pattern, dict):
            return pattern
        payload = self._model_dump(pattern)
        return payload if isinstance(payload, dict) else {}

    def _points_used(self, payload_value: Any, fallback_value: Any) -> list[str]:
        values = self._string_list(payload_value)
        if values:
            return values[:3]
        return self._string_list(fallback_value)[:3]

    def _feature_advantage_items(self, appeal: Any) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for item in self._field(appeal, "feature_advantages") or []:
            feature = self._clean_text(self._field(item, "feature", ""))
            advantage = self._clean_text(self._field(item, "advantage", ""))
            reader_interest = self._clean_text(self._field(item, "reader_interest", ""))
            evidence = self._clean_text(self._field(item, "evidence", ""))
            if feature or advantage or reader_interest:
                items.append(
                    {
                        "feature": feature,
                        "advantage": advantage,
                        "reader_interest": reader_interest,
                        "evidence": evidence,
                    }
                )
        return items

    def _advantage_paragraphs(
        self,
        project_name: str,
        focus_points: list[str],
        feature_advantages: list[dict[str, str]],
        practical_scenarios: list[str],
    ) -> list[str]:
        paragraphs: list[str] = []
        for index, point in enumerate(focus_points[:3]):
            item = feature_advantages[index] if index < len(feature_advantages) else {}
            advantage = item.get("advantage") or point
            reader_interest = item.get("reader_interest")
            scenario = practical_scenarios[index] if index < len(practical_scenarios) else ""
            parts = [f"第一眼值得看的，是 {self._truncate(point, 90)}。" if index == 0 else f"另一个值得留意的点，是 {self._truncate(point, 90)}。"]
            if advantage and advantage != point:
                parts.append(f"它的价值不在于多一个功能名，而在于 {self._truncate(advantage, 120)}。")
            if reader_interest:
                parts.append(f"读者会在意这一点，是因为 {self._truncate(reader_interest, 120)}。")
            elif scenario:
                parts.append(f"放到“{self._truncate(scenario, 80)}”这种场景里，它能帮你更快判断 {project_name} 是否值得继续试。")
            paragraphs.append("".join(parts))
        return paragraphs

    def _impact_paragraphs(
        self,
        project_name: str,
        impact: Any,
        required_examples: list[str] | None = None,
    ) -> list[str]:
        if not impact:
            return []
        core_effect = self._clean_text(self._field(impact, "core_effect", ""))
        effect_summary = self._clean_text(self._field(impact, "effect_summary", ""))
        outcomes = self._string_list(self._field(impact, "concrete_outcomes"))[:3]
        examples = self._dedupe((required_examples or []) + self._string_list(self._field(impact, "usage_examples")))[:3]
        benefits = self._string_list(self._field(impact, "user_benefits"))[:2]
        if not (core_effect or effect_summary or outcomes or examples):
            return []

        paragraphs: list[str] = []
        opening = effect_summary or f"{project_name} 真正能帮上的忙，是{core_effect}"
        paragraphs.append(self._truncate(opening, 240))

        details: list[str] = []
        for outcome in outcomes[:2]:
            details.append(f"一个直接结果是，{self._trim_sentence(outcome)}。")
        for example in examples[:2]:
            details.append(f"放到实际使用里，可以是{self._trim_sentence(example)}。")
        if benefits and len(details) < 2:
            details.append(f"对使用者来说，变化在于{self._trim_sentence(benefits[0])}。")
        if details:
            paragraphs.append("".join(details[:4]))
        return paragraphs

    def _wechat_example_paragraphs(
        self,
        project_name: str,
        examples: list[str],
        wechat_pattern: Any,
    ) -> list[str]:
        paragraphs: list[str] = []
        pattern_type = self._field(wechat_pattern, "pattern_type", "practical_tool")
        colloquial = self._string_list(self._field(wechat_pattern, "allowed_colloquial_phrases"))
        phrase = colloquial[0] if colloquial else "这个点挺实用"
        for index, example in enumerate(examples[:2], start=1):
            clean = self._trim_sentence(example)
            if not clean:
                continue
            if pattern_type == "platform_workbench":
                paragraph = (
                    f"放到平台型工具的视角里看，第 {index} 个例子可以是：{clean}。"
                    f"这里解决的不是单点功能不够，而是把原本散在各处的流程收进一个入口，团队看到的变化是协作和复用更清楚。{phrase}。"
                )
            elif pattern_type == "concept_practice":
                paragraph = (
                    f"这个思路落到具体场景里，可以是：{clean}。"
                    f"它把概念变成能操作的流程，用户看到的变化不是多一个名词，而是上下文、计划或材料能接着往下走。{phrase}。"
                )
            else:
                paragraph = (
                    f"具体一点，可以想象成：{clean}。"
                    f"这类场景里，{project_name} 解决的是重复整理、来回切换或重新交代背景的麻烦；用户看到的变化，是任务更容易从当前状态继续推进。{phrase}。"
                )
            paragraphs.extend([self._truncate(paragraph, 260), ""])
        return paragraphs

    def _ensure_impact_signal(self, markdown: str, content_plan: dict) -> str:
        impact = self._plan_impact(content_plan)
        if not impact or not self._missing_impact_points(markdown, impact):
            return markdown
        project_name = (
            self._clean_text(self._field(self._plan_appeal(content_plan), "project_name", ""))
            or str(content_plan.get("full_name") or "这个项目").split("/")[-1]
        )
        paragraphs = self._impact_paragraphs(project_name, impact)
        if not paragraphs:
            return markdown
        addition = "\n\n".join(paragraphs)
        content = re.sub(r"\n*项目地址：\s*https?://\S+\s*$", "", markdown.strip(), flags=re.MULTILINE).strip()
        return f"{content}\n\n{addition}\n"

    def _missing_impact_points(self, markdown: str, impact: Any) -> bool:
        compact = re.sub(r"\s+", "", markdown)
        candidates = (
            self._string_list(self._field(impact, "concrete_outcomes"))
            + self._string_list(self._field(impact, "usage_examples"))
            + self._string_list(self._field(impact, "user_benefits"))
        )
        matched = 0
        for item in candidates[:6]:
            keywords = self._impact_keywords(item)
            if keywords and sum(1 for keyword in keywords if keyword in compact) >= min(2, len(keywords)):
                matched += 1
        if matched >= 2:
            return False
        core_effect = self._clean_text(self._field(impact, "core_effect", ""))
        core_keywords = self._impact_keywords(core_effect)
        return not core_keywords or sum(1 for keyword in core_keywords if keyword in compact) < min(2, len(core_keywords))

    def _impact_keywords(self, value: str) -> list[str]:
        text = re.sub(r"\s+", "", str(value or ""))
        stopwords = {"这个", "项目", "用户", "可以", "一个", "直接", "结果", "实际", "使用", "帮助", "更容易"}
        keywords: list[str] = []
        for token in re.findall(r"[A-Za-z0-9_+-]{3,}", text):
            keywords.append(token.lower())
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            for part in re.split(r"[，。；、的和与及里把为是能让成在]+", chunk):
                if len(part) >= 2 and part not in stopwords:
                    keywords.append(part[:8])
        return self._dedupe(keywords)[:5]

    def _trim_sentence(self, value: str) -> str:
        return self._clean_text(value).rstrip("。；;，, ")

    def _valuable_author_note(self, content_plan: dict) -> str:
        author = self._field(content_plan, "author_profile") or {}
        login = self._clean_text(self._field(author, "login", ""))
        name = self._clean_text(self._field(author, "name", ""))
        company = self._clean_text(self._field(author, "company", ""))
        author_type = self._clean_text(self._field(author, "type", ""))
        known_orgs = {"microsoft", "google", "openai", "anthropic", "vercel", "langchain-ai", "langgenius"}
        label = name or login
        if author_type == "Organization" or login.lower() in known_orgs or company:
            return f"项目背后的公开身份可以轻轻带一句：{label}{f'，关联 {company}' if company else ''}。这不是主卖点，但能帮助读者判断生态背景。"
        return ""

    def _trim_project_definition_intro(self, intro: str, project_name: str) -> str:
        text = self._clean_text(intro)
        definition_prefix = f"{project_name} 是"
        if text.startswith(definition_prefix):
            return f"我注意到 {project_name}，不是因为它适合被一句定义概括，而是因为它解决的问题足够具体。{text}"
        return text

    def _repo_url(self, note: RepoResearchNote) -> str:
        if note.html_url:
            return note.html_url.rstrip("/")
        return f"https://github.com/{note.full_name}".rstrip("/")

    def _model_dump(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "dict"):
            return value.dict()
        return value

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

    def _fallback_summary(
        self,
        angle: TopicAngle,
        note: RepoResearchNote,
        description: str,
        readme_summary: str,
    ) -> str:
        pieces = [
            f"{angle.project_name or self._project_name(note)} 是 {note.full_name} 的开源项目。",
            description or angle.one_liner or readme_summary,
            f"当前约 {note.stars} stars，适合 {', '.join(angle.target_readers[:3]) or '技术读者'} 初步调研。",
            "本文基于 README、release 和 issue 样本做克制推荐，并提示采用前继续核验。",
        ]
        return self._truncate("".join(pieces), 180)

    def _first_title(self, angle: TopicAngle) -> str:
        if angle.title_candidates:
            return angle.title_candidates[0].title
        project_name = angle.project_name or angle.full_name.split("/")[-1]
        return f"这个开源项目值得关注：{project_name}"

    def _select_title_from_brief(
        self,
        brief: Any,
        fallback_title: str,
        content_plan: dict | None = None,
        note: RepoResearchNote | None = None,
    ) -> str:
        candidates: list[str] = []
        if content_plan:
            candidates.extend(self._wechat_title_candidates(content_plan, note))
        title_strategy = self._field(brief, "title_strategy") or {}
        for candidate in self._field(title_strategy, "title_candidates") or []:
            title = self._field(candidate, "title") or candidate if isinstance(candidate, str) else self._field(candidate, "title")
            if title:
                candidates.append(str(title))
        candidates.extend(str(item) for item in self._brief_list(brief, "title_direction"))
        if fallback_title:
            candidates.append(fallback_title)

        for title in candidates:
            clean_title = self._clean_text(title)
            if clean_title and not self._is_banned_title(clean_title) and not self._looks_like_title_instruction(clean_title):
                return clean_title

        project_name = ""
        if note is not None:
            project_name = self._project_name(note)
        elif content_plan:
            project_name = str(content_plan.get("full_name") or "unknown-project").split("/")[-1]
        project_kind = str((content_plan or {}).get("project_kind") or "").replace("_", " ")
        if project_kind:
            return f"{project_name}：一个面向 {project_kind} 场景的开源项目"
        return f"{project_name or '这个项目'}：一个值得放进工具箱的开源项目"

    def _wechat_title_candidates(
        self,
        content_plan: dict,
        note: RepoResearchNote | None,
    ) -> list[str]:
        pattern = self._plan_wechat_pattern(content_plan)
        appeal = self._plan_appeal(content_plan)
        impact = self._plan_impact(content_plan)
        project_name = (
            self._clean_text(self._field(appeal, "project_name", ""))
            or (self._project_name(note) if note is not None else str(content_plan.get("full_name") or "").split("/")[-1])
            or "这个项目"
        )
        pattern_type = self._field(pattern, "pattern_type", "practical_tool")
        title_formula = self._clean_text(self._field(pattern, "title_formula", ""))
        effect = self._title_effect_phrase(content_plan, note)
        candidates: list[str] = []
        if title_formula and not self._looks_like_title_instruction(title_formula):
            candidates.append(self._render_title_formula(title_formula, project_name, effect, note))
        if pattern_type == "hot_project" and note is not None and note.stars:
            candidates.append(f"{self._format_stars(note.stars)} Star，这个项目有点猛")
        if pattern_type == "platform_workbench":
            candidates.append(f"这个开源工作台，把{effect}做得很顺手")
        elif pattern_type == "demo_scene":
            candidates.append(f"{project_name} 这个 demo，能看出它解决了什么麻烦")
        elif pattern_type == "concept_practice":
            candidates.append(f"这个 GitHub 有意思啊，{project_name} 把{effect}落到项目里了")
        else:
            candidates.append(f"这个开源项目，把{effect}做得很顺手")
        candidates.append(f"我看了下，{project_name} 确实有点东西")
        if note is not None and note.stars and note.stars >= 1000 and pattern_type != "hot_project":
            candidates.append(f"{self._format_stars(note.stars)} Star，{project_name} 把{effect}讲明白了")
        return self._dedupe(candidates)

    def _render_title_formula(
        self,
        formula: str,
        project_name: str,
        effect: str,
        note: RepoResearchNote | None,
    ) -> str:
        title = formula
        title = title.replace("A + B = C", f"{project_name} + 工作流 = {effect}")
        title = title.replace("XXX", effect)
        title = title.replace("网页/终端/知识库", self._title_surface(note))
        title = title.replace("N Star", f"{self._format_stars(note.stars)} Star" if note and note.stars else project_name)
        title = title.replace("X 天涨了", "最近")
        title = re.sub(r"一周狂揽\s*", "", title)
        return self._truncate(title, 36)

    def _title_effect_phrase(self, content_plan: dict, note: RepoResearchNote | None) -> str:
        impact = self._plan_impact(content_plan)
        appeal = self._plan_appeal(content_plan)
        candidates = (
            self._string_list(self._field(impact, "concrete_outcomes"))
            + self._string_list(self._field(impact, "usage_examples"))
            + self._string_list(self._field(appeal, "top_selling_points"))
            + self._string_list(self._field(appeal, "practical_scenarios"))
        )
        for candidate in candidates:
            text = re.sub(r"\s+", "", self._trim_sentence(candidate))
            text = re.sub(r"^(把|让|帮助|可以|能够|用户|开发者|读者)", "", text)
            if len(text) >= 4:
                return text[:12]
        if note is not None:
            if note.project_kind in {"cli_tool", "developer_tool", "productivity_tool"}:
                return "日常工具链"
            if note.project_kind in {"self_hosted", "ai_agent"}:
                return "AI工作流"
        return "真实工作流"

    def _title_surface(self, note: RepoResearchNote | None) -> str:
        text = " ".join(
            [
                note.project_kind or "",
                note.description or "",
                note.language or "",
                " ".join(note.topics),
            ]
        ).lower() if note is not None else ""
        if any(word in text for word in ["browser", "web", "extension", "网页", "浏览器"]):
            return "网页"
        if any(word in text for word in ["cli", "terminal", "shell", "命令行", "终端"]):
            return "终端"
        if any(word in text for word in ["knowledge", "obsidian", "note", "知识库", "笔记"]):
            return "知识库"
        return "工作流"

    def _format_stars(self, stars: int) -> str:
        if stars >= 10000:
            value = stars / 10000
            return f"{value:.1f}w".replace(".0w", "w")
        if stars >= 1000:
            value = stars / 1000
            return f"{value:.1f}k".replace(".0k", "k")
        return str(stars)

    def _is_banned_title(self, title: str) -> bool:
        banned_fragments = ["多少 star", "README 里", "README里", "star 项目", "stars 项目", "值得关注", "值得顺手点开"]
        if any(fragment in title for fragment in banned_fragments):
            return True
        normalized = re.sub(r"\s+", "", title)
        if re.search(r"(发现|推荐|分享).{0,8}\d+(?:\.\d+)?[kK万wW]?(?:star|stars|Star|Stars).{0,8}项目", normalized):
            return True
        if re.search(r"发现一?个.+项目", normalized):
            return True
        return False

    def _looks_like_title_instruction(self, title: str) -> bool:
        instruction_markers = ["标题", "题目", "口语", "不要", "别", "夸张", "像朋友圈", "一点"]
        return any(marker in title for marker in instruction_markers) and not any(
            separator in title for separator in ["：", ":", "？", "?"]
        )

    def _release_title(self, release: dict) -> str:
        title = release.get("name") or release.get("tag_name") or "未命名 release"
        published_at = release.get("published_at") or "-"
        return f"{title}（{published_at}）"

    def _project_name(self, note: RepoResearchNote) -> str:
        return note.full_name.split("/")[-1] if note.full_name else "unknown-project"

    def _clean_text(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _markdown_bullets(self, values: list[str]) -> list[str]:
        clean_values = [value.strip() for value in values if value and value.strip()]
        if not clean_values:
            return ["- 暂无可验证信息"]
        return [f"- {value}" for value in clean_values]

    def _limit_items(
        self,
        values: list[str],
        limit: int,
        item_limit: int,
    ) -> list[str]:
        return [self._truncate(value, item_limit) for value in values if value and value.strip()][:limit]

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _field(self, source: Any, name: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(name, default)
        return getattr(source, name, default)

    def _plan_brief(self, content_plan: dict) -> Any:
        return self._field(content_plan, "brief") or {}

    def _plan_insight(self, content_plan: dict) -> Any:
        return self._field(content_plan, "insight") or {}

    def _plan_appeal(self, content_plan: dict) -> Any:
        return self._field(content_plan, "appeal") or {}

    def _plan_impact(self, content_plan: dict) -> Any:
        return self._field(content_plan, "impact") or {}

    def _custom_direction(self, content_plan: dict | None) -> dict[str, Any]:
        direction = self._field(content_plan or {}, "custom_direction") or self._field(content_plan or {}, "parsed_direction") or {}
        return direction if isinstance(direction, dict) else {}

    def _style_reference_profile(self, content_plan: dict | None) -> dict[str, Any]:
        profile = self._field(content_plan or {}, "style_reference_profile") or {}
        if isinstance(profile, dict) and int(profile.get("raw_count") or 0) > 0:
            return profile
        return {}

    def _style_reference_title(self, title: str, style_profile: dict[str, Any], project_name: str) -> str:
        if not style_profile:
            return title
        patterns = "；".join(self._string_list(style_profile.get("title_patterns")))
        tones = "；".join(self._string_list(style_profile.get("tone_traits")))
        if any(marker in patterns + tones for marker in ["口语", "短句", "问题式", "悬念", "态度"]):
            if len(title) > 24 or "：" in title:
                return f"{project_name}，这个工具有点顺手"
        return title

    def _style_reference_intro(
        self,
        intro: str,
        style_profile: dict[str, Any],
        project_name: str,
        scenario: str,
    ) -> str:
        if not style_profile:
            return intro
        opening = "；".join(self._string_list(style_profile.get("opening_patterns")))
        tones = "；".join(self._string_list(style_profile.get("tone_traits")))
        reader_relationship = str(style_profile.get("reader_relationship") or "")
        if any(marker in opening + tones + reader_relationship for marker in ["日常", "第一人称", "口语", "朋友", "同事"]):
            return (
                f"如果你平时也会在{scenario}里来回切工具，{project_name} 属于那种点开以后会想顺手试一下的项目。"
                "它不靠一长串功能名吸引人，真正有意思的是能不能把一个具体麻烦变轻。"
            )
        return intro

    def _direction_style_notes(self, custom_direction: dict[str, Any]) -> list[str]:
        if not custom_direction or not custom_direction.get("raw_text"):
            return []
        notes = ["已接入用户写作方向"]
        for key, label in [
            ("target_reader", "目标读者"),
            ("writing_perspective", "写作视角"),
            ("core_angle", "核心角度"),
        ]:
            value = self._clean_text(str(custom_direction.get(key) or ""))
            if value:
                notes.append(f"{label}：{value}")
        notes.extend(f"必写：{item}" for item in self._string_list(custom_direction.get("must_include"))[:4])
        notes.extend(f"避免：{item}" for item in self._string_list(custom_direction.get("avoid_topics"))[:4])
        notes.extend(f"语气：{item}" for item in self._string_list(custom_direction.get("tone_preferences"))[:3])
        return self._dedupe(notes)

    def _plan_facts(self, content_plan: dict) -> list[Any]:
        facts = self._field(content_plan, "facts") or []
        return facts if isinstance(facts, list) else []

    def _brief_text(self, brief: Any, name: str) -> str:
        return self._clean_text(self._field(brief, name, "") or "")

    def _brief_list(self, brief: Any, name: str) -> list[str]:
        return self._string_list(self._field(brief, name))

    def _brief_title_candidates(self, brief: Any) -> list[Any]:
        title_strategy = self._field(brief, "title_strategy") or {}
        candidates = self._field(title_strategy, "title_candidates") or []
        return candidates if isinstance(candidates, list) else []

    def _narrative_pattern(self, brief: Any) -> str | None:
        return self._brief_text(brief, "narrative_pattern") or None

    def _title_style(self, brief: Any) -> str | None:
        title_strategy = self._field(brief, "title_strategy") or {}
        directions = self._string_list(self._field(title_strategy, "directions"))
        return directions[0] if directions else None

    def _style_notes(self, content_plan: dict) -> list[str]:
        brief = self._plan_brief(content_plan)
        appeal = self._plan_appeal(content_plan)
        impact = self._plan_impact(content_plan)
        style_profile = self._style_reference_profile(content_plan)
        return self._dedupe(
            self._brief_list(brief, "human_tone_rules")
            + self._brief_list(brief, "article_differentiators")
            + self._brief_list(brief, "should_avoid")
            + self._string_list(self._field(appeal, "recommended_focus"))
            + self._string_list(self._field(appeal, "avoid_overemphasis"))
            + self._string_list(self._field(impact, "article_expansion_points"))
            + [f"项目效果：{item}" for item in self._string_list(self._field(impact, "concrete_outcomes"))[:3]]
            + [f"效果边界：{item}" for item in self._string_list(self._field(impact, "weak_or_unknown_effects"))[:3]]
            + ([f"已接入风格参考：{style_profile.get('summary')}"] if style_profile.get("summary") else [])
            + [f"风格语气：{item}" for item in self._string_list(style_profile.get("tone_traits"))[:3]]
            + [f"标题倾向：{item}" for item in self._string_list(style_profile.get("title_patterns"))[:3]]
            + [f"原创规则：{item}" for item in self._string_list(style_profile.get("originality_rules"))[:3]]
        )

    def _feature_advantage_lines(self, appeal: Any) -> list[str]:
        lines: list[str] = []
        for item in self._field(appeal, "feature_advantages") or []:
            feature = self._clean_text(self._field(item, "feature", ""))
            advantage = self._clean_text(self._field(item, "advantage", ""))
            reader_interest = self._clean_text(self._field(item, "reader_interest", ""))
            if feature and advantage:
                suffix = f"读者会关心的是：{reader_interest}" if reader_interest else ""
                lines.append(self._clean_text(f"{feature}：{advantage}{suffix}"))
        return self._dedupe(lines)

    def _fact_ids(self, payload_value: Any, content_plan: dict) -> list[int]:
        ids: list[int] = []
        for item in self._string_list(payload_value):
            try:
                ids.append(int(item))
            except ValueError:
                continue
        if ids:
            return ids
        return list(range(1, min(len(self._plan_facts(content_plan)), 8) + 1))

    def _publishable_fact_claims(self, content_plan: dict) -> list[str]:
        claims: list[str] = []
        for fact in self._plan_facts(content_plan):
            if self._field(fact, "publishable", True):
                claim = self._clean_text(self._field(fact, "claim", ""))
                if claim:
                    claims.append(claim)
        return claims

    def _plan_source_links(self, content_plan: dict) -> list[str]:
        links: list[str] = []
        for fact in self._plan_facts(content_plan):
            source = self._field(fact, "source")
            if source:
                links.append(str(source))
        project_links = self._field(content_plan, "project_links") or {}
        for key in ["homepage", "documentation", "demo", "examples", "website"]:
            links.extend(self._string_list(self._field(project_links, key)))
        return self._dedupe(links)

    def _plan_warnings(self, content_plan: dict) -> list[str]:
        warnings = self._string_list(self._field(content_plan, "warnings"))
        for fact in self._plan_facts(content_plan):
            if self._field(fact, "category") == "license" and "没有明确" in self._clean_text(self._field(fact, "claim", "")):
                warnings.append(self._clean_text(self._field(fact, "claim", "")))
        insight = self._plan_insight(content_plan)
        warnings.extend(self._string_list(self._field(insight, "not_to_overclaim"))[:3])
        return self._dedupe(warnings)

    def _author_note(self, content_plan: dict) -> str:
        author = self._field(content_plan, "author_profile") or {}
        name = self._field(author, "name") or self._field(author, "login")
        html_url = self._field(author, "html_url")
        bio = self._field(author, "bio")
        company = self._field(author, "company")
        parts = []
        if name:
            parts.append(f"作者/组织公开资料显示，项目背后是 {name}")
        if company:
            parts.append(f"关联信息包含 {company}")
        if bio:
            parts.append(f"简介提到：{self._truncate(str(bio), 90)}")
        if html_url:
            parts.append(f"GitHub 主页为 {html_url}")
        if not parts:
            return ""
        return "；".join(parts) + "。"

    def _opening_paragraph(
        self,
        brief: Any,
        angle: TopicAngle,
        project_name: str,
        problem: str,
    ) -> str:
        opening = self._brief_text(brief, "opening_direction") or angle.opening_hook
        if opening and self._looks_like_writing_instruction(opening):
            return (
                f"从原型到生产，很多团队卡住的不是能不能调用大模型，而是 RAG、工作流、"
                f"智能体逻辑和部署运维怎么接到一起。{project_name} 的切入点，正是把这些"
                f"分散步骤收进一个更容易落地的平台里。"
            )
        if opening:
            return self._truncate(opening, 220)
        return f"有些开源项目不需要先讲热度，先讲它想解决的问题就够了。{project_name} 就属于这一类：{self._truncate(problem, 160)}"

    def _looks_like_writing_instruction(self, text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith(("用", "以", "从")) and any(marker in stripped for marker in ["比如", "切入", "引发", "过渡"])

    def _article_reference_links(self, links: list[str]) -> list[str]:
        clean_links = [
            link
            for link in self._dedupe(links)
            if "localhost" not in link and not link.startswith("http://localhost")
        ]
        github_links = [link for link in clean_links if "github.com" in link]
        other_links = [link for link in clean_links if link not in github_links]
        return self._dedupe(github_links[:3] + other_links[:5])

    def _note_payload(self, note: RepoResearchNote) -> dict[str, Any]:
        if hasattr(note, "model_dump"):
            return note.model_dump(mode="json")
        return note.dict()

    def _angle_payload(self, angle: TopicAngle) -> dict[str, Any]:
        if hasattr(angle, "model_dump"):
            return angle.model_dump(mode="json")
        return angle.dict()

    def _truncate(self, value: str, limit: int) -> str:
        text = self._clean_text(value)
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _count_text(self, value: str) -> int:
        text = re.sub(r"\s+", "", value)
        return len(text)

    def _model_dump_title(self, candidate: Any) -> dict[str, Any]:
        if hasattr(candidate, "model_dump"):
            return candidate.model_dump()
        if hasattr(candidate, "dict"):
            return candidate.dict()
        return dict(candidate)
