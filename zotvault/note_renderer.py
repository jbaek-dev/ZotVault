"""Render Obsidian paper notes.

Rules:
- If a note already exists for a citekey, ZotVault NEVER touches it (M1).
  Any user-owned section survives because existing files are skipped entirely.
- Writes are atomic (tmp file + os.replace).
- The template is overridable: set [vault] template_file to a markdown file
  using the placeholders listed in DEFAULT_TEMPLATE. The shipped default is
  language-neutral and minimal; personal/opinionated layouts belong in an
  override file, not in the code.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from zotvault.zotero_reader import RawItem

if TYPE_CHECKING:
    from zotvault.config import Config

# Available placeholders: citekey, title, title_raw, authors, year, journal,
# doi, doi_link, url, created, item_key, abstract, pdf_line, analysis_link.
DEFAULT_TEMPLATE = """---
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
zotvault_note_version: 1
tags:
  - paper
---

# {title_raw}

## Notes
<!-- Your own notes go here. ZotVault never overwrites an existing note. -->

## Abstract
{abstract}

## Resources
- PDF: {pdf_line}
- Zotero: zotero://select/items/{item_key}
- DOI: {doi_link}

<!-- zotvault:annotations:start -->
<!-- zotvault:annotations:end -->

## AI Analysis
- [[{analysis_link}]]
"""

# Engine -> analysis-note filename suffix. Matches analyze.engine_suffix; the
# fallback for engine "none" is "claude" to match the historical convention.
_SUFFIX = {"claude-cli": "claude", "anthropic": "claude",
           "ollama": "ollama", "openai-compatible": "ai"}


def _analysis_suffix(cfg: "Optional[Config]") -> str:
    if cfg is None:
        return "claude"
    if getattr(cfg, "analysis_suffix", ""):
        return cfg.analysis_suffix
    return _SUFFIX.get(getattr(cfg, "analysis_engine", "none"), "claude")


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


def _load_template(cfg: "Optional[Config]") -> str:
    tf = getattr(cfg, "template_file", "") if cfg else ""
    if tf:
        p = Path(os.path.expanduser(tf))
        if p.exists():
            return p.read_text(encoding="utf-8")
    return DEFAULT_TEMPLATE


def render_note(item: RawItem, cfg: "Optional[Config]" = None) -> str:
    if not item.citekey:
        raise ValueError("cannot render note without citekey (item {})".format(item.item_key))
    doi = (item.doi or "").strip()
    template = _load_template(cfg)
    return template.format(
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
        analysis_link="{}_{}_analysis".format(item.citekey, _analysis_suffix(cfg)),
    )


def note_path_for(papers_dir: Path, citekey: str) -> Path:
    return Path(papers_dir) / citekey / (citekey + ".md")


def write_note(papers_dir: Path, item: RawItem, dry_run: bool = False,
               cfg: "Optional[Config]" = None) -> Tuple[str, Optional[Path]]:
    """Create the paper note if missing. Returns (status, path).

    status: 'created' | 'existing' | 'dry-run'
    """
    path = note_path_for(papers_dir, item.citekey)
    if path.exists():
        return "existing", path
    if dry_run:
        return "dry-run", path
    content = render_note(item, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    # temp must share the destination filesystem for os.replace to be atomic
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".zv-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "created", path
