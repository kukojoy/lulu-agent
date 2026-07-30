from enum import StrEnum


class ErrorType(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    TIMEOUT = "timeout"
    EXECUTION = "execution_error"
    EXTERNAL_TOOL = "external_tool_error"
    OUTPUT_TRUNCATED = "output_truncated"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"


ERROR_UNKNOWN_TOOL = ErrorType.UNKNOWN_TOOL
ERROR_INVALID_ARGUMENTS = ErrorType.INVALID_ARGUMENTS
ERROR_TIMEOUT = ErrorType.TIMEOUT
ERROR_EXECUTION = ErrorType.EXECUTION
ERROR_EXTERNAL_TOOL = ErrorType.EXTERNAL_TOOL
ERROR_OUTPUT_TRUNCATED = ErrorType.OUTPUT_TRUNCATED
ERROR_PERMISSION_DENIED = ErrorType.PERMISSION_DENIED
ERROR_NOT_FOUND = ErrorType.NOT_FOUND

ERROR_TYPES = frozenset(ErrorType)


class LuluError(RuntimeError):
    def __init__(self, error_message: str, error_type: ErrorType = ERROR_EXECUTION):
        super().__init__(error_message)
        self.error_message = error_message
        self.error_type = error_type
