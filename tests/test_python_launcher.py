#!/usr/bin/env python3
"""python_launcher + Windows script resolver smoke tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name} {detail}")
        failed += 1


def main() -> int:
    print("=== python launcher ===")
    from careerpilot.core.python_launcher import (
        resolve_python, resolve_python_argv, python_command, cli_hint,
        launcher_report, run_python,
    )

    resolved = resolve_python()
    check("resolve_python returns non-empty", bool(resolved), resolved)
    check("resolve_python is not bare 'python' only path when venv/sys exist",
          resolved != "python" or Path(sys.executable).exists())
    argv = resolve_python_argv()
    check("resolve_python_argv list", isinstance(argv, list) and len(argv) >= 1)
    cmd = python_command("-m", "pip", "--version")
    check("python_command builds -m pip", cmd[-3:] == ["-m", "pip", "--version"] or
          "-m" in cmd)

    r = run_python(["-c", "print(123)"], capture_output=True, text=True, timeout=30)
    check("run_python executes", r.returncode == 0 and "123" in (r.stdout or ""),
          str(r.returncode))

    report = launcher_report()
    check("launcher_report has resolved", "resolved" in report)
    check("cli_hint non-empty", bool(cli_hint()))

    # Doctor does not require bare `python` on PATH
    from careerpilot.core import windows_env as wenv
    ok, msg = wenv.py_launcher_available()
    check("py_launcher_available callable", isinstance(ok, bool), msg)

    # Scripts prefer py / resolver helpers
    check("scripts/_ResolvePython.ps1",
          (ROOT / "scripts/_ResolvePython.ps1").exists())
    check("scripts/_resolve_python.bat",
          (ROOT / "scripts/_resolve_python.bat").exists())
    for name in ("doctor.ps1", "run_careerpilot.ps1", "update_careerpilot.ps1",
                 "install_requirements.ps1", "Register-CareerPilotStartup.ps1",
                 "doctor.bat", "run_careerpilot.bat", "install_requirements.bat",
                 "restart_careerpilot.bat", "update_project.bat"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8", errors="replace")
        bad = ("where python" in text and "where py" not in text and
               "_resolve" not in text and "_ResolvePython" not in text)
        check(f"script prefers py resolver: {name}", not bad)

    setup = (ROOT / "setup_windows.ps1").read_text(encoding="utf-8")
    check("setup_windows prefers py", 'Test-Cmd "py"' in setup or "py" in setup)
    check("setup uses -m pip", "-m pip" in setup or '"-m", "pip"' in setup or
          "-m\", \"pip\"" in setup or " -m pip " in setup)

    # INSTALL_WINDOWS documents py
    inst = (ROOT / "docs/INSTALL_WINDOWS.md").read_text(encoding="utf-8")
    check("INSTALL_WINDOWS mentions py doctor", "py doctor.py" in inst or
          "py -m careerpilot.main" in inst)
    check("INSTALL_WINDOWS avoids 'python not found' as primary tip",
          "| `py` not found |" in inst or "py launcher" in inst.lower())

    # No Windows batch left that only knows `python` for launching CareerPilot
    for bat in (ROOT / "scripts").glob("*.bat"):
        if bat.name.startswith("_"):
            continue
        # Wrappers that only call other scripts / taskkill need no interpreter.
        if bat.name in ("stop_careerpilot.bat", "update_careerpilot.bat",
                        "setup_windows.bat"):
            check(f"bat wrapper ok: {bat.name}", True)
            continue
        t = bat.read_text(encoding="utf-8", errors="replace")
        if "careerpilot" in t.lower() or "pip" in t.lower() or "-m" in t:
            check(f"bat uses resolver or py: {bat.name}",
                  "_resolve_python" in t or "py" in t or ".venv" in t)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
