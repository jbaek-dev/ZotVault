"""The core loop: detect new Zotero items -> note -> PDF -> queue -> index.

Idempotent by construction:
- existing notes are never rewritten,
- PDFs already present (Zotero or cache) are never re-downloaded,
- index/log are only touched when something actually changed.
So the very first run over an already-populated library is a quiet backfill
that simply registers everything in local state.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from zotvault import analysis_queue, indexer, note_renderer, pdf_resolver
from zotvault.config import Config
from zotvault.i18n import t
from zotvault.state import State
from zotvault.zotero_reader import RawItem, ZoteroReader

log = logging.getLogger("zotvault.pipeline")


@dataclass
class RunSummary:
    scanned: int = 0
    new_items: int = 0
    notes_created: int = 0
    notes_existing: int = 0
    pdfs_downloaded: int = 0
    pdfs_missing: int = 0
    analyses_detected: int = 0
    citekey_pending: int = 0
    deleted: int = 0
    errors: int = 0
    created_citekeys: List[str] = field(default_factory=list)
    downloaded_citekeys: List[str] = field(default_factory=list)
    detected_citekeys: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.notes_created
            or self.pdfs_downloaded
            or self.analyses_detected
            or self.deleted
        )

    def line(self) -> str:
        if self.scanned == -1:
            return "scan skipped (Zotero DB unchanged); analyses+{}".format(self.analyses_detected)
        return (
            "scanned={} new={} notes+{} pdfs+{} analyses+{} pending_citekey={} "
            "deleted={} errors={}".format(
                self.scanned,
                self.new_items,
                self.notes_created,
                self.pdfs_downloaded,
                self.analyses_detected,
                self.citekey_pending,
                self.deleted,
                self.errors,
            )
        )


def _process_item(
    item: RawItem,
    citekey_map: Dict[str, str],
    cfg: Config,
    state: State,
    summary: RunSummary,
    is_new: bool,
) -> None:
    prev = state.get_item(item.item_id)
    # --- citekey -----------------------------------------------------------
    citekey = citekey_map.get(item.item_key) or item.extra_citekey()
    if not citekey and prev is not None and prev["citekey"]:
        citekey = prev["citekey"]
    if not citekey:
        retries = (prev["retries"] if prev is not None else 0) + 1
        # 'blocked' after a few tries makes the cause visible (status/dashboard)
        # instead of an invisible perpetual 'pending'.
        status = "blocked" if retries >= 3 else "pending"
        state.upsert_item(
            item.item_id,
            item_key=item.item_key,
            title=item.title,
            citekey=None,
            note_status=status,
            retries=retries,
        )
        if retries in (1, 3):
            state.trace(
                "citekey_blocked",
                item.item_key,
                "no citekey — ZotVault needs Better BibTeX (Zotero add-on) running; "
                "see README > Requirements",
            )
        summary.citekey_pending += 1
        return
    # citekeys become folder/file names — refuse anything filesystem-unsafe
    if not re.match(r"^[\w.\-]+$", citekey):
        state.upsert_item(
            item.item_id, item_key=item.item_key, title=item.title,
            note_status="error", last_error="unsafe citekey: " + citekey[:80],
        )
        state.trace("citekey_invalid", item.item_key, citekey[:80])
        summary.errors += 1
        return
    item.citekey = citekey

    # --- note ---------------------------------------------------------------
    note_status = prev["note_status"] if prev is not None else "pending"
    note_path: Optional[str] = prev["note_path"] if prev is not None else None
    if cfg.create_notes and cfg.papers_dir is not None:
        status, path = note_renderer.write_note(cfg.papers_dir, item, dry_run=cfg.dry_run, cfg=cfg)
        note_status, note_path = status, str(path)
        if status == "created":
            summary.notes_created += 1
            summary.created_citekeys.append(citekey)
            state.trace("note_created", citekey, str(path))
        elif status == "existing" and is_new:
            summary.notes_existing += 1
    elif cfg.papers_dir is None:
        note_status = "disabled"

    # --- pdf ------------------------------------------------------------------
    pdf_status, pdf_path = pdf_resolver.resolve(item, cfg, state)
    if pdf_status == "downloaded":
        summary.pdfs_downloaded += 1
        summary.downloaded_citekeys.append(citekey)
    elif pdf_status == "missing":
        summary.pdfs_missing += 1

    state.upsert_item(
        item.item_id,
        item_key=item.item_key,
        citekey=citekey,
        title=item.title,
        doi=(item.doi or "").lower() or None,
        arxiv_id=pdf_resolver.find_arxiv_id(item),
        note_status=note_status,
        note_path=note_path,
        pdf_status=pdf_status,
        pdf_path=pdf_path,
        retries=0,
        last_error=None,
    )
    if is_new:
        state.trace("item_registered", citekey, "itemKey={} pdf={}".format(item.item_key, pdf_status))


def _detect_analyses(cfg: Config, state: State, summary: RunSummary) -> None:
    if cfg.papers_dir is None:
        return
    for row in state.items_awaiting_analysis():
        hit = analysis_queue.analysis_file_for(cfg.papers_dir, row["citekey"])
        if hit is not None:
            state.upsert_item(row["item_id"], analysis_done=1, analysis_path=str(hit))
            state.trace("analysis_detected", row["citekey"], hit.name)
            summary.analyses_detected += 1
            summary.detected_citekeys.append(row["citekey"])


def _update_vault_records(cfg: Config, state: State, summary: RunSummary, backfill: bool) -> None:
    if cfg.papers_dir is None:
        return
    # index.md progress counters (vault-scan based: the vault is the truth)
    if cfg.update_index and cfg.index_path is not None:
        analyzed, total = analysis_queue.progress(cfg.papers_dir)
        if indexer.update_progress(cfg.index_path, analyzed, total, dry_run=cfg.dry_run):
            state.trace("index_updated", cfg.index_file, "{} / {}".format(analyzed, total))
    # log.md entry
    if cfg.append_log and cfg.log_path is not None and summary.changed and not cfg.dry_run:
        title = t("log.backfill_title") if backfill else t("log.sync_title")
        parts = []
        if summary.notes_created:
            parts.append(t("log.notes_created", n=summary.notes_created,
                           items=", ".join(summary.created_citekeys[:8])))
        if summary.pdfs_downloaded:
            parts.append(t("log.pdfs_fetched", n=summary.pdfs_downloaded,
                           items=", ".join(summary.downloaded_citekeys[:8])))
        if summary.analyses_detected:
            parts.append(t("log.analyses_detected", n=summary.analyses_detected,
                           items=", ".join(summary.detected_citekeys[:8])))
        if summary.deleted:
            parts.append(t("log.deleted_in_zotero", n=summary.deleted))
        files = t("log.files_field", papers_subdir=cfg.papers_subdir)
        indexer.append_log(cfg.log_path, title, "; ".join(parts) or summary.line(), files)
        state.trace("log_appended", cfg.log_file, summary.line())


def run_once(cfg: Config, state: State) -> RunSummary:
    summary = RunSummary()
    reader = ZoteroReader(cfg.zotero_data_dir, cfg.connector_url)

    # Cheap skip: if the Zotero DB hasn't changed since the last cycle and there
    # are no items still awaiting work, avoid the (potentially large) snapshot
    # copy + full re-scan entirely. Analysis-completion detection still runs.
    db_sig = reader.db_signature()
    if (db_sig and state.kv_get("zotero_db_sig") == db_sig
            and not state.retry_item_ids() and state.known_item_ids()):
        _detect_analyses(cfg, state, summary)
        _update_vault_records(cfg, state, summary, backfill=False)
        summary.scanned = -1  # sentinel: skipped a full scan
        return summary

    conn = reader.snapshot()
    try:
        items = reader.fetch_items(conn, cfg.item_types)
    finally:
        conn.close()
        reader.cleanup()

    summary.scanned = len(items)
    known = state.known_item_ids()
    backfill = len(known) == 0 and len(items) > 20

    # one-shot metadata backfill for state DBs created before v0.2 (doi/arxiv columns)
    if known and state.kv_get("doi_backfill_done") != "1":
        for it in items:
            if it.item_id in known:
                state.upsert_item(
                    it.item_id,
                    doi=(it.doi or "").lower() or None,
                    arxiv_id=pdf_resolver.find_arxiv_id(it),
                    title=it.title,
                )
        state.kv_set("doi_backfill_done", "1")
        state.trace("metadata_backfill", "", "doi/arxiv refreshed for {} items".format(len(known)))
    retry_ids = state.retry_item_ids()
    current_ids = set()
    targets: List[RawItem] = []
    new_ids = set()
    for it in items:
        current_ids.add(it.item_id)
        if it.item_id not in known:
            targets.append(it)
            new_ids.add(it.item_id)
        elif it.item_id in retry_ids:
            targets.append(it)
    summary.new_items = len(new_ids)

    citekey_map: Dict[str, str] = {}
    if targets:
        citekey_map = reader.bbt_citekeys([t.item_key for t in targets])
        if not citekey_map and not reader.zotero_alive():
            log.warning("Zotero local server unreachable; citekeys unavailable this cycle")

    for it in targets:
        try:
            _process_item(it, citekey_map, cfg, state, summary, is_new=(it.item_id in new_ids))
        except Exception as exc:  # keep the loop alive; record everything
            summary.errors += 1
            log.exception("item %s failed", it.item_key)
            state.upsert_item(
                it.item_id,
                item_key=it.item_key,
                title=it.title,
                note_status="error",
                last_error=str(exc)[:500],
            )
            state.trace("item_error", it.item_key, str(exc)[:500])

    # deletions (Zotero side). The vault is NEVER modified for deletions.
    for gone in sorted(known - current_ids):
        row = state.get_item(gone)
        if row is not None and not row["deleted"]:
            state.mark_deleted(gone)
            state.trace("item_deleted_in_zotero", row["citekey"] or row["item_key"], "vault untouched")
            summary.deleted += 1

    _detect_analyses(cfg, state, summary)
    _update_vault_records(cfg, state, summary, backfill)

    if db_sig:
        state.kv_set("zotero_db_sig", db_sig)
    state.kv_set("last_run", summary.line())
    import datetime as _dt

    state.kv_set("last_run_at", _dt.datetime.now().isoformat(timespec="seconds"))
    if backfill:
        state.trace("backfill", "", "registered {} existing items".format(summary.new_items))
    return summary
