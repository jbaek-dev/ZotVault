# Changelog

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
