# Canonical workout model — local schema v1

## Extension and compatibility decisions (recorded before implementation)

Keep the existing parser, pair/composite matcher and all source CSVs. Add `canonical_workouts.py`, consuming sources + matched relationships + in-memory timelines/events. It returns canonical parents, meaningful segments, source relationships, field provenance and review issues. No source values/flags are rewritten by reconstruction. Existing source counting flags describe the earlier preferred-source view; new summaries use canonical parents only. Preserve an explicit legacy source-summary helper for code compatibility, not as the authoritative training total.

The schema version is `canonical-workout-1`. This is a local file contract, not `pp-bridge-1`, not a deployed bridge contract. Canonical IDs use sorted stable Intervals IDs (fallback filename) so re-encoding the same activity changes the content revision but not counting identity. Changing group membership changes the parent identity. There is no false promise that a new canonical ID retires an old imported ID: bridge import remains blocked pending explicit supersession/reconciliation. A dataset manifest records current membership/revision.

Conservative reconstruction: preserve measured preferred-source distance for resolved duplicate/composite cases. Distance disagreement alone creates review, not repair. Repair requires actual continuous cumulative-distance records, dense sampling, aligned valid portions on both sides, an explicit Garmin timer pause or contextual confirmation, and sustained secondary motion with cadence/speed evidence. Sparse data, reset distances, weak alignment, device dropout or ambiguous walking remain reviewable. Never fill distance by interpolation over absent records. Record-gap detection is not proof of a timer pause.

Run/trail portions preserve their FIT sport identity; inferred warmup/workout/cooldown roles require explicit names or user decisions. Close time alone is insufficient to merge independent runs. A shared continuous counterpart or explicit session resolution permits grouped segments. Walking/social movement is physical distance but is not silently added to running mileage. Source-coded hiking inside a run remains documented as source classification pending bridge-team policy; ambiguous gap walking prompts review.

Whole-workout elapsed time may come from the continuous source. Garmin timer/HR/elevation/training effect remain supported by their measured portions; independent pace stores its own covered distance/time. Do not divide full reconstructed distance by partial timer. Genuine whole-workout active pace is blank when coverage is incomplete. Actual stationary evidence supports an estimated stopped duration, not a fatigue conclusion.

Unresolved canonical distance/run distance is blank. Preserve `provisional_distance_m`, provisional run mileage and candidate additional mileage separately. Daily/weekly `running_miles` is blank if any running contribution is unresolved; known/resolved and provisional subtotals are explicit. No ambiguous workout is silently counted twice. Review can be deterministic JSON input, rather than an interactive session. Imports never overwrite that local file.

Detailed schemas, resolution examples, measured validation and limits will be appended after implementation. October 6 reported weather/hydration/forgotten resume is context only; the supplied archive currently ends October 5.

## Implemented output contract

Logical row schema: [CANONICAL_SCHEMA.json](CANONICAL_SCHEMA.json). Non-GPS synthetic example with provenance: [examples/canonical_example.json](examples/canonical_example.json). The JSON schema describes typed logical rows; the routine data file is CSV: blanks are null, booleans are `True`/`False`, array/object cells are JSON, and numeric output is rounded to six decimal places. The example is explicitly synthetic, not the measured October 6 run.

| File | Entity / counting rule |
|---|---|
| activities_master.csv | Immutable source metrics plus existing source-matcher annotations; these flags are not canonical training totals |
| canonical_workouts.csv | One counting parent per resolved physical workout/session, or one provisional parent for an ambiguous overlap |
| workout_segments.csv | Source segments and recovered gap segments, with parent/session ID, role, role evidence, timestamps and distance; never counted separately |
| source_relationships.csv | Links sources to parents; a user-separated gap can reuse a continuous source over a different interval |
| field_provenance.csv | Selected/derived measurement, value/unit, source IDs, method, confidence, coverage scope and time bounds |
| reconstruction_issues.csv | All detected gaps/disagreements, including automatically handled or user-resolved cases |
| reconstruction_review.csv | Only cases still requiring context, with stable issue ID, candidate evidence and question |
| canonical_dataset_manifest.json | Deterministic dataset revision, active parent identities/revisions and source memberships; snapshot, not a retirement API |

Core parent fields:
- `distance_m` / `distance_miles`: physical outing distance, null when unresolved.
- `run_distance_m` / `run_distance_miles`: mileage counted as training running; separate from physical distance.
- `trail_distance_m` / `trail_distance_miles`: known running-coded trail subset. Unknown gap terrain is not invented.
- `provisional_distance_m`, `provisional_run_distance_m`, `candidate_additional_distance_m`: explicit baseline and review candidates, never implicitly accepted.
- `recovered_distance_m`, `non_running_recovered_distance_m`: accepted secondary gap movement and the non-running part.
- `recorded_active_distance_m`, `recorded_active_duration_s`, `recorded_active_pace_min_mile`: preferred source portions and their matching timer/distance denominator.
- `active_pace_min_mile`: blank after distance repair if whole-workout active time is unsupported. The recorded Garmin pace remains available separately. Composite source-segment pace is labeled `active_pace_scope=recorded_segments`.
- `elapsed_duration_s`, UTC/local endpoints and `elapsed_pace_min_mile`: the full selected continuous timeline when it spans the preferred sources, otherwise their time union.
- `estimated_stationary_duration_s`: observed gap sample durations below 0.2 m/s, not all possible stopped time.
- HR, ascent/descent, training effect/load: retained from supported preferred recorded portions. Garmin training effect is Garmin-only; multiple native session effects use a labeled maximum, not a fictitious sum.
- `canonical_status`, `confidence`, `requires_user_review`, `mileage_requires_user_review`, `physical_distance_requires_user_review`: whole-workout state versus independently resolved running mileage.
- `*_source_activity_ids`: convenience measurement-source lists; full methods and coverage remain in provenance.

Provenance time intervals are bounding intervals, with explicit `coverage_scope`; they do not assert that every second or every physiological sample in that interval was observed. `recorded_active_*` gives the measured distance/timer denominator. Physiological summaries cannot determine HR drift or fatigue within an unrecorded segment. None of the code infers fatigue from a stop, slow pace, hiking or a device mistake.

## Evidence rules and review thresholds

Timer pauses come from FIT timer stop/restart events. Record-only gaps exceed max(60 seconds, five times median source sampling interval). They are labeled dropout/unknown, not a proven forgotten resume. Secondary gap evidence needs actual cumulative-distance samples near both bounds (15-second tolerance), at least three points, monotonic nonnegative distances, max 30-second sample spacing, and >=90% sampled temporal coverage. There is no interpolation over absent data or distance resets.

Two-sided alignment compares measured distance increments in the 240-second moving windows before/after the gap: at least 50 m each, agreement within 15%, timestamp endpoint tolerance 20 seconds. This is temporal/distance alignment, not a claimed GPS route match. Coordinates remain local and are not required by this rule.

Automatic moving-pause repair additionally requires an explicit resumed timer pause, measured primary distance at gap bounds, >=80% secondary sample intervals with speed >=1.5 m/s and native cadence >=60 rpm (available HR must be >=40), missing distance >=max(50 m, 2% of preferred distance), and consistency with the overall distance difference. It is a conservative heuristic for running-coded exercise, not a gait diagnosis or proof of intent. Missing physical distance is secondary cumulative gap distance minus already recorded primary gap distance; valid Garmin distance remains intact.

A stationary gap has secondary distance <=max(15 m, 0.05 m/s × gap duration); no distance is added. `intentional_stationary_pause` describes observed stationary behavior, not independently proven intent. Gaps outside a secondary timeline, or unsupported gaps when both session distances agree within max(150 m, 5%), do not establish missing mileage. They remain in the issue report as `no_supported_missing_distance`. Small measured gap discrepancies <50 m stay below the review threshold. Sustained significant movement in record-only gaps remains reviewable even when alignment is strong.

Whole-distance differences >max(150 m, 5%) without sufficient localized evidence require review. Multiple gap candidates are not added twice to physical totals. Unknown movement between source segments remains distinguishable from the recorded running segments. Stationary/social/walking context comes from evidence and/or Jay; the code does not turn it into a fatigue assessment.

Active-window duplicate matching: a watch started and immediately paused gives session starts too far apart for the source pair matcher. Before canonical grouping, each timeline's active window drops leading/trailing record blocks shorter than 120 s that are separated from the rest by gaps over 300 s. Otherwise-ungrouped Garmin/Amazfit singletons of the same sport whose active windows start within 120 s, overlap at least 90% of the shorter window and agree on distance within 10% form one `duplicate_resolved` parent. The evidence is recorded as an automatic `active_window_duplicate` issue. Source matching flags are not rewritten.

## Persistent user decisions

By default the script reads `data/user_resolutions.json` if present. Use `--resolutions PATH` to select another file; an explicitly missing path is an error. Start from [config/user_resolutions.example.json](../config/user_resolutions.example.json). Imports never create or overwrite the decision input. The source ZIP, mapping and resolutions stay in ignored `data/`; an empty template is included in the upload ZIP, while applied choices/notes are represented in canonical outputs/provenance.

Example (replace placeholders with actual review/workout/Intervals IDs):

```json
{
  "schema_version": 1,
  "issues": {
    "ISSUE_ID": {"decision": "include_running", "note": "Forgot to resume after water stop"}
  },
  "workouts": {
    "CANONICAL_ID": {
      "run_distance_source_activity_ids": ["INTERVALS_SEGMENT_ID_1", "INTERVALS_SEGMENT_ID_2"],
      "segment_roles": {"INTERVALS_SEGMENT_ID_1": "warmup"},
      "note": "Running mileage is the confirmed recorded Garmin segments"
    }
  },
  "session_groups": []
}
```

Issue decisions: `include_running`, `include_walking`, `stationary_stop`, `use_preferred`, `use_secondary`, `separate_activity`, `unsure`. Included movement must have measured secondary evidence; a decision cannot invent missing samples. `use_secondary` selects its measured full-source distance with explicit user provenance. `separate_activity` also requires `sport` (`running`, `walking`, `cycling`, `hiking`, `other`); measured gap movement gets its own counting parent and is excluded from the original parent's running distance. `unsure` keeps the case unresolved. Jay's decision overrides automatic classification.

Workout overrides can choose `distance_source_activity_id`, supply explicit user-reported `distance_m` / `run_distance_m` / `trail_distance_m`, select non-overlapping recorded running sources with `run_distance_source_activity_ids`, set supported segment roles, or add a note. Running-source confirmation can settle running mileage while physical/social movement remains unresolved. Numeric physical-distance changes do not automatically assert that the extra movement was running: give `run_distance_m` separately when needed. Trail cannot exceed running, and running cannot exceed a confirmed physical total.

Explicit `session_groups` with `source_activity_ids` and optional `segment_roles` can join intentional splits without a continuous companion. Time alone never joins same-day runs. Supported roles: warmup/workout/cooldown/easy_run/trail/commute/walk/unknown. Names such as Warmup, Track workout, Cooldown and explicit FIT trail/walking classifications support roles; otherwise role remains unknown. Conflicting or missing source references fail validation; unmatched historical issue/workout decision IDs are preserved and reported, not discarded.

## Canonical summaries and bridge reconciliation

Daily/weekly summaries count parents only. `activity_count` now means physical-workout parent count; `source_segment_count` and `workout_segment_count` retain the other counts. Long-run distance now describes a parent outing rather than its largest source segment. Whole parents are assigned to the Los Angeles start date and Monday-start week, including midnight crossings; alternative midnight allocation awaits agreement.

`running_miles` is null if any running contribution is unresolved. `known_running_miles`, `provisional_running_miles`, `running_miles_including_provisional`, `candidate_additional_miles`, `unresolved_workout_count` and `mileage_complete` explain completeness. A running-specific user decision can keep running miles known while `unresolved_physical_distance_count` and `requires_user_review` identify unknown non-running physical movement. Non-running unknown distance never becomes an implicit running zero. Native load/ascent/time sums describe available measurements; HR is weighted only by observed preferred timer portions. Missing full timer durations after repair remain null.

The local schema deliberately separates physical/running distance and complete/provisional mileage, supporting either future Jay-approved bridge policy. It does not silently implement Bridge Claude's proposed `pp-bridge-1` field names. The bridge can eventually map confirmed daily running totals to `actual_run_miles`, and canonical notes/ordered segments to `run_details`, but must first agree on:
1. source-coded running versus hiking/social-walk policy;
2. null daily totals versus separately labeled provisional presentation;
3. canonical lifecycle/supersession and raw-import transition;
4. structured metric coverage/provenance and versioned transport;
5. midnight allocation and independent pace denominators.

The current bridge API is unchanged. Do not import these parent IDs into today's upsert store: regrouping changes memberships/IDs, and a current manifest does not retire formerly imported IDs. Exact-input reruns are deterministic, including resolutions; changed FIT encoding retains physical identity when Intervals IDs/membership stay stable but changes revisions. Grouping changes require downstream reconciliation. No deployment or sheet write was performed.

## Measured archive and example limits

The available archive has 97 source files through October 5, 2026, 25 standalone accepted pairs, four composites and 62 canonical parents (two dual-watch runs, Aug 23 and Aug 27, are joined by active-window matching). No timer events survive this regenerated export, so no high-confidence automatic forgotten-resume repair is claimed on it. October 5 retains the earlier explicitly requested 8.412658 running miles through a persisted confirmed Garmin-source decision; its extra physical movement remains reviewable. September 29 retains 2.160936 running miles, with the late elapsed-window discrepancy not interpreted as an added-distance hole.

The synthetic example repairs 750 m measured by the secondary device: 2250 m recorded Garmin + 750 m gap = 3000 m physical/running distance, while keeping Garmin HR/elevation and its recorded-portion pace. Tests also recover an 810 m (~0.5 mi) moving gap. Full-workout active pace stays unknown when its complete active denominator is unavailable. This is proof of algorithm behavior, not measurement of Jay's October 6 run. That reported hot/hilly hydration-pack run awaits updated FIT evidence.
