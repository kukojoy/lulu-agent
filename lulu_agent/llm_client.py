from openai import OpenAI

from lulu_agent.config import validate_config


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, config):
        validate_config(config)
        self.base_url = config.openai_base_url
        self.model = config.openai_model
        self.client = OpenAI(
            api_key=config.openai_api_key,
            base_url=self.base_url,
        )

    def chat(self, messages, tools=None):
        return self._create_chat_completion(messages=messages, tools=tools, stream=False)

    def stream_chat(self, messages, tools=None):
        return self._create_chat_completion(messages=messages, tools=tools, stream=True)

    def _create_chat_completion(self, messages, tools=None, stream=False):
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        if stream:
            kwargs["stream"] = True
        if tools:
            kwargs["tools"] = tools

        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            raise LLMClientError(
                f"LLM request failed for model '{self.model}' at '{self.base_url}': "
                f"{exc_name}: {exc}"
            ) from exc
