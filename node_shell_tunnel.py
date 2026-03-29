"""WS-tunneled shell bridge for Main <-> Node relaying."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from fastapi import WebSocketDisconnect

from ws.shell_handler import handle_shell_connection

ShellSender = Callable[[dict], Awaitable[None]]

_shell_tunnels: dict[str, dict] = {}


class _InMemoryShellSocket:
    def __init__(self, shell_id: str, sender: ShellSender):
        self.shell_id = shell_id
        self._sender = sender
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False

    async def accept(self):
        return None

    async def receive_text(self) -> str:
        payload = await self._incoming.get()
        if payload is None:
            raise WebSocketDisconnect()
        return payload

    async def send_json(self, data: dict):
        await self._sender(data)

    async def close(self, *_args, **_kwargs):
        if self._closed:
            return
        self._closed = True
        await self._incoming.put(None)

    async def feed(self, raw: str):
        if self._closed:
            raise RuntimeError(f"Shell tunnel {self.shell_id} is closed")
        await self._incoming.put(raw)


async def open_shell_tunnel(shell_id: str, init_message: str, sender: ShellSender) -> None:
    existing = _shell_tunnels.pop(shell_id, None)
    if existing:
        await existing["socket"].close()

    socket = _InMemoryShellSocket(shell_id, sender)

    async def _run():
        try:
            await handle_shell_connection(socket)
        finally:
            current = _shell_tunnels.get(shell_id)
            if current and current.get("task") is asyncio.current_task():
                _shell_tunnels.pop(shell_id, None)

    task = asyncio.create_task(_run())
    _shell_tunnels[shell_id] = {"socket": socket, "task": task}
    await socket.feed(init_message)


async def send_shell_message(shell_id: str, raw_message: str) -> None:
    tunnel = _shell_tunnels.get(shell_id)
    if not tunnel:
        raise RuntimeError(f"Shell tunnel {shell_id} not found")
    await tunnel["socket"].feed(raw_message)


async def close_shell_tunnel(shell_id: str) -> None:
    tunnel = _shell_tunnels.pop(shell_id, None)
    if not tunnel:
        return
    await tunnel["socket"].close()
