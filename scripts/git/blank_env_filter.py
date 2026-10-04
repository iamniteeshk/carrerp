#!/usr/bin/env python3
"""Git clean filter: keep .env keys, drop every value.

Git runs this when .env is staged. A filled working copy stays on disk.
The blob that would be committed has blank values only.
"""

from __future__ import annotations

import sys


def blank_env(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key, _sep, _value = line.partition("=")
        lines.append(f"{key}=")
    trailing = "\n" if text.endswith("\n") or not text else "\n"
    return "\n".join(lines) + (trailing if lines else "")


def main() -> int:
    sys.stdout.write(blank_env(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
