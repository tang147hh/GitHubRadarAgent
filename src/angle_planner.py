from __future__ import annotations

import json
import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import RepoResearchNote, TitleCandidate, TopicAngle


class AnglePlannerService:
    """Generate WeChat topic angles and title candidates from research notes."""

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.warnings: list[str] = []

    def plan_angles(self, research_notes: list[RepoResearchNote], top: int = 3) -> list[TopicAngle]:
        angles: list[TopicAngle] = []
        for note in research_notes[: max(0, top)]:
            angles.append(self.plan_angle(note))
        return angles

    def plan_angle(self, note: RepoResearchNote) -> TopicAngle:
        if self.llm_service is not None and self.llm_service.is_available():
            llm_angle = self._plan_angle_with_llm(note)
            if llm_angle is not None:
                self.used_llm = True
                return llm_angle

        return self._fallback_angle(note)

    def _plan_angle_with_llm(self, note: RepoResearchNote) -> Optional[TopicAngle]:
        content = self.llm_service.chat(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(note),
            temperature=0.7,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content)
            return None

        try:
            payload = self._extract_json_object(content)
            payload["full_name"] = note.full_name
            payload["html_url"] = note.html_url
            payload["project_name"] = payload.get("project_name") or self._project_name(note)
            payload["source_links"] = self._dedupe(
                [str(link) for link in payload.get("source_links", [])] + note.source_links
            )
            payload["factual_warnings"] = self._dedupe(
                [str(item) for item in payload.get("factual_warnings", [])] + note.risks
            )
            angle = self._parse_topic_angle(payload)
            return self._ensure_minimum_content(angle, note)
        except Exception as exc:
            self.warnings.append(f"LLM JSON parse failed for {note.full_name}, fallback used: {exc}")
            return None

    def _fallback_angle(self, note: RepoResearchNote) -> TopicAngle:
        project_name = self._project_name(note)
        audience_keyword = self._audience_keyword(note)
        one_liner = self._one_liner(note)
        selling_points = self._fallback_selling_points(note)
        titles = self._fallback_titles(note, project_name, audience_keyword)

        return TopicAngle(
            full_name=note.full_name,
            html_url=note.html_url,
            project_name=project_name,
            selected_angle=f"GitHub 上值得关注的 {project_name}：面向 {audience_keyword} 的开源项目",
            one_liner=one_liner,
            target_readers=self._dedupe(
                [
                    "AI 开发者",
                    "Agent 应用开发者",
                    "开源项目关注者",
                    f"{audience_keyword} 技术实践者",
                ]
            )[:5],
            reader_pain_points=self._fallback_pain_points(note),
            selling_points=selling_points,
            title_candidates=titles,
            opening_hook=self._opening_hook(note, project_name, one_liner),
            article_outline=[
                "开头：用项目定位和 GitHub 热度引出为什么值得看",
                "项目是什么：介绍项目目标、核心场景和技术关键词",
                "为什么值得关注：结合 README 摘要、stars、topics 和近期维护信息",
                "核心亮点：拆解 README 关键点中可验证的功能与使用路径",
                "适合谁：对应开发者、团队或开源关注者的具体使用场景",
                "如何开始：引用 README 中的 quick start、安装或文档入口",
                "总结：给出推荐理由，并提醒读者关注事实风险",
            ],
            cover_prompt=(
                "科技感 GitHub 开源项目推荐封面，包含 AI Agent、代码编辑器、"
                "雷达扫描、开源仓库星标元素，中文标题区域清晰，蓝绿橙点缀，高级但不夸张"
            ),
            source_links=note.source_links or [note.html_url],
            factual_warnings=note.risks,
        )

    def _system_prompt(self) -> str:
        return (
            "你是一个技术公众号选题策划专家，擅长把 GitHub 开源项目包装成有传播力但不夸大的"
            "公众号文章选题。你必须严格基于给定资料，不得编造项目能力、用户数据或作者背景。"
            "标题可以有爆款推荐风格，但必须避免“最强”“全网第一”“彻底取代”等绝对化表述。"
            "只输出严格 JSON，不要输出 Markdown、解释或代码块。"
        )

    def _user_prompt(self, note: RepoResearchNote) -> str:
        source_payload = {
            "full_name": note.full_name,
            "html_url": note.html_url,
            "description": note.description,
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
            "source_links": note.source_links,
        }
        return (
            "请基于以下 GitHub 项目调研资料，生成公众号选题角度与标题。"
            "必须输出一个 JSON object，字段为："
            "full_name, html_url, project_name, selected_angle, one_liner, target_readers, "
            "reader_pain_points, selling_points, title_candidates, opening_hook, article_outline, "
            "cover_prompt, source_links, factual_warnings。"
            "title_candidates 必须是 8 个对象，每个对象包含 title, style, reason, risk。"
            "target_readers 3-5 个，reader_pain_points 3-5 个，selling_points 4-6 个，"
            "article_outline 5-7 条。opening_hook 不超过 120 个中文字符。"
            "标题尽量包含项目真实用途或技术关键词，可使用“我发现一个...”“这个开源项目...”"
            "“GitHub 上这个...”等句式，但不得编造。项目资料如下：\n"
            f"{json.dumps(source_payload, ensure_ascii=False, indent=2)}"
        )

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

    def _parse_topic_angle(self, payload: dict[str, Any]) -> TopicAngle:
        if hasattr(TopicAngle, "model_validate"):
            return TopicAngle.model_validate(payload)
        return TopicAngle.parse_obj(payload)

    def _ensure_minimum_content(self, angle: TopicAngle, note: RepoResearchNote) -> TopicAngle:
        fallback = self._fallback_angle(note)
        if len(angle.title_candidates) < 5:
            angle.title_candidates = self._dedupe_titles(angle.title_candidates + fallback.title_candidates)
        if len(angle.title_candidates) > 8:
            angle.title_candidates = angle.title_candidates[:8]
        if not angle.selling_points:
            angle.selling_points = fallback.selling_points
        if not angle.article_outline:
            angle.article_outline = fallback.article_outline
        if not angle.opening_hook:
            angle.opening_hook = fallback.opening_hook
        if not angle.cover_prompt:
            angle.cover_prompt = fallback.cover_prompt
        return angle

    def _fallback_titles(
        self,
        note: RepoResearchNote,
        project_name: str,
        audience_keyword: str,
    ) -> list[TitleCandidate]:
        descriptor = self._short_descriptor(note)
        titles = [
            (
                f"GitHub 上这个 {project_name}，把 {descriptor} 做成了开源项目",
                "发现推荐",
                "用 GitHub 场景和项目真实定位引出关注点",
            ),
            (
                f"我发现一个适合 {audience_keyword} 开发者关注的开源项目：{project_name}",
                "个人发现",
                "面向目标读者，标题克制且不夸大",
            ),
            (
                f"{note.stars} stars 的 {project_name}，README 里最值得看的几个点",
                "数据切入",
                "基于 stars 和 README 关键点制造阅读理由",
            ),
            (
                f"这个开源项目值得收藏：{project_name} 的用途、亮点和风险一次看完",
                "收藏清单",
                "同时呈现亮点和风险，降低标题党风险",
            ),
            (
                f"如果你在看 AI Agent 开源项目，可以顺手研究一下 {project_name}",
                "场景推荐",
                "用读者正在做的技术选择作为入口",
            ),
            (
                f"从 README 看 {project_name}：它解决了什么问题，适合谁用？",
                "拆解分析",
                "强调资料来源，适合做深度拆解",
            ),
        ]
        return [
            TitleCandidate(title=title, style=style, reason=reason, risk=None)
            for title, style, reason in titles
        ]

    def _fallback_selling_points(self, note: RepoResearchNote) -> list[str]:
        points: list[str] = []
        if note.readme_key_points:
            points.extend([self._clean_text(point) for point in note.readme_key_points[:4]])
        if note.stars:
            points.append(f"GitHub stars 约 {note.stars}，具备较高开源关注度")
        if note.topics:
            points.append(f"Topics 覆盖 {', '.join(note.topics[:6])}")
        if note.license_name:
            points.append(f"仓库标注 License: {note.license_name}")
        if note.pushed_at:
            points.append(f"最近 push 时间：{note.pushed_at}")
        return self._dedupe(points)[:6]

    def _fallback_pain_points(self, note: RepoResearchNote) -> list[str]:
        points = [
            "想快速判断一个热门开源项目是否值得投入时间研究",
            "需要从 README 中提炼真实能力，而不是只看 star 数",
            "希望找到可用于 Agent、RAG 或工作流场景的参考项目",
        ]
        if note.releases:
            points.append("想了解项目近期版本变化，但不想逐条翻 release note")
        if note.open_issues:
            points.append("担心 open issues 较多，需要先识别采用风险")
        return points[:5]

    def _opening_hook(self, note: RepoResearchNote, project_name: str, one_liner: str) -> str:
        hook = (
            f"{project_name} 在 GitHub 上已有约 {note.stars} stars。"
            f"从 README 看，它的定位是：{one_liner}"
        )
        return self._truncate(hook, 120)

    def _one_liner(self, note: RepoResearchNote) -> str:
        description = (note.description or "").strip()
        if description:
            return description
        summary = (note.readme_summary or "").strip().split("\n")[0]
        return summary or f"{self._project_name(note)} 是一个 GitHub 开源项目。"

    def _short_descriptor(self, note: RepoResearchNote) -> str:
        text = self._one_liner(note).lower()
        topics = {topic.lower() for topic in note.topics}

        if "agentic workflow" in text or "agentic-workflow" in topics:
            return "Agent 工作流开发"
        if "agent engineering" in text or "agents" in topics:
            return "Agent 工程开发"
        if "harness" in text and "performance" in text:
            return "Agent Harness 性能优化"
        if "rag" in text or "rag" in topics:
            return "RAG 应用开发"
        if "mcp" in text or "mcp" in topics:
            return "MCP 工具集成"
        if "workflow" in text or "workflow" in topics:
            return "工作流自动化"
        if "llm" in text or "llm" in topics:
            return "LLM 应用开发"
        return "AI Agent 相关能力"

    def _audience_keyword(self, note: RepoResearchNote) -> str:
        topic = self._topic_keyword(note)
        if topic:
            topic_map = {
                "agent": "AI Agent",
                "agents": "AI Agent",
                "ai-agents": "AI Agent",
                "agentic-ai": "AI Agent",
                "agentic-workflow": "Agent 工作流",
                "llm": "LLM 应用",
                "rag": "RAG",
                "mcp": "MCP",
                "workflow": "工作流自动化",
            }
            return topic_map.get(topic.lower(), topic)
        return note.language or "AI Agent"

    def _project_name(self, note: RepoResearchNote) -> str:
        return note.full_name.split("/")[-1] if note.full_name else "unknown-project"

    def _topic_keyword(self, note: RepoResearchNote) -> Optional[str]:
        for topic in note.topics:
            if topic.lower() in {
                "agent",
                "agents",
                "ai-agents",
                "agentic-ai",
                "agentic-workflow",
                "llm",
                "rag",
                "mcp",
                "workflow",
            }:
                return topic
        return note.topics[0] if note.topics else None

    def _clean_text(self, value: str) -> str:
        text = value.strip()
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _dedupe_titles(self, titles: list[TitleCandidate]) -> list[TitleCandidate]:
        seen: set[str] = set()
        result: list[TitleCandidate] = []
        for candidate in titles:
            if candidate.title not in seen:
                seen.add(candidate.title)
                result.append(candidate)
        return result

    def _truncate(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit].rstrip()}..."
