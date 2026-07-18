"""Resolve a reliable Python interpreter across platforms.

Windows production machines should use the ``py`` launcher (avoids the broken
WindowsApps ``python`` stub). After ``setup_windows.ps1``, prefer the project
``.venv`` interpreter so installed packages are visible.

Resolution order:
  1. Active / project ``.venv`` (``Scripts/python.exe`` or ``bin/python``)
  2. ``py`` launcher (Windows)
  3. ``python3``
  4. ``python``
  5. ``sys.executable``

Never hardcode the string ``\"python\"`` as the only launch option.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def is_windows() -> bool:
    return sys.platform.startswith("win")


def venv_python(root: Path | None = None) -> Path | None:
    """Return the project virtualenv interpreter if it exists."""
    root = root or Path.cwd()
    for name in (".venv", "venv"):
        if is_windows():
            candidate = root / name / "Scripts" / "python.exe"
        else:
            candidate = root / name / "bin" / "python"
        if candidate.is_file():
            return candidate
    return None


def which_launcher(name: str) -> str | None:
    return shutil.which(name)


def resolve_python(*, root: Path | None = None, prefer_venv: bool = True) -> str:
    """Return an absolute path or launcher name suitable for subprocess.

    On Windows, ``py`` is preferred over bare ``python`` when no venv exists.
    """
    if prefer_venv:
        vp = venv_python(root)
        if vp is not None:
            return str(vp.resolve())

    if is_windows():
        py = which_launcher("py")
        if py:
            return py

    for name in ("python3", "python"):
        found = which_launcher(name)
        if found:
            # Skip the Windows Store redirector stub when possible.
            if is_windows() and "WindowsApps" in found and which_launcher("py"):
                continue
            return found

    return sys.executable


def resolve_python_argv(*, root: Path | None = None,
                        prefer_venv: bool = True) -> list[str]:
    """Argv prefix to invoke Python (``['py']`` or ``['/path/to/python']``)."""
    exe = resolve_python(root=root, prefer_venv=prefer_venv)
    return [exe]


def python_command(*module_args: str, root: Path | None = None,
                   prefer_venv: bool = True) -> list[str]:
    """Build ``[launcher, '-m', ...]`` or ``[launcher, script, ...]`` argv."""
    return resolve_python_argv(root=root, prefer_venv=prefer_venv) + list(module_args)


def run_python(args: Sequence[str], *, root: Path | None = None,
               prefer_venv: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run`` using the resolved interpreter as argv[0]."""
    cmd = resolve_python_argv(root=root, prefer_venv=prefer_venv) + list(args)
    return subprocess.run(cmd, **kwargs)


def launcher_report(root: Path | None = None) -> dict:
    """Diagnostics dict for doctor / health."""
    root = root or Path.cwd()
    vp = venv_python(root)
    return {
        "resolved": resolve_python(root=root),
        "venv": str(vp) if vp else None,
        "py_launcher": which_launcher("py"),
        "python3": which_launcher("python3"),
        "python": which_launcher("python"),
        "sys_executable": sys.executable,
        "platform": sys.platform,
    }


def cli_hint(module_cmd: str = "careerpilot.main doctor") -> str:
    """User-facing command hint for the current OS."""
    if is_windows():
        vp = venv_python()
        if vp is not None:
            return f".\\.venv\\Scripts\\python.exe -m {module_cmd}"
        return f"py -m {module_cmd}"
    vp = venv_python()
    if vp is not None:
        return f".venv/bin/python -m {module_cmd}"
    return f"python3 -m {module_cmd}"
