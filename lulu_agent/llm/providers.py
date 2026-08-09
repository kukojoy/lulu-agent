from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lulu_agent.config import (
    ConfigError,
    config,
)
from lulu_agent.llm.response import LLMClientConfig

DEFAULT_MODEL_PROVIDERS_PATH = Path.home() / ".lulu" / "models.json"


@dataclass(frozen=True)
class ModelProvider:
    name: str
    base_url: str
    api_key: str
    default_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url_host": _base_url_host(self.base_url),
            "default_model": self.default_model,
            "base_url_configured": bool(self.base_url),
            "api_key_configured": bool(self.api_key),
        }


@dataclass(frozen=True)
class ProviderModelDiscovery:
    provider: str
    models: list[str]
    discovered: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "models": self.models,
            "discovered": self.discovered,
            "error": self.error,
        }


@dataclass(frozen=True)
class ModelProviderConfig:
    default_provider: str
    providers: dict[str, ModelProvider]


# === 对外接口 ===
def list_model_providers() -> list[ModelProvider]:
    """获取模型服务商列表"""
    return list(_load_provider_config().providers.values())

def build_model_config(provider_name: str = "", model: str = "") -> LLMClientConfig:
    """构造模型配置"""
    provider = _get_provider(provider_name)
    _validate_provider_config(provider)
    selected_model = (model or provider.default_model).strip()
    if not selected_model:
        raise ConfigError("Model name is required.")

    return LLMClientConfig(
        provider=provider.name,
        model=selected_model,
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout_seconds=config.model_timeout_seconds,
        max_retries=config.model_max_retries,
    )

def discover_provider_models(provider_name: str, timeout_seconds: float = 5.0) -> ProviderModelDiscovery:
    """发现模型服务商可用的模型列表"""
    provider = _get_provider(provider_name)
    try:
        _validate_provider_config(provider)
    except ConfigError as exc:
        return ProviderModelDiscovery(
            provider=provider.name,
            models=[provider.default_model] if provider.default_model else [],
            discovered=False,
            error=exc.error_message,
        )
    request = urllib.request.Request(f"{provider.base_url.rstrip('/')}/models")
    request.add_header("Authorization", f"Bearer {provider.api_key}")

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return ProviderModelDiscovery(
            provider=provider.name,
            models=[provider.default_model] if provider.default_model else [],
            discovered=False,
            error=str(exc) or exc.__class__.__name__,
        )

    models = _extract_model_ids(payload)
    discovered = bool(models)
    if not models and provider.default_model:
        models = [provider.default_model]
    return ProviderModelDiscovery(provider=provider.name, models=models, discovered=discovered)


# === helper ===
def _get_provider(provider_name: str) -> ModelProvider:
    """获取模型服务商配置"""
    provider_name = provider_name.strip() or ""
    config = _load_provider_config()
    if not provider_name:
        provider_name = config.default_provider
    provider = config.providers.get(provider_name)
    if provider is None:
        raise ConfigError(f"Unknown model provider: {provider_name}")
    return provider

def _load_provider_config() -> ModelProviderConfig:
    """加载模型服务商配置"""
    raw = _read_models_json(DEFAULT_MODEL_PROVIDERS_PATH)
    providers = _parse_providers(raw)
    if not providers:
        raise ConfigError("models.json must contain at least one provider.")

    default_provider = raw.get("default_provider")
    if isinstance(default_provider, str):
        default_provider = default_provider.strip()
        if default_provider:
            if default_provider not in providers:
                raise ConfigError(f"Unknown default model provider: {default_provider}")
        else:
            default_provider = next(iter(providers))
    else:
        default_provider = next(iter(providers))
    
    return ModelProviderConfig(
        default_provider=default_provider,
        providers=providers,
    )

def _read_models_json(path: Path) -> dict[str, Any]:
    """读取模型配置文件"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Missing model config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Failed to load model provider config: {exc}") from exc
        
def _parse_providers(raw: dict[str, Any]) -> dict[str, ModelProvider]:
    """解析模型服务商配置"""
    providers_raw = raw.get("providers") if isinstance(raw, dict) else None
    if not isinstance(providers_raw, dict):
        raise ConfigError("models.json must contain a providers object.")

    providers: dict[str, ModelProvider] = {}
    for name, item in providers_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("Model provider name must be a non-empty string.")
        if not isinstance(item, dict):
            raise ConfigError(f"Model provider {name!r} must be an object.")
        base_url = str(item.get("base_url") or "").strip()
        api_key = str(item.get("api_key") or "").strip()
        provider_name = name.strip()
        providers[provider_name] = ModelProvider(
            name=provider_name,
            base_url=base_url,
            api_key=api_key,
            default_model=str(item.get("default_model") or "").strip(),
        )
    return providers

def _validate_provider_config(provider: ModelProvider) -> None:
    """校验模型服务商配置"""
    missing = []
    if not provider.base_url:
        missing.append("base_url")
    if not provider.api_key:
        missing.append("api_key")
    if missing:
        raise ConfigError(f"Model provider {provider.name!r} requires {', '.join(missing)}.")

def _extract_model_ids(payload: Any) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    ids = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip():
            model = model_id.strip()
            if _is_language_model(model):
                ids.append(model)
    return ids

def _is_language_model(model: str) -> bool:
    """判断模型是否为语言模型"""
    normalized = model.lower()
    excluded_markers = (
        "embedding",
        "embed",
        "rerank",
        "moderation",
        "tts",
        "stt",
        "whisper",
        "audio",
        "image",
    )
    return not any(marker in normalized for marker in excluded_markers)

def _base_url_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    return parsed.hostname or base_url
