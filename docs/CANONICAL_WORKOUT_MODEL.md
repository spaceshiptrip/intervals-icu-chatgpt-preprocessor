# Canonical workout model — local schema v3

Read HANDOFF.md and the shared parent CONTEXT.md before changing this model. Jay is product owner; Web ChatGPT is Project Engineer / Domain Lead. The preprocessor team owns implementation. The 2026-10-06 accepted mileage requirements supersede the earlier running-only training-volume policy.

## Architecture and compatibility

`preprocess_fit.py` decodes FITs, preserves source metrics, and performs existing pair/composite matching. `canonical_workouts.py` consumes matched sources and local in-memory timelines, producing parents, segments, source relationships, field provenance, reconstruction issues and review questions. No reconstruction changes source rows. Daily and weekly totals count parents once; segments and comparison watches never add a second contribution.

The version is `canonical-workout-3`. Existing source CSVs, comparison files, `distance_m`, `run_distance_m`, their mile equivalents and legacy `running_miles` summary fields are retained. They have not been renamed into training totals. New additive fields distinguish training volume and modality. The logical row schema is [CANONICAL_SCHEMA.json](CANONICAL_SCHEMA.json); CSV blanks represent null, booleans are True/False, and object/array cells are JSON. Numeric CSV values use six decimal places. The [synthetic example](examples/canonical_example.json) is test data, not the actual October 6 workout.

Canonical IDs derive from sorted Intervals source identities (filename fallback). Identical membership retains its ID; changed content/policy changes its revision. Regrouping changes IDs. Scoped snapshot retirement and lineage are implemented locally; see [snapshot contract](CANONICAL_SNAPSHOT_CONTRACT.md). The bridge must implement atomic replacement, raw-import migration and revision checks before importing it. No bridge API, deployment or sheet write is included here.

## Accepted mileage semantics

All intentional distance within a training outing counts toward training mileage: running, trail, hiking, walking, warmup/workout/cooldown and movement between meaningful segments. A mixture of exercise and social interaction during that outing does not itself exclude measured movement. Modality matters for analysis, not whether intentional distance counts.

Primary weekly training mileage is confirmed intentional **foot-based** distance. Cycling is retained separately, never added to this total. Deliberate recovery walks, walking workouts and hikes count. Generic standalone walks (e.g. Lunch Walk) have unknown intent unless a persistent override or clear training name establishes it: official distance remains null, measured unclassified distance remains visible, and a review is generated. Running/hiking recordings default to intentional workouts; unrelated movement can be explicitly excluded. Ambiguous mixed/unknown source modality also needs classification.

`intentional_training` is nullable; `training_intent_status` is intentional/incidental/unclassified. `foot_training_eligible` distinguishes supported foot classification from non-foot or unknown classification. User decisions can set intentional_training and foot_training_eligible (booleans); a cycling source cannot be classified as foot training. Imported FIT sport labels are not exact gait observations. Unknown modality inside an otherwise supported foot outing counts as foot training.

| Parent field | Meaning |
|---|---|
| training_distance_m / training_distance_miles | Official confirmed intentional foot distance, including confirmed portions when the full outing is unresolved |
| training_distance_complete | Whether the full intentional distance is settled; false does not discard the confirmed portion |
| training_distance_status | confirmed, confirmed_partial, unknown, excluded, non_foot, or unclassified |
| training_distance_requires_user_review | Full training distance remains unresolved |
| candidate_training_distance_m | Candidate additional distance, excluded from official mileage; null if an unresolved amount cannot be quantified |
| provisional_training_distance_m | Confirmed plus quantified candidates, explicitly not official; null if any required amount is unknown |
| total_physical_outing_distance_m / total_physical_outing_distance_miles | Whole defensible physical outing distance; null while unresolved; retained even for an excluded incidental outing |
| running_distance_m | Confirmed source-running portions plus strongly running-supported/user-classified repairs |
| walking_distance_m / hiking_distance_m | Source-coded or user-confirmed walking/hiking portions |
| unknown_training_distance_m | Confirmed training movement whose modality is not supported |
| other_training_distance_m | Confirmed known non-running/walking/hiking sport distance, such as cycling |
| modality_basis | Classification uses FIT sport labels and explicit decisions, not a fabricated per-step gait measurement |

Running/walking/hiking/unknown foot modalities sum to confirmed foot distance when available. Other-sport/cycling measures are separate. Missing measurements remain null. Explicitly excluded intentional_training=false yields a known zero training contribution while preserving physical distance. A running-coded activity can contain hiking; its source-running estimate is not proof every step was running. There is no automatic gait split of entire sessions. New gap movement with inadequate gait evidence stays unknown training distance. Users can supply modality overrides with explicit provenance, subject to the breakdown not exceeding confirmed training distance.

Legacy `run_distance_m` can be null while unresolved running coverage remains; new `running_distance_m` retains known source-running portions. Legacy `distance_m` aliases whole physical distance and stays null for an unresolved full outing. Neither is a substitute for the new confirmed training field.

## Gap evidence and automatic reconstruction

FIT timer events remain useful but are not required. Record gaps exceed max(60 seconds, five times median source spacing). Their neutral issue label is `recording_gap`, not a claim of hardware failure or forgotten resume. Legacy device_dropout issue IDs are preserved so existing decisions still apply. Explicit timer pauses may use probable_forgotten_resume, but reconstruction proves measured missing motion rather than motive.

Secondary evidence requires actual cumulative-distance samples at both bounds within 15 seconds, >=3 points, monotonic nonnegative distance, <=30-second sample gaps and >=90% temporal coverage. No interpolation fills missing samples or distance resets. Primary distance at gap bounds must also be available. Recoverable distance is the secondary measured increment minus distance already captured by Garmin.

Automatic internal-gap repair requires all of:
- A strongly supported same-workout relationship: a high source pair/composite, active-window duplicate, or matching starts within 120 seconds and >=90% shorter-window overlap reinforced by two-sided distance alignment.
- The continuous counterpart spans the gap inside the primary recording; primary segments do not overlap and the gap is <=30 minutes.
- Two-sided alignment: measured increments in the 240-second windows before and after the gap, >=50 m in each, agreement within 15%, endpoint tolerance 20 seconds. This is timeline/distance continuity, not a claimed GPS route match.
- Missing movement >=20 m and >=10 seconds of secondary motion at >=0.5 m/s; per-sample distance speed <=8 m/s for foot sports (12 for non-foot sports). Session distance discrepancy must reconcile with the candidate (>=0.5 times missing; <=1.5 times missing plus max(100 m, 3% of baseline)).

These thresholds permit movement during stops without requiring the entire gap to be running. A running fraction >=80% based on speed >=1.5 m/s, cadence >=60 native FIT rpm and available HR >=40 supports a running-coded repair. Otherwise confirmed movement contributes to unknown training modality, without reducing training mileage.

A stationary/noise interval has secondary distance <=max(15 m, gap seconds ×0.05); add no phantom distance. The policy intentionally does not equate GPS-distance jitter with confirmed movement. Unsupported gaps outside the counterpart or agreeing sessions retain a no_supported_missing_distance issue. Sparse samples, weak alignment, implausible speeds, inconsistent total distance, or a plausible separate-workout interval remain reviewable.

Short boundaries between sequential primary segments are inside a supported continuous outing. Dense measured motion >=5 m and >=5 seconds, plausible speed and <=5-minute boundary can be included when session distances agree within max(150 m, 5%). Smaller boundaries under 50 m remain below the review threshold; observed movement can be recovered, while stationary/noise samples are not added. Larger unsupported or unsampled boundaries go to review. Measured boundary movement defaults to unknown modality unless Jay classifies it.

Total distance disagreement alone never causes repair. Candidate whole-session distance and localized gap candidates are combined conservatively using the larger amount, not added twice. All user decisions override automation. A use_preferred/stationary decision retains the preferred distance; unsure preserves the candidate.

## Pace, physiology and provenance

Distance can use Garmin valid portions plus Amazfit measured gaps; elapsed time can use the continuous timeline. Garmin HR, elevation and device-specific training effect retain their measurement source. Native session training effects across segments use a labeled maximum, not an invented sum. Elevation provenance remains unknown where correction history is unavailable.

`recorded_active_distance_m`, `recorded_active_duration_s` and `recorded_active_pace_min_mile` describe measured preferred portions using matching denominators. After repair, whole-workout timer duration and active pace remain null if the missing active denominator is unsupported. Never divide the full reconstructed distance by incomplete Garmin timer time. Elapsed pace uses full supported elapsed time/distance and may include stops. Observed stationary-duration estimates cover only analyzed samples; no fatigue or intent is inferred.

`field_provenance.csv` records source IDs, method, confidence, coverage scope and time intervals for selected/derived fields. Bounding intervals do not assert every second was measured. User-reported modality values use user provenance, not falsely attributed watch measurements. Raw lat/lon stays local; routine exports contain no GPS records. Detail export remains opt-in and is excluded from the normal ZIP.

## Persistent resolutions

The default optional input is ignored `data/user_resolutions.json`; an explicit `--resolutions PATH` must exist. Imports never overwrite it or include personal resolution files in Git/the ZIP. The ZIP includes an empty config template and the applied decisions in provenance/notes.

Issue options: include_running, include_walking, include_hiking, include_training (unknown modality), stationary_stop, use_preferred, use_secondary, separate_activity, unsure. Including a gap requires measured evidence; a decision cannot fabricate absent samples. Separate activity requires sport running/walking/hiking/cycling/other and produces its own parent counted once; separated unrelated movement is excluded by default unless the decision explicitly includes intentional_training=true. Full-source selection uses the measured source with explicit user provenance.

Workout overrides support distance_source_activity_id, numeric distance_m/run_distance_m/trail_distance_m, walking_distance_m/hiking_distance_m, non-overlapping run_distance_source_activity_ids, segment_roles, intentional_training, foot_training_eligible and note. A physical total override alone does not assert a running gait; supply supported modality values separately. Negative or inconsistent breakdowns fail validation. Session groups can link intentional splits and roles without a second watch; close time alone does not merge independent doubles. Missing historical decision IDs are reported, not deleted.

Example exclusion (replace the ID):
```json
{"schema_version":1,"issues":{},"workouts":{"CANONICAL_ID":{"intentional_training":false,"note":"Unrelated store errand"}},"session_groups":[]}
```

## Summaries and bridge mapping

Daily/weekly summaries use local start date and Monday–Sunday America/Los_Angeles weeks. Parents crossing midnight remain wholly allocated to their start date. `activity_count` is physical-parent count; `training_workout_count` excludes incidental outings; source/segment counts remain explanatory.

**Bridge weekly training volume should consume `weekly_training_summary.csv.training_miles`, or sum canonical `confirmed_training_distance_mi` once per active parent (`training_distance_miles` is the same value).** Informational modality columns are running_distance_miles, walking_distance_miles, hiking_distance_miles, unknown_training_distance_miles and other_training_distance_miles. Legacy running_miles remains source-running-only and must not populate the broader training-volume total.

`training_miles` / `confirmed_training_miles` sum confirmed portions only. They are partial if training_mileage_complete=false; unknown_training_workout_count and unresolved_training_workout_count explain the limitation. When all intentional distances are unknown, the aggregate stays null. Candidate_additional_training_miles is null if unresolved additional distance cannot be quantified; known_candidate_additional_training_miles still preserves quantified candidates. Training_miles_including_candidates is a labeled provisional value and never replaces official mileage. Candidate distances remain outside totals until evidence or user resolution confirms them.

Claude approved v3 after the summary fix reviewed by Codex. Local snapshots now carry explicit retirement mappings, but bridge atomic replacement, raw-import migration, transport/display mapping and integration verification remain unimplemented. Its current API is unchanged; do not import the snapshot into an additive upsert store. Bridge teams must not reproduce upstream reconstruction.

## Measured validation and remaining limits

The original validation archive had 97 files through October 5; fresh Intervals FIT/CSV inputs now each contain 116 activities from August 11 through October 6. Final counts are recorded in HANDOFF.md and coverage_report.json. The v2 run confirms October 5 Garmin distance 13,538.86 m plus 321.17 m measured secondary movement (287.45 m main gap, 26.28 m smaller gap, 7.44 m split boundary): **13,860.03 m / 8.612223 training miles**. Source-running remains **8.412658 miles**; the 321.17 m is unknown modality, not automatically walking or running. This hybrid estimate is about 21 m above Amazfit's 13,839 m full-source total, within measurement tolerance, and explicitly retains its reconstruction method. Stationary/noise intervals are not added.

The accepted Aug 26 decision retains Garmin's complete 10,729.67 m; Sep 18 retains known segments without inventing an unsampled boundary distance. Sep 7 remains unresolved: measured 618.13 m has dense movement evidence but failed two-sided alignment. Confirmed 21,829.12 m = 13.563986 mi stays official; hybrid candidate 22,447.25 m = 13.948074 mi is provisional, differing from PE's prior approximate 13.93 mi. That evidence delta is reported rather than silently overriding it. There are also 22 standalone walks with unconfirmed intent, preserved as 22.368742 unclassified miles. October 6 is now validated from real FITs: Garmin 3,953.75 m plus a measured 501.28 m deficit (502.63 secondary meters minus 1.35 primary meters already captured) gives **4,455.03 m / 2.768227 training miles**. The 226-second interval has dense samples, two-sided alignment and 94.25% running-evidence fraction. Garmin original FIT independently records the matching stop/restart bounds. Ama full distance is 4,466 m, about 11 m above the hybrid reconstruction. Recorded Garmin pace/HR retain their sources; the whole running-coded session does not prove where hiking occurred.

The synthetic example demonstrates a 750 m recovered running gap (2,250→3,000 m), independently sourced pace/HR/elevation, and no GPS exposure. Additional tests cover no timer events, unknown modality, walking/hiking volume, stationary gaps, partial confirmed totals, exclusion, inconsistent totals, sparse coverage, candidate double-count prevention, deterministic reruns and schema compatibility.

## v3 bridge fields and additional review output

`confirmed_training_distance_mi` is the designated bridge primary field and equals training_distance_miles. Cycling_distance_m and cycling_duration_s retain separate cycling measurements. Unclassified_training_distance_m represents quantified movement not eligible for official foot totals until intent/classification is confirmed; it is not a gait claim and not a zero contribution measurement. Summary training_mileage_complete=false includes pending intent. Training_workout_count counts supported foot outings only. Cycling-only days have known zero foot contribution; days with only ambiguous walks have unknown official foot mileage. Foot mileage on a day with both confirmed runs and pending walks keeps its confirmed subtotal.

See CANONICAL_SNAPSHOT_CONTRACT.md for replacement scope, retirement, dates and importer acceptance criteria. The routine ZIP excludes internal review requests/drafts, raw coordinates/FITs and personal resolutions. Coverage input paths are basename-only in the upload report; local CLI inventory can retain exact paths for operations.

## Temporary historical-backlog policy — 2026-10-07

Jay/PE accepted all currently detected foot walks, including autodetected walks, for MVP. Existing workout resolutions set intentional_training=true for exactly the 22 historical canonical IDs, with summary notes identifying a temporary historical counting policy rather than a measured intent assertion. Field provenance remains user-owned context; original FIT/source walking classification is preserved. Imports read but never overwrite resolutions. New generic walks remain unclassified unless later confirmed; this policy does not permanently change default ingestion. Regrouped IDs require resolution migration if applicable, with unmatched IDs surfaced.

The latest official total is 242.375228 mi; Sep21 week is 6.193207 mi. All 22 historical intent reviews are resolved. Sep7 keeps confirmed 13.563986 mi plus 618.13 m (~0.384088 mi) provisional, and is explicitly non-blocking for schema/integration work. 107 tests pass. This policy uses the reviewed existing resolution mechanism; no schema or reconstruction algorithm changes are required. The earlier backlog counts/null walk-only examples document the stricter-policy validation, not the current MVP export.

## Existing moving-duration field — v1 repair pending review

moving_duration_s is independent of the timer/active pace denominator and may be sourced from a complete continuous recording after an accepted physical repair. Explicit FIT moving-time or Intervals CSV Moving Time metadata is preferred; full covered record bins are a labeled fallback. Never subtract the old analyzed-gap stationary estimate from timer time: it can include already-paused seconds. Unknown whole-outing coverage remains null. [MOVING_DURATION.md](MOVING_DURATION.md) defines selection, pause accounting, alternative canonical clocks, provenance and bounds. Calculation occurs before revision hashing; IDs/mileage/pace rules and schema version are unchanged. This fix awaits independent Claude review.
