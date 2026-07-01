"""Tests for the Universal AI Provider Framework (v2.8.3).

All HTTP is mocked -- no live network. Covers provider switching, runtime model
discovery, config reload (new + legacy schema), invalid keys (401), missing
models (404), deprecation, network failures, retry logic, automatic fallback,
benchmark, health check and model listing. Also guards against regression of the
existing evaluate_job path.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.ai import openai_compat
from careerpilot.ai.openai_compat import OpenAICompatibleProvider
from careerpilot.ai.provider_base import (AIProvider, AIProviderError,
                                          ProviderResponse)
from careerpilot.ai.factory import (ProviderSpec, build_provider,
                                    build_providers, DEFAULT_BASE_URLS)
from careerpilot.ai.gemini import GeminiProvider


# ---- fake requests --------------------------------------------------------

class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text or str(self._payload)
    def json(self):
        return self._payload


class FakeRequests:
    """Stand-in for the requests module used by openai_compat."""
    class RequestException(Exception):
        pass

    def __init__(self):
        self.post_resp = None
        self.get_resp = None
        self.raise_on_post = None
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("post", url))
        if self.raise_on_post:
            raise self.raise_on_post
        return self.post_resp

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("get", url))
        return self.get_resp


def _patch(monkey: FakeRequests):
    openai_compat.requests = monkey


def _restore():
    import requests
    openai_compat.requests = requests


# ---- generic provider: generate -----------------------------------------

def test_generate_success():
    fr = FakeRequests()
    fr.post_resp = FakeResp(200, {"choices": [{"message": {"content": "hi"}}],
                                  "usage": {"total_tokens": 12}})
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("DeepSeek", "https://x/v1", "key", model="m")
        r = p.generate("prompt", timeout=10)
        assert r.text == "hi" and r.tokens_used == 12 and r.model == "m"
    finally:
        _restore()


def test_generate_401_invalid_key():
    fr = FakeRequests(); fr.post_resp = FakeResp(401, text="unauthorized")
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("GLM", "https://x/v1", "bad", model="m")
        try:
            p.generate("prompt", timeout=10); assert False
        except AIProviderError as e:
            assert "authentication" in str(e).lower()
    finally:
        _restore()


def test_generate_404_missing_model():
    fr = FakeRequests(); fr.post_resp = FakeResp(404, text="no model")
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("Kimi", "https://x/v1", "k", model="gone")
        try:
            p.generate("prompt", timeout=10); assert False
        except AIProviderError as e:
            assert "not found" in str(e).lower() and "gone" in str(e)
    finally:
        _restore()


def test_generate_429_rate_limited():
    fr = FakeRequests(); fr.post_resp = FakeResp(429, text="slow down")
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("MiniMax", "https://x/v1", "k", model="m")
        try:
            p.generate("p", timeout=10); assert False
        except AIProviderError as e:
            assert "429" in str(e)
    finally:
        _restore()


def test_generate_network_error():
    fr = FakeRequests(); fr.raise_on_post = FakeRequests.RequestException("down")
    openai_compat.requests = fr
    # make the provider's except clause catch our fake exception type
    orig = openai_compat.requests.RequestException
    try:
        p = OpenAICompatibleProvider("DeepSeek", "https://x/v1", "k", model="m")
        try:
            p.generate("p", timeout=10); assert False
        except AIProviderError as e:
            assert "network error" in str(e).lower()
    finally:
        _restore()
        assert orig is FakeRequests.RequestException


def test_generate_without_model_raises_clear():
    p = OpenAICompatibleProvider("DeepSeek", "https://x/v1", "k", model="")
    try:
        p.generate("p", timeout=10); assert False
    except AIProviderError as e:
        assert "no model" in str(e).lower()


# ---- model discovery + resolution ----------------------------------------

def _models_payload():
    return {"data": [
        {"id": "chat-small", "context_length": 8000},
        {"id": "chat-large", "context_length": 128000},
        {"id": "old-model", "context_length": 4000, "deprecated": True},
        {"id": "vision-pro", "context_length": 32000, "vision": True,
         "function_calling": True}]}


def test_list_models_parses_metadata():
    fr = FakeRequests(); fr.get_resp = FakeResp(200, _models_payload())
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("GLM", "https://x/v1", "k")
        models = p.list_models()
        by = {m.name: m for m in models}
        assert by["chat-large"].context_window == 128000
        assert by["old-model"].deprecated is True
        assert by["vision-pro"].supports_vision and by["vision-pro"].supports_tools
    finally:
        _restore()


def test_resolve_keeps_configured_model_when_present():
    fr = FakeRequests(); fr.get_resp = FakeResp(200, _models_payload())
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("GLM", "https://x/v1", "k", model="chat-small")
        assert p.resolve_model() == "chat-small"
    finally:
        _restore()


def test_resolve_autoselects_largest_context_nondeprecated():
    fr = FakeRequests(); fr.get_resp = FakeResp(200, _models_payload())
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("GLM", "https://x/v1", "k", model="missing")
        chosen = p.resolve_model()
        assert chosen == "chat-large"      # largest ctx, not deprecated
        assert p.model == "chat-large"
    finally:
        _restore()


def test_resolve_discovery_off_keeps_manual_model():
    p = OpenAICompatibleProvider("X", "https://x/v1", "k", model="manual",
                                 discover_models=False)
    assert p.resolve_model() == "manual"


# ---- discovery is optional / cached / graceful ---------------------------

def test_list_models_is_cached():
    fr = FakeRequests(); fr.get_resp = FakeResp(200, _models_payload())
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("GLM", "https://x/v1", "k", cache_ttl=300)
        p.list_models(); p.list_models(); p.list_models()
        gets = [c for c in fr.calls if c[0] == "get"]
        assert len(gets) == 1                 # cached after first call
        p.list_models(force=True)
        assert len([c for c in fr.calls if c[0] == "get"]) == 2  # force refetches
    finally:
        _restore()


def test_resolve_falls_back_when_discovery_unavailable():
    # /models returns 404 (provider doesn't support discovery) -> keep configured.
    fr = FakeRequests(); fr.get_resp = FakeResp(404, text="no models route")
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("vLLM", "http://localhost:8000/v1", "",
                                     model="my-model", requires_auth=False)
        assert p.resolve_model() == "my-model"   # graceful fallback
    finally:
        _restore()


def test_resolve_discovery_unavailable_and_no_model_errors():
    fr = FakeRequests(); fr.get_resp = FakeResp(404, text="no models")
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("vLLM", "http://localhost:8000/v1", "",
                                     model="", requires_auth=False)
        try:
            p.resolve_model(); assert False
        except AIProviderError as e:
            assert "fall back" in str(e).lower()   # clear, not silent
    finally:
        _restore()


# ---- keyless / local OpenAI-compatible servers ---------------------------

def test_local_keyless_server_is_available_without_key():
    p = OpenAICompatibleProvider("Ollama", "http://localhost:11434/v1", "",
                                 model="llama3.1", requires_auth=False)
    assert p.is_available() is True
    assert "Authorization" not in p._headers()


def test_keyed_provider_without_key_is_unavailable():
    p = OpenAICompatibleProvider("GLM", "https://x/v1", "", requires_auth=True)
    assert p.is_available() is False           # cloud provider needs its key


def test_local_server_generate_sends_no_auth_header():
    fr = FakeRequests()
    fr.post_resp = FakeResp(200, {"choices": [{"message": {"content": "hi"}}],
                                  "usage": {"total_tokens": 3}})
    _patch(fr)
    try:
        p = OpenAICompatibleProvider("LMStudio", "http://localhost:1234/v1", "",
                                     model="local-model", requires_auth=False)
        r = p.generate("p", timeout=5)
        assert r.text == "hi"
        assert "Authorization" not in p._headers()
    finally:
        _restore()


def test_config_local_server_spec_keyless():
    from careerpilot.core.config import _build_provider_specs
    ai = {"active_provider": "ollama", "providers": {
        "ollama": {"enabled": True, "base_url": "http://localhost:11434/v1",
                   "preferred_model": "llama3.1"}}}
    _active, specs = _build_provider_specs(ai, [], "")
    assert specs[0].requires_auth is False     # no key env => keyless/local
    assert specs[0].base_url.endswith(":11434/v1")


# ---- factory + provider switching ----------------------------------------

def test_factory_builds_gemini_adapter_and_generic():
    g = build_provider(ProviderSpec(name="gemini", kind="gemini",
                                    api_keys=["k"], preferred_model="m"))
    assert isinstance(g, GeminiProvider)
    d = build_provider(ProviderSpec(name="deepseek", kind="openai",
                                    api_keys=["k"]))
    assert isinstance(d, OpenAICompatibleProvider)
    assert d.base_url == DEFAULT_BASE_URLS["deepseek"]


def test_build_providers_active_first():
    specs = [ProviderSpec(name="gemini", kind="gemini", api_keys=["k"]),
             ProviderSpec(name="deepseek", kind="openai", api_keys=["k"])]
    providers = build_providers(specs, active="deepseek")
    assert providers[0].name == "deepseek"     # active tried first


def test_disabled_provider_excluded():
    specs = [ProviderSpec(name="gemini", kind="gemini", api_keys=["k"]),
             ProviderSpec(name="kimi", kind="openai", api_keys=["k"],
                          enabled=False)]
    providers = build_providers(specs, active="gemini")
    assert [p.name for p in providers] == ["Gemini"] or \
           [p.name for p in providers] == ["gemini"]


# ---- engine orchestration: fallback + retry ------------------------------

class FlakyProvider(AIProvider):
    def __init__(self, name, fail_times=0, available=True, text="{}"):
        self.name = name; self.model = "m"; self._fail = fail_times
        self._avail = available; self._text = text; self.attempts = 0
    def is_available(self): return self._avail
    def generate(self, prompt, *, timeout):
        self.attempts += 1
        if self._fail > 0:
            self._fail -= 1
            raise AIProviderError("temporary")
        return ProviderResponse(text=self._text, tokens_used=5, model=self.model)


def _engine_with(providers, retries=2):
    from careerpilot.ai.engine import AIEngine
    from careerpilot.core.config import AIConfig
    cfg = AIConfig(gemini_keys=[], gemini_model="", deepseek_key="",
                   deepseek_model="", request_timeout=1, max_retries=retries,
                   min_apply_score=70, active_provider="", providers=[])
    eng = AIEngine.__new__(AIEngine)
    eng.cfg = cfg; eng.profile = "p"; eng.profile_names = ["A"]
    eng.default_profile = "A"; eng.providers = providers; eng.diag_recorder = None
    return eng


def test_engine_retry_then_succeeds(monkeypatch=None):
    import careerpilot.ai.engine as eng_mod
    eng_mod.time.sleep = lambda *_: None      # no real backoff sleeping
    p = FlakyProvider("P", fail_times=2)
    eng = _engine_with([p], retries=3)
    text, prov, model, tokens, elapsed = eng._generate("prompt")
    assert prov == "P" and p.attempts == 3    # failed twice, succeeded 3rd


def test_engine_automatic_fallback_when_active_fails():
    import careerpilot.ai.engine as eng_mod
    eng_mod.time.sleep = lambda *_: None
    dead = FlakyProvider("Active", fail_times=99)
    good = FlakyProvider("Fallback", fail_times=0, text="ok")
    eng = _engine_with([dead, good], retries=1)
    text, prov, *_ = eng._generate("prompt")
    assert prov == "Fallback"                 # fell back after active exhausted


def test_engine_all_fail_raises_unavailable():
    import careerpilot.ai.engine as eng_mod
    from careerpilot.ai.engine import AIUnavailable
    eng_mod.time.sleep = lambda *_: None
    eng = _engine_with([FlakyProvider("A", fail_times=99)], retries=1)
    try:
        eng._generate("p"); assert False
    except AIUnavailable:
        pass


# ---- benchmark + health + discovery --------------------------------------

def test_engine_benchmark_runs_every_provider():
    good = FlakyProvider("G", text='{"career_profile":"A","apply":true,'
                                    '"match_score":80,"confidence":90}')
    dead = FlakyProvider("D", available=False)
    eng = _engine_with([good, dead])
    from careerpilot.core.models import Job
    rows = eng.benchmark(Job(portal="b", job_title="t", company="c",
                             location="l", job_url="u", job_description="d"))
    by = {r["provider"]: r for r in rows}
    assert by["G"]["recommendation"] == "apply" and by["G"]["match_score"] == 80
    assert "error" in by["D"]


def test_engine_health_all_and_discover():
    fr = FakeRequests(); fr.get_resp = FakeResp(200, _models_payload())
    _patch(fr)
    try:
        prov = OpenAICompatibleProvider("GLM", "https://x/v1", "k", model="chat-large")
        eng = _engine_with([prov])
        health = eng.health_all()
        assert health[0]["provider"] == "GLM" and health[0]["models_available"] == 4
        disc = eng.discover_models()
        assert len(disc["GLM"]["models"]) == 4
    finally:
        _restore()


# ---- config reload: new + legacy schema ----------------------------------

def test_config_new_provider_schema(tmp_path=None):
    from careerpilot.core.config import _build_provider_specs
    ai = {"active_provider": "glm", "providers": {
        "gemini": {"enabled": True, "api_key_env": "X_GEM", "preferred_model": ""},
        "glm": {"enabled": True, "api_key_env": "X_GLM",
                "base_url": "https://glm/v4", "preferred_model": "glm-5"},
        "kimi": {"enabled": False, "api_key_env": "X_KIMI"}}}
    os.environ["X_GEM"] = "gk"; os.environ["X_GLM"] = "lk"
    active, specs = _build_provider_specs(ai, [], "")
    by = {s.name: s for s in specs}
    assert active == "glm"
    assert by["gemini"].kind == "gemini" and by["gemini"].has_credential()
    assert by["glm"].kind == "openai" and by["glm"].preferred_model == "glm-5"
    assert by["kimi"].enabled is False
    del os.environ["X_GEM"]; del os.environ["X_GLM"]


def test_config_legacy_schema_synthesizes_specs():
    from careerpilot.core.config import _build_provider_specs
    active, specs = _build_provider_specs(
        {"gemini_model": "gemini-2.5-flash"}, ["gk"], "dk")
    by = {s.name: s for s in specs}
    assert active == "gemini"
    assert by["gemini"].kind == "gemini" and by["gemini"].api_keys == ["gk"]
    assert by["deepseek"].kind == "openai" and by["deepseek"].enabled is True


# ---- regression: evaluate_job still works --------------------------------

def test_evaluate_job_no_regression():
    good = FlakyProvider("G", text='{"match_score":75,"career_profile":"A",'
                                   '"confidence":88,"reason":"fit","apply":true}')
    eng = _engine_with([good])
    from careerpilot.core.models import Job
    ev = eng.evaluate_job(Job(portal="p", job_title="Director", company="C",
                              location="L", job_url="u", job_description="JD"))
    assert ev.match_score == 75 and ev.career_profile == "A"
    assert ev.apply is True and ev.provider == "G"


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); passed += 1; print(f"PASS {name}")
            except Exception:
                failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
