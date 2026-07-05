from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import FinalArticle, PublishPolishReport, RepoResearchNote


class PublishPolisherService:
    """Clean final articles into publication-ready WeChat-style drafts."""

    REVIEW_SECTION_TITLES = [
        "参考链接",
        "来源链接",
        "阅读提醒",
        "当前需要留意的事实风险",
        "风险提示",
    ]
    REVIEW_PHRASES = [
        "可能随时间变化",
        "需注明数据截止日期",
        "数据截止日期",
        "需在文章中注明",
        "为项目资料提供",
        "以官方文档为准",
        "避免过度解读",
        "文章需",
        "不得扩展",
        "需保持客观表述",
        "功能描述需基于",
        "不替代实际测试",
        "使用前需关注",
        "商用或二次分发前需进一步确认",
        "采用前继续核验",
        "本文只基于当前调研资料",
        "不额外推断",
        "截至资料提供时间",
        "后续可能变化",
        "根据 README",
        "根据README",
        "资料显示",
        "数据可能变化",
        "本文将从以下几个方面",
        "本文将从",
        "综上",
        "具有较高参考价值",
        "建议结合实际情况",
        "参考文章中提到",
        "参考文章",
        "仿照某文",
        "仿写",
    ]
    AUTHOR_PROFILE_PHRASES = [
        "作者/组织公开资料显示",
        "关联信息包含",
        "简介提到",
        "GitHub 主页为",
        "公开资料显示",
        "项目背后是",
    ]
    KNOWN_ORG_LABELS = {
        "langchain-ai": "LangChain 生态",
        "langgenius": "Dify 团队",
        "microsoft": "Microsoft",
        "google": "Google",
        "facebook": "Meta/Facebook",
        "vercel": "Vercel",
        "anthropic": "Anthropic",
        "anthropics": "Anthropic",
        "openai": "OpenAI",
    }
    LINK_PATTERN = re.compile(r"https?://[^\s)>\]，。；、]+")

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.used_heuristic = False
        self.warnings: list[str] = []

    def polish_article(
        self,
        article: FinalArticle,
        note: Optional[RepoResearchNote] = None,
        content_plan: Optional[dict] = None,
    ) -> FinalArticle:
        heuristic_article = self._heuristic_polish(article, note, content_plan)
        self.used_heuristic = True
        if self.llm_service is not None and self.llm_service.is_available():
            llm_article = self._polish_with_llm(heuristic_article, note, content_plan)
            if llm_article is not None:
                self.used_llm = True
                return llm_article
        return heuristic_article

    def polish_articles(
        self,
        articles: list[FinalArticle],
        notes: list[RepoResearchNote],
        content_plans: list[dict] | None = None,
    ) -> list[FinalArticle]:
        notes_by_name = {note.full_name: note for note in notes}
        plans_by_name = {
            str(plan.get("full_name") or ""): plan
            for plan in (content_plans or [])
            if isinstance(plan, dict)
        }
        return [
            self.polish_article(
                article,
                note=notes_by_name.get(article.full_name),
                content_plan=plans_by_name.get(article.full_name),
            )
            for article in articles
        ]

    def _heuristic_polish(
        self,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> FinalArticle:
        removed_sections: list[str] = []
        removed_phrases: list[str] = []
        notes: list[str] = []
        content = article.content_markdown.strip()
        repo_url = self._repo_url(article, note)
        project_name = self._project_name(article, note, content_plan)

        content, sections = self._remove_review_sections(content)
        removed_sections.extend(sections)

        content, phrases = self._remove_review_phrase_lines(content)
        removed_phrases.extend(phrases)

        content, author_phrases, author_note = self._remove_author_profile_tone(content, article, note)
        removed_phrases.extend(author_phrases)
        if author_note:
            notes.append(author_note)

        content, star_phrases = self._soften_star_fork_language(content)
        removed_phrases.extend(star_phrases)

        content, risk_phrases = self._compress_risk_blocks(content)
        removed_phrases.extend(risk_phrases)

        content, tutorial_phrases = self._soften_tutorial_language(content)
        removed_phrases.extend(tutorial_phrases)
        content, firsthand_phrases = self._soften_unverified_firsthand_language(content)
        removed_phrases.extend(firsthand_phrases)
        content, investment_phrases = self._soften_investment_overclaims(content)
        removed_phrases.extend(investment_phrases)
        content, investment_cleanup = self._normalize_investment_auxiliary_text(content, note)
        removed_phrases.extend(investment_cleanup)

        content = self._remove_stray_reference_links(content, repo_url)
        content = self._cleanup_markdown(content)
        content = self._ensure_heading(article.title, content)
        appeal_missing_before = self._missing_appeal_points(content, content_plan)
        content = self._ensure_appeal_signal(content, content_plan, project_name)
        if content_plan and not self._missing_appeal_points(content, content_plan):
            notes.append("已保留或补入 ProjectAppeal 项目优势表达")
        elif appeal_missing_before:
            notes.append("ProjectAppeal 项目优势表达仍需人工复核")
        impact_missing_before = self._missing_impact_points(content, content_plan)
        content = self._ensure_impact_signal(content, content_plan, project_name)
        if content_plan and not self._missing_impact_points(content, content_plan):
            notes.append("已保留或补入 ProjectImpact 项目作用与效果表达")
        elif impact_missing_before:
            notes.append("ProjectImpact 项目作用与效果表达仍需人工复核")
        content = self._ensure_wechat_required_examples(content, content_plan, project_name)
        content = self._ensure_direction_signal(content, content_plan, project_name)
        content = self._ensure_natural_closing(content, article, note, content_plan, project_name)
        content = self._ensure_project_address(content, repo_url)
        content = self._cleanup_markdown(content)
        title = self._wechat_publish_title(article.title, note, content_plan)
        content = self._ensure_heading(title, content)

        remaining_issues = self._remaining_issues(content, content_plan)
        violated_preferences = self._direction_violations(article.title, content, content_plan)
        remaining_issues = self._dedupe(remaining_issues + [f"用户方向未完全满足：{item}" for item in violated_preferences])
        publish_ready = not remaining_issues
        report = PublishPolishReport(
            full_name=article.full_name,
            publish_ready=publish_ready,
            mode="heuristic",
            removed_sections=self._dedupe(removed_sections),
            removed_phrases=self._dedupe(removed_phrases),
            kept_links=[repo_url] if repo_url else [],
            remaining_issues=remaining_issues,
            notes=self._dedupe(notes),
            direction_followed=not violated_preferences,
            violated_preferences=violated_preferences,
        )
        return article.copy(
            update={
                "title": title,
                "content_markdown": content,
                "word_count": self._count_text(content),
                "publish_polish_report": report,
                "publish_ready": publish_ready,
                "publish_polish_mode": "heuristic",
            }
        )

    def _polish_with_llm(
        self,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> Optional[FinalArticle]:
        content = self.llm_service.chat(
            system_prompt=self._llm_system_prompt(),
            user_prompt=self._llm_user_prompt(article, note, content_plan),
            temperature=0.25,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            title = str(payload.get("title") or article.title).strip()
            title = self._wechat_publish_title(title, note, content_plan)
            summary = self._truncate(str(payload.get("summary") or article.summary).strip(), 220)
            content_markdown = str(payload.get("content_markdown") or article.content_markdown).strip()
            repo_url = self._repo_url(article, note)
            content_markdown, llm_removed_sections = self._remove_review_sections(content_markdown)
            content_markdown, llm_removed_phrases = self._remove_review_phrase_lines(content_markdown)
            content_markdown, llm_author_phrases, llm_author_note = self._remove_author_profile_tone(
                content_markdown,
                article,
                note,
            )
            content_markdown, llm_star_phrases = self._soften_star_fork_language(content_markdown)
            content_markdown, llm_risk_phrases = self._compress_risk_blocks(content_markdown)
            content_markdown, llm_tutorial_phrases = self._soften_tutorial_language(content_markdown)
            content_markdown, llm_firsthand_phrases = self._soften_unverified_firsthand_language(content_markdown)
            content_markdown, llm_investment_phrases = self._soften_investment_overclaims(content_markdown)
            content_markdown, llm_investment_cleanup = self._normalize_investment_auxiliary_text(content_markdown, note)
            content_markdown = self._remove_stray_reference_links(content_markdown, repo_url)
            content_markdown = self._ensure_heading(title, content_markdown)
            llm_notes = self._string_list(payload.get("notes"))
            content_markdown = self._ensure_appeal_signal(
                content_markdown,
                content_plan,
                self._project_name(article, note, content_plan),
            )
            if content_plan and not self._missing_appeal_points(content_markdown, content_plan):
                llm_notes.append("已保留 ProjectAppeal 项目优势表达")
            content_markdown = self._ensure_impact_signal(
                content_markdown,
                content_plan,
                self._project_name(article, note, content_plan),
            )
            if content_plan and not self._missing_impact_points(content_markdown, content_plan):
                llm_notes.append("已保留 ProjectImpact 项目作用与效果表达")
            content_markdown = self._ensure_wechat_required_examples(
                content_markdown,
                content_plan,
                self._project_name(article, note, content_plan),
            )
            content_markdown = self._ensure_direction_signal(
                content_markdown,
                content_plan,
                self._project_name(article, note, content_plan),
            )
            content_markdown = self._ensure_project_address(content_markdown, repo_url)
            content_markdown = self._cleanup_markdown(content_markdown)
            remaining_issues = self._remaining_issues(content_markdown, content_plan)
            violated_preferences = self._direction_violations(title, content_markdown, content_plan)
            remaining_issues = self._dedupe(
                remaining_issues + [f"用户方向未完全满足：{item}" for item in violated_preferences]
            )
            llm_remaining_notes = [
                f"LLM 建议：{item}" for item in self._string_list(payload.get("remaining_issues"))
            ]

            previous_report = article.publish_polish_report
            report = PublishPolishReport(
                full_name=article.full_name,
                publish_ready=not remaining_issues,
                mode="mixed" if previous_report and previous_report.mode == "heuristic" else "llm",
                removed_sections=self._dedupe(
                    (previous_report.removed_sections if previous_report else [])
                    + self._string_list(payload.get("removed_sections"))
                    + llm_removed_sections
                ),
                removed_phrases=self._dedupe(
                    (previous_report.removed_phrases if previous_report else [])
                    + self._string_list(payload.get("removed_phrases"))
                    + llm_removed_phrases
                    + llm_author_phrases
                    + llm_star_phrases
                    + llm_risk_phrases
                    + llm_tutorial_phrases
                    + llm_firsthand_phrases
                    + llm_investment_phrases
                    + llm_investment_cleanup
                ),
                kept_links=[repo_url] if repo_url else [],
                remaining_issues=remaining_issues,
                notes=self._dedupe(
                    (previous_report.notes if previous_report else [])
                    + llm_notes
                    + llm_remaining_notes
                    + ([llm_author_note] if llm_author_note else [])
                ),
                direction_followed=not violated_preferences,
                violated_preferences=violated_preferences,
            )
            return article.copy(
                update={
                    "title": title,
                    "summary": summary,
                    "content_markdown": content_markdown,
                    "word_count": self._count_text(content_markdown),
                    "publish_polish_report": report,
                    "publish_ready": report.publish_ready,
                    "publish_polish_mode": report.mode,
                }
            )
        except Exception as exc:
            self.warnings.append(f"LLM publish polish JSON parse failed for {article.full_name}: {exc}")
            return None

    def _remove_review_sections(self, markdown: str) -> tuple[str, list[str]]:
        lines = markdown.splitlines()
        output: list[str] = []
        removed: list[str] = []
        skip_title: str | None = None
        for line in lines:
            heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
            plain_title = self._normalize_heading(line)
            section_title = ""
            if heading:
                section_title = self._clean_heading_title(heading.group(2))
            elif plain_title in self.REVIEW_SECTION_TITLES:
                section_title = plain_title

            if skip_title is not None:
                if heading:
                    new_title = self._clean_heading_title(heading.group(2))
                    if new_title not in self.REVIEW_SECTION_TITLES:
                        skip_title = None
                        output.append(line)
                continue

            if section_title in self.REVIEW_SECTION_TITLES:
                removed.append(section_title)
                skip_title = section_title
                continue
            output.append(line)
        return "\n".join(output), removed

    def _remove_review_phrase_lines(self, markdown: str) -> tuple[str, list[str]]:
        removed: list[str] = []
        output: list[str] = []
        for line in markdown.splitlines():
            hits = [phrase for phrase in self.REVIEW_PHRASES if phrase in line]
            if hits:
                removed.extend(hits)
                if self._line_needs_natural_note(line):
                    output.append("如果要放进团队流程，最好先在自己的项目里跑一圈。")
                continue
            output.append(line)
        return "\n".join(output), removed

    def _remove_author_profile_tone(
        self,
        markdown: str,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
    ) -> tuple[str, list[str], str | None]:
        owner = (article.full_name or (note.full_name if note else "")).split("/")[0].lower()
        known_label = self.KNOWN_ORG_LABELS.get(owner)
        removed: list[str] = []
        output: list[str] = []
        inserted_known_intro = False
        for line in markdown.splitlines():
            hits = [phrase for phrase in self.AUTHOR_PROFILE_PHRASES if phrase in line]
            if not hits:
                output.append(line)
                continue
            removed.extend(hits)
            if known_label and not inserted_known_intro:
                output.append(f"这个项目来自 {known_label}。")
                inserted_known_intro = True
        note_text = f"保留知名组织自然介绍：{known_label}" if inserted_known_intro else None
        return "\n".join(output), removed, note_text

    def _soften_star_fork_language(self, markdown: str) -> tuple[str, list[str]]:
        removed: list[str] = []
        output: list[str] = []
        pattern = re.compile(r"(星标数|star|stars|Star|Stars).{0,40}(fork|Fork|分叉|复刻).{0,80}")
        for line in markdown.splitlines():
            if pattern.search(line) and any(
                phrase in line
                for phrase in ["可能随时间变化", "截至", "为项目资料提供", "后续可能变化", "需注明"]
            ):
                removed.append(line.strip())
                if "关注度" not in "\n".join(output[-2:]):
                    output.append("从 GitHub 反馈看，这个项目已经有不少开发者关注。")
                continue
            output.append(line)
        return "\n".join(output), removed

    def _compress_risk_blocks(self, markdown: str) -> tuple[str, list[str]]:
        removed: list[str] = []
        output: list[str] = []
        lines = markdown.splitlines()
        index = 0
        reminder = "如果要放进团队流程，最好先在自己的项目里跑一圈。"
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if "别急着直接上生产" in stripped or "别急着上生产" in stripped:
                removed.append(stripped)
                if reminder not in "\n".join(output[-3:]):
                    output.append(reminder)
                index += 1
                while index < len(lines) and not lines[index].strip():
                    index += 1
                while index < len(lines) and lines[index].strip().startswith(("- ", "* ")):
                    removed.append(lines[index].strip())
                    index += 1
                continue
            if stripped.startswith(("- ", "* ")) and self._looks_like_risk_bullet(stripped):
                removed.append(stripped)
                if reminder not in "\n".join(output[-3:]):
                    output.append(reminder)
                index += 1
                continue
            output.append(line)
            index += 1
        return "\n".join(output), removed

    def _soften_tutorial_language(self, markdown: str) -> tuple[str, list[str]]:
        replacements = {
            "项目 README": "项目资料",
            "README 里": "项目资料里",
            "README里": "项目资料里",
            "Quickstart": "基础示例",
            "quickstart": "基础示例",
            "Quick start": "基础示例",
            "quick start": "基础示例",
            "跑几条命令就能启动": "按官方部署说明就能启动",
            "几行配置就能跑通": "少量配置就能验证流程",
            "几行 Python 代码就能调起": "基础示例就能调起",
            "上手也很简单": "试用门槛不高",
            "直接上手试试": "点开看看",
            "安装，避免第三方修改版": "获取，避免第三方修改版",
        }
        text = markdown
        removed: list[str] = []
        for source, target in replacements.items():
            if source in text:
                text = text.replace(source, target)
                removed.append(source)
        text = re.sub(r"(?m)^#+\s*(如何快速了解或上手|安装|配置|运行命令)\s*$", "", text)
        tutorial_line_patterns = [
            r"(?m)^.*安装也很简单.*$",
            r"(?m)^.*安装也简单.*$",
            r"(?m)^.*安装方式也简单.*$",
            r"(?m)^.*安装方式也很简单.*$",
            r"(?m)^.*点击侧边栏.*(?:Plugins|插件).*$",
            r"(?m)^.*点开插件面板.*$",
            r"(?m)^.*侧边栏找到\s*Plugins.*$",
            r"(?m)^.*找到\s*Superpowers\s*并添加.*$",
            r"(?m)^.*重启即可.*$",
            r"(?m)^.*把\s*Skill\s*文件复制到.*$",
            r"(?m)^.*~/.claude/commands/.*$",
            r"(?m)^.*安装很简单.*$",
        ]
        for pattern in tutorial_line_patterns:
            if re.search(pattern, text):
                removed.append(pattern)
                text = re.sub(pattern, "", text)
        return text, self._dedupe(removed)

    def _soften_unverified_firsthand_language(self, markdown: str) -> tuple[str, list[str]]:
        removed: list[str] = []
        output: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if any(marker in stripped for marker in ["我试了一下", "我跑了一下", "我实际运行", "亲测", "试了几天"]):
                removed.append(stripped)
                replacement = re.sub(r"^.*?(我试了一下|我跑了一下|我实际运行|亲测|试了几天)[^。！？]*[。！？]?", "", stripped).strip()
                if replacement:
                    output.append(replacement)
                continue
            output.append(line)
        return "\n".join(output), removed

    def _soften_investment_overclaims(self, markdown: str) -> tuple[str, list[str]]:
        removed: list[str] = []
        text = markdown
        replacements = {
            "比如你想分析腾讯": "比如你想分析一家候选公司",
            "怎么看腾讯": "怎么看一家公司",
            "但至少说明项目方自己跑通了这套方法论，方向是靠谱的。": "但它更适合作为项目方展示的一类可观察信号，不能被写成未来收益承诺。",
            "这不代表未来表现，也不应作为投资建议。但它至少说明，这套方法论在作者自己的实践中是有效的。": "这不代表未来表现，也不应作为投资建议；文章里更适合把它当作项目资料中的效果展示信号，而不是收益承诺。",
        }
        for source, target in replacements.items():
            if source in text:
                text = text.replace(source, target)
                removed.append(source)
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.search(r"(买入|持有|卖出|观望|买点|卖点)", stripped) and any(term in stripped for term in ["AI", "项目", "指令", "判断", "结论"]):
                removed.append(stripped)
                if not cleaned_lines or "辅助判断" not in cleaned_lines[-1]:
                    cleaned_lines.append("投资分析类项目更适合写成辅助判断：它把公开信息、分析框架和分歧点整理出来，最后仍由人复核假设和结论。")
                continue
            if re.search(r"(实盘收益|全年收益|收益记录|收益率|\+\s*\d+(?:\.\d+)?\s*%)", stripped):
                removed.append(stripped)
                if not cleaned_lines or "投资类项目更适合写成辅助研究工具" not in cleaned_lines[-1]:
                    cleaned_lines.append("投资类项目更适合写成辅助研究工具：它可以帮你整理公开信息、拆出分析框架和待核验问题，但不能被写成收益承诺。")
                continue
            if re.search(r"(建议|结论|明确给出).{0,18}(买入|持有|卖出|加仓|减仓)", stripped):
                removed.append(stripped)
                cleaned_lines.append("如果需要举例，只适合写成工作流层面的辅助判断：先汇总资料和假设，再由人复核关键结论。")
                continue
            cleaned_lines.append(line)
        text = "\n".join(cleaned_lines)
        return text, removed

    def _normalize_investment_auxiliary_text(
        self,
        markdown: str,
        note: Optional[RepoResearchNote],
    ) -> tuple[str, list[str]]:
        source = " ".join([note.full_name if note else "", note.description if note else ""]).lower()
        if not any(word in source for word in ["berkshire", "invest", "stock", "投资", "股票"]):
            return markdown, []
        removed: list[str] = []
        helper_sentence = "投资类项目更适合写成辅助研究工具：它可以帮你整理公开信息、拆出分析框架和待核验问题，但不能被写成收益承诺。"
        text = markdown
        replacements = {
            "用四大师方法论和真实业绩说话": "用四大师方法论做辅助分析",
            "让 AI 做投资研究不再模棱两可——用四位大师的思维框架，强制给出结论。": "让 AI 投资研究少一点散乱：用四位大师的思维框架，先把公开信息和分析线索整理清楚。",
            "不是又一个 AI 投资聊天机器人，而是把大师的方法论编码成可执行的命令。": "不是又一个 AI 投资聊天机器人，而是把大师的方法论拆成可复核的分析流程。",
            "每部分都有明确的“人工复核后的判断/观望/人工复核后的判断”结论": "每部分都会沉淀成需要人工复核的判断线索",
            "每部分都有明确的结论": "每部分都有需要人工复核的判断线索",
            "用户可直接在报告基础上做判断": "用户可以在报告基础上继续核验假设",
            "投资者可以直接在报告基础上做自己的判断": "投资者可以把报告当成信息整理和假设核验材料",
            "潜在投资标的": "候选研究对象",
            "最近发现一个GitHub项目，专门解决这个痛点，": "ai-berkshire 的切入点很直接：",
            "最近发现一个 GitHub 项目，专门解决这个痛点，": "ai-berkshire 的切入点很直接：",
        }
        for source_text, target in replacements.items():
            if source_text in text:
                text = text.replace(source_text, target)
                removed.append(source_text)
        output: list[str] = []
        helper_seen = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == helper_sentence:
                if helper_seen:
                    removed.append(stripped)
                    continue
                helper_seen = True
            if re.match(r"^\*\*效果怎么样？项目公开了真实记录。", stripped):
                removed.append(stripped)
                continue
            if "真实记录" in stripped and "效果" in stripped:
                removed.append(stripped)
                continue
            if "安装" in stripped and ("客户端" in stripped or "命令" in stripped):
                removed.append(stripped)
                continue
            output.append(line)
        text = "\n".join(output)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text, removed

    def _remove_stray_reference_links(self, markdown: str, repo_url: str) -> str:
        output: list[str] = []
        for line in markdown.splitlines():
            links = self.LINK_PATTERN.findall(line)
            if not links:
                output.append(line)
                continue
            if repo_url and links == [repo_url]:
                output.append(line)
                continue
            if line.strip().startswith(("- ", "* ")) and any(link != repo_url for link in links):
                continue
            cleaned = line
            for link in links:
                if link != repo_url:
                    cleaned = cleaned.replace(link, "").strip()
            if cleaned and cleaned not in {"-", "*"}:
                output.append(cleaned)
        return "\n".join(output)

    def _ensure_project_address(self, markdown: str, repo_url: str) -> str:
        if not repo_url:
            return markdown.strip() + "\n"
        line = f"项目地址： {repo_url}"
        content = re.sub(r"^\s*项目地址[:：]\s*https?://github\.com/[^\s)>\]]+\s*$", "", markdown, flags=re.MULTILINE)
        return f"{content.rstrip()}\n\n{line}\n"

    def _ensure_natural_closing(
        self,
        markdown: str,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
        project_name: str,
    ) -> str:
        body = re.sub(r"^\s*#.*$", "", markdown, count=1, flags=re.MULTILINE).strip()
        body_without_links = re.sub(r"^\s*项目地址[:：].*$", "", body, flags=re.MULTILINE).strip()
        if not body_without_links:
            return markdown
        last_block = [block.strip() for block in re.split(r"\n\s*\n", body_without_links) if block.strip()][-1]
        if "项目地址" not in last_block and self._count_text(last_block) >= 45:
            return markdown

        kind = str(
            (content_plan or {}).get("project_kind")
            or (getattr(note, "project_kind", None) if note else "")
            or ""
        ).replace("_", " ")
        insight = self._content_plan_insight(content_plan)
        core_value = str(insight.get("core_value") or insight.get("problem_solved") or "").strip()
        if kind:
            closing = (
                f"如果你最近正好在看{kind}方向的工具，{project_name} 值得放进收藏夹。"
                "它不一定适合所有团队直接搬进生产流程，但很适合先拿一个真实项目跑一圈，看看它和现有工作流能不能接上。"
            )
        elif core_value:
            closing = (
                f"{project_name} 最值得看的地方，不只是功能列表，而是它对“{core_value}”这个问题给了一个开源实现。"
                "真要用到团队流程里，建议先用自己的项目小范围试一遍。"
            )
        else:
            closing = (
                f"如果你平时会在多个 AI 编程工具之间切换，{project_name} 这类项目至少值得放进收藏夹。"
                "它不一定适合所有人，但它指出了一个很现实的问题：AI 工具越来越多，真正麻烦的反而是工作流怎么统一。"
            )
        return f"{markdown.rstrip()}\n\n{closing}"

    def _ensure_appeal_signal(
        self,
        markdown: str,
        content_plan: Optional[dict],
        project_name: str,
    ) -> str:
        appeal = self._content_plan_appeal(content_plan)
        if not appeal:
            return markdown
        if not self._missing_appeal_points(markdown, content_plan):
            return markdown
        signal = str(appeal.get("primary_hook") or appeal.get("appeal_summary") or "").strip()
        if not signal:
            points = self._string_list(appeal.get("top_selling_points"))
            if points:
                signal = f"{project_name} 最值得先看的，是 {points[0]}。"
        if not signal or signal in markdown:
            return markdown

        lines = markdown.strip().splitlines()
        if lines and lines[0].lstrip().startswith("# "):
            return "\n".join([lines[0], "", signal, "", *lines[1:]]).strip() + "\n"
        return f"{signal}\n\n{markdown.strip()}\n"

    def _ensure_impact_signal(
        self,
        markdown: str,
        content_plan: Optional[dict],
        project_name: str,
    ) -> str:
        impact = self._content_plan_impact(content_plan)
        if not impact or not self._missing_impact_points(markdown, content_plan):
            return markdown
        paragraphs = self._impact_paragraphs(project_name, impact)
        if not paragraphs:
            return markdown
        addition = "\n\n".join(paragraphs)
        content = re.sub(r"\n*项目地址[:：]\s*https?://\S+\s*$", "", markdown.strip(), flags=re.MULTILINE).strip()
        return f"{content}\n\n{addition}\n"

    def _ensure_wechat_required_examples(
        self,
        markdown: str,
        content_plan: Optional[dict],
        project_name: str,
    ) -> str:
        pattern = (content_plan or {}).get("wechat_pattern") or {}
        if not isinstance(pattern, dict):
            return markdown
        examples = self._string_list(pattern.get("required_examples"))
        if not examples:
            return markdown
        current_count = self._concrete_example_count(markdown, examples)
        if current_count >= 2:
            return markdown
        additions: list[str] = []
        compact = re.sub(r"\s+", "", markdown)
        for example in examples:
            keywords = self._impact_keywords(example)
            if keywords and sum(1 for keyword in keywords if keyword in compact) >= min(2, len(keywords)):
                continue
            additions.append(
                f"再放到一个具体场景里看：{self._trim_sentence(example)}。"
                f"它解决的是任务开始前上下文不清、过程里反复返工或多工具切换后状态丢失的麻烦；用户看到的变化，是 {project_name} 能把分析、计划和执行衔接得更稳。"
            )
            if current_count + len(additions) >= 2:
                break
        if not additions:
            return markdown
        content = re.sub(r"\n*项目地址[:：]\s*https?://\S+\s*$", "", markdown.strip(), flags=re.MULTILINE).strip()
        return f"{content}\n\n" + "\n\n".join(additions) + "\n"

    def _impact_paragraphs(self, project_name: str, impact: dict[str, Any]) -> list[str]:
        core_effect = str(impact.get("core_effect") or "").strip()
        effect_summary = str(impact.get("effect_summary") or "").strip()
        outcomes = self._string_list(impact.get("concrete_outcomes"))[:2]
        examples = self._string_list(impact.get("usage_examples"))[:2]
        benefits = self._string_list(impact.get("user_benefits"))[:2]
        if not (core_effect or effect_summary or outcomes or examples):
            return []
        paragraphs = [self._truncate(effect_summary or f"{project_name} 更值得展开的，是它实际能带来的变化：{core_effect}", 260)]
        details: list[str] = []
        for outcome in outcomes:
            details.append(f"具体一点，{self._trim_sentence(outcome)}。")
        for example in examples:
            details.append(f"放到使用场景里，可以是{self._trim_sentence(example)}。")
        if benefits and len(details) < 2:
            details.append(f"对使用者来说，变化在于{self._trim_sentence(benefits[0])}。")
        if details:
            paragraphs.append("".join(details[:4]))
        return paragraphs

    def _ensure_direction_signal(
        self,
        markdown: str,
        content_plan: Optional[dict],
        project_name: str,
    ) -> str:
        direction = self._custom_direction(content_plan)
        core_angle = str(direction.get("core_angle") or "").strip()
        if not core_angle:
            return markdown
        if self._generic_direction_angle(core_angle):
            return markdown
        compact = re.sub(r"\s+", "", markdown.lower())
        keywords = self._direction_keywords(core_angle)
        matched = sum(1 for keyword in keywords if keyword in compact)
        if matched >= min(2, len(keywords)):
            return markdown

        if "cat" in core_angle.lower() and "替代" in core_angle:
            signal = (
                f"换句话说，{project_name} 最该被理解成一个 cat 替代品："
                "保留 cat 的顺手命令，同时把高亮、行号、Git 标记和分页这些日常爽点补齐。"
            )
        else:
            signal = f"这篇最该抓住的重点是：{core_angle}。"
        if signal in markdown:
            return markdown
        lines = markdown.strip().splitlines()
        if lines and lines[0].lstrip().startswith("# "):
            insert_at = 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            return "\n".join([*lines[:insert_at], "", signal, "", *lines[insert_at:]]).strip() + "\n"
        return f"{signal}\n\n{markdown.strip()}\n"

    def _generic_direction_angle(self, value: str) -> bool:
        compact = re.sub(r"\s+", "", value)
        generic_values = {
            "项目效果",
            "多写效果",
            "举例说明",
            "不要一笔带过",
            "不要只说提升效率",
            "作用效果",
            "效果提升",
        }
        return compact in generic_values or len(compact) <= 4 and any(term in compact for term in ["效果", "提升", "作用"])

    def _remaining_issues(self, markdown: str, content_plan: Optional[dict] = None) -> list[str]:
        issues: list[str] = []
        text = markdown
        for phrase in self.REVIEW_PHRASES + self.AUTHOR_PROFILE_PHRASES:
            if phrase in text:
                issues.append(f"仍包含发布前短语：{phrase}")
        headings = [self._clean_heading_title(match) for match in re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", text, flags=re.MULTILINE)]
        for title in self.REVIEW_SECTION_TITLES:
            if title in headings:
                issues.append(f"仍包含需删除小节：{title}")
        non_repo_links = [
            link
            for link in self.LINK_PATTERN.findall(text)
            if not re.fullmatch(r"https?://github\.com/[^/\s)>\]]+/[^/\s)>\]]+/?", link)
        ]
        if non_repo_links:
            issues.append("正文仍包含非项目地址链接")
        if self._missing_appeal_points(markdown, content_plan):
            issues.append("项目优势不够突出")
        if self._missing_impact_points(markdown, content_plan):
            issues.append("项目效果展开不足")
        vague_issues = self._vague_effect_issues(markdown)
        issues.extend(vague_issues)
        issues.extend(self._wechat_share_style_issues(markdown, content_plan))
        return self._dedupe(issues)

    def _llm_system_prompt(self) -> str:
        return (
            "你是一位中文技术公众号编辑。你要把一篇已经完成事实核查的开源项目文章整理成适合发布的版本。"
            "请删除参考链接堆叠、阅读提醒、审稿腔、资料卡式作者背景和过度谨慎表达。"
            "保留项目事实、项目地址，以及 content_plan.appeal 中已经自然呈现的项目特点和优势表达。"
            "同时保留 content_plan.impact 中的项目作用、效果和具体提升表达，不要把这类段落删短成空泛总结。"
            "不要新增未经验证的功能、作者背景、性能数据或用户数据。"
            "文章要像程序员分享，不像尽调报告。"
        )

    def _llm_user_prompt(
        self,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> str:
        payload = {
            "article": self._model_dump(article),
            "repo_url": self._repo_url(article, note),
            "research_note": self._model_dump(note) if note else None,
            "content_plan": content_plan,
            "custom_article_direction": self._custom_direction(content_plan),
            "style_reference_profile": self._style_reference_profile(content_plan),
            "style_reference_rules": (content_plan or {}).get("style_reference_rules") if content_plan else {},
            "wechat_article_pattern": (content_plan or {}).get("wechat_pattern") if content_plan else {},
        }
        return (
            "请输出严格 JSON object，字段为：title, summary, content_markdown, "
            "removed_sections, removed_phrases, remaining_issues, notes。\n"
            "正文 content_markdown 最后只能保留一个项目地址行，格式为：项目地址： https://github.com/owner/repo。\n"
            "不要删除 project_appeal/top_selling_points 对应的优势表达；如果当前文章没有体现它们，请自然补一句项目吸引力总结。\n"
            "不要删除 project_impact/concrete_outcomes/usage_examples 对应的作用和效果表达；如果当前文章没有体现，请自然展开至少两个具体结果或使用例子。\n"
            "如果出现“提升效率”“降低成本”“改善体验”，附近必须说明提升发生在什么具体动作或场景里。\n"
            "必须检查 wechat_article_pattern：正文至少有 2 个具体效果、2 个使用例子；每个重点功能都要说明解决什么麻烦、用户看到什么变化。"
            "保留有依据的轻口语判断，不要改回报告腔。\n"
            "不要保留“我试了一下/我跑了一下/亲测”这类未验证第一人称体验；不要编造投资项目的具体买入/持有/卖出比例、公司结论或收益率。\n"
            "不要保留安装步骤、点击菜单、重启工具等教程化说明，除非用户明确要求教程。\n"
            "必须遵守 custom_article_direction：保留用户指定重点和语气；avoid_topics 指定避免的内容不要出现在标题、小标题或正文展开中。\n"
            "如果有 style_reference_profile，只保留语气、节奏、读者关系、开头方式和标题倾向；"
            "必须删除“参考文章中提到”“仿照某文”“仿写”等元话语，并改写任何疑似复制参考文章原句、标题、独特比喻或段落结构的表达。\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _repo_url(self, article: FinalArticle, note: Optional[RepoResearchNote]) -> str:
        candidates = [article.html_url, note.html_url if note else "", *article.source_links]
        if note:
            candidates.extend(note.source_links)
        for value in candidates:
            clean = str(value or "").strip().rstrip("/")
            match = re.match(r"^(https?://github\.com/[^/\s)>\]]+/[^/\s)>\]]+)", clean)
            if match:
                return match.group(1).rstrip("/")
        if article.full_name and "/" in article.full_name:
            return f"https://github.com/{article.full_name}"
        return ""

    def _project_name(
        self,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> str:
        insight = self._content_plan_insight(content_plan)
        if insight.get("project_name"):
            return str(insight["project_name"])
        full_name = article.full_name or (note.full_name if note else "")
        return full_name.split("/")[-1] if full_name else "这个项目"

    def _content_plan_insight(self, content_plan: Optional[dict]) -> dict[str, Any]:
        insight = (content_plan or {}).get("insight")
        return insight if isinstance(insight, dict) else {}

    def _content_plan_appeal(self, content_plan: Optional[dict]) -> dict[str, Any]:
        appeal = (content_plan or {}).get("appeal")
        return appeal if isinstance(appeal, dict) else self._model_dump(appeal)

    def _content_plan_impact(self, content_plan: Optional[dict]) -> dict[str, Any]:
        impact = (content_plan or {}).get("impact")
        return impact if isinstance(impact, dict) else self._model_dump(impact)

    def _custom_direction(self, content_plan: Optional[dict]) -> dict[str, Any]:
        direction = (content_plan or {}).get("custom_direction") or (content_plan or {}).get("parsed_direction") or {}
        return direction if isinstance(direction, dict) else {}

    def _style_reference_profile(self, content_plan: Optional[dict]) -> dict[str, Any]:
        profile = (content_plan or {}).get("style_reference_profile") or {}
        if isinstance(profile, dict) and int(profile.get("raw_count") or 0) > 0:
            return profile
        return {}

    def _direction_violations(
        self,
        title: str,
        markdown: str,
        content_plan: Optional[dict],
    ) -> list[str]:
        direction = self._custom_direction(content_plan)
        if not direction or not direction.get("raw_text"):
            return []
        text = f"{title}\n{markdown}"
        compact = re.sub(r"\s+", "", text.lower())
        violations: list[str] = []

        for rule in self._string_list(direction.get("avoid_topics")) + [
            item
            for item in self._string_list(direction.get("content_preferences"))
            if any(marker in item for marker in ["不要", "少写", "避免", "别写", "不能", "不应"])
        ]:
            if self._direction_avoid_hit(rule, text, compact):
                violations.append(f"仍可能触碰避免项：{rule}")

        must_include = self._string_list(direction.get("must_include"))
        core_angle = str(direction.get("core_angle") or "").strip()
        if core_angle and not self._generic_direction_angle(core_angle):
            must_include = [core_angle] + must_include
        for item in self._dedupe(must_include)[:4]:
            keywords = self._direction_keywords(item)
            matched = sum(1 for keyword in keywords if keyword in compact)
            required_matches = min(2, len(keywords))
            if keywords and matched < required_matches:
                violations.append(f"重点表达不够明显：{item}")

        title_preferences = " ".join(self._string_list(direction.get("title_preferences")))
        if title_preferences and any(marker in title_preferences for marker in ["不要夸张", "标题不要夸张", "口语"]):
            if self._title_is_hype_or_template(title):
                violations.append(f"标题未满足偏好：{title_preferences}")

        return self._dedupe(violations)

    def _direction_avoid_hit(self, rule: str, text: str, compact: str) -> bool:
        if "README" in rule:
            readme_dump = (
                "根据 README" in text
                or "根据README" in compact
                or "readme功能" in compact
                or "readme功能列表" in compact
                or ("README" in text and self._looks_like_feature_dump(text))
            )
            return readme_dump
        if "阅读提示" in rule and "阅读提示" in text:
            return True
        if "教程" in rule and self._looks_like_tutorial(text):
            return True
        if "步骤" in rule and len(re.findall(r"^\s*\d+[.)、]\s+", text, flags=re.MULTILINE)) >= 3:
            return True
        if "功能" in rule and self._looks_like_feature_dump(text):
            return True
        if "实现" in rule and text.count("实现") >= 5:
            return True
        keywords = self._direction_keywords(rule)
        return bool(keywords and any(keyword in compact for keyword in keywords) and not any(marker in rule for marker in ["不要", "少写", "避免", "别写"]))

    def _direction_keywords(self, value: str) -> list[str]:
        text = re.sub(r"\s+", "", str(value or "").lower())
        text = re.sub(r"(不要|少写|避免|别写|不能|不应|重点|突出|主要写|标题|口语|一点|写成|太像)", "", text)
        keywords: list[str] = []
        for token in re.findall(r"[a-z0-9_+-]{2,}", text):
            keywords.append(token)
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            if chunk not in {"作为", "它的", "这篇", "文章", "内容"}:
                keywords.append(chunk[:8])
                for part in re.split(r"[的和与及、，。]+", chunk):
                    if len(part) >= 2 and part not in {"作为", "它的", "这篇", "文章", "内容"}:
                        keywords.append(part[:8])
        return self._dedupe([keyword for keyword in keywords if len(keyword) >= 2])

    def _title_is_hype_or_template(self, title: str) -> bool:
        return any(
            marker in title
            for marker in ["发现一个", "全网", "神器", "爆火", "必备", "吊打", "彻底", "多少 star", "star 项目", "Stars"]
        )

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
        code_commands = len(
            re.findall(
                r"```(?:bash|shell|sh)?|^\s{0,3}(?:pip|npm|pnpm|yarn|docker|uv|python)\s+",
                markdown,
                flags=re.MULTILINE | re.IGNORECASE,
            )
        )
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

    def _missing_appeal_points(self, markdown: str, content_plan: Optional[dict]) -> bool:
        appeal = self._content_plan_appeal(content_plan)
        points = self._string_list(appeal.get("top_selling_points"))
        if not points:
            return False
        text = re.sub(r"\s+", "", markdown.lower())
        matched = 0
        for point in points[:3]:
            keywords = self._appeal_keywords(point)
            if keywords and any(keyword in text for keyword in keywords):
                matched += 1
        return matched == 0

    def _missing_impact_points(self, markdown: str, content_plan: Optional[dict]) -> bool:
        impact = self._content_plan_impact(content_plan)
        if not impact:
            return False
        candidates = (
            self._string_list(impact.get("concrete_outcomes"))
            + self._string_list(impact.get("usage_examples"))
            + self._string_list(impact.get("user_benefits"))
        )
        if not candidates:
            return False
        text = re.sub(r"\s+", "", markdown)
        matched = 0
        for item in candidates[:6]:
            keywords = self._impact_keywords(item)
            if keywords and sum(1 for keyword in keywords if keyword in text) >= min(2, len(keywords)):
                matched += 1
        if matched >= 2:
            return False
        core_keywords = self._impact_keywords(str(impact.get("core_effect") or ""))
        return not core_keywords or sum(1 for keyword in core_keywords if keyword in text) < min(2, len(core_keywords))

    def _impact_keywords(self, value: str) -> list[str]:
        text = re.sub(r"\s+", "", str(value or ""))
        if not text:
            return []
        stopwords = {"这个", "项目", "用户", "可以", "一个", "实际", "使用", "帮助", "更容易", "具体"}
        keywords: list[str] = []
        for token in re.findall(r"[A-Za-z0-9_+-]{3,}", text):
            keywords.append(token.lower())
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            for part in re.split(r"[，。；、的和与及里把为是能让成在]+", chunk):
                if len(part) >= 2 and part not in stopwords:
                    keywords.append(part[:8])
        return self._dedupe(keywords)[:5]

    def _vague_effect_issues(self, markdown: str) -> list[str]:
        issues: list[str] = []
        vague_phrases = ["提升效率", "降低成本", "改善体验"]
        concrete_markers = [
            "信息",
            "整理",
            "报告",
            "判断",
            "上下文",
            "任务",
            "计划",
            "代码",
            "终端",
            "流程",
            "切换",
            "复用",
            "可视化",
            "团队",
            "场景",
            "动作",
            "省掉",
            "先输出",
            "设计文档",
            "实现计划",
            "自我审查",
            "减少返工",
            "直接生成",
        ]
        for phrase in vague_phrases:
            for match in re.finditer(re.escape(phrase), markdown):
                start = max(0, match.start() - 45)
                end = min(len(markdown), match.end() + 70)
                window = markdown[start:end]
                if not any(marker in window for marker in concrete_markers):
                    issues.append(f"空泛效果表达缺少具体说明：{phrase}")
                    break
        return issues

    def _wechat_share_style_issues(self, markdown: str, content_plan: Optional[dict]) -> list[str]:
        issues: list[str] = []
        body = re.sub(r"^\s*#.*$", "", markdown, count=1, flags=re.MULTILINE)
        pattern = (content_plan or {}).get("wechat_pattern") or {}
        required_effects = self._string_list(pattern.get("required_effect_points") if isinstance(pattern, dict) else [])
        required_examples = self._string_list(pattern.get("required_examples") if isinstance(pattern, dict) else [])
        effect_hits = self._concrete_effect_count(body, required_effects)
        example_hits = self._concrete_example_count(body, required_examples)
        if effect_hits < 2:
            issues.append("warning: 具体效果展开不足，至少需要自然展开 2 个效果点")
        if example_hits < 2:
            issues.append("warning: 具体使用例子不足，至少需要 2 个场景例子")
        if self._looks_like_feature_dump_without_benefit(body):
            issues.append("warning: 功能点偏罗列，缺少“解决什么麻烦/用户看到什么变化”的收益解释")
        if self._looks_like_ai_report_tone(body):
            issues.append("warning: 仍有 AI 报告腔或审稿腔")
        return issues

    def _concrete_example_count(self, markdown: str, required_examples: list[str]) -> int:
        compact = re.sub(r"\s+", "", markdown)
        matched = 0
        for example in required_examples[:6]:
            keywords = self._impact_keywords(example)
            if keywords and sum(1 for keyword in keywords if keyword in compact) >= min(2, len(keywords)):
                matched += 1
        scenario_markers = [
            "比如",
            "例如",
            "可以是",
            "放到实际",
            "具体一点",
            "写代码前",
            "任务中断",
            "恢复状态",
            "多工具",
            "临时想法",
            "投资备忘录",
            "信息整理",
        ]
        marker_hits = sum(1 for marker in scenario_markers if marker in markdown)
        return max(matched, min(marker_hits, 3))

    def _concrete_effect_count(self, markdown: str, required_effects: list[str]) -> int:
        compact = re.sub(r"\s+", "", markdown)
        matched = 0
        for effect in required_effects[:6]:
            keywords = self._impact_keywords(effect)
            if keywords and sum(1 for keyword in keywords if keyword in compact) >= min(2, len(keywords)):
                matched += 1
        effect_markers = [
            "解决的是",
            "看到的变化",
            "直接结果",
            "变化在于",
            "省掉",
            "减少",
            "整理",
            "报告",
            "判断",
            "上下文",
            "连续",
            "执行计划",
            "设计文档",
            "实现计划",
            "自我审查",
            "减少返工",
        ]
        marker_hits = sum(1 for marker in effect_markers if marker in markdown)
        return max(matched, min(marker_hits, 4))

    def _looks_like_feature_dump_without_benefit(self, markdown: str) -> bool:
        if not self._looks_like_feature_dump(markdown):
            return False
        benefit_markers = ["解决", "麻烦", "变化", "省掉", "减少", "看到", "不用", "更容易", "具体"]
        return sum(1 for marker in benefit_markers if marker in markdown) < 3

    def _looks_like_ai_report_tone(self, markdown: str) -> bool:
        markers = [
            "本文将",
            "从以下几个方面",
            "综上",
            "具有较高",
            "参考价值",
            "建议结合实际情况",
            "资料显示",
            "根据 README",
            "数据可能变化",
            "需注明",
        ]
        return any(marker in markdown for marker in markers)

    def _appeal_keywords(self, value: str) -> list[str]:
        text = re.sub(r"\s+", "", str(value or "").lower())
        if not text:
            return []
        keywords = [text[:18]]
        for token in re.findall(r"[a-z0-9_+-]{3,}", text):
            keywords.append(token)
        chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        keywords.extend(chunk[:8] for chunk in chinese_chunks)
        return self._dedupe([keyword for keyword in keywords if len(keyword) >= 2])

    def _trim_sentence(self, value: str) -> str:
        return str(value or "").strip().rstrip("。；;，, ")

    def _normalize_heading(self, line: str) -> str:
        return self._clean_heading_title(re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip())

    def _clean_heading_title(self, value: str) -> str:
        return str(value).strip().strip("#").strip("：: ")

    def _line_needs_natural_note(self, line: str) -> bool:
        return any(term in line for term in ["使用", "采用", "商用", "团队", "生产", "测试"])

    def _looks_like_risk_bullet(self, line: str) -> bool:
        return any(
            term in line
            for term in [
                "商用",
                "生产",
                "open issues",
                "Open Issues",
                "许可证",
                "许可",
                "部署前",
                "需要自行评估",
                "需要用户自行评估",
                "并非万能",
                "待解决",
            ]
        )

    def _ensure_heading(self, title: str, markdown: str) -> str:
        content = markdown.strip()
        if re.search(r"^\s*#\s+", content, flags=re.MULTILINE):
            return re.sub(r"^\s*#\s+.*$", f"# {title}", content, count=1, flags=re.MULTILINE)
        return f"# {title}\n\n{content}"

    def _wechat_publish_title(
        self,
        title: str,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict],
    ) -> str:
        clean = str(title or "").strip()
        if clean and not self._generic_or_old_title(clean) and not self._unsafe_investment_title(clean, note):
            return clean
        pattern = (content_plan or {}).get("wechat_pattern") or {}
        project_name = str((content_plan or {}).get("full_name") or (note.full_name if note else "") or "").split("/")[-1] or "这个项目"
        effect = self._title_effect_phrase(content_plan, note)
        formula = str(pattern.get("title_formula") or "").strip() if isinstance(pattern, dict) else ""
        if formula and not any(marker in formula for marker in ["不要", "标题要求"]):
            refreshed = formula.replace("XXX", effect).replace("A + B = C", f"{project_name} + 工作流 = {effect}")
            refreshed = refreshed.replace("N Star", f"{self._format_stars(note.stars)} Star" if note and note.stars else project_name)
            refreshed = re.sub(r"一周狂揽\s*", "", refreshed)
            return self._truncate(refreshed, 44)
        if note and note.stars >= 10000:
            return f"{self._format_stars(note.stars)} Star，{project_name} 这个项目有点东西"
        return f"这个开源项目，把{effect}做得很顺手"

    def _unsafe_investment_title(self, title: str, note: Optional[RepoResearchNote]) -> bool:
        source = " ".join([note.full_name if note else "", note.description if note else ""]).lower()
        if not any(word in source for word in ["berkshire", "invest", "stock", "投资", "股票"]):
            return False
        return any(marker in title for marker in ["收益", "业绩", "买入", "持有", "卖出", "稳赚", "真香"])

    def _generic_or_old_title(self, title: str) -> bool:
        compact = re.sub(r"\s+", "", title)
        return any(
            marker in compact
            for marker in ["发现一个", "值得顺手点开", "值得放进工具箱", "值得关注", "star项目", "stars项目"]
        )

    def _title_effect_phrase(self, content_plan: Optional[dict], note: Optional[RepoResearchNote]) -> str:
        impact = self._content_plan_impact(content_plan)
        appeal = self._content_plan_appeal(content_plan)
        candidates = (
            self._string_list(impact.get("concrete_outcomes"))
            + self._string_list(impact.get("usage_examples"))
            + self._string_list(appeal.get("top_selling_points"))
            + self._string_list(appeal.get("practical_scenarios"))
        )
        for candidate in candidates:
            text = re.sub(r"\s+", "", self._trim_sentence(candidate))
            text = re.sub(r"^(把|让|帮助|可以|能够|用户|开发者|读者)", "", text)
            if len(text) >= 4:
                return text[:12]
        if note and note.project_kind in {"self_hosted", "ai_agent"}:
            return "AI工作流"
        if note and note.project_kind in {"cli_tool", "developer_tool", "productivity_tool"}:
            return "日常工具链"
        return "真实工作流"

    def _format_stars(self, stars: int) -> str:
        if stars >= 10000:
            value = stars / 10000
            return f"{value:.1f}w".replace(".0w", "w")
        if stars >= 1000:
            value = stars / 1000
            return f"{value:.1f}k".replace(".0k", "k")
        return str(stars)

    def _cleanup_markdown(self, markdown: str) -> str:
        content = markdown.replace("\r\n", "\n").replace("\r", "\n")
        content = re.sub(r"[ \t]+\n", "\n", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r"\n\s*-\s*\n", "\n", content)
        content = re.sub(r"(如果要放进团队流程，最好先在自己的项目里跑一圈。\n?){2,}", "如果要放进团队流程，最好先在自己的项目里跑一圈。\n", content)
        return content.strip() + "\n"

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

    def _truncate(self, text: str, limit: int) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _count_text(self, text: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text))

    def _model_dump(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "dict"):
            return value.dict()
        return value if isinstance(value, dict) else {}
