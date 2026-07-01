"""Document Manager.

The single place that turns a Career Profile into concrete files to attach to an
application: resume, cover letter, and supporting documents. It speaks *only* in
terms of ``CareerProfile`` objects -- it never knows individual filenames,
profile names, keywords, or which specializations exist. That knowledge lives
entirely inside the Career Profile Engine.

This is what makes profiles behave like plug-ins: a brand-new profile folder
(e.g. "Cybersecurity") is resolved here exactly like any other, with no code
change, because the Document Manager only ever asks a profile for its files.
"""

from __future__ import annotations

from .career_profile import CareerProfile, CareerProfileEngine
from .logging_setup import get_logger

logger = get_logger(__name__)


class DocumentManager:
    """Resolves application documents for a given Career Profile."""

    def __init__(self, engine: CareerProfileEngine):
        self._engine = engine

    def resume_for(self, profile: CareerProfile) -> str:
        """Resume path for ``profile``; falls back to the default profile's
        resume if this profile has none on disk."""
        path = profile.resume_file()
        if path:
            return path
        default = self._engine.default_profile
        fallback = default.resume_file()
        logger.warning("Resume missing for profile '%s'; using default '%s'",
                       profile.name, default.name)
        return fallback

    def cover_letter_for(self, profile: CareerProfile) -> str:
        """Path to the profile's own cover-letter file, or '' if it has none
        (in which case the caller may generate one)."""
        return profile.cover_letter_file()

    def has_own_cover_letter(self, profile: CareerProfile) -> bool:
        return profile.has_own_cover_letter()

    def supporting_documents_for(self, profile: CareerProfile) -> dict[str, str]:
        """All existing supporting documents declared by the profile."""
        return profile.all_documents()
