"""DeepSeek fallback provider (OpenAI-compatible chat completions API).

DATA-RESIDENCY NOTE: DeepSeek is a China-based provider. Using it as a fallback
means job descriptions and candidate profile text are sent there. Given the
candidate's security background this is a conscious trade-off; it is documented
here and the provider can be disabled simply by leaving DEEPSEEK_API_KEY empty.
"""

from __future__ import annotations

import json

import requests

from ..core.logging_setup import get_logger
from .provider_base import AIProvider, AIProviderError, ProviderResponse

logger = get_logger(__name__)

_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"


class DeepSeekProvider(AIProvider):
    name = "DeepSeek"

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key or ""
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, *, timeout: int) -> ProviderResponse:
        if not self.api_key:
            raise AIProviderError("No DeepSeek API key configured")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            resp = requests.post(_ENDPOINT, headers=headers, json=payload,
                                 timeout=timeout)
        except requests.RequestException as exc:
            raise AIProviderError(f"network error: {exc}") from exc

        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"unexpected response shape: {exc}") from exc

        return ProviderResponse(text=text, tokens_used=tokens, model=self.model)
