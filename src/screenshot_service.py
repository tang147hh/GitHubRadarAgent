from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Literal


@dataclass
class ScreenshotResult:
    ok: bool
    output_path: Path
    source_url: str
    error: str | None = None


class ScreenshotService:
    """Captures real GitHub pages as optional article visuals."""

    def __init__(self, project_root: Path, width: int = 1440, height: int = 1200) -> None:
        self.project_root = project_root.resolve()
        self.width = width
        self.height = height

    def capture_github_readme(self, full_name: str, output_path: Path) -> ScreenshotResult:
        return self._capture(
            url=f"https://github.com/{full_name}#readme",
            output_path=output_path,
            target="readme",
        )

    def capture_github_repo(self, full_name: str, output_path: Path) -> ScreenshotResult:
        return self._capture(
            url=f"https://github.com/{full_name}",
            output_path=output_path,
            target="page",
        )

    def _capture(
        self,
        url: str,
        output_path: Path,
        target: Literal["readme", "page"],
    ) -> ScreenshotResult:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []

        python_result = self._capture_with_python_playwright(url, output_path, target)
        if python_result.ok:
            return python_result
        if python_result.error:
            errors.append(python_result.error)

        node_result = self._capture_with_node_playwright(url, output_path, target)
        if node_result.ok:
            return node_result
        if node_result.error:
            errors.append(node_result.error)

        return ScreenshotResult(
            ok=False,
            output_path=output_path,
            source_url=url,
            error="; ".join(error for error in errors if error) or "截图依赖不可用或页面截图失败。",
        )

    def _capture_with_python_playwright(
        self,
        url: str,
        output_path: Path,
        target: Literal["readme", "page"],
    ) -> ScreenshotResult:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return ScreenshotResult(False, output_path, url, f"Python Playwright 不可用：{exc}")

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(
                        viewport={"width": self.width, "height": self.height},
                        device_scale_factor=1,
                    )
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    self._prepare_page(page)
                    if target == "readme" and self._screenshot_readme_locator(page, output_path):
                        return ScreenshotResult(True, output_path, url)
                    page.screenshot(path=str(output_path), full_page=False)
                    return ScreenshotResult(True, output_path, url)
                finally:
                    browser.close()
        except Exception as exc:
            return ScreenshotResult(False, output_path, url, f"Python Playwright 截图失败：{exc}")

    def _capture_with_node_playwright(
        self,
        url: str,
        output_path: Path,
        target: Literal["readme", "page"],
    ) -> ScreenshotResult:
        node = self._node_binary()
        script = self.project_root / "frontend" / "scripts" / "capture_page.mjs"
        if not node:
            return ScreenshotResult(False, output_path, url, "Node.js 不可用，无法使用 Node Playwright fallback。")
        if not script.exists():
            return ScreenshotResult(False, output_path, url, f"截图脚本不存在：{script}")

        command = [
            node,
            str(script),
            "--url",
            url,
            "--out",
            str(output_path),
            "--width",
            str(self.width),
            "--height",
            str(self.height),
            "--target",
            target,
        ]
        env = os.environ.copy()
        node_modules = self.project_root / "frontend" / "node_modules"
        if node_modules.exists():
            env["NODE_PATH"] = str(node_modules)
        try:
            completed = subprocess.run(
                command,
                cwd=self.project_root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as exc:
            return ScreenshotResult(False, output_path, url, f"Node Playwright 截图失败：{exc}")
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            return ScreenshotResult(False, output_path, url, f"Node Playwright 截图失败：{message or completed.returncode}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            return ScreenshotResult(False, output_path, url, "Node Playwright 未生成有效截图文件。")
        return ScreenshotResult(True, output_path, url)

    def _prepare_page(self, page: object) -> None:
        try:
            page.add_style_tag(
                content="""
                cookie-consent, [data-testid*="cookie"], .js-cookie-consent,
                .cookie, .flash, .Popover-message, .Overlay,
                [role="dialog"], [aria-modal="true"] {
                  display: none !important;
                  visibility: hidden !important;
                }
                """
            )
        except Exception:
            pass

    def _screenshot_readme_locator(self, page: object, output_path: Path) -> bool:
        selectors = [
            "#readme",
            "[data-testid='readme']",
            "article.markdown-body",
            ".Box .markdown-body",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() <= 0:
                    continue
                locator.scroll_into_view_if_needed(timeout=5000)
                locator.screenshot(path=str(output_path), timeout=15000)
                return output_path.exists() and output_path.stat().st_size > 0
            except Exception:
                continue
        return False

    def _node_binary(self) -> str | None:
        candidates = [
            os.environ.get("NODE_BINARY"),
            shutil.which("node"),
            str(Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return None
