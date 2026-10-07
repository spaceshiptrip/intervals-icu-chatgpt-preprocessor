import copy
import unittest
from canonical_workouts import MILE, canonical_summaries, reconstruct
from test_canonical_workouts import source, normalize, START, paired_gap
from datetime import timedelta


class FootTrainingPolicyTests(unittest.TestCase):
    def test_cycling_distance_and_duration_are_separate_from_primary_mileage(self):
        run=source('run',distance=3000)
        bike=source('bike',start=START+timedelta(hours=3),distance=20000);bike['sport']='cycling'
        original=copy.deepcopy([run,bike]); result=reconstruct([run,bike]); summary=canonical_summaries(result['canonical_workouts'])[0]
        self.assertEqual(summary['training_miles'],3000/MILE)
        self.assertEqual(summary['cycling_miles'],20000/MILE)
        self.assertEqual(summary['cycling_duration_s'],1200)
        self.assertEqual([run,bike],original)
        self.assertEqual(next(w for w in result['canonical_workouts'] if w['sport']=='cycling')['training_distance_status'],'non_foot')

    def test_cycling_only_day_is_known_zero_foot_mileage(self):
        bike=source('bike');bike['sport']='cycling'
        self.assertEqual(canonical_summaries(normalize([bike])['canonical_workouts'])[0]['training_miles'],0)

    def test_generic_recorded_walk_retains_distance_but_unknown_intent(self):
        walk=source('walk',name='Lunch Walk',distance=1000);walk['sport']='walking'
        result=normalize([walk]); w=result['canonical_workouts'][0]
        self.assertIsNone(w['intentional_training'])
        self.assertIsNone(w['training_distance_m'])
        self.assertEqual(w['unclassified_training_distance_m'],1000)
        self.assertEqual(w['distance_m'],1000)
        self.assertFalse(w['counts_toward_training_totals'])
        self.assertTrue(w['requires_user_review'])
        summary=canonical_summaries([w])[0]
        self.assertIsNone(summary['training_miles'])
        self.assertEqual(summary['unclassified_training_miles'],1000/MILE)
        self.assertEqual(result['reconstruction_review'][0]['detected_problem'],'unclassified_training_intent')

    def test_explicit_walk_intent_counts_once_and_resolves_review_deterministically(self):
        walk=source('walk',name='Night Walk',distance=1000);walk['sport']='walking'
        cid=normalize([walk])['canonical_workouts'][0]['canonical_workout_id']
        decisions={'workouts':{cid:{'intentional_training':True}}}; original=copy.deepcopy(decisions)
        one=normalize([walk],resolutions=decisions);two=normalize([walk],resolutions=decisions)
        self.assertEqual(one,two);self.assertEqual(decisions,original)
        self.assertFalse(one['reconstruction_review'])
        w=one['canonical_workouts'][0]
        self.assertEqual(w['training_distance_m'],1000)
        self.assertEqual(w['confirmed_training_distance_mi'],1000/MILE)
        self.assertEqual(w['walking_distance_m'],1000)

    def test_confirmed_running_survives_pending_walk_intent(self):
        walk=source('walk',name='Lunch Walk',distance=1000,start=START+timedelta(hours=3));walk['sport']='walking'
        result=normalize([source('run',distance=3000),walk]); summary=canonical_summaries(result['canonical_workouts'])[0]
        self.assertEqual(summary['training_miles'],3000/MILE)
        self.assertFalse(summary['training_mileage_complete'])
        self.assertEqual(summary['unclassified_training_workout_count'],1)
        self.assertEqual(summary['unclassified_training_miles'],1000/MILE)
        self.assertEqual(summary['running_distance_miles'],3000/MILE)
        self.assertEqual(summary['walking_distance_miles'],0)
        self.assertEqual(summary['unknown_training_distance_miles'],0)

    def test_recovery_walk_and_hike_count_on_foot(self):
        walk=source('walk',name='Deliberate Recovery Walk',distance=1000);walk['sport']='walking'
        hike=source('hike',distance=2000,start=START+timedelta(hours=3));hike['sport']='hiking'
        summary=canonical_summaries(normalize([walk,hike])['canonical_workouts'],True)[0]
        self.assertEqual(summary['training_miles'],3000/MILE)
        self.assertTrue(summary['training_mileage_complete'])

    def test_unknown_sport_requires_classification_and_can_be_resolved(self):
        row=source('unknown',distance=1000);row['sport']='unknown'
        w=normalize([row])['canonical_workouts'][0];self.assertIsNone(w['training_distance_m'])
        resolved=normalize([row],resolutions={'workouts':{w['canonical_workout_id']:{'intentional_training':True,'foot_training_eligible':True}}})
        self.assertEqual(resolved['canonical_workouts'][0]['unknown_training_distance_m'],1000)
        self.assertFalse(resolved['reconstruction_review'])

    def test_cycling_cannot_be_relabelled_foot_by_override(self):
        row=source('bike');row['sport']='cycling';cid=normalize([row])['canonical_workouts'][0]['canonical_workout_id']
        with self.assertRaisesRegex(ValueError,'Cycling'): normalize([row],resolutions={'workouts':{cid:{'foot_training_eligible':True}}})

    def test_implausible_foot_speed_goes_to_review_even_with_strong_alignment(self):
        rows,timelines=paired_gap(timer_events=False)
        for rec in timelines['a']['records']:
            seconds=(__import__('datetime').datetime.fromisoformat(rec['timestamp_utc'])-START).total_seconds()
            if seconds in (450,456,462,468): rec['distance_m'] += {450:40,456:30,462:20,468:10}[seconds]
        result=normalize(rows,timelines); w=result['canonical_workouts'][0]
        self.assertEqual(w['recovered_distance_m'],0)
        self.assertTrue(w['requires_user_review'])
        evidence=result['reconstruction_issues'][0]['evidence_json']
        self.assertEqual(evidence['plausibility_speed_cap_mps'],8)
        self.assertGreater(evidence['max_distance_speed_mps'],8)

    def test_accepted_preferred_resolution_settles_distance_conflict(self):
        garmin=source('g',distance=3000); amazfit=source('a',device='Amazfit',distance=3400)
        from canonical_workouts import reconstruct
        rows=[garmin,amazfit];pairs=[{'activity_id_a':'g','activity_id_b':'a','confidence':'high','grouped_for_training':True,'start_difference_s':0,'overlap_fraction':1}]
        garmin['duplicate_group_id']=amazfit['duplicate_group_id']='manual_pair'
        initial=reconstruct(rows,pairs); iid=initial['reconstruction_review'][0]['issue_id']
        result=reconstruct(rows,pairs,resolutions={'issues':{iid:{'decision':'use_preferred'}}})
        self.assertEqual(result['canonical_workouts'][0]['training_distance_m'],3000)
        self.assertFalse(result['reconstruction_review'])

    def test_unsampled_boundary_can_keep_known_segments_without_fabrication(self):
        g1=source('g1',duration=600,distance=1500)
        g2=source('g2',start=START+timedelta(seconds=650),duration=600,distance=1500)
        a=source('a',device='Amazfit',duration=1250,distance=3000)
        initial=normalize([g1,g2,a]);iid=initial['reconstruction_review'][0]['issue_id']
        result=normalize([g1,g2,a],resolutions={'issues':{iid:{'decision':'use_preferred'}}})
        w=result['canonical_workouts'][0]
        self.assertEqual(w['training_distance_m'],3000)
        self.assertEqual(w['recovered_distance_m'],0)
        self.assertFalse(result['reconstruction_review'])

    def test_gap_resolution_cannot_silently_settle_unknown_training_intent(self):
        walk=source('walk',name='Lunch Walk');walk['sport']='walking'
        initial=normalize([walk]); iid=initial['reconstruction_review'][0]['issue_id']
        with self.assertRaisesRegex(ValueError,'workout intentional_training'):
            normalize([walk],resolutions={'issues':{iid:{'decision':'use_preferred'}}})

    def test_known_non_foot_sport_has_zero_primary_foot_contribution(self):
        row=source('swim',distance=1000); row['sport']='swimming'
        result=normalize([row]); w=result['canonical_workouts'][0]
        self.assertEqual(w['training_distance_m'],0)
        self.assertEqual(w['distance_m'],1000)
        self.assertFalse(result['reconstruction_review'])

    def test_historical_mvp_walk_override_does_not_count_future_generic_walk(self):
        old=source('historic',name='Lunch Walk',distance=1000);old['sport']='walking'
        future=source('future',name='Lunch Walk',distance=2000,start=START+timedelta(days=1));future['sport']='walking'
        cid=normalize([old])['canonical_workouts'][0]['canonical_workout_id']
        policy={'workouts':{cid:{'intentional_training':True,'note':'Temporary MVP historical counting policy; original intent unknown.'}}}
        result=normalize([old,future],resolutions=policy)
        by_id={w['canonical_workout_id']:w for w in result['canonical_workouts']}
        self.assertEqual(by_id[cid]['training_distance_m'],1000)
        self.assertIn('Temporary MVP historical',by_id[cid]['summary_note'])
        new=next(w for w in result['canonical_workouts'] if w['canonical_workout_id']!=cid)
        self.assertIsNone(new['training_distance_m'])
        self.assertEqual(new['unclassified_training_distance_m'],2000)
        self.assertEqual(len(result['reconstruction_review']),1)
        provenance=next(p for p in result['field_provenance'] if p['canonical_workout_id']==cid and p['field_name']=='intentional_training')
        self.assertEqual(provenance['method'],'user_outing_context')
        self.assertFalse(provenance['source_activity_ids'])
