# intervals-icu-chatgpt-preprocessor

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

## Device and elevation provenance

Intervals.icu can regenerate FIT exports using `manufacturer=development`, `product_name=Intervals.icu`, omitting original watch metadata. Such files are **Unknown**, not Garmin or Amazfit. Filename patterns, running dynamics, pause behavior and names alone are not reliable manufacturer evidence. `device_identification_source` records FIT metadata or an explicit user mapping. FIT file creation time may be export time. Device metadata is retained when present; creator device index 0 takes priority over attached sensors.

After confirming devices, copy `output/device_mapping_template.csv` into `data/device_mapping.csv`, fill the relevant rows, and rerun with `--device-map data/device_mapping.csv`. Allowed device families: Garmin, Amazfit, Other, Unknown. Match exact `source_filename`. Blank overrides leave FIT metadata unchanged.

Set `elevation_source` to `original` or `intervals_corrected` **only with external confirmation**. Otherwise it stays `unknown`. An exported ascent field does not prove original measurement, correction, correction provider, or use of a barometer. Mapping columns can separately supply original and corrected ascent/descent if both are known. Confirmed source labels populate the corresponding columns from exported FIT elevation if no explicit value was supplied. The supplied Activities CSV has no original/corrected elevation columns. This project does not invent a reconstruction source or calculate ascent by summing noisy GPS altitude changes.

## Outputs and units

- `activities_master.csv`: one row per FIT activity; stable content/filename based IDs, UTC/local timestamps, device metadata, normalized metrics and compact JSON for native/developer session metrics with unit metadata. Multisport sessions are preserved in JSON; additive totals are aggregated only when every session supplies them. Timer-weighted HR/cadence/speed/power and session maxima are used across sessions.
- `activity_laps.csv`: available lap metrics, timing and additional native fields.
- `duplicate_groups.csv`: one row per candidate pair, confidence, evidence and accepted group ID. Low-confidence candidates have no accepted group unless independently grouped; they do not suppress training totals.
- `paired_activity_comparison.csv`: all candidate comparisons; A=Garmin and B=Amazfit for confirmed cross-watch pairs, otherwise device labels identify A/B. Signed differences are B minus A. Missing values stay blank. Original/corrected Amazfit elevation has separate comparisons against Garmin, including absolute and signed percent differences.
- `elevation_comparison_summary.csv`: median signed/absolute elevation differences and signed percent difference by terrain and elevation provenance. Only high/medium Garmin/Amazfit candidates contribute. Garmin is a comparison reference, not ground truth. Empty pair sets have blank medians, not zero error.
- `daily_training_summary.csv`, `weekly_training_summary.csv`: preferred records only, grouped by local start date; Monday–Sunday weeks. Running miles include trail miles (trail is a subset); cycling is separate. Multisport components remain available in session JSON and are not allocated to running/cycling totals. Sums include available measurements only; coverage counts show missing ascent and training load. Duration-weighted HR uses positive timer durations with measured HR. Intervals load, FIT load and training stress score are separate.
- `data_quality.csv`: inventory, parsing failures/exclusions, local year/device/sport counts, coverage, missing rates, candidate counts, suspicious values, units/timezone notes. CRC/structural errors reject the file and are reported; the program finishes other files and exits 1 if any file failed.
- `device_mapping_template.csv`: editable helper included in the ZIP to preserve confirmed device/provenance overrides for reproducibility.

Distances/elevation: meters; distance also miles. Durations: seconds. Pace: minutes/mile. HR: bpm. Power: watts. Temperature: Celsius. **Cadence is native decoded FIT rpm**, often half running steps/minute; no undocumented doubling is performed. Native recovery/VO2/developer units are retained in session unit JSON. Blank means unavailable; numeric zero remains zero. Timer duration is not necessarily moving duration: `moving_duration_s` exists only when FIT explicitly supplies it. Intervals moving time is separately labeled. `elapsed_minus_timer_s` estimates excluded timer time, not actual stopped/non-running time. An unpaused Amazfit may include stopped time in timer duration. Pause count requires a timer stop followed by a restart; terminal stops do not count as pauses.

UTC is preserved; local timestamps use `America/Los_Angeles` with date-specific daylight saving offsets. Weekly/daily totals assign whole activities by local start date, including midnight crossings.

## Duplicate matching and limitations

Same sport (running/trail share running), start difference <=300 seconds and >=50% overlap of the shorter elapsed window produce a candidate. High confidence requires start <=120 seconds, overlap >=90%, elapsed-duration ratio >=80%, distance difference <=10%, or identical FIT bytes. Medium requires overlap >=80%, duration ratio >=70%, distance difference <=25%. Other candidates are low and need review. Distance percent uses the larger distance as denominator. Complete-link grouping requires every pair to match at high/medium confidence, avoiding chains through partial recordings. Thresholds are transparent heuristics; coincident same-sport workouts can still be false positives. Partial Garmin segments versus one continuous Amazfit workout may remain low candidates to avoid discarding a distinct segment.

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
| Oct 5, morning | 5671.01 / 13839 | 2291 / 9207 | 2290 / 9206 | 12 / 271 | Low, likely partial vs continuous recording; both preferred |

25 accepted pairs produce 72 preferred training rows. Lower-confidence/partial recordings are intentionally retained, so daily/weekly totals can still include overlapping partial workouts pending review. The Amazfit FIT timer and Intervals moving durations can differ considerably (Oct 5: 9206 s FIT timer vs 8146 s Intervals moving); they are kept separate. Neither should be called true running time without further evidence.

Across accepted pairs, exported Amazfit minus Garmin median ascent is +1 m for road/unspecified runs (18 pairs) and −2 m for trails (7 pairs); median absolute differences are 2 m and 3 m. These comparisons describe exported session metrics only, not validated correction accuracy. “Road_or_unspecified” includes generic running and does not prove a paved route. Corrected/original elevation comparisons remain blank until provenance is provided.
