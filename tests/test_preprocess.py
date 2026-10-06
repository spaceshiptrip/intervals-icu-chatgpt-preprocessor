import unittest
from datetime import datetime, timezone
from preprocess_fit import duplicates, match, summaries, metrics, family, times, comparisons, elevation_summary

def activity(aid,start='2026-10-05T16:00:00+00:00',distance=10000,duration=3600,device='Unknown'):
    from datetime import timedelta
    r={'activity_id':aid,'sport':'running','sub_sport':'generic','device_family':device,
       'content_sha256':aid,'record_count':100,'terrain_type':'road_or_unspecified',
       'elevation_source':'unknown','intervals_load':None,
       **metrics({'total_distance':distance,'total_elapsed_time':duration,'total_timer_time':duration,'avg_heart_rate':140,'total_ascent':100})}
    dt=datetime.fromisoformat(start); times(r,'start',dt); times(r,'end',dt+timedelta(seconds=duration))
    return r

class NormalizationTests(unittest.TestCase):
    def test_missing_and_zero(self):
        r=metrics({'total_distance':0,'total_timer_time':0})
        self.assertEqual(r['distance_m'],0)
        self.assertIsNone(r['avg_hr_bpm']); self.assertIsNone(r['timer_pace_min_mile'])
    def test_device_provenance(self):
        self.assertEqual(family('development','Intervals.icu'),'Unknown')
        self.assertEqual(family('garmin',None),'Garmin')
        self.assertEqual(family('huami',None),'Amazfit')
    def test_dst(self):
        r={}; times(r,'start',datetime(2026,1,1,8,tzinfo=timezone.utc))
        self.assertTrue(r['start_local'].endswith('-08:00'))
        times(r,'start',datetime(2026,7,1,7,tzinfo=timezone.utc))
        self.assertTrue(r['start_local'].endswith('-07:00'))
    def test_pair_preference_and_weekly_no_double_count(self):
        rows=[activity('a',device='Amazfit'),activity('g',device='Garmin',distance=9900)]
        pairs=duplicates(rows)
        self.assertEqual(pairs[0]['confidence'],'high')
        self.assertFalse(rows[0]['preferred_training_record']); self.assertTrue(rows[1]['preferred_training_record'])
        summary=summaries(rows,True)[0]
        self.assertEqual(summary['activity_count'],1)
        self.assertEqual(summary['week_starting_local'],'2026-10-05')
        self.assertAlmostEqual(summary['running_miles'],9900/1609.344)
    def test_partial_activity_not_suppressed(self):
        rows=[activity('full',duration=8000,distance=14000),activity('partial',duration=2200,distance=5600)]
        p=duplicates(rows)[0]
        self.assertEqual(p['confidence'],'low'); self.assertFalse(p['grouped_for_training'])
        self.assertEqual(sum(r['preferred_training_record'] for r in rows),2)
    def test_no_transitive_chain(self):
        rows=[activity('a',start='2026-10-05T16:00:00+00:00'),activity('b',start='2026-10-05T16:04:00+00:00'),activity('c',start='2026-10-05T16:08:00+00:00')]
        duplicates(rows)
        self.assertEqual(sum(r['preferred_training_record'] for r in rows),2)
    def test_corrected_elevation_never_invented(self):
        rows=[activity('g',device='Garmin'),activity('a',device='Amazfit')]
        out=comparisons(rows,duplicates(rows))[0]
        self.assertIsNone(out['amazfit_intervals_corrected_ascent_m'])
        self.assertEqual(out['garmin_ascent_m'],100)
        rows[1]['intervals_corrected_ascent_m']=120
        rows[1]['intervals_corrected_descent_m']=110
        out=comparisons(rows,duplicates(rows))[0]
        self.assertEqual(out['amazfit_intervals_corrected_ascent_difference_pct'],20)
        summary=elevation_summary([out])
        self.assertEqual(next(r for r in summary if r['terrain_type']=='road_or_unspecified' and r['amazfit_elevation_type']=='intervals_corrected' and r['metric']=='ascent')['median_difference_m'],20)

class RealArchiveTests(unittest.TestCase):
    def test_crc_rejects_corruption(self):
        import zipfile
        from pathlib import Path
        from preprocess_fit import parse
        archive=Path('data/i284770_fit_files.zip')
        if not archive.exists(): self.skipTest('Local archive unavailable')
        with zipfile.ZipFile(archive) as z:
            name=next(n for n in z.namelist() if n.lower().endswith('.fit'))
            content=bytearray(z.read(name))
        content[-1]^=1
        with self.assertRaises(Exception): parse(name,bytes(content),{},{})

if __name__=='__main__': unittest.main()
