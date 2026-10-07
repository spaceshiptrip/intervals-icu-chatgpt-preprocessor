"""Read-only source inventories and timestamp-based freshness checks; no GPS export."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fitdecode

LOCAL = ZoneInfo('America/Los_Angeles')


def timestamp(value, naive_zone=LOCAL):
    if not value: return None
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    return stamp.replace(tzinfo=naive_zone).astimezone(timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def fit_members(path):
    if path.is_dir():
        for member in sorted(path.rglob('*')):
            if member.is_file() and member.suffix.lower()=='.fit': yield str(member.relative_to(path)), member.read_bytes()
    elif path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.lower().endswith('.fit'): yield name, archive.read(name)
    elif path.suffix.lower()=='.fit': yield path.name, path.read_bytes()


def csv_records(path, garmin=False):
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as archive:
            if 'ActivitySummary.csv' not in archive.namelist(): return [], 0
            data=archive.read('ActivitySummary.csv').decode('utf-8-sig')
    else: data=path.read_text(encoding='utf-8-sig')
    rows=list(csv.DictReader(io.StringIO(data))); out=[]
    for row in rows:
        if garmin:
            if row.get('activityType','').lower() in ('no activity','') or row.get('activityName')=='END': continue
            key=row.get('ActivityID') or row.get('Activity_ID'); start=timestamp(row.get('time'),timezone.utc)
            sport=row.get('activityType'); distance=row.get('distance')
        else:
            key=row.get('id'); start=timestamp(row.get('Date')); sport=row.get('Type'); distance=row.get('Distance')
        if key and start: out.append({'activity_key':key,'start_utc':start.isoformat(),'sport':sport,'distance_m':float(distance) if distance else None})
    return out,len(rows)


def inventory(path, kind, rows=None, fit_count=None, failed_count=0):
    path=Path(path); activities=[]; count=0; csv_count=None; format_='fit'; errors=[]; members=[]
    if kind=='intervals_activities_csv':
        activities,csv_count=csv_records(path); format_='activities_csv'; count=csv_count
    elif rows is not None:
        activities=[{'activity_key':r.get('intervals_activity_id') or r['activity_id'],'start_utc':r['start_utc'],'sport':r['sport'],'distance_m':r.get('distance_m')} for r in rows]
        count=fit_count; errors=['FIT parse failures']*failed_count
    else:
        for name,content in fit_members(path):
            count+=1; members.append({'source_member':name,'sha256':hashlib.sha256(content).hexdigest()})
            try:
                sessions=[]; file_type=None
                with fitdecode.FitReader(io.BytesIO(content),check_crc=fitdecode.CrcCheck.RAISE) as fit:
                    for frame in fit:
                        if not isinstance(frame,fitdecode.FitDataMessage): continue
                        if frame.name not in ('file_id','session'): continue
                        fields={f.name:f.value for f in frame.fields}
                        if frame.name=='file_id': file_type=fields.get('type')
                        else: sessions.append(fields)
                starts=[timestamp(s.get('start_time'),timezone.utc) for s in sessions if s.get('start_time')]
                if not starts or file_type not in (None,4,'activity'): continue
                values=[s.get('total_distance') for s in sessions]
                activities.append({'activity_key':Path(name).name.split('_',1)[0], 'start_utc':min(starts).isoformat(),
                    'sport':str(sessions[0].get('sport')),'distance_m':sum(values) if all(v is not None for v in values) else None})
            except Exception as exc: errors.append(f'{name}: {type(exc).__name__}: {exc}')
        if not count and kind=='garmin_local':
            activities,csv_count=csv_records(path,garmin=True) if path.is_file() else ([],0); format_='garmin_index_only_no_fit' if path.is_file() else 'garmin_fit_directory_empty'; count=0
    starts=sorted(a['start_utc'] for a in activities); keys=Counter(a['activity_key'] for a in activities)
    result={'source_kind':kind,'source_path':str(path.resolve()),'source_filename':path.name,
        'source_sha256':digest(path) if path.is_file() else None,'format':format_,
        'used_for_activity_detail':kind=='intervals_fit','fit_file_count':count if format_!='activities_csv' else 0,
        'csv_row_count':csv_count,'activity_count':len(activities),'unique_activity_count':len(keys),
        'oldest_start_utc':starts[0] if starts else None,'newest_start_utc':starts[-1] if starts else None,
        'oldest_start_local':timestamp(starts[0]).astimezone(LOCAL).isoformat() if starts else None,
        'newest_start_local':timestamp(starts[-1]).astimezone(LOCAL).isoformat() if starts else None,
        'duplicate_activity_keys':[k for k,v in keys.items() if v>1], 'failed_file_count':len(errors),'errors':errors}
    return result,activities,members


def default_garmin_sources():
    exports=Path(__file__).resolve().parents[2]/'garmin-grafana'/'exports'
    filestore=exports.parent/'fit_filestore'
    return ([filestore] if filestore.exists() else []) + (sorted([*exports.glob('Garmin_Activities*.zip'),*exports.glob('Garmin_Incremental*.zip')]) if exports.exists() else [])


def coverage_report(intervals_path, csv_path=None, garmin_paths=(), parsed_rows=None, fit_count=None, failed_count=0):
    summaries=[]; details=[]; members=[]; warnings=[]
    s,fit,files=inventory(intervals_path,'intervals_fit',parsed_rows,fit_count,failed_count);summaries.append(s);details.extend(dict(a,source_kind='intervals_fit',source_filename=s['source_filename']) for a in fit);members.extend(files)
    indexed=[]
    if csv_path:
        s,indexed,_=inventory(csv_path,'intervals_activities_csv');summaries.append(s);details.extend(dict(a,source_kind='intervals_activities_csv',source_filename=s['source_filename']) for a in indexed)
        missing_fit=sorted({a['activity_key'] for a in indexed}-{a['activity_key'] for a in fit})
        missing_csv=sorted({a['activity_key'] for a in fit}-{a['activity_key'] for a in indexed})
        if missing_fit: warnings.append(f'{len(missing_fit)} CSV activities have no FIT detail; they are not substituted into canonical workouts')
        if missing_csv: warnings.append(f'{len(missing_csv)} FIT activities are absent from the CSV index')
    else: missing_fit=[]; missing_csv=[];warnings.append('No Intervals CSV cross-check supplied')
    garmin=[]; native_garmin=[]; native_members=[]
    for path in garmin_paths:
        s,acts,gmembers=inventory(path,'garmin_local');
        if s['format']=='fit': native_garmin.extend(acts); native_members.extend(dict(m,source_filename=s['source_filename']) for m in gmembers)
        summaries.append(s);garmin.extend(acts);details.extend(dict(a,source_kind='garmin_local',source_filename=s['source_filename']) for a in acts)
        if s['format']=='garmin_fit_directory_empty': warnings.append(f'{s["source_filename"]}: retained-FIT directory exists but is empty; native Garmin freshness is unverified')
        if s['format']=='garmin_index_only_no_fit': warnings.append(f'{s["source_filename"]}: zero raw FIT files; Garmin comparison uses an activity index only')
    if not garmin_paths: warnings.append('Separate local Garmin FIT source not located/provided; independent Garmin freshness cannot be verified')
    # Indices from overlapping local snapshots may repeat IDs; report coverage once.
    unique_garmin={(a['activity_key'],a['start_utc']):a for a in garmin}
    repeat=len(garmin)-len(unique_garmin)
    if repeat: warnings.append(f'{repeat} Garmin index entries repeat across snapshots; comparison deduplicates ID + start timestamp')
    if fit and garmin:
        newest_fit=max(a['start_utc'] for a in fit);newest_g=max(a['start_utc'] for a in garmin)
        if timestamp(newest_fit)>timestamp(newest_g): warnings.append('Local Garmin source/index is stale relative to Intervals by activity start timestamps')
        elif timestamp(newest_g)>timestamp(newest_fit): warnings.append('Intervals FIT export is stale relative to the local Garmin source/index by activity start timestamps')
        absent=[]
        for a in unique_garmin.values():
            # IDs differ across services; use tightly matching starts and distance.
            matches=[b for b in fit if abs((timestamp(a['start_utc'])-timestamp(b['start_utc'])).total_seconds())<=5 and
                (a['distance_m'] is None or b['distance_m'] is None or abs(a['distance_m']-b['distance_m'])<=max(100,a['distance_m']*.05))]
            if not matches: absent.append(a['activity_key'])
        if absent: warnings.append(f'{len(absent)} local Garmin index activities have no close start/distance match in the Intervals FIT set')
    else: absent=[]
    missing_native=[]
    if parsed_rows is not None:
        for row in parsed_rows:
            if row.get('device_family')!='Garmin': continue
            if not any(abs((timestamp(row['start_utc'])-timestamp(a['start_utc'])).total_seconds())<=5 and
                (row.get('distance_m') is None or a['distance_m'] is None or abs(row['distance_m']-a['distance_m'])<=max(100,row['distance_m']*.05)) for a in native_garmin):
                missing_native.append(row.get('intervals_activity_id') or row['activity_id'])
        if missing_native: warnings.append(f'{len(missing_native)} Garmin-coded Intervals activities have no retained native FIT counterpart; local retained history is incomplete')
    hashes=Counter(m['sha256'] for m in members)
    duplicate_payloads=sum(v-1 for v in hashes.values() if v>1)
    if duplicate_payloads: warnings.append(f'{duplicate_payloads} FIT payloads are byte-identical copies under multiple members; inspect duplicate coverage')
    for s in summaries:
        if s['duplicate_activity_keys']: warnings.append(f'{s["source_filename"]}: repeated activity IDs within one source; inspect suspicious duplicate coverage')
        if s['failed_file_count']: warnings.append(f'{s["source_filename"]}: {s["failed_file_count"]} failed FIT files')
    if indexed and fit and max(a['start_utc'] for a in indexed)!=max(a['start_utc'] for a in fit): warnings.append('Intervals CSV and FIT newest activity timestamps disagree')
    report={'coverage_schema_version':1,'timezone':'America/Los_Angeles','freshness_basis':'activity_start_timestamps_not_download_time',
        'sources':summaries,'warnings':warnings,'csv_without_fit_ids':missing_fit,'fit_without_csv_ids':missing_csv,
        'garmin_without_intervals_match_ids':absent,'intervals_garmin_without_native_fit_ids':missing_native,'garmin_fit_members':native_members,'garmin_fit_file_count':sum(s['fit_file_count'] for s in summaries if s['source_kind']=='garmin_local'), 'garmin_unique_activity_count':len(unique_garmin),'duplicate_fit_payload_count':duplicate_payloads,'fit_members':members}
    return report,details


def print_coverage(report, canonical=None):
    print('Source coverage (activity timestamps; download times are not freshness evidence):',flush=True)
    for s in report['sources']:
        print(f'  {s["source_kind"]}: {s["source_filename"]}; {s["format"]}; FIT={s["fit_file_count"]}, CSV rows={s["csv_row_count"]}, activities={s["activity_count"]}; {s["oldest_start_local"]} → {s["newest_start_local"]}',flush=True)
    for warning in report['warnings']: print('  WARNING: '+warning,flush=True)
    if canonical is not None: print('  Newest canonical workout: '+str(max((w['start_local'] for w in canonical),default=None)),flush=True)


def shareable_coverage(value):
    """Remove local input directories from the upload-facing coverage report."""
    if isinstance(value, dict):
        return {k: Path(v).name if k == 'source_path' and isinstance(v, str) else shareable_coverage(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shareable_coverage(v) for v in value]
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--intervals-fit',type=Path,required=True);parser.add_argument('--activities-csv',type=Path)
    parser.add_argument('--garmin-source',type=Path,action='append');parser.add_argument('--output',type=Path,default=Path('output'))
    args=parser.parse_args();report,details=coverage_report(args.intervals_fit,args.activities_csv,args.garmin_source if args.garmin_source is not None else default_garmin_sources());print_coverage(report)
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'coverage_report.json').write_text(json.dumps(report,indent=2)+'\n')
    with (args.output/'source_inventory.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['source_kind','source_filename','activity_key','start_utc','sport','distance_m']);writer.writeheader();writer.writerows(details)

if __name__=='__main__': main()
