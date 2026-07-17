from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.config import get_settings
from src.content_index import ContentIndexService
from src.models import NewsDigestPipelineResult
from src.news_collector import NewsCollectorService
from src.news_digest_polisher import NewsDigestPolisherService
from src.news_digest_quality import NewsDigestQualityEvaluator
from src.news_digest_writer import NewsDigestWriterService
from src.news_event_builder import NewsEventBuilderService
from src.news_scorer import NewsScoringService


STAGE_NAMES = (
    "采集新闻",
    "新闻评分",
    "合并事件",
    "生成简报",
    "质量检查",
    "发布整理",
    "更新内容库",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class NewsDigestPipelineService:
    """Run the independent daily AI news digest product pipeline."""

    def __init__(
        self,
        project_root: Path | None = None,
        workspace_dir: Path | None = None,
        output_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self.project_root = (project_root or Path(__file__).resolve().parents[1]).resolve()
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self.output_dir = output_dir or settings.output_dir

    def run(
        self,
        hours: int = 24,
        limit: int = 100,
        translate: bool = True,
        translate_limit: int = 100,
        score_top: int = 30,
        min_score: float = 50,
        event_top: int = 20,
        digest_top: int = 12,
        polish: bool = True,
        date: str | None = None,
    ) -> NewsDigestPipelineResult:
        digest_date = (date or datetime.now().date().isoformat()).strip()
        result = NewsDigestPipelineResult(
            generated_at=_utc_now_iso(),
            date=digest_date,
            status="running",
            stages=[self._new_stage(name) for name in STAGE_NAMES],
        )
        article = None
        events = None
        quality_report = None
        failed = False

        collection = self._execute(
            result,
            0,
            lambda: NewsCollectorService(self.workspace_dir, self.output_dir).collect(
                hours=hours,
                limit=limit,
                translate=translate,
                translate_limit=translate_limit,
            ),
            lambda value: f"采集 {value.total_count} 条新闻，其中 {value.fresh_count} 条在时间窗口内。",
        )
        if collection is None:
            failed = True
        else:
            result.collection_count = collection.total_count
            self._add_warnings(result, collection.warnings)

        scoring = None
        if not failed:
            scoring = self._execute(
                result,
                1,
                lambda: NewsScoringService(self.workspace_dir, self.output_dir).score_latest(
                    top=score_top,
                    min_score=min_score,
                ),
                lambda value: f"完成 {value.total_count} 条评分，推荐 {value.recommended_count} 条。",
            )
            if scoring is None:
                failed = True
            else:
                result.scored_count = scoring.total_count
                self._add_warnings(result, scoring.warnings)

        if not failed:
            events = self._execute(
                result,
                2,
                lambda: NewsEventBuilderService(self.workspace_dir, self.output_dir).build_latest(
                    top=event_top,
                    min_score=min_score,
                ),
                lambda value: f"合并为 {value.event_count} 个事件，其中推荐 {value.recommended_event_count} 个。",
            )
            if events is None:
                failed = True
            else:
                result.event_count = events.event_count
                self._add_warnings(result, events.warnings)

        if not failed:
            article = self._execute(
                result,
                3,
                lambda: NewsDigestWriterService(self.workspace_dir, self.output_dir).write_latest(
                    top=digest_top,
                    date=digest_date,
                ),
                lambda value: f"生成《{value.title}》，使用 {value.event_count} 个事件。",
            )
            if article is None:
                failed = True
            else:
                result.digest_event_count = article.event_count
                result.digest_title = article.title
                result.digest_path = f"outputs/{article.date}/ai_news_digest.md"
                self._add_warnings(result, article.warnings)

        if article is not None:
            evaluator = NewsDigestQualityEvaluator(self.workspace_dir, self.output_dir)
            quality_report = self._execute(
                result,
                4,
                lambda: self._evaluate_and_save(evaluator, article, events),
                lambda value: f"质量分 {value.total_score:.1f}，{'可发布' if value.publish_ready else '需要修改'}。",
            )
            if quality_report is None:
                failed = True
            else:
                result.quality_score = quality_report.total_score
                result.publish_ready = quality_report.publish_ready

        if article is not None and quality_report is not None:
            publish_result = self._execute(
                result,
                5,
                lambda: self._prepare_for_publish(article, quality_report, events, polish),
                lambda value: f"发布包已生成：{value[0].package_path or '-'}",
            )
            if publish_result is None:
                failed = True
            else:
                article, quality_report = publish_result
                result.package_path = article.package_path
                result.quality_score = quality_report.total_score
                result.publish_ready = quality_report.publish_ready
                self._add_warnings(result, article.warnings)

        if article is not None:
            indexed = self._execute(
                result,
                6,
                lambda: self._rebuild_and_locate(article.date, result.digest_path, result.package_path),
                lambda value: f"内容库已更新，content_id={value[1] or '未定位'}。",
            )
            if indexed is None:
                failed = True
            else:
                _, result.content_id = indexed
                if not result.content_id:
                    self._add_warnings(result, ["Content Index 已更新，但未能定位本次 AI 日报的 content_id。"])

        for stage in result.stages:
            if stage["status"] == "pending":
                stage["status"] = "skipped"
                stage["summary"] = "因前置阶段失败而跳过。"

        result.status = "failed" if failed else "completed"
        result.generated_at = _utc_now_iso()
        self.save_result(result)
        return result

    def load_latest(self) -> NewsDigestPipelineResult | None:
        path = self.workspace_dir / "news" / "news_digest_pipeline_latest.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if hasattr(NewsDigestPipelineResult, "model_validate"):
            return NewsDigestPipelineResult.model_validate(payload)
        return NewsDigestPipelineResult.parse_obj(payload)

    def save_result(self, result: NewsDigestPipelineResult) -> None:
        news_dir = self.workspace_dir / "news"
        snapshots_dir = self.workspace_dir / "snapshots"
        output_dir = self.output_dir / result.date
        news_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_model_dump(result), ensure_ascii=False, indent=2) + "\n"
        (news_dir / "news_digest_pipeline_latest.json").write_text(payload, encoding="utf-8")
        (snapshots_dir / "news_digest_pipeline_latest.json").write_text(payload, encoding="utf-8")
        (output_dir / "news_digest_pipeline_report.md").write_text(
            self.render_report(result),
            encoding="utf-8",
        )

    @staticmethod
    def render_report(result: NewsDigestPipelineResult) -> str:
        lines = [
            "# 每日新闻简报流水线报告",
            "",
            f"- 状态：{result.status}",
            f"- 日期：{result.date}",
            f"- 生成时间：{result.generated_at}",
            f"- 采集数量：{result.collection_count}",
            f"- 评分数量：{result.scored_count}",
            f"- 事件数量：{result.event_count}",
            f"- 日报事件数量：{result.digest_event_count}",
            f"- 质量分：{result.quality_score if result.quality_score is not None else '-'}",
            f"- 可发布：{'是' if result.publish_ready else '否'}",
            f"- 日报路径：{result.digest_path or '-'}",
            f"- 发布包路径：{result.package_path or '-'}",
            f"- Content ID：{result.content_id or '-'}",
            "",
            "## 阶段",
            "",
        ]
        for stage in result.stages:
            lines.extend(
                [
                    f"### {stage['name']}",
                    "",
                    f"- 状态：{stage['status']}",
                    f"- 开始：{stage['started_at'] or '-'}",
                    f"- 结束：{stage['finished_at'] or '-'}",
                    f"- 摘要：{stage['summary'] or '-'}",
                    f"- 错误：{stage['error'] or '-'}",
                    "",
                ]
            )
        lines.extend(["## Warnings", ""])
        lines.extend([f"- {warning}" for warning in result.warnings] or ["- 无"])
        return "\n".join(lines).rstrip() + "\n"

    def _execute(
        self,
        result: NewsDigestPipelineResult,
        stage_index: int,
        action: Callable[[], Any],
        summarize: Callable[[Any], str],
    ) -> Any | None:
        stage = result.stages[stage_index]
        stage["status"] = "running"
        stage["started_at"] = _utc_now_iso()
        try:
            value = action()
            stage["status"] = "completed"
            stage["summary"] = summarize(value)
            return value
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            stage["status"] = "failed"
            stage["error"] = message
            stage["summary"] = "阶段执行失败。"
            self._add_warnings(result, [f"{stage['name']}失败：{message}"])
            return None
        finally:
            stage["finished_at"] = _utc_now_iso()

    @staticmethod
    def _new_stage(name: str) -> dict[str, Any]:
        return {
            "name": name,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "summary": "",
            "error": None,
        }

    @staticmethod
    def _add_warnings(result: NewsDigestPipelineResult, warnings: list[str] | None) -> None:
        for warning in warnings or []:
            cleaned = str(warning or "").strip()
            if cleaned and cleaned not in result.warnings:
                result.warnings.append(cleaned)

    @staticmethod
    def _evaluate_and_save(evaluator: NewsDigestQualityEvaluator, article: Any, events: Any) -> Any:
        report = evaluator.evaluate(article, events, threshold=80)
        evaluator.save_report(article, report)
        return report

    def _prepare_for_publish(self, article: Any, report: Any, events: Any, polish: bool) -> tuple[Any, Any]:
        polisher = NewsDigestPolisherService(self.workspace_dir, self.output_dir)
        evaluator = NewsDigestQualityEvaluator(self.workspace_dir, self.output_dir)
        article = polisher.polish_article(article, report) if polish else polisher.attach_quality(article, report)
        if polish and article.polished:
            report = evaluator.evaluate(article, events, threshold=80)
            article = polisher.attach_quality(article, report)
        article = polisher.generate_package(article, report)
        polisher.save_article(article)
        evaluator.save_report(article, report)
        return article, report

    def _rebuild_and_locate(
        self,
        date: str,
        digest_path: str | None,
        package_path: str | None,
    ) -> tuple[Any, str | None]:
        index = ContentIndexService(self.project_root).build_index()
        normalized_digest = self._normalize_path(digest_path)
        normalized_package = self._normalize_path(package_path)
        candidates = [item for item in index.items if item.content_type == "ai_news_digest" and item.date == date]
        for item in candidates:
            if normalized_digest and self._normalize_path(item.markdown_path) == normalized_digest:
                return index, item.content_id
            if normalized_package and self._normalize_path(item.package_path) == normalized_package:
                return index, item.content_id
        return index, candidates[0].content_id if len(candidates) == 1 else None

    def _normalize_path(self, value: str | None) -> str | None:
        if not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return path.resolve().as_posix()
