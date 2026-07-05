from __future__ import annotations

import json
import re
from typing import Any

from .llm_service import LLMService
from .models import EditorialBrief, FactCard, FeatureAdvantage, ProjectAppeal, ProjectInsight, RepoResearchNote


class ProjectAppealService:
    """Extract the project appeal that should drive article recommendation."""

    KIND_DEFAULTS: dict[str, dict[str, list[str] | str]] = {
        "ai_agent": {
            "summary": "把 Agent / LLM 应用开发里的复杂环节收拢到更容易理解和验证的形态。",
            "selling_points": [
                "工作流、RAG、Agent 或模型集成能力更集中",
                "用可视化或统一抽象降低理解和调试成本",
                "更适合从原型走向可落地的工程化验证",
            ],
            "scenarios": ["做知识库问答", "做内部 AI 助手", "做 Agent workflow 原型", "做模型应用调试"],
        },
        "developer_tool": {
            "summary": "解决程序员日常开发里的具体小麻烦，让工具能自然融入已有流程。",
            "selling_points": ["上手负担轻", "解决一个足够具体的开发痛点", "可以融入日常开发流程"],
            "scenarios": ["终端工作流", "代码阅读", "自动化脚本", "多工具协作"],
        },
        "cli_tool": {
            "summary": "解决程序员日常开发里的具体小麻烦，让工具能自然融入已有流程。",
            "selling_points": ["上手负担轻", "解决一个足够具体的开发痛点", "可以融入日常开发流程"],
            "scenarios": ["终端工作流", "代码阅读", "自动化脚本", "多工具协作"],
        },
        "productivity_tool": {
            "summary": "少一点重复操作，把日常信息处理或任务流变得更顺手。",
            "selling_points": ["减少重复操作", "让信息整理更集中", "更适合放进个人效率流程"],
            "scenarios": ["笔记整理", "待办管理", "浏览器工作流", "文档处理", "自动化任务"],
        },
        "self_hosted": {
            "summary": "可自己部署，适合想要更强数据控制和私有化空间的团队。",
            "selling_points": ["可以自部署", "数据和流程更可控", "可作为 SaaS 替代方案继续评估"],
            "scenarios": ["团队内部工具", "私有化部署", "替代 SaaS", "内部自动化平台"],
        },
        "library_framework": {
            "summary": "用统一抽象减少重复封装，方便把能力扩展到更多项目里。",
            "selling_points": ["统一抽象", "方便扩展", "更容易接入相关生态"],
            "scenarios": ["快速搭原型", "减少重复封装", "接入生态", "沉淀团队基础设施"],
        },
    }

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service
        self.last_used_llm = False
        self.warnings: list[str] = []

    def build_appeal(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        brief: EditorialBrief | None = None,
    ) -> ProjectAppeal:
        self.last_used_llm = False
        self.warnings = []
        if self.llm_service is not None and self.llm_service.is_available():
            content = self.llm_service.chat(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(note, insight, facts, brief),
                temperature=0.35,
            )
            if content.startswith(LLMService.WARNING_PREFIX):
                self.warnings.append(content)
            else:
                try:
                    payload = self._extract_json_object(content)
                    appeal = self._parse_project_appeal(self._normalize_payload(payload, note, insight, facts))
                    self.last_used_llm = True
                    return appeal
                except Exception as exc:
                    self.warnings.append(f"LLM ProjectAppeal JSON parse failed for {note.full_name}, fallback used: {exc}")
        return self._fallback_appeal(note, insight, facts, brief)

    def build_many(self, content_plans: list[dict], notes: list[RepoResearchNote]) -> list[ProjectAppeal]:
        notes_by_name = {note.full_name: note for note in notes}
        appeals: list[ProjectAppeal] = []
        for plan in content_plans:
            if not isinstance(plan, dict):
                continue
            note = notes_by_name.get(str(plan.get("full_name") or ""))
            if note is None:
                continue
            facts = [self._parse_fact_card(item) for item in plan.get("facts", []) if isinstance(item, (dict, FactCard))]
            insight_data = plan.get("insight") or {}
            insight = self._parse_project_insight(insight_data)
            brief_data = plan.get("brief")
            brief = self._parse_editorial_brief(brief_data) if brief_data else None
            appeals.append(self.build_appeal(note, insight, facts, brief))
        return appeals

    def _system_prompt(self) -> str:
        return (
            "你是一位中文技术公众号选题编辑，擅长把 GitHub 开源项目提炼成有吸引力的项目推荐。"
            "你的任务不是复述 README，也不是写使用教程，而是判断这个项目最值得被分享的特点和优势。"
            "你必须基于事实卡和项目理解卡，不得编造功能、性能、作者背景或用户数据。输出严格 JSON。"
        )

    def _user_prompt(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        brief: EditorialBrief | None,
    ) -> str:
        payload = {
            "repo_research_note": self._model_dump(note),
            "fact_cards": [self._model_dump(fact) for fact in facts],
            "project_insight": self._model_dump(insight),
            "editorial_brief": self._model_dump(brief) if brief else None,
            "project_kind": note.project_kind,
            "project_links": self._model_dump(note.project_links) if note.project_links else None,
            "tool_use_cases": note.tool_use_cases,
        }
        return (
            "请输出 ProjectAppeal JSON，字段为：full_name, project_name, appeal_summary, primary_hook, "
            "feature_advantages, top_selling_points, reader_interest_points, practical_scenarios, "
            "differentiation_points, avoid_overemphasis, recommended_focus, confidence。\n"
            "feature_advantages 每项包含 feature, advantage, reader_interest, evidence, emphasis。"
            "关键要求：top_selling_points 只选 2-3 个，不要贪多；feature_advantages 要把功能转成读者能感知的优势；"
            "practical_scenarios 是场景，不是教程步骤；reader_interest_points 要说明读者为什么会想点开项目；"
            "不要写“原来 vs 现在”的结构；不要写“根据 README”；不要把 stars/forks 当作核心卖点；"
            "如果资料不足，confidence=low，并在 avoid_overemphasis 中说明。输入资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _fallback_appeal(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
        brief: EditorialBrief | None,
    ) -> ProjectAppeal:
        project_name = insight.project_name or self._project_name(note)
        kind = note.project_kind or "unknown"
        defaults = self.KIND_DEFAULTS.get(kind, {})
        summary_tail = str(defaults.get("summary") or insight.core_value or insight.problem_solved or "把一个具体开源实现放进可评估的项目清单里。")
        appeal_summary = f"{project_name} 最吸引人的地方，是它{self._lower_first(summary_tail)}"

        feature_advantages = self._feature_advantages(note, insight, facts)
        fact_based_points = [
            item.advantage for item in feature_advantages if item.emphasis in {"high", "medium"} and item.advantage
        ]
        insight_points = self._dedupe(insight.standout_points + insight.use_cases)
        default_points = [str(item) for item in defaults.get("selling_points", [])] if defaults else []
        top_selling_points = self._dedupe(fact_based_points + insight_points + default_points)[:3]
        if not top_selling_points:
            top_selling_points = self._dedupe([insight.core_value, insight.problem_solved])[:2]

        practical_scenarios = self._dedupe(
            note.tool_use_cases
            + insight.use_cases
            + ([str(item) for item in defaults.get("scenarios", [])] if defaults else [])
        )[:5]
        reader_interest_points = self._reader_interest_points(project_name, top_selling_points, practical_scenarios, kind)
        differentiation_points = self._differentiation_points(note, insight, facts)
        avoid_overemphasis = self._dedupe(
            insight.not_to_overclaim
            + (brief.should_avoid if brief else [])
            + [
                "不要把 stars/forks 写成核心卖点。",
                "不要写成安装教程或功能清单。",
                "不要使用“原来 vs 现在”的对比结构。",
            ]
        )[:8]
        recommended_focus = self._dedupe(top_selling_points + reader_interest_points[:2])[:5]
        confidence = "low" if len(feature_advantages) < 2 or not top_selling_points else "medium"
        if confidence == "low":
            avoid_overemphasis = self._dedupe(
                avoid_overemphasis + ["资料不足时，不要硬写差异化、性能表现或生产可用性。"]
            )

        return ProjectAppeal(
            full_name=note.full_name,
            project_name=project_name,
            appeal_summary=self._truncate(appeal_summary, 180),
            primary_hook=self._primary_hook(project_name, top_selling_points, practical_scenarios, appeal_summary),
            feature_advantages=feature_advantages[:6],
            top_selling_points=top_selling_points[:3],
            reader_interest_points=reader_interest_points[:5],
            practical_scenarios=practical_scenarios[:5],
            differentiation_points=differentiation_points[:4],
            avoid_overemphasis=avoid_overemphasis[:8],
            recommended_focus=recommended_focus[:5],
            confidence=confidence,
        )

    def _feature_advantages(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
    ) -> list[FeatureAdvantage]:
        candidates = [
            fact for fact in facts
            if fact.publishable and fact.category in {"capability", "use_case", "ecosystem", "project_link"}
        ]
        if not candidates and insight.standout_points:
            candidates = [
                FactCard(
                    full_name=note.full_name,
                    claim=point,
                    category="capability",
                    source=note.html_url,
                    source_type="derived",
                    confidence="medium",
                    publishable=True,
                )
                for point in insight.standout_points[:4]
            ]

        result: list[FeatureAdvantage] = []
        for fact in candidates:
            claim = self._clean_text(fact.claim)
            if not claim or self._looks_like_metric_claim(claim):
                continue
            feature = self._feature_label(claim, note)
            advantage = self._advantage_text(feature, claim, note.project_kind)
            result.append(
                FeatureAdvantage(
                    feature=feature,
                    advantage=advantage,
                    reader_interest=self._reader_interest_text(feature, note.project_kind),
                    evidence=self._truncate(claim, 160),
                    emphasis="high" if fact.category in {"capability", "use_case"} else "medium",
                )
            )
        return self._dedupe_feature_advantages(result)

    def _feature_label(self, claim: str, note: RepoResearchNote) -> str:
        text = re.sub(r"^可观察的使用场景[:：]\s*", "", claim).strip("。")
        text = re.sub(r"^项目资料显示，它提供了与\s*", "", text).strip("。")
        if len(text) <= 28:
            return text
        keywords = self._keywords_from_text(text, note)
        if keywords:
            return " / ".join(keywords[:3])
        return self._truncate(text, 28)

    def _advantage_text(self, feature: str, claim: str, project_kind: str | None) -> str:
        kind = project_kind or ""
        if kind == "ai_agent":
            return f"{feature} 的价值在于把 LLM 应用里的分散环节收拢，方便读者更快判断能否落地。"
        if kind in {"developer_tool", "cli_tool"}:
            return f"{feature} 的价值在于贴近日常开发动作，不需要为了一个小问题切换太多工具。"
        if kind == "productivity_tool":
            return f"{feature} 的价值在于减少重复整理和切换，让个人工作流更顺。"
        if kind == "self_hosted":
            return f"{feature} 的价值在于给团队更多自部署和数据控制空间。"
        if kind == "library_framework":
            return f"{feature} 的价值在于把重复封装沉淀成统一抽象，后续扩展更轻。"
        return f"{feature} 的价值在于把一个具体能力变成读者可以继续验证的开源选择。"

    def _reader_interest_text(self, feature: str, project_kind: str | None) -> str:
        if project_kind == "ai_agent":
            return "做 Agent 或 LLM 应用时，读者通常关心这类能力能否减少原型到落地的摩擦。"
        if project_kind in {"developer_tool", "cli_tool"}:
            return "如果它能少打断一次开发流程，就有继续点开项目看看的理由。"
        if project_kind == "self_hosted":
            return "对需要私有化和可控部署的读者来说，这类特性天然更值得评估。"
        return f"读者会想知道 {feature} 是否能解决自己手头的具体问题。"

    def _reader_interest_points(
        self,
        project_name: str,
        selling_points: list[str],
        scenarios: list[str],
        project_kind: str,
    ) -> list[str]:
        points = []
        if selling_points:
            points.append(f"它不是泛泛介绍功能，而是有清晰的推荐抓手：{selling_points[0]}")
        if len(selling_points) > 1:
            points.append(f"最值得点进去看的，是它如何把 {selling_points[1]} 做成可观察的项目能力。")
        if scenarios:
            points.append(f"如果你正在处理{scenarios[0]}这类场景，{project_name} 值得进入候选清单。")
        if project_kind:
            points.append(f"它适合从 {project_kind.replace('_', ' ')} 的真实需求出发，而不是只看热度。")
        return self._dedupe(points)

    def _differentiation_points(
        self,
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
    ) -> list[str]:
        source_text = " ".join(
            [note.description or "", note.readme_summary, *note.topics, *insight.standout_points]
            + [fact.claim for fact in facts if fact.publishable]
        ).lower()
        points: list[str] = []
        if any(word in source_text for word in ["visual", "可视化", "dashboard", "ui"]):
            points.append("相比只提供接口或脚本的项目，它更容易用可视化方式理解和调试。")
        if any(word in source_text for word in ["workflow", "工作流", "pipeline"]):
            points.append("它的重点不只是单点功能，而是把任务组织成可复用的工作流。")
        if any(word in source_text for word in ["self-host", "self hosted", "自部署", "本地部署"]):
            points.append("它可以围绕自部署或本地控制展开，而不只是依赖外部 SaaS。")
        if any(word in source_text for word in ["plugin", "extension", "插件", "扩展"]):
            points.append("扩展性可以成为文章里的一个差异化观察点。")
        return self._dedupe(points)

    def _primary_hook(
        self,
        project_name: str,
        top_selling_points: list[str],
        scenarios: list[str],
        appeal_summary: str,
    ) -> str:
        if scenarios and top_selling_points:
            return f"如果你最近正好在做{scenarios[0]}，{project_name} 最值得先看的不是热度，而是：{top_selling_points[0]}"
        if top_selling_points:
            return f"{project_name} 值得点进去看的地方，是它把“{top_selling_points[0]}”做成了一个可验证的开源项目。"
        return appeal_summary

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        note: RepoResearchNote,
        insight: ProjectInsight,
        facts: list[FactCard],
    ) -> dict[str, Any]:
        payload["full_name"] = note.full_name
        payload["project_name"] = self._clean_text(payload.get("project_name") or insight.project_name or self._project_name(note))
        for key in [
            "top_selling_points",
            "reader_interest_points",
            "practical_scenarios",
            "differentiation_points",
            "avoid_overemphasis",
            "recommended_focus",
        ]:
            payload[key] = self._string_list(payload.get(key))
        feature_advantages = []
        for item in payload.get("feature_advantages") or []:
            if isinstance(item, dict):
                item["emphasis"] = self._valid_emphasis(item.get("emphasis"))
                feature_advantages.append(item)
        payload["feature_advantages"] = feature_advantages
        payload["top_selling_points"] = payload["top_selling_points"][:3]
        payload["confidence"] = self._valid_confidence(payload.get("confidence"))
        if not payload.get("appeal_summary"):
            payload["appeal_summary"] = self._fallback_appeal(note, insight, facts, None).appeal_summary
        if not payload.get("primary_hook"):
            payload["primary_hook"] = payload["appeal_summary"]
        return payload

    def _parse_project_appeal(self, payload: dict[str, Any]) -> ProjectAppeal:
        if hasattr(ProjectAppeal, "model_validate"):
            return ProjectAppeal.model_validate(payload)
        return ProjectAppeal.parse_obj(payload)

    def _parse_fact_card(self, payload: dict | FactCard) -> FactCard:
        if isinstance(payload, FactCard):
            return payload
        if hasattr(FactCard, "model_validate"):
            return FactCard.model_validate(payload)
        return FactCard.parse_obj(payload)

    def _parse_project_insight(self, payload: dict | ProjectInsight) -> ProjectInsight:
        if isinstance(payload, ProjectInsight):
            return payload
        if hasattr(ProjectInsight, "model_validate"):
            return ProjectInsight.model_validate(payload)
        return ProjectInsight.parse_obj(payload)

    def _parse_editorial_brief(self, payload: dict | EditorialBrief) -> EditorialBrief:
        if isinstance(payload, EditorialBrief):
            return payload
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

    def _valid_emphasis(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"high", "medium", "low"} else "medium"

    def _valid_confidence(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"high", "medium", "low"} else "medium"

    def _keywords_from_text(self, text: str, note: RepoResearchNote) -> list[str]:
        lowered = text.lower()
        mapping = [
            ("agent", "Agent"),
            ("rag", "RAG"),
            ("workflow", "工作流"),
            ("automation", "自动化"),
            ("llm", "LLM"),
            ("mcp", "MCP"),
            ("cli", "CLI"),
            ("api", "API"),
            ("plugin", "插件"),
            ("dashboard", "Dashboard"),
            ("visual", "可视化"),
            ("self-host", "自部署"),
        ]
        hits = [label for keyword, label in mapping if keyword in lowered]
        hits.extend(topic for topic in note.topics[:3] if topic and topic.lower() in lowered)
        return self._dedupe(hits)

    def _looks_like_metric_claim(self, text: str) -> bool:
        lowered = text.lower()
        return "stars" in lowered or "forks" in lowered or "star" in lowered

    def _lower_first(self, text: str) -> str:
        clean = self._clean_text(text).lstrip("，。,. ")
        if not clean:
            return "有清晰的项目特点。"
        return clean if clean.startswith(("能", "可", "把", "用", "少", "解决", "提供")) else clean

    def _clean_text(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"^\s*[-*#+>\d.)]+\s*", "", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("根据 README", "").replace("README 中提到", "")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._clean_text(item) for item in value if self._clean_text(item)]
        if isinstance(value, str) and value.strip():
            return [self._clean_text(value)]
        return []

    def _dedupe_feature_advantages(self, values: list[FeatureAdvantage]) -> list[FeatureAdvantage]:
        seen: set[str] = set()
        result: list[FeatureAdvantage] = []
        for value in values:
            key = value.feature
            if key and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = self._clean_text(value)
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _truncate(self, value: str, limit: int) -> str:
        text = self._clean_text(value)
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _project_name(self, note: RepoResearchNote) -> str:
        return note.full_name.split("/")[-1] if note.full_name else "unknown-project"

    def _model_dump(self, model: Any) -> dict[str, Any]:
        if model is None:
            return {}
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        if hasattr(model, "dict"):
            return model.dict()
        return model if isinstance(model, dict) else {}
