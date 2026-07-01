"""Career Profile Engine.

A Career Profile is a self-contained career specialization living in its own
folder under ``profiles/``. Each profile owns everything needed to apply within
that specialization: resume, optional cover letter, keywords, preferred
locations, screening-answer cache, optional salary override, and supporting
documents.

    profiles/
      Infrastructure/
        profile.yaml
        resume.pdf
        cover_letter.docx          (optional)
        keywords.yaml
        screening_answers.yaml     (optional)
        preferred_locations.yaml   (optional)
        documents/                 (optional)

Adding a specialization is just adding a folder -- no Python or central config
changes. The AI returns a *profile name* and a *confidence*, never a filename;
the engine maps the name to the profile and falls back to the configured default
profile when confidence is below threshold or the name is unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


from .logging_setup import get_logger
from .yaml_utils import load_yaml, strip_line_meta

logger = get_logger(__name__)

PROFILE_FILE = "profile.yaml"
KEYWORDS_FILE = "keywords.yaml"
SCREENING_FILE = "screening_answers.yaml"
LOCATIONS_FILE = "preferred_locations.yaml"
DOCUMENTS_DIR = "documents"


@dataclass
class CareerProfile:
    """One self-contained career specialization."""

    name: str
    folder: Path
    description: str = ""
    resume_path: Path | None = None
    cover_letter_path: Path | None = None
    required_keywords: list[str] = field(default_factory=list)
    preferred_keywords: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    salary_override: int | None = None
    screening_answers: dict[str, str] = field(default_factory=dict)
    documents: dict[str, Path] = field(default_factory=dict)
    resume_version: str = "v1"

    def cached_answer(self, question: str) -> str | None:
        """Return a cached screening answer for ``question`` (case-insensitive)."""
        return self.screening_answers.get(_normalize(question))

    # ---- document accessors (the only way other modules get files) -------

    def has_resume(self) -> bool:
        return self.resume_path is not None and self.resume_path.exists()

    def resume_file(self) -> str:
        """Path to this profile's resume, or '' if it has none on disk."""
        return str(self.resume_path) if self.has_resume() else ""

    def has_own_cover_letter(self) -> bool:
        return (self.cover_letter_path is not None
                and self.cover_letter_path.exists())

    def cover_letter_file(self) -> str:
        return str(self.cover_letter_path) if self.has_own_cover_letter() else ""

    def document(self, doc_type: str) -> str:
        """Path to a named supporting document, or '' if absent."""
        path = self.documents.get(doc_type)
        return str(path) if path is not None and path.exists() else ""

    def all_documents(self) -> dict[str, str]:
        """All existing supporting documents as {type: path}."""
        return {t: str(p) for t, p in self.documents.items()
                if p is not None and p.exists()}


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


class CareerProfileError(Exception):
    """Raised for structural problems discovered while loading profiles."""


class CareerProfileEngine:
    """Discovers, loads, and selects Career Profiles."""

    def __init__(self, profiles_dir: str | Path, default_profile_name: str,
                 confidence_threshold: float):
        self.profiles_dir = Path(profiles_dir)
        self.default_profile_name = default_profile_name
        self.confidence_threshold = confidence_threshold
        self.profiles: dict[str, CareerProfile] = {}

    # ---- discovery / loading --------------------------------------------

    def load(self) -> dict[str, CareerProfile]:
        """Discover and load every profile folder. Idempotent."""
        self.profiles = {}
        if not self.profiles_dir.exists():
            raise CareerProfileError(
                f"Profiles directory not found: {self.profiles_dir}")
        for child in sorted(self.profiles_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / PROFILE_FILE).exists():
                logger.warning("Skipping '%s': no %s", child.name, PROFILE_FILE)
                continue
            profile = self._load_one(child)
            self.profiles[profile.name] = profile
        if not self.profiles:
            raise CareerProfileError(
                f"No valid career profiles found under {self.profiles_dir}")
        logger.info("Loaded %s career profile(s): %s",
                    len(self.profiles), ", ".join(self.profiles))
        return self.profiles

    def _load_one(self, folder: Path) -> CareerProfile:
        meta = strip_line_meta(load_yaml(folder / PROFILE_FILE))
        name = meta.get("name") or folder.name

        resume_path = self._resolve(folder, meta.get("resume", "resume.pdf"))
        cover = meta.get("cover_letter")
        cover_path = self._resolve(folder, cover) if cover else None

        keywords = self._load_keywords(folder)
        locations = self._load_list(folder / LOCATIONS_FILE)
        answers = self._load_answers(folder)
        documents = self._load_documents(folder, meta.get("documents", {}))

        salary_override = None
        so = meta.get("salary_override")
        if isinstance(so, dict) and "amount" in so:
            salary_override = int(so["amount"])
        elif isinstance(so, (int, float)):
            salary_override = int(so)

        return CareerProfile(
            name=name,
            folder=folder,
            description=meta.get("description", ""),
            resume_path=resume_path,
            cover_letter_path=cover_path,
            required_keywords=keywords[0],
            preferred_keywords=keywords[1],
            preferred_locations=locations,
            salary_override=salary_override,
            screening_answers=answers,
            documents=documents,
            resume_version=str(meta.get("resume_version", "v1")),
        )

    @staticmethod
    def _resolve(folder: Path, filename: str | None) -> Path | None:
        if not filename:
            return None
        return folder / filename

    def _load_keywords(self, folder: Path) -> tuple[list[str], list[str]]:
        path = folder / KEYWORDS_FILE
        if not path.exists():
            return [], []
        data = strip_line_meta(load_yaml(path))
        required = [str(k) for k in (data.get("required") or [])]
        preferred = [str(k) for k in (data.get("preferred") or [])]
        return required, preferred

    @staticmethod
    def _load_list(path: Path) -> list[str]:
        if not path.exists():
            return []
        data = strip_line_meta(load_yaml(path))
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict):
            return [str(x) for x in (data.get("locations") or [])]
        return []

    def _load_answers(self, folder: Path) -> dict[str, str]:
        path = folder / SCREENING_FILE
        if not path.exists():
            return {}
        data = strip_line_meta(load_yaml(path))
        answers = data.get("answers", data) if isinstance(data, dict) else {}
        return {_normalize(str(q)): str(a) for q, a in answers.items()}

    def _load_documents(self, folder: Path,
                        declared: dict[str, str]) -> dict[str, Path]:
        documents: dict[str, Path] = {}
        for doc_type, filename in (declared or {}).items():
            documents[str(doc_type)] = self._resolve(folder, str(filename))
        return documents

    # ---- selection ------------------------------------------------------

    def get(self, name: str) -> CareerProfile | None:
        return self.profiles.get(name)

    @property
    def default_profile(self) -> CareerProfile:
        profile = self.profiles.get(self.default_profile_name)
        if profile is None:
            raise CareerProfileError(
                f"Default career profile '{self.default_profile_name}' not loaded")
        return profile

    def select(self, profile_name: str, confidence: float) -> CareerProfile:
        """Map an AI choice to a profile, falling back to default when unsure."""
        if confidence < self.confidence_threshold:
            logger.info("Confidence %.1f < %.1f for '%s'; using default profile '%s'",
                        confidence, self.confidence_threshold, profile_name,
                        self.default_profile_name)
            return self.default_profile
        profile = self.profiles.get(profile_name)
        if profile is None:
            logger.warning("Unknown profile '%s' from AI; using default '%s'",
                           profile_name, self.default_profile_name)
            return self.default_profile
        return profile

    # ---- aggregates used by the Rule Engine (union across profiles) ------

    def all_required_keywords(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.profiles.values():
            for kw in p.required_keywords:
                seen.setdefault(kw, None)
        return list(seen)

    def all_preferred_locations(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.profiles.values():
            for loc in p.preferred_locations:
                seen.setdefault(loc, None)
        return list(seen)

    def names(self) -> list[str]:
        return list(self.profiles)
