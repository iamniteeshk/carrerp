"""Provider registry / factory.

Turns configuration into provider instances. A provider whose ``kind`` is
"gemini" gets the Gemini adapter; everything else is built as a generic
OpenAICompatibleProvider from config alone -- so DeepSeek, GLM, Kimi, MiniMax,
OpenRouter, Together, Fireworks, Mistral, etc. need no new Python, only config.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .gemini import GeminiProvider
from .openai_compat import OpenAICompatibleProvider
from .provider_base import AIProvider

# Convenience base URLs for well-known OpenAI-compatible providers, used only
# when config omits base_url. These are ENDPOINTS, not model names -- models are
# always discovered or set via preferred_model.
DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "kimi": "https://api.moonshot.ai/v1",
    "minimax": "https://api.minimax.chat/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openai": "https://api.openai.com/v1",
}


@dataclass
class ProviderSpec:
    name: str
    kind: str = "openai"          # "gemini" | "openai"
    enabled: bool = True
    api_keys: list = field(default_factory=list)
    base_url: str = ""
    discover_models: bool = True
    preferred_model: str = ""
    headers: dict = field(default_factory=dict)
    requires_auth: bool = True    # False for local servers (Ollama/LM Studio/vLLM)
    cache_ttl: int = 300

    def has_credential(self) -> bool:
        return bool([k for k in self.api_keys if k])


def build_provider(spec: ProviderSpec) -> AIProvider:
    if spec.kind == "gemini":
        return GeminiProvider([k for k in spec.api_keys if k],
                              spec.preferred_model)
    base = spec.base_url or DEFAULT_BASE_URLS.get(spec.name.lower(), "")
    key = next((k for k in spec.api_keys if k), "")
    return OpenAICompatibleProvider(
        name=spec.name, base_url=base, api_key=key,
        model=spec.preferred_model, headers=spec.headers,
        discover_models=spec.discover_models,
        requires_auth=spec.requires_auth, cache_ttl=spec.cache_ttl)


def build_providers(specs: list, active: str = "") -> list:
    """Build enabled providers, ACTIVE one first (so it's tried before fallbacks)."""
    enabled = [s for s in specs if s.enabled]
    enabled.sort(key=lambda s: (s.name.lower() != (active or "").lower()))
    return [build_provider(s) for s in enabled]
