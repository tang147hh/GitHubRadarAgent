from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.interaction_metrics import interaction_metric_hits, unsupported_community_claim_hits
from src.models import (
    NewsArticle,
    NewsArticlePlan,
    NewsArticleQualityIssue,
    NewsArticleQualityReport,
    NewsDetailResult,
    NewsSelectionContext,
)
from src.news_article_writer import NewsArticleWriterService


LINK_PATTERN = re.compile(r"https?://[^\s)>\]，。；、]+")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_class: Any, payload: Any) -> Any:
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(payload)
    return model_class.parse_obj(payload)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _clean_evidence(value: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip(" ，。；,.") + "..."


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


class NewsArticleQualityEvaluator:
    """Deterministic quality review for one AI news WeChat article."""

    CLICKBAIT_PHRASES = ["震惊", "炸裂", "全网", "封神", "彻底颠覆", "必看", "刚刚", "重磅"]
    AI_REPORT_PHRASES = [
        "本文将",
        "以下是",
        "从以下几个方面",
        "综上",
        "总的来说",
        "总体而言",
        "根据新闻",
        "资料显示",
        "具有重要意义",
        "具有较高参考价值",
        "值得注意的是",
        "可以看出",
        "赋能",
        "生态",
        "降本增效",
    ]
    MECHANICAL_TRANSITIONS = ["首先", "其次", "最后"]
    REPORT_STYLE_COLON_TITLES = [
        "对开发者来说",
        "为什么重要",
        "发生了什么",
        "我的判断",
        "继续关注",
        "行业影响",
        "读者收获",
    ]
    WEAK_OPENING_PHRASES = ["本文将", "随着人工智能的发展", "在当今快速发展的", "根据新闻", "今天我们来看"]
    INSIGHT_MARKERS = ["为什么", "意味着", "影响", "值得关注", "观察", "风险", "开发者", "读者", "我的判断", "下一步", "继续关注"]
    TAKEAWAY_MARKERS = ["我的判断", "读者", "开发者", "可以关注", "下一步", "继续关注", "意味着", "如果你"]
    OFFICIAL_FACT_WORDS = ["官方", "宣布", "证实", "确认", "证明", "表明", "结论是", "已经说明"]

    def __init__(self, workspace_dir: Path | None = None, output_dir: Path | None = None) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir
        self.writer = NewsArticleWriterService(workspace_dir=self.workspace_dir, output_dir=self.output_dir)

    def load_latest_article(self) -> NewsArticle:
        return self.writer.load_latest_article()

    def load_article(self, article_id: str) -> NewsArticle:
        return self.writer.load_article(article_id)

    def load_latest_plan(self) -> NewsArticlePlan:
        return self.writer.load_latest_plan()

    def load_latest_selection(self) -> NewsSelectionContext:
        return self.writer.load_latest_selection()

    def load_context_for_article(
        self,
        article: NewsArticle,
    ) -> tuple[NewsArticlePlan, NewsSelectionContext, list[NewsDetailResult]]:
        plan = self.writer.load_plan(article.plan_id) if article.plan_id else self.writer.load_latest_plan()
        selection = self.writer.load_selection(article.selection_id) if article.selection_id else self.writer.load_latest_selection()
        details = self.writer.load_details_for_selection(selection)
        return plan, selection, details

    def evaluate_latest(self, threshold: float = 80.0) -> NewsArticleQualityReport:
        article = self.load_latest_article()
        plan, selection, details = self.load_context_for_article(article)
        return self.evaluate(article, plan, selection, details, threshold=threshold)

    def evaluate(
        self,
        article: NewsArticle,
        plan: NewsArticlePlan,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult],
        threshold: float = 80.0,
    ) -> NewsArticleQualityReport:
        issues: list[NewsArticleQualityIssue] = []
        markdown = article.content_markdown or ""
        body = self._strip_markdown_noise(markdown)
        paragraphs = self._paragraphs(body)

        title_score = self._score_title(article, plan, issues)
        opening_score = self._score_opening(paragraphs, issues)
        factual_integrity_score = self._score_factual_integrity(article, plan, selection, details, body, issues)
        source_link_score = self._score_source_links(article, plan, details, markdown, issues)
        insight_score = self._score_insight(body, issues)
        readability_score = self._score_readability(markdown, paragraphs, issues)
        originality_score = self._score_originality(markdown, details, issues)
        human_tone_score = self._score_human_tone(body, issues)
        structure_naturalness_score = self._score_structure_naturalness(markdown, body, issues)
        self._check_reader_takeaway(body, issues)
        self._check_link_context(markdown, issues)
        self._check_interaction_metrics(markdown, issues)
        self._check_unsupported_community_claims(markdown, details, issues)

        total_score = round(
            title_score * 0.09
            + opening_score * 0.11
            + factual_integrity_score * 0.18
            + source_link_score * 0.13
            + insight_score * 0.13
            + readability_score * 0.09
            + originality_score * 0.11
            + human_tone_score * 0.08
            + structure_naturalness_score * 0.08,
            2,
        )
        issues = self._dedupe_issues(issues)
        publish_ready = total_score >= float(threshold or 80) and not any(issue.severity == "high" for issue in issues)
        scores = {
            "title": title_score,
            "opening": opening_score,
            "factual_integrity": factual_integrity_score,
            "source_link": source_link_score,
            "insight": insight_score,
            "readability": readability_score,
            "originality": originality_score,
            "human_tone": human_tone_score,
            "structure_naturalness": structure_naturalness_score,
        }

        return NewsArticleQualityReport(
            article_id=article.article_id,
            title=article.title or self._title_from_markdown(markdown),
            total_score=total_score,
            publish_ready=publish_ready,
            title_score=round(title_score, 2),
            opening_score=round(opening_score, 2),
            factual_integrity_score=round(factual_integrity_score, 2),
            source_link_score=round(source_link_score, 2),
            insight_score=round(insight_score, 2),
            readability_score=round(readability_score, 2),
            originality_score=round(originality_score, 2),
            human_tone_score=round(human_tone_score, 2),
            structure_naturalness_score=round(structure_naturalness_score, 2),
            issues=issues,
            strengths=self._strengths(scores),
            rewrite_recommendations=self._recommendations(issues, scores),
            summary=self._summary(total_score, publish_ready, issues),
        )

    def save_report(self, article: NewsArticle, report: NewsArticleQualityReport) -> None:
        generated_date = self._article_date(article)
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_article_dir = self.output_dir / generated_date / "news_articles"
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_article_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(report), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_article_review_latest.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_article_review_latest.json").write_text(payload, encoding="utf-8")
        (output_article_dir / f"{article.article_id}_quality_report.md").write_text(
            self.render_report_markdown(article, report),
            encoding="utf-8",
        )

    def render_report_markdown(self, article: NewsArticle, report: NewsArticleQualityReport) -> str:
        lines = [
            f"# 新闻文章质量评估：{report.title or article.title or article.article_id}",
            "",
            f"- Article ID: {report.article_id or article.article_id or '-'}",
            f"- 总分：{report.total_score:.1f}",
            f"- 可发布：{'是' if report.publish_ready else '否'}",
            "",
            "## 分项得分",
            "",
            f"- 标题：{report.title_score:.1f}",
            f"- 开头：{report.opening_score:.1f}",
            f"- 事实完整性：{report.factual_integrity_score:.1f}",
            f"- 原文链接：{report.source_link_score:.1f}",
            f"- 解读深度：{report.insight_score:.1f}",
            f"- 阅读体验：{report.readability_score:.1f}",
            f"- 原创表达：{report.originality_score:.1f}",
            f"- 人味表达：{report.human_tone_score:.1f}",
            f"- 结构自然度：{report.structure_naturalness_score:.1f}",
            "",
            "## 主要问题",
            "",
        ]
        if report.issues:
            for issue in report.issues:
                lines.extend([f"- [{issue.severity}] {issue.issue_type}：{issue.description}", f"  建议：{issue.suggestion}"])
                if issue.evidence:
                    lines.append(f"  证据：{issue.evidence}")
        else:
            lines.append("- 未发现阻塞发布的问题。")
        lines.extend(["", "## 修改建议", ""])
        lines.extend(f"- {item}" for item in (report.rewrite_recommendations or ["发布前人工通读一次事实边界和来源链接。"]))
        lines.extend(["", "## 优点", ""])
        lines.extend(f"- {item}" for item in (report.strengths or ["保留了基本文章结构。"]))
        lines.extend(["", "## 结论", "", report.summary, ""])
        return "\n".join(lines)

    def _score_title(self, article: NewsArticle, plan: NewsArticlePlan, issues: list[NewsArticleQualityIssue]) -> float:
        title = (article.title or self._title_from_markdown(article.content_markdown) or "").strip()
        if not title:
            return 35
        score = 88
        if len(title) < 10:
            score -= 12
        if len(title) > 34:
            score -= 10
        clickbait_hits = [phrase for phrase in self.CLICKBAIT_PHRASES if phrase in title]
        if clickbait_hits or title.count("！") + title.count("!") >= 2:
            score -= 30
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="title_too_clickbait",
                    severity="medium",
                    description="标题有明显标题党或过度情绪化风险。",
                    suggestion="保留新闻价值点，但去掉夸张词和多余感叹号。",
                    evidence=_clean_evidence(title),
                )
            )
        if plan.recommended_title and title == plan.recommended_title:
            score += 6
        return _clamp(score)

    def _score_opening(self, paragraphs: list[str], issues: list[NewsArticleQualityIssue]) -> float:
        opening = paragraphs[0] if paragraphs else ""
        score = 88
        if len(opening) < 45:
            score -= 25
        if any(phrase in opening for phrase in self.WEAK_OPENING_PHRASES):
            score -= 25
        if not any(marker in opening for marker in ["值得", "因为", "变化", "问题", "影响", "意味着"]):
            score -= 12
        if score < 72:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="weak_opening",
                    severity="low",
                    description="开头没有快速说明这条新闻的价值，或表达偏模板化。",
                    suggestion="开头先说这条新闻为什么值得看，再补背景。",
                    evidence=_clean_evidence(opening),
                )
            )
        return _clamp(score)

    def _score_factual_integrity(
        self,
        article: NewsArticle,
        plan: NewsArticlePlan,
        selection: NewsSelectionContext,
        details: list[NewsDetailResult],
        body: str,
        issues: list[NewsArticleQualityIssue],
    ) -> float:
        score = 92
        source_text = self._source_corpus(plan, details)
        article_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b|[一二三四五六七八九十百千万亿]+(?:个|款|项|家|倍|%|％)", body))
        source_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b|[一二三四五六七八九十百千万亿]+(?:个|款|项|家|倍|%|％)", source_text))
        unsupported_numbers = [item for item in article_numbers if item and item not in source_numbers][:3]
        if unsupported_numbers:
            score -= 16
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="fabricated_claim_risk",
                    severity="medium",
                    description="正文出现来源中未能匹配的数字或量化表述，存在事实扩写风险。",
                    suggestion="删除无来源数字，或在原文/摘要中确认后再保留。",
                    evidence="、".join(unsupported_numbers),
                )
            )

        summary_only = [detail for detail in details if detail.content_availability != "full_text"]
        if summary_only and self._looks_over_specific(body):
            score -= 12
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="fabricated_claim_risk",
                    severity="medium",
                    description="部分来源只有摘要，但文章写法包含较具体的细节或确定性推断。",
                    suggestion="把相关表述改成“报道/摘要显示”层面的保守描述，避免补写未确认细节。",
                    evidence=_clean_evidence(summary_only[0].title_zh or summary_only[0].title),
                )
            )

        if self._has_hn_overstatement(details, body):
            score -= 42
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="hn_discussion_overstated",
                    severity="high",
                    description="文章疑似把 Hacker News 社区讨论写成官方事实或行业结论。",
                    suggestion="明确写成社区讨论/开发者反馈，不要写成官方确认或能力结论。",
                    evidence="Hacker News / " + _clean_evidence(self._hn_sentence(body)),
                )
            )
        if not article.factual_boundaries and not plan.factual_boundaries:
            score -= 8
        return _clamp(score)

    def _score_source_links(
        self,
        article: NewsArticle,
        plan: NewsArticlePlan,
        details: list[NewsDetailResult],
        markdown: str,
        issues: list[NewsArticleQualityIssue],
    ) -> float:
        expected_urls = _unique([*(article.source_urls or []), *(plan.source_urls or []), *[detail.url for detail in details]])
        expected_urls = [url for url in expected_urls if url]
        if not expected_urls:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="missing_source_link",
                    severity="high",
                    description="文章没有可核验的原文链接。",
                    suggestion="至少保留主新闻原文链接，并让链接跟随对应内容。",
                )
            )
            return 20
        present = [url for url in expected_urls if url in markdown]
        score = _clamp(len(present) / len(expected_urls) * 100)
        if not present:
            severity = "high"
        elif score < 80:
            severity = "medium"
        else:
            severity = ""
        if severity:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="missing_source_link",
                    severity=severity,
                    description="部分原文链接没有出现在发布稿正文中。",
                    suggestion="保留主新闻和关键补充来源链接，最好跟随对应段落或小节。",
                    evidence=f"{len(present)}/{len(expected_urls)}",
                )
            )
        return score

    def _score_insight(self, body: str, issues: list[NewsArticleQualityIssue]) -> float:
        marker_hits = sum(body.count(marker) for marker in self.INSIGHT_MARKERS)
        score = _clamp(56 + marker_hits * 8)
        if marker_hits < 4:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="shallow_insight",
                    severity="medium",
                    description="文章解读偏浅，容易像新闻转述。",
                    suggestion="补清楚“为什么值得关注”：影响谁、改变什么、下一步看什么。",
                    evidence=f"解读标记 {marker_hits}",
                )
            )
        return score

    def _score_readability(self, markdown: str, paragraphs: list[str], issues: list[NewsArticleQualityIssue]) -> float:
        if not paragraphs:
            return 40
        lengths = [self._count_text(paragraph) for paragraph in paragraphs if not LINK_PATTERN.search(paragraph)] or [0]
        long_count = sum(1 for length in lengths if length > 260)
        very_long_count = sum(1 for length in lengths if length > 420)
        heading_count = len(re.findall(r"^##\s+", markdown, flags=re.MULTILINE))
        score = _clamp(92 - long_count * 7 - very_long_count * 12 + min(heading_count, 4) * 2)
        if very_long_count or long_count >= 3:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="readability",
                    severity="medium",
                    description="存在较长段落，不利于公众号阅读。",
                    suggestion="把长段拆成更短段落，每段只承载一个判断或事实。",
                    evidence=f"长段落 {long_count}，超长段落 {very_long_count}",
                )
            )
        return score

    def _score_originality(
        self,
        markdown: str,
        details: list[NewsDetailResult],
        issues: list[NewsArticleQualityIssue],
    ) -> float:
        copied = self._copied_source_segments(markdown, details)
        english_copy = self._english_copy_paragraphs(markdown)
        score = _clamp(100 - len(copied) * 24 - len(english_copy) * 18)
        if copied or english_copy:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="copied_source_text",
                    severity="high" if len(copied) >= 2 or len(english_copy) >= 2 else "medium",
                    description="疑似存在原文或摘要搬运。",
                    suggestion="改成中文编辑口吻转述，只保留必要短引语和原文链接。",
                    evidence=_clean_evidence((copied or english_copy)[0]),
                )
            )
        return score

    def _score_human_tone(self, body: str, issues: list[NewsArticleQualityIssue]) -> float:
        phrase_hits = [(phrase, body.count(phrase)) for phrase in self.AI_REPORT_PHRASES if phrase in body]
        total_hits = sum(count for _, count in phrase_hits)
        score = _clamp(100 - total_hits * 7)
        if total_hits >= 3:
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="ai_report_tone",
                    severity="medium",
                    description="报告腔短语较多，读起来不够像人工编辑。",
                    suggestion="把套话换成具体判断，例如“谁会受影响、下一步看什么”。",
                    evidence="、".join(phrase for phrase, _ in phrase_hits[:5]),
                )
            )
        return score

    def _score_structure_naturalness(
        self,
        markdown: str,
        body: str,
        issues: list[NewsArticleQualityIssue],
    ) -> float:
        score = 100.0
        heading_lines = re.findall(r"^#{2,3}\s+(.+)$", markdown, flags=re.MULTILINE)
        h2_count = len(re.findall(r"^##\s+", markdown, flags=re.MULTILINE))
        h3_count = len(re.findall(r"^###\s+", markdown, flags=re.MULTILINE))
        if heading_lines:
            score -= min(45, 24 + len(heading_lines) * 7)
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="markdown_heading_overuse",
                    severity="high",
                    description="最终发布稿包含二级或三级 Markdown 标题，容易显得像 AI 大纲展开。",
                    suggestion="把小标题改成自然转场句，最终发布稿只保留文章主标题。",
                    evidence=_clean_evidence("；".join(heading_lines[:3])),
                )
            )

        list_lines = [line.strip() for line in markdown.splitlines() if self._is_list_line(line)]
        max_list_block = self._max_consecutive_list_lines(markdown)
        if len(list_lines) > 5 or max_list_block >= 4:
            score -= min(32, 12 + len(list_lines) * 3)
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="bullet_list_overuse",
                    severity="medium",
                    description="正文存在较多列表行，发布观感偏报告式。",
                    suggestion="把列表合并成自然段落，每段只保留一个事实或判断。",
                    evidence=_clean_evidence(" / ".join(list_lines[:4])),
                )
            )

        transition_positions = [body.find(word) for word in self.MECHANICAL_TRANSITIONS]
        if all(position >= 0 for position in transition_positions) and transition_positions == sorted(transition_positions):
            score -= 18
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="mechanical_structure",
                    severity="medium",
                    description="出现“首先/其次/最后”的机械推进，容易暴露 AI 写作痕迹。",
                    suggestion="改成按新闻事实、背景、影响自然递进的段落，不显式标序。",
                    evidence="首先 / 其次 / 最后",
                )
            )

        colon_title_lines = self._colon_title_lines(markdown)
        report_colon_hits = [
            line
            for line in colon_title_lines
            if any(line.startswith(title) for title in self.REPORT_STYLE_COLON_TITLES)
        ]
        if len(colon_title_lines) >= 3 or report_colon_hits:
            score -= min(24, 10 + len(colon_title_lines) * 4 + len(report_colon_hits) * 5)
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="mechanical_structure",
                    severity="medium",
                    description="冒号式小标题偏多，文章像报告结构而不是自然解读文。",
                    suggestion="删除冒号标题，把后面的判断并入同一自然段。",
                    evidence=_clean_evidence("；".join((report_colon_hits or colon_title_lines)[:3])),
                )
            )

        template_phrases = [phrase for phrase in ["本文将", "以下是", "从以下几个方面", "综上所述"] if phrase in body]
        if template_phrases:
            score -= 14
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="ai_report_tone",
                    severity="medium",
                    description="正文含有报告/提纲式套话。",
                    suggestion="删除说明性套话，直接进入新闻事实和编辑判断。",
                    evidence="、".join(template_phrases),
                )
            )

        if h2_count or h3_count:
            score -= min(14, (h2_count + h3_count) * 4)
        return _clamp(score)

    def _is_list_line(self, line: str) -> bool:
        return bool(re.match(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十]+[、.]\s*)", line or ""))

    def _max_consecutive_list_lines(self, markdown: str) -> int:
        longest = 0
        current = 0
        for line in markdown.splitlines():
            if self._is_list_line(line):
                current += 1
                longest = max(longest, current)
            elif line.strip():
                current = 0
        return longest

    def _colon_title_lines(self, markdown: str) -> list[str]:
        lines: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip().strip("*")
            if not stripped or LINK_PATTERN.search(stripped):
                continue
            if re.match(r"^[\u4e00-\u9fffA-Za-z0-9「」《》]{2,18}[:：]\s*$", stripped):
                lines.append(stripped.rstrip("：:"))
            elif re.match(r"^[\u4e00-\u9fffA-Za-z0-9「」《》]{2,18}[:：]\s*\S.{0,80}$", stripped) and len(stripped) <= 96:
                prefix = re.split(r"[:：]", stripped, maxsplit=1)[0]
                if len(prefix) <= 18:
                    lines.append(prefix)
        return lines

    def _check_link_context(self, markdown: str, issues: list[NewsArticleQualityIssue]) -> None:
        urls = LINK_PATTERN.findall(markdown)
        link_only_lines = [
            line.strip()
            for line in markdown.splitlines()
            if LINK_PATTERN.search(line) and len(re.sub(LINK_PATTERN, "", line).strip(" -*：:")) < 4
        ]
        if len(urls) >= 5 and len(link_only_lines) >= max(4, len(urls) // 2):
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="too_many_links_without_context",
                    severity="medium",
                    description="链接裸露或堆砌偏多。",
                    suggestion="把链接移动到对应事实或小节下方，并补一句来源上下文。",
                    evidence=f"裸链接行 {len(link_only_lines)} / 链接 {len(urls)}",
                )
            )

    def _check_reader_takeaway(self, body: str, issues: list[NewsArticleQualityIssue]) -> None:
        if not any(marker in body for marker in self.TAKEAWAY_MARKERS):
            issues.append(
                NewsArticleQualityIssue(
                    issue_type="missing_reader_takeaway",
                    severity="medium",
                    description="缺少清晰的读者收获或编辑判断。",
                    suggestion="补一段“我的判断/读者可以怎么用这条信息/下一步看什么”。",
                )
            )

    def _check_interaction_metrics(self, markdown: str, issues: list[NewsArticleQualityIssue]) -> None:
        hits = interaction_metric_hits(markdown)
        if not hits:
            return
        issues.append(
            NewsArticleQualityIssue(
                issue_type="interaction_metric_used",
                severity="high",
                description="文章使用了点赞数、评论数、points、comments 或互动热度相关表述。",
                suggestion="删除互动数量相关表述，改成基于事实、来源和事件影响来写。",
                evidence="、".join(hits[:6]),
            )
        )

    def _check_unsupported_community_claims(
        self,
        markdown: str,
        details: list[NewsDetailResult],
        issues: list[NewsArticleQualityIssue],
    ) -> None:
        hits = unsupported_community_claim_hits(markdown)
        if not hits:
            return
        source_text = "\n".join(
            detail.content_text or detail.content_preview or detail.summary_zh or detail.summary or "" for detail in details
        )
        if all(hit in source_text for hit in hits):
            return
        issues.append(
            NewsArticleQualityIssue(
                issue_type="unsupported_community_claim",
                severity="high",
                description="文章概括了社区共识或开发者普遍观点，但当前来源中没有具体评论正文支撑。",
                suggestion="删除社区共识判断；只有抓取到有信息增量的评论正文时，才可作为补充参考。",
                evidence="、".join(hits[:6]),
            )
        )

    def _has_hn_overstatement(self, details: list[NewsDetailResult], body: str) -> bool:
        has_hn = any("hn" in (detail.source_type or detail.source or "").casefold() or "hacker" in (detail.source_type or detail.source or "").casefold() for detail in details)
        if not has_hn:
            return False
        sentences = re.split(r"[。！？\n]", body)
        for sentence in sentences:
            if not sentence.strip():
                continue
            mentions_discussion = any(keyword in sentence for keyword in ["Hacker News", "HN", "社区", "开发者讨论", "网友"])
            official_words = any(word in sentence for word in self.OFFICIAL_FACT_WORDS)
            if mentions_discussion and official_words:
                return True
        return False

    def _hn_sentence(self, body: str) -> str:
        for sentence in re.split(r"[。！？\n]", body):
            if any(keyword in sentence for keyword in ["Hacker News", "HN", "社区", "开发者讨论", "网友"]):
                return sentence
        return ""

    def _looks_over_specific(self, body: str) -> bool:
        concrete_markers = ["发布了", "上线了", "融资", "营收", "用户数", "准确率", "提升", "降低", "版本", "参数", "负责人", "路线图"]
        number_count = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", body))
        return number_count >= 3 or sum(body.count(marker) for marker in concrete_markers) >= 5

    def _source_corpus(self, plan: NewsArticlePlan, details: list[NewsDetailResult]) -> str:
        parts = [
            plan.event_summary,
            " ".join(plan.key_facts or []),
            " ".join(plan.background_context or []),
            " ".join(plan.factual_boundaries or []),
        ]
        for detail in details:
            parts.extend([detail.title, detail.title_zh or "", detail.summary, detail.summary_zh or "", detail.content_preview, detail.content_text or ""])
        return "\n".join(part for part in parts if part)

    def _copied_source_segments(self, markdown: str, details: list[NewsDetailResult]) -> list[str]:
        normalized_markdown = re.sub(r"\s+", "", markdown)
        copied: list[str] = []
        for detail in details:
            for text in [detail.summary_zh, detail.summary, detail.content_preview, detail.content_text]:
                for segment in self._candidate_source_segments(text or ""):
                    normalized = re.sub(r"\s+", "", segment)
                    if len(normalized) >= 80 and normalized[:80] in normalized_markdown:
                        copied.append(segment)
                        break
                if copied and len(copied) >= 3:
                    return copied
        return copied

    def _candidate_source_segments(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return []
        sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])\s+", cleaned) if len(item.strip()) >= 80]
        if sentences:
            return sentences[:8]
        return [cleaned[:260]] if len(cleaned) >= 120 else []

    def _english_copy_paragraphs(self, markdown: str) -> list[str]:
        risky: list[str] = []
        for line in markdown.splitlines():
            paragraph = line.strip()
            if len(paragraph) < 160 or LINK_PATTERN.search(paragraph):
                continue
            letters = sum(1 for char in paragraph if char.isascii() and char.isalpha())
            chinese = sum(1 for char in paragraph if "\u4e00" <= char <= "\u9fff")
            if letters > 130 and letters > max(1, chinese) * 2:
                risky.append(paragraph)
        return risky

    def _strip_markdown_noise(self, markdown: str) -> str:
        lines = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(">"):
                continue
            lines.append(stripped)
        return "\n".join(lines)

    def _paragraphs(self, text: str) -> list[str]:
        return [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]

    def _count_text(self, value: str) -> int:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", value or ""))
        words = len(re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", value or ""))
        return chinese_chars + words

    def _title_from_markdown(self, markdown: str) -> str:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def _dedupe_issues(self, issues: list[NewsArticleQualityIssue]) -> list[NewsArticleQualityIssue]:
        severity_rank = {"high": 3, "medium": 2, "low": 1}
        by_type: dict[str, NewsArticleQualityIssue] = {}
        for issue in issues:
            current = by_type.get(issue.issue_type)
            if current is None or severity_rank.get(issue.severity, 0) > severity_rank.get(current.severity, 0):
                by_type[issue.issue_type] = issue
        return list(by_type.values())

    def _strengths(self, scores: dict[str, float]) -> list[str]:
        labels = {
            "title": "标题克制且有信息量",
            "opening": "开头能较快进入新闻价值",
            "factual_integrity": "事实边界较稳",
            "source_link": "原文链接保留较完整",
            "insight": "具备读者视角解读",
            "readability": "段落适合公众号阅读",
            "originality": "未发现明显原文搬运",
            "human_tone": "整体语气不算生硬",
            "structure_naturalness": "结构推进较自然",
        }
        return [labels[key] for key, score in scores.items() if score >= 85][:5]

    def _recommendations(self, issues: list[NewsArticleQualityIssue], scores: dict[str, float]) -> list[str]:
        recommendations = [issue.suggestion for issue in issues if issue.suggestion]
        if scores.get("factual_integrity", 100) < 85:
            recommendations.append("优先复核所有确定性表述，尤其是数字、时间、官方态度和模型能力结论。")
        if scores.get("source_link", 100) < 90:
            recommendations.append("检查主新闻和关键补充来源链接是否出现在正文中。")
        if scores.get("insight", 100) < 80:
            recommendations.append("补强“为什么值得关注”和“读者下一步看什么”。")
        if scores.get("human_tone", 100) < 85:
            recommendations.append("减少报告腔套话，改成更具体的编辑判断。")
        if scores.get("structure_naturalness", 100) < 85:
            recommendations.append("去掉二级/三级标题和大段列表，把“发生了什么、为什么重要、影响”改成自然转场段落。")
        return _unique(recommendations)[:8]

    def _summary(self, total_score: float, publish_ready: bool, issues: list[NewsArticleQualityIssue]) -> str:
        high_count = sum(1 for issue in issues if issue.severity == "high")
        if publish_ready:
            return f"质量分 {total_score:.1f}，没有高严重度问题，可以进入发布前人工通读。"
        if high_count:
            return f"质量分 {total_score:.1f}，存在 {high_count} 个高严重度问题，暂不建议发布。"
        return f"质量分 {total_score:.1f}，建议按报告修订后再发布。"

    def _article_date(self, article: NewsArticle) -> str:
        if article.generated_at:
            try:
                return datetime.fromisoformat(article.generated_at.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return article.generated_at[:10]
        return datetime.now().date().isoformat()
