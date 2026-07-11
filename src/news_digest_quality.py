from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.models import (
    NewsDigestArticle,
    NewsDigestQualityIssue,
    NewsDigestQualityReport,
    NewsEventCard,
    NewsEventResult,
)


LINK_PATTERN = re.compile(r"https?://[^\s)>\]，。；、]+")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_class: Any, payload: dict[str, Any]) -> Any:
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


class NewsDigestQualityEvaluator:
    """Deterministic quality review for the AI news digest."""

    AI_REPORT_PHRASES = [
        "本文将",
        "综上",
        "总的来说",
        "总体而言",
        "根据新闻",
        "具有重要意义",
        "具有较高参考价值",
        "值得注意的是",
        "可以看出",
        "赋能",
        "生态",
        "降本增效",
        "提升效率",
    ]
    INSIGHT_MARKERS = [
        "为什么值得关注",
        "值得关注",
        "这意味着",
        "影响",
        "后续",
        "观察",
        "信号",
        "风险",
        "开发者",
        "落地",
        "验证",
        "反馈",
        "合规",
    ]
    WEAK_OPENING_PHRASES = [
        "本文将",
        "随着人工智能的发展",
        "在当今快速发展的",
        "根据新闻",
        "今天的 AI 新闻重点来自",
    ]

    def __init__(self, workspace_dir: Path | None = None, output_dir: Path | None = None) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir

    def load_latest_digest(self) -> NewsDigestArticle:
        path = self.workspace_dir / "news" / "news_digest_latest.json"
        if not path.exists():
            raise FileNotFoundError("workspace/news/news_digest_latest.json not found. Please run write-news-digest first.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workspace/news/news_digest_latest.json must contain a JSON object.")
        return _model_validate(NewsDigestArticle, payload)

    def load_latest_events(self) -> NewsEventResult | None:
        path = self.workspace_dir / "news" / "news_events_latest.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return _model_validate(NewsEventResult, payload)

    def evaluate_latest(self, threshold: float = 80.0) -> NewsDigestQualityReport:
        return self.evaluate(self.load_latest_digest(), self.load_latest_events(), threshold=threshold)

    def evaluate(
        self,
        article: NewsDigestArticle,
        events_result: NewsEventResult | None = None,
        threshold: float = 80.0,
    ) -> NewsDigestQualityReport:
        issues: list[NewsDigestQualityIssue] = []
        markdown = article.content_markdown or ""
        body = self._strip_markdown_noise(markdown)
        paragraphs = self._paragraphs(body)
        selected_events = self._selected_events(article, events_result)

        freshness_score = self._score_freshness(article, selected_events, issues)
        source_integrity_score = self._score_source_integrity(article, selected_events, markdown, issues)
        section_balance_score = self._score_section_balance(article, markdown, issues)
        insight_score = self._score_insight(article, body, issues)
        readability_score = self._score_readability(markdown, paragraphs, issues)
        originality_score = self._score_originality(markdown, selected_events, issues)
        human_tone_score = self._score_human_tone(body, issues)
        link_integrity_score = self._score_link_integrity(markdown, issues)
        self._check_opening(paragraphs, issues)
        self._check_today_observation(markdown, issues)

        total_score = round(
            freshness_score * 0.15
            + source_integrity_score * 0.16
            + section_balance_score * 0.10
            + insight_score * 0.17
            + readability_score * 0.12
            + originality_score * 0.12
            + human_tone_score * 0.10
            + link_integrity_score * 0.08,
            2,
        )
        issues = self._dedupe_issues(issues)
        publish_ready = total_score >= float(threshold or 80) and not any(issue.severity == "high" for issue in issues)
        scores = {
            "freshness": freshness_score,
            "source_integrity": source_integrity_score,
            "section_balance": section_balance_score,
            "insight": insight_score,
            "readability": readability_score,
            "originality": originality_score,
            "human_tone": human_tone_score,
            "link_integrity": link_integrity_score,
        }

        return NewsDigestQualityReport(
            title=article.title or self._title_from_markdown(markdown),
            total_score=total_score,
            publish_ready=publish_ready,
            freshness_score=round(freshness_score, 2),
            source_integrity_score=round(source_integrity_score, 2),
            section_balance_score=round(section_balance_score, 2),
            insight_score=round(insight_score, 2),
            readability_score=round(readability_score, 2),
            originality_score=round(originality_score, 2),
            human_tone_score=round(human_tone_score, 2),
            link_integrity_score=round(link_integrity_score, 2),
            issues=issues,
            strengths=self._strengths(scores),
            rewrite_recommendations=self._recommendations(issues, scores),
            summary=self._summary(total_score, publish_ready, issues),
        )

    def save_report(self, article: NewsDigestArticle, report: NewsDigestQualityReport) -> None:
        generated_date = article.date or datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        report_payload = json.dumps(_model_dump(report), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_digest_review_latest.json").write_text(report_payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news-digest-review.json").write_text(report_payload, encoding="utf-8")
        (snapshots_dir / "news_digest_review_latest.json").write_text(report_payload, encoding="utf-8")
        (output_date_dir / "ai_news_digest_review.md").write_text(self.render_report_markdown(article, report), encoding="utf-8")

    def render_report_markdown(self, article: NewsDigestArticle, report: NewsDigestQualityReport) -> str:
        lines = [
            f"# AI 新闻日报质量评估：{report.title or article.title or article.date}",
            "",
            f"- 总分：{report.total_score:.1f}",
            f"- 可发布：{'是' if report.publish_ready else '否'}",
            f"- 日报日期：{article.date or '-'}",
            f"- 事件数：{article.event_count}",
            "",
            "## 分项得分",
            "",
            f"- 新闻新鲜度：{report.freshness_score:.1f}",
            f"- 来源完整性：{report.source_integrity_score:.1f}",
            f"- 栏目均衡：{report.section_balance_score:.1f}",
            f"- 解读深度：{report.insight_score:.1f}",
            f"- 阅读体验：{report.readability_score:.1f}",
            f"- 原创表达：{report.originality_score:.1f}",
            f"- 人味表达：{report.human_tone_score:.1f}",
            f"- 链接完整性：{report.link_integrity_score:.1f}",
            "",
            "## 主要问题",
            "",
        ]
        if report.issues:
            for issue in report.issues:
                evidence = f"  证据：{issue.evidence}" if issue.evidence else ""
                lines.extend(
                    [
                        f"- [{issue.severity}] {issue.issue_type}：{issue.description}",
                        f"  建议：{issue.suggestion}",
                    ]
                )
                if evidence:
                    lines.append(evidence)
        else:
            lines.append("- 未发现阻塞发布的问题。")

        lines.extend(["", "## 修改建议", ""])
        lines.extend(f"- {item}" for item in (report.rewrite_recommendations or ["保持现有结构，发布前人工通读事实表述。"]))
        lines.extend(["", "## 结论", "", report.summary, ""])
        return "\n".join(lines)

    def _selected_events(
        self,
        article: NewsDigestArticle,
        events_result: NewsEventResult | None,
    ) -> list[NewsEventCard]:
        if not events_result:
            return []
        wanted = {event_id for event_id in article.source_event_ids if event_id}
        if not wanted:
            return events_result.events[: article.event_count or 0]
        return [event for event in events_result.events if event.event_id in wanted]

    def _score_freshness(
        self,
        article: NewsDigestArticle,
        events: list[NewsEventCard],
        issues: list[NewsDigestQualityIssue],
    ) -> float:
        if events:
            values = [self._freshness_value(event) for event in events]
            score = sum(values) / len(values)
            stale_count = sum(1 for value in values if value < 60)
            if stale_count:
                issues.append(
                    NewsDigestQualityIssue(
                        issue_type="stale_news",
                        severity="high" if stale_count >= max(2, len(values) // 2) else "medium",
                        description=f"{stale_count} 条事件新鲜度偏低。",
                        suggestion="优先使用 today、last_24h 或 last_72h 的事件，旧新闻放到“继续跟进”。",
                    )
                )
            return _clamp(score)

        try:
            digest_date = datetime.fromisoformat((article.date or "").strip()).date()
            days_old = (datetime.now().date() - digest_date).days
        except ValueError:
            days_old = 999
        if days_old <= 0:
            return 82
        if days_old <= 3:
            return 68
        issues.append(
            NewsDigestQualityIssue(
                issue_type="stale_news",
                severity="medium",
                description="没有事件卡可核验新鲜度，且日报日期不是今天。",
                suggestion="重新运行 collect-news --hours 72 后再生成日报。",
                evidence=article.date,
            )
        )
        return 45

    def _freshness_value(self, event: NewsEventCard) -> float:
        freshness = (event.freshness or "").lower()
        if freshness in {"today", "last_24h", "24h", "fresh"}:
            return 100
        if freshness in {"last_72h", "72h", "recent"}:
            return 86
        if freshness in {"older", "old", "stale"}:
            return 42
        timestamp = event.latest_published_at or event.published_at
        if timestamp:
            try:
                published = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
                if hours <= 24:
                    return 100
                if hours <= 72:
                    return 86
                if hours <= 168:
                    return 62
            except ValueError:
                pass
        return 65

    def _score_source_integrity(
        self,
        article: NewsDigestArticle,
        events: list[NewsEventCard],
        markdown: str,
        issues: list[NewsDigestQualityIssue],
    ) -> float:
        source_urls = _unique([url for url in article.source_urls if url])
        markdown_urls = set(LINK_PATTERN.findall(markdown))
        expected = max(article.event_count or 0, len(events), len(source_urls), 1)
        present_source_urls = [url for url in source_urls if url in markdown]
        event_with_link = 0
        for event in events:
            urls = _unique([*(event.urls or []), event.primary_url])
            if urls and any(url in markdown for url in urls):
                event_with_link += 1
        coverage_count = max(len(present_source_urls), event_with_link, len(markdown_urls))
        score = _clamp(coverage_count / expected * 100)

        if score < 75:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="missing_source_links",
                    severity="high" if score < 50 else "medium",
                    description="部分新闻没有在正文中保留对应原文链接。",
                    suggestion="每条新闻下面保留至少一个原文链接，链接跟随对应新闻，不集中堆到文末。",
                    evidence=f"{coverage_count}/{expected}",
                )
            )
        return score

    def _score_section_balance(
        self,
        article: NewsDigestArticle,
        markdown: str,
        issues: list[NewsDigestQualityIssue],
    ) -> float:
        sections = article.sections or re.findall(r"^##\s+(.+)$", markdown, flags=re.MULTILINE)
        publish_sections = [section for section in sections if "观察" not in section and "链接" not in section]
        unique_sections = _unique(publish_sections)
        if len(unique_sections) >= 4:
            return 100
        if len(unique_sections) == 3:
            return 88
        if len(unique_sections) == 2:
            return 72
        issues.append(
            NewsDigestQualityIssue(
                issue_type="section_too_single",
                severity="medium",
                description="日报栏目过于单一，阅读上像单主题汇总。",
                suggestion="尽量覆盖模型产品、开源工具、研究、社区、商业监管中的至少两个栏目。",
                evidence="、".join(unique_sections) or "未识别到栏目",
            )
        )
        return 52 if unique_sections else 35

    def _score_insight(
        self,
        article: NewsDigestArticle,
        body: str,
        issues: list[NewsDigestQualityIssue],
    ) -> float:
        marker_hits = sum(body.count(marker) for marker in self.INSIGHT_MARKERS)
        h3_count = max(1, len(re.findall(r"^###\s+", article.content_markdown or "", flags=re.MULTILINE)))
        ratio = marker_hits / h3_count
        score = _clamp(58 + ratio * 18)
        if marker_hits < max(2, h3_count // 2):
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="shallow_insight",
                    severity="medium",
                    description="解读信号偏少，容易变成新闻标题罗列。",
                    suggestion="每条新闻补一句“为什么值得关注”：影响谁、可能改变什么、后续看什么。",
                    evidence=f"解读标记 {marker_hits} / 新闻小节 {h3_count}",
                )
            )
        return score

    def _score_readability(
        self,
        markdown: str,
        paragraphs: list[str],
        issues: list[NewsDigestQualityIssue],
    ) -> float:
        if not paragraphs:
            return 45
        readable_paragraphs = [paragraph for paragraph in paragraphs if not LINK_PATTERN.search(paragraph)] or paragraphs
        lengths = [self._count_text(paragraph) for paragraph in readable_paragraphs]
        long_count = sum(1 for length in lengths if length > 260)
        very_long_count = sum(1 for length in lengths if length > 420)
        score = _clamp(100 - long_count * 7 - very_long_count * 12)
        if very_long_count or long_count >= 3:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="readability",
                    severity="medium",
                    description="存在较长段落，不利于公众号阅读。",
                    suggestion="把长段拆成 2-3 段，先说结论，再补背景和后续观察。",
                    evidence=f"长段落 {long_count}，超长段落 {very_long_count}",
                )
            )
        return score

    def _score_originality(
        self,
        markdown: str,
        events: list[NewsEventCard],
        issues: list[NewsDigestQualityIssue],
    ) -> float:
        english_copy = self._english_copy_paragraphs(markdown)
        repeated_source_summaries = self._copied_event_summary_count(markdown, events)
        score = _clamp(100 - len(english_copy) * 22 - repeated_source_summaries * 12)
        if english_copy or repeated_source_summaries:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="copied_source_text",
                    severity="high" if len(english_copy) >= 2 else "medium",
                    description="疑似存在原文或事件摘要搬运。",
                    suggestion="改成中文编辑口吻重述事实，只保留短引语和原文链接。",
                    evidence=_clean_evidence(english_copy[0] if english_copy else f"疑似重复摘要 {repeated_source_summaries} 处"),
                )
            )
        return score

    def _score_human_tone(self, body: str, issues: list[NewsDigestQualityIssue]) -> float:
        phrase_hits = [(phrase, body.count(phrase)) for phrase in self.AI_REPORT_PHRASES if phrase in body]
        total_hits = sum(count for _, count in phrase_hits)
        score = _clamp(100 - total_hits * 6)
        if total_hits >= 4:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="ai_report_tone",
                    severity="medium",
                    description="报告腔短语较多，读起来不够像人工编辑。",
                    suggestion="减少“综上、具有重要意义、赋能生态”等套话，改成更具体的编辑判断。",
                    evidence="、".join(phrase for phrase, _ in phrase_hits[:5]),
                )
            )
        return score

    def _score_link_integrity(self, markdown: str, issues: list[NewsDigestQualityIssue]) -> float:
        urls = LINK_PATTERN.findall(markdown)
        malformed = re.findall(r"https?://\S*[\u4e00-\u9fff]\S*", markdown)
        link_only_lines = [
            line.strip()
            for line in markdown.splitlines()
            if LINK_PATTERN.search(line) and len(re.sub(LINK_PATTERN, "", line).strip(" -*：:")) < 4
        ]
        score = _clamp(100 - len(malformed) * 20 - max(0, len(link_only_lines) - 3) * 7)
        if len(urls) >= 8 and len(link_only_lines) >= max(5, len(urls) // 2):
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="too_many_links_without_context",
                    severity="medium",
                    description="链接裸露或堆砌偏多。",
                    suggestion="链接应跟随对应新闻，并用“原文链接：URL”的固定格式承接。",
                    evidence=f"裸链接行 {len(link_only_lines)} / 链接 {len(urls)}",
                )
            )
        if "### 补充原文链接" in markdown:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="too_many_links_without_context",
                    severity="medium",
                    description="正文末尾存在补充链接区，链接没有跟随对应新闻。",
                    suggestion="把补充链接移动到对应新闻下方，避免读者在文末重新匹配来源。",
                    evidence="### 补充原文链接",
                )
            )
            score = min(score, 72)
        if malformed:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="link_integrity",
                    severity="medium",
                    description="存在疑似格式异常的链接。",
                    suggestion="检查 URL 是否被中文标点或正文粘连。",
                    evidence=_clean_evidence(malformed[0]),
                )
            )
        return score

    def _check_opening(self, paragraphs: list[str], issues: list[NewsDigestQualityIssue]) -> None:
        opening = "\n".join(paragraphs[:2])
        if not opening or len(opening) < 45 or any(phrase in opening for phrase in self.WEAK_OPENING_PHRASES):
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="weak_opening",
                    severity="low",
                    description="开头比较模板化或信息量不足。",
                    suggestion="用今天最值得看的变化开场，少写流程说明。",
                    evidence=_clean_evidence(opening),
                )
            )

    def _check_today_observation(self, markdown: str, issues: list[NewsDigestQualityIssue]) -> None:
        if "今日观察" not in markdown and "值得继续关注" not in markdown:
            issues.append(
                NewsDigestQualityIssue(
                    issue_type="missing_today_observation",
                    severity="medium",
                    description="缺少结尾的今日观察或继续关注。",
                    suggestion="补一个短结尾，总结当天新闻的共同方向和下一步观察点。",
                )
            )

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

    def _english_copy_paragraphs(self, markdown: str) -> list[str]:
        paragraphs = [
            line.strip()
            for line in markdown.splitlines()
            if len(line.strip()) >= 160 and not LINK_PATTERN.search(line)
        ]
        risky: list[str] = []
        for paragraph in paragraphs:
            letters = sum(1 for char in paragraph if char.isascii() and char.isalpha())
            chinese = sum(1 for char in paragraph if "\u4e00" <= char <= "\u9fff")
            if letters > 130 and letters > max(1, chinese) * 2:
                risky.append(paragraph)
        return risky

    def _copied_event_summary_count(self, markdown: str, events: list[NewsEventCard]) -> int:
        normalized_markdown = re.sub(r"\s+", "", markdown)
        count = 0
        for event in events:
            for summary in (event.event_summary_zh, event.event_summary):
                cleaned = re.sub(r"\s+", "", summary or "")
                if len(cleaned) >= 80 and cleaned[:80] in normalized_markdown:
                    count += 1
                    break
        return count

    def _count_text(self, value: str) -> int:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", value or ""))
        words = len(re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", value or ""))
        return chinese_chars + words

    def _title_from_markdown(self, markdown: str) -> str:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def _dedupe_issues(self, issues: list[NewsDigestQualityIssue]) -> list[NewsDigestQualityIssue]:
        severity_rank = {"high": 3, "medium": 2, "low": 1}
        by_type: dict[str, NewsDigestQualityIssue] = {}
        for issue in issues:
            current = by_type.get(issue.issue_type)
            if current is None or severity_rank.get(issue.severity, 0) > severity_rank.get(current.severity, 0):
                by_type[issue.issue_type] = issue
        return list(by_type.values())

    def _strengths(self, scores: dict[str, float]) -> list[str]:
        labels = {
            "freshness": "新闻新鲜度较好",
            "source_integrity": "原文来源保留较完整",
            "section_balance": "栏目分布比较均衡",
            "insight": "具备一定编辑解读",
            "readability": "段落长度适合公众号阅读",
            "originality": "未发现明显搬运原文",
            "human_tone": "整体语气不算生硬",
            "link_integrity": "链接格式基本正常",
        }
        return [labels[key] for key, score in scores.items() if score >= 85][:5]

    def _recommendations(self, issues: list[NewsDigestQualityIssue], scores: dict[str, float]) -> list[str]:
        recommendations = [issue.suggestion for issue in issues if issue.suggestion]
        if scores.get("insight", 100) < 80:
            recommendations.append("优先补强每条新闻的“为什么值得关注”，把事实和编辑判断分开写。")
        if scores.get("human_tone", 100) < 85:
            recommendations.append("把报告腔套话替换成具体判断，例如“这会影响谁、下一步看什么”。")
        if scores.get("source_integrity", 100) < 90:
            recommendations.append("人工复核每条新闻是否有紧随其后的原文链接。")
        return _unique(recommendations)[:8]

    def _summary(self, total_score: float, publish_ready: bool, issues: list[NewsDigestQualityIssue]) -> str:
        high_count = sum(1 for issue in issues if issue.severity == "high")
        if publish_ready:
            return f"质量分 {total_score:.1f}，没有高严重度问题，可以进入发布前人工通读。"
        if high_count:
            return f"质量分 {total_score:.1f}，存在 {high_count} 个高严重度问题，暂不建议发布。"
        return f"质量分 {total_score:.1f}，未达到发布阈值，建议按问题列表轻量修改后再评估。"
