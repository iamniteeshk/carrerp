"""Abstract AI provider interface.

The AI Engine never talks to a specific provider directly -- only through this
interface. Adding a provider that speaks an OpenAI-compatible API requires NO
new Python (configuration only, via OpenAICompatibleProvider); only a provider
with a fundamentally different API (e.g. Gemini) needs its own adapter.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field


@dataclass
class ProviderResponse:
    text: str
    tokens_used: int
    model: str
    cost_usd: float | None = None


@dataclass
class ModelInfo:
    name: str
    context_window: int | None = None
    supports_chat: bool = True
    supports_vision: bool = False
    supports_tools: bool = False
    deprecated: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "context_window": self.context_window,
                "supports_chat": self.supports_chat,
                "supports_vision": self.supports_vision,
                "supports_tools": self.supports_tools,
                "deprecated": self.deprecated}


@dataclass
class HealthReport:
    provider: str
    reachable: bool = False
    authenticated: bool = False
    latency_ms: int | None = None
    current_model: str = ""
    models_available: int = 0
    rate_limits: dict = field(default_factory=dict)
    recommendation: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {"provider": self.provider, "reachable": self.reachable,
                "authenticated": self.authenticated, "latency_ms": self.latency_ms,
                "current_model": self.current_model,
                "models_available": self.models_available,
                "rate_limits": self.rate_limits,
                "recommendation": self.recommendation, "error": self.error}


class AIProviderError(Exception):
    """Raised when a provider call fails (network, quota, bad response)."""


class AIProvider(abc.ABC):
    """Common interface every AI provider must implement."""

    name: str = "abstract"
    model: str = ""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Whether this provider currently has a usable credential."""

    @abc.abstractmethod
    def generate(self, prompt: str, *, timeout: int) -> ProviderResponse:
        """Send a prompt and return the response. Raises AIProviderError on any
        failure so the engine can fall back to the next provider."""

    # ---- optional capabilities (safe defaults) -------------------------

    def list_models(self, timeout: int = 20) -> list[ModelInfo]:
        """Discover available models. Default: none (manual config required)."""
        return []

    def resolve_model(self, timeout: int = 20) -> str:
        """Validate/choose the model to use. Default: keep configured model."""
        return self.model

    def health(self, timeout: int = 15) -> HealthReport:
        """Default health probe via list_models (overridable)."""
        rep = HealthReport(provider=self.name, current_model=self.model)
        if not self.is_available():
            rep.error = "no API key"
            rep.recommendation = "set the API key env var"
            return rep
        start = time.time()
        try:
            models = self.list_models(timeout=timeout)
            rep.reachable = True
            rep.authenticated = True
            rep.latency_ms = int((time.time() - start) * 1000)
            rep.models_available = len(models)
            rep.recommendation = "ok"
        except AIProviderError as exc:
            rep.error = str(exc)
            rep.reachable = "network" not in str(exc).lower()
            rep.recommendation = "check key / base_url / connectivity"
        return rep
