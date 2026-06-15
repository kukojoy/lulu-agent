# lulu-agent

`lulu-agent` is a minimal local agent prototype.

Current capabilities:

- Call an OpenAI-compatible LLM
- Run a simple agent loop with tool calling
- Use three native tools:
  - `read_file`
  - `write_file`
  - `run_shell`
- Run from a basic CLI

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `.env` from `.env.example` and fill in:

```bash
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
```

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

## Status

This is still stage 1. The code is intentionally small and will change a lot.

