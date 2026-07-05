from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse
from typing import Any

from .models import ArticlePackage, FinalArticle, RepoResearchNote, VisualAsset


class VisualPlannerService:
    """Plans publication visuals for final articles without generating files."""

    def __init__(self) -> None:
        pass

    def plan_assets(
        self,
        final_article: FinalArticle,
        note: RepoResearchNote | None,
        content_plan: dict | None,
    ) -> list[VisualAsset]:
        full_name = final_article.full_name
        safe_name = full_name.replace("/", "__")
        readme_images = note.readme_images if note else []
        selected_images = self._select_readme_images(
            images=readme_images,
            full_name=full_name,
            default_branch=self._default_branch(note, content_plan),
        )

        if selected_images:
            return [
                VisualAsset(
                    full_name=full_name,
                    asset_id=f"{safe_name}_readme_image_{index}",
                    asset_type="readme_image",
                    title="README 项目图片",
                    description="来自项目 README 的已有图片。",
                    source_url=image_url,
                    format=self._image_format(image_url),
                    status="planned",
                )
                for index, image_url in enumerate(selected_images, start=1)
            ]

        return [
            VisualAsset(
                full_name=full_name,
                asset_id=f"{safe_name}_github_readme_screenshot",
                asset_type="github_readme_screenshot",
                title="GitHub README 页面截图",
                description="README 未发现合适图片时，截取真实 GitHub README 页面作为配图。",
                source_url=f"https://github.com/{full_name}#readme",
                output_path=f"assets/{safe_name}/github_readme_screenshot.png",
                format="png",
                status="planned",
            ),
            VisualAsset(
                full_name=full_name,
                asset_id=f"{safe_name}_github_repo_screenshot",
                asset_type="github_repo_screenshot",
                title="GitHub 仓库首页截图",
                description="GitHub README 页面截图失败时，截取真实 GitHub 仓库首页作为 fallback 配图。",
                source_url=f"https://github.com/{full_name}",
                output_path=f"assets/{safe_name}/github_repo_screenshot.png",
                format="png",
                status="planned",
            ),
        ]

    def plan_many(
        self,
        final_articles: list[FinalArticle],
        notes: list[RepoResearchNote] | dict[str, RepoResearchNote] | None,
        content_plans: list[dict] | dict[str, dict] | None,
    ) -> list[ArticlePackage]:
        notes_by_name = self._by_full_name(notes)
        plans_by_name = self._by_full_name(content_plans)
        packages: list[ArticlePackage] = []
        for article in final_articles:
            safe_name = article.full_name.replace("/", "__")
            package_dir = f"outputs/{{date}}/assets/{safe_name}"
            article_path = f"outputs/{{date}}/final_articles/{safe_name}.md"
            packaged_article_path = f"{package_dir}/packaged_article.md"
            note = notes_by_name.get(article.full_name)
            plan = plans_by_name.get(article.full_name)
            assets = self.plan_assets(article, note, plan)
            notes = self._asset_source_notes(assets)
            packages.append(
                ArticlePackage(
                    full_name=article.full_name,
                    title=article.title,
                    article_path=article_path,
                    packaged_article_path=packaged_article_path,
                    assets=assets,
                    cover_prompt="",
                    package_dir=package_dir,
                    status="planned",
                    notes=notes,
                )
            )
        return packages

    def _asset_source_notes(self, assets: list[VisualAsset]) -> list[str]:
        if any(asset.asset_type == "readme_image" for asset in assets):
            return ["配图来源：README 图片。"]
        if any(asset.asset_type == "github_readme_screenshot" for asset in assets):
            return ["README 未发现合适图片，使用 GitHub README 页面截图。"]
        return ["截图失败，发布稿不插图。"]

    def _select_readme_images(self, images: list[str], full_name: str, default_branch: str) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        candidates: list[tuple[int, str]] = []
        for image in images:
            image_url = self._normalize_readme_image_url(image, full_name, default_branch)
            if not image_url or image_url in seen or self._is_excluded_image(image_url):
                continue
            seen.add(image_url)
            candidates.append((self._image_priority(image_url), image_url))
        for _, image_url in sorted(candidates, key=lambda item: item[0]):
            selected.append(image_url)
            if len(selected) >= 3:
                break
        return selected

    def _normalize_readme_image_url(self, url: str, full_name: str, default_branch: str) -> str | None:
        value = str(url or "").strip().strip("<>")
        if not value or value.startswith(("#", "mailto:", "javascript:", "data:")):
            return None
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
        path = value.split("#", 1)[0].split("?", 1)[0].lstrip("/")
        if not path or ".." in PurePosixPath(path).parts:
            return None
        branch = default_branch or "main"
        return f"https://raw.githubusercontent.com/{full_name}/{branch}/{path}"

    def _is_excluded_image(self, url: str) -> bool:
        lowered = url.lower()
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        query = parsed.query.lower()
        text = f"{host} {path} {query}"
        if any(domain in host for domain in ["shields.io", "badgen.net", "badge.fury.io", "img.shields.io"]):
            return True
        if any(domain in host for domain in ["api.star-history.com", "contrib.rocks"]):
            return True
        small_visual_terms = ["badge", "shield", "icon", "logo", "sponsor", "avatar"]
        if any(term in text for term in small_visual_terms):
            return True
        extension = self._image_extension(path)
        if extension == "svg":
            return True
        if extension in {"png", "jpg", "jpeg", "webp", "gif"}:
            return False
        if "github.com" in host and ("/assets/" in path or "/user-attachments/assets/" in path):
            return False
        return True

    def _image_priority(self, url: str) -> int:
        lowered = url.lower()
        score = 50
        if any(term in lowered for term in ["screenshot", "screen-shot", "demo", "preview", "showcase", "example"]):
            score -= 25
        if any(term in lowered for term in ["/docs/", "/demo", "/examples/", "/assets/", "/images/"]):
            score -= 10
        if "github.com" in lowered and ("/assets/" in lowered or "/user-attachments/assets/" in lowered):
            score -= 8
        if "raw.githubusercontent.com" in lowered:
            score -= 6
        if self._image_extension(urlparse(url).path.lower()) in {"png", "jpg", "jpeg", "webp", "gif"}:
            score -= 5
        return score

    def _image_format(self, url: str) -> str:
        extension = self._image_extension(urlparse(url).path.lower())
        return extension or "image"

    def _image_extension(self, path: str) -> str:
        suffix = PurePosixPath(path).suffix.lower().lstrip(".")
        return suffix if suffix in {"png", "jpg", "jpeg", "webp", "gif", "svg"} else ""

    def _default_branch(self, note: RepoResearchNote | None, content_plan: dict | None) -> str:
        for value in [
            self._field(note, "default_branch"),
            self._field(content_plan, "default_branch"),
            self._field(self._plan_section(content_plan, "repository"), "default_branch"),
        ]:
            if value:
                return str(value)
        return "main"

    def _project_name(
        self,
        final_article: FinalArticle,
        note: RepoResearchNote | None,
        content_plan: dict | None,
    ) -> str:
        appeal = self._plan_section(content_plan, "appeal")
        insight = self._plan_section(content_plan, "insight")
        for value in [
            self._field(appeal, "project_name"),
            self._field(insight, "project_name"),
            final_article.full_name.rsplit("/", 1)[-1],
            note.full_name.rsplit("/", 1)[-1] if note else "",
        ]:
            if value:
                return str(value)
        return final_article.full_name

    def _selling_points(
        self,
        final_article: FinalArticle,
        note: RepoResearchNote | None,
        content_plan: dict | None,
    ) -> list[str]:
        appeal = self._plan_section(content_plan, "appeal")
        items: list[str] = []
        for item in self._list_field(appeal, "feature_advantages"):
            feature = self._field(item, "feature")
            advantage = self._field(item, "advantage")
            reader_interest = self._field(item, "reader_interest")
            text = " / ".join(str(value) for value in [feature, advantage, reader_interest] if value)
            if text:
                items.append(text)
        items.extend(str(value) for value in self._list_field(appeal, "top_selling_points"))
        items.extend(final_article.top_selling_points_used)
        if note:
            items.extend(note.readme_key_points[:3])
        if final_article.summary:
            items.append(final_article.summary)
        return self._clean_list(items, fallback=["降低使用门槛", "聚合关键能力", "适合快速试用"])

    def _scenarios(
        self,
        final_article: FinalArticle,
        note: RepoResearchNote | None,
        content_plan: dict | None,
    ) -> list[str]:
        appeal = self._plan_section(content_plan, "appeal")
        insight = self._plan_section(content_plan, "insight")
        items: list[str] = []
        items.extend(str(value) for value in self._list_field(appeal, "practical_scenarios"))
        items.extend(str(value) for value in self._list_field(insight, "use_cases"))
        items.extend(final_article.practical_scenarios_used)
        if note:
            items.extend(note.tool_use_cases)
        return self._clean_list(items, fallback=["个人开发者试用", "团队内部工具评估", "AI 应用原型验证"])

    def _cover_prompt(
        self,
        final_article: FinalArticle,
        project_name: str,
        selling_points: list[str],
        scenarios: list[str],
    ) -> str:
        if final_article.cover_prompt:
            return final_article.cover_prompt
        point = selling_points[0] if selling_points else "开源 AI 工具"
        scenario = scenarios[0] if scenarios else "开发者工作流"
        return (
            f"公众号封面图，主题是开源项目 {project_name}，突出“{point}”，"
            f"画面呈现 {scenario} 的真实工具使用感；白色或浅色背景，蓝色科技主色，"
            "清晰标题留白，现代产品截图感，不要夸张科幻，不要出现虚假 Logo。"
        )

    def _plan_section(self, content_plan: dict | None, name: str) -> Any:
        if not isinstance(content_plan, dict):
            return None
        return content_plan.get(name)

    def _field(self, value: Any, name: str) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    def _list_field(self, value: Any, name: str) -> list[Any]:
        field_value = self._field(value, name)
        return field_value if isinstance(field_value, list) else []

    def _clean_list(self, values: list[str], fallback: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = " ".join(str(value).split())
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
            if len(result) >= 6:
                break
        return result or fallback

    def _by_full_name(self, values: Any) -> dict[str, Any]:
        if isinstance(values, dict):
            return values
        result: dict[str, Any] = {}
        if not isinstance(values, list):
            return result
        for value in values:
            full_name = self._field(value, "full_name")
            if full_name:
                result[str(full_name)] = value
        return result
