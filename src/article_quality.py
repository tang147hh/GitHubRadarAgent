from __future__ import annotations

import re
from typing import Any, Optional

from .llm_service import LLMService
from .models import (
    ArticleQualityIssue,
    ArticleQualityReport,
    FinalArticle,
    ProjectImpact,
    RepoResearchNote,
    WechatArticlePattern,
)


class ArticleQualityEvaluator:
    """Evaluate whether a final article is worth publishing as a WeChat project share."""

    OLD_TITLE_PATTERNS = [
        re.compile(r"发现(了)?一个.*(star|Star|stars|Stars).*项目"),
        re.compile(r"发现(了)?一个.*开源项目"),
        re.compile(r"GitHub\s*上.*(star|Star|stars|Stars)"),
    ]
    WEAK_OPENING_PHRASES = [
        "今天介绍一个项目",
        "今天给大家介绍一个项目",
        "今天给大家推荐一个项目",
        "今天分享一个项目",
        "本文将从以下几个方面",
        "本文将从",
        "随着人工智能的发展",
        "在当今快速发展的",
    ]
    README_TONE_PHRASES = [
        "根据 README",
        "根据README",
        "资料显示",
        "官方文档显示",
        "README 中提到",
        "README 里提到",
        "从 README 可以看到",
        "项目资料显示",
    ]
    AI_REPORT_PHRASES = [
        "值得关注的是",
        "综上",
        "总的来说",
        "总体而言",
        "具有较高参考价值",
        "建议结合实际情况",
        "可以帮助开发者",
        "降低门槛",
        "提升效率",
        "提高效率",
        "赋能",
        "生态",
        "本文将",
        "核心价值在于",
    ]
    TECHNICAL_TERMS = [
        "架构",
        "协议",
        "接口",
        "API",
        "SDK",
        "CLI",
        "Docker",
        "Kubernetes",
        "部署",
        "配置",
        "参数",
        "命令",
        "源码",
        "模块",
        "框架",
        "数据库",
        "向量",
        "推理",
        "微服务",
    ]
    CONCRETE_MARKERS = [
        "比如",
        "例如",
        "举个例子",
        "举例",
        "场景",
        "当你",
        "如果你",
        "假设",
        "拿",
        "日常",
        "团队",
        "个人",
        "本地",
        "代码审查",
        "知识库",
        "客服",
        "命令行",
        "CI",
        "PR",
        "Issue",
    ]
    EFFECT_MARKERS = [
        "效果",
        "结果",
        "带来",
        "省",
        "减少",
        "不用",
        "不必",
        "直接",
        "更快",
        "更稳",
        "收益",
        "好处",
        "从",
        "变成",
        "落地",
        "之后",
    ]
    HOOK_MARKERS = [
        "痛点",
        "麻烦",
        "头疼",
        "有没有",
        "如果",
        "当你",
        "最近",
        "不用",
        "只要",
        "为什么",
        "问题",
        "场景",
    ]
    VALUE_MARKERS = ["可以", "能够", "用来", "让", "把", "解决", "支持", "适合", "帮你", "直接"]
    NATURAL_TONE_MARKERS = ["我", "你", "我们", "说白了", "这个点", "挺", "顺手", "单拎出来", "用过", "适合"]
    LINK_PATTERN = re.compile(r"https?://[^\s)>\]，。；、]+")

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self.llm_service = llm_service
        self.used_llm = False
        self.warnings: list[str] = []

    def evaluate_article(
        self,
        final_article: FinalArticle,
        research_note: Optional[RepoResearchNote] = None,
        content_plan: Optional[dict[str, Any]] = None,
        impact: Optional[ProjectImpact] = None,
        wechat_pattern: Optional[WechatArticlePattern] = None,
    ) -> FinalArticle:
        report = self.build_report(final_article, research_note, content_plan, impact, wechat_pattern)
        return final_article.copy(
            update={
                "article_quality_report": report,
                "quality_score": report.total_score,
                "quality_publish_ready": report.publish_ready,
            }
        )

    def evaluate_articles(
        self,
        final_articles: list[FinalArticle],
        research_notes: list[RepoResearchNote] | None = None,
        content_plans: list[dict[str, Any]] | None = None,
    ) -> list[FinalArticle]:
        notes_by_name = {note.full_name: note for note in (research_notes or [])}
        plans_by_name = {
            str(plan.get("full_name") or ""): plan
            for plan in (content_plans or [])
            if isinstance(plan, dict)
        }
        return [
            self.evaluate_article(
                article,
                research_note=notes_by_name.get(article.full_name),
                content_plan=plans_by_name.get(article.full_name),
            )
            for article in final_articles
        ]

    def build_report(
        self,
        final_article: FinalArticle,
        research_note: Optional[RepoResearchNote] = None,
        content_plan: Optional[dict[str, Any]] = None,
        impact: Optional[ProjectImpact] = None,
        wechat_pattern: Optional[WechatArticlePattern] = None,
    ) -> ArticleQualityReport:
        text = final_article.content_markdown or ""
        body = self._strip_markdown_noise(text)
        title = final_article.title or self._title_from_markdown(text)
        paragraphs = self._paragraphs(body)
        opening = "\n".join(paragraphs[:3])
        content_impact = impact or self._model_from_plan(content_plan, "impact", ProjectImpact)
        content_pattern = wechat_pattern or self._model_from_plan(content_plan, "wechat_pattern", WechatArticlePattern)

        issues: list[ArticleQualityIssue] = []
        title_score = self._score_title(title, research_note, issues)
        opening_score = self._score_opening(opening, issues)
        project_value_score = self._score_project_value(body, final_article, research_note, content_plan, issues)
        concrete_example_score = self._score_concrete_examples(body, content_impact, content_pattern, issues)
        effect_depth_score = self._score_effect_depth(body, content_impact, issues)
        readability_score = self._score_readability(text, paragraphs, issues)
        human_tone_score = self._score_human_tone(body, issues)
        anti_readme_score = self._score_anti_readme(body, issues)
        wechat_style_score = self._score_wechat_style(body, title, final_article, issues)

        scores = {
            "title": title_score,
            "opening": opening_score,
            "project_value": project_value_score,
            "concrete_example": concrete_example_score,
            "effect_depth": effect_depth_score,
            "readability": readability_score,
            "human_tone": human_tone_score,
            "anti_readme": anti_readme_score,
            "wechat_style": wechat_style_score,
        }
        total_score = round(
            title_score * 0.12
            + opening_score * 0.12
            + project_value_score * 0.14
            + concrete_example_score * 0.13
            + effect_depth_score * 0.12
            + readability_score * 0.11
            + human_tone_score * 0.11
            + anti_readme_score * 0.08
            + wechat_style_score * 0.07,
            2,
        )
        issues = self._dedupe_issues(issues)
        publish_ready = total_score >= 80 and not any(issue.severity == "high" for issue in issues)
        strengths = self._strengths(scores)
        recommendations = self._recommendations(issues, scores)
        summary = self._summary(total_score, publish_ready, issues)

        return ArticleQualityReport(
            full_name=final_article.full_name,
            title=title,
            total_score=total_score,
            publish_ready=publish_ready,
            title_score=round(title_score, 2),
            opening_score=round(opening_score, 2),
            project_value_score=round(project_value_score, 2),
            concrete_example_score=round(concrete_example_score, 2),
            effect_depth_score=round(effect_depth_score, 2),
            readability_score=round(readability_score, 2),
            human_tone_score=round(human_tone_score, 2),
            anti_readme_score=round(anti_readme_score, 2),
            wechat_style_score=round(wechat_style_score, 2),
            issues=issues,
            strengths=strengths,
            rewrite_recommendations=recommendations,
            summary=summary,
        )

    def _score_title(
        self,
        title: str,
        note: Optional[RepoResearchNote],
        issues: list[ArticleQualityIssue],
    ) -> float:
        score = 88.0
        if not title.strip():
            return 35.0
        if any(pattern.search(title) for pattern in self.OLD_TITLE_PATTERNS):
            score -= 42
            self._add_issue(
                issues,
                "old_title_template",
                "high",
                "标题仍像“发现一个 XX star 项目”的旧模板，点击欲和差异感都偏弱。",
                "改成项目带来的具体效果、使用场景或好奇心问题。",
                title,
            )
        if "star" in title.lower() and not note:
            score -= 10
        if any(word in title for word in ["让", "把", "不用", "自动", "一键", "解决", "为什么", "怎么"]):
            score += 10
        if len(title) < 10:
            score -= 18
        if len(title) > 38:
            score -= 8
        if any(phrase in title for phrase in ["值得关注", "值得收藏", "推荐一个", "项目分享"]):
            score -= 12
        return self._clamp(score, 0, 100)

    def _score_opening(self, opening: str, issues: list[ArticleQualityIssue]) -> float:
        score = 86.0
        weak_hits = [phrase for phrase in self.WEAK_OPENING_PHRASES if phrase in opening]
        if weak_hits:
            score -= 32
            self._add_issue(
                issues,
                "weak_opening",
                "medium",
                "开头进入方式偏平，像例行介绍项目，缺少痛点、场景或亮点。",
                "前三段直接写一个具体麻烦、热点变化或使用后的明显收益。",
                weak_hits[0],
            )
        if not any(marker in opening for marker in self.HOOK_MARKERS):
            score -= 20
            self._add_issue(
                issues,
                "missing_wechat_hook",
                "medium",
                "前三段没有明显公众号钩子，读者不容易立刻知道为什么要继续看。",
                "补一个“什么情况下会用到它”的真实场景或问题。",
                self._snippet(opening),
            )
        if len(opening) < 80:
            score -= 8
        if any(marker in opening for marker in ["比如", "当你", "如果你", "不用", "只要"]):
            score += 10
        return self._clamp(score, 0, 100)

    def _score_project_value(
        self,
        body: str,
        article: FinalArticle,
        note: Optional[RepoResearchNote],
        content_plan: Optional[dict[str, Any]],
        issues: list[ArticleQualityIssue],
    ) -> float:
        score = 82.0
        value_hits = sum(1 for marker in self.VALUE_MARKERS if marker in body)
        project_name = (article.full_name.split("/")[-1] if article.full_name else "").lower()
        mentions_project = bool(project_name and project_name in body.lower())
        plan_has_value = bool(
            self._object_field(self._object_field(content_plan, "appeal"), "top_selling_points", [])
            or self._object_field(self._object_field(content_plan, "impact"), "core_effect", "")
        )
        if value_hits < 3 and not plan_has_value:
            score -= 28
            self._add_issue(
                issues,
                "shallow_project_effect",
                "high",
                "正文没有把项目能做什么、为什么值得看讲清楚。",
                "补一段“它解决了什么具体问题，以及读者为什么会在意”。",
                self._snippet(body),
            )
        if not mentions_project and not (note and note.description):
            score -= 10
        if any(word in body for word in ["适合", "用来", "解决", "带来"]):
            score += 8
        return self._clamp(score, 0, 100)

    def _score_concrete_examples(
        self,
        body: str,
        impact: Optional[ProjectImpact],
        pattern: Optional[WechatArticlePattern],
        issues: list[ArticleQualityIssue],
    ) -> float:
        marker_count = sum(1 for marker in self.CONCRETE_MARKERS if marker in body)
        plan_examples = 0
        if impact:
            plan_examples += len(impact.usage_examples or []) + len(impact.before_after_examples or [])
        if pattern:
            plan_examples += len(pattern.required_examples or [])
        generic_only = marker_count < 2 and any(term in body for term in ["提升效率", "降低门槛", "改善体验"])
        score = 88.0 + min(8, marker_count * 2)
        if marker_count < 2:
            score -= 34 if plan_examples else 42
            self._add_issue(
                issues,
                "no_concrete_examples",
                "high" if marker_count == 0 else "medium",
                "具体例子不足，文章容易停留在“提升效率、降低门槛”这类抽象判断。",
                "至少补两个使用场景：谁在什么情况下用它，原来怎么做，现在有什么变化。",
                self._snippet(body),
            )
        if generic_only:
            score -= 10
        return self._clamp(score, 0, 100)

    def _score_effect_depth(
        self,
        body: str,
        impact: Optional[ProjectImpact],
        issues: list[ArticleQualityIssue],
    ) -> float:
        marker_count = sum(1 for marker in self.EFFECT_MARKERS if marker in body)
        plan_effects = len(impact.concrete_outcomes or []) + len(impact.article_expansion_points or []) if impact else 0
        score = 82.0 + min(10, marker_count)
        if marker_count < 4 and plan_effects < 2:
            score -= 30
            self._add_issue(
                issues,
                "shallow_project_effect",
                "medium",
                "项目效果展开不足，只说功能或价值，没有讲用了以后会发生什么。",
                "把关键功能翻译成结果：少做哪一步、避免什么麻烦、对个人或团队有什么变化。",
                self._snippet(body),
            )
        return self._clamp(score, 0, 100)

    def _score_readability(
        self,
        raw_markdown: str,
        paragraphs: list[str],
        issues: list[ArticleQualityIssue],
    ) -> float:
        score = 88.0
        long_paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) > 260]
        code_chars = sum(len(match.group(0)) for match in re.finditer(r"```.*?```", raw_markdown, flags=re.S))
        bullet_lines = [line for line in raw_markdown.splitlines() if re.match(r"\s*[-*+]\s+", line)]
        technical_hits = sum(raw_markdown.count(term) for term in self.TECHNICAL_TERMS)
        if long_paragraphs:
            score -= min(22, len(long_paragraphs) * 7)
        if code_chars > max(500, len(raw_markdown) * 0.16):
            score -= 28
            self._add_issue(
                issues,
                "too_much_tutorial",
                "medium",
                "正文代码或教程块占比偏高，公众号项目分享会显得像说明书。",
                "保留最能说明效果的一小段，其余改成场景化描述。",
                self._snippet(raw_markdown),
            )
        if technical_hits > 28:
            score -= 18
            self._add_issue(
                issues,
                "too_hardcore",
                "medium",
                "技术名词密度偏高，非深度教程读者会比较难扫读。",
                "减少配置和实现细节，改成“这个功能解决什么问题”。",
                ", ".join(self.TECHNICAL_TERMS[:6]),
            )
        if len(bullet_lines) > 18:
            score -= 12
        return self._clamp(score, 0, 100)

    def _score_human_tone(self, body: str, issues: list[ArticleQualityIssue]) -> float:
        score = 84.0
        ai_hits = [phrase for phrase in self.AI_REPORT_PHRASES if phrase in body]
        if len(ai_hits) >= 4:
            score -= min(34, len(ai_hits) * 5)
            self._add_issue(
                issues,
                "ai_report_tone",
                "medium",
                "文章有明显 AI 报告腔或泛化套话，缺少使用者自己的判断。",
                "把抽象词换成具体观察，例如“它省掉了哪一步”或“什么时候会踩坑”。",
                "、".join(ai_hits[:6]),
            )
        natural_hits = sum(1 for marker in self.NATURAL_TONE_MARKERS if marker in body)
        if natural_hits >= 3:
            score += 10
        elif natural_hits == 0:
            score -= 10
        return self._clamp(score, 0, 100)

    def _score_anti_readme(self, body: str, issues: list[ArticleQualityIssue]) -> float:
        score = 90.0
        readme_hits = [phrase for phrase in self.README_TONE_PHRASES if phrase in body]
        support_lines = [
            line.strip()
            for line in body.splitlines()
            if line.strip().startswith(("- 支持", "* 支持", "支持"))
        ]
        if readme_hits:
            score -= min(42, len(readme_hits) * 18)
            self._add_issue(
                issues,
                "readme_copy_tone",
                "high" if len(readme_hits) >= 2 else "medium",
                "正文出现 README/资料搬运感表达，会削弱原创分享感。",
                "删除“根据 README/资料显示”，改成自然介绍和使用判断。",
                "、".join(readme_hits[:4]),
            )
        if len(support_lines) >= 5:
            score -= 18
            self._add_issue(
                issues,
                "readme_copy_tone",
                "medium",
                "功能列表堆叠较多，像 README 摘要而不是公众号分享。",
                "把功能列表合并成 2-3 个亮点，每个亮点配一个场景或效果。",
                self._snippet("\n".join(support_lines[:3])),
            )
        return self._clamp(score, 0, 100)

    def _score_wechat_style(
        self,
        body: str,
        title: str,
        article: FinalArticle,
        issues: list[ArticleQualityIssue],
    ) -> float:
        score = 84.0
        has_address = article.html_url in body or "项目地址" in body or "github.com/" in body.lower()
        links = self._links(body)
        if not has_address:
            score -= 28
            self._add_issue(
                issues,
                "missing_project_address",
                "high",
                "正文缺少清晰项目地址，发布时读者无法顺手打开项目。",
                "文末保留一个 GitHub 项目地址即可。",
                None,
            )
        if len(links) > 3:
            score -= 16
            self._add_issue(
                issues,
                "too_many_links",
                "medium",
                "链接过多，会打断公众号阅读节奏，也像资料汇总。",
                "发布稿中通常只保留项目主页，其他链接放进内部备查。",
                "；".join(links[:4]),
            )
        if not any(marker in body[:450] for marker in self.HOOK_MARKERS):
            score -= 12
        if not any(marker in body for marker in ["亮点", "适合", "效果", "场景", "项目地址"]):
            score -= 14
        if any(marker in title for marker in ["让", "把", "不用", "为什么", "怎么"]) and has_address:
            score += 8
        return self._clamp(score, 0, 100)

    def _model_from_plan(self, content_plan: Optional[dict[str, Any]], key: str, model_cls: Any) -> Any:
        raw = self._object_field(content_plan, key)
        if raw is None:
            return None
        if isinstance(raw, model_cls):
            return raw
        if isinstance(raw, dict):
            try:
                if hasattr(model_cls, "model_validate"):
                    return model_cls.model_validate(raw)
                return model_cls.parse_obj(raw)
            except Exception:
                return None
        return None

    def _add_issue(
        self,
        issues: list[ArticleQualityIssue],
        issue_type: str,
        severity: str,
        description: str,
        suggestion: str,
        evidence: Optional[str],
    ) -> None:
        issues.append(
            ArticleQualityIssue(
                issue_type=issue_type,
                severity=severity,
                description=description,
                suggestion=suggestion,
                evidence=self._snippet(evidence or "") if evidence else None,
            )
        )

    def _strengths(self, scores: dict[str, float]) -> list[str]:
        labels = {
            "title": "标题有明确点击点",
            "opening": "开头能较快进入场景",
            "project_value": "项目价值表达清楚",
            "concrete_example": "具体例子相对充分",
            "effect_depth": "项目效果有展开",
            "readability": "段落和技术密度适合公众号阅读",
            "human_tone": "语气接近真实使用者分享",
            "anti_readme": "README 搬运感较低",
            "wechat_style": "结构接近项目分享公众号稿",
        }
        strengths = [label for key, label in labels.items() if scores.get(key, 0) >= 86]
        return strengths[:5] or ["文章基础结构完整，但发布前仍建议按问题列表做一次人工打磨。"]

    def _recommendations(self, issues: list[ArticleQualityIssue], scores: dict[str, float]) -> list[str]:
        recommendations = self._dedupe([issue.suggestion for issue in issues if issue.suggestion])
        if scores.get("concrete_example", 100) < 80:
            recommendations.append("补两个具体例子：个人开发者怎么用、团队协作时怎么用。")
        if scores.get("effect_depth", 100) < 80:
            recommendations.append("每个核心功能后补一句“它带来的结果”，避免只写功能名。")
        if scores.get("human_tone", 100) < 80:
            recommendations.append("删掉报告腔套话，加入一两句自然判断。")
        return self._dedupe(recommendations)[:8]

    def _summary(self, total_score: float, publish_ready: bool, issues: list[ArticleQualityIssue]) -> str:
        high_issues = [issue.issue_type for issue in issues if issue.severity == "high"]
        if publish_ready:
            return f"质量分 {total_score:.1f}，结构和表达已基本达到公众号发布要求。"
        if high_issues:
            return f"质量分 {total_score:.1f}，暂不建议直接发布；优先处理 {', '.join(high_issues[:3])}。"
        return f"质量分 {total_score:.1f}，可以生成但建议轻量修改后再发布。"

    def _strip_markdown_noise(self, text: str) -> str:
        without_code = re.sub(r"```.*?```", " ", text or "", flags=re.S)
        without_images = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", without_code)
        return without_images.strip()

    def _title_from_markdown(self, text: str) -> str:
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return ""

    def _paragraphs(self, text: str) -> list[str]:
        paragraphs: list[str] = []
        for chunk in re.split(r"\n\s*\n", text or ""):
            stripped = re.sub(r"^#+\s*", "", chunk.strip())
            if not stripped or stripped.startswith(("http://", "https://")):
                continue
            if re.fullmatch(r"[-*_]{3,}", stripped):
                continue
            paragraphs.append(stripped)
        return paragraphs

    def _links(self, text: str) -> list[str]:
        links = []
        for link in self.LINK_PATTERN.findall(text or ""):
            cleaned = link.rstrip(".,;，。；")
            if cleaned not in links:
                links.append(cleaned)
        return links

    def _object_field(self, value: Any, field: str, default: Any = None) -> Any:
        if value is None:
            return default
        if isinstance(value, dict):
            return value.get(field, default)
        return getattr(value, field, default)

    def _snippet(self, text: str, limit: int = 90) -> str:
        clean = " ".join((text or "").split())
        if len(clean) <= limit:
            return clean
        return f"{clean[:limit].rstrip()}..."

    def _dedupe_issues(self, issues: list[ArticleQualityIssue]) -> list[ArticleQualityIssue]:
        severity_rank = {"high": 3, "medium": 2, "low": 1}
        by_type: dict[str, ArticleQualityIssue] = {}
        for issue in issues:
            existing = by_type.get(issue.issue_type)
            if existing is None or severity_rank.get(issue.severity, 0) > severity_rank.get(existing.severity, 0):
                by_type[issue.issue_type] = issue
        return list(by_type.values())

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = str(item or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            result.append(clean)
        return result

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
