<div align="center">
  <img src="./frontend-src/public/logo-256.png" alt="VibeBridge logo" width="120" />
  <h1>VibeBridge</h1>
  <p>
    一个 Main Server，连接多个 Node，只保留一个浏览器入口。
    在同一个控制面里统一管理多台机器上的 Claude Code 与 Codex 会话。
  </p>
</div>

<div align="right"><i><a href="./README.md">English</a> · <b>中文</b></i></div>

---

<p align="center">
  <img src="./docs/screenshots/vibebridge-overview.jpg" alt="VibeBridge 在一个界面中统一管理多个节点上的 Claude Code 与 Codex 会话" width="100%" />
</p>

## 一对多节点管理

`VibeBridge` 的核心不是“单机 UI 包一层壳”，而是一个很明确的一对多控制模型。

一个 `Main Server` 作为唯一浏览器入口和控制面，多个 `Node Server` 挂到它下面。每个节点各自运行本机工作目录、本机 shell、本机 Git，以及本机的 `Claude Code` 和 `Codex`，而浏览器始终只需要打开同一个 Main。

这意味着你可以：

- 用一个 UI 管多台机器
- 在节点 A 上开 Claude Code，会话同时也能在节点 B 上开 Codex
- 在不同节点的 session 之间切换，而不用切换不同网页入口
- 让文件、终端、Git 操作始终落在真正拥有该工作目录的那台机器上

## 项目概览

`VibeBridge` 是一个基于 Python 的多节点控制面，用来在一台或多台机器上运行 `Claude Code` 和 `Codex`，并通过同一个浏览器入口统一操作。

它的目标不是把每台机器都直接暴露给浏览器，而是把“控制面”和“执行面”明确拆开。

系统围绕两个角色构建：

- `main_server.py`：唯一用户入口、控制面、静态文件服务、认证与节点转发
- `app.py`：工作节点、执行面、本机 Claude Code / Codex / shell / 文件 / 项目能力承载

仓库目录目前仍然叫 `cc_server`，但这份 README 面向的产品名是 `VibeBridge`。

这条边界是刻意保持的：

- 浏览器始终应该访问 Main Server
- Node Server 不应该被当成浏览器直接访问的页面服务
- 不要再把 Main 和 Node 重新合成一个单体服务

## 核心特性

- 一对多节点管理：一个 Main 可以统一管理多个 Node，并汇总它们上的 Claude Code / Codex 会话
- 单一浏览器入口：浏览器始终从 Main 进入
- Session 优先的工作流：新建会话时选择节点、输入路径、选择 provider
- 当前支持的 provider：Claude Code 与 Codex
- 聊天与 shell 请求通过 WebSocket relay 转发
- 各节点本地执行项目、文件、shell、Git 与 provider 能力
- 设置页已简化：当前仅保留 `Agents`、`Appearance`、`Git`
- Main 与 Node 均为 Python 后端，基于 FastAPI

换句话说，你可以把多台工作机器接到同一个 Main 上，然后在同一个 UI 里统一操作不同节点上的 Claude Code 与 Codex 会话，而不需要来回切换多个页面入口。

## 架构

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

关键约束：

- `Main Server` 是唯一浏览器入口
- `Node Server` 不是给浏览器直接打开的页面服务
- 浏览器不应该绕过 Main 直接访问 Node
- 不要把 Main 和 Node 再揉回一个服务

## 连接模型

VibeBridge 目前支持两种 Node 接入 Main 的方式：

### 1. Node 主动直连 Main WebSocket

Node 直接连到 Main 的 `/ws/node`。

- Main 在节点接入链路上是被动接收方
- 适合 Node 能直接访问 Main 的场景
- 在 `configs/node.toml` 里配置 `node.main_server_url`
- 如果 Main 自动识别到的 Node IP 不对，可以手动填 `node.advertise_host`，端口不对时再配 `node.advertise_port`

### 2. Node 先发 HTTP 注册，再由 Main 主动反连 Node

Node 先向 Main 发送 HTTP 注册请求，随后 Main 主动连到 Node 的 `/ws/main`。

- 适合希望由 Node 发起发现、但由 Main 持有长连接的场景
- 适合“先注册节点，再由 Main 统一反连”的部署方式
- 在 `configs/node.toml` 里配置 `node.main_register_url`
- 如果 Main 反连 Node 时地址不对，可以手动指定 `node.advertise_host` 和 `node.advertise_port`

如果同一个 Node 同时设置了 `node.main_server_url` 和 `node.main_register_url`，当前实现会优先使用直连 WebSocket 模式。

## 使用模型

VibeBridge 的设计核心是 session，而不是一个很重的“先建项目再工作”的流程。

- 开始工作时，先选 `node`
- 再输入工作目录 `path`
- 再选择 `claude` 或 `codex`

浏览器侧只负责统一入口和会话管理，真正的执行发生在目标机器上。这样在多节点场景下，用户仍然能清楚知道“这个 session 属于哪台机器、哪个目录”。

<a id="quick-start"></a>

## 快速开始

### 1. 准备环境

建议使用独立 conda 环境。当前开发默认使用名为 `cc_server` 的环境。

### 2. 安装 Python 依赖

```bash
cd cc_server
conda run --no-capture-output -n cc_server pip install -r requirements.txt
```

### 3. 安装前端依赖

```bash
cd cc_server/frontend-src
npm install
```

### 4. 构建前端

`dist/` 由 Main Server 提供给浏览器，因此推荐直接把前端构建到仓库根目录的 `dist/`。

```bash
cd cc_server/frontend-src
npm run typecheck
npm run build -- --emptyOutDir --outDir ../dist
```

### 5. 编辑 TOML 配置

VibeBridge 现在只使用两个运行配置文件：

- `configs/main.toml`
- `configs/node.toml`

直接编辑这两个文件即可。Main 进程固定读取 `configs/main.toml`，每个 Node 进程读取自己机器上的 `configs/node.toml`。

### 6. 启动 Main Server

```bash
cd cc_server
conda run --no-capture-output -n cc_server \
python main_server.py
```

### 7. 启动一个 Node Server

如果 Node 要连远端 Main，或者要切换到 HTTP 注册模式，先编辑 `configs/node.toml`。

模式 A：Node 直接 WS 连接 Main

```bash
cd cc_server
conda run --no-capture-output -n cc_server \
python app.py
```

模式 B：Node 先 HTTP 注册，再由 Main 主动 WS 反连

```bash
cd cc_server
conda run --no-capture-output -n cc_server \
python app.py
```

如果要接更多节点，只需要在其他机器上再启动更多 `app.py`，并为各自准备单独的 `configs/node.toml`。

### 8. 打开界面

```text
http://<main-host>:4457/
```

如果数据库为空，第一次访问会进入注册流程。当前系统是单用户模型：Main 负责签发 JWT，Node 在多节点模式下信任 Main 转发的已认证用户信息。

如果只是同机本地联调，使用 `http://127.0.0.1:4457/` 或 `http://localhost:4457/` 也完全可以；如果是正式多节点使用，就应该通过 Main Server 的实际可访问主机名或 IP 打开。

本地开发时，也建议把 Main 和 Node 分别跑在不同端口、不同 SQLite 文件上。即使是单机联调，也尽量保持真实的 Main + Node 形态，不要退回“浏览器直接打 Node”的临时结构。

## 配置文件

| 文件或键 | 作用角色 | 说明 |
| --- | --- | --- |
| `configs/main.toml` | Main | Main 运行配置文件 |
| `configs/node.toml` | Node | Node 运行配置文件 |
| `server.host` / `server.port` | Main / Node | 监听地址和端口 |
| `database.path` | Main / Node | SQLite 数据库路径 |
| `auth.jwt_secret` | Main | JWT 密钥；不传时会自动生成并保存 |
| `main.node_register_tokens` | Main | 允许节点注册到 Main 的 token 列表 |
| `main.node_addresses` | Main | Main 启动时主动连接的节点地址 |
| `node.main_server_url` | Node | 直连 Main 的 WebSocket 地址 |
| `node.main_register_url` | Node | HTTP 注册地址，供 Main 反连模式使用 |
| `node.id` / `node.name` | Node | 节点稳定标识和显示名称 |
| `node.register_token` | Node | 节点注册 token |
| `node.labels` / `node.capabilities` | Node | 节点标签和能力声明 |
| `node.advertise_host` / `node.advertise_port` | Node | 手动指定 Main 回连该 Node 时应使用的主机名/IP 和端口 |
| `filesystem.*` | Node | 文件浏览相关限制 |
| `terminal.default_shell` | Node | 内置终端默认使用的 shell |
| `providers.claude.*` / `providers.codex.*` | Node | Provider 相关超时和限制 |

运行配置现在只从 TOML 文件读取。

## 目录结构

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

建议优先阅读这些文件：

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

如果你第一次读这个仓库，一个比较顺的阅读顺序是：

1. `main_server.py`
2. `app.py`
3. `node_connector.py`
4. `main/browser_gateway.py`
5. `providers/claude_sdk.py` 与 `providers/codex_mcp.py`

## Provider 说明

### Claude

- `providers/claude_sdk.py`
- 走真实 Python SDK 链路，不应该用 fake stub 替代
- 依赖由 `requirements.txt` 提供：`claude-agent-sdk`

### Codex

- `providers/codex_mcp.py`
- 优先走 `codex mcp-server`
- 如果 MCP 初始化失败，会回退到 `codex exec --json`
- 机器上需要可用的 `codex` CLI

## 验证方式

Main:

```bash
curl -sf http://<main-host>:4457/health
```

Node:

```bash
curl -sf http://<node-host>:4456/health
```

正常情况下：

- Main 会打印 `/ws/node` 与 `/ws` 地址
- Node 会打印注册到 Main 的连接日志
- 浏览器登录后应能获取 `/api/nodes`

<a id="acknowledgements"></a>

## 致谢

- [claudecodeui](https://github.com/siteboon/claudecodeui)
- [happy](https://github.com/slopus/happy)
