"""Enumerations used across CareerPilot.

Using enums (per the coding standard) avoids string literals scattered
through the codebase and gives a single authoritative list of valid values.
"""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle status of a job. A job always has exactly one status."""

    FOUND = "FOUND"
    REJECTED = "REJECTED"
    MATCHED = "MATCHED"
    QUEUED = "QUEUED"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PARTIAL_DATA = "PARTIAL_DATA"  # JD could not be fully read; never auto-decided
    MANUAL_REVIEW = "MANUAL_REVIEW"  # e.g. LinkedIn -> external ATS redirect
    # Operator overrode a REJECTED decision in the dashboard; apply on next run.
    APPROVED = "APPROVED"


class Portal(str, Enum):
    """Supported job portals in Version 1."""

    LINKEDIN = "LinkedIn"
    NAUKRI = "Naukri"


class RejectionReason(str, Enum):
    """Single primary reason a job was rejected by the Rule Engine."""

    DUPLICATE = "Duplicate Job"
    PORTAL_NOT_ALLOWED = "Portal Not Allowed"
    SALARY_BELOW_THRESHOLD = "Salary Below Threshold"
    EXPERIENCE_MISMATCH = "Experience Mismatch"
    WRONG_EMPLOYMENT_TYPE = "Wrong Employment Type"
    NIGHT_SHIFT = "Night Shift"
    LOCATION_MISMATCH = "Location Mismatch"
    INVALID_JOB_TITLE = "Invalid Job Title"
    BLACKLISTED_COMPANY = "Blacklisted Company"
    DOMAIN_MISMATCH = "Domain Mismatch"
    LOW_MATCH_SCORE = "Match Score Below Threshold"


class AIProvider(str, Enum):
    GEMINI = "Gemini"
    DEEPSEEK = "DeepSeek"


class AITask(str, Enum):
    JOB_UNDERSTANDING = "job_understanding"
    EVALUATION = "evaluation"  # combined score + resume + reason + apply
    COVER_LETTER = "cover_letter"
    SCREENING_ANSWER = "screening_answer"


class NotificationType(str, Enum):
    APPLICATION_SUBMITTED = "application_submitted"
    APPLICATION_FAILED = "application_failed"
    LOGIN_REQUIRED = "login_required"
    OTP_REQUIRED = "otp_required"
    DAILY_SUMMARY = "daily_summary"
    CRITICAL_ERROR = "critical_error"
    UNSUPPORTED_ATS = "unsupported_ats"
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    QUEUE = "queue"
    APPROVAL_REQUEST = "approval_request"


class ApplyMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"
