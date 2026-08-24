# lulu-agent

`lulu-agent` 是一个本地运行的通用 agent。它提供 Web GUI (推荐) 和 CLI 两种入口，可以在本机进行日常对话、读写文件、执行命令、维护长期记忆和复用技能等。

当前版本：`v4.0`。

## 主要能力

- 本地 Web GUI，支持按 workspace 分组的会话列表、创建会话前选择 workspace、聊天、工具调用展示、任务状态、Trace、Memory、Skills 和 MCP 工具查看。
- CLI 入口，支持会话恢复、会话查看和 context inspect。
- OpenAI-compatible 模型服务，支持 streaming 和 tool calling。
- 全局 session / trace 持久化，可以跨 workspace 恢复历史会话并查看运行诊断；workspace 失效时会锁定 session，保留数据等待原路径恢复或用户显式删除。
- 持久化会话历史和任务状态，关闭后可以继续恢复和查看。
- 本地文件工具：列文件、读文件、写文件、替换文件、全文搜索。
- Shell 工具：执行本地命令，并对高风险命令做安全拦截或确认。
- Web 工具：通过 Tavily 进行搜索和网页内容提取。
- 长期记忆：将跨会话事实和偏好保存到全局 memory。
- Skills：将可复用流程沉淀为全局 skill，并在需要时读取。
- Knowledge review：后台定期审查 memory / skills，并在 Trace 中展示 review 是否发生和粗粒度变更摘要。
- MCP：从全局 MCP 配置加载外部 stdio MCP 工具。

## 安装

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

初始化全局 lulu 配置和内置 skill：

```bash
python setup/lulu_setup.py
```

首次使用前建议先运行这一步，确保 `~/.lulu/` 里的 `memory/MEMORY.md`、`skills`、`mcp.json` 和 `models.json` 都已准备好。session 和 trace 目录会在首次写入时自动创建。

如果使用 Web GUI，还需要安装 GUI 依赖：

```bash
cd gui
npm install
```

## 配置

模型配置保存在全局用户目录 `~/.lulu/models.json`。每个 provider 直接填写 OpenAI-compatible 服务地址、API key 和默认模型
暂不使用的 provider 可以先留空 `base_url` 或 `api_key`，GUI 会显示但禁止选择：
```json
{
  "default_provider": "deepseek",
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com",
      "api_key": "your-api-key",
      "default_model": "deepseek-v4-flash"
    }
  }
}
```

模型服务需要兼容 OpenAI chat completion，并支持 tool calling。GUI 会尝试从 provider 拉取可用模型列表，若 `default_model` 留空时会自动切换，若已配置的 `default_model` 不可用也可手动切换。

`.env` 只用于其他配置，例如 `TAVILY_API_KEY`、模型请求超时/重试次数和 safety profile。首次初始化后，模型配置、MCP 配置和内置 skill 分别位于 `~/.lulu/models.json`、`~/.lulu/mcp.json` 和 `~/.lulu/skills/`。当前环境变量名使用 `MODEL_TIMEOUT_SECONDS`、`MODEL_MAX_RETRIES` 和 `SAFETY_PROFILE`。

如果需要 web search / web extract，可从 tavily 官网免费申请 API key 并配置：

```bash
TAVILY_API_KEY=
```

如果需要 MCP，在全局用户目录创建：

```text
~/.lulu/mcp.json
```

示例：

```json
{
  "mcpServers": {
    "demo": {
      "command": "python",
      "args": ["path/to/server.py"],
      "env": {},
      "timeout": 30
    }
  }
}
```

## 启动 GUI

推荐使用：

```bash
./lulu.sh
```

Windows 可使用：

```bat
.\lulu.bat
```

默认起始地址：

- 后端：`http://127.0.0.1:8000`
- GUI：`http://127.0.0.1:5173`

`lulu.sh` / `lulu.bat` 会同时启动后端和 GUI，等待后端 `/health` 与前端页面可用后再打开浏览器。按 `Ctrl+C` 会停止两个进程。

启动脚本使用当前运行环境 (推荐使用 conda/uv/nvm) 中的 `python` / `python.exe` 和 `npm` / `npm.cmd`。如果默认端口已被占用，会自动尝试后续端口。启动脚本所在 shell 的当前目录是新会话的默认 workspace；GUI 创建会话时也可以浏览并选择其他目录。

## 使用 CLI

启动：

```bash
python -m cli.main
```

退出：

```text
/exit
/quit
```

恢复会话：

```bash
python -m cli.main --resume <session_id>
```

列出近期会话：

```bash
python -m cli.main --list-sessions
```

查看会话信息：

```bash
python -m cli.main --inspect-session <session_id>
```

查看拼接后的 system/context：

```bash
python -m cli.main --inspect-context <session_id>
```

## 本地数据

运行数据统一保存在用户目录 `~/.lulu/`：

```text
~/.lulu/
  sessions/
  traces/
  memory/MEMORY.md
  skills/<name>/SKILL.md
  models.json
  mcp.json
```

`sessions/` 保存会话历史和任务状态，`traces/` 保存运行过程。删除 session 时，对应的 trace 也会一起删除。每个 session 都会记住创建时选择的 workspace；恢复会话后，文件读写、文本搜索、Shell 命令和项目指导文件都会继续以该目录为准。

如果绑定的 workspace 被移动、删除或当前不可访问，session 会进入锁定状态，避免后续操作意外落到其他目录。此时可以检查文件系统后点击 `Recheck`，也可以显式删除 session。恢复原路径后重新检查即可解锁；workspace 失效不会自动删除会话和 trace 数据。

旧版本保存在项目目录 `.lulu/sessions` / `.lulu/traces` 的数据不会自动迁移到 `~/.lulu/`。升级前如需保留这些数据，请先备份原目录。

## Memory

Memory 用来保存跨会话的长期事实、偏好和经验。

默认路径：

```text
~/.lulu/memory/MEMORY.md
```

使用方式：

- 你可以直接告诉 agent 需要记住、更新或忘记某条长期信息。
- Memory 会在后续对话中作为上下文提供给模型。
- Memory 不等于聊天记录，不适合保存临时任务状态或完整对话。
- 后台 memory review 会周期性检查最近对话和现有 memory，结果写入 Trace，不进入聊天记录。

## Skills

Skill 用来保存可复用的操作流程或工作方法。

默认路径：

```text
~/.lulu/skills/<name>/SKILL.md
```

使用方式：

- agent 可以按需查看已有 skill。
- 你可以要求 agent 创建或修改某个 skill。
- 运行 `python setup/lulu_setup.py` 会将内置 skill 安装到全局 skills 目录；已有同名 skill 不会被覆盖。
- 后台 skill review 会周期性检查最近对话是否沉淀出可复用流程，结果写入 Trace，不进入聊天记录。

## MCP

MCP 用来接入外部工具。当前支持 stdio MCP server。

配置路径：

```text
~/.lulu/mcp.json
```

启动 session 时，lulu-agent 会连接配置中的 MCP server 并加载可用工具。可以在 GUI 的 MCP 面板查看加载结果；修改配置或连接异常时，可以针对当前 session 重新加载。

## Trace

GUI 的 Trace 面板按 turn 展示运行过程，包括模型请求、retry、工具调用、工具结果、turn 结束状态，以及后台 knowledge review 的 `review_summary`。发生过 review 的 turn 会有 `reviewed`、`review updated` 或 `review failed` 标识。

## 注意事项

- 当前安全边界是本地 soft workspace safety，不是完整 OS sandbox。
- Shell 工具会拒绝明显高风险命令，并对部分文件变更命令请求确认。
- Web search / extract 需要 `TAVILY_API_KEY`。
- 当前 MCP 仅支持 stdio transport。
- 当前按本地单用户工具设计，不适合直接作为多用户或公网服务部署。
