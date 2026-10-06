# intervals-icu-chatgpt-preprocessor

Read [HANDOFF.md](HANDOFF.md) first for team coordination and [the canonical model](docs/CANONICAL_WORKOUT_MODEL.md) for reconstruction/schema details. Cross-team coordination is in the parent `CONTEXT.md`; this is the preprocessor component, not the bridge.

Local Python 3.13 project. Originals are read only; ZIP members are decoded in memory without extraction. The only third-party dependency is fitdecode (MIT licensed).

## Setup and rerun

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python preprocess_fit.py --input data/i284770_fit_files.zip --output output --activities-csv data/i284770_activities.csv --device-map data/device_mapping.csv
python -m unittest discover -s tests -v
```

Upload `output/Garmin_Amazfit_Training_Normalized.zip`. Add a separately downloaded Wellness CSV for sleep, HRV, resting HR and recovery analysis; activity FITs are not a complete recovery dataset. For a new dataset, omit `--device-map` until labels are confirmed. The included mapping template can be passed to `--device-map` after review. Activities CSV enrichment is optional and joins only on the Intervals activity ID in the filename. It supplies names, Intervals load, moving time and distance in separate columns without replacing FIT measurements.

The cumulative export uses one stable ZIP filename, replaced on each successful run. No dated ZIP is created by default. To keep an occasional snapshot, add `--archive`:

```bash
python preprocess_fit.py --input data/i284770_fit_files.zip --output output --activities-csv data/i284770_activities.csv --device-map data/device_mapping.csv --archive
```

The current ZIP is updated first, then an identical copy is saved under `output/archive/Garmin_Amazfit_Training_Normalized_YYYY-MM-DD_HHMMSS_microseconds.zip`. The timestamp uses America/Los_Angeles; unique filenames preserve multiple snapshots made on the same day. The archive directory is created automatically, and both ZIP paths are printed. Only the completed ZIP is copied; intermediate CSV files are not separately archived. A failed parse or package build leaves the previous current ZIP intact and creates no snapshot; diagnostic CSVs may reflect the failed attempt. If copying a requested snapshot fails, the successfully updated current ZIP remains available and the command reports an error.

## Device and elevation provenance

Intervals.icu can regenerate FIT exports using `manufacturer=development`, `product_name=Intervals.icu`, omitting original watch metadata. Such files are **Unknown**, not Garmin or Amazfit. Filename patterns, running dynamics, pause behavior and names alone are not reliable manufacturer evidence. `device_identification_source` records FIT metadata or an explicit user mapping. FIT file creation time may be export time. Device metadata is retained when present; creator device index 0 takes priority over attached sensors.

After confirming devices, copy `output/device_mapping_template.csv` into `data/device_mapping.csv`, fill the relevant rows, and rerun with `--device-map data/device_mapping.csv`. Allowed device families: Garmin, Amazfit, Other, Unknown. Match exact `source_filename`. Blank overrides leave FIT metadata unchanged.

Set `elevation_source` to `original` or `intervals_corrected` **only with external confirmation**. Otherwise it stays `unknown`. An exported ascent field does not prove original measurement, correction, correction provider, or use of a barometer. Mapping columns can separately supply original and corrected ascent/descent if both are known. Confirmed source labels populate the corresponding columns from exported FIT elevation if no explicit value was supplied. The supplied Activities CSV has no original/corrected elevation columns. This project does not invent a reconstruction source or calculate ascent by summing noisy GPS altitude changes.

## Outputs and units

- `activities_master.csv`: one row per FIT activity; stable content/filename based IDs, UTC/local timestamps, device metadata, normalized metrics and compact JSON for native/developer session metrics with unit metadata. Multisport sessions are preserved in JSON; additive totals are aggregated only when every session supplies them. Timer-weighted HR/cadence/speed/power and session maxima are used across sessions.
- `activity_laps.csv`: available lap metrics, timing and additional native fields.
- `duplicate_groups.csv`: one row per candidate pair, confidence, evidence and accepted group ID. Low-confidence pairs can belong to an accepted composite group based on combined evidence.
- `composite_duplicate_groups.csv`: one continuous activity versus two or more sequential activities from another device, member IDs, confidence, summed distance, full window, coverage, between-segment gaps and preferred source role.
- `paired_activity_comparison.csv`: all candidate comparisons; A=Garmin and B=Amazfit for confirmed cross-watch pairs, otherwise device labels identify A/B. Composite rows compare a virtual combined segment record with the continuous recording; `comparison_type`, `continuous_activity_id` and `segment_activity_ids` distinguish them. Virtual records are never added to the master activity CSV. Composite elapsed duration is the sum of segment elapsed durations; the separate segment time window includes gaps. Signed differences are B minus A. Missing values stay blank. Original/corrected Amazfit elevation has separate comparisons against Garmin, including absolute and signed percent differences.
- `elevation_comparison_summary.csv`: median signed/absolute elevation differences and signed percent difference by terrain and elevation provenance. Only high/medium Garmin/Amazfit comparisons contribute; individual members of composites are excluded in favor of the combined comparison. Garmin is a comparison reference, not ground truth. Empty pair sets have blank medians, not zero error.
- `daily_training_summary.csv`, `weekly_training_summary.csv`: canonical physical-workout parents only, grouped by local start date; Monday–Sunday weeks. Null running totals indicate unresolved contributions; known/provisional subtotals and completeness fields are separate. Source counting flags are retained as legacy matcher annotations, not the canonical counting basis. Running miles include trail miles (trail is a subset); cycling is separate. Multisport components remain available in session JSON and are not allocated to running/cycling totals. Sums include available measurements only; coverage counts show missing ascent and training load. Duration-weighted HR uses positive timer durations with measured HR. Intervals load, FIT load and training stress score are separate.
- `data_quality.csv`: inventory, parsing failures/exclusions, local year/device/sport counts, coverage, missing rates, candidate counts, suspicious values, units/timezone notes. CRC/structural errors reject the file and are reported; the program finishes other files and exits 1 if any file failed, preserving the previous current ZIP.
- `device_mapping_template.csv`: editable helper included in the ZIP to preserve confirmed device/provenance overrides for reproducibility.

Distances/elevation: meters; distance also miles. Durations: seconds. Pace: minutes/mile. HR: bpm. Power: watts. Temperature: Celsius. **Cadence is native decoded FIT rpm**, often half running steps/minute; no undocumented doubling is performed. Native recovery/VO2/developer units are retained in session unit JSON. Blank means unavailable; numeric zero remains zero. Timer duration is not necessarily moving duration: `moving_duration_s` exists only when FIT explicitly supplies it. Intervals moving time is separately labeled. `elapsed_minus_timer_s` estimates excluded timer time, not actual stopped/non-running time. An unpaused Amazfit may include stopped time in timer duration. Pause count requires a timer stop followed by a restart; terminal stops do not count as pauses.

UTC is preserved; local timestamps use `America/Los_Angeles` with date-specific daylight saving offsets. Weekly/daily totals assign whole activities by local start date, including midnight crossings.

## Duplicate matching and limitations

Same sport (running/trail share running), start difference <=300 seconds and >=50% overlap of the shorter elapsed window produce a candidate. High confidence requires start <=120 seconds, overlap >=90%, elapsed-duration ratio >=80%, distance difference <=10%, or identical FIT bytes. Medium requires overlap >=80%, duration ratio >=70%, distance difference <=25%. When elapsed durations differ substantially, start difference <=120 seconds, overlap >=90%, distance difference <=10% and timer-duration ratio >=80% can instead support a medium-confidence pair. This handles a late terminal stop without equating elapsed time to moving time. Other candidates are low and need review. Distance percent uses the larger distance as denominator. Complete-link grouping requires every pair to match at high/medium confidence, avoiding chains through partial recordings. Thresholds are transparent heuristics; coincident same-sport workouts can still be false positives. Composite detection follows pair matching. For each continuous recording with known device family, it searches sequential same-sport segments from a different known device family. Their first start and last end must be within 300 seconds of the continuous window; gaps are limited to 300 seconds and overlaps to 5 seconds of timestamp jitter. The segments must cover >=80% of the continuous elapsed window, and summed distance must differ by <=25% using the larger distance as denominator. High confidence requires endpoint differences <=120 seconds, coverage >=90%, and distance difference <=10%. Running and trail-running segments can coexist since both have FIT sport `running`.

Candidates are ranked by confidence, distance agreement, endpoint agreement, then stable group ID. Accepted groups have disjoint memberships, and do not break an existing pair with a recording outside the proposed composite. The preferred device wins collectively: Garmin segments all contribute versus one continuous Amazfit recording; conversely a continuous Garmin contributes versus Amazfit segments. Every original row remains intact, with `composite_duplicate_group_id`, `composite_role` (`continuous` / `segment`) and `contributes_to_training_totals`. `preferred_training_record` remains synchronized for compatibility. Individual pair evidence is retained even when combined group evidence provides a stronger match.

Unmatched partial recordings remain counted separately; only an accepted complete composite suppresses a secondary recording. Thresholds are conservative, so long breaks or poor distance agreement may still require manual review. Unknown devices are never assigned composite roles from filenames or metrics alone.

Preferred source order: Garmin, Amazfit, Other, Unknown; ties choose more detailed record count then stable ID. Both recordings remain in all activity/lap exports. Unknown-device groups use this deterministic fallback and must be reviewed before treating totals as a Garmin training log. Matching does not infer device identity. IDs remain stable for an unchanged archive member; renamed/re-encoded activities can change IDs.

Non-activity file types and files without session/start metadata are excluded. Valid session-bearing marker-like names are flagged for review rather than silently removed. Suspicious zero distances, timestamps, HR, speed, duration, climbing and timer exceeding elapsed are flagged, not replaced.

## Selected detailed export

```bash
python preprocess_fit.py --input data/i284770_fit_files.zip --output detailed --activity-id i178426505
# Repeat --activity-id for more selections, or use --include-records for all.
```

Explicit detailed requests produce `activity_records.csv` with timestamps, cumulative distance, HR, native cadence, altitude, speed, power and latitude/longitude converted from semicircles to degrees. Neither this file nor raw FITs enters the ZIP, even if a detailed file exists from a previous run. Normal activity/lap JSON filters location fields. Treat detailed exports as sensitive. The normal package retains requested device serial numbers but no GPS coordinates.

## Decoder references

[fitdecode reader](https://fitdecode.readthedocs.io/en/latest/reference/reader.html) and [message fields](https://fitdecode.readthedocs.io/en/latest/reference/records.html); [Garmin FIT protocol](https://developer.garmin.com/fit/protocol/) for field validity, UTC timestamps and file identity.

## Validation of the supplied archive

97 FIT files parsed with zero failures, covering August 19–October 5, 2026. The Activities CSV has 114 entries; 17 have no corresponding FIT in this archive and are not added as FIT workouts. Every FIT labels its creator Intervals.icu, and no device_info or timer event messages were present. Watch family uses the user's naming confirmation: time-of-day names (Morning/Lunch/Afternoon/Evening/Night Run/Walk/Ride) are mapped to Amazfit; location names to Garmin. This pattern extension applies to 60 Amazfit and 37 Garmin files and should be checked if your naming convention changes. Amazfit model is user-supplied “Bip Max”; Garmin remains Epix Pro Gen 2 or Fenix 5X Plus 51mm, unresolved per file. No elevation corrections or original barometric values are claimed without confirmation. No reliable pause-event counts are available; duration gaps still permit comparisons.

Manual inspection of candidate session data:

| Local date | Garmin / Amazfit distance (m) | Elapsed (s) | Timer (s) | Ascent (m) | Decision |
|---|---|---|---|---|---|
| Aug 21, trail | 11560.48 / 11409 | 7397 / 7367 | 6840 / 6768 | 311 / 366 | High, same start window and distance |
| Aug 24, road | 8606.86 / 8542 | 4642 / 4620 | 3853 / 3997 | 81 / 85 | High, near-identical window/distance |
| Aug 30, trail | 14140.89 / 14174 | 8248 / 8352 | 7591 / 7688 | 494 / 496 | High, start difference 54 s |
| Oct 5, morning (combined Garmin) | 13538.86 / 13839 | 9170 / 9207 | 7967 / 9206 | 262 / 271 | High composite, Garmin segments contribute; Amazfit retained for comparison |

25 accepted standalone pairs and four composite groups produce 67 training-contributing rows. Unmatched partial recordings can still overlap pending review; accepted composites no longer double-count. The Amazfit FIT timer and Intervals moving durations can differ considerably (Oct 5: 9206 s FIT timer vs 8146 s Intervals moving); they are kept separate. Neither should be called true running time without further evidence.

Elevation summaries include accepted standalone pairs and combined composite comparisons. Their medians and counts are available in `elevation_comparison_summary.csv`. These comparisons describe exported session metrics only, not validated correction accuracy. “Road_or_unspecified” includes generic running and does not prove a paved route. Corrected/original elevation comparisons remain blank until provenance is provided.

## Composite regression validation

The full supplied archive contains four accepted composites, all high confidence:

| Local date | Continuous recording | Sequential segments | Training contribution |
|---|---|---|---|
| August 26 | Garmin, 10729.67 m | Two Amazfit records totaling 11653 m | Garmin continuous only |
| September 9 | Amazfit, 5327 m | Two Garmin records totaling 5297.78 m | Both Garmin segments |
| September 18 | Amazfit, 9820 m | Two Garmin records totaling 9911.45 m | Both Garmin segments |
| October 5 | Amazfit, 13839 m | Two Garmin records totaling 13538.86 m | Both Garmin segments |

October 5 now totals **8.412658 running miles**, including **4.888855 trail miles**, with two Garmin source segments represented by one canonical parent. Both the daily total and the week starting October 5 use this corrected distance. All three original records remain available. `long_run_miles` now describes the canonical parent; source segments remain separately inspectable. Physical distance beyond the confirmed running portions may remain unresolved.

September 29 is not a one-to-many composite in this archive. Its second Garmin/Amazfit pair has 1176.51/1175 m and timer durations 560/551 s, but elapsed durations 8529/552 s. This pair is medium confidence based on shared start, distance and timer time; the prolonged Garmin elapsed window is preserved for comparison. Garmin's two records now contribute **2.160936 running miles** that day, with both Amazfit counterparts retained and excluded from totals.

Tests cover the real October 5 and September 29 FITs, three-segment composites, reverse source preference, input-order stability, overlapping/incomplete/mismatched segment rejection, missing values, timezone handling and CRC rejection.


## Canonical workouts and review

New outputs: `canonical_workouts.csv`, `workout_segments.csv`, `source_relationships.csv`, `field_provenance.csv`, `reconstruction_issues.csv`, `reconstruction_review.csv`, `canonical_dataset_manifest.json`. The logical schema is `canonical-workout-1`; all sources and prior pair/composite comparison outputs remain available. See [model/schema and decision examples](docs/CANONICAL_WORKOUT_MODEL.md).

The processor uses decoded records/timer events locally for gap evidence, while the routine ZIP omits records and coordinates. An explicit Garmin pause with aligned, dense secondary movement can support distance repair. Record gaps, conflicting distances, sparse samples, ambiguous walking or unsupported timing produce review questions instead of fabricated mileage. Garmin's recorded-portion pace/HR/elevation stay separately sourced; repaired distance is never divided by an incomplete Garmin timer.

Review `output/reconstruction_review.csv`, put decisions in `data/user_resolutions.json` (copy `config/user_resolutions.example.json` to start), then rerun the usual command. The default reads that file if present. Use `--resolutions path/to/decisions.json` for a different input. The decision input is never overwritten. The persisted October 5 running-source choice records Jay's earlier explicit instruction to count both Garmin segments; other physical movement stays reviewable. No new measured October 6 distance is claimed: this ZIP still ends October 5.

Canonical bridge import is pending schema/counting/lifecycle agreement with the bridge team. These local exports and manifest are not a deployed bridge API or saved spreadsheet update. Shared communication lives in the parent `CONTEXT.md`, whose initial Git ownership belongs to Bridge Codex.
