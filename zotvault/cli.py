"""ZotVault command-line interface.

Commands:
  init            create ~/.zotvault/config.toml from the template
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
import re
import sys
from pathlib import Path
from typing import List, Optional

from zotvault import __version__, analysis_queue
from zotvault.config import CONFIG_TEMPLATE, DEFAULT_CONFIG_PATH, Config, load_config
from zotvault.health import checks as _checks
from zotvault.state import State

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zotvault.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>zotvault.cli</string>
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
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{home}/.zotvault/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>{home}/.zotvault/launchd.err.log</string>
</dict>
</plist>
"""


def _print(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    tail = " [{}]".format(default) if default else ""
    try:
        val = input("  {}{}: ".format(prompt, tail)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return val or default


def _toml_str(value: str) -> str:
    return value.replace("\\", "/").replace('"', '\\"')


def _clean_pasted_path(raw: str) -> str:
    """Undo shell-style backslash-escaping before a pasted path reaches
    Path()/_toml_str(). Terminal tab-completion (or dragging a folder into a
    POSIX shell) inserts a backslash before spaces/tildes/etc. so the shell
    treats them literally — e.g. ``Mobile\\ Documents``, ``iCloud\\~md``.
    ``input()`` is not a shell, so those backslashes are never interpreted;
    left alone they survive into the stored value, and _toml_str()'s
    (intentional, Windows-path-normalizing) backslash -> forward-slash
    conversion then turns them into a similar-looking but nonexistent path
    (``Mobile/ Documents``, ``iCloud/~md``) — see the v0.9.8 vault-path bug.
    Windows paths use backslash as the real separator, so this is a no-op
    there.
    """
    if os.name == "nt" or "\\" not in raw:
        return raw
    return re.sub(r"\\(.)", r"\1", raw)


def apply_init_answers(text: str, vault: str = "", papers: str = "",
                       email: str = "", lang: str = "") -> str:
    """Inject setup-wizard answers into the config template (pure, testable)."""
    if vault:
        text = text.replace('dir = ""', 'dir = "{}"'.format(_toml_str(vault)), 1)
    if papers:
        text = text.replace('papers_subdir = "30_Resources/Papers/zotero"',
                            'papers_subdir = "{}"'.format(_toml_str(papers)), 1)
    if email:
        text = text.replace('unpaywall_email = ""',
                            'unpaywall_email = "{}"'.format(_toml_str(email)), 1)
    if lang and lang != "en":
        text = text.replace('language = "en"', 'language = "{}"'.format(_toml_str(lang)), 1)
    return text


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(DEFAULT_CONFIG_PATH).expanduser()
    if path.exists() and not args.force:
        _print("config already exists: {} (use --force to overwrite)".format(path))
        return 1
    text = CONFIG_TEMPLATE
    interactive = (not getattr(args, "yes", False)
                   and sys.stdin is not None and sys.stdin.isatty()
                   and sys.stdout.isatty())
    if interactive:
        _print("ZotVault setup — Enter accepts the [default], blank skips a question.")
        _print()
        while True:
            vault = _clean_pasted_path(
                _ask("Obsidian/markdown vault folder (blank = Zotero-only mode)"))
            if not vault or Path(vault).expanduser().is_dir():
                break
            if _ask("    '{}' does not exist — use it anyway? (y/N)".format(vault),
                    "n").lower().startswith("y"):
                break
        papers = _clean_pasted_path(_ask("Subfolder for paper notes (inside the vault)",
                      "30_Resources/Papers/zotero")) if vault else ""
        email = _ask("Email for Unpaywall open-access PDF lookup (blank = disabled)")
        lang = _ask("Vault log language — en or ko", "en").lower()
        text = apply_init_answers(text, vault, papers, email, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _print("wrote {}".format(path))
    if not interactive:
        _print("Edit at least: [vault] dir, [pdf] unpaywall_email")
        return 0
    cfg = load_config()
    if cfg.vault_dir is not None and cfg.papers_dir is not None:
        missing = []
        if not cfg.papers_dir.exists():
            missing.append("papers folder ({})".format(cfg.papers_dir))
        index_p = cfg.vault_dir / cfg.index_file
        log_p = cfg.vault_dir / cfg.log_file
        if not index_p.exists():
            missing.append(cfg.index_file)
        if not log_p.exists():
            missing.append(cfg.log_file)
        if missing and _ask("Create missing vault files now? ({}) (Y/n)".format(
                ", ".join(missing)), "y").lower().startswith("y"):
            cfg.papers_dir.mkdir(parents=True, exist_ok=True)
            if not index_p.exists():
                index_p.write_text(
                    "# Index\n\nPapers analyzed: <!-- zotvault:progress 0/0 -->\n",
                    encoding="utf-8")
            if not log_p.exists():
                log_p.write_text("# Log\n", encoding="utf-8")
            _print("  created.")
    _print()
    _print("Checking your environment (doctor):")
    cmd_doctor(cfg, args)
    _print()
    if cfg.vault_dir is None:
        _print("Starting in Zotero-only mode: search / one-shot add / OA PDFs / "
               "arXiv alert inbox.")
        _print("Whenever you adopt Obsidian (any markdown folder works), just set "
               "[vault] dir — notes, highlight sync and the AI queue switch on.")
        _print()
    _print("Next steps:")
    _print("  zotvault run-once --dry-run    preview one cycle (writes nothing)")
    _print("  zotvault daemon                run continuously (+ dashboard)")
    return 0



def cmd_doctor(cfg: Config, args: argparse.Namespace) -> int:
    ok_all = True
    for name, ok, detail in _checks(cfg):
        optional = "(optional" in name
        if ok:
            mark = "✅"
        elif optional:
            mark = "–"   # optional layer that is simply off — not a failure
        else:
            mark = "❌"
            ok_all = False
        _print("{} {:36s} {}".format(mark, name, detail))
    _print()
    _print("verdict: {}".format("ready" if ok_all else "issues found (see ❌ above)"))
    return 0 if ok_all else 1


def cmd_run_once(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault.daemon import setup_logging
    from zotvault.pipeline import run_once

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
    from zotvault import daemon

    return daemon.run(cfg)


def cmd_install_daemon(cfg: Config, args: argparse.Namespace) -> int:
    Path("~/.zotvault").expanduser().mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        repo = Path(__file__).resolve().parent.parent
        plist = PLIST_TEMPLATE.format(python=sys.executable, repo=repo, home=Path.home())
        dest = Path("~/Library/LaunchAgents/com.zotvault.daemon.plist").expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(plist, encoding="utf-8")
        _print("wrote {}".format(dest))
        _print("ZotVault does not auto-load it. To start now and at login:")
        _print("  launchctl load {}".format(dest))
        _print("To stop: launchctl unload {}".format(dest))
        return 0
    if system == "Windows":
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        _print("Windows: register a logon task (run in an elevated-less prompt):")
        _print('  schtasks /Create /SC ONLOGON /TN "ZotVault" /TR "\"{}\" -m zotvault.cli daemon"'.format(exe))
        _print("or, with the tray extra installed (pip install \"zotvault[tray]\"):")
        _print('  schtasks /Create /SC ONLOGON /TN "ZotVault" /TR "\"{}\" -m zotvault.cli tray"'.format(exe))
        _print("Remove with: schtasks /Delete /TN \"ZotVault\"")
        _print("(ZotVault does not register it for you — you stay in control.)")
        return 0
    # Linux / other: systemd user unit
    unit = (
        "[Unit]\nDescription=ZotVault daemon\nAfter=network.target\n\n"
        "[Service]\nExecStart={} -m zotvault.cli daemon\nRestart=on-failure\n\n"
        "[Install]\nWantedBy=default.target\n"
    ).format(sys.executable)
    dest = Path("~/.config/systemd/user/zotvault.service").expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(unit, encoding="utf-8")
    _print("wrote {}".format(dest))
    _print("Enable with:  systemctl --user enable --now zotvault")
    return 0


def cmd_queue(cfg: Config, args: argparse.Namespace) -> int:
    if cfg.papers_dir is None:
        _print("Zotero-only mode — the analysis queue needs a vault. "
               "Set [vault] dir in ~/.zotvault/config.toml to enable it.")
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
    _print("Analyze with `zotvault analyze` (set [analysis] engine), or with your own")
    _print("LLM workflow — ZotVault auto-detects the resulting *_analysis.md files.")
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    state = State(cfg.state_db)
    c = state.counts()
    _print("ZotVault {}".format(__version__))
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
        _print("[!] {} item(s) BLOCKED with no citekey — install/enable Better BibTeX in "
               "Zotero (see README > Requirements): {}".format(
                   len(stuck), ", ".join(r["item_key"] for r in stuck[:10])))
    state.close()
    return 0


def cmd_add(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault.zotero_writer import add_identifiers

    state = State(cfg.state_db)
    try:
        results = add_identifiers(args.identifiers, cfg, state,
                                  attach_pdf=not args.no_pdf, dry_run=args.dry_run,
                                  force=getattr(args, "force", False))
    finally:
        state.close()
    failures = 0
    for r in results:
        mark = {"added": "✅", "resolved": "🔎", "duplicate": "↩️", "ignored": "🚫",
                "error": "❌"}.get(r["status"], "•")
        if r["status"] == "error":
            failures += 1
        _print("{} [{}] {} — {}".format(mark, r["status"], r.get("title") or r["identifier"],
                                         r.get("message", "")))
    if any(r["status"] == "added" for r in results):
        _print()
        if _kick_daemon_run(cfg):
            _print("Zotero received the item(s); asked the running daemon for an "
                   "immediate cycle — note/PDF/queue should appear within seconds.")
        else:
            _print("Zotero received the item(s); the daemon (or `zotvault run-once`) will "
                   "create notes / fetch PDFs / queue analysis.")
    return 0 if failures == 0 else 1


def _kick_daemon_run(cfg: Config) -> bool:
    """Ask a running daemon's dashboard for one immediate pipeline cycle."""
    import time as _time
    import urllib.request

    try:
        _time.sleep(4)  # let Zotero commit the new item first
        req = urllib.request.Request(
            "http://{}:{}/api/run-once".format(cfg.web_host, cfg.web_port),
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "X-ZotVault": "1"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status == 200
    except Exception:
        return False


def cmd_search(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault.search import search

    state = State(cfg.state_db)
    try:
        results = search(args.query, args.source or cfg.search_default_source, cfg, state,
                         args.max)
    except Exception as exc:
        _print("❌ {}".format(exc))
        return 1
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
    _print("add with: zotvault add <doi|arxiv-id> [...]")
    return 0


def cmd_web(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault import webapp
    from zotvault.daemon import setup_logging

    setup_logging(cfg.log_level)
    try:
        server = webapp.serve(cfg)
    except OSError as exc:
        _print("❌ cannot bind {}:{} — {}".format(cfg.web_host, cfg.web_port, exc))
        _print("   (daemon already serving the dashboard? just open http://{}:{})".format(
            cfg.web_host, cfg.web_port))
        return 1
    _print("ZotVault dashboard: http://{}:{}  (Ctrl-C to stop)".format(cfg.web_host, cfg.web_port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_alerts(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault import alerts

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
    from zotvault import enrich, related, synthesis
    from zotvault.daemon import setup_logging

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
    from zotvault import related

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
    from zotvault import synthesis

    state = State(cfg.state_db)
    try:
        clusters = synthesis.suggest(cfg, state, write_note=args.write)
    finally:
        state.close()
    if not clusters:
        _print("no clusters (run `zotvault enrich` first; needs Ollama embeddings)")
        return 0
    for c in clusters:
        _print("• {} ({} papers)".format(c["label"], len(c["citekeys"])))
        _print("  " + ", ".join(c["citekeys"]))
    if args.write:
        _print("\n_Synthesis_Suggestions.md updated (vault/syntheses/)")
    return 0


def cmd_analyze(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault import analyze
    from zotvault.daemon import setup_logging

    setup_logging(cfg.log_level)
    if args.dry_run:
        cfg.dry_run = True
    state = State(cfg.state_db)
    try:
        results = analyze.run_batch(cfg, state, citekeys=args.citekeys or None,
                                    limit=args.limit)
    finally:
        state.close()
    if not results:
        _print("analysis queue is empty ✅")
        return 0
    failures = 0
    for r in results:
        mark = {"written": "✅", "exists": "↩️", "deferred": "⏸", "error": "❌"}.get(r["status"], "•")
        if r["status"] == "error":
            failures += 1
        _print("{} {:36s} [{}] {}".format(mark, r["citekey"], r["status"], r["detail"][:110]))
    _print()
    _print("today's engine analyses: {}/{} · completion is auto-detected by the daemon".format(
        State(cfg.state_db).analyses_today(), cfg.analysis_daily_limit))
    return 0 if failures == 0 else 1


def cmd_tray(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault import tray
    from zotvault.daemon import setup_logging

    setup_logging(cfg.log_level)
    return tray.main(cfg)


def cmd_assist(cfg: Config, args: argparse.Namespace) -> int:
    from zotvault import assist

    state = State(cfg.state_db)
    try:
        n = assist.triage_alerts(cfg, state, limit=args.limit)
    finally:
        state.close()
    if not cfg.assist_enabled or not cfg.assist_model:
        _print("[assist] is disabled — set enabled = true and a small model in config")
        return 1
    _print("{} alert(s) triaged with {}".format(n, cfg.assist_model))
    return 0


def cmd_trace(cfg: Config, args: argparse.Namespace) -> int:
    state = State(cfg.state_db)
    for row in reversed(state.recent_trace(args.limit)):
        _print("{}  {:22s} {:28s} {}".format(row["ts"], row["action"], row["target"] or "-", row["detail"] or ""))
    state.close()
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zotvault", description="Local-first Zotero ↔ Obsidian paper pipeline")
    p.add_argument("--config", help="config file path (default ~/.zotvault/config.toml)")
    p.add_argument("--version", action="version", version="zotvault " + __version__)
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init", help="interactive setup: create the config file + doctor")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--yes", action="store_true",
                    help="non-interactive: write the unmodified template")

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
    sp.add_argument("--force", action="store_true",
                    help="add even if the paper is on the ignore list")

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

    sub.add_parser("tray", help="system tray + daemon (needs: pip install 'zotvault[tray]')")

    sp = sub.add_parser("assist", help="run local-model assists (alert triage)")
    sp.add_argument("--limit", type=int, default=None)

    sp = sub.add_parser("analyze", help="AI-analyze pending papers ([analysis] engine)")
    sp.add_argument("citekeys", nargs="*", help="specific citekeys (default: all pending)")
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--dry-run", action="store_true")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    # Windows consoles (cp949/cp1252) crash on emoji — degrade instead of dying.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass
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
        "analyze": cmd_analyze,
        "assist": cmd_assist,
        "tray": cmd_tray,
    }
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
