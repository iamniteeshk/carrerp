"""Tests for the deterministic and mockable parts of CareerPilot.

These run without any network, credentials, or browser. They cover the Rule
Engine (fully deterministic), config validation, and the AI engine's
parsing/fallback logic (with a fake provider).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.config import RuleConfig
from careerpilot.core.enums import RejectionReason
from careerpilot.core.models import Job
from careerpilot.rules.rule_engine import (RuleEngine, _parse_salary_to_inr,
                                           _parse_experience_min)


def _rule_config(**overrides) -> RuleConfig:
    base = dict(
        minimum_salary=3_500_000, salary_currency="INR", minimum_experience=15,
        accepted_employment_types=["Full Time"], rejected_shifts=["Night Shift"],
        preferred_locations=["Chennai", "Bangalore", "Remote"],
        accepted_titles=["Director", "Head", "VP"],
        rejected_titles=["Desktop Support", "Engineer", "L1"],
        blacklist_companies=["BadCorp"],
        required_keywords=["Infrastructure", "Cloud"],
        nice_to_have_keywords=["Azure"],
    )
    base.update(overrides)
    return RuleConfig(**base)


def _job(**kw) -> Job:
    defaults = dict(portal="LinkedIn", company="Acme", job_title="Director - IT Infrastructure",
                    location="Chennai", salary="", experience="18 years",
                    employment_type="Full Time", shift="Day Shift",
                    job_description="Enterprise Infrastructure and Cloud leadership role")
    defaults.update(kw)
    return Job(**defaults)


def test_accepts_good_leadership_job():
    engine = RuleEngine(_rule_config())
    assert engine.evaluate(_job()).accepted


def test_rejects_bad_title():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(job_title="Desktop Support Engineer"))
    assert not r.accepted and r.reason == RejectionReason.INVALID_JOB_TITLE


def test_engineering_director_not_rejected_by_engineer_keyword():
    # 'Engineering Director' contains 'engineer' but is a leadership role.
    engine = RuleEngine(_rule_config(accepted_titles=["Director"]))
    assert engine.evaluate(_job(job_title="Engineering Director")).accepted


def test_rejects_blacklisted_company():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(company="BadCorp"))
    assert not r.accepted and r.reason == RejectionReason.BLACKLISTED_COMPANY


def test_rejects_night_shift():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(shift="Night Shift"))
    assert not r.accepted and r.reason == RejectionReason.NIGHT_SHIFT


def test_rejects_low_experience():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(experience="8 years"))
    assert not r.accepted and r.reason == RejectionReason.EXPERIENCE_MISMATCH


def test_rejects_domain_mismatch():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(job_title="Director - Sales",
                             job_description="Sales and marketing leadership"))
    assert not r.accepted and r.reason == RejectionReason.DOMAIN_MISMATCH


def test_rejects_location_mismatch():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(location="Delhi"))
    assert not r.accepted and r.reason == RejectionReason.LOCATION_MISMATCH


def test_rejects_ai_role_despite_director_title():
    # v3.0.0: the exact reported bug -- an AI role must NOT be rescued by the
    # generic 'Director' leadership word. It is rejected before the AI runs.
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(job_title="Director - AI",
                             job_description="Lead AI research and ML teams"))
    assert not r.accepted and r.reason == RejectionReason.DOMAIN_MISMATCH


def test_rejects_ml_role_despite_director_title():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(job_title="Director - AI/ML",
                             job_description="Machine learning platform leadership"))
    assert not r.accepted and r.reason == RejectionReason.DOMAIN_MISMATCH


def test_rejects_data_scientist_lead():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(job_title="Head of Data Science",
                             job_description="Build data science and analytics"))
    assert not r.accepted and r.reason == RejectionReason.DOMAIN_MISMATCH


def test_ai_infrastructure_role_is_borderline_not_hard_rejected():
    # A title carrying the candidate's own domain keyword ('Infrastructure') is
    # borderline, so it is NOT hard-rejected -- the AI is allowed to judge it.
    engine = RuleEngine(_rule_config())
    assert engine.evaluate(_job(
        job_title="Director - AI Infrastructure",
        job_description="Own cloud and infrastructure platform for AI")).accepted


def test_excluded_title_terms_are_config_extensible():
    engine = RuleEngine(_rule_config(excluded_title_terms=["blockchain"]))
    r = engine.evaluate(_job(job_title="Director - Blockchain",
                             job_description="Lead blockchain platform"))
    assert not r.accepted and r.reason == RejectionReason.DOMAIN_MISMATCH


def test_missing_salary_allowed():
    engine = RuleEngine(_rule_config())
    assert engine.evaluate(_job(salary="")).accepted


def test_salary_below_threshold_rejected():
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(salary="18 LPA"))
    assert not r.accepted and r.reason == RejectionReason.SALARY_BELOW_THRESHOLD


def test_salary_parsing():
    assert _parse_salary_to_inr("35 LPA") == 3_500_000
    assert _parse_salary_to_inr("1.2 Cr") == 12_000_000
    assert _parse_salary_to_inr("") is None
    assert _parse_salary_to_inr("competitive") is None


def test_experience_parsing():
    assert _parse_experience_min("15-20 years") == 15
    assert _parse_experience_min("18+ yrs") == 18
    assert _parse_experience_min("") is None


# ---- AI engine parsing / fallback (no network) ---------------------------

def test_ai_json_extraction_and_fallback():
    from careerpilot.ai.engine import AIEngine, _extract_json
    from careerpilot.ai.provider_base import AIProvider, AIProviderError, ProviderResponse
    from careerpilot.core.config import AIConfig

    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('garbage') == {}

    class Failing(AIProvider):
        name = "Failing"
        def is_available(self): return True
        def generate(self, prompt, *, timeout): raise AIProviderError("boom")

    class Working(AIProvider):
        name = "Working"
        def is_available(self): return True
        def generate(self, prompt, *, timeout):
            return ProviderResponse(
                text='{"match_score": 92, "career_profile": "Infrastructure", '
                     '"confidence": 85, "reason": "Strong match.", "apply": true}',
                tokens_used=10, model="fake")

    cfg = AIConfig(gemini_keys=[], gemini_model="m", deepseek_key="",
                   deepseek_model="d", request_timeout=5, max_retries=0,
                   min_apply_score=90)
    engine = AIEngine(cfg, "profile", ["Infrastructure", "GCC"],
                      default_profile="Infrastructure")
    engine.providers = [Failing(), Working()]  # first fails, second works
    result = engine.evaluate_job(_job())
    assert result.match_score == 92
    assert result.career_profile == "Infrastructure"
    assert result.confidence == 85
    assert result.apply is True
    assert result.provider == "Working"

    # Unknown profile name from AI is preserved (engine.select maps to default).
    class Unknown(AIProvider):
        name = "Unknown"
        def is_available(self): return True
        def generate(self, prompt, *, timeout):
            return ProviderResponse(
                text='{"match_score": 80, "career_profile": "Nonexistent", '
                     '"confidence": 30, "reason": "x", "apply": false}',
                tokens_used=5, model="fake")
    engine.providers = [Unknown()]
    r2 = engine.evaluate_job(_job())
    assert r2.career_profile == "Nonexistent"  # not invented away
    assert r2.confidence == 30


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
