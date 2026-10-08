"""Canonical moving time excludes stops once and changes transport revisions."""
import copy
import unittest
from datetime import timedelta
from canonical_workouts import reconstruct
from test_canonical_workouts import START, source, normalize, paired_gap


def fixture(pauses=(), stationary=(), timer=True, records=True):
    row = source('g', duration=100, distance=200)
    if not timer: row['timer_duration_s'] = None
    else: row['timer_duration_s'] = 100 - sum(b-a for a,b in pauses)
    points = []; distance = 0
    for seconds in range(101):
        if seconds and not any(a <= seconds-1 < b for a,b in (*pauses, *stationary)):
            distance += 2
        points.append({'timestamp_utc':(START+timedelta(seconds=seconds)).isoformat(), 'distance_m':distance,'speed_mps':2})
    row['distance_m'] = distance
    events = [{'timestamp_utc':(START+timedelta(seconds=a)).isoformat(),'event_type':'stop'} for a,b in pauses]
    events += [{'timestamp_utc':(START+timedelta(seconds=b)).isoformat(),'event_type':'start'} for a,b in pauses]
    return row, {'g':{'records':points if records else [],'timer_events':events}}


class MovingDurationTests(unittest.TestCase):
    def test_no_stops_complete_record_fallback(self):
        row,timeline=fixture()
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertEqual(w['moving_duration_s'],100)

    def test_manual_pause_is_excluded_once(self):
        row,timeline=fixture(pauses=((40,60),))
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertEqual(w['timer_duration_s'],80)
        self.assertEqual(w['moving_duration_s'],80)

    def test_stationary_period_with_running_timer(self):
        row,timeline=fixture(stationary=((40,60),))
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertEqual(w['timer_duration_s'],100)
        self.assertEqual(w['moving_duration_s'],80)

    def test_combined_pause_and_stationary_is_not_double_subtracted(self):
        row,timeline=fixture(pauses=((40,60),),stationary=((40,60),(70,80)))
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertEqual(w['moving_duration_s'],70)

    def test_missing_timer_can_use_complete_record_fallback(self):
        row,timeline=fixture(pauses=((40,60),),stationary=((70,80),),timer=False)
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertIsNone(w['timer_duration_s'])
        self.assertEqual(w['moving_duration_s'],70)

    def test_timer_alone_does_not_become_moving_time(self):
        row,timeline=fixture(records=False)
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertIsNone(w['moving_duration_s'])

    def test_explicit_intervals_moving_metric_is_not_timer_alias(self):
        row,timeline=fixture(records=False)
        row['intervals_moving_duration_s']=63
        result=reconstruct([row],timelines=timeline)
        w=result['canonical_workouts'][0]
        self.assertEqual(w['moving_duration_s'],63)
        p=next(p for p in result['field_provenance'] if p['field_name']=='moving_duration_s')
        self.assertEqual(p['method'],'Intervals_activity_index_moving_time')
        self.assertEqual(p['source_activity_ids'],['g'])
        self.assertEqual(p['unit'],'s')

    def test_existing_stationary_gap_estimate_is_not_subtracted_from_moving_metric(self):
        rows,timeline=paired_gap(stationary=True)
        rows[0]['intervals_moving_duration_s']=900
        result=normalize(rows,timeline);w=result['canonical_workouts'][0]
        self.assertGreater(w['estimated_stationary_duration_s'],250)
        self.assertEqual(w['moving_duration_s'],900)

    def test_confirmed_movement_missed_during_garmin_pause_uses_whole_continuous_source(self):
        rows,timeline=paired_gap()
        result=normalize(rows,timeline);w=result['canonical_workouts'][0]
        self.assertEqual(w['moving_duration_s'],1200)
        self.assertIsNone(w['timer_duration_s'])
        self.assertIsNone(w['active_pace_min_mile'])
        p=next(p for p in result['field_provenance'] if p['field_name']=='moving_duration_s')
        self.assertEqual(p['source_activity_ids'],['a'])
        self.assertEqual(p['coverage_scope'],'whole_continuous_reconstructed_outing')

    def test_fit_moving_zero_is_known_and_preferred_over_csv(self):
        row,timeline=fixture(records=False);row['moving_duration_s']=0;row['intervals_moving_duration_s']=90
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertEqual(w['moving_duration_s'],0)

    def test_incomplete_active_samples_stay_unknown(self):
        row,timeline=fixture()
        timeline['g']['records']=[r for i,r in enumerate(timeline['g']['records']) if i<=30 or i>=80]
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertIsNone(w['moving_duration_s'])

    def test_out_of_range_moving_measurement_stays_unknown(self):
        row,timeline=fixture(records=False);row['moving_duration_s']=101;row['intervals_moving_duration_s']=-1
        w=reconstruct([row],timelines=timeline)['canonical_workouts'][0]
        self.assertIsNone(w['moving_duration_s'])

    def test_revision_changes_but_identity_does_not_when_moving_changes(self):
        row=source('g');original=copy.deepcopy(row)
        one=reconstruct([row])['canonical_workouts'][0]
        row['intervals_moving_duration_s']=1000
        two=reconstruct([row])['canonical_workouts'][0]
        row['intervals_moving_duration_s']=900
        three=reconstruct([row])['canonical_workouts'][0]
        self.assertEqual(one['canonical_workout_id'],two['canonical_workout_id'])
        self.assertEqual(two['canonical_workout_id'],three['canonical_workout_id'])
        self.assertNotEqual(one['revision'],two['revision'])
        self.assertNotEqual(two['revision'],three['revision'])
        self.assertEqual(row, {**original,'intervals_moving_duration_s':900})
        self.assertEqual(three,reconstruct([row])['canonical_workouts'][0])

    def test_user_selected_whole_source_supplies_its_moving_time(self):
        rows,timeline=paired_gap()
        rows[0]['intervals_moving_duration_s']=880;rows[1]['intervals_moving_duration_s']=1170
        cid=normalize(rows,timeline)['canonical_workouts'][0]['canonical_workout_id']
        result=normalize(rows,timeline,{'workouts':{cid:{'distance_source_activity_id':'a'}}})
        self.assertEqual(result['canonical_workouts'][0]['moving_duration_s'],1170)

    def test_duration_is_not_clamped_when_preferred_watch_exceeds_canonical_clock(self):
        g=source('g',duration=100,distance=200);g['intervals_moving_duration_s']=97
        a=source('a',device='Amazfit',start=START+timedelta(seconds=10),duration=85,distance=195)
        a['intervals_moving_duration_s']=80
        result=normalize([g,a]);w=result['canonical_workouts'][0]
        self.assertEqual(w['elapsed_duration_s'],85)
        self.assertEqual(w['moving_duration_s'],80)
        p=next(p for p in result['field_provenance'] if p['field_name']=='moving_duration_s')
        self.assertEqual(p['source_activity_ids'],['a'])
        self.assertEqual(p['coverage_scope'],'whole_canonical_elapsed_source')

    def test_unresolved_physical_gap_keeps_full_moving_duration_unknown(self):
        rows,timeline=paired_gap(timer_events=False,gap=(60,360))
        rows[0]['intervals_moving_duration_s']=850
        rows[1]['intervals_moving_duration_s']=1150
        result=normalize(rows,timeline);w=result['canonical_workouts'][0]
        self.assertTrue(w['requires_user_review'])
        self.assertIsNone(w['moving_duration_s'])
        p=next(p for p in result['field_provenance'] if p['field_name']=='moving_duration_s')
        self.assertEqual(p['method'],'unknown_unresolved_outing_motion')
