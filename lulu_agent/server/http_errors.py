from __future__ import annotations

from typing import Any


def not_found_error(exc: Exception) -> Exception:
    return _http_exception(404, str(exc))


def bad_request_error(exc: Exception) -> Exception:
    return _http_exception(400, str(exc))


def internal_error(exc: Exception) -> Exception:
    return _http_exception(500, str(exc))


def conflict_error(exc: Exception) -> Exception:
    return _http_exception(
        409,
        {
            "message": str(exc),
            "code": getattr(exc, "code", "server_error"),
        },
    )


def skill_not_found_error(exc: Exception) -> Exception:
    return _http_exception(404, getattr(exc, "error_message", str(exc)))


def _http_exception(status_code: int, detail: Any) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=status_code, detail=detail)
