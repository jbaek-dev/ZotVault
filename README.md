# ZotVault

**Local-first paper pipeline orchestrator between [Zotero](https://www.zotero.org/) and [Obsidian](https://obsidian.md/).**

ZotVault watches your Zotero library and, for every new paper, automatically: creates an Obsidian note, secures a PDF (open-access first, politely rate-limited), puts the paper on an AI-analysis queue, and keeps your vault's index current. Around that core loop it adds one-shot DOI/arXiv adding, paper search, a local dashboard, arXiv keyword alerts, an in-library citation graph, embedding-based related-paper suggestions, and synthesis-cluster proposals.

Everything runs on your machine. No cloud accounts required, no API keys required for the core loop, **zero runtime dependencies** (Python ≥ 3.9 standard library only).

```
[search]                       [collect]                [archive]           [wiki]
arXiv / S2 / Crossref  ──▶  dashboard / CLI / agent ──▶  Zotero (BBT)  ──▶  Obsidian vault
        ▲                        │ you approve             │ sqlite poll        │
        └── arXiv alert inbox ───┘                         ▼                    ▼
                                            daemon: note → PDF (OA→proxy) → queue → index
                                                     + citation graph · related · synthesis
```

## Features

- **One-shot add** — `zotvault add 10.1103/PhysRevB.1.1 arXiv:2405.01234`: metadata via Crossref/DataCite/arXiv → straight into Zotero through the same local channel the browser connector uses — including the OA PDF when one exists (Zotero downloads it itself, like the browser connector). Duplicates are detected before saving; a pipeline cycle runs immediately after the add. Optional [translation-server](https://github.com/zotero/translation-server) support for arbitrary URL imports.
- **Automatic wiki-fication** — new Zotero items become Obsidian notes (template-compatible, atomic writes). Existing notes are **never rewritten**; your manual sections are structurally safe.
- **Edit-safe highlight sync** — Zotero PDF highlights land in ONE marker-delimited block per note (grouped by color, deep links back to the exact annotation), kept in sync incl. deletions. Figure/area annotations are embedded as images (copied from Zotero's cache). Color groups can be renamed to *your* semantics (`label_red = "Core Claims"`). Everything outside the block is untouchable; unmarked legacy notes are opt-in (`[annotations] adopt_existing`). See [docs/MIGRATION.md](docs/MIGRATION.md).
- **PDF resolution, politely** — Zotero attachment → cache → arXiv → Unpaywall → (opt-in) institutional proxy with browser-session cookies. Sequential, delayed, daily-capped: designed to *not* get your campus blocked. See [docs/PROXY.md](docs/PROXY.md).
- **AI-analysis queue** — ZotVault doesn't run an LLM; it feeds yours. `zotvault queue --json` lists unanalyzed papers with readable PDF paths; when your agent (e.g. Claude batch) writes `*_analysis.md`, completion is auto-detected.
- **Dashboard** — `zotvault web` → http://127.0.0.1:8377 : search → tick → add, queue, alerts inbox, suggestions, audit trail. Localhost only.
- **arXiv alerts** — daily keyword digest into a review inbox. Nothing enters Zotero without your click (propose, don't execute).
- **Alert triage (assist)** — optionally, a *small* local Ollama model scores inbox candidates 0–10 for relevance under a strict JSON contract (constrained decoding + validation + one retry); the dashboard sorts by score. Advisory only, off by default.
- **Citation graph** — Semantic Scholar citation counts + who-cites-whom *within your library*, regenerated into `Citation_Graph.md`.
- **Related papers** — local [Ollama](https://ollama.com) embeddings over your analysis notes → `Related_Suggestions.md` link candidates. Free, offline.
- **Synthesis suggestions** — clusters analyzed-but-unsynthesized papers into proposed review topics.
- **Reconciliation, on your terms** — deletions are detected on both sides but never acted on silently: a vault note you deleted is marked *missing* (dashboard: Recreate / Ignore), a paper deleted from Zotero shows up as *vault-only* (Re-add / Dismiss), and dismissed papers live on a reviewable ignore list that also guards `add`.
- **Auditable** — every automatic action lands in a SQLite trace (`zotvault trace`).

## Requirements

- Python ≥ 3.9 (CLI is cross-platform; the double-click app + `install-daemon` autostart are macOS today)
- Zotero desktop with **[Better BibTeX](https://retorque.re/zotero-better-bibtex/)** — **required**: it is ZotVault's citekey source. Without it, items can't be named and nothing syncs (ZotVault will mark them `blocked` and tell you).
- An Obsidian vault (any folder). ZotVault writes per-paper notes under `<papers_subdir>/<citekey>/` — configure the paths; it does not impose a vault structure.
- Optional: `pdftotext` (poppler) for full-text AI analysis, Ollama (related papers / local analysis), an institutional web proxy for licensed PDFs.

## Quick start

```bash
pip install zotvault                   # or: pipx install zotvault / uv tool install zotvault
# (from source: git clone https://github.com/jbaek-dev/ZotVault && pip install ./ZotVault)
zotvault init                          # interactive setup: paths, email, vault scaffolding + doctor
# (--yes for the non-interactive template; add [alerts] keywords later if you want digests)
zotvault run-once --dry-run
zotvault run-once
```

**Run it continuously.** Two options on every platform:

- **System tray** (recommended): `pip install "zotvault[tray]"` then `zotvault tray` — daemon + tray icon with Open Dashboard / Run now / Pause / Quit. The only third-party packages ZotVault can use, and only if you opt in.
- **OS service:** `zotvault install-daemon` — macOS writes a launchd plist, Linux writes a systemd user unit, Windows prints the Task Scheduler command. Never auto-loads; it tells you the enable command.

macOS extra: double-click ZotVault.app (`bash scripts/build_app.sh`).

Every command also works without installing, via `python3 -m zotvault.cli <cmd>`.

## Commands

| command | what it does |
|---|---|
| `init` / `doctor` | config file / environment health check |
| `run-once [--dry-run]` / `daemon` | one cycle / poll loop (+dashboard thread) |
| `install-daemon` | autostart: launchd plist (macOS) / systemd unit (Linux) / schtasks cmd (Windows) |
| `tray` | daemon + system-tray icon (needs `pip install "zotvault[tray]"`) |
| `add <ids…> [--dry-run]` | resolve DOI/arXiv/URL → save to Zotero |
| `search <query> [--source arxiv\|s2\|crossref]` | search with in-library marks |
| `web` | dashboard server in the foreground |
| `queue [--json]` | papers awaiting AI analysis |
| `alerts [--fetch\|--approve N\|--dismiss N]` | arXiv digest inbox |
| `enrich [--limit N]` | citation graph + embeddings + suggestion notes |
| `assist [--limit N]` | score pending alerts with the small local model |
| `related <citekey>` / `synthesis [--write]` | similarity / cluster proposals |
| `status` / `trace [--limit N]` | state summary / audit trail |

## Design guarantees

- **Read-only toward Zotero's data.** Library reads use a temp snapshot of `zotero.sqlite`; adds go through Zotero's own connector endpoint (Zotero writes its DB itself). ZotVault never touches `storage/`; downloaded PDFs live in `~/.zotvault/pdfs/`.
- **Vault safety.** Existing notes are never rewritten; auto-notes (`Citation_Graph.md`, `Related_Suggestions.md`, `_Synthesis_Suggestions.md`) are clearly marked and ZotVault-owned; index.md is only patched via a strict counter regex; log.md is append-only; `--dry-run` previews; no delete code path exists.
- **Polite networking.** OA-first, sequential fetches, delays, hard daily caps (separate, stricter cap for the proxy), honest User-Agent, backs off on HTTP 429.
- **Nothing personal in code.** All user-specific values live in `~/.zotvault/config.toml`.

## Agent integration

Any agent can drive ZotVault through the localhost API (`/api/search`, `/api/add`, `/api/queue`, `/api/status`). A ready-made tool module for the Polaris local agent (not yet public) lives in that repo (`polaris/tools/zotvault_tools.py`): search results show up with in-library marks, and adding requires the user to have explicitly picked papers.

## Tests

```bash
python3 -m unittest discover -s tests -v   # 101 tests, no network needed
```

## License

MIT — see [LICENSE](LICENSE). Changelog in [CHANGELOG.md](CHANGELOG.md).
