"""Long-running poller: run the pipeline every poll_interval_sec.

Single-instance guard via a pid lockfile; SIGTERM/SIGINT exit cleanly.
Logs to ~/.paperflow/paperflow.log (rotating) and stderr.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import time
from pathlib import Path

from paperflow.config import Config
from paperflow.pipeline import run_once
from paperflow.state import State

log = logging.getLogger("paperflow")

_LOCK = Path("~/.paperflow/daemon.pid").expanduser()
_LOGFILE = Path("~/.paperflow/paperflow.log").expanduser()

_stop = False


def _handle_signal(signum, frame):  # noqa: ANN001
    global _stop
    _stop = True
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


def run(cfg: Config) -> int:
    setup_logging(cfg.log_level)
    if not acquire_lock():
        log.error("another paperflow daemon is already running (pid file: %s)", _LOCK)
        return 1
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    state = State(cfg.state_db)
    state.trace("daemon_start", "", "poll every {}s".format(cfg.poll_interval_sec))
    log.info("PaperFlow daemon started (poll every %ss, dry_run=%s)", cfg.poll_interval_sec, cfg.dry_run)
    try:
        while not _stop:
            try:
                summary = run_once(cfg, state)
                if summary.changed or summary.errors:
                    log.info("cycle: %s", summary.line())
                else:
                    log.debug("cycle: %s", summary.line())
            except Exception:
                log.exception("pipeline cycle failed")
            # sleep in 1s slices so signals stop us promptly
            for _ in range(max(1, int(cfg.poll_interval_sec))):
                if _stop:
                    break
                time.sleep(1)
    finally:
        state.trace("daemon_stop", "", "")
        state.close()
        release_lock()
        log.info("PaperFlow daemon stopped")
    return 0
