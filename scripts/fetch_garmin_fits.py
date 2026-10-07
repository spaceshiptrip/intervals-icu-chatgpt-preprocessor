#!/usr/bin/env python3
"""Fetch retained Garmin FITs with the existing local Docker Compose setup.

No credentials are accepted or printed. Defaults to an activity-only current-day
fetch; --start/--end requests an inclusive backfill. --check is read-only.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from source_coverage import inventory

DEFAULT_REPO = ROOT.parent.parent / 'garmin-grafana'
SERVICE = 'garmin-fetch-data'


def day(value):
    try: return date.fromisoformat(value)
    except ValueError as exc: raise argparse.ArgumentTypeError('Date must be YYYY-MM-DD') from exc


def run_json(command, cwd):
    try: result=subprocess.run(command,cwd=cwd,capture_output=True,text=True)
    except FileNotFoundError as exc: raise RuntimeError('Docker CLI unavailable; install/start the existing Docker setup') from exc
    if result.returncode: raise RuntimeError(f'{" ".join(command)} failed (exit {result.returncode}); check Docker access and local Compose configuration. Credentials were not printed.')
    try: return json.loads(result.stdout)
    except json.JSONDecodeError as exc: raise RuntimeError('Docker did not return the expected JSON configuration') from exc


def retained_path(repo):
    config=run_json(['docker','compose','config','--format','json'],repo)
    service=config.get('services',{}).get(SERVICE)
    if not service: raise RuntimeError(f'Compose service {SERVICE} is missing')
    environment=service.get('environment',{})
    if str(environment.get('KEEP_FIT_FILES','')).lower() not in ('true','t','yes','1'):
        raise RuntimeError('KEEP_FIT_FILES is not enabled; follow docs/GARMIN_FIT_RETRIEVAL.md')
    target=environment.get('FIT_FILE_STORAGE_LOCATION')
    if not target: raise RuntimeError('Set explicit FIT_FILE_STORAGE_LOCATION so retention has an unambiguous mount')
    mounts=[v for v in service.get('volumes',[]) if v.get('type')=='bind' and v.get('target')==target]
    if len(mounts)!=1: raise RuntimeError('Exactly one writable FIT filestore bind mount is required')
    if mounts[0].get('read_only'): raise RuntimeError('FIT filestore bind mount is read-only')
    source=Path(mounts[0]['source'])
    if not source.is_dir(): raise RuntimeError(f'FIT output directory does not exist: {source}')
    if not os.access(source,os.R_OK|os.X_OK): raise RuntimeError(f'FIT output directory is not readable: {source}')
    return source


def fetch_command(start, end):
    return ['docker','compose','run','--rm','--no-deps',
        '-e',f'MANUAL_START_DATE={start.isoformat()}', '-e',f'MANUAL_END_DATE={end.isoformat()}',
        '-e','FETCH_SELECTION=activity',SERVICE]


def fetch(repo, start, end):
    command=fetch_command(start,end)
    print(f'Fetching Garmin activities for {start} through {end} (inclusive).',flush=True)
    # Existing Compose credentials/tokens remain private; fetcher logs can contain
    # identifying information, so only retained-file confirmations are displayed.
    try:
        process=subprocess.Popen(command,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    except FileNotFoundError as exc: raise RuntimeError('Docker CLI unavailable') from exc
    stored=0
    assert process.stdout is not None
    for line in process.stdout:
        if 'stored in output file ' in line and line.rstrip().endswith('.fit'):
            stored+=1;print('Retained: '+Path(line.split('stored in output file ',1)[1].strip()).name,flush=True)
    code=process.wait()
    if code: raise RuntimeError(f'Garmin fetch failed (exit {code}); check authentication, InfluxDB connectivity, rate limits and filestore permissions using the existing Garmin setup. Credentials/log contents were not printed.')
    if not stored: print('No retained-file confirmation was logged; inventory below is the evidence, not exit status alone.',flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=DEFAULT_REPO)
    parser.add_argument('--start',type=day);parser.add_argument('--end',type=day)
    parser.add_argument('--check',action='store_true',help='Check config and retained FIT coverage without Docker mutation or fetching')
    args=parser.parse_args(argv)
    if bool(args.start)!=bool(args.end): parser.error('Supply both --start and --end, or neither for today')
    if args.check and args.start: parser.error('--check does not accept fetch dates')
    today=datetime.now(ZoneInfo('America/Los_Angeles')).date();start=args.start or today;end=args.end or today
    if start>end: parser.error('Start date must not follow end date')
    try:
        if not args.repo.is_dir(): raise RuntimeError(f'Garmin checkout directory does not exist: {args.repo}')
        folder=retained_path(args.repo);print('Retained FIT directory: '+str(folder),flush=True)
        if not args.check: fetch(args.repo,start,end)
        summary,activities,_=inventory(folder,'garmin_local')
        print(f'Retained FIT files: {summary["fit_file_count"]}; parsed activities: {summary["activity_count"]}',flush=True)
        print('Oldest activity (LA): '+str(summary['oldest_start_local']),flush=True)
        print('Newest activity (LA): '+str(summary['newest_start_local']),flush=True)
        if summary['failed_file_count']: raise RuntimeError(f'{summary["failed_file_count"]} retained FIT files failed parsing; inspect source coverage report')
        if not args.check:
            in_range=[a for a in activities if start<=datetime.fromisoformat(a['start_utc']).astimezone(ZoneInfo('America/Los_Angeles')).date()<=end]
            if not in_range: raise RuntimeError('No valid retained FIT activity exists in the requested date range; fetch may have found no activities or failed to retain them')
            print(f'Valid retained activities in requested range: {len(in_range)}. File presence confirms retention, not complete Garmin server history.')
        return 0
    except (RuntimeError,OSError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__': raise SystemExit(main())
