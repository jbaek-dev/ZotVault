# PaperFlow Architecture

> Companion to `graph.json` (machine-readable map) and `AGENTS.md` (change
> protocol). The code is the source of truth; this explains the *why*.

## Data flow

```
            ┌────────────── collect ──────────────┐
 browser Connector      paperflow add / dashboard      arXiv alerts inbox
        │                       │  (user approves)            │ (user approves)
        └───────────────►  Zotero desktop (BBT citekeys) ◄────┘
                                │
                                │  zotero.sqlite — READ-ONLY temp snapshot, polled
                                ▼
                        pipeline.run_once
        ┌───────────────┬───────┴────────┬──────────────────┐
        ▼               ▼                ▼                  ▼
  note_renderer    pdf_resolver    analysis_queue      state (sqlite)
  (create-once     (zotero→cache   (pending list +     items/trace/
   vault notes)     →arXiv→Unpay-   completion          budgets/edges
                     wall→proxy)     detection)
        └───────────────┴────────┬───────┴──────────────────┘
                                 ▼
                     indexer (index.md counters, log.md append)

 daily jobs: alerts.fetch → inbox | enrich (S2 citations) | related (Ollama
 embeddings) | synthesis (clustering) → three AUTO-owned vault notes
 interface: webapp (localhost JSON API + dashboard) ← CLI ← Polaris tools
```

## Key design decisions

**Read-only toward Zotero.** Reads copy `zotero.sqlite` (+wal/journal) to a
temp dir and open read-only — safe while Zotero runs. Writes go through
Zotero's *own* connector endpoint (`/connector/saveItems`), so Zotero manages
its DB itself. Citekeys come live from Better BibTeX JSON-RPC (fallback:
`Citation Key:` in Extra). PaperFlow never touches `storage/`.

**Vault contract.** A paper note is created once and never rewritten — the
`## My Synthesis` section is structurally safe. Only three clearly-marked
AUTO notes are regenerated wholesale. `index.md` is patched via one strict
regex; `log.md` is append-only; there is no delete path; `dry_run` short-
circuits every write.

**Analysis stays external.** PaperFlow feeds an LLM workflow (queue with PDF
paths) and detects `*_analysis.md` appearing; it does not call an LLM itself.
This keeps the core engine-agnostic (Claude batch today, `claude -p`
automation tomorrow — see extension points).

**Polite networking.** Sequential fetches, per-request delays, per-day
budgets (separate stricter budget for the institutional proxy), honest
User-Agent, 429 backoff. Designed not to get a campus IP blocked.

**Zero dependencies.** Python ≥ 3.9 stdlib only: no venvs, no supply chain,
runs on the macOS CLT python. TOML parsing has a built-in fallback for 3.9.

## macOS app identity (hard-won)

The .app is a *frozen, ad-hoc-signed* launcher. macOS TCC binds privacy
grants (Full Disk Access — needed because the vault lives in an iCloud
container) to the code signature: unsigned apps can't hold grants, and
modifying a signed bundle invalidates them. Therefore:

- bundle: signed once, never modified afterwards;
- code: lives in `~/.paperflow/app/paperflow` (non-TCC path), loaded via
  `PYTHONPATH`, updated by `scripts/apply_edits.sh` (rsync + daemon restart);
- FDA: granted once to the frozen bundle, survives all code edits;
- full rebuild (`scripts/build_app.sh`) is only for icon/launcher changes and
  requires re-granting FDA (remove + re-add).

## State machine (per item)

`note_status`: pending → created | existing | dry-run | error (retried)
`pdf_status` : pending → zotero | cached | downloaded | deferred | disabled | missing
`analysis_done`: 0 → 1 when a `*_analysis.md` file appears in the citekey folder.
Zotero deletion → `deleted=1` in state, vault untouched.

The pipeline is idempotent: first run over an existing library is a quiet
backfill; repeated runs are no-ops until Zotero or the vault changes.

## Testing

`tests/` is network-free (fixtures + tmpdirs). Every new feature lands with
tests; `python3 -m unittest discover -s tests` must stay green on 3.9.
