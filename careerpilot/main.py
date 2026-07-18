"""CareerPilot entry point.

Startup sequence (P004): load+validate config -> logging -> database+migrations
-> Telegram -> browser portals -> AI -> scheduler -> dashboard. Config
validation fails fast before anything else starts.

Usage:
    py -m careerpilot.main run          # start scheduler + dashboard
    py -m careerpilot.main scan         # run a single scan and exit
    py -m careerpilot.main dashboard    # dashboard only
    py -m careerpilot.main check        # validate config + init DB, exit
    py -m careerpilot.main doctor       # pre-flight PASS/WARN/FAIL report
    py -m careerpilot.main doctor --fix  # repair safe issues, then report
    py -m careerpilot.main maintenance  # retention cleanup
    py -m careerpilot.main setup        # scaffold config/profiles/.env
"""

from __future__ import annotations

import signal
import sys
import threading
import os
from pathlib import Path

from .ai.engine import AIEngine
from .apply.auto_apply import AutoApplyEngine
from .browser.linkedin_portal import LinkedInPortal
from .browser.naukri_portal import NaukriPortal
from .browser.session import BrowserManager, BrowserSession
from .browser.visual_debug import VisualDebugger
from .browser.humanize import Humanizer
from .browser.job_detail import JobDetailExtractor
from .diagnostics import DiagnosticsToolkit
from .core.job_cache import JobCache
from .collectors.manager import CollectorManager
from .core.human_interaction import HumanInteractionEngine
from .core.config import AppConfig, ConfigError, load_config
from .core.document_manager import DocumentManager
from .core.doctor import run_doctor
from .core.enums import NotificationType, Portal
from .core.logging_setup import get_logger, setup_logging
from .core.pipeline import ScanPipeline
from .core.scheduler import Scheduler
from .dashboard.app import create_dashboard
from .ops_dashboard import start_ops_dashboard_thread
from .ops_dashboard.activity import FEED, emit
from .ops_dashboard.runtime import HUB
from .db.database import Database
from .db.services import (AIHistoryService, ApplicationService, FailedJobService,
                          JobService, NotificationService, ScanService)
from .notify.telegram_service import TelegramService
from .reports.csv_reporter import CSVReporter
from .rules.rule_engine import RuleEngine


class CareerPilot:
    """Composition root -- builds and wires all components."""

    def __init__(self, config: AppConfig):
        self.cfg = config
        self.logger = get_logger("main")
        self._sessions: list[BrowserSession] = []
        self._shutting_down = False

        self.db = Database(config.database_path)
        self.db.initialize()

        self.job_service = JobService(self.db)
        self.app_service = ApplicationService(self.db)
        self.ai_history = AIHistoryService(self.db)
        self.notif_service = NotificationService(self.db)
        self.failed_service = FailedJobService(self.db)
        self.scan_service = ScanService(self.db)

        self.telegram = TelegramService(
            config.telegram_token, config.telegram_chat_id, self.notif_service)

        self.ai = AIEngine(
            config.ai, candidate_profile=self._candidate_profile(),
            profile_names=config.profile_engine.names(),
            default_profile=config.default_career_profile)
        self.ai.history_service = self.ai_history

        self.portals = self._build_portals()
        # Route AI request logs into the Diagnostics recorder (read-only use of
        # the toolkit; the toolkit itself is unchanged).
        self.ai.diag_recorder = self.diagnostics.recorder
        # Search terms are the accepted leadership titles from config (profile-
        # driven domain matching happens later in the Rule Engine). No hardcoded
        # domain or profile names.
        self.human = HumanInteractionEngine(
            diagnostics_dir=config.screenshot_path,
            notify=lambda msg: self.telegram.send(
                NotificationType.APPROVAL_REQUEST, msg))
        self.collector = CollectorManager(
            list(self.portals.values()),
            keywords=(config.rules.search_keywords or config.rules.accepted_titles),
            locations=config.rules.preferred_locations,
            human=self.human)
        self.rules = RuleEngine(config.rules)
        self.reporter = CSVReporter(self.db, config.report_path)

        self.documents = DocumentManager(config.profile_engine)
        self.apply_engine = AutoApplyEngine(
            config, self.ai, self.portals, self.telegram,
            self.job_service, self.app_service, self.failed_service,
            profile_engine=config.profile_engine,
            document_manager=self.documents)

        self.pipeline = ScanPipeline(
            config, self.collector, self.rules, self.ai, self.apply_engine,
            self.job_service, self.scan_service, self.reporter,
            notifier=self.telegram)
        self.pipeline.status_sink = self.diagnostics.status
        self.pipeline.diagnostics = self.diagnostics

        # Learning + session memory (JSON stores next to the SQLite DB). These let
        # CareerPilot vary behaviour over time and improve scoring from history.
        from pathlib import Path as _Path
        from .core.learning import GoodJobsStore, SessionHistoryStore
        db_dir = _Path(config.database_path).parent
        self.good_jobs = GoodJobsStore(db_dir / "good_jobs.json")
        self.session_history = SessionHistoryStore(db_dir / "session_history.json")
        self.pipeline.good_jobs = self.good_jobs
        self.pipeline.session_history = self.session_history
        # Feed past strong matches into the AI prompt so scoring improves.
        try:
            self.ai.learned_summary = self.good_jobs.summary()
        except Exception:  # noqa: BLE001
            self.ai.learned_summary = ""

        self.scheduler = Scheduler(
            self.pipeline, config.scan_interval_hours, self.telegram,
            self.job_service, reporter=self.reporter,
            backup_path=config.backup_path,
            summary_hour=config.daily_summary_hour,
            maintenance_hour=getattr(config.retention, "maintenance_hour", 3),
            app_config=config)

        # Bind live runtime into the ops dashboard hub (read-only + controls).
        HUB.bind(
            config=config, db=self.db, scheduler=self.scheduler,
            browser=self.browser, ai=self.ai, pipeline=self.pipeline,
            diagnostics=self.diagnostics, telegram=self.telegram, app=self)
        FEED.bind_db(self.db)

    def _candidate_profile(self) -> str:
        return self.cfg.candidate.summary()

    def _build_portals(self) -> dict:
        # ONE Playwright instance for the whole process (see BrowserManager).
        self.browser = BrowserManager(self.cfg.browser)
        self.debugger = VisualDebugger(self.cfg.debug)
        self.humanizer = Humanizer(self.cfg.human)
        self.job_cache = JobCache()
        self.logger.info("Job cache ready (%s cached jobs)", len(self.job_cache))
        self.diagnostics = DiagnosticsToolkit(
            enabled=self.cfg.debug.visual_mode,
            base_dir=self.cfg.debug.evidence_dir)
        if self.diagnostics.enabled:
            self.logger.info("Diagnostics Toolkit ON (recorder + evidence + "
                             "export under %s/)", self.cfg.debug.evidence_dir)
        self.humanizer.recorder = self.diagnostics.recorder
        self.debugger.live_status = self.diagnostics.status
        self.detail_extractor = JobDetailExtractor(
            debugger=self.debugger, humanizer=self.humanizer,
            job_cache=self.job_cache, detail_config=self.cfg.portals_parse,
            diagnostics=self.diagnostics)
        if self.debugger.enabled:
            self.logger.info("Visual Debug Mode is ON (overlays, panel, evidence "
                             "under %s/)", self.cfg.debug.evidence_dir)
        ln_session = BrowserSession(Portal.LINKEDIN.value, self.browser)
        nk_session = BrowserSession(Portal.NAUKRI.value, self.browser)
        self._sessions = [ln_session, nk_session]
        portals = {
            Portal.LINKEDIN.value: LinkedInPortal(
                ln_session, self.cfg.candidate, self.cfg.apply.easy_apply_only,
                debugger=self.debugger, humanizer=self.humanizer,
                detail_extractor=self.detail_extractor,
                parse_config=self.cfg.portals_parse.get("linkedin")),
            Portal.NAUKRI.value: NaukriPortal(
                nk_session, self.cfg.candidate, debugger=self.debugger,
                humanizer=self.humanizer, detail_extractor=self.detail_extractor,
                parse_config=self.cfg.portals_parse.get("naukri")),
        }
        for portal in portals.values():
            portal.search_nationwide = self.cfg.rules.search_nationwide
            portal.search_include_recommended = (
                self.cfg.rules.search_include_recommended)
        return portals

    def run(self) -> None:
        self._install_signal_handlers()
        if not self._acquire_pid_lock():
            self.logger.error(
                "Another CareerPilot instance appears to be running "
                "(PID file %s). Stop it first or remove a stale PID file.",
                self._PID_FILE)
            sys.exit(4)
        from . import __version__
        from .core.startup_banner import build_banner
        from .core.win_events import EventKind, write_event
        banner = build_banner(self.cfg)
        self.logger.info("\n%s", banner)
        print(banner, flush=True)
        write_event(EventKind.STARTUP,
                    f"CareerPilot v{__version__} started (mode={self.cfg.apply.mode})")
        self.logger.info("Starting CareerPilot v%s (mode: %s)",
                         __version__, self.cfg.apply.mode)
        self.telegram.send(NotificationType.SYSTEM_STARTUP,
                           f"CareerPilot v{__version__} started "
                           f"(mode: {self.cfg.apply.mode})")
        # Validate/repair the AI model against the live API before scanning so a
        # stale Gemini model name is auto-corrected rather than 404-ing per job.
        self.ai.startup_validate()
        if not self.ai.any_available():
            self.logger.warning("No AI provider is configured/available; jobs "
                                 "that pass the Rule Engine will be QUEUED.")
            write_event(EventKind.AI, "No AI provider available at startup — "
                        "jobs will be QUEUED until keys/network recover")
        # Ops Mission Control (FastAPI) — LAN-ready by default (0.0.0.0:8006).
        start_ops_dashboard_thread(db=self.db, config=self.cfg)
        emit("CareerPilot started — ops dashboard online",
             level="success", category="system")
        self.logger.info("Ops dashboard at http://%s:%s",
                         self.cfg.dashboard_host, self.cfg.dashboard_port)
        # Optional legacy Flask read-only board on +1 port when explicitly enabled.
        if getattr(self.cfg, "dashboard_legacy_flask", False):
            legacy = create_dashboard(self.db, self.cfg.dashboard_refresh_seconds)
            legacy_port = int(self.cfg.dashboard_port) + 1
            threading.Thread(
                target=lambda: legacy.run(
                    host="127.0.0.1", port=legacy_port,
                    debug=False, use_reloader=False),
                daemon=True).start()
            self.logger.info("Legacy Flask dashboard at http://127.0.0.1:%s",
                             legacy_port)
        self.scheduler.start(run_immediately=True)
        try:
            threading.Event().wait()  # keep main thread alive
        except KeyboardInterrupt:
            self.shutdown()

    _PID_FILE = Path("careerpilot.pid")

    def _acquire_pid_lock(self) -> bool:
        """Write PID file only if no other live process owns it."""
        try:
            if self._PID_FILE.exists():
                raw = self._PID_FILE.read_text(encoding="utf-8").strip()
                try:
                    old_pid = int(raw)
                except ValueError:
                    old_pid = -1
                if old_pid > 0:
                    try:
                        os.kill(old_pid, 0)
                        # Process exists — refuse to start a second instance.
                        return False
                    except OSError:
                        # Stale PID file; replace it.
                        self.logger.warning(
                            "Removing stale PID file (process %s not running)",
                            old_pid)
            self._PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except OSError as exc:
            self.logger.warning("Could not write PID file: %s", exc)
            return True  # do not block startup on filesystem issues

    def _write_pid_file(self) -> None:
        self._acquire_pid_lock()

    def _remove_pid_file(self) -> None:
        try:
            if self._PID_FILE.exists():
                # Only remove if it still points at us.
                try:
                    if int(self._PID_FILE.read_text(encoding="utf-8").strip()) == os.getpid():
                        self._PID_FILE.unlink()
                except (ValueError, OSError):
                    self._PID_FILE.unlink(missing_ok=True)
        except OSError as exc:
            self.logger.warning("Could not remove PID file: %s", exc)

    def _install_signal_handlers(self) -> None:
        import atexit

        def handler(signum, _frame):
            self.logger.info("Received signal %s; shutting down gracefully", signum)
            self.shutdown()
            sys.exit(0)

        def _atexit():
            # Windows logoff / process teardown — best-effort flush.
            try:
                self.shutdown()
            except Exception:  # noqa: BLE001
                pass

        atexit.register(_atexit)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass  # not on main thread / unsupported platform
        # Windows console close (best-effort).
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, handler)
            except (ValueError, OSError):
                pass
    def _log_effective_config(self) -> None:
        from . import __version__ as _pkg_ver
        c = self.cfg
        prov = getattr(c.ai, "active_provider", "") or "(none)"
        model = ""
        for p in getattr(self.ai, "providers", []):
            if p.name.lower() == prov.lower():
                model = getattr(p, "model", "") or "(discover)"
                break
        portals = ",".join(self.portals.keys()) if self.portals else "(none)"
        # Prove the job-opening path is actually wired -- the #1 source of the
        # "never opened" symptom. If open_jobs is on but no reader is attached,
        # or open_jobs is off, say so LOUDLY.
        reader_ok = self.detail_extractor is not None
        open_path = "READY" if (c.browser.open_jobs and reader_ok) else (
            "DISABLED (browser.open_jobs=false)" if not c.browser.open_jobs
            else "BROKEN (no detail reader wired)")
        banner = (
            "\n========== EFFECTIVE CONFIG ==========\n"
            f"package version   = {_pkg_ver}\n"
            f"config file       = {getattr(c, 'source_path', 'config/config.yaml')}\n"
            f"database path     = {os.path.abspath(c.database_path)}\n"
            f"reports path      = {os.path.abspath(c.report_path)}\n"
            f"screenshots path  = {os.path.abspath(c.screenshot_path)}\n"
            f"logs path         = {os.path.abspath(c.log_path)}\n"
            f"browser profiles  = {os.path.abspath(c.browser.profiles_path)}\n"
            f"browser.open_jobs = {c.browser.open_jobs}\n"
            f"job-open path     = {open_path}\n"
            f"debug.visual_mode = {c.debug.visual_mode}\n"
            f"apply.mode        = {c.apply.mode}\n"
            f"portals           = {portals}\n"
            f"search titles     = {', '.join((c.rules.search_keywords or c.rules.accepted_titles)[:6])}"
            f"{' ...' if len(c.rules.search_keywords or c.rules.accepted_titles) > 6 else ''}\n"
            f"locations (order) = {', '.join(c.rules.preferred_locations) or '(any)'}\n"
            f"AI Provider       = {prov}\n"
            f"AI Model          = {model or '(resolved at first call)'}\n"
            "======================================")
        self.logger.info(banner)
        if open_path != "READY":
            self.logger.warning("JOB-OPEN PATH %s -- jobs will not be read in "
                                "full; decisions will be Partial Data. Fix this "
                                "before a production run.", open_path)

    def scan_once(self) -> dict[str, int]:
        from .core.startup_banner import build_banner
        banner = build_banner(self.cfg)
        self.logger.info("\n%s", banner)
        print(banner, flush=True)
        self._log_effective_config()
        return self.pipeline.run_once()

    def run_dashboard(self) -> None:
        """Run the ops dashboard only (no scheduler). Blocks."""
        import uvicorn
        from .ops_dashboard.app import create_ops_dashboard
        HUB.bind(
            config=self.cfg, db=self.db, scheduler=self.scheduler,
            browser=self.browser, ai=self.ai, pipeline=self.pipeline,
            diagnostics=self.diagnostics, telegram=self.telegram, app=self)
        FEED.bind_db(self.db)
        app = create_ops_dashboard(db=self.db, config=self.cfg)
        uvicorn.run(
            app, host=app.state.bind_host, port=app.state.bind_port,
            log_level="info")

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.logger.info("Shutting down CareerPilot")
        try:
            from .core.win_events import EventKind, write_event
            write_event(EventKind.SHUTDOWN, "Graceful shutdown started")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.scheduler.shutdown()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Scheduler shutdown error: %s", exc)
        for session in self._sessions:
            try:
                session.close()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Session cleanup error: %s", exc)
        try:
            self.browser.close_all()  # stop the single Playwright instance
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Browser manager cleanup error: %s", exc)
        try:
            self.telegram.send(NotificationType.SYSTEM_SHUTDOWN, "CareerPilot stopped")
        except Exception:  # noqa: BLE001
            pass
        # Flush DB (commit + close) before releasing the PID lock.
        try:
            self.db.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Database close error: %s", exc)
        self._remove_pid_file()
        self.logger.info("Shutdown complete (browser closed, DB flushed, PID released)")


def _ai_engine_for_cli():
    """Build a standalone AI Engine from config for the AI dev commands."""
    from .ai.engine import AIEngine
    cfg = load_config()
    names = cfg.profile_engine.names()
    return cfg, AIEngine(cfg.ai, candidate_profile="(cli)", profile_names=names,
                         default_profile=cfg.default_career_profile)


def _cmd_models() -> int:
    import csv
    import json as _json
    from pathlib import Path
    try:
        cfg, engine = _ai_engine_for_cli()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not load config: {exc}", file=sys.stderr)
        return 1
    discovered = engine.discover_models()
    Path("reports").mkdir(exist_ok=True)
    rows = []
    print(f"Active provider: {cfg.ai.active_provider}\n")
    for provider, info in discovered.items():
        if "error" in info:
            print(f"{provider}: ERROR -- {info['error']}")
            continue
        models = info.get("models", [])
        print(f"{provider} ({len(models)} models):")
        print(f"  {'MODEL':<34} {'CTX':>9}  CHAT VISN TOOL  DEPRECATED")
        for m in models:
            ctx = m.get("context_window")
            print(f"  {m['name']:<34} {str(ctx) if ctx else '-':>9}  "
                  f"{'yes' if m['supports_chat'] else 'no ':>4} "
                  f"{'yes' if m['supports_vision'] else 'no ':>4} "
                  f"{'yes' if m['supports_tools'] else 'no ':>4}  "
                  f"{'DEPRECATED' if m['deprecated'] else 'active'}")
            rows.append({"provider": provider, **m})
        print()
    Path("reports/models.json").write_text(_json.dumps(discovered, indent=2))
    with open("reports/models.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["provider", "name", "context_window",
                                           "supports_chat", "supports_vision",
                                           "supports_tools", "deprecated"])
        w.writeheader()
        w.writerows(rows)
    print("Exported -> reports/models.json, reports/models.csv")
    return 0


def _cmd_ai_health() -> int:
    try:
        _cfg, engine = _ai_engine_for_cli()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not load config: {exc}", file=sys.stderr)
        return 1
    print(f"{'PROVIDER':<12} {'REACH':<6} {'AUTH':<6} {'LATENCY':<9} "
          f"{'MODELS':<7} {'MODEL':<26} RECOMMENDATION")
    for h in engine.health_all():
        lat = f"{h['latency_ms']}ms" if h.get("latency_ms") is not None else "-"
        print(f"{h['provider']:<12} "
              f"{'yes' if h['reachable'] else 'no':<6} "
              f"{'yes' if h['authenticated'] else 'no':<6} {lat:<9} "
              f"{h['models_available']:<7} {(h.get('current_model') or '-'):<26} "
              f"{h.get('recommendation') or h.get('error') or ''}")
    return 0


def _cmd_benchmark_ai() -> int:
    import json as _json
    from pathlib import Path
    from .core.models import Job
    try:
        _cfg, engine = _ai_engine_for_cli()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not load config: {exc}", file=sys.stderr)
        return 1
    sample = Job(
        portal="benchmark", job_title="Director - Global IT Infrastructure",
        company="Acme Manufacturing", location="Chennai",
        job_url="https://example.com/benchmark",
        job_description=("Lead global infrastructure across data centres and "
                         "cloud for a manufacturing enterprise. 18+ years, large "
                         "team leadership, P&L ownership, vendor governance."))
    results = engine.benchmark(sample)
    print(f"{'PROVIDER':<12} {'TIME':<9} {'TOKENS':<8} {'RESUME':<18} "
          f"{'REC':<6} {'SCORE':<6} CONFID")
    for r in results:
        if "error" in r:
            print(f"{r['provider']:<12} ERROR -- {r['error']}")
            continue
        print(f"{r['provider']:<12} {str(r.get('response_time_ms','?'))+'ms':<9} "
              f"{str(r.get('tokens','?')):<8} "
              f"{str(r.get('resume_selection',''))[:18]:<18} "
              f"{r.get('recommendation',''):<6} "
              f"{str(r.get('match_score','')):<6} {r.get('confidence','')}")
    Path("reports").mkdir(exist_ok=True)
    Path("reports/benchmark.json").write_text(_json.dumps(results, indent=2))
    print("\nExported -> reports/benchmark.json")
    return 0


def _matching_subselector(card, full_selector: str) -> str:
    """Which specific comma-separated part of a multi-selector actually matched
    this element (e.g. 'div.srp-jobtuple-wrapper, article.jobTuple' -> tells you
    which one). Falls back to the full configured string if it can't tell."""
    parts = [s.strip() for s in full_selector.split(",") if s.strip()]
    for part in parts:
        try:
            if card.evaluate("(el, sel) => el.matches(sel)", part):
                return part
        except Exception:  # noqa: BLE001
            continue
    return full_selector


def _diagnostic_click_stages(page, job, title_selector: str, *,
                             jd_container_selector: str = "",
                             jd_description_selector: str = "",
                             humanizer=None, timeout_ms: int = 5000) -> dict:
    """Granular, stage-by-stage version of the open/click workflow, used ONLY
    by probe-open for diagnosis. Deliberately separate from the production
    click_job_card() (base_portal.py) so this diagnostic tool can never affect
    or risk the already-verified live pipeline -- it re-implements the same
    steps but reports each one individually: Visible / Clickable / Hover /
    Mouse Move / DOM Click / Navigation / JD Loaded / Extractor. A single
    collapsed 'clicked: yes/no' hides which of these actually failed; this
    doesn't.
    """
    from .core.logging_setup import get_logger
    _log = get_logger("careerpilot.probe")
    title = (getattr(job, "job_title", "") or "").strip()
    url = getattr(job, "job_url", "") or ""
    stages = {"visible": "SKIPPED", "clickable": "SKIPPED", "hover": "SKIPPED",
              "mouse_move": "SKIPPED", "dom_click": "SKIPPED",
              "navigation": "SKIPPED", "jd_loaded": "SKIPPED",
              "extractor": "SKIPPED"}

    target = None
    try:
        locator = page.locator(title_selector)
        count = locator.count()
        if url:
            for i in range(count):
                el = locator.nth(i)
                try:
                    href = el.get_attribute("href") or ""
                except Exception:  # noqa: BLE001
                    href = ""
                if href and (href == url or href in url or url.endswith(href)):
                    target = el
                    break
        if target is None and title:
            filtered = locator.filter(has_text=title)
            if filtered.count() > 0:
                target = filtered.first
    except Exception as exc:  # noqa: BLE001
        _log.debug("probe locate failed: %s", exc)

    if target is None:
        stages["visible"] = "NOT FOUND"
        stages["clickable"] = "NOT FOUND"
        return stages

    try:
        stages["visible"] = "YES" if target.is_visible() else "NO"
    except Exception as exc:  # noqa: BLE001
        stages["visible"] = f"UNKNOWN ({exc})"

    box = None
    try:
        target.scroll_into_view_if_needed(timeout=timeout_ms)
        box = target.bounding_box()
        enabled = target.is_enabled()
        stages["clickable"] = "YES" if (box and enabled) else "NO"
    except Exception as exc:  # noqa: BLE001
        stages["clickable"] = f"FAIL ({exc})"

    if not box:
        return stages

    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pre_url = page.url

    try:
        if humanizer is not None and humanizer.enabled:
            humanizer.move_mouse(page, cx, cy)
            page.wait_for_timeout(150)
            stages["mouse_move"] = "SUCCESS"
        else:
            stages["mouse_move"] = "SKIPPED (humanizer disabled)"
    except Exception as exc:  # noqa: BLE001
        stages["mouse_move"] = f"FAIL ({exc})"

    try:
        target.hover(timeout=timeout_ms)
        page.wait_for_timeout(150)
        stages["hover"] = "SUCCESS"
    except Exception as exc:  # noqa: BLE001
        stages["hover"] = f"FAIL ({exc})"

    try:
        target.click(timeout=timeout_ms)
        stages["dom_click"] = "SUCCESS"
    except Exception as exc:  # noqa: BLE001 -- a navigating frame can throw here
        stages["dom_click"] = f"FAIL ({exc})"

    navigated = False
    for _ in range(max(1, timeout_ms // 200)):
        try:
            if page.url != pre_url:
                navigated = True
                break
        except Exception:  # noqa: BLE001 -- mid-navigation counts as navigated
            navigated = True
            break
        page.wait_for_timeout(200)
    stages["navigation"] = "SUCCESS" if navigated else "FAIL (URL did not change)"

    if not navigated:
        return stages

    if jd_container_selector:
        try:
            page.wait_for_selector(jd_container_selector, timeout=timeout_ms,
                                   state="attached")
            stages["jd_loaded"] = "SUCCESS"
        except Exception as exc:  # noqa: BLE001
            stages["jd_loaded"] = f"FAIL ({exc})"
    else:
        stages["jd_loaded"] = "SKIPPED (no JD container selector configured)"

    if jd_description_selector:
        try:
            from .browser.job_detail import _MIN_JD_CHARS
            el = page.query_selector(jd_description_selector)
            text = el.inner_text().strip() if el else ""
            stages["extractor"] = ("SUCCESS" if len(text) >= _MIN_JD_CHARS else
                                   f"FAIL (only {len(text)} chars, need "
                                   f"{_MIN_JD_CHARS})")
        except Exception as exc:  # noqa: BLE001
            stages["extractor"] = f"FAIL ({exc})"
    else:
        stages["extractor"] = "SKIPPED (no description selector configured)"

    return stages


def _cmd_probe_open(pilot, argv: list[str]) -> int:
    """One-page, few-second diagnostic: opens ONE search page for ONE portal,
    looks at the first few real cards, and prints IN PLAIN TEXT exactly what
    each stage saw -- no log-hunting required. This exists because repeated
    fixes verified against local fixtures have not resolved a live 'never opens
    a job description' report; this command gets real ground truth from the
    actual site in one short run so the fix can be evidence-based, not another
    guess.

    Usage: python -m careerpilot.main probe-open [naukri|linkedin] [n]
    """
    from .core.enums import Portal
    from .browser.base_portal import navigate, wait_for_ready

    portal_name = argv[1] if len(argv) > 1 else Portal.NAUKRI.value
    n = int(argv[2]) if len(argv) > 2 else 3
    pilot._build_portals()
    portal = pilot.portals.get(portal_name)
    if portal is None:
        print(f"Unknown portal '{portal_name}'. Try: naukri or linkedin",
              file=sys.stderr)
        return 1

    cfg = pilot.cfg
    keywords = cfg.rules.search_keywords or cfg.rules.accepted_titles
    locations = cfg.rules.preferred_locations
    kw = keywords[0] if keywords else "Director"
    loc = locations[0] if locations else ""
    url = portal._search_url(kw, loc)
    page = portal.session.page

    print(f"\n===== PROBE-OPEN: {portal_name} =====")
    print(f"Search URL : {url}")
    navigate(page, url, reason="probe-open")
    rsel = portal._results_selector()
    print(f"Card selector configured : {rsel!r}")
    wait_for_ready(page, networkidle_timeout_ms=cfg.browser.networkidle_timeout_ms,
                   render_settle_ms=cfg.browser.render_settle_ms,
                   results_selector=rsel, reason="probe-open results")
    try:
        cards = page.query_selector_all(rsel)
    except Exception as exc:  # noqa: BLE001
        print(f"CARD SELECTOR FAILED: {exc}")
        cards = []
    print(f"Cards found on page (raw DOM count) : {len(cards)}")
    if not cards:
        print("\n>>> DIAGNOSIS: the card selector matched ZERO elements. This "
              "means the results-page selector in config.yaml -> portals -> "
              f"{portal_name} -> results_selector no longer matches the live "
              "page. This is the most likely reason nothing ever opens.")
        return 0

    title_sel = portal.field_selectors.get("title", "")
    url_sel = portal.field_selectors.get("url") or title_sel
    print(f"Title selector (scoped to card) : {title_sel!r}")
    print(f"URL/href selector (scoped to card) : {url_sel!r}\n")

    jobs = portal._parse_result_cards(page)
    print(f"Cards successfully parsed into Job objects : {len(jobs)} / {len(cards)}")
    if len(jobs) < len(cards):
        print(">>> DIAGNOSIS: some cards were dropped because title or href "
              "extraction returned empty (see per-card detail below).")
    print()
    detail_sel = (portal.detail_extractor._selectors(portal_name)
                 if portal.detail_extractor is not None else {})
    jd_container_sel = detail_sel.get("container", "")
    jd_description_sel = detail_sel.get("description", "")

    for i in range(min(n, len(cards))):
        # Re-query fresh each time: after a click+go_back the previous card
        # ElementHandles are stale/detached (the DOM was recreated).
        fresh_cards = page.query_selector_all(rsel)
        if i >= len(fresh_cards):
            break
        card = fresh_cards[i]
        matched_sub = _matching_subselector(card, rsel)
        title_el = card.query_selector(title_sel) if title_sel else None
        title = title_el.inner_text().strip() if title_el else "(not found)"
        href_el = card.query_selector(url_sel) if url_sel else None
        href = href_el.get_attribute("href") if href_el else None

        print(f"Card #{i + 1}\n")
        print(f"Selector:\n{matched_sub}\n")
        print(f"Title:\n{title}\n")
        print(f"URL:\n{href or '(none)'}\n")

        if not href:
            print("Pre-filter:\nN/A -- no href extracted, card was never "
                  "collected\n")
            print("Visible:\nSKIPPED\n\nClickable:\nSKIPPED\n\nHover:\n"
                  "SKIPPED\n\nMouse Move:\nSKIPPED\n\nDOM Click:\nSKIPPED\n\n"
                  "Navigation:\nSKIPPED\n\nJD Loaded:\nSKIPPED\n\n"
                  "Extractor:\nSKIPPED\n")
            print("-" * 40 + "\n")
            continue

        job = None
        try:
            from .core.models import Job as _Job
            job = _Job(portal=portal_name, job_title=title, job_url=href)
        except Exception:  # noqa: BLE001
            pass

        prefilter_result = pilot.rules.prefilter(job) if job else None
        if prefilter_result is not None:
            pf = ("OPEN" if prefilter_result.accepted else
                  f"SKIP ({prefilter_result.reason.value})")
            print(f"Pre-filter:\n{pf}\n")
            if not prefilter_result.accepted:
                print("Visible:\nSKIPPED (pre-filter rejected)\n\n"
                      "Clickable:\nSKIPPED\n\nHover:\nSKIPPED\n\n"
                      "Mouse Move:\nSKIPPED\n\nDOM Click:\nSKIPPED\n\n"
                      "Navigation:\nSKIPPED\n\nJD Loaded:\nSKIPPED\n\n"
                      "Extractor:\nSKIPPED\n")
                print("-" * 40 + "\n")
                continue

        stages = _diagnostic_click_stages(
            page, job, title_sel,
            jd_container_selector=jd_container_sel,
            jd_description_selector=jd_description_sel,
            humanizer=pilot.humanizer)

        print(f"Visible:\n{stages['visible']}\n")
        print(f"Clickable:\n{stages['clickable']}\n")
        print(f"Hover:\n{stages['hover']}\n")
        print(f"Mouse Move:\n{stages['mouse_move']}\n")
        print(f"DOM Click:\n{stages['dom_click']}\n")
        print(f"Navigation:\n{stages['navigation']}\n")
        print(f"JD Loaded:\n{stages['jd_loaded']}\n")
        print(f"Extractor:\n{stages['extractor']}\n")
        print("-" * 40 + "\n")

        # Return to the results page for the next card, same as production.
        if stages["navigation"] == "SUCCESS":
            try:
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_timeout(300)
            except Exception as exc:  # noqa: BLE001
                print(f"(go_back failed: {exc} -- re-navigating to search URL)\n")
                navigate(page, url, reason="probe-open recover", force=True)
    print("===== END PROBE — copy everything above this line back into chat "
          "=====\n")
    return 0


def _bootstrap_config() -> None:
    """On a fresh install the ZIP ships NO runtime data and NO personal config,
    only *.example templates. Create the real config + profiles from the examples
    on first run so the app runs directly, and tell the user to review them."""
    import shutil
    # 1) config/config.yaml from config.example.yaml (includes candidate section)
    target = os.path.join("config", "config.yaml")
    if not os.path.exists(target):
        example = None
        for cand in ("config.example.yaml",
                     os.path.join("config", "config.example.yaml")):
            if os.path.exists(cand):
                example = cand
                break
        if example:
            os.makedirs("config", exist_ok=True)
            shutil.copyfile(example, target)
            print(f"[first-run] Created {target} from {example}. Review your "
                  f"search_keywords, accepted_titles, locations and AI keys.")
    # 2) profiles/ from profiles.example/ (career-profile templates)
    if not os.path.isdir("profiles") and os.path.isdir("profiles.example"):
        shutil.copytree("profiles.example", "profiles")
        print("[first-run] Created profiles/ from profiles.example/. Edit these "
              "with your real experience before a live run.")
    # 3) .env from .env.example (AI keys) -- optional; app runs without it
    if not os.path.exists(".env") and os.path.exists(".env.example"):
        shutil.copyfile(".env.example", ".env")
        print("[first-run] Created .env from .env.example. Add your AI API key "
              "to enable matching.")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    command = argv[0] if argv else "run"

    from .core.bootstrap import ensure_scaffold

    # 'setup' explicitly scaffolds a fresh clone, then points the user onward.
    if command == "setup":
        actions = ensure_scaffold()
        if actions:
            print("CareerPilot setup complete:")
            for a in actions:
                print(f"  - {a}")
        else:
            print("Nothing to do -- already set up.")
        print("\nNext steps:")
        print("  1. Edit config/config.yaml -> set your real candidate details "
              "(name, email, phone) and rules.")
        print("  2. Put your resume.pdf in each profiles/<Name>/ folder.")
        print("  3. Add API keys to .env")
        print("  4. py -m careerpilot.main doctor")
        return 0

    # Auto-bootstrap on first run so the project is clone-and-run even without
    # an explicit 'setup'. Never overwrites existing files.
    ensure_scaffold()

    # 'models' connects to every enabled provider, lists their models with
    # metadata, and exports reports/models.json + reports/models.csv.
    if command == "models":
        return _cmd_models()
    if command == "ai-health":
        return _cmd_ai_health()
    if command == "benchmark-ai":
        return _cmd_benchmark_ai()

    # The doctor must run even when config is broken -- that's its job.
    if command == "doctor":
        _bootstrap_config()   # a fresh install has only *.example templates
        fix = "--fix" in argv or "-f" in argv
        production = "--production" in argv
        return 0 if run_doctor(fix=fix, production=production) else 3

    _bootstrap_config()
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}\nRun 'py -m careerpilot.main doctor' "
              f"for a full diagnostic.", file=sys.stderr)
        return 2

    import logging as _logging
    setup_logging(config.log_path,
                  level=getattr(_logging, config.log_level, _logging.INFO))
    logger = get_logger("main")

    if command == "check":
        db = Database(config.database_path)
        db.initialize()
        db.close()
        logger.info("Config valid and database initialized. All checks passed.")
        return 0

    pilot = CareerPilot(config)
    if command == "run":
        # Fail fast: a mandatory doctor failure must not reach live operation.
        if not run_doctor():
            print("Doctor reported mandatory failures. Aborting startup.",
                  file=sys.stderr)
            return 3
        pilot.run()
    elif command == "scan":
        pilot.scan_once()
    elif command == "validate":
        from .core.pipeline_validator import validate_pipeline, print_report
        ok, results = validate_pipeline(pilot)
        print_report(ok, results)
        return 0 if ok else 4
    elif command == "checklist":
        # Portal Completion Checklist -- the roadmap. Reads debug/ evidence to
        # promote items automatically and compute quantitative metrics.
        from .diagnostics import portal_checklist as pc
        evidence = argv[2] if (len(argv) > 2 and argv[1] == "--evidence") else "debug"
        checklists = pc.apply_evidence(pc.build_checklists(), evidence)
        metrics = pc.quantitative_metrics(checklists, evidence)
        print(pc.render_markdown(checklists, metrics))
        pc.generate(evidence, write_to="debug/portal_checklist.md")
        return 0
    elif command == "probe-open":
        return _cmd_probe_open(pilot, argv)
    elif command == "export":
        # One-shot DOM export of a URL using the (logged-in) portal profile.
        from .core.enums import Portal
        from .browser.base_portal import navigate, wait_for_ready
        url = argv[1] if len(argv) > 1 else None
        if not url:
            print("usage: export <url> [linkedin|naukri]", file=sys.stderr)
            return 1
        portal = argv[2] if len(argv) > 2 else Portal.NAUKRI.value
        pilot._build_portals()  # builds browser + diagnostics
        page = pilot.browser.page(portal)
        pilot.diagnostics.enabled = True
        pilot.diagnostics.attach(page)
        navigate(page, url, reason="manual export")
        wait_for_ready(page, networkidle_timeout_ms=pilot.cfg.browser.networkidle_timeout_ms,
                       render_settle_ms=pilot.cfg.browser.render_settle_ms,
                       reason="manual export")
        dest = pilot.diagnostics.export(page, "debug/exports/manual")
        pilot.browser.close_all()
        print(f"Exported current page to: {dest}")
        return 0
    elif command == "dashboard":
        pilot.run_dashboard()
    elif command == "maintenance":
        from .core.maintenance import RetentionConfig, run_maintenance, write_health_heartbeat
        ret = config.retention
        result = run_maintenance(
            cache_dir="cache/jobs",
            report_dir=config.report_path,
            screenshot_dir=config.screenshot_path,
            evidence_dir=getattr(config.debug, "evidence_dir", "debug"),
            backup_dir=config.backup_path,
            database_path=config.database_path,
            config=RetentionConfig(
                cache_days=ret.cache_days, report_days=ret.report_days,
                screenshot_days=ret.screenshot_days,
                evidence_days=ret.evidence_days, backup_days=ret.backup_days,
                human_interaction_days=ret.human_interaction_days,
                session_history_max=ret.session_history_max,
                good_jobs_max=ret.good_jobs_max, vacuum_db=ret.vacuum_db,
            ),
        )
        write_health_heartbeat(status="ok", extra=result.as_dict())
        print(f"Maintenance complete: {result.as_dict()}")
        return 0 if not result.errors else 1
    elif command == "backup":
        from .core.backup_ops import create_backup
        include_chrome = "--chrome" in argv or "--include-chrome" in argv
        result = create_backup(
            config_path="config/config.yaml",
            env_path=".env",
            database_path=config.database_path,
            profiles_dir=config.profiles_dir,
            browser_profiles=config.browser_profiles_path,
            logs_dir=config.log_path,
            reports_dir=config.report_path,
            include_chrome_profiles=include_chrome,
        )
        print(f"Backup -> {result.path}")
        print(f"  copied: {result.copied}")
        if result.skipped:
            print(f"  skipped: {result.skipped}")
        if result.errors:
            print(f"  errors: {result.errors}")
            return 1
        return 0
    elif command == "restore":
        from .core.backup_ops import restore_backup
        if len(argv) < 2:
            print("usage: restore <backups/YYYY-MM-DD> [--force] [--chrome]",
                  file=sys.stderr)
            return 1
        result = restore_backup(
            argv[1], force="--force" in argv,
            restore_chrome_profiles=("--chrome" in argv or "--include-chrome" in argv))
        print(f"Restore from {result.path}")
        print(f"  copied: {result.copied}")
        print(f"  skipped: {result.skipped}")
        if result.errors:
            print(f"  errors: {result.errors}")
            return 1
        return 0
    elif command == "health":
        import json as _json
        from .core.health_snapshot import collect_health, write_health_snapshot
        snap = collect_health(config=config, db_path=config.database_path)
        path = write_health_snapshot(config=config, db_path=config.database_path)
        print(_json.dumps(snap, indent=2, default=str))
        print(f"\nWrote {path}")
        return 0
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: run | scan | dashboard | doctor | check | validate | "
              "maintenance | backup | restore | health | models | ai-health | "
              "checklist | export",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
