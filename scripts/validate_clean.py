#!/usr/bin/env python3
"""Packaging validator (Issue 6/18).

Fails (exit 1) if the working tree contains any runtime artifact that must NOT
ship in the distributed ZIP -- a stale database, CSVs, logs, cache, browser
profiles, screenshots, Playwright state, __pycache__, .pyc, .DS_Store, etc.

Run this BEFORE creating the release ZIP:

    python scripts/validate_clean.py .

Exit codes: 0 = clean (safe to package), 1 = dirty (packaging must abort).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Directories that only ever hold generated runtime data.
FORBIDDEN_DIRS = {
    "database", "logs", "reports", "debug", "screenshots", "cache",
    "profiles_browser", "profiles", "documents", "resumes",
    ".playwright", "playwright-state",
}
# File patterns that are always runtime/OS artifacts.
FORBIDDEN_GLOBS = [
    "**/*.db", "**/*.sqlite", "**/*.sqlite3", "**/*.pyc", "**/*.pyo",
    "**/*.log", "**/*.csv", "**/.DS_Store", "**/Thumbs.db",
    "**/careerpilot.pid", "**/*.session",
]
FORBIDDEN_DIR_NAMES = {"__pycache__", ".pytest_cache"}
# Files that are allowed even though they'd match a glob (none for .csv here;
# the project ships no data CSVs).
ALLOWLIST: set[str] = set()


def scan(root: Path) -> list[str]:
    problems: list[str] = []
    for name in FORBIDDEN_DIRS:
        p = root / name
        if p.exists() and any(p.iterdir()) if p.is_dir() else p.exists():
            problems.append(f"runtime dir present: {name}/")
    for d in root.rglob("*"):
        if d.is_dir() and d.name in FORBIDDEN_DIR_NAMES:
            problems.append(f"cache dir present: {d.relative_to(root)}")
    for pattern in FORBIDDEN_GLOBS:
        for f in root.glob(pattern):
            rel = str(f.relative_to(root))
            if rel in ALLOWLIST:
                continue
            problems.append(f"runtime file present: {rel}")
    return sorted(set(problems))


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = scan(root)
    if problems:
        print("PACKAGING VALIDATION FAILED -- runtime artifacts detected:")
        for p in problems:
            print(f"  - {p}")
        print("\nRemove these before packaging. The released ZIP must start "
              "from a clean state.")
        return 1
    print("PACKAGING VALIDATION PASSED -- no runtime artifacts. Safe to ZIP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
