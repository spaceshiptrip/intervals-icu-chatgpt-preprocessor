# Proposed coordination entry — v3, not finalized

Do not publish as VERIFIED until Claude completes the actual implementation review. Bridge Codex owns CONTEXT.md commits. Keep the existing v2 entry/history.

## 2026-10-06 — Preprocessor team: accepted intentional foot mileage and snapshot retirement
Status: IMPLEMENTED locally; Claude review pending
Component: Preprocessor → Bridge; local canonical-workout-3
Commit: fill after component commit and Claude review

Accepted Jay/PE policy: primary training miles are intentional foot distance including running, hiking, recovery walks and in-outing foot movement. Cycling is separate. Generic standalone walks with unclear intent remain measured/unclassified and outside official totals until confirmed. Unknown is null; confirmed partial mileage remains official.

Designated bridge field: canonical_workouts.csv.confirmed_training_distance_mi (same as training_distance_miles); summaries training_miles. Cycling_distance_m/cycling_duration_s and cycling_miles/cycling_duration_s are separate cross-training. Running/walking/hiking/unknown foot modalities are informational. Candidate gaps and unclassified_training_distance_m are separate from confirmed totals. Preserve completeness/review/provenance flags.

Version 3 explicitly changes v2 primary mileage semantics; legacy source comparisons/running-only fields remain. Generic-walk intent is nullable and reviewable. Scope replacement manifest now retains retired IDs/source keys/replacement lineage and historical affected dates. Unchanged grouping keeps IDs; changed grouping retires obsolete identities. Bridge must atomically replace its canonical actuals scope and recompute days/weeks, with raw-import migration and stale revision safety, preserving separately owned plans/user fields. Local snapshots are not additive upsert payloads. Bridge application is not implemented/verified: canonical import remains blocked.

Non-GPS example: Oct 6 confirmed_training_distance_mi=2.768227; recovered_distance_m=501.28; foot_training_eligible=true; training_distance_complete=true; sources/provenance retained. Oct 5 remains 8.612223 confirmed foot miles.

Accepted Aug 26/Sep 18 choices retain preferred complete/known segments. Sep 7 delta: measured 618.13 m gap is dense but current alignment fails; 13.563986 mi confirmed, 13.948074 mi hybrid candidate, rather than automatically accepting prior approximate 13.93. Ask PE/Jay to reconcile this evidence before confirming the addition. Twenty-two walks also need intent context.

Current measured results: 116 sources, 78 parents, 23 reviews, 106 tests; all require final review/readback of results before this entry becomes VERIFIED. Detailed operational Docker mechanics remain in repo docs. Valhalla remains deferred. No bridge code or Sheets action.
