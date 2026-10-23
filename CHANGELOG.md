# Changelog

## 0.10.0 — Unreleased (PDF lands inside Zotero; security fix)

### Security

- **`claude-cli` analysis engine: tools were not actually disabled.** It ran
  `claude -p --allowedTools ""`, but `--allowedTools` only adds allow rules; it
  does not remove tools, and the user's own rules still applied. With a broad
  rule such as `Bash(*)` in your Claude Code settings, text planted in a paper
  (prompt injection) could have made the analysis step run shell commands. We
  confirmed this with a harmless canary command. It now runs with
  `--tools ""` (no built-in tools), `--strict-mcp-config` (no MCP servers) and
  an empty temporary working directory; the same canary test then finds no
  tool that can touch the machine. A Claude Code too old for `--tools` makes the analysis fail rather
  than run unprotected. Affects only `[analysis] engine = "claude-cli"`
  (default is `none`), in every published version (0.9.1 to 0.9.7; the flag
  was added in 0.7.0). If you used it, update.
- The PDF fetcher opens only `http(s)` URLs (urllib would also follow
  `file://` or `ftp://` from an Unpaywall/arXiv answer) and refuses bodies over
  100 MB instead of reading them into memory (the proxy path already did).
- Citekeys starting with a dot (`.`, `..`, `.hidden`) are refused as folder
  names; `..` would have placed a note one level above the papers folder.
- Dashboard: the escaping helper now also escapes `'`, and the item key in the
  "Needs attention" buttons is JSON-encoded before it goes into `onclick`
  (HTML escaping alone cannot protect a JavaScript string there).

### Fixes and features
- Related-paper embeddings no longer stall. A note longer than the embedding
  model's context made Ollama answer HTTP 500, and the refresh stopped at that
  note on every run, so every note after it was never embedded (here: 101 of
  296 notes, for weeks). The text is now halved and retried on a context-length
  refusal; a note that still does not fit is skipped and traced once, and the
  refresh continues. Ollama being down still stops the run as before.
  Notes are now embedded without their YAML frontmatter: about 1 KB of nearly
  identical metadata (model, input basis, tags) at the top made the vectors of
  shortened notes look alike. Each vector records this preparation version
  (`embeddings.prep`, guarded migration), so existing vectors are re-embedded
  once, within the usual per-run budget.
- Default similarity thresholds raised: `related_threshold` 0.75 -> 0.85,
  `synthesis_threshold` 0.70 -> 0.80 (`[features]`). With every note embedded,
  the old values let nearly every pair through in a single-field library
  (Related listed all papers; Synthesis made one 171-paper cluster). The new
  values were calibrated on one 296-paper library (random-pair median 0.71,
  p90 0.82); a broad library may want them lower.

- `zotvault add` (and approving an alert, and the dashboard's Add) now puts
  the open-access PDF inside the Zotero item. Zotero's local connector runs
  `saveItems` in `ATTACHMENT_MODE_IGNORE`, so an `attachments` hint is always
  discarded (confirmed in Zotero's debug log). The browser connector gets its
  PDF in by a second call in the same save session, `/connector/saveAttachment`;
  ZotVault now does the same. The PDF is fetched first (arXiv, then Unpaywall,
  same polite delays and daily budget as the daemon), the item is saved with an
  explicit connector id, and the file is uploaded as its child. If no OA PDF is
  found, Zotero's own resolver (`/connector/saveAttachmentFromResolver`, the
  engine behind Find Available PDF) is asked. Success means HTTP 201 from the
  upload and the message says so; a failed or missing PDF is reported as such.
  The two-call wire protocol was verified live on Zotero 9.0.6 with a test
  script (attachment row under the new item, byte-identical 20 MB file in
  `storage/`); the shipped `add` path itself is covered by mocked tests, and
  the Zotero-resolver fallback has not been run against Zotero yet. Only works at add time (the parent
  must be an item saved in the same session); existing items still need
  Find Available PDF. `--no-pdf` is back and now really skips the PDF.
  (The earlier draft of this release claimed this was impossible. That
  conclusion came from testing `saveItems` alone.)
- A registered item whose Better BibTeX citekey changes in Zotero is now re-pointed
  to the note folder of the new key, if that folder already exists. Until now only
  new items were ever looked at, so restoring an old key (for instance after a
  duplicate clean-up deleted the item that carried your analysis) left the item
  bound to the empty copy forever. The note is adopted as-is: nothing is created,
  rewritten or removed, the analysis in the folder is re-detected, and the
  highlight block is not touched until annotations actually change. If the new
  key has no note folder, or the folder already belongs to another live item,
  nothing is created or adopted and the change is only traced (once). A registered
  item now keeps its stored key in the per-item path (also used when an item is
  being retried), so a changed key can no longer create a new note there.
  The adopted note keeps its original `itemKey` / `zotero://` link in its header,
  which still point at the deleted item (existing notes are never rewritten).
- The "Needs attention" list no longer shows a deleted item whose note a live item
  now uses (same key reused or restored), since there is nothing left to act on.
- `Citation_Graph.md` and `Related_Suggestions.md` no longer keep links to papers
  that are gone. Citation edges and embeddings are stored by citekey and were
  never cleaned up, so a deleted item, a re-keyed one, or a note folder moved out
  of the vault left dangling `[[links]]` there for good (enrichment only fetches
  items it has never seen). Now the citation graph lists only live items, related
  suggestions (and synthesis clusters) only papers whose note folder is still in
  the vault, a citekey relink carries the paper's edges over to the new key, and
  an existing `Citation_Graph.md` is re-rendered on every enrich run even when
  nothing new was fetched (it is still only created by a first real enrichment).
  Rendering filters stored rows without deleting them. Moving edges on a relink
  drops only the rows the merge makes redundant (an edge that already exists
  under the new key, or a paper citing its own re-keyed duplicate).
  Embeddings are not re-keyed: they are computed per note folder, so the new
  key's folder has (or gets) its own vector.
- `add` now checks Zotero's own database for an existing DOI/arXiv id across
  every regular item type, not just ZotVault's `state.db` (which only knows the
  item types the pipeline makes notes for). Found while testing: a paper that
  was already in the library as a `webpage` item (saved from its arXiv abstract
  page) was saved a second time as a journal article.
- A PDF attachment titled like supplementary material (Supplementary / Supporting
  Information / Appendix, or SI / ESI / ESM as written) is no longer preferred as
  the paper's main PDF when the item also has another PDF, so analysis, highlight
  sync and the note's PDF link do not latch onto an SI file. An item whose only
  PDF looks like SI keeps using it.
- Fixed `zotvault init` corrupting the vault path when it's pasted from a
  shell-escaped source (terminal tab-completion, or dragging a folder into
  a POSIX terminal escapes spaces/tildes as `Mobile\ Documents`,
  `iCloud\~md\~obsidian`). `input()` isn't a shell, so those backslashes
  were never interpreted — they survived into the stored value, and the
  config writer's Windows-path-normalizing backslash→slash conversion then
  turned them into a similar-looking but nonexistent path (`Mobile/
  Documents`, `iCloud/~md`), silently failing every vault-dependent
  `doctor` check. The vault-folder prompt now strips shell-style
  backslash-escapes before validating/storing the path (no-op on Windows,
  where backslash is the real separator); `doctor` also now recognizes the
  old corruption pattern in an existing config and suggests the fix. 138 tests.

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
