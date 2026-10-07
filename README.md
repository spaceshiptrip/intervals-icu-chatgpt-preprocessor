# intervals-icu-chatgpt-preprocessor

Read [HANDOFF.md](HANDOFF.md) first for team coordination and [the canonical model](docs/CANONICAL_WORKOUT_MODEL.md) for reconstruction/schema details. Cross-team coordination is in the parent `CONTEXT.md`; this is the preprocessor component, not the bridge.

Local Python 3.13 project. Originals are read only; ZIP members are decoded in memory without extraction. The only third-party dependency is fitdecode (MIT licensed).

## Setup and rerun

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python preprocess_fit.py --input "data/i284770_fit_files(1).zip" --output output --activities-csv "data/i284770_activities(2).csv" --device-map data/device_mapping_current.csv
python -m unittest discover -s tests -v
```

Upload `output/Garmin_Amazfit_Training_Normalized.zip`. Add a separately downloaded Wellness CSV for sleep, HRV, resting HR and recovery analysis; activity FITs are not a complete recovery dataset. For a new dataset, omit `--device-map` until labels are confirmed. The included mapping template can be passed to `--device-map` after review. Activities CSV enrichment is optional and joins only on the Intervals activity ID in the filename. It supplies names, Intervals load, moving time and distance in separate columns without replacing FIT measurements.

The cumulative export uses one stable ZIP filename, replaced on each successful run. No dated ZIP is created by default. To keep an occasional snapshot, add `--archive`:

```bash
python preprocess_fit.py --input "data/i284770_fit_files(1).zip" --output output --activities-csv "data/i284770_activities(2).csv" --device-map data/device_mapping_current.csv --archive
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
- `daily_training_summary.csv`, `weekly_training_summary.csv`: canonical physical-workout parents only, grouped by local start date; Monday–Sunday weeks. `training_miles` is the official confirmed total of intentional foot-based training; confirmed partial mileage stays visible when full distance is unresolved. Candidates and completeness are separate. Legacy `running_miles` remains running-only and may be null for unresolved running coverage. Source counting flags are retained as legacy matcher annotations, not the canonical counting basis. Running miles include trail miles (trail is a subset); cycling is separately identifiable. Cycling is excluded from primary training miles and retains separate cycling miles/duration. Generic standalone walks require intent confirmation and retain measured unclassified distance outside official totals. Multisport components remain available in session JSON and are not allocated to running/cycling totals. Sums include available measurements only; coverage counts show missing ascent and training load. Duration-weighted HR uses positive timer durations with measured HR. Intervals load, FIT load and training stress score are separate.
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

## Original archive validation (historical)

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

October 5 now totals **8.412658 running miles**, including **4.888855 trail miles**, with two Garmin source segments represented by one canonical parent. The running-only daily/week fields retain this corrected distance; the new broader training total is **8.612223 miles**, including **321.17 m** of confirmed secondary-watch movement with unknown modality. All three original records remain available. `long_run_miles` now describes the canonical parent; source segments remain separately inspectable. The physical distance is reconstructed locally with field provenance; no extra gait classification is invented.

September 29 is not a one-to-many composite in this archive. Its second Garmin/Amazfit pair has 1176.51/1175 m and timer durations 560/551 s, but elapsed durations 8529/552 s. This pair is medium confidence based on shared start, distance and timer time; the prolonged Garmin elapsed window is preserved for comparison. Garmin's two records now contribute **2.160936 running miles** that day, with both Amazfit counterparts retained and excluded from totals.

Tests cover the real October 5 and September 29 FITs, three-segment composites, reverse source preference, input-order stability, overlapping/incomplete/mismatched segment rejection, missing values, timezone handling and CRC rejection.


## Canonical workouts and review

New outputs: `canonical_workouts.csv`, `workout_segments.csv`, `source_relationships.csv`, `field_provenance.csv`, `reconstruction_issues.csv`, `reconstruction_review.csv`, `canonical_dataset_manifest.json`. The logical schema is `canonical-workout-3`; all sources and prior pair/composite comparison outputs remain available. See [model/schema and decision examples](docs/CANONICAL_WORKOUT_MODEL.md).

The processor uses decoded records/timer events locally for gap evidence, while the routine ZIP omits records and coordinates. Aligned, dense secondary movement can support repair even when Intervals omits timer events. Conflicting distances, sparse samples, weak alignment or unsupported timing remain reviewable. Strongly supported movement within the training outing counts regardless of uncertain gait; uncertain modality stays explicitly unknown. Garmin's recorded-portion pace/HR/elevation stay separately sourced; repaired distance is never divided by an incomplete Garmin timer.

Review `output/reconstruction_review.csv`, put decisions in `data/user_resolutions.json` (copy `config/user_resolutions.example.json` to start), then rerun the usual command. The default reads that file if present. Use `--resolutions path/to/decisions.json` for a different input. The decision input is never overwritten. The persisted October 5 running-source choice records Jay's earlier explicit instruction to count both Garmin segments; other measured outing movement can contribute to training volume under the accepted “miles are still miles” policy. The fresh ZIP now includes October 6: **501.28 m** recovered from a 226-second gap yields **4,455.03 m / 2.768227 training miles**. Native retained Garmin FIT independently confirms the pause bounds. Full-workout active pace remains unavailable; recorded Garmin pace/HR retain coverage.

Canonical bridge import is pending schema/counting/lifecycle agreement with the bridge team. These local exports and manifest are not a deployed bridge API or saved spreadsheet update. Shared communication lives in the parent `CONTEXT.md`, whose initial Git ownership belongs to Bridge Codex.


## Source refresh and native Garmin retention

Fresh inputs are selected by their activity timestamps, never download time. Preflight example:

```bash
python source_coverage.py --intervals-fit "data/i284770_fit_files(1).zip" --activities-csv "data/i284770_activities(2).csv" --output output
python preprocess_fit.py --input "data/i284770_fit_files(1).zip" --activities-csv "data/i284770_activities(2).csv" --device-map data/device_mapping_current.csv --output output
```

Every build prints source counts and oldest/newest activity times, warnings and newest canonical start before replacing the stable ZIP. `coverage_report.json` records exact input paths/hashes, member hashes, date coverage, missing IDs and duplicate checks. `source_inventory.csv` is the GPS-free activity index across compared sources. FITs remain primary detail; activities CSV only indexes/enriches them. Missing CSV-only activities are not fabricated FIT workouts. Use repeated `--garmin-source PATH` to choose independent Garmin FIT directories/ZIPs explicitly; by default the known sibling filestore/activity exports are checked when available.

The fresh Intervals FIT ZIP and CSV each contain 116 activities, **Aug 11 08:09:38 through Oct 6 13:06:18 America/Los_Angeles**. There are no CSV/FIT missing IDs. It restores 17 older activities missing from the previous 97-FIT archive and adds the two October 6 watch recordings. Device mappings in `data/device_mapping_current.csv` extend the existing user-confirmed names, including already-confirmed Pasadena names; raw metadata still takes precedence without explicit overrides.

The sibling `garmin-grafana/exports` archives are InfluxDB CSV exports, not FITs. Their ActivitySummary rows include END/No Activity markers, excluded from workout counts. Those indices end Oct 5, but the new native filestore is independently current through Oct 6. Retention was unset with no mount. A minimal `compose.override.yml` now enables KEEP_FIT_FILES=True and mounts `./fit_filestore:/home/appuser/fit_filestore`, with explicit FIT_FILE_STORAGE_LOCATION. Runtime UID/GID is 1000:1000; an isolated write probe passed. Only the Garmin fetcher was recreated using its existing image; other services/base settings were unchanged. Its normal fetch saved the October 6 FIT, so no manual re-fetch was needed for initial retention. The wrapper was subsequently verified with a single-day October 6 activity-only re-fetch.

Native files now land at `/Users/jtorres/Workspaces/pnb/garmin-grafana/fit_filestore`. Older retained FIT history is incomplete; the current filestore contains one activity. The source report warns about missing native counterparts rather than confusing fresh date coverage with complete historical coverage. Current normalized detail remains the cumulative Intervals FIT set; native Garmin is an independent cross-check, not an extra counting contribution. The native Oct 6 FIT has explicit timer events at 20:35:36–20:39:22 UTC, confirming the interval repaired from Intervals samples. Its decoded creator product is fenix5x_plus; no whole-archive watch-model claim is made from it.

The inspected service supports inclusive MANUAL_START_DATE / MANUAL_END_DATE ranges. For a deliberate future historical fetch, from the Garmin repo:

```bash
docker compose run --rm --no-deps -e MANUAL_START_DATE=2026-08-11 -e MANUAL_END_DATE=2026-10-06 -e FETCH_SELECTION=activity garmin-fetch-data
```

This full historical range writes the existing local InfluxDB and retains files; that range was **not run** as part of this change. Only a single-day October 6 wrapper verification was run. Avoid overlapping manual and scheduled fetches. Raw filestore files are ignored by Git. Never package retained FITs or raw GPS into the normalized ZIP.

For the repeatable operational commands and wrapper, see [Garmin FIT retrieval](docs/GARMIN_FIT_RETRIEVAL.md). Use `.venv/bin/python scripts/fetch_garmin_fits.py --check`, a current-day fetch without flags, or `--start YYYY-MM-DD --end YYYY-MM-DD` for an inclusive backfill.

## Accepted foot-mileage policy and snapshot lifecycle (v3)

Primary training miles include intentional running, hiking and walking, including recovery walks and foot movement within a run outing. Cycling stays separate. `canonical_workouts.csv.confirmed_training_distance_mi` is the designated bridge field and equals `training_distance_miles`; daily/weekly `training_miles` sums it once per active parent. Generic walks without clear training intent have null official mileage and a review row. Set a persistent workout `intentional_training` boolean to confirm/exclude them; unknown is not zero.

The [scoped snapshot contract](docs/CANONICAL_SNAPSHOT_CONTRACT.md) specifies retirement/supersession, traceable source keys, old/new date recomputation and complete scope replacement. Use one output directory per `--snapshot-scope` (default jay-training). Coverage shrink is refused unless explicitly acknowledged with `--allow-source-removals`. The bridge has not implemented atomic application/raw-import migration: current output is for reviewed analysis, not an additive bridge import.

Current v3 real export: 116 sources, 78 workouts, 23 reviews (22 unclassified walks and Sep 7). Confirmed foot miles ~220.006487; cycling ~25.365615; unclassified walks ~22.368742. Aug 26/Sep 18 follow accepted preferred-source decisions. Sep 7 measured gap has failed alignment: 13.563986 mi confirmed, 618.13 m additional provisional. Oct 5 remains 8.612223 mi and Oct 6 2.768227 mi. Claude approved the implementation after a summary fix reviewed by Codex. All 106 tests pass; confirmed daily/weekly modality subtotals remain available despite pending walks.
