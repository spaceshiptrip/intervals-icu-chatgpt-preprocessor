# Garmin raw FIT retrieval — verified local workflow

Read HANDOFF.md first. This is a local Garmin operational step, not bridge deployment or a Google Sheet operation. It uses the existing authenticated Garmin/Docker/InfluxDB setup and never puts credentials in command arguments or exports.

## Actual configuration

| Setting | Verified value |
|---|---|
| Garmin checkout | /Users/jtorres/Workspaces/pnb/garmin-grafana |
| Compose service | garmin-fetch-data |
| Base Compose file | compose.yml, preserved unchanged |
| Retention override | compose.override.yml, automatically loaded by default Compose invocation |
| KEEP_FIT_FILES | True (the string True is accepted by this fetcher) |
| FIT_FILE_STORAGE_LOCATION | /home/appuser/fit_filestore |
| Host bind directory | /Users/jtorres/Workspaces/pnb/garmin-grafana/fit_filestore |
| Container bind directory | /home/appuser/fit_filestore |
| Runtime user | appuser, UID/GID 1000:1000 |
| One-off range variables | MANUAL_START_DATE, MANUAL_END_DATE; inclusive YYYY-MM-DD |
| Activity-only selection | FETCH_SELECTION=activity |

The inspected checkout defines retention and path handling in src/garmin_grafana/garmin_fetch.py. Its iter_days loop includes both endpoints and walks backwards. The running container also uses appuser. Existing token mounting/authentication and all InfluxDB settings remain in the original setup.

The minimal added override is:

```yaml
services:
  garmin-fetch-data:
    environment:
      KEEP_FIT_FILES: "True"
      FIT_FILE_STORAGE_LOCATION: /home/appuser/fit_filestore
    volumes:
      - ./fit_filestore:/home/appuser/fit_filestore
```

Use default `docker compose` from this checkout, which loads the override. If you explicitly pass `-f compose.yml`, also pass `-f compose.override.yml`; otherwise you omit retention. Do not dump `docker compose config` to chat: it includes resolved credentials. The wrapper reads its JSON privately and displays only errors without config/log contents.

## Permissions

The new bind directory was given UID/GID 1000:1000 and mode 0755 using an isolated root container. Only that new directory was affected; no recursive changes to token, database or checkout ownership. A network-disabled container running as 1000:1000 created and removed a temporary write probe successfully. Retained files are readable by the local preprocessor. Docker Desktop can display mapped host ownership differently, so an actual container write probe is stronger evidence than macOS ls ownership alone.

If recreating the directory, verify that appuser can write it and the host can read it. Do not run the whole fetcher as root to bypass a bind problem: that changes token/home paths. Do not chmod the repository or database recursively.

## Normal ongoing retention

From the actual Garmin checkout:

```bash
cd /Users/jtorres/Workspaces/pnb/garmin-grafana
docker compose up -d --no-deps --pull never garmin-fetch-data
```

This exact command was run successfully: it recreated only the fetcher using its existing image, loaded the retention override and left other services unchanged. Its ordinary sync immediately retained the October 6 native FIT. `up` enables the normal scheduler; an unchanged running container does not necessarily force an immediate new sync.

Read-only check from the preprocessor checkout:

```bash
.venv/bin/python scripts/fetch_garmin_fits.py --check
```

This verifies enabled retention, an explicit writable bind configuration, directory readability, parsed FIT count and oldest/newest **activity** timestamps. It does not infer freshness from filesystem modification time, mutate Compose or query Garmin.

## Immediate current-day fetch

From the preprocessor checkout:

```bash
.venv/bin/python scripts/fetch_garmin_fits.py
```

The wrapper defaults to the current America/Los_Angeles day. It uses the existing Compose setup, validates retention/mount settings, runs a one-off activity-only job and prints the retained directory and newest valid activity timestamp afterward. Credentials remain in the existing Compose/token setup; fetcher logs are suppressed except saved-FIT filename confirmations. This writes activity points to the existing local InfluxDB as the existing fetcher normally does.

## Inclusive historical backfill

For a bounded date range:

```bash
.venv/bin/python scripts/fetch_garmin_fits.py --start 2026-08-11 --end 2026-10-06
```

Equivalent verified checkout-supported Docker invocation:

```bash
cd /Users/jtorres/Workspaces/pnb/garmin-grafana
docker compose run --rm --no-deps \
  -e MANUAL_START_DATE=2026-08-11 \
  -e MANUAL_END_DATE=2026-10-06 \
  -e FETCH_SELECTION=activity \
  garmin-fetch-data
```

The variables, service and inclusive handling were inspected in this checkout, rather than guessed. The full historical range above is an example and has **not** been run. A single-day October 6 request uses the same path and is the operational verification case recorded in HANDOFF.md. Supply both start/end dates; invalid or reversed ranges fail before Docker execution. Use --repo only if the Garmin checkout moves. Avoid simultaneous manual jobs and wait for the normal fetcher's active sync to finish to reduce shared token/rate-limit contention.

The fetcher uses a timestamp/sport filename such as `20261006T200618UTC-running.fit`; a repeated fetch may rewrite that retained cache entry from Garmin. The preprocessor itself never edits original FITs. Treat retrieval as a cache refresh, not immutable historical versioning. Do not backfill a broad date range casually; choose the needed window and retain source hashes in coverage reports.

## Verify actual files and activity freshness

The initial retained file is:

`fit_filestore/20261006T200618UTC-running.fit`

It decodes as an activity starting 2026-10-06 13:06:18 America/Los_Angeles. FIT-native timer events confirm the stop/restart at 20:35:36–20:39:22 UTC, the gap repaired from the Intervals recording. Its presence verifies raw retention; the directory currently has one activity, not a complete Garmin history.

Compare all current sources from the preprocessor checkout:

```bash
.venv/bin/python source_coverage.py \
  --intervals-fit "/Users/jtorres/Downloads/i284770_fit_files(1).zip" \
  --activities-csv "/Users/jtorres/Downloads/i284770_activities(2).csv" \
  --output output
```

Normal preprocess runs perform the same check and print it before replacing the stable ZIP. Default comparison includes the known retained-FIT directory and available Garmin activity indices. Specify `--garmin-source /actual/fit/directory` (repeatable) to override discovery. `coverage_report.json` records source/member hashes, roles, timestamp ranges and missing/duplicate coverage; `source_inventory.csv` records activity indices without GPS.

Intervals FITs remain the selected cumulative detail source for this build. Activities CSV enriches/cross-checks those FITs. Native Garmin is an independent detail/freshness cross-check and is not added again to canonical totals. CSV exports in garmin-grafana/exports are **InfluxDB indices**, not raw FITs: keep their source role explicit and exclude END/No Activity marker rows. Their Oct 5 timestamps do not make the new native Oct 6 FIT stale; their historical coverage is limited.

## Common failures

- Docker CLI/socket unavailable: start the existing Docker setup and grant the coding agent Docker access if its sandbox blocks the socket.
- Retention unset or override omitted: use default Compose invocation or both -f files, then recreate only the fetcher.
- Wrong/missing/read-only mount: wrapper rejects it; fix the small override rather than changing unrelated settings.
- Permission denied: verify appuser UID/GID and write access inside an isolated container; keep the token/database directories unchanged.
- Garmin authentication or rate limit: use the existing Garmin setup's login/token workflow; never paste credentials. Avoid concurrent fetches.
- InfluxDB unavailable: one-off fetch still uses the existing database; --no-deps assumes its normal service is already up.
- Empty/old filestore: enabling retention does not backfill history automatically. Use a deliberate range and compare activity timestamps afterward.
- TCX fallback: the fetcher can save .tcx if FIT download/parsing fails. The FIT inventory does not pretend those files are FIT detail.
- Newly downloaded stale export: source coverage compares session start timestamps, not names/download times. Missing IDs, old sources and repeated snapshot coverage are reported explicitly.

Detailed Docker mechanics stay here. Publish cross-team updates only for interface/semantic changes, after required review; do not put tokens or raw FIT/GPS in CONTEXT.md or the normalized ZIP.
