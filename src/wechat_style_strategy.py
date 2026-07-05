from __future__ import annotations

import json
import re
from typing import Any

from .llm_service import LLMService
from .models import (
    CustomArticleDirection,
    ProjectAppeal,
    ProjectImpact,
    RepoResearchNote,
    StyleReferenceProfile,
    WechatArticlePattern,
)


class WechatStyleStrategyService:
    """Plan the WeChat project-sharing rhythm without producing an article outline."""

    PATTERN_TYPES = {
        "concept_practice",
        "hot_project",
        "demo_scene",
        "practical_tool",
        "platform_workbench",
    }
    OPENING_STRATEGIES = {
        "trend_hook",
        "pain_hook",
        "concept_hook",
        "author_hook",
        "personal_trial_hook",
    }
    DEFAULT_BANNED_PHRASES = [
        "发现一个 XX star 项目",
        "根据 README",
        "根据README",
        "资料显示",
        "数据可能变化",
        "本文将从以下几个方面",
        "阅读提示",
        "综上",
        "值得关注",
        "具有较高参考价值",
        "建议结合实际情况",
    ]
    DEFAULT_COLLOQUIAL_PHRASES = [
        "这个点挺实用",
        "用过一次就很难回去",
        "单拎出来都值得试试",
        "适合花一个下午玩玩",
        "有点东西",
    ]

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service
        self.last_used_llm = False
        self.warnings: list[str] = []

    def build_pattern(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        impact: ProjectImpact,
        custom_direction: CustomArticleDirection | None = None,
        style_reference_profile: StyleReferenceProfile | None = None,
    ) -> WechatArticlePattern:
        self.last_used_llm = False
        self.warnings = []
        if self.llm_service is not None and self.llm_service.is_available():
            content = self.llm_service.chat(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(note, appeal, impact, custom_direction, style_reference_profile),
                temperature=0.36,
            )
            if content.startswith(LLMService.WARNING_PREFIX):
                self.warnings.append(content)
            else:
                try:
                    payload = self._extract_json_object(content)
                    pattern = self._parse_pattern(self._normalize_payload(payload, note, appeal, impact))
                    self.last_used_llm = True
                    return pattern
                except Exception as exc:
                    self.warnings.append(f"LLM WechatArticlePattern JSON parse failed for {note.full_name}, fallback used: {exc}")
        return self._fallback_pattern(note, appeal, impact, custom_direction, style_reference_profile)

    def _system_prompt(self) -> str:
        return (
            "你是一位中文技术公众号主编，专门把 GitHub 项目规划成“项目种草 + 使用场景 + 具体效果 + 轻口语判断”的文章。"
            "你的任务是输出写作策略，不是文章大纲，不要给固定二级标题。必须基于输入事实，不编造 star 增长、收益率、作者背景或体验。"
            "输出严格 JSON。"
        )

    def _user_prompt(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        impact: ProjectImpact,
        custom_direction: CustomArticleDirection | None,
        style_reference_profile: StyleReferenceProfile | None,
    ) -> str:
        payload = {
            "repo_research_note": self._model_dump(note),
            "project_appeal": self._model_dump(appeal),
            "project_impact": self._model_dump(impact),
            "custom_article_direction": self._model_dump(custom_direction) if custom_direction else None,
            "style_reference_profile": self._model_dump(style_reference_profile) if style_reference_profile else None,
        }
        return (
            "请输出 WechatArticlePattern JSON，字段为：pattern_type, opening_strategy, title_formula, lead_hook, "
            "key_storyline, required_effect_points, required_examples, allowed_colloquial_phrases, banned_phrases, "
            "image_placement_hints, ending_style。\n"
            "pattern_type 只能从 concept_practice, hot_project, demo_scene, practical_tool, platform_workbench 选择。"
            "opening_strategy 只能从 trend_hook, pain_hook, concept_hook, author_hook, personal_trial_hook 选择。\n"
            "要求：\n"
            "- 输出的是公众号项目分享策略，不是固定文章模板，也不是二级标题大纲。\n"
            "- lead_hook 要像自然开头钩子，不能写“发现一个 XX star 项目”。\n"
            "- required_effect_points 至少 2 条，写项目必须展开的作用/效果。\n"
            "- required_examples 至少 2 条，写具体使用例子或场景，不是教程步骤。\n"
            "- 每个重点功能都要能回答：解决什么麻烦，用户看到什么变化。\n"
            "- title_formula 可以参考“这个 GitHub 有意思啊，A + B = C”“N Star，网页/终端/知识库秒变 AI 助手”这类口吻，"
            "但不要复制样本文案，不要没数据硬写增长。\n"
            "- banned_phrases 必须包含：根据 README、资料显示、数据可能变化、本文将从以下几个方面、综上、值得关注。\n"
            "- image_placement_hints 要说明配图跟功能/场景如何匹配。\n"
            "输入资料如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        impact: ProjectImpact,
    ) -> dict[str, Any]:
        fallback = self._fallback_pattern(note, appeal, impact, None, None)
        pattern_type = str(payload.get("pattern_type") or fallback.pattern_type).strip()
        opening_strategy = str(payload.get("opening_strategy") or fallback.opening_strategy).strip()
        payload["pattern_type"] = pattern_type if pattern_type in self.PATTERN_TYPES else fallback.pattern_type
        payload["opening_strategy"] = (
            opening_strategy if opening_strategy in self.OPENING_STRATEGIES else fallback.opening_strategy
        )
        payload["title_formula"] = str(payload.get("title_formula") or fallback.title_formula).strip()
        payload["lead_hook"] = str(payload.get("lead_hook") or fallback.lead_hook).strip()
        payload["key_storyline"] = str(payload.get("key_storyline") or fallback.key_storyline).strip()
        payload["required_effect_points"] = self._limit(
            self._sanitize_investment_items(
                self._string_list(payload.get("required_effect_points")) or fallback.required_effect_points,
                note,
            ),
            6,
            160,
        )
        payload["required_examples"] = self._limit(
            self._sanitize_investment_items(
                self._string_list(payload.get("required_examples")) or fallback.required_examples,
                note,
            ),
            6,
            160,
        )
        payload["allowed_colloquial_phrases"] = self._dedupe(
            self._string_list(payload.get("allowed_colloquial_phrases")) + self.DEFAULT_COLLOQUIAL_PHRASES
        )[:8]
        payload["banned_phrases"] = self._dedupe(
            self._string_list(payload.get("banned_phrases")) + self.DEFAULT_BANNED_PHRASES
        )[:16]
        payload["image_placement_hints"] = self._limit(
            self._sanitize_investment_items(
                self._string_list(payload.get("image_placement_hints")) or fallback.image_placement_hints,
                note,
            ),
            6,
            120,
        )
        payload["ending_style"] = str(payload.get("ending_style") or fallback.ending_style).strip()
        return payload

    def _sanitize_investment_items(self, values: list[str], note: RepoResearchNote) -> list[str]:
        text = " ".join([note.full_name, note.description or "", note.readme_summary, *note.topics]).lower()
        if not any(word in text for word in ["berkshire", "invest", "stock", "投资", "股票", "金融"]):
            return values
        sanitized: list[str] = []
        for value in values:
            item = re.sub(r"(实盘收益|全年收益|收益记录|收益率|\+\s*\d+(?:\.\d+)?\s*%)", "分析材料展示", value)
            item = re.sub(r"(买入|持有|卖出|加仓|减仓)", "人工复核后的判断", item)
            if item.strip():
                sanitized.append(item)
        return sanitized

    def _fallback_pattern(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        impact: ProjectImpact,
        custom_direction: CustomArticleDirection | None,
        style_reference_profile: StyleReferenceProfile | None,
    ) -> WechatArticlePattern:
        text = self._source_text(note, appeal, impact, custom_direction, style_reference_profile)
        pattern_type = self._select_pattern_type(note, text)
        opening_strategy = self._select_opening_strategy(note, text, pattern_type)
        project_name = appeal.project_name or note.full_name.rsplit("/", 1)[-1]
        pain = self._first(
            appeal.reader_interest_points,
            appeal.practical_scenarios,
            note.tool_use_cases,
            [impact.core_effect],
            fallback="把一个真实工作流里的麻烦处理得更顺手",
        )
        lead_hook = self._lead_hook(project_name, pain, pattern_type, opening_strategy)
        title_formula = self._title_formula(note, project_name, pain, pattern_type)
        required_effect_points = self._dedupe(
            impact.concrete_outcomes
            + impact.user_benefits
            + appeal.reader_interest_points
            + [impact.core_effect, impact.effect_summary]
        )[:4]
        required_examples = self._dedupe(
            impact.usage_examples
            + impact.before_after_examples
            + appeal.practical_scenarios
            + note.tool_use_cases
        )[:4]
        if len(required_effect_points) < 2:
            required_effect_points.extend(
                [
                    f"讲清楚 {project_name} 解决的麻烦是什么。",
                    "写出用户使用后能看到的具体变化，而不是只说提升效率。",
                ][: 2 - len(required_effect_points)]
            )
        if len(required_examples) < 2:
            required_examples.extend(
                [
                    "用一个日常工作流例子说明它怎么接入真实场景。",
                    "用一个任务前后变化例子说明省掉了哪些动作。",
                ][: 2 - len(required_examples)]
            )

        return WechatArticlePattern(
            pattern_type=pattern_type,
            opening_strategy=opening_strategy,
            title_formula=title_formula,
            lead_hook=lead_hook,
            key_storyline=self._key_storyline(pattern_type),
            required_effect_points=self._limit(required_effect_points, 6, 160),
            required_examples=self._limit(required_examples, 6, 160),
            allowed_colloquial_phrases=self.DEFAULT_COLLOQUIAL_PHRASES,
            banned_phrases=self.DEFAULT_BANNED_PHRASES,
            image_placement_hints=self._image_hints(note, pattern_type),
            ending_style=self._ending_style(pattern_type),
        )

    def _select_pattern_type(self, note: RepoResearchNote, text: str) -> str:
        lowered = text.lower()
        has_demo = bool(note.readme_images or (note.project_links and (note.project_links.demo or note.project_links.examples)))
        if note.stars >= 10000 or any(word in lowered for word in ["hot", "viral", "trending", "爆火", "狂揽", "增长"]):
            return "hot_project"
        if has_demo or any(word in lowered for word in ["demo", "screenshot", "preview", "示例", "截图", "演示"]):
            return "demo_scene"
        if note.project_kind in {"cli_tool", "developer_tool", "productivity_tool"} or any(word in lowered for word in ["cli", "terminal", "browser extension", "插件", "命令行", "终端", "小工具"]):
            return "practical_tool"
        if note.project_kind in {"self_hosted", "ai_agent"} or any(word in lowered for word in ["workbench", "workspace", "platform", "dashboard", "平台", "工作台", "自托管"]):
            return "platform_workbench"
        if any(word in lowered for word in ["workflow", "obsidian", "knowledge", "agent", "context", "理念", "范式", "工作流", "知识库", "上下文"]):
            return "concept_practice"
        return "practical_tool"

    def _select_opening_strategy(self, note: RepoResearchNote, text: str, pattern_type: str) -> str:
        lowered = text.lower()
        author = note.author_profile
        famous_author = bool(author and (author.type == "Organization" or (author.followers or 0) >= 5000))
        if note.stars >= 10000 or any(word in lowered for word in ["trending", "viral", "增长", "热度"]):
            return "trend_hook"
        if famous_author:
            return "author_hook"
        if pattern_type == "concept_practice" or any(word in lowered for word in ["理念", "工作流", "范式", "context", "knowledge"]):
            return "concept_hook"
        if pattern_type in {"demo_scene", "practical_tool"}:
            return "personal_trial_hook"
        return "pain_hook"

    def _lead_hook(self, project_name: str, pain: str, pattern_type: str, opening_strategy: str) -> str:
        clean_pain = self._trim_sentence(pain)
        if opening_strategy == "trend_hook":
            return f"最近这类项目热度起来，不只是因为名字新，而是它确实踩中了“{clean_pain}”这个需求。"
        if opening_strategy == "concept_hook":
            return f"现在很多 AI 工具不缺能力，缺的是把“{clean_pain}”这件事真正接进工作流。{project_name} 有意思就在这里。"
        if opening_strategy == "author_hook":
            return f"{project_name} 可以先从来头看一眼，但文章重点还是它怎么把“{clean_pain}”做成可用工具。"
        if opening_strategy == "personal_trial_hook":
            return f"这类工具最怕只看功能表，得放到“{clean_pain}”这种场景里才看得出值不值。"
        return f"如果你也遇到过“{clean_pain}”这种麻烦，{project_name} 这类项目就会变得很顺眼。"

    def _title_formula(self, note: RepoResearchNote, project_name: str, pain: str, pattern_type: str) -> str:
        effect = self._short_effect(pain)
        if pattern_type == "hot_project" and note.stars:
            return f"{self._format_stars(note.stars)} Star，这个开源项目有点东西"
        if pattern_type == "platform_workbench":
            return f"这个开源工作台，把{effect}做得很顺手"
        if pattern_type == "demo_scene":
            return f"{project_name} 这个 demo，能看出它解决了什么麻烦"
        if pattern_type == "concept_practice":
            return f"这个 GitHub 有意思啊，{project_name} 把{effect}落到项目里了"
        return f"这个开源项目，把{effect}做得很顺手"

    def _key_storyline(self, pattern_type: str) -> str:
        storylines = {
            "concept_practice": "理念/趋势 -> 项目落地 -> 使用效果 -> 适合谁",
            "hot_project": "热度/来头 -> 项目价值 -> 核心功能效果 -> 作者判断",
            "demo_scene": "痛点 -> 具体 demo -> 功能特性 -> 适合场景",
            "practical_tool": "日常麻烦 -> 工具怎么解决 -> 用起来爽在哪里 -> 项目地址",
            "platform_workbench": "覆盖哪些工作流 -> 核心模块 -> 实际使用收益 -> 注意点",
        }
        return storylines.get(pattern_type, storylines["practical_tool"])

    def _image_hints(self, note: RepoResearchNote, pattern_type: str) -> list[str]:
        hints = ["开头后放项目总览截图"]
        if pattern_type == "demo_scene":
            hints.append("demo 场景讲完后放对应截图")
        if note.readme_images:
            hints.append("功能点后优先放 README 里和该功能匹配的图片")
        else:
            hints.append("README 无图时使用 GitHub README 页面截图")
        if pattern_type == "platform_workbench":
            hints.append("讲核心模块时放能展示工作台/界面的截图")
        return self._dedupe(hints)

    def _ending_style(self, pattern_type: str) -> str:
        if pattern_type == "hot_project":
            return "用一句轻口语判断收束，提醒读者适合点开看看，文末只保留项目地址。"
        if pattern_type == "platform_workbench":
            return "收束到适合哪些工作流先试，不写参考链接堆，文末只保留项目地址。"
        return "自然讲清适合谁试试，不写综上和风险提示小节，文末只保留项目地址。"

    def _source_text(
        self,
        note: RepoResearchNote,
        appeal: ProjectAppeal,
        impact: ProjectImpact,
        custom_direction: CustomArticleDirection | None,
        style_reference_profile: StyleReferenceProfile | None,
    ) -> str:
        parts: list[str] = [
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
            impact.core_effect,
            impact.effect_summary,
            *impact.concrete_outcomes,
            *impact.usage_examples,
        ]
        if custom_direction:
            parts.append(custom_direction.raw_text)
            parts.extend(custom_direction.must_include)
            parts.extend(custom_direction.content_preferences)
        if style_reference_profile and style_reference_profile.raw_count > 0:
            parts.extend(style_reference_profile.title_patterns)
            parts.extend(style_reference_profile.opening_patterns)
            parts.extend(style_reference_profile.structure_tendencies)
        return " ".join(str(part) for part in parts if part)

    def _first(self, *groups: list[str], fallback: str) -> str:
        for group in groups:
            for item in group:
                clean = self._trim_sentence(item)
                if clean:
                    return clean
        return fallback

    def _short_effect(self, value: str) -> str:
        text = re.sub(r"\s+", "", self._trim_sentence(value))
        text = re.sub(r"^(把|让|帮助|可以|能够|用户|开发者)", "", text)
        if not text:
            return "真实工作流"
        return text[:12]

    def _format_stars(self, stars: int) -> str:
        if stars >= 10000:
            value = stars / 10000
            return f"{value:.1f}w".replace(".0w", "w")
        if stars >= 1000:
            value = stars / 1000
            return f"{value:.1f}k".replace(".0k", "k")
        return str(stars)

    def _trim_sentence(self, value: str) -> str:
        return str(value or "").strip().rstrip("。；;，, ")

    def _limit(self, values: list[str], count: int, char_limit: int) -> list[str]:
        return [self._truncate(value, char_limit) for value in self._dedupe(values)[:count]]

    def _truncate(self, value: str, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

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
            clean = " ".join(str(value).split())
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

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

    def _parse_pattern(self, payload: dict[str, Any]) -> WechatArticlePattern:
        if hasattr(WechatArticlePattern, "model_validate"):
            return WechatArticlePattern.model_validate(payload)
        return WechatArticlePattern.parse_obj(payload)

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
