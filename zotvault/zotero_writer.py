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
            "title": " ".join((e.findtext(_ATOM + "title") or "").split()),
            "summary": " ".join((e.findtext(_ATOM + "summary") or "").split()),
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
        "http://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id),
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
                         timeout: int = 30) -> Tuple[bool, str]:
    if not items:
        return False, "nothing to save"
    payload = json.dumps({
        "items": items,
        "sessionID": uuid.uuid4().hex,
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


def _oa_pdf_url(doi: str, cfg: Config) -> str:
    """Best OA PDF url for a DOI (one quick Unpaywall lookup), '' when none.

    Used to put an `attachments` entry into the saveItems payload so that
    ZOTERO downloads the PDF itself into its own storage — exactly what the
    browser connector does. ZotVault still never writes storage/; licensed
    (proxy) PDFs are not attempted here and stay on the daemon's OA→proxy
    fallback path into ~/.zotvault/pdfs/.
    """
    try:
        from zotvault.pdf_resolver import unpaywall_pdf_urls
        urls = unpaywall_pdf_urls(doi, cfg.unpaywall_email, timeout=15)
        return urls[0] if urls else ""
    except Exception:
        return ""  # advisory only — the daemon fallback still runs


def add_identifiers(identifiers: List[str], cfg: Config, state: State,
                    attach_pdf: bool = True, dry_run: bool = False,
                    force: bool = False) -> List[Dict[str, Any]]:
    """Resolve each identifier and save it to Zotero. Returns per-identifier results."""
    results: List[Dict[str, Any]] = []
    doi_map = state.doi_map()
    arxiv_map = state.arxiv_map()
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
            elif kind == "arxiv":
                dup = arxiv_map.get(norm.lower().split("v")[0])
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
            pdf_url = ""
            if cfg.translation_server_url:
                items = ts_lookup(norm, cfg.translation_server_url, kind)
                item = items[0]
            elif kind == "doi":
                item = resolve_doi(norm)
                if attach_pdf and cfg.unpaywall_email:
                    pdf_url = _oa_pdf_url(norm, cfg)
            elif kind == "arxiv":
                item = resolve_arxiv(norm)
                pdf_url = item.pop("_pdf_url", "")
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
            if attach_pdf and pdf_url and "attachments" not in item:
                item["attachments"] = [{
                    "title": "Full Text PDF (OA)", "url": pdf_url,
                    "mimeType": "application/pdf",
                }]
                res["pdf_attached"] = True
            if dry_run:
                res.update(status="resolved", message="dry-run: not saved")
                results.append(res)
                continue
            ok, msg = save_items_to_zotero([item], cfg.connector_url)
            if ok:
                note = ("saved to Zotero (Zotero is downloading the OA PDF)"
                        if res.get("pdf_attached") else "saved to Zotero")
                res.update(status="added", message=note)
                state.trace("zotero_added", norm, res["title"][:120])
            else:
                res.update(status="error", message=msg)
        except Exception as exc:
            res.update(status="error", message=str(exc)[:300])
        results.append(res)
    return results
