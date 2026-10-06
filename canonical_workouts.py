"""Canonical physical workouts from immutable source rows and local timelines.

No FIT decoding, bridge writes, location exports, or source mutation occurs here.
See docs/CANONICAL_WORKOUT_MODEL.md for the versioned local contract.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 'canonical-workout-1'
EXPORT_HEADERS = {
    'canonical_workouts': ('schema_version', 'canonical_workout_id', 'local_date', 'canonical_status', 'distance_m', 'run_distance_m', 'requires_user_review'),
    'workout_segments': ('workout_segment_id', 'canonical_workout_id', 'source_activity_id', 'segment_role', 'start_utc', 'end_utc', 'distance_m'),
    'source_relationships': ('canonical_workout_id', 'source_activity_id', 'source_activity_key', 'relationship_type', 'counts_separately_in_training_totals'),
    'field_provenance': ('canonical_workout_id', 'field_name', 'value', 'unit', 'source_activity_ids', 'method', 'coverage_scope', 'confidence', 'coverage_intervals'),
    'reconstruction_issues': ('issue_id', 'canonical_workout_id', 'local_date', 'classification', 'start_utc', 'end_utc', 'source_activity_ids', 'evidence_json', 'candidate_additional_distance_m', 'confidence', 'requires_user_review', 'resolution', 'user_decision'),
    'reconstruction_review': ('issue_id', 'canonical_workout_id', 'date', 'source_activities', 'detected_problem', 'suggested_interpretation', 'candidate_distance_m', 'candidate_elapsed_time_s', 'confidence', 'question_for_user', 'user_decision', 'resolution'),
}
LOCAL = ZoneInfo('America/Los_Angeles')
MILE = 1609.344
DEVICE_RANK = {'Garmin': 0, 'Amazfit': 1, 'Other': 2, 'Unknown': 3}
ROLES = {'warmup', 'workout', 'cooldown', 'easy_run', 'trail', 'commute', 'walk', 'unknown'}
DECISIONS = {'include_running', 'include_walking', 'stationary_stop', 'separate_activity', 'unsure', 'use_preferred', 'use_secondary'}


def stable_id(prefix, parts):
    return prefix + hashlib.sha256('|'.join(sorted(map(str, parts))).encode()).hexdigest()[:20]


def source_key(row):
    return row.get('intervals_activity_id') or row['source_filename']


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def sum_complete(rows, field):
    values = [r.get(field) for r in rows]
    return sum(values) if values and all(finite(v) for v in values) else None


def max_complete(rows, field):
    values = [r.get(field) for r in rows]
    return max(values) if values and all(finite(v) for v in values) else None


def weighted(rows, field):
    if not rows or not all(finite(r.get(field)) and (r.get('timer_duration_s') or 0) > 0 for r in rows):
        return None
    return sum(r[field] * r['timer_duration_s'] for r in rows) / sum(r['timer_duration_s'] for r in rows)


def infer_role(row):
    name = (row.get('activity_name') or '').lower()
    if re.search(r'\bwarm[ -]?up\b', name): return 'warmup'
    if re.search(r'\bcool[ -]?down\b', name): return 'cooldown'
    if re.search(r'\b(intervals?|track workout)\b', name): return 'workout'
    if row.get('sub_sport') == 'trail': return 'trail'
    if row.get('sport') == 'walking': return 'walk'
    return 'unknown'


def load_resolutions(path):
    """Read user-owned input; never create, rewrite, or truncate it."""
    if path is None or not Path(path).exists(): return {'schema_version': 1, 'issues': {}, 'workouts': {}, 'session_groups': []}
    with Path(path).open(encoding='utf-8') as f: result = json.load(f)
    if not isinstance(result, dict) or result.get('schema_version') != 1:
        raise ValueError('User resolutions require schema_version: 1')
    for key, kind in (('issues', dict), ('workouts', dict), ('session_groups', list)):
        if not isinstance(result.get(key, kind()), kind): raise ValueError(f'Resolution {key} must be {kind.__name__}')
    for decision in result.get('issues', {}).values():
        if not isinstance(decision, dict) or decision.get('decision') not in DECISIONS:
            raise ValueError('Invalid issue resolution decision')
        if decision['decision'] == 'separate_activity' and decision.get('sport') not in ('running', 'walking', 'cycling', 'hiking', 'other'):
            raise ValueError('separate_activity resolution requires sport: running/walking/cycling/hiking/other')
    for override in result.get('workouts', {}).values():
        if not isinstance(override, dict): raise ValueError('Workout resolution must be an object')
        for key in ('distance_m', 'run_distance_m', 'trail_distance_m'):
            if key in override and (not finite(override[key]) or override[key] < 0):
                raise ValueError(f'{key} resolution must be a finite nonnegative number')
        if any(role not in ROLES for role in override.get('segment_roles', {}).values()):
            raise ValueError('Unsupported segment role')
        if 'run_distance_source_activity_ids' in override and (not isinstance(override['run_distance_source_activity_ids'], list) or not override['run_distance_source_activity_ids']):
            raise ValueError('run_distance_source_activity_ids must be a nonempty list')
    return result


class Timeline:
    def __init__(self, data=None):
        data = data or {}
        # One record per timestamp, deterministic without modifying caller dictionaries.
        points = {}
        for record in data.get('records', []):
            timestamp = record.get('timestamp_utc')
            if timestamp:
                points[dt(timestamp).timestamp()] = record
        self.times = sorted(points)
        self.records = [points[t] for t in self.times]
        self.events = sorted((e for e in data.get('timer_events', []) if e.get('timestamp_utc')), key=lambda e: e['timestamp_utc'])

    def nearest(self, when, tolerance=15):
        target = dt(when).timestamp() if not isinstance(when, (int, float)) else when
        index = bisect.bisect_left(self.times, target)
        candidates = [i for i in (index - 1, index) if 0 <= i < len(self.times)]
        if not candidates: return None
        chosen = min(candidates, key=lambda i: (abs(self.times[i] - target), i))
        return (self.times[chosen], self.records[chosen]) if abs(self.times[chosen] - target) <= tolerance else None

    def evidence(self, start, end):
        """Measured cumulative distance only; no interpolation over absent samples."""
        begin = self.nearest(start); finish = self.nearest(end)
        if not begin or not finish or finish[0] <= begin[0]: return None
        i = bisect.bisect_left(self.times, begin[0]); j = bisect.bisect_left(self.times, finish[0])
        sampled = self.records[i:j + 1]; stamps = self.times[i:j + 1]
        distances = [r.get('distance_m') for r in sampled]
        if len(sampled) < 3 or not all(finite(v) and v >= 0 for v in distances): return None
        deltas = [b - a for a, b in zip(distances, distances[1:])]
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        if any(delta < 0 for delta in deltas) or max(gaps, default=0) > 30: return None
        requested = (dt(end) - dt(start)).total_seconds()
        coverage = (finish[0] - begin[0]) / requested if requested > 0 else 0
        if coverage < .9: return None
        motion_seconds = running_seconds = stationary_seconds = 0
        for duration, distance, record in zip(gaps, deltas, sampled[1:]):
            speed = distance / duration if duration else 0
            cadence = record.get('cadence_fit_rpm'); hr = record.get('hr_bpm')
            if speed >= .5: motion_seconds += duration
            if speed >= 1.5 and finite(cadence) and cadence >= 60 and (hr is None or finite(hr) and hr >= 40): running_seconds += duration
            if speed < .2: stationary_seconds += duration
        measured_duration = finish[0] - begin[0]
        return {'distance_m': distances[-1] - distances[0], 'sample_count': len(sampled),
                'sampled_start_utc': sampled[0]['timestamp_utc'], 'sampled_end_utc': sampled[-1]['timestamp_utc'],
                'coverage_fraction': min(1, coverage), 'motion_duration_s': motion_seconds,
                'running_fraction': running_seconds / measured_duration,
                'stationary_duration_s': stationary_seconds, 'max_sample_gap_s': max(gaps)}

    def delta(self, start, end, tolerance=20):
        a, b = self.nearest(start, tolerance), self.nearest(end, tolerance)
        if not a or not b or b[0] <= a[0]: return None
        x, y = a[1].get('distance_m'), b[1].get('distance_m')
        return y - x if finite(x) and finite(y) and y >= x else None

    def gaps(self, row):
        start, end = dt(row['start_utc']), dt(row['end_utc'])
        intervals = []; stopped = None
        for event in self.events:
            timestamp = dt(event['timestamp_utc'])
            if event['event_type'] in ('stop', 'stop_all', 'stop_disable', 'stop_disable_all'):
                if stopped is None: stopped = timestamp
            elif event['event_type'] == 'start' and stopped is not None:
                if timestamp > stopped: intervals.append((max(start, stopped), min(end, timestamp), 'timer_pause'))
                stopped = None
        if stopped is not None and stopped < end - timedelta(seconds=60):
            intervals.append((max(start, stopped), end, 'terminal_pause'))
        spacings = [b - a for a, b in zip(self.times, self.times[1:])]
        threshold = max(60, statistics.median(spacings) * 5) if spacings else 60
        for a, b in zip(self.times, self.times[1:]):
            if b - a > threshold:
                gap = (datetime.fromtimestamp(a, start.tzinfo), datetime.fromtimestamp(b, start.tzinfo), 'record_gap')
                if not any(gap[0] < right and gap[1] > left for left, right, _ in intervals): intervals.append(gap)
        return sorted((a, b, kind) for a, b, kind in intervals if (b - a).total_seconds() >= 30)


def aligned_outside_gap(primary, secondary, start, end):
    """Agreement on two valid moving windows, one before and one after gap."""
    agreements = []
    for left, right in ((start - timedelta(seconds=240), start), (end, end + timedelta(seconds=240))):
        a, b = primary.delta(left, right), secondary.delta(left, right)
        agreements.append(a is not None and b is not None and min(a, b) >= 50 and abs(a - b) / max(a, b) <= .15)
    return all(agreements)


def overlapping(row_a, row_b):
    start = max(dt(row_a['start_utc']), dt(row_b['start_utc']))
    end = min(dt(row_a['end_utc']), dt(row_b['end_utc']))
    return max(0, (end - start).total_seconds())


def build_groups(rows, pairs, resolutions):
    groups = defaultdict(list)
    for row in rows: groups[row.get('duplicate_group_id') or row['activity_id']].append(row)
    # Large-distance disagreements can remain low pair candidates. Represent them
    # once as ambiguous when temporal evidence strongly indicates overlapping watches.
    for pair in sorted(pairs, key=lambda p: (p['start_difference_s'], p['activity_id_a'], p['activity_id_b'])):
        a = next(r for r in rows if r['activity_id'] == pair['activity_id_a'])
        b = next(r for r in rows if r['activity_id'] == pair['activity_id_b'])
        if {a['device_family'], b['device_family']} != {'Garmin', 'Amazfit'}: continue
        if a['activity_id'] not in groups or b['activity_id'] not in groups: continue
        if pair['start_difference_s'] > 120 or pair['overlap_fraction'] < .9: continue
        # Temporal evidence supports a reviewable relationship, never automatic repair.
        members = groups.pop(a['activity_id']) + groups.pop(b['activity_id'])
        groups[stable_id('candidate_', [source_key(r) for r in members])] = members
    for session in resolutions.get('session_groups', []):
        if not isinstance(session, dict) or not isinstance(session.get('source_activity_ids'), list):
            raise ValueError('session_groups require source_activity_ids')
        keys = set(session['source_activity_ids'])
        selected = [r for r in rows if r['activity_id'] in keys or source_key(r) in keys]
        if len(selected) != len(keys) or len(selected) < 2: raise ValueError('Session grouping references missing/duplicate source identities')
        roles = session.get('segment_roles', {})
        if any(role not in ROLES for role in roles.values()): raise ValueError('Unsupported session segment role')
        member_ids = {r['activity_id'] for r in selected}
        group_keys = [key for key, members in groups.items() if member_ids.intersection(r['activity_id'] for r in members)]
        all_members = [r for key in group_keys for r in groups[key]]
        for key in group_keys: del groups[key]
        groups[stable_id('session_', [source_key(r) for r in all_members])] = all_members
    return sorted(groups.values(), key=lambda group: (min(r['start_utc'] for r in group), sorted(source_key(r) for r in group)))


def choose_primary(members):
    preferred = [r for r in members if r.get('contributes_to_training_totals')]
    if not preferred: preferred = [min(members, key=lambda r: (DEVICE_RANK[r['device_family']], r['activity_id']))]
    # Review candidates still have two old source contributors. Pick a known family,
    # then preserve multiple genuinely sequential segments from that family.
    rank = min(DEVICE_RANK[r['device_family']] for r in preferred)
    return sorted((r for r in preferred if DEVICE_RANK[r['device_family']] == rank), key=lambda r: (r['start_utc'], source_key(r)))


def reconstruct(rows, pairs=(), composite_groups=(), timelines=None, resolutions=None):
    """Return canonical exports. Inputs (including source flags) remain untouched."""
    resolutions = resolutions or {'schema_version': 1, 'issues': {}, 'workouts': {}, 'session_groups': []}
    timeline = {key: Timeline(value) for key, value in (timelines or {}).items()}
    workouts = []; segments = []; relationships = []; provenance = []; issues = []; review = []
    applied = set()
    for members in build_groups(rows, pairs, resolutions):
        members = sorted(members, key=lambda r: (source_key(r), r['activity_id']))
        cw_id = stable_id('cw_', [source_key(r) for r in members])
        primary = choose_primary(members)
        # Validate sequentiality rather than silently summing overlapping primary sources.
        source_overlap = any(overlapping(a, b) > 5 for a, b in zip(primary, primary[1:]))
        baseline = sum_complete(primary, 'distance_m')
        run_base = sum_complete([r for r in primary if r['sport'] == 'running'], 'distance_m') if any(r['sport'] == 'running' for r in primary) else 0
        trail_base = sum_complete([r for r in primary if r.get('sub_sport') == 'trail'], 'distance_m') if any(r.get('sub_sport') == 'trail' for r in primary) else 0
        base_ids = [r['activity_id'] for r in primary]
        secondary = [r for r in members if r['activity_id'] not in base_ids]
        continuous = max(secondary, key=lambda r: (r.get('elapsed_duration_s') or 0, r['activity_id']), default=None)
        is_composite = any(r.get('composite_duplicate_group_id') for r in members)
        status = 'composite' if is_composite or len(primary) > 1 else ('duplicate_resolved' if len(members) > 1 else 'direct')
        start = min(dt(r['start_utc']) for r in primary)
        end = max(dt(r['end_utc']) for r in primary)
        elapsed_ids = base_ids
        # A continuous counterpart is a full-timeline source only when it spans the primary timeline.
        if continuous and dt(continuous['start_utc']) <= start + timedelta(seconds=120) and dt(continuous['end_utc']) >= end - timedelta(seconds=120):
            start, end = dt(continuous['start_utc']), dt(continuous['end_utc']); elapsed_ids = [continuous['activity_id']]
        cw = {'schema_version': SCHEMA_VERSION, 'canonical_workout_id': cw_id, 'session_group_id': cw_id,
              'local_date': start.astimezone(LOCAL).date().isoformat(), 'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
              'start_local': start.astimezone(LOCAL).isoformat(), 'end_local': end.astimezone(LOCAL).isoformat(),
              'sport': primary[0]['sport'] if len({r['sport'] for r in primary}) == 1 else 'mixed',
              'sub_sport': primary[0].get('sub_sport') if len({r.get('sub_sport') for r in primary}) == 1 else 'mixed',
              'source_activity_ids': sorted(r['activity_id'] for r in members), 'primary_source_activity_ids': base_ids,
              'segment_count': len(primary), 'canonical_status': status, 'confidence': 'high', 'requires_user_review': False,
              'mileage_requires_user_review': False, 'physical_distance_requires_user_review': False,
              'distance_m': baseline, 'run_distance_m': run_base, 'trail_distance_m': trail_base,
              'provisional_distance_m': baseline, 'provisional_run_distance_m': run_base,
              'candidate_additional_distance_m': 0, 'recovered_distance_m': 0, 'non_running_recovered_distance_m': 0,
              'elapsed_duration_s': max(0, (end - start).total_seconds()), 'timer_duration_s': sum_complete(primary, 'timer_duration_s'),
              'moving_duration_s': sum_complete(primary, 'moving_duration_s'), 'active_distance_m': baseline,
              'active_pace_min_mile': None, 'active_pace_scope': 'recorded_portions',
              'recorded_active_distance_m': baseline, 'recorded_active_duration_s': sum_complete(primary, 'timer_duration_s'),
              'recorded_active_pace_min_mile': None, 'estimated_stationary_duration_s': None,
              'avg_hr_bpm': weighted(primary, 'avg_hr_bpm'), 'max_hr_bpm': max_complete(primary, 'max_hr_bpm'),
              'ascent_m': sum_complete(primary, 'ascent_m'), 'descent_m': sum_complete(primary, 'descent_m'),
              'elevation_source': primary[0].get('elevation_source', 'unknown') if len({r.get('elevation_source') for r in primary}) == 1 else 'mixed',
              'training_load': sum_complete(primary, 'training_load'), 'intervals_load': sum_complete(primary, 'intervals_load'),
              'training_stress_score': sum_complete(primary, 'training_stress_score'),
              'aerobic_training_effect': max_complete([r for r in primary if r['device_family'] == 'Garmin'], 'aerobic_training_effect'),
              'anaerobic_training_effect': max_complete([r for r in primary if r['device_family'] == 'Garmin'], 'anaerobic_training_effect'),
              'summary_note': '', 'counts_toward_training_totals': True}
        ledger = {}
        def record(field, ids, method='preferred_source', scope='recorded_portions', confidence='high', intervals=None):
            ledger[field] = {'source_activity_ids': sorted(set(ids)), 'method': method, 'coverage_scope': scope,
                             'confidence': confidence, 'coverage_intervals': intervals or [
                                 {'source_activity_id': r['activity_id'], 'start_utc': r['start_utc'], 'end_utc': r['end_utc']}
                                 for r in members if r['activity_id'] in ids]}
        for field in ('distance_m', 'run_distance_m', 'trail_distance_m', 'timer_duration_s', 'moving_duration_s', 'active_distance_m',
                      'avg_hr_bpm', 'max_hr_bpm', 'ascent_m', 'descent_m', 'training_load', 'intervals_load', 'training_stress_score',
                      'recorded_active_distance_m', 'recorded_active_duration_s', 'recorded_active_pace_min_mile'):
            record(field, base_ids, 'sum_segments' if len(primary) > 1 else 'preferred_source')
        for field in ('aerobic_training_effect', 'anaerobic_training_effect'):
            record(field, [r['activity_id'] for r in primary if r['device_family'] == 'Garmin'], 'Garmin_metric_max_over_segments')
        for field in ('start_utc', 'end_utc', 'elapsed_duration_s'):
            record(field, elapsed_ids, 'continuous_timeline' if continuous and elapsed_ids == [continuous['activity_id']] else 'source_timeline_union', 'whole_workout')
        elapsed = cw['elapsed_duration_s']; timer = cw['recorded_active_duration_s']
        if baseline and timer is not None: cw['recorded_active_pace_min_mile'] = timer / 60 / (baseline / MILE)
        cw['active_pace_min_mile'] = cw['recorded_active_pace_min_mile']
        cw['active_pace_scope'] = 'recorded_segments' if len(primary) > 1 else 'whole_recorded_workout'
        record('active_pace_min_mile', base_ids, 'timer_over_same_source_distance', cw['active_pace_scope'])
        local_issues = []; known_repair = 0; walk_repair = 0; trail_repair = 0; unresolved = False; notes = []
        repair_ids = []; repaired_intervals = []; full_secondary_choice = False; separate_gaps = []
        def issue(kind, left=None, right=None, secondary_row=None, evidence=None, auto=False, extra=None):
            key = [cw_id, kind, left.isoformat() if left else '', right.isoformat() if right else '']
            identifier = stable_id('issue_', key)
            evidence = evidence or {}
            candidate = extra if extra is not None else evidence.get('recoverable_distance_m')
            item = {'issue_id': identifier, 'canonical_workout_id': cw_id, 'local_date': cw['local_date'],
                    'classification': kind, 'start_utc': left.isoformat() if left else None, 'end_utc': right.isoformat() if right else None,
                    'source_activity_ids': sorted([*base_ids, *([secondary_row['activity_id']] if secondary_row else [])]),
                    'evidence_json': evidence, 'candidate_additional_distance_m': candidate,
                    'confidence': 'high' if auto else 'medium', 'requires_user_review': not auto,
                    'resolution': 'automatic_no_distance_change' if auto else 'unresolved', 'user_decision': None}
            decision = resolutions.get('issues', {}).get(identifier)
            if decision:
                applied.add(identifier); item['user_decision'] = decision['decision']; item['resolution'] = 'user_' + decision['decision']
                item['requires_user_review'] = decision['decision'] in ('unsure', 'separate_activity')
            local_issues.append(item)
            return item, decision

        if source_overlap:
            issue('overlapping_primary_segments', evidence={'reason': 'Preferred source segments overlap; cannot sum physical distance safely'})
            unresolved = True
        examined = set()
        for source in primary:
            if source['device_family'] != 'Garmin' or not continuous or continuous['device_family'] != 'Amazfit': continue
            ptime = timeline.get(source['activity_id'], Timeline()); stime = timeline.get(continuous['activity_id'], Timeline())
            for left, right, gap_kind in ptime.gaps(source):
                key = (left, right)
                if key in examined: continue
                examined.add(key)
                evidence = stime.evidence(left, right)
                if not evidence:
                    agreement = baseline is not None and continuous.get('distance_m') is not None and abs(continuous['distance_m'] - baseline) <= max(150, baseline * .05)
                    outside = right > dt(continuous['end_utc']) + timedelta(seconds=30) or left < dt(continuous['start_utc']) - timedelta(seconds=30)
                    item, decision = issue('unknown_pause' if gap_kind != 'record_gap' else 'device_dropout', left, right, continuous,
                          {'gap_signal': gap_kind, 'reason': 'Secondary samples insufficient, sparse, or cumulative distance invalid',
                           'session_distances_agree_within_tolerance': agreement, 'outside_secondary_timeline': outside}, auto=agreement or outside)
                    if agreement or outside: item['resolution'] = 'no_supported_missing_distance'
                    elif not (decision and decision['decision'] in ('stationary_stop', 'use_preferred')): unresolved = True
                    continue
                primary_delta = ptime.delta(left, right, 30)
                evidence['gap_signal'] = gap_kind; evidence['primary_distance_during_gap_m'] = primary_delta
                evidence['aligned_before_and_after'] = aligned_outside_gap(ptime, stime, left, right)
                missing = max(0, evidence['distance_m'] - primary_delta) if primary_delta is not None else evidence['distance_m']
                evidence['recoverable_distance_m'] = missing
                stationary = evidence['distance_m'] <= max(15, (right - left).total_seconds() * .05)
                if stationary:
                    item, decision = issue('intentional_stationary_pause', left, right, continuous, evidence, auto=True, extra=0)
                    cw['estimated_stationary_duration_s'] = (cw['estimated_stationary_duration_s'] or 0) + evidence['stationary_duration_s']
                    notes.append('Secondary evidence shows stationary pause; no distance added.')
                    continue
                explicit = gap_kind == 'timer_pause'
                running = evidence['running_fraction'] >= .8
                significant = missing >= max(50, (baseline or 0) * .02)
                discrepancy = (continuous.get('distance_m') or 0) - (baseline or 0)
                consistent = discrepancy >= missing * .5 and discrepancy <= missing * 1.5 + max(100, (baseline or 0) * .03)
                auto = explicit and primary_delta is not None and running and significant and consistent and evidence['aligned_before_and_after']
                kind = 'probable_forgotten_resume' if explicit else ('device_dropout' if gap_kind == 'record_gap' else 'unknown_pause')
                item, decision = issue(kind, left, right, continuous, evidence, auto=auto)
                if auto: item['resolution'] = 'automatic_secondary_gap_repair'
                if not significant and missing < 50 and not decision:
                    item['requires_user_review'] = False; item['resolution'] = 'gap_distance_below_review_threshold'
                accept = decision['decision'] in ('include_running', 'include_walking') if decision else auto
                reject = decision and decision['decision'] in ('stationary_stop', 'use_preferred')
                if accept:
                    if not significant and not decision: continue
                    if decision and decision['decision'] == 'include_walking': walk_repair += missing
                    else:
                        known_repair += missing
                        if source.get('sub_sport') == 'trail': trail_repair += missing
                    repair_ids.append(continuous['activity_id']); repaired_intervals.append({'source_activity_id': continuous['activity_id'], 'start_utc': evidence['sampled_start_utc'], 'end_utc': evidence['sampled_end_utc']})
                    notes.append(f'{missing:.1f} m recovered from Amazfit measured gap evidence; Garmin pace covers recorded portions.')
                    item['requires_user_review'] = False
                elif reject:
                    item['requires_user_review'] = False
                    notes.append('User retained preferred distance; no gap distance added.')
                elif decision and decision['decision'] == 'separate_activity':
                    separate_gaps.append((item, decision, evidence, continuous))
                    item['requires_user_review'] = False
                    notes.append('User assigned measured gap movement to a separate activity.')
                elif missing >= 50:
                    unresolved = True
                if decision and decision['decision'] == 'use_secondary':
                    full_secondary_choice = True; item['requires_user_review'] = False
        # Segment boundary motion is real physical evidence but not necessarily running.
        if continuous and len(primary) > 1:
            stime = timeline.get(continuous['activity_id'], Timeline())
            for a, b in zip(primary, primary[1:]):
                left, right = dt(a['end_utc']), dt(b['start_utc'])
                if right <= left: continue
                evidence = stime.evidence(left, right)
                if evidence is None: evidence = {'reason': 'No dense continuous distance samples at split boundary'}
                evidence['recoverable_distance_m'] = evidence.get('distance_m')
                extra = evidence.get('distance_m')
                auto = extra is not None and extra < 50
                item, decision = issue('split_activity_boundary', left, right, continuous, evidence, auto=auto, extra=extra)
                if decision and decision['decision'] in ('include_running', 'include_walking') and extra is not None:
                    if decision['decision'] == 'include_running': known_repair += extra
                    else: walk_repair += extra
                    repair_ids.append(continuous['activity_id']); repaired_intervals.append({'source_activity_id': continuous['activity_id'], 'start_utc': evidence['sampled_start_utc'], 'end_utc': evidence['sampled_end_utc']})
                    item['requires_user_review'] = False
                elif decision and decision['decision'] == 'separate_activity' and extra is not None:
                    separate_gaps.append((item, decision, evidence, continuous))
                    item['requires_user_review'] = False
                elif extra is not None and extra >= 50 and not (decision and decision['decision'] in ('stationary_stop', 'use_preferred')):
                    unresolved = True
                elif decision and decision['decision'] in ('stationary_stop', 'use_preferred'):
                    item['requires_user_review'] = False
        # Never repair from total distance disagreement alone.
        difference = None
        if continuous and baseline is not None and continuous.get('distance_m') is not None:
            difference = continuous['distance_m'] - baseline - known_repair - walk_repair - sum(entry[2]['recoverable_distance_m'] for entry in separate_gaps)
            unresolved_gap_distance = sum(max(0, item['candidate_additional_distance_m'] or 0) for item in local_issues if item['requires_user_review'])
            user_retained = any(item['user_decision'] in ('use_preferred', 'stationary_stop') for item in local_issues)
            if abs(difference) > max(150, baseline * .05) and not user_retained and unresolved_gap_distance < abs(difference) * .5:
                item, decision = issue('conflicting_distance', secondary_row=continuous,
                    evidence={'preferred_distance_m': baseline, 'secondary_distance_m': continuous['distance_m'], 'reason': 'Distance difference without localized gap evidence'}, extra=max(0, difference))
                if decision and decision['decision'] == 'use_preferred': item['requires_user_review'] = False
                elif decision and decision['decision'] == 'use_secondary':
                    full_secondary_choice = True; item['requires_user_review'] = False
                else: unresolved = True
        if known_repair or walk_repair:
            cw['distance_m'] = baseline + known_repair + walk_repair if baseline is not None else None
            cw['run_distance_m'] = run_base + known_repair if run_base is not None and cw['sport'] == 'running' else run_base
            cw['trail_distance_m'] = trail_base + trail_repair if trail_base is not None else None
            cw['recovered_distance_m'] = known_repair + walk_repair; cw['non_running_recovered_distance_m'] = walk_repair
            cw['canonical_status'] = 'reconstructed'; cw['active_distance_m'] = None; cw['timer_duration_s'] = None
            cw['moving_duration_s'] = None; cw['active_pace_min_mile'] = None; cw['active_pace_scope'] = 'partial_Garmin_pace_separate'
            record('distance_m', base_ids + repair_ids, 'preferred_distance_plus_measured_secondary_gap', 'whole_workout', intervals=ledger['distance_m']['coverage_intervals'] + repaired_intervals)
            record('run_distance_m', base_ids + repair_ids, 'confirmed_running_gap_plus_recorded_running', 'whole_workout', intervals=ledger['distance_m']['coverage_intervals'])
            if trail_repair: record('trail_distance_m', base_ids + repair_ids, 'recovered_motion_within_source_trail_segment', 'whole_workout')
            for field in ('active_distance_m', 'timer_duration_s', 'moving_duration_s', 'active_pace_min_mile'):
                record(field, base_ids, 'unknown_full_coverage_after_distance_repair', 'incomplete')
        if full_secondary_choice:
            cw['distance_m'] = continuous['distance_m']
            if cw['sport'] == 'running': cw['run_distance_m'] = continuous['distance_m']
            cw['recovered_distance_m'] = max(0, continuous['distance_m'] - baseline)
            cw['active_distance_m'] = cw['timer_duration_s'] = cw['moving_duration_s'] = cw['active_pace_min_mile'] = None
            cw['active_pace_scope'] = 'partial_Garmin_pace_separate'; unresolved = False
            record('distance_m', [continuous['activity_id']], 'user_selected_full_source', 'whole_workout')
            if cw['sport'] == 'running': record('run_distance_m', [continuous['activity_id']], 'user_confirmed_run_source', 'whole_workout')
            for field in ('active_distance_m', 'timer_duration_s', 'moving_duration_s', 'active_pace_min_mile'):
                record(field, base_ids, 'unknown_full_coverage_after_user_distance_change', 'incomplete')
            for item in local_issues:
                item['requires_user_review'] = False
                item['resolution'] = 'user_selected_secondary_full_source'
        # User-owned workout overrides can settle distance source, counting and roles.
        override = resolutions.get('workouts', {}).get(cw_id, {})
        run_confirmed = False
        if override:
            applied.add(cw_id)
            chosen_key = override.get('distance_source_activity_id')
            if chosen_key:
                chosen = next((r for r in members if r['activity_id'] == chosen_key or source_key(r) == chosen_key), None)
                if chosen is None or chosen.get('distance_m') is None: raise ValueError('Distance-source override requires an available measured source')
                cw['distance_m'] = chosen['distance_m']; record('distance_m', [chosen['activity_id']], 'user_selected_full_source', 'whole_workout')
                if cw['sport'] == 'running': cw['run_distance_m'] = chosen['distance_m']; record('run_distance_m', [chosen['activity_id']], 'user_confirmed_run_source', 'whole_workout')
            for field, key in (('distance_m', 'distance_m'), ('run_distance_m', 'run_distance_m'), ('trail_distance_m', 'trail_distance_m')):
                if key in override:
                    cw[field] = override[key]; record(field, [], 'user_reported_distance', 'user_confirmed')
            run_keys = override.get('run_distance_source_activity_ids')
            if run_keys:
                run_sources = [r for r in members if r['activity_id'] in run_keys or source_key(r) in run_keys]
                if len(run_sources) != len(run_keys) or any(r['sport'] != 'running' for r in run_sources):
                    raise ValueError('Confirmed running sources must be available unique running activities')
                ordered = sorted(run_sources, key=lambda r:r['start_utc'])
                if any(overlapping(a,b)>5 for a,b in zip(ordered,ordered[1:])):
                    raise ValueError('Confirmed running source intervals overlap; would double-count')
                cw['run_distance_m'] = sum_complete(run_sources,'distance_m')
                if cw['run_distance_m'] is None: raise ValueError('Confirmed running sources lack measured distance')
                trail_sources = [r for r in run_sources if r.get('sub_sport')=='trail']
                cw['trail_distance_m'] = sum_complete(trail_sources,'distance_m') if trail_sources else 0
                run_confirmed = True
                record('run_distance_m',[r['activity_id'] for r in run_sources],'user_confirmed_recorded_running_sources','user_confirmed')
                record('trail_distance_m',[r['activity_id'] for r in trail_sources],'user_confirmed_recorded_trail_sources','user_confirmed')
            if chosen_key or 'distance_m' in override:
                unresolved = False
                for item in local_issues: item['requires_user_review'] = False; item['resolution'] = 'user_workout_override'
                cw['canonical_status'] = 'user_confirmed'
                if cw['distance_m'] != baseline:
                    cw['active_pace_min_mile'] = None; cw['timer_duration_s'] = None; cw['active_distance_m'] = None; cw['moving_duration_s'] = None
                    cw['active_pace_scope'] = 'partial_Garmin_pace_separate'
                    for field in ('active_pace_min_mile', 'timer_duration_s', 'moving_duration_s', 'active_distance_m'):
                        record(field, base_ids, 'unknown_full_coverage_after_user_distance_change', 'incomplete')
            if override.get('note'): notes.append(str(override['note']))
        if any(item['user_decision'] and not item['requires_user_review'] for item in local_issues) and not unresolved:
            cw['canonical_status'] = 'user_confirmed'
        if cw['distance_m'] is None or cw['run_distance_m'] is None or source_overlap: unresolved = True
        if cw['distance_m'] is not None and cw['run_distance_m'] is not None and cw['run_distance_m'] > cw['distance_m'] + .001:
            raise ValueError('Confirmed running distance exceeds physical distance')
        if cw['run_distance_m'] is not None and cw['trail_distance_m'] is not None and cw['trail_distance_m'] > cw['run_distance_m'] + .001:
            raise ValueError('Confirmed trail distance exceeds running distance')
        if unresolved:
            cw['provisional_distance_m'] = cw['distance_m']; cw['provisional_run_distance_m'] = cw['run_distance_m']
            cw['distance_m'] = None
            if 'run_distance_m' not in override and not run_confirmed: cw['run_distance_m'] = None
            cw['active_pace_min_mile'] = None; cw['active_distance_m'] = None
            cw['canonical_status'] = 'ambiguous'; cw['confidence'] = 'low'
            cw['mileage_requires_user_review'] = cw['run_distance_m'] is None
            cw['physical_distance_requires_user_review'] = True
            record('distance_m', base_ids + repair_ids, 'unresolved_see_provisional_and_issues', 'incomplete', 'low')
            if cw['run_distance_m'] is None: record('run_distance_m', base_ids + repair_ids, 'unresolved_running_count', 'incomplete', 'low')
            for field in ('active_distance_m', 'active_pace_min_mile'):
                record(field, base_ids, 'unknown_full_coverage_while_distance_unresolved', 'incomplete', 'low')
        cw['requires_user_review'] = unresolved or any(item['requires_user_review'] for item in local_issues)
        cw['candidate_additional_distance_m'] = sum(max(0, item['candidate_additional_distance_m'] or 0) for item in local_issues if item['requires_user_review'])
        if not unresolved: cw['provisional_distance_m'] = cw['distance_m']; cw['provisional_run_distance_m'] = cw['run_distance_m']
        cw['distance_miles'] = cw['distance_m'] / MILE if cw['distance_m'] is not None else None
        cw['run_distance_miles'] = cw['run_distance_m'] / MILE if cw['run_distance_m'] is not None else None
        cw['trail_distance_miles'] = cw['trail_distance_m'] / MILE if cw['trail_distance_m'] is not None else None
        cw['elapsed_pace_min_mile'] = elapsed / 60 / cw['distance_miles'] if cw['distance_miles'] else None
        record('elapsed_pace_min_mile', ledger['distance_m']['source_activity_ids'] + elapsed_ids, 'elapsed_over_canonical_physical_distance', 'whole_workout', cw['confidence'])
        if cw['estimated_stationary_duration_s'] is not None:
            record('estimated_stationary_duration_s', [continuous['activity_id']] if continuous else [], 'secondary_sample_speed_below_0.2_mps', 'observed_gaps')
        for field, basis in (('distance_miles', 'distance_m'), ('run_distance_miles', 'run_distance_m'), ('trail_distance_miles', 'trail_distance_m')):
            record(field, ledger[basis]['source_activity_ids'], 'meters_to_miles', ledger[basis]['coverage_scope'], ledger[basis]['confidence'])
        for field in ('local_date', 'start_local', 'end_local'):
            record(field, elapsed_ids, 'America/Los_Angeles_calendar_conversion', 'whole_workout')
        for field in ('provisional_distance_m', 'provisional_run_distance_m', 'recorded_active_pace_min_mile'):
            record(field, base_ids + repair_ids if field.startswith('provisional') else base_ids,
                   'explicit_provisional_baseline' if field.startswith('provisional') else 'timer_over_recorded_distance', 'recorded_portions')
        for field in ('recovered_distance_m', 'non_running_recovered_distance_m', 'candidate_additional_distance_m'):
            record(field, base_ids + repair_ids + [identifier for item in local_issues for identifier in item['source_activity_ids']], 'measured_gap_decision_ledger', 'observed_gaps', cw['confidence'])
        for field, basis in (('distance_source_activity_ids', 'distance_m'), ('pace_source_activity_ids', 'recorded_active_pace_min_mile'),
                             ('hr_source_activity_ids', 'avg_hr_bpm'), ('elevation_source_activity_ids', 'ascent_m'), ('elapsed_source_activity_ids', 'elapsed_duration_s')):
            cw[field] = ledger[basis]['source_activity_ids']
        roles = dict(override.get('segment_roles', {}))
        for session in resolutions.get('session_groups', []): roles.update(session.get('segment_roles', {}))
        for order, source in enumerate(primary, 1):
            role = roles.get(source['activity_id'], roles.get(source_key(source), infer_role(source)))
            sid = stable_id('segment_', [cw_id, source_key(source)])
            segments.append({'workout_segment_id': sid, 'canonical_workout_id': cw_id, 'session_group_id': cw_id,
                'source_activity_id': source['activity_id'], 'segment_order': order, 'segment_role': role,
                'role_source': 'user_resolution' if source['activity_id'] in roles or source_key(source) in roles else ('source_name_or_subsport' if role != 'unknown' else 'unknown'),
                'sport': source['sport'], 'sub_sport': source.get('sub_sport'), 'start_utc': source['start_utc'], 'end_utc': source['end_utc'],
                'distance_m': source.get('distance_m'), 'timer_duration_s': source.get('timer_duration_s'),
                'counts_separately_in_training_totals': False, 'included_in_parent_distance': True,
                'distance_coverage': 'recorded_portion', 'name': source.get('activity_name')})
        for item in local_issues:
            if item['resolution'] not in ('automatic_secondary_gap_repair', 'user_include_running', 'user_include_walking'): continue
            if item.get('candidate_additional_distance_m') is None or not item['start_utc']: continue
            segments.append({'workout_segment_id': stable_id('segment_', [cw_id, item['issue_id']]),
                'canonical_workout_id': cw_id, 'session_group_id': cw_id, 'source_activity_id': continuous['activity_id'],
                'segment_order': None, 'segment_role': 'walk' if item['user_decision'] == 'include_walking' else 'unknown',
                'role_source': 'user_resolution' if item['user_decision'] else 'unknown', 'sport': 'walking' if item['user_decision'] == 'include_walking' else cw['sport'],
                'sub_sport': None, 'start_utc': item['start_utc'], 'end_utc': item['end_utc'],
                'distance_m': item['candidate_additional_distance_m'], 'timer_duration_s': None,
                'counts_separately_in_training_totals': False, 'included_in_parent_distance': True,
                'distance_coverage': 'secondary_recovered_gap', 'name': 'Recovered secondary-device movement'})
        for source in members:
            relationships.append({'canonical_workout_id': cw_id, 'source_activity_id': source['activity_id'],
                'source_activity_key': source_key(source), 'device_family': source['device_family'],
                'relationship_type': 'primary_segment' if source['activity_id'] in base_ids else 'comparison_recording',
                'counts_separately_in_training_totals': False})
        cw['summary_note'] = ' '.join(dict.fromkeys(notes)) or ('Preferred source segments counted once; continuous recording retained.' if is_composite else 'Source metrics preserved; watch duplicates counted once.' if len(members) > 1 else 'Direct source recording.')
        if unresolved:
            cw['summary_note'] += ' Physical outing distance unresolved; running distance separately confirmed.' if not cw['mileage_requires_user_review'] else ' Mileage unresolved; provisional values are not a confirmed total.'
        cw['source_segment_count'] = len(primary)
        cw['segment_count'] = sum(s['canonical_workout_id']==cw_id for s in segments)
        for field in ('segment_count', 'source_segment_count', 'canonical_status', 'confidence', 'requires_user_review', 'mileage_requires_user_review', 'physical_distance_requires_user_review'):
            record(field, [r['activity_id'] for r in members], 'canonical_relationship_and_issue_rules', 'whole_workout', cw['confidence'])
        cw['revision'] = stable_id('revision_', [json.dumps(cw, sort_keys=True, default=str), *(r.get('content_sha256', r['activity_id']) for r in members), json.dumps(override, sort_keys=True), json.dumps(local_issues, sort_keys=True, default=str)])
        for field, metadata in ledger.items():
            unit = 'm' if field.endswith('_m') else 's' if field.endswith('_s') else 'min/mile' if 'pace' in field else 'bpm' if field.endswith('_bpm') else 'ISO UTC' if field.endswith('_utc') else 'native source unit'
            provenance.append({'canonical_workout_id': cw_id, 'field_name': field, 'value': cw.get(field), 'unit': unit, **metadata})
        for item in local_issues:
            issues.append(item)
            if item['requires_user_review']:
                review.append({'issue_id': item['issue_id'], 'canonical_workout_id': cw_id, 'date': cw['local_date'],
                    'source_activities': item['source_activity_ids'], 'detected_problem': item['classification'],
                    'suggested_interpretation': 'Movement in a Garmin gap is not automatically running; confirm context and counting.',
                    'candidate_distance_m': item['candidate_additional_distance_m'], 'candidate_elapsed_time_s': (dt(item['end_utc']) - dt(item['start_utc'])).total_seconds() if item['start_utc'] and item['end_utc'] else None,
                    'confidence': item['confidence'],
                    'question_for_user': 'Was this running/hiking to include as running, separate walking/social movement, a stationary stop, a separate activity, or unsure? For total-distance conflicts, which source is supported?',
                    'user_decision': item['user_decision'], 'resolution': item['resolution']})
        workouts.append(cw)
        for item, decision, evidence, secondary_row in separate_gaps:
            extra = dict(cw)
            extra_id = stable_id('cw_', [cw_id, item['issue_id'], 'user_separate_activity'])
            start_extra, end_extra = dt(evidence['sampled_start_utc']), dt(evidence['sampled_end_utc'])
            distance = evidence['recoverable_distance_m']
            for field in ('avg_hr_bpm', 'max_hr_bpm', 'ascent_m', 'descent_m', 'training_load', 'intervals_load', 'training_stress_score',
                          'aerobic_training_effect', 'anaerobic_training_effect', 'timer_duration_s', 'moving_duration_s', 'active_distance_m',
                          'active_pace_min_mile', 'recorded_active_distance_m', 'recorded_active_duration_s', 'recorded_active_pace_min_mile', 'estimated_stationary_duration_s'):
                extra[field] = None
            extra.update(canonical_workout_id=extra_id,session_group_id=extra_id,local_date=start_extra.astimezone(LOCAL).date().isoformat(),
                start_utc=start_extra.isoformat(),end_utc=end_extra.isoformat(),start_local=start_extra.astimezone(LOCAL).isoformat(),end_local=end_extra.astimezone(LOCAL).isoformat(),
                sport=decision['sport'],sub_sport=None,source_activity_ids=[secondary_row['activity_id']],primary_source_activity_ids=[secondary_row['activity_id']],
                segment_count=1,source_segment_count=1,canonical_status='user_confirmed',confidence='high',requires_user_review=False,mileage_requires_user_review=False,
                physical_distance_requires_user_review=False,distance_m=distance,run_distance_m=distance if decision['sport']=='running' else 0,
                trail_distance_m=0,provisional_distance_m=distance,provisional_run_distance_m=distance if decision['sport']=='running' else 0,
                candidate_additional_distance_m=0,recovered_distance_m=distance,non_running_recovered_distance_m=0 if decision['sport']=='running' else distance,
                elapsed_duration_s=(end_extra-start_extra).total_seconds(),active_pace_scope='unknown',elevation_source='unknown',
                distance_miles=distance/MILE,run_distance_miles=distance/MILE if decision['sport']=='running' else 0,trail_distance_miles=0,
                elapsed_pace_min_mile=(end_extra-start_extra).total_seconds()/60/(distance/MILE) if distance else None,
                summary_note='User-separated measured secondary-device gap; excluded from original parent distance.')
            for field in ('distance_source_activity_ids','elapsed_source_activity_ids'): extra[field]=[secondary_row['activity_id']]
            for field in ('pace_source_activity_ids','hr_source_activity_ids','elevation_source_activity_ids'): extra[field]=[]
            extra.pop('revision',None); extra['revision']=stable_id('revision_', [json.dumps(extra,sort_keys=True,default=str),json.dumps(decision,sort_keys=True)])
            workouts.append(extra)
            relationships.append({'canonical_workout_id':extra_id,'source_activity_id':secondary_row['activity_id'],
                'source_activity_key':source_key(secondary_row),'device_family':secondary_row['device_family'],
                'relationship_type':'user_separated_gap','counts_separately_in_training_totals':False})
            segments.append({'workout_segment_id':stable_id('segment_',[extra_id,item['issue_id']]),'canonical_workout_id':extra_id,'session_group_id':extra_id,
                'source_activity_id':secondary_row['activity_id'],'segment_order':1,'segment_role':'walk' if decision['sport']=='walking' else 'unknown',
                'role_source':'user_resolution','sport':decision['sport'],'sub_sport':None,'start_utc':extra['start_utc'],'end_utc':extra['end_utc'],
                'distance_m':distance,'timer_duration_s':None,'counts_separately_in_training_totals':False,'included_in_parent_distance':True,
                'distance_coverage':'user_separated_measured_gap','name':'User-separated gap movement'})
            for field in ledger:
                provenance.append({'canonical_workout_id':extra_id,'field_name':field,'value':extra.get(field),'unit':next(p['unit'] for p in provenance if p['canonical_workout_id']==cw_id and p['field_name']==field),
                    'source_activity_ids':item['source_activity_ids'] if extra.get(field) is not None else [],'method':'user_separated_secondary_gap' if extra.get(field) is not None else 'not_measured',
                    'coverage_scope':'extracted_gap','confidence':'high','coverage_intervals':[{'source_activity_id':secondary_row['activity_id'],'start_utc':extra['start_utc'],'end_utc':extra['end_utc']}]})
    unmatched = sorted((set(resolutions.get('issues', {})) | set(resolutions.get('workouts', {}))) - applied)
    return {'canonical_workouts': workouts, 'workout_segments': segments, 'source_relationships': relationships,
            'field_provenance': provenance, 'reconstruction_issues': issues, 'reconstruction_review': review,
            'unused_resolution_ids': unmatched}


def canonical_summaries(workouts, weekly=False):
    groups = defaultdict(list)
    for workout in workouts:
        day = dt(workout['start_local']).date()
        if weekly: day -= timedelta(days=day.weekday())
        groups[day.isoformat()].append(workout)
    out = []
    for day, items in sorted(groups.items()):
        runs = [w for w in items if w['sport'] in ('running', 'mixed')]
        unresolved = [w for w in runs if w['run_distance_m'] is None or w['mileage_requires_user_review']]
        known = sum(w['run_distance_m'] for w in runs if w['run_distance_m'] is not None) / MILE
        provisional = sum(w['provisional_run_distance_m'] or 0 for w in unresolved) / MILE
        trail = sum(w['trail_distance_m'] or 0 for w in runs) / MILE
        weights = [w for w in items if w['avg_hr_bpm'] is not None and (w['recorded_active_duration_s'] or 0) > 0]
        def total(field):
            values = [w[field] for w in items if w.get(field) is not None]
            return sum(values) if values else None
        distances = [w['run_distance_miles'] for w in runs if w['run_distance_miles'] is not None]
        durations = [w['elapsed_duration_s'] for w in items if w['elapsed_duration_s'] is not None]
        out.append({'week_starting_local' if weekly else 'date_local': day,
            'counting_basis': 'canonical_physical_workouts', 'activity_count': len(items), 'canonical_workout_count': len(items),
            'source_segment_count': sum(w['source_segment_count'] for w in items), 'running_miles': None if unresolved else known,
            'workout_segment_count': sum(w['segment_count'] for w in items),
            'known_running_miles': known, 'provisional_running_miles': provisional,
            'running_miles_including_provisional': known + provisional,
            'candidate_additional_miles': sum(w['candidate_additional_distance_m'] for w in unresolved) / MILE,
            'unresolved_workout_count': len(unresolved), 'requires_user_review': any(w['requires_user_review'] for w in items),
            'unresolved_physical_distance_count': sum(w['physical_distance_requires_user_review'] for w in items),
            'mileage_complete': not unresolved, 'trail_running_miles': None if unresolved else trail,
            'cycling_miles': sum_complete([w for w in items if w['sport'] == 'cycling'], 'distance_miles') if any(w['sport'] == 'cycling' for w in items) else 0,
            'running_timer_duration_s': sum_complete(runs, 'timer_duration_s') if runs else 0,
            'total_timer_duration_s': total('timer_duration_s'), 'total_elapsed_duration_s': total('elapsed_duration_s'),
            'total_ascent_m': total('ascent_m'), 'ascent_available_activity_count': sum(w['ascent_m'] is not None for w in items),
            'long_run_miles': max(distances) if distances else None, 'longest_activity_timer_s': max((w['timer_duration_s'] for w in items if w['timer_duration_s'] is not None), default=None),
            'longest_workout_elapsed_s': max(durations) if durations else None,
            'duration_weighted_avg_hr_bpm': sum(w['avg_hr_bpm'] * w['recorded_active_duration_s'] for w in weights) / sum(w['recorded_active_duration_s'] for w in weights) if weights else None,
            'hr_weighted_duration_s': sum(w['recorded_active_duration_s'] for w in weights),
            'training_load_sum': total('training_load'), 'training_load_available_activity_count': sum(w['training_load'] is not None for w in items),
            'intervals_load_sum': total('intervals_load'), 'training_stress_score_sum': total('training_stress_score')})
    return out
