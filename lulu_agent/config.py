import os
from dataclasses import dataclass

from dotenv import load_dotenv

from lulu_agent.safety import DEFAULT_SAFETY_PROFILE, validate_safety_profile

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    # 模型服务 (required)
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    model_timeout_seconds: float | str = 60.0

    # 网络搜索服务 (optional)
    tavily_api_key: str = ""

    # 安全档位
    safety_profile: str = DEFAULT_SAFETY_PROFILE

def load_config() -> Config:
    return Config(
        openai_api_key=os.getenv("OPENAI_API_KEY") or "",
        openai_base_url=os.getenv("OPENAI_BASE_URL") or "",
        openai_model=os.getenv("OPENAI_MODEL") or "",
        model_timeout_seconds=os.getenv("LULU_MODEL_TIMEOUT_SECONDS") or 60.0,
        tavily_api_key=os.getenv("TAVILY_API_KEY") or "",
        safety_profile=os.getenv("LULU_SAFETY_PROFILE") or DEFAULT_SAFETY_PROFILE,
    )


def validate_config(config: Config) -> None:
    validate_model_config(config)

    try:
        validate_safety_profile(config.safety_profile)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def validate_model_config(config: Config) -> None:
    missing = []
    if not config.openai_base_url:
        missing.append("OPENAI_BASE_URL")
    if not config.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not config.openai_model:
        missing.append("OPENAI_MODEL")

    if missing:
        names = ", ".join(missing)
        raise ConfigError(f"Missing required environment variable(s): {names}")

    config.model_timeout_seconds = _validate_model_timeout(config.model_timeout_seconds)


def _validate_model_timeout(value: float | str) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("LULU_MODEL_TIMEOUT_SECONDS must be a positive number.") from exc
    if timeout <= 0:
        raise ConfigError("LULU_MODEL_TIMEOUT_SECONDS must be a positive number.")
    return timeout


config = load_config()
