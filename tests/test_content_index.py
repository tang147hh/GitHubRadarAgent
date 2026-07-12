import json
from pathlib import Path

import pytest

from src.content_index import ContentIndexService
from src.manual_edits import ManualEditService


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_index_merges_agent_artifacts_and_reads_variants(tmp_path: Path) -> None:
    source = tmp_path / "outputs/2026-07-12/custom_articles/acme__demo.md"
    package = tmp_path / "outputs/2026-07-12/assets/acme__demo/packaged_article.md"
    _write(source, "# Demo article\n\n" + "content " * 120)
    _write(package, "# Packaged demo\n\n" + "package " * 120)
    snapshot = tmp_path / "workspace/snapshots/custom_article_latest.json"
    _write(
        snapshot,
        json.dumps(
            {
                "full_name": "acme/demo",
                "generated_at": "2026-07-12T10:00:00Z",
                "output_markdown_path": source.relative_to(tmp_path).as_posix(),
                "packaged_article_path": package.relative_to(tmp_path).as_posix(),
                "quality_score": 91,
                "quality_publish_ready": True,
            }
        ),
    )
    run = tmp_path / "workspace/agent_runs/agentrun_test.json"
    _write(
        run,
        json.dumps(
            {
                "run_id": "agentrun_test",
                "created_at": "2026-07-12T10:00:00Z",
                "status": "succeeded",
                "artifacts": [source.relative_to(tmp_path).as_posix(), package.relative_to(tmp_path).as_posix()],
            }
        ),
    )

    service = ContentIndexService(tmp_path)
    index = service.build_index()

    assert index.total_count == 1
    item = index.items[0]
    assert item.content_type == "github_custom_article"
    assert item.agent_run_id == "agentrun_test"
    assert item.status == "packaged"
    assert service.read_markdown(item.content_id, "source")[0].startswith("# Demo article")
    assert service.read_markdown(item.content_id, "package")[0].startswith("# Packaged demo")
    assert service.index_path.is_file()
    assert service.report_path and service.report_path.is_file()


def test_markdown_reader_rejects_paths_outside_content_roots(tmp_path: Path) -> None:
    service = ContentIndexService(tmp_path)
    with pytest.raises(ValueError, match="outside allowed content roots"):
        service._safe_path("../secret.md")


def test_manual_edit_links_to_original_and_generates_package(tmp_path: Path) -> None:
    source = tmp_path / "outputs/2026-07-12/custom_articles/acme__demo.md"
    _write(source, "# AI article\n\n" + "content " * 120)
    _write(
        tmp_path / "workspace/snapshots/custom_article_latest.json",
        json.dumps({"full_name": "acme/demo", "generated_at": "2026-07-12T10:00:00Z"}),
    )
    index_service = ContentIndexService(tmp_path)
    item = index_service.build_index().items[0]
    manual_service = ManualEditService(tmp_path)

    result = manual_service.save(item.content_id, "# Human article\n\nEdited copy", "source", "editor note")
    rebuilt = index_service.build_index()
    original = next(candidate for candidate in rebuilt.items if candidate.content_id == item.content_id)

    assert original.has_manual_edit is True
    assert original.manual_edit_path == result.manual_edit_path
    assert index_service.read_markdown(item.content_id, "manual")[0].startswith("# Human article")
    package = manual_service.package_from_manual(item.content_id)
    rebuilt = index_service.build_index()
    original = next(candidate for candidate in rebuilt.items if candidate.content_id == item.content_id)
    assert original.status == "packaged"
    assert original.package_path == package["package_path"]
    assert (tmp_path / package["package_path"]).read_text(encoding="utf-8").startswith("# Human article")

    manual_service.delete(item.content_id)
    rebuilt = index_service.build_index()
    original = next(candidate for candidate in rebuilt.items if candidate.content_id == item.content_id)
    assert original.has_manual_edit is False


def test_publishing_readiness_and_export_priority(tmp_path: Path) -> None:
    source = tmp_path / "outputs/2026-07-12/custom_articles/acme__desk.md"
    package = tmp_path / "outputs/2026-07-12/assets/acme__desk/packaged_article.md"
    report = tmp_path / "outputs/2026-07-12/custom_articles/acme__desk_report.md"
    _write(source, "# Source\n\n" + "content " * 120)
    _write(package, "# Package\n\nPackaged copy")
    _write(report, "# Review\n\nPassed")
    _write(
        tmp_path / "workspace/snapshots/custom_article_latest.json",
        json.dumps(
            {
                "full_name": "acme/desk",
                "quality_score": 92,
                "quality_publish_ready": True,
            }
        ),
    )
    service = ContentIndexService(tmp_path)
    item = service.build_index().items[0]
    assert item.readiness_status == "ready"
    assert service.build_publishing_desk()["summary"]["ready_count"] == 1

    ManualEditService(tmp_path).save(item.content_id, "# Manual\n\nEdited copy", "source")
    service.build_index()
    exported = service.export_publish_markdown(item.content_id)
    assert exported["variant"] == "manual"
    assert exported["content"].startswith("# Manual")
