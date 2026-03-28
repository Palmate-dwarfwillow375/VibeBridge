"""Helpers for locating and launching the Codex CLI in constrained environments."""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

_EXTRA_BIN_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / ".local" / "bin"),
]


def build_augmented_path(current_path: str | None = None) -> str:
    seen: set[str] = set()
    ordered: list[str] = []

    for raw_entry in [*(_EXTRA_BIN_DIRS), *((current_path or "").split(os.pathsep))]:
        entry = raw_entry.strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        ordered.append(entry)

    return os.pathsep.join(ordered)


def get_codex_cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = build_augmented_path(env.get("PATH"))
    return env


@lru_cache(maxsize=1)
def resolve_codex_cli() -> str:
    override = os.environ.get("CODEX_CLI_PATH", "").strip()
    if override:
        return override

    resolved = shutil.which("codex", path=build_augmented_path(os.environ.get("PATH")))
    if resolved:
        return resolved

    for candidate in _EXTRA_BIN_DIRS:
        binary = Path(candidate) / "codex"
        if binary.is_file():
            return str(binary)

    return "codex"
