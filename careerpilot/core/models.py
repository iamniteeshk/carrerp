"""Structured data models (dataclasses) used across CareerPilot.

These are the common objects passed between modules. Collectors produce
``Job`` objects; the AI Engine produces ``AIEvaluation``; the Auto Apply
engine produces ``ApplicationResult``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from .enums import JobStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    """Normalized job object returned by every collector.

    Every portal must be converted into this common structure (P009 §6).
    Missing values stay empty -- collectors must never invent data.
    """

    portal: str
    company: str = ""
    job_title: str = ""
    location: str = ""
    salary: str = ""
    experience: str = ""
    employment_type: str = ""
    shift: str = ""
    job_url: str = ""
    job_description: str = ""
    responsibilities: str = ""
    posted_date: str = ""
    recruiter_name: str = ""
    recruiter_email: str = ""
    recruiter_notes: str = ""
    company_website: str = ""
    company_description: str = ""
    benefits: str = ""
    raw_html: str = ""
    external_apply_url: str = ""
    apply_url: str = ""
    preferred_skills: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    source_id: str = ""
    # Easy Apply (LinkedIn) vs external redirect is decided at parse time.
    is_easy_apply: bool = False

    # Populated as the job moves through the pipeline.
    job_id: int | None = None
    status: JobStatus = JobStatus.FOUND
    match_score: float | None = None
    selected_resume: str | None = None
    rejection_reason: str | None = None
    # Full-JD reading state set by the Job Detail Reader. The Rule/AI engines
    # only ever decide on a COMPLETE job -- never on card-only data.
    read_status: str = "UNREAD"          # UNREAD | COMPLETE | PARTIAL | SKIPPED_PREFILTER
    missing_fields: list[str] = field(default_factory=list)
    reading_ms: int = 0
    failure_detail: str = ""
    # How the job page was opened (url_navigate is the production path since v2.9.7).
    open_mode: str = ""
    discovered_at: datetime = field(default_factory=_utcnow)

    def dedupe_key(self) -> str:
        """Fallback duplicate key when URL/source_id are unavailable."""
        return f"{self.company.strip().lower()}|{self.job_title.strip().lower()}|{self.location.strip().lower()}"

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AIEvaluation:
    """Result of the AI Engine evaluating a single job.

    The AI returns a *career profile name* and a *confidence* in that choice --
    never a filename. ``match_score`` is the separate job-fit score that gates
    whether to apply; ``confidence`` gates the default-profile fallback.
    """

    match_score: float
    career_profile: str
    confidence: float
    reason: str
    apply: bool
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    execution_time: float = 0.0
    raw_response: str = ""


@dataclass
class ScreeningAnswer:
    question: str
    answer: str
    source: str  # "config" (factual) or "ai" (reasoned)
    is_knockout: bool = False


@dataclass
class ApplicationResult:
    """Outcome of an auto-apply attempt."""

    job_id: int | None
    success: bool
    status: JobStatus
    portal: str
    company: str
    resume_used: str = ""
    resume_version: str = ""
    match_score: float | None = None
    portal_reference: str = ""
    failure_reason: str = ""
    screenshot_path: str = ""
    cover_letter: str = ""
    screening_answers: list[ScreeningAnswer] = field(default_factory=list)
    dry_run: bool = False
    applied_at: datetime = field(default_factory=_utcnow)
