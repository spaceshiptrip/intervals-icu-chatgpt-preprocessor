# Preprocessor handoff — read first

Updated 2026-10-06 by Preprocessor Codex. This repository owns FIT decoding, source matching, canonical workout reconstruction, normalized exports, tests, and local user review. Preprocessor Claude reviews and extends this same pipeline; do not replace it with a competing implementation. Read [README.md](README.md), [canonical model](docs/CANONICAL_WORKOUT_MODEL.md), and [shared workflow](docs/WORKFLOW.md) before editing.

## Implemented architecture

Baseline: `preprocess_fit.py`, Python 3.13, one dependency (`fitdecode==0.11.0`). Existing pair/composite matching, source-oriented exports, Garmin preference, optional detailed GPS export, stable atomic ZIP replacement and opt-in archive snapshots are preserved. Baseline tests: 25 passing before this change. Source ZIP covers 97 activities through October 5; October 6 user report is context, not measured evidence.

Minimal extension: a pure canonical module reading matched source rows plus in-memory records/timer events, producing parents, segments, relationships, field provenance, gaps/issues/review rows. Summaries switch to canonical parents. The module must never mutate source metrics or matching flags. Store user decisions separately under ignored `data/`; imports never overwrite decisions.

## Accepted decisions and boundaries

- Physical workout != source activity. Keep every recording. Count canonical parents once; children are explanatory, not additional totals.
- Garmin preferred where valid; Amazfit can supply missing physical evidence and elapsed timeline. Garmin physiology remains Garmin-specific.
- Running/source pace coverage is explicit; full reconstructed distance divided by incomplete Garmin timer is prohibited.
- Unknown != zero; unresolved totals remain blank with known/provisional subtotals and candidate extra mileage clearly separated.
- GPS stays local; routine ZIP omits raw coordinates/tracks.
- User reports are authoritative context, but do not invent measured distance/weather from the reported October 6 example.
- No paid services, deployment, bridge API changes, sheet writes or plan changes. Cross-team interface communication uses the shared parent CONTEXT.md.

## Cross-component reconciliation

Read-only inspected sibling bridge `HANDOFF.md`, `docs/WORKFLOW.md`, `docs/PREPROCESSOR_CONTRACT.md`, `docs/API_SPEC.md`, latest `docs/ASSISTANT_HANDOFF.md`. Canonical import is proposed there, not implemented. Existing bridge API remains authoritative. It cannot safely ingest regrouped records yet: no supersession, structured provenance or canonical review handling. Publish actual local schema + non-GPS sample; do not call `importActivities` or pretend the proposed bridge contract is accepted. Mixed social-walk mileage policy and split/merge lifecycle need explicit agreement. Same-input IDs/revisions are deterministic; grouping changes require downstream reconciliation before import.

## Verified local results

The canonical layer is implemented in `canonical_workouts.py`; existing source matching remains in `preprocess_fit.py`. All 57 tests pass, including stationary pauses, measured forgotten-resume repairs, half-mile gaps, splits, doubles, composite matching, dropout ambiguity, persistent resolutions, deterministic reruns, immutable source rows and provenance/privacy. A synthetic repair recovers 750 measured secondary-device meters: 2,250 Garmin meters become 3,000 canonical meters. Its incomplete Garmin pace remains labeled as recorded-portion pace; whole-workout active pace is unknown.

The current archive parses all 97 FIT files (37 Garmin, 60 Amazfit), producing 64 canonical workouts and four open review issues. October 5 running mileage is 8.412658 miles from the two Garmin segments, counted once; full physical distance remains reviewable. September 29 running mileage is 2.160936 miles. This archive has no timer events, so no accidental pause is automatically asserted or repaired on these real files. October 6 validation awaits an updated archive.

New outputs: canonical_workouts.csv, workout_segments.csv, source_relationships.csv, field_provenance.csv, reconstruction_issues.csv, reconstruction_review.csv and canonical_dataset_manifest.json. Daily/weekly totals use canonical parents. Unknown running totals remain blank with known/provisional subtotals; confirmed running distance can coexist with unknown total physical distance. Local resolutions in `data/user_resolutions.json` survive reruns and are excluded from Git and ZIP. The user's earlier October 5 Garmin-mileage instruction is represented there. See the model document for decision options and evidence thresholds.

Local schema version: `canonical-workout-1`; logical JSON schema and synthetic non-GPS example are in `docs/CANONICAL_SCHEMA.json` and `docs/examples/canonical_example.json`. Stable membership-based IDs and content revisions do not implement retirement/supersession after regrouping. The dataset manifest is a current snapshot, not a bridge import contract.

## Coordination and next actions

At session start read this handoff/specs and `/Users/jtorres/Workspaces/pnb/training_sheet/CONTEXT.md`. Read CONTEXT.md again immediately before editing it; preserve other teams' entries. Bridge Codex owns initial parent-repository setup, already completed. This team owns only this component. Commit component changes here and cross-team communication separately in the existing coordination repository, referencing the component commit.

Preprocessor Claude should review the extension and evidence thresholds. Bridge teams should review the published schema/example before agreeing on canonical transport, retirement, raw-import migration and walk/hike counting. No automatic claim of fatigue, intent, semantic segment role or corrected elevation. Validate the October 6 forgotten-resume example only when its actual FIT files arrive.
