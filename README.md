<div align="center">
  <img src="./frontend-src/public/logo-256.png" alt="VibeBridge logo" width="120" />
  <h1>VibeBridge</h1>
  <p>
    One Main Server, many Nodes, one browser UI.
    Manage Claude Code and Codex sessions across multiple machines from a single control plane.
  </p>
</div>

<div align="right"><i><b>English</b> · <a href="./README.zh-CN.md">中文</a></i></div>

---

<p align="center">
  <img src="./docs/screenshots/vibebridge-overview.jpg" alt="VibeBridge managing Claude Code and Codex sessions from multiple nodes in one UI" width="100%" />
</p>

## One Main, Many Nodes

The core model of `VibeBridge` is one-to-many node management.

One `Main Server` acts as the browser-facing control plane, and many `Node Servers` can attach to it. Each node can host local workspaces and run `Claude Code` and `Codex`, while the browser stays pointed at a single Main entry.

That means you can:

- keep multiple machines online under one UI
- open Claude Code sessions on one node and Codex sessions on another
- switch between sessions from different nodes without changing browser entry points
- keep file, shell, and Git actions anchored to the machine that actually owns the workspace

## Overview

`VibeBridge` is a Python-based control plane for running `Claude Code` and `Codex` across one or many machines.

Instead of exposing each machine separately, VibeBridge gives you one browser entry point and a clear split between control plane and execution plane.

The system is built around two roles:

- `main_server.py`: the single user entry, control plane, static file server, auth layer, and node router
- `app.py`: the worker node, execution plane, and local Claude Code / Codex / shell / filesystem / project host

The repository directory is still named `cc_server`, but the product described by this README is `VibeBridge`.

This split is intentional:

- The browser should always talk to the Main Server
- Node Servers should not be treated as direct browser-facing UI servers
- Main and Node should not be collapsed back into one monolith

## Features

- One-to-many node management: one Main can manage multiple Nodes and aggregate their Claude Code / Codex sessions
- Single browser entry: the browser always enters through Main
- Session-centric workflow: creating a session means choosing a node, entering a path, and selecting a provider
- Provider support: Claude Code and Codex
- WebSocket relay for chat and shell traffic
- Local execution on each node for project, filesystem, shell, Git, and provider operations
- Simplified settings: the current Settings UI exposes only `Agents`, `Appearance`, and `Git`
- Python backend on both Main and Node, built with FastAPI

In practice, this means you can keep multiple work machines online, register them to one Main Server, and operate Claude Code and Codex sessions from different nodes inside the same UI.

## Architecture

```text
Browser
  -> Main Server (main_server.py)
       - serve dist/
       - auth + JWT
       - /api/nodes/*
       - /ws and /shell relay
       - node registry and routing
  -> Node Server(s) (app.py)
       - connect to Main via /ws/node
       - run Claude Code / Codex locally
       - expose local project, filesystem, shell, git and settings APIs
```

Important guardrails:

- `Main Server` is the only browser entry
- `Node Server` is not the page server for browsers
- Browsers should not bypass Main and talk directly to Nodes
- Do not merge Main and Node back into one service

## Connection Models

VibeBridge supports two node-to-main connection models:

### 1. Node-initiated direct WebSocket

The Node opens a direct WebSocket connection to Main at `/ws/node`.

- Main stays passive on the node connection path
- Simple when Nodes can directly reach Main
- Configure with `node.main_server_url` in `configs/node.toml`
- If Main sees the wrong Node IP, set `node.advertise_host` and optionally `node.advertise_port`

### 2. Node HTTP registration + Main outbound WebSocket

The Node sends an HTTP registration request to Main, and Main then actively connects back to the Node at `/ws/main`.

- Useful when Main can reach the Node, but you want Node discovery to begin from the Node side
- Useful when you want to register a node by HTTP and let Main own the long-lived WebSocket
- Configure with `node.main_register_url` in `configs/node.toml`
- If the callback address should be forced manually, set `node.advertise_host` and `node.advertise_port`

If both `node.main_server_url` and `node.main_register_url` are set on the same node, VibeBridge currently prefers the direct WebSocket mode.

## How It Feels

VibeBridge is designed around sessions, not around a heavyweight "project first" flow.

- To start work, you choose a `node`
- Then you enter the workspace `path`
- Then you select the provider, `claude` or `codex`

The UI keeps the browser side simple while leaving execution on the target machine. That makes it practical to manage Claude Code and Codex work across multiple nodes without losing the mental model of "this session belongs to that machine and that folder."

<a id="quick-start"></a>

## Quick Start

### 1. Prepare the environment

Use a dedicated conda environment if possible. The current development setup uses an environment named `cc_server`.

### 2. Install Python dependencies

```bash
cd cc_server
conda run --no-capture-output -n cc_server pip install -r requirements.txt
```

### 3. Install frontend dependencies

```bash
cd cc_server/frontend-src
npm install
```

### 4. Build the frontend

`dist/` is served by the Main Server, so the recommended workflow is to build directly into the repository root `dist/`.

```bash
cd cc_server/frontend-src
npm run typecheck
npm run build -- --emptyOutDir --outDir ../dist
```

### 5. Edit the TOML configs

VibeBridge now uses only two runtime config files:

- `configs/main.toml`
- `configs/node.toml`

Edit those two files directly. The Main process always reads `configs/main.toml`, and each Node process reads its own local copy of `configs/node.toml`.

### 6. Start the Main Server

```bash
cd cc_server
conda run --no-capture-output -n cc_server \
python main_server.py
```

### 7. Start one Node Server

Edit `configs/node.toml` first if the Node should register to another Main host or use HTTP registration instead of direct WebSocket.

Mode A, direct Node -> Main WebSocket:

```bash
cd cc_server
conda run --no-capture-output -n cc_server \
python app.py
```

Mode B, Node HTTP registration and Main -> Node outbound WebSocket:

```bash
cd cc_server
conda run --no-capture-output -n cc_server \
python app.py
```

To add more nodes, start additional `app.py` processes on other machines with their own `configs/node.toml`.

### 8. Open the UI

```text
http://<main-host>:4457/
```

If the database is empty, the first visit goes through registration. The current system is single-user: Main issues the JWT, and Nodes trust the authenticated user context forwarded by Main.

For same-machine local testing, `http://127.0.0.1:4457/` or `http://localhost:4457/` is still fine. For real multi-node use, open the Main Server through its reachable host or IP.

For local development, keeping Main and Node on separate ports and separate SQLite files is strongly recommended. Even on a single machine, it is better to keep the real Main + Node shape than to fall back to a browser-direct-to-node shortcut.

## Configuration Files

| File or Key | Used By | Description |
| --- | --- | --- |
| `configs/main.toml` | Main | Main runtime config file |
| `configs/node.toml` | Node | Node runtime config file |
| `server.host` / `server.port` | Main / Node | Listening address and port |
| `database.path` | Main / Node | SQLite database path |
| `auth.jwt_secret` | Main | JWT secret; auto-generated and persisted if omitted |
| `main.node_register_tokens` | Main | Allowed node registration tokens |
| `main.node_addresses` | Main | Nodes that Main should connect to proactively |
| `node.main_server_url` | Node | Direct WebSocket registration target |
| `node.main_register_url` | Node | HTTP registration target for Main callback mode |
| `node.id` / `node.name` | Node | Stable node identifier and display name |
| `node.register_token` | Node | Node registration token |
| `node.labels` / `node.capabilities` | Node | Labels and declared capabilities |
| `node.advertise_host` / `node.advertise_port` | Node | Manually override the host/port Main should use to reach this Node |
| `filesystem.*` | Node | File browser guardrails |
| `terminal.default_shell` | Node | Default shell used by the built-in terminal view |
| `providers.claude.*` / `providers.codex.*` | Node | Provider-specific timeouts and limits |

Runtime configuration is loaded from TOML files only.

## Repository Layout

```text
cc_server/
├── README.md
├── README.zh-CN.md
├── app.py
├── main_server.py
├── config.py
├── requirements.txt
├── Dockerfile
├── database/
├── main/
├── middleware/
├── providers/
├── routes/
├── ws/
├── frontend-src/
└── dist/
```

Good starting points:

- `main_server.py`
- `app.py`
- `node_connector.py`
- `main/browser_gateway.py`
- `main/node_ws_server.py`
- `main/ws_relay.py`
- `main/shell_relay.py`
- `providers/claude_sdk.py`
- `providers/codex_mcp.py`
- `frontend-src/src/components/sidebar/view/Sidebar.tsx`
- `frontend-src/src/components/settings/view/Settings.tsx`

If you are new to the codebase, a practical reading order is:

1. `main_server.py`
2. `app.py`
3. `node_connector.py`
4. `main/browser_gateway.py`
5. `providers/claude_sdk.py` and `providers/codex_mcp.py`

## Providers

### Claude

- `providers/claude_sdk.py`
- Uses the real Python SDK path and should not be replaced by a fake stub
- Dependency is declared in `requirements.txt`: `claude-agent-sdk`

### Codex

- `providers/codex_mcp.py`
- Uses `codex mcp-server` as the primary path
- Falls back to `codex exec --json` if MCP bootstrap fails
- Requires the `codex` CLI to be available on the machine

## Frontend Notes

The frontend has already been adapted to the current session model:

- Creating a session means choosing `node + path + provider`
- The default sidebar shows only opened sessions
- A grouped mode is available as `node -> project -> session`
- Settings currently expose only `Agents`, `Appearance`, and `Git`

The current UI intentionally avoids re-introducing a separate "new project" concept at the top level. A new session still registers the workspace under the hood, but the user-facing action is session-first.

## Development Notes

- The root `dist/` directory is what Main serves to browsers
- A plain `npm run build` writes to `frontend-src/dist/`, so sync it if needed
- The current `Dockerfile` only describes the `Node Server` role, not the full `Main + Node` deployment
- If the browser still requests stale assets, first check old bundles in `dist/`, browser cache, or service workers

When updating docs or product copy, prefer describing the system as:

- one Main Server
- many Node Servers
- one browser entry
- session-centric multi-machine control

That wording matches the actual implementation better than older single-machine or monolithic descriptions.

## Verification

Main:

```bash
curl -sf http://<main-host>:4457/health
```

Node:

```bash
curl -sf http://<node-host>:4456/health
```

In a healthy local setup:

- Main prints `/ws/node` and `/ws` addresses
- Node prints connection logs when registering to Main
- After login, the browser should be able to load `/api/nodes`

## Design Decisions

- Do not let browsers bypass Main and talk directly to Node
- Do not merge Main and Node back into one service
- Do not add fake Claude responses just to make things appear to work

<a id="acknowledgements"></a>

## Acknowledgements

- [claudecodeui](https://github.com/siteboon/claudecodeui)
- [happy](https://github.com/slopus/happy)
