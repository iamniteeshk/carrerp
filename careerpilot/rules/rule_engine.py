"""Rule Engine -- deterministic, AI-free filtering (P006).

Answers one question: "Is this job worth sending to the AI?" Rules execute
cheapest-first and return the first matching rejection reason, so AI only ever
sees jobs that survive every rule. Everything is driven by ``RuleConfig`` --
no hardcoded thresholds, titles, or keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.config import RuleConfig
from ..core.enums import RejectionReason
from ..core.logging_setup import get_logger
from ..core.models import Job

logger = get_logger(__name__)

# Built-in off-domain terms used by the card-stage open/skip gate (prefilter).
# A card whose title contains one of these (and no accepted leadership term) is
# clearly not an IT-infrastructure / digital-workplace / GCC leadership role, so
# it is not worth opening. This is a denylist (FAIL-OPEN): anything NOT listed
# here is still opened and judged on the full JD. Tunable via rejected_titles.
OFF_DOMAIN_TERMS = {
    "cfo", "cmo", "chro", "chief financial", "finance", "financial", "accounts",
    "accounting", "audit", "taxation", "treasury", "sales", "presales",
    "business development", "marketing", "hospitality", "hotel", "chef",
    "culinary", "kitchen", "housekeeping", "nurse", "nursing", "doctor",
    "physician", "pharma", "medical", "clinical", "construction", "civil",
    "plant", "production", "mechanical", "legal", "lawyer", "advocate",
    "paralegal", "recruiter", "talent acquisition", "teacher", "professor",
    "faculty", "driver", "warehouse", "retail", "cashier", "beautician",
    "fashion", "interior", "real estate", "insurance agent",
    # Banking / HR / other clearly off-domain functions.
    "banking", "investment banking", "hr", "human resources", "human resource",
    "payroll", "procurement",
    # AI / ML / Data-Science research roles -- NOT this candidate's IT
    # infrastructure / digital-workplace / EUC / service-delivery domain.
    "ai", "ml", "artificial intelligence", "machine learning", "deep learning",
    "generative ai", "llm", "llms", "nlp", "prompt engineer", "data scientist",
    "data science", "data analyst", "computer vision", "ai engineer",
    "ml engineer",
    # Hands-on software engineering / hardware roles -- individual-contributor,
    # not IT-infrastructure leadership.
    "developer", "programmer", "software engineer", "software architect",
    "full stack", "fullstack", "full-stack", "frontend", "front end",
    "front-end", "backend", "back end", "back-end", "python developer",
    "java developer", "cloud developer", "web developer", "mobile developer",
    "qa engineer", "quality assurance", "sdet", "test engineer", "testing",
    "automation tester", "support engineer", "rtl", "vlsi", "semiconductor",
    "embedded", "firmware", "asic", "fpga", "device driver",
    # Creative / media / design roles (LinkedIn surfaces many of these).
    "video editor", "social media", "graphic designer", "graphics designer",
    "content writer", "copywriter", "photographer", "animator", "ux designer",
    "ui designer", "ui/ux", "designer", "ui", "ux", "coder", "tester",
}

# Junior / entry-level / individual-contributor seniority terms. A 25+ year
# Director-level candidate must never see these. They reject regardless of a
# domain keyword, UNLESS the title ALSO carries a strong senior leadership term
# (e.g. "Executive Director" keeps 'Director'; "IT Executive" does not).
JUNIOR_TERMS = {
    "intern", "internship", "graduate", "fresher", "entry level", "entry-level",
    "junior", "jr", "trainee", "apprentice", "associate engineer", "l1", "l2",
    "l1 engineer", "l2 engineer", "executive", "coordinator", "assistant",
}

# Strong, unambiguous senior leadership terms that "rescue" a title from the
# junior denylist above (and mark real seniority).
STRONG_SENIOR_TERMS = {
    "director", "head", "vp", "avp", "svp", "evp", "chief", "cio", "cto", "coo",
    "president", "managing director",
}

# Generic seniority / management words that are NOT domain signals. They appear
# in the profile keyword union but must NOT rescue an off-domain title (a title
# is only "borderline" if it carries a real DOMAIN keyword, not just 'Director').
GENERIC_TITLE_TERMS = {
    "director", "associate director", "head", "avp", "vp", "svp", "evp", "coo",
    "cio", "cto", "general manager", "gm", "manager", "senior", "lead", "chief",
    "leadership", "management", "strategy", "transformation", "operations",
}

# Weak / overloaded words that appear in many unrelated JDs. Alone they must NOT
# rescue an off-domain title (e.g. "Cloud Developer", "Sales Cloud Director").
WEAK_DOMAIN_KEYWORDS = {
    "cloud", "technology", "technologies", "tech", "it", "information technology",
    "digital", "enterprise", "global", "platform", "platforms", "systems",
    "solution", "solutions", "delivery", "service", "services", "support",
}

# Hard IC / wrong-domain title terms that are NEVER rescued by a domain keyword.
# "Cloud Developer" and "AI Infrastructure Engineer" must never become matches.
HARD_IC_TERMS = {
    "developer", "programmer", "software engineer", "software architect",
    "full stack", "fullstack", "full-stack", "frontend", "front end", "front-end",
    "backend", "back end", "back-end", "python developer", "java developer",
    "cloud developer", "web developer", "mobile developer", "qa engineer",
    "sdet", "test engineer", "automation tester", "data scientist",
    "data science", "data analyst", "ml engineer", "ai engineer",
    "prompt engineer", "machine learning", "deep learning", "generative ai",
    "video editor", "graphic designer", "graphics designer", "content writer",
    "copywriter", "ux designer", "ui designer", "coder", "tester",
    "sales", "marketing", "business development", "presales",
}


@dataclass
class RuleResult:
    accepted: bool
    reason: RejectionReason | None = None


class RuleEngine:
    """Applies deterministic rules in a fixed, cheapest-first order."""

    def __init__(self, config: RuleConfig):
        self.cfg = config

    def evaluate(self, job: Job) -> RuleResult:
        """Run all rules. The first failure wins; otherwise accept."""
        for rule in (
            self._portal_rule,
            self._salary_rule,
            self._experience_rule,
            self._employment_type_rule,
            self._shift_rule,
            self._location_rule,
            self._seniority_rule,
            self._title_rule,
            self._excluded_domain_rule,
            self._blacklist_rule,
            self._keyword_rule,
        ):
            result = rule(job)
            if not result.accepted:
                logger.info("Rejected '%s' @ %s: %s",
                            job.job_title, job.company, result.reason.value)
                return result
        return RuleResult(accepted=True)

    def prefilter(self, job: Job) -> RuleResult:
        """Cheap card-stage gate: decide ONLY whether a job is worth OPENING,
        from the card title. This is deliberately FAIL-OPEN: a job is opened
        unless its title clearly belongs to an unrelated domain (CFO, sales,
        finance, plant, medical, hotel, legal, ...). It must NEVER skip a job
        just because the title doesn't match an accepted phrase -- requiring an
        accepted-title match here is what caused 'never opened', since live card
        titles rarely contain the exact configured phrases. The real fit decision
        (matched/rejected) happens later on the COMPLETE JD via evaluate().
        """
        title = (job.job_title or "").lower().strip()
        if not title:
            return RuleResult(accepted=True)            # can't judge -> open

        # Junior / entry-level / IC titles are never worth opening for this
        # senior candidate (e.g. 'Fresher', 'Intern', 'IT Executive').
        if self._is_junior_title(title):
            logger.info("[prefilter] skip-open '%s' @ %s: junior/entry title",
                        job.job_title, job.company)
            return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)

        # Hard IC / sales / marketing titles are NEVER opened, even when a weak
        # domain word like 'Cloud' is also present ("Cloud Developer").
        if self._has_hard_ic_term(title):
            logger.info("[prefilter] skip-open '%s' @ %s: hard IC/off-domain title",
                        job.job_title, job.company)
            return RuleResult(False, RejectionReason.DOMAIN_MISMATCH)

        # Clearly off-domain -> skip opening even if a generic leadership word
        # (Director/Head) is present, UNLESS the title also carries a STRONG
        # domain keyword (borderline -> open and let the AI judge).
        if not self._title_has_strong_domain_keyword(title):
            for term in self._excluded_terms():
                if re.search(rf"\b{re.escape(term)}\b", title):
                    logger.info("[prefilter] skip-open '%s' @ %s: off-domain "
                                "term '%s'", job.job_title, job.company, term)
                    return RuleResult(False, RejectionReason.DOMAIN_MISMATCH)

        # Clearly relevant -> always open.
        if self._has_accepted_title(title):
            return RuleResult(accepted=True)

        # Blacklisted company -> skip opening (substring-aware).
        company = (job.company or "").strip().lower()
        if company:
            for raw in self.cfg.blacklist_companies or []:
                b = (raw or "").strip().lower()
                if b and (b == company or b in company or company in b):
                    logger.info("[prefilter] skip-open '%s' @ %s: blacklisted "
                                "company", job.job_title, job.company)
                    return RuleResult(False, RejectionReason.BLACKLISTED_COMPANY)

        # Configured rejected_titles (soft denylist) also skip opening.
        denylist = {t.lower() for t in self.cfg.rejected_titles}
        for term in denylist:
            if re.search(rf"\b{re.escape(term)}\b", title):
                logger.info("[prefilter] skip-open '%s' @ %s: off-domain term "
                            "'%s'", job.job_title, job.company, term)
                return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)

        # Not clearly relevant, but not clearly off-domain -> OPEN and let the
        # full-JD Rule/AI decide (fail-open).
        return RuleResult(accepted=True)

    # ---- individual rules ------------------------------------------------

    def _portal_rule(self, job: Job) -> RuleResult:
        from ..core.enums import Portal
        if job.portal not in {p.value for p in Portal}:
            return RuleResult(False, RejectionReason.PORTAL_NOT_ALLOWED)
        return RuleResult(True)

    def _salary_rule(self, job: Job) -> RuleResult:
        # Missing salary is allowed through (common for leadership roles).
        amount = _parse_salary_to_inr(job.salary)
        if amount is not None and self.cfg.minimum_salary > 0 \
                and amount < self.cfg.minimum_salary:
            return RuleResult(False, RejectionReason.SALARY_BELOW_THRESHOLD)
        return RuleResult(True)

    def _experience_rule(self, job: Job) -> RuleResult:
        years = _parse_experience_min(job.experience)
        if years is not None and years < self.cfg.minimum_experience:
            return RuleResult(False, RejectionReason.EXPERIENCE_MISMATCH)
        return RuleResult(True)

    def _employment_type_rule(self, job: Job) -> RuleResult:
        if not job.employment_type:
            return RuleResult(True)
        accepted = {t.lower() for t in self.cfg.accepted_employment_types}
        if job.employment_type.lower() not in accepted:
            return RuleResult(False, RejectionReason.WRONG_EMPLOYMENT_TYPE)
        return RuleResult(True)

    def _shift_rule(self, job: Job) -> RuleResult:
        if not job.shift:
            return RuleResult(True)
        rejected = {s.lower() for s in self.cfg.rejected_shifts}
        if job.shift.lower() in rejected:
            return RuleResult(False, RejectionReason.NIGHT_SHIFT)
        return RuleResult(True)

    def _location_rule(self, job: Job) -> RuleResult:
        if not job.location or not self.cfg.preferred_locations:
            return RuleResult(True)  # unknown/unconfigured -> let AI decide
        loc = job.location.lower()
        if any(pref.lower() in loc for pref in self.cfg.preferred_locations):
            return RuleResult(True)
        if "remote" in loc:
            return RuleResult(True)
        return RuleResult(False, RejectionReason.LOCATION_MISMATCH)

    def _is_junior_title(self, title_lower: str) -> bool:
        """True if the title is junior/entry-level/IC and NOT rescued by a strong
        senior leadership term (Director/Head/VP/Chief/CIO/CTO...)."""
        if not title_lower:
            return False
        for s in STRONG_SENIOR_TERMS:
            if re.search(rf"\b{re.escape(s)}\b", title_lower):
                return False
        for j in JUNIOR_TERMS:
            if re.search(rf"\b{re.escape(j)}\b", title_lower):
                return True
        return False

    def _seniority_rule(self, job: Job) -> RuleResult:
        """Reject junior / entry-level / IC titles for this senior candidate
        (e.g. 'Fresher', 'IT Executive', 'L1 Engineer') -- unless the title has a
        strong senior leadership term. Runs before the AI (saves tokens)."""
        if self._is_junior_title((job.job_title or "").lower().strip()):
            logger.info("Rejected '%s' @ %s: junior/entry-level title",
                        job.job_title, job.company)
            return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)
        return RuleResult(True)

    def _excluded_domain_rule(self, job: Job) -> RuleResult:
        """Hard off-domain gate that runs BEFORE the AI (saves tokens).

        A title containing a clearly off-domain term (finance, sales, AI/ML,
        data science, legal, medical, ...) is rejected REGARDLESS of a generic
        leadership word like 'Director'/'Head' -- that word alone must never
        rescue an off-domain role (the root cause of 'Director - AI' matching).

        Hard IC terms (developer, data scientist, ...) are NEVER rescued, even
        by a strong domain keyword. Weak words like 'Cloud' alone also cannot
        rescue an off-domain title. Only a STRONG domain keyword (Infrastructure,
        Digital Workplace, EUC, Service Delivery, ...) may keep a borderline
        title for the AI (e.g. 'Director - AI Infrastructure').
        """
        title = (job.job_title or "").lower().strip()
        if not title:
            return RuleResult(True)
        if self._has_hard_ic_term(title):
            logger.info("Rejected '%s' @ %s: hard IC/off-domain title",
                        job.job_title, job.company)
            return RuleResult(False, RejectionReason.DOMAIN_MISMATCH)
        if self._title_has_strong_domain_keyword(title):
            return RuleResult(True)
        for term in self._excluded_terms():
            if re.search(rf"\b{re.escape(term)}\b", title):
                logger.info("Rejected '%s' @ %s: off-domain title term '%s'",
                            job.job_title, job.company, term)
                return RuleResult(False, RejectionReason.DOMAIN_MISMATCH)
        return RuleResult(True)

    def _excluded_terms(self) -> set[str]:
        extra = getattr(self.cfg, "excluded_title_terms", None) or []
        return OFF_DOMAIN_TERMS | {t.lower().strip() for t in extra if t}

    def _has_hard_ic_term(self, title_lower: str) -> bool:
        for term in HARD_IC_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", title_lower):
                return True
        return False

    def _title_has_domain_keyword(self, title_lower: str) -> bool:
        """Backward-compatible alias for strong-domain rescue checks."""
        return self._title_has_strong_domain_keyword(title_lower)

    def _title_has_strong_domain_keyword(self, title_lower: str) -> bool:
        """True if the title carries a STRONG domain keyword (Infrastructure,
        Digital Workplace, EUC, ...). Generic seniority words and weak overloaded
        words (Cloud, Technology, Operations) do NOT count.
        """
        for kw in getattr(self.cfg, "required_keywords", None) or []:
            kw = kw.lower().strip()
            if not kw or kw in GENERIC_TITLE_TERMS or kw in WEAK_DOMAIN_KEYWORDS:
                continue
            if re.search(rf"\b{re.escape(kw)}\b", title_lower):
                return True
        # Explicit strong phrases that must always count even if not in profile.
        strong = {
            "infrastructure", "digital workplace", "euc", "end user computing",
            "it operations", "service delivery", "it service delivery",
            "managed services", "global it", "enterprise it", "gcc",
            "global capability", "workplace technology", "itsm",
            "data center", "datacenter",
        }
        for kw in strong:
            if re.search(rf"\b{re.escape(kw)}\b", title_lower):
                return True
        return False

    def _title_rule(self, job: Job) -> RuleResult:
        title = job.job_title.lower()
        if not title:
            return RuleResult(True)
        # Explicit rejects take priority (use word boundaries to avoid
        # 'engineering director' tripping the 'engineer' reject).
        for bad in self.cfg.rejected_titles:
            if re.search(rf"\b{re.escape(bad.lower())}\b", title):
                # ...unless an accepted leadership term is also present.
                if not self._has_accepted_title(title):
                    return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)
        if self.cfg.accepted_titles and not self._has_accepted_title(title):
            return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)
        return RuleResult(True)

    def _has_accepted_title(self, title_lower: str) -> bool:
        return any(good.lower() in title_lower for good in self.cfg.accepted_titles)

    def _blacklist_rule(self, job: Job) -> RuleResult:
        company = (job.company or "").strip().lower()
        if not company:
            return RuleResult(True)
        for raw in self.cfg.blacklist_companies or []:
            b = (raw or "").strip().lower()
            if not b:
                continue
            if b == company or b in company or company in b:
                return RuleResult(False, RejectionReason.BLACKLISTED_COMPANY)
        return RuleResult(True)

    def _keyword_rule(self, job: Job) -> RuleResult:
        if not self.cfg.required_keywords:
            return RuleResult(True)
        haystack = (f"{job.job_title} {job.job_description} "
                    f"{getattr(job, 'responsibilities', '')}").lower()
        if any(kw.lower() in haystack for kw in self.cfg.required_keywords):
            return RuleResult(True)
        return RuleResult(False, RejectionReason.DOMAIN_MISMATCH)


# ---- parsing helpers (deterministic, best-effort) ------------------------

def _parse_salary_to_inr(salary: str) -> int | None:
    """Best-effort parse of salary strings like '35 LPA', '₹40,00,000'.

    Returns annual INR, or None if it can't be determined (never rejects on
    inability to parse).
    """
    if not salary:
        return None
    s = salary.lower().replace(",", "").replace("₹", "").replace("inr", "")
    lpa = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lac)", s)
    if lpa:
        return int(float(lpa.group(1)) * 100_000)
    crore = re.search(r"(\d+(?:\.\d+)?)\s*(?:cr|crore)", s)
    if crore:
        return int(float(crore.group(1)) * 10_000_000)
    plain = re.search(r"(\d{6,})", s)  # a raw rupee figure
    if plain:
        return int(plain.group(1))
    return None


def _parse_experience_min(experience: str) -> int | None:
    """Extract the minimum years from strings like '15-20 years', '18+ yrs'."""
    if not experience:
        return None
    m = re.search(r"(\d+)", experience)
    return int(m.group(1)) if m else None
