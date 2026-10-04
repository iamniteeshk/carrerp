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


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


# Keyword groups that are exclusions or score settings, not search terms.
_KEYWORD_SKIP = {
    "negative", "scoring", "minimum_score", "strong_match_score",
    "excellent_match_score", "application_score",
}
_LOCATION_SKIP = {
    "exclude_locations", "location_rules", "search", "relocation",
    "priority", "priority_overrides",
}


def split_keywords(data) -> tuple[list[str], list[str]]:
    """Read required/preferred, or primary plus every other keyword list."""
    if not isinstance(data, dict):
        return [], []
    if isinstance(data.get("required"), list) or isinstance(data.get("preferred"), list):
        return _string_list(data.get("required")), _string_list(data.get("preferred"))
    required = _string_list(data.get("primary"))
    preferred: list[str] = []
    for key, value in data.items():
        if key in _KEYWORD_SKIP or key == "primary":
            continue
        preferred.extend(_string_list(value))
    return required, preferred


def flatten_locations(data) -> list[str]:
    """Read a list, a locations: list, or the grouped preferred/remote map."""
    if isinstance(data, list):
        return _string_list(data)
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("locations"), list):
        return _string_list(data["locations"])
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            out.extend(_string_list(node))
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in _LOCATION_SKIP:
                    continue
                walk(value)

    walk(data)
    seen: dict[str, None] = {}
    for item in out:
        seen.setdefault(item, None)
    return list(seen)


def collect_answers(data) -> dict[str, str]:
    """Read answers: {question: text} or nested maps that each have answer:."""
    if not isinstance(data, dict):
        return {}
    block = data.get("answers")
    if isinstance(block, dict) and block and all(
            not isinstance(value, (dict, list)) for value in block.values()):
        return {_normalize(str(q)): str(a) for q, a in block.items()}
    found: dict[str, str] = {}

    def walk(node, key: str | None = None) -> None:
        if isinstance(node, dict):
            answer = node.get("answer")
            if key and isinstance(answer, str) and answer.strip():
                found[_normalize(key.replace("_", " "))] = answer.strip()
            for child_key, child in node.items():
                if child_key == "answer":
                    continue
                walk(child, str(child_key))
        elif isinstance(node, list):
            for item in node:
                walk(item, key)

    walk(data)
    return found


def _resume_filename(meta: dict) -> str:
    resume = (meta or {}).get("resume", "resume.pdf")
    if isinstance(resume, dict):
        resume = resume.get("file") or "resume.pdf"
    resume = str(resume or "resume.pdf").strip()
    return resume or "resume.pdf"


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

        resume_path = self._resolve(folder, _resume_filename(meta))
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
        return split_keywords(data)

    @staticmethod
    def _load_list(path: Path) -> list[str]:
        if not path.exists():
            return []
        return flatten_locations(strip_line_meta(load_yaml(path)))

    def _load_answers(self, folder: Path) -> dict[str, str]:
        path = folder / SCREENING_FILE
        if not path.exists():
            return {}
        return collect_answers(strip_line_meta(load_yaml(path)))

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
