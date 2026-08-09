import os
from dataclasses import dataclass

from dotenv import load_dotenv

from lulu_agent.runtime.errors import ERROR_CONFIGURATION, LuluError
from lulu_agent.safety import DEFAULT_SAFETY_PROFILE, validate_safety_profile

load_dotenv()


class ConfigError(LuluError):
    def __init__(self, error_message: str):
        super().__init__(error_message=error_message, error_type=ERROR_CONFIGURATION)


@dataclass
class Config:
    # 模型运行参数。provider/model/base_url/api_key 由 ~/.lulu/models.json 构造为 LLMClientConfig。
    model_timeout_seconds: float | str = 60.0
    model_max_retries: int | str = 3

    # 网络搜索服务 (optional)
    tavily_api_key: str = ""

    # 安全档位
    safety_profile: str = DEFAULT_SAFETY_PROFILE


def load_config() -> Config:
    config = Config(
        model_timeout_seconds=os.getenv("LULU_MODEL_TIMEOUT_SECONDS") or 60.0,
        model_max_retries=os.getenv("LULU_MODEL_MAX_RETRIES") or 3,
        tavily_api_key=os.getenv("TAVILY_API_KEY") or "",
        safety_profile=os.getenv("LULU_SAFETY_PROFILE") or DEFAULT_SAFETY_PROFILE,
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    validate_model_config(config)

    try:
        validate_safety_profile(config.safety_profile)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def validate_model_config(config: Config) -> None:
    config.model_timeout_seconds = _validate_model_timeout(config.model_timeout_seconds)
    config.model_max_retries = _validate_model_max_retries(config.model_max_retries)


def _validate_model_timeout(value: float | str) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("LULU_MODEL_TIMEOUT_SECONDS must be a positive number.") from exc
    if timeout <= 0:
        raise ConfigError("LULU_MODEL_TIMEOUT_SECONDS must be a positive number.")
    return timeout


def _validate_model_max_retries(value: int | str) -> int:
    try:
        retries = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("LULU_MODEL_MAX_RETRIES must be a non-negative integer.") from exc
    if isinstance(value, bool) or retries < 0:
        raise ConfigError("LULU_MODEL_MAX_RETRIES must be a non-negative integer.")
    return retries


config = load_config()
