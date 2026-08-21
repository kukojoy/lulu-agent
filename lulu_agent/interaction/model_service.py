from typing import Any

from lulu_agent.llm.client import LLMClient
from lulu_agent.llm import providers as model_providers
from lulu_agent.llm.response import LLMClientConfig


class ModelInteractionService:
    def get_model_config(self) -> dict[str, Any]:
        return self.config_view(self.build_model_config())

    def config_view(self, model_config: LLMClientConfig) -> dict[str, Any]:
        return LLMClient(model_config).get_model_config().to_dict()

    def build_model_config(self, provider: str = "", model: str = "") -> LLMClientConfig:
        return model_providers.build_model_config(provider, model)

    def list_model_providers(self) -> list[dict[str, Any]]:
        return [provider.to_dict() for provider in model_providers.list_model_providers()]

    def list_provider_models(self, provider: str) -> dict[str, Any]:
        return model_providers.discover_provider_models(provider).to_dict()
