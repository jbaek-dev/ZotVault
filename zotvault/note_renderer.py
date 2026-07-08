"""Render Obsidian paper notes compatible with the Papers_Zotero_v3 template.

Rules:
- If a note already exists for a citekey, ZotVault NEVER touches it (M1).
  The `## My Synthesis` section is user-owned; skipping existing files is the
  strongest possible guarantee that it survives.
- Writes are atomic (tmp file + os.replace).
- Annotation (highlight) sections are emitted empty; rich highlight import can
  still be done via the obsidian-zotero-desktop-connector plugin, which
  ZotVault deliberately does not overwrite.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from zotvault.zotero_reader import RawItem

NOTE_TEMPLATE = """---
type: paper
source: zotero
citekey: "{citekey}"
title: "{title}"
authors: "{authors}"
year: "{year}"
journal: "{journal}"
doi: "{doi}"
url: "{url}"
created: "{created}"
itemKey: "{item_key}"
template: Papers_Zotero_v3
PDF: "[View inside Zotero](zotero://select/library/items/{item_key})"
tags:
  - paper
---

# {title_raw}

---

## 🧠 My Synthesis (DO NOT AUTO-OVERWRITE)
> ⚠️ **Manually written section**
> This section must NOT be modified by Zotero re-sync.

- Key contributions:
- What I care about:
- Open questions / limitations:
- Ideas for my own research:

---

## 📄 Abstract
{abstract}

---

## 📚 Resources
- **PDF:** {pdf_line}
- **Zotero:** zotero://select/items/{item_key}
- **DOI:** {doi_link}

---

## ✏️ Zotero Notes & Highlights (AUTO-GENERATED)
> 🔄 Automatically updated when Zotero highlights or comments change

---

### 🔴 Red — Core Claims / Main Ideas


---

### 🟨 Yellow — Key Evidence / Important Points


---

### 🟩 Green — Background / Context


---

## 📎 Figure / Image Annotations


---

## 🔖 Links
- Related papers:
  - [[ ]]
- Concepts / notes:
  - [[ ]]

## 🤖 AI Analysis
- [[{citekey}_claude_analysis]]
"""


def _yaml_escape(value: str) -> str:
    """Escape a value for use inside a double-quoted YAML scalar."""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def render_note(item: RawItem) -> str:
    if not item.citekey:
        raise ValueError("cannot render note without citekey (item {})".format(item.item_key))
    doi = (item.doi or "").strip()
    return NOTE_TEMPLATE.format(
        citekey=_yaml_escape(item.citekey),
        title=_yaml_escape(item.title),
        title_raw=(item.title or item.citekey).replace("\n", " ").strip(),
        authors=_yaml_escape(item.authors),
        year=_yaml_escape(item.year),
        journal=_yaml_escape(item.journal),
        doi=_yaml_escape(doi),
        url=_yaml_escape(item.url),
        created=_yaml_escape(item.date_added_day),
        item_key=item.item_key,
        abstract=(item.abstract or "").strip(),
        pdf_line=(item.pdf_path or ""),
        doi_link=("https://doi.org/" + doi) if doi else "",
    )


def note_path_for(papers_dir: Path, citekey: str) -> Path:
    return Path(papers_dir) / citekey / (citekey + ".md")


def write_note(papers_dir: Path, item: RawItem, dry_run: bool = False) -> Tuple[str, Optional[Path]]:
    """Create the paper note if missing. Returns (status, path).

    status: 'created' | 'existing' | 'dry-run'
    """
    path = note_path_for(papers_dir, item.citekey)
    if path.exists():
        return "existing", path
    if dry_run:
        return "dry-run", path
    content = render_note(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "created", path
