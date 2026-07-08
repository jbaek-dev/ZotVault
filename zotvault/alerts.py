"""arXiv keyword alerts -> review inbox.

Daily (daemon) or on demand (`zotvault alerts --fetch`): query arXiv for each
configured keyword, keep entries newer than the lookback window that are not
already in the library or inbox. NOTHING is added to Zotero automatically —
approval happens in the dashboard or CLI (propose, don't execute).
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Dict

from zotvault import __version__
from zotvault.config import Config
from zotvault.state import State
from zotvault.zotero_writer import parse_arxiv_atom

log = logging.getLogger("zotvault.alerts")

_API = "http://export.arxiv.org/api/query?search_query={q}&sortBy=submittedDate&sortOrder=descending&max_results={n}"


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ZotVault/{} (alerts)".format(__version__)})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def fetch(cfg: Config, state: State) -> int:
    """Fetch new alert candidates. Returns the number added to the inbox."""
    if not cfg.alerts_keywords:
        return 0
    seen = state.alert_seen_ids()
    in_library = state.arxiv_map()
    cutoff = (_dt.datetime.now(_dt.timezone.utc)
              - _dt.timedelta(hours=cfg.alerts_lookback_hours)).date().isoformat()
    added = 0
    cats = cfg.alerts_categories or [""]
    for kw in cfg.alerts_keywords:
        for cat in cats:
            q = 'all:"{}"'.format(kw)
            if cat:
                q = "cat:{} AND {}".format(cat, q)
            url = _API.format(q=urllib.parse.quote(q), n=cfg.alerts_max_per_fetch)
            try:
                entries = parse_arxiv_atom(_get(url))
            except Exception as exc:
                log.warning("alert query failed (%s @ %s): %s", kw, cat or "any", exc)
                continue
            added += store_entries(entries, kw, cat, cutoff, seen, in_library, state)
            time.sleep(3)  # arXiv API etiquette
    if added:
        state.trace("alerts_fetch", "", "{} new candidate(s)".format(added))
    return added


def store_entries(entries, keyword: str, category: str, cutoff: str,
                  seen: set, in_library: Dict[str, str], state: State) -> int:
    """Pure-ish storage step, split out for testability."""
    added = 0
    for e in entries:
        base_id = (e.get("arxiv_id") or "").split("v")[0]
        if not base_id or base_id in seen or base_id in in_library:
            continue
        published = e.get("published") or ""
        if published and published < cutoff:
            continue
        matched = keyword + (" @" + category if category else "")
        if state.alert_add(
            base_id,
            e.get("title", ""),
            ", ".join(e.get("authors", [])[:6]),
            (e.get("summary") or "")[:800],
            published,
            matched,
        ):
            seen.add(base_id)
            added += 1
    return added


def approve(alert_id: int, cfg: Config, state: State) -> Dict[str, Any]:
    from zotvault.zotero_writer import add_identifiers

    row = state.alert_get(alert_id)
    if row is None:
        return {"ok": False, "message": "alert #{} not found".format(alert_id)}
    results = add_identifiers(["arXiv:" + row["arxiv_id"]], cfg, state)
    r = results[0]
    if r["status"] in ("added", "duplicate"):
        state.alert_set_status(alert_id, "added")
        return {"ok": True, "message": r.get("message", "saved"), "title": row["title"]}
    state.alert_set_status(alert_id, "error")
    return {"ok": False, "message": r.get("message", "failed")}
