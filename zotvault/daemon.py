"""Long-running poller: run the pipeline every poll_interval_sec.

`run()` is the CLI/launchd entry (signal-driven). `run_loop()` is the reusable
core used both by run() and by the system tray (`zotvault tray`), which drives
it from a background thread with stop/pause events.

Single-instance guard via a pid lockfile; SIGTERM/SIGINT exit cleanly.
Logs to ~/.zotvault/zotvault.log (rotating) and stderr.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

from zotvault.config import Config
from zotvault.pipeline import run_once
from zotvault.state import State

log = logging.getLogger("zotvault")

_LOCK = Path("~/.zotvault/daemon.pid").expanduser()
_LOGFILE = Path("~/.zotvault/zotvault.log").expanduser()

_stop_event = threading.Event()


def _handle_signal(signum, frame):  # noqa: ANN001
    _stop_event.set()
    log.info("signal %s received, stopping after current cycle", signum)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock() -> bool:
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    if _LOCK.exists():
        try:
            other = int(_LOCK.read_text().strip())
        except ValueError:
            other = -1
        if other > 0 and _pid_alive(other):
            return False
        _LOCK.unlink(missing_ok=True)
    _LOCK.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        if _LOCK.exists() and _LOCK.read_text().strip() == str(os.getpid()):
            _LOCK.unlink()
    except OSError:
        pass


def setup_logging(level: str = "INFO") -> None:
    _LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        str(_LOGFILE), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.handlers = [fh, sh]


def _daily_jobs(cfg: Config, state: State) -> None:
    """Low-frequency background work: arXiv alerts + enrichment. Never raises."""
    import datetime as _dt

    today = _dt.date.today().isoformat()
    hour = _dt.datetime.now().hour
    if (cfg.alerts_enabled and cfg.alerts_keywords
            and state.kv_get("alerts_last_day") != today and hour >= cfg.alerts_hour):
        try:
            from zotvault import alerts

            added = alerts.fetch(cfg, state)
            state.kv_set("alerts_last_day", today)
            if added:
                log.info("arXiv alerts: %s new candidate(s) in inbox", added)
            if cfg.assist_enabled:
                from zotvault import assist

                scored = assist.triage_alerts(cfg, state)
                if scored:
                    log.info("assist: %s alert(s) triaged", scored)
        except Exception:
            log.exception("alerts fetch failed")
    if cfg.enrich_every_hours > 0 and (cfg.feat_citation_graph or cfg.feat_related or cfg.feat_synthesis):
        last = state.kv_get("enrich_last_ts")
        due = True
        if last:
            try:
                last_dt = _dt.datetime.fromisoformat(last)
                due = (_dt.datetime.now() - last_dt).total_seconds() >= cfg.enrich_every_hours * 3600
            except ValueError:
                due = True
        if due:
            try:
                from zotvault import enrich, related, synthesis

                if cfg.feat_citation_graph:
                    enrich.run(cfg, state)
                if cfg.feat_related:
                    related.refresh(cfg, state)
                    related.write_note(cfg, state)
                if cfg.feat_synthesis:
                    synthesis.suggest(cfg, state, write_note=True)
                state.kv_set("enrich_last_ts", _dt.datetime.now().isoformat(timespec="seconds"))
            except Exception:
                log.exception("enrichment failed")


def run_loop(cfg: Config, stop: threading.Event,
             paused: Optional[threading.Event] = None) -> None:
    """Core loop: web thread + pipeline cycles until `stop` is set.

    The caller owns the single-instance lock and logging setup.
    """
    from zotvault.webapp import RUN_LOCK

    state = State(cfg.state_db)
    state.trace("daemon_start", "", "poll every {}s".format(cfg.poll_interval_sec))
    log.info("ZotVault daemon started (poll every %ss, dry_run=%s)",
             cfg.poll_interval_sec, cfg.dry_run)
    web_server = None
    if cfg.web_enabled:
        from zotvault import webapp

        web_server = webapp.start_in_thread(cfg)
    try:
        while not stop.is_set():
            if paused is None or not paused.is_set():
                try:
                    with RUN_LOCK:
                        summary = run_once(cfg, state)
                    if summary.changed or summary.errors:
                        log.info("cycle: %s", summary.line())
                    else:
                        log.debug("cycle: %s", summary.line())
                    _daily_jobs(cfg, state)
                    if cfg.analysis_auto and cfg.analysis_engine != "none" and summary.changed:
                        from zotvault import analyze

                        analyze.run_batch_bg(cfg)
                except Exception:
                    log.exception("pipeline cycle failed")
            stop.wait(max(1, int(cfg.poll_interval_sec)))
    finally:
        if web_server is not None:
            web_server.shutdown()
        state.trace("daemon_stop", "", "")
        state.close()
        log.info("ZotVault daemon stopped")


def run(cfg: Config) -> int:
    setup_logging(cfg.log_level)
    if not acquire_lock():
        # exit 0 on purpose: launchd's KeepAlive={SuccessfulExit:false} must not
        # respawn-loop when the icon-launched daemon already holds the lock.
        log.info("another zotvault daemon is already running (pid file: %s) — exiting", _LOCK)
        return 0
    _stop_event.clear()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        run_loop(cfg, _stop_event)
    finally:
        release_lock()
    return 0
