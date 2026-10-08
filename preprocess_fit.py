#!/usr/bin/env python3
"""Normalize FIT archives without altering originals; see README.md for semantics."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import statistics
import tempfile
import warnings
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fitdecode
from canonical_workouts import SCHEMA_VERSION, EXPORT_HEADERS, canonical_summaries, load_resolutions, reconstruct, stable_id
from canonical_snapshot import build_snapshot
from source_coverage import coverage_report, print_coverage, default_garmin_sources, shareable_coverage

LOCAL = ZoneInfo('America/Los_Angeles')
MILE = 1609.344
METRICS = {
 'distance_m': ('total_distance',), 'timer_duration_s': ('total_timer_time',),
 'moving_duration_s': ('total_moving_time',), 'elapsed_duration_s': ('total_elapsed_time',),
 'avg_hr_bpm': ('avg_heart_rate',), 'max_hr_bpm': ('max_heart_rate',),
 'avg_cadence_fit_rpm': ('avg_running_cadence','avg_cadence'),
 'max_cadence_fit_rpm': ('max_running_cadence','max_cadence'),
 'avg_speed_mps': ('enhanced_avg_speed','avg_speed'), 'max_speed_mps': ('enhanced_max_speed','max_speed'),
 'ascent_m': ('total_ascent',), 'descent_m': ('total_descent',), 'calories_kcal': ('total_calories',),
 'aerobic_training_effect': ('total_training_effect',), 'anaerobic_training_effect': ('total_anaerobic_training_effect',),
 'training_load': ('training_load_peak', 'training_load'), 'recovery_time': ('recovery_time',),
 'vo2_max': ('vo2_max',), 'normalized_power_w': ('normalized_power',),
 'avg_power_w': ('avg_power',), 'max_power_w': ('max_power',),
 'avg_temperature_c': ('avg_temperature',), 'max_temperature_c': ('max_temperature',),
 'min_altitude_m': ('enhanced_min_altitude','min_altitude'),
 'max_altitude_m': ('enhanced_max_altitude','max_altitude'),
 'training_stress_score': ('training_stress_score',), 'intensity_factor': ('intensity_factor',),
}

def safe(value):
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, (list,tuple)): return [safe(v) for v in value]
    if isinstance(value, bytes): return value.hex()
    return value

def number(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError): return None

def first(d, names):
    return next((d[n] for n in names if d.get(n) is not None), None)

def iso(dt): return dt.isoformat() if isinstance(dt,datetime) else None

def times(row, prefix, dt):
    row[prefix+'_utc']=iso(dt)
    row[prefix+'_local']=iso(dt.astimezone(LOCAL)) if isinstance(dt,datetime) else None

def metrics(d):
    row={k:first(d,names) for k,names in METRICS.items()}
    distance=number(row['distance_m'])
    row['distance_miles']=distance/MILE if distance is not None else None
    for label, duration in [('timer',row['timer_duration_s']),('moving',row['moving_duration_s']),('elapsed',row['elapsed_duration_s'])]:
        row[label+'_pace_min_mile']=duration/60/(distance/MILE) if distance and duration is not None else None
    e,t=row['elapsed_duration_s'],row['timer_duration_s']
    row['elapsed_minus_timer_s']=max(0,e-t) if e is not None and t is not None else None
    return row

def family(manufacturer, product):
    m=str(manufacturer or '').lower()
    if m=='garmin' or manufacturer==1: return 'Garmin'
    if any(x in m for x in ('amazfit','huami','zepp')): return 'Amazfit'
    if not m or m in ('development','unknown') or 'intervals.icu' in str(product).lower(): return 'Unknown'
    return 'Other'

def is_location_field(name):
    normalized=str(name).lower()
    return any(word in normalized for word in ('position','latitude','longitude')) or bool(re.search(r'(^|[_. -])(lat|lon|lng)([_. -]|$)',normalized))

def write_csv(path, rows, base=()):
    fields=list(dict.fromkeys([*base,*(k for row in rows for k in row)]))
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v,default=safe,sort_keys=True) if isinstance(v,(dict,list)) else (round(v,6) if isinstance(v,float) else v) for k,v in row.items()})

def read_csv(path):
    if not path: return []
    with Path(path).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def publish_package(output, files, archive=False):
    """Replace the canonical ZIP atomically, then optionally snapshot its bytes."""
    output.mkdir(parents=True,exist_ok=True)
    current=output/'Garmin_Amazfit_Training_Normalized.zip'
    with tempfile.NamedTemporaryFile(prefix='.normalized_',suffix='.zip',dir=output,delete=False) as f:
        temporary=Path(f.name)
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
            for name,path in files.items(): z.write(path,arcname=name)
        temporary.replace(current)
    finally:
        temporary.unlink(missing_ok=True)
    snapshot=None
    if archive:
        directory=output/'archive'
        directory.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(LOCAL).strftime('%Y-%m-%d_%H%M%S_%f')
        stem=f'Garmin_Amazfit_Training_Normalized_{stamp}'
        counter=0
        while True:
            snapshot=directory/(stem+(f'_{counter}' if counter else '')+'.zip')
            try:
                target=snapshot.open('xb')
                break
            except FileExistsError:
                counter+=1
        try:
            with target, current.open('rb') as source: shutil.copyfileobj(source,target)
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise
    return current,snapshot

def sources(path):
    if path.is_dir():
        for p in sorted(path.rglob('*')):
            if p.is_file() and p.suffix.lower()=='.fit': yield str(p.relative_to(path)),p.read_bytes()
    elif path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as z:
            for info in sorted(z.infolist(),key=lambda x:x.filename):
                if not info.is_dir() and info.filename.lower().endswith('.fit'):
                    yield info.filename,z.read(info)
    elif path.suffix.lower()=='.fit': yield path.name,path.read_bytes()
    else: raise ValueError('Input must be a FIT file, FIT directory, or ZIP archive')

def parse(name, content, metadata, override, timeline_sink=None):
    messages=defaultdict(list); field_units={}; diagnostics=[]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with fitdecode.FitReader(io.BytesIO(content),check_crc=fitdecode.CrcCheck.RAISE,error_handling=fitdecode.ErrorHandling.RAISE) as reader:
            for msg in reader:
                if isinstance(msg,fitdecode.FitDataMessage):
                    d={}
                    for field in msg.fields:
                        if field.value is not None:
                            key=field.name or f'field_{field.def_num}'
                            d[key]=field.value
                            field_units[msg.name+'.'+key]=field.units
                    messages[msg.name].append(d)
        diagnostics=[str(w.message) for w in caught]
    sessions=messages['session']
    fid=messages['file_id'][0] if messages['file_id'] else {}
    if fid.get('type') not in (None,'activity',4) or not sessions:
        return None,[],[],['non_activity_or_no_session'],{}
    starts=[s['start_time'] for s in sessions if isinstance(s.get('start_time'),datetime)]
    ends=[s['timestamp'] for s in sessions if isinstance(s.get('timestamp'),datetime)]
    if not starts: return None,[],[],['missing_session_start'],{}
    # FIT multisport files remain one activity; preserve each session separately as JSON.
    s=dict(sessions[0])
    if len(sessions)>1:
        for key in ('total_distance','total_elapsed_time','total_timer_time','total_moving_time','total_ascent','total_descent','total_calories'):
            vals=[x[key] for x in sessions if x.get(key) is not None]
            s[key]=sum(vals) if len(vals)==len(sessions) else None
        for key in ('avg_heart_rate','avg_cadence','avg_running_cadence','avg_speed','enhanced_avg_speed','avg_power'):
            valid=[x for x in sessions if x.get(key) is not None and x.get('total_timer_time',0)>0]
            s[key]=sum(x[key]*x['total_timer_time'] for x in valid)/sum(x['total_timer_time'] for x in valid) if valid else None
        for key in ('max_heart_rate','max_speed','enhanced_max_speed','max_power','max_cadence','max_running_cadence'):
            vals=[x[key] for x in sessions if x.get(key) is not None]; s[key]=max(vals) if vals else None
        s['sport']='multisport'; s['sub_sport']=None
    recording=next((d for d in messages['device_info'] if d.get('device_index') in (0,'creator')), {})
    manufacturer=first(recording,('manufacturer',)) or fid.get('manufacturer')
    product=first(recording,('product_name','garmin_product','product')) or first(fid,('product_name','garmin_product','product'))
    activity_id='fit_'+hashlib.sha256(name.encode()+b'\0'+content).hexdigest()[:16]
    intervals_id=Path(name).name.split('_',1)[0]
    row={'activity_id':activity_id,'intervals_activity_id':intervals_id,'source_filename':name,
         'content_sha256':hashlib.sha256(content).hexdigest(), 'device_family':family(manufacturer,product),
         'device_identification_source':'FIT metadata' if family(manufacturer,product)!='Unknown' else 'unavailable',
         'manufacturer':manufacturer,'fit_product_model':product,'file_id_metadata_json':{k:safe(v) for k,v in fid.items() if not is_location_field(k)},'product_model':product,'serial_number':first(recording,('serial_number',)) or fid.get('serial_number'),
         'software_version':recording.get('software_version'),'file_creation_utc':iso(fid.get('time_created')),
         'sport':s.get('sport'),'sub_sport':s.get('sub_sport'), 'activity_name':metadata.get('Name') or s.get('name'),
         'session_count':len(sessions),'lap_count':len(messages['lap']), 'record_count':len(messages['record']),
         'elevation_source':'unknown','original_ascent_m':None,'original_descent_m':None,
         'intervals_corrected_ascent_m':None,'intervals_corrected_descent_m':None,
         **metrics(s)}
    times(row,'start',min(starts)); times(row,'end',max(ends) if ends else min(starts)+timedelta(seconds=row.get('elapsed_duration_s') or 0))
    row['end_time_source']='session timestamp' if ends else 'start plus elapsed fallback'
    row['terrain_type']='trail' if s.get('sub_sport')=='trail' or metadata.get('Type')=='TrailRun' else ('road_or_unspecified' if s.get('sport')=='running' else 'other')
    if override.get('device_family'):
        if override['device_family'] not in ('Garmin','Amazfit','Other','Unknown'): raise ValueError('Invalid device_family override')
        row['device_family']=override['device_family']; row['device_identification_source']='user mapping'
    for key in ('elevation_source','product_model'):
        if override.get(key): row[key]=override[key]
    for key in ('original_ascent_m','original_descent_m','intervals_corrected_ascent_m','intervals_corrected_descent_m'):
        row[key]=number(override.get(key))
    if row['elevation_source']=='intervals_corrected':
        for kind in ('ascent','descent'):
            if row['intervals_corrected_'+kind+'_m'] is None: row['intervals_corrected_'+kind+'_m']=row[kind+'_m']
    elif row['elevation_source']=='original':
        for kind in ('ascent','descent'):
            if row['original_'+kind+'_m'] is None: row['original_'+kind+'_m']=row[kind+'_m']
    row['intervals_load']=number(metadata.get('Load'))
    row['intervals_moving_duration_s']=number(metadata.get('Moving Time'))
    row['intervals_distance_m']=number(metadata.get('Distance'))
    # Preserve useful native/developer session fields, excluding location and duplicate timestamps.
    row['session_metrics_json']=[{k:safe(v) for k,v in x.items() if not is_location_field(k) and k not in ('timestamp','start_time')} for x in sessions]
    row['session_units_json']={k:v for k,v in field_units.items() if k.startswith('session.') and not is_location_field(k)}
    row['device_metadata_json']=[{k:safe(v) for k,v in d.items() if not is_location_field(k)} for d in messages['device_info']]
    stops=[e for e in messages['event'] if e.get('event')=='timer' and e.get('event_type') in ('stop','stop_all','stop_disable','stop_disable_all')]
    unique_stops={iso(e.get('timestamp')) for e in stops if isinstance(e.get('timestamp'),datetime)}
    row['timer_stop_event_count']=len(unique_stops) if messages['event'] else None
    row['pause_count']=sum(1 for stop in unique_stops if any(e.get('event')=='timer' and e.get('event_type')=='start' and iso(e.get('timestamp')) and iso(e['timestamp'])>stop for e in messages['event'])) if messages['event'] else None
    laps=[]
    for i,lap in enumerate(messages['lap'],1):
        lr={'activity_id':activity_id,'device_family':row['device_family'],'lap_number':i,**metrics(lap)}
        times(lr,'start',lap.get('start_time')); times(lr,'end',lap.get('timestamp'))
        lr['lap_metrics_json']={k:safe(v) for k,v in lap.items() if not is_location_field(k) and k not in ('timestamp','start_time')}
        laps.append(lr)
    records=[]
    for record in messages['record']:
        rr={'activity_id':activity_id}; times(rr,'timestamp',record.get('timestamp'))
        for dest, keys in {'distance_m':('distance',),'hr_bpm':('heart_rate',),'cadence_fit_rpm':('cadence',),'altitude_m':('enhanced_altitude','altitude'),'speed_mps':('enhanced_speed','speed'),'power_w':('power',)}.items(): rr[dest]=first(record,keys)
        for dest, key in [('latitude_deg','position_lat'),('longitude_deg','position_long')]:
            val=record.get(key); rr[dest]=val*180/(2**31) if val is not None else None
        records.append(rr)
    if timeline_sink is not None:
        timeline_sink[activity_id]={'records':records,'timer_events':[
            {'timestamp_utc':iso(e.get('timestamp')),'event_type':e.get('event_type')}
            for e in messages['event'] if e.get('event')=='timer' and isinstance(e.get('timestamp'),datetime)]}
    return row,laps,records,diagnostics,field_units

def match(a,b):
    if a['sport']!=b['sport']: return None
    sa,sb=(datetime.fromisoformat(x['start_utc']) for x in (a,b))
    gap=abs((sa-sb).total_seconds())
    if gap>300: return None
    ea,eb=(datetime.fromisoformat(x['end_utc']) for x in (a,b))
    shortest=min((ea-sa).total_seconds(),(eb-sb).total_seconds())
    overlap=max(0,(min(ea,eb)-max(sa,sb)).total_seconds())/shortest if shortest>0 else 0
    if overlap<0.5: return None
    da,db=a['distance_m'],b['distance_m']
    delta=abs(da-db) if da is not None and db is not None else None
    pct=100*delta/max(da,db) if delta is not None and max(da,db)>0 else None
    duration_ratio=min(a['elapsed_duration_s'] or 0,b['elapsed_duration_s'] or 0)/max(a['elapsed_duration_s'] or 0,b['elapsed_duration_s'] or 0,1)
    exact=a['content_sha256']==b['content_sha256']
    ta,tb=a.get('timer_duration_s'),b.get('timer_duration_s')
    timer_ratio=min(ta,tb)/max(ta,tb) if ta and tb and ta>0 and tb>0 else None
    timer_match=gap<=120 and overlap>=.9 and pct is not None and pct<=10 and timer_ratio is not None and timer_ratio>=.8
    confidence='high' if exact or (gap<=120 and overlap>=.9 and duration_ratio>=.8 and pct is not None and pct<=10) else ('medium' if (overlap>=.8 and duration_ratio>=.7 and pct is not None and pct<=25) or timer_match else 'low')
    reason='identical FIT content' if exact else 'same sport; starts within 300 s; overlapping elapsed windows; distance/duration similarity assessed'
    if timer_match and duration_ratio<.7: reason+='; matching timer durations despite different elapsed windows'
    return {'start_difference_s':gap,'distance_difference_m':delta,'distance_difference_pct':pct,'overlap_fraction':overlap,'duration_ratio':duration_ratio,'timer_duration_ratio':timer_ratio,'confidence':confidence,'reason':reason}

def duplicates(rows):
    pairs=[]; clusters=[]
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            evidence=match(a,b)
            if evidence: pairs.append({'activity_id_a':a['activity_id'],'activity_id_b':b['activity_id'], 'device_a':a['device_family'],'device_b':b['device_family'],**evidence})
    lookup={r['activity_id']:r for r in rows}
    strong={frozenset((p['activity_id_a'],p['activity_id_b'])) for p in pairs if p['confidence']!='low'}
    # Complete-link groups avoid chaining separate or partial workouts through one long recording.
    for row in rows:
        aid=row['activity_id']
        group=next((g for g in clusters if all(frozenset((aid,x)) in strong for x in g)),None)
        if group is None: clusters.append([aid])
        else: group.append(aid)
    rank={'Garmin':0,'Amazfit':1,'Other':2,'Unknown':3}
    for group in clusters:
        gid='dup_'+hashlib.sha256('|'.join(sorted(group)).encode()).hexdigest()[:12] if len(group)>1 else None
        primary=min(group,key=lambda x:(rank[lookup[x]['device_family']], -(lookup[x]['record_count'] or 0),x))
        for aid in group:
            lookup[aid].update(duplicate_group_id=gid,preferred_training_record=aid==primary,
                               contributes_to_training_totals=aid==primary,composite_duplicate_group_id=None,composite_role=None,
                               secondary_comparison_available=len(group)>1,preference_reason='device priority; record count; stable ID tie-break')
    for pair in pairs:
        a,b=(lookup[pair[k]] for k in ('activity_id_a','activity_id_b'))
        pair['duplicate_group_id']=a['duplicate_group_id'] if a['duplicate_group_id']==b['duplicate_group_id'] else None
        pair['grouped_for_training']=pair['duplicate_group_id'] is not None
        pair['duration_difference_s']=abs(a['elapsed_duration_s']-b['elapsed_duration_s']) if a['elapsed_duration_s'] is not None and b['elapsed_duration_s'] is not None else None
    return pairs

def composite_duplicates(rows,pairs):
    """Match a continuous known-device activity to sequential other-device segments.

    Compare full windows and summed distance, allowing stops between segments.
    Requiring all-pair sequentiality prevents overlapping watches/segments from
    being summed, while disjoint accepted memberships avoid competing groups.
    """
    rank={'Garmin':0,'Amazfit':1,'Other':2}
    lookup={r['activity_id']:r for r in rows}
    windows={r['activity_id']:(datetime.fromisoformat(r['start_utc']),datetime.fromisoformat(r['end_utc'])) for r in rows}
    candidates=[]
    for continuous in rows:
        if continuous['device_family'] not in rank or not continuous.get('distance_m'): continue
        start,end=windows[continuous['activity_id']]
        duration=(end-start).total_seconds()
        if duration<=0: continue
        for device in rank:
            if device==continuous['device_family']: continue
            segments=[]
            for r in rows:
                if r['device_family']!=device or r['sport']!=continuous['sport'] or not r.get('distance_m'): continue
                rs,re=windows[r['activity_id']]
                if re>rs and rs>=start-timedelta(seconds=300) and re<=end+timedelta(seconds=300) and min(end,re)>max(start,rs): segments.append(r)
            segments.sort(key=lambda r:(r['start_utc'],r['activity_id']))
            for i in range(len(segments)):
                for j in range(i+2,len(segments)+1):
                    chosen=segments[i:j]
                    first_start=windows[chosen[0]['activity_id']][0]
                    last_end=windows[chosen[-1]['activity_id']][1]
                    start_gap=abs((first_start-start).total_seconds())
                    end_gap=abs((last_end-end).total_seconds())
                    if start_gap>300 or end_gap>300: continue
                    gaps=[(windows[b['activity_id']][0]-windows[a['activity_id']][1]).total_seconds() for a,b in zip(chosen,chosen[1:])]
                    if any(gap < -5 or gap>300 for gap in gaps): continue
                    # Union of clipped segment windows; tolerate <=5 s timestamp jitter.
                    covered=0; previous_end=start
                    for segment in chosen:
                        ss,se=windows[segment['activity_id']]
                        covered+=max(0,(min(end,se)-max(start,ss,previous_end)).total_seconds())
                        previous_end=max(previous_end,se)
                    coverage=covered/duration
                    distance=sum(r['distance_m'] for r in chosen)
                    difference=distance-continuous['distance_m']
                    pct=100*abs(difference)/max(distance,continuous['distance_m'])
                    if coverage<.8 or pct>25: continue
                    ids=[continuous['activity_id'],*(r['activity_id'] for r in chosen)]
                    # Do not break an existing pair with an unrelated outside recording.
                    existing={r['duplicate_group_id'] for r in [continuous,*chosen] if r['duplicate_group_id']}
                    if any(r['duplicate_group_id'] in existing and r['activity_id'] not in ids for r in rows): continue
                    high=start_gap<=120 and end_gap<=120 and coverage>=.9 and pct<=10
                    candidates.append({'composite_duplicate_group_id':'composite_'+hashlib.sha256('|'.join(sorted(ids)).encode()).hexdigest()[:12],
                        'continuous_activity_id':continuous['activity_id'],'segment_activity_ids':[r['activity_id'] for r in chosen],
                        'continuous_device':continuous['device_family'],'segment_device':device,'sport':continuous['sport'],
                        'segment_count':len(chosen),'continuous_distance_m':continuous['distance_m'],'segments_distance_m':distance,
                        'segments_minus_continuous_distance_m':difference,'distance_difference_pct':pct,
                        'continuous_start_utc':iso(start),'continuous_end_utc':iso(end),
                        'segments_start_utc':iso(first_start),'segments_end_utc':iso(last_end),
                        'start_difference_s':start_gap,'end_difference_s':end_gap,'segment_window_coverage_fraction':coverage,
                        'gap_between_segments_s':sum(max(0,g) for g in gaps),
                        'segments_elapsed_sum_s':sum((windows[r['activity_id']][1]-windows[r['activity_id']][0]).total_seconds() for r in chosen),
                        'segments_time_window_s':(last_end-first_start).total_seconds(),
                        'confidence':'high' if high else 'medium',
                        'reason':'same sport; sequential other-device segments; summed distance and full elapsed window match'})
    accepted=[]; used=set()
    candidates.sort(key=lambda c:(c['confidence']!='high',c['distance_difference_pct'],c['start_difference_s']+c['end_difference_s'],c['composite_duplicate_group_id']))
    for group in candidates:
        ids=[group['continuous_activity_id'],*group['segment_activity_ids']]
        if used.intersection(ids): continue
        used.update(ids); accepted.append(group)
        prefer_segments=rank[group['segment_device']]<rank[group['continuous_device']]
        group['preferred_source_role']='segment' if prefer_segments else 'continuous'
        for aid in ids:
            row=lookup[aid]; role='continuous' if aid==group['continuous_activity_id'] else 'segment'
            contributes=(role=='segment')==prefer_segments
            row.update(composite_duplicate_group_id=group['composite_duplicate_group_id'],composite_role=role,
                duplicate_group_id=group['composite_duplicate_group_id'],preferred_training_record=contributes,
                contributes_to_training_totals=contributes,secondary_comparison_available=True,
                preference_reason='composite group: preferred device segments collectively' if prefer_segments else 'composite group: preferred continuous device')
    for pair in pairs:
        a,b=lookup[pair['activity_id_a']],lookup[pair['activity_id_b']]
        pair['composite_duplicate_group_id']=a['composite_duplicate_group_id'] if a['composite_duplicate_group_id']==b['composite_duplicate_group_id'] else None
        pair['duplicate_group_id']=a['duplicate_group_id'] if a['duplicate_group_id']==b['duplicate_group_id'] else None
        pair['grouped_for_training']=pair['duplicate_group_id'] is not None
    return accepted

def composite_comparisons(rows,groups):
    """Compare a virtual combined segment record; never add it to master rows."""
    lookup={r['activity_id']:r for r in rows}; out=[]
    for group in groups:
        segments=[lookup[aid] for aid in group['segment_activity_ids']]
        continuous=lookup[group['continuous_activity_id']]
        combined=dict(segments[0]); combined['activity_id']=group['composite_duplicate_group_id']+'_segments'
        combined['start_utc']=group['segments_start_utc']; combined['end_utc']=group['segments_end_utc']
        additive=('distance_m','timer_duration_s','moving_duration_s','elapsed_duration_s','ascent_m','descent_m','calories_kcal','original_ascent_m','original_descent_m','intervals_corrected_ascent_m','intervals_corrected_descent_m')
        for key in additive:
            values=[r.get(key) for r in segments]
            combined[key]=sum(values) if all(v is not None for v in values) else None
        for key in ('avg_hr_bpm','avg_cadence_fit_rpm'):
            complete=all(r.get(key) is not None and (r.get('timer_duration_s') or 0)>0 for r in segments)
            combined[key]=sum(r[key]*r['timer_duration_s'] for r in segments)/sum(r['timer_duration_s'] for r in segments) if complete else None
        for key in ('max_hr_bpm','max_cadence_fit_rpm'):
            values=[r.get(key) for r in segments]; combined[key]=max(values) if all(v is not None for v in values) else None
        combined['terrain_type']='trail' if any(r['terrain_type']=='trail' for r in segments) else segments[0]['terrain_type']
        sources={r['elevation_source'] for r in segments}; combined['elevation_source']=next(iter(sources)) if len(sources)==1 else 'mixed'
        for label in ('timer','moving','elapsed'):
            duration=combined[label+'_duration_s']; distance=combined['distance_m']
            combined[label+'_pace_min_mile']=duration/60/(distance/MILE) if duration is not None and distance else None
        e,t=combined['elapsed_duration_s'],combined['timer_duration_s']
        combined['elapsed_minus_timer_s']=max(0,e-t) if e is not None and t is not None else None
        pair={'activity_id_a':combined['activity_id'],'activity_id_b':continuous['activity_id'],'duplicate_group_id':group['composite_duplicate_group_id'],'confidence':group['confidence']}
        comparison=comparisons([combined,continuous],[pair])[0]
        comparison.update(comparison_type='composite',composite_duplicate_group_id=group['composite_duplicate_group_id'],
            continuous_activity_id=continuous['activity_id'],segment_activity_ids=group['segment_activity_ids'],
            segment_elapsed_sum_s=group['segments_elapsed_sum_s'],segment_time_window_s=group['segments_time_window_s'])
        out.append(comparison)
    return out

def comparisons(rows,pairs):
    lookup={r['activity_id']:r for r in rows}; out=[]
    for p in pairs:
        a,b=lookup[p['activity_id_a']],lookup[p['activity_id_b']]
        if a['device_family']=='Amazfit' and b['device_family']=='Garmin': a,b=b,a
        r={'duplicate_group_id':p['duplicate_group_id'],'comparison_type':'pair','composite_duplicate_group_id':p.get('composite_duplicate_group_id'),'activity_id_a':a['activity_id'],'activity_id_b':b['activity_id'],
           'device_a':a['device_family'],'device_b':b['device_family'],'confidence':p['confidence'],
           'terrain_type':'trail' if 'trail' in (a['terrain_type'],b['terrain_type']) else a['terrain_type'],
           'difference_direction':'B minus A','elevation_source_a':a['elevation_source'],'elevation_source_b':b['elevation_source']}
        for key in ('distance_m','elapsed_duration_s','timer_duration_s','moving_duration_s','timer_pace_min_mile','elapsed_pace_min_mile','avg_hr_bpm','max_hr_bpm','ascent_m','descent_m','avg_cadence_fit_rpm','max_cadence_fit_rpm','elapsed_minus_timer_s'):
            va,vb=a.get(key),b.get(key); r[key+'_a']=va; r[key+'_b']=vb
            diff=vb-va if va is not None and vb is not None else None
            r[key+'_difference']=diff; r[key+'_difference_pct']=100*diff/va if diff is not None and va else None
            if key in ('ascent_m','descent_m'): r[key+'_absolute_difference']=abs(diff) if diff is not None else None
        garmin=next((x for x in (a,b) if x['device_family']=='Garmin'),{})
        amazfit=next((x for x in (a,b) if x['device_family']=='Amazfit'),{})
        for kind in ('ascent','descent'):
            ref=garmin.get(kind+'_m'); r['garmin_'+kind+'_m']=ref
            r['amazfit_exported_'+kind+'_m']=amazfit.get(kind+'_m')
            for source in ('original','intervals_corrected'):
                val=amazfit.get(source+'_'+kind+'_m'); r['amazfit_'+source+'_'+kind+'_m']=val
                diff=val-ref if val is not None and ref is not None else None
                r['amazfit_'+source+'_'+kind+'_difference_m']=diff
                r['amazfit_'+source+'_'+kind+'_absolute_difference_m']=abs(diff) if diff is not None else None
                r['amazfit_'+source+'_'+kind+'_difference_pct']=100*diff/ref if diff is not None and ref else None
        out.append(r)
    return out

def elevation_summary(pairs):
    out=[]
    for terrain in ('road_or_unspecified','trail'):
        for source in ('exported','original','intervals_corrected'):
            for kind in ('ascent','descent'):
                differences=[]; percents=[]
                for p in pairs:
                    if p['terrain_type']!=terrain or p['confidence']=='low': continue
                    if p.get('comparison_type')=='pair' and p.get('composite_duplicate_group_id'): continue
                    ref=p.get('garmin_'+kind+'_m'); val=p.get('amazfit_'+source+'_'+kind+'_m')
                    if ref is not None and val is not None:
                        differences.append(val-ref)
                        if ref: percents.append(100*(val-ref)/ref)
                out.append({'terrain_type':terrain,'amazfit_elevation_type':source,'metric':kind,'pair_count':len(differences),
                    'median_difference_m':statistics.median(differences) if differences else None,
                    'median_absolute_difference_m':statistics.median(map(abs,differences)) if differences else None,
                    'median_difference_pct':statistics.median(percents) if percents else None})
    return out

def summaries(rows,weekly=False):
    groups=defaultdict(list)
    for r in rows:
        if r['contributes_to_training_totals']:
            day=datetime.fromisoformat(r['start_local']).date()
            if weekly: day-=timedelta(days=day.weekday())
            groups[day.isoformat()].append(r)
    out=[]
    for day,items in sorted(groups.items()):
        def total(field,subset=items):
            values=[r[field] for r in subset if r.get(field) is not None]
            return sum(values) if values else None
        runs=[r for r in items if r['sport']=='running']; trail=[r for r in runs if r['terrain_type']=='trail']; cycling=[r for r in items if r['sport']=='cycling']
        weighted=[r for r in items if r['avg_hr_bpm'] is not None and (r['timer_duration_s'] or 0)>0]
        durations=[r['timer_duration_s'] for r in items if r['timer_duration_s'] is not None]
        run_distances=[r['distance_miles'] for r in runs if r['distance_miles'] is not None]
        out.append({'week_starting_local' if weekly else 'date_local':day,'activity_count':len(items),
            'running_miles':total('distance_miles',runs) if runs else 0, 'trail_running_miles':total('distance_miles',trail) if trail else 0,
            'cycling_miles':total('distance_miles',cycling) if cycling else 0,'running_timer_duration_s':total('timer_duration_s',runs) if runs else 0,
            'total_timer_duration_s':total('timer_duration_s'),'total_elapsed_duration_s':total('elapsed_duration_s'),
            'total_ascent_m':total('ascent_m'),'ascent_available_activity_count':sum(r['ascent_m'] is not None for r in items),
            'long_run_miles':max(run_distances) if run_distances else None,'longest_activity_timer_s':max(durations) if durations else None,
            'duration_weighted_avg_hr_bpm':sum(r['avg_hr_bpm']*r['timer_duration_s'] for r in weighted)/sum(r['timer_duration_s'] for r in weighted) if weighted else None,
            'hr_weighted_duration_s':sum(r['timer_duration_s'] for r in weighted),
            'training_load_sum':total('training_load'),'training_load_available_activity_count':sum(r['training_load'] is not None for r in items),
            'intervals_load_sum':total('intervals_load'),'training_stress_score_sum':total('training_stress_score')})
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True); parser.add_argument('--output',type=Path,default=Path('output'))
    parser.add_argument('--activities-csv',type=Path); parser.add_argument('--device-map',type=Path)
    parser.add_argument('--garmin-source',type=Path,action='append',help='Local Garmin FIT directory/ZIP, or index-only export; repeatable. Defaults to known local garmin-grafana activity exports when available.')
    parser.add_argument('--snapshot-scope', default='jay-training', help='Authoritative canonical replacement scope; use a separate output directory per scope')
    parser.add_argument('--allow-source-removals', action='store_true', help='Acknowledge deliberately shrinking the prior source coverage; retires removed workouts')
    parser.add_argument('--archive',action='store_true',help='Also save a timestamped ZIP copy in OUTPUT/archive after updating the stable ZIP')
    parser.add_argument('--resolutions',type=Path,help='User-owned canonical decisions (default: data/user_resolutions.json if present; input is read only)')
    parser.add_argument('--include-records',action='store_true'); parser.add_argument('--activity-id',action='append',default=[],help='Internal or Intervals activity ID; repeatable. Produces selected detailed records.')
    args=parser.parse_args()
    if args.input.resolve()==(args.output/'Garmin_Amazfit_Training_Normalized.zip').resolve():
        parser.error('Output ZIP must not overwrite the input archive')
    metadata={r['id']:r for r in read_csv(args.activities_csv) if r.get('id')}
    overrides={r['source_filename']:r for r in read_csv(args.device_map) if r.get('source_filename')}
    if args.resolutions and not args.resolutions.exists(): parser.error('Explicit resolutions file does not exist')
    resolutions=load_resolutions(args.resolutions or Path('data/user_resolutions.json'))
    rows=[]; laps=[]; records=[]; quality=[]; found=parsed=0; mapping=[]; timelines={}; input_members=[]
    def q(category,metric,value,aid=None,detail=None): quality.append({'category':category,'metric':metric,'value':value,'activity_id':aid,'detail':detail})
    for name,content in sources(args.input):
        found+=1; iid=Path(name).name.split('_',1)[0]
        input_members.append({'source_member':name,'sha256':hashlib.sha256(content).hexdigest()})
        try:
            row,ls,rs,notes,units=parse(name,content,metadata.get(iid,{}),overrides.get(name,{}),timeline_sink=timelines); parsed+=1
            if row is None:
                q('excluded',name,1,detail='; '.join(notes)); continue
            rows.append(row); laps.extend(ls)
            if args.include_records or row['activity_id'] in args.activity_id or iid in args.activity_id: records.extend(rs)
            mapping.append({'source_filename':name,'device_family':overrides.get(name,{}).get('device_family',''),
                'product_model':overrides.get(name,{}).get('product_model',''),'elevation_source':overrides.get(name,{}).get('elevation_source',''),
                **{k:overrides.get(name,{}).get(k,'') for k in ('original_ascent_m','original_descent_m','intervals_corrected_ascent_m','intervals_corrected_descent_m')}})
            for note in notes: q('parser_warning',name,1,row['activity_id'],note)
            if row['distance_m']==0: q('suspicious','zero_distance',1,row['activity_id'])
            if any(token in (row.get('activity_name') or Path(name).stem).upper().split('_') for token in ('END','NO ACTIVITY')): q('review','marker_like_name',1,row['activity_id'],'Valid session retained for review')
            start=datetime.fromisoformat(row['start_utc'])
            if start.year<2000 or start>datetime.now(timezone.utc)+timedelta(days=1): q('suspicious','timestamp',row['start_utc'],row['activity_id'])
            for key,lo,hi in [('avg_hr_bpm',20,250),('max_hr_bpm',20,260),('distance_m',0,1000000),('elapsed_duration_s',0,604800),('avg_speed_mps',0,50),('max_speed_mps',0,100),('ascent_m',0,20000)]:
                value=row[key]
                if value is not None and not lo<=value<=hi: q('suspicious',key,value,row['activity_id'])
            if row['timer_duration_s'] is not None and row['elapsed_duration_s'] is not None and row['timer_duration_s']>row['elapsed_duration_s']+1: q('suspicious','timer_exceeds_elapsed',1,row['activity_id'])
        except Exception as exc: q('failed',name,1,detail=f'{type(exc).__name__}: {exc}')
    rows.sort(key=lambda r:(r['start_utc'],r['activity_id']))
    requested=set(args.activity_id); valid={r[k] for r in rows for k in ('activity_id','intervals_activity_id')}
    if requested-valid: parser.error('Unknown activity IDs: '+', '.join(sorted(requested-valid)))
    pairs=duplicates(rows); composite_groups=composite_duplicates(rows,pairs)
    comparison=comparisons(rows,pairs)+composite_comparisons(rows,composite_groups)
    canonical=reconstruct(rows,pairs,composite_groups,timelines,resolutions)
    manifest_path=args.output/'canonical_dataset_manifest.json'
    failed=any(x['category']=='failed' for x in quality)
    previous=json.loads(manifest_path.read_text()) if manifest_path.exists() and not failed else None
    prior_zip=args.output/'Garmin_Amazfit_Training_Normalized.zip'
    if prior_zip.exists() and not failed:
        with zipfile.ZipFile(prior_zip) as z:
            if 'canonical_dataset_manifest.json' in z.namelist():
                previous=json.loads(z.read('canonical_dataset_manifest.json'))
    # Enrich pre-v3 manifests with historical dates before CSVs are overwritten.
    if previous and (args.output/'canonical_workouts.csv').exists():
        prior_dates={w['canonical_workout_id']:w['local_date'] for w in read_csv(args.output/'canonical_workouts.csv')}
        for w in previous.get('workouts', []):
            if w['canonical_workout_id'] in prior_dates: w.setdefault('local_date',prior_dates[w['canonical_workout_id']])
    if previous and (args.output/'source_relationships.csv').exists():
        prior_keys={w['source_activity_id']:w['source_activity_key'] for w in read_csv(args.output/'source_relationships.csv')}
        for w in previous.get('workouts', []): w.setdefault('source_activity_keys',sorted({prior_keys.get(k,k) for k in w['source_activity_ids']}))
    manifest=build_snapshot(canonical['canonical_workouts'],len(rows),previous,args.snapshot_scope,args.allow_source_removals,{r['source_activity_id']:r['source_activity_key'] for r in canonical['source_relationships']}) if not failed else None
    coverage,inventory_rows=coverage_report(args.input,args.activities_csv,args.garmin_source if args.garmin_source is not None else default_garmin_sources(),rows,found,sum(x['category']=='failed' for x in quality))
    coverage['fit_members']=input_members
    coverage['auxiliary_inputs']=[{'role':role,'source_path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for role,path in [('device_map',args.device_map),('user_resolutions',args.resolutions or Path('data/user_resolutions.json'))] if path and path.exists()]
    print_coverage(coverage,canonical['canonical_workouts'])
    q('metadata','activities_csv_rows',len(metadata)); q('metadata','activities_csv_without_fit',len(set(metadata)-{r['intervals_activity_id'] for r in rows})); q('inventory','fit_files_found',found); q('inventory','fit_files_parsed',parsed); q('inventory','activity_rows',len(rows)); q('inventory','failed_files',sum(x['category']=='failed' for x in quality))
    for field in ('device_family','sport'):
        for value,count in Counter(r[field] for r in rows).items(): q('counts_by_'+field,str(value),count)
    for year,count in Counter(r['start_local'][:4] for r in rows).items(): q('counts_by_year',year,count)
    for key in METRICS:
        q('missing_rate',key,sum(r[key] is None for r in rows)/len(rows) if rows else None)
    q('duplicates','group_count',len({r['duplicate_group_id'] for r in rows if r['duplicate_group_id']}))
    q('duplicates','low_confidence_candidates',sum(p['confidence']=='low' for p in pairs))
    q('duplicates','composite_group_count',len(composite_groups))
    q('duplicates','training_contributing_rows',sum(r['contributes_to_training_totals'] for r in rows))
    q('canonical','workout_count',len(canonical['canonical_workouts']))
    q('canonical','review_issue_count',len(canonical['reconstruction_review']))
    q('canonical','reconstructed_workout_count',sum(w['canonical_status']=='reconstructed' for w in canonical['canonical_workouts']))
    for identifier in canonical['unused_resolution_ids']: q('canonical','unused_resolution',identifier,detail='User resolution input was preserved; identity not applied to this dataset')
    q('coverage','earliest_start_utc',rows[0]['start_utc'] if rows else None); q('coverage','latest_start_utc',rows[-1]['start_utc'] if rows else None)
    q('semantics','timezone','America/Los_Angeles','', 'UTC preserved; local ISO timestamps include DST offset; weeks start Monday')
    q('semantics','units','meters; seconds; miles; min/mile; bpm; watts; Celsius; native FIT cadence rpm')
    args.output.mkdir(parents=True,exist_ok=True)
    exports={'activities_master.csv':(rows,('activity_id','source_filename')),'activity_laps.csv':(laps,('activity_id','lap_number')),
             'duplicate_groups.csv':(pairs,('duplicate_group_id','activity_id_a','activity_id_b','confidence')),
             'composite_duplicate_groups.csv':(composite_groups,('composite_duplicate_group_id','continuous_activity_id','segment_activity_ids','confidence')),
             'paired_activity_comparison.csv':(comparison,('duplicate_group_id','activity_id_a','activity_id_b')),
             'daily_training_summary.csv':(canonical_summaries(canonical['canonical_workouts']),('date_local','activity_count')),
             'weekly_training_summary.csv':(canonical_summaries(canonical['canonical_workouts'],True),('week_starting_local','activity_count')),
             'elevation_comparison_summary.csv':(elevation_summary(comparison),('terrain_type','pair_count')),
             'data_quality.csv':(quality,('category','metric','value','activity_id','detail'))}
    for key in ('canonical_workouts','workout_segments','source_relationships','field_provenance','reconstruction_issues','reconstruction_review'):
        exports[key+'.csv']=(canonical[key],EXPORT_HEADERS[key])
    exports['source_inventory.csv']=(inventory_rows,('source_kind','source_filename','activity_key','start_utc','sport','distance_m'))
    for name,(data,base) in exports.items(): write_csv(args.output/name,data,base)
    write_csv(args.output/'device_mapping_template.csv',mapping,('source_filename','device_family','elevation_source'))
    if args.include_records or args.activity_id: write_csv(args.output/'activity_records.csv',records,('activity_id','timestamp_utc','latitude_deg','longitude_deg'))
    coverage['newest_canonical_start_local']=max((w['start_local'] for w in canonical['canonical_workouts']),default=None)
    (args.output/'coverage_report.json').write_text(json.dumps(shareable_coverage(coverage),indent=2,sort_keys=True)+'\n')
    if manifest is not None: manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    # Explicit allowlist prevents a previous detailed export entering the upload ZIP.
    root=Path(__file__).resolve().parent
    documentation=['README.md','HANDOFF.md','docs/WORKFLOW.md','docs/CANONICAL_WORKOUT_MODEL.md','docs/CANONICAL_SCHEMA.json','docs/CANONICAL_SNAPSHOT_CONTRACT.md','docs/MOVING_DURATION.md','docs/GARMIN_FIT_RETRIEVAL.md','scripts/fetch_garmin_fits.py','docs/examples/canonical_example.json','config/user_resolutions.example.json']
    package_names=list(exports)+['canonical_dataset_manifest.json','coverage_report.json','requirements.txt','preprocess_fit.py','canonical_workouts.py','canonical_snapshot.py','source_coverage.py','device_mapping_template.csv']+documentation
    for name in ('requirements.txt','preprocess_fit.py','canonical_workouts.py','canonical_snapshot.py','source_coverage.py',*documentation):
        target=args.output/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.resolve()!=(root/name).resolve(): target.write_bytes((root/name).read_bytes())
    failed=any(x['category']=='failed' for x in quality)
    snapshot=None
    current=args.output/'Garmin_Amazfit_Training_Normalized.zip'
    if not failed:
        files={name:args.output/name if name in exports or name in ('device_mapping_template.csv','canonical_dataset_manifest.json','coverage_report.json') else root/name for name in package_names}
        current,snapshot=publish_package(args.output,files,args.archive)
    ga=sum({p['device_a'],p['device_b']}=={'Garmin','Amazfit'} and p['grouped_for_training'] and not p.get('composite_duplicate_group_id') for p in pairs)
    print(f'FIT files: {found}; parsed: {parsed}; activities: {len(rows)}; failures: {sum(x["category"]=="failed" for x in quality)}')
    print('Devices: '+str(dict(Counter(r['device_family'] for r in rows))))
    print(f'Garmin/Amazfit grouped pairs: {ga}; all duplicate groups: {len({r["duplicate_group_id"] for r in rows if r["duplicate_group_id"]})}')
    print(f'Composite groups: {len(composite_groups)}; legacy preferred-source rows: {sum(r["contributes_to_training_totals"] for r in rows)}')
    print(f'Canonical workouts: {len(canonical["canonical_workouts"])}; open review issues: {len(canonical["reconstruction_review"])}')
    print('Coverage: '+(rows[0]['start_utc']+' to '+rows[-1]['start_utc'] if rows else 'none'))
    for name in package_names:
        p=args.output/name if (args.output/name).exists() else root/name
        if p.exists(): print(f'{p}: {p.stat().st_size:,} bytes')
    if failed:
        print(f'Parsing failed; current ZIP left unchanged: {current}. No snapshot created. See data_quality.csv.')
    else:
        print(f'{current}: {current.stat().st_size:,} bytes')
        if snapshot is not None: print(f'{snapshot}: {snapshot.stat().st_size:,} bytes')
    if args.include_records or args.activity_id: print(f'{args.output / "activity_records.csv"}: {len(records):,} detailed records (outside ZIP)')
    return 1 if failed else 0

if __name__=='__main__': raise SystemExit(main())
