"""PDF acquisition: open-access first, politely rate-limited.

Chain (M1): Zotero attachment -> local cache -> arXiv -> Unpaywall.
Institutional proxy fallback is milestone M3 and intentionally absent here.

Etiquette safeguards (bulk-download bans are real):
- sequential downloads only, with a delay after every network fetch
- hard daily download limit (state-tracked)
- honest User-Agent including a contact email

Downloads land in cfg.pdf_dir — PaperFlow never writes into Zotero storage/.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from paperflow import __version__
from paperflow.config import Config
from paperflow.state import State
from paperflow.zotero_reader import RawItem

_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.I)
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)
_ARXIV_EXTRA_RE = re.compile(r"arXiv:\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", re.I)

_MIN_PDF_BYTES = 10_000


def _ua(cfg: Config) -> str:
    contact = cfg.unpaywall_email or "no-contact-configured"
    return "PaperFlow/{} (mailto:{})".format(__version__, contact)


def find_arxiv_id(item: RawItem) -> Optional[str]:
    for text, rx in ((item.url, _ARXIV_URL_RE), (item.doi, _ARXIV_DOI_RE), (item.extra, _ARXIV_EXTRA_RE)):
        if not text:
            continue
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


def unpaywall_pdf_urls(doi: str, email: str, timeout: int) -> List[str]:
    if not doi or not email:
        return []
    url = "https://api.unpaywall.org/v2/{}?email={}".format(
        urllib.parse.quote(doi), urllib.parse.quote(email)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "PaperFlow/" + __version__})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    urls: List[str] = []
    locations = []
    if data.get("best_oa_location"):
        locations.append(data["best_oa_location"])
    locations.extend(data.get("oa_locations") or [])
    for loc in locations:
        for key in ("url_for_pdf", "url"):
            u = (loc or {}).get(key)
            if u and u not in urls:
                urls.append(u)
    return urls


def download_pdf(url: str, dest: Path, cfg: Config) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": _ua(cfg), "Accept": "application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.download_timeout_sec) as resp:
            data = resp.read()
    except Exception:
        return False
    if len(data) < _MIN_PDF_BYTES or not data[:8].lstrip().startswith(b"%PDF"):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return True


def resolve(item: RawItem, cfg: Config, state: State) -> Tuple[str, Optional[str]]:
    """Return (status, path). status: zotero|cached|downloaded|deferred|disabled|missing."""
    # 1. Zotero already has it
    if item.pdf_path:
        return "zotero", item.pdf_path
    # 2. previously downloaded
    cached = cfg.pdf_dir / (item.citekey + ".pdf") if item.citekey else None
    if cached is not None and cached.exists():
        return "cached", str(cached)
    if not cfg.resolve_pdfs:
        return "disabled", None
    if cached is None:
        return "missing", None
    if cfg.dry_run:
        return "deferred", None
    # 3. budget check
    if state.downloads_today() >= cfg.daily_download_limit:
        state.trace("pdf_deferred", item.citekey or item.item_key, "daily download limit reached")
        return "deferred", None
    # 4. candidate URLs, OA only (proxy fallback is M3)
    candidates: List[str] = []
    arxiv_id = find_arxiv_id(item)
    if arxiv_id:
        candidates.append("https://arxiv.org/pdf/" + arxiv_id)
    candidates.extend(unpaywall_pdf_urls(item.doi, cfg.unpaywall_email, cfg.download_timeout_sec))
    tried = 0
    for url in candidates[:5]:
        tried += 1
        ok = download_pdf(url, cached, cfg)
        time.sleep(max(0.0, cfg.request_delay_sec))
        if ok:
            state.record_download()
            state.trace("pdf_downloaded", item.citekey, url)
            return "downloaded", str(cached)
    if tried:
        state.trace("pdf_not_found", item.citekey or item.item_key, "{} candidate(s) failed".format(tried))
    return "missing", None
