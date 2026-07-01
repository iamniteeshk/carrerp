"""Shared test fixture: build a complete, valid CareerPilot deployment in a temp
directory (config.yaml + profiles/ + .env), with NO dependency on any file the
end user owns. This is what lets the suite pass on a completely clean clone.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# A minimal valid PDF so resume files are real on disk.
_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF")

# Six profiles so tests that assert a specific count remain meaningful.
_PROFILES = {
    "Infrastructure": (["Infrastructure", "Cloud"], ["Chennai", "Remote"]),
    "Digital_Workplace": (["Digital Workplace", "EUC"], ["Bangalore", "Remote"]),
    "Contact_Centre": (["Contact Centre", "BPO"], ["Chennai", "Remote"]),
    "GCC": (["GCC", "Global Delivery"], ["Bangalore", "Remote"]),
    "Leadership": (["Leadership", "Operations"], ["Chennai", "Remote"]),
    "GCC_Head_CXO": (["GCC Head", "CXO"], ["Bangalore", "Remote"]),
}


def make_profile(profiles_dir: Path, name: str,
                 required=("Infrastructure",), preferred=("Azure",),
                 locations=("Chennai", "Remote"), with_resume: bool = True) -> Path:
    d = profiles_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text(
        f"name: {name}\ndescription: test\nresume: resume.pdf\n"
        f"resume_version: v2\ndocuments:\n  resume: resume.pdf\n")
    if with_resume:
        (d / "resume.pdf").write_bytes(_PDF)
    (d / "keywords.yaml").write_text(
        "required:\n" + "".join(f"  - {k}\n" for k in required)
        + "preferred:\n" + "".join(f"  - {k}\n" for k in preferred))
    (d / "preferred_locations.yaml").write_text(
        "".join(f"- {x}\n" for x in locations))
    (d / "screening_answers.yaml").write_text(
        'answers:\n  "how many years of experience": "25 years"\n')
    return d


def make_deployment(tmp: Path, default: str = "Infrastructure") -> tuple[str, str]:
    """Create a full valid deployment under ``tmp``. Returns (config_path, env_path)."""
    tmp = Path(tmp)
    profiles_dir = tmp / "profiles"
    for name, (req, locs) in _PROFILES.items():
        make_profile(profiles_dir, name, required=req, locations=locs)

    env_path = tmp / ".env"
    env_path.write_text("GEMINI_API_KEY_1=testkey\n")

    config = {
        "application": {"name": "CareerPilot", "reports_dir": str(tmp / "reports")},
        "scheduler": {"scan_interval_hours": 4},
        "candidate": {  # real, non-placeholder values so validation passes
            "full_name": "Test User", "email": "test@example.com",
            "phone": "+1-555-0100", "current_location": "Chennai, India",
            "total_experience": "25 years", "current_company": "TestCo",
            "current_designation": "Director", "linkedin_url": "https://x/in/test"},
        "ai": {"gemini_model": "gemini-1.5-flash",
               "gemini_key_env_vars": ["GEMINI_API_KEY_1"]},
        "browser": {"engine": "chromium", "channel": "msedge",
                    "profiles_path": str(tmp / "profiles_browser"),
                    "screenshots_path": str(tmp / "screenshots")},
        "dashboard": {"host": "127.0.0.1", "port": 5000},
        "database": {"path": str(tmp / "database" / "cp.db"),
                     "backups_path": str(tmp / "database" / "backups")},
        "telegram": {"enabled": False},
        "profiles": {"dir": str(profiles_dir), "default": default,
                     "confidence_threshold": 70},
        "rules": {"minimum_salary": {"amount": 6000000, "currency": "INR"},
                  "minimum_experience": 15,
                  "accepted_titles": ["Director", "Head", "VP"],
                  "rejected_titles": ["Engineer", "Analyst"],
                  "blacklist_companies": ["BlacklistedCo"]},
        "apply": {"mode": "dry_run", "min_apply_score": 90},
        "logging": {"dir": str(tmp / "logs"), "level": "INFO"},
        "documents": {"dir": str(tmp / "documents")},
    }
    config_path = tmp / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    return str(config_path), str(env_path)
