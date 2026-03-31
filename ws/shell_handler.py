"""PTY shell WebSocket handler — port of handleShellConnection from server/index.js.

Handles /shell WebSocket connections for terminal sessions.
Uses ptyprocess for pseudo-terminal management on macOS/Linux.
Message types: init, input, resize.
"""
import asyncio
import hashlib
import json
import os
import platform
import re
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import ptyprocess

from fastapi import WebSocket, WebSocketDisconnect

from config import DEFAULT_TERMINAL_SHELL, TERMINAL_ENABLED

# ---------------------------------------------------------------------------
# PTY session cache (survives WebSocket reconnects)
# ---------------------------------------------------------------------------

DEFAULT_PTY_SESSION_TIMEOUT = 5 * 60
MAX_PTY_SESSION_TIMEOUT = 60 * 60
DEFAULT_MAX_RETAINED_SESSIONS = 5
MAX_RETAINED_SESSIONS = 10
SHELL_URL_PARSE_BUFFER_LIMIT = 2048

pty_sessions: dict[str, dict] = {}

# URL detection patterns
_URL_PATTERN = re.compile(r"https?://[^\s\x1b\x07]+")
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def _strip_ansi(text: str) -> str:
    return _ANSI_PATTERN.sub("", text)


def _extract_urls(text: str) -> list[str]:
    return _URL_PATTERN.findall(text)


def _normalize_url(url: str) -> str | None:
    """Normalize a detected URL (strip trailing punctuation, etc.)."""
    url = url.rstrip(".,;:!?)>]}'\"")
    if not url.startswith("http"):
        return None
    return url


def _clamp_int(value: object, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _parse_retention_settings(data: dict) -> tuple[int, int]:
    retention_minutes = _clamp_int(
        data.get("shellRetentionMinutes"),
        DEFAULT_PTY_SESSION_TIMEOUT // 60,
        0,
        MAX_PTY_SESSION_TIMEOUT // 60,
    )
    max_retained_sessions = _clamp_int(
        data.get("shellMaxRetainedSessions"),
        DEFAULT_MAX_RETAINED_SESSIONS,
        0,
        MAX_RETAINED_SESSIONS,
    )
    return retention_minutes, max_retained_sessions


def _build_session_key(user_scope: str, project_path: str, session_id: str | None, cmd_suffix: str) -> str:
    return f"{user_scope}::{project_path}_{session_id or 'default'}{cmd_suffix}"


def _terminate_retained_session(session_key: str, reason: str) -> None:
    session = pty_sessions.pop(session_key, None)
    if not session:
        return
    timeout_task = session.get("timeout_task")
    if timeout_task:
        timeout_task.cancel()
    proc = session.get("pty")
    if proc and proc.isalive():
        proc.terminate(force=True)
    print(f"[Shell] PTY session closed: {session_key} ({reason})")


def _enforce_retention_limit(user_scope: str, max_retained_sessions: int) -> None:
    if max_retained_sessions <= 0:
        for key, session in list(pty_sessions.items()):
            if session.get("userScope") == user_scope and not session.get("ws"):
                _terminate_retained_session(key, "retention disabled")
        return

    detached_sessions = [
        (key, session)
        for key, session in pty_sessions.items()
        if session.get("userScope") == user_scope and not session.get("ws")
    ]
    detached_sessions.sort(key=lambda item: item[1].get("lastDetachedAt") or 0, reverse=True)

    for key, _session in detached_sessions[max_retained_sessions:]:
        _terminate_retained_session(key, "retention limit exceeded")


async def _safe_send_terminal_disabled(ws: WebSocket):
    try:
        await ws.send_json({
            "type": "output",
            "data": "\x1b[33mTerminal access is disabled for this node.\x1b[0m\r\n",
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shell handler
# ---------------------------------------------------------------------------

async def handle_shell_connection(ws: WebSocket):
    """Handle a /shell WebSocket connection."""
    await ws.accept()
    print("[Shell] WebSocket connected")

    if not TERMINAL_ENABLED:
        await _safe_send_terminal_disabled(ws)
        try:
            await ws.close()
        except Exception:
            pass
        return

    pty_proc = None
    pty_session_key: str | None = None
    url_buffer = ""
    announced_urls: set[str] = set()
    read_task: asyncio.Task | None = None

    async def _send(data: dict):
        try:
            await ws.send_json(data)
        except Exception:
            pass

    async def _read_pty_output(proc, session_key: str):
        """Continuously read from PTY and forward to WebSocket."""
        nonlocal url_buffer
        loop = asyncio.get_event_loop()

        while True:
            try:
                # Read from PTY in executor (blocking I/O)
                data = await loop.run_in_executor(None, lambda: proc.read(4096))
                if not data:
                    break

                text = data if isinstance(data, str) else data.decode("utf-8", errors="replace")

                # Buffer for session
                session = pty_sessions.get(session_key)
                if session:
                    buf = session.get("buffer", [])
                    if len(buf) < 5000:
                        buf.append(text)
                    else:
                        buf.pop(0)
                        buf.append(text)

                    # Only send if we have an active WS
                    if session.get("ws"):
                        # URL detection
                        clean = _strip_ansi(text)
                        url_buffer = (url_buffer + clean)[-SHELL_URL_PARSE_BUFFER_LIMIT:]

                        # Replace OPEN_URL markers
                        output = re.sub(
                            r"OPEN_URL:\s*(https?://[^\s\x1b\x07]+)",
                            r"[INFO] Opening in browser: \1",
                            text,
                        )

                        # Detect and announce auth URLs
                        for raw_url in _extract_urls(url_buffer):
                            url = _normalize_url(raw_url)
                            if url and url not in announced_urls:
                                announced_urls.add(url)
                                try:
                                    await session["ws"].send_json({
                                        "type": "auth_url",
                                        "url": url,
                                        "autoOpen": False,
                                    })
                                except Exception:
                                    pass

                        try:
                            await session["ws"].send_json({"type": "output", "data": output})
                        except Exception:
                            pass

            except EOFError:
                break
            except Exception as e:
                if "I/O operation on closed file" in str(e):
                    break
                print(f"[Shell] PTY read error: {e}")
                break

        # Process exited
        try:
            exit_code = proc.wait(timeout=1) if proc.isalive() else proc.exitstatus or 0
        except Exception:
            exit_code = -1

        session = pty_sessions.get(session_key)
        if session and session.get("ws"):
            try:
                await session["ws"].send_json({
                    "type": "output",
                    "data": f"\r\n\x1b[33mProcess exited with code {exit_code}\x1b[0m\r\n",
                })
            except Exception:
                pass

        # Cleanup
        pty_sessions.pop(session_key, None)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "init":
                project_path = data.get("projectPath") or os.getcwd()
                session_id = data.get("sessionId")
                has_session = data.get("hasSession", False)
                provider = data.get("provider", "claude")
                initial_command = data.get("initialCommand")
                user_scope = str(data.get("userId") or "anon")
                retention_minutes, max_retained_sessions = _parse_retention_settings(data)
                is_plain_shell = data.get("isPlainShell") or (bool(initial_command) and not has_session) or provider == "plain-shell"

                url_buffer = ""
                announced_urls.clear()

                # Build session key
                cmd_suffix = ""
                if is_plain_shell and initial_command:
                    cmd_hash = hashlib.md5(initial_command.encode()).hexdigest()[:16]
                    cmd_suffix = f"_cmd_{cmd_hash}"
                pty_session_key = _build_session_key(user_scope, project_path, session_id, cmd_suffix)

                # Login command detection
                is_login = initial_command and any(
                    kw in initial_command for kw in ("setup-token", "auth login")
                )

                # Kill old login sessions
                if is_login and pty_session_key in pty_sessions:
                    old = pty_sessions.pop(pty_session_key)
                    if old.get("pty") and old["pty"].isalive():
                        old["pty"].terminate(force=True)
                    if old.get("timeout_task"):
                        old["timeout_task"].cancel()

                # Try reconnect to existing session
                existing = None if is_login else pty_sessions.get(pty_session_key)
                if existing:
                    print(f"[Shell] Reconnecting to existing PTY: {pty_session_key}")
                    pty_proc = existing["pty"]
                    existing["retentionSeconds"] = retention_minutes * 60
                    existing["maxRetainedSessions"] = max_retained_sessions

                    if existing.get("timeout_task"):
                        existing["timeout_task"].cancel()
                        existing["timeout_task"] = None

                    await _send({"type": "output", "data": "\x1b[36m[Reconnected to existing session]\x1b[0m\r\n"})

                    # Replay buffer
                    for buf_data in existing.get("buffer", []):
                        await _send({"type": "output", "data": buf_data})

                    existing["ws"] = ws
                    continue

                # Validate project path
                resolved_path = os.path.abspath(project_path)
                if not os.path.isdir(resolved_path):
                    print(f"[Shell] Invalid project path: {project_path} -> {resolved_path}")
                    await _send({"type": "error", "message": "Invalid project path"})
                    continue

                # Validate session ID
                if session_id and not re.match(r"^[a-zA-Z0-9_.\-:]+$", session_id):
                    await _send({"type": "error", "message": "Invalid session ID"})
                    continue

                # Build shell command
                if is_plain_shell:
                    shell_command = initial_command or DEFAULT_TERMINAL_SHELL
                elif provider == "codex":
                    if has_session and session_id:
                        shell_command = f'codex resume "{session_id}" || codex'
                    else:
                        shell_command = "codex"
                else:
                    # Claude (default)
                    command = initial_command or "claude"
                    if has_session and session_id:
                        shell_command = f'claude --resume "{session_id}" || claude'
                    else:
                        shell_command = command

                # Welcome message
                if is_plain_shell:
                    welcome = f"\x1b[36mStarting terminal in: {project_path}\x1b[0m\r\n"
                else:
                    pname = "Codex" if provider == "codex" else "Claude"
                    if has_session:
                        welcome = f"\x1b[36mResuming {pname} session {session_id} in: {project_path}\x1b[0m\r\n"
                    else:
                        welcome = f"\x1b[36mStarting new {pname} session in: {project_path}\x1b[0m\r\n"

                await _send({"type": "output", "data": welcome})

                try:
                    cols = data.get("cols", 80)
                    rows = data.get("rows", 24)

                    shell = "/bin/bash"
                    env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "FORCE_COLOR": "3"}

                    print(f"[Shell] Spawning: {shell_command} in {resolved_path} ({cols}x{rows})")

                    pty_proc = ptyprocess.PtyProcess.spawn(
                        [shell, "-c", shell_command],
                        dimensions=(rows, cols),
                        cwd=resolved_path,
                        env=env,
                    )

                    pty_sessions[pty_session_key] = {
                        "pty": pty_proc,
                        "ws": ws,
                        "buffer": [],
                        "timeout_task": None,
                        "userScope": user_scope,
                        "retentionSeconds": retention_minutes * 60,
                        "maxRetainedSessions": max_retained_sessions,
                        "lastDetachedAt": None,
                        "project_path": project_path,
                        "session_id": session_id,
                    }

                    # Start reading PTY output
                    read_task = asyncio.create_task(_read_pty_output(pty_proc, pty_session_key))

                except Exception as e:
                    print(f"[Shell] Spawn error: {e}")
                    await _send({"type": "output", "data": f"\r\n\x1b[31mError: {e}\x1b[0m\r\n"})

            elif msg_type == "input":
                if pty_proc and pty_proc.isalive():
                    try:
                        input_data = data.get("data", "")
                        if isinstance(input_data, str):
                            pty_proc.write(input_data.encode("utf-8"))
                        else:
                            pty_proc.write(input_data)
                    except Exception as e:
                        print(f"[Shell] Write error: {e}")

            elif msg_type == "resize":
                if pty_proc and pty_proc.isalive():
                    cols = data.get("cols", 80)
                    rows = data.get("rows", 24)
                    try:
                        pty_proc.setwinsize(rows, cols)
                    except Exception:
                        pass

    except WebSocketDisconnect:
        print("[Shell] WebSocket disconnected")
    except Exception as e:
        print(f"[Shell] Connection error: {e}")
    finally:
        # Keep PTY alive for reconnection
        if pty_session_key and pty_session_key in pty_sessions:
            session = pty_sessions[pty_session_key]
            session["ws"] = None
            session["lastDetachedAt"] = time.time()
            print(f"[Shell] PTY kept alive for reconnection: {pty_session_key}")

            keepalive_seconds = int(session.get("retentionSeconds") or 0)
            max_retained_sessions = int(session.get("maxRetainedSessions") or 0)
            user_scope = str(session.get("userScope") or "anon")

            if session.get("timeout_task"):
                session["timeout_task"].cancel()

            _enforce_retention_limit(user_scope, max_retained_sessions)

            if keepalive_seconds <= 0 or max_retained_sessions <= 0:
                _terminate_retained_session(pty_session_key, "retention disabled")
                return

            async def _timeout_kill():
                await asyncio.sleep(keepalive_seconds)
                if pty_session_key in pty_sessions:
                    _terminate_retained_session(pty_session_key, "retention timeout")

            try:
                session["timeout_task"] = asyncio.create_task(_timeout_kill())
            except RuntimeError:
                pass

        if read_task and not read_task.done():
            # Let it finish naturally when PTY closes
            pass
