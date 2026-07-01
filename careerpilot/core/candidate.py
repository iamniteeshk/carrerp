"""Candidate profile -- all user-specific personal data, loaded from candidate.yaml.

Nothing here is ever hardcoded in source. One deployment represents exactly one
candidate (see the V2 design note). These are the factual values used to fill
application forms; the AI never overrides them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any




@dataclass
class Candidate:
    """Factual candidate data. Free-form extras are preserved in ``extra``."""

    full_name: str
    email: str
    phone: str
    current_location: str = ""
    total_experience: str = ""
    current_company: str = ""
    current_designation: str = ""
    current_ctc: str = ""
    expected_ctc: str = ""
    notice_period: str = ""
    work_authorization: str = ""
    linkedin_url: str = ""
    willing_to_relocate: bool = True
    remote_preference: str = "Any"
    preferred_shift: str = "Any"
    # Anything else under candidate.yaml (employment history, education, skills,
    # certifications, etc.) is kept here so future phases can use it without a
    # schema change.
    extra: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """A compact profile string for AI context (no secrets)."""
        parts = [self.full_name]
        if self.total_experience:
            parts.append(f"{self.total_experience} experience")
        if self.current_designation and self.current_company:
            parts.append(f"currently {self.current_designation} at {self.current_company}")
        if self.current_location:
            parts.append(f"based in {self.current_location}")
        return ", ".join(parts) + "."

    def form_values(self) -> dict[str, str]:
        """Canonical factual values for form filling (knockout answers)."""
        return {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "current_location": self.current_location,
            "total_experience": self.total_experience,
            "current_company": self.current_company,
            "current_designation": self.current_designation,
            "current_ctc": self.current_ctc,
            "expected_ctc": self.expected_ctc,
            "notice_period": self.notice_period,
            "work_authorization": self.work_authorization,
            "linkedin_url": self.linkedin_url,
        }


# Keys consumed explicitly; everything else flows into ``extra``.
_KNOWN_KEYS = {
    "full_name", "email", "phone", "current_location", "total_experience",
    "current_company", "current_designation", "current_ctc", "expected_ctc",
    "notice_period", "work_authorization", "linkedin_url", "willing_to_relocate",
    "remote_preference", "preferred_shift", "__lines__",
}


def candidate_from_dict(clean: dict[str, Any]) -> Candidate:
    """Build a Candidate from an already-parsed dict (line-meta stripped)."""
    extra = {k: v for k, v in clean.items() if k not in _KNOWN_KEYS}
    return Candidate(
        full_name=clean.get("full_name", ""),
        email=clean.get("email", ""),
        phone=clean.get("phone", ""),
        current_location=clean.get("current_location", ""),
        total_experience=clean.get("total_experience", ""),
        current_company=clean.get("current_company", ""),
        current_designation=clean.get("current_designation", ""),
        current_ctc=clean.get("current_ctc", ""),
        expected_ctc=clean.get("expected_ctc", ""),
        notice_period=clean.get("notice_period", ""),
        work_authorization=clean.get("work_authorization", ""),
        linkedin_url=clean.get("linkedin_url", ""),
        willing_to_relocate=bool(clean.get("willing_to_relocate", True)),
        remote_preference=clean.get("remote_preference", "Any"),
        preferred_shift=clean.get("preferred_shift", "Any"),
        extra=extra,
    )

