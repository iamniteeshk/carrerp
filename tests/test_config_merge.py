"""Tests for the single-file config, backward compatibility, and the
configuration-driven browser launch plan.

The launch-plan tests verify that the correct Playwright parameters are built
for each engine/channel WITHOUT launching a browser, so cross-platform browser
selection is validated here (real on-device launch must be checked on macOS /
Windows separately).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.session import BrowserConfig, build_launch_plan
from careerpilot.core.config import load_config, ConfigError


# ---- configuration-driven browser launch plan ---------------------------

def test_launch_plan_edge_default():
    engine, kw = build_launch_plan(BrowserConfig(), "/tmp/x")
    assert engine == "chromium"
    assert kw["channel"] == "msedge"          # Edge is the default
    assert kw["viewport"] == {"width": 1366, "height": 900}
    assert "--disable-blink-features=AutomationControlled" in kw["args"]


def test_launch_plan_chrome_channel():
    engine, kw = build_launch_plan(
        BrowserConfig(engine="chromium", channel="chrome"), "/tmp/x")
    assert engine == "chromium" and kw["channel"] == "chrome"


def test_launch_plan_bundled_chromium_when_blank_channel():
    engine, kw = build_launch_plan(
        BrowserConfig(engine="chromium", channel=""), "/tmp/x")
    assert engine == "chromium" and "channel" not in kw


def test_launch_plan_firefox_ignores_channel_and_args():
    engine, kw = build_launch_plan(
        BrowserConfig(engine="firefox", channel="msedge"), "/tmp/x")
    assert engine == "firefox"
    assert "channel" not in kw      # channel is chromium-only
    assert "args" not in kw          # anti-automation arg is chromium-only


def test_launch_plan_unknown_engine_falls_back_to_chromium():
    engine, _ = build_launch_plan(BrowserConfig(engine="netscape"), "/tmp/x")
    assert engine == "chromium"


def test_launch_plan_custom_viewport_and_headless():
    engine, kw = build_launch_plan(
        BrowserConfig(engine="webkit", headless=True,
                      viewport_width=1920, viewport_height=1080), "/tmp/x")
    assert engine == "webkit"
    assert kw["headless"] is True
    assert kw["viewport"] == {"width": 1920, "height": 1080}


# ---- single-file config + backward compatibility ------------------------

def _make_profile(root: Path, name: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(f"name: {name}\nresume: resume.pdf\n")
    (d / "resume.pdf").write_text("%PDF fake")
    (d / "keywords.yaml").write_text("required:\n  - Infrastructure\n")
    (d / "preferred_locations.yaml").write_text("- Remote\n")


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_single_file_config_with_inline_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_profile(tmp / "profiles", "Infrastructure")
        env = _write(tmp / ".env", "GEMINI_API_KEY_1=k\n")
        cfg = _write(tmp / "config.yaml", f"""
application: {{name: CP}}
scheduler: {{scan_interval_hours: 6}}
candidate:
  full_name: Jane Doe
  email: jane@x.com
  phone: "+1-555"
ai: {{gemini_model: m, gemini_key_env_vars: [GEMINI_API_KEY_1]}}
browser: {{engine: chromium, channel: chrome, headless: true, viewport: {{width: 800, height: 600}}}}
dashboard: {{host: 127.0.0.1, port: 5000}}
database: {{path: {tmp}/db.sqlite, backups_path: {tmp}/backups}}
profiles: {{dir: {tmp}/profiles, default: Infrastructure, confidence_threshold: 70}}
rules: {{}}
apply: {{mode: dry_run, min_apply_score: 90}}
logging: {{dir: {tmp}/logs, level: DEBUG}}
documents: {{dir: {tmp}/docs}}
""")
        c = load_config(cfg, env)
        assert c.candidate.full_name == "Jane Doe"
        assert c.candidate.email == "jane@x.com"
        assert c.scan_interval_hours == 6
        assert c.browser.engine == "chromium" and c.browser.channel == "chrome"
        assert c.browser.headless is True
        assert c.browser.viewport_width == 800
        assert c.log_level == "DEBUG"
        assert "Infrastructure" in c.profiles


def test_missing_candidate_raises_clear_error():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_profile(tmp / "profiles", "Infrastructure")
        env = _write(tmp / ".env", "GEMINI_API_KEY_1=k\n")
        cfg = _write(tmp / "config.yaml", f"""
database: {{path: {tmp}/db.sqlite}}
dashboard: {{host: x, port: 1}}
browser: {{}}
ai: {{gemini_model: m, gemini_key_env_vars: [GEMINI_API_KEY_1]}}
profiles: {{dir: {tmp}/profiles, default: Infrastructure}}
rules: {{}}
apply: {{mode: dry_run, min_apply_score: 90}}
""")
        try:
            load_config(cfg, env)
            assert False, "should have raised (no candidate)"
        except ConfigError as exc:
            assert "candidate" in str(exc).lower()


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
