"""Edit-safe Zotero annotation (highlight) sync — v0.8.

The single most requested capability in the Zotero↔Obsidian ecosystem, built
on ZotVault's vault contract:

- Annotations render into ONE marker-delimited block:
      <!-- zotvault:annotations:start --> ... <!-- zotvault:annotations:end -->
  Only the text BETWEEN the markers is ever rewritten. Everything outside —
  your notes, syntheses, other plugins' sections — remains untouchable.
- Notes created by ZotVault (v0.8+ templates) carry the empty marker pair, so
  they get live annotation sync out of the box.
- Notes WITHOUT markers (pre-existing / other tools') are NOT modified unless
  you opt in with [annotations] adopt_existing = true, which appends the block
  once at the end of the note.
- A per-paper digest keeps this idempotent: the block is rewritten only when
  the annotation set actually changed (including deletions — the block is
  regenerated wholesale from Zotero's current truth).

This refines the historical "never rewrite an existing note" invariant to:
"never touch anything outside ZotVault-owned marker blocks" (decision
2026-07-08, see docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

log = logging.getLogger("zotvault.annotations")

if TYPE_CHECKING:
    from zotvault.config import Config
    from zotvault.zotero_reader import Annotation

START = "<!-- zotvault:annotations:start -->"
END = "<!-- zotvault:annotations:end -->"

# Zotero default palette -> (emoji, English name). Unknown colors fall back to
# the hex code so nothing is ever silently dropped.
COLOR_NAMES = {
    "#ffd400": ("🟡", "Yellow"),
    "#ff6666": ("🔴", "Red"),
    "#5fb236": ("🟢", "Green"),
    "#2ea8e5": ("🔵", "Blue"),
    "#a28ae5": ("🟣", "Purple"),
    "#e56eee": ("🩷", "Magenta"),
    "#f19837": ("🟠", "Orange"),
    "#aaaaaa": ("⚪", "Gray"),
}

# Zotero annotation types: 1 highlight, 2 note, 3 image, 4 ink, 5 underline,
# 6 text. Text-bearing types are rendered; image/ink are embedded when Zotero's
# rendered cache PNG exists (falling back to a deep link).
TEXT_TYPES = {1, 2, 5, 6}
IMAGE_TYPES = {3, 4}

# config color keys -> palette hex (for [annotations] label_<name> overrides)
LABEL_KEYS = {
    "yellow": "#ffd400", "red": "#ff6666", "green": "#5fb236", "blue": "#2ea8e5",
    "purple": "#a28ae5", "magenta": "#e56eee", "orange": "#f19837", "gray": "#aaaaaa",
}


def color_label(color: str, cfg: "Config"):
    """(emoji, label) for a hex color, honoring [annotations] label_* overrides."""
    c = (color or "").lower()
    emoji, default = COLOR_NAMES.get(c, ("⬜", c or "No color"))
    overrides = getattr(cfg, "annotations_labels", {}) or {}
    for key, hexval in LABEL_KEYS.items():
        if hexval == c and overrides.get(key):
            return emoji, overrides[key]
    return emoji, default


def prepare_images(annotations: "List[Annotation]", zotero_cache_dir: Path,
                   assets_dir: Path, citekey: str, dry_run: bool = False) -> Dict[str, str]:
    """Copy Zotero's rendered annotation images into the note's assets folder.

    Returns {annotation_key: embedded_filename}. Only annotations whose cache
    PNG exists are embedded; the rest fall back to a deep link. Files are
    app-owned but never deleted (no-delete principle) — orphans are harmless.
    """
    out: Dict[str, str] = {}
    for a in annotations:
        if a.type not in IMAGE_TYPES:
            continue
        src = Path(zotero_cache_dir) / (a.key + ".png")
        if not src.exists():
            continue
        fname = "{}_{}.png".format(citekey, a.key)
        dest = Path(assets_dir) / fname
        try:
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
                    shutil.copy2(str(src), str(dest))
            out[a.key] = fname
        except OSError as exc:
            log.warning("annotation image copy failed (%s): %s", a.key, exc)
    return out


def digest(annotations: "List[Annotation]") -> str:
    h = hashlib.sha1()
    for a in sorted(annotations, key=lambda x: (x.sort_index, x.key)):
        h.update("|".join([
            a.key, str(a.type), a.color or "", a.page_label or "",
            a.text or "", a.comment or "", a.date_modified or "",
        ]).encode("utf-8"))
    return h.hexdigest()


def _quote(text: str, max_chars: int) -> str:
    flat = " ".join((text or "").split())
    if len(flat) > max_chars:
        flat = flat[:max_chars].rstrip() + "…"
    return flat


def _deep_link(a: "Annotation") -> str:
    return "zotero://open-pdf/library/items/{}?page={}&annotation={}".format(
        a.attachment_key, a.page_label or "", a.key)


def render_block(annotations: "List[Annotation]", cfg: "Config",
                 images: "Dict[str, str]" = None) -> str:
    """Render the full marker-delimited block (deterministic).

    images: {annotation_key: filename} for image/ink annotations whose PNG was
    copied into the vault (see prepare_images).
    """
    images = images or {}
    lines = [START, "", "## Annotations (Zotero)",
             "<!-- auto-synced by ZotVault; edits inside this block are overwritten -->", ""]
    text_anns = [a for a in annotations if a.type in TEXT_TYPES and (a.text or a.comment)]
    image_anns = [a for a in annotations if a.type in IMAGE_TYPES]

    by_color: Dict[str, List] = {}
    for a in text_anns:
        by_color.setdefault((a.color or "").lower(), []).append(a)

    # stable ordering: known palette order first, then unknown colors
    palette = list(COLOR_NAMES.keys())
    ordered = sorted(by_color.keys(), key=lambda c: (palette.index(c) if c in palette else 99, c))
    for color in ordered:
        emoji, name = color_label(color, cfg)
        group = sorted(by_color[color], key=lambda x: (x.sort_index, x.key))
        lines.append("### {} {} ({})".format(emoji, name, len(group)))
        lines.append("")
        for a in group:
            if a.text:
                lines.append("> {}".format(_quote(a.text, cfg.annotations_max_quote_chars)))
            if a.comment and cfg.annotations_include_comments:
                lines.append("> 💬 {}".format(_quote(a.comment, cfg.annotations_max_quote_chars)))
            lines.append("> — p.{} · [open]({})".format(a.page_label or "?", _deep_link(a)))
            lines.append("")
    if image_anns:
        lines.append("### 🖼 Figures & areas ({})".format(len(image_anns)))
        lines.append("")
        for a in sorted(image_anns, key=lambda x: (x.sort_index, x.key)):
            fname = images.get(a.key)
            if fname:
                lines.append("![[{}]]".format(fname))
            if a.comment and cfg.annotations_include_comments:
                lines.append("> 💬 {}".format(_quote(a.comment, cfg.annotations_max_quote_chars)))
            lines.append("> — p.{} · [open]({})".format(a.page_label or "?", _deep_link(a)))
            lines.append("")
    if not text_anns and not image_anns:
        lines.append("_no annotations_")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def upsert_block(note_path: Path, block: str, adopt_existing: bool,
                 dry_run: bool = False) -> str:
    """Insert/replace the annotations block. Returns status:
    updated | appended | unchanged | skipped-unmarked | missing-note
    """
    note_path = Path(note_path)
    if not note_path.exists():
        return "missing-note"
    text = note_path.read_text(encoding="utf-8")
    start_i = text.find(START)
    end_i = text.find(END)
    if start_i != -1 and end_i != -1 and end_i >= start_i:
        current = text[start_i:end_i + len(END)]
        if current == block:
            return "unchanged"
        new_text = text[:start_i] + block + text[end_i + len(END):]
        status = "updated"
    elif adopt_existing:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        new_text = text + sep + block + "\n"
        status = "appended"
    else:
        return "skipped-unmarked"
    if dry_run:
        return status
    fd, tmp = tempfile.mkstemp(dir=str(note_path.parent), prefix=".zv-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        os.replace(tmp, str(note_path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return status
