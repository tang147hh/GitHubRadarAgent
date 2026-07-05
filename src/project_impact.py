from __future__ import annotations

import json
import re
from typing import Any

from .llm_service import LLMService
from .models import CustomArticleDirection, EditorialBrief, ProjectAppeal, ProjectImpact, RepoResearchNote


class ProjectImpactService:
    """Extract concrete project effects for article planning and writing."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service
        self.last_used_llm = False
        self.warnings: list[str] = []

    def build_impact(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        brief: EditorialBrief,
        custom_direction: CustomArticleDirection | None = None,
    ) -> ProjectImpact:
        self.last_used_llm = False
        self.warnings = []
        if self.llm_service is not None and self.llm_service.is_available():
            content = self.llm_service.chat(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(note, appeal, brief, custom_direction),
                temperature=0.32,
            )
            if content.startswith(LLMService.WARNING_PREFIX):
                self.warnings.append(content)
            else:
                try:
                    payload = self._extract_json_object(content)
                    impact = self._parse_project_impact(
                        self._normalize_payload(payload, note, appeal, brief, custom_direction)
                    )
                    self.last_used_llm = True
                    return impact
                except Exception as exc:
                    self.warnings.append(f"LLM ProjectImpact JSON parse failed for {note.full_name}, fallback used: {exc}")
        return self._fallback_impact(note, appeal, brief, custom_direction)

    def _system_prompt(self) -> str:
        return (
            "你是一位技术产品分析编辑。你的任务是把 GitHub 项目的特点转成可写进文章的实际作用、效果和具体提升。"
            "不要写文章正文，不要写教程步骤，不要复述 README。必须基于仓库描述、README 摘要、关键点、链接、release、issue、"
            "ProjectAppeal 和 EditorialBrief 推断；不确定的效果放入 weak_or_unknown_effects，不要硬编。输出严格 JSON。"
        )

    def _user_prompt(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        brief: EditorialBrief,
        custom_direction: CustomArticleDirection | None,
    ) -> str:
        payload = {
            "repo_research_note": self._model_dump(note),
            "project_appeal": self._model_dump(appeal),
            "editorial_brief": self._model_dump(brief),
            "custom_article_direction": self._model_dump(custom_direction) if custom_direction else None,
            "project_kind": note.project_kind,
            "project_links": self._model_dump(note.project_links) if note.project_links else None,
            "tool_use_cases": note.tool_use_cases,
        }
        return (
            "请输出 ProjectImpact JSON，字段为：full_name, core_effect, effect_summary, concrete_outcomes, "
            "before_after_examples, usage_examples, user_benefits, measurable_signals, article_expansion_points, "
            "weak_or_unknown_effects。\n"
            "要求：\n"
            "- 不要空泛写“提升效率”“降低成本”“改善体验”，每个效果都尽量落到具体场景或动作。\n"
            "- concrete_outcomes 写用户用了以后能看到的变化；usage_examples 写文章可以自然展开的例子，不是教程步骤。\n"
            "- before_after_examples 只是给 writer 的可选素材，不要求文章必须写成“相比原来”。\n"
            "- measurable_signals 只能放 README、描述、demo、截图、benchmark、示例输出、release 或 issue 中可观察的信号；没有就留空。\n"
            "- weak_or_unknown_effects 写资料不足、不能硬编的效果边界。\n"
            "- 投资/分析类项目重点提炼信息收集、投资逻辑整理、报告生成、辅助判断、降低分析门槛。\n"
            "- 工作流/AI 助手类项目重点给 2-3 个具象例子，例如写代码前整理上下文、多工具间保持任务连续、把临时想法转成可执行计划。\n"
            "- CLI/工具类项目重点写日常爽点和省掉的动作；平台类项目重点写流程产品化、可视化、可复用。\n"
            "- 不要写“根据 README”，不要把文章写成教程步骤。\n"
            "输入资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _fallback_impact(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        brief: EditorialBrief,
        custom_direction: CustomArticleDirection | None,
    ) -> ProjectImpact:
        project_name = appeal.project_name or self._project_name(note)
        source_text = self._source_text(note, appeal, brief, custom_direction)
        category = self._impact_category(note, source_text)
        scenarios = self._dedupe(note.tool_use_cases + appeal.practical_scenarios + appeal.reader_interest_points)[:5]
        selling_points = self._dedupe(appeal.top_selling_points + appeal.recommended_focus)[:4]
        direction_text = self._custom_direction_text(custom_direction)

        if category == "investment_analysis":
            core_effect = "把分散的投资信息、公司材料和分析逻辑整理成更容易复核的判断线索。"
            concrete_outcomes = [
                "把信息收集、观点整理和报告草稿集中到同一条分析链路里，减少手动翻资料后的遗漏。",
                "把投资分析拆成可阅读的逻辑和输出，帮助读者更快看到项目试图给出的判断依据。",
                "让非专业量化背景的用户也能先拿到一份分析框架，再决定是否继续深挖财报、新闻和估值假设。",
            ]
            usage_examples = [
                "研究一家公司前，先让项目汇总公开资料和关键线索，再人工核验重要假设。",
                "比较多个投资标的时，把分析报告作为统一格式的初筛材料，而不是在浏览器标签页里来回翻。",
                "写投资备忘录时，用它整理已有信息、风险点和待确认问题，最后仍由人做判断。",
            ]
            user_benefits = [
                "降低从零开始做投资研究的资料整理门槛。",
                "让投资逻辑更容易被复盘和讨论。",
                "把“我看了很多信息”变成更结构化的分析材料。",
            ]
            article_expansion_points = [
                "重点写它能做出怎样的分析材料，而不是只解释它是什么。",
                "展开信息整理、投资逻辑梳理、报告生成和辅助判断分别解决什么痛点。",
                "提醒不要把工具输出当成收益率承诺或投资结论。",
            ]
        elif category == "workflow_ai_assistant":
            core_effect = "把 AI 辅助从一次性问答推进到更连续的工作流，让上下文、工具和计划更容易接上。"
            concrete_outcomes = [
                "写代码前先把需求、相关文件和限制条件整理清楚，减少一上来就让 AI 猜上下文。",
                "在多个工具或任务之间切换时，保留任务连续性，不必每次重新解释目标和当前状态。",
                "把临时想法收束成可执行计划，让 AI 协作更像推进任务，而不是聊天记录堆叠。",
            ]
            usage_examples = [
                "开始改一个复杂模块前，先让它整理目标、约束和待检查文件，再进入编码。",
                "调试到一半切到别的工具时，保留当前假设、已尝试方案和下一步动作。",
                "会议或走路时冒出的想法，回来后整理成任务清单、上下文和可执行步骤。",
            ]
            user_benefits = [
                "减少重复交代背景的心智负担。",
                "让 AI 工具更贴近程序员真实的任务推进节奏。",
                "把零散灵感和工具调用变成更稳定的工作流。",
            ]
            article_expansion_points = [
                "用程序员视角写具体场景，不只说效率提升。",
                "至少展开两个例子：写代码前整理上下文、多工具间保持任务连续、把想法转成计划。",
                "说明提升发生在任务衔接、上下文保存和计划落地这些环节。",
            ]
        elif category == "cli_tool":
            core_effect = "把日常命令行里的重复动作压缩成更顺手的工具动作。"
            concrete_outcomes = [
                "减少在终端、编辑器和浏览器之间来回切换的次数。",
                "把常见操作做成更短路径，让开发者在当前工作流里完成处理。",
                "让一次性脚本或手动整理变成可以重复使用的命令。",
            ]
            usage_examples = scenarios[:3] or [
                "处理代码或文本时少开一个临时脚本。",
                "排查问题时直接在终端拿到更可读的结果。",
                "把团队常用动作封装成统一命令。",
            ]
            user_benefits = ["少打断开发节奏。", "减少重复敲命令和复制粘贴。", "把小工具自然塞进已有 shell 工作流。"]
            article_expansion_points = ["重点写日常使用时省掉哪些动作。", "用一个具体终端场景解释爽点。"]
        elif category == "platform":
            core_effect = "把复杂流程沉淀成可视化、可复用、可协作的平台能力。"
            concrete_outcomes = [
                "团队可以把分散脚本、模型调用或任务链路整理成更稳定的流程。",
                "复杂任务有了统一入口，更容易交给不同角色复用和维护。",
                "流程变化可以通过配置、可视化或统一抽象沉淀下来，而不是只存在某个人电脑里。",
            ]
            usage_examples = scenarios[:3] or [
                "把内部自动化流程做成可复用入口。",
                "把 AI 应用原型整理成团队能共同评估的流程。",
                "把分散服务、任务和数据处理步骤产品化。",
            ]
            user_benefits = ["降低团队协作中的交接成本。", "让流程更容易复用和迭代。", "把复杂系统暴露成更可管理的界面或抽象。"]
            article_expansion_points = ["重点写流程产品化和复用效果。", "说明团队采用后可视化、维护和交接会发生什么变化。"]
        else:
            core_effect = self._generic_core_effect(project_name, selling_points, scenarios)
            concrete_outcomes = self._generic_outcomes(selling_points, scenarios)
            usage_examples = scenarios[:3] or [
                "把它放进一个真实项目里验证是否贴合现有流程。",
                "用它处理一个当前最重复、最容易出错的小任务。",
                "让团队先围绕一个低风险场景评估维护成本和收益。",
            ]
            user_benefits = self._generic_benefits(note, selling_points)
            article_expansion_points = [
                "不要只解释项目定义，要写它能帮用户少掉哪些麻烦。",
                "从读者最可能遇到的场景切入，展开至少两个具体变化。",
            ]

        if direction_text and any(word in direction_text for word in ["效果", "提升", "举例", "不要只说", "不要一笔带过"]):
            article_expansion_points = self._dedupe(
                ["用户方向要求强化效果和例子，writer 应优先展开 ProjectImpact。"] + article_expansion_points
            )

        measurable_signals = self._measurable_signals(note)
        weak_or_unknown_effects = self._weak_effects(note, category)
        effect_summary = self._effect_summary(project_name, core_effect, concrete_outcomes)
        before_after_examples = self._before_after_examples(category, concrete_outcomes, usage_examples)

        return ProjectImpact(
            full_name=note.full_name,
            core_effect=self._truncate(core_effect, 180),
            effect_summary=self._truncate(effect_summary, 260),
            concrete_outcomes=self._limit(concrete_outcomes, 5, 180),
            before_after_examples=self._limit(before_after_examples, 4, 180),
            usage_examples=self._limit(usage_examples, 5, 180),
            user_benefits=self._limit(user_benefits, 5, 150),
            measurable_signals=self._limit(measurable_signals, 5, 160),
            article_expansion_points=self._limit(article_expansion_points, 6, 180),
            weak_or_unknown_effects=self._limit(weak_or_unknown_effects, 6, 180),
        )

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        brief: EditorialBrief,
        custom_direction: CustomArticleDirection | None,
    ) -> dict[str, Any]:
        payload["full_name"] = note.full_name
        for key in [
            "concrete_outcomes",
            "before_after_examples",
            "usage_examples",
            "user_benefits",
            "measurable_signals",
            "article_expansion_points",
            "weak_or_unknown_effects",
        ]:
            payload[key] = self._sanitize_investment_items(self._string_list(payload.get(key)), note)
        if not payload.get("core_effect") or not payload.get("effect_summary"):
            fallback = self._fallback_impact(note, appeal, brief, custom_direction)
            payload["core_effect"] = payload.get("core_effect") or fallback.core_effect
            payload["effect_summary"] = payload.get("effect_summary") or fallback.effect_summary
            for key in [
                "concrete_outcomes",
                "usage_examples",
                "user_benefits",
                "article_expansion_points",
                "weak_or_unknown_effects",
            ]:
                if not payload.get(key):
                    payload[key] = getattr(fallback, key)
        return payload

    def _sanitize_investment_items(self, values: list[str], note: RepoResearchNote) -> list[str]:
        source = " ".join([note.full_name, note.description or "", note.readme_summary, *note.topics]).lower()
        if not any(word in source for word in ["berkshire", "invest", "stock", "投资", "股票", "金融"]):
            return values
        sanitized: list[str] = []
        for value in values:
            item = re.sub(r"(实盘收益|全年收益|收益记录|收益率|\+\s*\d+(?:\.\d+)?\s*%)", "分析材料展示", value)
            item = re.sub(r"(买入|持有|卖出|加仓|减仓)", "人工复核后的判断", item)
            if item.strip():
                sanitized.append(item)
        return sanitized

    def _impact_category(self, note: RepoResearchNote, source_text: str) -> str:
        text = source_text.lower()
        if any(word in text for word in ["berkshire", "invest", "stock", "portfolio", "财报", "投资", "股票", "估值", "金融", "分析报告"]):
            return "investment_analysis"
        if any(word in text for word in ["superpowers", "agent", "assistant", "workflow", "context", "mcp", "ai coding", "上下文", "工作流", "助手"]):
            return "workflow_ai_assistant"
        if note.project_kind == "cli_tool" or any(word in text for word in ["cli", "terminal", "command line", "命令行", "终端"]):
            return "cli_tool"
        if note.project_kind in {"self_hosted", "ai_agent"} or any(word in text for word in ["platform", "dashboard", "visual", "workflow", "平台", "可视化"]):
            return "platform"
        return "general"

    def _source_text(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        brief: EditorialBrief,
        custom_direction: CustomArticleDirection | None,
    ) -> str:
        parts = [
            note.full_name,
            note.description or "",
            note.readme_summary,
            note.language or "",
            note.project_kind or "",
            *note.topics,
            *note.readme_key_points,
            *note.tool_use_cases,
            appeal.appeal_summary,
            appeal.primary_hook,
            *appeal.top_selling_points,
            *appeal.practical_scenarios,
            brief.recommended_angle,
            brief.reader_takeaway,
            self._custom_direction_text(custom_direction),
        ]
        return " ".join(str(part) for part in parts if part)

    def _measurable_signals(self, note: RepoResearchNote) -> list[str]:
        signals: list[str] = []
        text_items = [note.readme_summary, *note.readme_key_points]
        patterns = [
            r"benchmark[^。；\n]*",
            r"demo[^。；\n]*",
            r"example[^。；\n]*",
            r"screenshot[^。；\n]*",
            r"\d+(?:\.\d+)?\s*(?:%|x|倍|seconds?|ms|tokens?|accuracy|score)[^。；\n]*",
            r"示例[^。；\n]*",
            r"截图[^。；\n]*",
            r"报告[^。；\n]*",
            r"输出[^。；\n]*",
        ]
        for item in text_items:
            for pattern in patterns:
                for match in re.findall(pattern, item or "", flags=re.IGNORECASE):
                    signals.append(self._clean_text(match))
        if note.project_links:
            if note.project_links.demo:
                signals.append("项目资料提供了 demo 链接，可用于观察实际输出。")
            if note.project_links.examples:
                signals.append("项目资料提供了 examples 链接，可用于核验示例效果。")
            if note.project_links.images or note.readme_images:
                signals.append("项目资料包含截图或图片，可用于观察界面/输出形态。")
        return self._dedupe(signals)

    def _weak_effects(self, note: RepoResearchNote, category: str) -> list[str]:
        effects = [
            "没有独立验证的性能、收益、准确率或生产可用性数据时，不要写成确定结论。",
        ]
        if category == "investment_analysis":
            effects.append("不能把项目输出写成投资建议、收益率承诺或确定买卖结论。")
        if not self._measurable_signals(note):
            effects.append("没有明确 benchmark、demo 结果或量化指标时，只写可观察的工作流效果。")
        if not note.license_name:
            effects.append("许可证信息不足时，不要暗示可直接商用。")
        return self._dedupe(effects)

    def _before_after_examples(self, category: str, outcomes: list[str], examples: list[str]) -> list[str]:
        if category == "investment_analysis":
            return [
                "原本要在多处资料里拼分析线索，现在可以先得到一份结构化材料，再人工复核。",
                "原本投资备忘录容易散落在笔记里，现在可以围绕报告输出统一讨论假设和风险。",
            ]
        if category == "workflow_ai_assistant":
            return [
                "原本每次切工具都要重新解释背景，现在可以保留目标、上下文和下一步动作。",
                "原本临时想法停在聊天记录里，现在可以整理成可执行计划。",
            ]
        if outcomes and examples:
            return [f"原本容易卡在“{examples[0]}”，现在更容易看到的变化是：{outcomes[0]}"]
        return []

    def _generic_core_effect(self, project_name: str, selling_points: list[str], scenarios: list[str]) -> str:
        if selling_points and scenarios:
            return f"让用户在{scenarios[0]}时，更容易把“{selling_points[0]}”落到实际流程里。"
        if selling_points:
            return f"把“{selling_points[0]}”做成一个可以实际验证的开源能力。"
        return f"{project_name} 的作用是把一个具体问题变成可试用、可评估的开源方案。"

    def _generic_outcomes(self, selling_points: list[str], scenarios: list[str]) -> list[str]:
        outcomes = []
        for index, point in enumerate(selling_points[:3]):
            scenario = scenarios[index] if index < len(scenarios) else "真实项目评估"
            outcomes.append(f"在{scenario}里，把“{point}”从概念变成可以试验的处理方式。")
        return outcomes or ["让读者能围绕一个具体场景判断项目是否值得继续试用。"]

    def _generic_benefits(self, note: RepoResearchNote, selling_points: list[str]) -> list[str]:
        benefits = ["更快判断项目是否贴合自己的实际场景。"]
        if note.project_kind in {"developer_tool", "cli_tool"}:
            benefits.append("减少日常开发里重复切换和手动整理。")
        if selling_points:
            benefits.append(f"围绕“{selling_points[0]}”形成更清楚的采用理由。")
        return self._dedupe(benefits)

    def _effect_summary(self, project_name: str, core_effect: str, outcomes: list[str]) -> str:
        if outcomes:
            return f"{project_name} 的价值更像是：{core_effect}{outcomes[0]}"
        return f"{project_name} 的价值更像是：{core_effect}"

    def _custom_direction_text(self, custom_direction: CustomArticleDirection | None) -> str:
        if custom_direction is None:
            return ""
        parts = [
            custom_direction.raw_text,
            custom_direction.target_reader or "",
            custom_direction.writing_perspective or "",
            custom_direction.core_angle or "",
            *custom_direction.must_include,
            *custom_direction.content_preferences,
        ]
        return " ".join(part for part in parts if part)

    def _parse_project_impact(self, payload: dict[str, Any]) -> ProjectImpact:
        if hasattr(ProjectImpact, "model_validate"):
            return ProjectImpact.model_validate(payload)
        return ProjectImpact.parse_obj(payload)

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

    def _project_name(self, note: RepoResearchNote) -> str:
        return note.full_name.split("/")[-1] if note.full_name else "这个项目"

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [self._clean_text(str(item)) for item in value if self._clean_text(str(item))]
        return [self._clean_text(str(value))] if self._clean_text(str(value)) else []

    def _limit(self, values: list[str], limit: int, item_limit: int) -> list[str]:
        return [self._truncate(value, item_limit) for value in self._dedupe(values)[:limit]]

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = self._clean_text(value)
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def _clean_text(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" -:：。")

    def _truncate(self, value: str, limit: int) -> str:
        text = self._clean_text(value)
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."
