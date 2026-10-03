"""Classify local-model failures without calling a cloud API."""

from __future__ import annotations


def classify_provider_failure(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "timed out" in msg or "timeout" in msg or "read timed out" in msg:
        return "timeout"
    if any(tok in msg for tok in (
            "connection refused", "failed to establish", "unreachable",
            "name or service not known", "nodename nor servname",
            "connection aborted", "network error")):
        return "ollama_unavailable"
    if any(tok in msg for tok in (
            "out of memory", "cuda out of memory", "insufficient",
            "resource", "cannot allocate")):
        return "insufficient_resources"
    if any(tok in msg for tok in (
            "not found", "404", "model unavailable", "no such model")):
        return "model_unavailable"
    if any(tok in msg for tok in (
            "unexpected response", "json", "invalid", "bad models")):
        return "invalid_response"
    return f"error: {exc}"


def prefer_small_local_model(names: list[str]) -> str:
    """Pick a configured-empty local model without jumping to a 70B."""

    def rank(name: str) -> tuple:
        n = name.lower()
        if "70b" in n or "72b" in n:
            size = 70
        elif "32b" in n or "34b" in n:
            size = 32
        elif "14b" in n:
            size = 14
        elif "8b" in n or "7b" in n:
            size = 8
        elif "4b" in n or "3b" in n or "1.5" in n:
            size = 4
        else:
            size = 16
        return (size, len(n))

    usable = [n for n in names if "70b" not in n.lower() and "72b" not in n.lower()]
    pool = usable or list(names)
    pool.sort(key=rank)
    return pool[0]
