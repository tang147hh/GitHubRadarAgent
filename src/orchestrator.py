from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, TypeVar, Union

from .angle_planner import AnglePlannerService
from .article_quality import ArticleQualityEvaluator
from .asset_generator import AssetGeneratorService
from .article_selection import ArticleSelectionService
from .article_writer import ArticleWriterService
from .config import get_settings
from .content_planner import ContentPlanningService
from .custom_project import parse_github_repo_url
from .direction_parser import DirectionParserService
from .discovery import DiscoveryService
from .editor import EditorService
from .github_client import GitHubClient
from .humanization_editor import HumanizationEditorService
from .llm_service import LLMService
from .models import (
    ArticleDraft,
    ArticlePackage,
    ArticleReview,
    CustomArticleDirection,
    DailyRun,
    FinalArticle,
    HumanizationReport,
    OriginalityReport,
    PublishPolishReport,
    RepoCandidate,
    RepoResearchNote,
    RepoScore,
    StyleReferenceProfile,
    TitleCandidate,
    TopicAngle,
    VisualAsset,
)
from .originality_guard import OriginalityGuardService
from .publish_polisher import PublishPolisherService
from .research import RepoResearchService
from .scoring import ScoringService
from .style_reference import StyleReferenceService
from .visual_planner import VisualPlannerService


T = TypeVar("T")


class DailyOrchestrator:
    """Coordinates the daily GitHubRadarAgent workflow."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def run_daily(
        self,
        limit_per_keyword: int = 5,
        score_top: int = 30,
        research_top: int = 3,
        article_top: int = 3,
        review_threshold: float = 80,
        daily_keywords: list[str] | None = None,
        cooldown_days: int = 30,
        ignore_history: bool = False,
        allow_recent_fallback: bool = False,
        prefer_growth_projects: bool | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> DailyRun:
        started_at = datetime.utcnow()
        run_date = started_at.strftime("%Y-%m-%d")
        run_id = started_at.strftime("daily_%Y%m%d_%H%M%S")
        active_keywords = daily_keywords or self.settings.daily_keywords
        run = DailyRun(
            run_id=run_id,
            date=run_date,
            started_at=self._format_utc(started_at),
            output_dir=str(self.settings.output_dir / run_date),
            keywords=active_keywords,
        )

        print(f"[run-daily] Run ID: {run.run_id}")
        print(f"[run-daily] Date: {run.date}")
        print(f"[run-daily] Keywords: {', '.join(run.keywords)}")
        print(
            "[run-daily] Pipeline: discover -> score -> select-projects -> "
            "research-selected -> angles -> plan-content -> write-articles -> review-articles -> package-articles"
        )
        self._save_run_state(run)
        self._emit_progress(
            progress_callback,
            {
                "type": "run_started",
                "message": f"Run {run.run_id} started.",
                "time": run.started_at,
            },
        )

        try:
            self._run_stage(
                run,
                "discover",
                lambda: self.discover(limit_per_keyword=limit_per_keyword, keywords=active_keywords),
                lambda result: f"Discovered {len(result)} candidate repositories.",
                progress_callback,
            )
            self._run_stage(
                run,
                "score",
                lambda: self.score(top=score_top),
                lambda result: f"Scored {len(result)} candidate repositories.",
                progress_callback,
            )
            selection_summary = self._run_stage(
                run,
                "select-projects",
                lambda: self.select_article_projects(
                    article_top=article_top,
                    cooldown_days=cooldown_days,
                    ignore_history=ignore_history,
                    allow_recent_fallback=allow_recent_fallback,
                    prefer_growth_projects=prefer_growth_projects,
                ),
                lambda result: (
                    f"Selected {len(result.get('selected_repos', []))} projects "
                    f"from {result.get('candidate_count', 0)} candidates."
                ),
                progress_callback,
            )
            run.selection_summary = selection_summary
            self._save_run_state(run)
            selected_repo_full_names = selection_summary.get("selected_repos", [])
            self._run_stage(
                run,
                "research-selected",
                lambda: self.research_selected(selected_repo_full_names=selected_repo_full_names),
                lambda result: f"Generated {len(result)} selected research notes.",
                progress_callback,
            )
            self._run_stage(
                run,
                "angles",
                lambda: self.plan_angles(top=len(selected_repo_full_names), selected_repo_full_names=selected_repo_full_names),
                lambda result: f"Generated {len(result)} topic angle plans.",
                progress_callback,
            )
            self._run_stage(
                run,
                "plan-content",
                lambda: self.plan_content(top=len(selected_repo_full_names), selected_repo_full_names=selected_repo_full_names),
                lambda result: f"Generated {len(result)} content planning artifacts.",
                progress_callback,
            )
            self._run_stage(
                run,
                "write-articles",
                lambda: self.write_articles(top=len(selected_repo_full_names), selected_repo_full_names=selected_repo_full_names),
                lambda result: f"Generated {len(result)} article drafts.",
                progress_callback,
            )
            final_articles = self._run_stage(
                run,
                "review-articles",
                lambda: self.review_articles(
                    top=len(selected_repo_full_names),
                    threshold=review_threshold,
                    selected_repo_full_names=selected_repo_full_names,
                ),
                lambda result: f"Reviewed and saved {len(result)} final articles.",
                progress_callback,
            )
            article_packages = self._run_stage(
                run,
                "package-articles",
                lambda: self.package_articles(
                    top=len(selected_repo_full_names),
                    full_names=selected_repo_full_names,
                ),
                lambda result: f"Generated {len(result)} article packages.",
                progress_callback,
                fatal=False,
                require_output=False,
            )
        except Exception as exc:
            run.status = "failed"
            run.current_stage = None
            run.finished_at = self._format_utc()
            run.error = f"{type(exc).__name__}: {exc}"
            run.snapshot_files = self._collect_snapshot_files()
            run.final_article_files = self._collect_final_article_files(run.date)
            self._save_run_state(run)
            print(f"[run-daily] Failed: {run.error}")
            self._emit_progress(
                progress_callback,
                {
                    "type": "run_failed",
                    "message": f"Run {run.run_id} failed.",
                    "error": run.error,
                    "time": run.finished_at,
                },
            )
            raise

        run.status = "success"
        run.current_stage = None
        run.finished_at = self._format_utc()
        run.error = None
        run.snapshot_files = self._collect_snapshot_files()
        run.final_article_files = self._collect_final_article_files(run.date)
        self._update_article_history_after_daily(final_articles, run.final_article_files)
        daily_report_path = self._save_daily_report(run, final_articles, article_packages)
        self._save_run_state(run)

        print(f"[run-daily] Success: {run.run_id}")
        print(f"[run-daily] Saved run state: {self._runs_dir() / f'{run.run_id}.json'}")
        print(f"[run-daily] Saved latest run state: {self._runs_dir() / 'latest_run.json'}")
        print(f"[run-daily] Saved daily report: {daily_report_path}")
        print(f"[run-daily] Saved final articles index: {self.settings.output_dir / run.date / 'final_articles_index.md'}")
        self._emit_progress(
            progress_callback,
            {
                "type": "run_succeeded",
                "message": f"Run {run.run_id} completed successfully.",
                "time": run.finished_at,
                "result": {
                    "run_id": run.run_id,
                    "date": run.date,
                    "status": run.status,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                    "output_dir": run.output_dir,
                },
            },
        )
        return run

    def discover(self, limit_per_keyword: int = 10, keywords: list[str] | None = None) -> List[RepoCandidate]:
        active_keywords = keywords or self.settings.daily_keywords
        github_client = GitHubClient(token=self.settings.github_personal_access_token)
        discovery_service = DiscoveryService(
            github_client=github_client,
            keywords=active_keywords,
        )

        try:
            candidates = discovery_service.discover(limit_per_keyword=limit_per_keyword)
        except RuntimeError as exc:
            cached_candidates = self._load_cached_discovery_candidates()
            if not cached_candidates:
                raise
            warning = f"Discovery API failed; reused cached discovery_latest.json: {exc}"
            discovery_service.warnings.append(warning)
            candidates = cached_candidates
        print(f"Discovered {len(candidates)} candidate repositories.")
        for warning in discovery_service.warnings:
            print(f"Warning: {warning}")
        self._print_candidate_summaries(candidates[:10])
        self._save_discovery_snapshots(candidates, keywords=active_keywords, warnings=discovery_service.warnings)
        return candidates

    def _load_cached_discovery_candidates(self) -> list[RepoCandidate]:
        discovery_snapshot_path = self.settings.workspace_dir / "snapshots" / "discovery_latest.json"
        if not discovery_snapshot_path.exists():
            return []
        try:
            payload = json.loads(discovery_snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        candidate_items = payload.get("candidates", []) if isinstance(payload, dict) else []
        if not isinstance(candidate_items, list):
            return []
        return [self._parse_repo_candidate(item) for item in candidate_items if isinstance(item, dict)]

    def write(self, repo: str) -> ArticleDraft:
        print(f"TODO: write a WeChat-style Markdown recommendation article for {repo}.")
        print("This placeholder will later use project notes, repo metadata, and LLM generation.")
        return ArticleDraft(
            repo_full_name=repo,
            title=f"{repo} 推荐文章占位",
            summary="TODO: generate article summary.",
        )

    def write_custom_article(
        self,
        repo_url: str,
        direction_text: str | None = None,
        reference_texts: list[str] | None = None,
        reference_source_names: list[str] | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._emit_progress(
            progress_callback,
            {
                "type": "run_started",
                "message": "Custom article writing started.",
                "time": started_at,
            },
        )
        self._emit_custom_stage_started(progress_callback, "parse_repo", "Parsing GitHub repository URL.")
        try:
            repo_ref = parse_github_repo_url(repo_url)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit_progress(
                progress_callback,
                {
                    "type": "stage_failed",
                    "stage": "parse_repo",
                    "message": "parse_repo failed.",
                    "error": error,
                    "time": self._format_utc(),
                },
            )
            self._emit_progress(
                progress_callback,
                {
                    "type": "run_failed",
                    "message": "Custom article writing failed.",
                    "error": error,
                    "time": self._format_utc(),
                },
            )
            raise
        self._emit_custom_stage_succeeded(progress_callback, "parse_repo", f"Parsed project {repo_ref.full_name}.")
        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        safe_name = f"{repo_ref.owner}__{repo_ref.repo}"
        output_dir = self.settings.output_dir / run_date / "custom_articles"
        markdown_path = output_dir / f"{safe_name}.md"
        report_path = output_dir / f"{safe_name}_report.md"
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        latest_snapshot_path = snapshots_dir / "custom_article_latest.json"
        dated_snapshot_path = snapshots_dir / f"{run_date}-custom-article-{safe_name}.json"

        print(f"[write-custom] Project: {repo_ref.full_name}")
        print("[write-custom] Pipeline: research -> plan-content -> write -> review -> humanize -> polish -> originality")

        base_payload: dict[str, Any] = {
            "generated_at": started_at,
            "repo_url": repo_url,
            "normalized_repo_url": repo_ref.html_url,
            "owner": repo_ref.owner,
            "repo": repo_ref.repo,
            "full_name": repo_ref.full_name,
            "direction_text": direction_text or "",
            "custom_direction": None,
            "parsed_direction": None,
            "style_reference_profile": None,
            "wechat_pattern": None,
            "reference_source_names": reference_source_names or [],
            "reference_text_count": len(reference_texts or []),
            "status": "running",
            "output_markdown_path": str(markdown_path),
            "report_path": str(report_path),
            "research_note": None,
            "content_plan": None,
            "draft": None,
            "review": None,
            "final_article": None,
            "humanization_report": None,
            "publish_polish_report": None,
            "article_quality_report": None,
            "originality_report": {
                "checked": False,
                "passed": True,
                "similarity_score": 0.0,
                "max_common_sequence_length": 0,
                "copied_sentence_count": 0,
                "structure_similarity": 0.0,
                "issues": [],
                "rewrite_attempted": False,
                "rewrite_mode": "none",
                "summary": "未提供参考文章，本次未执行相似度检查",
            },
            "originality_checked": False,
            "originality_passed": True,
            "warnings": [],
        }

        try:
            github_client = GitHubClient(token=self.settings.github_personal_access_token)
            research_service = RepoResearchService(github_client=github_client)
            research_note = self._run_custom_stage(
                progress_callback,
                "research",
                lambda: research_service.research_by_full_name(repo_ref.owner, repo_ref.repo),
                f"Researching {repo_ref.full_name}.",
                "Research notes are ready.",
            )
            self._print_research_summaries([research_note])

            llm_service = LLMService(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
                model=self.settings.openai_model,
            )
            direction_parser = DirectionParserService(llm_service=llm_service)
            custom_direction = self._run_custom_stage(
                progress_callback,
                "parse_direction",
                lambda: direction_parser.parse(direction_text),
                "Parsing article direction.",
                "Article direction parsed.",
            )
            style_reference_service = StyleReferenceService(llm_service=llm_service)
            style_reference_profile = self._run_custom_stage(
                progress_callback,
                "analyze_style_reference",
                lambda: self._normalize_style_reference_intent(
                    direction_text,
                    style_reference_service.analyze(reference_texts, reference_source_names),
                ),
                "Analyzing style reference profile.",
                "Style reference profile is ready.",
            )
            angle = self._build_custom_topic_angle(research_note, direction_text, custom_direction)

            planner = ContentPlanningService(llm_service=llm_service)
            content_plan = self._run_custom_stage(
                progress_callback,
                "plan_content",
                lambda: self._build_custom_content_plan(
                    planner,
                    research_note,
                    angle,
                    custom_direction,
                    style_reference_profile,
                ),
                "Planning article structure and emphasis.",
                "Content plan is ready.",
            )

            writer = ArticleWriterService(llm_service=llm_service)
            draft = self._run_custom_stage(
                progress_callback,
                "write_article",
                lambda: writer.write_article(angle, research_note, content_plan),
                "Writing article draft.",
                "Article draft is ready.",
            )

            editor = EditorService(llm_service=llm_service)
            review, final_article = self._run_custom_stage(
                progress_callback,
                "review",
                lambda: (
                    lambda article_review: (
                        article_review,
                        editor.revise_article(draft, article_review, research_note, angle),
                    )
                )(editor.review_article(draft, research_note, angle)),
                "Reviewing and revising draft.",
                "Review and revision finished.",
            )

            humanization_editor = HumanizationEditorService(llm_service=llm_service)
            final_article = self._run_custom_stage(
                progress_callback,
                "humanize",
                lambda: humanization_editor.process_articles(
                    [final_article],
                    [draft],
                    [research_note],
                    [content_plan],
                )[0],
                "Improving naturalness and originality expression.",
                "Humanization pass finished.",
            )

            publish_polisher = PublishPolisherService(llm_service=llm_service)
            final_article = self._run_custom_stage(
                progress_callback,
                "polish",
                lambda: self._ensure_custom_article_project_address_only(
                    publish_polisher.polish_article(final_article, research_note, content_plan),
                    research_note,
                ),
                "Polishing article for publishing.",
                "Publish polish finished.",
            )

            originality_guard = OriginalityGuardService(llm_service=llm_service)
            originality_result = self._run_custom_stage(
                progress_callback,
                "originality",
                lambda: originality_guard.guard(
                    final_article=final_article,
                    reference_texts=reference_texts or [],
                    style_reference_profile=style_reference_profile,
                    custom_direction=custom_direction,
                ),
                (
                    "Running Originality Check and Similarity Guard."
                    if reference_texts
                    else "Preparing originality status."
                ),
                "Originality Check finished.",
            )
            final_article = self._ensure_custom_article_project_address_only(
                originality_result.final_article,
                research_note,
            )
            originality_report = final_article.originality_report or originality_result.originality_report
            article_quality_evaluator = ArticleQualityEvaluator(llm_service=llm_service)
            final_article = self._run_custom_stage(
                progress_callback,
                "article_quality",
                lambda: article_quality_evaluator.evaluate_article(
                    final_article=final_article,
                    research_note=research_note,
                    content_plan=content_plan,
                ),
                "Evaluating article quality for WeChat publishing.",
                "Article quality evaluation finished.",
            )
            article_package = self._run_custom_stage(
                progress_callback,
                "package",
                lambda: self._package_custom_article(
                    final_article=final_article,
                    research_note=research_note,
                    content_plan=content_plan,
                    markdown_path=markdown_path,
                    run_date=run_date,
                ),
                "Packaging article with README images.",
                "Article package is ready.",
            )

            warnings = (
                direction_parser.warnings
                + style_reference_service.warnings
                + planner.warnings
                + writer.warnings
                + editor.warnings
                + humanization_editor.warnings
                + publish_polisher.warnings
                + originality_guard.warnings
                + article_quality_evaluator.warnings
            )
            selected_readme_images = [
                asset.source_url
                for asset in article_package.assets
                if asset.asset_type == "readme_image" and asset.source_url
            ]
            visual_assets = [self._model_dump(asset) for asset in article_package.assets]
            payload = {
                **base_payload,
                "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "status": "success",
                "llm_available": llm_service.is_available(),
                "used_llm_direction_parsing": direction_parser.used_llm,
                "used_fallback_direction_parsing": direction_parser.used_fallback,
                "used_llm_style_reference": style_reference_service.used_llm,
                "used_fallback_style_reference": style_reference_service.used_fallback,
                "used_llm_content_planning": planner.used_llm,
                "used_llm_writing": writer.used_llm,
                "used_llm_review": editor.used_llm_review,
                "used_llm_revision": editor.used_llm_revision,
                "used_llm_humanization": humanization_editor.used_llm,
                "used_fallback_humanization": humanization_editor.used_fallback_rewrite,
                "used_llm_publish_polish": publish_polisher.used_llm,
                "used_llm_originality_rewrite": originality_guard.used_llm,
                "used_fallback_originality_rewrite": originality_guard.used_fallback_rewrite,
                "used_llm_article_quality": article_quality_evaluator.used_llm,
                "custom_direction": self._model_dump(custom_direction),
                "parsed_direction": self._model_dump(custom_direction),
                "style_reference_profile": self._model_dump(style_reference_profile),
                "wechat_pattern": self._model_dump(content_plan.get("wechat_pattern")),
                "reference_source_names": style_reference_profile.source_names,
                "reference_text_count": style_reference_profile.raw_count,
                "research_note": self._model_dump(research_note),
                "content_plan": content_plan,
                "draft": self._model_dump(draft),
                "review": self._model_dump(review),
                "final_article": self._model_dump(final_article),
                "humanization_report": self._model_dump(final_article.humanization_report)
                if final_article.humanization_report
                else None,
                "publish_polish_report": self._model_dump(final_article.publish_polish_report)
                if final_article.publish_polish_report
                else None,
                "originality_report": self._model_dump(originality_report),
                "originality_checked": bool(originality_report.checked),
                "originality_passed": bool(originality_report.passed),
                "article_quality_report": self._model_dump(final_article.article_quality_report)
                if final_article.article_quality_report
                else None,
                "quality_score": final_article.quality_score,
                "quality_publish_ready": final_article.quality_publish_ready,
                "package_path": article_package.packaged_article_path,
                "packaged_article_path": article_package.packaged_article_path,
                "packaged_article_available": bool(article_package.packaged_article_path),
                "package_dir": article_package.package_dir,
                "asset_manifest_path": str(Path(article_package.package_dir) / "assets.json")
                if article_package.package_dir
                else None,
                "selected_readme_images": selected_readme_images,
                "asset_count": len(article_package.assets),
                "visual_assets": visual_assets,
                "article_package": self._model_dump(article_package),
                "warnings": warnings,
            }
            self._run_custom_stage(
                progress_callback,
                "done",
                lambda: self._save_custom_article_outputs(
                    payload=payload,
                    final_article=final_article,
                    research_note=research_note,
                    content_plan=content_plan,
                    markdown_path=markdown_path,
                    report_path=report_path,
                    latest_snapshot_path=latest_snapshot_path,
                    dated_snapshot_path=dated_snapshot_path,
                ),
                "Saving custom article outputs.",
                "Custom article outputs saved.",
            )
            print(f"[write-custom] Saved markdown: {markdown_path}")
            print(f"[write-custom] Saved packaged article: {article_package.packaged_article_path}")
            print(f"[write-custom] Saved report: {report_path}")
            self._emit_progress(
                progress_callback,
                {
                    "type": "run_succeeded",
                    "message": "Custom article writing completed successfully.",
                    "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "result": {
                        "status": "success",
                        "date": run_date,
                        "output_dir": str(output_dir),
                    },
                },
            )
            return {
                "full_name": repo_ref.full_name,
                "title": final_article.title,
                "generation_mode": final_article.generation_mode,
                "markdown_path": str(markdown_path),
                "report_path": str(report_path),
                "package_path": article_package.packaged_article_path,
                "packaged_article_available": bool(article_package.packaged_article_path),
                "snapshot_path": str(latest_snapshot_path),
                "dated_snapshot_path": str(dated_snapshot_path),
                "style_reference_used": style_reference_profile.raw_count > 0,
                "payload": payload,
            }
        except Exception as exc:
            self._emit_progress(
                progress_callback,
                {
                    "type": "run_failed",
                    "message": "Custom article writing failed.",
                    "error": f"{type(exc).__name__}: {exc}",
                    "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                },
            )
            error_payload = {
                **base_payload,
                "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(latest_snapshot_path, error_payload)
            self._write_json(dated_snapshot_path, error_payload)
            print(f"[write-custom] Failed: {error_payload['error']}")
            raise

    def score(self, top: int = 10) -> List[RepoScore]:
        discovery_snapshot_path = self.settings.workspace_dir / "snapshots" / "discovery_latest.json"
        if not discovery_snapshot_path.exists():
            print(f"Discovery snapshot not found: {discovery_snapshot_path}")
            print("Please run first: python3 main.py discover --limit-per-keyword 5")
            return []

        payload = json.loads(discovery_snapshot_path.read_text(encoding="utf-8"))
        candidate_items = payload.get("candidates", [])
        candidates = [self._parse_repo_candidate(item) for item in candidate_items]

        scoring_service = ScoringService()
        scores = scoring_service.score_candidates(candidates)
        selected_scores = scores[: max(0, top)]
        print(f"Scored {len(scores)} candidate repositories; kept top {len(selected_scores)} for selection.")
        self._print_score_summaries(selected_scores, candidates)
        self._save_score_outputs(selected_scores, candidates, discovery_snapshot_path)
        return selected_scores

    def research(self, top: int = 3) -> List[RepoResearchNote]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        score_snapshot_path = snapshots_dir / "score_latest.json"
        discovery_snapshot_path = snapshots_dir / "discovery_latest.json"

        if not score_snapshot_path.exists():
            print(f"Score snapshot not found: {score_snapshot_path}")
            print("Please run first: python3 main.py score --top 10")
            return []
        if not discovery_snapshot_path.exists():
            print(f"Discovery snapshot not found: {discovery_snapshot_path}")
            print("Please run first: python3 main.py discover --limit-per-keyword 5")
            return []

        score_payload = json.loads(score_snapshot_path.read_text(encoding="utf-8"))
        discovery_payload = json.loads(discovery_snapshot_path.read_text(encoding="utf-8"))
        score_items = score_payload.get("scores", [])
        candidate_items = discovery_payload.get("candidates", [])
        candidates_by_name = {
            candidate.full_name: candidate
            for candidate in [self._parse_repo_candidate(item) for item in candidate_items]
        }

        selected_candidates: list[RepoCandidate] = []
        for score_item in score_items[: max(0, top)]:
            full_name = score_item.get("full_name")
            if not full_name:
                continue
            candidate = candidates_by_name.get(full_name)
            if candidate is None:
                candidate = self._candidate_from_score_item(score_item)
            selected_candidates.append(candidate)

        if not selected_candidates:
            print("No scored repositories available for research.")
            return []

        github_client = GitHubClient(token=self.settings.github_personal_access_token)
        research_service = RepoResearchService(github_client=github_client)
        notes = research_service.research_top_repos(selected_candidates, top=top)

        print(f"Researched {len(notes)} top repositories.")
        self._print_research_summaries(notes)
        self._save_research_outputs(
            notes=notes,
            source_score_snapshot_path=score_snapshot_path,
            source_discovery_snapshot_path=discovery_snapshot_path,
        )
        return notes

    def research_selected(self, selected_repo_full_names: list[str]) -> List[RepoResearchNote]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        score_snapshot_path = snapshots_dir / "score_latest.json"
        discovery_snapshot_path = snapshots_dir / "discovery_latest.json"
        selection_snapshot_path = snapshots_dir / "selection_latest.json"

        if not selected_repo_full_names:
            print("No selected repositories available for research.")
            self._save_research_outputs(
                notes=[],
                source_score_snapshot_path=score_snapshot_path,
                source_discovery_snapshot_path=discovery_snapshot_path,
                source_selection_snapshot_path=selection_snapshot_path if selection_snapshot_path.exists() else None,
            )
            return []
        if not score_snapshot_path.exists():
            print(f"Score snapshot not found: {score_snapshot_path}")
            print("Please run first: python3 main.py score --top 30")
            return []
        if not discovery_snapshot_path.exists():
            print(f"Discovery snapshot not found: {discovery_snapshot_path}")
            print("Please run first: python3 main.py discover --limit-per-keyword 5")
            return []

        score_payload = json.loads(score_snapshot_path.read_text(encoding="utf-8"))
        discovery_payload = json.loads(discovery_snapshot_path.read_text(encoding="utf-8"))
        score_items = score_payload.get("scores", [])
        candidate_items = discovery_payload.get("candidates", [])
        candidates_by_name = {
            candidate.full_name: candidate
            for candidate in [self._parse_repo_candidate(item) for item in candidate_items]
        }
        scores_by_name = {
            str(item.get("full_name") or ""): item
            for item in score_items
            if isinstance(item, dict) and item.get("full_name")
        }

        selected_candidates: list[RepoCandidate] = []
        for full_name in selected_repo_full_names:
            candidate = candidates_by_name.get(full_name)
            if candidate is None:
                candidate = self._candidate_from_score_item(scores_by_name.get(full_name, {"full_name": full_name}))
            selected_candidates.append(candidate)

        github_client = GitHubClient(token=self.settings.github_personal_access_token)
        research_service = RepoResearchService(github_client=github_client)
        notes = research_service.research_selected_repos(selected_candidates)

        print(f"Researched {len(notes)} selected repositories.")
        self._print_research_summaries(notes)
        self._save_research_outputs(
            notes=notes,
            source_score_snapshot_path=score_snapshot_path,
            source_discovery_snapshot_path=discovery_snapshot_path,
            source_selection_snapshot_path=selection_snapshot_path if selection_snapshot_path.exists() else None,
        )
        return notes

    def select_article_projects(
        self,
        article_top: int = 3,
        cooldown_days: int = 30,
        ignore_history: bool = False,
        allow_recent_fallback: bool = False,
        prefer_growth_projects: bool | None = None,
    ) -> dict[str, Any]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        score_snapshot_path = snapshots_dir / "score_latest.json"
        if not score_snapshot_path.exists():
            print(f"Score snapshot not found: {score_snapshot_path}")
            print("Please run first: python3 main.py score --top 30")
            return {}

        score_payload = json.loads(score_snapshot_path.read_text(encoding="utf-8"))
        scored_repos = [self._parse_repo_score(item) for item in score_payload.get("scores", [])]
        selector = ArticleSelectionService(
            history_path=self.settings.workspace_dir / "article_history.json",
            prefer_growth_projects=self.settings.prefer_growth_projects
            if prefer_growth_projects is None
            else prefer_growth_projects,
        )
        history = selector.load_history()
        selected_repos, summary = selector.select_repos(
            scored_repos=scored_repos,
            research_notes=None,
            article_top=article_top,
            article_history=history,
            cooldown_days=cooldown_days,
            allow_recent_fallback=allow_recent_fallback,
            ignored_history=ignore_history,
        )

        if not selected_repos:
            print("No repositories selected for article writing.")

        self._save_selection_outputs(
            summary=summary,
            source_score_snapshot_path=score_snapshot_path,
            source_research_snapshot_path=None,
        )
        for warning in selector.warnings:
            print(f"Warning: {warning}")
        print(
            f"Selected {len(selected_repos)} article projects: "
            f"{', '.join(selected_repos) if selected_repos else '-'}"
        )
        return summary

    def plan_angles(self, top: int = 3, selected_repo_full_names: list[str] | None = None) -> List[TopicAngle]:
        research_snapshot_path = self.settings.workspace_dir / "snapshots" / "research_latest.json"
        if not research_snapshot_path.exists():
            print(f"Research snapshot not found: {research_snapshot_path}")
            print("Please run first: python3 main.py research --top 3")
            return []

        payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        note_items = payload.get("notes", [])
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        research_notes = self._filter_by_selected_names(research_notes, selected_repo_full_names)
        if not research_notes:
            print("No research notes available for angle planning.")
            return []

        llm_service = LLMService(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
        )
        planner = AnglePlannerService(llm_service=llm_service)
        angles = planner.plan_angles(research_notes, top=top)

        print(f"Generated {len(angles)} topic angle plans.")
        print(f"LLM available: {'yes' if llm_service.is_available() else 'no'}")
        print(f"Used LLM successfully: {'yes' if planner.used_llm else 'no'}")
        for warning in planner.warnings:
            print(f"Warning: {warning}")
        self._print_angle_summaries(angles)
        self._save_angle_outputs(
            angles=angles,
            source_research_snapshot_path=research_snapshot_path,
            used_llm=planner.used_llm,
            llm_available=llm_service.is_available(),
            warnings=planner.warnings,
        )
        return angles

    def plan_content(self, top: int = 3, selected_repo_full_names: list[str] | None = None) -> list[dict[str, Any]]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        research_snapshot_path = snapshots_dir / "research_latest.json"
        angles_snapshot_path = snapshots_dir / "angles_latest.json"

        if not research_snapshot_path.exists():
            print(f"Research snapshot not found: {research_snapshot_path}")
            print("Please run first: python3 main.py research --top 3")
            return []

        research_payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        note_items = research_payload.get("notes", [])
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        research_notes = self._filter_by_selected_names(research_notes, selected_repo_full_names)[: max(0, top)]
        if not research_notes:
            print("No research notes available for content planning.")
            return []

        angles: list[TopicAngle] = []
        if angles_snapshot_path.exists():
            angles_payload = json.loads(angles_snapshot_path.read_text(encoding="utf-8"))
            angle_items = angles_payload.get("angles", [])
            angles = [self._parse_topic_angle(item) for item in angle_items]
            angles = self._filter_by_selected_names(angles, selected_repo_full_names)
        else:
            print(f"Angles snapshot not found: {angles_snapshot_path}")
            print("Content planning will run without topic angle input.")

        llm_service = LLMService(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
        )
        planner = ContentPlanningService(llm_service=llm_service)
        plans = planner.build_content_plans(research_notes, angles)

        print(f"Generated {len(plans)} content planning artifacts.")
        print(f"LLM available: {'yes' if llm_service.is_available() else 'no'}")
        print(f"Used LLM successfully: {'yes' if planner.used_llm else 'no'}")
        for warning in planner.warnings:
            print(f"Warning: {warning}")
        self._print_content_plan_summaries(plans)
        self._save_content_plan_outputs(
            plans=plans,
            source_research_snapshot_path=research_snapshot_path,
            source_angles_snapshot_path=angles_snapshot_path if angles_snapshot_path.exists() else None,
            llm_available=llm_service.is_available(),
            used_llm=planner.used_llm,
            warnings=planner.warnings,
        )
        return plans

    def write_articles(self, top: int = 3, selected_repo_full_names: list[str] | None = None) -> List[ArticleDraft]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        angles_snapshot_path = snapshots_dir / "angles_latest.json"
        research_snapshot_path = snapshots_dir / "research_latest.json"
        content_plan_snapshot_path = snapshots_dir / "content_plan_latest.json"

        if not research_snapshot_path.exists():
            print(f"Research snapshot not found: {research_snapshot_path}")
            print("Please run first: python3 main.py research --top 3")
            return []
        if not angles_snapshot_path.exists():
            print(f"Angles snapshot not found: {angles_snapshot_path}")
            print("Please run first: python3 main.py angles --top 3")
            return []

        angles_payload = json.loads(angles_snapshot_path.read_text(encoding="utf-8"))
        research_payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        angle_items = angles_payload.get("angles", [])
        note_items = research_payload.get("notes", [])
        angles = [self._parse_topic_angle(item) for item in angle_items]
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        angles = self._filter_by_selected_names(angles, selected_repo_full_names)
        research_notes = self._filter_by_selected_names(research_notes, selected_repo_full_names)
        content_plans: list[dict] | None = None
        if content_plan_snapshot_path.exists():
            content_plan_payload = json.loads(content_plan_snapshot_path.read_text(encoding="utf-8"))
            plan_items = content_plan_payload.get("plans", [])
            if isinstance(plan_items, list):
                content_plans = [item for item in plan_items if isinstance(item, dict)]
                content_plans = self._filter_dicts_by_selected_names(content_plans, selected_repo_full_names)
                print(f"Loaded {len(content_plans)} content plans for article writing.")
        else:
            print(f"Content plan snapshot not found: {content_plan_snapshot_path}")
            print("Article writing will use the legacy angle + research path.")

        if not angles:
            print("No topic angles available for article writing.")
            return []
        if not research_notes:
            print("No research notes available for article writing.")
            return []

        llm_service = LLMService(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
        )
        writer = ArticleWriterService(llm_service=llm_service)
        drafts = writer.write_articles(angles, research_notes, top=top, content_plans=content_plans)

        print(f"Generated {len(drafts)} article drafts.")
        print(f"LLM available: {'yes' if llm_service.is_available() else 'no'}")
        print(f"Used LLM successfully: {'yes' if writer.used_llm else 'no'}")
        for warning in writer.warnings:
            print(f"Warning: {warning}")
        self._print_article_summaries(drafts)
        self._save_article_outputs(
            drafts=drafts,
            source_angles_snapshot_path=angles_snapshot_path,
            source_research_snapshot_path=research_snapshot_path,
            used_llm=writer.used_llm,
            llm_available=llm_service.is_available(),
            warnings=writer.warnings,
        )
        return drafts

    def review_articles(
        self,
        top: int = 3,
        threshold: float = 80,
        selected_repo_full_names: list[str] | None = None,
    ) -> List[FinalArticle]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        articles_snapshot_path = snapshots_dir / "articles_latest.json"
        research_snapshot_path = snapshots_dir / "research_latest.json"
        angles_snapshot_path = snapshots_dir / "angles_latest.json"
        content_plan_snapshot_path = snapshots_dir / "content_plan_latest.json"

        missing_paths = [
            path
            for path in [articles_snapshot_path, research_snapshot_path, angles_snapshot_path]
            if not path.exists()
        ]
        if missing_paths:
            for path in missing_paths:
                print(f"Required snapshot not found: {path}")
            print("Please run first: python3 main.py write-articles --top 3")
            return []

        articles_payload = json.loads(articles_snapshot_path.read_text(encoding="utf-8"))
        research_payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        angles_payload = json.loads(angles_snapshot_path.read_text(encoding="utf-8"))

        article_items = articles_payload.get("articles", articles_payload.get("drafts", []))
        note_items = research_payload.get("notes", [])
        angle_items = angles_payload.get("angles", [])
        drafts = [self._parse_article_draft(item) for item in article_items]
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        angles = [self._parse_topic_angle(item) for item in angle_items]
        content_plans = self._load_content_plans(content_plan_snapshot_path)
        drafts = self._filter_by_selected_names(drafts, selected_repo_full_names)[: max(0, top)]
        research_notes = self._filter_by_selected_names(research_notes, selected_repo_full_names)
        angles = self._filter_by_selected_names(angles, selected_repo_full_names)
        content_plans = self._filter_dicts_by_selected_names(content_plans, selected_repo_full_names)

        if not drafts:
            print("No article drafts available for review.")
            return []
        if not research_notes:
            print("No research notes available for article review.")
            return []
        if not angles:
            print("No topic angles available for article review.")
            return []

        llm_service = LLMService(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
        )
        editor = EditorService(llm_service=llm_service, pass_threshold=threshold)
        reviews = editor.review_articles(drafts, research_notes, angles)
        final_articles = editor.revise_articles(drafts, reviews, research_notes, angles)
        humanization_editor = HumanizationEditorService(llm_service=llm_service)
        final_articles = humanization_editor.process_articles(final_articles, drafts, research_notes, content_plans)
        publish_polisher = PublishPolisherService(llm_service=llm_service)
        final_articles = publish_polisher.polish_articles(final_articles, research_notes, content_plans)
        article_quality_evaluator = ArticleQualityEvaluator(llm_service=llm_service)
        final_articles = article_quality_evaluator.evaluate_articles(final_articles, research_notes, content_plans)

        print(f"Reviewed {len(reviews)} article drafts.")
        print(f"LLM available: {'yes' if llm_service.is_available() else 'no'}")
        print(f"Used LLM for review: {'yes' if editor.used_llm_review else 'no'}")
        print(f"Used LLM for revision: {'yes' if editor.used_llm_revision else 'no'}")
        print(f"Used LLM for humanization: {'yes' if humanization_editor.used_llm else 'no'}")
        print(f"Used fallback humanization: {'yes' if humanization_editor.used_fallback_rewrite else 'no'}")
        print(f"Used LLM for publish polish: {'yes' if publish_polisher.used_llm else 'no'}")
        print(f"Used LLM for article quality: {'yes' if article_quality_evaluator.used_llm else 'no'}")
        for warning in editor.warnings:
            print(f"Warning: {warning}")
        for warning in humanization_editor.warnings:
            print(f"Warning: {warning}")
        for warning in publish_polisher.warnings:
            print(f"Warning: {warning}")
        for warning in article_quality_evaluator.warnings:
            print(f"Warning: {warning}")
        self._print_review_summaries(final_articles)
        self._print_article_quality_summaries(final_articles)
        self._save_review_outputs(
            reviews=reviews,
            final_articles=final_articles,
            source_articles_snapshot_path=articles_snapshot_path,
            source_research_snapshot_path=research_snapshot_path,
            source_angles_snapshot_path=angles_snapshot_path,
            llm_available=llm_service.is_available(),
            used_llm_review=editor.used_llm_review,
            used_llm_revision=editor.used_llm_revision,
            pass_threshold=editor.pass_threshold,
            warnings=editor.warnings
            + humanization_editor.warnings
            + publish_polisher.warnings
            + article_quality_evaluator.warnings,
            humanization_llm_used=humanization_editor.used_llm,
            humanization_fallback_used=humanization_editor.used_fallback_rewrite,
        )
        self._save_humanization_outputs(
            final_articles=final_articles,
            source_final_articles_snapshot_path=snapshots_dir / "final_articles_latest.json",
            source_articles_snapshot_path=articles_snapshot_path,
            source_research_snapshot_path=research_snapshot_path,
            source_content_plan_snapshot_path=content_plan_snapshot_path if content_plan_snapshot_path.exists() else None,
            llm_available=llm_service.is_available(),
            used_llm=humanization_editor.used_llm,
            used_fallback=humanization_editor.used_fallback_rewrite,
            warnings=humanization_editor.warnings,
            rewrite_final_articles=False,
        )
        self._save_publish_polish_outputs(
            final_articles=final_articles,
            source_final_articles_snapshot_path=snapshots_dir / "final_articles_latest.json",
            source_research_snapshot_path=research_snapshot_path,
            source_content_plan_snapshot_path=content_plan_snapshot_path if content_plan_snapshot_path.exists() else None,
            llm_available=llm_service.is_available(),
            used_llm=publish_polisher.used_llm,
            warnings=publish_polisher.warnings,
            rewrite_final_articles=True,
        )
        self._save_article_quality_outputs(
            final_articles=final_articles,
            source_final_articles_snapshot_path=snapshots_dir / "final_articles_latest.json",
            source_research_snapshot_path=research_snapshot_path,
            source_content_plan_snapshot_path=content_plan_snapshot_path if content_plan_snapshot_path.exists() else None,
            llm_available=llm_service.is_available(),
            used_llm=article_quality_evaluator.used_llm,
            warnings=article_quality_evaluator.warnings,
            rewrite_final_articles=True,
        )
        return final_articles

    def humanize_articles(self, top: int = 3) -> List[FinalArticle]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        final_articles_snapshot_path = snapshots_dir / "final_articles_latest.json"
        articles_snapshot_path = snapshots_dir / "articles_latest.json"
        research_snapshot_path = snapshots_dir / "research_latest.json"
        content_plan_snapshot_path = snapshots_dir / "content_plan_latest.json"

        missing_paths = [
            path
            for path in [final_articles_snapshot_path, articles_snapshot_path, research_snapshot_path]
            if not path.exists()
        ]
        if missing_paths:
            for path in missing_paths:
                print(f"Required snapshot not found: {path}")
            print("Please run first: python3 main.py review-articles --top 3")
            return []

        final_payload = json.loads(final_articles_snapshot_path.read_text(encoding="utf-8"))
        articles_payload = json.loads(articles_snapshot_path.read_text(encoding="utf-8"))
        research_payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        final_items = final_payload.get("articles", [])
        article_items = articles_payload.get("articles", articles_payload.get("drafts", []))
        note_items = research_payload.get("notes", [])

        final_articles = [self._parse_final_article(item) for item in final_items[: max(0, top)]]
        drafts = [self._parse_article_draft(item) for item in article_items]
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        content_plans = self._load_content_plans(content_plan_snapshot_path)

        if not final_articles:
            print("No final articles available for humanization.")
            return []

        llm_service = LLMService(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
        )
        humanization_editor = HumanizationEditorService(llm_service=llm_service)
        humanized_articles = humanization_editor.process_articles(final_articles, drafts, research_notes, content_plans)

        print(f"Humanized {len(humanized_articles)} final articles.")
        print(f"LLM available: {'yes' if llm_service.is_available() else 'no'}")
        print(f"Used LLM for humanization: {'yes' if humanization_editor.used_llm else 'no'}")
        print(f"Used fallback humanization: {'yes' if humanization_editor.used_fallback_rewrite else 'no'}")
        for warning in humanization_editor.warnings:
            print(f"Warning: {warning}")
        self._print_humanization_summaries(humanized_articles)
        self._save_humanization_outputs(
            final_articles=humanized_articles,
            source_final_articles_snapshot_path=final_articles_snapshot_path,
            source_articles_snapshot_path=articles_snapshot_path,
            source_research_snapshot_path=research_snapshot_path,
            source_content_plan_snapshot_path=content_plan_snapshot_path if content_plan_snapshot_path.exists() else None,
            llm_available=llm_service.is_available(),
            used_llm=humanization_editor.used_llm,
            used_fallback=humanization_editor.used_fallback_rewrite,
            warnings=humanization_editor.warnings,
            rewrite_final_articles=True,
        )
        return humanized_articles

    def polish_for_publish(self, top: int = 3) -> List[FinalArticle]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        final_articles_snapshot_path = snapshots_dir / "final_articles_latest.json"
        research_snapshot_path = snapshots_dir / "research_latest.json"
        content_plan_snapshot_path = snapshots_dir / "content_plan_latest.json"

        missing_paths = [
            path
            for path in [final_articles_snapshot_path, research_snapshot_path]
            if not path.exists()
        ]
        if missing_paths:
            for path in missing_paths:
                print(f"Required snapshot not found: {path}")
            print("Please run first: python3 main.py review-articles --top 3")
            return []

        final_payload = json.loads(final_articles_snapshot_path.read_text(encoding="utf-8"))
        research_payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        final_items = final_payload.get("articles", [])
        note_items = research_payload.get("notes", [])
        final_articles = [self._parse_final_article(item) for item in final_items[: max(0, top)]]
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        content_plans = self._load_content_plans(content_plan_snapshot_path)

        if not final_articles:
            print("No final articles available for publish polish.")
            return []

        llm_service = LLMService(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.openai_model,
        )
        publish_polisher = PublishPolisherService(llm_service=llm_service)
        polished_articles = publish_polisher.polish_articles(final_articles, research_notes, content_plans)

        print(f"Publish-polished {len(polished_articles)} final articles.")
        print(f"LLM available: {'yes' if llm_service.is_available() else 'no'}")
        print(f"Used LLM for publish polish: {'yes' if publish_polisher.used_llm else 'no'}")
        for warning in publish_polisher.warnings:
            print(f"Warning: {warning}")
        self._print_publish_polish_summaries(polished_articles)
        self._save_publish_polish_outputs(
            final_articles=polished_articles,
            source_final_articles_snapshot_path=final_articles_snapshot_path,
            source_research_snapshot_path=research_snapshot_path,
            source_content_plan_snapshot_path=content_plan_snapshot_path if content_plan_snapshot_path.exists() else None,
            llm_available=llm_service.is_available(),
            used_llm=publish_polisher.used_llm,
            warnings=publish_polisher.warnings,
            rewrite_final_articles=True,
        )
        return polished_articles

    def package_articles(
        self,
        top: int | None = 3,
        safe_names: list[str] | None = None,
        full_names: list[str] | None = None,
    ) -> list[ArticlePackage]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        final_articles_snapshot_path = snapshots_dir / "final_articles_latest.json"
        research_snapshot_path = snapshots_dir / "research_latest.json"
        content_plan_snapshot_path = snapshots_dir / "content_plan_latest.json"

        missing_paths = [
            path
            for path in [final_articles_snapshot_path, research_snapshot_path]
            if not path.exists()
        ]
        if missing_paths:
            for path in missing_paths:
                print(f"Required snapshot not found: {path}")
            print("Please run first: python3 main.py polish-for-publish --top 3")
            custom_packages = self._package_matching_custom_articles(
                safe_names=safe_names,
                full_names=full_names,
            )
            return custom_packages

        final_payload = json.loads(final_articles_snapshot_path.read_text(encoding="utf-8"))
        research_payload = json.loads(research_snapshot_path.read_text(encoding="utf-8"))
        final_items = final_payload.get("articles", [])
        note_items = research_payload.get("notes", [])
        final_articles = [self._parse_final_article(item) for item in final_items]
        final_articles = self._select_articles_for_packaging(final_articles, top, safe_names, full_names)
        research_notes = [self._parse_repo_research_note(item) for item in note_items]
        content_plans = self._load_content_plans(content_plan_snapshot_path)

        packages: list[ArticlePackage] = []
        run_date = self._output_date_from_payload(final_payload)
        if final_articles:
            packages = self._package_final_articles(
                final_articles=final_articles,
                research_notes=research_notes,
                content_plans=content_plans,
                run_date=run_date,
            )
            print(f"Packaged {len(packages)} final articles.")
            self._print_article_package_summaries(packages)
            self._save_article_package_outputs(
                packages=packages,
                run_date=run_date,
                source_final_articles_snapshot_path=final_articles_snapshot_path,
                source_research_snapshot_path=research_snapshot_path,
                source_content_plan_snapshot_path=content_plan_snapshot_path if content_plan_snapshot_path.exists() else None,
            )

        custom_packages = self._package_matching_custom_articles(
            safe_names=safe_names,
            full_names=full_names,
        )
        if custom_packages:
            print(f"Packaged {len(custom_packages)} custom articles.")
            self._print_article_package_summaries(custom_packages)
        all_packages = packages + custom_packages
        if not all_packages:
            print("No final articles available for packaging.")
        return all_packages

    def _build_custom_topic_angle(
        self,
        note: RepoResearchNote,
        direction_text: str | None = None,
        custom_direction: CustomArticleDirection | None = None,
    ) -> TopicAngle:
        project_name = note.full_name.split("/")[-1]
        direction = (direction_text or "").strip()
        parsed_direction = custom_direction or CustomArticleDirection(raw_text=direction)
        selected_angle = (
            self._truncate_for_custom(parsed_direction.core_angle or direction, 120)
            if direction
            else f"从使用者视角分享 {project_name} 的项目特点和适合场景"
        )
        one_liner = self._truncate_for_custom(
            note.description or note.readme_summary or f"{project_name} 是一个值得进一步了解的开源项目。",
            180,
        )
        selling_points = parsed_direction.must_include + note.tool_use_cases[:3] + note.readme_key_points[:4]
        if note.language:
            selling_points.append(f"主要语言是 {note.language}，适合关注相关技术栈的读者先看实现。")
        title_candidates = [
            TitleCandidate(
                title=f"{project_name}：一个值得顺手点开的开源项目",
                style="project_share",
                reason="保留项目名和分享口吻，不用 star 数标题模板。",
            ),
            TitleCandidate(
                title=f"用程序员视角看看 {project_name}",
                style="hands_on_observation",
                reason="强调使用者视角，适合指定项目文章。",
            ),
        ]
        target_readers = self._dedupe_markdown_items(
            [
                parsed_direction.target_reader or "",
                "喜欢折腾开源工具的开发者",
                "正在给团队找候选工具的技术同学",
            ]
        )
        perspective = parsed_direction.writing_perspective or "使用者视角"
        opening_hook = (
            f"从{perspective}看，{project_name} 最值得聊的不是功能有多少，而是它能不能顺手放进真实工作流。"
            if parsed_direction.writing_perspective or parsed_direction.core_angle
            else f"有些项目适合先收藏，有些项目会让人想马上点进去看一眼。{project_name} 更接近后者。"
        )
        return TopicAngle(
            full_name=note.full_name,
            html_url=note.html_url,
            project_name=project_name,
            selected_angle=selected_angle,
            one_liner=one_liner,
            target_readers=target_readers,
            reader_pain_points=note.tool_use_cases[:3] or ["想快速判断一个开源项目是否值得继续看"],
            selling_points=self._dedupe_markdown_items(selling_points)[:6],
            title_candidates=title_candidates,
            opening_hook=opening_hook,
            article_outline=[
                "从一个具体使用场景切入",
                "解释项目最值得看的 2-3 个特点",
                "说明适合哪些读者继续打开项目页",
                "文末只保留项目地址",
            ],
            cover_prompt=f"技术公众号封面，主题是 GitHub 开源项目 {project_name}，干净、现代、偏开发者工具气质。",
            source_links=[note.html_url],
            factual_warnings=note.risks,
        )

    def _ensure_custom_article_project_address_only(
        self,
        article: FinalArticle,
        note: RepoResearchNote,
    ) -> FinalArticle:
        repo_url = note.html_url.rstrip("/")
        content = article.content_markdown.strip()
        content = re.sub(r"\n*项目地址：\s*https?://\S+\s*$", "", content, flags=re.MULTILINE).strip()
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = f"{content.rstrip()}\n\n项目地址：{repo_url}\n"
        report = article.publish_polish_report
        if report is not None:
            report.kept_links = [repo_url]
        return article.copy(
            update={
                "content_markdown": content,
                "word_count": len(re.sub(r"\s+", "", content)),
                "source_links": [repo_url],
                "publish_polish_report": report,
                "publish_ready": article.publish_ready,
            }
        )

    def _apply_custom_direction_to_content_plan(
        self,
        content_plan: dict[str, Any],
        custom_direction: CustomArticleDirection,
    ) -> dict[str, Any]:
        direction_payload = self._model_dump(custom_direction)
        raw_text = custom_direction.raw_text.strip()
        content_plan["direction_text"] = raw_text
        content_plan["custom_direction"] = direction_payload
        content_plan["parsed_direction"] = direction_payload
        content_plan["direction_used_in_writing"] = bool(raw_text)
        if not raw_text:
            return content_plan

        avoid_rules = self._direction_avoid_rules(custom_direction)
        must_include = self._dedupe_markdown_items(
            [custom_direction.core_angle or ""]
            + custom_direction.must_include
            + [
                preference
                for preference in custom_direction.content_preferences
                if not any(marker in preference for marker in ["不要", "少写", "避免", "别写", "不应", "不能"])
            ]
        )

        brief = content_plan.get("brief")
        if isinstance(brief, dict):
            if custom_direction.target_reader:
                brief["target_reader"] = custom_direction.target_reader
            if custom_direction.core_angle:
                brief["recommended_angle"] = custom_direction.core_angle
            if custom_direction.writing_perspective:
                brief["opening_direction"] = (
                    f"从{custom_direction.writing_perspective}切入，先写真实使用感，再自然带出项目特点。"
                )
                brief["narrative_pattern"] = "scene_first"
            brief["must_include"] = self._dedupe_markdown_items(must_include + self._string_list(brief.get("must_include")))[:12]
            brief["should_avoid"] = self._dedupe_markdown_items(avoid_rules + self._string_list(brief.get("should_avoid")))
            brief["title_direction"] = self._filter_custom_direction_avoids(
                self._dedupe_markdown_items(custom_direction.title_preferences + self._string_list(brief.get("title_direction"))),
                custom_direction,
            )[:10]
            if custom_direction.tone_preferences:
                brief["tone"] = "；".join(custom_direction.tone_preferences)
            brief["human_tone_rules"] = self._dedupe_markdown_items(
                custom_direction.tone_preferences + self._string_list(brief.get("human_tone_rules"))
            )
            paragraph_plan = self._filter_custom_direction_avoids(
                self._string_list(brief.get("paragraph_plan")) or self._string_list(brief.get("suggested_structure")),
                custom_direction,
            )
            if custom_direction.core_angle:
                paragraph_plan = self._dedupe_markdown_items([f"优先围绕用户指定角度展开：{custom_direction.core_angle}"] + paragraph_plan)
            brief["paragraph_plan"] = paragraph_plan
            brief["suggested_structure"] = paragraph_plan
            writer_persona = brief.get("writer_persona")
            if not isinstance(writer_persona, dict):
                writer_persona = {}
            writer_persona["persona"] = "programmer"
            writer_persona["voice"] = custom_direction.writing_perspective or writer_persona.get("voice") or "像一个经常折腾开发工具的程序员"
            writer_persona["article_goal"] = custom_direction.core_angle or writer_persona.get("article_goal") or "按用户指定方向完成项目分享"
            writer_persona["do"] = self._dedupe_markdown_items(
                must_include
                + custom_direction.tone_preferences
                + self._string_list(writer_persona.get("do"))
            )
            writer_persona["dont"] = self._dedupe_markdown_items(avoid_rules + self._string_list(writer_persona.get("dont")))
            brief["writer_persona"] = writer_persona
            title_strategy = brief.get("title_strategy")
            if isinstance(title_strategy, dict):
                title_strategy["directions"] = self._dedupe_markdown_items(
                    custom_direction.title_preferences + self._string_list(title_strategy.get("directions"))
                )
                title_strategy["banned_templates"] = self._dedupe_markdown_items(
                    avoid_rules + self._string_list(title_strategy.get("banned_templates"))
                )

        appeal = content_plan.get("appeal")
        if isinstance(appeal, dict):
            appeal["top_selling_points"] = self._dedupe_markdown_items(
                must_include + self._string_list(appeal.get("top_selling_points"))
            )[:5]
            appeal["recommended_focus"] = self._dedupe_markdown_items(
                must_include + self._string_list(appeal.get("recommended_focus"))
            )[:8]
            appeal["avoid_overemphasis"] = self._dedupe_markdown_items(
                avoid_rules + self._string_list(appeal.get("avoid_overemphasis"))
            )
            if custom_direction.core_angle:
                appeal["appeal_summary"] = self._truncate_for_custom(
                    f"按用户指定方向，这篇文章优先写：{custom_direction.core_angle}。"
                    f"{appeal.get('appeal_summary') or ''}",
                    220,
                )
            if custom_direction.writing_perspective:
                appeal["primary_hook"] = self._truncate_for_custom(
                    f"从{custom_direction.writing_perspective}看，这个项目最值得聊的是"
                    f"{custom_direction.core_angle or '它放进日常工作流后的实际感受'}。",
                    180,
                )
            scenarios = self._string_list(appeal.get("practical_scenarios"))
            if custom_direction.writing_perspective:
                scenarios.insert(0, custom_direction.writing_perspective)
            appeal["practical_scenarios"] = self._dedupe_markdown_items(scenarios)[:6]

        wechat_pattern = content_plan.get("wechat_pattern")
        if isinstance(wechat_pattern, dict):
            required_effect_points = self._dedupe_markdown_items(
                must_include + self._string_list(wechat_pattern.get("required_effect_points"))
            )
            required_examples = self._dedupe_markdown_items(
                [
                    preference
                    for preference in custom_direction.content_preferences
                    if any(marker in preference for marker in ["例子", "场景", "案例", "效果", "提升"])
                ]
                + self._string_list(wechat_pattern.get("required_examples"))
            )
            banned_phrases = self._dedupe_markdown_items(
                avoid_rules + self._string_list(wechat_pattern.get("banned_phrases"))
            )
            wechat_pattern["required_effect_points"] = required_effect_points[:8]
            wechat_pattern["required_examples"] = required_examples[:8]
            wechat_pattern["banned_phrases"] = banned_phrases
            if custom_direction.title_preferences:
                wechat_pattern["title_formula"] = self._truncate_for_custom(
                    "；".join(custom_direction.title_preferences + [str(wechat_pattern.get("title_formula") or "")]),
                    220,
                )
            if custom_direction.core_angle:
                wechat_pattern["lead_hook"] = self._truncate_for_custom(
                    f"开头优先扣住用户指定角度：{custom_direction.core_angle}。{wechat_pattern.get('lead_hook') or ''}",
                    240,
                )

        insight = content_plan.get("insight")
        if isinstance(insight, dict):
            if custom_direction.target_reader:
                insight["ideal_users"] = self._dedupe_markdown_items(
                    [custom_direction.target_reader] + self._string_list(insight.get("ideal_users"))
                )
            insight["standout_points"] = self._dedupe_markdown_items(
                must_include + self._string_list(insight.get("standout_points"))
            )
            insight["not_to_overclaim"] = self._dedupe_markdown_items(
                avoid_rules + self._string_list(insight.get("not_to_overclaim"))
            )

        return content_plan

    def _apply_style_reference_to_content_plan(
        self,
        content_plan: dict[str, Any],
        style_profile: StyleReferenceProfile,
    ) -> dict[str, Any]:
        profile_payload = self._model_dump(style_profile)
        content_plan["style_reference_profile"] = profile_payload
        content_plan["reference_source_names"] = style_profile.source_names
        content_plan["reference_text_count"] = style_profile.raw_count
        content_plan["style_reference_used_in_writing"] = style_profile.raw_count > 0
        if style_profile.raw_count <= 0:
            return content_plan

        safety_rules = self._dedupe_markdown_items(style_profile.do_not_copy + style_profile.originality_rules)
        tone_rules = self._dedupe_markdown_items(
            style_profile.tone_traits
            + style_profile.pacing_traits
            + style_profile.sentence_style
            + ([style_profile.reader_relationship] if style_profile.reader_relationship else [])
        )

        brief = content_plan.get("brief")
        if isinstance(brief, dict):
            existing_title_direction = self._string_list(brief.get("title_direction"))
            brief["title_direction"] = self._dedupe_markdown_items(
                style_profile.title_patterns + existing_title_direction
            )[:10]
            opening_notes = "；".join(style_profile.opening_patterns[:3])
            if opening_notes:
                current_opening = str(brief.get("opening_direction") or "").strip()
                brief["opening_direction"] = self._truncate_for_custom(
                    f"{current_opening} 风格参考开头倾向：{opening_notes}",
                    240,
                )
            existing_structure = self._string_list(brief.get("suggested_structure"))
            brief["suggested_structure"] = self._dedupe_markdown_items(
                style_profile.structure_tendencies + existing_structure
            )[:10]
            brief["paragraph_plan"] = self._dedupe_markdown_items(
                style_profile.structure_tendencies + self._string_list(brief.get("paragraph_plan"))
            )[:10]
            existing_tone = str(brief.get("tone") or "").strip()
            if tone_rules:
                brief["tone"] = self._truncate_for_custom(
                    "；".join(self._dedupe_markdown_items(([existing_tone] if existing_tone else []) + tone_rules[:5])),
                    260,
                )
            brief["human_tone_rules"] = self._dedupe_markdown_items(
                tone_rules + self._string_list(brief.get("human_tone_rules")) + safety_rules
            )
            brief["should_avoid"] = self._dedupe_markdown_items(
                safety_rules + self._string_list(brief.get("should_avoid"))
            )
            writer_persona = brief.get("writer_persona")
            if not isinstance(writer_persona, dict):
                writer_persona = {}
            writer_persona["do"] = self._dedupe_markdown_items(
                tone_rules + style_profile.opening_patterns + style_profile.transition_patterns + self._string_list(writer_persona.get("do"))
            )
            writer_persona["dont"] = self._dedupe_markdown_items(
                safety_rules + self._string_list(writer_persona.get("dont"))
            )
            if style_profile.reader_relationship and not writer_persona.get("voice"):
                writer_persona["voice"] = style_profile.reader_relationship
            brief["writer_persona"] = writer_persona

            title_strategy = brief.get("title_strategy")
            if isinstance(title_strategy, dict):
                title_strategy["directions"] = self._dedupe_markdown_items(
                    style_profile.title_patterns + self._string_list(title_strategy.get("directions"))
                )
                title_strategy["banned_templates"] = self._dedupe_markdown_items(
                    safety_rules + self._string_list(title_strategy.get("banned_templates"))
                )

        content_plan["style_reference_rules"] = {
            "style_controls_how_to_write": True,
            "direction_controls_what_to_write": True,
            "project_facts_and_appeal_control_claims": True,
            "summary": style_profile.summary,
            "do_not_copy": style_profile.do_not_copy,
            "originality_rules": style_profile.originality_rules,
        }
        wechat_pattern = content_plan.get("wechat_pattern")
        if isinstance(wechat_pattern, dict):
            wechat_pattern["allowed_colloquial_phrases"] = self._dedupe_markdown_items(
                self._string_list(wechat_pattern.get("allowed_colloquial_phrases"))
                + style_profile.tone_traits[:3]
            )[:10]
            if style_profile.title_patterns:
                wechat_pattern["title_formula"] = self._truncate_for_custom(
                    "；".join(style_profile.title_patterns[:3] + [str(wechat_pattern.get("title_formula") or "")]),
                    260,
                )
            if style_profile.opening_patterns:
                wechat_pattern["lead_hook"] = self._truncate_for_custom(
                    "；".join(style_profile.opening_patterns[:2] + [str(wechat_pattern.get("lead_hook") or "")]),
                    260,
                )
            wechat_pattern["banned_phrases"] = self._dedupe_markdown_items(
                self._string_list(wechat_pattern.get("banned_phrases"))
                + safety_rules
                + ["参考文章", "仿写", "仿照某文"]
            )
        return content_plan

    def _normalize_style_reference_intent(
        self,
        direction_text: str | None,
        style_profile: StyleReferenceProfile,
    ) -> StyleReferenceProfile:
        text = direction_text or ""
        markers = ["仿写", "洗稿", "照着写", "照搬", "不要被识别出抄袭", "规避抄袭", "躲避检测", "绕过检测"]
        if style_profile.raw_count <= 0 or not any(marker in text for marker in markers):
            return style_profile
        rule = "已将非原创复述类表达转化为原创风格参考：只参考风格，不复制内容。"
        originality_rules = self._dedupe_markdown_items([rule] + style_profile.originality_rules)
        do_not_copy = self._dedupe_markdown_items(
            [
                "不要复制参考文章原句、标题、独特比喻、段落结构或核心表达。",
            ]
            + style_profile.do_not_copy
        )
        return style_profile.copy(update={"originality_rules": originality_rules, "do_not_copy": do_not_copy})

    def _direction_avoid_rules(self, custom_direction: CustomArticleDirection) -> list[str]:
        return self._dedupe_markdown_items(
            custom_direction.avoid_topics
            + [
                preference
                for preference in custom_direction.content_preferences
                if any(marker in preference for marker in ["不要", "少写", "避免", "别写", "不应", "不能"])
            ]
        )

    def _filter_custom_direction_avoids(
        self,
        values: list[str],
        custom_direction: CustomArticleDirection,
    ) -> list[str]:
        avoid_keywords: list[str] = []
        for rule in self._direction_avoid_rules(custom_direction):
            avoid_keywords.extend(re.findall(r"README|教程|功能|实现|标题|夸张|阅读提示|步骤|star|stars|Star|Stars", rule))
            for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", rule):
                if chunk not in {"不要", "少写", "避免", "写成", "太像", "一点"}:
                    avoid_keywords.append(chunk[:6])
        if not avoid_keywords:
            return values
        filtered: list[str] = []
        for value in values:
            compact = re.sub(r"\s+", "", str(value))
            if any(keyword and keyword in compact for keyword in avoid_keywords):
                continue
            filtered.append(value)
        return filtered

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _save_custom_article_outputs(
        self,
        payload: dict[str, Any],
        final_article: FinalArticle,
        research_note: RepoResearchNote,
        content_plan: dict[str, Any],
        markdown_path: Path,
        report_path: Path,
        latest_snapshot_path: Path,
        dated_snapshot_path: Path,
    ) -> None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        latest_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(final_article.content_markdown, encoding="utf-8")
        report_path.write_text(
            self._build_custom_article_report(
                payload=payload,
                final_article=final_article,
                research_note=research_note,
                content_plan=content_plan,
                markdown_path=markdown_path,
            ),
            encoding="utf-8",
        )
        self._write_json(latest_snapshot_path, payload)
        self._write_json(dated_snapshot_path, payload)

    def _package_custom_article(
        self,
        final_article: FinalArticle,
        research_note: RepoResearchNote,
        content_plan: dict[str, Any],
        markdown_path: Path,
        run_date: str,
    ) -> ArticlePackage:
        return self._package_single_article(
            final_article=final_article,
            research_note=research_note,
            content_plan=content_plan,
            run_date=run_date,
            article_path_override=markdown_path,
        )

    def _package_final_articles(
        self,
        final_articles: list[FinalArticle],
        research_notes: list[RepoResearchNote],
        content_plans: list[dict[str, Any]],
        run_date: str,
    ) -> list[ArticlePackage]:
        notes_by_name = {note.full_name: note for note in research_notes}
        plans_by_name = {
            str(plan.get("full_name") or plan.get("repo_full_name") or ""): plan
            for plan in content_plans
            if isinstance(plan, dict)
        }
        return [
            self._package_single_article(
                final_article=article,
                research_note=notes_by_name.get(article.full_name),
                content_plan=plans_by_name.get(article.full_name),
                run_date=run_date,
            )
            for article in final_articles
        ]

    def _package_single_article(
        self,
        final_article: FinalArticle,
        research_note: RepoResearchNote | None,
        content_plan: dict[str, Any] | None,
        run_date: str,
        article_path_override: Path | str | None = None,
    ) -> ArticlePackage:
        safe_name = final_article.full_name.replace("/", "__")
        planner = VisualPlannerService()
        assets = planner.plan_assets(final_article, research_note, content_plan)
        package_dir = self.settings.output_dir / run_date / "assets" / safe_name
        default_article_path = self.settings.output_dir / run_date / "final_articles" / f"{safe_name}.md"
        article_package = ArticlePackage(
            full_name=final_article.full_name,
            title=final_article.title,
            article_path=str(article_path_override or default_article_path),
            packaged_article_path=str(package_dir / "packaged_article.md"),
            assets=assets,
            cover_prompt="",
            package_dir=str(package_dir),
            status="planned",
            notes=VisualPlannerService()._asset_source_notes(assets),
        )
        generator = AssetGeneratorService(project_root=Path(__file__).resolve().parents[1])
        return generator.generate_package(
            article_package=article_package,
            final_article=final_article,
            note=research_note,
            content_plan=content_plan,
            date=run_date,
            article_path_override=article_path_override,
        )

    def _select_articles_for_packaging(
        self,
        final_articles: list[FinalArticle],
        top: int | None,
        safe_names: list[str] | None,
        full_names: list[str] | None,
    ) -> list[FinalArticle]:
        selected_names = self._selected_package_full_names(safe_names=safe_names, full_names=full_names)
        if selected_names:
            order = {full_name: index for index, full_name in enumerate(selected_names)}
            return sorted(
                [article for article in final_articles if article.full_name in order],
                key=lambda article: order[article.full_name],
            )
        if top is None:
            return final_articles
        return final_articles[: max(0, top)]

    def _selected_package_full_names(
        self,
        safe_names: list[str] | None,
        full_names: list[str] | None,
    ) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        for full_name in full_names or []:
            value = str(full_name or "").strip()
            if value and "/" in value and value not in seen:
                seen.add(value)
                selected.append(value)
        for safe_name in safe_names or []:
            value = str(safe_name or "").strip()
            if not value:
                continue
            full_name = value.replace("__", "/", 1)
            if full_name not in seen:
                seen.add(full_name)
                selected.append(full_name)
        return selected

    def _package_matching_custom_articles(
        self,
        safe_names: list[str] | None,
        full_names: list[str] | None,
    ) -> list[ArticlePackage]:
        selected_names = self._selected_package_full_names(safe_names=safe_names, full_names=full_names)
        if not selected_names:
            return []
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        latest_path = snapshots_dir / "custom_article_latest.json"
        if not latest_path.exists():
            return []
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict) or payload.get("status") not in {None, "success"}:
            return []
        full_name = str(payload.get("full_name") or "")
        if full_name not in selected_names:
            return []
        final_payload = payload.get("final_article")
        research_payload = payload.get("research_note")
        if not isinstance(final_payload, dict) or not isinstance(research_payload, dict):
            return []
        final_article = self._parse_final_article(final_payload)
        research_note = self._parse_repo_research_note(research_payload)
        content_plan = payload.get("content_plan") if isinstance(payload.get("content_plan"), dict) else {}
        markdown_path_value = str(payload.get("output_markdown_path") or "").strip()
        run_date = self._custom_package_run_date(payload)
        package = self._package_single_article(
            final_article=final_article,
            research_note=research_note,
            content_plan=content_plan,
            run_date=run_date,
            article_path_override=Path(markdown_path_value) if markdown_path_value else None,
        )
        selected_readme_images = [
            asset.source_url
            for asset in package.assets
            if asset.asset_type == "readme_image" and asset.source_url and asset.status != "failed"
        ]
        visual_assets = [self._model_dump(asset) for asset in package.assets]
        payload.update(
            {
                "package_path": package.packaged_article_path,
                "packaged_article_path": package.packaged_article_path,
                "packaged_article_available": bool(package.packaged_article_path),
                "package_dir": package.package_dir,
                "asset_manifest_path": str(Path(package.package_dir) / "assets.json")
                if package.package_dir
                else None,
                "selected_readme_images": selected_readme_images,
                "asset_count": len(package.assets),
                "visual_assets": visual_assets,
                "article_package": self._model_dump(package),
            }
        )
        dated_path = snapshots_dir / f"{run_date}-custom-article-{full_name.replace('/', '__')}.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        return [package]

    def _custom_package_run_date(self, payload: dict[str, Any]) -> str:
        for key in ["output_markdown_path", "package_path", "packaged_article_path"]:
            value = str(payload.get(key) or "")
            if match := re.search(r"outputs/(\d{4}-\d{2}-\d{2})/", value):
                return match.group(1)
        generated_at = str(payload.get("generated_at") or "")
        if match := re.match(r"^(\d{4}-\d{2}-\d{2})", generated_at):
            return match.group(1)
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _build_custom_article_report(
        self,
        payload: dict[str, Any],
        final_article: FinalArticle,
        research_note: RepoResearchNote,
        content_plan: dict[str, Any],
        markdown_path: Path,
    ) -> str:
        review = final_article.review
        humanization_report = final_article.humanization_report
        publish_report = final_article.publish_polish_report
        article_quality_report = final_article.article_quality_report
        originality_report = final_article.originality_report
        warnings = [str(warning) for warning in payload.get("warnings", [])]
        style_profile = payload.get("style_reference_profile") or {}
        style_used = bool(self._object_field(style_profile, "raw_count", 0))
        visual_assets = payload.get("visual_assets") or self._object_field(payload.get("article_package"), "assets", []) or []
        readme_assets = [
            asset for asset in visual_assets
            if self._object_field(asset, "asset_type") == "readme_image"
        ]
        generated_readme_screenshot = next(
            (
                asset for asset in visual_assets
                if self._object_field(asset, "asset_type") == "github_readme_screenshot"
                and self._object_field(asset, "status") == "generated"
            ),
            None,
        )
        generated_repo_screenshot = next(
            (
                asset for asset in visual_assets
                if self._object_field(asset, "asset_type") == "github_repo_screenshot"
                and self._object_field(asset, "status") == "generated"
            ),
            None,
        )
        failed_screenshots = [
            asset for asset in visual_assets
            if self._object_field(asset, "asset_type") in {"github_readme_screenshot", "github_repo_screenshot"}
            and self._object_field(asset, "status") == "failed"
        ]
        visual_source = (
            "README 图片"
            if readme_assets
            else "GitHub README 页面截图"
            if generated_readme_screenshot
            else "GitHub 仓库首页截图"
            if generated_repo_screenshot
            else "截图失败，发布稿不插图"
            if failed_screenshots
            else "未插图"
        )
        screenshot_status = (
            f"成功：{self._object_field(generated_readme_screenshot, 'output_path')}"
            if generated_readme_screenshot
            else f"成功：{self._object_field(generated_repo_screenshot, 'output_path')}"
            if generated_repo_screenshot
            else "失败：" + "；".join(
                str(self._object_field(asset, "error", "-") or "-") for asset in failed_screenshots
            )
            if failed_screenshots
            else "未尝试"
        )
        lines = [
            "# 指定 GitHub 项目写作报告",
            "",
            "## 基本信息",
            f"- 项目：{final_article.full_name}",
            f"- GitHub：{final_article.html_url}",
            f"- 文章标题：{final_article.title}",
            f"- 生成模式：{final_article.generation_mode}",
            f"- 输出 Markdown：{markdown_path}",
            f"- 发布包：{payload.get('package_path') or '-'}",
            f"- 是否生成发布包：{'是' if payload.get('packaged_article_available') else '否'}",
            f"- 是否使用 README 图片：{'是' if payload.get('selected_readme_images') else '否'}",
            f"- README 图片数量：{len(readme_assets)}",
            f"- 素材数量：{payload.get('asset_count', 0) or 0}",
            f"- 配图来源：{visual_source}",
            f"- 截图状态：{screenshot_status}",
            f"- 用户方向：{payload.get('direction_text') or '-'}",
            "",
            "配图素材：",
        ]
        selected_readme_images = [str(item) for item in payload.get("selected_readme_images", []) if str(item).strip()]
        if selected_readme_images:
            lines.extend(self._markdown_bullets(selected_readme_images[:3]))
        elif generated_readme_screenshot or generated_repo_screenshot:
            screenshot_asset = generated_readme_screenshot or generated_repo_screenshot
            lines.extend(
                self._markdown_bullets(
                    [
                        f"{self._object_field(screenshot_asset, 'asset_type')}：{self._object_field(screenshot_asset, 'output_path')}",
                        f"来源 URL：{self._object_field(screenshot_asset, 'source_url')}",
                    ]
                )
            )
        elif failed_screenshots:
            lines.extend(
                self._markdown_bullets(
                    [
                        f"{self._object_field(asset, 'asset_type')} 失败：{self._object_field(asset, 'error', '-') or '-'}"
                        for asset in failed_screenshots
                    ]
                )
            )
        else:
            lines.append("- 未插图（no_suitable_image）")
        lines.extend(
            [
                "",
            "## 用户方向解析结果",
            f"- 原始方向文本：{payload.get('direction_text') or '-'}",
            f"- 已用于写作：{'是' if content_plan.get('direction_used_in_writing') else '否'}",
            f"- 目标读者：{self._object_field(payload.get('custom_direction'), 'target_reader', '-') or '-'}",
            f"- 写作视角：{self._object_field(payload.get('custom_direction'), 'writing_perspective', '-') or '-'}",
            f"- 核心角度：{self._object_field(payload.get('custom_direction'), 'core_angle', '-') or '-'}",
            "",
            "必写 / 重点：",
            ]
        )
        direction_payload = payload.get("custom_direction") or {}
        lines.extend(self._markdown_bullets(self._object_field(direction_payload, "must_include", [])))
        lines.extend(["", "避免 / 少写："])
        lines.extend(self._markdown_bullets(self._object_field(direction_payload, "avoid_topics", [])))
        lines.extend(["", "语气要求："])
        lines.extend(self._markdown_bullets(self._object_field(direction_payload, "tone_preferences", [])))
        lines.extend(["", "标题要求："])
        lines.extend(self._markdown_bullets(self._object_field(direction_payload, "title_preferences", [])))
        lines.extend(["", "内容取舍："])
        lines.extend(self._markdown_bullets(self._object_field(direction_payload, "content_preferences", [])))
        lines.extend(
            [
                "",
                "## 参考文章风格画像",
                f"- 是否使用风格参考：{'是' if style_used else '否'}",
                f"- 参考来源数量：{self._object_field(style_profile, 'raw_count', 0) or 0}",
                f"- 参考来源：{'; '.join(self._object_field(style_profile, 'source_names', []) or []) or '-'}",
                f"- 风格画像摘要：{self._object_field(style_profile, 'summary', '-') or '-'}",
                "",
                "语气特征：",
            ]
        )
        lines.extend(self._markdown_bullets(self._object_field(style_profile, "tone_traits", [])))
        lines.extend(["", "标题倾向："])
        lines.extend(self._markdown_bullets(self._object_field(style_profile, "title_patterns", [])))
        lines.extend(["", "原创规则："])
        lines.extend(self._markdown_bullets(self._object_field(style_profile, "originality_rules", [])))
        lines.extend(["", "禁止复制："])
        lines.extend(self._markdown_bullets(self._object_field(style_profile, "do_not_copy", [])))
        lines.extend(
            [
                "",
                "## 链路结果",
                f"- 内容策划模式：{content_plan.get('planning_mode') or '-'}",
                f"- 评审总分：{review.total_score:.2f}",
                f"- 评审通过：{'是' if review.pass_review else '否'}",
                f"- 去 AI 味：{final_article.humanization_mode or '-'}",
                f"- 发布清理：{final_article.publish_polish_mode or '-'}",
                f"- 发布就绪：{'是' if final_article.publish_ready else '否'}",
                f"- 文章质量评分：{final_article.quality_score:.2f}",
                f"- 质量可发布：{'是' if final_article.quality_publish_ready else '否'}",
                f"- 原创性检查：{'是' if final_article.originality_checked else '否'}",
                f"- 相似度保护通过：{'是' if final_article.originality_passed else '否'}",
                f"- 字数估算：{final_article.word_count}",
                "",
                "## 调研摘要",
                f"- 描述：{research_note.description or '-'}",
                f"- Stars/Forks：{research_note.stars}/{research_note.forks}",
                f"- 主要语言：{research_note.language or '-'}",
                f"- License：{research_note.license_name or '-'}",
                f"- 项目类型：{research_note.project_kind or '-'}",
                f"- README 摘要：{self._markdown_table_cell(research_note.readme_summary[:300]) or '-'}",
                "",
                "## 内容规划重点",
                "",
            ]
        )
        appeal = content_plan.get("appeal")
        if appeal is not None:
            lines.extend(
                [
                    f"- 主钩子：{self._object_field(appeal, 'primary_hook', '-')}",
                    f"- 吸引力摘要：{self._object_field(appeal, 'appeal_summary', '-')}",
                    "",
                    "重点卖点：",
                ]
            )
            lines.extend(self._markdown_bullets(self._object_field(appeal, "top_selling_points", [])))
            lines.extend(["", "适合场景："])
            lines.extend(self._markdown_bullets(self._object_field(appeal, "practical_scenarios", [])))
        else:
            lines.append("- -")
        impact = content_plan.get("impact")
        lines.extend(["", "## 项目作用与效果", ""])
        if impact is not None:
            lines.extend(
                [
                    f"- 核心效果：{self._object_field(impact, 'core_effect', '-')}",
                    f"- 效果摘要：{self._object_field(impact, 'effect_summary', '-')}",
                    "",
                    "具体结果：",
                ]
            )
            lines.extend(self._markdown_bullets(self._object_field(impact, "concrete_outcomes", [])))
            lines.extend(["", "使用例子："])
            lines.extend(self._markdown_bullets(self._object_field(impact, "usage_examples", [])))
            lines.extend(["", "文章可展开点："])
            lines.extend(self._markdown_bullets(self._object_field(impact, "article_expansion_points", [])))
        else:
            lines.append("- -")
        wechat_pattern = content_plan.get("wechat_pattern") or payload.get("wechat_pattern")
        lines.extend(["", "## 公众号项目分享策略", ""])
        if wechat_pattern is not None:
            lines.extend(
                [
                    f"- Pattern Type：{self._object_field(wechat_pattern, 'pattern_type', '-')}",
                    f"- Opening Strategy：{self._object_field(wechat_pattern, 'opening_strategy', '-')}",
                    f"- Title Formula：{self._object_field(wechat_pattern, 'title_formula', '-')}",
                    f"- Lead Hook：{self._object_field(wechat_pattern, 'lead_hook', '-')}",
                    f"- Key Storyline：{self._object_field(wechat_pattern, 'key_storyline', '-')}",
                    f"- Ending Style：{self._object_field(wechat_pattern, 'ending_style', '-')}",
                    "",
                    "必须展开的效果点：",
                ]
            )
            lines.extend(self._markdown_bullets(self._object_field(wechat_pattern, "required_effect_points", [])))
            lines.extend(["", "必须展开的例子："])
            lines.extend(self._markdown_bullets(self._object_field(wechat_pattern, "required_examples", [])))
            lines.extend(["", "配图放置提示："])
            lines.extend(self._markdown_bullets(self._object_field(wechat_pattern, "image_placement_hints", [])))
        else:
            lines.append("- -")
        lines.extend(
            [
                "",
                "## 评审问题",
                "",
            ]
        )
        lines.extend(self._markdown_bullets(review.issues))
        lines.extend(["", "## 去 AI 味报告", ""])
        if humanization_report is not None:
            lines.extend(
                [
                    f"- 自然度：{humanization_report.ai_smell_score:.2f}",
                    f"- 模板风险：{humanization_report.template_risk:.2f}",
                    f"- README 搬运风险：{humanization_report.readme_similarity_risk:.2f}",
                    f"- 本土化分：{humanization_report.localization_score:.2f}",
                ]
            )
        else:
            lines.append("- -")
        lines.extend(["", "## 发布清理报告", ""])
        if publish_report is not None:
            lines.extend(
                [
                    f"- 保留链接：{'; '.join(publish_report.kept_links) or '-'}",
                    f"- 删除小节：{'; '.join(publish_report.removed_sections) or '-'}",
                    f"- 剩余问题：{'; '.join(publish_report.remaining_issues) or '-'}",
                    f"- 用户方向遵守：{'是' if publish_report.direction_followed else '否'}",
                    f"- 方向违背项：{'; '.join(publish_report.violated_preferences) or '-'}",
                ]
            )
        else:
            lines.append("- -")
        lines.extend(["", "## 文章质量评估", ""])
        if article_quality_report is not None:
            lines.extend(
                [
                    f"- 质量分：{article_quality_report.total_score:.2f}",
                    f"- 可发布：{'是' if article_quality_report.publish_ready else '否'}",
                    f"- 标题分：{article_quality_report.title_score:.2f}",
                    f"- 开头分：{article_quality_report.opening_score:.2f}",
                    f"- 项目价值分：{article_quality_report.project_value_score:.2f}",
                    f"- 具体例子分：{article_quality_report.concrete_example_score:.2f}",
                    f"- 效果展开分：{article_quality_report.effect_depth_score:.2f}",
                    f"- 可读性分：{article_quality_report.readability_score:.2f}",
                    f"- 人味分：{article_quality_report.human_tone_score:.2f}",
                    f"- 反 README 分：{article_quality_report.anti_readme_score:.2f}",
                    f"- 公众号结构分：{article_quality_report.wechat_style_score:.2f}",
                    f"- 摘要：{article_quality_report.summary or '-'}",
                    "",
                    "主要问题：",
                ]
            )
            issue_lines = [
                f"{issue.issue_type}/{issue.severity}：{issue.description}"
                + (f"（证据：{issue.evidence}）" if issue.evidence else "")
                for issue in article_quality_report.issues[:8]
            ]
            lines.extend(self._markdown_bullets(issue_lines))
            lines.extend(["", "修改建议："])
            lines.extend(self._markdown_bullets(article_quality_report.rewrite_recommendations))
        else:
            lines.append("- 未生成质量评估")
        lines.extend(["", "## 原创性检查", ""])
        if originality_report is not None:
            issue_summaries = []
            for issue in originality_report.issues[:5]:
                matched = f"；短片段：{issue.matched_text}" if issue.matched_text else ""
                issue_summaries.append(
                    f"{issue.issue_type}/{issue.severity}：{issue.description}{matched}；建议：{issue.recommendation}"
                )
            lines.extend(
                [
                    f"- 是否检查：{'是' if originality_report.checked else '否'}",
                    f"- 是否通过：{'是' if originality_report.passed else '否'}",
                    f"- 相似度分数：{originality_report.similarity_score:.4f}",
                    f"- 最长连续相同片段：{originality_report.max_common_sequence_length}",
                    f"- 完整句子重复数量：{originality_report.copied_sentence_count}",
                    f"- 段落结构相似度：{originality_report.structure_similarity:.4f}",
                    f"- 是否自动改写：{'是' if originality_report.rewrite_attempted else '否'}",
                    f"- 改写模式：{originality_report.rewrite_mode}",
                    f"- 摘要：{originality_report.summary or '-'}",
                    "",
                    "主要风险：",
                ]
            )
            lines.extend(self._markdown_bullets(issue_summaries))
        else:
            lines.extend(
                [
                    "- 是否检查：否",
                    "- 是否通过：是",
                    "- 摘要：未提供参考文章，本次未执行相似度检查",
                ]
            )
        if warnings:
            lines.extend(["", "## 警告", ""])
            lines.extend(self._markdown_bullets(warnings))
        return "\n".join(lines) + "\n"

    def _truncate_for_custom(self, value: str, limit: int) -> str:
        text = " ".join((value or "").split())
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _run_stage(
        self,
        run: DailyRun,
        name: str,
        action: Callable[[], T],
        message_builder: Callable[[T], str],
        progress_callback: Callable[[dict], None] | None = None,
        fatal: bool = True,
        require_output: bool = True,
    ) -> T:
        started_at = datetime.utcnow()
        stage = {
            "name": name,
            "status": "running",
            "started_at": self._format_utc(started_at),
            "finished_at": None,
            "message": "",
            "error": None,
        }
        run.current_stage = name
        run.stages.append(stage)
        self._save_run_state(run)
        print(f"[run-daily] Starting stage: {name}")
        self._emit_progress(
            progress_callback,
            {
                "type": "stage_started",
                "stage": name,
                "message": f"Starting {name}",
                "time": stage["started_at"],
            },
        )

        try:
            result = action()
            if require_output and not result:
                raise RuntimeError(f"Stage {name} completed without output.")
            stage["status"] = "success"
            stage["finished_at"] = self._format_utc()
            stage["message"] = message_builder(result)
            run.snapshot_files = self._collect_snapshot_files()
            run.final_article_files = self._collect_final_article_files(run.date)
            self._save_run_state(run)
            print(f"[run-daily] Completed stage: {name} - {stage['message']}")
            self._emit_progress(
                progress_callback,
                {
                    "type": "stage_succeeded",
                    "stage": name,
                    "message": stage["message"],
                    "time": stage["finished_at"],
                },
            )
            return result
        except Exception as exc:
            stage["status"] = "failed"
            stage["finished_at"] = self._format_utc()
            stage["error"] = f"{type(exc).__name__}: {exc}"
            stage["message"] = f"Stage {name} failed."
            if fatal:
                run.error = stage["error"]
            run.snapshot_files = self._collect_snapshot_files()
            run.final_article_files = self._collect_final_article_files(run.date)
            self._save_run_state(run)
            print(f"[run-daily] Failed stage: {name} - {stage['error']}")
            self._emit_progress(
                progress_callback,
                {
                    "type": "stage_failed",
                    "stage": name,
                    "message": stage["message"],
                    "error": stage["error"],
                    "time": stage["finished_at"],
                },
            )
            if fatal:
                raise
            return []  # type: ignore[return-value]

    def _build_custom_content_plan(
        self,
        planner: ContentPlanningService,
        research_note: RepoResearchNote,
        angle: TopicAngle,
        custom_direction: CustomArticleDirection,
        style_reference_profile: StyleReferenceProfile,
    ) -> dict[str, Any]:
        raw_content_plan = planner.build_content_plan(
            research_note,
            angle,
            custom_direction=custom_direction,
            style_reference_profile=style_reference_profile,
        )
        content_plan = self._content_plan_payload(raw_content_plan)
        content_plan = self._apply_custom_direction_to_content_plan(content_plan, custom_direction)
        return self._apply_style_reference_to_content_plan(content_plan, style_reference_profile)

    def _run_custom_stage(
        self,
        progress_callback: Callable[[dict], None] | None,
        name: str,
        action: Callable[[], T],
        start_message: str,
        success_message: str,
    ) -> T:
        self._emit_custom_stage_started(progress_callback, name, start_message)
        try:
            result = action()
        except Exception as exc:
            self._emit_progress(
                progress_callback,
                {
                    "type": "stage_failed",
                    "stage": name,
                    "message": f"{name} failed.",
                    "error": f"{type(exc).__name__}: {exc}",
                    "time": self._format_utc(),
                },
            )
            raise
        self._emit_custom_stage_succeeded(progress_callback, name, success_message)
        return result

    def _emit_custom_stage_started(
        self,
        progress_callback: Callable[[dict], None] | None,
        name: str,
        message: str,
    ) -> None:
        self._emit_progress(
            progress_callback,
            {
                "type": "stage_started",
                "stage": name,
                "message": message,
                "time": self._format_utc(),
            },
        )

    def _emit_custom_stage_succeeded(
        self,
        progress_callback: Callable[[dict], None] | None,
        name: str,
        message: str,
    ) -> None:
        self._emit_progress(
            progress_callback,
            {
                "type": "stage_succeeded",
                "stage": name,
                "message": message,
                "time": self._format_utc(),
            },
        )

    def _runs_dir(self) -> Path:
        return self.settings.workspace_dir / "runs"

    def _save_run_state(self, run: DailyRun) -> None:
        runs_dir = self._runs_dir()
        runs_dir.mkdir(parents=True, exist_ok=True)
        payload = self._model_dump(run)
        self._write_json(runs_dir / f"{run.run_id}.json", payload)
        self._write_json(runs_dir / "latest_run.json", payload)

    def _collect_snapshot_files(self) -> list[str]:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        names = [
            "discovery_latest.json",
            "score_latest.json",
            "research_latest.json",
            "selection_latest.json",
            "angles_latest.json",
            "content_plan_latest.json",
            "articles_latest.json",
            "reviews_latest.json",
            "humanization_latest.json",
            "publish_polish_latest.json",
            "article_quality_latest.json",
            "final_articles_latest.json",
            "article_packages_latest.json",
        ]
        return [str(snapshots_dir / name) for name in names if (snapshots_dir / name).exists()]

    def _collect_final_article_files(self, run_date: str) -> list[str]:
        final_articles_dir = self.settings.output_dir / run_date / "final_articles"
        if not final_articles_dir.exists():
            return []
        return [str(path) for path in sorted(final_articles_dir.glob("*.md"))]

    def _update_article_history_after_daily(
        self,
        final_articles: list[FinalArticle],
        final_article_files: list[str],
    ) -> None:
        if not final_articles:
            return
        output_paths_by_name = {
            Path(path).stem.replace("__", "/"): path
            for path in final_article_files
        }
        selector = ArticleSelectionService(history_path=self.settings.workspace_dir / "article_history.json")
        selector.update_history(
            final_articles=final_articles,
            source="daily",
            output_paths_by_name=output_paths_by_name,
        )
        for warning in selector.warnings:
            print(f"Warning: {warning}")

    def _save_daily_report(
        self,
        run: DailyRun,
        final_articles: List[FinalArticle],
        article_packages: list[ArticlePackage] | None = None,
    ) -> Path:
        report_dir = self.settings.output_dir / run.date
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "daily_report.md"
        report_path.write_text(
            self._build_daily_report(run=run, final_articles=final_articles, article_packages=article_packages or []),
            encoding="utf-8",
        )
        return report_path

    def _build_daily_report(
        self,
        run: DailyRun,
        final_articles: List[FinalArticle],
        article_packages: list[ArticlePackage],
    ) -> str:
        final_paths_by_name = {
            Path(path).stem.replace("__", "/"): path
            for path in run.final_article_files
        }
        lines = [
            "# GitHubRadarAgent 每日运行报告",
            "",
            "## 运行信息",
            f"- Run ID：{run.run_id}",
            f"- 日期：{run.date}",
            f"- 状态：{run.status}",
            f"- 开始时间：{run.started_at}",
            f"- 结束时间：{run.finished_at or '-'}",
            "",
            "## 阶段结果",
            "",
            "| 阶段 | 状态 | 耗时 | 说明 |",
            "| --- | --- | --- | --- |",
        ]

        for stage in run.stages:
            duration = self._stage_duration(stage)
            message = stage.get("message") or stage.get("error") or "-"
            lines.append(
                "| "
                f"{stage.get('name') or '-'} | {stage.get('status') or '-'} | "
                f"{duration} | {self._markdown_table_cell(message)} |"
            )

        lines.extend(self._daily_package_summary_lines(article_packages))

        selection_summary = run.selection_summary or {}
        selected_repos = selection_summary.get("selected_repos") or []
        skipped_recent = selection_summary.get("skipped_recent_repos") or []
        fallback_repos = selection_summary.get("fallback_repos") or []
        selected_with_reason = selection_summary.get("selected_repos_with_reason") or []
        lines.extend(
            [
                "",
                "## 本次项目选择",
                "",
                f"- 候选项目数：{selection_summary.get('candidate_count', 0)}",
                f"- 新项目候选数：{selection_summary.get('fresh_candidate_count', 0)}",
                f"- 冷却期内重复候选数：{selection_summary.get('repeated_candidate_count', 0)}",
                f"- 目标文章数：{selection_summary.get('target_count', len(selected_repos))}",
                f"- 冷却天数：{selection_summary.get('cooldown_days', '-')}",
                f"- 是否忽略历史记录：{'是' if selection_summary.get('ignored_history') else '否'}",
                f"- 是否允许旧项目补位：{'是' if selection_summary.get('allow_recent_fallback') else '否'}",
                f"- 历史过滤项目数：{selection_summary.get('skipped_recent_count', len(skipped_recent))}",
                f"- 是否有历史项目补位：{'是' if fallback_repos else '否'}",
                f"- 历史补位项目：{', '.join(fallback_repos) if fallback_repos else '-'}",
                f"- 新项目不足：{'是' if selection_summary.get('new_project_shortage') else '否'}",
                f"- 近期增长项目数量：{selection_summary.get('growth_selected_count', 0)}",
                f"- 实用工具项目数量：{selection_summary.get('tool_selected_count', 0)}",
                "- 本次选中项目：",
            ]
        )
        if selected_with_reason:
            for item in selected_with_reason:
                repo_name = item.get("repo_full_name") or "-"
                bucket = item.get("bucket") or "-"
                reason = item.get("reason") or "-"
                discovery_reason = item.get("discovery_reason") or "-"
                lines.append(f"  - {repo_name}：{reason}（分桶：{bucket}，发现来源：{discovery_reason}）")
        elif selected_repos:
            for repo_name in selected_repos:
                lines.append(f"  - {repo_name}")
        else:
            lines.append("  - -")

        if skipped_recent:
            lines.extend(["", "### 最近写过并跳过的项目", ""])
            for item in skipped_recent[:20]:
                lines.append(
                    "- "
                    f"{item.get('repo_full_name') or '-'}"
                    f"（上次写作：{item.get('last_written_at') or '-'}，"
                    f"次数：{item.get('write_count', 0)}）"
                )
        else:
            lines.extend(["", "### 最近写过并跳过的项目", "", "- -"])

        if selection_summary.get("new_project_shortage"):
            shortage_count = selection_summary.get("shortage_count", 0)
            lines.extend(
                [
                    "",
                    "### 新项目不足提示",
                    "",
                    f"- 新项目不足，本次少生成 {shortage_count} 篇；默认不会用冷却期内项目补位。",
                ]
            )

        lines.extend(
            [
                "",
                "## 今日终稿文章",
                "",
                "| 标题 | 项目 | 本地路径 | GitHub 链接 | 字数 | 评审分数 | 质量分 | 质量可发布 |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        if final_articles:
            for article in final_articles:
                local_path = final_paths_by_name.get(article.full_name, "-")
                project = self._markdown_table_cell(article.full_name)
                title = self._markdown_table_cell(article.title)
                github_link = f"[{article.html_url}]({article.html_url})" if article.html_url else "-"
                quality_report = article.article_quality_report
                quality_score = (
                    quality_report.total_score
                    if quality_report is not None
                    else article.quality_score
                )
                quality_ready = (
                    quality_report.publish_ready
                    if quality_report is not None
                    else article.quality_publish_ready
                )
                lines.append(
                    "| "
                    f"{title} | {project} | {local_path} | {github_link} | "
                    f"{article.word_count} | {article.review.total_score:.2f} | "
                    f"{quality_score:.2f} | {'是' if quality_ready else '否'} |"
                )
        else:
            lines.append("| - | - | - | - | 0 | 0 | 0 | 否 |")

        quality_reports = [
            article.article_quality_report
            for article in final_articles
            if article.article_quality_report is not None
        ]
        average_quality = (
            sum(report.total_score for report in quality_reports) / len(quality_reports)
            if quality_reports
            else 0.0
        )
        low_quality_reports = [
            report
            for report in quality_reports
            if report.total_score < 80 or not report.publish_ready
        ]
        lines.extend(
            [
                "",
                "## 文章质量摘要",
                "",
                f"- 平均质量分：{average_quality:.2f}",
                f"- 低于阈值文章：{len(low_quality_reports)}",
                "",
                "| 项目 | 质量分 | 可发布 | 主要问题 |",
                "| --- | ---: | --- | --- |",
            ]
        )
        if quality_reports:
            for report in quality_reports:
                issues = self._markdown_table_cell(
                    "; ".join(f"{issue.issue_type}/{issue.severity}" for issue in report.issues[:3]) or "-"
                )
                lines.append(
                    "| "
                    f"{self._markdown_table_cell(report.full_name)} | {report.total_score:.2f} | "
                    f"{'是' if report.publish_ready else '否'} | {issues} |"
                )
        else:
            lines.append("| - | 0 | 否 | - |")

        artifact_paths = [
            *run.snapshot_files,
            str(self.settings.output_dir / run.date / "score_report.md"),
            str(self.settings.output_dir / run.date / "research_notes.md"),
            str(self.settings.output_dir / run.date / "topic_angles.md"),
            str(self.settings.output_dir / run.date / "article_drafts.md"),
            str(self.settings.output_dir / run.date / "review_report.md"),
            str(self.settings.output_dir / run.date / "humanization_report.md"),
            str(self.settings.output_dir / run.date / "publish_polish_report.md"),
            str(self.settings.output_dir / run.date / "article_quality_report.md"),
            str(self.settings.output_dir / run.date / "final_articles_index.md"),
            str(self.settings.output_dir / run.date / "article_packages.md"),
            str(self.settings.output_dir / run.date / "daily_report.md"),
            *[
                package.packaged_article_path
                for package in article_packages
                if package.packaged_article_path
            ],
            *run.final_article_files,
        ]
        seen_paths: set[str] = set()
        lines.extend(["", "## 产物索引", ""])
        for artifact_path in artifact_paths:
            if artifact_path in seen_paths:
                continue
            seen_paths.add(artifact_path)
            if Path(artifact_path).exists():
                lines.append(f"- {artifact_path}")
        if not seen_paths:
            lines.append("- -")

        return "\n".join(lines) + "\n"

    def _daily_package_summary_lines(self, article_packages: list[ArticlePackage]) -> list[str]:
        readme_packages = [
            package.full_name
            for package in article_packages
            if any(asset.asset_type == "readme_image" and asset.status != "failed" for asset in package.assets)
        ]
        readme_screenshot_packages = [
            package.full_name
            for package in article_packages
            if any(asset.asset_type == "github_readme_screenshot" and asset.status == "generated" for asset in package.assets)
        ]
        repo_screenshot_packages = [
            package.full_name
            for package in article_packages
            if any(asset.asset_type == "github_repo_screenshot" and asset.status == "generated" for asset in package.assets)
        ]
        no_image_packages = [
            package.full_name
            for package in article_packages
            if not any(
                (
                    asset.asset_type == "readme_image" and asset.status != "failed"
                )
                or (
                    asset.asset_type in {"github_readme_screenshot", "github_repo_screenshot"}
                    and asset.status == "generated"
                )
                for asset in package.assets
            )
        ]
        return [
            "",
            "## 发布包摘要",
            "",
            f"- 已生成发布包：{len(article_packages)} 篇",
            f"- 使用 README 图片：{', '.join(readme_packages) if readme_packages else '-'}",
            f"- 使用 GitHub README 截图：{', '.join(readme_screenshot_packages) if readme_screenshot_packages else '-'}",
            f"- 使用 GitHub 仓库首页截图：{', '.join(repo_screenshot_packages) if repo_screenshot_packages else '-'}",
            f"- 无图纯文字发布包：{', '.join(no_image_packages) if no_image_packages else '-'}",
        ]

    def _stage_duration(self, stage: dict) -> str:
        started_at = stage.get("started_at")
        finished_at = stage.get("finished_at")
        if not started_at or not finished_at:
            return "-"
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        except ValueError:
            return "-"
        seconds = max(0.0, (finish - start).total_seconds())
        return f"{seconds:.1f}s"

    def _format_utc(self, value: datetime | None = None) -> str:
        return (value or datetime.utcnow()).isoformat(timespec="seconds") + "Z"

    def _output_date_from_payload(self, payload: dict[str, Any]) -> str:
        generated_at = str(payload.get("generated_at") or "")
        if re_match := re.match(r"^\d{4}-\d{2}-\d{2}", generated_at):
            candidate = re_match.group(0)
            if (self.settings.output_dir / candidate / "final_articles").exists():
                return candidate
        dated_dirs = [
            path
            for path in self.settings.output_dir.glob("*/final_articles")
            if path.is_dir()
        ]
        if dated_dirs:
            latest = max(dated_dirs, key=lambda path: path.stat().st_mtime)
            return latest.parent.name
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _emit_progress(self, progress_callback: Callable[[dict], None] | None, event: dict) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(event)
        except Exception as exc:
            print(f"[run-daily] Progress callback failed: {type(exc).__name__}: {exc}")

    def _print_candidate_summaries(self, candidates: List[RepoCandidate]) -> None:
        if not candidates:
            print("No repository candidates discovered.")
            return

        print("Top discovered candidates:")
        for index, candidate in enumerate(candidates, start=1):
            description = (candidate.description or "").replace("\n", " ").strip()
            if len(description) > 100:
                description = f"{description[:100]}..."
            print(
                f"{index}. {candidate.full_name} | stars={candidate.stars} | "
                f"language={candidate.language or '-'} | {candidate.html_url}"
            )
            if description:
                print(f"   {description}")

    def _save_discovery_snapshots(
        self,
        candidates: List[RepoCandidate],
        keywords: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "keywords": keywords or self.settings.daily_keywords,
            "total_count": len(candidates),
            "warnings": warnings or [],
            "candidates": [self._model_dump(candidate) for candidate in candidates],
        }

        latest_path = snapshots_dir / "discovery_latest.json"
        dated_path = snapshots_dir / f"{datetime.utcnow().strftime('%Y-%m-%d')}-discovery.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved discovery snapshot: {latest_path}")
        print(f"Saved dated discovery snapshot: {dated_path}")

    def _print_score_summaries(self, scores: List[RepoScore], candidates: List[RepoCandidate]) -> None:
        if not scores:
            print("No repository scores generated.")
            return

        candidates_by_name = {candidate.full_name: candidate for candidate in candidates}
        print("Top scored candidates:")
        for rank, score in enumerate(scores, start=1):
            candidate = candidates_by_name.get(score.full_name)
            stars = candidate.stars if candidate is not None else "-"
            language = candidate.language if candidate is not None else "-"
            top_reasons = "; ".join(score.reasons[:3]) or "-"
            print(
                f"{rank}. {score.full_name} | total={score.total_score:.2f} | "
                f"velocity={score.velocity_score:.2f} | freshness={score.freshness_score:.2f} | "
                f"stars={stars} | source={score.discovery_reason or '-'} | "
                f"language={language or '-'} | {score.html_url}"
            )
            print(f"   reasons: {top_reasons}")

    def _save_score_outputs(
        self,
        scores: List[RepoScore],
        candidates: List[RepoCandidate],
        source_snapshot_path: Path,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "source_snapshot": str(source_snapshot_path),
            "total_count": len(scores),
            "scores": [self._model_dump(score) for score in scores],
        }

        latest_path = snapshots_dir / "score_latest.json"
        dated_path = snapshots_dir / f"{run_date}-score.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved score snapshot: {latest_path}")
        print(f"Saved dated score snapshot: {dated_path}")

        report_path = self.settings.output_dir / run_date / "score_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            self._build_score_report(
                run_date=run_date,
                source_snapshot=str(source_snapshot_path),
                scores=scores,
                candidates=candidates,
            ),
            encoding="utf-8",
        )
        print(f"Saved score report: {report_path}")

    def _print_research_summaries(self, notes: List[RepoResearchNote]) -> None:
        if not notes:
            print("No repository research notes generated.")
            return

        print("Top repository research notes:")
        for rank, note in enumerate(notes, start=1):
            risks = "; ".join(note.risks[:3]) or "-"
            print(
                f"{rank}. {note.full_name} | stars={note.stars} | "
                f"language={note.language or '-'} | {note.html_url}"
            )
            print(f"   README summary: {note.readme_summary[:160]}")
            print(f"   risks: {risks}")

    def _print_angle_summaries(self, angles: List[TopicAngle]) -> None:
        if not angles:
            print("No topic angles generated.")
            return

        print("Top repository topic angles:")
        for rank, angle in enumerate(angles, start=1):
            print(f"{rank}. {angle.full_name}")
            print(f"   selected_angle: {angle.selected_angle}")
            print("   top titles:")
            for title in angle.title_candidates[:3]:
                print(f"   - {title.title}")
            print(f"   opening_hook: {angle.opening_hook}")

    def _print_article_summaries(self, drafts: List[ArticleDraft]) -> None:
        if not drafts:
            print("No article drafts generated.")
            return

        print("Top repository article drafts:")
        for rank, draft in enumerate(drafts, start=1):
            print(f"{rank}. {draft.full_name}")
            print(f"   title: {draft.title}")
            print(f"   generation_mode: {draft.generation_mode}")
            print(f"   word_count: {draft.word_count}")
            print(f"   source count: {len(draft.source_links)}")

    def _print_content_plan_summaries(self, plans: list[dict[str, Any]]) -> None:
        if not plans:
            print("No content plans generated.")
            return

        print("Top content planning artifacts:")
        for rank, plan in enumerate(plans, start=1):
            insight = plan.get("insight")
            brief = plan.get("brief")
            plain_summary = getattr(insight, "plain_summary", "") if insight is not None else ""
            impact = plan.get("impact")
            core_effect = self._object_field(impact, "core_effect", "-") if impact is not None else "-"
            wechat_pattern = plan.get("wechat_pattern")
            pattern_type = self._object_field(wechat_pattern, "pattern_type", "-") if wechat_pattern is not None else "-"
            opening_strategy = self._object_field(wechat_pattern, "opening_strategy", "-") if wechat_pattern is not None else "-"
            narrative_pattern = getattr(brief, "narrative_pattern", "") if brief is not None else ""
            recommended_angle = getattr(brief, "recommended_angle", "") if brief is not None else ""
            print(f"{rank}. {plan.get('full_name') or '-'}")
            print(f"   planning_mode: {plan.get('planning_mode') or '-'}")
            print(f"   plain_summary: {plain_summary}")
            print(f"   core_effect: {core_effect}")
            print(f"   wechat_pattern: {pattern_type} / {opening_strategy}")
            print(f"   narrative_pattern: {narrative_pattern}")
            print(f"   recommended_angle: {recommended_angle}")

    def _print_review_summaries(self, final_articles: List[FinalArticle]) -> None:
        if not final_articles:
            print("No article reviews generated.")
            return

        print("Article review results:")
        for rank, article in enumerate(final_articles, start=1):
            review = article.review
            issues = "; ".join(review.issues[:3]) or "-"
            print(f"{rank}. {article.full_name}")
            print(f"   title: {article.title}")
            print(
                f"   total_score: {review.total_score:.2f} | "
                f"pass_review: {'yes' if review.pass_review else 'no'} | "
                f"revision_mode: {article.revision_mode}"
            )
            print(f"   top issues: {issues}")

    def _print_humanization_summaries(self, final_articles: List[FinalArticle]) -> None:
        if not final_articles:
            print("No humanization results generated.")
            return

        print("Article humanization results:")
        for rank, article in enumerate(final_articles, start=1):
            report = article.humanization_report
            if report is None:
                print(f"{rank}. {article.full_name} | humanization_report: -")
                continue
            print(f"{rank}. {article.full_name}")
            print(f"   title: {article.title}")
            print(
                f"   humanized: {'yes' if article.humanized else 'no'} | "
                f"ai_smell_score: {report.ai_smell_score:.2f} | "
                f"template_risk: {report.template_risk:.2f} | "
                f"localization_score: {report.localization_score:.2f}"
            )
            if report.issues:
                print(f"   top humanization issues: {'; '.join(issue.text for issue in report.issues[:3])}")

    def _print_publish_polish_summaries(self, final_articles: List[FinalArticle]) -> None:
        if not final_articles:
            print("No publish polish results generated.")
            return

        print("Publish polish results:")
        for rank, article in enumerate(final_articles, start=1):
            report = article.publish_polish_report
            if report is None:
                print(f"{rank}. {article.full_name} | publish_polish_report: -")
                continue
            print(f"{rank}. {article.full_name}")
            print(f"   title: {article.title}")
            print(
                f"   publish_ready: {'yes' if article.publish_ready else 'no'} | "
                f"mode: {report.mode} | kept_links: {len(report.kept_links)} | "
                f"removed_sections: {len(report.removed_sections)} | "
                f"removed_phrases: {len(report.removed_phrases)}"
            )
            if report.remaining_issues:
                print(f"   remaining issues: {'; '.join(report.remaining_issues[:3])}")

    def _print_article_quality_summaries(self, final_articles: List[FinalArticle]) -> None:
        if not final_articles:
            print("No article quality results generated.")
            return

        print("Article quality results:")
        for rank, article in enumerate(final_articles, start=1):
            report = article.article_quality_report
            if report is None:
                print(f"{rank}. {article.full_name} | article_quality_report: -")
                continue
            issues = "; ".join(
                f"{issue.issue_type}/{issue.severity}"
                for issue in report.issues[:3]
            ) or "-"
            print(f"{rank}. {article.full_name}")
            print(f"   title: {article.title}")
            print(
                f"   quality_score: {report.total_score:.2f} | "
                f"quality_publish_ready: {'yes' if report.publish_ready else 'no'} | "
                f"issues: {issues}"
            )

    def _print_article_package_summaries(self, packages: list[ArticlePackage]) -> None:
        if not packages:
            print("No article packages generated.")
            return

        print("Article package results:")
        for rank, article_package in enumerate(packages, start=1):
            readme_assets = [
                asset for asset in article_package.assets
                if asset.asset_type == "readme_image"
            ]
            failed_assets = [
                asset for asset in article_package.assets
                if asset.status == "failed"
            ]
            print(f"{rank}. {article_package.full_name}")
            print(f"   packaged_article: {article_package.packaged_article_path}")
            print(
                f"   status: {article_package.status} | "
                f"readme_images: {len(readme_assets)} | failed_assets: {len(failed_assets)}"
            )
            if failed_assets:
                print(f"   failed: {'; '.join(asset.title for asset in failed_assets[:4])}")

    def _save_research_outputs(
        self,
        notes: List[RepoResearchNote],
        source_score_snapshot_path: Path,
        source_discovery_snapshot_path: Path,
        source_selection_snapshot_path: Path | None = None,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        notes_dir = self.settings.workspace_dir / "notes"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        notes_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "source_score_snapshot": str(source_score_snapshot_path),
            "source_discovery_snapshot": str(source_discovery_snapshot_path),
            "source_selection_snapshot": str(source_selection_snapshot_path) if source_selection_snapshot_path else None,
            "total_count": len(notes),
            "notes": [self._model_dump(note) for note in notes],
        }

        latest_path = snapshots_dir / "research_latest.json"
        dated_path = snapshots_dir / f"{run_date}-research.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved research snapshot: {latest_path}")
        print(f"Saved dated research snapshot: {dated_path}")

        note_paths: list[Path] = []
        for note in notes:
            note_path = notes_dir / f"{note.full_name.replace('/', '__')}.md"
            note_path.write_text(self._build_repo_note_markdown(note), encoding="utf-8")
            note_paths.append(note_path)
            print(f"Saved project research note: {note_path}")

        report_path = self.settings.output_dir / run_date / "research_notes.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            self._build_research_report(
                run_date=run_date,
                source_score_snapshot=str(source_score_snapshot_path),
                notes=notes,
                note_paths=note_paths,
            ),
            encoding="utf-8",
        )
        print(f"Saved research report: {report_path}")

    def _save_angle_outputs(
        self,
        angles: List[TopicAngle],
        source_research_snapshot_path: Path,
        used_llm: bool,
        llm_available: bool,
        warnings: List[str],
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "source_research_snapshot": str(source_research_snapshot_path),
            "total_count": len(angles),
            "llm_available": llm_available,
            "used_llm": used_llm,
            "warnings": warnings,
            "angles": [self._model_dump(angle) for angle in angles],
        }

        latest_path = snapshots_dir / "angles_latest.json"
        dated_path = snapshots_dir / f"{run_date}-angles.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved angles snapshot: {latest_path}")
        print(f"Saved dated angles snapshot: {dated_path}")

        report_path = self.settings.output_dir / run_date / "topic_angles.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            self._build_angle_report(
                run_date=run_date,
                source_research_snapshot=str(source_research_snapshot_path),
                angles=angles,
                used_llm=used_llm,
            ),
            encoding="utf-8",
        )
        print(f"Saved topic angle report: {report_path}")

    def _save_content_plan_outputs(
        self,
        plans: list[dict[str, Any]],
        source_research_snapshot_path: Path,
        source_angles_snapshot_path: Path | None,
        llm_available: bool,
        used_llm: bool,
        warnings: list[str],
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "source_research_snapshot": str(source_research_snapshot_path),
            "source_angles_snapshot": str(source_angles_snapshot_path) if source_angles_snapshot_path else None,
            "total_count": len(plans),
            "llm_available": llm_available,
            "used_llm": used_llm,
            "warnings": warnings,
            "plans": [self._content_plan_payload(plan) for plan in plans],
        }

        latest_path = snapshots_dir / "content_plan_latest.json"
        dated_path = snapshots_dir / f"{run_date}-content-plan.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved content plan snapshot: {latest_path}")
        print(f"Saved dated content plan snapshot: {dated_path}")

        report_path = self.settings.output_dir / run_date / "content_plan.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            self._build_content_plan_report(
                run_date=run_date,
                source_research_snapshot=str(source_research_snapshot_path),
                source_angles_snapshot=str(source_angles_snapshot_path) if source_angles_snapshot_path else None,
                plans=plans,
                used_llm=used_llm,
            ),
            encoding="utf-8",
        )
        print(f"Saved content plan report: {report_path}")

    def _save_selection_outputs(
        self,
        summary: dict[str, Any],
        source_score_snapshot_path: Path,
        source_research_snapshot_path: Path | None = None,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        payload = {
            **summary,
            "source_score_snapshot": str(source_score_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path) if source_research_snapshot_path else None,
        }
        latest_path = snapshots_dir / "selection_latest.json"
        dated_path = snapshots_dir / f"{run_date}-selection.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved selection snapshot: {latest_path}")
        print(f"Saved dated selection snapshot: {dated_path}")

    def _save_article_outputs(
        self,
        drafts: List[ArticleDraft],
        source_angles_snapshot_path: Path,
        source_research_snapshot_path: Path,
        used_llm: bool,
        llm_available: bool,
        warnings: List[str],
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        articles_dir = self.settings.workspace_dir / "articles"
        output_articles_dir = self.settings.output_dir / datetime.utcnow().strftime("%Y-%m-%d") / "articles"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        articles_dir.mkdir(parents=True, exist_ok=True)
        output_articles_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "source_angles_snapshot": str(source_angles_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path),
            "total_count": len(drafts),
            "llm_available": llm_available,
            "used_llm": used_llm,
            "warnings": warnings,
            "articles": [self._model_dump(draft) for draft in drafts],
        }

        latest_path = snapshots_dir / "articles_latest.json"
        dated_path = snapshots_dir / f"{run_date}-articles.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved articles snapshot: {latest_path}")
        print(f"Saved dated articles snapshot: {dated_path}")

        article_paths: list[Path] = []
        output_article_paths: list[Path] = []
        for draft in drafts:
            article_path = articles_dir / f"{draft.full_name.replace('/', '__')}.md"
            article_path.write_text(draft.content_markdown, encoding="utf-8")
            article_paths.append(article_path)
            print(f"Saved article draft: {article_path}")

            output_article_path = output_articles_dir / f"{draft.full_name.replace('/', '__')}.md"
            output_article_path.write_text(draft.content_markdown, encoding="utf-8")
            output_article_paths.append(output_article_path)
            print(f"Saved output article draft: {output_article_path}")

        report_path = self.settings.output_dir / run_date / "article_drafts.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            self._build_article_report(
                run_date=run_date,
                source_angles_snapshot=str(source_angles_snapshot_path),
                drafts=drafts,
                article_paths=article_paths,
                used_llm=used_llm,
            ),
            encoding="utf-8",
        )
        print(f"Saved article draft report: {report_path}")

        index_path = self.settings.output_dir / run_date / "articles_index.md"
        index_path.write_text(
            self._build_articles_index(
                run_date=run_date,
                drafts=drafts,
                article_paths=output_article_paths,
            ),
            encoding="utf-8",
        )
        print(f"Saved articles index: {index_path}")

    def _save_review_outputs(
        self,
        reviews: List[ArticleReview],
        final_articles: List[FinalArticle],
        source_articles_snapshot_path: Path,
        source_research_snapshot_path: Path,
        source_angles_snapshot_path: Path,
        llm_available: bool,
        used_llm_review: bool,
        used_llm_revision: bool,
        pass_threshold: float,
        warnings: List[str],
        humanization_llm_used: bool = False,
        humanization_fallback_used: bool = False,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        final_articles_dir = self.settings.output_dir / datetime.utcnow().strftime("%Y-%m-%d") / "final_articles"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        final_articles_dir.mkdir(parents=True, exist_ok=True)

        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        review_payload = {
            "generated_at": generated_at,
            "source_articles_snapshot": str(source_articles_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path),
            "source_angles_snapshot": str(source_angles_snapshot_path),
            "total_count": len(reviews),
            "llm_available": llm_available,
            "used_llm": used_llm_review,
            "pass_threshold": pass_threshold,
            "warnings": warnings,
            "reviews": [self._model_dump(review) for review in reviews],
        }
        final_payload = {
            "generated_at": generated_at,
            "source_articles_snapshot": str(source_articles_snapshot_path),
            "source_reviews_snapshot": str(snapshots_dir / "reviews_latest.json"),
            "total_count": len(final_articles),
            "llm_available": llm_available,
            "used_llm_review": used_llm_review,
            "used_llm_revision": used_llm_revision,
            "used_llm_humanization": humanization_llm_used,
            "used_fallback_humanization": humanization_fallback_used,
            "pass_threshold": pass_threshold,
            "warnings": warnings,
            "articles": [self._model_dump(article) for article in final_articles],
        }

        reviews_latest_path = snapshots_dir / "reviews_latest.json"
        reviews_dated_path = snapshots_dir / f"{run_date}-reviews.json"
        final_latest_path = snapshots_dir / "final_articles_latest.json"
        final_dated_path = snapshots_dir / f"{run_date}-final-articles.json"
        self._write_json(reviews_latest_path, review_payload)
        self._write_json(reviews_dated_path, review_payload)
        self._write_json(final_latest_path, final_payload)
        self._write_json(final_dated_path, final_payload)
        print(f"Saved review snapshot: {reviews_latest_path}")
        print(f"Saved dated review snapshot: {reviews_dated_path}")
        print(f"Saved final articles snapshot: {final_latest_path}")
        print(f"Saved dated final articles snapshot: {final_dated_path}")

        final_article_paths: list[Path] = []
        for article in final_articles:
            final_path = final_articles_dir / f"{article.full_name.replace('/', '__')}.md"
            final_path.write_text(article.content_markdown, encoding="utf-8")
            final_article_paths.append(final_path)
            print(f"Saved final article: {final_path}")

        report_dir = self.settings.output_dir / run_date
        report_dir.mkdir(parents=True, exist_ok=True)
        review_report_path = report_dir / "review_report.md"
        review_report_path.write_text(
            self._build_review_report(
                run_date=run_date,
                reviews=reviews,
                final_articles=final_articles,
                used_llm=used_llm_review,
                pass_threshold=pass_threshold,
                humanization_llm_used=humanization_llm_used,
                humanization_fallback_used=humanization_fallback_used,
            ),
            encoding="utf-8",
        )
        print(f"Saved review report: {review_report_path}")

        final_index_path = report_dir / "final_articles_index.md"
        final_index_path.write_text(
            self._build_final_articles_index(
                run_date=run_date,
                final_articles=final_articles,
                final_article_paths=final_article_paths,
            ),
            encoding="utf-8",
        )
        print(f"Saved final articles index: {final_index_path}")

    def _save_humanization_outputs(
        self,
        final_articles: List[FinalArticle],
        source_final_articles_snapshot_path: Path,
        source_articles_snapshot_path: Path,
        source_research_snapshot_path: Path,
        source_content_plan_snapshot_path: Path | None,
        llm_available: bool,
        used_llm: bool,
        used_fallback: bool,
        warnings: List[str],
        rewrite_final_articles: bool,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        reports = [
            article.humanization_report
            for article in final_articles
            if article.humanization_report is not None
        ]
        payload = {
            "generated_at": generated_at,
            "source_final_articles_snapshot": str(source_final_articles_snapshot_path),
            "source_articles_snapshot": str(source_articles_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path),
            "source_content_plan_snapshot": str(source_content_plan_snapshot_path) if source_content_plan_snapshot_path else None,
            "total_count": len(reports),
            "llm_available": llm_available,
            "used_llm": used_llm,
            "used_fallback": used_fallback,
            "warnings": warnings,
            "reports": [self._model_dump(report) for report in reports],
        }

        latest_path = snapshots_dir / "humanization_latest.json"
        dated_path = snapshots_dir / f"{run_date}-humanization.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved humanization snapshot: {latest_path}")
        print(f"Saved dated humanization snapshot: {dated_path}")

        if rewrite_final_articles:
            final_payload = {}
            if source_final_articles_snapshot_path.exists():
                try:
                    final_payload = json.loads(source_final_articles_snapshot_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    final_payload = {}
            final_payload.update(
                {
                    "generated_at": generated_at,
                    "total_count": len(final_articles),
                    "llm_available": llm_available,
                    "used_llm_humanization": used_llm,
                    "used_fallback_humanization": used_fallback,
                    "warnings": warnings,
                    "articles": [self._model_dump(article) for article in final_articles],
                }
            )
            final_latest_path = snapshots_dir / "final_articles_latest.json"
            final_dated_path = snapshots_dir / f"{run_date}-final-articles.json"
            self._write_json(final_latest_path, final_payload)
            self._write_json(final_dated_path, final_payload)
            print(f"Updated final articles snapshot: {final_latest_path}")
            print(f"Updated dated final articles snapshot: {final_dated_path}")

        final_articles_dir = self.settings.output_dir / run_date / "final_articles"
        final_articles_dir.mkdir(parents=True, exist_ok=True)
        final_article_paths: list[Path] = []
        for article in final_articles:
            final_path = final_articles_dir / f"{article.full_name.replace('/', '__')}.md"
            final_path.write_text(article.content_markdown, encoding="utf-8")
            final_article_paths.append(final_path)
            print(f"Saved humanized final article: {final_path}")

        report_dir = self.settings.output_dir / run_date
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "humanization_report.md"
        report_path.write_text(
            self._build_humanization_report(
                run_date=run_date,
                final_articles=final_articles,
                used_llm=used_llm,
                used_fallback=used_fallback,
                source_final_articles_snapshot=str(source_final_articles_snapshot_path),
            ),
            encoding="utf-8",
        )
        print(f"Saved humanization report: {report_path}")

        if rewrite_final_articles:
            final_index_path = report_dir / "final_articles_index.md"
            final_index_path.write_text(
                self._build_final_articles_index(
                    run_date=run_date,
                    final_articles=final_articles,
                    final_article_paths=final_article_paths,
                ),
                encoding="utf-8",
            )
            print(f"Updated final articles index: {final_index_path}")

    def _save_publish_polish_outputs(
        self,
        final_articles: List[FinalArticle],
        source_final_articles_snapshot_path: Path,
        source_research_snapshot_path: Path,
        source_content_plan_snapshot_path: Path | None,
        llm_available: bool,
        used_llm: bool,
        warnings: List[str],
        rewrite_final_articles: bool,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        reports = [
            article.publish_polish_report
            for article in final_articles
            if article.publish_polish_report is not None
        ]
        payload = {
            "generated_at": generated_at,
            "source_final_articles_snapshot": str(source_final_articles_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path),
            "source_content_plan_snapshot": str(source_content_plan_snapshot_path) if source_content_plan_snapshot_path else None,
            "total_count": len(reports),
            "llm_available": llm_available,
            "used_llm": used_llm,
            "warnings": warnings,
            "reports": [self._model_dump(report) for report in reports],
        }

        latest_path = snapshots_dir / "publish_polish_latest.json"
        dated_path = snapshots_dir / f"{run_date}-publish-polish.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved publish polish snapshot: {latest_path}")
        print(f"Saved dated publish polish snapshot: {dated_path}")

        if rewrite_final_articles:
            final_payload = {}
            if source_final_articles_snapshot_path.exists():
                try:
                    final_payload = json.loads(source_final_articles_snapshot_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    final_payload = {}
            final_payload.update(
                {
                    "generated_at": generated_at,
                    "total_count": len(final_articles),
                    "llm_available": llm_available,
                    "used_llm_publish_polish": used_llm,
                    "warnings": warnings,
                    "articles": [self._model_dump(article) for article in final_articles],
                }
            )
            final_latest_path = snapshots_dir / "final_articles_latest.json"
            final_dated_path = snapshots_dir / f"{run_date}-final-articles.json"
            self._write_json(final_latest_path, final_payload)
            self._write_json(final_dated_path, final_payload)
            print(f"Updated final articles snapshot: {final_latest_path}")
            print(f"Updated dated final articles snapshot: {final_dated_path}")

        final_articles_dir = self.settings.output_dir / run_date / "final_articles"
        final_articles_dir.mkdir(parents=True, exist_ok=True)
        expected_filenames = {
            f"{article.full_name.replace('/', '__')}.md"
            for article in final_articles
        }
        for stale_path in final_articles_dir.glob("*.md"):
            if stale_path.name not in expected_filenames:
                stale_path.unlink()
                print(f"Removed stale final article: {stale_path}")

        final_article_paths: list[Path] = []
        for article in final_articles:
            final_path = final_articles_dir / f"{article.full_name.replace('/', '__')}.md"
            final_path.write_text(article.content_markdown, encoding="utf-8")
            final_article_paths.append(final_path)
            print(f"Saved publish-ready final article: {final_path}")

        report_dir = self.settings.output_dir / run_date
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "publish_polish_report.md"
        report_path.write_text(
            self._build_publish_polish_report(
                run_date=run_date,
                final_articles=final_articles,
                used_llm=used_llm,
                source_final_articles_snapshot=str(source_final_articles_snapshot_path),
            ),
            encoding="utf-8",
        )
        print(f"Saved publish polish report: {report_path}")

        if rewrite_final_articles:
            final_index_path = report_dir / "final_articles_index.md"
            final_index_path.write_text(
                self._build_final_articles_index(
                    run_date=run_date,
                    final_articles=final_articles,
                    final_article_paths=final_article_paths,
                ),
                encoding="utf-8",
            )
            print(f"Updated final articles index: {final_index_path}")

    def _save_article_quality_outputs(
        self,
        final_articles: List[FinalArticle],
        source_final_articles_snapshot_path: Path,
        source_research_snapshot_path: Path,
        source_content_plan_snapshot_path: Path | None,
        llm_available: bool,
        used_llm: bool,
        warnings: List[str],
        rewrite_final_articles: bool,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        reports = [
            article.article_quality_report
            for article in final_articles
            if article.article_quality_report is not None
        ]
        low_quality = [
            report
            for report in reports
            if report.total_score < 80 or not report.publish_ready
        ]
        average_score = (
            sum(report.total_score for report in reports) / len(reports)
            if reports
            else 0.0
        )
        payload = {
            "generated_at": generated_at,
            "source_final_articles_snapshot": str(source_final_articles_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path),
            "source_content_plan_snapshot": str(source_content_plan_snapshot_path) if source_content_plan_snapshot_path else None,
            "total_count": len(reports),
            "average_score": round(average_score, 2),
            "publish_ready_count": sum(1 for report in reports if report.publish_ready),
            "low_quality_count": len(low_quality),
            "llm_available": llm_available,
            "used_llm": used_llm,
            "warnings": warnings,
            "reports": [self._model_dump(report) for report in reports],
        }

        latest_path = snapshots_dir / "article_quality_latest.json"
        dated_path = snapshots_dir / f"{run_date}-article-quality.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved article quality snapshot: {latest_path}")
        print(f"Saved dated article quality snapshot: {dated_path}")

        final_articles_dir = self.settings.output_dir / run_date / "final_articles"
        final_articles_dir.mkdir(parents=True, exist_ok=True)
        final_article_paths: list[Path] = []
        for article in final_articles:
            final_path = final_articles_dir / f"{article.full_name.replace('/', '__')}.md"
            final_path.write_text(article.content_markdown, encoding="utf-8")
            final_article_paths.append(final_path)

        if rewrite_final_articles:
            final_payload = {}
            if source_final_articles_snapshot_path.exists():
                try:
                    final_payload = json.loads(source_final_articles_snapshot_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    final_payload = {}
            final_payload.update(
                {
                    "generated_at": generated_at,
                    "total_count": len(final_articles),
                    "llm_available": llm_available,
                    "used_llm_article_quality": used_llm,
                    "warnings": warnings,
                    "articles": [self._model_dump(article) for article in final_articles],
                }
            )
            final_latest_path = snapshots_dir / "final_articles_latest.json"
            final_dated_path = snapshots_dir / f"{run_date}-final-articles.json"
            self._write_json(final_latest_path, final_payload)
            self._write_json(final_dated_path, final_payload)
            print(f"Updated final articles snapshot with article quality: {final_latest_path}")
            print(f"Updated dated final articles snapshot with article quality: {final_dated_path}")

        report_dir = self.settings.output_dir / run_date
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "article_quality_report.md"
        report_path.write_text(
            self._build_article_quality_report(
                run_date=run_date,
                final_articles=final_articles,
                used_llm=used_llm,
                source_final_articles_snapshot=str(source_final_articles_snapshot_path),
            ),
            encoding="utf-8",
        )
        print(f"Saved article quality report: {report_path}")

        if rewrite_final_articles:
            final_index_path = report_dir / "final_articles_index.md"
            final_index_path.write_text(
                self._build_final_articles_index(
                    run_date=run_date,
                    final_articles=final_articles,
                    final_article_paths=final_article_paths,
                ),
                encoding="utf-8",
            )
            print(f"Updated final articles index with article quality: {final_index_path}")

    def _save_article_package_outputs(
        self,
        packages: list[ArticlePackage],
        run_date: str,
        source_final_articles_snapshot_path: Path,
        source_research_snapshot_path: Path,
        source_content_plan_snapshot_path: Path | None,
    ) -> None:
        snapshots_dir = self.settings.workspace_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = {
            "generated_at": generated_at,
            "source_final_articles_snapshot": str(source_final_articles_snapshot_path),
            "source_research_snapshot": str(source_research_snapshot_path),
            "source_content_plan_snapshot": str(source_content_plan_snapshot_path) if source_content_plan_snapshot_path else None,
            "total_count": len(packages),
            "packages": [self._model_dump(article_package) for article_package in packages],
        }

        latest_path = snapshots_dir / "article_packages_latest.json"
        dated_path = snapshots_dir / f"{run_date}-article-packages.json"
        self._write_json(latest_path, payload)
        self._write_json(dated_path, payload)
        print(f"Saved article package snapshot: {latest_path}")
        print(f"Saved dated article package snapshot: {dated_path}")
        self._update_final_articles_with_package_metadata(
            packages=packages,
            source_final_articles_snapshot_path=source_final_articles_snapshot_path,
            run_date=run_date,
        )

        report_dir = self.settings.output_dir / run_date
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "article_packages.md"
        report_path.write_text(
            self._build_article_packages_report(
                run_date=run_date,
                packages=packages,
                source_final_articles_snapshot=str(source_final_articles_snapshot_path),
            ),
            encoding="utf-8",
        )
        print(f"Saved article packages report: {report_path}")

    def _update_final_articles_with_package_metadata(
        self,
        packages: list[ArticlePackage],
        source_final_articles_snapshot_path: Path,
        run_date: str,
    ) -> None:
        if not packages or not source_final_articles_snapshot_path.exists():
            return
        try:
            final_payload = json.loads(source_final_articles_snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        article_items = final_payload.get("articles")
        if not isinstance(article_items, list):
            return
        packages_by_name = {package.full_name: package for package in packages}
        changed = False
        for article in article_items:
            if not isinstance(article, dict):
                continue
            package = packages_by_name.get(str(article.get("full_name") or ""))
            if package is None:
                continue
            article["package_path"] = package.packaged_article_path
            article["packaged_article_path"] = package.packaged_article_path
            article["packaged_article_available"] = bool(package.packaged_article_path)
            article["asset_count"] = len(package.assets)
            changed = True
        if not changed:
            return
        final_payload["generated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        final_latest_path = self.settings.workspace_dir / "snapshots" / "final_articles_latest.json"
        final_dated_path = self.settings.workspace_dir / "snapshots" / f"{run_date}-final-articles.json"
        self._write_json(final_latest_path, final_payload)
        self._write_json(final_dated_path, final_payload)
        print(f"Updated final articles package metadata: {final_latest_path}")

    def _build_score_report(
        self,
        run_date: str,
        source_snapshot: str,
        scores: List[RepoScore],
        candidates: List[RepoCandidate],
    ) -> str:
        candidates_by_name = {candidate.full_name: candidate for candidate in candidates}
        lines = [
            "# GitHubRadarAgent 候选项目评分报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 候选项目数量：{len(scores)}",
            f"- 数据来源：{source_snapshot}",
            "",
            "## Top 项目",
            "",
            "| 排名 | 项目 | 总分 | 相关度 | 热度规模 | 增长速度 | 新鲜度 | 活跃度 | 发现来源 | 推荐理由 | 风险提示 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]

        for rank, score in enumerate(scores[:10], start=1):
            candidate = candidates_by_name.get(score.full_name)
            project = f"[{score.full_name}]({score.html_url})"
            if candidate is not None:
                project = f"{project}<br>{candidate.language or '-'} · {candidate.stars} stars"
            reasons = self._markdown_table_cell("; ".join(score.reasons[:3]) or "-")
            warnings = self._markdown_table_cell("; ".join(score.warnings[:3]) or "-")
            lines.append(
                "| "
                f"{rank} | {project} | {score.total_score:.2f} | {score.relevance_score:.2f} | "
                f"{score.growth_score:.2f} | {score.velocity_score:.2f} | {score.freshness_score:.2f} | "
                f"{score.activity_score:.2f} | {score.discovery_reason or '-'} | {reasons} | {warnings} |"
            )

        lines.extend(
            [
                "",
                "## 评分规则说明",
                "",
                "- 热度规模 growth_score：18 分，保留 stars/forks 的质量参考，但降低总量压倒性。",
                "- 增长速度 velocity_score：17 分，根据创建时间、Star 密度、recent_active/newly_created/practical_tool 来源加权。",
                "- 新鲜度 freshness_score：10 分，根据最近 pushed_at / updated_at 是否在 7/30/90 天窗口内评分。",
                "- 相关度 relevance_score：22 分，根据项目名称、描述、topics、语言中的 AI/Agent/工具关键词命中情况评分。",
                "- 基础质量 quality_score：18 分，综合 description、topics、license、stars/forks 比例和 open issues 风险。",
                "- 维护活跃度 activity_score：10 分，根据 pushed_at / updated_at 距离 2026-07-04 的天数评分。",
                "- 传播潜力 communication_score：5 分，评估描述清晰度、项目名可理解度、趋势技术词和实用工具传播性。",
                "",
                "说明：当前评分为确定性启发式规则，不调用 LLM。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _build_repo_note_markdown(self, note: RepoResearchNote) -> str:
        lines = [
            f"# {note.full_name}",
            "",
            "## 基本信息",
            f"- GitHub: {note.html_url}",
            f"- Stars: {note.stars}",
            f"- Forks: {note.forks}",
            f"- Language: {note.language or '-'}",
            f"- License: {note.license_name or '-'}",
            f"- Topics: {', '.join(note.topics) if note.topics else '-'}",
            f"- Last Push: {note.pushed_at or '-'}",
            f"- Project Kind: {note.project_kind or '-'}",
            "",
            "## 作者/组织背景",
            "",
        ]
        lines.extend(self._author_profile_bullets(note.author_profile))
        lines.extend(
            [
                "",
                "## 项目链接",
                "",
            ]
        )
        lines.extend(self._project_links_bullets(note.project_links))
        lines.extend(
            [
                "",
                "## README 图片/视频素材",
                "",
            ]
        )
        media_links = []
        if note.project_links:
            media_links.extend(note.project_links.images)
            media_links.extend(note.project_links.videos)
        lines.extend(self._markdown_bullets(self._dedupe_markdown_items(media_links)))
        lines.extend(
            [
                "",
                "## 工具使用场景",
                "",
            ]
        )
        lines.extend(self._markdown_bullets(note.tool_use_cases))
        lines.extend(
            [
                "",
                "## README 摘要",
                "",
                note.readme_summary or "-",
                "",
                "## README 关键点",
                "",
            ]
        )
        lines.extend(self._markdown_bullets(note.readme_key_points))
        lines.extend(["", "## 最新 Releases", ""])
        lines.extend(self._release_bullets(note.releases))
        lines.extend(["", "## 当前 Open Issues", ""])
        lines.extend(self._issue_bullets(note.open_issues))
        lines.extend(["", "## 来源链接", ""])
        lines.extend(self._markdown_bullets(note.source_links))
        lines.extend(["", "## 风险提示", ""])
        lines.extend(self._markdown_bullets(note.risks))
        return "\n".join(lines) + "\n"

    def _build_research_report(
        self,
        run_date: str,
        source_score_snapshot: str,
        notes: List[RepoResearchNote],
        note_paths: List[Path],
    ) -> str:
        note_paths_by_name = {
            note.full_name: note_path
            for note, note_path in zip(notes, note_paths)
        }
        lines = [
            "# GitHubRadarAgent 项目深度调研笔记",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 调研项目数量：{len(notes)}",
            f"- 数据来源：{source_score_snapshot}",
            "- 摘要方式：GitHub API + README 启发式摘要，未调用 LLM",
            "",
            "## Top 项目摘要",
            "",
        ]

        for rank, note in enumerate(notes, start=1):
            note_path = note_paths_by_name.get(note.full_name)
            note_link = str(note_path) if note_path is not None else "-"
            risks = "; ".join(note.risks[:3]) or "暂未识别明显风险"
            author = note.author_profile.html_url if note.author_profile else "-"
            docs = "; ".join(note.project_links.documentation[:3]) if note.project_links else ""
            demos = "; ".join(note.project_links.demo[:3]) if note.project_links else ""
            homepage = note.project_links.homepage if note.project_links and note.project_links.homepage else "-"
            media_count = len(note.readme_images or []) + (len(note.project_links.videos) if note.project_links else 0)
            use_cases = "; ".join(note.tool_use_cases[:3]) or "-"
            lines.extend(
                [
                    f"### {rank}. {note.full_name}",
                    "",
                    f"- GitHub: {note.html_url}",
                    f"- 本地笔记: {note_link}",
                    f"- Stars/Forks: {note.stars}/{note.forks}",
                    f"- Language: {note.language or '-'}",
                    f"- License: {note.license_name or '-'}",
                    f"- 项目类型: {note.project_kind or '-'}",
                    f"- 作者/组织背景: {author}",
                    f"- 项目主页: {homepage}",
                    f"- Docs: {docs or '-'}",
                    f"- Demo: {demos or '-'}",
                    f"- README 图片/视频素材数: {media_count}",
                    f"- 工具使用场景: {use_cases}",
                    f"- README 摘要: {note.readme_summary[:300]}",
                    f"- 风险提示: {risks}",
                    "",
                ]
            )

        return "\n".join(lines)

    def _build_angle_report(
        self,
        run_date: str,
        source_research_snapshot: str,
        angles: List[TopicAngle],
        used_llm: bool,
    ) -> str:
        lines = [
            "# GitHubRadarAgent 公众号选题角度报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 项目数量：{len(angles)}",
            f"- 是否使用 LLM：{'是' if used_llm else '否，已使用启发式 fallback'}",
            f"- 数据来源：{source_research_snapshot}",
            "",
            "## 项目选题",
            "",
        ]

        for rank, angle in enumerate(angles, start=1):
            lines.extend(
                [
                    f"### {rank}. {angle.full_name}",
                    "",
                    f"- 项目名：{angle.project_name}",
                    f"- GitHub 链接：{angle.html_url}",
                    f"- 推荐角度：{angle.selected_angle}",
                    f"- 一句话介绍：{angle.one_liner}",
                    "",
                    "#### 目标读者",
                    "",
                ]
            )
            lines.extend(self._markdown_bullets(angle.target_readers))
            lines.extend(["", "#### 读者痛点", ""])
            lines.extend(self._markdown_bullets(angle.reader_pain_points))
            lines.extend(["", "#### 传播卖点", ""])
            lines.extend(self._markdown_bullets(angle.selling_points))
            lines.extend(["", "#### 标题候选", ""])
            lines.extend(self._title_candidate_bullets(angle.title_candidates))
            lines.extend(
                [
                    "",
                    "#### 开头钩子",
                    "",
                    angle.opening_hook or "-",
                    "",
                    "#### 文章大纲",
                    "",
                ]
            )
            lines.extend(self._markdown_bullets(angle.article_outline))
            lines.extend(
                [
                    "",
                    "#### 封面提示词",
                    "",
                    angle.cover_prompt or "-",
                    "",
                    "#### 事实风险",
                    "",
                ]
            )
            lines.extend(self._markdown_bullets(angle.factual_warnings))
            lines.extend(["", "#### 来源链接", ""])
            lines.extend(self._markdown_bullets(angle.source_links))
            lines.append("")

        return "\n".join(lines)

    def _build_content_plan_report(
        self,
        run_date: str,
        source_research_snapshot: str,
        source_angles_snapshot: str | None,
        plans: list[dict[str, Any]],
        used_llm: bool,
    ) -> str:
        lines = [
            "# 内容策划中间产物报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 项目数量：{len(plans)}",
            f"- 是否使用 LLM：{'是' if used_llm else '否，已使用启发式 fallback'}",
            f"- 调研数据来源：{source_research_snapshot}",
            f"- 选题数据来源：{source_angles_snapshot or '未提供，按调研笔记 fallback'}",
            "",
            "## 项目内容计划",
            "",
        ]

        for rank, plan in enumerate(plans, start=1):
            facts = plan.get("facts", [])
            insight = plan.get("insight")
            brief = plan.get("brief")
            appeal = plan.get("appeal")
            impact = plan.get("impact")
            wechat_pattern = plan.get("wechat_pattern")
            warnings = plan.get("warnings") or []
            author_profile = plan.get("author_profile")
            project_links = plan.get("project_links")
            lines.extend(
                [
                    f"### {rank}. {plan.get('full_name') or '-'}",
                    "",
                    f"- 生成模式：{plan.get('planning_mode') or '-'}",
                    f"- 项目类型：{plan.get('project_kind') or '-'}",
                    "",
                    "#### 作者/组织 Facts",
                    "",
                ]
            )
            lines.extend(self._author_profile_bullets(author_profile))
            lines.extend(["", "#### Project Links Facts", ""])
            lines.extend(self._project_links_bullets(project_links))
            lines.extend(["", "#### 工具使用场景 Facts", ""])
            lines.extend(self._markdown_bullets(plan.get("tool_use_cases", [])))
            lines.extend(
                [
                    "",
                    "#### 事实卡摘要",
                    "",
                ]
            )
            lines.extend(self._fact_card_bullets(facts))
            lines.extend(["", "#### 项目理解卡", ""])
            if insight is not None:
                lines.extend(
                    [
                        f"- 项目名：{getattr(insight, 'project_name', '-')}",
                        f"- 白话总结：{getattr(insight, 'plain_summary', '-')}",
                        f"- 解决问题：{getattr(insight, 'problem_solved', '-')}",
                        f"- 核心价值：{getattr(insight, 'core_value', '-')}",
                        f"- 本土化理解：{getattr(insight, 'local_context', '-')}",
                        "",
                        "适合用户：",
                    ]
                )
                lines.extend(self._markdown_bullets(getattr(insight, "ideal_users", [])))
                lines.extend(["", "使用场景："])
                lines.extend(self._markdown_bullets(getattr(insight, "use_cases", [])))
                lines.extend(["", "真正值得说的亮点："])
                lines.extend(self._markdown_bullets(getattr(insight, "standout_points", [])))
                lines.extend(["", "使用前注意："])
                lines.extend(self._markdown_bullets(getattr(insight, "adoption_notes", [])))
            else:
                lines.append("- -")

            lines.extend(["", "#### 主编 Brief", ""])
            if brief is not None:
                narrative_strategy = getattr(brief, "narrative_strategy", None)
                title_strategy = getattr(brief, "title_strategy", None)
                lines.extend(
                    [
                        f"- 推荐角度：{getattr(brief, 'recommended_angle', '-')}",
                        f"- 叙事模式：{getattr(brief, 'narrative_pattern', '-')}",
                        f"- 目标读者：{getattr(brief, 'target_reader', '-')}",
                        f"- 读者收获：{getattr(brief, 'reader_takeaway', '-')}",
                        f"- 开头方向：{getattr(brief, 'opening_direction', '-')}",
                        f"- 语气：{getattr(brief, 'tone', '-')}",
                        "",
                        "标题方向：",
                    ]
                )
                lines.extend(self._markdown_bullets(getattr(brief, "title_direction", [])))
                lines.extend(["", "必须包含："])
                lines.extend(self._markdown_bullets(getattr(brief, "must_include", [])))
                lines.extend(["", "建议推进结构："])
                lines.extend(self._markdown_bullets(getattr(brief, "suggested_structure", [])))
                lines.extend(["", "#### 叙事策略", ""])
                if narrative_strategy is not None:
                    lines.extend(
                        [
                            f"- Pattern：{getattr(narrative_strategy, 'pattern', '-')}",
                            f"- Rationale：{getattr(narrative_strategy, 'rationale', '-')}",
                            f"- Opening Style：{getattr(narrative_strategy, 'opening_style', '-')}",
                            f"- Structure Style：{getattr(narrative_strategy, 'structure_style', '-')}",
                            f"- Title Style：{getattr(narrative_strategy, 'title_style', '-')}",
                            "",
                            "避免写法：",
                        ]
                    )
                    lines.extend(self._markdown_bullets(getattr(narrative_strategy, "avoid_patterns", [])))
                    lines.extend(["", "转场提示："])
                    lines.extend(self._markdown_bullets(getattr(narrative_strategy, "transition_notes", [])))
                else:
                    lines.append("- -")

                lines.extend(["", "#### 标题策略", ""])
                if title_strategy is not None:
                    lines.extend([f"- 策略说明：{getattr(title_strategy, 'rationale', '-')}", "", "标题方向："])
                    lines.extend(self._markdown_bullets(getattr(title_strategy, "directions", [])))
                    lines.extend(["", "禁用标题模板："])
                    lines.extend(self._markdown_bullets(getattr(title_strategy, "banned_templates", [])))
                    lines.extend(["", "标题候选："])
                    lines.extend(self._title_candidate_bullets(getattr(title_strategy, "title_candidates", [])))
                else:
                    lines.append("- -")

                lines.extend(["", "#### 人味写作规则", ""])
                lines.extend(self._markdown_bullets(getattr(brief, "human_tone_rules", [])))
                lines.extend(["", "#### 自然段落推进计划", ""])
                lines.extend(self._markdown_bullets(getattr(brief, "paragraph_plan", [])))
                lines.extend(["", "#### 本文差异化点", ""])
                lines.extend(self._markdown_bullets(getattr(brief, "article_differentiators", [])))
            else:
                lines.append("- -")

            lines.extend(["", "#### 项目吸引力卡", ""])
            if appeal is not None:
                lines.extend(
                    [
                        f"- 项目吸引力一句话：{self._object_field(appeal, 'appeal_summary', '-')}",
                        f"- 最适合开头抓人的点：{self._object_field(appeal, 'primary_hook', '-')}",
                        f"- 置信度：{self._object_field(appeal, 'confidence', '-')}",
                        "",
                        "特点 -> 优势 -> 读者兴趣：",
                    ]
                )
                lines.extend(self._feature_advantage_bullets(self._object_field(appeal, "feature_advantages", [])))
                lines.extend(["", "重点卖点："])
                lines.extend(self._markdown_bullets(self._object_field(appeal, "top_selling_points", [])))
                lines.extend(["", "读者兴趣点："])
                lines.extend(self._markdown_bullets(self._object_field(appeal, "reader_interest_points", [])))
                lines.extend(["", "适合放进文章的场景："])
                lines.extend(self._markdown_bullets(self._object_field(appeal, "practical_scenarios", [])))
                lines.extend(["", "差异点："])
                lines.extend(self._markdown_bullets(self._object_field(appeal, "differentiation_points", [])))
                lines.extend(["", "不要过度强调的点："])
                lines.extend(self._markdown_bullets(self._object_field(appeal, "avoid_overemphasis", [])))
                lines.extend(["", "本文推荐聚焦："])
                lines.extend(self._markdown_bullets(self._object_field(appeal, "recommended_focus", [])))
            else:
                lines.append("- -")

            lines.extend(["", "#### 项目作用与效果", ""])
            if impact is not None:
                lines.extend(
                    [
                        f"- 核心效果：{self._object_field(impact, 'core_effect', '-')}",
                        f"- 效果摘要：{self._object_field(impact, 'effect_summary', '-')}",
                        "",
                        "具体结果：",
                    ]
                )
                lines.extend(self._markdown_bullets(self._object_field(impact, "concrete_outcomes", [])))
                lines.extend(["", "使用例子："])
                lines.extend(self._markdown_bullets(self._object_field(impact, "usage_examples", [])))
                lines.extend(["", "文章可展开点："])
                lines.extend(self._markdown_bullets(self._object_field(impact, "article_expansion_points", [])))
            else:
                lines.append("- -")

            lines.extend(["", "#### 公众号项目分享策略", ""])
            if wechat_pattern is not None:
                lines.extend(
                    [
                        f"- Pattern Type：{self._object_field(wechat_pattern, 'pattern_type', '-')}",
                        f"- Opening Strategy：{self._object_field(wechat_pattern, 'opening_strategy', '-')}",
                        f"- Lead Hook：{self._object_field(wechat_pattern, 'lead_hook', '-')}",
                        f"- Key Storyline：{self._object_field(wechat_pattern, 'key_storyline', '-')}",
                        "",
                        "必须展开的效果点：",
                    ]
                )
                lines.extend(self._markdown_bullets(self._object_field(wechat_pattern, "required_effect_points", [])))
                lines.extend(["", "必须展开的例子："])
                lines.extend(self._markdown_bullets(self._object_field(wechat_pattern, "required_examples", [])))
                lines.extend(["", "配图放置提示："])
                lines.extend(self._markdown_bullets(self._object_field(wechat_pattern, "image_placement_hints", [])))
            else:
                lines.append("- -")

            lines.extend(["", "#### 不应夸大的点", ""])
            not_to_overclaim = getattr(insight, "not_to_overclaim", []) if insight is not None else []
            should_avoid = getattr(brief, "should_avoid", []) if brief is not None else []
            lines.extend(self._markdown_bullets(self._dedupe_markdown_items(list(not_to_overclaim) + list(should_avoid))))
            lines.extend(["", "#### 视觉需求", ""])
            visual_needs = getattr(brief, "visual_needs", []) if brief is not None else []
            lines.extend(self._markdown_bullets(list(visual_needs)))
            if warnings:
                lines.extend(["", "#### 生成警告", ""])
                lines.extend(self._markdown_bullets([str(warning) for warning in warnings]))
            lines.append("")

        return "\n".join(lines)

    def _build_article_report(
        self,
        run_date: str,
        source_angles_snapshot: str,
        drafts: List[ArticleDraft],
        article_paths: List[Path],
        used_llm: bool,
    ) -> str:
        article_paths_by_name = {
            draft.full_name: article_path
            for draft, article_path in zip(drafts, article_paths)
        }
        lines = [
            "# GitHubRadarAgent 公众号文章初稿",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 项目数量：{len(drafts)}",
            f"- 是否使用 LLM：{'是' if used_llm else '否，已使用模板化 fallback'}",
            f"- 数据来源：{source_angles_snapshot}",
            "",
            "## 初稿摘要",
            "",
        ]

        for rank, draft in enumerate(drafts, start=1):
            article_path = article_paths_by_name.get(draft.full_name)
            source_links = "; ".join(draft.source_links[:4]) or draft.html_url
            warnings = "; ".join(draft.factual_warnings[:3]) or "暂未识别明显事实风险"
            writer_persona = draft.writer_persona.persona if draft.writer_persona else "-"
            writer_voice = draft.writer_persona.voice if draft.writer_persona else "-"
            lines.extend(
                [
                    f"### {rank}. {draft.full_name}",
                    "",
                    f"- 标题：{draft.title}",
                    f"- GitHub：{draft.html_url}",
                    f"- 本地初稿：{article_path if article_path is not None else '-'}",
                    f"- 生成模式：{draft.generation_mode}",
                    f"- 使用内容策划：{'是' if draft.content_plan_used else '否'}",
                    f"- Writer Persona：{writer_persona}",
                    f"- Writer Voice：{writer_voice}",
                    f"- 已使用主卖点：{'; '.join(draft.top_selling_points_used) or '-'}",
                    f"- 已使用场景：{'; '.join(draft.practical_scenarios_used) or '-'}",
                    f"- 叙事模式：{draft.narrative_pattern or '-'}",
                    f"- 标题风格：{draft.title_style or '-'}",
                    f"- 风格备注：{'; '.join(draft.article_style_notes[:4]) or '-'}",
                    f"- 字数估算：{draft.word_count}",
                    f"- 摘要：{draft.summary}",
                    f"- 来源链接：{source_links}",
                    f"- 事实风险：{warnings}",
                    "",
                ]
            )

        return "\n".join(lines)

    def _build_articles_index(
        self,
        run_date: str,
        drafts: List[ArticleDraft],
        article_paths: List[Path],
    ) -> str:
        article_paths_by_name = {
            draft.full_name: article_path
            for draft, article_path in zip(drafts, article_paths)
        }
        lines = [
            "# GitHubRadarAgent 公众号文章初稿索引",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 文章数量：{len(drafts)}",
            "",
            "## 初稿列表",
            "",
            "| 标题 | 项目链接 | 字数 | 生成模式 | 本地文章路径 |",
            "| --- | --- | ---: | --- | --- |",
        ]

        for draft in drafts:
            article_path = article_paths_by_name.get(draft.full_name)
            project = f"[{draft.full_name}]({draft.html_url})" if draft.html_url else draft.full_name
            local_path = str(article_path) if article_path is not None else "-"
            lines.append(
                "| "
                f"{self._markdown_table_cell(draft.title)} | {project} | "
                f"{draft.word_count} | {draft.generation_mode} | {local_path} |"
            )

        lines.append("")
        return "\n".join(lines)

    def _build_review_report(
        self,
        run_date: str,
        reviews: List[ArticleReview],
        final_articles: List[FinalArticle],
        used_llm: bool,
        pass_threshold: float,
        humanization_llm_used: bool = False,
        humanization_fallback_used: bool = False,
    ) -> str:
        articles_by_name = {article.full_name: article for article in final_articles}
        lines = [
            "# GitHubRadarAgent 文章评审报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 文章数量：{len(reviews)}",
            f"- 是否使用 LLM：{'是' if used_llm else '否，已使用启发式 fallback'}",
            f"- 通过阈值：{pass_threshold:.0f}",
            f"- 去 AI 味 LLM：{'是' if humanization_llm_used else '否'}",
            f"- 去 AI 味 fallback：{'是' if humanization_fallback_used else '否'}",
            "",
            "## 评审结果",
            "",
            "| 项目 | 标题 | 总分 | 事实分 | 标题分 | 结构分 | 可读性 | 完整度 | 是否通过 | 主要问题 | 修改建议 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]

        for review in reviews:
            article = articles_by_name.get(review.full_name)
            project = review.full_name
            if article is not None and article.html_url:
                project = f"[{review.full_name}]({article.html_url})"
            issues = self._markdown_table_cell("; ".join(review.issues[:3]) or "-")
            suggestions = self._markdown_table_cell("; ".join(review.revision_suggestions[:3]) or "-")
            title = self._markdown_table_cell(review.title)
            lines.append(
                "| "
                f"{project} | {title} | {review.total_score:.2f} | {review.factual_score:.2f} | "
                f"{review.title_score:.2f} | {review.structure_score:.2f} | "
                f"{review.readability_score:.2f} | {review.completeness_score:.2f} | "
                f"{'是' if review.pass_review else '否'} | {issues} | {suggestions} |"
            )

        lines.extend(
            [
                "",
                "## 去 AI 味检查",
                "",
                "| 项目 | 是否润色 | 自然度 | 模板风险 | README 搬运风险 | 本土化分 | 是否通过 | 主要问题 |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for article in final_articles:
            report = article.humanization_report
            if report is None:
                lines.append(f"| {article.full_name} | 否 | - | - | - | - | - | - |")
                continue
            issues = self._markdown_table_cell("; ".join(f"{issue.category}: {issue.text}" for issue in report.issues[:3]) or "-")
            project = f"[{article.full_name}]({article.html_url})" if article.html_url else article.full_name
            lines.append(
                "| "
                f"{project} | {'是' if article.humanized else '否'} | "
                f"{report.ai_smell_score:.2f} | {report.template_risk:.2f} | "
                f"{report.readme_similarity_risk:.2f} | {report.localization_score:.2f} | "
                f"{'是' if report.pass_humanization else '否'} | {issues} |"
            )

        lines.extend(
            [
                "",
                "## 评分说明",
                "",
                "- factual_score：30 分，检查事实是否基于资料、是否保留来源链接、是否有无法验证的夸张表述。",
                "- title_score：20 分，检查标题是否清楚、有吸引力且不过度标题党。",
                "- structure_score：20 分，检查是否包含开头、项目是什么、为什么值得关注、核心亮点、适合谁、上手方式、小结、参考链接。",
                "- readability_score：15 分，检查公众号阅读体验、段落清晰度和技术堆砌情况。",
                "- completeness_score：15 分，检查项目基本信息、亮点、适用人群、风险提示和参考链接覆盖情况。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _build_humanization_report(
        self,
        run_date: str,
        final_articles: List[FinalArticle],
        used_llm: bool,
        used_fallback: bool,
        source_final_articles_snapshot: str,
    ) -> str:
        lines = [
            "# GitHubRadarAgent 去 AI 味编辑报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 文章数量：{len(final_articles)}",
            f"- 是否使用 LLM：{'是' if used_llm else '否'}",
            f"- 是否使用 fallback 改写：{'是' if used_fallback else '否'}",
            f"- 数据来源：{source_final_articles_snapshot}",
            "",
            "## 检查结果",
            "",
            "| 项目 | 标题 | 已润色 | 自然度 | 模板风险 | README 搬运风险 | 本土化分 | 模式 | 主要问题 | 改写建议 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
        for article in final_articles:
            report = article.humanization_report
            if report is None:
                lines.append(
                    "| "
                    f"{article.full_name} | {self._markdown_table_cell(article.title)} | 否 | "
                    "- | - | - | - | - | - | - |"
                )
                continue
            project = f"[{article.full_name}]({article.html_url})" if article.html_url else article.full_name
            issues = self._markdown_table_cell("; ".join(f"{issue.category}/{issue.severity}: {issue.text}" for issue in report.issues[:4]) or "-")
            suggestions = self._markdown_table_cell("; ".join(report.rewrite_suggestions[:4]) or "-")
            lines.append(
                "| "
                f"{project} | {self._markdown_table_cell(article.title)} | {'是' if article.humanized else '否'} | "
                f"{report.ai_smell_score:.2f} | {report.template_risk:.2f} | "
                f"{report.readme_similarity_risk:.2f} | {report.localization_score:.2f} | "
                f"{report.mode} | {issues} | {suggestions} |"
            )

        lines.extend(
            [
                "",
                "## 说明",
                "",
                "- 自然度 ai_smell_score：越高越像自然中文技术分享。",
                "- 模板风险 template_risk：越高越像固定公众号模板。",
                "- README 搬运风险 readme_similarity_risk：越高越需要人工复核与改写。",
                "- 本土化分 localization_score：越高越贴近中文开发者语境。",
                "- 这个编辑器用于提升原创表达和阅读质量，不承诺规避任何平台检测。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _build_publish_polish_report(
        self,
        run_date: str,
        final_articles: List[FinalArticle],
        used_llm: bool,
        source_final_articles_snapshot: str,
    ) -> str:
        lines = [
            "# GitHubRadarAgent 发布稿清理报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 文章数量：{len(final_articles)}",
            f"- 是否使用 LLM：{'是' if used_llm else '否，仅使用确定性规则'}",
            f"- 数据来源：{source_final_articles_snapshot}",
            "",
            "## 清理结果",
            "",
            "| 项目 | 标题 | 发布就绪 | 模式 | 保留链接 | 删除小节 | 删除短语 | 剩余问题 | 备注 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for article in final_articles:
            report = article.publish_polish_report
            project = f"[{article.full_name}]({article.html_url})" if article.html_url else article.full_name
            if report is None:
                lines.append(
                    "| "
                    f"{project} | {self._markdown_table_cell(article.title)} | 否 | - | - | - | - | 未生成发布稿报告 | - |"
                )
                continue
            lines.append(
                "| "
                f"{project} | {self._markdown_table_cell(article.title)} | "
                f"{'是' if report.publish_ready else '否'} | {report.mode} | "
                f"{self._markdown_table_cell('; '.join(report.kept_links) or '-')} | "
                f"{self._markdown_table_cell('; '.join(report.removed_sections[:6]) or '-')} | "
                f"{self._markdown_table_cell('; '.join(report.removed_phrases[:8]) or '-')} | "
                f"{self._markdown_table_cell('; '.join(report.remaining_issues[:5]) or '-')} | "
                f"{self._markdown_table_cell('; '.join(report.notes[:5]) or '-')} |"
            )

        lines.extend(
            [
                "",
                "## 规则说明",
                "",
                "- 正文只保留一个项目地址，不展示 docs、release、issues、社媒或包管理器链接。",
                "- 删除阅读提醒、事实风险列表、审稿口吻和资料卡式作者背景。",
                "- 如果仍需要提醒，压缩成适合公众号发布的自然表达。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _build_article_quality_report(
        self,
        run_date: str,
        final_articles: List[FinalArticle],
        used_llm: bool,
        source_final_articles_snapshot: str,
    ) -> str:
        reports = [
            article.article_quality_report
            for article in final_articles
            if article.article_quality_report is not None
        ]
        average_score = sum(report.total_score for report in reports) / len(reports) if reports else 0.0
        low_reports = [report for report in reports if report.total_score < 80 or not report.publish_ready]
        lines = [
            "# GitHubRadarAgent 公众号文章质量评估报告",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 文章数量：{len(final_articles)}",
            f"- 平均质量分：{average_score:.2f}",
            f"- 低于阈值文章：{len(low_reports)}",
            f"- 是否使用 LLM 辅助：{'是' if used_llm else '否，仅使用确定性规则'}",
            f"- 数据来源：{source_final_articles_snapshot}",
            "",
            "## 总览",
            "",
            "| 项目 | 标题 | 质量分 | 可发布 | 标题 | 开头 | 项目价值 | 具体例子 | 效果展开 | 可读性 | 人味 | 反 README | 公众号结构 | 主要问题 |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for article in final_articles:
            report = article.article_quality_report
            project = f"[{article.full_name}]({article.html_url})" if article.html_url else article.full_name
            if report is None:
                lines.append(
                    "| "
                    f"{project} | {self._markdown_table_cell(article.title)} | - | 否 | "
                    "- | - | - | - | - | - | - | - | - | 未生成质量报告 |"
                )
                continue
            issues = self._markdown_table_cell(
                "; ".join(f"{issue.issue_type}/{issue.severity}: {issue.description}" for issue in report.issues[:4]) or "-"
            )
            lines.append(
                "| "
                f"{project} | {self._markdown_table_cell(report.title)} | {report.total_score:.2f} | "
                f"{'是' if report.publish_ready else '否'} | "
                f"{report.title_score:.2f} | {report.opening_score:.2f} | "
                f"{report.project_value_score:.2f} | {report.concrete_example_score:.2f} | "
                f"{report.effect_depth_score:.2f} | {report.readability_score:.2f} | "
                f"{report.human_tone_score:.2f} | {report.anti_readme_score:.2f} | "
                f"{report.wechat_style_score:.2f} | {issues} |"
            )

        lines.extend(["", "## 修改建议", ""])
        for article in final_articles:
            report = article.article_quality_report
            if report is None:
                continue
            lines.extend(
                [
                    f"### {article.full_name}",
                    "",
                    f"- 质量分：{report.total_score:.2f}",
                    f"- 可发布：{'是' if report.publish_ready else '否'}",
                    f"- 摘要：{report.summary or '-'}",
                    "",
                    "主要问题：",
                ]
            )
            issue_lines = [
                f"{issue.issue_type}/{issue.severity}：{issue.description}"
                + (f"（证据：{issue.evidence}）" if issue.evidence else "")
                for issue in report.issues
            ]
            lines.extend(self._markdown_bullets(issue_lines))
            lines.extend(["", "建议："])
            lines.extend(self._markdown_bullets(report.rewrite_recommendations))
            lines.extend(["", "亮点："])
            lines.extend(self._markdown_bullets(report.strengths))
            lines.append("")

        lines.extend(
            [
                "## 评分说明",
                "",
                "- total_score：0-100，80 分以上且没有 high 问题时视为可发布。",
                "- title/opening/project_value/concrete_example/effect_depth/readability/human_tone/anti_readme/wechat_style 均为 0-100。",
                "- 质量分不会阻止文章生成，只提示是否适合直接发布，以及优先改哪里。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _build_article_packages_report(
        self,
        run_date: str,
        packages: list[ArticlePackage],
        source_final_articles_snapshot: str,
    ) -> str:
        lines = [
            "# 公众号文章配图与发布包索引",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 发布包数量：{len(packages)}",
            f"- 终稿数据来源：{source_final_articles_snapshot}",
            "",
            "## 发布包列表",
            "",
            "| 项目 | 标题 | 状态 | 发布稿 | 包目录 | 配图来源 | 失败素材 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]

        for article_package in packages:
            readme_assets = [
                f"{asset.title}({asset.format})"
                for asset in article_package.assets
                if asset.asset_type == "readme_image"
            ]
            readme_screenshot = next(
                (
                    asset for asset in article_package.assets
                    if asset.asset_type == "github_readme_screenshot" and asset.status == "generated"
                ),
                None,
            )
            repo_screenshot = next(
                (
                    asset for asset in article_package.assets
                    if asset.asset_type == "github_repo_screenshot" and asset.status == "generated"
                ),
                None,
            )
            failed_assets = [
                f"{asset.title}: {asset.error or '-'}"
                for asset in article_package.assets
                if asset.status == "failed"
            ]
            source_summary = (
                f"README 图片：{'; '.join(readme_assets)}"
                if readme_assets
                else f"GitHub README 页面截图：{readme_screenshot.output_path}"
                if readme_screenshot
                else f"GitHub 仓库首页截图：{repo_screenshot.output_path}"
                if repo_screenshot
                else "截图失败，发布稿不插图"
                if failed_assets
                else "未插图"
            )
            project = self._markdown_table_cell(article_package.full_name)
            lines.append(
                "| "
                f"{project} | {self._markdown_table_cell(article_package.title)} | "
                f"{article_package.status} | {article_package.packaged_article_path} | "
                f"{article_package.package_dir} | "
                f"{self._markdown_table_cell(source_summary)} | "
                f"{self._markdown_table_cell('; '.join(failed_assets) or '-')} |"
            )

        lines.extend(["", "## 素材明细", ""])
        for article_package in packages:
            source_summary = "未插图"
            if any(asset.asset_type == "readme_image" for asset in article_package.assets):
                source_summary = "README 图片"
            elif any(
                asset.asset_type == "github_readme_screenshot" and asset.status == "generated"
                for asset in article_package.assets
            ):
                source_summary = "GitHub README 页面截图"
            elif any(
                asset.asset_type == "github_repo_screenshot" and asset.status == "generated"
                for asset in article_package.assets
            ):
                source_summary = "GitHub 仓库首页截图"
            elif any(asset.status == "failed" for asset in article_package.assets):
                source_summary = "截图失败，发布稿不插图"
            lines.extend(
                [
                    f"### {article_package.full_name}",
                    "",
                    f"- 发布稿：{article_package.packaged_article_path}",
                    f"- 包目录：{article_package.package_dir}",
                    f"- 配图来源：{source_summary}",
                    "",
                    "| 素材 | 类型 | 格式 | 状态 | 来源 URL | 输出路径 | 错误 |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for asset in article_package.assets:
                lines.append(
                    "| "
                    f"{self._markdown_table_cell(asset.title)} | {asset.asset_type} | {asset.format} | "
                    f"{asset.status} | {self._markdown_table_cell(asset.source_url or '-')} | "
                    f"{asset.output_path or '-'} | "
                    f"{self._markdown_table_cell(asset.error or '-')} |"
                )
            if article_package.notes:
                lines.extend(["", "#### 备注", ""])
                lines.extend(self._markdown_bullets(article_package.notes))
            lines.append("")

        return "\n".join(lines) + "\n"

    def _build_final_articles_index(
        self,
        run_date: str,
        final_articles: List[FinalArticle],
        final_article_paths: List[Path],
    ) -> str:
        article_paths_by_name = {
            article.full_name: article_path
            for article, article_path in zip(final_articles, final_article_paths)
        }
        lines = [
            "# GitHubRadarAgent 公众号终稿索引",
            "",
            "## 运行信息",
            f"- 日期：{run_date}",
            f"- 终稿数量：{len(final_articles)}",
            "",
            "## 终稿列表",
            "",
            "| 项目 | 标题 | 分数 | 是否通过 | 质量分 | 质量可发布 | 已润色 | 发布就绪 | 发布清理模式 | 自然度 | 模板风险 | 修改模式 | 本地终稿 | 参考链接 |",
            "| --- | --- | ---: | --- | ---: | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]

        for article in final_articles:
            article_path = article_paths_by_name.get(article.full_name)
            project = f"[{article.full_name}]({article.html_url})" if article.html_url else article.full_name
            publish_links = article.publish_polish_report.kept_links if article.publish_polish_report else []
            source_links = self._markdown_table_cell("; ".join((publish_links or article.source_links)[:4]) or "-")
            local_path = str(article_path) if article_path is not None else "-"
            report = article.humanization_report
            ai_smell_score = f"{report.ai_smell_score:.2f}" if report else "-"
            template_risk = f"{report.template_risk:.2f}" if report else "-"
            quality_score = (
                f"{article.article_quality_report.total_score:.2f}"
                if article.article_quality_report
                else f"{article.quality_score:.2f}"
                if article.quality_score
                else "-"
            )
            quality_ready = (
                article.article_quality_report.publish_ready
                if article.article_quality_report
                else article.quality_publish_ready
            )
            lines.append(
                "| "
                f"{project} | {self._markdown_table_cell(article.title)} | "
                f"{article.review.total_score:.2f} | {'是' if article.review.pass_review else '否'} | "
                f"{quality_score} | {'是' if quality_ready else '否'} | "
                f"{'是' if article.humanized else '否'} | "
                f"{'是' if article.publish_ready else '否'} | {article.publish_polish_mode or '-'} | "
                f"{ai_smell_score} | {template_risk} | "
                f"{article.revision_mode} | {local_path} | {source_links} |"
            )

        lines.append("")
        return "\n".join(lines)

    def _release_bullets(self, releases: List[dict]) -> list[str]:
        if not releases:
            return ["- 暂无 release 信息"]

        lines: list[str] = []
        for release in releases:
            title = release.get("name") or release.get("tag_name") or "Untitled release"
            published_at = release.get("published_at") or "-"
            html_url = release.get("html_url") or "-"
            body = release.get("body") or ""
            line = f"- {title} ({published_at}) - {html_url}"
            if body:
                line = f"{line}\n  {body[:240]}"
            lines.append(line)
        return lines

    def _issue_bullets(self, issues: List[dict]) -> list[str]:
        if not issues:
            return ["- 暂无 open issue 样本"]

        return [
            "- "
            f"{issue.get('title') or 'Untitled issue'} "
            f"({issue.get('created_at') or '-'}, comments={issue.get('comments') or 0}) - "
            f"{issue.get('html_url') or '-'}"
            for issue in issues
        ]

    def _author_profile_bullets(self, author: Any) -> list[str]:
        if not author:
            return ["- 暂无作者/组织资料"]
        def value_of(name: str) -> Any:
            return author.get(name) if isinstance(author, dict) else getattr(author, name, None)
        fields = [
            ("GitHub", value_of("html_url")),
            ("Login", value_of("login")),
            ("Type", value_of("type")),
            ("Name", value_of("name")),
            ("Bio", value_of("bio")),
            ("Company", value_of("company")),
            ("Blog", value_of("blog")),
            ("Location", value_of("location")),
            ("Twitter", value_of("twitter_username")),
            ("Public Repos", value_of("public_repos")),
            ("Followers", value_of("followers")),
            ("Created At", value_of("created_at")),
        ]
        return [f"- {label}: {value}" for label, value in fields if value not in (None, "")]

    def _project_links_bullets(self, links: Any) -> list[str]:
        if not links:
            return ["- 暂无项目链接资料"]
        def value_of(name: str) -> Any:
            return links.get(name) if isinstance(links, dict) else getattr(links, name, None)
        lines: list[str] = []
        homepage = value_of("homepage")
        if homepage:
            lines.append(f"- Homepage: {homepage}")
        for label, attr in [
            ("Documentation", "documentation"),
            ("Demo", "demo"),
            ("Examples", "examples"),
            ("Website", "website"),
            ("Images", "images"),
            ("Videos", "videos"),
            ("Badges", "badges"),
        ]:
            values = value_of(attr)
            for value in list(values or [])[:10]:
                lines.append(f"- {label}: {value}")
        return lines or ["- 暂无项目链接资料"]

    def _markdown_bullets(self, values: List[str]) -> list[str]:
        if not values:
            return ["- -"]
        return [f"- {value}" for value in values]

    def _title_candidate_bullets(self, values: List[dict]) -> list[str]:
        if not values:
            return ["- -"]

        lines: list[str] = []
        for candidate in values:
            if hasattr(candidate, "title"):
                title = candidate.title
                style = candidate.style
                reason = candidate.reason
                risk = candidate.risk
            else:
                title = candidate.get("title") or "-"
                style = candidate.get("style") or "-"
                reason = candidate.get("reason") or "-"
                risk = candidate.get("risk")
            suffix = f"；风险：{risk}" if risk else ""
            lines.append(f"- {title}（{style}；理由：{reason}{suffix}）")
        return lines

    def _fact_card_bullets(self, values: list[Any]) -> list[str]:
        if not values:
            return ["- -"]

        lines: list[str] = []
        for index, fact in enumerate(values[:14], start=1):
            category = getattr(fact, "category", None) or fact.get("category", "-")
            claim = getattr(fact, "claim", None) or fact.get("claim", "-")
            confidence = getattr(fact, "confidence", None) or fact.get("confidence", "-")
            publishable = getattr(fact, "publishable", None)
            if publishable is None and isinstance(fact, dict):
                publishable = fact.get("publishable")
            publishable_text = "可发布" if publishable else "仅核验"
            lines.append(f"- [{index}] {category} / {confidence} / {publishable_text}：{claim}")
        if len(values) > 14:
            lines.append(f"- 另有 {len(values) - 14} 条事实卡见 JSON 快照。")
        return lines

    def _feature_advantage_bullets(self, values: Any) -> list[str]:
        if not values:
            return ["- -"]
        lines: list[str] = []
        for item in list(values)[:8]:
            feature = self._object_field(item, "feature", "-")
            advantage = self._object_field(item, "advantage", "-")
            reader_interest = self._object_field(item, "reader_interest", "-")
            evidence = self._object_field(item, "evidence", "-")
            emphasis = self._object_field(item, "emphasis", "-")
            lines.append(
                f"- {feature} -> {advantage} -> {reader_interest}（强调级别：{emphasis}；依据：{evidence}）"
            )
        return lines

    def _object_field(self, value: Any, name: str, default: Any = None) -> Any:
        if value is None:
            return default
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    def _dedupe_markdown_items(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _markdown_table_cell(self, value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _model_dump(
        self,
        model: Union[
            RepoCandidate,
            RepoScore,
            RepoResearchNote,
            TopicAngle,
            ArticleDraft,
            ArticleReview,
            CustomArticleDirection,
            StyleReferenceProfile,
            FinalArticle,
            HumanizationReport,
            OriginalityReport,
            PublishPolishReport,
            VisualAsset,
            ArticlePackage,
        ],
    ) -> dict:
        if model is None:
            return {}
        if isinstance(model, dict):
            return model
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()

    def _content_plan_payload(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "full_name": plan.get("full_name"),
            "project_kind": plan.get("project_kind"),
            "tool_use_cases": plan.get("tool_use_cases", []),
            "author_profile": self._model_dump(plan["author_profile"]) if plan.get("author_profile") is not None else None,
            "project_links": self._model_dump(plan["project_links"]) if plan.get("project_links") is not None else None,
            "facts": [self._model_dump(fact) for fact in plan.get("facts", [])],
            "insight": self._model_dump(plan["insight"]) if plan.get("insight") is not None else None,
            "brief": self._model_dump(plan["brief"]) if plan.get("brief") is not None else None,
            "appeal": self._model_dump(plan["appeal"]) if plan.get("appeal") is not None else None,
            "impact": self._model_dump(plan["impact"]) if plan.get("impact") is not None else None,
            "wechat_pattern": self._model_dump(plan["wechat_pattern"]) if plan.get("wechat_pattern") is not None else None,
            "direction_text": plan.get("direction_text", ""),
            "custom_direction": self._model_dump(plan["custom_direction"]) if plan.get("custom_direction") is not None else None,
            "parsed_direction": self._model_dump(plan["parsed_direction"]) if plan.get("parsed_direction") is not None else None,
            "direction_used_in_writing": bool(plan.get("direction_used_in_writing", False)),
            "style_reference_profile": self._model_dump(plan["style_reference_profile"]) if plan.get("style_reference_profile") is not None else None,
            "reference_source_names": plan.get("reference_source_names", []),
            "reference_text_count": int(plan.get("reference_text_count") or 0),
            "style_reference_used_in_writing": bool(plan.get("style_reference_used_in_writing", False)),
            "style_reference_rules": plan.get("style_reference_rules", {}),
            "planning_mode": plan.get("planning_mode", "fallback"),
            "warnings": plan.get("warnings", []),
        }

    def _parse_repo_candidate(self, payload: dict) -> RepoCandidate:
        if hasattr(RepoCandidate, "model_validate"):
            return RepoCandidate.model_validate(payload)
        return RepoCandidate.parse_obj(payload)

    def _parse_repo_score(self, payload: dict) -> RepoScore:
        if hasattr(RepoScore, "model_validate"):
            return RepoScore.model_validate(payload)
        return RepoScore.parse_obj(payload)

    def _candidate_from_score_item(self, payload: dict) -> RepoCandidate:
        full_name = payload.get("full_name") or ""
        owner, _, name = full_name.partition("/")
        return RepoCandidate(
            full_name=full_name,
            owner=owner,
            name=name,
            html_url=payload.get("html_url") or f"https://github.com/{full_name}",
            url=payload.get("html_url") or f"https://github.com/{full_name}",
            discovery_reason=payload.get("discovery_reason"),
        )

    def _parse_repo_research_note(self, payload: dict) -> RepoResearchNote:
        if hasattr(RepoResearchNote, "model_validate"):
            return RepoResearchNote.model_validate(payload)
        return RepoResearchNote.parse_obj(payload)

    def _parse_topic_angle(self, payload: dict) -> TopicAngle:
        if hasattr(TopicAngle, "model_validate"):
            return TopicAngle.model_validate(payload)
        return TopicAngle.parse_obj(payload)

    def _parse_article_draft(self, payload: dict) -> ArticleDraft:
        if hasattr(ArticleDraft, "model_validate"):
            return ArticleDraft.model_validate(payload)
        return ArticleDraft.parse_obj(payload)

    def _parse_final_article(self, payload: dict) -> FinalArticle:
        if hasattr(FinalArticle, "model_validate"):
            return FinalArticle.model_validate(payload)
        return FinalArticle.parse_obj(payload)

    def _filter_by_selected_names(self, items: list[T], selected_repo_full_names: list[str] | None) -> list[T]:
        if not selected_repo_full_names:
            return items
        selected_order = {full_name: index for index, full_name in enumerate(selected_repo_full_names)}
        filtered = [
            item
            for item in items
            if str(getattr(item, "full_name", "") or getattr(item, "repo_full_name", "")) in selected_order
        ]
        return sorted(
            filtered,
            key=lambda item: selected_order[
                str(getattr(item, "full_name", "") or getattr(item, "repo_full_name", ""))
            ],
        )

    def _filter_dicts_by_selected_names(
        self,
        items: list[dict[str, Any]],
        selected_repo_full_names: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not selected_repo_full_names:
            return items
        selected_order = {full_name: index for index, full_name in enumerate(selected_repo_full_names)}
        filtered = [
            item
            for item in items
            if str(item.get("full_name") or item.get("repo_full_name") or "") in selected_order
        ]
        return sorted(
            filtered,
            key=lambda item: selected_order[str(item.get("full_name") or item.get("repo_full_name") or "")],
        )

    def _load_content_plans(self, content_plan_snapshot_path: Path) -> list[dict[str, Any]]:
        if not content_plan_snapshot_path.exists():
            return []
        try:
            content_plan_payload = json.loads(content_plan_snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Content plan snapshot is invalid: {content_plan_snapshot_path} ({exc})")
            return []
        plan_items = content_plan_payload.get("plans", [])
        if not isinstance(plan_items, list):
            return []
        return [item for item in plan_items if isinstance(item, dict)]
