from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.interaction_metrics import strip_interaction_metric_text
from src.llm_service import LLMService
from src.models import NewsArticle, NewsArticleQualityReport


LINK_PATTERN = re.compile(r"https?://[^\s)>\]，。；、]+")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_copy(model: Any, update: dict[str, Any]) -> Any:
    if hasattr(model, "model_copy"):
        return model.model_copy(update=update)
    return model.copy(update=update)


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


class NewsArticlePolisherService:
    """Lightly polish and package one AI news article without changing facts."""

    RULE_REPLACEMENTS = [
        ("本文将从以下几个方面", ""),
        ("本文将", ""),
        ("以下是", ""),
        ("从以下几个方面", ""),
        ("综上所述，", ""),
        ("综上，", ""),
        ("根据新闻，", ""),
        ("根据新闻", ""),
        ("资料显示，", ""),
        ("资料显示", ""),
        ("具有重要意义", "值得继续观察"),
        ("具有较高参考价值", "值得单独看一眼"),
        ("赋能", "支持"),
        ("降本增效", "提高使用效率"),
    ]

    def __init__(
        self,
        workspace_dir: Path | None = None,
        output_dir: Path | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        settings = get_settings()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir
        self.llm = llm_service or LLMService(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )
        self.used_llm = False
        self.warnings: list[str] = []

    def polish_article(
        self,
        article: NewsArticle,
        quality_report: NewsArticleQualityReport,
    ) -> NewsArticle:
        original_markdown = article.content_markdown or ""
        if quality_report.total_score >= 92 and quality_report.publish_ready and not self._needs_structural_polish(original_markdown):
            return self.attach_quality(article, quality_report, polished=False)

        original_urls = _unique(article.source_urls or LINK_PATTERN.findall(original_markdown))
        polished_markdown = self._heuristic_polish(original_markdown)
        if self.llm.is_available() and quality_report.issues:
            llm_markdown = self._polish_with_llm(article, quality_report, polished_markdown)
            if llm_markdown and self._keeps_links(llm_markdown, original_urls):
                self.used_llm = True
                polished_markdown = llm_markdown
            elif llm_markdown:
                self.warnings.append("LLM polish was rejected because it dropped source links.")

        if not self._keeps_links(polished_markdown, original_urls):
            self.warnings.append("Polish was reverted because it dropped source links.")
            polished_markdown = original_markdown

        changed = polished_markdown.strip() != original_markdown.strip()
        return _model_copy(
            article,
            update={
                "content_markdown": polished_markdown.rstrip() + "\n",
                "word_count": self._word_count(polished_markdown),
                "quality_report": quality_report,
                "quality_score": quality_report.total_score,
                "quality_publish_ready": quality_report.publish_ready,
                "publish_ready": quality_report.publish_ready,
                "publish_polished": changed,
                "warnings": _unique([*(article.warnings or []), *self.warnings]),
            },
        )

    def attach_quality(
        self,
        article: NewsArticle,
        quality_report: NewsArticleQualityReport,
        polished: bool = False,
    ) -> NewsArticle:
        return _model_copy(
            article,
            update={
                "quality_report": quality_report,
                "quality_score": quality_report.total_score,
                "quality_publish_ready": quality_report.publish_ready,
                "publish_ready": quality_report.publish_ready,
                "publish_polished": polished,
            },
        )

    def generate_package(
        self,
        article: NewsArticle,
        quality_report: NewsArticleQualityReport,
    ) -> NewsArticle:
        generated_date = self._article_date(article)
        output_article_dir = self.output_dir / generated_date / "news_articles"
        output_article_dir.mkdir(parents=True, exist_ok=True)
        publish_path = output_article_dir / f"{article.article_id}_publish.md"
        package_path = output_article_dir / f"{article.article_id}_package.md"

        publish_markdown = self._publish_markdown(article)
        package_markdown = self._package_markdown(article, quality_report, publish_markdown)
        publish_path.write_text(publish_markdown.rstrip() + "\n", encoding="utf-8")
        package_path.write_text(package_markdown.rstrip() + "\n", encoding="utf-8")
        return _model_copy(article, update={"publish_package_path": self._relative_path(package_path)})

    def save_article(self, article: NewsArticle) -> None:
        generated_date = self._article_date(article)
        news_dir = self.workspace_dir / "news"
        articles_dir = news_dir / "articles"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_article_dir = self.output_dir / generated_date / "news_articles"
        news_dir.mkdir(parents=True, exist_ok=True)
        articles_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_article_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(article), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_article_latest.json").write_text(payload, encoding="utf-8")
        (articles_dir / f"{article.article_id}.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_article_latest.json").write_text(payload, encoding="utf-8")
        (output_article_dir / f"{article.article_id}.md").write_text(self._with_cover_header(article, article.content_markdown), encoding="utf-8")

    def _heuristic_polish(self, markdown: str) -> str:
        content = markdown.strip()
        for old, new in self.RULE_REPLACEMENTS:
            content = content.replace(old, new)
        content = self._naturalize_headings(content)
        content = self._merge_list_blocks(content)
        content = self._remove_report_colon_titles(content)
        content = self._remove_mechanical_transitions(content)
        content = self._format_link_blocks(content)
        content = self._normalize_repeated_phrases(content)
        content = strip_interaction_metric_text(content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r"[ \t]+\n", "\n", content)
        content = re.sub(r"([。！？])\s+([^\n#>-])", r"\1\n\n\2", content)
        return content.strip() + "\n"

    def _needs_structural_polish(self, markdown: str) -> bool:
        return bool(
            re.search(r"^#{2,3}\s+", markdown, flags=re.MULTILINE)
            or self._max_consecutive_list_lines(markdown) >= 4
            or sum(1 for line in markdown.splitlines() if self._is_list_line(line)) > 5
            or re.search(r"首先[\s，,].*其次[\s，,].*最后[\s，,]", markdown, flags=re.DOTALL)
        )

    def _naturalize_headings(self, markdown: str) -> str:
        transitions = {
            "发生了什么": "先说新闻本身。",
            "先说发生了什么": "先说新闻本身。",
            "为什么重要": "这件事真正值得看的地方在后面。",
            "为什么这件事不只是热闹": "这件事不只是热闹。",
            "对开发者的影响": "把视角放到开发者身上，影响会更具体一些。",
            "对开发者和 AI 使用者意味着什么": "把视角放到开发者和 AI 使用者身上，影响会更具体一些。",
            "行业层面可以怎么观察": "行业层面暂时不需要过度推演。",
            "我的判断": "我的判断是，先把它放进观察列表。",
            "继续关注什么": "后续继续看事实边界就够了。",
            "原文链接": "原文链接：",
            "来源链接": "来源链接：",
        }

        def replace_heading(match: re.Match[str]) -> str:
            heading = match.group(1).strip().strip("* ：:。")
            return transitions.get(heading, f"{heading}。")

        return re.sub(r"^#{2,3}\s+(.+?)\s*$", replace_heading, markdown, flags=re.MULTILINE)

    def _merge_list_blocks(self, markdown: str) -> str:
        lines = markdown.splitlines()
        merged: list[str] = []
        block: list[str] = []

        def flush() -> None:
            nonlocal block
            if not block:
                return
            items = [self._strip_list_marker(item) for item in block]
            if all(LINK_PATTERN.fullmatch(item.strip()) for item in items):
                label = "原文链接"
                if merged and re.match(r"^(原文链接|来源链接)[:：]?\s*$", merged[-1].strip()):
                    previous = merged.pop().strip()
                    label = "来源链接" if previous.startswith("来源链接") else "原文链接"
                merged.append(f"{label}：{' | '.join(items)}")
            else:
                merged.append(self._join_list_items(items))
            block = []

        for line in lines:
            if self._is_list_line(line):
                block.append(line)
                continue
            flush()
            merged.append(line)
        flush()
        return "\n".join(merged)

    def _is_list_line(self, line: str) -> bool:
        return bool(re.match(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十]+[、.]\s*)", line or ""))

    def _strip_list_marker(self, line: str) -> str:
        return re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十]+[、.]\s*)", "", line or "").strip()

    def _join_list_items(self, items: list[str]) -> str:
        cleaned = [item.rstrip("。；;") for item in items if item.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0].rstrip() + ("。" if not re.search(r"[。！？.!?]$", cleaned[0]) else "")
        return "；".join(cleaned) + "。"

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

    def _remove_report_colon_titles(self, markdown: str) -> str:
        report_titles = {
            "发生了什么": "先说新闻本身。",
            "为什么重要": "这件事真正值得看的地方在后面。",
            "对开发者来说": "对开发者来说，",
            "对开发者的影响": "对开发者来说，",
            "行业影响": "放到行业层面看，",
            "我的判断": "我的判断是，",
            "继续关注": "后续可以继续看，",
        }
        result: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip().strip("*")
            match = re.match(r"^([\u4e00-\u9fffA-Za-z0-9「」《》]{2,18})[:：]\s*(.*)$", stripped)
            if not match or LINK_PATTERN.search(stripped):
                result.append(line)
                continue
            prefix, rest = match.group(1), match.group(2).strip()
            replacement = report_titles.get(prefix)
            if replacement:
                result.append(f"{replacement}{rest}".rstrip())
            elif not rest:
                result.append(f"{prefix}。")
            else:
                result.append(f"{prefix}，{rest}")
        return "\n".join(result)

    def _remove_mechanical_transitions(self, markdown: str) -> str:
        content = markdown
        content = re.sub(r"首先[，,、]?", "", content)
        content = re.sub(r"其次[，,、]?", "再往下看，", content)
        content = re.sub(r"最后[，,、]?", "收回来讲，", content)
        return content

    def _normalize_repeated_phrases(self, markdown: str) -> str:
        replacements = {
            "值得关注的是，值得关注的是，": "值得关注的是，",
            "这条消息的核心是": "这条消息最核心的变化是",
            "从新闻看，": "",
            "从报道看，": "",
        }
        content = markdown
        for old, new in replacements.items():
            content = content.replace(old, new)
        return content

    def _format_link_blocks(self, markdown: str) -> str:
        formatted: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("原文链接：", "原文链接:", "来源链接：", "来源链接:")):
                formatted.append(line)
                continue
            label = "原文链接" if stripped.startswith("原文链接") else "来源链接"
            links_text = re.sub(r"^(原文链接|来源链接)[:：]\s*", "", stripped).strip()
            parts = [part.strip() for part in re.split(r"\s+\|\s+", links_text) if part.strip()]
            if len(parts) <= 1 and len(stripped) <= 160:
                formatted.append(line)
                continue
            formatted.append(f"{label}：{' | '.join(parts)}")
        return "\n".join(formatted)

    def _polish_with_llm(
        self,
        article: NewsArticle,
        quality_report: NewsArticleQualityReport,
        markdown: str,
    ) -> str | None:
        issue_payload = [
            {
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "description": issue.description,
                "suggestion": issue.suggestion,
            }
            for issue in quality_report.issues[:8]
        ]
        content = self.llm.chat(
            system_prompt=(
                "你是中文 AI 新闻公众号发布编辑。只做轻量润色，不新增事实，不删除原文链接。"
                "必须保留文章主标题和所有 URL，但要把二级标题、三级标题、编号列表、bullet 列表改成自然段落。"
                "最终 content_markdown 不得包含 ## 或 ###，不得包含大段 Markdown 列表。"
                "必须删除点赞数、评论数、points、comments、评论区炸了、很多人讨论、大家都在讨论、开发者普遍认为等互动数量或无支撑社区共识表述。"
                "如果句子核心依赖互动数量，就整句删除；如果只是修饰语，删掉修饰语并保留事实。"
                "降低 AI 报告腔，增强读者视角和可读性。输出严格 JSON：content_markdown、notes。"
            ),
            user_prompt=(
                "请根据质量问题轻量润色下面的单篇 AI 新闻文章。不要删 URL，不要新增数据、人物表态、模型能力结论或官方态度。\n\n"
                f"质量问题：\n{json.dumps(issue_payload, ensure_ascii=False, indent=2)}\n\n"
                f"原文：\n{markdown}"
            ),
            temperature=0.25,
        )
        if content.startswith(LLMService.WARNING_PREFIX):
            self.warnings.append(content.replace(LLMService.WARNING_PREFIX, "").strip())
            return None
        try:
            payload = self._parse_llm_json(content)
        except ValueError as exc:
            self.warnings.append(f"LLM polish JSON parse failed: {exc}")
            return None
        polished = str(payload.get("content_markdown") or "").strip()
        if not polished:
            return None
        if not polished.startswith("# "):
            polished = f"# {article.title}\n\n{polished}"
        polished = self._heuristic_polish(polished)
        return polished.rstrip() + "\n"

    def _parse_llm_json(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("response did not contain a JSON object")
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("response JSON must be an object")
        return payload

    def _keeps_links(self, markdown: str, urls: list[str]) -> bool:
        return all(url in markdown for url in urls if url)

    def _publish_markdown(self, article: NewsArticle) -> str:
        markdown = (article.content_markdown or "").strip()
        urls = _unique(article.source_urls or LINK_PATTERN.findall(markdown))
        if urls and not any(url in markdown for url in urls):
            markdown = markdown.rstrip() + "\n\n" + f"原文链接：{' | '.join(urls)}"
        markdown = self._heuristic_polish(markdown)
        return self._with_cover_header(article, markdown)

    def _package_markdown(
        self,
        article: NewsArticle,
        quality_report: NewsArticleQualityReport,
        publish_markdown: str,
    ) -> str:
        header = [
            "<!-- AI 新闻文章发布包 -->",
            f"<!-- article_id: {article.article_id or '-'} -->",
            f"<!-- quality_score: {quality_report.total_score:.1f} -->",
            f"<!-- publish_ready: {'true' if quality_report.publish_ready else 'false'} -->",
            f"<!-- cover_image_status: {article.cover_image_status or 'missing'} -->",
            f"<!-- cover_image_url: {article.cover_image_url or 'null'} -->",
            f"<!-- cover_image_source_url: {article.cover_image_source_url or 'null'} -->",
            f"<!-- cover_image_alt: {article.cover_image_alt or '-'} -->",
        ]
        if quality_report.summary:
            header.append(f"<!-- review_summary: {quality_report.summary} -->")
        return "\n".join(header) + "\n\n" + publish_markdown.rstrip() + "\n"

    def _with_cover_header(self, article: NewsArticle, markdown: str) -> str:
        body = (markdown or "").strip()
        body = re.sub(r"^<!-- AI 新闻文章封面图 -->\s*(?:<!-- .*? -->\s*){0,8}", "", body, flags=re.DOTALL)
        header = [
            "<!-- AI 新闻文章封面图 -->",
            f"<!-- cover_image_status: {article.cover_image_status or 'missing'} -->",
            f"<!-- cover_image_url: {article.cover_image_url or 'null'} -->",
            f"<!-- cover_image_source_url: {article.cover_image_source_url or 'null'} -->",
            f"<!-- cover_image_alt: {article.cover_image_alt or '-'} -->",
        ]
        return "\n".join(header) + "\n\n" + body.rstrip() + "\n"

    def _word_count(self, markdown: str) -> int:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", markdown or ""))
        words = len(re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", markdown or ""))
        return chinese_chars + words

    def _article_date(self, article: NewsArticle) -> str:
        if article.generated_at:
            try:
                return datetime.fromisoformat(article.generated_at.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return article.generated_at[:10]
        return datetime.now().date().isoformat()

    def _relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            return path.as_posix()
