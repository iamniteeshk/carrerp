#!/usr/bin/env python3
"""Convenience entry point for production pre-flight checks.

Examples:
    python doctor.py
    python doctor.py --fix
    python doctor.py --fix --production

Prefer the package entry when possible:
    python -m careerpilot.main doctor [--fix] [--production]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is importable when launched as ``python doctor.py``.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    args = sys.argv[1:]
    # Re-dispatch through the real CLI so behaviour stays identical.
    from careerpilot.main import main as cp_main
    return cp_main(["doctor", *args])


if __name__ == "__main__":
    raise SystemExit(main())
