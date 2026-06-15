from openai import OpenAI

from lulu_agent.config import config


class LLMClient:
    def __init__(self, config):
        self.model = config.openai_model
        self.client = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
        )

    def chat(self, messages, tools=None):
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        return self.client.chat.completions.create(**kwargs)
