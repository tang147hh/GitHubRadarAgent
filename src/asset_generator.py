from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import ArticlePackage, FinalArticle, RepoResearchNote, VisualAsset
from .screenshot_service import ScreenshotService


class AssetGeneratorService:
    """Generates article package metadata and Markdown using project-owned visuals."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.screenshot_service = ScreenshotService(project_root=self.project_root)

    def generate_package(
        self,
        article_package: ArticlePackage,
        final_article: FinalArticle,
        note: RepoResearchNote | None,
        content_plan: dict | None,
        date: str,
        article_path_override: Path | str | None = None,
    ) -> ArticlePackage:
        safe_name = final_article.full_name.replace("/", "__")
        output_dir = self.project_root / "outputs" / date
        package_dir = output_dir / "assets" / safe_name
        package_dir.mkdir(parents=True, exist_ok=True)

        article_package.package_dir = str(package_dir)
        article_package.article_path = str(article_path_override or output_dir / "final_articles" / f"{safe_name}.md")
        article_package.packaged_article_path = str(package_dir / "packaged_article.md")
        assets = self._generate_assets(article_package.assets, final_article.full_name, safe_name, package_dir)
        article_package.notes = self._asset_notes(assets)

        packaged_path = package_dir / "packaged_article.md"
        packaged_path.write_text(
            self._package_markdown(final_article=final_article, assets=assets),
            encoding="utf-8",
        )
        article_package.packaged_article_path = str(packaged_path)
        article_package.assets = assets
        article_package.cover_prompt = ""
        article_package.status = "generated"

        assets_json_path = package_dir / "assets.json"
        assets_json_path.write_text(
            json.dumps(self._package_payload(article_package), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        article_package.notes.append(f"assets.json: {assets_json_path}")
        return article_package

    def generate_many(
        self,
        article_packages: list[ArticlePackage],
        final_articles: list[FinalArticle],
        notes: list[RepoResearchNote] | dict[str, RepoResearchNote] | None,
        content_plans: list[dict] | dict[str, dict] | None,
        date: str,
    ) -> list[ArticlePackage]:
        notes_by_name = self._by_full_name(notes)
        plans_by_name = self._by_full_name(content_plans)
        articles_by_name = {article.full_name: article for article in final_articles}
        generated: list[ArticlePackage] = []
        for article_package in article_packages:
            article = articles_by_name.get(article_package.full_name)
            if article is None:
                article_package.status = "skipped"
                article_package.notes.append("未找到对应终稿，已跳过。")
                generated.append(article_package)
                continue
            generated.append(
                self.generate_package(
                    article_package=article_package,
                    final_article=article,
                    note=notes_by_name.get(article.full_name),
                    content_plan=plans_by_name.get(article.full_name),
                    date=date,
                )
            )
        return generated

    def _package_markdown(self, final_article: FinalArticle, assets: list[VisualAsset]) -> str:
        readme_images = [
            asset for asset in assets
            if asset.asset_type == "readme_image" and asset.source_url and asset.status != "failed"
        ][:2]
        screenshot = next(
            (
                asset for asset in assets
                if asset.asset_type in {"github_readme_screenshot", "github_repo_screenshot"}
                and asset.output_path
                and asset.status == "generated"
            ),
            None,
        )
        if not readme_images and not screenshot:
            return final_article.content_markdown.strip() + "\n"

        content = self._strip_existing_packaged_images(final_article.content_markdown.strip())
        if not content:
            content = f"# {final_article.title}\n\n{final_article.summary}"
        if not content.lstrip().startswith("# "):
            content = f"# {final_article.title}\n\n{content}"

        lines = content.splitlines()
        if readme_images:
            image_refs = [
                f"![{alt}]({asset.source_url})"
                for asset, alt in zip(readme_images, ["项目截图", "项目界面"])
                if asset.source_url
            ]
        else:
            alt = "GitHub README 页面截图" if screenshot and screenshot.asset_type == "github_readme_screenshot" else "GitHub 仓库页面截图"
            image_refs = [f"![{alt}]({screenshot.output_path})"] if screenshot and screenshot.output_path else []
        if not image_refs:
            return content.strip() + "\n"
        title_index = next((index for index, line in enumerate(lines) if line.startswith("# ")), -1)
        if title_index >= 0:
            lines[title_index + 1:title_index + 1] = ["", image_refs[0]]
        else:
            lines[0:0] = [f"# {final_article.title}", "", image_refs[0], ""]

        if len(image_refs) > 1:
            insert_index = self._find_insert_index(lines, ["示例", "界面", "截图", "演示", "效果"], start=title_index + 3)
            if insert_index is None:
                insert_index = max(3, min(len(lines), len(lines) // 2))
            lines[insert_index:insert_index] = ["", image_refs[1], ""]

        return "\n".join(lines).strip() + "\n"

    def _strip_existing_packaged_images(self, content: str) -> str:
        patterns = [
            r"!\[GitHub README 页面截图\]\(assets/[^)]+/github_readme_screenshot\.png\)",
            r"!\[GitHub 仓库页面截图\]\(assets/[^)]+/github_repo_screenshot\.png\)",
            r"!\[项目 GitHub 页面\]\(assets/[^)]+/github_screenshot\.png\)",
            r"!\[项目亮点解释图\]\(assets/[^)]+/feature_diagram\.(?:png|svg)\)",
            r"!\[适合的使用场景\]\(assets/[^)]+/use_case_diagram\.(?:png|svg)\)",
            r"<!-- GitHub 截图待生成:[\s\S]*?-->",
        ]
        result = content
        for pattern in patterns:
            result = re.sub(pattern, "", result)
        return re.sub(r"\n{3,}", "\n\n", result).strip()

    def _find_insert_index(self, lines: list[str], keywords: list[str], start: int = 0) -> int | None:
        for index in range(max(0, start), len(lines)):
            line = lines[index].strip()
            if line.startswith("#") and any(keyword in line for keyword in keywords):
                return index + 1
        for index in range(max(0, start), len(lines)):
            line = lines[index].strip()
            if any(keyword in line for keyword in keywords):
                return index
        return None

    def _field(self, value: Any, name: str) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

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

    def _generate_assets(
        self,
        planned_assets: list[VisualAsset],
        full_name: str,
        safe_name: str,
        package_dir: Path,
    ) -> list[VisualAsset]:
        readme_assets = [
            asset for asset in planned_assets
            if asset.asset_type == "readme_image" and asset.source_url
        ]
        if readme_assets:
            for asset in readme_assets:
                asset.status = "generated"
                asset.error = None
            return readme_assets

        screenshot_assets = [
            asset for asset in planned_assets
            if asset.asset_type in {"github_readme_screenshot", "github_repo_screenshot"}
        ]
        generated = False
        for asset in screenshot_assets:
            filename = (
                "github_readme_screenshot.png"
                if asset.asset_type == "github_readme_screenshot"
                else "github_repo_screenshot.png"
            )
            relative_path = f"assets/{safe_name}/{filename}"
            output_path = package_dir / filename
            asset.output_path = relative_path
            asset.format = "png"
            if generated:
                asset.status = "skipped"
                asset.error = None
                continue

            if asset.asset_type == "github_readme_screenshot":
                result = self.screenshot_service.capture_github_readme(full_name, output_path)
            else:
                result = self.screenshot_service.capture_github_repo(full_name, output_path)
            asset.source_url = result.source_url
            if result.ok:
                asset.status = "generated"
                asset.error = None
                asset.output_path = relative_path
                generated = True
            else:
                asset.status = "failed"
                asset.error = result.error or "截图失败。"
        return screenshot_assets

    def _asset_notes(self, assets: list[VisualAsset]) -> list[str]:
        if any(asset.asset_type == "readme_image" and asset.status != "failed" for asset in assets):
            return ["配图来源：README 图片。"]
        if any(asset.asset_type == "github_readme_screenshot" and asset.status == "generated" for asset in assets):
            return ["README 未发现合适图片，使用 GitHub README 页面截图。"]
        if any(asset.asset_type == "github_repo_screenshot" and asset.status == "generated" for asset in assets):
            return ["README 未发现合适图片，使用 GitHub 仓库首页截图。"]
        return ["截图失败，发布稿不插图。"]

    def _package_payload(self, article_package: ArticlePackage) -> dict[str, Any]:
        if hasattr(article_package, "model_dump"):
            return article_package.model_dump(mode="json")
        return article_package.dict()
