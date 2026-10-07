# Preprocessor Claude review request — training mileage v2 and source refresh

Read repository HANDOFF.md, docs/CANONICAL_WORKOUT_MODEL.md, docs/GARMIN_FIT_RETRIEVAL.md and the parent CONTEXT.md first. Review the committed Codex extension against Jay/Project Engineer's accepted 2026-10-06 mileage semantics. This is the existing pipeline; do not design a competing one or change bridge code/sheets.

Review:
- All intentional outing movement contributes to confirmed training volume regardless of modality; unrelated incidental outings can be explicitly excluded.
- Official training_distance_m/miles and daily/weekly training_miles retain confirmed portions. Candidate additions remain separate; null stays unknown. Modality breakdowns remain source-supported/user-confirmed rather than invented gait measurements.
- Broad training_miles currently includes all intentional source sports, including cycling under other_training_distance_m; examine this explicitly against the “ALL intentional distance” wording. Running-only/cycling columns remain available.
- Strong aligned record gaps can repair distance without timer events; stationary/noisy/sparse/implausible/inconsistent gaps cannot fabricate mileage. Review threshold combinations and unchanged-ID migration for recording_gap labels.
- Source rows are unchanged; duplicate/composite/active-window grouping counts parents once. Full repaired distance never divides by incomplete Garmin timer. Provenance/revisions remain deterministic.
- Source coverage reflects activity times, exact paths/hashes, missing IDs and limited native history. InfluxDB CSV exports are indices, not raw FIT detail. Current primary details remain Intervals FITs; native Garmin is not counted again.
- Retrieval wrapper checks config/mount/dates, hides credentials, reports decoded FIT timestamps and fails clearly. It uses the existing Garmin service, rather than a parallel downloader. Do not trigger a broad historical fetch as part of review.
- ZIP contains new code/docs/coverage outputs, no raw FITs, GPS records or personal resolution input.

Run `.venv/bin/python -m unittest discover -s tests -v` (82 tests expected). Inspect the rebuilt source/parent/provenance/review CSVs, especially:
- October 5: training 13,860.03 m / 8.612223 mi; source-running 13,538.86 m / 8.412658 mi; extra 321.17 m unknown modality (287.45 + 26.28 + 7.44), counted once.
- October 6: Garmin 3,953.75 m + (Amazfit gap 502.63 m − primary captured 1.35 m) = 4,455.03 m / 2.768227 mi. Native timer events independently confirm 20:35:36–20:39:22 UTC. Full session sport does not determine exact hike portions.
- Fresh FIT/CSV each have 116 activities covering Aug 11–Oct 6; maps identify 42 Garmin/74 Amazfit; 78 canonical parents; three unresolved cases (Aug 26, Sep 7, Sep 18).
- Native Garmin filestore has one Oct 6 FIT, not historical completeness; older two-activity indices still end Oct 5. Reports distinguish these facts.

Make clear fixes with regression tests, update docs/HANDOFF and commit if permitted; otherwise leave exact changes for Codex. Review does not authorize semantic changes beyond accepted requirements. Report findings, tests and unresolved questions.

After review, finalize the exact cross-team interface entry prepared in docs/CONTEXT_HANDOFF_PENDING_REVIEW.md. Reread parent CONTEXT.md immediately before appending; preserve other entries and commit separately. Include implementation/review hashes. Do not claim canonical bridge import is safe: regrouping can change IDs and retirement/transport remain unimplemented. Docker mechanics belong in local retrieval docs, not CONTEXT.md. Do not push or write sheets.
