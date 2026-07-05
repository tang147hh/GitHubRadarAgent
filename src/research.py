from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from .github_client import GitHubClient
from .models import AuthorProfile, ProjectLinks, RepoCandidate, RepoResearchNote


class RepoResearchService:
    """Fetch repository details and build deterministic research notes."""

    REFERENCE_DATE = datetime(2026, 7, 1, tzinfo=timezone.utc)
    KEYWORDS = [
        "agent",
        "agents",
        "llm",
        "mcp",
        "rag",
        "workflow",
        "automation",
        "openai",
        "langchain",
        "model",
        "deploy",
        "quickstart",
        "install",
        "usage",
        "feature",
    ]

    def __init__(self, github_client: GitHubClient) -> None:
        self.github_client = github_client

    def research_repo(self, candidate: RepoCandidate) -> RepoResearchNote:
        repository, repository_error = self._fetch_repository(candidate)
        readme, readme_error = self._fetch_readme(candidate.full_name)
        releases, releases_error = self._fetch_releases(candidate.full_name)
        open_issues, issues_error = self._fetch_open_issues(candidate.full_name)
        author_profile, author_error = self._fetch_owner_profile(repository.owner or candidate.owner)

        fetch_errors = [
            error
            for error in [repository_error, readme_error, releases_error, issues_error, author_error]
            if error
        ]
        summary = "未找到 README"
        key_points: list[str] = []
        risks: list[str] = fetch_errors
        readme_text = readme or ""

        if readme is None:
            risks.append("缺少 README，调研信息有限")
        else:
            readme_excerpt = readme[:8000]
            summary = self._summarize_readme(readme_excerpt)
            key_points = self._extract_key_points(readme_excerpt)
            if len(self._clean_markdown(readme_excerpt)) < 500:
                risks.append("README 内容较短，项目说明可能不充分")

        risks.extend(self._detect_risks(repository, readme, open_issues))
        project_links = self._extract_project_links(repository, readme_text)
        project_kind = self.classify_project_kind(repository, readme_text)
        tool_use_cases = self._extract_tool_use_cases(repository, readme_text, project_kind)
        source_links = self._build_source_links(repository, releases, open_issues, author_profile, project_links)

        return RepoResearchNote(
            full_name=repository.full_name,
            html_url=repository.html_url,
            description=repository.description,
            stars=repository.stars,
            forks=repository.forks,
            language=repository.language,
            topics=repository.topics,
            license_name=repository.license_name,
            pushed_at=repository.pushed_at,
            readme_summary=summary,
            readme_key_points=key_points,
            releases=releases,
            open_issues=open_issues,
            source_links=source_links,
            risks=self._dedupe(risks),
            author_profile=author_profile,
            project_links=project_links,
            readme_images=project_links.images if project_links else [],
            readme_links=self._dedupe(self._readme_absolute_links(readme_text))[:30],
            tool_use_cases=tool_use_cases,
            project_kind=project_kind,
        )

    def research_top_repos(self, candidates: list[RepoCandidate], top: int = 3) -> list[RepoResearchNote]:
        notes: list[RepoResearchNote] = []
        for candidate in candidates[: max(0, top)]:
            notes.append(self.research_repo(candidate))
        return notes

    def research_selected_repos(self, candidates: list[RepoCandidate]) -> list[RepoResearchNote]:
        notes: list[RepoResearchNote] = []
        for candidate in candidates:
            notes.append(self.research_repo(candidate))
        return notes

    def research_by_full_name(self, owner: str, repo: str) -> RepoResearchNote:
        full_name = f"{owner}/{repo}"
        try:
            repository = self.github_client.get_repository(full_name)
        except RuntimeError as exc:
            raise RuntimeError(f"指定项目元信息拉取失败：{full_name}。{exc}") from exc
        return self.research_repo(repository)

    def _fetch_repository(self, candidate: RepoCandidate) -> tuple[RepoCandidate, Optional[str]]:
        try:
            return self.github_client.get_repository(candidate.full_name), None
        except RuntimeError as exc:
            return candidate, f"仓库元信息拉取失败，已使用评分快照数据：{self._truncate(str(exc), 240)}"

    def _fetch_readme(self, full_name: str) -> tuple[Optional[str], Optional[str]]:
        try:
            return self.github_client.get_readme(full_name), None
        except RuntimeError as exc:
            return None, f"README 拉取失败：{self._truncate(str(exc), 240)}"

    def _fetch_releases(self, full_name: str) -> tuple[list[dict], Optional[str]]:
        try:
            return self.github_client.get_releases(full_name, limit=3), None
        except RuntimeError as exc:
            return [], f"Releases 拉取失败：{self._truncate(str(exc), 240)}"

    def _fetch_open_issues(self, full_name: str) -> tuple[list[dict], Optional[str]]:
        try:
            return self.github_client.get_open_issues(full_name, limit=5), None
        except RuntimeError as exc:
            return [], f"Open issues 拉取失败：{self._truncate(str(exc), 240)}"

    def _fetch_owner_profile(self, owner: str) -> tuple[Optional[AuthorProfile], Optional[str]]:
        if not owner:
            return None, "作者/组织资料拉取失败：缺少 owner"
        try:
            payload = self.github_client.get_owner_profile(owner)
        except RuntimeError as exc:
            return None, f"作者/组织资料拉取失败：{self._truncate(str(exc), 240)}"
        if payload is None:
            return None, None
        return (
            AuthorProfile(
                login=payload.get("login") or owner,
                type=payload.get("type"),
                name=payload.get("name"),
                html_url=payload.get("html_url") or f"https://github.com/{owner}",
                avatar_url=payload.get("avatar_url"),
                bio=payload.get("bio"),
                company=payload.get("company"),
                blog=payload.get("blog"),
                location=payload.get("location"),
                twitter_username=payload.get("twitter_username"),
                public_repos=payload.get("public_repos"),
                followers=payload.get("followers"),
                created_at=payload.get("created_at"),
                source="github_users_api",
            ),
            None,
        )

    def _summarize_readme(self, readme: str) -> str:
        paragraphs = [
            self._clean_markdown(paragraph)
            for paragraph in re.split(r"\n\s*\n", readme)
        ]
        paragraphs = [
            paragraph
            for paragraph in paragraphs
            if paragraph and not self._is_noise_paragraph(paragraph)
        ]

        summary_parts: list[str] = []
        for paragraph in paragraphs:
            if len(" ".join(summary_parts + [paragraph])) > 500:
                break
            summary_parts.append(paragraph)
            if len(summary_parts) >= 3:
                break

        summary = "\n\n".join(summary_parts).strip()
        if not summary:
            summary = self._clean_markdown(readme)[:500].strip()
        if len(summary) > 500:
            summary = f"{summary[:500].rstrip()}..."
        return summary or "README 内容为空"

    def _extract_key_points(self, readme: str) -> list[str]:
        points: list[str] = []
        for raw_line in readme.splitlines():
            line = raw_line.strip()
            if not line or self._is_noise_line(line):
                continue

            cleaned = self._clean_markdown(line)
            if not cleaned or len(cleaned) < 8:
                continue

            is_heading = line.startswith("#")
            is_list_item = bool(re.match(r"^[-*+]\s+", line) or re.match(r"^\d+\.\s+", line))
            has_keyword = any(keyword in cleaned.lower() for keyword in self.KEYWORDS)

            if is_heading or is_list_item or has_keyword:
                points.append(self._truncate(cleaned, 160))

            if len(points) >= 8:
                break

        return self._dedupe(points)[:8]

    def _detect_risks(
        self,
        repository: RepoCandidate,
        readme: Optional[str],
        open_issues: list[dict],
    ) -> list[str]:
        risks: list[str] = []

        if not repository.license_name:
            risks.append("缺少 license，商用或二次分发前需进一步确认授权")
        if not readme:
            risks.append("README 不存在或无法通过 API 获取")
        if not (repository.description or "").strip():
            risks.append("description 为空，对外定位不够清晰")

        pushed_at = self._parse_github_datetime(repository.pushed_at)
        if pushed_at is None:
            risks.append("缺少最近更新时间信息")
        else:
            days_since_push = (self.REFERENCE_DATE - pushed_at).days
            if days_since_push > 180:
                risks.append(f"最近 {days_since_push} 天未更新，维护活跃度需关注")

        open_issues_count = repository.open_issues or len(open_issues)
        if open_issues_count >= 1000:
            risks.append(f"open issues 数量较高（约 {open_issues_count} 个）")
        elif open_issues_count >= 300:
            risks.append(f"open issues 偏多（约 {open_issues_count} 个）")

        return risks

    def _build_source_links(
        self,
        repository: RepoCandidate,
        releases: list[dict],
        open_issues: list[dict],
        author_profile: Optional[AuthorProfile] = None,
        project_links: Optional[ProjectLinks] = None,
    ) -> list[str]:
        links = [repository.html_url]
        if repository.homepage:
            links.append(repository.homepage)
        if author_profile:
            links.append(author_profile.html_url)
        if project_links:
            links.extend(project_links.documentation[:5])
            links.extend(project_links.demo[:5])
        if releases:
            links.append(f"{repository.html_url}/releases")
        if open_issues:
            links.append(f"{repository.html_url}/issues")
        return self._dedupe([link for link in links if link])

    def _extract_project_links(self, repository: RepoCandidate, readme: str) -> ProjectLinks:
        markdown_links = self._markdown_links(readme)
        markdown_images = self._markdown_images(readme)
        html_images = self._html_images(readme)
        naked_urls = [(url, url) for url in self._naked_urls(readme)]

        links = ProjectLinks(homepage=self._normalize_absolute_url(repository.homepage))
        image_urls = [
            self._resolve_readme_asset_url(url, repository)
            for _, url in [*markdown_images, *html_images]
        ]
        image_urls = [url for url in image_urls if url]

        all_link_pairs = []
        for text, url in [*markdown_links, *naked_urls]:
            normalized = self._normalize_absolute_url(url)
            if normalized:
                all_link_pairs.append((text, normalized))

        if links.homepage:
            links.website.append(links.homepage)

        for text, url in all_link_pairs:
            haystack = f"{text} {url}".lower()
            if self._is_badge_link(haystack):
                links.badges.append(url)
            elif self._is_video_link(haystack):
                links.videos.append(url)
            elif self._is_documentation_link(haystack):
                links.documentation.append(url)
            elif self._is_demo_link(haystack):
                links.demo.append(url)
            elif self._is_examples_link(haystack):
                links.examples.append(url)
            elif self._is_image_link(haystack):
                links.images.append(url)
            elif self._is_website_link(url, repository):
                links.website.append(url)

        for url in image_urls:
            haystack = url.lower()
            if self._is_badge_link(haystack):
                links.badges.append(url)
            else:
                links.images.append(url)

        links.documentation = self._dedupe(links.documentation)[:10]
        links.demo = self._dedupe(links.demo)[:10]
        links.examples = self._dedupe(links.examples)[:10]
        links.website = self._dedupe(links.website)[:10]
        links.images = self._dedupe(links.images)[:10]
        links.videos = self._dedupe(links.videos)[:10]
        links.badges = self._dedupe(links.badges)[:10]
        return links

    def classify_project_kind(self, repository: RepoCandidate, readme: str) -> str:
        text = " ".join(
            [
                repository.full_name,
                repository.description or "",
                repository.language or "",
                " ".join(repository.topics or []),
                self._clean_markdown(readme[:12000]),
            ]
        ).lower()
        topics_text = " ".join(repository.topics or []).lower()

        if self._contains_any(text, ["agent", "llm", "rag", "mcp", "openai", "langchain"]):
            return "ai_agent"
        if self._contains_any(text, ["cli", "terminal", "command line", "command-line", "shell"]):
            return "cli_tool"
        if self._contains_any(
            text,
            ["developer tool", "developer-tools", "devtool", "devtools", "debug", "testing", "lint", "formatter", "sdk", "api"],
        ):
            return "developer_tool"
        if self._contains_any(
            text,
            ["productivity", "note", "todo", "automation", "workflow", "obsidian", "notion"],
        ):
            return "productivity_tool"
        if self._contains_any(text, ["self-hosted", "self hosted", "docker compose", "deploy", "server"]):
            return "self_hosted"
        if repository.language and self._contains_any(text + " " + topics_text, ["framework", "library", "sdk"]):
            return "library_framework"
        return "unknown"

    def _extract_tool_use_cases(self, repository: RepoCandidate, readme: str, project_kind: str) -> list[str]:
        candidates: list[str] = []
        use_case_keywords = [
            "use case",
            "usage",
            "examples",
            "features",
            "quickstart",
            "getting started",
            "workflow",
            "automation",
            "cli",
            "terminal",
            "self-hosted",
            "docker",
            "extension",
        ]
        for raw_line in readme.splitlines():
            line = self._clean_markdown(raw_line)
            if len(line) < 12 or len(line) > 180:
                continue
            lowered = line.lower()
            if any(keyword in lowered for keyword in use_case_keywords):
                candidates.append(line)
            if len(candidates) >= 8:
                break

        fallback_by_kind = {
            "cli_tool": ["适合在终端中完成重复性操作、脚本化任务或本地开发辅助。"],
            "developer_tool": ["适合开发者在调试、测试、格式化、API 集成或工程效率场景中试用。"],
            "productivity_tool": ["适合用于笔记、待办、自动化流程或个人/团队效率工作流。"],
            "self_hosted": ["适合希望自行部署、掌控数据和服务运行环境的团队继续调研。"],
            "library_framework": ["适合作为工程依赖、二次开发基础或同类框架选型参考。"],
            "ai_agent": ["适合 AI Agent、LLM 应用、RAG 或工作流编排方向的开发者继续验证。"],
        }
        candidates.extend(fallback_by_kind.get(project_kind, []))
        if repository.description:
            candidates.append(f"可围绕项目描述中的场景评估：{repository.description}")
        return self._dedupe([self._truncate(item, 160) for item in candidates])[:6]

    def _markdown_links(self, readme: str) -> list[tuple[str, str]]:
        pattern = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
        return [(text.strip(), url.strip("<> \t")) for text, url in pattern.findall(readme)]

    def _markdown_images(self, readme: str) -> list[tuple[str, str]]:
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
        return [(alt.strip(), url.strip("<> \t")) for alt, url in pattern.findall(readme)]

    def _html_images(self, readme: str) -> list[tuple[str, str]]:
        pattern = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", flags=re.I)
        return [("html img", url.strip()) for url in pattern.findall(readme)]

    def _naked_urls(self, readme: str) -> list[str]:
        urls = re.findall(r"https?://[^\s<>)\"'\]]+", readme)
        return [url.rstrip(".,;:!?") for url in urls]

    def _readme_absolute_links(self, readme: str) -> list[str]:
        links = [
            self._normalize_absolute_url(url)
            for _, url in [*self._markdown_links(readme), *[(url, url) for url in self._naked_urls(readme)]]
        ]
        return [link for link in links if link]

    def _resolve_readme_asset_url(self, url: str, repository: RepoCandidate) -> Optional[str]:
        absolute = self._normalize_absolute_url(url)
        if absolute:
            return absolute
        if not url or url.startswith(("#", "mailto:", "javascript:")):
            return None
        default_branch = repository.default_branch or "main"
        path = url.split("#", 1)[0].split("?", 1)[0].lstrip("/")
        if not path:
            return None
        return f"https://raw.githubusercontent.com/{repository.full_name}/{default_branch}/{path}"

    def _normalize_absolute_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        value = url.strip().strip("<>").rstrip(".,;:!?")
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
        return None

    def _is_documentation_link(self, value: str) -> bool:
        return self._contains_any(value, ["docs", "documentation", "guide", "quickstart", "getting-started", "manual"])

    def _is_demo_link(self, value: str) -> bool:
        return self._contains_any(value, ["demo", "playground", "example app", "live", "preview", "try"])

    def _is_examples_link(self, value: str) -> bool:
        return self._contains_any(value, ["examples", "sample", "template", "starter"])

    def _is_image_link(self, value: str) -> bool:
        return self._contains_any(value, ["user-images", "raw.githubusercontent.com", "/assets/", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"])

    def _is_video_link(self, value: str) -> bool:
        return self._contains_any(value, ["youtube", "youtu.be", "bilibili", "loom", "video", ".mp4", ".webm"])

    def _is_badge_link(self, value: str) -> bool:
        return self._contains_any(value, ["shields.io", "badge"])

    def _is_website_link(self, url: str, repository: RepoCandidate) -> bool:
        parsed = urlparse(url)
        if not parsed.netloc:
            return False
        repo_host = urlparse(repository.html_url).netloc
        return parsed.netloc != repo_host or "github.io" in parsed.netloc

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in keywords)

    def _clean_markdown(self, value: str) -> str:
        text = value.strip()
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^[-*+]\s+", "", text)
        text = re.sub(r"^\d+\.\s+", "", text)
        text = re.sub(r"[*_~>|]", "", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _is_noise_line(self, line: str) -> bool:
        lowered = line.lower()
        return (
            line.startswith("[!")
            or line.startswith("<!--")
            or lowered.startswith("<p align=")
            or lowered.startswith("<div align=")
            or lowered.startswith("<img ")
            or lowered.startswith("<a ")
        )

    def _is_noise_paragraph(self, paragraph: str) -> bool:
        lowered = paragraph.lower()
        return (
            len(paragraph) < 20
            or lowered.startswith("badge")
            or "shields.io" in lowered
            or paragraph.count("http") >= 3
        )

    def _parse_github_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _truncate(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit].rstrip()}..."

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result
