# PaperFlow

**Local-first paper pipeline orchestrator between [Zotero](https://www.zotero.org/) and [Obsidian](https://obsidian.md/).**

PaperFlow watches your Zotero library and, for every new paper, automatically: creates an Obsidian note, secures a PDF (open-access first, politely rate-limited), puts the paper on an AI-analysis queue, and keeps your vault's index current. Around that core loop it adds one-shot DOI/arXiv adding, paper search, a local dashboard, arXiv keyword alerts, an in-library citation graph, embedding-based related-paper suggestions, and synthesis-cluster proposals.

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

- **One-shot add** — `paperflow add 10.1103/PhysRevB.1.1 arXiv:2405.01234`: metadata via Crossref/DataCite/arXiv → straight into Zotero through the same local channel the browser connector uses. Duplicates are detected before saving. Optional [translation-server](https://github.com/zotero/translation-server) support for arbitrary URL imports.
- **Automatic wiki-fication** — new Zotero items become Obsidian notes (template-compatible, atomic writes). Existing notes are **never rewritten**; your manual sections are structurally safe.
- **PDF resolution, politely** — Zotero attachment → cache → arXiv → Unpaywall → (opt-in) institutional proxy with browser-session cookies. Sequential, delayed, daily-capped: designed to *not* get your campus blocked. See [docs/PROXY.md](docs/PROXY.md).
- **AI-analysis queue** — PaperFlow doesn't run an LLM; it feeds yours. `paperflow queue --json` lists unanalyzed papers with readable PDF paths; when your agent (e.g. Claude batch) writes `*_analysis.md`, completion is auto-detected.
- **Dashboard** — `paperflow web` → http://127.0.0.1:8377 : search → tick → add, queue, alerts inbox, suggestions, audit trail. Localhost only.
- **arXiv alerts** — daily keyword digest into a review inbox. Nothing enters Zotero without your click (propose, don't execute).
- **Citation graph** — Semantic Scholar citation counts + who-cites-whom *within your library*, regenerated into `Citation_Graph.md`.
- **Related papers** — local [Ollama](https://ollama.com) embeddings over your analysis notes → `Related_Suggestions.md` link candidates. Free, offline.
- **Synthesis suggestions** — clusters analyzed-but-unsynthesized papers into proposed review topics.
- **Auditable** — every automatic action lands in a SQLite trace (`paperflow trace`).

## Requirements

- macOS (launchd integration; CLI itself is OS-agnostic), Python ≥ 3.9
- Zotero desktop with [Better BibTeX](https://retorque.re/zotero-better-bibtex/) (citekey source)
- An Obsidian vault with per-paper folders (`<papers_subdir>/<citekey>/`)
- Optional: Ollama (related papers), UIC-style web proxy access (licensed PDFs)

## Quick start

```bash
git clone <this repo> && cd PaperFlow
python3 -m paperflow.cli init            # writes ~/.paperflow/config.toml
# edit: [vault] dir, [pdf] unpaywall_email  (+ [alerts] keywords if you want digests)
python3 -m paperflow.cli doctor
python3 -m paperflow.cli run-once --dry-run
python3 -m paperflow.cli run-once
python3 -m paperflow.cli install-daemon  # launchd plist; load it when ready
```

## Commands

| command | what it does |
|---|---|
| `init` / `doctor` | config file / environment health check |
| `run-once [--dry-run]` / `daemon` | one cycle / poll loop (+dashboard thread) |
| `install-daemon` | write launchd plist (never auto-loads) |
| `add <ids…> [--dry-run]` | resolve DOI/arXiv/URL → save to Zotero |
| `search <query> [--source arxiv\|s2\|crossref]` | search with in-library marks |
| `web` | dashboard server in the foreground |
| `queue [--json]` | papers awaiting AI analysis |
| `alerts [--fetch\|--approve N\|--dismiss N]` | arXiv digest inbox |
| `enrich [--limit N]` | citation graph + embeddings + suggestion notes |
| `related <citekey>` / `synthesis [--write]` | similarity / cluster proposals |
| `status` / `trace [--limit N]` | state summary / audit trail |

## Design guarantees

- **Read-only toward Zotero's data.** Library reads use a temp snapshot of `zotero.sqlite`; adds go through Zotero's own connector endpoint (Zotero writes its DB itself). PaperFlow never touches `storage/`; downloaded PDFs live in `~/.paperflow/pdfs/`.
- **Vault safety.** Existing notes are never rewritten; auto-notes (`Citation_Graph.md`, `Related_Suggestions.md`, `_Synthesis_Suggestions.md`) are clearly marked and PaperFlow-owned; index.md is only patched via a strict counter regex; log.md is append-only; `--dry-run` previews; no delete code path exists.
- **Polite networking.** OA-first, sequential fetches, delays, hard daily caps (separate, stricter cap for the proxy), honest User-Agent, backs off on HTTP 429.
- **Nothing personal in code.** All user-specific values live in `~/.paperflow/config.toml`.

## Agent integration

Any agent can drive PaperFlow through the localhost API (`/api/search`, `/api/add`, `/api/queue`, `/api/status`). A ready-made tool module for the [Polaris](https://github.com/) local agent lives in the Polaris repo (`polaris/tools/paperflow_tools.py`): search results show up with in-library marks, and adding requires the user to have explicitly picked papers.

## Tests

```bash
python3 -m unittest discover -s tests -v   # 47 tests, no network needed
```

## License

MIT — see [LICENSE](LICENSE). Changelog in [CHANGELOG.md](CHANGELOG.md).
