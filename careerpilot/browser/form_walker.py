"""Walk a LinkedIn Easy Apply or Naukri apply dialog like a person.

Fills fields the candidate profile already answers, asks the supplied
answer function for anything else, and records every value. The Submit
button is never clicked here — the portal decides that from the apply mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.logging_setup import get_logger
from ..core.models import ScreeningAnswer
from .base_portal import ApplyOutcome

logger = get_logger(__name__)

# Markers let tests script page.evaluate without a real browser.
_SNAPSHOT_JS = r"""
() => {
  /*CP_SNAPSHOT*/
  const root = document.querySelector(
    '.jobs-easy-apply-modal, .jobs-easy-apply-content, #easyApplyModal, ' +
    '.chatbot_Drawer, .chatbot_MessageContainer, [role="dialog"]'
  ) || document.body;
  function labelFor(el) {
    if (el.id) {
      const lab = document.querySelector('label[for="' + el.id + '"]');
      if (lab && lab.innerText) return lab.innerText.trim();
    }
    const wrap = el.closest('div, li, fieldset');
    const lab = wrap && wrap.querySelector('label, span, legend');
    const text = (lab && lab.innerText) || el.getAttribute('aria-label')
      || el.getAttribute('name') || el.getAttribute('placeholder') || '';
    return String(text).trim();
  }
  const fields = [];
  root.querySelectorAll('input, textarea, select').forEach((el) => {
    const type = (el.type || '').toLowerCase();
    if (type === 'hidden' || el.disabled) return;
    const idx = fields.length;
    el.setAttribute('data-cp-field', String(idx));
    let options = [];
    if (el.tagName === 'SELECT') {
      options = Array.from(el.options).map(o => (o.text || '').trim()).filter(Boolean).slice(0, 30);
    }
    fields.push({
      idx: idx,
      label: labelFor(el).slice(0, 180),
      type: el.tagName === 'SELECT' ? 'select' : (type || 'text'),
      value: el.value || '',
      required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      options: options,
    });
  });
  const buttons = [];
  root.querySelectorAll('button, [role="button"]').forEach((el) => {
    const text = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    const idx = buttons.length;
    el.setAttribute('data-cp-btn', String(idx));
    buttons.push({idx: idx, text: text.slice(0, 80)});
  });
  return {fields: fields, buttons: buttons};
}
"""

_FILL_JS = r"""
(arg) => {
  /*CP_FILL*/
  const el = document.querySelector('[data-cp-field="' + arg.idx + '"]');
  if (!el) return false;
  const value = arg.value == null ? '' : String(arg.value);
  if (el.tagName === 'SELECT') {
    const want = value.toLowerCase();
    for (const opt of el.options) {
      const text = (opt.text || '').toLowerCase();
      if (text === want || text.indexOf(want) >= 0 || String(opt.value).toLowerCase() === want) {
        el.value = opt.value;
        el.dispatchEvent(new Event('change', {bubbles: true}));
        return true;
      }
    }
    return false;
  }
  const type = (el.type || '').toLowerCase();
  if (type === 'checkbox' || type === 'radio') {
    el.checked = true;
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (type === 'file') return false;
  el.focus();
  el.value = value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}
"""

_CLICK_JS = r"""
(idx) => {
  /*CP_CLICK*/
  const el = document.querySelector('[data-cp-btn="' + idx + '"]');
  if (!el) return false;
  el.click();
  return true;
}
"""

_OPEN_WORDS = ("easy apply", "apply now")
_NEXT_WORDS = ("next", "continue", "review your application", "review")
_SUBMIT_WORDS = ("submit application", "submit")


@dataclass
class FilledField:
    label: str
    value: str
    source: str  # candidate | profile | ai | file


@dataclass
class WalkResult:
    filled: list[FilledField] = field(default_factory=list)
    reached_submit: bool = False
    needs_review: bool = False
    note: str = ""

    def as_dicts(self) -> list[dict]:
        return [{"label": f.label, "value": f.value, "source": f.source}
                for f in self.filled]


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _button_kind(text: str, *, filled_any: bool, has_next: bool) -> str:
    t = _norm(text)
    if not t:
        return "other"
    if any(w in t for w in _NEXT_WORDS) and "submit" not in t:
        return "next"
    if any(w in t for w in _SUBMIT_WORDS):
        return "submit" if not has_next else "other"
    if t in _OPEN_WORDS or t.startswith("easy apply"):
        return "open"
    # Naukri's last step is often a plain Apply once the form is filled.
    if filled_any and not has_next and t in ("apply", "send"):
        return "submit"
    if t == "apply" or t.startswith("apply"):
        return "open"
    return "other"


def _candidate_answer(label: str, values: dict[str, str]) -> str:
    lab = _norm(label)
    if not lab:
        return ""
    if any(k in lab for k in ("first name", "firstname")):
        return (values.get("full_name") or "").split(" ")[0]
    if any(k in lab for k in ("last name", "surname", "family name")):
        parts = (values.get("full_name") or "").split(" ")
        return parts[-1] if len(parts) > 1 else ""
    mapping = (
        (("email",), "email"),
        (("phone", "mobile", "contact number"), "phone"),
        (("full name", "your name", "name"), "full_name"),
        (("current location", "location", "city"), "current_location"),
        (("current company", "company", "employer", "organization"), "current_company"),
        (("designation", "current title", "job title"), "current_designation"),
        (("total experience", "years of experience", "experience"), "total_experience"),
        (("expected ctc", "expected salary", "expected"), "expected_ctc"),
        (("current ctc", "current salary", "ctc", "salary"), "current_ctc"),
        (("notice",), "notice_period"),
        (("linkedin",), "linkedin_url"),
        (("work authorization", "authorised", "authorized", "visa"), "work_authorization"),
    )
    for keys, field_name in mapping:
        if any(k in lab for k in keys):
            return str(values.get(field_name) or "")
    if "relocat" in lab:
        return "Yes"
    return ""


def _snapshot(page) -> dict:
    try:
        data = page.evaluate(_SNAPSHOT_JS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Form snapshot failed: %s", exc)
        return {"fields": [], "buttons": []}
    if not isinstance(data, dict):
        return {"fields": [], "buttons": []}
    data.setdefault("fields", [])
    data.setdefault("buttons", [])
    return data


def _click_index(page, idx: int) -> bool:
    try:
        return bool(page.evaluate(_CLICK_JS, idx))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Form click failed: %s", exc)
        return False


def _fill_index(page, idx: int, value: str) -> bool:
    try:
        return bool(page.evaluate(_FILL_JS, {"idx": idx, "value": value}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Form fill failed: %s", exc)
        return False


def _pause(page, ms: int = 400) -> None:
    wait = getattr(page, "wait_for_timeout", None)
    if callable(wait):
        try:
            wait(ms)
        except Exception:  # noqa: BLE001
            pass


def click_visible_submit(page) -> bool:
    """Click the final Submit control if it is on screen. Returns False if not."""
    snap = _snapshot(page)
    buttons = snap.get("buttons") or []
    texts = [_norm(b.get("text", "")) for b in buttons]
    has_next = any(_button_kind(t, filled_any=True, has_next=False) == "next"
                   for t in texts)
    for button in buttons:
        kind = _button_kind(button.get("text", ""), filled_any=True, has_next=has_next)
        if kind == "submit":
            return _click_index(page, int(button.get("idx", -1)))
    return False


def walk_application(page, *, candidate, answer_fn, resume_path: str = "",
                     max_steps: int = 8) -> WalkResult:
    """Fill the open application up to, but not including, Submit."""
    result = WalkResult()
    seen_labels: set[str] = set()
    values = {}
    if candidate is not None and hasattr(candidate, "form_values"):
        values = {k: str(v or "") for k, v in candidate.form_values().items()}

    opened = False
    for step in range(max_steps):
        snap = _snapshot(page)
        fields = snap.get("fields") or []
        buttons = snap.get("buttons") or []
        button_texts = [b.get("text", "") for b in buttons]
        has_next = any(
            _button_kind(t, filled_any=bool(result.filled), has_next=False) == "next"
            for t in button_texts)

        if not fields and not opened:
            opener = next((b for b in buttons if _button_kind(
                b.get("text", ""), filled_any=False, has_next=False) == "open"), None)
            if opener is None:
                result.note = "apply dialog not found"
                result.needs_review = True
                return result
            if not _click_index(page, int(opener.get("idx", -1))):
                result.note = "could not open apply dialog"
                result.needs_review = True
                return result
            opened = True
            _pause(page, 700)
            continue

        for field_info in fields:
            label = field_info.get("label") or f"field {field_info.get('idx')}"
            current = str(field_info.get("value") or "").strip()
            ftype = (field_info.get("type") or "text").lower()
            if ftype == "file":
                if resume_path and hasattr(page, "locator"):
                    try:
                        page.locator(
                            f'[data-cp-field="{int(field_info.get("idx", 0))}"]'
                        ).set_input_files(resume_path)
                        result.filled.append(FilledField(label, resume_path, "file"))
                    except Exception as exc:  # noqa: BLE001
                        logger.info("Resume upload skipped (%s): %s", label, exc)
                        if field_info.get("required"):
                            result.needs_review = True
                            result.note = f"could not upload resume for {label}"
                            return result
                continue
            if label in seen_labels:
                continue
            if current:
                seen_labels.add(label)
                result.filled.append(FilledField(label, current, "profile"))
                continue
            answer = _candidate_answer(label, values)
            source = "candidate"
            if not answer and field_info.get("required") and callable(answer_fn):
                try:
                    answer = str(answer_fn(label) or "").strip()
                    source = "ai"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Screening answer failed for %s: %s", label, exc)
                    answer = ""
            if not answer:
                if field_info.get("required"):
                    result.needs_review = True
                    result.note = f"unanswered required field: {label}"
                    return result
                continue
            idx = int(field_info.get("idx", 0))
            if _fill_index(page, idx, answer):
                seen_labels.add(label)
                result.filled.append(FilledField(label, answer, source))
            elif field_info.get("required"):
                result.needs_review = True
                result.note = f"could not fill required field: {label}"
                return result

        submit_btn = next((b for b in buttons if _button_kind(
            b.get("text", ""), filled_any=bool(result.filled) or bool(fields),
            has_next=has_next) == "submit"), None)
        next_btn = next((b for b in buttons if _button_kind(
            b.get("text", ""), filled_any=bool(result.filled), has_next=False) == "next"),
            None)
        if next_btn is not None:
            if not _click_index(page, int(next_btn.get("idx", -1))):
                result.needs_review = True
                result.note = "could not advance the form"
                return result
            _pause(page, 600)
            continue
        if submit_btn is not None:
            result.reached_submit = True
            result.note = "stopped before submit"
            return result
        if not fields and not buttons:
            result.note = "apply dialog not found"
            result.needs_review = True
            return result
        result.note = "stopped before submit"
        result.reached_submit = False
        return result

    result.note = "form step limit reached"
    result.needs_review = True
    return result


def finish_application(portal, page, job, resume_path: str, answer_fn,
                       dry_run: bool, confirm_fn=None) -> ApplyOutcome:
    """Fill, optionally ask for approval, and click Submit only when allowed.

    ``submitted`` is True only after the Submit control was actually clicked.
    """
    evidence = getattr(portal, "apply_evidence", None)
    if evidence:
        evidence.capture(page, job, "01_opened_job")
    walked = walk_application(
        page, candidate=getattr(portal, "candidate", None),
        answer_fn=answer_fn, resume_path=resume_path or "")
    answers = [
        ScreeningAnswer(question=item.label, answer=item.value, source=item.source)
        for item in walked.filled
    ]
    filled = walked.as_dicts()
    if evidence:
        evidence.capture(page, job, "03_form_filled")

    note = walked.note or ""
    if walked.needs_review:
        note = "needs_review: " + (walked.note or "uncertain form")
    elif dry_run:
        note = "dry_run"
        if evidence:
            evidence.capture(page, job, "04_stop_before_apply")
        logger.info("DRY RUN: filled %s field(s), stopped before submit for %s @ %s",
                    len(filled), job.job_title, job.company)
    elif confirm_fn is not None:
        try:
            decision = confirm_fn(job, filled) or "wait"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Approval callback failed: %s", exc)
            decision = "wait"
        decision = str(decision).strip().lower()
        if decision != "proceed":
            note = f"approval:{decision}"
        elif click_visible_submit(page):
            note = "submitted"
        else:
            note = "awaiting_final_confirmation: submit button not found"
    elif click_visible_submit(page):
        note = "submitted"
    else:
        note = "awaiting_final_confirmation: submit button not found"

    shot = ""
    session = getattr(portal, "session", None)
    if session is not None and hasattr(session, "screenshot"):
        prefix = "dryrun" if dry_run else "apply"
        shot = session.screenshot(
            f"{session.profile_dir}/{prefix}_{getattr(job, 'source_id', None) or 'job'}.png")
    submitted = note == "submitted" and not dry_run
    return ApplyOutcome(
        submitted=submitted, screenshot_path=shot or "", answers=answers,
        note=note, filled=filled)
