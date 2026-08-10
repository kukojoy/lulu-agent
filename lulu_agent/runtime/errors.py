from enum import StrEnum


class ErrorType(StrEnum):
    # Tool runtime
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    TIMEOUT = "timeout"
    EXECUTION = "execution_error"

    # Model runtime
    MODEL_TIMEOUT = "model_timeout"
    MODEL_AUTHENTICATION = "model_authentication_error"
    MODEL_RATE_LIMIT = "model_rate_limit_error"
    MODEL_BAD_REQUEST = "model_bad_request_error"
    MODEL_CONTEXT_LENGTH = "model_context_length_error"
    MODEL_CONNECTION = "model_connection_error"
    EXTERNAL_MODEL = "external_model_error"

    # External integrations
    EXTERNAL_TOOL = "external_tool_error"

    # Tool result boundary
    OUTPUT_TRUNCATED = "output_truncated"

    # Safety / approval
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_DENIED = "approval_denied"

    # Turn control
    USER_CANCELLED = "user_cancelled"

    # Storage / lookup
    NOT_FOUND = "not_found"

    # Configuration
    CONFIGURATION = "configuration_error"


ERROR_UNKNOWN_TOOL = ErrorType.UNKNOWN_TOOL
ERROR_INVALID_ARGUMENTS = ErrorType.INVALID_ARGUMENTS
ERROR_TIMEOUT = ErrorType.TIMEOUT
ERROR_EXECUTION = ErrorType.EXECUTION
ERROR_MODEL_TIMEOUT = ErrorType.MODEL_TIMEOUT
ERROR_MODEL_AUTHENTICATION = ErrorType.MODEL_AUTHENTICATION
ERROR_MODEL_RATE_LIMIT = ErrorType.MODEL_RATE_LIMIT
ERROR_MODEL_BAD_REQUEST = ErrorType.MODEL_BAD_REQUEST
ERROR_MODEL_CONTEXT_LENGTH = ErrorType.MODEL_CONTEXT_LENGTH
ERROR_MODEL_CONNECTION = ErrorType.MODEL_CONNECTION
ERROR_EXTERNAL_TOOL = ErrorType.EXTERNAL_TOOL
ERROR_EXTERNAL_MODEL = ErrorType.EXTERNAL_MODEL
ERROR_OUTPUT_TRUNCATED = ErrorType.OUTPUT_TRUNCATED
ERROR_PERMISSION_DENIED = ErrorType.PERMISSION_DENIED
ERROR_APPROVAL_DENIED = ErrorType.APPROVAL_DENIED
ERROR_USER_CANCELLED = ErrorType.USER_CANCELLED
ERROR_NOT_FOUND = ErrorType.NOT_FOUND
ERROR_CONFIGURATION = ErrorType.CONFIGURATION

ERROR_TYPES = frozenset(ErrorType)


class LuluError(RuntimeError):
    def __init__(self, error_message: str, error_type: ErrorType = ERROR_EXECUTION):
        super().__init__(error_message)
        self.error_message = error_message
        self.error_type = error_type
