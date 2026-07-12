from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.content_index import ContentIndexService, _word_count
from src.models import ManualEditResult


class ManualEditService:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root).resolve()
        self.outputs_dir = self.project_root / "outputs"
        self.workspace_dir = self.project_root / "workspace"
        self.metadata_dir = self.workspace_dir / "manual_edits"
        self.index_service = ContentIndexService(self.project_root)

    @staticmethod
    def safe_id(content_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", content_id).strip("-").lower()[:100] or "content"
        digest = hashlib.sha256(content_id.encode("utf-8")).hexdigest()[:12]
        return f"{slug}-{digest}"

    def get(self, content_id: str) -> dict[str, Any]:
        metadata = self._read_metadata(content_id)
        path = self._safe_stored_path(metadata.get("manual_edit_path"))
        if not path.is_file():
            raise FileNotFoundError("Manual edit was not found")
        return {**metadata, "content_markdown": path.read_text(encoding="utf-8")}

    def save(self, content_id: str, content_markdown: str, based_on_variant: str, notes: str | None) -> ManualEditResult:
        item = self._require_item(content_id)
        now = datetime.now(timezone.utc)
        safe_id = self.safe_id(content_id)
        path = self.outputs_dir / now.date().isoformat() / "manual_edits" / f"{safe_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = content_markdown.rstrip() + "\n"
        path.write_text(normalized, encoding="utf-8")
        saved_at = now.isoformat().replace("+00:00", "Z")
        result = ManualEditResult(
            content_id=content_id,
            manual_edit_path=self._relative(path),
            saved_at=saved_at,
            word_count=_word_count(path) or 0,
            based_on_variant=based_on_variant,
        )
        metadata = {
            **self._dump(result),
            "title": item.title,
            "source_id": item.source_id,
            "safe_name": item.safe_name,
            "date": item.date,
            "notes": notes,
        }
        self._write_metadata(content_id, metadata)
        return result

    def delete(self, content_id: str) -> dict[str, Any]:
        metadata = self._read_metadata(content_id)
        path = self._safe_stored_path(metadata.get("manual_edit_path"))
        if path.exists():
            path.unlink()
        metadata_path = self._metadata_path(content_id)
        if metadata_path.exists():
            metadata_path.unlink()
        self._update_index(remove_content_id=content_id)
        return {"content_id": content_id, "deleted": True}

    def package_from_manual(self, content_id: str) -> dict[str, Any]:
        item = self._require_item(content_id)
        metadata = self._read_metadata(content_id)
        manual_path = self._safe_stored_path(metadata.get("manual_edit_path"))
        if not manual_path.is_file():
            raise FileNotFoundError("Manual edit was not found")
        package_path = self._package_path(item)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        package_path.write_text(manual_path.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")
        metadata["package_from_manual_path"] = self._relative(package_path)
        metadata["package_generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._write_metadata(content_id, metadata)
        return {
            "content_id": content_id,
            "package_path": self._relative(package_path),
            "manual_edit_path": self._relative(manual_path),
            "generated_at": metadata["package_generated_at"],
        }

    def _package_path(self, item: Any) -> Path:
        if item.package_path:
            return self._safe_stored_path(item.package_path)
        day = self.outputs_dir / item.date
        safe_name = item.safe_name or self.safe_id(item.content_id)
        if item.content_type in {"github_article", "github_custom_article"}:
            return day / "assets" / safe_name / "packaged_article.md"
        if item.content_type == "ai_news_article":
            return day / "news_articles" / f"{safe_name}_package.md"
        if item.content_type == "ai_news_digest":
            return day / "news_digest_package" / "packaged_ai_news_digest.md"
        return day / "manual_packages" / f"{self.safe_id(item.content_id)}.md"

    def _require_item(self, content_id: str) -> Any:
        item = self.index_service.find_item(content_id)
        if item is None:
            self.index_service.build_index()
            item = self.index_service.find_item(content_id)
        if item is None:
            raise KeyError(content_id)
        if item.content_type == "manual_edit":
            raise ValueError("Manual edits must be attached to an original content item")
        return item

    def _metadata_path(self, content_id: str) -> Path:
        return self.metadata_dir / f"{self.safe_id(content_id)}.json"

    def _read_metadata(self, content_id: str) -> dict[str, Any]:
        path = self._metadata_path(content_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            raise FileNotFoundError("Manual edit was not found")
        if not isinstance(data, dict) or data.get("content_id") != content_id:
            raise FileNotFoundError("Manual edit metadata is invalid")
        return data

    def _write_metadata(self, content_id: str, metadata: dict[str, Any]) -> None:
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_path(content_id).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._update_index(metadata)

    def _update_index(self, metadata: dict[str, Any] | None = None, remove_content_id: str | None = None) -> None:
        index_path = self.metadata_dir / "index.json"
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            payload = {"items": []}
        records = [record for record in payload.get("items", []) if isinstance(record, dict)]
        target_id = remove_content_id or (metadata or {}).get("content_id")
        records = [record for record in records if record.get("content_id") != target_id]
        if metadata:
            records.append(metadata)
        index_path.write_text(json.dumps({"items": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _safe_stored_path(self, value: Any) -> Path:
        if not isinstance(value, str) or not value:
            raise FileNotFoundError("Manual edit path is missing")
        return self.index_service._safe_path(value)

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.project_root).as_posix()

    @staticmethod
    def _dump(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="json") if hasattr(model, "model_dump") else model.dict()
