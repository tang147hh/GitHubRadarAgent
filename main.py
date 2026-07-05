from __future__ import annotations

import argparse
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Optional

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
