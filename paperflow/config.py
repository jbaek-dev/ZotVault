"""Configuration loading.

Hierarchy (later wins): built-in defaults -> config file (TOML) -> environment variables.

No personal data is hardcoded anywhere in the package; everything user-specific
lives in ~/.paperflow/config.toml (see CONFIG_TEMPLATE / `paperflow init`).

Python 3.9 compatible: uses tomllib when available (3.11+), otherwise a small
built-in parser that covers the subset of TOML this app uses (sections,
string/int/float/bool values, flat arrays of strings).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = "~/.paperflow/config.toml"

DEFAULT_ITEM_TYPES = [
    "journalArticle",
    "preprint",
    "conferencePaper",
    "book",
    "bookSection",
    "report",
    "thesis",
]

CONFIG_TEMPLATE = '''# PaperFlow configuration
# Location: ~/.paperflow/config.toml   (override with $PAPERFLOW_CONFIG)

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
# Downloaded PDFs are stored here (PaperFlow never writes into Zotero storage/)
dir = "~/.paperflow/pdfs"
# Required by the Unpaywall API. Use your real email.
unpaywall_email = ""
daily_download_limit = 20
request_delay_sec = 5
download_timeout_sec = 30

[app]
state_db = "~/.paperflow/state.db"
log_level = "INFO"
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
    pdf_dir: Path = Path("~/.paperflow/pdfs").expanduser()
    unpaywall_email: str = ""
    daily_download_limit: int = 20
    request_delay_sec: float = 5.0
    download_timeout_sec: int = 30
    # app
    state_db: Path = Path("~/.paperflow/state.db").expanduser()
    log_level: str = "INFO"
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
    """Parse the subset of TOML used by PaperFlow's config file.

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
    path = _expand(config_path or os.environ.get("PAPERFLOW_CONFIG", DEFAULT_CONFIG_PATH))
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

    cfg.pdf_dir = _expand(get("pdf", "dir", "~/.paperflow/pdfs"))
    cfg.unpaywall_email = str(get("pdf", "unpaywall_email", ""))
    cfg.daily_download_limit = int(get("pdf", "daily_download_limit", cfg.daily_download_limit))
    cfg.request_delay_sec = float(get("pdf", "request_delay_sec", cfg.request_delay_sec))
    cfg.download_timeout_sec = int(get("pdf", "download_timeout_sec", cfg.download_timeout_sec))

    cfg.state_db = _expand(get("app", "state_db", "~/.paperflow/state.db"))
    cfg.log_level = str(get("app", "log_level", cfg.log_level)).upper()

    # Environment overrides (highest priority)
    env = os.environ
    if env.get("PAPERFLOW_ZOTERO_DIR"):
        cfg.zotero_data_dir = _expand(env["PAPERFLOW_ZOTERO_DIR"])
    if env.get("PAPERFLOW_VAULT_DIR"):
        cfg.vault_dir = _expand(env["PAPERFLOW_VAULT_DIR"])
    if env.get("PAPERFLOW_CONNECTOR_URL"):
        cfg.connector_url = env["PAPERFLOW_CONNECTOR_URL"].rstrip("/")
    if env.get("PAPERFLOW_STATE_DB"):
        cfg.state_db = _expand(env["PAPERFLOW_STATE_DB"])
    if env.get("PAPERFLOW_DRY_RUN"):
        cfg.dry_run = env["PAPERFLOW_DRY_RUN"] not in ("0", "false", "False", "")
    return cfg
