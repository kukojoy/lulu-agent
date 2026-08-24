from __future__ import annotations

from typing import Any

from lulu_agent.runtime.errors import (
    ERROR_INVALID_ARGUMENTS,
    ERROR_NOT_FOUND,
    ERROR_SESSION_NOT_FOUND,
    ERROR_SESSION_WORKSPACE_UNAVAILABLE,
    LuluError,
)


def not_found_error(exc: Exception) -> Exception:
    return _http_exception(404, str(exc))


def bad_request_error(exc: Exception) -> Exception:
    return _http_exception(400, str(exc))


def internal_error(exc: Exception) -> Exception:
    return _http_exception(500, str(exc))


def conflict_error(exc: Exception) -> Exception:
    return _http_exception(
        409,
        _error_detail(exc),
    )


def session_error(exc: Exception) -> Exception:
    if isinstance(exc, LuluError):
        if exc.error_type == ERROR_SESSION_WORKSPACE_UNAVAILABLE:
            return _http_exception(409, _error_detail(exc))
        if exc.error_type == ERROR_INVALID_ARGUMENTS:
            return _http_exception(400, _error_detail(exc))
        if exc.error_type in {ERROR_NOT_FOUND, ERROR_SESSION_NOT_FOUND}:
            return _http_exception(404, _error_detail(exc))
        return _http_exception(500, _error_detail(exc))
    return internal_error(exc)


def skill_not_found_error(exc: Exception) -> Exception:
    return _http_exception(404, getattr(exc, "error_message", str(exc)))


def _error_detail(exc: Exception) -> dict[str, str]:
    if isinstance(exc, LuluError):
        return {
            "message": exc.error_message,
            "code": exc.error_type.value,
        }
    return {"message": str(exc), "code": "execution_error"}


def _http_exception(status_code: int, detail: Any) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=status_code, detail=detail)
