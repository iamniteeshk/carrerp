"""Gemini provider with multiple-API-key support.

NOTE ON KEYS: rotating multiple personal keys to multiply free-tier quota can
violate Gemini's terms. The rotation here is implemented because it is a
documented product requirement; the safer production path is a single paid key.
The rotation simply tries each configured key in turn on failure.

The actual HTTP call is isolated in ``_call_api`` so it can be mocked in tests
and so swapping the SDK later touches one method only.
"""

from __future__ import annotations

import json
import time

import requests

from ..core.logging_setup import get_logger
from .provider_base import (AIProvider, AIProviderError, ModelInfo,
                            ProviderResponse)

logger = get_logger(__name__)

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)
_LIST_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models?key={key}"


class GeminiProvider(AIProvider):
    name = "Gemini"

    def __init__(self, api_keys: list[str], model: str):
        self.api_keys = [k for k in api_keys if k]
        self.model = model
        self._key_index = 0

    def is_available(self) -> bool:
        return bool(self.api_keys)

    def list_models(self, timeout: int = 20, key: str | None = None) -> list:
        """Query the live API for models that support generateContent, as
        ModelInfo (name + context window + capabilities). The authoritative way
        to learn valid names -- nothing is hardcoded.
        """
        key = key or (self.api_keys[0] if self.api_keys else "")
        if not key:
            raise AIProviderError("No Gemini API key to list models")
        try:
            resp = requests.get(_LIST_ENDPOINT.format(key=key), timeout=timeout)
        except requests.RequestException as exc:
            raise AIProviderError(f"network error listing models: {exc}") from exc
        if resp.status_code == 401 or resp.status_code == 403:
            raise AIProviderError(f"authentication failed ({resp.status_code})")
        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        out = []
        for m in resp.json().get("models", []):
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            name = m.get("name", "").replace("models/", "")
            out.append(ModelInfo(
                name=name, context_window=m.get("inputTokenLimit"),
                supports_chat=True,
                supports_vision="vision" in name.lower(),
                supports_tools="generateContent" in methods))
        return out

    @staticmethod
    def _names(models: list) -> list:
        """Tolerate either ModelInfo objects or plain name strings."""
        return [m.name if hasattr(m, "name") else m for m in models]

    def resolve_model(self, timeout: int = 20) -> str:
        """Validate the configured model against the live list; if it's missing,
        auto-select the newest compatible Flash model. Returns the model in use.
        On any failure it leaves the configured model unchanged.
        """
        try:
            available = self._names(self.list_models(timeout=timeout))
        except AIProviderError as exc:
            logger.warning("Could not validate Gemini model (%s); keeping '%s'",
                           exc, self.model)
            return self.model
        if not available:
            return self.model
        if self.model in available:
            logger.info("Gemini model '%s' is valid", self.model)
            return self.model
        newest = self._newest_flash(available) or (available[0] if available else "")
        if newest:
            logger.warning("Configured Gemini model '%s' unavailable; switching to "
                           "'%s' (auto-selected from live model list)",
                           self.model, newest)
            self.model = newest
        return self.model

    @staticmethod
    def _newest_flash(models: list[str]) -> str:
        """Pick the newest 'flash' model by a version-aware sort.

        'flash' is preferred (fast + cheap); the highest version number wins,
        falling back to lexical order. No specific version is assumed -- this
        ranks whatever the API actually offers.
        """
        import re
        flash = [m for m in models if "flash" in m.lower()
                 and "embedding" not in m.lower()]
        if not flash:
            return ""

        def version_key(name: str):
            nums = [int(x) for x in re.findall(r"\d+", name)]
            return (nums, name)

        return sorted(flash, key=version_key, reverse=True)[0]

    def generate(self, prompt: str, *, timeout: int) -> ProviderResponse:
        if not self.api_keys:
            raise AIProviderError("No Gemini API keys configured")

        last_error: Exception | None = None
        for offset in range(len(self.api_keys)):
            idx = (self._key_index + offset) % len(self.api_keys)
            key = self.api_keys[idx]
            try:
                response = self._call_api(prompt, key, timeout)
                self._key_index = idx  # stick with the key that worked
                return response
            except AIProviderError as exc:
                last_error = exc
                logger.warning("Gemini key #%s failed: %s", idx + 1, exc)
                time.sleep(0.5)
        raise AIProviderError(f"All Gemini keys failed. Last error: {last_error}")

    def _call_api(self, prompt: str, key: str, timeout: int) -> ProviderResponse:
        url = _ENDPOINT.format(model=self.model, key=key)
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise AIProviderError(f"network error: {exc}") from exc

        if resp.status_code == 429:
            raise AIProviderError("quota exhausted (429)")
        if resp.status_code == 404:
            # The configured model isn't valid for this API/key. Surface the
            # real, currently-available model names instead of an opaque 404.
            try:
                available = self._names(self.list_models(timeout=timeout, key=key))
                hint = ", ".join(available[:12]) or "(none returned)"
            except Exception as exc:  # noqa: BLE001
                hint = f"(could not list models: {exc})"
            raise AIProviderError(
                f"model '{self.model}' not found (HTTP 404). Set ai.gemini_model "
                f"in config.yaml to one of the available models: {hint}. "
                f"Run `py -m careerpilot.main models` to list them.")
        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"unexpected response shape: {exc}") from exc

        return ProviderResponse(text=text, tokens_used=tokens, model=self.model)
