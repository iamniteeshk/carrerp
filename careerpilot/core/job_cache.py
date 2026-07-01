"""Persistent Job Memory Cache.

Once a job has been opened and its full data extracted, it is cached so it never
needs to be reopened -- unless the posting changed. Keyed by a stable job key
(URL) with a content hash for change detection. Backed by JSON files on disk so
it survives restarts. Deterministic, AI-free; the AI Engine reads cached Job
data rather than driving the browser to re-fetch.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)


def job_key(url: str) -> str:
    """Stable key for a job URL (strips query/fragment and trailing slash)."""
    url = (url or "").split("#")[0].split("?")[0].rstrip("/")
    return url


def content_hash(data: dict) -> str:
    """Hash the fields that indicate a posting changed."""
    basis = "|".join(str(data.get(k, "")) for k in
                     ("job_title", "company", "location", "salary", "experience",
                      "job_description"))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    changed: int = 0

    def as_dict(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "changed": self.changed}


class JobCache:
    def __init__(self, cache_dir: str | Path = "cache/jobs"):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stats = CacheStats()

    def _path(self, key: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", key)[-120:] or "job"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return self.dir / f"{safe}-{digest}.json"

    def get(self, url: str) -> dict | None:
        p = self._path(job_key(url))
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache read failed for %s: %s", url, exc)
            return None

    def needs_open(self, url: str, current_hash: str | None = None) -> bool:
        """True if the job must be opened: not cached, or content changed."""
        cached = self.get(url)
        if cached is None:
            self.stats.misses += 1
            logger.info("Cache MISS | %s", job_key(url))
            return True
        if current_hash is not None and cached.get("hash") != current_hash:
            self.stats.changed += 1
            logger.info("Cache CHANGED | %s (reopening)", job_key(url))
            return True
        self.stats.hits += 1
        logger.info("Cache HIT | %s (reusing cached data)", job_key(url))
        return False

    def put(self, job_data: dict) -> str:
        url = job_data.get("job_url", "")
        key = job_key(url)
        record = dict(job_data)
        record["hash"] = content_hash(job_data)
        record["_key"] = key
        p = self._path(key)
        try:
            p.write_text(json.dumps(record, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache write failed for %s: %s", url, exc)
        return record["hash"]

    def __len__(self) -> int:
        return len(list(self.dir.glob("*.json")))
