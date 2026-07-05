"""Read-only access to the Zotero library.

Strategy (inherited from the proven vault scripts):
- Copy zotero.sqlite (+ -wal / -journal siblings) to a temp dir, open read-only.
  Zotero's live DB is locked while the app runs; the copy is always safe.
- Citekeys come from Better BibTeX's JSON-RPC endpoint on the local Zotero
  HTTP server (item.citationkey). Fallback: "Citation Key: X" in the Extra
  field. PaperFlow NEVER invents citekeys silently — items without one are
  retried on later cycles and surfaced via `paperflow status`.

PaperFlow never writes to zotero.sqlite or Zotero's storage/ directory.
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

    # -- snapshot ---------------------------------------------------------------
    def snapshot(self) -> sqlite3.Connection:
        src = self.data_dir / "zotero.sqlite"
        if not src.exists():
            raise FileNotFoundError("zotero.sqlite not found in {}".format(self.data_dir))
        self._tmpdir = tempfile.mkdtemp(prefix="paperflow_zt_")
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
