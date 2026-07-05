"""Local state + audit trace, stored in a single SQLite DB (~/.paperflow/state.db).

Every automatic action is recorded in `trace` so behaviour is reconstructable
(auditable-not-opaque, inherited from the Polaris design philosophy).
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS items (
    item_id       INTEGER PRIMARY KEY,
    item_key      TEXT UNIQUE,
    citekey       TEXT,
    title         TEXT,
    note_status   TEXT DEFAULT 'pending',   -- pending|created|existing|dry-run|disabled|error
    note_path     TEXT,
    pdf_status    TEXT DEFAULT 'pending',   -- pending|zotero|downloaded|cached|missing|deferred|disabled|error
    pdf_path      TEXT,
    analysis_done INTEGER DEFAULT 0,
    analysis_path TEXT,
    deleted       INTEGER DEFAULT 0,
    retries       INTEGER DEFAULT 0,
    last_error    TEXT,
    first_seen    TEXT,
    last_update   TEXT
);
CREATE TABLE IF NOT EXISTS trace (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS downloads (
    day   TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return _dt.date.today().isoformat()


class State:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- kv ----------------------------------------------------------------
    def kv_get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- items ---------------------------------------------------------------
    def known_item_ids(self) -> Set[int]:
        return {r["item_id"] for r in self.conn.execute("SELECT item_id FROM items")}

    def retry_item_ids(self) -> Set[int]:
        rows = self.conn.execute(
            "SELECT item_id FROM items WHERE deleted=0 AND "
            "(citekey IS NULL OR note_status IN ('pending','error','dry-run','disabled') "
            " OR pdf_status IN ('pending','deferred','error','disabled'))"
        )
        return {r["item_id"] for r in rows}

    def upsert_item(self, item_id: int, **fields: Any) -> None:
        existing = self.conn.execute(
            "SELECT item_id FROM items WHERE item_id=?", (item_id,)
        ).fetchone()
        fields["last_update"] = _now()
        if existing is None:
            fields.setdefault("first_seen", _now())
            cols = ["item_id"] + list(fields.keys())
            sql = "INSERT INTO items({}) VALUES({})".format(
                ",".join(cols), ",".join("?" * len(cols))
            )
            self.conn.execute(sql, [item_id] + list(fields.values()))
        else:
            sets = ",".join("{}=?".format(k) for k in fields)
            self.conn.execute(
                "UPDATE items SET {} WHERE item_id=?".format(sets),
                list(fields.values()) + [item_id],
            )
        self.conn.commit()

    def get_item(self, item_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM items WHERE item_id=?", (item_id,)
        ).fetchone()

    def all_items(self, include_deleted: bool = False) -> List[sqlite3.Row]:
        sql = "SELECT * FROM items"
        if not include_deleted:
            sql += " WHERE deleted=0"
        return list(self.conn.execute(sql + " ORDER BY item_id"))

    def items_awaiting_analysis(self) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM items WHERE deleted=0 AND analysis_done=0 "
                "AND citekey IS NOT NULL ORDER BY item_id"
            )
        )

    def mark_deleted(self, item_id: int) -> None:
        self.conn.execute(
            "UPDATE items SET deleted=1, last_update=? WHERE item_id=?",
            (_now(), item_id),
        )
        self.conn.commit()

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        out["items"] = self.conn.execute(
            "SELECT COUNT(*) c FROM items WHERE deleted=0"
        ).fetchone()["c"]
        out["analyzed"] = self.conn.execute(
            "SELECT COUNT(*) c FROM items WHERE deleted=0 AND analysis_done=1"
        ).fetchone()["c"]
        for status in ("created", "existing", "pending", "error"):
            out["note_" + status] = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE deleted=0 AND note_status=?",
                (status,),
            ).fetchone()["c"]
        for status in ("zotero", "downloaded", "cached", "missing", "deferred"):
            out["pdf_" + status] = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE deleted=0 AND pdf_status=?",
                (status,),
            ).fetchone()["c"]
        return out

    # -- trace ---------------------------------------------------------------
    def trace(self, action: str, target: str = "", detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO trace(ts,action,target,detail) VALUES(?,?,?,?)",
            (_now(), action, target, detail),
        )
        self.conn.commit()

    def recent_trace(self, limit: int = 30) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM trace ORDER BY id DESC LIMIT ?", (limit,)
            )
        )

    # -- download budget -------------------------------------------------------
    def downloads_today(self) -> int:
        row = self.conn.execute(
            "SELECT count FROM downloads WHERE day=?", (_today(),)
        ).fetchone()
        return row["count"] if row else 0

    def record_download(self) -> None:
        self.conn.execute(
            "INSERT INTO downloads(day,count) VALUES(?,1) "
            "ON CONFLICT(day) DO UPDATE SET count=count+1",
            (_today(),),
        )
        self.conn.commit()
