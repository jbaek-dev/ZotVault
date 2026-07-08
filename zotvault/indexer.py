"""Vault index.md / log.md maintenance.

Deliberately conservative:
- index.md: only the `- ✅ **N / M** zotero 논문` progress counters are touched,
  via a strict regex. If the pattern is not found, nothing is written.
- log.md: append-only, one entry per run *that changed something*.
- dry_run skips all writes.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Optional

PROGRESS_RE = re.compile(r"(-\s*✅\s*\*\*)(\d+)(\s*/\s*)(\d+)(\*\*\s*zotero\s*논문)")


def update_progress(index_path: Path, analyzed: int, total: int, dry_run: bool = False) -> bool:
    """Update the literature-review progress counters. Returns True if changed."""
    index_path = Path(index_path)
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    m = PROGRESS_RE.search(text)
    if not m:
        return False
    if m.group(2) == str(analyzed) and m.group(4) == str(total):
        return False
    new_text = PROGRESS_RE.sub(
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
    m = PROGRESS_RE.search(index_path.read_text(encoding="utf-8"))
    if not m:
        return None
    return int(m.group(2)), int(m.group(4))
