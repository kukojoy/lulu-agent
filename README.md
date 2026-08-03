# lulu-agent

`lulu-agent` 是一个本地运行的通用 agent。它提供 Web GUI 和 CLI 两种入口，可以在本机完成对话、调用工具、读写文件、执行命令、维护长期记忆和复用技能。

当前状态：`v3.2 completed`。

## 主要能力

- 本地 Web GUI，支持会话列表、聊天、工具调用展示、任务状态、Memory 和 Skills 查看。
- CLI 入口，支持会话恢复、会话查看和 context inspect。
- OpenAI-compatible 模型服务，支持 streaming 和 tool calling。
- 本地 session 持久化，可以恢复历史会话。
- 本地文件工具：列文件、读文件、写文件、替换文件、全文搜索。
- Shell 工具：执行本地命令，并对高风险命令做安全拦截或确认。
- Web 工具：通过 Tavily 进行搜索和网页内容提取。
- 长期记忆：将跨会话事实和偏好保存到全局 memory。
- Skills：将可复用流程沉淀为全局 skill，并在需要时读取。
- MCP：从全局 MCP 配置加载外部 stdio MCP 工具。

## 安装

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

如果使用 Web GUI，还需要安装 GUI 依赖：

```bash
cd gui
npm install
```

## 配置

在仓库根目录创建 `.env`：

```bash
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
```

模型服务需要兼容 OpenAI chat completion，并支持 tool calling。

如果需要 web search / web extract，配置：

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

默认地址：

- 后端：`http://127.0.0.1:8000`
- GUI：`http://127.0.0.1:5173`

`lulu.sh` 会同时启动后端和 GUI，并在可用环境中自动打开浏览器。按 `Ctrl+C` 会停止两个进程。

可选环境变量：

```bash
LULU_BACKEND_HOST=127.0.0.1
LULU_BACKEND_PORT=8000
LULU_FRONTEND_PORT=5173
LULU_CONDA_ENV=lulu-agent
LULU_PYTHON=/path/to/python
```

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

项目工作目录下的 `.lulu/` 保存当前项目的运行状态：

```text
.lulu/
  sessions/
  traces/
```

跨项目长期数据保存在用户目录：

```text
~/.lulu/
  memory/MEMORY.md
  skills/<name>/SKILL.md
  mcp.json
```

`.lulu/` 是本地运行状态，不应提交到 Git。

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

## Skills

Skill 用来保存可复用的操作流程或工作方法。

默认路径：

```text
~/.lulu/skills/<name>/SKILL.md
```

使用方式：

- agent 可以按需查看已有 skill。
- 你可以要求 agent 创建或修改某个 skill。
- 内置 skill 会在启动时安装到全局 skills 目录；已有同名 skill 不会被覆盖。

## MCP

MCP 用来接入外部工具。当前支持 stdio MCP server。

配置路径：

```text
~/.lulu/mcp.json
```

启动时 lulu-agent 会读取该配置，发现 MCP tools，并把它们注册为可调用工具。

## 注意事项

- 当前安全边界是本地 soft workspace safety，不是完整 OS sandbox。
- Shell 工具会拒绝明显高风险命令，并对部分文件变更命令请求确认。
- Web search / extract 需要 `TAVILY_API_KEY`。
- 当前 MCP 仅支持 stdio transport。
- lulu-agent 仍不是完整生产级平台；更强的中断恢复、工具治理、安全隔离、模型运行层和知识质量控制仍是后续方向。
