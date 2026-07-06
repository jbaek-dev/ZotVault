# Changelog

## 0.5.0 — 2026-07-05 (M2–M5)

### M2 — collect
- One-shot add: `paperflow add <doi|arxiv|url>` — Crossref/DataCite/arXiv
  native resolvers → Zotero `/connector/saveItems` (the browser-connector
  channel). Optional translation-server for arbitrary URL imports.
- Duplicate detection against local state (DOI / arXiv id).
- Paper search (`paperflow search`, dashboard): arXiv, Semantic Scholar,
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
- Polaris agent bridge (`polaris/tools/paperflow_tools.py` in the Polaris
  repo): status / queue / search / add via the PaperFlow HTTP API.
- Docs, 47+ unit tests, zero runtime dependencies (Python ≥ 3.9 stdlib).

## 0.1.0 — 2026-07-04 (M1)
- Core loop: Zotero sqlite-snapshot polling → Papers_Zotero_v3-compatible
  note creation (existing notes never rewritten) → OA-first PDF resolution
  (arXiv, Unpaywall; daily limit + delays) → analysis queue with completion
  detection → conservative index.md counter patch + append-only log.md.
- Better BibTeX JSON-RPC citekey resolution (+ Extra-field fallback).
- CLI (init/doctor/run-once/daemon/queue/status/trace), launchd integration,
  SQLite state + full audit trace.
