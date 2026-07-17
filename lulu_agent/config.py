import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    # 模型服务 (required)
    openai_base_url: str
    openai_api_key: str
    openai_model: str

    # 网络搜索服务 (optional)
    tavily_api_key: str

def load_config() -> Config:
    return Config(
        openai_api_key=os.getenv("OPENAI_API_KEY") or "",
        openai_base_url=os.getenv("OPENAI_BASE_URL") or "",
        openai_model=os.getenv("OPENAI_MODEL") or "",
        tavily_api_key=os.getenv("TAVILY_API_KEY") or "",
    )


def validate_config(config: Config) -> None:
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


config = load_config()
