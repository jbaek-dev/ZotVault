# PaperFlow

**Local-first paper pipeline orchestrator between [Zotero](https://www.zotero.org/) and [Obsidian](https://obsidian.md/).**

PaperFlow watches your Zotero library and, for every new paper, automatically: creates an Obsidian note (Papers_Zotero_v3-compatible), secures a PDF (open-access sources first, politely rate-limited), puts the paper on an AI-analysis queue, and keeps your vault's index/log current. The AI analysis itself is produced by your own agent workflow (e.g. Claude batch runs) — PaperFlow supplies the queue and detects completion.

Everything runs on your machine. No cloud accounts, no API keys required for the core loop. Zero runtime dependencies (Python ≥ 3.9 standard library only).

```
[search]                    [collect]              [archive]            [wiki]
arXiv / journals  ──▶  browser / DOI / CLI  ──▶  Zotero (BBT)  ──▶  Obsidian vault
                                                     │ sqlite poll         │
                                                     ▼                     ▼
                                              PaperFlow daemon:  note → PDF → queue → index
```

## Status

M1 (core loop) — working. Roadmap: M2 programmatic DOI add via local translation-server + web dashboard, M3 institutional-proxy PDF fallback, M4 citation graph / related-paper suggestions / arXiv alerts / synthesis proposals, M5 open-source polish.

## Requirements

- macOS (launchd integration; the CLI itself is OS-agnostic)
- Python ≥ 3.9 (no packages needed)
- Zotero desktop with [Better BibTeX](https://retorque.re/zotero-better-bibtex/) (citekey source, queried via its local JSON-RPC)
- An Obsidian vault where paper notes live under `<vault>/30_Resources/Papers/zotero/<citekey>/` (configurable)

## Quick start

```bash
git clone <this repo> && cd PaperFlow
python3 -m paperflow.cli init          # writes ~/.paperflow/config.toml
# edit ~/.paperflow/config.toml: [vault] dir, [pdf] unpaywall_email
python3 -m paperflow.cli doctor        # health check
python3 -m paperflow.cli run-once --dry-run
python3 -m paperflow.cli run-once
python3 -m paperflow.cli install-daemon   # writes launchd plist, prints launchctl commands
```

(Or `pip3 install -e .` and use the `paperflow` command directly.)

## Commands

| command | what it does |
|---|---|
| `init` | create `~/.paperflow/config.toml` |
| `doctor` | check Zotero, Better BibTeX, vault paths, permissions |
| `run-once [--dry-run]` | one pipeline cycle |
| `daemon` | poll loop in the foreground |
| `install-daemon` | write the launchd plist (never auto-loads it) |
| `queue [--json]` | papers still awaiting AI analysis, with PDF paths |
| `status` | tracked items, note/PDF states, download budget |
| `trace [--limit N]` | audit trail of every automatic action |

## Design guarantees

- **Read-only toward Zotero.** The library is read from a temp snapshot of `zotero.sqlite`; PaperFlow never writes to Zotero's DB or `storage/`. Downloaded PDFs go to `~/.paperflow/pdfs/`.
- **Vault safety.** Existing notes are never rewritten (your `## My Synthesis` sections are untouchable), index.md is only patched via a strict counter regex, log.md is append-only, `--dry-run` previews everything, and there is no delete code path at all.
- **Polite downloading.** OA sources first (arXiv, Unpaywall), sequential fetches with a delay, hard daily limit, honest User-Agent. Bulk-scraping publishers gets universities blocked; PaperFlow is deliberately slow.
- **Auditable.** Every action lands in the `trace` table (`paperflow trace`).
- **Nothing personal in code.** All user-specific values (paths, email, proxy) live in the config file.

## First run on an existing library

The pipeline is idempotent: notes that already exist are skipped, PDFs already in Zotero are recognized, analyses already written are detected. The first run over a populated library is a quiet backfill that registers everything in local state (`~/.paperflow/state.db`) without touching your vault.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
