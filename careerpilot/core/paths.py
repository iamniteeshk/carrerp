"""Production data-root layout — clean split between app code and user data.

Install layout (Windows dedicated PC)::

    C:\\CareerPilot\\
      app\\          Git repository (this package) — no personal files
      data\\         CAREERPILOT_DATA_ROOT — all user/runtime state
      backups\\      Dated full backups (outside ``data`` for easy copy)

Resolution order for the data root:

1. ``CAREERPILOT_DATA_ROOT`` environment variable
2. ``CAREERPILOT_HOME/data`` when ``CAREERPILOT_HOME`` is set
3. Sibling ``../data`` when the repo lives in ``.../app``
4. ``./data`` if it already looks like a *live* data root
   (contains ``config/config.yaml``, ``.env``, or ``.careerpilot_data_root``).
   A shipped templates-only ``data/`` tree does **not** count.
5. Current working directory (legacy / single-folder mode)

All relative paths from ``config.yaml`` are resolved against the data root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# Subdirectories created under the data root (production).
DATA_SUBDIRS: tuple[str, ...] = (
    "config",
    "profiles",
    "documents",
    "certificates",
    "browser",
    "browser/linkedin",
    "browser/naukri",
    "database",
    "database/backups",
    "logs",
    "reports",
    "reports/sessions",
    "screenshots",
    "cache",
    "cache/jobs",
    "debug",
    "health",
    "temp",
    "exports",
)


@dataclass(frozen=True)
class DataLayout:
    """Resolved absolute paths for one CareerPilot deployment."""

    data_root: Path
    app_root: Path
    backups_root: Path  # sibling of data by default (HOME/backups)

    @property
    def config_dir(self) -> Path:
        return self.data_root / "config"

    @property
    def config_yaml(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def env_file(self) -> Path:
        return self.data_root / ".env"

    @property
    def profiles_dir(self) -> Path:
        return self.data_root / "profiles"

    @property
    def documents_dir(self) -> Path:
        return self.data_root / "documents"

    @property
    def certificates_dir(self) -> Path:
        return self.data_root / "certificates"

    @property
    def browser_dir(self) -> Path:
        return self.data_root / "browser"

    @property
    def database_dir(self) -> Path:
        return self.data_root / "database"

    @property
    def database_path(self) -> Path:
        return self.database_dir / "careerpilot.db"

    @property
    def database_backups(self) -> Path:
        return self.database_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.data_root / "reports"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_root / "screenshots"

    @property
    def cache_dir(self) -> Path:
        return self.data_root / "cache"

    @property
    def debug_dir(self) -> Path:
        return self.data_root / "debug"

    @property
    def health_dir(self) -> Path:
        return self.data_root / "health"

    @property
    def temp_dir(self) -> Path:
        return self.data_root / "temp"

    @property
    def exports_dir(self) -> Path:
        return self.data_root / "exports"

    @property
    def pid_file(self) -> Path:
        return self.data_root / "careerpilot.pid"

    def resolve(self, path: str | Path) -> Path:
        """Resolve a config-relative path against the data root.

        Absolute paths are returned unchanged. Relative paths join ``data_root``.
        """
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.data_root / p).resolve()

    def ensure_dirs(self) -> list[str]:
        """Create the standard data-tree directories. Idempotent."""
        created: list[str] = []
        self.data_root.mkdir(parents=True, exist_ok=True)
        for rel in DATA_SUBDIRS:
            d = self.data_root / rel
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))
        self.backups_root.mkdir(parents=True, exist_ok=True)
        return created

    def as_dict(self) -> dict:
        return {
            "data_root": str(self.data_root),
            "app_root": str(self.app_root),
            "backups_root": str(self.backups_root),
            "config_yaml": str(self.config_yaml),
            "env_file": str(self.env_file),
            "profiles_dir": str(self.profiles_dir),
            "browser_dir": str(self.browser_dir),
            "database_path": str(self.database_path),
            "logs_dir": str(self.logs_dir),
            "reports_dir": str(self.reports_dir),
        }


def detect_app_root(start: Path | None = None) -> Path:
    """Find the Git/app root (directory containing the ``careerpilot`` package)."""
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "careerpilot" / "__init__.py").exists():
            return p
    return cur


def _looks_like_live_data_root(path: Path) -> bool:
    """True when ``path`` is a real data root, not the shipped templates tree.

    The Git repo may contain ``data/`` with ``*.example`` files only. That must
    NOT become CAREERPILOT_DATA_ROOT merely because the directory exists.
    """
    if (path / ".careerpilot_data_root").exists():
        return True
    if (path / "config" / "config.yaml").exists():
        return True
    if (path / ".env").exists():
        return True
    return False

def resolve_data_root(app_root: Path | None = None,
                      explicit: str | Path | None = None) -> Path:
    """Pick the data root using env / sibling / legacy rules."""
    if explicit:
        return Path(explicit).expanduser().resolve()

    env = (os.getenv("CAREERPILOT_DATA_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()

    home = (os.getenv("CAREERPILOT_HOME") or "").strip()
    if home:
        return (Path(home).expanduser() / "data").resolve()

    app = detect_app_root(app_root)
    # Sibling layout: .../CareerPilot/app  +  .../CareerPilot/data
    if app.name.lower() == "app":
        sibling = app.parent / "data"
        return sibling.resolve()

    local = app / "data"
    if local.is_dir() and _looks_like_live_data_root(local):
        return local.resolve()

    # Legacy: data lives in the repo / cwd (gitignored paths).
    return app.resolve()


def resolve_backups_root(data_root: Path, app_root: Path) -> Path:
    env = (os.getenv("CAREERPILOT_BACKUPS_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    home = (os.getenv("CAREERPILOT_HOME") or "").strip()
    if home:
        return (Path(home).expanduser() / "backups").resolve()
    # Sibling of data when using .../CareerPilot/data
    if data_root.name.lower() == "data":
        return (data_root.parent / "backups").resolve()
    # Legacy: ./backups next to cwd/app
    return (app_root / "backups").resolve()


def get_layout(*, data_root: str | Path | None = None,
               app_root: Path | None = None) -> DataLayout:
    app = detect_app_root(app_root)
    data = resolve_data_root(app, explicit=data_root)
    backups = resolve_backups_root(data, app)
    return DataLayout(data_root=data, app_root=app, backups_root=backups)


# Default production-relative path values written into new config.yaml files.
DEFAULT_PATH_CONFIG: dict[str, str] = {
    "database.path": "database/careerpilot.db",
    "database.backups_path": "database/backups",
    "browser.profiles_path": "browser",
    "browser.screenshots_path": "screenshots",
    "logging.dir": "logs",
    "application.reports_dir": "reports",
    "profiles.dir": "profiles",
    "documents.dir": "documents",
    "debug.evidence_dir": "debug",
}
