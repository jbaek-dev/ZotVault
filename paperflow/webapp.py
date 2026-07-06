"""Local web dashboard — stdlib http.server only, bound to localhost.

Endpoints (JSON unless noted):
  GET  /                    dashboard (static/index.html)
  GET  /api/status          state summary
  GET  /api/queue           papers awaiting analysis
  GET  /api/search          ?q=&source=arxiv|s2|crossref&max=
  POST /api/add             {"identifiers": [...], "dry_run": false}
  POST /api/run-once        trigger one pipeline cycle (no-op if one is running)
  GET  /api/alerts          ?status=pending
  POST /api/alerts/action   {"id": N, "action": "approve"|"dismiss"}
  GET  /api/related         ?citekey=X
  GET  /api/suggestions     synthesis cluster suggestions
  POST /api/enrich          run enrichment in the background
  GET  /api/trace           ?limit=30

No authentication — bind to 127.0.0.1 only (default). Do not expose publicly.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from paperflow import __version__
from paperflow.config import Config
from paperflow.state import State

log = logging.getLogger("paperflow.web")

RUN_LOCK = threading.Lock()          # shared with the daemon loop
_BG_LOCK = threading.Lock()          # single background enrich at a time

_STATIC = Path(__file__).parent / "static"


def _run_pipeline_guarded(cfg: Config) -> Dict[str, Any]:
    from paperflow.pipeline import run_once

    if not RUN_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "a pipeline cycle is already running"}
    try:
        state = State(cfg.state_db)
        try:
            summary = run_once(cfg, state)
        finally:
            state.close()
        return {"ok": True, "summary": summary.line()}
    finally:
        RUN_LOCK.release()


def make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PaperFlow/" + __version__

        # -- plumbing -----------------------------------------------------
        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return {}

        def _query(self) -> Dict[str, str]:
            qs = urllib.parse.urlparse(self.path).query
            return {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}

        @property
        def route(self) -> str:
            return urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

        # -- GET ------------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            try:
                r = self.route
                if r == "/":
                    html = (_STATIC / "index.html").read_bytes()
                    self._send(200, html, "text/html; charset=utf-8")
                elif r == "/api/status":
                    self._json(self._status())
                elif r == "/api/queue":
                    self._json(self._queue())
                elif r == "/api/search":
                    self._json(self._search())
                elif r == "/api/alerts":
                    self._json(self._alerts())
                elif r == "/api/related":
                    self._json(self._related())
                elif r == "/api/suggestions":
                    self._json(self._suggestions())
                elif r == "/api/trace":
                    self._json(self._trace())
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:
                log.exception("GET %s failed", self.path)
                self._json({"error": str(exc)[:300]}, 500)

        # -- POST ---------------------------------------------------------------
        def do_POST(self) -> None:  # noqa: N802
            try:
                r = self.route
                if r == "/api/add":
                    self._json(self._add())
                elif r == "/api/run-once":
                    self._json(_run_pipeline_guarded(cfg))
                elif r == "/api/alerts/action":
                    self._json(self._alert_action())
                elif r == "/api/enrich":
                    self._json(self._enrich_bg())
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:
                log.exception("POST %s failed", self.path)
                self._json({"error": str(exc)[:300]}, 500)

        # -- handlers ---------------------------------------------------------
        def _status(self) -> Dict[str, Any]:
            state = State(cfg.state_db)
            try:
                c = state.counts()
                return {
                    "version": __version__,
                    "counts": c,
                    "last_run_at": state.kv_get("last_run_at"),
                    "last_run": state.kv_get("last_run"),
                    "downloads_today": state.downloads_today(),
                    "download_limit": cfg.daily_download_limit,
                    "proxy_enabled": cfg.proxy_enabled,
                    "alerts_enabled": cfg.alerts_enabled,
                    "pending_alerts": len(state.alerts_list("pending")),
                }
            finally:
                state.close()

        def _queue(self) -> Any:
            from paperflow import analysis_queue

            if cfg.papers_dir is None:
                return {"error": "vault dir not configured"}
            state = State(cfg.state_db)
            try:
                pdf = {r["citekey"]: (r["pdf_status"], r["pdf_path"])
                       for r in state.all_items() if r["citekey"]}
            finally:
                state.close()
            out = []
            for e in analysis_queue.pending(cfg.papers_dir):
                status, path = pdf.get(e.citekey, ("unknown", None))
                out.append({"citekey": e.citekey, "pdf_status": status, "pdf_path": path,
                            "has_note": e.has_note})
            return out

        def _search(self) -> Any:
            from paperflow.search import search

            q = self._query()
            query = q.get("q", "").strip()
            if not query:
                return {"error": "empty query"}
            state = State(cfg.state_db)
            try:
                results = search(query, q.get("source", cfg.search_default_source),
                                 cfg, state, int(q.get("max", 0)) or None)
            finally:
                state.close()
            return [r.to_dict() for r in results]

        def _add(self) -> Any:
            from paperflow.zotero_writer import add_identifiers

            body = self._body()
            ids = body.get("identifiers") or []
            if not ids:
                return {"error": "no identifiers"}
            state = State(cfg.state_db)
            try:
                return add_identifiers([str(i) for i in ids][:20], cfg, state,
                                       dry_run=bool(body.get("dry_run")))
            finally:
                state.close()

        def _alerts(self) -> Any:
            state = State(cfg.state_db)
            try:
                rows = state.alerts_list(self._query().get("status", "pending"))
                return [dict(r) for r in rows]
            finally:
                state.close()

        def _alert_action(self) -> Any:
            from paperflow import alerts as alerts_mod

            body = self._body()
            alert_id = int(body.get("id", 0))
            action = body.get("action")
            state = State(cfg.state_db)
            try:
                if action == "approve":
                    return alerts_mod.approve(alert_id, cfg, state)
                if action == "dismiss":
                    state.alert_set_status(alert_id, "dismissed")
                    return {"ok": True}
                return {"error": "unknown action"}
            finally:
                state.close()

        def _related(self) -> Any:
            from paperflow import related as related_mod

            citekey = self._query().get("citekey", "")
            state = State(cfg.state_db)
            try:
                return related_mod.related_for(citekey, cfg, state)
            finally:
                state.close()

        def _suggestions(self) -> Any:
            from paperflow import synthesis as synthesis_mod

            state = State(cfg.state_db)
            try:
                return synthesis_mod.suggest(cfg, state, write_note=False)
            finally:
                state.close()

        def _enrich_bg(self) -> Any:
            if not _BG_LOCK.acquire(blocking=False):
                return {"ok": False, "message": "enrichment already running"}

            def job() -> None:
                try:
                    from paperflow import enrich, related, synthesis

                    state = State(cfg.state_db)
                    try:
                        enrich.run(cfg, state)
                        related.refresh(cfg, state)
                        related.write_note(cfg, state)
                        synthesis.suggest(cfg, state, write_note=True)
                    finally:
                        state.close()
                except Exception:
                    log.exception("background enrich failed")
                finally:
                    _BG_LOCK.release()

            threading.Thread(target=job, daemon=True, name="paperflow-enrich").start()
            return {"ok": True, "message": "enrichment started"}

        def _trace(self) -> Any:
            state = State(cfg.state_db)
            try:
                rows = state.recent_trace(int(self._query().get("limit", 30)))
                return [dict(r) for r in rows]
            finally:
                state.close()

    return Handler


def serve(cfg: Config) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((cfg.web_host, cfg.web_port), make_handler(cfg))
    log.info("dashboard on http://%s:%s", cfg.web_host, cfg.web_port)
    return server


def start_in_thread(cfg: Config) -> Optional[ThreadingHTTPServer]:
    try:
        server = serve(cfg)
    except OSError as exc:
        log.error("web dashboard disabled: %s", exc)
        return None
    threading.Thread(target=server.serve_forever, daemon=True, name="paperflow-web").start()
    return server
