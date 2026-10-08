# Canonical moving duration — final v1 data-contract fix

Implementation pending independent Preprocessor Claude code review. Existing local schema canonical-workout-3 and the bridge field name remain unchanged. No bridge changes or production operations accompany this fix.

## Meaning and stationary-estimate scope

moving_duration_s describes moving time for the canonical outing, with stop/paused time excluded once. It is independent of recorded_active_duration_s, timer_duration_s and elapsed_duration_s; none is substituted merely because moving time is missing.

The pre-existing estimated_stationary_duration_s is **not** stationary time while the primary timer was running. It sums some secondary-watch stationary sample bins inside primary stationary pause/record-gap intervals. It covers analyzed gaps, not all stops, and can include time already removed from Garmin timer duration. Therefore timer minus that estimate is not a valid canonical formula. The field/algorithm is unchanged; the moving-duration implementation never subtracts it.

## Source selection

For each preferred non-overlapping source segment, select a valid FIT total_moving_time if provided; otherwise use that activity's explicitly indexed Intervals CSV Moving Time (seconds). These are published moving metrics, not aliases of timer time. FIT detail remains the primary distance/device/lap/record input; this is documented CSV metadata enrichment from a field already parsed into intervals_moving_duration_s. CSV matching remains by activity identity. Validate finite nonnegative values against source elapsed time and, when present, timer time (one second tolerance for source rounding). Moving zero remains known zero. FIT provenance is high confidence; Intervals computed moving-time provenance is medium, because the source owns its motion-filtering algorithm.

Sum preferred sequential segments once. Do not include unrecorded split-boundary time just because an elapsed gap exists. For a reconstructed outing with accepted moving-distance repair, use the continuous counterpart's full moving metric only if it covers the canonical window and does not include user-excluded/separated motion. This covers physical movement missed while Garmin remained paused; standing water/social stops still do not count. A watch pause during accepted physical motion is not itself proof of a physical stop. Whole-workout timer/active pace are not changed or synthesized from this independent moving field.

Existing canonical timestamps can follow a slightly shorter continuous watch. If the preferred source's moving duration cannot fit that existing clock, do not clamp it or alter unrelated elapsed/timer fields: use an independently valid continuous moving measurement only when its start/end exactly match the canonical clock. This occurs on Sep8 (389 s) and one Sep29 workout (705 s). Provenance names the canonical elapsed source. If no suitable source exists, preserve null.

A pending physical-gap/distance issue prevents declaring whole-outing moving coverage complete. For Sep7, retain null rather than label primary recorded-portion moving time as a whole-workout value. Its source values (Garmin 10,014 s; Amazfit 10,521 s) remain available in activities_master.csv; they are not silently selected over the unresolved gap. This is the remaining review case, not a missing CSV value.

## Record-based fallback

If neither explicit moving metric is usable, estimate motion from local FIT sample intervals. Bins at least 0.2 m/s count as motion; the threshold distinguishes movement from stationary noise and is an estimate rather than exact gait detection. Prefer valid monotonic cumulative-distance increments; otherwise use valid nonnegative speed samples. Clip to the source elapsed window, exclude timer stop/start intervals once (including duplicate stop events and terminal pauses), and reject unobserved active sample gaps over 30 s, missing motion signals or implausible speeds (8 m/s foot, 50 m/s other sports).

Observed active coverage must agree with a valid timer duration within one second. The timer is a coverage check, not the moving result. When the timer is absent, require coverage of elapsed time minus explicitly known pause intervals. Missing records or ambiguous active gaps remain null. Do not interpolate long gaps or estimate movement by subtracting the old stationary aggregate. Record fallback uses medium-confidence provenance. User-separated sampled movement is evaluated only inside its extracted window, not by copying a whole-source duration.

Every canonical value must satisfy 0 <= moving_duration_s <= elapsed_duration_s; inconsistent coverage stays null. Field provenance records selected source IDs, method, confidence and coverage scope. Source rows stay immutable.

## Revisions, validation and release

Moving duration is calculated before the existing content revision hash. Same membership retains canonical_workout_id; changed moving duration changes revision. The manifest carries the changed revisions, so the bridge's normal client delta comparison can resend the changed parents without reset/backfill. This is an expectation of the existing contract, not a live import/readback claim.

Current candidate: 116 source activities, 78 canonical workouts, 77 populated durations / changed revisions, zero added/retired IDs. Sep7 (cw_38efeca565fcb102dcdd) remains null: unknown_unresolved_outing_motion. Oct5=8,146 s; Oct6=2,212 s. All other canonical values, training totals and source outputs are unchanged. 123 tests pass, including no stops, manual pause, timer-running stationary time, combined/overlapping pause and stationary time, missing timer, explicit metadata, zero, incomplete samples, bounds, continuous repair coverage, alternative clock and revision changes.

Candidate files/ZIP are under output/moving_duration_review/. The routine output/Garmin_Amazfit_Training_Normalized.zip remains the last reviewed upload. After Claude approves and any fixes are reviewed/tested, regenerate the routine ZIP and publish the reviewed fix to Bridge Codex. Only then run the separately authorized normal TEST delta import and verify moving-hours readback. v1 completion is not claimed by this local implementation.
