"""Institutional proxy fallback for licensed PDFs (M3). OFF by default.

Design constraints (deliberate):
- Only used AFTER open-access sources fail.
- Separate, stricter budget (proxy_daily_limit) + longer delay between requests.
  Systematic bulk downloading violates library license agreements and gets
  whole universities blocked by publishers — PaperFlow refuses to be that tool.
- Authentication is NOT automated (Duo/2FA can't be headless anyway). Instead,
  reuse the session cookies of a browser where you are already logged in:
  export a Netscape cookies.txt and point [proxy] cookie_file at it.
  See docs/PROXY.md for setup.

Fetch heuristic:
1. GET the proxied DOI landing page (template rewrites the URL through EZproxy
   or similar).
2. If the response is already a PDF -> done.
3. Otherwise look for the standard `citation_pdf_url` meta tag (present on
   virtually all publisher pages for Google Scholar indexing) and fetch that.
"""
from __future__ import annotations

import http.cookiejar
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from paperflow import __version__
from paperflow.config import Config
from paperflow.state import State
from paperflow.zotero_reader import RawItem

log = logging.getLogger("paperflow.proxy")

_META_PDF_RES = [
    re.compile(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']', re.I),
]

_MIN_PDF_BYTES = 10_000
_MAX_HTML_BYTES = 3_000_000


def load_cookiejar(cookie_file: str) -> http.cookiejar.MozillaCookieJar:
    jar = http.cookiejar.MozillaCookieJar(os.path.expanduser(cookie_file))
    jar.load(ignore_discard=True, ignore_expires=True)
    # Browser-exported *session* cookies (the EZproxy ones) carry expiry=0.
    # http.cookiejar loads them but refuses to SEND expired cookies — pin them
    # to the far future; the proxy server decides real validity.
    future = int(time.time()) + 365 * 24 * 3600
    for c in jar:
        if not c.expires:
            c.expires = future
            c.discard = False
    return jar


def build_opener(jar: http.cookiejar.CookieJar) -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Macintosh) PaperFlow/{}".format(__version__)),
        ("Accept", "application/pdf,text/html,application/xhtml+xml,*/*"),
    ]
    return opener


def proxied_url(url: str, template: str) -> str:
    if "{url}" not in template:
        raise ValueError("proxy url_template must contain {url}")
    return template.replace("{url}", urllib.parse.quote(url, safe=":/?&=%~._-"))


def is_proxied(url: str, template: str) -> bool:
    """True when the URL already lives on the proxy host (rewritten form)."""
    proxy_host = urllib.parse.urlparse(template.replace("{url}", "x")).netloc.lower()
    host = urllib.parse.urlparse(url).netloc.lower()
    return bool(proxy_host) and (host == proxy_host or host.endswith("." + proxy_host))


def pdf_url_candidates(pdf_url: str, template: str) -> list:
    """Order of attempts for a citation_pdf_url, all routed through the proxy.

    Publishers sometimes serve an HTML viewer at /doi/pdf/ — the Wiley-style
    /doi/pdfdirect/ variant returns the raw file, so try it first.
    """
    variants = []
    if "/doi/pdf/" in pdf_url:
        variants.append(pdf_url.replace("/doi/pdf/", "/doi/pdfdirect/"))
    variants.append(pdf_url)
    out = []
    for v in variants:
        out.append(v if is_proxied(v, template) else proxied_url(v, template))
    return out


def extract_pdf_url(html: str, base_url: str) -> Optional[str]:
    for rx in _META_PDF_RES:
        m = rx.search(html)
        if m:
            return urllib.parse.urljoin(base_url, m.group(1))
    return None


def _is_pdf(data: bytes) -> bool:
    return len(data) >= _MIN_PDF_BYTES and data[:8].lstrip().startswith(b"%PDF")


def fetch_licensed_pdf(item: RawItem, cfg: Config, state: State) -> Tuple[bool, str]:
    """Try to download a licensed PDF through the configured proxy.

    Returns (saved, message). Never raises.
    """
    if not cfg.proxy_enabled:
        return False, "proxy disabled"
    if not cfg.proxy_url_template or "{url}" not in cfg.proxy_url_template:
        return False, "proxy url_template not configured"
    if not item.citekey:
        return False, "no citekey"
    landing = ("https://doi.org/" + item.doi) if item.doi else (item.url or "")
    if not landing:
        return False, "no DOI or URL to resolve"
    if state.proxy_downloads_today() >= cfg.proxy_daily_limit:
        state.trace("proxy_deferred", item.citekey, "proxy daily limit reached")
        return False, "proxy daily limit reached"

    try:
        jar = load_cookiejar(cfg.proxy_cookie_file) if cfg.proxy_cookie_file else http.cookiejar.CookieJar()
    except Exception as exc:
        return False, "cookie file unreadable: {}".format(exc)
    opener = build_opener(jar)
    dest = cfg.pdf_dir / (item.citekey + ".pdf")

    try:
        target = proxied_url(landing, cfg.proxy_url_template)
        with opener.open(target, timeout=cfg.download_timeout_sec) as resp:
            final_url = resp.geturl()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read(_MAX_HTML_BYTES)
        time.sleep(max(0.0, cfg.proxy_request_delay_sec))

        if "pdf" in ctype or _is_pdf(data):
            if not _is_pdf(data):
                return False, "response claimed PDF but wasn't"
            _save(dest, data)
            state.record_proxy_download()
            state.trace("pdf_downloaded_proxy", item.citekey, final_url[:200])
            return True, str(dest)

        # HTML landing page -> citation_pdf_url
        html = data.decode("utf-8", errors="replace")
        if "not been configured for access" in html:
            return False, ("EZproxy: this publisher is not in the library's stanza list — "
                           "ask the library to add it (host: {})".format(landing.split("/")[2]))
        pdf_url = extract_pdf_url(html, final_url)
        if not pdf_url:
            # login redirect is the usual cause
            if "login" in final_url.lower() or "auth" in final_url.lower():
                return False, "proxy session expired — re-export cookies.txt after logging in"
            return False, "no citation_pdf_url on landing page"
        for target in pdf_url_candidates(pdf_url, cfg.proxy_url_template):
            with opener.open(target, timeout=cfg.download_timeout_sec) as resp:
                data = resp.read()
            time.sleep(max(0.0, cfg.proxy_request_delay_sec))
            if _is_pdf(data):
                _save(dest, data)
                state.record_proxy_download()
                state.trace("pdf_downloaded_proxy", item.citekey, target[:200])
                return True, str(dest)
        return False, "citation_pdf_url did not return a PDF (viewer-only or bot-blocked publisher)"
    except Exception as exc:
        return False, str(exc)[:200]


def _save(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
