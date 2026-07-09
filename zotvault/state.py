"""Local state + audit trace, stored in a single SQLite DB (~/.zotvault/state.db).

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
CREATE TABLE IF NOT EXISTS alerts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id  TEXT UNIQUE,
    title     TEXT,
    authors   TEXT,
    summary   TEXT,
    published TEXT,
    matched   TEXT,
    status    TEXT DEFAULT 'pending',  -- pending|approved|dismissed|added|error
    created   TEXT
);
CREATE TABLE IF NOT EXISTS embeddings (
    citekey   TEXT PRIMARY KEY,
    model     TEXT,
    dim       INTEGER,
    vec       BLOB,
    src_mtime REAL,
    updated   TEXT
);
CREATE TABLE IF NOT EXISTS citations (
    citing TEXT NOT NULL,
    cited  TEXT NOT NULL,
    PRIMARY KEY (citing, cited)
);
"""

# Guarded column additions for DBs created by older versions.
_MIGRATIONS = [
    "ALTER TABLE items ADD COLUMN ignored INTEGER DEFAULT 0",
    "ALTER TABLE items ADD COLUMN doi TEXT",
    "ALTER TABLE items ADD COLUMN arxiv_id TEXT",
    "ALTER TABLE items ADD COLUMN citation_count INTEGER",
    "ALTER TABLE items ADD COLUMN s2_id TEXT",
    "ALTER TABLE items ADD COLUMN enriched_at TEXT",
    "ALTER TABLE items ADD COLUMN annotations_hash TEXT",
    "ALTER TABLE alerts ADD COLUMN score REAL",
    "ALTER TABLE alerts ADD COLUMN reason TEXT",
]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return _dt.date.today().isoformat()


class State:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        for stmt in _MIGRATIONS:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        self.conn.execute("PRAGMA journal_mode=WAL")
        # the daemon writes while the web layer opens fresh connections per
        # request; wait instead of erroring "database is locked".
        self.conn.execute("PRAGMA busy_timeout=10000")
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
            "SELECT item_id FROM items WHERE deleted=0 AND ignored=0 AND "
            "(citekey IS NULL OR note_status IN ('pending','error','dry-run','disabled','blocked') "
            " OR pdf_status IN ('pending','deferred','error','disabled'))"
        )
        return {r["item_id"] for r in rows}

    def set_ignored(self, item_key: str, flag: bool) -> bool:
        cur = self.conn.execute(
            "UPDATE items SET ignored=? WHERE item_key=?", (1 if flag else 0, item_key))
        self.conn.commit()
        return cur.rowcount > 0

    def ignored_identifiers(self) -> Dict[str, str]:
        """lowercased doi/arxiv id -> citekey, for rows the user dismissed."""
        out: Dict[str, str] = {}
        for r in self.conn.execute(
                "SELECT doi, arxiv_id, citekey, item_key FROM items WHERE ignored=1"):
            ck = r["citekey"] or r["item_key"]
            if r["doi"]:
                out[r["doi"].lower()] = ck
            if r["arxiv_id"]:
                out[r["arxiv_id"].lower()] = ck
        return out

    def attention_rows(self) -> Dict[str, List[sqlite3.Row]]:
        """Rows the user may want to act on (file existence checked by caller)."""
        missing = self.conn.execute(
            "SELECT * FROM items WHERE deleted=0 AND ignored=0 AND note_status='missing' "
            "ORDER BY citekey").fetchall()
        vault_only = self.conn.execute(
            "SELECT * FROM items WHERE deleted=1 AND ignored=0 AND note_path IS NOT NULL "
            "ORDER BY citekey").fetchall()
        ignored = self.conn.execute(
            "SELECT * FROM items WHERE ignored=1 ORDER BY citekey").fetchall()
        return {"missing": missing, "vault_only": vault_only, "ignored": ignored}

    def item_by_key(self, item_key: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM items WHERE item_key=?", (item_key,)).fetchone()

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
            "SELECT COUNT(*) c FROM items WHERE deleted=0 AND ignored=0"
        ).fetchone()["c"]
        out["analyzed"] = self.conn.execute(
            "SELECT COUNT(*) c FROM items WHERE deleted=0 AND ignored=0 AND analysis_done=1"
        ).fetchone()["c"]
        for status in ("created", "existing", "pending", "error"):
            out["note_" + status] = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE deleted=0 AND ignored=0 AND note_status=?",
                (status,),
            ).fetchone()["c"]
        for status in ("zotero", "downloaded", "cached", "missing", "deferred"):
            out["pdf_" + status] = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE deleted=0 AND ignored=0 AND pdf_status=?",
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

    # -- identifier maps (duplicate detection, enrichment) -----------------------
    def doi_map(self) -> Dict[str, str]:
        """lowercased DOI -> citekey (or item_key when citekey missing)."""
        out: Dict[str, str] = {}
        for r in self.conn.execute(
            "SELECT doi, citekey, item_key FROM items WHERE deleted=0 AND doi IS NOT NULL AND doi != ''"
        ):
            out[r["doi"].lower()] = r["citekey"] or r["item_key"]
        return out

    def arxiv_map(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for r in self.conn.execute(
            "SELECT arxiv_id, citekey, item_key FROM items "
            "WHERE deleted=0 AND arxiv_id IS NOT NULL AND arxiv_id != ''"
        ):
            out[r["arxiv_id"].lower().split("v")[0]] = r["citekey"] or r["item_key"]
        return out

    def items_for_enrich(self, limit: int) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM items WHERE deleted=0 AND citekey IS NOT NULL "
                "AND ((doi IS NOT NULL AND doi != '') OR (arxiv_id IS NOT NULL AND arxiv_id != '')) "
                "AND enriched_at IS NULL ORDER BY item_id LIMIT ?",
                (limit,),
            )
        )

    # -- alerts ------------------------------------------------------------------
    def alert_add(self, arxiv_id: str, title: str, authors: str, summary: str,
                  published: str, matched: str) -> bool:
        """Insert if unseen. Returns True when newly added."""
        try:
            self.conn.execute(
                "INSERT INTO alerts(arxiv_id,title,authors,summary,published,matched,created) "
                "VALUES(?,?,?,?,?,?,?)",
                (arxiv_id, title, authors, summary, published, matched, _now()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def alerts_list(self, status: Optional[str] = "pending", limit: int = 100) -> List[sqlite3.Row]:
        if status:
            return list(self.conn.execute(
                "SELECT * FROM alerts WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)))
        return list(self.conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)))

    def alert_get(self, alert_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()

    def alert_set_score(self, alert_id: int, score: float, reason: str) -> None:
        self.conn.execute("UPDATE alerts SET score=?, reason=? WHERE id=?",
                          (score, reason, alert_id))
        self.conn.commit()

    def alert_set_status(self, alert_id: int, status: str) -> None:
        self.conn.execute("UPDATE alerts SET status=? WHERE id=?", (status, alert_id))
        self.conn.commit()

    def alert_seen_ids(self) -> Set[str]:
        return {r["arxiv_id"] for r in self.conn.execute("SELECT arxiv_id FROM alerts")}

    # -- embeddings ---------------------------------------------------------------
    def emb_get(self, citekey: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM embeddings WHERE citekey=?", (citekey,)).fetchone()

    def emb_set(self, citekey: str, model: str, dim: int, vec: bytes, src_mtime: float) -> None:
        self.conn.execute(
            "INSERT INTO embeddings(citekey,model,dim,vec,src_mtime,updated) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(citekey) DO UPDATE SET model=excluded.model, dim=excluded.dim, "
            "vec=excluded.vec, src_mtime=excluded.src_mtime, updated=excluded.updated",
            (citekey, model, dim, vec, src_mtime, _now()),
        )
        self.conn.commit()

    def emb_all(self, model: str) -> List[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM embeddings WHERE model=?", (model,)))

    # -- citation edges (in-library, by citekey) -----------------------------------
    def cite_replace(self, citing: str, cited_list: List[str]) -> None:
        self.conn.execute("DELETE FROM citations WHERE citing=?", (citing,))
        self.conn.executemany(
            "INSERT OR IGNORE INTO citations(citing,cited) VALUES(?,?)",
            [(citing, c) for c in cited_list],
        )
        self.conn.commit()

    def cite_edges(self) -> List[sqlite3.Row]:
        return list(self.conn.execute("SELECT citing, cited FROM citations ORDER BY citing, cited"))

    # -- proxy download budget (separate, stricter) ----------------------------------
    def proxy_downloads_today(self) -> int:
        return int(self.kv_get("proxy_dl_" + _today(), "0") or "0")

    def record_proxy_download(self) -> None:
        key = "proxy_dl_" + _today()
        self.kv_set(key, str(int(self.kv_get(key, "0") or "0") + 1))

    # -- analysis budget (v0.6 engine) ----------------------------------------
    def analyses_today(self) -> int:
        return int(self.kv_get("analysis_dl_" + _today(), "0") or "0")

    def record_analysis(self) -> None:
        key = "analysis_dl_" + _today()
        self.kv_set(key, str(int(self.kv_get(key, "0") or "0") + 1))

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
