# Universal AI Provider Framework — v2.8.3

The AI Engine is now provider-independent and future-proof. It is the ONLY part
touched in this release: Browser, Rule, Diagnostics and Portal engines are
unchanged. 162 tests pass (21 new, all HTTP mocked).

## Architecture

- `ai/provider_base.py` — common interface: `generate`, plus optional
  `list_models() -> [ModelInfo]`, `resolve_model()`, `health() -> HealthReport`.
  `ModelInfo` carries name, context window, chat/vision/tools support and
  deprecation.
- `ai/openai_compat.py` — **generic OpenAI-compatible provider**. Speaks
  `/chat/completions` + `/models`. Supports DeepSeek, GLM, Kimi, MiniMax,
  OpenRouter, Together, Fireworks, Mistral and any future OpenAI-compatible API
  with **no new Python** — only config (name + base_url + api_key + optional
  headers + timeout).
- `ai/gemini.py` — the one bespoke adapter (Gemini's API differs). Now returns
  `ModelInfo` and conforms to the same interface.
- `ai/factory.py` — turns config `ProviderSpec`s into provider instances;
  Gemini → adapter, everything else → generic provider. Active provider first,
  others as fallbacks.
- `ai/engine.py` — knows nothing about specific providers: it builds them from
  config and orchestrates generate / retry / fallback with rich logging.

## No hardcoded models

No model name is hardcoded in Python. `resolve_model()` does: preferred_model →
validate against discovered list → newest non-deprecated (largest context
window) → clear error. Discovery can be turned off per provider to use a
manually pinned `preferred_model`.

## Configuration (provider-driven)

```yaml
ai:
  active_provider: gemini
  request_timeout_seconds: 30
  max_retries: 3
  providers:
    gemini:   {enabled: true,  kind: gemini, api_key_envs: [GEMINI_API_KEY_1], preferred_model: ""}
    deepseek: {enabled: false, api_key_env: DEEPSEEK_API_KEY, base_url: https://api.deepseek.com/v1}
    glm:      {enabled: false, api_key_env: GLM_API_KEY,  base_url: https://open.bigmodel.cn/api/paas/v4}
    kimi:     {enabled: false, api_key_env: KIMI_API_KEY, base_url: https://api.moonshot.ai/v1}
    minimax:  {enabled: false, api_key_env: MINIMAX_API_KEY, base_url: https://api.minimax.chat/v1}
```

Adding OpenAI/Grok/OpenRouter/Together/etc. = one more block (base_url + key).
**Backward compatible:** the old `gemini_model` / `gemini_key_env_vars` /
`deepseek_*` config still loads and is synthesized into provider specs.

## Commands

- `python -m careerpilot.main models` — connects to every enabled provider,
  lists Provider / Model / Context Window / Chat / Vision / Tools / Deprecation,
  and exports `reports/models.json` + `reports/models.csv`.
- `python -m careerpilot.main ai-health` — Provider / Reachable / Auth / Latency
  / Current Model / #Models / Recommendation.
- `python -m careerpilot.main benchmark-ai` — same JD across every enabled
  provider: response time, tokens, cost (if exposed), resume selection,
  recommendation, match score, confidence; exports `reports/benchmark.json`.

## Logging

Every AI request logs provider, model, latency, retry count, tokens, cost,
success/failure reason — to the log files and (when debug is on) into the
Diagnostics recorder (read-only use; the toolkit itself is unchanged).

## Tested (all mocked, no live network)

Provider switching, runtime model discovery, config reload (new + legacy),
invalid API keys (401), missing models (404), rate limiting (429), deprecation,
network failures, retry logic, automatic fallback, benchmark, health check,
model listing, and a regression guard on `evaluate_job`.

## Honest limitation

I cannot reach the live provider endpoints from the build environment, so live
model discovery, real latency and actual benchmark numbers are yours to confirm
with your keys: set them, enable the providers, and run `ai-health`, `models`
and `benchmark-ai`. The framework, discovery/fallback/health/benchmark logic and
exports are all verified against mocked HTTP; the live calls are config + network
on your side.

---

## v2.8.4 refinement — optional/cached discovery + local servers

- **Discovery is optional and cached.** `list_models()` results are cached for
  `model_cache_ttl_seconds` (default 300), so startup model resolution and the
  `models` command don't re-hit the API. `force=True` refetches.
- **Graceful fallback.** If discovery is turned off, unsupported (the server
  returns 404 on `/models`), or unreachable, `resolve_model()` falls back to the
  configured `preferred_model`. It only errors when there is no model to fall
  back to — never silently.
- **Local OpenAI-compatible servers (Ollama, LM Studio, vLLM) are first-class.**
  A provider block with a `base_url` but no `api_key_env` is treated as keyless:
  it is usable without a key and the `Authorization` header is omitted. Example
  blocks are in `config.example.yaml`. For servers that pin a single served
  model and don't list models, set `discover_models: false` + `preferred_model`.
- No AI Engine code changes are needed to add either a new cloud provider or a
  local server — configuration only.
