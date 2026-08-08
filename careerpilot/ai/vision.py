"""Vision helpers for login verification (Ollama / OpenAI-compatible VL).

Used as a compulsory safety check when enabled: screenshot the portal page and
ask a vision model whether the session looks logged in. On failure the scan
holds, Telegram is notified, and the dashboard shows an emergency banner.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.ai.vision")


@dataclass
class VisionLoginResult:
    logged_in: bool
    reason: str
    raw: str = ""
    error: str = ""


LOGIN_PROMPT = (
    "You are checking whether a user is logged into a job portal webpage. "
    "Look at the screenshot. Reply with ONLY compact JSON, no markdown:\n"
    '{{"logged_in": true|false, "reason": "short reason"}}\n'
    "Portal: {portal}. Treat login walls, sign-in forms, auth checkpoints, "
    "CAPTCHA-only screens, or 'join now' prompts as logged_in=false. "
    "A normal feed, jobs list, or profile menu means logged_in=true."
)


def _encode_image(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def _parse_json_reply(text: str) -> dict:
    text = (text or "").strip()
    # Qwen3 thinking mode may wrap reasoning before the JSON payload.
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.I)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]+\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def check_login_vision(
    image_path: str | Path,
    *,
    portal: str,
    base_url: str = "http://127.0.0.1:11434/v1",
    model: str = "qwen3-vl:8b",
    api_key: str = "",
    timeout: int = 90,
) -> VisionLoginResult:
    """Ask a vision model if the screenshot looks logged in."""
    path = Path(image_path)
    if not path.is_file():
        return VisionLoginResult(False, "screenshot missing", error="no_file")
    try:
        b64 = _encode_image(path)
    except OSError as exc:
        return VisionLoginResult(False, "screenshot unreadable", error=str(exc))

    url = f"{(base_url or '').rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": LOGIN_PROMPT.format(portal=portal)},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Vision login check network error: %s", exc)
        return VisionLoginResult(False, "vision unreachable", error=str(exc))
    if resp.status_code >= 400:
        logger.warning("Vision login HTTP %s: %s", resp.status_code, resp.text[:200])
        return VisionLoginResult(False, f"vision HTTP {resp.status_code}",
                                 error=resp.text[:200])
    try:
        raw = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        return VisionLoginResult(False, "bad vision response", error=str(exc))
    data = _parse_json_reply(raw)
    logged = bool(data.get("logged_in"))
    reason = str(data.get("reason") or ("logged in" if logged else "not logged in"))
    return VisionLoginResult(logged_in=logged, reason=reason, raw=raw)


def capture_page_screenshot(page: Any, dest: str | Path) -> str:
    """Best-effort Playwright screenshot; returns path or ''."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(dest), full_page=False)
        return str(dest)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision screenshot failed: %s", exc)
        return ""
