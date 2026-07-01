"""SQLite database initialization and schema migrations.

SQLite is the single source of truth (P005). The schema is applied through a
simple, ordered migration list and a ``schema_version`` table, so the schema
can evolve without manual surgery. ``initialize()`` is idempotent and safe to
call on every startup.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..core.logging_setup import get_logger

logger = get_logger(__name__)


# Each migration is (version, SQL). Applied in order; only those newer than the
# stored schema_version run. Never edit a shipped migration -- add a new one.
MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS settings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        key        TEXT UNIQUE NOT NULL,
        value      TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS scan_history (
        scan_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at       DATETIME,
        finished_at      DATETIME,
        portals_scanned  INTEGER DEFAULT 0,
        jobs_found       INTEGER DEFAULT 0,
        jobs_rejected    INTEGER DEFAULT 0,
        jobs_matched     INTEGER DEFAULT 0,
        jobs_applied     INTEGER DEFAULT 0,
        duration_seconds REAL,
        status           TEXT
    );

    CREATE TABLE IF NOT EXISTS jobs (
        job_id           INTEGER PRIMARY KEY AUTOINCREMENT,
        portal           TEXT NOT NULL,
        company          TEXT,
        job_title        TEXT,
        location         TEXT,
        salary           TEXT,
        experience       TEXT,
        employment_type  TEXT,
        shift            TEXT,
        job_url          TEXT UNIQUE,
        job_description  TEXT,
        is_easy_apply    INTEGER DEFAULT 0,
        status           TEXT NOT NULL DEFAULT 'FOUND',
        match_score      REAL,
        selected_resume  TEXT,
        rejection_reason TEXT,
        source_id        TEXT,
        discovered_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS applications (
        application_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id             INTEGER REFERENCES jobs(job_id),
        company            TEXT,
        portal             TEXT,
        resume_used        TEXT,
        resume_version     TEXT,
        match_score        REAL,
        cover_letter       TEXT,
        screening_answers  TEXT,
        application_status TEXT,
        portal_reference   TEXT,
        screenshot         TEXT,
        dry_run            INTEGER DEFAULT 0,
        applied_at         DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS resume_profiles (
        resume_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT,
        file_name   TEXT,
        version     TEXT DEFAULT 'v1',
        description TEXT,
        active      INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS ai_history (
        ai_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        provider       TEXT,
        model          TEXT,
        job_id         INTEGER REFERENCES jobs(job_id),
        purpose        TEXT,
        tokens_used    INTEGER,
        execution_time REAL,
        success        INTEGER,
        created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS portal_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        portal     TEXT,
        action     TEXT,
        result     TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS notifications (
        notification_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        notification_type TEXT,
        message           TEXT,
        sent              INTEGER DEFAULT 0,
        created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
        sent_at           DATETIME
    );

    CREATE TABLE IF NOT EXISTS system_logs (
        log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        module     TEXT,
        level      TEXT,
        message    TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS failed_jobs (
        failed_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       INTEGER REFERENCES jobs(job_id),
        reason       TEXT,
        retry_count  INTEGER DEFAULT 0,
        screenshot   TEXT,
        last_attempt DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS ai_queue (
        queue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id      INTEGER REFERENCES jobs(job_id),
        task        TEXT,
        payload     TEXT,
        attempts    INTEGER DEFAULT 0,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """),
    (2, """
    CREATE INDEX IF NOT EXISTS idx_jobs_job_url ON jobs(job_url);
    CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
    CREATE INDEX IF NOT EXISTS idx_jobs_portal ON jobs(portal);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_discovered ON jobs(discovered_at);
    CREATE INDEX IF NOT EXISTS idx_apps_applied ON applications(applied_at);
    CREATE INDEX IF NOT EXISTS idx_apps_company ON applications(company);
    """),
]


class Database:
    """Thread-safe SQLite wrapper with migrations and auto-reconnect.

    Each thread gets its own connection (sharing one sqlite3 connection across
    threads is unsafe). WAL mode permits concurrent readers plus a single
    writer across connections; busy_timeout absorbs brief lock contention.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False,
                               timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")  # wait up to 30s on a lock
        return conn

    def connect(self) -> sqlite3.Connection:
        """Return this thread's connection, (re)creating it if needed."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1;")  # liveness check
                return conn
            except sqlite3.Error:
                logger.warning("Stale DB connection detected; reconnecting")
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
        conn = self._new_connection()
        self._local.conn = conn
        return conn

    def initialize(self) -> None:
        """Create the database and apply any pending migrations."""
        conn = self.connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER NOT NULL, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP);"
        )
        current = self._current_version(conn)
        for version, sql in MIGRATIONS:
            if version > current:
                logger.info("Applying database migration v%s", version)
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                conn.commit()
        logger.info("Database ready at %s (schema v%s)",
                    self.db_path, self._current_version(conn))

    @staticmethod
    def _current_version(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] if row and row["v"] is not None else 0

    def backup(self, backup_dir: str | Path) -> str:
        """Create a consistent on-disk backup using SQLite's backup API."""
        from datetime import datetime, timezone
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = backup_dir / f"careerpilot_{stamp}.db"
        dest = sqlite3.connect(str(target))
        try:
            self.connect().backup(dest)
        finally:
            dest.close()
        logger.info("Database backed up to %s", target)
        return str(target)

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.commit()
                conn.close()
            except sqlite3.Error as exc:
                logger.warning("Error closing DB connection: %s", exc)
            self._local.conn = None
