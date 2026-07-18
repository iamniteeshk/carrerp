"""AI Engine -- the only module that talks to AI providers.

Responsibilities (P007): job evaluation (score + resume + reason + apply
decision), cover letters, and free-text screening answers. It tries Gemini
(all keys) then DeepSeek; if every provider fails it raises ``AIUnavailable``
so the caller can queue the job and retry next cycle -- the app never crashes
on AI failure.

Prompts request strict JSON to keep parsing robust and tokens low.
"""

from __future__ import annotations

import json
import time

from ..core.config import AIConfig
from ..core.logging_setup import get_logger
from ..core.models import AIEvaluation, Job
from .factory import build_providers
from .provider_base import AIProvider, AIProviderError

logger = get_logger(__name__)


class AIUnavailable(Exception):
    """Every provider failed; the request should be queued for retry."""


_EVAL_PROMPT = """You are screening ONE leadership job for ONE specific candidate.
Judge the WHOLE job against the WHOLE candidate profile -- never score on the
job title alone. Return ONLY a JSON object, no markdown, no prose.

Candidate profile (their real background -- this is the ground truth):
{profile}

Available career profiles (choose EXACTLY one by name): {profiles}

Job under review:
Title: {title}
Company: {company}
Location: {location}
Description:
{description}
Responsibilities:
{responsibilities}
Skills: {skills}

This candidate is an IT INFRASTRUCTURE / IT LEADERSHIP executive. Score by fit
to THAT background, not by the seniority word in the title.

STRONGLY PREFER (score high when the role is genuinely one of these):
- IT Infrastructure, Infrastructure Head/Director/Manager, Global/Enterprise IT
- End User Computing (EUC), Digital Workplace, Workplace Technology, Desktop
- Service Delivery, IT Service Delivery, IT Operations, ITSM, IT Transformation
- Internal/Regional/Global IT, Infrastructure Program Manager, Head IT
- Managed Services, Enterprise IT, GCC / Global Capability Centre IT leadership

SECONDARY (acceptable, score moderate): technology leadership, operations
leadership, shared services, infrastructure consulting.

STRONG PENALTY (score LOW, <30, and do not apply) -- these are the WRONG domain
even with a Director/Head title: AI Engineering, Machine Learning, LLMs, Data
Science, Python/Java/Cloud Developer, Software Engineer/Architect, Full Stack,
RTL, VLSI, Semiconductor, Embedded, QA/Testing, Marketing, Sales, Business
Development.

How to decide match_score (0-100), weigh ALL of these, not just the title:
- Domain fit vs the lists above -- this is the most important factor.
- Years of experience required vs the candidate's 25+ years.
- Leadership scope and team size (this candidate leads large teams/functions).
- Relevance to IT infrastructure, End User Computing, Digital Workplace, IT
  Service Delivery, Managed Services and GCC environments.
- Technologies & responsibilities: overlap with what the candidate actually did.
- Organisational/industry fit, location, and salary (if stated).

Seniority: BOOST genuine senior leadership (Head, Director, Senior/Associate
Director, VP/AVP/SVP, CIO/CTO, technology/service-delivery/infrastructure
leader). PENALISE individual-contributor and junior/entry roles.

CRITICAL: a hands-on software/developer/AI-ML role must score LOW even if its JD
mentions matching keywords (cloud, infrastructure, operations) -- keyword overlap
alone is NOT domain fit for an infrastructure LEADERSHIP candidate.

Scoring guide (be consistent, not generous):
- 85-100: strong fit -- senior IT-infrastructure/leadership role in-domain.
- 60-84 : relevant domain, some gaps.
- 40-59 : partly related; borderline.
- 0-39  : wrong domain, IC/junior level, or developer role -- do NOT apply.

Learned from this candidate's past strong matches (use as extra signal):
{learned}

Set "apply" true ONLY when it is a genuine, high-confidence fit in-domain.

Return JSON with this exact shape:
{{"match_score": <int 0-100, holistic fit per the guide above>,
"career_profile": "<one profile name from the list>",
"confidence": <int 0-100, how confident you are in that profile choice>,
"reason": "<<=3 sentences, cite the domain-fit reasoning>",
"apply": <true|false>}}
"""


class AIEngine:
    def __init__(self, config: AIConfig, candidate_profile: str,
                 profile_names: list[str], default_profile: str = ""):
        self.cfg = config
        self.profile = candidate_profile
        self.profile_names = profile_names
        self.default_profile = (
            default_profile or (profile_names[0] if profile_names else ""))
        # Provider-independent: built from config specs via the factory. The
        # active provider is tried first, the rest are fallbacks. No provider
        # names or models are hardcoded here.
        if getattr(config, "providers", None):
            self.providers: list[AIProvider] = build_providers(
                config.providers, config.active_provider)
        else:
            self.providers = []
        self.diag_recorder = None   # optional: set by main to log AI events
        # Optional digest of past strong matches (from GoodJobsStore.summary()),
        # injected into the evaluation prompt so scoring improves over time.
        self.learned_summary = ""

    def startup_validate(self) -> dict:
        """Validate/repair provider config at startup. For Gemini, resolves the
        model against the live list (auto-selecting a compatible Flash model if
        the configured one is gone). Never raises -- returns a status summary.
        """
        status: dict = {}
        for provider in self.providers:
            if not provider.is_available():
                status[provider.name] = "no key configured"
                continue
            resolve = getattr(provider, "resolve_model", None)
            if callable(resolve):
                try:
                    model = resolve()
                    status[provider.name] = f"ready (model={model})"
                except Exception as exc:  # noqa: BLE001
                    status[provider.name] = f"validation error: {exc}"
            else:
                status[provider.name] = "ready"
        logger.info("AI startup validation: %s", status)
        return status

    def any_available(self) -> bool:
        return any(p.is_available() for p in self.providers)

    def evaluate_job(self, job: Job) -> AIEvaluation:
        prompt = _EVAL_PROMPT.format(
            profile=self.profile,
            profiles=", ".join(self.profile_names),
            title=job.job_title,
            company=job.company,
            location=job.location,
            description=_truncate(job.job_description, 6000),
            responsibilities=_truncate(getattr(job, "responsibilities", ""), 2000),
            skills=", ".join(getattr(job, "skills", []) or [])[:1000],
            learned=(getattr(self, "learned_summary", "") or "(no history yet)"),
        )
        text, provider, model, tokens, elapsed = self._generate(prompt)
        data = _extract_json(text)

        career_profile = data.get("career_profile", "")
        confidence = float(data.get("confidence", 0))
        # The engine never invents a profile. If the name is unknown we keep it
        # as-is with the reported confidence; the CareerProfileEngine.select()
        # call downstream maps unknown/low-confidence choices to the default.
        if career_profile not in self.profile_names:
            logger.warning("AI returned unknown career profile '%s'", career_profile)

        return AIEvaluation(
            match_score=float(data.get("match_score", 0)),
            career_profile=career_profile or self.default_profile,
            confidence=confidence,
            reason=str(data.get("reason", ""))[:500],
            apply=bool(data.get("apply", False)),
            provider=provider, model=model, tokens_used=tokens,
            execution_time=elapsed, raw_response=text,
        )

    def generate_cover_letter(self, job: Job, profile_name: str) -> str:
        prompt = (
            f"Write a concise, professional cover letter (max 200 words) for "
            f"this leadership role. Focus on relevant leadership experience. "
            f"Avoid generic AI phrasing.\n\nCandidate:\n{self.profile}\n\n"
            f"Role: {job.job_title} at {job.company}\n"
            f"Resume angle: {profile_name}\n\n"
            f"Job description:\n{_truncate(job.job_description, 4000)}"
        )
        text, *_ = self._generate(prompt)
        return text.strip()

    def answer_screening_question(self, question: str, job: Job) -> str:
        prompt = (
            f"Answer this job application question concisely and factually as "
            f"the candidate. 2-4 sentences, professional, first person.\n\n"
            f"Candidate:\n{self.profile}\n\nRole: {job.job_title} at "
            f"{job.company}\n\nQuestion: {question}"
        )
        text, *_ = self._generate(prompt)
        return text.strip()

    # ---- provider orchestration -----------------------------------------

    def _generate(self, prompt: str) -> tuple[str, str, str, int, float]:
        last_error: Exception | None = None
        for provider in self.providers:
            if not provider.is_available():
                continue
            for attempt in range(self.cfg.max_retries + 1):
                start = time.time()
                try:
                    resp = provider.generate(prompt, timeout=self.cfg.request_timeout)
                    elapsed = time.time() - start
                    self._log_ai("success", provider.name, resp.model, elapsed,
                                 attempt, resp.tokens_used, resp.cost_usd)
                    return (resp.text, provider.name, resp.model,
                            resp.tokens_used, elapsed)
                except AIProviderError as exc:
                    elapsed = time.time() - start
                    last_error = exc
                    self._log_ai("failure", provider.name,
                                 getattr(provider, "model", ""), elapsed, attempt,
                                 reason=str(exc))
                    time.sleep(min(2 ** attempt, 5))
        raise AIUnavailable(f"All AI providers failed. Last error: {last_error}")

    def _log_ai(self, status: str, provider: str, model: str, elapsed: float,
                attempt: int, tokens: int = 0, cost=None, reason: str = "") -> None:
        msg = (f"AI {status} | provider={provider} | model={model} | "
               f"latency={int(elapsed*1000)}ms | retry={attempt} | "
               f"tokens={tokens} | cost={cost if cost is not None else 'n/a'}")
        if status == "success":
            logger.info(msg)
        else:
            logger.warning("%s | reason=%s", msg, reason)
        rec = self.diag_recorder
        if rec is not None:
            try:
                rec.record("ai_request", status=status, provider=provider,
                           model=model, latency_ms=int(elapsed * 1000),
                           retry=attempt, tokens=tokens, reason=reason)
            except Exception:  # noqa: BLE001
                pass
        # Persist for ops dashboard + runtime counters.
        try:
            hist = getattr(self, "history_service", None)
            if hist is not None:
                hist.record(
                    provider=provider, model=model or "", job_id=None,
                    purpose="generate", tokens_used=int(tokens or 0),
                    execution_time=float(elapsed),
                    success=(status == "success"))
        except Exception:  # noqa: BLE001
            pass
        try:
            from ..ops_dashboard.runtime import HUB
            from ..ops_dashboard.activity import emit
            HUB.note_ai(
                success=(status == "success"), tokens=int(tokens or 0),
                latency_ms=elapsed * 1000, retry=attempt,
                cost=float(cost) if cost is not None else None)
            if status != "success":
                emit(f"AI unavailable / failed ({provider}): {reason}",
                     level="error", category="ai")
        except Exception:  # noqa: BLE001
            pass

    # ---- developer tooling (models / health / benchmark) ----------------

    def discover_models(self) -> dict:
        """Connect to every enabled provider and list its models (ModelInfo)."""
        out: dict = {}
        for p in self.providers:
            if not p.is_available():
                out[p.name] = {"error": "no api key"}
                continue
            try:
                models = p.list_models(timeout=self.cfg.request_timeout)
                out[p.name] = {"models": [m.as_dict() for m in models]}
            except Exception as exc:  # noqa: BLE001
                out[p.name] = {"error": str(exc)}
        return out

    def health_all(self) -> list:
        return [p.health(timeout=self.cfg.request_timeout).as_dict()
                for p in self.providers]

    def benchmark(self, job: Job) -> list:
        """Run the same evaluation prompt against every enabled provider and
        compare time / tokens / resume choice / recommendation / confidence."""
        prompt = _EVAL_PROMPT.format(
            profile=self.profile, profiles=", ".join(self.profile_names),
            title=job.job_title, company=job.company, location=job.location,
            description=_truncate(job.job_description, 6000),
            responsibilities=_truncate(getattr(job, "responsibilities", ""), 2000),
            skills=", ".join(getattr(job, "skills", []) or [])[:1000],
            learned=(getattr(self, "learned_summary", "") or "(no history yet)"))
        results = []
        for p in self.providers:
            row = {"provider": p.name, "model": getattr(p, "model", "")}
            if not p.is_available():
                row["error"] = "no api key"
                results.append(row)
                continue
            start = time.time()
            try:
                resp = p.generate(prompt, timeout=self.cfg.request_timeout)
                data = _extract_json(resp.text)
                row.update(
                    response_time_ms=int((time.time() - start) * 1000),
                    tokens=resp.tokens_used, cost_usd=resp.cost_usd,
                    resume_selection=data.get("career_profile", ""),
                    recommendation="apply" if data.get("apply") else "skip",
                    match_score=data.get("match_score"),
                    confidence=data.get("confidence"))
            except Exception as exc:  # noqa: BLE001
                row["error"] = str(exc)
            results.append(row)
        return results


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " ...[truncated]"


def _extract_json(text: str) -> dict:
    """Parse JSON from a model response, tolerating ```json fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Could not parse AI JSON: %s", text[:200])
        return {}
