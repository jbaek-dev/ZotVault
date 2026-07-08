# Coming from obsidian-zotero-integration / ZotLit

ZotVault coexists with — and can gradually replace — the click-driven import
plugins. Your existing literature notes are safe by construction: ZotVault
never rewrites an existing note outside its own marker block.

## What carries over automatically

- **Your notes**: nothing is re-imported or overwritten. ZotVault keys papers
  by Better BibTeX citekey; if your notes already live in per-citekey folders
  (`<papers_subdir>/<citekey>/<citekey>.md`), ZotVault recognizes them as
  "existing" and leaves them alone.
- **Your citekeys**: same source (Better BibTeX), so filenames match.
- **New papers**: from now on the daemon creates notes automatically — the
  thing the plugins never did.

## Folder layout differences

The plugins typically write flat files (`Reading/@citekey.md`). ZotVault uses
per-citekey folders so a paper's note, AI analysis and assets live together.
Two options:

1. **Fresh cutover (recommended)**: point `[vault] papers_subdir` at a new
   folder and let ZotVault populate it going forward. Old notes stay where
   they are; wiki-links keep working because Obsidian resolves by filename.
2. **Move-in**: place each `@citekey.md` as `<citekey>/<citekey>.md` inside
   `papers_subdir`. ZotVault will treat them as existing notes.

## Annotation (highlight) sync

ZotVault syncs Zotero highlights into ONE marker-delimited block per note:

```
<!-- zotvault:annotations:start -->
...auto-managed, grouped by highlight color, deep links to the PDF...
<!-- zotvault:annotations:end -->
```

- Notes created by ZotVault (v0.8+) include the markers — sync just works.
- Notes imported by the plugins do NOT have markers, so by default ZotVault
  leaves them byte-identical. To opt in, set:

```toml
[annotations]
adopt_existing = true   # appends the block once at the end of unmarked notes
```

Only papers that actually have annotations are touched. Everything outside
the markers (including the plugins' own annotation sections and your
`{% persist %}` content) is never modified — you can keep the old sections as
history or delete them yourself.

## Template

Bring your favorite layout: copy your structure into a file and set
`[vault] template_file`. Available placeholders are listed at the top of
`zotvault/note_renderer.py` (add the marker pair to get annotation sync in
new notes). Nunjucks logic from plugin templates isn't supported — the
ZotVault template is intentionally plain `{placeholder}` substitution.

## Keeping the plugin around

Perfectly fine. ZotVault never touches notes it doesn't own, so you can keep
using the plugin's in-editor citation picker or one-off imports alongside the
daemon. Just avoid pointing both tools' *automatic* writes at the same file.
