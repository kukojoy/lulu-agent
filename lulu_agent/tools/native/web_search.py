import json
import os
import urllib.error
import urllib.request

from lulu_agent.tools import ToolResult, tool, truncate_text
from lulu_agent.runtime.errors import ERROR_EXTERNAL_TOOL, ERROR_INVALID_ARGUMENTS, ERROR_TIMEOUT, ErrorType

from lulu_agent.config import config

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_WEB_SEARCH_COUNT = 5
MAX_WEB_SEARCH_COUNT = 10
WEB_SEARCH_TIMEOUT_SECONDS = 10
MAX_SNIPPET_CHARS = 1000


@tool(
    name="web_search",
    description=(
        "Search the web with Tavily and return candidate sources. For current or recent facts, "
        "include the relevant date/year, entity, and fact type in the query; snippets are leads, "
        "not final evidence. For event status, prefer queries for results/status/finished/latest "
        "over background or schedule-only queries."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "count": {
                "type": "integer",
                "description": "Maximum number of results to return. Defaults to 5, max 10.",
            },
        },
        "required": ["query"],
    },
)
def web_search(args):
    query = args["query"].strip()
    if not query:
        return ToolResult(ok=False, error="query must not be empty.", error_type=ERROR_INVALID_ARGUMENTS)

    count = args.get("count", DEFAULT_WEB_SEARCH_COUNT)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return ToolResult(
            ok=False,
            error="count must be an integer greater than or equal to 1.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )

    count = min(count, MAX_WEB_SEARCH_COUNT)
    api_key = config.tavily_api_key or os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return _search_error("Missing required environment variable: TAVILY_API_KEY", query)

    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=json.dumps(
            {
                "query": query,
                "search_depth": "basic",
                "max_results": count,
                "topic": "general",
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
            }
        ).encode("utf-8"),
        headers={
            "User-Agent": "lulu-agent/0.1",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=WEB_SEARCH_TIMEOUT_SECONDS) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except TimeoutError:
        return _search_error(
            f"Web search timed out after {WEB_SEARCH_TIMEOUT_SECONDS} seconds.",
            query,
            error_type=ERROR_TIMEOUT,
        )
    except urllib.error.HTTPError as exc:
        return _search_error(
            f"Tavily search request failed with HTTP {exc.code}.{_read_error_detail(exc)}",
            query,
            metadata={"status": exc.code},
        )
    except urllib.error.URLError as exc:
        return _search_error(f"Tavily search request failed: {exc.reason}", query)
    except OSError as exc:
        return _search_error(f"Failed to read Tavily search response: {exc}", query)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        return _search_error(f"Failed to parse Tavily search response: {exc}", query)

    raw_results = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(raw_results, list):
        raw_results = []

    results = []
    for item in raw_results[:count]:
        if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
            continue
        results.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": truncate_text(str(item.get("content") or ""), MAX_SNIPPET_CHARS),
            }
        )

    return ToolResult(
        ok=True,
        output={
            "provider": "tavily",
            "query": query,
            "results": results,
            "returned_count": len(results),
            "more_results_available": len(raw_results) > count,
        },
        metadata={"provider": "tavily", "query": query, "returned_count": len(results)},
    )


def _search_error(
    error: str,
    query: str,
    *,
    error_type: ErrorType = ERROR_EXTERNAL_TOOL,
    metadata: dict[str, object] | None = None,
) -> ToolResult:
    return ToolResult(
        ok=False,
        error=error,
        error_type=error_type,
        metadata={"provider": "tavily", "query": query, **(metadata or {})},
    )


def _read_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    return f" {truncate_text(body, 500)['text']}" if body else ""
