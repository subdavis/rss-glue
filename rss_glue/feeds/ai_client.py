from dataclasses import dataclass
from typing import Protocol

import anthropic


@dataclass
class AiClientResponse:
    response: str
    tokens_used: int


class AiClient(Protocol):

    def get_response(self, prompt: str) -> AiClientResponse:
        pass


class ClaudeClient(AiClient):

    client: anthropic.Client

    def __init__(
        self, api_key: str, model: str = "claude-3-5-sonnet-20240620", **kwargs
    ):
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, **kwargs)

    def get_response(self, prompt: str) -> AiClientResponse:
        message = self.client.messages.create(
            max_tokens=5000,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model=self.model,
        )
        document = ""

        # how many tokens did this take?
        tokens_used = message.usage.input_tokens + message.usage.output_tokens

        for line in message.content:
            document += getattr(line, "text", "") + "\n"

        return AiClientResponse(response=document, tokens_used=tokens_used)
