from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.llm_service import LLMService
from src.models import NewsDigestArticle, NewsDigestQualityReport


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


class NewsDigestPolisherService:
    """Lightly polish and package an AI news digest without changing facts."""

    RULE_REPLACEMENTS = [
        ("本文将从以下几个方面", ""),
        ("本文将", ""),
        ("综上所述，", ""),
        ("综上，", ""),
        ("根据新闻，", ""),
        ("根据新闻", ""),
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
        article: NewsDigestArticle,
        quality_report: NewsDigestQualityReport,
    ) -> NewsDigestArticle:
        if quality_report.total_score >= 92 and quality_report.publish_ready:
            return self._with_quality(article, quality_report, polished=False)

        original_markdown = article.content_markdown or ""
        original_urls = _unique(article.source_urls or LINK_PATTERN.findall(original_markdown))
        heuristic_markdown = self._heuristic_polish(original_markdown)
        if self.llm.is_available() and quality_report.issues:
            llm_markdown = self._polish_with_llm(article, quality_report, heuristic_markdown)
            if llm_markdown and self._keeps_links(llm_markdown, original_urls):
                self.used_llm = True
                heuristic_markdown = llm_markdown
            elif llm_markdown:
                self.warnings.append("LLM polish was rejected because it dropped source links.")

        if not self._keeps_links(heuristic_markdown, original_urls):
            self.warnings.append("Heuristic polish was reverted because it dropped source links.")
            heuristic_markdown = original_markdown

        changed = heuristic_markdown.strip() != original_markdown.strip()
        return _model_copy(
            article,
            update={
                "content_markdown": heuristic_markdown.rstrip() + "\n",
                "word_count": self._word_count(heuristic_markdown),
                "polished": changed,
                "quality_report": quality_report,
                "quality_score": quality_report.total_score,
                "publish_ready": quality_report.publish_ready,
                "warnings": _unique([*(article.warnings or []), *self.warnings]),
            },
        )

    def attach_quality(
        self,
        article: NewsDigestArticle,
        quality_report: NewsDigestQualityReport,
    ) -> NewsDigestArticle:
        return self._with_quality(article, quality_report, polished=False)

    def save_article(self, article: NewsDigestArticle) -> None:
        generated_date = article.date or datetime.now().date().isoformat()
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_date_dir = self.output_dir / generated_date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_date_dir.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_model_dump(article), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_digest_latest.json").write_text(payload, encoding="utf-8")
        (news_dir / f"{generated_date}-news-digest.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_digest_latest.json").write_text(payload, encoding="utf-8")
        (output_date_dir / "ai_news_digest.md").write_text(article.content_markdown.rstrip() + "\n", encoding="utf-8")

    def generate_package(
        self,
        article: NewsDigestArticle,
        quality_report: NewsDigestQualityReport,
    ) -> NewsDigestArticle:
        generated_date = article.date or datetime.now().date().isoformat()
        package_dir = self.output_dir / generated_date / "news_digest_package"
        package_dir.mkdir(parents=True, exist_ok=True)
        package_path = package_dir / "packaged_ai_news_digest.md"
        assets_path = package_dir / "assets.json"

        package_markdown = self._package_markdown(article)
        package_path.write_text(package_markdown.rstrip() + "\n", encoding="utf-8")
        assets = {
            "type": "ai_news_digest_package",
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "title": article.title,
            "date": article.date,
            "asset_count": 0,
            "assets": [],
            "source_urls": article.source_urls,
            "quality_score": quality_report.total_score,
            "publish_ready": quality_report.publish_ready,
            "packaged_markdown_path": self._relative_path(package_path),
        }
        assets_path.write_text(json.dumps(assets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return _model_copy(article, update={"package_path": self._relative_path(package_path)})

    def _with_quality(
        self,
        article: NewsDigestArticle,
        quality_report: NewsDigestQualityReport,
        polished: bool,
    ) -> NewsDigestArticle:
        return _model_copy(
            article,
            update={
                "quality_report": quality_report,
                "quality_score": quality_report.total_score,
                "publish_ready": quality_report.publish_ready,
                "polished": polished,
            },
        )

    def _heuristic_polish(self, markdown: str) -> str:
        content = markdown.strip()
        for old, new in self.RULE_REPLACEMENTS:
            content = content.replace(old, new)
        content = self._move_supplemental_links(content)
        content = self._format_link_blocks(content)
        content = self._normalize_repeated_starts(content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r"[ \t]+\n", "\n", content)
        content = re.sub(r"([。！？])\s+([^\n#>-])", r"\1\n\n\2", content)
        return content.strip() + "\n"

    def _normalize_repeated_starts(self, markdown: str) -> str:
        replacements = {
            "值得关注的是，值得关注的是，": "值得关注的是，",
            "这条消息的核心是": "这条消息最核心的变化是",
            "从事件卡片看，": "",
        }
        content = markdown
        for old, new in replacements.items():
            content = content.replace(old, new)
        return content

    def _move_supplemental_links(self, markdown: str) -> str:
        lines = markdown.splitlines()
        kept: list[str] = []
        supplemental: list[str] = []
        in_supplement = False
        for line in lines:
            stripped = line.strip()
            if stripped == "### 补充原文链接":
                in_supplement = True
                continue
            if in_supplement and stripped.startswith("#"):
                in_supplement = False
            if in_supplement:
                supplemental.extend(LINK_PATTERN.findall(line))
                continue
            kept.append(line)

        supplemental = _unique(supplemental)
        if not supplemental:
            return "\n".join(kept)

        insert_at = -1
        for index, line in enumerate(kept):
            if line.strip().startswith("原文链接"):
                insert_at = index + 1
                break
        if insert_at < 0:
            for index, line in enumerate(kept):
                if line.startswith("### "):
                    insert_at = index + 1
                    break
        if insert_at < 0:
            insert_at = len(kept)

        block = ["", "延伸来源：", *[f"- {url}" for url in supplemental], ""]
        return "\n".join([*kept[:insert_at], *block, *kept[insert_at:]])

    def _format_link_blocks(self, markdown: str) -> str:
        formatted: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("原文链接：", "原文链接:", "延伸来源：", "延伸来源:")):
                formatted.append(line)
                continue
            label = "原文链接" if stripped.startswith("原文链接") else "延伸来源"
            links_text = re.sub(r"^(原文链接|延伸来源)[:：]\s*", "", stripped).strip()
            parts = [part.strip() for part in re.split(r"\s+\|\s+", links_text) if part.strip()]
            if len(parts) <= 1 and len(stripped) <= 160:
                formatted.append(line)
                continue
            formatted.append(f"{label}：")
            formatted.extend(f"- {part}" for part in parts)
        return "\n".join(formatted)

    def _polish_with_llm(
        self,
        article: NewsDigestArticle,
        quality_report: NewsDigestQualityReport,
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
                "你是中文 AI 新闻日报发布编辑。只做轻量润色，不改事实、不新增未给出的事实。"
                "必须保留原有 Markdown 栏目结构、所有原文 URL、标题层级和每条新闻对应链接。"
                "降低报告腔，补强为什么值得关注，但不要把链接集中到文末。"
                "输出严格 JSON：content_markdown、notes。"
            ),
            user_prompt=(
                "请根据质量问题轻量润色下面的 AI 日报。不要改日期，不要删 URL。\n\n"
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

    def _package_markdown(self, article: NewsDigestArticle) -> str:
        markdown = article.content_markdown.strip()
        quality = article.quality_report
        header = [
            "<!-- AI 新闻日报发布包 -->",
            f"<!-- quality_score: {article.quality_score:.1f} -->",
            f"<!-- publish_ready: {'true' if article.publish_ready else 'false'} -->",
        ]
        if quality and quality.summary:
            header.append(f"<!-- review_summary: {quality.summary} -->")
        return "\n".join(header) + "\n\n" + markdown + "\n"

    def _word_count(self, markdown: str) -> int:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", markdown or ""))
        words = len(re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", markdown or ""))
        return chinese_chars + words

    def _relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            return path.as_posix()
