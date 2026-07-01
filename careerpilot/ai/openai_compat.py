"""Generic OpenAI-compatible provider.

Speaks the OpenAI Chat Completions + Models API, so it supports DeepSeek, GLM
(Z.ai), Kimi (Moonshot), MiniMax, OpenRouter, Together, Fireworks, Mistral and
any future OpenAI-compatible provider with NO new Python -- only configuration
(name + base_url + api_key + optional headers + timeout). Model names are never
hardcoded: they are discovered via /models or set via preferred_model.
"""

from __future__ import annotations

import json
import time

import requests

from ..core.logging_setup import get_logger
from .provider_base import (AIProvider, AIProviderError, HealthReport,
                            ModelInfo, ProviderResponse)

logger = get_logger("careerpilot.ai.openai_compat")


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, name: str, base_url: str, api_key: str, *,
                 model: str = "", headers: dict | None = None,
                 discover_models: bool = True, requires_auth: bool = True,
                 cache_ttl: int = 300):
        self.name = name
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.extra_headers = headers or {}
        self.discover_models = discover_models
        # Local OpenAI-compatible servers (Ollama, LM Studio, vLLM) need no key.
        # When no auth is required, the provider is usable without an API key and
        # the Authorization header is omitted.
        self.requires_auth = requires_auth
        self.cache_ttl = cache_ttl
        self._model_cache: list | None = None
        self._cache_at: float = 0.0

    def is_available(self) -> bool:
        if not self.base_url:
            return False
        return bool(self.api_key) or not self.requires_auth

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:                      # omit empty Bearer for local servers
            h["Authorization"] = f"Bearer {self.api_key}"
        h.update(self.extra_headers)
        return h

    # ---- chat completions ----------------------------------------------

    def generate(self, prompt: str, *, timeout: int) -> ProviderResponse:
        if not self.is_available():
            raise AIProviderError(f"{self.name}: no base_url (or missing key)")
        if not self.model:
            raise AIProviderError(f"{self.name}: no model resolved (run model "
                                  "discovery or set preferred_model)")
        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model,
                   "messages": [{"role": "user", "content": prompt}],
                   "stream": False}
        try:
            resp = requests.post(url, headers=self._headers(), json=payload,
                                 timeout=timeout)
        except requests.RequestException as exc:
            raise AIProviderError(f"network error: {exc}") from exc
        if resp.status_code == 401:
            raise AIProviderError("authentication failed (401) -- bad API key")
        if resp.status_code == 404:
            raise AIProviderError(
                f"model '{self.model}' not found (404) at {self.base_url}; "
                "run `models` to list valid names")
        if resp.status_code == 429:
            raise AIProviderError("rate limited (429)")
        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"unexpected response shape: {exc}") from exc
        return ProviderResponse(text=text, tokens_used=tokens, model=self.model)

    # ---- model discovery (optional + cached + graceful) ----------------

    def list_models(self, timeout: int = 20, force: bool = False) -> list:
        """Discover models via /models. Results are cached for ``cache_ttl``
        seconds so startup resolution + the `models` command don't re-hit the
        API. Discovery is optional: a provider may simply not support it."""
        if (not force and self._model_cache is not None
                and (time.time() - self._cache_at) < self.cache_ttl):
            return self._model_cache
        if not self.is_available():
            raise AIProviderError(f"{self.name}: no base_url (or missing key)")
        url = f"{self.base_url}/models"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            raise AIProviderError(f"network error: {exc}") from exc
        if resp.status_code == 401:
            raise AIProviderError("authentication failed (401)")
        if resp.status_code == 404:
            raise AIProviderError("this provider does not expose /models "
                                  "(discovery unavailable)")
        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            rows = resp.json().get("data", [])
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"bad models response: {exc}") from exc
        out = []
        for m in rows:
            mid = m.get("id") or m.get("name") or ""
            if not mid:
                continue
            ctx = (m.get("context_window") or m.get("context_length")
                   or m.get("max_tokens"))
            out.append(ModelInfo(
                name=mid, context_window=ctx, supports_chat=True,
                supports_vision=bool(m.get("vision") or "vision" in mid.lower()),
                supports_tools=bool(m.get("tools") or m.get("function_calling")),
                deprecated=bool(m.get("deprecated"))))
        self._model_cache = out
        self._cache_at = time.time()
        return out

    def resolve_model(self, timeout: int = 20) -> str:
        """preferred_model -> validate against discovered models -> newest
        non-deprecated. Discovery is OPTIONAL: if it is turned off, unsupported,
        or unreachable, this gracefully falls back to the configured model and
        only errors when there is no model to fall back to."""
        if not self.discover_models:
            if self.model:
                logger.info("%s: discovery off, using configured model '%s'",
                            self.name, self.model)
                return self.model
            raise AIProviderError(f"{self.name}: discovery off and no "
                                  "preferred_model set")
        try:
            models = self.list_models(timeout=timeout)
        except AIProviderError as exc:
            if self.model:
                logger.warning("%s: discovery unavailable (%s); falling back to "
                               "configured model '%s'", self.name, exc, self.model)
                return self.model
            raise AIProviderError(
                f"{self.name}: discovery unavailable ({exc}) and no "
                "preferred_model to fall back to") from exc
        names = [m.name for m in models]
        if self.model and self.model in names:
            return self.model
        usable = [m for m in models if not m.deprecated and m.supports_chat] \
            or models
        if not usable:
            if self.model:
                logger.warning("%s: no models discovered; keeping '%s'",
                               self.name, self.model)
                return self.model
            raise AIProviderError(f"{self.name}: no usable models discovered")
        usable.sort(key=lambda m: (m.context_window or 0, -len(m.name)),
                    reverse=True)
        pick = usable[0].name
        logger.warning("%s: model '%s' not usable; auto-selected '%s'",
                       self.name, self.model or "(unset)", pick)
        self.model = pick
        return pick

    def health(self, timeout: int = 15) -> HealthReport:
        return super().health(timeout=timeout)
