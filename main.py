from __future__ import annotations

import argparse
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.news_collector import NewsCollectorService
from src.news_detail_service import NewsDetailService
from src.news_article_planner import NewsArticlePlannerService
from src.news_digest_polisher import NewsDigestPolisherService
from src.news_digest_quality import NewsDigestQualityEvaluator
from src.news_digest_writer import NewsDigestWriterService
from src.news_event_builder import NewsEventBuilderService
from src.news_scorer import NewsScoringService
from src.news_selection_service import NewsSelectionService
from src.models import RepoCandidate
from src.orchestrator import DailyOrchestrator


try:
    import typer
except ImportError:  # pragma: no cover - local bootstrap fallback
    typer = None


try:
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover - rich is optional at runtime
    Console = None
    Table = None


def _print_candidates(candidates: list[RepoCandidate]) -> None:
    if not candidates:
        print("No candidates discovered.")
        return

    if Console is not None and Table is not None:
        table = Table(title="GitHub Repository Candidates")
        table.add_column("Repository", style="cyan", no_wrap=True)
        table.add_column("Stars", justify="right")
        table.add_column("Language")
        table.add_column("URL")
        table.add_column("Description")

        for candidate in candidates:
            description = (candidate.description or "").replace("\n", " ").strip()
            if len(description) > 100:
                description = f"{description[:100]}..."
            table.add_row(
                candidate.full_name,
                str(candidate.stars),
                candidate.language or "-",
                candidate.html_url,
                description,
            )

        Console().print(table)
        return

    print("GitHub Repository Candidates")
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


def _run_daily_command(
    limit_per_keyword: int = 5,
    score_top: int = 30,
    research_top: int = 3,
    article_top: int = 3,
    review_threshold: float = 80,
    cooldown_days: int = 30,
    ignore_history: bool = False,
    allow_recent_fallback: bool = False,
):
    return DailyOrchestrator().run_daily(
        limit_per_keyword=limit_per_keyword,
        score_top=score_top,
        research_top=research_top,
        article_top=article_top,
        review_threshold=review_threshold,
        cooldown_days=cooldown_days,
        ignore_history=ignore_history,
        allow_recent_fallback=allow_recent_fallback,
    )


def _run_collect_news_command(
    hours: int = 24,
    limit: int = 100,
    include_fulltext: bool = False,
    sources: list[str] | None = None,
    keywords: list[str] | None = None,
    translate: bool = True,
    translate_limit: int = 50,
):
    result = NewsCollectorService().collect(
        hours=hours,
        limit=limit,
        sources=sources,
        keywords=keywords,
        include_fulltext=include_fulltext,
        translate=translate,
        translate_limit=translate_limit,
    )
    translation_counts = {}
    for item in result.items:
        status = item.translation_status or "skipped"
        translation_counts[status] = translation_counts.get(status, 0) + 1
    print(f"Collected {result.total_count} news items ({result.fresh_count} within {result.window_hours}h).")
    print(
        "Translations: "
        f"translated={translation_counts.get('translated', 0)}, "
        f"skipped={translation_counts.get('skipped', 0)}, "
        f"failed={translation_counts.get('failed', 0)}, "
        f"source_is_chinese={translation_counts.get('source_is_chinese', 0)}"
    )
    print("JSON: workspace/news/news_latest.json")
    print("Snapshot: workspace/snapshots/news_latest.json")
    print(f"Report: outputs/{datetime.now().date().isoformat()}/news_collection_report.md")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
    return result


def _run_fetch_news_detail_command(news_id: str, refresh: bool = False):
    service = NewsDetailService()
    detail = service.get_detail(news_id=news_id, refresh=refresh)
    cache_path = service.cache_path_for(news_id)
    print(f"News detail: {detail.news_id}")
    print(f"Title: {detail.title_zh or detail.title}")
    print(f"content_availability: {detail.content_availability}")
    print(f"extraction_status: {detail.extraction_status}")
    print(f"word_count: {detail.word_count}")
    if detail.extraction_error:
        print(f"extraction_error: {detail.extraction_error}")
    print(f"Cache: {cache_path.as_posix()}")
    return detail


def _run_select_news_command(news_ids: list[str], primary_news_id: str | None = None, direction: str | None = None):
    service = NewsSelectionService()
    context = service.build_selection(
        news_ids=news_ids,
        primary_news_id=primary_news_id,
        direction_text=direction,
    )
    context = service.save_selection(context)
    print(f"Saved news selection: {context.selection_id}")
    print(f"Primary news: {context.primary_news_id}")
    print(f"Items: {len(context.items)}")
    print(f"JSON: workspace/news/selections/{context.selection_id}.json")
    print("Latest: workspace/news/selections/latest_selection.json")
    if context.warnings:
        print("Warnings:")
        for warning in context.warnings[:10]:
            print(f"- {warning}")
    return context


def _run_plan_news_article_command(selection_id: str | None = None, latest: bool = True):
    service = NewsArticlePlannerService()
    if selection_id and not latest:
        plan = service.plan_by_selection_id(selection_id)
    elif selection_id:
        plan = service.plan_by_selection_id(selection_id)
    else:
        plan = service.plan_latest()
    generated_date = plan.generated_at[:10] if plan.generated_at else datetime.now().date().isoformat()
    print(f"Generated news article plan: {plan.plan_id}")
    print(f"Selection: {plan.selection_id}")
    print(f"Primary news: {plan.primary_news_id}")
    print(f"Generation mode: {plan.generation_mode}")
    print("JSON: workspace/news/news_article_plan_latest.json")
    print(f"Plan JSON: workspace/news/plans/{plan.plan_id}.json")
    print("Snapshot: workspace/snapshots/news_article_plan_latest.json")
    print(f"Markdown: outputs/{generated_date}/news_article_plan.md")
    if plan.recommended_title:
        print(f"Recommended title: {plan.recommended_title}")
    if plan.warnings:
        print("Warnings:")
        for warning in plan.warnings[:10]:
            print(f"- {warning}")
    return plan


def _run_score_news_command(top: int = 20, min_score: float = 60.0):
    result = NewsScoringService().score_latest(top=top, min_score=min_score)
    print(f"Scored {result.total_count} news items. Recommended {result.recommended_count}.")
    print("Top 5 recommended:")
    for index, score in enumerate([item for item in result.scores if item.recommended][:5], start=1):
        title = score.title_zh or score.title
        print(f"{index}. [{score.total_score:.1f}] {score.recommended_section} | {title}")
        print(f"   {score.url}")
    print("JSON: workspace/news/news_scores_latest.json")
    print("Snapshot: workspace/snapshots/news_scores_latest.json")
    print(f"Report: outputs/{datetime.now().date().isoformat()}/news_scores_report.md")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
    return result


def _run_build_news_events_command(top: int = 20, min_score: float = 60.0, similarity_threshold: float = 0.55):
    result = NewsEventBuilderService().build_latest(
        top=top,
        min_score=min_score,
        similarity_threshold=similarity_threshold,
    )
    print(f"Built {result.event_count} news events from {result.total_news_count} news items.")
    print(f"Recommended events: {result.recommended_event_count}.")
    print("Top 5 events:")
    for index, event in enumerate([item for item in result.events if item.recommended_section != "暂不推荐"][:5], start=1):
        title = event.event_title_zh or event.event_title
        print(f"{index}. [{event.total_score:.1f}] {event.recommended_section} | sources={event.source_count} | {title}")
        print(f"   {event.primary_url}")
    print("JSON: workspace/news/news_events_latest.json")
    print("Snapshot: workspace/snapshots/news_events_latest.json")
    print(f"Report: outputs/{datetime.now().date().isoformat()}/news_events_report.md")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
    return result


def _run_write_news_digest_command(top: int = 12, date: str | None = None):
    result = NewsDigestWriterService().write_latest(top=top, date=date)
    print(f"Wrote AI news digest with {result.event_count} events.")
    print(f"Generation mode: {result.generation_mode}")
    print("JSON: workspace/news/news_digest_latest.json")
    print("Snapshot: workspace/snapshots/news_digest_latest.json")
    print(f"Markdown: outputs/{result.date}/ai_news_digest.md")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
    return result


def _model_copy(model, update: dict):
    if hasattr(model, "model_copy"):
        return model.model_copy(update=update)
    return model.copy(update=update)


def _run_review_news_digest_command(threshold: float = 80.0, polish: bool = True):
    evaluator = NewsDigestQualityEvaluator()
    polisher = NewsDigestPolisherService()
    article = evaluator.load_latest_digest()
    events_result = evaluator.load_latest_events()
    report = evaluator.evaluate(article, events_result, threshold=threshold)

    if polish:
        article = polisher.polish_article(article, report)
        if article.polished:
            report = evaluator.evaluate(article, events_result, threshold=threshold)
            article = _model_copy(
                article,
                {
                    "quality_report": report,
                    "quality_score": report.total_score,
                    "publish_ready": report.publish_ready,
                },
            )
    else:
        article = polisher.attach_quality(article, report)

    article = polisher.generate_package(article, report)
    polisher.save_article(article)
    evaluator.save_report(article, report)

    print(f"Reviewed AI news digest. Score: {report.total_score:.1f}. Publish ready: {'yes' if report.publish_ready else 'no'}.")
    print(f"Polished: {'yes' if article.polished else 'no'}")
    print("JSON: workspace/news/news_digest_review_latest.json")
    print("Snapshot: workspace/snapshots/news_digest_review_latest.json")
    print(f"Review Markdown: outputs/{article.date}/ai_news_digest_review.md")
    print(f"Digest Markdown: outputs/{article.date}/ai_news_digest.md")
    print(f"Package: {article.package_path or f'outputs/{article.date}/news_digest_package/packaged_ai_news_digest.md'}")
    if report.issues:
        print("Top issues:")
        for issue in report.issues[:5]:
            print(f"- [{issue.severity}] {issue.issue_type}: {issue.description}")
    return {"article": article, "quality_report": report}


def _load_custom_direction(direction: str | None = None, direction_file: str | None = None) -> str | None:
    parts: list[str] = []
    if direction:
        parts.append(direction.strip())
    if direction_file:
        path = Path(direction_file)
        if not path.exists():
            raise FileNotFoundError(f"Direction file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Direction file is not a file: {path}")
        parts.append(path.read_text(encoding="utf-8").strip())
    merged = "\n\n".join(part for part in parts if part)
    return merged or None


def _load_style_references(
    reference_files: list[str] | None = None,
    reference_texts: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    source_names: list[str] = []
    for file_name in reference_files or []:
        path = Path(file_name)
        if not path.exists():
            raise FileNotFoundError(f"Reference file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Reference file is not a file: {path}")
        if path.suffix.lower() not in {".txt", ".md"}:
            raise ValueError(f"Reference file extension is not supported: {path}. Only .txt and .md are supported.")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Reference file is empty: {path}")
        texts.append(content)
        source_names.append(str(path))

    for index, reference_text in enumerate(reference_texts or [], start=1):
        content = (reference_text or "").strip()
        if not content:
            raise ValueError(f"Reference text #{index} is empty.")
        texts.append(content)
        source_names.append(f"reference_text_{index}")
    return texts, source_names


def _print_custom_article_result(result: dict) -> None:
    print("Custom article generated.")
    print(f"Project: {result.get('full_name') or '-'}")
    print(f"Title: {result.get('title') or '-'}")
    print(f"Generation mode: {result.get('generation_mode') or '-'}")
    print(f"Style reference used: {'yes' if result.get('style_reference_used') else 'no'}")
    print(f"Markdown: {result.get('markdown_path') or '-'}")
    print(f"Report: {result.get('report_path') or '-'}")


def _schedule_daily(
    run_time: str = "09:00",
    limit_per_keyword: int = 5,
    score_top: int = 30,
    research_top: int = 3,
    article_top: int = 3,
    review_threshold: float = 80,
    cooldown_days: int = 30,
    ignore_history: bool = False,
    allow_recent_fallback: bool = False,
    run_once_first: bool = False,
) -> None:
    try:
        import schedule
    except ImportError as exc:  # pragma: no cover - dependency bootstrap fallback
        raise RuntimeError("Missing dependency: schedule. Please run: pip install -r requirements.txt") from exc

    def job() -> None:
        print(f"[schedule] Triggered run-daily at {datetime.now().isoformat(timespec='seconds')}")
        try:
            _run_daily_command(
                limit_per_keyword=limit_per_keyword,
                score_top=score_top,
                research_top=research_top,
                article_top=article_top,
                review_threshold=review_threshold,
                cooldown_days=cooldown_days,
                ignore_history=ignore_history,
                allow_recent_fallback=allow_recent_fallback,
            )
        except Exception as exc:
            print(f"[schedule] run-daily failed: {type(exc).__name__}: {exc}")

    schedule.clear("daily-run")
    schedule.every().day.at(run_time).do(job).tag("daily-run")
    next_run = schedule.next_run()
    print(f"[schedule] Daily run scheduled at {run_time}.")
    print(f"[schedule] Next run: {next_run.isoformat(timespec='seconds') if next_run else '-'}")
    print("[schedule] Keep this terminal running. Press Ctrl+C to stop.")

    if run_once_first:
        print("[schedule] --run-once-first enabled; running once now.")
        job()
        next_run = schedule.next_run()
        print(f"[schedule] Next run: {next_run.isoformat(timespec='seconds') if next_run else '-'}")

    try:
        while True:
            schedule.run_pending()
            time_module.sleep(30)
    except KeyboardInterrupt:
        print("\n[schedule] Stopped by user.")


if typer is not None:
    app = typer.Typer(help="GitHubRadarAgent CLI")


    @app.command("run-daily")
    def run_daily(
        limit_per_keyword: int = typer.Option(
            5,
            "--limit-per-keyword",
            help="Maximum repositories to fetch for each discovery keyword.",
        ),
        score_top: int = typer.Option(
            30,
            "--score-top",
            help="Number of scored repositories to keep visible for downstream selection.",
        ),
        research_top: int = typer.Option(
            3,
            "--research-top",
            help="Number of top scored repositories to research.",
        ),
        article_top: int = typer.Option(
            3,
            "--article-top",
            help="Number of top repositories to write and review.",
        ),
        review_threshold: float = typer.Option(
            80,
            "--review-threshold",
            help="Minimum total score required to pass review.",
        ),
        cooldown_days: int = typer.Option(
            30,
            "--cooldown-days",
            help="Days to avoid repeating daily article projects from history.",
        ),
        ignore_history: bool = typer.Option(
            False,
            "--ignore-history",
            help="Ignore article history and use the old score-first selection behavior.",
        ),
        allow_recent_fallback: bool = typer.Option(
            False,
            "--allow-recent-fallback",
            help="Allow recently written projects to fill article slots when fresh candidates are insufficient.",
        ),
    ) -> None:
        """Run the full daily workflow."""
        _run_daily_command(
            limit_per_keyword=limit_per_keyword,
            score_top=score_top,
            research_top=research_top,
            article_top=article_top,
            review_threshold=review_threshold,
            cooldown_days=cooldown_days,
            ignore_history=ignore_history,
            allow_recent_fallback=allow_recent_fallback,
        )


    @app.command("schedule")
    def schedule_command(
        run_time: str = typer.Option(
            "09:00",
            "--time",
            help="Local time for the daily run in HH:MM format.",
        ),
        limit_per_keyword: int = typer.Option(
            5,
            "--limit-per-keyword",
            help="Maximum repositories to fetch for each discovery keyword.",
        ),
        score_top: int = typer.Option(
            30,
            "--score-top",
            help="Number of scored repositories to keep visible for downstream selection.",
        ),
        research_top: int = typer.Option(
            3,
            "--research-top",
            help="Number of top scored repositories to research.",
        ),
        article_top: int = typer.Option(
            3,
            "--article-top",
            help="Number of top repositories to write and review.",
        ),
        review_threshold: float = typer.Option(
            80,
            "--review-threshold",
            help="Minimum total score required to pass review.",
        ),
        cooldown_days: int = typer.Option(
            30,
            "--cooldown-days",
            help="Days to avoid repeating daily article projects from history.",
        ),
        ignore_history: bool = typer.Option(
            False,
            "--ignore-history",
            help="Ignore article history and use the old score-first selection behavior.",
        ),
        allow_recent_fallback: bool = typer.Option(
            False,
            "--allow-recent-fallback",
            help="Allow recently written projects to fill article slots when fresh candidates are insufficient.",
        ),
        run_once_first: bool = typer.Option(
            False,
            "--run-once-first",
            help="Run immediately once before waiting for the scheduled time.",
        ),
    ) -> None:
        """Run the daily workflow in a local long-running scheduler process."""
        _schedule_daily(
            run_time=run_time,
            limit_per_keyword=limit_per_keyword,
            score_top=score_top,
            research_top=research_top,
            article_top=article_top,
            review_threshold=review_threshold,
            cooldown_days=cooldown_days,
            ignore_history=ignore_history,
            allow_recent_fallback=allow_recent_fallback,
            run_once_first=run_once_first,
        )


    @app.command("discover")
    def discover(
        limit_per_keyword: int = typer.Option(
            10,
            "--limit-per-keyword",
            help="Maximum repositories to fetch for each discovery keyword.",
        ),
    ) -> None:
        """Discover repository candidates from GitHub."""
        candidates = DailyOrchestrator().discover(limit_per_keyword=limit_per_keyword)
        _print_candidates(candidates)


    @app.command("write")
    def write(repo: str = typer.Option(..., "--repo", help="Repository in owner/name format.")) -> None:
        """Run placeholder article writing for one repository."""
        DailyOrchestrator().write(repo)


    @app.command("score")
    def score(
        top: int = typer.Option(
            10,
            "--top",
            help="Number of top scored repositories to print.",
        ),
    ) -> None:
        """Score discovered repository candidates."""
        DailyOrchestrator().score(top=top)


    @app.command("research")
    def research(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of top scored repositories to research.",
        ),
    ) -> None:
        """Research top scored repositories and write notes."""
        DailyOrchestrator().research(top=top)


    @app.command("angles")
    def angles(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of researched repositories to plan topic angles for.",
        ),
    ) -> None:
        """Generate WeChat topic angles, hooks, outlines, and title candidates."""
        DailyOrchestrator().plan_angles(top=top)


    @app.command("articles")
    def articles(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of top repositories to write article drafts for.",
        ),
    ) -> None:
        """Generate WeChat recommendation article drafts from topic angles."""
        DailyOrchestrator().write_articles(top=top)


    @app.command("plan-content")
    def plan_content(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of researched repositories to build content planning artifacts for.",
        ),
    ) -> None:
        """Build FactCard, ProjectInsight, and EditorialBrief intermediates."""
        DailyOrchestrator().plan_content(top=top)


    @app.command("write-articles")
    def write_articles(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of top repositories to write article drafts for.",
        ),
    ) -> None:
        """Generate WeChat recommendation article drafts from topic angles."""
        DailyOrchestrator().write_articles(top=top)


    @app.command("review-articles")
    def review_articles(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of article drafts to review and revise.",
        ),
        threshold: float = typer.Option(
            80,
            "--threshold",
            help="Minimum total score required to pass review.",
        ),
    ) -> None:
        """Review article drafts and generate final revised articles."""
        DailyOrchestrator().review_articles(top=top, threshold=threshold)


    @app.command("humanize-articles")
    def humanize_articles(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of final articles to inspect and humanize.",
        ),
    ) -> None:
        """Run the humanization editor on existing final articles."""
        DailyOrchestrator().humanize_articles(top=top)


    @app.command("polish-for-publish")
    def polish_for_publish(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of final articles to clean for publication.",
        ),
    ) -> None:
        """Clean final articles into publication-ready drafts."""
        DailyOrchestrator().polish_for_publish(top=top)


    @app.command("write-custom")
    def write_custom(
        repo_url: str = typer.Option(
            ...,
            "--repo-url",
            help="GitHub repository URL or owner/repo.",
        ),
        direction: Optional[str] = typer.Option(
            None,
            "--direction",
            help="Optional writing direction text.",
        ),
        direction_file: Optional[str] = typer.Option(
            None,
            "--direction-file",
            help="Optional Markdown/text file with writing direction.",
        ),
        reference_file: Optional[list[str]] = typer.Option(
            None,
            "--reference-file",
            help="Optional local .md/.txt reference article file for style-only analysis. Repeatable.",
        ),
        reference_text: Optional[list[str]] = typer.Option(
            None,
            "--reference-text",
            help="Optional reference article text for style-only analysis. Repeatable.",
        ),
    ) -> None:
        """Write one WeChat article for a specified GitHub repository."""
        direction_text = _load_custom_direction(direction=direction, direction_file=direction_file)
        reference_texts, reference_source_names = _load_style_references(reference_file, reference_text)
        result = DailyOrchestrator().write_custom_article(
            repo_url=repo_url,
            direction_text=direction_text,
            reference_texts=reference_texts,
            reference_source_names=reference_source_names,
        )
        _print_custom_article_result(result)


    @app.command("collect-news")
    def collect_news(
        hours: int = typer.Option(
            24,
            "--hours",
            help="News freshness window in hours.",
        ),
        limit: int = typer.Option(
            100,
            "--limit",
            help="Maximum standardized news items to keep.",
        ),
        include_fulltext: bool = typer.Option(
            False,
            "--include-fulltext/--no-fulltext",
            help="Try extracting article body text with trafilatura.",
        ),
        source: Optional[list[str]] = typer.Option(
            None,
            "--source",
            help="Source group to collect. Repeatable: official, hn, arxiv, gdelt, rsshub.",
        ),
        keyword: Optional[list[str]] = typer.Option(
            None,
            "--keyword",
            help="Keyword to query and tag. Repeatable.",
        ),
        translate: bool = typer.Option(
            True,
            "--translate/--no-translate",
            help="Translate news titles and summaries to Chinese with the configured OpenAI-compatible LLM.",
        ),
        translate_limit: int = typer.Option(
            50,
            "--translate-limit",
            help="Maximum number of ranked news items to translate.",
        ),
    ) -> None:
        """Collect and standardize AI news with optional Chinese title/summary translation."""
        _run_collect_news_command(
            hours=hours,
            limit=limit,
            include_fulltext=include_fulltext,
            sources=source,
            keywords=keyword,
            translate=translate,
            translate_limit=translate_limit,
        )


    @app.command("score-news")
    def score_news(
        top: int = typer.Option(
            20,
            "--top",
            help="Maximum recommended news items to keep.",
        ),
        min_score: float = typer.Option(
            60,
            "--min-score",
            help="Minimum score for recommended news.",
        ),
    ) -> None:
        """Score and classify latest collected AI news for editorial selection."""
        _run_score_news_command(top=top, min_score=min_score)


    @app.command("fetch-news-detail")
    def fetch_news_detail(
        news_id: str = typer.Option(
            ...,
            "--news-id",
            help="News item id from workspace/news/news_latest.json.",
        ),
        refresh: bool = typer.Option(
            False,
            "--refresh/--no-refresh",
            help="Force a trafilatura refresh even when cached detail exists.",
        ),
    ) -> None:
        """Fetch and cache one news article detail."""
        _run_fetch_news_detail_command(news_id=news_id, refresh=refresh)


    @app.command("select-news")
    def select_news(
        news_id: list[str] = typer.Option(
            ...,
            "--news-id",
            help="News item id from workspace/news/news_latest.json. Repeatable, max 5.",
        ),
        primary_news_id: Optional[str] = typer.Option(
            None,
            "--primary-news-id",
            help="Primary news id. Defaults to the first --news-id.",
        ),
        direction: Optional[str] = typer.Option(
            None,
            "--direction",
            help="Optional article writing direction for the next planning step.",
        ),
    ) -> None:
        """Save selected AI news context for the next article planning step."""
        _run_select_news_command(news_ids=news_id, primary_news_id=primary_news_id, direction=direction)


    @app.command("plan-news-article")
    def plan_news_article(
        selection_id: Optional[str] = typer.Option(
            None,
            "--selection-id",
            help="Selection id from workspace/news/selections. Defaults to latest selection.",
        ),
        latest: bool = typer.Option(
            True,
            "--latest/--no-latest",
            help="Use workspace/news/selections/latest_selection.json when --selection-id is not provided.",
        ),
    ) -> None:
        """Generate a planning brief for one AI news article without writing the final article."""
        _run_plan_news_article_command(selection_id=selection_id, latest=latest)


    @app.command("build-news-events")
    def build_news_events(
        top: int = typer.Option(
            20,
            "--top",
            help="Maximum recommended event cards to keep.",
        ),
        min_score: float = typer.Option(
            60,
            "--min-score",
            help="Minimum event score for recommendation.",
        ),
        similarity_threshold: float = typer.Option(
            0.55,
            "--similarity-threshold",
            help="Conservative keyword similarity threshold for event merging.",
        ),
    ) -> None:
        """Merge latest scored AI news into event cards."""
        _run_build_news_events_command(top=top, min_score=min_score, similarity_threshold=similarity_threshold)


    @app.command("write-news-digest")
    def write_news_digest(
        top: int = typer.Option(
            12,
            "--top",
            help="Maximum event cards to use in the AI news digest.",
        ),
        date: Optional[str] = typer.Option(
            None,
            "--date",
            help="Digest date in YYYY-MM-DD format. Defaults to today.",
        ),
    ) -> None:
        """Write a Chinese AI news digest from latest event cards."""
        _run_write_news_digest_command(top=top, date=date)


    @app.command("review-news-digest")
    def review_news_digest(
        threshold: float = typer.Option(
            80,
            "--threshold",
            help="Minimum total quality score required for publish_ready.",
        ),
        polish: bool = typer.Option(
            True,
            "--polish/--no-polish",
            help="Lightly polish the digest before packaging.",
        ),
    ) -> None:
        """Review, optionally polish, and package the latest AI news digest."""
        _run_review_news_digest_command(threshold=threshold, polish=polish)


    @app.command("package-articles")
    def package_articles(
        top: int = typer.Option(
            3,
            "--top",
            help="Number of final articles to package with README images.",
        ),
    ) -> None:
        """Generate packaged Markdown for final articles using README images."""
        packages = DailyOrchestrator().package_articles(top=top)
        for article_package in packages:
            print(f"{article_package.full_name}")
            print(f"  package_dir: {article_package.package_dir}")
            print(f"  packaged_article: {article_package.packaged_article_path}")


def _run_with_argparse(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="GitHubRadarAgent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_daily_parser = subparsers.add_parser("run-daily", help="Run the full daily workflow.")
    run_daily_parser.add_argument("--limit-per-keyword", type=int, default=5)
    run_daily_parser.add_argument("--score-top", type=int, default=30)
    run_daily_parser.add_argument("--research-top", type=int, default=3)
    run_daily_parser.add_argument("--article-top", type=int, default=3)
    run_daily_parser.add_argument("--review-threshold", type=float, default=80)
    run_daily_parser.add_argument("--cooldown-days", type=int, default=30)
    run_daily_parser.add_argument("--ignore-history", action="store_true")
    run_daily_parser.add_argument("--allow-recent-fallback", action="store_true")

    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Run the daily workflow in a local long-running scheduler process.",
    )
    schedule_parser.add_argument("--time", default="09:00", help="Local time for the daily run in HH:MM format.")
    schedule_parser.add_argument("--limit-per-keyword", type=int, default=5)
    schedule_parser.add_argument("--score-top", type=int, default=30)
    schedule_parser.add_argument("--research-top", type=int, default=3)
    schedule_parser.add_argument("--article-top", type=int, default=3)
    schedule_parser.add_argument("--review-threshold", type=float, default=80)
    schedule_parser.add_argument("--cooldown-days", type=int, default=30)
    schedule_parser.add_argument("--ignore-history", action="store_true")
    schedule_parser.add_argument("--allow-recent-fallback", action="store_true")
    schedule_parser.add_argument("--run-once-first", action="store_true")

    discover_parser = subparsers.add_parser("discover", help="Discover repository candidates from GitHub.")
    discover_parser.add_argument(
        "--limit-per-keyword",
        type=int,
        default=10,
        help="Maximum repositories to fetch for each discovery keyword.",
    )

    write_parser = subparsers.add_parser("write", help="Run placeholder article writing.")
    write_parser.add_argument("--repo", required=True, help="Repository in owner/name format.")

    score_parser = subparsers.add_parser("score", help="Score discovered repository candidates.")
    score_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top scored repositories to print.",
    )

    research_parser = subparsers.add_parser("research", help="Research top scored repositories.")
    research_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of top scored repositories to research.",
    )

    angles_parser = subparsers.add_parser("angles", help="Generate WeChat topic angles.")
    angles_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of researched repositories to plan topic angles for.",
    )

    articles_parser = subparsers.add_parser(
        "articles",
        help="Generate WeChat recommendation article drafts.",
    )
    articles_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of top repositories to write article drafts for.",
    )

    write_articles_parser = subparsers.add_parser(
        "write-articles",
        help="Generate WeChat recommendation article drafts.",
    )
    write_articles_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of top repositories to write article drafts for.",
    )

    plan_content_parser = subparsers.add_parser(
        "plan-content",
        help="Build FactCard, ProjectInsight, and EditorialBrief intermediates.",
    )
    plan_content_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of researched repositories to build content planning artifacts for.",
    )

    review_articles_parser = subparsers.add_parser(
        "review-articles",
        help="Review article drafts and generate final revised articles.",
    )
    review_articles_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of article drafts to review and revise.",
    )
    review_articles_parser.add_argument(
        "--threshold",
        type=float,
        default=80,
        help="Minimum total score required to pass review.",
    )

    humanize_articles_parser = subparsers.add_parser(
        "humanize-articles",
        help="Run the humanization editor on existing final articles.",
    )
    humanize_articles_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of final articles to inspect and humanize.",
    )

    polish_for_publish_parser = subparsers.add_parser(
        "polish-for-publish",
        help="Clean final articles into publication-ready drafts.",
    )
    polish_for_publish_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of final articles to clean for publication.",
    )

    write_custom_parser = subparsers.add_parser(
        "write-custom",
        help="Write one WeChat article for a specified GitHub repository.",
    )
    write_custom_parser.add_argument(
        "--repo-url",
        required=True,
        help="GitHub repository URL or owner/repo.",
    )
    write_custom_parser.add_argument(
        "--direction",
        default=None,
        help="Optional writing direction text.",
    )
    write_custom_parser.add_argument(
        "--direction-file",
        default=None,
        help="Optional Markdown/text file with writing direction.",
    )
    write_custom_parser.add_argument(
        "--reference-file",
        action="append",
        default=[],
        help="Optional local .md/.txt reference article file for style-only analysis. Repeatable.",
    )
    write_custom_parser.add_argument(
        "--reference-text",
        action="append",
        default=[],
        help="Optional reference article text for style-only analysis. Repeatable.",
    )

    collect_news_parser = subparsers.add_parser(
        "collect-news",
        help="Collect and standardize AI news with optional Chinese title/summary translation.",
    )
    collect_news_parser.add_argument("--hours", type=int, default=24)
    collect_news_parser.add_argument("--limit", type=int, default=100)
    collect_news_parser.add_argument(
        "--include-fulltext",
        dest="include_fulltext",
        action="store_true",
        help="Try extracting article body text with trafilatura.",
    )
    collect_news_parser.add_argument(
        "--no-fulltext",
        dest="include_fulltext",
        action="store_false",
        help="Skip full-text extraction.",
    )
    collect_news_parser.set_defaults(include_fulltext=False)
    collect_news_parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source group to collect. Repeatable: official, hn, arxiv, gdelt, rsshub.",
    )
    collect_news_parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Keyword to query and tag. Repeatable.",
    )
    collect_news_parser.add_argument(
        "--translate",
        dest="translate",
        action="store_true",
        help="Translate news titles and summaries to Chinese with the configured OpenAI-compatible LLM.",
    )
    collect_news_parser.add_argument(
        "--no-translate",
        dest="translate",
        action="store_false",
        help="Skip Chinese translation.",
    )
    collect_news_parser.set_defaults(translate=True)
    collect_news_parser.add_argument(
        "--translate-limit",
        type=int,
        default=50,
        help="Maximum number of ranked news items to translate.",
    )

    score_news_parser = subparsers.add_parser(
        "score-news",
        help="Score and classify latest collected AI news for editorial selection.",
    )
    score_news_parser.add_argument("--top", type=int, default=20)
    score_news_parser.add_argument("--min-score", type=float, default=60.0)

    fetch_news_detail_parser = subparsers.add_parser(
        "fetch-news-detail",
        help="Fetch and cache one news article detail.",
    )
    fetch_news_detail_parser.add_argument("--news-id", required=True)
    fetch_news_detail_parser.add_argument(
        "--refresh",
        dest="refresh",
        action="store_true",
        help="Force a trafilatura refresh even when cached detail exists.",
    )
    fetch_news_detail_parser.add_argument(
        "--no-refresh",
        dest="refresh",
        action="store_false",
        help="Use cached detail when available.",
    )
    fetch_news_detail_parser.set_defaults(refresh=False)

    select_news_parser = subparsers.add_parser(
        "select-news",
        help="Save selected AI news context for the next article planning step.",
    )
    select_news_parser.add_argument(
        "--news-id",
        action="append",
        required=True,
        help="News item id from workspace/news/news_latest.json. Repeatable, max 5.",
    )
    select_news_parser.add_argument("--primary-news-id", default=None)
    select_news_parser.add_argument("--direction", default=None)

    plan_news_article_parser = subparsers.add_parser(
        "plan-news-article",
        help="Generate a planning brief for one selected AI news article.",
    )
    plan_news_article_parser.add_argument("--selection-id", default=None)
    plan_news_article_parser.add_argument(
        "--latest",
        dest="latest",
        action="store_true",
        help="Use workspace/news/selections/latest_selection.json.",
    )
    plan_news_article_parser.add_argument(
        "--no-latest",
        dest="latest",
        action="store_false",
        help="Require --selection-id instead of using the latest selection.",
    )
    plan_news_article_parser.set_defaults(latest=True)

    build_news_events_parser = subparsers.add_parser(
        "build-news-events",
        help="Merge latest scored AI news into event cards.",
    )
    build_news_events_parser.add_argument("--top", type=int, default=20)
    build_news_events_parser.add_argument("--min-score", type=float, default=60.0)
    build_news_events_parser.add_argument("--similarity-threshold", type=float, default=0.55)

    write_news_digest_parser = subparsers.add_parser(
        "write-news-digest",
        help="Write a Chinese AI news digest from latest event cards.",
    )
    write_news_digest_parser.add_argument("--top", type=int, default=12)
    write_news_digest_parser.add_argument("--date", default=None)

    review_news_digest_parser = subparsers.add_parser(
        "review-news-digest",
        help="Review, optionally polish, and package the latest AI news digest.",
    )
    review_news_digest_parser.add_argument("--threshold", type=float, default=80.0)
    review_news_digest_parser.add_argument(
        "--polish",
        dest="polish",
        action="store_true",
        help="Lightly polish the digest before packaging.",
    )
    review_news_digest_parser.add_argument(
        "--no-polish",
        dest="polish",
        action="store_false",
        help="Review and package without changing the digest text.",
    )
    review_news_digest_parser.set_defaults(polish=True)

    package_articles_parser = subparsers.add_parser(
        "package-articles",
        help="Generate packaged Markdown for final articles using README images.",
    )
    package_articles_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of final articles to package with README images.",
    )

    args = parser.parse_args(argv)
    orchestrator = DailyOrchestrator()

    if args.command == "run-daily":
        orchestrator.run_daily(
            limit_per_keyword=args.limit_per_keyword,
            score_top=args.score_top,
            research_top=args.research_top,
            article_top=args.article_top,
            review_threshold=args.review_threshold,
            cooldown_days=args.cooldown_days,
            ignore_history=args.ignore_history,
            allow_recent_fallback=args.allow_recent_fallback,
        )
    elif args.command == "schedule":
        _schedule_daily(
            run_time=args.time,
            limit_per_keyword=args.limit_per_keyword,
            score_top=args.score_top,
            research_top=args.research_top,
            article_top=args.article_top,
            review_threshold=args.review_threshold,
            cooldown_days=args.cooldown_days,
            ignore_history=args.ignore_history,
            allow_recent_fallback=args.allow_recent_fallback,
            run_once_first=args.run_once_first,
        )
    elif args.command == "discover":
        candidates = orchestrator.discover(limit_per_keyword=args.limit_per_keyword)
        _print_candidates(candidates)
    elif args.command == "write":
        orchestrator.write(args.repo)
    elif args.command == "score":
        orchestrator.score(top=args.top)
    elif args.command == "research":
        orchestrator.research(top=args.top)
    elif args.command == "angles":
        orchestrator.plan_angles(top=args.top)
    elif args.command in {"articles", "write-articles"}:
        orchestrator.write_articles(top=args.top)
    elif args.command == "plan-content":
        orchestrator.plan_content(top=args.top)
    elif args.command == "review-articles":
        orchestrator.review_articles(top=args.top, threshold=args.threshold)
    elif args.command == "humanize-articles":
        orchestrator.humanize_articles(top=args.top)
    elif args.command == "polish-for-publish":
        orchestrator.polish_for_publish(top=args.top)
    elif args.command == "write-custom":
        direction_text = _load_custom_direction(
            direction=args.direction,
            direction_file=args.direction_file,
        )
        reference_texts, reference_source_names = _load_style_references(
            reference_files=args.reference_file,
            reference_texts=args.reference_text,
        )
        result = orchestrator.write_custom_article(
            repo_url=args.repo_url,
            direction_text=direction_text,
            reference_texts=reference_texts,
            reference_source_names=reference_source_names,
        )
        _print_custom_article_result(result)
    elif args.command == "collect-news":
        _run_collect_news_command(
            hours=args.hours,
            limit=args.limit,
            include_fulltext=args.include_fulltext,
            sources=args.source,
            keywords=args.keyword,
            translate=args.translate,
            translate_limit=args.translate_limit,
        )
    elif args.command == "score-news":
        _run_score_news_command(top=args.top, min_score=args.min_score)
    elif args.command == "fetch-news-detail":
        _run_fetch_news_detail_command(news_id=args.news_id, refresh=args.refresh)
    elif args.command == "select-news":
        _run_select_news_command(
            news_ids=args.news_id,
            primary_news_id=args.primary_news_id,
            direction=args.direction,
        )
    elif args.command == "plan-news-article":
        if not args.latest and not args.selection_id:
            raise SystemExit("No selection specified. Use --latest or pass --selection-id.")
        _run_plan_news_article_command(selection_id=args.selection_id, latest=args.latest)
    elif args.command == "build-news-events":
        _run_build_news_events_command(
            top=args.top,
            min_score=args.min_score,
            similarity_threshold=args.similarity_threshold,
        )
    elif args.command == "write-news-digest":
        _run_write_news_digest_command(top=args.top, date=args.date)
    elif args.command == "review-news-digest":
        _run_review_news_digest_command(threshold=args.threshold, polish=args.polish)
    elif args.command == "package-articles":
        packages = orchestrator.package_articles(top=args.top)
        for article_package in packages:
            print(f"{article_package.full_name}")
            print(f"  package_dir: {article_package.package_dir}")
            print(f"  packaged_article: {article_package.packaged_article_path}")


def main() -> None:
    if typer is not None:
        app()
        return

    _run_with_argparse()


if __name__ == "__main__":
    main()
