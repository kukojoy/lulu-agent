# lulu-agent

`lulu-agent` 是一个本地 agent runtime 原型。

它的目标不是复制完整 agent 平台，而是在保持代码足够小、足够容易推理的前提下，逐步搭建一个能继续演进到生产级 agent 的基础架构。

当前状态：`v2.0 completed`。

## 当前能力

- 本地 CLI 交互。
- OpenAI-compatible chat completion 调用。
- assistant delta 流式输出。
- OpenAI-compatible tool calling。
- `.lulu/sessions` 本地 session 持久化。
- session 创建、resume、list、inspect。
- `ContextManager` 构造本轮 api context，并将 raw transcript 与 api messages 分离。
- `MEMORY.md` 本地长期记忆。
- `.lulu/skills/<name>/SKILL.md` 本地 skills。
- `.lulu/mcp.json` stdio MCP server discovery、tool 注册和调用。
- runtime events 和 event sinks。
- `ToolResult` 结构化工具结果。
- native coding tools：
  - `list_files`
  - `read_file`
  - `write_file`
  - `replace_in_file`
  - `run_shell`
  - `memory`
  - `skill`
- soft workspace safety boundary。
- shell command 风险拒绝和最小 CLI approval。
- 大型 shell 输出截断。
- 配置错误和 LLM 请求错误的 CLI 友好提示。

## 安装

安装依赖：

```bash
pip install -r requirements.txt
```

创建本地 `.env`：

```bash
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
```

模型服务需要兼容 OpenAI chat completion，并支持 tool calling。要使用 MCP，需要安装 `mcp` 相关依赖，并在工作目录配置 `.lulu/mcp.json`。

## 运行

```bash
python -m lulu_agent.main
```

退出：

```text
/exit
/quit
```

CLI 会在可用环境中启用 Python `readline`，支持常见终端输入编辑能力。

## Sessions

每次 CLI 启动默认创建一个本地 session：

```text
.lulu/sessions/
```

启动时会打印 session id：

```text
Session id: session-YYYYMMDD-HHMMSS-XXXXXXXX
```

恢复历史 session：

```bash
python -m lulu_agent.main --resume <session_id>
```

列出近期 sessions：

```bash
python -m lulu_agent.main --list-sessions
```

查看 session metadata：

```bash
python -m lulu_agent.main --inspect-session <session_id>
```

session transcript 使用 append-only JSONL。session index 存在 `.lulu/sessions/sessions_index.jsonl`。`.lulu/` 是本地运行状态，不应提交。

## Memory

长期记忆存储在工作目录下：

```text
MEMORY.md
```

关键行为：

- 每轮模型调用前，`MEMORY.md` 会作为 context block 注入。
- memory context block 不会写入 raw session transcript。
- `memory` 工具支持 `read`、`add`、`replace`、`remove`。
- `replace` 和 `remove` 通过唯一 `old_text` 子串定位整条记忆项。
- 当前不做自动总结、embedding 检索、后台 review 或外部 provider sync。

## Skills

本地 skills 存储在：

```text
.lulu/skills/<name>/SKILL.md
```

关键行为：

- 每个 skill 一个子目录。
- `SKILL.md` 使用 frontmatter 声明 `name` 和 `description`。
- skill metadata 会进入 context block。
- 完整 skill 正文不会自动注入，需要模型通过 `skill read` 按需读取。
- 当前只支持工作目录级 skills，不支持全局安装、下载器或 marketplace。

## MCP

MCP 配置文件位于：

```text
.lulu/mcp.json
```

当前支持：

- stdio MCP server。
- 启动本地 stdio MCP 进程并进行 tool discovery。
- 将 MCP tool 适配成本地 `Tool` 后注册进 `ToolRegistry`。
- 调用 MCP tool 并返回 `ToolResult`。

当前不支持：

- HTTP/SSE MCP transport。
- OAuth。
- 长生命周期 MCP session pool。
- MCP tool marketplace 或自动安装。

## Native Tools

### `list_files`

列出文件和目录。

关键行为：

- 解析为绝对路径。
- 默认当前目录。
- 默认只列一层。
- 可通过 `recursive=true` 递归列出。
- 默认隐藏 dotfiles。
- 返回 name、path、type、size。
- 支持 `max_entries` 截断并返回 `truncated`。

### `read_file`

读取文本文件。

关键行为：

- 解析为绝对路径。
- 成功返回 `{path, content}`。
- 对文件不存在、目录路径等情况返回结构化错误。

### `write_file`

写入文本文件。

关键行为：

- 解析为绝对路径。
- 自动创建父目录。
- 覆盖整个文件。
- 成功返回 `{path, content_length}`。

### `replace_in_file`

对单个文件执行精确文本替换。

关键行为：

- 解析为绝对路径。
- 要求 `old_string` 和 `new_string`。
- `old_string` 不能为空。
- `old_string` 和 `new_string` 不能相同。
- 默认要求唯一匹配。
- 多处匹配时需要 `replace_all=true`。
- 成功返回 `{path, replacements, content_length}`。

### `run_shell`

运行本地 shell 命令。

关键行为：

- 返回结构化 `stdout`、`stderr`、`exit_code`、`cwd`。
- 截断大型输出。
- 拒绝明显高风险命令，例如 recursive forced delete 和 `sudo`。
- 对部分文件变更命令触发一次性 CLI approval，例如 `rm`、`mv`、`chmod`、`chown`。
- system prompt 会要求模型在必要时用 `ls`、`test`、`find` 验证 shell 文件操作结果。
- 当前安全边界是 soft workspace，不是 OS sandbox。

## 代码结构

```text
lulu_agent/
  config.py               # 环境变量配置
  main.py                 # CLI 入口

  core/
    agent_loop.py         # turn lifecycle、消息顺序、模型调用、工具调用
    assistant_response.py # streaming chunk 聚合
    context_manager.py    # api_messages 构造和 context blocks 注入

  llm/
    client.py             # OpenAI-compatible client

  runtime/
    approval.py           # 最小 CLI approval
    cli_input.py          # readline 输入封装
    event_sinks.py        # CLI / recording / noop event sink
    events.py             # runtime event 契约
    safety.py             # 路径和 shell 安全策略

  mcp/
    adapter.py            # MCP tool 适配
    client.py             # stdio MCP client
    config.py             # .lulu/mcp.json 加载
    registry.py           # MCP tool 注册入口

  skills/
    loader.py             # .lulu/skills 加载

  storage/
    memory_store.py       # MEMORY.md
    session_store.py      # .lulu/sessions JSONL

  tools/
    registry.py           # ToolResult、Tool、ToolRegistry、decorator
    native/
      list_files.py
      memory.py
      read_file.py
      replace_in_file.py
      run_shell.py
      skill.py
      write_file.py
```

## 模块边界

- `main.py` 负责 CLI interaction、session CLI 参数和用户可见错误。
- `core/agent_loop.py` 负责 turn lifecycle、message ordering、model call、tool dispatch 和 tool result insertion。
- `core/context_manager.py` 负责本轮 request context 的形状。
- `core/assistant_response.py` 负责 streaming chunk 聚合，避免 AgentLoop 直接绑定 SDK chunk 结构。
- `llm/client.py` 负责 OpenAI-compatible API 调用和错误包装。
- `runtime/` 负责 events、approval、CLI input 和 safety。
- `storage/` 负责 session 与 memory 的本地持久化。
- `skills/` 负责本地 skill metadata 和正文加载。
- `mcp/` 负责 MCP 配置、discovery、tool 适配和注册。
- `tools/registry.py` 负责 tool schema、注册、查询、参数校验和 dispatch。
- native tools 负责自己的领域行为，并返回 `ToolResult`。

这些边界刻意保持较窄，方便后续向生产级 agent 演进时继续扩展，而不是把所有能力堆进 AgentLoop。

## 验证

语法检查：

```bash
conda run -n lulu-agent python -m py_compile lulu_agent/*.py lulu_agent/core/*.py lulu_agent/runtime/*.py lulu_agent/mcp/*.py lulu_agent/storage/*.py lulu_agent/skills/*.py lulu_agent/tools/*.py lulu_agent/tools/native/*.py lulu_agent/llm/*.py
```

全量测试：

```bash
conda run -n lulu-agent python -m pytest -q
```

测试不需要真实 API credentials 或网络调用。

## v2.0 Scope

`lulu-agent v2.0` 是 runtime foundation，不是完整生产级平台。

已包含：

- CLI。
- OpenAI-compatible model client。
- Persistent local sessions。
- Context pipeline。
- Durable local memory。
- Local workspace skills。
- stdio MCP tools。
- Runtime events。
- CLI streaming。
- Native coding toolset。
- Soft workspace safety。
- Minimal CLI approval。
- Focused tests for config、LLM client、tool runtime、message flow、session、context、memory、skills、MCP 和 runtime events。

未包含：

- HTTP/SSE server endpoint。
- Web UI / TUI / gateway。
- Provider router。
- Subagents。
- Browser automation。
- OS 级 sandbox。
- 复杂 session search。
- 自动 memory review。
- LLM-based context compression。
- Marketplace 级 plugin / skill installer。
- 生产级 observability 平台。

## 后续方向

后续目标是从 v2.0 runtime foundation 走向 v3.0 production-oriented runtime。优先方向：

- Runtime control：中断、取消、turn state、错误恢复。
- Observability / audit：event log、tool audit、approval trace、run replay。
- Context engineering：token budget、summary、tool pair 保护、检索入口。
- Provider runtime：provider protocol、capability detection、retry、timeout、rate limit。
- Safety hardening：policy profiles、approval record、OS sandbox adapter 边界。
- Tool / MCP hardening：timeout、统一截断、MCP lifecycle、HTTP/SSE MCP transport 评估。
- Product surface：在 runtime 稳定后再选择 CLI 增强、TUI、HTTP/SSE server 或 gateway。
