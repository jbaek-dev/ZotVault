"""Vault index.md / log.md maintenance.

Deliberately conservative:
- index.md: only a progress counter is touched. Preferred marker is the
  language-neutral `<!-- zotvault:progress N/M -->`; a legacy Korean marker is
  still recognized so existing vaults keep working. If neither is present,
  nothing is written.
- log.md: append-only, one entry per run *that changed something*.
- dry_run skips all writes.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Optional

# Language-neutral marker (recommended for new vaults). Place anywhere:
#   <!-- zotvault:progress 12/34 -->
SENTINEL_RE = re.compile(r"(<!--\s*zotvault:progress\s+)(\d+)(\s*/\s*)(\d+)(\s*-->)")
# Legacy Korean marker, kept as a fallback.
PROGRESS_RE = re.compile(r"(-\s*✅\s*\*\*)(\d+)(\s*/\s*)(\d+)(\*\*\s*zotero\s*논문)")


def _active_re(text: str) -> "re.Pattern[str]":
    return SENTINEL_RE if SENTINEL_RE.search(text) else PROGRESS_RE


def update_progress(index_path: Path, analyzed: int, total: int, dry_run: bool = False) -> bool:
    """Update the literature-review progress counter. Returns True if changed."""
    index_path = Path(index_path)
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    rx = _active_re(text)
    m = rx.search(text)
    if not m:
        return False
    if m.group(2) == str(analyzed) and m.group(4) == str(total):
        return False
    new_text = rx.sub(
        lambda mm: "{}{}{}{}{}".format(mm.group(1), analyzed, mm.group(3), total, mm.group(5)),
        text,
        count=1,
    )
    if not dry_run:
        index_path.write_text(new_text, encoding="utf-8")
    return True


def append_log(
    log_path: Path,
    title: str,
    summary: str,
    files: str,
    dry_run: bool = False,
    entry_type: str = "log",
) -> bool:
    """Append a work-log entry in the vault's established format."""
    log_path = Path(log_path)
    if not log_path.exists():
        return False
    day = _dt.date.today().isoformat()
    block = "\n## [{day}] {etype} | {title}\n- summary: {summary}\n- files: {files}\n".format(
        day=day, etype=entry_type, title=title, summary=summary, files=files
    )
    if not dry_run:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(block)
    return True


def current_progress(index_path: Path) -> Optional["tuple[int, int]"]:
    index_path = Path(index_path)
    if not index_path.exists():
        return None
    text = index_path.read_text(encoding="utf-8")
    m = _active_re(text).search(text)
    if not m:
        return None
    return int(m.group(2)), int(m.group(4))
