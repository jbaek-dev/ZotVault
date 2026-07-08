"""Read-only access to the Zotero library.

Strategy (inherited from the proven vault scripts):
- Copy zotero.sqlite (+ -wal / -journal siblings) to a temp dir, open read-only.
  Zotero's live DB is locked while the app runs; the copy is always safe.
- Citekeys come from Better BibTeX's JSON-RPC endpoint on the local Zotero
  HTTP server (item.citationkey). Fallback: "Citation Key: X" in the Extra
  field. ZotVault NEVER invents citekeys silently — items without one are
  retried on later cycles and surfaced via `zotvault status`.

ZotVault never writes to zotero.sqlite or Zotero's storage/ directory.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_EXTRA_CITEKEY_RE = re.compile(r"^\s*Citation Key:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


@dataclass
class Annotation:
    key: str                 # annotation item key
    attachment_key: str      # parent attachment item key (for deep links)
    type: int                # 1 hl, 2 note, 3 image, 4 ink, 5 underline, 6 text
    text: str
    comment: str
    color: str
    page_label: str
    sort_index: str
    date_modified: str


@dataclass
class RawItem:
    item_id: int
    item_key: str
    type_name: str
    date_added: str
    fields: Dict[str, str] = field(default_factory=dict)
    creators: List[Tuple[str, str]] = field(default_factory=list)
    pdf_path: Optional[str] = None
    citekey: Optional[str] = None

    # -- convenience accessors ------------------------------------------------
    @property
    def title(self) -> str:
        return self.fields.get("title", "")

    @property
    def doi(self) -> str:
        return self.fields.get("DOI", "")

    @property
    def url(self) -> str:
        return self.fields.get("url", "")

    @property
    def journal(self) -> str:
        return self.fields.get("publicationTitle", "") or self.fields.get(
            "proceedingsTitle", ""
        ) or self.fields.get("repository", "")

    @property
    def abstract(self) -> str:
        return self.fields.get("abstractNote", "")

    @property
    def extra(self) -> str:
        return self.fields.get("extra", "")

    @property
    def year(self) -> str:
        m = _YEAR_RE.search(self.fields.get("date", ""))
        return m.group(1) if m else ""

    @property
    def authors(self) -> str:
        parts = []
        for first, last in self.creators:
            name = " ".join(x for x in (first, last) if x)
            if name:
                parts.append(name)
        return ", ".join(parts)

    @property
    def date_added_day(self) -> str:
        return (self.date_added or "")[:10]

    def extra_citekey(self) -> Optional[str]:
        m = _EXTRA_CITEKEY_RE.search(self.extra)
        return m.group(1) if m else None


class ZoteroReader:
    def __init__(self, data_dir: Path, connector_url: str = "http://127.0.0.1:23119"):
        self.data_dir = Path(data_dir)
        self.connector_url = connector_url.rstrip("/")
        self._tmpdir: Optional[str] = None

    def db_signature(self) -> str:
        """Cheap change token from the Zotero DB files' size+mtime (no copy).
        Empty string if the DB is absent."""
        parts = []
        for suffix in ("", "-wal", "-journal"):
            s = self.data_dir / ("zotero.sqlite" + suffix)
            try:
                st = s.stat()
                parts.append("{}:{}:{}".format(suffix or "db", st.st_size, int(st.st_mtime)))
            except OSError:
                continue
        return "|".join(parts)

    # -- snapshot ---------------------------------------------------------------
    def snapshot(self) -> sqlite3.Connection:
        src = self.data_dir / "zotero.sqlite"
        if not src.exists():
            raise FileNotFoundError("zotero.sqlite not found in {}".format(self.data_dir))
        self._tmpdir = tempfile.mkdtemp(prefix="zotvault_zt_")
        for suffix in ("", "-wal", "-journal"):
            s = self.data_dir / ("zotero.sqlite" + suffix)
            if s.exists():
                shutil.copy2(str(s), str(Path(self._tmpdir) / s.name))
        conn = sqlite3.connect(
            "file:{}?mode=ro".format(Path(self._tmpdir) / "zotero.sqlite"), uri=True
        )
        conn.row_factory = sqlite3.Row
        return conn

    def cleanup(self) -> None:
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    # -- queries ------------------------------------------------------------------
    def fetch_items(self, conn: sqlite3.Connection, item_types: List[str]) -> List[RawItem]:
        marks = ",".join("?" * len(item_types))
        rows = conn.execute(
            "SELECT i.itemID, i.key, i.dateAdded, it.typeName "
            "FROM items i JOIN itemTypes it ON i.itemTypeID = it.itemTypeID "
            "WHERE it.typeName IN ({}) "
            "AND i.itemID NOT IN (SELECT itemID FROM deletedItems) "
            "ORDER BY i.itemID".format(marks),
            item_types,
        ).fetchall()
        items = []
        for r in rows:
            item = RawItem(
                item_id=r["itemID"],
                item_key=r["key"],
                type_name=r["typeName"],
                date_added=r["dateAdded"] or "",
            )
            item.fields = self._fields(conn, item.item_id)
            item.creators = self._creators(conn, item.item_id)
            item.pdf_path = self._pdf_for(conn, item.item_id)
            items.append(item)
        return items

    def _fields(self, conn: sqlite3.Connection, item_id: int) -> Dict[str, str]:
        rows = conn.execute(
            "SELECT f.fieldName AS name, idv.value AS value "
            "FROM itemData d "
            "JOIN fields f ON d.fieldID = f.fieldID "
            "JOIN itemDataValues idv ON d.valueID = idv.valueID "
            "WHERE d.itemID = ?",
            (item_id,),
        )
        return {r["name"]: r["value"] for r in rows}

    def _creators(self, conn: sqlite3.Connection, item_id: int) -> List[Tuple[str, str]]:
        rows = conn.execute(
            "SELECT c.firstName AS f, c.lastName AS l "
            "FROM itemCreators ic JOIN creators c ON ic.creatorID = c.creatorID "
            "WHERE ic.itemID = ? ORDER BY ic.orderIndex",
            (item_id,),
        )
        return [((r["f"] or ""), (r["l"] or "")) for r in rows]

    def _pdf_for(self, conn: sqlite3.Connection, item_id: int) -> Optional[str]:
        rows = conn.execute(
            "SELECT ai.key AS akey, ia.path AS apath "
            "FROM itemAttachments ia JOIN items ai ON ia.itemID = ai.itemID "
            "WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf' "
            "AND ai.itemID NOT IN (SELECT itemID FROM deletedItems)",
            (item_id,),
        ).fetchall()
        for r in rows:
            apath = r["apath"] or ""
            if apath.startswith("storage:"):
                p = self.data_dir / "storage" / r["akey"] / apath[len("storage:"):]
                if p.exists():
                    return str(p)
            elif apath.startswith("/"):
                if Path(apath).exists():
                    return apath
        return None

    def annotations_map(self, conn: sqlite3.Connection) -> Dict[int, List[Annotation]]:
        """All PDF annotations, grouped by top-level paper itemID (one query)."""
        rows = conn.execute(
            "SELECT att.parentItemID AS paper_id, attItems.key AS att_key, "
            "annItems.key AS ann_key, ann.type, ann.text, ann.comment, ann.color, "
            "ann.pageLabel, ann.sortIndex, annItems.dateModified "
            "FROM itemAnnotations ann "
            "JOIN items annItems ON ann.itemID = annItems.itemID "
            "JOIN itemAttachments att ON ann.parentItemID = att.itemID "
            "JOIN items attItems ON att.itemID = attItems.itemID "
            "WHERE att.parentItemID IS NOT NULL "
            "AND annItems.itemID NOT IN (SELECT itemID FROM deletedItems) "
            "ORDER BY att.parentItemID, ann.sortIndex"
        ).fetchall()
        out: Dict[int, List[Annotation]] = {}
        for r in rows:
            out.setdefault(r["paper_id"], []).append(Annotation(
                key=r["ann_key"], attachment_key=r["att_key"], type=r["type"] or 0,
                text=r["text"] or "", comment=r["comment"] or "", color=r["color"] or "",
                page_label=r["pageLabel"] or "", sort_index=r["sortIndex"] or "",
                date_modified=r["dateModified"] or "",
            ))
        return out

    # -- Better BibTeX JSON-RPC -----------------------------------------------------
    def bbt_citekeys(self, item_keys: List[str], timeout: int = 10) -> Dict[str, str]:
        """Map Zotero item keys -> Better BibTeX citekeys. {} on any failure."""
        if not item_keys:
            return {}
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": "item.citationkey", "params": [item_keys], "id": 1}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.connector_url + "/better-bibtex/json-rpc",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            result = body.get("result") or {}
            return {k: v for k, v in result.items() if isinstance(v, str) and v}
        except Exception:
            return {}

    def zotero_alive(self, timeout: int = 3) -> bool:
        try:
            with urllib.request.urlopen(
                self.connector_url + "/connector/ping", timeout=timeout
            ) as resp:
                return resp.status == 200
        except Exception:
            return False
