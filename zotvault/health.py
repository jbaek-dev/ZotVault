"""Environment health checks — shared by `zotvault doctor` and GET /api/doctor."""
from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path
from typing import List, Tuple

from zotvault.config import Config
from zotvault.state import State
from zotvault.zotero_reader import ZoteroReader


def _decorrupted_vault_hint(path_str: str) -> str:
    """Best-effort detection of the pre-v0.9.8 `zotvault init` bug: a pasted,
    shell-escaped path (space/tilde preceded by ``\\``) had its backslashes
    folded into ``/`` by `_toml_str()`, producing a similar-looking but
    nonexistent path (``Mobile/ Documents``, ``iCloud/~md``). If undoing
    that folding yields a directory that actually exists, return it as a
    fix suggestion; otherwise return "" (don't guess at unrelated typos).
    """
    candidate = re.sub(r"/(?= )", "", path_str).replace("/~", "~")
    if candidate != path_str and Path(candidate).expanduser().is_dir():
        return candidate
    return ""


def checks(cfg: Config) -> List[Tuple[str, bool, str]]:
    checks: List[Tuple[str, bool, str]] = []
    py_ok = sys.version_info >= (3, 9)
    checks.append(("python >= 3.9", py_ok, platform.python_version()))
    checks.append(
        ("config file", cfg.config_path is not None, str(cfg.config_path or "missing — run `zotvault init`"))
    )
    checks.append(("zotero data dir", cfg.zotero_data_dir.exists(), str(cfg.zotero_data_dir)))
    checks.append(("zotero.sqlite", cfg.zotero_sqlite.exists(), str(cfg.zotero_sqlite)))
    checks.append(("zotero storage/", cfg.zotero_storage.exists(), str(cfg.zotero_storage)))
    reader = ZoteroReader(cfg.zotero_data_dir, cfg.connector_url)
    alive = reader.zotero_alive()
    checks.append(("zotero running (connector ping)", alive, cfg.connector_url))
    if alive:
        bbt = reader.bbt_citekeys(["__zotvault_probe__"])
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
        checks.append(("Better BibTeX (REQUIRED)", probe_ok,
                       "citekey source — without it NOTHING syncs" if not probe_ok
                       else "citekey source"))
    if cfg.vault_dir is None:
        checks.append(("vault (optional)", False,
                       "not set — Zotero-only mode; set [vault] dir to unlock "
                       "notes, highlight sync & the analysis queue"))
    else:
        vault_exists = cfg.vault_dir.exists()
        vault_detail = str(cfg.vault_dir)
        if not vault_exists:
            hint = _decorrupted_vault_hint(vault_detail)
            if hint:
                vault_detail += " — looks like a pasted path got backslash-corrupted; try: " + hint
        checks.append(("vault dir", vault_exists, vault_detail))
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
            checks.append(("ollama (optional, embeddings)", ok, cfg.ollama_url))
        except Exception:
            checks.append(("ollama (optional, embeddings)", False,
                           cfg.ollama_url + " unreachable — related/synthesis suggestions off"))
    if cfg.proxy_enabled:
        tmpl_ok = "{url}" in cfg.proxy_url_template
        checks.append(("proxy url_template", tmpl_ok,
                       cfg.proxy_url_template or "empty"))
        ck = Path(os.path.expanduser(cfg.proxy_cookie_file)) if cfg.proxy_cookie_file else None
        checks.append(("proxy cookie file", ck is not None and ck.exists(),
                       str(ck) if ck else "not set"))
        if ck is not None and ck.exists():
            mode = ck.stat().st_mode & 0o777
            checks.append(("proxy cookie permissions", mode in (0o600, 0o400),
                           oct(mode) + (" — run: chmod 600 " + str(ck) if mode not in (0o600, 0o400) else "")))
    if cfg.alerts_enabled:
        checks.append(("alerts keywords", bool(cfg.alerts_keywords),
                       ", ".join(cfg.alerts_keywords) or "empty"))
    if cfg.analysis_engine != "none":
        import shutil as _sh

        from zotvault import analyze as _an

        checks.append(("analysis engine", cfg.analysis_engine in _an.ENGINES,
                       _an.engine_label(cfg)))
        checks.append(("pdftotext (full-text input)", _an.pdftotext_available(),
                       "poppler" if _an.pdftotext_available() else "missing — falls back to abstract-only"))
        if cfg.analysis_engine == "claude-cli":
            checks.append(("claude CLI", _sh.which("claude") is not None, _sh.which("claude") or "not found"))
        if cfg.analysis_engine == "ollama":
            checks.append(("analysis model set", bool(cfg.analysis_model), cfg.analysis_model or "set [analysis] model"))
        if cfg.analysis_engine == "openai-compatible":
            checks.append(("analysis base_url", bool(cfg.analysis_base_url), cfg.analysis_base_url or "set [analysis] base_url"))
        if cfg.analysis_engine == "anthropic":
            import os as _os
            has_key = bool(cfg.analysis_api_key or _os.environ.get("ANTHROPIC_API_KEY"))
            checks.append(("anthropic api key", has_key, "set" if has_key else "missing"))
    return checks


