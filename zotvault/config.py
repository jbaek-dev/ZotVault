"""Configuration loading.

Hierarchy (later wins): built-in defaults -> config file (TOML) -> environment variables.

No personal data is hardcoded anywhere in the package; everything user-specific
lives in ~/.zotvault/config.toml (see CONFIG_TEMPLATE / `zotvault init`).

Python 3.9 compatible: uses tomllib when available (3.11+), otherwise a small
built-in parser that covers the subset of TOML this app uses (sections,
string/int/float/bool values, flat arrays of strings).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = "~/.zotvault/config.toml"
APP_CODE_DIR = "~/.zotvault/app"  # where the launcher loads code from (see scripts/build_app.sh)

DEFAULT_ITEM_TYPES = [
    "journalArticle",
    "preprint",
    "conferencePaper",
    "book",
    "bookSection",
    "report",
    "thesis",
]

CONFIG_TEMPLATE = '''# ZotVault configuration
# Location: ~/.zotvault/config.toml   (override with $ZOTVAULT_CONFIG)

[zotero]
# Zotero data directory (contains zotero.sqlite and storage/)
data_dir = "~/Zotero"
# Local Zotero HTTP server (connector + Better BibTeX JSON-RPC)
connector_url = "http://127.0.0.1:23119"

[vault]
# Obsidian vault root. REQUIRED for note creation / queue / indexing.
dir = ""
# Where paper notes live, relative to the vault root
papers_subdir = "30_Resources/Papers/zotero"
index_file = "index.md"
log_file = "log.md"

[pipeline]
poll_interval_sec = 120
create_notes = true
resolve_pdfs = true
update_index = true
append_log = true
dry_run = false

[pdf]
# Downloaded PDFs are stored here (ZotVault never writes into Zotero storage/)
dir = "~/.zotvault/pdfs"
# Required by the Unpaywall API. Use your real email.
unpaywall_email = ""
daily_download_limit = 20
request_delay_sec = 5
download_timeout_sec = 30

[web]
# Local dashboard (bound to localhost only)
enabled = true
host = "127.0.0.1"
port = 8377

[search]
# Optional Semantic Scholar API key (higher rate limits)
semantic_scholar_api_key = ""
default_source = "arxiv"       # arxiv | s2 | crossref
max_results = 20

[proxy]
# Institutional proxy fallback for licensed PDFs. OFF by default.
# See docs/PROXY.md. {url} in the template is replaced with the target URL.
enabled = false
url_template = ""              # e.g. "https://login.ezproxy.example.edu/login?url={url}"
cookie_file = ""               # Netscape cookies.txt exported from a logged-in browser
daily_limit = 10
request_delay_sec = 10

[alerts]
# Daily arXiv keyword digest -> review inbox (dashboard/CLI); nothing is added
# to Zotero without your approval.
enabled = false
keywords = []                  # e.g. ["valleytronics", "Janus TMDC"]
categories = ["cond-mat.mes-hall"]
lookback_hours = 48
hour = 7
max_per_fetch = 30

[ollama]
# Local embeddings for related-paper suggestions (free, optional)
url = "http://127.0.0.1:11434"
embed_model = "nomic-embed-text"

[features]
citation_graph = true
related_papers = true
synthesis_suggestions = true
enrich_every_hours = 24

[annotations]
# Edit-safe Zotero highlight sync. Notes created by ZotVault carry a marker
# block that is kept in sync; notes WITHOUT markers are never touched unless
# adopt_existing = true (appends the block once at the end).
enabled = true
adopt_existing = false
include_comments = true

[analysis]
# Pluggable AI review engine. "none" = manual workflow (queue only). Others
# generate {citekey}_*_analysis.md automatically (never overwrites existing):
#   ollama            local & free  -> also set: model = "qwen2.5:14b" (etc.)
#   claude-cli        uses your Claude Code subscription (`claude -p`)
#   openai-compatible LM Studio / vLLM / OpenRouter ... -> set base_url (+model)
#   anthropic         Anthropic API -> set api_key or $ANTHROPIC_API_KEY (+model)
engine = "none"
model = ""
base_url = ""
api_key = ""
auto = false            # let the daemon analyze new papers automatically
daily_limit = 5

[app]
state_db = "~/.zotvault/state.db"
log_level = "INFO"
language = "en"          # en | ko (affects log.md wording and messages)
'''


@dataclass
class Config:
    # zotero
    zotero_data_dir: Path = Path("~/Zotero").expanduser()
    connector_url: str = "http://127.0.0.1:23119"
    # vault
    vault_dir: Optional[Path] = None
    papers_subdir: str = "30_Resources/Papers/zotero"
    index_file: str = "index.md"
    log_file: str = "log.md"
    # pipeline
    poll_interval_sec: int = 120
    create_notes: bool = True
    resolve_pdfs: bool = True
    update_index: bool = True
    append_log: bool = True
    dry_run: bool = False
    item_types: List[str] = field(default_factory=lambda: list(DEFAULT_ITEM_TYPES))
    # pdf
    pdf_dir: Path = Path("~/.zotvault/pdfs").expanduser()
    unpaywall_email: str = ""
    daily_download_limit: int = 20
    request_delay_sec: float = 5.0
    download_timeout_sec: int = 30
    # web dashboard
    web_enabled: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = 8377
    # zotero write path (optional translation-server for URL imports)
    translation_server_url: str = ""
    # institutional proxy fallback (M3) — disabled by default
    proxy_enabled: bool = False
    proxy_url_template: str = ""
    proxy_cookie_file: str = ""
    proxy_daily_limit: int = 10
    proxy_request_delay_sec: float = 10.0
    # search
    s2_api_key: str = ""
    search_default_source: str = "arxiv"
    search_max_results: int = 20
    # arXiv alerts
    alerts_enabled: bool = False
    alerts_keywords: List[str] = field(default_factory=list)
    alerts_categories: List[str] = field(default_factory=lambda: ["cond-mat.mes-hall"])
    alerts_lookback_hours: int = 48
    alerts_hour: int = 7
    alerts_max_per_fetch: int = 30
    # local intelligence (Ollama embeddings + Semantic Scholar enrichment)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "nomic-embed-text"
    feat_citation_graph: bool = True
    feat_related: bool = True
    feat_synthesis: bool = True
    enrich_every_hours: int = 24
    enrich_budget_per_run: int = 40
    embed_budget_per_run: int = 30
    related_threshold: float = 0.75
    synthesis_threshold: float = 0.70
    synthesis_min_cluster: int = 4
    # annotations sync (v0.8) — edit-safe marker blocks
    annotations_enabled: bool = True
    annotations_adopt_existing: bool = False   # append block to unmarked notes
    annotations_include_comments: bool = True
    annotations_max_quote_chars: int = 600
    # analysis engine (v0.6) — pluggable AI review
    analysis_engine: str = "none"       # none|ollama|claude-cli|openai-compatible|anthropic
    analysis_model: str = ""
    analysis_base_url: str = ""          # openai-compatible endpoint, e.g. http://localhost:1234/v1
    analysis_api_key: str = ""           # or $OPENAI_API_KEY / $ANTHROPIC_API_KEY
    analysis_prompt_file: str = ""       # custom prompt template
    analysis_suffix: str = ""            # analysis filename tag; default per engine
    analysis_auto: bool = False          # daemon auto-analyzes new papers (budgeted)
    analysis_daily_limit: int = 5
    analysis_max_chars: int = 40000
    analysis_timeout_sec: int = 600
    # app
    state_db: Path = Path("~/.zotvault/state.db").expanduser()
    log_level: str = "INFO"
    language: str = "en"           # en | ko — locale for log.md / messages
    template_file: str = ""        # override note template (see note_renderer.DEFAULT_TEMPLATE)
    config_path: Optional[Path] = None

    @property
    def papers_dir(self) -> Optional[Path]:
        if self.vault_dir is None:
            return None
        return self.vault_dir / self.papers_subdir

    @property
    def index_path(self) -> Optional[Path]:
        return None if self.vault_dir is None else self.vault_dir / self.index_file

    @property
    def log_path(self) -> Optional[Path]:
        return None if self.vault_dir is None else self.vault_dir / self.log_file

    @property
    def zotero_sqlite(self) -> Path:
        return self.zotero_data_dir / "zotero.sqlite"

    @property
    def zotero_storage(self) -> Path:
        return self.zotero_data_dir / "storage"


# ---------------------------------------------------------------------------
# TOML parsing (tomllib on 3.11+, minimal fallback parser on 3.9/3.10)
# ---------------------------------------------------------------------------

def _parse_scalar(token: str) -> Any:
    token = token.strip()
    if token.startswith('"') and token.endswith('"') and len(token) >= 2:
        return token[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    low = token.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _strip_comment(line: str) -> str:
    """Remove a trailing comment, respecting double-quoted strings."""
    out = []
    in_str = False
    prev = ""
    for ch in line:
        if ch == '"' and prev != "\\":
            in_str = not in_str
        if ch == "#" and not in_str:
            break
        out.append(ch)
        prev = ch
    return "".join(out)


def parse_toml_mini(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse the subset of TOML used by ZotVault's config file.

    Supports [sections], key = "string" | int | float | bool | ["a", "b"].
    Does NOT support nested tables, multi-line strings, or dates.
    """
    data: Dict[str, Dict[str, Any]] = {}
    section: Optional[str] = None
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue
        if "=" not in line or section is None:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if val.startswith("["):
            inner = val.strip()[1:-1]
            items = [t.strip() for t in inner.split(",") if t.strip()]
            data[section][key.strip()] = [_parse_scalar(t) for t in items]
        else:
            data[section][key.strip()] = _parse_scalar(val)
    return data


def _load_toml_file(path: Path) -> Dict[str, Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # Python 3.11+

        return tomllib.loads(text)
    except ModuleNotFoundError:
        return parse_toml_mini(text)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _expand(p: str) -> Path:
    return Path(os.path.expanduser(str(p)))


def load_config(config_path: Optional[str] = None) -> Config:
    cfg = Config()
    path = _expand(config_path or os.environ.get("ZOTVAULT_CONFIG", DEFAULT_CONFIG_PATH))
    data: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        data = _load_toml_file(path)
        cfg.config_path = path

    def get(section: str, key: str, default: Any) -> Any:
        return data.get(section, {}).get(key, default)

    cfg.zotero_data_dir = _expand(get("zotero", "data_dir", "~/Zotero"))
    cfg.connector_url = str(get("zotero", "connector_url", cfg.connector_url)).rstrip("/")

    vault_dir = str(get("vault", "dir", "")).strip()
    cfg.vault_dir = _expand(vault_dir) if vault_dir else None
    cfg.papers_subdir = str(get("vault", "papers_subdir", cfg.papers_subdir))
    cfg.index_file = str(get("vault", "index_file", cfg.index_file))
    cfg.log_file = str(get("vault", "log_file", cfg.log_file))

    cfg.poll_interval_sec = int(get("pipeline", "poll_interval_sec", cfg.poll_interval_sec))
    cfg.create_notes = bool(get("pipeline", "create_notes", cfg.create_notes))
    cfg.resolve_pdfs = bool(get("pipeline", "resolve_pdfs", cfg.resolve_pdfs))
    cfg.update_index = bool(get("pipeline", "update_index", cfg.update_index))
    cfg.append_log = bool(get("pipeline", "append_log", cfg.append_log))
    cfg.dry_run = bool(get("pipeline", "dry_run", cfg.dry_run))
    item_types = get("pipeline", "item_types", None)
    if isinstance(item_types, list) and item_types:
        cfg.item_types = [str(t) for t in item_types]

    cfg.pdf_dir = _expand(get("pdf", "dir", "~/.zotvault/pdfs"))
    cfg.unpaywall_email = str(get("pdf", "unpaywall_email", ""))
    cfg.daily_download_limit = int(get("pdf", "daily_download_limit", cfg.daily_download_limit))
    cfg.request_delay_sec = float(get("pdf", "request_delay_sec", cfg.request_delay_sec))
    cfg.download_timeout_sec = int(get("pdf", "download_timeout_sec", cfg.download_timeout_sec))

    cfg.web_enabled = bool(get("web", "enabled", cfg.web_enabled))
    cfg.web_host = str(get("web", "host", cfg.web_host))
    cfg.web_port = int(get("web", "port", cfg.web_port))

    cfg.translation_server_url = str(get("zotero", "translation_server_url", "")).rstrip("/")

    cfg.proxy_enabled = bool(get("proxy", "enabled", cfg.proxy_enabled))
    cfg.proxy_url_template = str(get("proxy", "url_template", ""))
    cfg.proxy_cookie_file = str(get("proxy", "cookie_file", ""))
    cfg.proxy_daily_limit = int(get("proxy", "daily_limit", cfg.proxy_daily_limit))
    cfg.proxy_request_delay_sec = float(get("proxy", "request_delay_sec", cfg.proxy_request_delay_sec))

    cfg.s2_api_key = str(get("search", "semantic_scholar_api_key", ""))
    cfg.search_default_source = str(get("search", "default_source", cfg.search_default_source))
    cfg.search_max_results = int(get("search", "max_results", cfg.search_max_results))

    cfg.alerts_enabled = bool(get("alerts", "enabled", cfg.alerts_enabled))
    kw = get("alerts", "keywords", None)
    if isinstance(kw, list):
        cfg.alerts_keywords = [str(k) for k in kw]
    cats = get("alerts", "categories", None)
    if isinstance(cats, list) and cats:
        cfg.alerts_categories = [str(c) for c in cats]
    cfg.alerts_lookback_hours = int(get("alerts", "lookback_hours", cfg.alerts_lookback_hours))
    cfg.alerts_hour = int(get("alerts", "hour", cfg.alerts_hour))
    cfg.alerts_max_per_fetch = int(get("alerts", "max_per_fetch", cfg.alerts_max_per_fetch))

    cfg.ollama_url = str(get("ollama", "url", cfg.ollama_url)).rstrip("/")
    cfg.ollama_embed_model = str(get("ollama", "embed_model", cfg.ollama_embed_model))
    cfg.feat_citation_graph = bool(get("features", "citation_graph", cfg.feat_citation_graph))
    cfg.feat_related = bool(get("features", "related_papers", cfg.feat_related))
    cfg.feat_synthesis = bool(get("features", "synthesis_suggestions", cfg.feat_synthesis))
    cfg.enrich_every_hours = int(get("features", "enrich_every_hours", cfg.enrich_every_hours))
    cfg.enrich_budget_per_run = int(get("features", "enrich_budget_per_run", cfg.enrich_budget_per_run))
    cfg.embed_budget_per_run = int(get("features", "embed_budget_per_run", cfg.embed_budget_per_run))
    cfg.related_threshold = float(get("features", "related_threshold", cfg.related_threshold))
    cfg.synthesis_threshold = float(get("features", "synthesis_threshold", cfg.synthesis_threshold))
    cfg.synthesis_min_cluster = int(get("features", "synthesis_min_cluster", cfg.synthesis_min_cluster))

    cfg.annotations_enabled = bool(get("annotations", "enabled", cfg.annotations_enabled))
    cfg.annotations_adopt_existing = bool(get("annotations", "adopt_existing",
                                              cfg.annotations_adopt_existing))
    cfg.annotations_include_comments = bool(get("annotations", "include_comments",
                                                cfg.annotations_include_comments))
    cfg.annotations_max_quote_chars = int(get("annotations", "max_quote_chars",
                                              cfg.annotations_max_quote_chars))

    cfg.analysis_engine = str(get("analysis", "engine", cfg.analysis_engine)).lower()
    cfg.analysis_model = str(get("analysis", "model", ""))
    cfg.analysis_base_url = str(get("analysis", "base_url", "")).rstrip("/")
    cfg.analysis_api_key = str(get("analysis", "api_key", ""))
    cfg.analysis_prompt_file = str(get("analysis", "prompt_file", ""))
    cfg.analysis_suffix = str(get("analysis", "suffix", ""))
    cfg.analysis_auto = bool(get("analysis", "auto", cfg.analysis_auto))
    cfg.analysis_daily_limit = int(get("analysis", "daily_limit", cfg.analysis_daily_limit))
    cfg.analysis_max_chars = int(get("analysis", "max_chars", cfg.analysis_max_chars))
    cfg.analysis_timeout_sec = int(get("analysis", "timeout_sec", cfg.analysis_timeout_sec))

    cfg.state_db = _expand(get("app", "state_db", "~/.zotvault/state.db"))
    cfg.log_level = str(get("app", "log_level", cfg.log_level)).upper()
    cfg.language = str(get("app", "language", cfg.language)).lower()
    cfg.template_file = str(get("vault", "template_file", ""))
    from zotvault.i18n import set_language
    set_language(cfg.language)

    # Environment overrides (highest priority)
    env = os.environ
    if env.get("ZOTVAULT_ZOTERO_DIR"):
        cfg.zotero_data_dir = _expand(env["ZOTVAULT_ZOTERO_DIR"])
    if env.get("ZOTVAULT_VAULT_DIR"):
        cfg.vault_dir = _expand(env["ZOTVAULT_VAULT_DIR"])
    if env.get("ZOTVAULT_CONNECTOR_URL"):
        cfg.connector_url = env["ZOTVAULT_CONNECTOR_URL"].rstrip("/")
    if env.get("ZOTVAULT_STATE_DB"):
        cfg.state_db = _expand(env["ZOTVAULT_STATE_DB"])
    if env.get("ZOTVAULT_DRY_RUN"):
        cfg.dry_run = env["ZOTVAULT_DRY_RUN"] not in ("0", "false", "False", "")
    return cfg
