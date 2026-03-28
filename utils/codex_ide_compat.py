"""Normalize local Codex history so IDE/app thread listing stays aligned."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

HOME = Path.home()
CODEX_DIR = HOME / ".codex"
CODEX_CONFIG_PATH = CODEX_DIR / "config.toml"
CODEX_THREADS_DB_PATH = CODEX_DIR / "state_5.sqlite"
CODEX_SESSIONS_DIR = CODEX_DIR / "sessions"
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_thread_text(value: str) -> str:
    text = _WHITESPACE_RE.sub(" ", (value or "").strip())
    if len(text) > 120:
        text = text[:117].rstrip() + "..."
    return text


def _resolve_target_model_provider() -> str:
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            tomllib = None  # type: ignore

    if tomllib and CODEX_CONFIG_PATH.is_file():
        try:
            data = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
            value = data.get("model_provider")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
    return "OpenAI"


def _find_rollout_path(thread_id: str, existing_path: str | None = None) -> Path | None:
    if existing_path:
        path = Path(existing_path)
        if path.is_file():
            return path

    if not CODEX_SESSIONS_DIR.is_dir():
        return None

    pattern = f"*{thread_id}*.jsonl"
    for path in CODEX_SESSIONS_DIR.rglob(pattern):
        if path.is_file():
            return path
    return None


def _normalize_session_meta(path: Path, *, target_source: str, target_provider: str) -> bool:
    if not path.is_file():
        return False

    changed = False
    updated_lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            updated_lines.append(raw_line)
            continue
        try:
            entry = json.loads(raw_line)
        except Exception:
            updated_lines.append(raw_line)
            continue

        if entry.get("type") == "session_meta" and isinstance(entry.get("payload"), dict):
            payload = dict(entry["payload"])
            if payload.get("source") != target_source:
                payload["source"] = target_source
                changed = True
            if payload.get("model_provider") != target_provider:
                payload["model_provider"] = target_provider
                changed = True
            if changed:
                entry = dict(entry)
                entry["payload"] = payload

        updated_lines.append(json.dumps(entry, ensure_ascii=False))

    if changed:
        path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return changed


def normalize_codex_threads_for_ide() -> dict[str, int]:
    """Make persisted threads match what local Codex thread/list expects."""
    if not CODEX_THREADS_DB_PATH.is_file():
        return {"updated": 0, "skipped": 0}

    target_provider = _resolve_target_model_provider()
    updated = 0
    skipped = 0

    try:
        connection = sqlite3.connect(str(CODEX_THREADS_DB_PATH))
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, rollout_path, source, model_provider, title, first_user_message
                FROM threads
                WHERE archived = 0
                """
            ).fetchall()

            for row in rows:
                current_source = row["source"] or ""
                current_provider = row["model_provider"] or ""
                next_source = "vscode" if current_source in {"mcp", "exec"} else current_source
                if current_provider.lower() == target_provider.lower():
                    next_provider = target_provider
                else:
                    next_provider = current_provider

                next_title = _sanitize_thread_text(row["title"] or "")
                next_first_user_message = _sanitize_thread_text(row["first_user_message"] or "")

                row_changed = (
                    next_source != current_source
                    or next_provider != current_provider
                    or next_title != (row["title"] or "")
                    or next_first_user_message != (row["first_user_message"] or "")
                )

                if row_changed:
                    connection.execute(
                        """
                        UPDATE threads
                        SET source = ?, model_provider = ?, title = ?, first_user_message = ?
                        WHERE id = ?
                        """,
                        (
                            next_source,
                            next_provider,
                            next_title,
                            next_first_user_message,
                            row["id"],
                        ),
                    )
                    updated += 1
                else:
                    skipped += 1

                rollout_path = _find_rollout_path(row["id"], row["rollout_path"])
                if rollout_path is not None:
                    if _normalize_session_meta(
                        rollout_path,
                        target_source=next_source or current_source or "vscode",
                        target_provider=next_provider or target_provider,
                    ):
                        if not row_changed:
                            updated += 1
                            skipped = max(0, skipped - 1)

            connection.commit()
        finally:
            connection.close()
    except Exception:
        return {"updated": 0, "skipped": 0}

    return {"updated": updated, "skipped": skipped}
