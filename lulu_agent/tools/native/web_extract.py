import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from lulu_agent.tools import ToolResult, tool
from lulu_agent.runtime.errors import ERROR_EXTERNAL_TOOL, ERROR_INVALID_ARGUMENTS, ERROR_TIMEOUT


DEFAULT_EXTRACT_LIMIT = 8000
MAX_EXTRACT_LIMIT = 30000
WEB_EXTRACT_TIMEOUT_SECONDS = 10


@tool(
    name="web_extract",
    description=(
        "Extract readable text from one HTTP/HTTPS URL. Use after web_search to verify exact "
        "dates, scores, policies, prices, or other source-sensitive facts from a trusted result. "
        "If extraction fails, search for another trusted source for the same fact rather than "
        "switching to background information."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL to extract.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of text characters to return. Defaults to 8000, max 30000.",
            },
        },
        "required": ["url"],
    },
)
def web_extract(args):
    url = args["url"].strip()
    if not url:
        return ToolResult(ok=False, error="url must not be empty.", error_type=ERROR_INVALID_ARGUMENTS)

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ToolResult(
            ok=False,
            error="url must be an absolute http or https URL.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )

    limit = args.get("limit", DEFAULT_EXTRACT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return ToolResult(
            ok=False,
            error="limit must be an integer greater than or equal to 1.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )
    limit = min(limit, MAX_EXTRACT_LIMIT)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "lulu-agent/0.1",
            "Accept": "text/html,text/plain,application/xhtml+xml",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=WEB_EXTRACT_TIMEOUT_SECONDS) as response:
            content_type = _response_header(response, "Content-Type").lower()
            body = response.read()
            final_url = getattr(response, "url", url)
    except TimeoutError:
        return ToolResult(
            ok=False,
            error=f"Web extract timed out after {WEB_EXTRACT_TIMEOUT_SECONDS} seconds.",
            error_type=ERROR_TIMEOUT,
            metadata={"url": url},
        )
    except urllib.error.HTTPError as exc:
        return ToolResult(
            ok=False,
            error=f"Web extract request failed with HTTP {exc.code}.",
            error_type=ERROR_EXTERNAL_TOOL,
            metadata={"url": url, "status": exc.code},
        )
    except urllib.error.URLError as exc:
        return ToolResult(
            ok=False,
            error=f"Web extract request failed: {exc.reason}",
            error_type=ERROR_EXTERNAL_TOOL,
            metadata={"url": url},
        )
    except OSError as exc:
        return ToolResult(
            ok=False,
            error=f"Failed to read web extract response: {exc}",
            error_type=ERROR_EXTERNAL_TOOL,
            metadata={"url": url},
        )

    if content_type and not _is_text_content_type(content_type):
        return ToolResult(
            ok=False,
            error=f"Unsupported content type: {content_type}",
            error_type=ERROR_EXTERNAL_TOOL,
            metadata={"url": url, "content_type": content_type},
        )

    text = body.decode(_charset_from_content_type(content_type), errors="replace")
    if "html" in content_type or _looks_like_html(text):
        title, content = _extract_html_text(text)
    else:
        title, content = "", _normalize_text(text)

    original_length = len(content)
    truncated = original_length > limit
    output = {
        "url": final_url,
        "title": title,
        "content": content[:limit] if truncated else content,
        "content_type": content_type or "unknown",
        "truncated": truncated,
        "original_length": original_length,
    }
    if truncated:
        output["hint"] = "Increase limit to retrieve more extracted text."

    return ToolResult(
        ok=True,
        output=output,
        metadata={
            "url": final_url,
            "content_type": content_type or "unknown",
            "original_length": original_length,
            "limit": limit,
        },
        truncated=truncated,
    )


def _response_header(response, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        value = headers.get(name)
        return value if isinstance(value, str) else ""

    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        value = getheader(name)
        return value if isinstance(value, str) else ""
    return ""


def _is_text_content_type(content_type: str) -> bool:
    return (
        content_type.startswith("text/")
        or "html" in content_type
        or "json" in content_type
        or "xml" in content_type
    )


def _charset_from_content_type(content_type: str) -> str:
    for part in content_type.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() == "charset" and value.strip():
            return value.strip()
    return "utf-8"


def _looks_like_html(text: str) -> bool:
    prefix = text[:500].lower()
    return "<html" in prefix or "<body" in prefix or "<!doctype html" in prefix


def _extract_html_text(html: str) -> tuple[str, str]:
    parser = _ReadableHTMLParser()
    parser.feed(html)
    return parser.title, _normalize_text(" ".join(parser.text_parts))


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript", "svg", "nav"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg", "nav"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            self.title = _normalize_text(" ".join(self._title_parts))

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        if data.strip():
            self.text_parts.append(data.strip())
