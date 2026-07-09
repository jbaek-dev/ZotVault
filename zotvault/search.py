"""Paper search across arXiv, Semantic Scholar and Crossref (no API keys needed;
an optional Semantic Scholar key raises rate limits).

Results are normalized to SearchResult and annotated with in_library when the
DOI / arXiv id already exists in the local state — so the dashboard can show
"already in Zotero" instead of offering a duplicate add.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from zotvault import __version__
from zotvault.config import Config
from zotvault.state import State
from zotvault.zotero_writer import parse_arxiv_atom, strip_markup


@dataclass
class SearchResult:
    source: str
    title: str
    authors: str = ""
    year: str = ""
    venue: str = ""
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    pdf_url: str = ""
    citations: Optional[int] = None
    in_library: Optional[str] = None  # citekey when already present

    @property
    def best_identifier(self) -> str:
        return self.doi or ("arXiv:" + self.arxiv_id if self.arxiv_id else "")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["best_identifier"] = self.best_identifier
        return d


def _get(url: str, timeout: int = 20, headers: Optional[Dict[str, str]] = None) -> bytes:
    h = {"User-Agent": "ZotVault/{} (local research tool)".format(__version__)}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

def search_arxiv(query: str, max_results: int = 20, timeout: int = 20) -> List[SearchResult]:
    # AND-join individual terms (an exact-phrase query over 3+ words rarely matches)
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    q = urllib.parse.quote(" AND ".join('all:"{}"'.format(t.replace('"', "")) for t in terms))
    xml_text = _get(
        "http://export.arxiv.org/api/query?search_query={}&max_results={}&sortBy=relevance".format(
            q, max_results),
        timeout,
    ).decode("utf-8")
    out = []
    for e in parse_arxiv_atom(xml_text):
        out.append(SearchResult(
            source="arxiv",
            title=e["title"],
            authors=", ".join(e["authors"][:6]) + (" et al." if len(e["authors"]) > 6 else ""),
            year=e["published"][:4],
            venue="arXiv:" + e["arxiv_id"],
            abstract=e["summary"][:600],
            doi=e["doi"],
            arxiv_id=e["arxiv_id"].split("v")[0],
            pdf_url=e["pdf_url"],
        ))
    return out


def parse_s2(data: Dict[str, Any]) -> List[SearchResult]:
    out = []
    for p in data.get("data") or []:
        ext = p.get("externalIds") or {}
        authors = [a.get("name", "") for a in (p.get("authors") or [])]
        oa = p.get("openAccessPdf") or {}
        out.append(SearchResult(
            source="s2",
            title=p.get("title", "") or "",
            authors=", ".join(authors[:6]) + (" et al." if len(authors) > 6 else ""),
            year=str(p.get("year") or ""),
            venue=p.get("venue") or "",
            abstract=(p.get("abstract") or "")[:600],
            doi=(ext.get("DOI") or "").lower(),
            arxiv_id=(ext.get("ArXiv") or ""),
            pdf_url=oa.get("url") or "",
            citations=p.get("citationCount"),
        ))
    return out


def search_semantic_scholar(query: str, max_results: int = 20, api_key: str = "",
                            timeout: int = 20) -> List[SearchResult]:
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?query={}&limit={}"
           "&fields=title,abstract,year,venue,externalIds,citationCount,openAccessPdf,authors"
           ).format(urllib.parse.quote(query), max_results)
    headers = {"x-api-key": api_key} if api_key else None
    try:
        data = json.loads(_get(url, timeout, headers).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError(
                "Semantic Scholar rate limit (shared free tier) — wait ~1 min and retry, "
                "use source=arxiv/crossref, or set [search] semantic_scholar_api_key"
            ) from None
        raise
    return parse_s2(data)


def search_crossref(query: str, max_results: int = 20, timeout: int = 20) -> List[SearchResult]:
    url = "https://api.crossref.org/works?query={}&rows={}".format(
        urllib.parse.quote(query), max_results)
    data = json.loads(_get(url, timeout).decode("utf-8"))
    out = []
    for m in (data.get("message") or {}).get("items") or []:
        titles = m.get("title") or []
        authors = []
        for a in (m.get("author") or [])[:6]:
            authors.append(" ".join(x for x in (a.get("given"), a.get("family")) if x))
        parts = (m.get("issued") or {}).get("date-parts") or [[None]]
        container = m.get("container-title") or []
        out.append(SearchResult(
            source="crossref",
            title=strip_markup(titles[0] if titles else ""),
            authors=", ".join(a for a in authors if a),
            year=str(parts[0][0] or "") if parts and parts[0] else "",
            venue=strip_markup(container[0] if container else ""),
            doi=(m.get("DOI") or "").lower(),
            citations=m.get("is-referenced-by-count"),
        ))
    return [r for r in out if r.title]


# ---------------------------------------------------------------------------
# direct identifier lookup (DOI / arXiv id typed into the search box)
# ---------------------------------------------------------------------------

def _item_to_result(item: dict, source: str) -> SearchResult:
    creators = item.get("creators") or []
    names = []
    for c in creators[:6]:
        n = " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x)
        if n:
            names.append(n)
    return SearchResult(
        source=source,
        title=item.get("title", ""),
        authors=", ".join(names) + (" et al." if len(creators) > 6 else ""),
        year=(item.get("date") or "")[:4],
        venue=item.get("publicationTitle") or item.get("repository", "") or "",
        abstract=(item.get("abstractNote") or "")[:600],
        doi=(item.get("DOI") or "").lower(),
    )


def lookup_identifier(query: str, timeout: int = 20) -> Optional[List[SearchResult]]:
    """If the query IS an identifier, resolve it directly.

    Returns None when the query is not an identifier (-> keyword search),
    [] when it is one but could not be resolved, [one result] on success.
    """
    from zotvault.zotero_writer import classify_identifier, resolve_arxiv, resolve_doi

    kind, norm = classify_identifier(query)
    if kind == "doi":
        try:
            item = resolve_doi(norm, timeout)
        except Exception:
            return []
        r = _item_to_result(item, "doi-lookup")
        r.doi = r.doi or norm.lower()
        return [r] if r.title else []
    if kind == "arxiv":
        try:
            item = resolve_arxiv(norm, timeout)
        except Exception:
            return []
        r = _item_to_result(item, "arxiv-lookup")
        r.arxiv_id = norm.lower().split("v")[0]
        r.venue = r.venue or "arXiv"
        r.pdf_url = item.get("_pdf_url", "")
        return [r] if r.title else []
    return None  # not an identifier (plain keywords or a URL)


def mark_in_library(results: List[SearchResult], state: State) -> None:
    dois = state.doi_map()
    arxivs = state.arxiv_map()
    for r in results:
        if r.doi and r.doi.lower() in dois:
            r.in_library = dois[r.doi.lower()]
        elif r.arxiv_id and r.arxiv_id.lower().split("v")[0] in arxivs:
            r.in_library = arxivs[r.arxiv_id.lower().split("v")[0]]


def search(query: str, source: str, cfg: Config, state: Optional[State] = None,
           max_results: Optional[int] = None) -> List[SearchResult]:
    # A DOI / arXiv id beats keyword search regardless of the selected source.
    hits = lookup_identifier(query)
    if hits is not None:
        if state is not None:
            mark_in_library(hits, state)
        return hits
    n = max_results or cfg.search_max_results
    if source in ("s2", "semanticscholar"):
        results = search_semantic_scholar(query, n, cfg.s2_api_key)
    elif source == "crossref":
        results = search_crossref(query, n)
    else:
        results = search_arxiv(query, n)
    if state is not None:
        mark_in_library(results, state)
    return results
