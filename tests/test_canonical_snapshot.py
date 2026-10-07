import copy
import unittest
from canonical_snapshot import build_snapshot


def workout(cid, sources, day='2026-10-05', revision='r1'):
    return {'canonical_workout_id': cid, 'source_activity_ids': sources, 'revision': revision, 'local_date': day}


class SnapshotTests(unittest.TestCase):
    def test_merge_retires_both_old_ids_with_traceable_replacement(self):
        old = build_snapshot([workout('a',['g']),workout('b',['a'])],2)
        current = build_snapshot([workout('merged',['g','a'])],2,old)
        self.assertEqual([w['canonical_workout_id'] for w in current['workouts']],['merged'])
        self.assertEqual(len(current['retired_workouts']),2)
        for w in current['retired_workouts']:
            self.assertFalse(w['counts_toward_training_totals'])
            self.assertEqual(w['replacement_canonical_workout_ids'],['merged'])
        self.assertEqual(current['recompute_local_dates'],['2026-10-05'])

    def test_split_retires_parent_and_retains_both_replacements(self):
        old=build_snapshot([workout('merged',['g','a'])],2)
        new=build_snapshot([workout('a',['g']),workout('b',['a'],'2026-10-06')],2,old)
        self.assertEqual(new['retired_workouts'][0]['replacement_canonical_workout_ids'],['a','b'])
        self.assertEqual(new['recompute_local_dates'],['2026-10-05','2026-10-06'])
        self.assertEqual(new['recompute_week_starting_dates'],['2026-10-05'])

    def test_identical_rerun_is_identical_and_does_not_mutate_previous(self):
        rows=[workout('a',['g'])]; old=build_snapshot(rows,1); original=copy.deepcopy(old)
        self.assertEqual(build_snapshot(rows,1,old),old)
        self.assertEqual(old,original)

    def test_tombstones_survive_skipped_intermediate_imports_and_reruns(self):
        old=build_snapshot([workout('a',['g']),workout('b',['a'])],2)
        rows=[workout('merged',['g','a'])]; current=build_snapshot(rows,2,old)
        self.assertEqual(build_snapshot(rows,2,current),current)

    def test_source_removal_requires_explicit_acknowledgement(self):
        old=build_snapshot([workout('a',['g']),workout('b',['a'])],2)
        with self.assertRaisesRegex(ValueError,'coverage shrank'): build_snapshot([workout('a',['g'])],1,old)
        new=build_snapshot([workout('a',['g'])],1,old,allow_source_removals=True)
        self.assertEqual(new['retired_workouts'][0]['reason'],'source_removed')

    def test_changed_scope_or_duplicate_ids_are_rejected(self):
        old=build_snapshot([workout('a',['g'])],1)
        with self.assertRaisesRegex(ValueError,'scope changed'): build_snapshot([],0,old,scope='partial')
        with self.assertRaisesRegex(ValueError,'Duplicate'): build_snapshot([workout('a',['g']),workout('a',['g'])],1)

    def test_content_revision_changes_keep_identity(self):
        old=build_snapshot([workout('a',['g'])],1)
        new=build_snapshot([workout('a',['g'],revision='r2')],1,old)
        self.assertFalse(new['retired_workouts'])
        self.assertNotEqual(new['dataset_revision'],old['dataset_revision'])

    def test_stable_source_keys_handle_reexported_fit_bytes(self):
        old=build_snapshot([workout('a',['old_fit_hash'])],1,source_keys={'old_fit_hash':'intervals_id'})
        new=build_snapshot([workout('merged',['new_fit_hash'])],1,old,source_keys={'new_fit_hash':'intervals_id'})
        self.assertEqual(new['retired_workouts'][0]['replacement_canonical_workout_ids'],['merged'])

    def test_reintroduced_id_is_active_without_active_tombstone(self):
        first=build_snapshot([workout('a',['g'])],1)
        second=build_snapshot([workout('b',['g'])],1,first)
        third=build_snapshot([workout('a',['g'])],1,second)
        self.assertEqual([r['canonical_workout_id'] for r in third['retired_workouts']],['b'])

    def test_date_change_recomputes_old_and_new_dates_on_every_rerun(self):
        old=build_snapshot([workout('a',['g'],'2026-10-04')],1)
        rows=[workout('a',['g'],'2026-10-05')]
        new=build_snapshot(rows,1,old)
        self.assertEqual(new['recompute_local_dates'],['2026-10-04','2026-10-05'])
        self.assertEqual(new['recompute_week_starting_dates'],['2026-09-28','2026-10-05'])
        self.assertEqual(build_snapshot(rows,1,new),new)
