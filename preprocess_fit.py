#!/usr/bin/env python3
"""Normalize FIT archives without altering originals; see README.md for semantics."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import warnings
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fitdecode

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

def write_csv(path, rows, base=()):
    fields=list(dict.fromkeys([*base,*(k for row in rows for k in row)]))
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v,default=safe,sort_keys=True) if isinstance(v,(dict,list)) else (round(v,6) if isinstance(v,float) else v) for k,v in row.items()})

def read_csv(path):
    if not path: return []
    with Path(path).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

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

def parse(name, content, metadata, override):
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
         'manufacturer':manufacturer,'fit_product_model':product,'file_id_metadata_json':{k:safe(v) for k,v in fid.items() if 'position' not in k},'product_model':product,'serial_number':first(recording,('serial_number',)) or fid.get('serial_number'),
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
    row['session_metrics_json']=[{k:safe(v) for k,v in x.items() if 'position' not in k and k not in ('timestamp','start_time')} for x in sessions]
    row['session_units_json']={k:v for k,v in field_units.items() if k.startswith('session.') and 'position' not in k}
    row['device_metadata_json']=[{k:safe(v) for k,v in d.items() if 'position' not in k} for d in messages['device_info']]
    stops=[e for e in messages['event'] if e.get('event')=='timer' and e.get('event_type') in ('stop','stop_all','stop_disable','stop_disable_all')]
    unique_stops={iso(e.get('timestamp')) for e in stops if isinstance(e.get('timestamp'),datetime)}
    row['timer_stop_event_count']=len(unique_stops) if messages['event'] else None
    row['pause_count']=sum(1 for stop in unique_stops if any(e.get('event')=='timer' and e.get('event_type')=='start' and iso(e.get('timestamp')) and iso(e['timestamp'])>stop for e in messages['event'])) if messages['event'] else None
    laps=[]
    for i,lap in enumerate(messages['lap'],1):
        lr={'activity_id':activity_id,'device_family':row['device_family'],'lap_number':i,**metrics(lap)}
        times(lr,'start',lap.get('start_time')); times(lr,'end',lap.get('timestamp'))
        lr['lap_metrics_json']={k:safe(v) for k,v in lap.items() if 'position' not in k and k not in ('timestamp','start_time')}
        laps.append(lr)
    records=[]
    for record in messages['record']:
        rr={'activity_id':activity_id}; times(rr,'timestamp',record.get('timestamp'))
        for dest, keys in {'distance_m':('distance',),'hr_bpm':('heart_rate',),'cadence_fit_rpm':('cadence',),'altitude_m':('enhanced_altitude','altitude'),'speed_mps':('enhanced_speed','speed'),'power_w':('power',)}.items(): rr[dest]=first(record,keys)
        for dest, key in [('latitude_deg','position_lat'),('longitude_deg','position_long')]:
            val=record.get(key); rr[dest]=val*180/(2**31) if val is not None else None
        records.append(rr)
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
    confidence='high' if exact or (gap<=120 and overlap>=.9 and duration_ratio>=.8 and pct is not None and pct<=10) else ('medium' if overlap>=.8 and duration_ratio>=.7 and pct is not None and pct<=25 else 'low')
    return {'start_difference_s':gap,'distance_difference_m':delta,'distance_difference_pct':pct,'overlap_fraction':overlap,'duration_ratio':duration_ratio,'confidence':confidence,'reason':'identical FIT content' if exact else 'same sport; starts within 300 s; overlapping elapsed windows; distance/duration similarity assessed'}

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
                               secondary_comparison_available=len(group)>1,preference_reason='device priority; record count; stable ID tie-break')
    for pair in pairs:
        a,b=(lookup[pair[k]] for k in ('activity_id_a','activity_id_b'))
        pair['duplicate_group_id']=a['duplicate_group_id'] if a['duplicate_group_id']==b['duplicate_group_id'] else None
        pair['grouped_for_training']=pair['duplicate_group_id'] is not None
        pair['duration_difference_s']=abs(a['elapsed_duration_s']-b['elapsed_duration_s']) if a['elapsed_duration_s'] is not None and b['elapsed_duration_s'] is not None else None
    return pairs

def comparisons(rows,pairs):
    lookup={r['activity_id']:r for r in rows}; out=[]
    for p in pairs:
        a,b=lookup[p['activity_id_a']],lookup[p['activity_id_b']]
        if a['device_family']=='Amazfit' and b['device_family']=='Garmin': a,b=b,a
        r={'duplicate_group_id':p['duplicate_group_id'],'activity_id_a':a['activity_id'],'activity_id_b':b['activity_id'],
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
        if r['preferred_training_record']:
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
    parser.add_argument('--include-records',action='store_true'); parser.add_argument('--activity-id',action='append',default=[],help='Internal or Intervals activity ID; repeatable. Produces selected detailed records.')
    args=parser.parse_args()
    if args.input.resolve()==(args.output/'Garmin_Amazfit_Training_Normalized.zip').resolve():
        parser.error('Output ZIP must not overwrite the input archive')
    metadata={r['id']:r for r in read_csv(args.activities_csv) if r.get('id')}
    overrides={r['source_filename']:r for r in read_csv(args.device_map) if r.get('source_filename')}
    rows=[]; laps=[]; records=[]; quality=[]; found=parsed=0; mapping=[]
    def q(category,metric,value,aid=None,detail=None): quality.append({'category':category,'metric':metric,'value':value,'activity_id':aid,'detail':detail})
    for name,content in sources(args.input):
        found+=1; iid=Path(name).name.split('_',1)[0]
        try:
            row,ls,rs,notes,units=parse(name,content,metadata.get(iid,{}),overrides.get(name,{})); parsed+=1
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
    pairs=duplicates(rows); comparison=comparisons(rows,pairs)
    q('metadata','activities_csv_rows',len(metadata)); q('metadata','activities_csv_without_fit',len(set(metadata)-{r['intervals_activity_id'] for r in rows})); q('inventory','fit_files_found',found); q('inventory','fit_files_parsed',parsed); q('inventory','activity_rows',len(rows)); q('inventory','failed_files',sum(x['category']=='failed' for x in quality))
    for field in ('device_family','sport'):
        for value,count in Counter(r[field] for r in rows).items(): q('counts_by_'+field,str(value),count)
    for year,count in Counter(r['start_local'][:4] for r in rows).items(): q('counts_by_year',year,count)
    for key in METRICS:
        q('missing_rate',key,sum(r[key] is None for r in rows)/len(rows) if rows else None)
    q('duplicates','group_count',len({r['duplicate_group_id'] for r in rows if r['duplicate_group_id']}))
    q('duplicates','low_confidence_candidates',sum(p['confidence']=='low' for p in pairs))
    q('coverage','earliest_start_utc',rows[0]['start_utc'] if rows else None); q('coverage','latest_start_utc',rows[-1]['start_utc'] if rows else None)
    q('semantics','timezone','America/Los_Angeles','', 'UTC preserved; local ISO timestamps include DST offset; weeks start Monday')
    q('semantics','units','meters; seconds; miles; min/mile; bpm; watts; Celsius; native FIT cadence rpm')
    args.output.mkdir(parents=True,exist_ok=True)
    exports={'activities_master.csv':(rows,('activity_id','source_filename')),'activity_laps.csv':(laps,('activity_id','lap_number')),
             'duplicate_groups.csv':(pairs,('duplicate_group_id','activity_id_a','activity_id_b','confidence')),
             'paired_activity_comparison.csv':(comparison,('duplicate_group_id','activity_id_a','activity_id_b')),
             'daily_training_summary.csv':(summaries(rows),('date_local','activity_count')),
             'weekly_training_summary.csv':(summaries(rows,True),('week_starting_local','activity_count')),
             'elevation_comparison_summary.csv':(elevation_summary(comparison),('terrain_type','pair_count')),
             'data_quality.csv':(quality,('category','metric','value','activity_id','detail'))}
    for name,(data,base) in exports.items(): write_csv(args.output/name,data,base)
    write_csv(args.output/'device_mapping_template.csv',mapping,('source_filename','device_family','elevation_source'))
    if args.include_records or args.activity_id: write_csv(args.output/'activity_records.csv',records,('activity_id','timestamp_utc','latitude_deg','longitude_deg'))
    # Explicit allowlist prevents a previous detailed export entering the upload ZIP.
    root=Path(__file__).resolve().parent
    package_names=list(exports)+['README.md','requirements.txt','preprocess_fit.py','device_mapping_template.csv']
    for name in ('README.md','requirements.txt','preprocess_fit.py'):
        target=args.output/name
        if target.resolve()!=(root/name).resolve(): target.write_bytes((root/name).read_bytes())
    with zipfile.ZipFile(args.output/'Garmin_Amazfit_Training_Normalized.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in package_names:
            p=args.output/name if name in exports or name=='device_mapping_template.csv' else root/name
            z.write(p,arcname=name)
    ga=sum({p['device_a'],p['device_b']}=={'Garmin','Amazfit'} and p['grouped_for_training'] for p in pairs)
    print(f'FIT files: {found}; parsed: {parsed}; activities: {len(rows)}; failures: {sum(x["category"]=="failed" for x in quality)}')
    print('Devices: '+str(dict(Counter(r['device_family'] for r in rows))))
    print(f'Garmin/Amazfit grouped pairs: {ga}; all duplicate groups: {len({r["duplicate_group_id"] for r in rows if r["duplicate_group_id"]})}')
    print('Coverage: '+(rows[0]['start_utc']+' to '+rows[-1]['start_utc'] if rows else 'none'))
    for name in package_names+['Garmin_Amazfit_Training_Normalized.zip']:
        p=args.output/name if (args.output/name).exists() else root/name
        print(f'{p}: {p.stat().st_size:,} bytes')
    if args.include_records or args.activity_id: print(f'{args.output / "activity_records.csv"}: {len(records):,} detailed records (outside ZIP)')
    return 1 if any(x['category']=='failed' for x in quality) else 0

if __name__=='__main__': raise SystemExit(main())
