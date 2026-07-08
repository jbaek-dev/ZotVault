"""System tray for the daemon (v0.9) — the Syncthing/Jellyfin pattern.

`zotvault tray` runs the daemon loop in a background thread and shows a small
tray/menu-bar icon: Open Dashboard · Run now · Pause/Resume · Quit.

This is the ONLY module allowed third-party imports (pystray + Pillow), and
they are an optional extra so the core stays stdlib-only:

    pip install "zotvault[tray]"     # or: uv tool install "zotvault[tray]"

Autostart:
- Windows: Task Scheduler / shell:startup shortcut running `zotvault tray`
  (see `zotvault install-daemon` for the exact command)
- macOS: ZotVault.app or launchd (tray optional)
- Linux: a systemd user unit or your DE's autostart entry
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zotvault.config import Config

log = logging.getLogger("zotvault.tray")

try:  # optional extra — keep the core zero-dependency.
    # NOT just ImportError: pystray probes a GUI backend at import time and
    # raises backend-specific errors on headless systems (e.g. Xlib
    # DisplayNameError when $DISPLAY is unset on Linux).
    import pystray
    from PIL import Image, ImageDraw
except Exception as _exc:  # pragma: no cover
    pystray = None
    _IMPORT_ERROR = _exc
else:
    _IMPORT_ERROR = None


def _icon_image():
    """Simple generated icon (blue rounded square + white dot) — no asset file
    needed, keeps the wheel slim."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(45, 110, 200, 255))
    d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
    return img


def main(cfg: "Config") -> int:
    if pystray is None:
        if isinstance(_IMPORT_ERROR, ImportError):
            print("tray needs the optional extra:  pip install '.[tray]'  (from the repo)")
        else:
            print("tray backend unavailable on this system: {}".format(_IMPORT_ERROR))
            print("(headless server? no tray is possible — use `zotvault daemon`)")
        print("the daemon itself runs fine without a tray: `zotvault daemon`")
        return 1

    from zotvault import daemon

    if not daemon.acquire_lock():
        print("a ZotVault daemon is already running — opening the dashboard instead")
        webbrowser.open("http://{}:{}".format(cfg.web_host, cfg.web_port))
        return 0

    daemon.setup_logging(cfg.log_level)
    stop = threading.Event()
    paused = threading.Event()

    worker = threading.Thread(
        target=daemon.run_loop, args=(cfg, stop, paused), daemon=True, name="zotvault-daemon")
    worker.start()

    url = "http://{}:{}".format(cfg.web_host, cfg.web_port)

    def open_dash(icon, item):  # noqa: ANN001
        webbrowser.open(url)

    def run_now(icon, item):  # noqa: ANN001
        from zotvault.pipeline import run_once
        from zotvault.state import State
        from zotvault.webapp import RUN_LOCK

        def job():
            if RUN_LOCK.acquire(blocking=False):
                try:
                    state = State(cfg.state_db)
                    try:
                        run_once(cfg, state)
                    finally:
                        state.close()
                except Exception:
                    log.exception("run-now failed")
                finally:
                    RUN_LOCK.release()

        threading.Thread(target=job, daemon=True).start()

    def toggle_pause(icon, item):  # noqa: ANN001
        if paused.is_set():
            paused.clear()
        else:
            paused.set()

    def quit_app(icon, item):  # noqa: ANN001
        stop.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", open_dash, default=True),
        pystray.MenuItem("Run now", run_now),
        pystray.MenuItem("Pause", toggle_pause,
                         checked=lambda item: paused.is_set()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit ZotVault", quit_app),
    )
    icon = pystray.Icon("zotvault", _icon_image(), "ZotVault", menu)
    try:
        icon.run()  # blocks the main thread (required on macOS)
    finally:
        stop.set()
        worker.join(timeout=10)
        daemon.release_lock()
    return 0
