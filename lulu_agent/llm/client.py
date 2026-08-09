import time

from openai import OpenAI

from lulu_agent.config import ConfigError
from lulu_agent.llm.response import (
    LLMClientConfig,
    ModelRequest,
    ModelResponse,
    StreamingAssistantResponseBuilder,
)
from lulu_agent.runtime.errors import (
    ERROR_EXTERNAL_MODEL,
    ERROR_MODEL_AUTHENTICATION,
    ERROR_MODEL_BAD_REQUEST,
    ERROR_MODEL_CONNECTION,
    ERROR_MODEL_CONTEXT_LENGTH,
    ERROR_MODEL_RATE_LIMIT,
    ERROR_MODEL_TIMEOUT,
    ErrorType,
    LuluError,
)
from lulu_agent.llm.usage import extract_usage


class LLMClientError(LuluError):
    def __init__(
        self,
        error_message: str,
        error_type: ErrorType = ERROR_EXTERNAL_MODEL,
        retryable: bool | None = None,
    ):
        super().__init__(error_message=error_message, error_type=error_type)
        self.retryable = retryable


class LLMClient:
    def __init__(self, config: LLMClientConfig):
        _validate_client_config(config)
        self.config = config
        self.provider = config.provider
        self.base_url = config.base_url
        self.model = config.model
        self.timeout_seconds = config.timeout_seconds
        self.max_retries = config.max_retries
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def chat(self, messages, tools=None):
        return self._create_chat_completion(messages=messages, tools=tools, stream=False)

    def stream_chat(self, messages, tools=None):
        stream = self._create_chat_completion(messages=messages, tools=tools, stream=True)
        return self._wrap_stream(stream)

    def get_model_config(self) -> LLMClientConfig:
        return self.config

    def complete(self, request: ModelRequest, on_delta=None, on_retry=None) -> ModelResponse:
        attempts = self.max_retries + 1
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return self._complete_once(request, on_delta=on_delta)
            except LLMClientError as exc:
                last_error = exc
                if not _is_retryable_model_error(exc) or attempt >= attempts:
                    raise
                delay_seconds = _retry_delay_seconds(attempt)
                if on_retry:
                    on_retry(
                        {
                            "attempt": attempt,
                            "max_retries": self.max_retries,
                            "delay_seconds": delay_seconds,
                            "error_type": exc.error_type,
                            "error_message": exc.error_message,
                        }
                    )
                time.sleep(delay_seconds)
        raise last_error

    def _complete_once(self, request: ModelRequest, on_delta=None) -> ModelResponse:
        if request.stream:
            stream_response = self.stream_chat(messages=request.messages, tools=request.tools)
            builder = StreamingAssistantResponseBuilder()
            try:
                for content_delta in builder.consume(stream_response):
                    if on_delta:
                        on_delta(content_delta)
                return builder.build()
            except LLMClientError as exc:
                if builder.streamed:
                    exc.retryable = False
                raise

        response = self.chat(messages=request.messages, tools=request.tools)
        return ModelResponse(
            message=response.choices[0].message,
            streamed=False,
            usage=extract_usage(response),
        )

    def _create_chat_completion(self, messages, tools=None, stream=False):
        kwargs = {
            "model": self.model,
            "messages": messages
        }
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}   
        if tools:
            kwargs["tools"] = tools

        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise self._model_error(exc) from exc

    def _model_error(self, exc: Exception) -> LLMClientError:
        exc_name = type(exc).__name__
        error_type = _classify_error_type(exc)
        return LLMClientError(
            error_message=(
                f"LLM request failed for model '{self.model}' at '{self.base_url}': "
                f"{exc_name}: {_safe_exception_message(exc)}"
            ),
            error_type=error_type,
        )

    def _wrap_stream(self, stream):
        try:
            for chunk in stream:
                yield chunk
        except LLMClientError:
            raise
        except Exception as exc:
            raise self._model_error(exc) from exc


def _classify_error_type(exc: Exception) -> ErrorType:
    if isinstance(exc, TimeoutError) or _is_exc_type(exc, "APITimeoutError"):
        return ERROR_MODEL_TIMEOUT
    if _is_exc_type(exc, "AuthenticationError", "PermissionDeniedError"):
        return ERROR_MODEL_AUTHENTICATION
    if _is_exc_type(exc, "RateLimitError"):
        return ERROR_MODEL_RATE_LIMIT
    if _is_exc_type(exc, "BadRequestError", "NotFoundError", "UnprocessableEntityError"):
        if _is_context_length_error(exc):
            return ERROR_MODEL_CONTEXT_LENGTH
        return ERROR_MODEL_BAD_REQUEST
    if _is_exc_type(exc, "APIConnectionError"):
        return ERROR_MODEL_CONNECTION
    if _is_exc_type(exc, "APIStatusError", "ConflictError", "InternalServerError"):
        return _classify_status_error(exc)
    return ERROR_EXTERNAL_MODEL


def _is_retryable_model_error(exc: LLMClientError) -> bool:
    if exc.retryable is not None:
        return exc.retryable
    return exc.error_type in {
        ERROR_MODEL_TIMEOUT,
        ERROR_MODEL_CONNECTION,
        ERROR_MODEL_RATE_LIMIT,
        ERROR_EXTERNAL_MODEL,
    }


def _retry_delay_seconds(attempt: int) -> float:
    return 2.0


def _is_exc_type(exc: Exception, *names: str) -> bool:
    return type(exc).__name__ in names


def _classify_status_error(exc: Exception) -> ErrorType:
    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        return ERROR_MODEL_AUTHENTICATION
    if status_code == 429:
        return ERROR_MODEL_RATE_LIMIT
    if status_code in (400, 404, 422):
        if _is_context_length_error(exc):
            return ERROR_MODEL_CONTEXT_LENGTH
        return ERROR_MODEL_BAD_REQUEST
    if status_code in (408, 500, 502, 503, 504):
        return ERROR_MODEL_CONNECTION
    return ERROR_EXTERNAL_MODEL


def _is_context_length_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "context length",
            "maximum context",
            "max context",
            "token limit",
            "prompt too long",
        )
    )


def _safe_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if len(message) > 500:
        return message[:500].rstrip() + "..."
    return message


def _validate_client_config(config: LLMClientConfig) -> None:
    missing = []
    if not config.base_url:
        missing.append("base_url")
    if not config.api_key:
        missing.append("api_key")
    if not config.model:
        missing.append("model")
    if missing:
        names = ", ".join(missing)
        provider = f" for provider {config.provider!r}" if config.provider else ""
        raise ConfigError(f"Missing model config field(s){provider}: {names}")
    if config.timeout_seconds <= 0:
        raise ConfigError("Model timeout_seconds must be a positive number.")
    if isinstance(config.max_retries, bool) or config.max_retries < 0:
        raise ConfigError("Model max_retries must be a non-negative integer.")
