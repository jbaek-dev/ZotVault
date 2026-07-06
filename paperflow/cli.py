"""PaperFlow command-line interface.

Commands:
  init            create ~/.paperflow/config.toml from the template
  doctor          environment health check (Zotero, BBT, vault, paths)
  run-once        one pipeline cycle (use --dry-run to preview)
  daemon          run the poller in the foreground
  install-daemon  write a launchd plist (prints the launchctl commands; does
                  not load it for you — you stay in control)
  queue           papers still waiting for AI analysis (feed for Claude batch)
  status          state summary
  trace           recent audit trail
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from paperflow import __version__, analysis_queue
from paperflow.config import CONFIG_TEMPLATE, DEFAULT_CONFIG_PATH, Config, load_config
from paperflow.state import State
from paperflow.zotero_reader import ZoteroReader

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.paperflow.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>paperflow.cli</string>
        <string>daemon</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{repo}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{home}/.paperflow/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>{home}/.paperflow/launchd.err.log</string>
</dict>
</plist>
"""


def _print(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    path = Path(DEFAULT_CONFIG_PATH).expanduser()
    if path.exists() and not args.force:
        _print("config already exists: {} (use --force to overwrite)".format(path))
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    _print("wrote {}".format(path))
    _print("Edit at least: [vault] dir, [pdf] unpaywall_email")
    return 0


def _checks(cfg: Config) -> List[Tuple[str, bool, str]]:
    checks: List[Tuple[str, bool, str]] = []
    py_ok = sys.version_info >= (3, 9)
    checks.append(("python >= 3.9", py_ok, platform.python_version()))
    checks.append(
        ("config file", cfg.config_path is not None, str(cfg.config_path or "missing — run `paperflow init`"))
    )
    checks.append(("zotero data dir", cfg.zotero_data_dir.exists(), str(cfg.zotero_data_dir)))
    checks.append(("zotero.sqlite", cfg.zotero_sqlite.exists(), str(cfg.zotero_sqlite)))
    checks.append(("zotero storage/", cfg.zotero_storage.exists(), str(cfg.zotero_storage)))
    reader = ZoteroReader(cfg.zotero_data_dir, cfg.connector_url)
    alive = reader.zotero_alive()
    checks.append(("zotero running (connector ping)", alive, cfg.connector_url))
    if alive:
        bbt = reader.bbt_citekeys(["__paperflow_probe__"])
        # a working endpoint answers (with an empty/mapped result); failure -> {}
        probe_ok = isinstance(bbt, dict)
        try:
            import urllib.request

            req = urllib.request.Request(
                cfg.connector_url + "/better-bibtex/json-rpc",
                data=b'{"jsonrpc":"2.0","method":"item.citationkey","params":[[]],"id":1}',
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                probe_ok = resp.status == 200
        except Exception:
            probe_ok = False
        checks.append(("Better BibTeX JSON-RPC", probe_ok, "citekey source"))
    if cfg.vault_dir is None:
        checks.append(("vault dir", False, "not configured ([vault] dir)"))
    else:
        checks.append(("vault dir", cfg.vault_dir.exists(), str(cfg.vault_dir)))
        papers = cfg.papers_dir
        checks.append(("papers dir", papers is not None and papers.exists(), str(papers)))
        checks.append(
            ("index.md", cfg.index_path is not None and cfg.index_path.exists(), str(cfg.index_path))
        )
        checks.append(("log.md", cfg.log_path is not None and cfg.log_path.exists(), str(cfg.log_path)))
    try:
        cfg.pdf_dir.mkdir(parents=True, exist_ok=True)
        checks.append(("pdf dir writable", True, str(cfg.pdf_dir)))
    except OSError as exc:
        checks.append(("pdf dir writable", False, str(exc)))
    try:
        State(cfg.state_db).close()
        checks.append(("state db writable", True, str(cfg.state_db)))
    except Exception as exc:
        checks.append(("state db writable", False, str(exc)))
    if not cfg.unpaywall_email:
        checks.append(("unpaywall email", False, "empty — OA lookup disabled"))
    else:
        checks.append(("unpaywall email", True, cfg.unpaywall_email))
    # optional subsystems (informational — failures don't block the core loop)
    if cfg.translation_server_url:
        try:
            import urllib.request as _ur

            with _ur.urlopen(cfg.translation_server_url + "/", timeout=4) as r:
                checks.append(("translation-server", True, cfg.translation_server_url))
        except Exception:
            checks.append(("translation-server", False, cfg.translation_server_url + " unreachable"))
    if cfg.feat_related or cfg.feat_synthesis:
        try:
            import urllib.request as _ur

            with _ur.urlopen(cfg.ollama_url + "/api/tags", timeout=4) as r:
                ok = r.status == 200
            checks.append(("ollama (embeddings)", ok, cfg.ollama_url))
        except Exception:
            checks.append(("ollama (embeddings)", False,
                           cfg.ollama_url + " unreachable — related/synthesis suggestions off"))
    if cfg.proxy_enabled:
        tmpl_ok = "{url}" in cfg.proxy_url_template
        checks.append(("proxy url_template", tmpl_ok,
                       cfg.proxy_url_template or "empty"))
        ck = Path(os.path.expanduser(cfg.proxy_cookie_file)) if cfg.proxy_cookie_file else None
        checks.append(("proxy cookie file", ck is not None and ck.exists(),
                       str(ck) if ck else "not set"))
    if cfg.alerts_enabled:
        checks.append(("alerts keywords", bool(cfg.alerts_keywords),
                       ", ".join(cfg.alerts_keywords) or "empty"))
    return checks


def cmd_doctor(cfg: Config, args: argparse.Namespace) -> int:
    ok_all = True
    for name, ok, detail in _checks(cfg):
        mark = "✅" if ok else "❌"
        if not ok:
            ok_all = False
        _print("{} {:32s} {}".format(mark, name, detail))
    _print()
    _print("verdict: {}".format("ready" if ok_all else "issues found (see ❌ above)"))
    return 0 if ok_all else 1


def cmd_run_once(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow.daemon import setup_logging
    from paperflow.pipeline import run_once

    setup_logging(cfg.log_level)
    if args.dry_run:
        cfg.dry_run = True
    state = State(cfg.state_db)
    try:
        summary = run_once(cfg, state)
    finally:
        state.close()
    _print(("[dry-run] " if cfg.dry_run else "") + summary.line())
    if summary.created_citekeys:
        _print("notes created: " + ", ".join(summary.created_citekeys))
    if summary.downloaded_citekeys:
        _print("pdfs downloaded: " + ", ".join(summary.downloaded_citekeys))
    if summary.detected_citekeys:
        _print("analyses detected: " + ", ".join(summary.detected_citekeys))
    return 0 if summary.errors == 0 else 1


def cmd_daemon(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow import daemon

    return daemon.run(cfg)


def cmd_install_daemon(cfg: Config, args: argparse.Namespace) -> int:
    repo = Path(__file__).resolve().parent.parent
    plist = PLIST_TEMPLATE.format(python=sys.executable, repo=repo, home=Path.home())
    dest = Path("~/Library/LaunchAgents/com.paperflow.daemon.plist").expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(plist, encoding="utf-8")
    _print("wrote {}".format(dest))
    _print("PaperFlow does not auto-load it. To start now and at login:")
    _print("  launchctl load {}".format(dest))
    _print("To stop: launchctl unload {}".format(dest))
    return 0


def cmd_queue(cfg: Config, args: argparse.Namespace) -> int:
    if cfg.papers_dir is None:
        _print("vault dir not configured")
        return 1
    state = State(cfg.state_db)
    pdf_by_citekey = {}
    for row in state.all_items():
        if row["citekey"]:
            pdf_by_citekey[row["citekey"]] = (row["pdf_status"], row["pdf_path"])
    state.close()
    entries = analysis_queue.pending(cfg.papers_dir)
    if args.json:
        out = []
        for e in entries:
            status, path = pdf_by_citekey.get(e.citekey, ("unknown", None))
            out.append(
                {
                    "citekey": e.citekey,
                    "folder": str(e.folder),
                    "has_note": e.has_note,
                    "pdf_status": status,
                    "pdf_path": path,
                }
            )
        _print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if not entries:
        _print("analysis queue is empty — everything analyzed ✅")
        return 0
    _print("{} paper(s) waiting for analysis:".format(len(entries)))
    for e in entries:
        status, path = pdf_by_citekey.get(e.citekey, ("unknown", None))
        pdf_mark = {"zotero": "📄", "downloaded": "📄", "cached": "📄"}.get(status, "⬜")
        _print("  {} {:40s} pdf={:10s} {}".format(pdf_mark, e.citekey, status, path or ""))
    _print()
    _print("Analyze via Cowork/Claude using the vault contract prompts/analyze_paper.md;")
    _print("PaperFlow auto-detects the resulting *_analysis.md files.")
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    state = State(cfg.state_db)
    c = state.counts()
    _print("PaperFlow {}".format(__version__))
    _print("state db     : {}".format(cfg.state_db))
    _print("last run     : {} ({})".format(state.kv_get("last_run_at", "never"), state.kv_get("last_run", "-")))
    _print("items tracked: {} (analyzed {})".format(c["items"], c["analyzed"]))
    _print(
        "notes        : created {} / existing {} / pending {} / error {}".format(
            c["note_created"], c["note_existing"], c["note_pending"], c["note_error"]
        )
    )
    _print(
        "pdf          : zotero {} / downloaded {} / cached {} / missing {} / deferred {}".format(
            c["pdf_zotero"], c["pdf_downloaded"], c["pdf_cached"], c["pdf_missing"], c["pdf_deferred"]
        )
    )
    _print("downloads    : {} today (limit {})".format(state.downloads_today(), cfg.daily_download_limit))
    stuck = [r for r in state.all_items() if r["citekey"] is None]
    if stuck:
        _print("⚠ citekey pending for {} item(s): {}".format(
            len(stuck), ", ".join(r["item_key"] for r in stuck[:10])
        ))
    state.close()
    return 0


def cmd_add(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow.zotero_writer import add_identifiers

    state = State(cfg.state_db)
    try:
        results = add_identifiers(args.identifiers, cfg, state,
                                  attach_pdf=not args.no_pdf, dry_run=args.dry_run)
    finally:
        state.close()
    failures = 0
    for r in results:
        mark = {"added": "✅", "resolved": "🔎", "duplicate": "↩️", "error": "❌"}.get(r["status"], "•")
        if r["status"] == "error":
            failures += 1
        _print("{} [{}] {} — {}".format(mark, r["status"], r.get("title") or r["identifier"],
                                         r.get("message", "")))
    if any(r["status"] == "added" for r in results):
        _print()
        _print("Zotero received the item(s); the daemon (or `paperflow run-once`) will "
               "create notes / fetch PDFs / queue analysis.")
    return 0 if failures == 0 else 1


def cmd_search(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow.search import search

    state = State(cfg.state_db)
    try:
        results = search(args.query, args.source or cfg.search_default_source, cfg, state,
                         args.max)
    finally:
        state.close()
    if args.json:
        _print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
        return 0
    if not results:
        _print("no results")
        return 0
    for i, r in enumerate(results, 1):
        lib = " [in library: {}]".format(r.in_library) if r.in_library else ""
        cites = " · {} cites".format(r.citations) if r.citations is not None else ""
        _print("{:2d}. {} ({}){}{}".format(i, r.title, r.year or "?", cites, lib))
        _print("    {} · {}".format(r.authors[:100], r.venue))
        if r.best_identifier:
            _print("    id: {}".format(r.best_identifier))
    _print()
    _print("add with: paperflow add <doi|arxiv-id> [...]")
    return 0


def cmd_web(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow.daemon import setup_logging
    from paperflow import webapp

    setup_logging(cfg.log_level)
    server = webapp.serve(cfg)
    _print("PaperFlow dashboard: http://{}:{}  (Ctrl-C to stop)".format(cfg.web_host, cfg.web_port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_alerts(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow import alerts

    state = State(cfg.state_db)
    try:
        if args.fetch:
            n = alerts.fetch(cfg, state)
            _print("{} new candidate(s) added to the inbox".format(n))
        if args.approve:
            res = alerts.approve(args.approve, cfg, state)
            _print(("✅ " if res.get("ok") else "❌ ") + str(res.get("message", res)))
        if args.dismiss:
            state.alert_set_status(args.dismiss, "dismissed")
            _print("dismissed #{}".format(args.dismiss))
        rows = state.alerts_list("pending")
        if not rows:
            _print("inbox empty")
        for r in rows:
            _print("#{:<4d} {}  ({} · arXiv:{})".format(r["id"], r["title"][:90],
                                                        r["published"], r["arxiv_id"]))
            _print("      matched: {}".format(r["matched"]))
    finally:
        state.close()
    return 0


def cmd_enrich(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow.daemon import setup_logging
    from paperflow import enrich, related, synthesis

    setup_logging(cfg.log_level)
    state = State(cfg.state_db)
    try:
        if cfg.feat_citation_graph:
            n = enrich.run(cfg, state, limit=args.limit)
            _print("citation graph: {} item(s) enriched".format(n))
        if cfg.feat_related:
            e = related.refresh(cfg, state)
            _print("embeddings: {} refreshed".format(e))
            if related.write_note(cfg, state):
                _print("Related_Suggestions.md updated")
        if cfg.feat_synthesis:
            clusters = synthesis.suggest(cfg, state, write_note=True)
            _print("synthesis suggestions: {} cluster(s)".format(len(clusters)))
    finally:
        state.close()
    return 0


def cmd_related(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow import related

    state = State(cfg.state_db)
    try:
        out = related.related_for(args.citekey, cfg, state)
    finally:
        state.close()
    if isinstance(out, dict) and out.get("error"):
        _print("❌ " + out["error"])
        return 1
    for r in out:
        _print("{:.3f}  {}".format(r["score"], r["citekey"]))
    return 0


def cmd_synthesis(cfg: Config, args: argparse.Namespace) -> int:
    from paperflow import synthesis

    state = State(cfg.state_db)
    try:
        clusters = synthesis.suggest(cfg, state, write_note=args.write)
    finally:
        state.close()
    if not clusters:
        _print("no clusters (run `paperflow enrich` first; needs Ollama embeddings)")
        return 0
    for c in clusters:
        _print("• {} ({} papers)".format(c["label"], len(c["citekeys"])))
        _print("  " + ", ".join(c["citekeys"]))
    if args.write:
        _print("\n_Synthesis_Suggestions.md updated (vault/syntheses/)")
    return 0


def cmd_trace(cfg: Config, args: argparse.Namespace) -> int:
    state = State(cfg.state_db)
    for row in reversed(state.recent_trace(args.limit)):
        _print("{}  {:22s} {:28s} {}".format(row["ts"], row["action"], row["target"] or "-", row["detail"] or ""))
    state.close()
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paperflow", description="Local-first Zotero ↔ Obsidian paper pipeline")
    p.add_argument("--config", help="config file path (default ~/.paperflow/config.toml)")
    p.add_argument("--version", action="version", version="paperflow " + __version__)
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init", help="create the config file")
    sp.add_argument("--force", action="store_true")

    sub.add_parser("doctor", help="environment health check")

    sp = sub.add_parser("run-once", help="run one pipeline cycle")
    sp.add_argument("--dry-run", action="store_true")

    sub.add_parser("daemon", help="run the poller (foreground)")
    sub.add_parser("install-daemon", help="write launchd plist (not auto-loaded)")

    sp = sub.add_parser("queue", help="papers awaiting AI analysis")
    sp.add_argument("--json", action="store_true")

    sub.add_parser("status", help="state summary")

    sp = sub.add_parser("trace", help="recent audit trail")
    sp.add_argument("--limit", type=int, default=30)

    sp = sub.add_parser("add", help="add paper(s) to Zotero by DOI / arXiv id / URL")
    sp.add_argument("identifiers", nargs="+")
    sp.add_argument("--dry-run", action="store_true", help="resolve metadata only")
    sp.add_argument("--no-pdf", action="store_true", help="don't attach the arXiv PDF")

    sp = sub.add_parser("search", help="search arXiv / Semantic Scholar / Crossref")
    sp.add_argument("query")
    sp.add_argument("--source", choices=["arxiv", "s2", "crossref"])
    sp.add_argument("--max", type=int)
    sp.add_argument("--json", action="store_true")

    sub.add_parser("web", help="run the dashboard server (foreground)")

    sp = sub.add_parser("alerts", help="arXiv keyword alert inbox")
    sp.add_argument("--fetch", action="store_true", help="fetch new candidates now")
    sp.add_argument("--approve", type=int, metavar="ID", help="add inbox item to Zotero")
    sp.add_argument("--dismiss", type=int, metavar="ID")

    sp = sub.add_parser("enrich", help="citation graph + embeddings + suggestion notes")
    sp.add_argument("--limit", type=int, default=None, help="max items for citation enrichment")

    sp = sub.add_parser("related", help="similar papers for a citekey (local embeddings)")
    sp.add_argument("citekey")

    sp = sub.add_parser("synthesis", help="suggest synthesis clusters")
    sp.add_argument("--write", action="store_true", help="also write _Synthesis_Suggestions.md")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        build_parser().print_help()
        return 0
    if args.command == "init":
        return cmd_init(args)
    cfg = load_config(args.config)
    handlers = {
        "doctor": cmd_doctor,
        "run-once": cmd_run_once,
        "daemon": cmd_daemon,
        "install-daemon": cmd_install_daemon,
        "queue": cmd_queue,
        "status": cmd_status,
        "trace": cmd_trace,
        "add": cmd_add,
        "search": cmd_search,
        "web": cmd_web,
        "alerts": cmd_alerts,
        "enrich": cmd_enrich,
        "related": cmd_related,
        "synthesis": cmd_synthesis,
    }
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
