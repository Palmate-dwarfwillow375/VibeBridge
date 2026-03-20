"""In-memory node registry for the Main Server.

Port of server/main/node-registry.js.
Tracks connected Node servers and their status.
"""
import asyncio
import time

NODE_STATUS_ONLINE = "online"
NODE_STATUS_SUSPECT = "suspect"
NODE_STATUS_OFFLINE = "offline"

SUSPECT_TIMEOUT = 45  # seconds
OFFLINE_TIMEOUT = 75  # seconds


class NodeRegistry:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self._health_task: asyncio.Task | None = None

    @staticmethod
    def _is_ws_usable(ws) -> bool:
        if ws is None:
            return False

        client_state = getattr(ws, "client_state", None)
        application_state = getattr(ws, "application_state", None)
        if client_state is not None or application_state is not None:
            state_names = [
                getattr(value, "name", str(value)).upper()
                for value in (client_state, application_state)
                if value is not None
            ]
            if state_names:
                if any("DISCONNECT" in name or "CLOSED" in name for name in state_names):
                    return False
                if all("CONNECTED" in name for name in state_names):
                    return True

        closed = getattr(ws, "closed", None)
        if isinstance(closed, bool):
            return not closed

        state = getattr(ws, "state", None)
        if state is not None:
            state_name = getattr(state, "name", None)
            if state_name:
                normalized = str(state_name).upper()
                if "OPEN" in normalized or "CONNECTED" in normalized:
                    return True
                if "CLOSED" in normalized or "DISCONNECT" in normalized:
                    return False

        try:
            return bool(ws)
        except Exception:
            return True

    def _effective_status(self, record: dict) -> str:
        status = record.get("status", NODE_STATUS_OFFLINE)
        if status == NODE_STATUS_ONLINE and not self._is_ws_usable(record.get("ws")):
            return NODE_STATUS_OFFLINE
        return status

    def start_health_check(self, interval: float = 5.0):
        if self._health_task is None:
            self._health_task = asyncio.create_task(self._health_loop(interval))

    def stop_health_check(self):
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None

    def register(self, node_id: str, ws, info: dict | None = None) -> dict:
        info = info or {}
        existing = self.nodes.get(node_id)

        # Close old WS if replaced
        if existing and existing.get("ws") and existing["ws"] is not ws:
            try:
                asyncio.create_task(existing["ws"].close(1000, "Replaced by new connection"))
            except Exception:
                pass

        now = time.time()
        record = {
            "nodeId": node_id,
            "displayName": info.get("displayName") or info.get("nodeName") or node_id,
            "status": NODE_STATUS_ONLINE,
            "version": info.get("version", "unknown"),
            "capabilities": info.get("capabilities", []),
            "labels": info.get("labels", []),
            "port": info.get("port", 3000),
            "advertiseHost": info.get("advertiseHost"),
            "advertisePort": info.get("advertisePort"),
            "explicitHost": info.get("host"),
            "explicitPort": info.get("explicitPort"),
            "connectedAt": existing["connectedAt"] if existing else now,
            "lastSeenAt": now,
            "ws": ws,
        }
        self.nodes[node_id] = record
        return record

    def unregister(self, node_id: str):
        record = self.nodes.get(node_id)
        if record:
            record["status"] = NODE_STATUS_OFFLINE
            record["ws"] = None

    def remove(self, node_id: str) -> dict | None:
        record = self.nodes.pop(node_id, None)
        if record and record.get("ws"):
            try:
                asyncio.create_task(record["ws"].close(1000, "Removed from registry"))
            except Exception:
                pass
            record["ws"] = None
        return record

    def get_node(self, node_id: str) -> dict | None:
        return self.nodes.get(node_id)

    def get_all_nodes(self) -> list[dict]:
        result = []
        for r in self.nodes.values():
            status = self._effective_status(r)
            if status != r.get("status"):
                r["status"] = status
            host = r.get("explicitHost") or r.get("advertiseHost") or "localhost"
            port = r.get("explicitPort") or r.get("advertisePort") or r.get("port")
            result.append({
                "nodeId": r["nodeId"],
                "displayName": r["displayName"],
                "status": status,
                "version": r["version"],
                "capabilities": r["capabilities"],
                "labels": r["labels"],
                "host": host,
                "port": port,
                "connectedAt": r["connectedAt"],
                "lastSeenAt": r["lastSeenAt"],
            })
        return result

    def update_heartbeat(self, node_id: str):
        record = self.nodes.get(node_id)
        if record:
            record["lastSeenAt"] = time.time()
            record["status"] = NODE_STATUS_ONLINE

    def is_online(self, node_id: str) -> bool:
        record = self.nodes.get(node_id)
        if not record:
            return False
        status = self._effective_status(record)
        if status != record.get("status"):
            record["status"] = status
        return status == NODE_STATUS_ONLINE

    def get_node_address(self, node_id: str) -> dict | None:
        record = self.nodes.get(node_id)
        if not record:
            return None

        host = record.get("explicitHost") or record.get("advertiseHost") or "localhost"

        port = record.get("explicitPort") or record.get("advertisePort") or record.get("port", 3000)
        return {"host": host, "port": port}

    async def _health_loop(self, interval: float):
        while True:
            await asyncio.sleep(interval)
            now = time.time()
            for record in self.nodes.values():
                if record["status"] == NODE_STATUS_OFFLINE:
                    continue
                elapsed = now - record["lastSeenAt"]
                if elapsed > OFFLINE_TIMEOUT:
                    record["status"] = NODE_STATUS_OFFLINE
                    record["ws"] = None
                elif elapsed > SUSPECT_TIMEOUT:
                    record["status"] = NODE_STATUS_SUSPECT
