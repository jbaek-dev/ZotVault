# PaperFlow — Agent Protocol

You are an AI tool asked to modify or extend PaperFlow. Read in this order:

1. **This file** — the rules.
2. **`graph.json`** — structure map: modules, data stores, HTTP API, invariants, extension points. Orientation only; the code is the source of truth.
3. **`docs/ARCHITECTURE.md`** — data flow and design rationale.
4. Only then read the specific source files you plan to touch.

## Change protocol (propose-first)

1. Produce a short written plan: goal, files to touch, invariants affected,
   new/changed tests, config or schema changes (state.db migrations go in
   `state._MIGRATIONS`, guarded ALTERs only).
2. **Wait for the user's approval.** Do not edit before approval, except
   single-line bugfixes explicitly requested.
3. Implement. Keep Python ≥3.9 stdlib-only. Match existing style.
4. Run `python3 -m unittest discover -s tests` — all green, add tests for new
   logic (network-free; mock/fixture based).
5. Apply to the installed app with `bash scripts/apply_edits.sh` — it rsyncs
   the source to `~/.paperflow/app` (the runtime code home) and restarts the
   daemon. NEVER modify or re-sign /Applications/PaperFlow.app: macOS binds
   the Full Disk Access grant to its frozen signature. Full
   `scripts/build_app.sh` only for icon/launcher changes (user must then
   re-grant FDA).
6. Update `graph.json` if module-level structure changed, and `CHANGELOG.md`.

## Hard invariants (violating these = automatic rejection)

- Never write to `zotero.sqlite` or Zotero `storage/`.
- Never rewrite existing paper notes; only the three AUTO notes are
  regenerated (`Citation_Graph.md`, `Related_Suggestions.md`,
  `_Synthesis_Suggestions.md`).
- No vault delete code path. `dry_run` must skip every write.
- Keep network etiquette: sequential + delayed + daily budgets; 429 backoff.
- Nothing enters Zotero without explicit user selection.
- No personal data hardcoded — config file only.
- Every automatic action appends a `trace` row.
