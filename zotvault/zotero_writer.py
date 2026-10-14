"""Add items to Zotero programmatically — the M2 "one-shot DOI add".

Resolution paths (first available wins):
1. translation-server (optional, config [zotero] translation_server_url):
   Zotero's official translation service; also handles arbitrary web URLs.
2. Native resolvers (zero dependencies, default):
   - DOI    -> Crossref REST API (fallback: DataCite)
   - arXiv  -> arXiv export API

Saving uses POST /connector/saveItems on Zotero's local HTTP server —
exactly the channel the browser connector uses. Zotero desktop must be
running; Better BibTeX assigns the citekey on arrival, and the ZotVault
daemon picks the new item up on its next cycle (note -> PDF -> queue).
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from zotvault import __version__
from zotvault.config import Config
from zotvault.state import State

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.I)
_ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")

_CROSSREF_TYPE_MAP = {
    "journal-article": "journalArticle",
    "proceedings-article": "conferencePaper",
    "book-chapter": "bookSection",
    "book": "book",
    "monograph": "book",
    "posted-content": "preprint",
    "report": "report",
    "dissertation": "thesis",
}

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _ua() -> str:
    return "ZotVault/{} (https://github.com/jbaek-dev/ZotVault; local research tool)".format(__version__)


def _get(url: str, timeout: int = 20, headers: Optional[Dict[str, str]] = None) -> bytes:
    h = {"User-Agent": _ua()}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# identifier classification
# ---------------------------------------------------------------------------

def classify_identifier(raw: str) -> Tuple[str, str]:
    """Return (kind, normalized) with kind in doi|arxiv|url|unknown."""
    s = (raw or "").strip()
    if not s:
        return "unknown", s
    low = s.lower()
    # doi.org URLs and bare DOIs
    if "doi.org/" in low:
        m = _DOI_RE.search(urllib.parse.unquote(s))
        if m:
            return "doi", m.group(1).rstrip(".,;)")
    if low.startswith("doi:"):
        s = s[4:].strip()
        low = s.lower()
    if low.startswith("10."):
        m = _DOI_RE.search(s)
        if m:
            return "doi", m.group(1).rstrip(".,;)")
    # arXiv ids / URLs
    if "arxiv.org/" in low or low.startswith("arxiv:"):
        text = s.split(":", 1)[1] if low.startswith("arxiv:") else s
        m = _ARXIV_NEW_RE.search(text) or _ARXIV_OLD_RE.search(text)
        if m:
            return "arxiv", m.group(1) + (m.group(2) or "")
    m = _ARXIV_NEW_RE.fullmatch(s) or _ARXIV_OLD_RE.fullmatch(s)
    if m:
        return "arxiv", m.group(1) + (m.group(2) or "")
    if low.startswith("http://") or low.startswith("https://"):
        return "url", s
    # last chance: a DOI buried in free text
    m = _DOI_RE.search(s)
    if m:
        return "doi", m.group(1).rstrip(".,;)")
    return "unknown", s


# ---------------------------------------------------------------------------
# native resolvers (pure parse functions kept separate for testability)
# ---------------------------------------------------------------------------

def strip_markup(text: str, sep: str = "") -> str:
    """Remove embedded XML/HTML (JATS, MathML) from Crossref-style rich text.

    Crossref ships titles like ``bilayer <mml:math…><mml:msub><mml:mi>MoS
    </mml:mi><mml:mn>2</mml:mn></mml:msub></mml:math>`` — for titles the tag
    replacement must be EMPTY so adjacent text nodes join ("MoS" + "2" →
    "MoS2"); for abstracts a space keeps JATS paragraphs apart. LaTeX
    ``<mml:annotation>`` duplicates the rendered text, so it is dropped
    wholesale. Entities are unescaped last (safe: tags are already gone).
    """
    t = re.sub(r"<mml:annotation\b[^>]*>.*?</mml:annotation>", "", text or "",
               flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", sep, t)
    t = html.unescape(t)
    return " ".join(t.split())


def _strip_jats(text: str) -> str:
    return strip_markup(text, sep=" ")


# --- LaTeX-in-titles (arXiv) -> readable unicode (v0.9.6) -------------------
# arXiv titles/abstracts carry raw TeX: "monolayer WSe$_2$", "$\Gamma$ point",
# "10$^{-9}$ s". Rendered as-is they look broken in the dashboard AND would be
# saved verbatim into Zotero on approve/add.

_SUB = str.maketrans("0123456789+-=()x", "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089\u208a\u208b\u208c\u208d\u208e\u2093")
_SUP = str.maketrans("0123456789+-=()ni", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b\u207c\u207d\u207e\u207f\u2071")
_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_TEXSYM = {"times": "×", "cdot": "·", "pm": "±", "mp": "∓", "sim": "~",
           "approx": "≈", "to": "→", "rightarrow": "→", "leftarrow": "←",
           "prime": "′", "degree": "°", "circ": "°", "infty": "∞",
           "AA": "Å", "angstrom": "Å", "hbar": "ℏ", "ell": "ℓ"}


def _tex_names(text: str) -> str:
    for name, ch in _GREEK.items():
        text = re.sub(r"\\" + name + r"(?![A-Za-z])", ch, text)
    for name, ch in _TEXSYM.items():
        text = re.sub(r"\\" + name + r"(?![A-Za-z])", ch, text)
    return text


def _convert_math(seg: str) -> str:
    seg = re.sub(r"\\(?:mathrm|mathbf|mathit|textrm|textbf|textit|text|rm|bf|it)\s*\{([^{}]*)\}", r"\1", seg)
    seg = _tex_names(seg)

    def script(m: "re.Match", table: Dict[int, str]) -> str:
        body = m.group(1) if m.group(1) is not None else m.group(2)
        conv = body.translate(table)
        return conv if conv != body or body == "" else body  # best effort

    seg = re.sub(r"_\{([^{}]*)\}|_(\S)", lambda m: script(m, _SUB), seg)
    seg = re.sub(r"\^\{([^{}]*)\}|\^(\S)", lambda m: script(m, _SUP), seg)
    seg = seg.replace("\\,", " ").replace("\\;", " ").replace("\\!", "")
    seg = seg.replace("{", "").replace("}", "")
    return seg


def delatex(text: str) -> str:
    r"""Best-effort LaTeX -> readable unicode for titles/abstracts.

    Only $...$ segments get sub/superscript treatment (a bare "_" outside math
    must survive untouched); Greek/symbol commands are mapped everywhere; the
    escape forms \%, \&, \_ are unescaped. Unknown commands lose only the
    backslash — degrading to a readable word beats dropping content.
    """
    t = re.sub(r"\$([^$]*)\$", lambda m: _convert_math(m.group(1)), text or "")
    t = _tex_names(t)
    t = t.replace("\\%", "%").replace("\\&", "&").replace("\\_", "_")
    t = re.sub(r"\\([A-Za-z]+)", r"\1", t)
    return " ".join(t.split())


def parse_crossref(msg: Dict[str, Any]) -> Dict[str, Any]:
    itype = _CROSSREF_TYPE_MAP.get(msg.get("type", ""), "journalArticle")
    titles = msg.get("title") or []
    title = strip_markup(titles[0] if titles else "")
    creators = []
    for a in msg.get("author") or []:
        if a.get("family"):
            creators.append({
                "creatorType": "author",
                "firstName": a.get("given", ""),
                "lastName": a["family"],
            })
        elif a.get("name"):
            creators.append({"creatorType": "author", "lastName": a["name"], "fieldMode": 1})
    parts = (msg.get("issued") or {}).get("date-parts") or [[]]
    date = "-".join("{:02d}".format(p) if i else str(p) for i, p in enumerate(parts[0]) if p is not None)
    container = msg.get("container-title") or []
    item: Dict[str, Any] = {
        "itemType": itype,
        "title": title,
        "creators": creators,
        "date": date,
        "DOI": msg.get("DOI", ""),
        "url": msg.get("URL", ""),
        "abstractNote": _strip_jats(msg.get("abstract", "")),
        "volume": str(msg.get("volume", "") or ""),
        "issue": str(msg.get("issue", "") or ""),
        "pages": str(msg.get("page", "") or ""),
        "libraryCatalog": "Crossref (ZotVault)",
    }
    if itype in ("journalArticle", "conferencePaper"):
        item["publicationTitle"] = strip_markup(container[0] if container else "")
    if itype == "preprint":
        item["repository"] = (msg.get("institution") or [{}])[0].get("name", "") if msg.get("institution") else ""
    return item


def parse_datacite(attrs: Dict[str, Any]) -> Dict[str, Any]:
    titles = attrs.get("titles") or [{}]
    creators = []
    for c in attrs.get("creators") or []:
        if c.get("familyName"):
            creators.append({
                "creatorType": "author",
                "firstName": c.get("givenName", ""),
                "lastName": c["familyName"],
            })
        elif c.get("name"):
            creators.append({"creatorType": "author", "lastName": c["name"], "fieldMode": 1})
    return {
        "itemType": "journalArticle",
        "title": strip_markup(titles[0].get("title", "")),
        "creators": creators,
        "date": str(attrs.get("publicationYear", "") or ""),
        "DOI": attrs.get("doi", ""),
        "url": attrs.get("url", ""),
        "abstractNote": "",
        "libraryCatalog": "DataCite (ZotVault)",
    }


def resolve_doi(doi: str, timeout: int = 20) -> Dict[str, Any]:
    try:
        data = json.loads(_get(
            "https://api.crossref.org/works/" + urllib.parse.quote(doi), timeout).decode("utf-8"))
        return parse_crossref(data["message"])
    except Exception:
        data = json.loads(_get(
            "https://api.datacite.org/dois/" + urllib.parse.quote(doi), timeout).decode("utf-8"))
        return parse_datacite(data["data"]["attributes"])


def parse_arxiv_atom(xml_text: str) -> List[Dict[str, Any]]:
    """Parse an arXiv Atom feed into a list of entry dicts (shared with search/alerts)."""
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall(_ATOM + "entry"):
        raw_id = (e.findtext(_ATOM + "id") or "").rsplit("/", 1)[-1]
        pdf_url = ""
        for link in e.findall(_ATOM + "link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
        out.append({
            "arxiv_id": raw_id,
            "title": delatex(e.findtext(_ATOM + "title") or ""),
            "summary": delatex(e.findtext(_ATOM + "summary") or ""),
            "published": (e.findtext(_ATOM + "published") or "")[:10],
            "authors": [a.findtext(_ATOM + "name") or "" for a in e.findall(_ATOM + "author")],
            "doi": e.findtext(_ARXIV_NS + "doi") or "",
            "pdf_url": pdf_url or ("https://arxiv.org/pdf/" + raw_id if raw_id else ""),
            "categories": [c.get("term", "") for c in e.findall(_ATOM + "category")],
        })
    return out


def _author_to_creator(name: str) -> Dict[str, Any]:
    parts = name.strip().split()
    if len(parts) >= 2:
        return {"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]}
    return {"creatorType": "author", "lastName": name.strip(), "fieldMode": 1}


def entry_to_preprint_item(entry: Dict[str, Any]) -> Dict[str, Any]:
    aid = entry.get("arxiv_id", "")
    return {
        "itemType": "preprint",
        "title": entry.get("title", ""),
        "creators": [_author_to_creator(n) for n in entry.get("authors", [])],
        "date": entry.get("published", ""),
        "DOI": entry.get("doi", ""),
        "url": "https://arxiv.org/abs/" + aid if aid else "",
        "abstractNote": entry.get("summary", ""),
        "repository": "arXiv",
        "archiveID": "arXiv:" + aid if aid else "",
        "libraryCatalog": "arXiv (ZotVault)",
    }


def resolve_arxiv(arxiv_id: str, timeout: int = 20) -> Dict[str, Any]:
    xml_text = _get(
        "https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id),
        timeout,
    ).decode("utf-8")
    entries = parse_arxiv_atom(xml_text)
    if not entries or not entries[0].get("title"):
        raise ValueError("arXiv id not found: " + arxiv_id)
    entry = entries[0]
    item = entry_to_preprint_item(entry)
    item["_pdf_url"] = entry.get("pdf_url", "")
    return item


# ---------------------------------------------------------------------------
# optional translation-server
# ---------------------------------------------------------------------------

def ts_lookup(identifier_or_url: str, ts_url: str, kind: str, timeout: int = 30) -> List[Dict[str, Any]]:
    endpoint = "/web" if kind == "url" else "/search"
    req = urllib.request.Request(
        ts_url + endpoint,
        data=identifier_or_url.encode("utf-8"),
        headers={"Content-Type": "text/plain", "User-Agent": _ua()},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if isinstance(data, dict) and data.get("items"):
        # multiple-choice response from /web — not auto-resolvable
        raise ValueError("page offers multiple items; import it via the browser connector")
    if not isinstance(data, list):
        raise ValueError("unexpected translation-server response")
    return data


# ---------------------------------------------------------------------------
# saving into Zotero
# ---------------------------------------------------------------------------

def save_items_to_zotero(items: List[Dict[str, Any]], connector_url: str,
                         timeout: int = 30,
                         session_id: Optional[str] = None) -> Tuple[bool, str]:
    if not items:
        return False, "nothing to save"
    payload = json.dumps({
        "items": items,
        "sessionID": session_id or uuid.uuid4().hex,
        "uri": "https://zotvault.local/import",
    }).encode("utf-8")
    req = urllib.request.Request(
        connector_url.rstrip("/") + "/connector/saveItems",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": _ua()},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 201):
                return True, "saved"
            return False, "connector answered HTTP {}".format(resp.status)
    except urllib.error.HTTPError as exc:
        return False, "connector HTTP {}: {}".format(exc.code, exc.read()[:200])
    except Exception as exc:
        return False, "Zotero unreachable ({}) — is the desktop app running?".format(exc)


def _strip_ver(arxiv_id: str) -> str:
    """2506.07043v3 -> 2506.07043 (old-style ids like solv-int/9901001 keep their 'v')."""
    return re.sub(r"v\d+$", "", arxiv_id.lower())


def _zotero_identifier_maps(cfg: Config) -> Tuple[Dict[str, str], Dict[str, str]]:
    """lowercase DOI -> item key, arXiv id -> item key, read from a snapshot of
    Zotero's own database.

    Covers EVERY regular item type, not just the ones the pipeline makes notes
    for: "is this paper already in Zotero?" must also see a `webpage` saved from
    an arXiv abstract page by the browser connector. Fail-open: an unreadable DB
    just means the state.db check is the only guard.
    """
    from zotvault.pdf_resolver import find_arxiv_id
    from zotvault.zotero_reader import ZoteroReader

    doi_map: Dict[str, str] = {}
    arxiv_map: Dict[str, str] = {}
    reader = ZoteroReader(cfg.zotero_data_dir, cfg.connector_url)
    try:
        conn = reader.snapshot()
        try:
            types = [r[0] for r in conn.execute(
                "SELECT typeName FROM itemTypes "
                "WHERE typeName NOT IN ('attachment', 'note', 'annotation')")]
            for it in reader.fetch_items(conn, types):
                if it.doi:
                    doi_map[it.doi.lower()] = it.item_key
                ax = find_arxiv_id(it)
                if ax:
                    arxiv_map[_strip_ver(ax)] = it.item_key
        finally:
            conn.close()
    except Exception:
        pass
    finally:
        reader.cleanup()
    return doi_map, arxiv_map


# The connector key the saved item carries inside its save session. The PDF
# upload names it as `parentItemID`; without an explicit id every item in a
# session shares the key `undefined` and a batch would attach to the wrong one.
_PARENT_ID = "zv1"

_NO_PDF_HINT = "use Zotero's Find Available PDF"


def _post(url: str, data: bytes, headers: Dict[str, str], timeout: int) -> Tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def attach_pdf_to_saved_item(connector_url: str, session_id: str, pdf: bytes,
                             source_url: str, parent_id: str = _PARENT_ID,
                             timeout: int = 90) -> Tuple[bool, str]:
    """Upload `pdf` as a child of an item saved earlier in the SAME session.

    This is what Zotero's own browser connector does. `saveItems` alone cannot
    attach files (the local connector runs it in ATTACHMENT_MODE_IGNORE); the
    separate /connector/saveAttachment call can. Only HTTP 201 means success --
    200 is Zotero's "library files are not editable" answer.
    """
    # json.dumps keeps its default ensure_ascii: the metadata travels in an
    # HTTP header, which must stay ASCII (titles like WSe₂ would break it).
    meta = json.dumps({"sessionID": session_id, "parentItemID": parent_id,
                       "title": "Full Text PDF", "url": source_url})
    try:
        status, body = _post(connector_url.rstrip("/") + "/connector/saveAttachment", pdf,
                             {"Content-Type": "application/pdf", "X-Metadata": meta,
                              "User-Agent": _ua()}, timeout)
    except Exception as exc:
        return False, "attachment upload failed ({})".format(exc)
    if status == 201:
        return True, "attached"
    return False, "Zotero answered HTTP {} ({})".format(status, body[:120].decode("utf-8", "replace"))


def attach_via_zotero_resolver(connector_url: str, session_id: str,
                               parent_id: str = _PARENT_ID,
                               timeout: int = 90) -> Tuple[bool, str]:
    """Ask Zotero itself to find an OA PDF (same engine as Find Available PDF)."""
    payload = json.dumps({"sessionID": session_id, "itemID": parent_id}).encode("utf-8")
    try:
        status, body = _post(connector_url.rstrip("/") + "/connector/saveAttachmentFromResolver",
                             payload, {"Content-Type": "application/json",
                                       "User-Agent": _ua()}, timeout)
    except Exception as exc:
        return False, str(exc)
    return status == 201, body[:120].decode("utf-8", "replace")


def fetch_pdf_for_add(kind: str, norm: str, item: Dict[str, Any], cfg: Config,
                      state: State) -> Tuple[Optional[bytes], str, str]:
    """Get the PDF bytes BEFORE saving (a connector save session expires, so
    nothing slow may sit between saveItems and the upload).

    Returns (bytes | None, source_url, note). Same etiquette as the daemon:
    sequential, delayed, counted against the daily download budget.
    """
    import time

    from zotvault import pdf_resolver

    if state.downloads_today() >= cfg.daily_download_limit:
        return None, "", "daily download limit reached"
    candidates: List[str] = []
    arxiv_id = norm if kind == "arxiv" else None
    if arxiv_id is None and kind == "doi":
        m = re.match(r"^10\.48550/arxiv\.(.+)$", norm, re.I)
        arxiv_id = m.group(1) if m else None
    if arxiv_id:
        candidates.append("https://arxiv.org/pdf/" + arxiv_id)
    doi = item.get("DOI") or (norm if kind == "doi" else "")
    candidates.extend(pdf_resolver.unpaywall_pdf_urls(
        doi, cfg.unpaywall_email, cfg.download_timeout_sec))
    for url in candidates[:5]:
        data = pdf_resolver.fetch_pdf_bytes(url, cfg)
        if data:
            state.record_download()
            return data, url, ""
        time.sleep(max(0.0, cfg.request_delay_sec))
    return None, "", "no open-access PDF found" if candidates else "no PDF source known"


def add_identifiers(identifiers: List[str], cfg: Config, state: State,
                    dry_run: bool = False,
                    force: bool = False,
                    attach_pdf: bool = True) -> List[Dict[str, Any]]:
    """Resolve each identifier and save it to Zotero. Returns per-identifier results."""
    results: List[Dict[str, Any]] = []
    doi_map = state.doi_map()
    arxiv_map = state.arxiv_map()
    # state.db only knows what the daemon has already seen; Zotero's own DB is
    # the source of truth (an item added in the last hours, or while the daemon
    # was off, is invisible to state.db and would be saved twice).
    zdoi, zarxiv = _zotero_identifier_maps(cfg)
    for k, v in zdoi.items():
        doi_map.setdefault(k, v)
    for k, v in zarxiv.items():
        arxiv_map.setdefault(k, v)
    ignored = {} if force else state.ignored_identifiers()
    for raw in identifiers:
        kind, norm = classify_identifier(raw)
        res: Dict[str, Any] = {"identifier": raw, "kind": kind, "normalized": norm}
        try:
            if kind == "unknown":
                res.update(status="error", message="not a DOI / arXiv id / URL")
                results.append(res)
                continue
            # duplicate check
            dup = None
            if kind == "doi":
                dup = doi_map.get(norm.lower())
                m_ax = re.match(r"^10\.48550/arxiv\.(.+)$", norm, re.I)
                if not dup and m_ax:
                    dup = arxiv_map.get(_strip_ver(m_ax.group(1)))
            elif kind == "arxiv":
                dup = arxiv_map.get(_strip_ver(norm)) \
                    or doi_map.get("10.48550/arxiv." + _strip_ver(norm))
            if dup:
                res.update(status="duplicate", citekey=dup,
                           message="already in library as {}".format(dup))
                results.append(res)
                continue
            ign = ignored.get(norm.lower()) or ignored.get(norm.lower().split("v")[0])
            if ign:
                res.update(status="ignored", citekey=ign,
                           message="on your ignore list (dismissed as {}) — "
                                   "unignore in the dashboard, or CLI: add --force".format(ign))
                results.append(res)
                continue
            # resolve
            if cfg.translation_server_url:
                items = ts_lookup(norm, cfg.translation_server_url, kind)
                item = items[0]
            elif kind == "doi":
                item = resolve_doi(norm)
            elif kind == "arxiv":
                item = resolve_arxiv(norm)
                item.pop("_pdf_url", None)  # internal-only; not a Zotero field
            else:  # url without translation-server
                res.update(status="error",
                           message="URL import needs translation-server "
                                   "([zotero] translation_server_url) — or pass the DOI instead")
                results.append(res)
                continue
            res["title"] = item.get("title", "")
            if not res["title"]:
                res.update(status="error", message="resolver returned no title")
                results.append(res)
                continue
            # PDFs never travel inside the saveItems payload: the local connector
            # runs that call in ATTACHMENT_MODE_IGNORE (confirmed v0.9.8 in
            # Zotero's debug log), so any `attachments` entry is discarded.
            # The browser connector gets its PDF in by a second call in the
            # same save session (/connector/saveAttachment); so do we.
            if dry_run:
                res.update(status="resolved", message="dry-run: not saved")
                results.append(res)
                continue
            want_pdf = attach_pdf and cfg.resolve_pdfs
            pdf, pdf_src, pdf_note = (None, "", "")
            if want_pdf:
                # fetch first: nothing slow may sit between save and upload
                pdf, pdf_src, pdf_note = fetch_pdf_for_add(kind, norm, item, cfg, state)
            item["id"] = _PARENT_ID
            sid = uuid.uuid4().hex
            ok, msg = save_items_to_zotero([item], cfg.connector_url, session_id=sid)
            if not ok:
                res.update(status="error", message=msg)
                results.append(res)
                continue
            state.trace("zotero_added", norm, res["title"][:120])
            res.update(status="added", pdf="skipped", message="saved to Zotero")
            if want_pdf:
                if pdf:
                    up_ok, up_msg = attach_pdf_to_saved_item(cfg.connector_url, sid, pdf, pdf_src)
                    if up_ok:
                        res.update(pdf="attached", message="saved to Zotero, PDF attached")
                        state.trace("zotero_pdf_attached", norm, "{} ({} bytes)".format(pdf_src, len(pdf)))
                    else:
                        res.update(pdf="failed", message="saved to Zotero; PDF upload failed ({}) -- {}".format(
                            up_msg, _NO_PDF_HINT))
                        state.trace("zotero_pdf_failed", norm, up_msg[:200])
                else:
                    rs_ok, _ = attach_via_zotero_resolver(cfg.connector_url, sid)
                    if rs_ok:
                        res.update(pdf="attached", message="saved to Zotero, PDF attached by Zotero's own resolver")
                        state.trace("zotero_pdf_attached", norm, "zotero resolver")
                    else:
                        res.update(pdf="none", message="saved to Zotero; no PDF attached ({}) -- {}".format(
                            pdf_note, _NO_PDF_HINT))
        except Exception as exc:
            res.update(status="error", message=str(exc)[:300])
        results.append(res)
    return results
