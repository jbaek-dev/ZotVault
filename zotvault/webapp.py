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
  GET  /api/doctor          environment health checks (doctor)
  GET  /api/attention       reconciliation lists (missing notes / vault-only / ignored)
  POST /api/attention/action {"item_key": K, "action": "recreate|ignore|dismiss|readd|unignore"}

No authentication — bind to 127.0.0.1 only (default). Do not expose publicly.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from zotvault import __version__
from zotvault.config import Config
from zotvault.state import State

log = logging.getLogger("zotvault.web")

RUN_LOCK = threading.Lock()          # shared with the daemon loop
_BG_LOCK = threading.Lock()          # single background enrich at a time

_STATIC = Path(__file__).parent / "static"


def _run_pipeline_guarded(cfg: Config) -> Dict[str, Any]:
    from zotvault.pipeline import run_once

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
        server_version = "ZotVault/" + __version__

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
                # Block DNS-rebinding: only serve API reads to a local Host.
                # The dashboard HTML itself is harmless to serve.
                if r != "/" and not self._origin_ok():
                    self._json({"error": "forbidden (non-local Host)"}, 403)
                    return
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
                elif r == "/api/doctor":
                    self._json(self._doctor())
                elif r == "/api/attention":
                    self._json(self._attention())
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:
                log.exception("GET %s failed", self.path)
                self._json({"error": str(exc)[:300]}, 500)

        def _origin_ok(self) -> bool:
            """Reject non-local hosts and, for state-changing calls, require the
            custom header — a malicious web page can fire cross-origin POSTs at
            127.0.0.1 but cannot attach custom headers without CORS approval."""
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost", cfg.web_host)

        # -- POST ---------------------------------------------------------------
        def do_POST(self) -> None:  # noqa: N802
            try:
                if not self._origin_ok() or self.headers.get("X-ZotVault") != "1":
                    self._json({"error": "forbidden (missing X-ZotVault header)"}, 403)
                    return
                r = self.route
                if r == "/api/add":
                    self._json(self._add())
                elif r == "/api/run-once":
                    self._json(_run_pipeline_guarded(cfg))
                elif r == "/api/alerts/action":
                    self._json(self._alert_action())
                elif r == "/api/attention/action":
                    self._json(self._attention_action())
                elif r == "/api/enrich":
                    self._json(self._enrich_bg())
                elif r == "/api/analyze":
                    self._json(self._analyze_bg())
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
                    "analysis_engine": cfg.analysis_engine,
                    "analyses_today": state.analyses_today(),
                    "analysis_limit": cfg.analysis_daily_limit,
                }
            finally:
                state.close()

        def _attention(self) -> Any:
            state = State(cfg.state_db)
            try:
                rows = state.attention_rows()
            finally:
                state.close()

            def slim(r: Any) -> Dict[str, Any]:
                return {"item_key": r["item_key"],
                        "citekey": r["citekey"] or r["item_key"],
                        "title": (r["title"] or "")[:140],
                        "doi": r["doi"] or "", "arxiv": r["arxiv_id"] or ""}

            vault_only = [slim(r) for r in rows["vault_only"]
                          if r["note_path"] and Path(r["note_path"]).exists()]
            return {"missing": [slim(r) for r in rows["missing"]],
                    "vault_only": vault_only,
                    "ignored": [slim(r) for r in rows["ignored"]]}

        def _attention_action(self) -> Any:
            body = self._body()
            key = str(body.get("item_key") or "")
            action = str(body.get("action") or "")
            state = State(cfg.state_db)
            try:
                row = state.item_by_key(key)
                if row is None:
                    return {"error": "unknown item"}
                ck = row["citekey"] or key
                if action == "recreate":
                    state.upsert_item(row["item_id"], note_status="pending")
                    state.trace("note_recreate_requested", ck, "dashboard")

                    def _kick() -> None:
                        time.sleep(1)
                        _run_pipeline_guarded(cfg)
                    threading.Thread(target=_kick, daemon=True,
                                     name="zotvault-recreate").start()
                    return {"ok": True, "message": "recreating {} now".format(ck)}
                if action in ("ignore", "dismiss"):
                    state.set_ignored(key, True)
                    state.trace("item_ignored", ck, action)
                    return {"ok": True, "message": "{} moved to the ignore list".format(ck)}
                if action == "unignore":
                    state.set_ignored(key, False)
                    state.trace("item_unignored", ck, "")
                    return {"ok": True, "message": "{} removed from the ignore list".format(ck)}
                if action == "readd":
                    ident = row["doi"] or row["arxiv_id"]
                    if not ident:
                        return {"error": "no DOI/arXiv id stored for {} — use search/add".format(ck)}
                    from zotvault.zotero_writer import add_identifiers
                    res = add_identifiers([ident], cfg, state, force=True)[0]
                    if res.get("status") == "added":
                        state.set_ignored(key, True)  # ghost row is now history
                        state.trace("item_readded", ck, ident)
                    return {"ok": res.get("status") == "added",
                            "message": res.get("message", "")}
                return {"error": "unknown action"}
            finally:
                state.close()

        def _doctor(self) -> Any:
            from zotvault.health import checks
            return [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in checks(cfg)]

        def _queue(self) -> Any:
            from zotvault import analysis_queue

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
            from zotvault.search import search

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
            from zotvault.zotero_writer import add_identifiers

            body = self._body()
            ids = body.get("identifiers") or []
            if not ids:
                return {"error": "no identifiers"}
            state = State(cfg.state_db)
            try:
                results = add_identifiers([str(i) for i in ids][:20], cfg, state,
                                          dry_run=bool(body.get("dry_run")))
            finally:
                state.close()
            if any(r.get("status") == "added" for r in results):
                # give Zotero a moment to commit, then run one cycle so the
                # note/queue/PDF status appear in seconds instead of at the
                # next poll (no-op if a cycle is already running).
                def _kick() -> None:
                    time.sleep(4)
                    _run_pipeline_guarded(cfg)
                threading.Thread(target=_kick, daemon=True,
                                 name="zotvault-post-add").start()
            return results

        def _alerts(self) -> Any:
            state = State(cfg.state_db)
            try:
                rows = state.alerts_list(self._query().get("status", "pending"))
                return [dict(r) for r in rows]
            finally:
                state.close()

        def _alert_action(self) -> Any:
            from zotvault import alerts as alerts_mod

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
            from zotvault import related as related_mod

            citekey = self._query().get("citekey", "")
            state = State(cfg.state_db)
            try:
                return related_mod.related_for(citekey, cfg, state)
            finally:
                state.close()

        def _suggestions(self) -> Any:
            from zotvault import synthesis as synthesis_mod

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
                    from zotvault import enrich, related, synthesis

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

            threading.Thread(target=job, daemon=True, name="zotvault-enrich").start()
            return {"ok": True, "message": "enrichment started"}

        def _analyze_bg(self) -> Any:
            from zotvault import analyze

            if cfg.analysis_engine == "none":
                return {"ok": False,
                        "message": "[analysis] engine = none — configure an engine in config.toml"}
            if analyze.run_batch_bg(cfg):
                return {"ok": True, "message": "analysis started ({})".format(cfg.analysis_engine)}
            return {"ok": False, "message": "an analysis batch is already running"}

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
    threading.Thread(target=server.serve_forever, daemon=True, name="zotvault-web").start()
    return server
