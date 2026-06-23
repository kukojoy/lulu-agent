# lulu-agent

`lulu-agent` is a minimal local coding agent core.

It is intentionally small: the goal is not to copy a full agent platform, but
to keep the core loop, context handling, LLM client, and native tool runtime
easy to read and extend.

## Current Capabilities

- Runs from a local CLI.
- Calls an OpenAI-compatible chat completion endpoint.
- Persists CLI session transcripts under `.lulu/sessions`.
- Supports creating, resuming, listing, and inspecting local sessions.
- Sends a bounded context window to the model through `ContextManager`.
- Supports OpenAI-compatible tool calls.
- Returns structured tool results through `ToolResult`.
- Provides native tools for basic coding workflows:
  - `list_files`
  - `read_file`
  - `write_file`
  - `replace_in_file`
  - `run_shell`
- Handles missing config and LLM request failures with readable CLI errors.
- Rejects a small set of risky shell commands.
- Truncates large shell output before sending it back to the model.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env` file:

```bash
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
```

The model endpoint must be OpenAI-compatible and support tool calling.

## Run

```bash
python -m lulu_agent.main
```

Exit with:

```text
/exit
```

or:

```text
/quit
```

The CLI enables basic line editing through Python `readline` when available,
so normal terminal editing keys should work in supported environments.

## Sessions

By default, each CLI run creates a new persistent session under:

```text
.lulu/sessions/
```

The CLI prints the session id at startup:

```text
Session id: session-YYYYMMDD-HHMMSS-XXXXXXXX
```

Resume a previous session:

```bash
python -m lulu_agent.main --resume <session_id>
```

List recent sessions:

```bash
python -m lulu_agent.main --list-sessions
```

Inspect one session without printing the full transcript:

```bash
python -m lulu_agent.main --inspect-session <session_id>
```

Session transcripts are append-only JSONL files. The index is stored in
`.lulu/sessions/sessions_index.jsonl`. The `.lulu/` directory is local runtime
state and should not be committed.

## Typical Workflow

A minimal coding task usually follows this shape:

```text
list_files -> read_file -> replace_in_file -> run_shell
```

Example tool responsibilities:

- Use `list_files` to inspect directories.
- Use `read_file` to inspect file contents.
- Use `write_file` to create or fully overwrite a file.
- Use `replace_in_file` for small exact text edits.
- Use `run_shell` to run tests, inspect git state, or verify filesystem state.

## Native Tools

### `list_files`

Lists files and directories at a path.

Key behavior:

- Resolves the target path to an absolute path.
- Defaults to the current directory.
- Defaults to one directory level only.
- Can recursively list entries with `recursive=true`.
- Hides dotfiles by default.
- Returns structured entries with name, path, type, and file size.
- Limits output with `max_entries` and reports whether results were truncated.

### `read_file`

Reads a text file.

Key behavior:

- Resolves the file path to an absolute path.
- Returns `{path, content}` on success.
- Returns structured errors for missing files or directory paths.

### `write_file`

Writes text content to a file.

Key behavior:

- Resolves the file path to an absolute path.
- Creates parent directories when needed.
- Overwrites the whole file.
- Returns `{path, content_length}` on success.

### `replace_in_file`

Performs exact text replacement in one file.

Key behavior:

- Resolves the file path to an absolute path.
- Requires `old_string` and `new_string`.
- Fails if `old_string` is empty.
- Fails if `old_string` and `new_string` are identical.
- Defaults to replacing one unique match only.
- Fails on multiple matches unless `replace_all=true`.
- Returns `{path, replacements, content_length}` on success.

### `run_shell`

Runs a local shell command.

Key behavior:

- Returns structured `stdout`, `stderr`, `exit_code`, and `cwd`.
- Truncates large output.
- Rejects obvious risky patterns such as recursive forced delete and `sudo`.
- The model is prompted to verify shell-based file operations with `ls`,
  `test`, or `find` when needed.

## Architecture

```text
lulu_agent/
  main.py                 # CLI entry point
  cli_input.py            # CLI line editing wrapper
  agent_loop.py           # Conversation loop and tool-call cycle
  context_manager.py      # Bounded request context selection
  llm_client.py           # OpenAI-compatible client wrapper
  config.py               # Environment-based config loading and validation
  session_store.py        # JSONL session persistence
  tools.py                # ToolResult, Tool, ToolRegistry, schema validation
  native_tools/
    list_files.py
    read_file.py
    write_file.py
    replace_in_file.py
    run_shell.py
```

### Module Boundaries

- `main.py` owns CLI interaction and user-visible errors.
- `AgentLoop` owns message ordering, model calls, tool dispatch, and tool result
  insertion.
- `ContextManager` owns the request context shape sent to the model.
- `LLMClient` owns OpenAI-compatible API calls and wraps request failures.
- `SessionStore` owns JSONL transcript persistence and session metadata.
- `ToolRegistry` owns tool registration, schemas, basic argument validation,
  and dispatch.
- Native tools own their domain behavior and return `ToolResult`.

These boundaries are deliberately narrow so future production-grade work can
extend the system without moving every concern into the agent loop.

## Verification

Syntax check:

```bash
conda run -n lulu-agent python -m py_compile lulu_agent/*.py lulu_agent/native_tools/*.py
```

Tests:

```bash
conda run -n lulu-agent python -m pytest
```

The test suite does not require real API credentials or network calls.

## v1.0 Scope

`lulu-agent v1.0` is a minimal agent core, not a full production platform.

Included:

- Local CLI.
- OpenAI-compatible model client.
- Persistent local sessions and resume.
- Simple context window bounding.
- Minimal native coding toolset.
- Structured tool results.
- Focused tests for config, LLM client behavior, tool runtime, and message flow.

Not included:

- Persistent memory.
- LLM-based context compression.
- Approval system.
- Sandbox or container execution.
- MCP, plugins, skills, or subagents.
- Multi-provider routing.
- Streaming output.
- TUI, browser automation, gateway, or cron.

## Future Direction

The current code is meant to be a clean base for future production-grade work.
Likely extension points:

- Replace `ContextManager` with token budgeting, summarization, or memory
  injection.
- Extend `ToolRegistry` to load plugin or MCP tools.
- Upgrade shell safety from refusal rules to approval and sandbox policies.
- Add persistent sessions and resume support.
- Add streaming model responses.
- Add a richer CLI or TUI.

Those are intentionally outside `v1.0`.
