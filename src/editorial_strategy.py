from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import (
    EditorialBrief,
    FactCard,
    NarrativeStrategy,
    ProjectInsight,
    RepoResearchNote,
    TitleCandidate,
    TitleStrategy,
    TopicAngle,
)


class EditorialStrategyService:
    """Build editor-level narrative and title strategies for content plans."""

    NARRATIVE_PATTERNS = {
        "scene_first",
        "pain_point_first",
        "discovery_note",
        "comparison",
        "hands_on",
        "trend_context",
        "story_first",
        "listicle",
    }
    OPENING_STYLES = {
        "concrete_scene",
        "direct_question",
        "surprising_fact",
        "personal_discovery",
        "pain_point",
        "contrast",
    }
    STRUCTURE_STYLES = {
        "no_headings",
        "soft_sections",
        "short_blocks",
        "numbered_notes",
        "qa_style",
    }
    TITLE_STYLES = {
        "practical_benefit",
        "curiosity_gap",
        "pain_solution",
        "comparison",
        "understated_recommendation",
        "tool_collection",
    }
    REQUIRED_AVOID_ITEMS = [
        "不要频繁写“根据 README”",
        "不要直接搬运 README 原句",
        "不要用固定的“这个项目是什么/核心亮点/适合谁/小结”结构",
        "不要夸大未验证能力",
    ]
    HUMAN_TONE_RULES = [
        "少用“值得关注”",
        "少用“根据 README”",
        "不要直接复制英文原句",
        "不要每段都用总结式口吻",
        "不要写成说明书",
        "允许有判断，但要有来源",
        "先说使用场景，再说项目能力",
    ]
    BANNED_TITLE_TEMPLATES = [
        "发现一个 X star 项目",
        "GitHub 上这个项目...",
        "README 里...",
        "X stars 说明它很火",
        "又一个值得关注的开源项目",
    ]
    DEFAULT_VISUAL_NEEDS = [
        "GitHub 项目首页截图",
        "项目能力关系图",
        "使用场景示意图",
    ]

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.last_used_llm = False
        self.warnings: list[str] = []

    def build_strategy(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        angle: Optional[TopicAngle] = None,
    ) -> EditorialBrief:
        self.last_used_llm = False
        if self.llm_service is not None and self.llm_service.is_available():
            content = self.llm_service.chat(
                system_prompt=self._strategy_system_prompt(),
                user_prompt=self._strategy_user_prompt(note, insight, facts, angle),
                temperature=0.65,
            )
            if content.startswith(LLMService.WARNING_PREFIX):
                self.warnings.append(content)
            else:
                try:
                    brief = self._brief_from_llm_payload(
                        note=note,
                        insight=insight,
                        facts=facts,
                        angle=angle,
                        payload=self._extract_json_object(content),
                    )
                    self.used_llm = True
                    self.last_used_llm = True
                    return brief
                except Exception as exc:
                    self.warnings.append(
                        f"LLM EditorialStrategy JSON parse failed for {note.full_name}, fallback used: {exc}"
                    )

        return self._fallback_strategy(note, insight, facts, angle)

    def build_strategies(
        self,
        content_plans: list[dict],
        notes: list[RepoResearchNote],
        angles: list[TopicAngle],
    ) -> list[EditorialBrief]:
        notes_by_name = {note.full_name: note for note in notes}
        angles_by_name = {angle.full_name: angle for angle in angles}
        briefs: list[EditorialBrief] = []
        for plan in content_plans:
            full_name = plan.get("full_name")
            note = notes_by_name.get(full_name)
            insight = plan.get("insight")
            facts = plan.get("facts") or []
            if note is None or insight is None:
                continue
            briefs.append(self.build_strategy(note, insight, facts, angles_by_name.get(full_name)))
        return briefs

    def _brief_from_llm_payload(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        angle: Optional[TopicAngle],
        payload: dict[str, Any],
    ) -> EditorialBrief:
        payload = dict(payload)
        raw_narrative_strategy = payload.get("narrative_strategy")
        raw_title_strategy = payload.get("title_strategy")
        narrative_strategy_payload = raw_narrative_strategy if isinstance(raw_narrative_strategy, dict) else {}
        title_strategy_payload = raw_title_strategy if isinstance(raw_title_strategy, dict) else {}
        payload["full_name"] = note.full_name
        payload["narrative_pattern"] = self._valid_value(
            payload.get("narrative_pattern") or narrative_strategy_payload.get("pattern"),
            self.NARRATIVE_PATTERNS,
            self._fallback_narrative_values(note)["pattern"],
        )
        payload["recommended_angle"] = self._clean_text(
            payload.get("recommended_angle") or (angle.selected_angle if angle else "") or insight.core_value
        )
        payload["target_reader"] = self._clean_text(
            payload.get("target_reader") or "、".join(insight.ideal_users[:3]) or "中文技术读者"
        )
        payload["reader_takeaway"] = self._clean_text(
            payload.get("reader_takeaway") or f"判断 {insight.project_name} 是否值得继续调研或试用。"
        )
        payload["title_direction"] = self._dedupe(
            self._string_list(payload.get("title_direction")) + self._string_list(title_strategy_payload.get("directions"))
        )[:8]
        payload["opening_direction"] = self._clean_text(
            payload.get("opening_direction") or payload.get("opening_style") or "从具体场景切入，再带出项目能力。"
        )
        payload["must_include"] = self._dedupe(
            self._string_list(payload.get("must_include")) + self._must_include(note, insight, facts)
        )[:10]
        payload["should_avoid"] = self._dedupe(
            self._string_list(payload.get("should_avoid")) + self.REQUIRED_AVOID_ITEMS
        )
        payload["suggested_structure"] = self._string_list(payload.get("suggested_structure"))
        payload["tone"] = self._clean_text(payload.get("tone") or "像一个懂技术的朋友分享，克制但有判断")
        payload["visual_needs"] = self._string_list(payload.get("visual_needs")) or self.DEFAULT_VISUAL_NEEDS

        narrative_strategy = self._normalize_narrative_strategy(raw_narrative_strategy, note)
        title_strategy = self._normalize_title_strategy(raw_title_strategy, note, insight, angle)
        payload["narrative_strategy"] = self._model_dump(narrative_strategy)
        payload["title_strategy"] = self._model_dump(title_strategy)
        payload["article_differentiators"] = self._dedupe(
            self._string_list(payload.get("article_differentiators")) + self._fallback_differentiators(note, insight)
        )[:8]
        payload["human_tone_rules"] = self._dedupe(
            self._string_list(payload.get("human_tone_rules")) + self.HUMAN_TONE_RULES
        )
        payload["paragraph_plan"] = self._string_list(payload.get("paragraph_plan")) or self._paragraph_plan(
            note, insight, narrative_strategy.pattern
        )
        payload["suggested_structure"] = payload["suggested_structure"] or payload["paragraph_plan"]
        payload["title_direction"] = payload["title_direction"] or title_strategy.directions

        return self._parse_editorial_brief(payload)

    def _fallback_strategy(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        angle: Optional[TopicAngle],
    ) -> EditorialBrief:
        values = self._fallback_narrative_values(note)
        narrative_strategy = NarrativeStrategy(
            pattern=values["pattern"],
            rationale=values["rationale"],
            opening_style=values["opening_style"],
            structure_style=values["structure_style"],
            title_style=values["title_style"],
            avoid_patterns=[
                "不要按“项目是什么/核心亮点/适合谁/小结”逐段套模板",
                "不要从 stars 开始写成榜单口吻",
                "不要连续使用“它可以/它支持/它提供”开头",
            ],
            transition_notes=self._transition_notes(values["pattern"]),
        )
        title_strategy = self._fallback_title_strategy(note, insight, angle, narrative_strategy.title_style)
        paragraph_plan = self._paragraph_plan(note, insight, narrative_strategy.pattern)

        return EditorialBrief(
            full_name=note.full_name,
            recommended_angle=angle.selected_angle if angle and angle.selected_angle else insight.core_value,
            narrative_pattern=narrative_strategy.pattern,
            target_reader="、".join(insight.ideal_users[:3]) or "中文技术读者",
            reader_takeaway=f"读者读完后应能判断 {insight.project_name} 是否值得继续调研或试用。",
            title_direction=title_strategy.directions,
            opening_direction=self._opening_direction(note, insight, narrative_strategy),
            must_include=self._must_include(note, insight, facts),
            should_avoid=self._dedupe(self.REQUIRED_AVOID_ITEMS + insight.not_to_overclaim[:4]),
            suggested_structure=paragraph_plan,
            tone="像一个懂技术的人分享项目：先讲场景和判断，再给事实依据，少用宣传腔",
            visual_needs=self.DEFAULT_VISUAL_NEEDS,
            narrative_strategy=narrative_strategy,
            title_strategy=title_strategy,
            article_differentiators=self._fallback_differentiators(note, insight),
            human_tone_rules=self.HUMAN_TONE_RULES,
            paragraph_plan=paragraph_plan,
        )

    def _fallback_narrative_values(self, note: RepoResearchNote) -> dict[str, str]:
        kind = note.project_kind or ""
        if kind in {"cli_tool", "developer_tool", "productivity_tool"}:
            pattern = self._choose(note, ["scene_first", "pain_point_first"])
            opening = self._choose(note, ["concrete_scene", "direct_question"])
            structure = self._choose(note, ["short_blocks", "numbered_notes"])
            title = self._choose(note, ["practical_benefit", "pain_solution"])
            rationale = "工具类项目更适合先进入读者的真实工作流，再解释能力。"
        elif kind == "self_hosted":
            pattern = self._choose(note, ["hands_on", "comparison"])
            opening = "pain_point"
            structure = "soft_sections"
            title = "practical_benefit"
            rationale = "自托管项目需要先讲部署或替代场景，再提醒边界。"
        elif kind == "ai_agent":
            pattern = self._choose(note, ["trend_context", "discovery_note"])
            opening = self._choose(note, ["contrast", "surprising_fact"])
            structure = "soft_sections"
            title = "understated_recommendation"
            rationale = "AI Agent 项目容易写虚，先给趋势位置和事实边界更稳。"
        elif kind == "library_framework":
            pattern = self._choose(note, ["comparison", "trend_context"])
            opening = "contrast"
            structure = self._choose(note, ["qa_style", "soft_sections"])
            title = "comparison"
            rationale = "库和框架要帮助读者放进同类方案里理解。"
        else:
            pattern = self._choose(note, ["discovery_note", "scene_first", "pain_point_first"])
            opening = self._choose(note, ["personal_discovery", "concrete_scene", "direct_question"])
            structure = self._choose(note, ["soft_sections", "short_blocks"])
            title = self._choose(note, ["understated_recommendation", "practical_benefit"])
            rationale = "资料不足时用发现笔记或场景切入，避免过度包装。"
        return {
            "pattern": pattern,
            "opening_style": opening,
            "structure_style": structure,
            "title_style": title,
            "rationale": rationale,
        }

    def _fallback_title_strategy(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        angle: Optional[TopicAngle],
        default_style: str,
    ) -> TitleStrategy:
        project_name = insight.project_name
        topic = self._topic_label(note)
        use_case = self._first_use_case(note, insight)
        star_text = f"{note.stars} stars" if note.stars else "这些 stars"
        candidates = [
            TitleCandidate(
                title=f"把 {use_case} 这件事交给 {project_name}，会顺手多少？",
                style="scene_first",
                reason="场景型标题，先让读者看到具体工作流。",
            ),
            TitleCandidate(
                title=f"{topic} 工具太散？这个项目想把关键步骤收到一起",
                style="pain_solution",
                reason="痛点型标题，适合工具和效率项目。",
            ),
            TitleCandidate(
                title=f"{project_name}：一个可以先收藏、再按场景试用的开源项目",
                style="understated_recommendation",
                reason="克制推荐型标题，不承诺生产可用。",
            ),
            TitleCandidate(
                title=f"和常见 {topic} 方案相比，{project_name} 的切入点在哪里？",
                style="comparison",
                reason="对比型标题，降低单纯吹项目的感觉。",
            ),
            TitleCandidate(
                title=f"少一点手工整理：{project_name} 能给开发流程省下什么",
                style="practical_benefit",
                reason="工具收益型标题，强调实际收益。",
            ),
            TitleCandidate(
                title=f"不只看 {star_text}：{project_name} 真正值得核验的几个点",
                style="curiosity_gap",
                reason="唯一带 star 的标题，把热度转成事实核验。",
                risk="不要把 stars 写成采用理由。",
            ),
            TitleCandidate(
                title=f"我会怎样判断 {project_name} 是否适合放进自己的工具箱",
                style="discovery_note",
                reason="发现笔记型标题，带一点个人判断但不夸张。",
            ),
            TitleCandidate(
                title=f"GitHub 上这个 {topic} 项目，更适合从使用场景读起",
                style="tool_collection",
                reason="保留一个 GitHub 入口标题，但重心放在场景而不是平台感。",
            ),
        ]
        if angle and angle.title_candidates:
            candidates = self._dedupe_title_candidates(list(angle.title_candidates)[:3] + candidates)
        return TitleStrategy(
            directions=[
                "至少准备场景型、痛点型、克制推荐型、对比型和工具收益型标题",
                "标题优先表达使用场景或判断问题，不把 star 数当主卖点",
                "不同候选标题必须对应不同文章角度",
                f"默认标题风格可偏向 {default_style}",
            ],
            banned_templates=self.BANNED_TITLE_TEMPLATES,
            title_candidates=candidates[:8],
            rationale="标题策略的目标是减少“GitHub 爆款项目”套路感，让标题先服务读者问题。",
        )

    def _normalize_narrative_strategy(self, value: Any, note: RepoResearchNote) -> NarrativeStrategy:
        fallback = self._fallback_narrative_values(note)
        data = value if isinstance(value, dict) else {}
        return NarrativeStrategy(
            pattern=self._valid_value(data.get("pattern"), self.NARRATIVE_PATTERNS, fallback["pattern"]),
            rationale=self._clean_text(data.get("rationale") or fallback["rationale"]),
            opening_style=self._valid_value(data.get("opening_style"), self.OPENING_STYLES, fallback["opening_style"]),
            structure_style=self._valid_value(data.get("structure_style"), self.STRUCTURE_STYLES, fallback["structure_style"]),
            title_style=self._valid_value(data.get("title_style"), self.TITLE_STYLES, fallback["title_style"]),
            avoid_patterns=self._dedupe(self._string_list(data.get("avoid_patterns")) + self.REQUIRED_AVOID_ITEMS),
            transition_notes=self._string_list(data.get("transition_notes")) or self._transition_notes(fallback["pattern"]),
        )

    def _normalize_title_strategy(
        self,
        value: Any,
        note: RepoResearchNote,
        insight: ProjectInsight,
        angle: Optional[TopicAngle],
    ) -> TitleStrategy:
        fallback = self._fallback_title_strategy(note, insight, angle, self._fallback_narrative_values(note)["title_style"])
        data = value if isinstance(value, dict) else {}
        candidates = self._parse_title_candidates(data.get("title_candidates"))
        if len(candidates) < 5:
            candidates = self._dedupe_title_candidates(candidates + fallback.title_candidates)
        banned = self._dedupe(self._string_list(data.get("banned_templates")) + self.BANNED_TITLE_TEMPLATES)
        return TitleStrategy(
            directions=self._dedupe(self._string_list(data.get("directions")) + fallback.directions),
            banned_templates=banned,
            title_candidates=candidates[:8],
            rationale=self._clean_text(data.get("rationale") or fallback.rationale),
        )

    def _parse_title_candidates(self, value: Any) -> list[TitleCandidate]:
        if not isinstance(value, list):
            return []
        candidates: list[TitleCandidate] = []
        for item in value:
            if isinstance(item, TitleCandidate):
                candidates.append(item)
            elif isinstance(item, dict):
                title = self._clean_text(item.get("title") or "")
                if not title:
                    continue
                candidates.append(
                    TitleCandidate(
                        title=title,
                        style=self._clean_text(item.get("style") or "candidate"),
                        reason=self._clean_text(item.get("reason") or "提供不同标题角度。"),
                        risk=self._clean_text(item.get("risk")) or None,
                    )
                )
            elif isinstance(item, str) and item.strip():
                candidates.append(
                    TitleCandidate(
                        title=self._clean_text(item),
                        style="candidate",
                        reason="LLM 提供的标题候选。",
                    )
                )
        return self._dedupe_title_candidates(candidates)

    def _paragraph_plan(self, note: RepoResearchNote, insight: ProjectInsight, pattern: str) -> list[str]:
        project_name = insight.project_name
        use_case = self._first_use_case(note, insight)
        base_end = [
            f"用事实卡里的 stars、维护时间、license、release 或 issue 样本交代可信度和采用边界。",
            "收束到适合谁继续试、谁应该先观望，并附上 GitHub 或文档入口。",
        ]
        plans = {
            "scene_first": [
                f"先写一个读者会遇到的具体场景：{use_case}。",
                f"自然引出 {project_name}，用一句话解释它要解决的问题。",
                "挑两三个最有辨识度的能力讲清楚，不按 README 顺序罗列。",
                "插入作者/组织、项目链接或示例资料，让读者知道去哪里核验。",
                *base_end,
            ],
            "pain_point_first": [
                f"先抛出一个实际痛点：{use_case} 为什么麻烦。",
                f"再说明 {project_name} 的切入点，不急着下推荐结论。",
                "用事实卡支撑核心能力，并把未验证部分说清楚。",
                "给出适合试用的场景和不适合直接采用的场景。",
                *base_end,
            ],
            "hands_on": [
                "先从自部署、安装或试用前最容易卡住的问题切入。",
                f"说明 {project_name} 提供了哪些入口、文档或 demo 可以帮助上手。",
                "按实际试用顺序解释核心能力，而不是按功能清单展开。",
                "单独提醒部署成本、license、维护活跃度和 issue 风险。",
                *base_end,
            ],
            "comparison": [
                f"先把 {project_name} 放到常见 {self._topic_label(note)} 方案旁边，说明它不是在解决所有问题。",
                "提出一个对比问题：它的切入点、适用场景或工程形态有什么不同。",
                "用事实卡说明它已有的能力和资料入口。",
                "再讲读者什么时候可以选择它，什么时候该继续看成熟方案。",
                *base_end,
            ],
            "trend_context": [
                f"先用 {self._topic_label(note)} 的近期趋势或常见需求做背景。",
                f"说明 {project_name} 在这个趋势里提供了一个什么样的实现样本。",
                "用事实卡挑选能力、维护、生态链接做解释。",
                "降低抽象感，回到一两个具体使用场景。",
                *base_end,
            ],
            "discovery_note": [
                f"先写成一次技术发现：为什么这个项目会让人停下来多看一眼。",
                f"用白话解释 {project_name} 是什么，以及它最像给谁用。",
                "围绕一两个事实和使用场景展开，而不是给出全功能介绍。",
                "加入个人判断式过渡，但每个判断都回到事实卡。",
                *base_end,
            ],
            "story_first": [
                "先讲一个短小的使用或选型故事，把读者带入问题。",
                f"再揭示故事里出现的工具是 {project_name}。",
                "用事实卡解释它为什么可能有用，并保留试用边界。",
                "把故事落回读者自己的工作流。",
                *base_end,
            ],
            "listicle": [
                f"先说明这篇不是完整评测，而是关于 {project_name} 的几条观察。",
                "每条观察都从一个事实或场景开始，避免空泛评价。",
                "把能力、适用人群、风险分散写进观察里。",
                "最后给出是否继续调研的判断。",
                *base_end,
            ],
        }
        return plans.get(pattern, plans["scene_first"])[:7]

    def _strategy_system_prompt(self) -> str:
        return (
            "你是一位中文技术公众号主编，不是营销号编辑。你要为一篇 GitHub 开源项目分享文章制定写作策略。"
            "目标是让文章像一个懂技术的人在分享项目，而不是 README 搬运或 AI 模板稿。"
            "你必须基于事实卡和项目理解卡，不得编造。请输出严格 JSON。"
        )

    def _strategy_user_prompt(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        angle: Optional[TopicAngle],
    ) -> str:
        payload = {
            "repo_research_note": self._note_payload(note),
            "project_insight": self._model_dump(insight),
            "facts": [self._model_dump(fact) for fact in facts],
            "topic_angle": self._model_dump(angle) if angle is not None else None,
            "project_kind": note.project_kind,
            "author_profile": self._model_dump(note.author_profile) if note.author_profile else None,
            "project_links": self._model_dump(note.project_links) if note.project_links else None,
        }
        return (
            "请输出 JSON，字段必须包含：recommended_angle, narrative_pattern, target_reader, reader_takeaway, "
            "title_direction, opening_direction, must_include, should_avoid, suggested_structure, tone, visual_needs, "
            "narrative_strategy, title_strategy, article_differentiators, human_tone_rules, paragraph_plan。\n"
            "narrative_strategy 字段包含：pattern, rationale, opening_style, structure_style, title_style, "
            "avoid_patterns, transition_notes。pattern 从 scene_first, pain_point_first, discovery_note, comparison, "
            "hands_on, trend_context, story_first, listicle 中选；opening_style 从 concrete_scene, direct_question, "
            "surprising_fact, personal_discovery, pain_point, contrast 中选；structure_style 从 no_headings, "
            "soft_sections, short_blocks, numbered_notes, qa_style 中选；title_style 从 practical_benefit, "
            "curiosity_gap, pain_solution, comparison, understated_recommendation, tool_collection 中选。\n"
            "title_strategy 字段包含：directions, banned_templates, title_candidates, rationale。"
            "title_candidates 每项包含 title, style, reason, risk。标题候选不要都使用“发现一个 X star 项目”、"
            "“GitHub 上这个项目...”、“README 里...”，每个标题必须表达不同角度；最多 1 个标题可以把 star 数作为素材，"
            "但不要把 star 数当主要卖点。\n"
            "不要要求文章固定使用“这个项目是什么/核心亮点/适合谁/小结”等二级标题。"
            "paragraph_plan 只描述自然推进，不是 Markdown 标题。"
            "should_avoid 必须包含“不要频繁写根据 README”。输入资料如下：\n"
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
            "readme_summary": note.readme_summary,
            "readme_key_points": note.readme_key_points,
            "releases": note.releases,
            "open_issues": note.open_issues,
            "source_links": note.source_links,
            "risks": note.risks,
            "tool_use_cases": note.tool_use_cases,
            "project_kind": note.project_kind,
        }

    def _opening_direction(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        strategy: NarrativeStrategy,
    ) -> str:
        if strategy.opening_style == "direct_question":
            return f"用一个具体问题开头：{self._first_use_case(note, insight)} 有没有更省事的做法？"
        if strategy.opening_style == "pain_point":
            return f"先写 {self._first_use_case(note, insight)} 里的麻烦，再引出项目。"
        if strategy.opening_style == "contrast":
            return "先做同类方案或常见做法的对照，再说明这个项目的切入点。"
        if strategy.opening_style == "surprising_fact":
            return "从一个可核验事实或反差观察切入，不要用夸张数字做噱头。"
        if strategy.opening_style == "personal_discovery":
            return "写成一次技术发现笔记：为什么它值得停下来多看一眼。"
        return f"从一个具体使用场景开始：{self._first_use_case(note, insight)}。"

    def _must_include(self, note: RepoResearchNote, insight: ProjectInsight, facts: list[FactCard]) -> list[str]:
        items = [
            insight.plain_summary,
            insight.core_value,
            f"GitHub stars/forks：{note.stars}/{note.forks}",
        ]
        items.extend([fact.claim for fact in facts if fact.publishable][:5])
        return self._dedupe(items)[:10]

    def _fallback_differentiators(self, note: RepoResearchNote, insight: ProjectInsight) -> list[str]:
        return [
            "不是从 README 功能列表开头，而是从读者场景或判断问题开头",
            "标题候选覆盖不同角度，不把 GitHub stars 当主卖点",
            f"围绕 {self._topic_label(note)} 和 {insight.project_name} 的适用边界写，而不是泛泛推荐",
            "把作者/组织、项目链接、license、维护状态等事实融入判断",
        ]

    def _transition_notes(self, pattern: str) -> list[str]:
        notes = {
            "scene_first": ["场景之后再解释项目，不要突然切成说明书", "能力介绍之间用“这对读者意味着什么”过渡"],
            "pain_point_first": ["痛点不要铺太长，第二段就给项目切入点", "风险提示要像选型建议，不像免责声明"],
            "hands_on": ["按试用顺序推进", "每讲一个能力就回到上手成本或边界"],
            "comparison": ["对比要克制，不贬低同类项目", "每个差异点都尽量落到事实卡"],
            "trend_context": ["趋势背景只写一小段", "尽快回到项目本身和可核验资料"],
            "discovery_note": ["允许有个人判断，但不要脱离事实", "用观察串联能力和风险"],
            "story_first": ["故事要短，不能盖过项目信息", "故事之后立刻给事实支撑"],
            "listicle": ["每条观察都要有事实或场景", "列表不是功能清单"],
        }
        return notes.get(pattern, notes["scene_first"])

    def _first_use_case(self, note: RepoResearchNote, insight: ProjectInsight) -> str:
        values = [*note.tool_use_cases, *insight.use_cases, insight.problem_solved]
        for value in values:
            text = self._clean_text(value)
            if text:
                return self._truncate(text, 34)
        return "日常开发或技术选型"

    def _topic_label(self, note: RepoResearchNote) -> str:
        if note.topics:
            return self._clean_text(note.topics[0])
        if note.project_kind:
            return note.project_kind.replace("_", " ")
        return note.language or "开源工具"

    def _choose(self, note: RepoResearchNote, values: list[str]) -> str:
        if not values:
            return ""
        seed = sum(ord(char) for char in note.full_name)
        return values[seed % len(values)]

    def _valid_value(self, value: Any, allowed: set[str], fallback: str) -> str:
        text = str(value or "").strip()
        return text if text in allowed else fallback

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

    def _parse_editorial_brief(self, payload: dict[str, Any]) -> EditorialBrief:
        if hasattr(EditorialBrief, "model_validate"):
            return EditorialBrief.model_validate(payload)
        return EditorialBrief.parse_obj(payload)

    def _model_dump(self, model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [self._clean_text(str(item)) for item in value if self._clean_text(str(item))]
        if isinstance(value, str) and value.strip():
            return [self._clean_text(value)]
        return []

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = self._clean_text(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _dedupe_title_candidates(self, values: list[TitleCandidate]) -> list[TitleCandidate]:
        seen: set[str] = set()
        result: list[TitleCandidate] = []
        for candidate in values:
            title = self._clean_text(candidate.title)
            if not title or title in seen:
                continue
            seen.add(title)
            result.append(candidate)
        return result

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _truncate(self, value: str, limit: int) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."
