"""Helpers for keeping Codex's lightweight session index in sync.

This module deliberately avoids touching Codex's SQLite runtime database.
Instead, it appends entries to ``~/.codex/session_index.jsonl`` so sessions
created via MCP/exec become visible to Codex's own history UI.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from database.db import session_names_db

HOME = Path.home()
CODEX_DIR = HOME / ".codex"
CODEX_SESSION_INDEX_PATH = CODEX_DIR / "session_index.jsonl"
CODEX_THREADS_DB_PATH = CODEX_DIR / "state_5.sqlite"

_WHITESPACE_RE = re.compile(r"\s+")
_INDEX_LOCK = Lock()
_INDEX_CACHE: dict[str, dict[str, str]] = {}
_INDEX_FINGERPRINT: tuple[int, int] | None = None


def reset_codex_session_index_cache() -> None:
    """Reset the in-memory session_index cache (mainly used by tests)."""
    global _INDEX_CACHE, _INDEX_FINGERPRINT
    with _INDEX_LOCK:
        _INDEX_CACHE = {}
        _INDEX_FINGERPRINT = None


def _get_index_fingerprint() -> tuple[int, int] | None:
    try:
        stat = CODEX_SESSION_INDEX_PATH.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load_index_cache_locked() -> None:
    global _INDEX_CACHE, _INDEX_FINGERPRINT

    fingerprint = _get_index_fingerprint()
    if fingerprint == _INDEX_FINGERPRINT:
        return

    cache: dict[str, dict[str, str]] = {}
    if CODEX_SESSION_INDEX_PATH.is_file():
        try:
            with CODEX_SESSION_INDEX_PATH.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue

                    thread_id = str(entry.get("id") or "").strip()
                    thread_name = str(entry.get("thread_name") or "").strip()
                    updated_at = str(entry.get("updated_at") or "").strip()
                    if not thread_id or not thread_name:
                        continue

                    cache[thread_id] = {
                        "id": thread_id,
                        "thread_name": thread_name,
                        "updated_at": updated_at,
                    }
        except Exception:
            cache = {}

    _INDEX_CACHE = cache
    _INDEX_FINGERPRINT = fingerprint


def get_session_index_entry(thread_id: str) -> dict[str, str] | None:
    normalized_id = str(thread_id or "").strip()
    if not normalized_id:
        return None

    with _INDEX_LOCK:
        _load_index_cache_locked()
        entry = _INDEX_CACHE.get(normalized_id)
        return dict(entry) if entry else None


def is_session_indexed(thread_id: str) -> bool:
    return get_session_index_entry(thread_id) is not None


def _looks_like_real_codex_thread_id(thread_id: str) -> bool:
    if not thread_id or not isinstance(thread_id, str):
        return False
    normalized_id = thread_id.strip()
    if not normalized_id or normalized_id.startswith("codex-"):
        return False
    try:
        uuid.UUID(normalized_id)
    except Exception:
        return False
    return True


def _sanitize_thread_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    text = _WHITESPACE_RE.sub(" ", value).strip()
    if not text:
        return None

    if len(text) > 120:
        text = text[:117].rstrip() + "..."

    return text


def _format_updated_at(updated_at: Any = None) -> str:
    if isinstance(updated_at, str):
        text = updated_at.strip()
        if text:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return text
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    if isinstance(updated_at, datetime):
        parsed = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    if isinstance(updated_at, (int, float)):
        parsed = datetime.fromtimestamp(float(updated_at), tz=timezone.utc)
        return parsed.isoformat().replace("+00:00", "Z")

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_session_index_entry(
    thread_id: str,
    thread_name: str,
    *,
    updated_at: Any = None,
) -> bool:
    global _INDEX_FINGERPRINT

    normalized_id = str(thread_id or "").strip()
    normalized_name = _sanitize_thread_name(thread_name)

    if not _looks_like_real_codex_thread_id(normalized_id) or not normalized_name:
        return False

    entry = {
        "id": normalized_id,
        "thread_name": normalized_name,
        "updated_at": _format_updated_at(updated_at),
    }

    CODEX_SESSION_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"

    with _INDEX_LOCK:
        _load_index_cache_locked()
        with CODEX_SESSION_INDEX_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
        _INDEX_CACHE[normalized_id] = entry
        _INDEX_FINGERPRINT = _get_index_fingerprint()

    return True


def _get_custom_session_name(thread_id: str) -> str | None:
    try:
        custom_name = session_names_db.get_name(thread_id, "codex")
    except Exception:
        return None
    return _sanitize_thread_name(custom_name)


def get_codex_thread_metadata(thread_id: str) -> dict[str, Any] | None:
    normalized_id = str(thread_id or "").strip()
    if not normalized_id or not CODEX_THREADS_DB_PATH.is_file():
        return None

    try:
        connection = sqlite3.connect(str(CODEX_THREADS_DB_PATH))
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """
                SELECT id, title, first_user_message, updated_at, source, archived
                FROM threads
                WHERE id = ?
                """,
                (normalized_id,),
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return None

    if row is None:
        return None

    return {
        "id": row["id"],
        "title": row["title"],
        "first_user_message": row["first_user_message"],
        "updated_at": row["updated_at"],
        "source": row["source"],
        "archived": row["archived"],
    }


def resolve_codex_thread_name(
    thread_id: str,
    *,
    fallback_name: str | None = None,
    prefer_existing_name: bool = True,
) -> str | None:
    custom_name = _get_custom_session_name(thread_id)
    if custom_name:
        return custom_name

    if prefer_existing_name:
        existing_entry = get_session_index_entry(thread_id)
        if existing_entry:
            existing_name = _sanitize_thread_name(existing_entry.get("thread_name"))
            if existing_name:
                return existing_name

    metadata = get_codex_thread_metadata(thread_id)
    if metadata:
        for candidate in (metadata.get("title"), metadata.get("first_user_message")):
            normalized = _sanitize_thread_name(candidate)
            if normalized:
                return normalized

    return _sanitize_thread_name(fallback_name)


def sync_codex_session_index_entry(
    thread_id: str,
    *,
    fallback_name: str | None = None,
    updated_at: Any = None,
    prefer_existing_name: bool = True,
) -> bool:
    normalized_id = str(thread_id or "").strip()
    if not _looks_like_real_codex_thread_id(normalized_id):
        return False

    thread_name = resolve_codex_thread_name(
        normalized_id,
        fallback_name=fallback_name,
        prefer_existing_name=prefer_existing_name,
    )
    if not thread_name:
        return False

    return append_session_index_entry(
        normalized_id,
        thread_name,
        updated_at=updated_at,
    )


def backfill_codex_session_index(*, limit: int | None = None) -> dict[str, int]:
    """Append missing MCP/exec threads into Codex's session index."""
    if not CODEX_THREADS_DB_PATH.is_file():
        return {"added": 0, "skipped": 0}

    try:
        connection = sqlite3.connect(str(CODEX_THREADS_DB_PATH))
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, title, first_user_message, updated_at, source
                FROM threads
                WHERE archived = 0
                  AND source IN ('mcp', 'exec')
                  AND (
                    COALESCE(first_user_message, '') <> ''
                    OR COALESCE(title, '') <> ''
                  )
                ORDER BY updated_at ASC
                """
            ).fetchall()
        finally:
            connection.close()
    except Exception:
        return {"added": 0, "skipped": 0}

    added = 0
    skipped = 0

    for row in rows:
        thread_id = row["id"]
        if is_session_indexed(thread_id):
            skipped += 1
            continue

        thread_name = resolve_codex_thread_name(
            thread_id,
            fallback_name=row["title"] or row["first_user_message"],
            prefer_existing_name=False,
        )
        if not thread_name:
            skipped += 1
            continue

        if append_session_index_entry(thread_id, thread_name, updated_at=row["updated_at"]):
            added += 1
        else:
            skipped += 1

        if limit is not None and added >= limit:
            break

    return {"added": added, "skipped": skipped}
