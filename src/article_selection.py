from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import shutil
from typing import Any

from .models import RepoResearchNote, RepoScore


class ArticleSelectionService:
    """Select daily article projects with history cooldown and fair fallback."""

    def __init__(self, history_path: Path, prefer_growth_projects: bool = True) -> None:
        self.history_path = history_path
        self.prefer_growth_projects = prefer_growth_projects
        self.warnings: list[str] = []

    def load_history(self) -> dict[str, Any]:
        if not self.history_path.exists():
            return {"version": 1, "articles": []}

        try:
            payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        except Exception as exc:
            backup_path = self._backup_corrupt_history()
            self.warnings.append(
                "article history is unreadable; backed up corrupt file and rebuilt empty history: "
                f"{type(exc).__name__}: {exc}"
                + (f" ({backup_path})" if backup_path else "")
            )
            return {"version": 1, "articles": []}

        if not isinstance(payload, dict):
            backup_path = self._backup_corrupt_history()
            self.warnings.append(
                "article history must be a JSON object; backed up corrupt file and rebuilt empty history."
                + (f" ({backup_path})" if backup_path else "")
            )
            return {"version": 1, "articles": []}

        articles = payload.get("articles")
        if isinstance(articles, list):
            return {"version": int(payload.get("version") or 1), "articles": articles}

        legacy_items = [
            item
            for item in payload.values()
            if isinstance(item, dict) and item.get("repo_full_name")
        ]
        if legacy_items:
            return {"version": 1, "articles": legacy_items}

        backup_path = self._backup_corrupt_history()
        self.warnings.append(
            "article history has no articles list; backed up corrupt file and rebuilt empty history."
            + (f" ({backup_path})" if backup_path else "")
        )
        return {"version": 1, "articles": []}

    def select_repos(
        self,
        scored_repos: list[RepoScore],
        research_notes: list[RepoResearchNote] | None,
        article_top: int,
        article_history: dict[str, Any] | None = None,
        cooldown_days: int = 30,
        allow_recent_fallback: bool = False,
        ignored_history: bool = False,
    ) -> tuple[list[str], dict[str, Any]]:
        target_count = max(0, article_top)
        notes_by_name = {note.full_name: note for note in (research_notes or [])}
        scored_candidates = [
            score
            for score in sorted(scored_repos, key=lambda item: item.total_score, reverse=True)
        ]
        researched_candidate_count = sum(1 for score in scored_candidates if score.full_name in notes_by_name)

        if ignored_history:
            history = article_history if article_history is not None else self.load_history()
            history_by_name = self._daily_history_by_name(history)
            cutoff = datetime.utcnow() - timedelta(days=max(0, cooldown_days))
            skipped_recent = []
            for score in scored_candidates:
                entry = history_by_name.get(score.full_name)
                last_written_at = self._parse_datetime(entry.get("last_written_at")) if entry else None
                if entry and last_written_at and last_written_at >= cutoff:
                    skipped_recent.append(
                        {
                            "repo_full_name": score.full_name,
                            "title": entry.get("title") or "",
                            "last_written_at": entry.get("last_written_at"),
                            "write_count": int(entry.get("write_count") or 0),
                        }
                    )
            selected_scores = scored_candidates[:target_count]
            selection_buckets = {"top_score": [score.full_name for score in selected_scores]} if selected_scores else {}
            selected = [score.full_name for score in selected_scores]
            summary = self._summary(
                selected_repos=selected,
                selected_scores=selected_scores,
                selection_buckets=selection_buckets,
                candidate_count=len(scored_candidates),
                fresh_candidate_count=len(scored_candidates),
                repeated_candidate_count=len(skipped_recent),
                researched_candidate_count=researched_candidate_count,
                target_count=target_count,
                skipped_recent=skipped_recent,
                fallback_repos=[],
                cooldown_days=cooldown_days,
                ignored_history=True,
                allow_recent_fallback=allow_recent_fallback,
                history_warning_count=len(self.warnings),
            )
            return selected, summary

        history = article_history if article_history is not None else self.load_history()
        history_by_name = self._daily_history_by_name(history)
        cutoff = datetime.utcnow() - timedelta(days=max(0, cooldown_days))

        unwritten_candidates: list[RepoScore] = []
        older_history_candidates: list[RepoScore] = []
        recent_candidates: list[RepoScore] = []
        skipped_recent: list[dict[str, Any]] = []

        for score in scored_candidates:
            entry = history_by_name.get(score.full_name)
            if not entry:
                unwritten_candidates.append(score)
                continue
            last_written_at = self._parse_datetime(entry.get("last_written_at")) if entry else None
            if last_written_at and last_written_at >= cutoff:
                recent_candidates.append(score)
                skipped_recent.append(
                    {
                        "repo_full_name": score.full_name,
                        "title": entry.get("title") or "",
                        "last_written_at": entry.get("last_written_at"),
                        "write_count": int(entry.get("write_count") or 0),
                    }
                )
                continue
            older_history_candidates.append(score)

        fresh_candidates = unwritten_candidates + older_history_candidates
        selected_scores, selection_buckets = self._select_diverse(fresh_candidates, target_count)
        selected = [score.full_name for score in selected_scores]
        fallback_repos: list[str] = []

        if len(selected) < target_count and allow_recent_fallback:
            already_selected = set(selected)
            needed = target_count - len(selected)
            fallback_candidates = sorted(
                recent_candidates,
                key=lambda score: self._history_fallback_key(score.full_name, history_by_name),
            )
            for score in fallback_candidates:
                if score.full_name in already_selected:
                    continue
                selected.append(score.full_name)
                selected_scores.append(score)
                selection_buckets.setdefault("history_fallback", []).append(score.full_name)
                fallback_repos.append(score.full_name)
                if len(fallback_repos) >= needed:
                    break

        summary = self._summary(
            selected_repos=selected,
            selected_scores=selected_scores,
            selection_buckets=selection_buckets,
            candidate_count=len(scored_candidates),
            fresh_candidate_count=len(fresh_candidates),
            repeated_candidate_count=len(recent_candidates),
            researched_candidate_count=researched_candidate_count,
            target_count=target_count,
            skipped_recent=skipped_recent,
            fallback_repos=fallback_repos,
            cooldown_days=cooldown_days,
            ignored_history=False,
            allow_recent_fallback=allow_recent_fallback,
            history_warning_count=len(self.warnings),
        )
        return selected, summary

    def _select_diverse(
        self,
        candidates: list[RepoScore],
        target_count: int,
    ) -> tuple[list[RepoScore], dict[str, list[str]]]:
        if target_count <= 0:
            return [], {}

        sorted_candidates = sorted(candidates, key=lambda item: item.total_score, reverse=True)
        if not self.prefer_growth_projects:
            selected = sorted_candidates[:target_count]
            return selected, {"top_score": [score.full_name for score in selected]}

        selected: list[RepoScore] = []
        selected_names: set[str] = set()
        buckets: dict[str, list[str]] = {"top_score": [], "recent_growth": [], "practical_tool": [], "score_fill": []}

        def add_candidate(score: RepoScore, bucket: str) -> bool:
            if score.full_name in selected_names or len(selected) >= target_count:
                return False
            selected.append(score)
            selected_names.add(score.full_name)
            buckets.setdefault(bucket, []).append(score.full_name)
            return True

        if sorted_candidates:
            add_candidate(sorted_candidates[0], "top_score")

        if len(selected) < target_count:
            growth_candidate = next(
                (score for score in sorted_candidates if self._is_growth_candidate(score) and score.full_name not in selected_names),
                None,
            )
            if growth_candidate is not None:
                add_candidate(growth_candidate, "recent_growth")

        if len(selected) < target_count:
            tool_candidate = next(
                (score for score in sorted_candidates if self._is_tool_candidate(score) and score.full_name not in selected_names),
                None,
            )
            if tool_candidate is not None:
                add_candidate(tool_candidate, "practical_tool")

        for score in sorted_candidates:
            if len(selected) >= target_count:
                break
            add_candidate(score, "score_fill")

        return selected, {key: value for key, value in buckets.items() if value}

    def _is_growth_candidate(self, score: RepoScore) -> bool:
        discovery_reason = (score.discovery_reason or "").lower()
        if "recent_active" in discovery_reason or "recent_growth" in discovery_reason or "newly_created" in discovery_reason:
            return True
        return score.velocity_score >= 8.0 or (score.freshness_score >= 8.0 and score.growth_score <= 14.0)

    def _is_tool_candidate(self, score: RepoScore) -> bool:
        discovery_reason = (score.discovery_reason or "").lower()
        reason_text = " ".join(score.reasons).lower()
        if "practical_tool" in discovery_reason or "active_tooling" in discovery_reason:
            return True
        return "实用工具" in reason_text or "tool" in reason_text or "cli" in reason_text or "terminal" in reason_text

    def update_history(
        self,
        final_articles: list[Any],
        source: str = "daily",
        output_paths_by_name: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        history = self.load_history()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        articles = [
            item
            for item in history.get("articles", [])
            if isinstance(item, dict) and item.get("repo_full_name")
        ]
        index = {
            (str(item.get("source") or "daily"), str(item.get("repo_full_name"))): item
            for item in articles
        }

        for article in final_articles:
            full_name = str(getattr(article, "full_name", "") or getattr(article, "repo_full_name", "") or "")
            if not full_name:
                continue
            title = str(getattr(article, "title", "") or "")
            output_path = (output_paths_by_name or {}).get(full_name, "")
            key = (source, full_name)
            entry = index.get(key)
            if entry is None:
                entry = {
                    "repo_full_name": full_name,
                    "title": title,
                    "source": source,
                    "first_written_at": now,
                    "last_written_at": now,
                    "write_count": 1,
                    "latest_output_path": output_path,
                }
                articles.append(entry)
                index[key] = entry
                continue

            entry["title"] = title or entry.get("title") or ""
            entry["source"] = source
            entry["first_written_at"] = entry.get("first_written_at") or now
            entry["last_written_at"] = now
            entry["write_count"] = int(entry.get("write_count") or 0) + 1
            entry["latest_output_path"] = output_path or entry.get("latest_output_path") or ""

        payload = {"version": 1, "updated_at": now, "articles": articles}
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def _daily_history_by_name(self, history: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in history.get("articles", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("source") or "daily") != "daily":
                continue
            full_name = str(item.get("repo_full_name") or "")
            if not full_name:
                continue
            current = result.get(full_name)
            if current is None:
                result[full_name] = item
                continue
            if self._parse_datetime(str(item.get("last_written_at") or "")) > self._parse_datetime(
                str(current.get("last_written_at") or "")
            ):
                result[full_name] = item
        return result

    def _backup_corrupt_history(self) -> str:
        if not self.history_path.exists():
            return ""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        backup_path = self.history_path.with_name(f"article_history.corrupt.{timestamp}.json")
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.history_path, backup_path)
            self.history_path.write_text(
                json.dumps({"version": 1, "articles": []}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self.warnings.append(f"failed to back up corrupt article history: {type(exc).__name__}: {exc}")
            return ""
        return str(backup_path)

    def _history_fallback_key(
        self,
        full_name: str,
        history_by_name: dict[str, dict[str, Any]],
    ) -> tuple[datetime, int, str]:
        entry = history_by_name.get(full_name, {})
        last_written_at = self._parse_datetime(str(entry.get("last_written_at") or ""))
        write_count = int(entry.get("write_count") or 0)
        return (last_written_at, write_count, full_name)

    def _parse_datetime(self, value: str | None) -> datetime:
        if not value:
            return datetime.min
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is not None:
                return parsed.replace(tzinfo=None)
            return parsed
        except ValueError:
            return datetime.min

    def _summary(
        self,
        selected_repos: list[str],
        selected_scores: list[RepoScore],
        selection_buckets: dict[str, list[str]],
        candidate_count: int,
        fresh_candidate_count: int,
        repeated_candidate_count: int,
        researched_candidate_count: int,
        target_count: int,
        skipped_recent: list[dict[str, Any]],
        fallback_repos: list[str],
        cooldown_days: int,
        ignored_history: bool,
        allow_recent_fallback: bool,
        history_warning_count: int,
    ) -> dict[str, Any]:
        selected_repos_with_reason = [
            {
                "repo_full_name": score.full_name,
                "bucket": (bucket := self._bucket_for_repo(score.full_name, selection_buckets)),
                "reason": self._selection_reason(score, bucket),
                "total_score": score.total_score,
                "growth_score": score.growth_score,
                "velocity_score": score.velocity_score,
                "freshness_score": score.freshness_score,
                "discovery_reason": score.discovery_reason,
            }
            for score in selected_scores
        ]
        growth_selected_count = sum(1 for score in selected_scores if self._is_growth_candidate(score))
        tool_selected_count = sum(1 for score in selected_scores if self._is_tool_candidate(score))
        return {
            "candidate_count": candidate_count,
            "fresh_candidate_count": fresh_candidate_count,
            "repeated_candidate_count": repeated_candidate_count,
            "researched_candidate_count": researched_candidate_count,
            "target_count": target_count,
            "selected_repos": selected_repos,
            "selected_repos_with_reason": selected_repos_with_reason,
            "selection_buckets": selection_buckets,
            "growth_selected_count": growth_selected_count,
            "tool_selected_count": tool_selected_count,
            "skipped_recent_repos": skipped_recent,
            "skipped_recent_count": len(skipped_recent),
            "fallback_repos": fallback_repos,
            "fallback_count": len(fallback_repos),
            "cooldown_days": cooldown_days,
            "ignored_history": ignored_history,
            "allow_recent_fallback": allow_recent_fallback,
            "allow_fill_from_history": allow_recent_fallback,
            "new_project_shortage": len(selected_repos) < target_count,
            "shortage_count": max(0, target_count - len(selected_repos)),
            "history_warning_count": history_warning_count,
            "warnings": list(self.warnings),
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }

    def _bucket_for_repo(self, full_name: str, selection_buckets: dict[str, list[str]]) -> str:
        for bucket, names in selection_buckets.items():
            if full_name in names:
                return bucket
        return "score_fill"

    def _selection_reason(self, score: RepoScore, bucket: str) -> str:
        if bucket == "practical_tool":
            return "实用工具属性明确，适合写给开发者日常使用场景。"
        if bucket == "top_score":
            if self._is_growth_candidate(score):
                return "综合评分最高，同时具备近期增长/新鲜度信号。"
            return "综合评分最高，作为稳定质量项目保留。"
        if bucket == "recent_growth" or self._is_growth_candidate(score):
            return "近期增长/新鲜度信号突出，避免只按总 Star 排序遗漏。"
        return "综合评分最高，作为稳定质量项目保留。"
