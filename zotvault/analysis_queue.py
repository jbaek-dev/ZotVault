"""Analysis queue: which papers still lack an AI analysis note.

The analysis itself is produced either by the built-in engine (`zotvault
analyze`, see docs/ANALYSIS.md) or by your own LLM workflow. ZotVault only:
- lists pending papers (with a readable PDF path when available), and
- detects completion (a `*_analysis.md` file appearing in the citekey folder).

Convention: any file matching `*_analysis.md` in the citekey folder counts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class QueueEntry:
    citekey: str
    folder: Path
    has_note: bool
    analysis_files: List[str]
    pdf_path: Optional[str] = None

    @property
    def analyzed(self) -> bool:
        return len(self.analysis_files) > 0


def scan(papers_dir: Path) -> List[QueueEntry]:
    papers_dir = Path(papers_dir)
    entries: List[QueueEntry] = []
    if not papers_dir.exists():
        return entries
    for sub in sorted(papers_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        analysis = sorted(p.name for p in sub.glob("*_analysis.md"))
        entries.append(
            QueueEntry(
                citekey=sub.name,
                folder=sub,
                has_note=(sub / (sub.name + ".md")).exists(),
                analysis_files=analysis,
            )
        )
    return entries


def pending(papers_dir: Path) -> List[QueueEntry]:
    return [e for e in scan(papers_dir) if not e.analyzed]


def progress(papers_dir: Path) -> "tuple[int, int]":
    entries = scan(papers_dir)
    analyzed = sum(1 for e in entries if e.analyzed)
    return analyzed, len(entries)


def analysis_file_for(papers_dir: Path, citekey: str) -> Optional[Path]:
    folder = Path(papers_dir) / citekey
    if not folder.is_dir():
        return None
    hits = sorted(folder.glob("*_analysis.md"))
    return hits[0] if hits else None
