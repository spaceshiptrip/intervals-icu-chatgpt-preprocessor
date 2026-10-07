# Finalized coordination entry — reviewed v3

Claude review and Codex review of the summary fix are complete. Bridge Codex should append the entry below to CONTEXT.md, preserving the existing v2 entry/history, and commit it in the coordination repository. The implementation and reviewed summary-fix commits are recorded below.

## 2026-10-07 — Preprocessor team: accepted intentional foot mileage and snapshot retirement
Status: VERIFIED locally; Preprocessor Claude review COMPLETE; summary fix reviewed by Codex
Component: Preprocessor → Bridge; local canonical-workout-3
Commit: 1445172 + b497e15d4b8848cd791c50d58f8494a2088feec0; review in preprocessor HANDOFF.md "Preprocessor Claude review — 1445172"

Accepted Jay/PE policy: primary training miles are intentional foot distance including running, hiking, recovery walks and in-outing foot movement. Cycling is separate. Generic standalone walks with unclear intent remain measured/unclassified and outside official totals until confirmed. Unknown is null; confirmed partial mileage remains official.

Designated bridge field: canonical_workouts.csv.confirmed_training_distance_mi (same as training_distance_miles); summaries training_miles. cycling_distance_m/cycling_duration_s and cycling_miles/cycling_duration_s are separate cross-training. Running/walking/hiking/unknown foot modalities are informational and sum to confirmed training_miles. A day/week with only unclassified walks has training_miles=null (pending), not 0. Candidate gaps and unclassified_training_distance_m are separate from confirmed totals. Preserve completeness/review/provenance flags.

Version 3 explicitly changes v2 primary mileage semantics; legacy source comparisons/running-only fields remain. Generic-walk intent is nullable and reviewable. Scope replacement manifest now retains retired IDs/source keys/replacement lineage and historical affected dates. Unchanged grouping keeps IDs; changed grouping retires obsolete identities. Bridge must atomically replace its canonical actuals scope and recompute days/weeks, with raw-import migration and stale revision safety, preserving separately owned plans/user fields. Local snapshots are not additive upsert payloads. Bridge application is not implemented/verified: canonical import remains blocked.

Non-GPS example: Oct 6 confirmed_training_distance_mi=2.768227; recovered_distance_m=501.28; foot_training_eligible=true; training_distance_complete=true; sources/provenance retained. Oct 5 remains 8.612223 confirmed foot miles.

Accepted Aug 26/Sep 18 choices retain preferred complete/known segments. Sep 7 delta: measured 618.13 m gap is dense but current alignment fails; 13.563986 mi confirmed, 13.948074 mi hybrid candidate, rather than automatically accepting prior approximate 13.93. Ask PE/Jay to reconcile this evidence before confirming the addition. Twenty-two walks also need intent context.

Verified results: 116 sources, 78 active parents, 0 retired in this unchanged real snapshot, 23 reviews and 106 passing tests. Modality breakdowns reconcile to confirmed training_miles in all eight known weeks and 34 known days; the walk-only Sep 21 week and six walk-only days stay null/pending. Canonical rows, snapshot manifest and input files are byte-identical after the summary fix/rebuild. Detailed operational Docker mechanics remain in repo docs. Valhalla remains deferred. No bridge code or Sheets action.

Bridge action: review this finalized local v3 contract and reconcile transport, atomic scope replacement/retirement, raw-import migration and revision safety before implementing imports. Display unknown primary mileage as pending, preserve confirmed partial mileage and separate candidate/unclassified amounts, and never add cycling to primary training miles. Do not interpret this review as live bridge verification or production authorization.
