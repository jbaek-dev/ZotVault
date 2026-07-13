# Changelog

## 0.9.7 — 2026-07-12 (search reliability + collected-picks cart)

- Search & Add dashboard: each result now has an ↗ link to its actual page
  (DOI resolver, or the arXiv abstract page when there's no DOI) so you can
  read before adding. A "Copy DOIs" button copies the DOI (or `arXiv:id`
  when there's no DOI) of everything selected, one per line, to the
  clipboard. Selections now survive across searches — checking a paper adds
  it to a small collected-picks strip above the results that stays put
  while you search other keywords, so you can gather picks from several
  queries and add them to Zotero in one batch; click a pick's ✕ or "Clear
  all" to drop it.
- Fixed dashboard search intermittently failing with "The read operation
  timed out" on arXiv queries. `export.arxiv.org` was being called over
  plain `http://`, which always 301-redirects to `https://` — under
  back-to-back requests that extra hop would occasionally stall past the
  20s timeout instead of erroring cleanly. Search (and the arXiv-id
  resolver used by `add`/alerts) now calls `https://` directly, and search
  retries once after a short delay on a stalled connection before
  surfacing a plain-language error instead of a raw socket message. 132 tests.

## 0.9.6 — 2026-07-10 (readable arXiv titles)

- arXiv titles/abstracts arrive with raw TeX ("monolayer WSe$_2$",
  "$\\Gamma$ point", "10$^{-9}$ s"). They are now converted to readable
  unicode (WSe₂, Γ, 10⁻⁹) at parse time — fixing the alert inbox, search
  results, AND the titles saved into Zotero on approve/add. Sub/superscripts
  are only touched inside $…$ (a bare snake_case survives); unmappable
  scripts degrade to plain text (T$_c$ → Tc). 129 tests.

## 0.9.5 — 2026-07-10 (dashboard polish, from real use)

- The Doctor button now **toggles** the setup checklist, and the card has a
  Close button.
- The **queue** and **alerts pending** stats are clickable — they jump to
  (and briefly highlight) their sections, so a nonzero count is never a
  dead end.

## 0.9.4 — 2026-07-09 (Zotero-only mode: tiered requirements)

ZotVault now runs with **just Zotero** — Obsidian and Ollama are layers, not
prerequisites:

- **Zotero-only mode**: with no `[vault] dir`, the search dashboard,
  one-shot `add` (+OA PDF), arXiv alert inbox, proxy fallback and audit
  trace all work; note/annotation/queue/suggestion machinery stays cleanly
  off (the guards already existed — this release makes the mode a first-class
  citizen).
- `zotvault init` treats the vault question as optional ("blank =
  Zotero-only mode") and explains what switches on when you add a vault
  later.
- `doctor` no longer fails on optional layers: vault and Ollama checks are
  marked `(optional)` and render as "–" instead of "❌"; the verdict only
  counts real problems.
- Dashboard: `/api/status` reports `mode`; in Zotero-only mode the queue and
  suggestion sections hide behind a one-line "set [vault] dir to unlock…"
  hint, and the setup checklist no longer demands a vault.
- README: requirements rewritten as a tier table (Zotero required → +markdown
  folder → +Ollama). 124 tests.

## 0.9.3 — 2026-07-09 (Zotero <-> vault reconciliation)

Closes the "deletions leave ghosts" gap found in real use (dashboard queue
count disagreed with the actual note folders):

- **Vault note deleted by the user** (item still in Zotero): detected on scan
  and marked `missing` — **never recreated behind your back**. The dashboard's
  new *Needs attention* card offers **Recreate note** / **Ignore** per paper.
- **Item deleted from Zotero** (note still in the vault): listed with
  **Re-add to Zotero** (uses the stored DOI/arXiv id, connector channel) /
  **Dismiss**. The note itself is never touched (standing invariant).
- **Ignore list**: dismissed/ignored papers are excluded from counts, retries
  and the queue; viewable/undoable via a dashboard toggle; `zotvault add` of
  an ignored paper warns and requires `--force` (or Unignore).
- Dashboard **queue stat now shows the real queue length** instead of
  items−analyzed arithmetic (the source of the original confusion).
- New: `GET /api/attention`, `POST /api/attention/action`. 122 tests.

## 0.9.2 — 2026-07-08 (first-run experience)

- **Interactive setup**: `zotvault init` is now a wizard when run in a
  terminal — asks for the vault folder (validated), notes subfolder,
  Unpaywall email and language; offers to scaffold missing vault files
  (papers folder, index.md with the progress marker, log.md); then runs
  `doctor` and prints next steps. Non-interactive contexts (pipes, the app
  launcher, `--yes`) keep the old template-only behavior.
- **Dashboard setup checklist**: new `GET /api/doctor` + a checklist card
  that appears automatically when core config is missing (or the library is
  empty), and on demand via the new **Doctor** header button. Buttons got
  explanatory tooltips; "Enrich" is now "Refresh suggestions".
- Health checks moved to `zotvault/health.py` (shared by CLI + web); fixed a
  crash in the state-db check. 113 tests.

## 0.9.1 — 2026-07-08 (first real-use feedback)

- **Fix: MathML/JATS markup in titles** — Crossref ships titles like
  `bilayer <mml:math…>MoS 2…</mml:math>`; titles (and journal names) from
  Crossref/DataCite are now sanitized everywhere (add, search results),
  joining math text nodes correctly ("MoS2") and dropping duplicate LaTeX
  `<mml:annotation>` bodies.
- **PDF arrives with the paper**: DOI adds now do one quick Unpaywall lookup
  and put the OA PDF into the connector payload — *Zotero itself* downloads
  it into its own storage (same as the browser connector; ZotVault still
  never writes `storage/`). Licensed/proxy PDFs keep using the daemon's
  fallback path.
- **No more 2-minute wait**: a successful add (dashboard or CLI) triggers one
  immediate pipeline cycle, so the note/queue/PDF status appear in seconds.
- 109 tests.

## 0.9.0 — 2026-07-08 (figures, triage, tray)

- **Figure/area annotations embedded**: image and ink annotations now land in
  the notes as `![[citekey_ANNKEY.png]]` (copied from Zotero's rendered
  cache; deep-link fallback when no cache exists). App-owned files, never
  deleted.
- **Color semantics are yours**: `[annotations] label_red = "Core Claims"`
  etc. rename the highlight groups to match your own highlighting system.
- **assist — small-local-model structured output**: first task is arXiv alert
  triage. A small Ollama model scores inbox candidates 0-10 under a strict
  JSON contract (constrained decoding + schema validation + one retry);
  dashboard sorts by score. Purely advisory, off by default.
- **System tray** (`zotvault tray`, optional extra `pip install ".[tray]"`): daemon + tray icon with Open Dashboard / Run now /
  Pause / Quit — the Syncthing pattern. Core stays zero-dependency (extras
  are the only third-party imports, enforced by the CI stdlib guard).
- **Windows**: console-encoding crash fix (emoji on cp949/cp1252),
  `install-daemon` now prints the Task Scheduler command on Windows and
  writes a systemd user unit on Linux.
- Daemon loop refactored around stop/pause events (shared by CLI and tray).
- 101 tests.

## 0.8.0 — 2026-07-08 (edit-safe annotation sync)

The ecosystem's most-requested capability, on ZotVault's safety contract:

- **Highlight sync**: Zotero PDF annotations render into one marker-delimited
  block per note — grouped by highlight color (Zotero palette names/emoji),
  with quotes, optional comments, page labels and `zotero://open-pdf` deep
  links to the exact annotation. Deletions in Zotero clear the block; a
  per-paper digest keeps every cycle idempotent.
- **Edit-safe by construction**: only the text between
  `<!-- zotvault:annotations:start/end -->` is ever rewritten. Notes without
  markers are left byte-identical unless `[annotations] adopt_existing = true`
  (appends the block once). New-note templates include the markers.
- **Invariant refined**: "never rewrite an existing note" → "never touch
  anything outside ZotVault-owned marker blocks" (docs/ARCHITECTURE.md).
- docs/MIGRATION.md for obsidian-zotero-integration / ZotLit users.
- 90 tests (annotation render/upsert/digest + full pipeline E2E incl.
  user-edit preservation and deletion-clearing).

## 0.7.0 — 2026-07-08 (adoption hardening)

After an adversarial review (6 hostile personas) + market research, fixed the
issues that blocked non-me users:

- **i18n**: English is now the default for `log.md` wording and messages;
  `[app] language = "ko"` restores Korean. `index.md` progress uses a
  language-neutral `<!-- zotvault:progress N/M -->` marker (legacy Korean
  marker still recognized).
- **Template externalization**: the note template is minimal/neutral by
  default and overridable via `[vault] template_file`; the analysis backlink
  now follows the engine suffix (no more dangling `_claude_analysis` for other
  engines).
- **Security**: PDF text is delimited as UNTRUSTED DATA with an explicit
  "don't obey instructions" preamble; `claude-cli` runs with tools disabled
  and prompt on stdin (no "read this file and follow it"); analysis output is
  length-capped; dashboard GET endpoints now enforce the local-Host guard
  (DNS-rebind); PDF/proxy downloads are byte-capped (memory-DoS).
- **Non-BBT clarity**: items without a Better BibTeX citekey become `blocked`
  (not silently `pending`) with an actionable trace + doctor/status message;
  Better BibTeX documented as required.
- **Performance**: skip the full sqlite snapshot + rescan when the Zotero DB
  is unchanged and nothing is pending; `busy_timeout` on state.db.
- **Fixed broken references** to non-existent `prompts/analyze_paper.md` /
  `scripts/find_unanalyzed_papers.sh` (CLI + dashboard + docs).
- **Contributor infra**: GitHub Actions (unittest on 3.9–3.13 + ruff +
  stdlib-only guard), `ruff.toml`, `docs/ANALYSIS.md`; README clone dir /
  install / Windows-Linux run instructions fixed. 77 tests.

## 0.6.0 — 2026-07-08 (ZotVault)

- **Renamed PaperFlow → ZotVault** (name collisions with papersflow.ai,
  paper-flow.ai and same-named GitHub projects). Module `zotvault`, CLI
  `zotvault`, config/state at `~/.zotvault/`, app bundle ZotVault.app,
  header `X-ZotVault`, env `ZOTVAULT_*` / `POLARIS_ZOTVAULT_URL`.
- **Pluggable AI analysis engine** (`[analysis] engine`): `ollama` (local,
  free), `claude-cli` (your Claude subscription via `claude -p`),
  `openai-compatible` (LM Studio/vLLM/OpenRouter/...), `anthropic` (API), or
  `none` (manual workflow, default). Generates `{citekey}_*_analysis.md` with
  the vault's ai_analysis frontmatter; never overwrites existing analyses;
  daily budget; `auto = false` by default (daemon can auto-analyze when
  enabled). Full text via poppler `pdftotext`, abstract fallback recorded in
  `input_basis`. New: `zotvault analyze`, dashboard "Analyze pending" button,
  doctor engine checks.

## 0.5.1 — 2026-07-08 (ultrareview hardening)

- **search**: DOI/arXiv id in the search box now resolves the exact paper
  (direct lookup) instead of keyword-matching garbage; friendly S2 429 message.
- **proxy**: EZproxy sessions actually work — browser-exported session cookies
  (expiry=0) are pinned so Python sends them; `citation_pdf_url` is re-routed
  through the proxy; Wiley `/doi/pdfdirect/` variant; EZproxy "not configured"
  stanza error surfaced with an actionable message. Verified live end-to-end.
- **security**: dashboard POST endpoints require the `X-ZotVault` header and
  a local `Host` (blocks cross-origin CSRF against 127.0.0.1); cookie-file
  permission check in `doctor`; `.gitignore` blocks cookie files.
- **launchd**: `KeepAlive.SuccessfulExit=false` + lock-conflict exit 0 —
  removes the respawn loop when the icon-launched daemon already runs.
- **robustness**: filesystem-unsafe citekeys are rejected per-item; friendly
  port-in-use message for `zotvault web`; lint cleanups.
- **app bundle**: AppleScript-applet launcher (the only bundle form macOS TCC
  can bind grants to); bundle frozen after ad-hoc signing; code loads from
  `~/.zotvault/app` synced by `scripts/apply_edits.sh` — grants survive edits.

## 0.5.0 — 2026-07-05 (M2–M5)

### M2 — collect
- One-shot add: `zotvault add <doi|arxiv|url>` — Crossref/DataCite/arXiv
  native resolvers → Zotero `/connector/saveItems` (the browser-connector
  channel). Optional translation-server for arbitrary URL imports.
- Duplicate detection against local state (DOI / arXiv id).
- Paper search (`zotvault search`, dashboard): arXiv, Semantic Scholar,
  Crossref, with in-library annotation.
- Local web dashboard (stdlib HTTP server, localhost-only): search → select →
  add, analysis queue, alerts inbox, suggestions, audit trace.

### M3 — licensed PDFs (opt-in, off by default)
- EZproxy-style URL template + browser `cookies.txt` session reuse (no
  password automation; 2FA-friendly).
- `citation_pdf_url` landing-page heuristic.
- Separate strict budget (`proxy_daily_limit`) + long delays. docs/PROXY.md.

### M4 — intelligence
- Citation graph: Semantic Scholar citation counts + in-library citation
  edges → auto-regenerated `Citation_Graph.md` (human notes never touched).
- Related papers: local Ollama embeddings (nomic-embed-text) over analysis
  notes → `Related_Suggestions.md` candidates.
- arXiv alerts: daily keyword digest → review inbox; approval required
  before anything enters Zotero.
- Synthesis suggestions: leader clustering of analyzed-but-unsynthesized
  papers → `syntheses/_Synthesis_Suggestions.md`.

### M5 — ecosystem
- Polaris agent bridge (`polaris/tools/zotvault_tools.py` in the Polaris
  repo): status / queue / search / add via the ZotVault HTTP API.
- Docs, 47+ unit tests, zero runtime dependencies (Python ≥ 3.9 stdlib).

## 0.1.0 — 2026-07-04 (M1)
- Core loop: Zotero sqlite-snapshot polling → Papers_Zotero_v3-compatible
  note creation (existing notes never rewritten) → OA-first PDF resolution
  (arXiv, Unpaywall; daily limit + delays) → analysis queue with completion
  detection → conservative index.md counter patch + append-only log.md.
- Better BibTeX JSON-RPC citekey resolution (+ Extra-field fallback).
- CLI (init/doctor/run-once/daemon/queue/status/trace), launchd integration,
  SQLite state + full audit trace.
