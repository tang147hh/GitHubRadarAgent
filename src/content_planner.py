from __future__ import annotations

import json
import re
from typing import Any, Optional

from .editorial_strategy import EditorialStrategyService
from .llm_service import LLMService
from .models import CustomArticleDirection, EditorialBrief, FactCard, ProjectInsight, RepoResearchNote, StyleReferenceProfile, TopicAngle
from .project_appeal import ProjectAppealService
from .project_impact import ProjectImpactService
from .wechat_style_strategy import WechatStyleStrategyService


class ContentPlanningService:
    """Build content planning intermediates before article writing."""

    NARRATIVE_PATTERNS = {
        "scene_first",
        "pain_point_first",
        "discovery_note",
        "comparison",
        "hands_on",
        "trend_context",
    }

    REQUIRED_AVOID_ITEMS = [
        "不要频繁写“根据 README”",
        "不要直接搬运 README 原句",
        "不要用固定的“核心亮点/适合谁/小结”模板",
        "不要夸大未验证能力",
    ]

    DEFAULT_VISUAL_NEEDS = [
        "GitHub 项目首页截图",
        "项目能力关系图",
        "使用场景示意图",
    ]

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.warnings: list[str] = []

    def build_content_plan(
        self,
        note: RepoResearchNote,
        angle: Optional[TopicAngle] = None,
        custom_direction: Optional[CustomArticleDirection] = None,
        style_reference_profile: Optional[StyleReferenceProfile] = None,
    ) -> dict[str, Any]:
        plan_warnings: list[str] = []
        facts = self._build_fact_cards(note)
        insight, insight_used_llm, insight_warnings = self._build_project_insight(note, facts, angle)
        brief, brief_used_llm, brief_warnings = self._build_editorial_brief(note, facts, insight, angle)
        appeal_service = ProjectAppealService(llm_service=self.llm_service)
        appeal = appeal_service.build_appeal(note=note, insight=insight, facts=facts, brief=brief)
        impact_service = ProjectImpactService(llm_service=self.llm_service)
        impact = impact_service.build_impact(
            note=note,
            appeal=appeal,
            brief=brief,
            custom_direction=custom_direction,
        )
        wechat_strategy_service = WechatStyleStrategyService(llm_service=self.llm_service)
        wechat_pattern = wechat_strategy_service.build_pattern(
            note=note,
            appeal=appeal,
            impact=impact,
            custom_direction=custom_direction,
            style_reference_profile=style_reference_profile,
        )
        plan_warnings.extend(insight_warnings)
        plan_warnings.extend(brief_warnings)
        plan_warnings.extend(appeal_service.warnings)
        plan_warnings.extend(impact_service.warnings)
        plan_warnings.extend(wechat_strategy_service.warnings)

        planning_mode = (
            "llm"
            if (
                insight_used_llm
                or brief_used_llm
                or appeal_service.last_used_llm
                or impact_service.last_used_llm
                or wechat_strategy_service.last_used_llm
            )
            else "fallback"
        )
        if planning_mode == "llm":
            self.used_llm = True
        self.warnings.extend(plan_warnings)

        return {
            "full_name": note.full_name,
            "project_kind": note.project_kind,
            "tool_use_cases": note.tool_use_cases,
            "author_profile": note.author_profile,
            "project_links": note.project_links,
            "facts": facts,
            "insight": insight,
            "brief": brief,
            "appeal": appeal,
            "impact": impact,
            "wechat_pattern": wechat_pattern,
            "planning_mode": planning_mode,
            "warnings": plan_warnings,
        }

    def build_content_plans(self, notes: list[RepoResearchNote], angles: list[TopicAngle]) -> list[dict[str, Any]]:
        angles_by_name = {angle.full_name: angle for angle in angles}
        return [
            self.build_content_plan(note, angles_by_name.get(note.full_name))
            for note in notes
        ]

    def _build_fact_cards(self, note: RepoResearchNote) -> list[FactCard]:
        facts: list[FactCard] = []
        repo_source = note.html_url or f"https://github.com/{note.full_name}"

        facts.append(
            self._fact(
                note,
                f"{note.full_name} 在 GitHub 上约有 {note.stars} stars、{note.forks} forks。",
                "metric",
                repo_source,
                "github_repo",
                "high",
                True,
            )
        )

        if note.license_name:
            facts.append(
                self._fact(
                    note,
                    f"仓库标注的许可证是 {note.license_name}。",
                    "license",
                    repo_source,
                    "github_repo",
                    "high",
                    True,
                )
            )
        else:
            facts.append(
                self._fact(
                    note,
                    "仓库资料中没有明确识别到许可证信息，采用前需要额外确认授权边界。",
                    "license",
                    repo_source,
                    "github_repo",
                    "medium",
                    True,
                    "缺少许可证信息更适合作为采用风险提示，不宜当作项目缺陷放大。",
                )
            )

        if note.pushed_at:
            facts.append(
                self._fact(
                    note,
                    f"仓库最近一次 push 时间为 {note.pushed_at}。",
                    "maintenance",
                    repo_source,
                    "github_repo",
                    "high",
                    True,
                )
            )

        if note.project_kind:
            facts.append(
                self._fact(
                    note,
                    f"项目类型识别为 {note.project_kind}。",
                    "project_kind",
                    repo_source,
                    "derived",
                    "medium",
                    True,
                )
            )

        if note.author_profile:
            author = note.author_profile
            facts.append(
                self._fact(
                    note,
                    f"作者/组织 GitHub 主页为 {author.html_url}。",
                    "author",
                    author.html_url,
                    "github_profile",
                    "high",
                    True,
                )
            )
            author_parts = []
            if author.name:
                author_parts.append(f"名称：{author.name}")
            if author.type:
                author_parts.append(f"类型：{author.type}")
            if author.bio:
                author_parts.append(f"简介：{author.bio}")
            if author.company:
                author_parts.append(f"公司/组织：{author.company}")
            if author.blog:
                author_parts.append(f"主页/博客：{author.blog}")
            if author.followers is not None:
                author_parts.append(f"followers：{author.followers}")
            if author.public_repos is not None:
                author_parts.append(f"公开仓库：{author.public_repos}")
            if author_parts:
                facts.append(
                    self._fact(
                        note,
                        "作者/组织资料：" + "；".join(author_parts) + "。",
                        "author",
                        author.html_url,
                        "github_profile",
                        "high",
                        True,
                    )
                )

        if note.project_links:
            link_facts = [
                ("homepage", note.project_links.homepage, "项目主页"),
                ("documentation", note.project_links.documentation, "文档链接"),
                ("demo", note.project_links.demo, "Demo/预览链接"),
                ("examples", note.project_links.examples, "示例链接"),
            ]
            for category, value, label in link_facts:
                values = [value] if isinstance(value, str) and value else list(value or [])
                for link in values[:5]:
                    facts.append(
                        self._fact(
                            note,
                            f"{label}：{link}",
                            "project_link",
                            link,
                            category,
                            "high",
                            category != "examples",
                        )
                    )

        tech_parts = []
        if note.language:
            tech_parts.append(f"主要语言为 {note.language}")
        if note.topics:
            tech_parts.append(f"topics 包含 {', '.join(note.topics[:8])}")
        if tech_parts:
            facts.append(
                self._fact(
                    note,
                    "；".join(tech_parts) + "。",
                    "ecosystem",
                    repo_source,
                    "github_repo",
                    "high",
                    True,
                )
            )

        for release in note.releases[:3]:
            title = self._release_title(release)
            published_at = release.get("published_at") or "未知时间"
            source = release.get("html_url") or repo_source
            facts.append(
                self._fact(
                    note,
                    f"最近 release 包含 {title}，发布时间为 {published_at}。",
                    "release",
                    source,
                    "release",
                    "high" if release.get("html_url") else "medium",
                    True,
                )
            )

        for issue in note.open_issues[:3]:
            title = self._clean_text(str(issue.get("title") or "未命名 issue"))
            comments = issue.get("comments")
            source = issue.get("html_url") or repo_source
            comment_text = f"，已有 {comments} 条评论" if comments is not None else ""
            facts.append(
                self._fact(
                    note,
                    f"当前 open issue 样本包含「{title}」{comment_text}。",
                    "issue",
                    source,
                    "issue",
                    "medium",
                    True,
                    "适合作为使用前关注点，不代表项目整体质量结论。",
                )
            )

        for link in self._dedupe(note.source_links or [repo_source])[:8]:
            facts.append(
                self._fact(
                    note,
                    f"调研资料包含来源链接：{link}",
                    "ecosystem",
                    link,
                    "docs" if "docs" in link.lower() else "github_repo",
                    "high",
                    False,
                    "来源链接用于核验事实，一般不直接写成文章正文事实。",
                )
            )

        for point in note.readme_key_points[:8]:
            claim = self._readme_point_to_claim(point)
            if claim:
                facts.append(
                    self._fact(
                        note,
                        claim,
                        "capability",
                        repo_source,
                        "readme",
                        "medium",
                        True,
                    )
                )

        for use_case in note.tool_use_cases[:6]:
            claim = self._clean_text(use_case)
            if claim:
                facts.append(
                    self._fact(
                        note,
                        f"可观察的使用场景：{claim}",
                        "use_case",
                        repo_source,
                        "derived",
                        "medium",
                        True,
                    )
                )

        for risk in note.risks:
            claim = self._clean_text(risk)
            if claim:
                facts.append(
                    self._fact(
                        note,
                        f"使用前需要注意：{claim}",
                        "risk",
                        repo_source,
                        "derived",
                        "medium",
                        True,
                    )
                )

        return self._dedupe_facts(facts)

    def _build_project_insight(
        self,
        note: RepoResearchNote,
        facts: list[FactCard],
        angle: Optional[TopicAngle],
    ) -> tuple[ProjectInsight, bool, list[str]]:
        warnings: list[str] = []
        if self.llm_service is not None and self.llm_service.is_available():
            content = self.llm_service.chat(
                system_prompt=self._insight_system_prompt(),
                user_prompt=self._insight_user_prompt(note, facts, angle),
                temperature=0.45,
            )
            if content.startswith(LLMService.WARNING_PREFIX):
                warnings.append(content)
            else:
                try:
                    payload = self._extract_json_object(content)
                    payload["full_name"] = note.full_name
                    payload["project_name"] = payload.get("project_name") or self._project_name(note)
                    for key in (
                        "ideal_users",
                        "use_cases",
                        "standout_points",
                        "adoption_notes",
                        "not_to_overclaim",
                    ):
                        payload[key] = self._string_list(payload.get(key))
                    payload["source_fact_ids"] = self._normalize_int_list(payload.get("source_fact_ids")) or list(
                        range(min(len(facts), 8))
                    )
                    return self._parse_project_insight(payload), True, warnings
                except Exception as exc:
                    warnings.append(f"LLM ProjectInsight JSON parse failed for {note.full_name}, fallback used: {exc}")

        return self._fallback_project_insight(note, facts, angle), False, warnings

    def _build_editorial_brief(
        self,
        note: RepoResearchNote,
        facts: list[FactCard],
        insight: ProjectInsight,
        angle: Optional[TopicAngle],
    ) -> tuple[EditorialBrief, bool, list[str]]:
        strategy_service = EditorialStrategyService(llm_service=self.llm_service)
        brief = strategy_service.build_strategy(note=note, insight=insight, facts=facts, angle=angle)
        return brief, strategy_service.last_used_llm, strategy_service.warnings

    def _fallback_project_insight(
        self,
        note: RepoResearchNote,
        facts: list[FactCard],
        angle: Optional[TopicAngle],
    ) -> ProjectInsight:
        project_name = self._project_name(note)
        summary_source = angle.one_liner if angle and angle.one_liner else note.description or note.readme_summary
        plain_summary = self._zh_summary(summary_source, project_name)
        capability_claims = [
            fact.claim for fact in facts if fact.category == "capability" and fact.publishable
        ][:4]
        risk_claims = [
            self._strip_risk_prefix(fact.claim) for fact in facts if fact.category in {"risk", "issue", "license"}
        ][:5]
        is_tool_project = note.project_kind in {"developer_tool", "productivity_tool", "cli_tool", "self_hosted"}

        if angle and angle.target_readers:
            target_readers = angle.target_readers
        elif is_tool_project:
            target_readers = ["开发者工具使用者", "效率工具爱好者", "开源项目选型者"]
        else:
            target_readers = ["技术开发者", "AI 应用开发者", "开源项目选型者"]
        selling_points = angle.selling_points if angle and angle.selling_points else capability_claims
        if angle and angle.reader_pain_points:
            use_cases = angle.reader_pain_points
        elif note.tool_use_cases:
            use_cases = note.tool_use_cases
        else:
            use_cases = selling_points
        topic_text = "、".join(note.topics[:5]) if note.topics else (note.language or "相关技术")
        problem_solved = (
            f"它更适合从具体工作流切入：帮助读者判断这个 {note.project_kind} 能否解决日常开发、效率或自部署中的实际问题。"
            if is_tool_project
            else (
                f"它主要帮助关注 {topic_text} 的读者理解并尝试一个具体开源实现。"
                if topic_text
                else "它提供了一个可调研、可参考的开源项目实现。"
            )
        )
        local_context = (
            "对中文开发者来说，它更适合写成项目分享或工具推荐：先讲清楚使用场景，再提醒部署、授权和维护边界。"
            if is_tool_project
            else "对中文开发者来说，它更适合作为选型调研和工程参考，而不是只凭 star 数直接采用。"
        )

        return ProjectInsight(
            full_name=note.full_name,
            project_name=project_name,
            plain_summary=plain_summary,
            problem_solved=problem_solved,
            core_value=self._fallback_core_value(note, selling_points),
            ideal_users=self._dedupe(target_readers)[:5],
            use_cases=self._dedupe([self._clean_text(item) for item in use_cases])[:6],
            standout_points=self._dedupe([self._clean_text(item) for item in selling_points + capability_claims])[:6],
            adoption_notes=risk_claims or ["采用前需要结合文档、issue、release 和自身场景做二次验证。"],
            local_context=local_context,
            not_to_overclaim=self._fallback_not_to_overclaim(note, risk_claims),
            source_fact_ids=list(range(min(len(facts), 10))),
        )

    def _fallback_editorial_brief(
        self,
        note: RepoResearchNote,
        facts: list[FactCard],
        insight: ProjectInsight,
        angle: Optional[TopicAngle],
    ) -> EditorialBrief:
        narrative_pattern = self._select_narrative_pattern(note)
        target_reader = "、".join(insight.ideal_users[:3]) or "中文技术读者"
        must_include = [
            insight.plain_summary,
            insight.core_value,
            f"GitHub stars/forks：{note.stars}/{note.forks}",
        ]
        must_include.extend([fact.claim for fact in facts if fact.publishable][:4])

        return EditorialBrief(
            full_name=note.full_name,
            recommended_angle=angle.selected_angle if angle and angle.selected_angle else insight.core_value,
            narrative_pattern=narrative_pattern,
            target_reader=target_reader,
            reader_takeaway=f"读者读完后应能判断 {insight.project_name} 是否值得继续调研或试用。",
            title_direction=self._fallback_title_directions(note, insight),
            opening_direction=(
                "从一个具体使用场景或选型疑问切入，再自然带出项目，而不是先罗列 README 功能。"
            ),
            must_include=self._dedupe(must_include)[:8],
            should_avoid=self.REQUIRED_AVOID_ITEMS + insight.not_to_overclaim[:4],
            suggested_structure=[
                "先写一个读者可能遇到的真实问题或发现项目的理由",
                "用两三句话讲清楚项目到底是什么",
                "挑选最值得看的事实和能力做解释，不逐条搬运功能列表",
                "结合适用人群和使用场景说明价值边界",
                "最后提醒采用前需要核验的风险和资料入口",
            ],
            tone="像一个懂技术的朋友分享，克制但有判断",
            visual_needs=self.DEFAULT_VISUAL_NEEDS,
        )

    def _fact(
        self,
        note: RepoResearchNote,
        claim: str,
        category: str,
        source: str,
        source_type: str,
        confidence: str,
        publishable: bool,
        note_text: Optional[str] = None,
    ) -> FactCard:
        return FactCard(
            full_name=note.full_name,
            claim=self._clean_claim(claim),
            category=category,
            source=source or note.html_url or f"https://github.com/{note.full_name}",
            source_type=source_type,
            confidence=confidence,
            publishable=publishable,
            note=note_text,
        )

    def _insight_system_prompt(self) -> str:
        return (
            "你是一个技术产品分析师。你的任务不是搬运 README，而是把 GitHub 项目资料转化成中文读者能理解的项目洞察。"
            "你必须基于事实卡和调研资料，不得编造功能、数据、作者背景。不要写“根据 README”。输出严格 JSON。"
        )

    def _insight_user_prompt(
        self,
        note: RepoResearchNote,
        facts: list[FactCard],
        angle: Optional[TopicAngle],
    ) -> str:
        payload = {
            "repo_research_note": self._note_payload(note),
            "topic_angle": self._model_dump(angle) if angle is not None else None,
            "facts": [self._model_dump(fact) for fact in facts],
        }
        return (
            "请输出 ProjectInsight JSON 字段：plain_summary, problem_solved, core_value, "
            "ideal_users, use_cases, standout_points, adoption_notes, local_context, not_to_overclaim, source_fact_ids。"
            "plain_summary 必须用中文解释项目到底是什么，不要出现“根据 README”。"
            "source_fact_ids 可以使用 facts 数组索引。输入资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _brief_system_prompt(self) -> str:
        return (
            "你是一位技术公众号主编。你的任务是为一篇开源项目分享文章制定选题 brief。"
            "你要避免 AI 模板稿、避免固定二级标题、避免 README 搬运。"
            "文章应该像一个懂技术的人在分享项目价值。输出严格 JSON。"
        )

    def _brief_user_prompt(
        self,
        note: RepoResearchNote,
        facts: list[FactCard],
        insight: ProjectInsight,
        angle: Optional[TopicAngle],
    ) -> str:
        payload = {
            "repo": {
                "full_name": note.full_name,
                "html_url": note.html_url,
                "stars": note.stars,
                "forks": note.forks,
                "language": note.language,
                "topics": note.topics,
                "license_name": note.license_name,
                "pushed_at": note.pushed_at,
                "project_kind": note.project_kind,
                "author_profile": self._model_dump(note.author_profile) if note.author_profile else None,
                "project_links": self._model_dump(note.project_links) if note.project_links else None,
                "tool_use_cases": note.tool_use_cases,
            },
            "insight": self._model_dump(insight),
            "facts": [self._model_dump(fact) for fact in facts],
            "topic_angle": self._model_dump(angle) if angle is not None else None,
        }
        return (
            "请输出 EditorialBrief JSON 字段：recommended_angle, narrative_pattern, target_reader, reader_takeaway, "
            "title_direction, opening_direction, must_include, should_avoid, suggested_structure, tone, visual_needs。"
            "narrative_pattern 必须从 scene_first, pain_point_first, discovery_note, comparison, hands_on, trend_context 中选一个。"
            "title_direction 给 4-6 个方向，不要都是“发现一个 X star 项目”。suggested_structure 是自然段落/内容推进建议，"
            "不是强制 Markdown 二级标题。should_avoid 必须包含：不要频繁写“根据 README”、不要直接搬运 README 原句、"
            "不要用固定的“核心亮点/适合谁/小结”模板、不要夸大未验证能力。输入资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _note_payload(self, note: RepoResearchNote) -> dict[str, Any]:
        return {
            "full_name": note.full_name,
            "html_url": note.html_url,
            "description": note.description,
            "stars": note.stars,
            "forks": note.forks,
            "language": note.language,
            "topics": note.topics,
            "license_name": note.license_name,
            "pushed_at": note.pushed_at,
            "author_profile": self._model_dump(note.author_profile) if note.author_profile else None,
            "project_links": self._model_dump(note.project_links) if note.project_links else None,
            "readme_images": note.readme_images,
            "readme_links": note.readme_links,
            "tool_use_cases": note.tool_use_cases,
            "project_kind": note.project_kind,
            "readme_summary": note.readme_summary,
            "readme_key_points": note.readme_key_points,
            "releases": note.releases,
            "open_issues": note.open_issues,
            "source_links": note.source_links,
            "risks": note.risks,
        }

    def _parse_project_insight(self, payload: dict[str, Any]) -> ProjectInsight:
        if hasattr(ProjectInsight, "model_validate"):
            return ProjectInsight.model_validate(payload)
        return ProjectInsight.parse_obj(payload)

    def _parse_editorial_brief(self, payload: dict[str, Any]) -> EditorialBrief:
        if hasattr(EditorialBrief, "model_validate"):
            return EditorialBrief.model_validate(payload)
        return EditorialBrief.parse_obj(payload)

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

    def _readme_point_to_claim(self, value: str) -> str:
        text = self._clean_text(value)
        text = re.sub(r"^(according to|based on)\s+(the\s+)?readme[:,]?\s*", "", text, flags=re.I)
        text = text.replace("根据 README", "").replace("README 中提到", "").strip(" :：-")
        if not text:
            return ""
        text = self._truncate(text, 140)
        if self._looks_english(text):
            return f"项目资料显示，它提供了与 {self._english_keyword_hint(text)} 相关的能力。"
        if not text.endswith(("。", "！", "？")):
            text = f"{text}。"
        return text

    def _release_title(self, release: dict[str, Any]) -> str:
        raw_title = str(release.get("name") or release.get("tag_name") or "").strip()
        title = self._clean_text(raw_title)
        return title or raw_title or "未命名 release"

    def _zh_summary(self, value: str, project_name: str) -> str:
        text = self._clean_text(value)
        if not text:
            return f"{project_name} 是一个值得进一步调研的 GitHub 开源项目。"
        if self._looks_english(text):
            return f"{project_name} 是一个围绕 {self._english_keyword_hint(text)} 的开源项目，适合先作为技术选型和工程参考来了解。"
        text = text.replace("根据 README", "").replace("README", "项目资料")
        return self._truncate(text, 180)

    def _fallback_core_value(self, note: RepoResearchNote, selling_points: list[str]) -> str:
        if selling_points:
            return self._truncate(self._clean_text(selling_points[0]), 160)
        if note.stars >= 10000:
            return f"它已有较高开源关注度，适合作为 {note.language or '相关领域'} 项目的重点调研对象。"
        if note.pushed_at:
            return f"它近期仍有维护痕迹，适合结合文档和 issue 继续评估工程可用性。"
        return "它的价值主要在于提供一个可观察、可复盘的开源实现样本。"

    def _fallback_not_to_overclaim(self, note: RepoResearchNote, risk_claims: list[str]) -> list[str]:
        claims = risk_claims[:]
        if not note.license_name:
            claims.append("不要默认它已经具备清晰的商用授权条件。")
        claims.extend(
            [
                "不要把 GitHub stars 等同于生产可用性。",
                "不要声称它能替代同类成熟产品，除非有独立对比依据。",
                "不要编造用户规模、性能数据或作者背景。",
            ]
        )
        return self._dedupe(claims)[:8]

    def _select_narrative_pattern(self, note: RepoResearchNote) -> str:
        if note.project_kind in {"developer_tool", "cli_tool", "productivity_tool"}:
            return "scene_first"
        if note.project_kind == "self_hosted":
            return "pain_point_first"
        if note.project_kind == "library_framework":
            return "trend_context"
        if note.project_kind == "ai_agent":
            return "pain_point_first"
        text = " ".join([note.full_name, note.description or "", note.language or "", *note.topics]).lower()
        if note.stars < 1000:
            return "discovery_note"
        if any(keyword in text for keyword in ["framework", "sdk", "library"]):
            return "trend_context"
        if any(keyword in text for keyword in ["tool", "cli", "automation", "workflow"]):
            return "scene_first"
        return "pain_point_first"

    def _fallback_title_directions(self, note: RepoResearchNote, insight: ProjectInsight) -> list[str]:
        project_name = insight.project_name
        topic = note.topics[0] if note.topics else (note.language or "开源项目")
        return [
            f"从一个具体使用场景切入介绍 {project_name}",
            f"围绕 {topic} 选型解释它为什么值得调研",
            f"用 stars、维护状态和风险边界做克制推荐",
            f"把 {project_name} 写成一次技术发现笔记",
            "标题中保留项目真实用途，不只强调 star 数",
        ]

    def _valid_narrative_pattern(self, value: Any) -> str:
        pattern = str(value or "").strip()
        return pattern if pattern in self.NARRATIVE_PATTERNS else "pain_point_first"

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [self._clean_text(str(item)) for item in value if self._clean_text(str(item))]
        if isinstance(value, str) and value.strip():
            return [self._clean_text(value)]
        return []

    def _normalize_int_list(self, value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result

    def _dedupe_facts(self, facts: list[FactCard]) -> list[FactCard]:
        seen: set[tuple[str, str]] = set()
        result: list[FactCard] = []
        for fact in facts:
            key = (fact.category, fact.claim)
            if fact.claim and key not in seen:
                seen.add(key)
                result.append(fact)
        return result

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = self._clean_text(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _clean_claim(self, value: str) -> str:
        text = self._clean_text(value)
        text = text.replace("根据 README", "").replace("According to the README", "")
        return text.strip()

    def _clean_text(self, value: str) -> str:
        text = value.strip()
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"^\s*[-*#+>\d.)]+\s*", "", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _strip_risk_prefix(self, value: str) -> str:
        return re.sub(r"^使用前需要注意：", "", value).strip()

    def _looks_english(self, text: str) -> bool:
        letters = sum(1 for char in text if ("a" <= char.lower() <= "z"))
        chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        return letters > chinese * 2 and letters > 20

    def _english_keyword_hint(self, text: str) -> str:
        lowered = text.lower()
        keyword_map = [
            ("agent", "AI Agent"),
            ("rag", "RAG"),
            ("workflow", "工作流"),
            ("automation", "自动化"),
            ("llm", "LLM 应用"),
            ("mcp", "MCP 集成"),
            ("framework", "框架开发"),
            ("tool", "工具链"),
        ]
        hits = [label for keyword, label in keyword_map if keyword in lowered]
        return "、".join(self._dedupe(hits)[:3]) if hits else "项目描述中的核心场景"

    def _truncate(self, value: str, limit: int) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _project_name(self, note: RepoResearchNote) -> str:
        return note.full_name.split("/")[-1] if note.full_name else "unknown-project"

    def _model_dump(self, model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
