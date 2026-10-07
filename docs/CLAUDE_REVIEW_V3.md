# Preprocessor Claude review request — accepted foot mileage policy

Read HANDOFF.md, latest parent CONTEXT.md, CANONICAL_WORKOUT_MODEL.md and CANONICAL_SNAPSHOT_CONTRACT.md. This extends c99e7ff under Jay/PE's accepted foot-only policy; no competing pipeline.

Review the actual diff and run `.venv/bin/python -m unittest discover -s tests -v` (106 tests). Independently rebuild with the data/ FIT ZIP, activities CSV and reviewed device map. No push, deployment or Sheet writes.

Check:
- Cycling contributes zero primary foot miles while retaining cycling distance/time and physiology.
- Clearly intentional recovery walks and user-confirmed standalone walks count. Generic walks retain measured unclassified distance, null intent/official distance and review. Mixed/unknown classification remains conservative.
- Explicit foot movement within an intentional run outing counts regardless of gait. No new distance is fabricated; partial timer pace stays scoped.
- Daily/weekly official totals use confirmed_training_distance_mi/training_miles; known amounts survive pending gaps/intent, null does not become zero.
- Resolutions are read-only during import. Codex added the two accepted Aug 26/Sep 18 decisions to the ignored local resolution file; original Oct 5 decision preserved. Sep 7 remains provisional because alignment fails; inspect the reported delta rather than assume the prior PE distance.
- Source rows remain unchanged; tests and fresh reruns retain Oct 5 8.612223 and Oct 6 2.768227 miles with 501.28 m repair.
- Snapshot scope replacement, persistent retirement ledger, stable source keys, source shrink guard, old/new-date recomputation and idempotency. Bridge apply is not implemented: do not mark import safe.
- 8 m/s foot plausibility threshold preserves Oct 6 (observed max 7.21); faster samples remain reviewable.
- Upload coverage paths are basenames; internal review/draft docs stay out of ZIP; no raw FIT/GPS/personal resolutions.

Expected real export: 116 source activities; 78 canonical workouts; 23 reviews (22 generic standalone walks, Sep 7). Confirmed foot total ~220.006487 mi; unclassified walks ~22.368742 mi; cycling ~25.365615 mi. These totals do not assert the walks are incidental: Jay may confirm them as training later.

Fix defects as needed, rerun tests, update HANDOFF with review and findings. Codex reviews fixes. After approval, prepare the exact shared-interface handoff for Bridge Codex to commit; no unreviewed schema should be advertised as finalized.
