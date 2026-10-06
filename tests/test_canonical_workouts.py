"""Scenario fixtures for physical-workout counting and evidence-based repair."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from canonical_workouts import reconstruct, canonical_summaries, load_resolutions, MILE
from preprocess_fit import metrics, times, duplicates, composite_duplicates

START = datetime(2026, 10, 6, 17, tzinfo=timezone.utc)


def source(aid, device='Garmin', start=START, duration=1200, distance=3000, name='Morning Run', trail=False):
    row = {'activity_id': aid, 'intervals_activity_id': 'i_' + aid, 'source_filename': aid + '.fit',
           'content_sha256': 'hash_' + aid, 'device_family': device, 'activity_name': name,
           'sport': 'running', 'sub_sport': 'trail' if trail else 'generic',
           'terrain_type': 'trail' if trail else 'road_or_unspecified', 'record_count': 200,
           'elevation_source': 'unknown', 'intervals_load': None,
           **metrics({'total_distance': distance, 'total_elapsed_time': duration, 'total_timer_time': duration,
                      'avg_heart_rate': 135 if device == 'Garmin' else 140, 'max_heart_rate': 160,
                      'total_ascent': 120 if device == 'Garmin' else 140, 'total_descent': 115})}
    times(row, 'start', start); times(row, 'end', start + timedelta(seconds=duration))
    return row


def paired_gap(gap=(360, 660), stationary=False, timer_events=True, secondary=True, cadence=True, sparse=False, reset=False):
    duration = 1200; speed = 2.5
    length = gap[1] - gap[0]
    missing = 0 if stationary else length * speed
    physical = duration * speed - (length * speed if stationary else 0)
    garmin = source('g', distance=physical - missing)
    garmin['timer_duration_s'] = duration - length
    garmin['timer_pace_min_mile'] = garmin['timer_duration_s'] / 60 / (garmin['distance_m'] / MILE)
    amazfit = source('a', device='Amazfit', distance=physical)
    rows = [garmin, amazfit] if secondary else [garmin]
    records_g = []; records_a = []
    for seconds in range(0, duration + 1, 6):
        removed = max(0, min(seconds, gap[1]) - gap[0])
        distance_a = speed * seconds - (removed * speed if stationary else 0)
        stamp = (START + timedelta(seconds=seconds)).isoformat()
        record = {'timestamp_utc': stamp, 'distance_m': distance_a, 'hr_bpm': 145,
                  'cadence_fit_rpm': (0 if stationary and gap[0] <= seconds < gap[1] else 80) if cadence else None,
                  'speed_mps': 0 if stationary and gap[0] <= seconds < gap[1] else speed,
                  'latitude_deg': 34.1234, 'longitude_deg': -118.2345}
        if not sparse or seconds % 60 == 0: records_a.append(record)
        if not gap[0] < seconds < gap[1]:
            records_g.append({**record, 'distance_m': speed * seconds - removed * speed})
    if reset:
        for record in records_a:
            if (datetime.fromisoformat(record['timestamp_utc']) - START).total_seconds() >= 480: record['distance_m'] -= 1000
    events = [{'timestamp_utc': START.isoformat(), 'event_type': 'start'},
              {'timestamp_utc': (START + timedelta(seconds=gap[0])).isoformat(), 'event_type': 'stop'},
              {'timestamp_utc': (START + timedelta(seconds=gap[1])).isoformat(), 'event_type': 'start'}] if timer_events else []
    timelines = {'g': {'records': records_g, 'timer_events': events}}
    if secondary: timelines['a'] = {'records': records_a, 'timer_events': []}
    return rows, timelines


def normalize(rows, timelines=None, resolutions=None):
    pairs = duplicates(rows)
    groups = composite_duplicates(rows, pairs)
    return reconstruct(rows, pairs, groups, timelines, resolutions)


class CanonicalScenarios(unittest.TestCase):
    def test_identical_dual_watch_workout_counted_once(self):
        result = normalize([source('g'), source('a', device='Amazfit')])
        self.assertEqual(len(result['canonical_workouts']), 1)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['canonical_status'], 'duplicate_resolved')
        self.assertEqual(workout['distance_m'], 3000)
        self.assertEqual(workout['avg_hr_bpm'], 135)
        self.assertEqual(canonical_summaries(result['canonical_workouts'])[0]['running_miles'], 3000 / MILE)
        self.assertEqual(len(result['source_relationships']), 2)

    def test_stationary_pause_does_not_add_phantom_distance(self):
        rows, timelines = paired_gap(stationary=True)
        result = normalize(rows, timelines)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['distance_m'], rows[0]['distance_m'])
        self.assertEqual(workout['recovered_distance_m'], 0)
        self.assertEqual(result['reconstruction_issues'][0]['classification'], 'intentional_stationary_pause')
        self.assertGreater(workout['estimated_stationary_duration_s'], 250)
        self.assertIsNotNone(workout['active_pace_min_mile'])
        self.assertFalse(workout['mileage_requires_user_review'])

    def test_forgotten_resume_repairs_using_measured_secondary_gap(self):
        rows, timelines = paired_gap()
        original = copy.deepcopy(rows)
        result = normalize(rows, timelines)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['canonical_status'], 'reconstructed')
        self.assertEqual(workout['distance_m'], 3000)
        self.assertEqual(workout['recovered_distance_m'], 750)
        self.assertEqual(workout['avg_hr_bpm'], 135)
        self.assertEqual(workout['ascent_m'], 120)
        self.assertEqual(workout['elapsed_duration_s'], 1200)
        self.assertIsNone(workout['active_pace_min_mile'])
        self.assertIsNone(workout['timer_duration_s'])
        self.assertAlmostEqual(workout['recorded_active_pace_min_mile'], 900 / 60 / (2250 / MILE))
        self.assertEqual(rows[0]['distance_m'], original[0]['distance_m'])
        metric = next(p for p in result['field_provenance'] if p['field_name'] == 'distance_m')
        self.assertEqual(set(metric['source_activity_ids']), {'g', 'a'})
        self.assertFalse(workout['requires_user_review'])

    def test_half_mile_gap_recovered(self):
        rows, timelines = paired_gap(gap=(300, 624))
        result = normalize(rows, timelines)
        workout = result['canonical_workouts'][0]
        self.assertAlmostEqual(workout['recovered_distance_m'], 810)
        self.assertAlmostEqual(workout['recovered_distance_m'] / MILE, .5033, places=3)
        self.assertEqual(workout['run_distance_m'], 3000)

    def test_split_warmup_workout_cooldown_keeps_three_segments(self):
        rows = [source('continuous', device='Amazfit', duration=1220, distance=3050),
                source('warm', duration=400, distance=1000, name='Warmup'),
                source('work', start=START + timedelta(seconds=410), duration=400, distance=1000, name='Track workout'),
                source('cool', start=START + timedelta(seconds=820), duration=400, distance=1000, name='Cooldown')]
        result = normalize(rows)
        self.assertEqual(len(result['canonical_workouts']), 1)
        self.assertEqual(result['canonical_workouts'][0]['distance_m'], 3000)
        self.assertEqual([r['segment_role'] for r in result['workout_segments']], ['warmup', 'workout', 'cooldown'])
        self.assertEqual(canonical_summaries(result['canonical_workouts'])[0]['running_miles'], 3000 / MILE)
        self.assertTrue(all(not r['counts_separately_in_training_totals'] for r in result['workout_segments']))

    def test_genuine_same_day_doubles_remain_separate(self):
        result = normalize([source('morning'), source('evening', start=START + timedelta(hours=8))])
        self.assertEqual(len(result['canonical_workouts']), 2)
        self.assertEqual(canonical_summaries(result['canonical_workouts'])[0]['running_miles'], 6000 / MILE)

    def test_social_walking_not_silently_running_mileage(self):
        rows, timelines = paired_gap(cadence=False)
        result = normalize(rows, timelines)
        issue = next(i for i in result['reconstruction_issues'] if i['classification'] == 'probable_forgotten_resume')
        self.assertTrue(issue['requires_user_review'])
        resolutions = {'issues': {issue['issue_id']: {'decision': 'include_walking'}}}
        result = reconstruct(rows, timelines=timelines, resolutions=resolutions)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['distance_m'], 3000)
        self.assertEqual(workout['run_distance_m'], 2250)
        self.assertEqual(workout['non_running_recovered_distance_m'], 750)

    def test_october_five_composite_garmin_sum_retained(self):
        rows = [source('a', device='Amazfit', start=START, distance=13839, duration=9207),
                source('g1', start=START + timedelta(seconds=4), distance=5671.01, duration=2291),
                source('g2', start=START + timedelta(seconds=2328), distance=7867.85, duration=6879, trail=True)]
        result = normalize(rows)
        self.assertEqual(len(result['canonical_workouts']), 1)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['distance_m'], 13538.86)
        self.assertEqual(workout['trail_distance_m'], 7867.85)
        self.assertEqual(workout['elapsed_duration_s'], 9207)
        self.assertAlmostEqual(canonical_summaries([workout])[0]['running_miles'], 8.412658, places=5)
        self.assertEqual([r['segment_role'] for r in result['workout_segments']], ['unknown', 'trail'])

    def test_device_dropout_requires_context_even_with_secondary_movement(self):
        rows, timelines = paired_gap(timer_events=False)
        result = normalize(rows, timelines)
        self.assertEqual(result['reconstruction_issues'][0]['classification'], 'device_dropout')
        self.assertIsNone(result['canonical_workouts'][0]['run_distance_m'])
        self.assertEqual(result['canonical_workouts'][0]['recovered_distance_m'], 0)
        self.assertGreater(result['canonical_workouts'][0]['candidate_additional_distance_m'], 700)

    def test_conflicting_total_distance_without_gap_evidence_requires_review(self):
        result = normalize([source('g', distance=2300), source('a', device='Amazfit', distance=3000)])
        self.assertEqual(len(result['canonical_workouts']), 1)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['canonical_status'], 'ambiguous')
        self.assertIsNone(workout['distance_m'])
        self.assertEqual(workout['provisional_distance_m'], 2300)
        summary = canonical_summaries([workout])[0]
        self.assertIsNone(summary['running_miles'])
        self.assertAlmostEqual(summary['provisional_running_miles'], 2300 / MILE)
        self.assertAlmostEqual(summary['candidate_additional_miles'], 700 / MILE)

    def test_user_resolution_persists_on_rerun_and_input_is_not_overwritten(self):
        rows, timelines = paired_gap(timer_events=False)
        pairs = duplicates(rows); composite_duplicates(rows, pairs)
        result = reconstruct(rows, pairs, timelines=timelines)
        issue_id = result['reconstruction_issues'][0]['issue_id']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'user_resolutions.json'
            payload = {'schema_version': 1, 'issues': {issue_id: {'decision': 'include_running'}}, 'workouts': {}, 'session_groups': []}
            path.write_text(json.dumps(payload)); original = path.read_bytes()
            first = reconstruct(rows, pairs, timelines=timelines, resolutions=load_resolutions(path))
            second = reconstruct(rows, pairs, timelines=timelines, resolutions=load_resolutions(path))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(first, second)
            self.assertEqual(first['canonical_workouts'][0]['canonical_status'], 'user_confirmed')
            self.assertEqual(first['canonical_workouts'][0]['distance_m'], 3000)
            self.assertEqual(first['unused_resolution_ids'], [])

    def test_deterministic_results_and_no_source_mutation(self):
        rows, timelines = paired_gap(); pairs = duplicates(rows); groups = composite_duplicates(rows, pairs)
        original_rows = copy.deepcopy(rows); original_timeline = copy.deepcopy(timelines)
        first = reconstruct(rows, pairs, groups, timelines)
        second = reconstruct(rows, pairs, groups, timelines)
        self.assertEqual(first, second)
        self.assertEqual(rows, original_rows); self.assertEqual(timelines, original_timeline)
        self.assertNotIn('latitude', json.dumps(first)); self.assertNotIn('longitude', json.dumps(first))

    def test_daily_weekly_parent_counts_do_not_add_segments_or_comparison(self):
        rows, timelines = paired_gap(); result = normalize(rows, timelines)
        daily = canonical_summaries(result['canonical_workouts'])[0]
        weekly = canonical_summaries(result['canonical_workouts'], True)[0]
        self.assertEqual(daily['activity_count'], 1); self.assertEqual(weekly['activity_count'], 1)
        self.assertEqual(daily['running_miles'], 3000 / MILE)
        self.assertEqual(weekly['running_miles'], 3000 / MILE)
        self.assertEqual(weekly['week_starting_local'], '2026-10-05')

    def test_missing_secondary_watch_does_not_invent_distance(self):
        rows, timelines = paired_gap(secondary=False)
        result = normalize(rows, timelines)
        self.assertEqual(result['canonical_workouts'][0]['canonical_status'], 'direct')
        self.assertEqual(result['canonical_workouts'][0]['distance_m'], 2250)
        self.assertEqual(result['canonical_workouts'][0]['recovered_distance_m'], 0)

    def test_offset_watch_start_still_preserves_independent_timeline(self):
        rows = [source('g'), source('a', device='Amazfit', start=START - timedelta(seconds=15), duration=1215)]
        result = normalize(rows)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['elapsed_duration_s'], 1215)
        self.assertEqual(workout['distance_m'], 3000)
        self.assertEqual(workout['start_utc'], rows[1]['start_utc'])

    def test_elevation_sources_remain_independent_of_distance_source(self):
        rows, timelines = paired_gap()
        rows[0]['elevation_source'] = 'original'; rows[1]['elevation_source'] = 'intervals_corrected'
        result = normalize(rows, timelines)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['ascent_m'], 120)
        self.assertEqual(workout['elevation_source'], 'original')
        provenance = next(p for p in result['field_provenance'] if p['field_name'] == 'ascent_m')
        self.assertEqual(provenance['source_activity_ids'], ['g'])

    def test_sparse_secondary_and_distance_resets_are_never_interpolated(self):
        for kwargs in ({'sparse': True}, {'reset': True}):
            with self.subTest(**kwargs):
                rows, timelines = paired_gap(**kwargs); result = normalize(rows, timelines)
                workout = result['canonical_workouts'][0]
                self.assertEqual(workout['recovered_distance_m'], 0)
                self.assertIsNone(workout['distance_m'])

    def test_user_explicit_session_and_roles_without_continuous_watch(self):
        rows = [source('warm', duration=400, distance=1000), source('cool', start=START + timedelta(seconds=450), duration=400, distance=1000)]
        resolutions = {'session_groups': [{'source_activity_ids': ['i_warm', 'i_cool'], 'segment_roles': {'i_warm': 'warmup', 'i_cool': 'cooldown'}}]}
        result = normalize(rows, resolutions=resolutions)
        self.assertEqual(len(result['canonical_workouts']), 1)
        self.assertEqual([s['segment_role'] for s in result['workout_segments']], ['warmup', 'cooldown'])
        self.assertEqual(result['canonical_workouts'][0]['distance_m'], 2000)

    def test_unknown_running_distance_is_not_zero(self):
        row = source('g'); row['distance_m'] = None
        result = normalize([row]); summary = canonical_summaries(result['canonical_workouts'])[0]
        self.assertIsNone(summary['running_miles']); self.assertFalse(summary['mileage_complete'])

    def test_source_encoding_change_preserves_workout_identity_changes_revision(self):
        rows = [source('g')]; first = normalize(rows)['canonical_workouts'][0]
        rows[0]['content_sha256'] = 'new_encoding'; rows[0]['activity_id'] = 'changed_hash_id'
        second = normalize(rows)['canonical_workouts'][0]
        self.assertEqual(first['canonical_workout_id'], second['canonical_workout_id'])
        self.assertNotEqual(first['revision'], second['revision'])

    def test_user_selects_secondary_full_source_without_fabrication(self):
        rows = [source('g', distance=2300), source('a', device='Amazfit', distance=3000)]
        result = normalize(rows); workout = result['canonical_workouts'][0]
        resolution = {'workouts': {workout['canonical_workout_id']: {'distance_source_activity_id': 'i_a', 'note': 'Jay confirms missed resume'}}}
        result = reconstruct(rows, resolutions=resolution)
        workout = result['canonical_workouts'][0]
        self.assertEqual(workout['canonical_status'], 'user_confirmed')
        self.assertEqual(workout['distance_m'], 3000); self.assertEqual(workout['run_distance_m'], 3000)
        self.assertEqual(workout['avg_hr_bpm'], 135); self.assertIsNone(workout['active_pace_min_mile'])

    def test_user_stationary_decision_overrides_automatic_moving_gap_repair(self):
        rows, timelines = paired_gap(); initial = normalize(rows, timelines)
        issue_id = initial['reconstruction_issues'][0]['issue_id']
        result = reconstruct(rows, timelines=timelines, resolutions={'issues': {issue_id: {'decision': 'stationary_stop'}}})
        self.assertEqual(result['canonical_workouts'][0]['distance_m'], 2250)
        self.assertEqual(result['canonical_workouts'][0]['recovered_distance_m'], 0)
        self.assertEqual(result['canonical_workouts'][0]['canonical_status'], 'user_confirmed')

    def test_user_separate_gap_counts_once_under_independent_parent(self):
        rows, timelines = paired_gap(timer_events=False); initial = normalize(rows, timelines)
        issue_id = initial['reconstruction_issues'][0]['issue_id']
        result = reconstruct(rows, timelines=timelines, resolutions={'issues': {issue_id: {'decision': 'separate_activity', 'sport': 'walking'}}})
        self.assertEqual(len(result['canonical_workouts']), 2)
        parents = result['canonical_workouts']
        self.assertEqual(sum(w['distance_m'] for w in parents), 3000)
        self.assertEqual(sum(w['run_distance_m'] for w in parents), 2250)
        summary = canonical_summaries(parents)[0]
        self.assertAlmostEqual(summary['running_miles'], 2250 / MILE)
        self.assertEqual(parents[1]['sport'], 'walking')
        self.assertFalse(parents[1]['requires_user_review'])
        self.assertIsNone(parents[1]['avg_hr_bpm'])

    def test_confirmed_running_sources_do_not_hide_unresolved_physical_distance(self):
        rows, timelines = paired_gap(timer_events=False); initial = normalize(rows, timelines)
        cwid = initial['canonical_workouts'][0]['canonical_workout_id']
        result = reconstruct(rows, timelines=timelines, resolutions={'workouts': {cwid: {'run_distance_source_activity_ids': ['i_g']}}})
        workout = result['canonical_workouts'][0]
        self.assertIsNone(workout['distance_m'])
        self.assertEqual(workout['run_distance_m'], 2250)
        self.assertTrue(workout['physical_distance_requires_user_review'])
        self.assertFalse(workout['mileage_requires_user_review'])
        self.assertAlmostEqual(canonical_summaries([workout])[0]['running_miles'], 2250 / MILE)

    def test_secondary_selection_decision_uses_full_measured_source(self):
        rows, timelines = paired_gap(timer_events=False); initial = normalize(rows, timelines)
        issue_id = initial['reconstruction_issues'][0]['issue_id']
        result = reconstruct(rows, timelines=timelines, resolutions={'issues': {issue_id: {'decision': 'use_secondary'}}})
        self.assertEqual(result['canonical_workouts'][0]['distance_m'], 3000)
        self.assertEqual(result['canonical_workouts'][0]['canonical_status'], 'user_confirmed')
        field = next(p for p in result['field_provenance'] if p['field_name'] == 'distance_m')
        self.assertEqual(field['method'], 'user_selected_full_source')

    def test_preserved_resolution_validates_instead_of_applying_typo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resolution.json'
            for payload in ({'schema_version': 1, 'issues': {'id': {'decision': 'guess'}}},
                            {'schema_version': 1, 'workouts': {'id': {'distance_m': -1}}},
                            {'schema_version': 1, 'issues': {'id': {'decision': 'separate_activity'}}}):
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError): load_resolutions(path)

    def test_cross_midnight_allocates_whole_workout_to_start_date(self):
        start = datetime(2026, 10, 7, 6, 50, tzinfo=timezone.utc)
        result = normalize([source('night', start=start, duration=1200)])
        summary = canonical_summaries(result['canonical_workouts'])
        self.assertEqual(len(summary), 1); self.assertEqual(summary[0]['date_local'], '2026-10-06')

    def test_reconstructed_trail_distance_has_secondary_provenance(self):
        rows, timelines = paired_gap(); rows[0]['sub_sport'] = 'trail'
        result = normalize(rows, timelines)
        self.assertEqual(result['canonical_workouts'][0]['trail_distance_m'], 3000)
        provenance = next(p for p in result['field_provenance'] if p['field_name'] == 'trail_distance_m')
        self.assertEqual(set(provenance['source_activity_ids']), {'g', 'a'})

    def test_input_order_is_not_a_new_canonical_revision(self):
        rows, timelines = paired_gap(); initial = normalize(rows, timelines)
        result = reconstruct(list(reversed(rows)), timelines=timelines)
        self.assertEqual(initial, result)

    def test_all_selected_and_derived_metrics_have_provenance(self):
        rows, timelines = paired_gap(); result = normalize(rows, timelines)
        names = {p['field_name'] for p in result['field_provenance']}
        self.assertTrue({'distance_m','run_distance_m','distance_miles','elapsed_pace_min_mile','recorded_active_pace_min_mile','local_date','canonical_status'} <= names)
        for p in result['field_provenance']:
            self.assertIn('coverage_scope', p); self.assertIn('coverage_intervals', p)

    def test_schema_matches_direct_repaired_and_separate_workout_shapes(self):
        schema = json.loads(Path('docs/CANONICAL_SCHEMA.json').read_text())['items']
        rows, timelines = paired_gap(); initial = normalize(rows, timelines)
        issue_id = initial['reconstruction_issues'][0]['issue_id']
        separate = reconstruct(rows, timelines=timelines, resolutions={'issues': {issue_id: {'decision': 'separate_activity', 'sport': 'walking'}}})
        for result in (initial, normalize([source('alone')]), separate):
            for w in result['canonical_workouts']:
                self.assertEqual(set(w), set(schema['properties']))

    def test_garmin_physiology_does_not_change_when_distance_reconstructed(self):
        rows, timelines = paired_gap()
        rows[0]['aerobic_training_effect'] = 3.5; rows[0]['anaerobic_training_effect'] = 1.2
        rows[1]['aerobic_training_effect'] = 99
        result = normalize(rows, timelines)
        self.assertEqual(result['canonical_workouts'][0]['aerobic_training_effect'], 3.5)
        p = next(p for p in result['field_provenance'] if p['field_name'] == 'aerobic_training_effect')
        self.assertEqual(p['source_activity_ids'], ['g'])


if __name__ == '__main__': unittest.main()
