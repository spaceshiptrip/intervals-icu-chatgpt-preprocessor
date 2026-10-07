# Proposed exact coordination entry — append only after Claude review

This is a draft, not an entry already added to shared CONTEXT.md. Replace commit placeholders and reconcile any review fixes. Detailed Docker operations remain in GARMIN_FIT_RETRIEVAL.md.

## 2026-10-06 — Preprocessor team: intentional training mileage and canonical v2
Status: VERIFIED locally; cross-review COMPLETE only when documented by Preprocessor Claude
Component: Preprocessor → Bridge canonical training interface
Schema: canonical-workout-2 (local file contract; bridge transport still to be agreed)
Preprocessor implementation commit: <CODEX_COMMIT>
Preprocessor review/fix commit: <CLAUDE_COMMIT_OR_REVIEW_REFERENCE>

Accepted semantics from Jay / Project Engineer: all intentional distance within a training outing counts toward training volume, including running, trail, hiking, walking, warmup/workout/cooldown and in-outing segment transitions. Modality is analytical, not a mileage exclusion. Unrelated incidental movement is excluded through persistent user context.

Consume canonical_workouts.csv.training_distance_miles once per current canonical parent, or daily/weekly_training_summary.csv.training_miles. These represent confirmed intentional distance, including confirmed partial portions. Informational running_distance_m, walking_distance_m, hiking_distance_m, unknown_training_distance_m and other_training_distance_m preserve modality; source sport is not an exact per-step gait split. The broad aggregate includes intentional non-foot sports under other_training_distance_m, with running/cycling-specific columns retained.

training_distance_complete / training_mileage_complete indicate completeness. Candidate_training_distance_m / candidate_additional_training_miles are additional unconfirmed amounts excluded from official totals; provisional_training_distance_m / training_miles_including_candidates are explicitly labeled estimates. Unknown amounts remain null; confirmed mileage is never discarded because an additional portion remains unresolved. Total_physical_outing_distance_m is whole outing distance if defensible. Intentional_training=false preserves incidental source/physical data with zero official training contribution.

Gap repair no longer requires timer_pause events: dense monotonic measured secondary increments, measured primary bounds, same-outing temporal support, two-sided distance alignment, motion plausibility and session reconciliation can confirm missing movement. Ambiguous modality remains unknown training rather than being omitted. No distance is interpolated or repaired from total disagreement alone. Full repaired distance is never paired with incomplete Garmin timer pace; provenance retains sources, coverage, methods/confidence and user choices. GPS stays local.

Backward compatibility: existing source/pair/composite outputs and legacy running-only fields remain. Running_miles must not be silently mapped to broader weekly training volume. Canonical_workouts, field_provenance, reconstruction_issues/review and daily/weekly summaries have additive v2 fields/semantics; source_inventory.csv and coverage_report.json document actual input/coverage. Reviewed logical schema and non-GPS example are in docs/CANONICAL_SCHEMA.json / docs/examples/canonical_example.json.

Tiny real non-GPS example:
{"schema_version":"canonical-workout-2","canonical_workout_id":"cw_93bae90b6e71dc3836fd","local_date":"2026-10-06","training_distance_m":4455.03,"training_distance_miles":2.768227,"training_distance_complete":true,"running_distance_m":4455.03,"walking_distance_m":0,"hiking_distance_m":0,"unknown_training_distance_m":0,"recovered_distance_m":501.28,"canonical_status":"reconstructed","requires_user_review":false,"modality_basis":"source sport and supported gap evidence; not a per-step gait claim"}

October 5 now has 8.612223 confirmed training miles, 8.412658 source-running miles and 321.17 m unknown training modality. October 6 recovers 501.28 m from real FIT evidence; independently retained native Garmin timer events confirm the gap. Fresh Intervals FIT/CSV coverage is Aug 11–Oct 6, 116 activities each; native retained history is current but incomplete. Local verification: 82 passing tests, 78 canonical parents and three unresolved cases. Applied user decisions persist locally without input overwrite.

IDs are deterministic for unchanged membership. Regrouping changes IDs; retirement/supersession and raw-import transition are NOT implemented. The manifest remains a current snapshot, not a retirement API. Canonical import is NOT safe to begin in the current bridge upsert store. No bridge code, live sheet, plans or notes were changed.

Bridge action: agree versioned transport and explicit training-volume field/display mapping; preserve completeness/candidate/provenance, implement retirement and raw-import migration before imports. Do not recreate upstream gap logic. Project Engineer/Jay review any remaining semantic disagreements. Detailed retrieval/refresh commands are repo-local, linked from HANDOFF.md.
