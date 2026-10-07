import unittest
import contextlib
import io
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from preprocess_fit import duplicates, match, summaries, metrics, family, times, comparisons, elevation_summary, composite_duplicates, composite_comparisons, publish_package, main

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
    def test_october_5_and_september_29_from_archive(self):
        from pathlib import Path
        from preprocess_fit import sources, parse, read_csv
        archive=Path('data/i284770_fit_files.zip')
        mapping=Path('data/device_mapping.csv')
        if not archive.exists() or not mapping.exists(): self.skipTest('Local archive and confirmed mapping unavailable')
        overrides={r['source_filename']:r for r in read_csv(mapping)}
        ids={'i193992529','i193938668','i193992699','i191627512','i191573994','i191573995','i191627533'}
        rows=[]
        for name,content in sources(archive):
            if Path(name).name.split('_',1)[0] in ids: rows.append(parse(name,content,{},overrides[name])[0])
        self.assertEqual(len(rows),7)
        pairs=duplicates(rows); groups=composite_duplicates(rows,pairs)
        self.assertEqual(len(groups),1)
        by_id={r['intervals_activity_id']:r for r in rows}
        self.assertEqual(by_id['i193992529']['composite_role'],'continuous')
        self.assertFalse(by_id['i193992529']['contributes_to_training_totals'])
        for aid in ('i193938668','i193992699'):
            self.assertEqual(by_id[aid]['composite_role'],'segment')
            self.assertTrue(by_id[aid]['contributes_to_training_totals'])
        daily={r['date_local']:r for r in summaries(rows)}
        self.assertAlmostEqual(daily['2026-10-05']['running_miles'],13538.86/1609.344)
        self.assertAlmostEqual(daily['2026-10-05']['running_miles'],8.412658,places=5)
        self.assertEqual(daily['2026-10-05']['activity_count'],2)
        weekly={r['week_starting_local']:r for r in summaries(rows,True)}
        self.assertAlmostEqual(weekly['2026-10-05']['running_miles'],13538.86/1609.344)
        self.assertAlmostEqual(daily['2026-09-29']['running_miles'],(2301.18+1176.51)/1609.344)
        self.assertFalse(by_id['i191573995']['contributes_to_training_totals'])
        comparison=composite_comparisons(rows,groups)[0]
        self.assertAlmostEqual(comparison['distance_m_a'],13538.86)
        self.assertEqual(comparison['distance_m_b'],13839)

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

class CompositeTests(unittest.TestCase):
    def example(self,continuous_device='Amazfit',segment_device='Garmin'):
        return [activity('continuous',start='2026-10-05T16:48:54+00:00',distance=13839,duration=9207,device=continuous_device),
            activity('segment1',start='2026-10-05T16:48:58+00:00',distance=5671.01,duration=2291,device=segment_device),
            activity('segment2',start='2026-10-05T17:27:42+00:00',distance=7867.85,duration=6879,device=segment_device)]

    def test_composite_preference_and_comparison(self):
        rows=self.example(); pairs=duplicates(rows); groups=composite_duplicates(rows,pairs)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['confidence'],'high')
        self.assertEqual(groups[0]['gap_between_segments_s'],33)
        self.assertEqual([r['contributes_to_training_totals'] for r in rows],[False,True,True])
        self.assertEqual(len({r['composite_duplicate_group_id'] for r in rows}),1)
        comparison=composite_comparisons(rows,groups)[0]
        self.assertEqual(comparison['comparison_type'],'composite')
        self.assertAlmostEqual(comparison['distance_m_difference'],300.14)
        self.assertEqual(comparison['segment_elapsed_sum_s'],9170)
        self.assertEqual(comparison['segment_time_window_s'],9203)
        self.assertEqual(len(rows),3)

    def test_reverse_device_preference(self):
        rows=self.example('Garmin','Amazfit'); pairs=duplicates(rows)
        groups=composite_duplicates(rows,pairs)
        self.assertEqual(len(groups),1)
        self.assertEqual([r['contributes_to_training_totals'] for r in rows],[True,False,False])

    def test_overlapping_segments_rejected(self):
        rows=self.example()
        times(rows[1],'end',datetime.fromisoformat('2026-10-05T18:00:00+00:00'))
        pairs=duplicates(rows)
        self.assertEqual(composite_duplicates(rows,pairs),[])

    def test_incomplete_coverage_and_distance_rejected(self):
        rows=self.example(); rows[2]['distance_m']=1000
        pairs=duplicates(rows); self.assertEqual(composite_duplicates(rows,pairs),[])
        rows=self.example(); times(rows[2],'end',datetime.fromisoformat('2026-10-05T18:00:00+00:00'))
        pairs=duplicates(rows); self.assertEqual(composite_duplicates(rows,pairs),[])

    def test_unknown_devices_not_inferred(self):
        rows=self.example('Unknown','Garmin'); pairs=duplicates(rows)
        self.assertEqual(composite_duplicates(rows,pairs),[])

    def test_long_gap_and_mixed_sports_rejected(self):
        rows=self.example()
        times(rows[1],'end',datetime.fromisoformat('2026-10-05T17:20:00+00:00'))
        pairs=duplicates(rows); self.assertEqual(composite_duplicates(rows,pairs),[])
        rows=self.example(); rows[2]['sport']='walking'
        pairs=duplicates(rows); self.assertEqual(composite_duplicates(rows,pairs),[])

    def test_existing_outside_pair_not_broken(self):
        rows=self.example()
        rows.append(activity('second_continuous',start='2026-10-05T16:48:54+00:00',distance=13839,duration=9207,device='Other'))
        pairs=duplicates(rows)
        self.assertEqual(composite_duplicates(rows,pairs),[])

    def test_input_order_does_not_change_composite(self):
        rows=self.example(); pairs=duplicates(rows); groups=composite_duplicates(rows,pairs)
        reverse=list(reversed(self.example())); pairs=duplicates(reverse); reverse_groups=composite_duplicates(reverse,pairs)
        self.assertEqual(groups,reverse_groups)

    def test_three_segments(self):
        rows=[activity('full',duration=3600,distance=9000,device='Amazfit'),
            activity('s1',duration=1200,distance=3000,device='Garmin'),
            activity('s2',start='2026-10-05T16:20:00+00:00',duration=1200,distance=3000,device='Garmin'),
            activity('s3',start='2026-10-05T16:40:00+00:00',duration=1200,distance=3000,device='Garmin')]
        pairs=duplicates(rows); groups=composite_duplicates(rows,pairs)
        self.assertEqual(groups[0]['segment_count'],3)
        self.assertEqual(summaries(rows)[0]['activity_count'],3)
        self.assertAlmostEqual(summaries(rows)[0]['running_miles'],9000/1609.344)

    def test_timer_match_with_late_terminal_stop(self):
        rows=[activity('g',duration=8529,distance=1176.51,device='Garmin'),
            activity('a',duration=552,distance=1175,device='Amazfit')]
        rows[0]['timer_duration_s']=560; rows[1]['timer_duration_s']=551
        pairs=duplicates(rows)
        self.assertEqual(pairs[0]['confidence'],'medium')
        self.assertIn('matching timer durations',pairs[0]['reason'])
        self.assertEqual([r['contributes_to_training_totals'] for r in rows],[True,False])
        rows[1]['timer_duration_s']=100
        self.assertEqual(match(*rows)['confidence'],'low')

class PackagingTests(unittest.TestCase):
    def test_normal_run_replaces_current_without_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'activity.csv'; source.write_text('first export')
            out=root/'output'
            current,snapshot=publish_package(out,{'activity.csv':source})
            self.assertIsNone(snapshot); self.assertFalse((out/'archive').exists())
            first=current.read_bytes(); source.write_text('updated export')
            updated,snapshot=publish_package(out,{'activity.csv':source})
            self.assertEqual(current,updated); self.assertNotEqual(first,updated.read_bytes())
            self.assertIsNone(snapshot)
            with zipfile.ZipFile(updated) as z: self.assertEqual(z.read('activity.csv'),b'updated export')
            self.assertEqual(list(out.iterdir()),[current])

    def test_snapshot_matches_updated_current_and_preserves_prior_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'activity.csv'; source.write_text('first export')
            now=datetime(2026,10,6,10,25,tzinfo=timezone.utc)
            with patch('preprocess_fit.datetime') as clock:
                clock.now.return_value=now
                current,first=publish_package(root/'output',{'activity.csv':source},archive=True)
                original=first.read_bytes(); source.write_text('second export')
                current,second=publish_package(root/'output',{'activity.csv':source},archive=True)
            self.assertEqual(first.parent,root/'output'/'archive')
            self.assertNotEqual(first,second)
            self.assertEqual(first.read_bytes(),original)
            self.assertEqual(second.read_bytes(),current.read_bytes())
            self.assertNotEqual(original,current.read_bytes())
            self.assertEqual(set(first.parent.iterdir()),{first,second})

    def test_build_failure_preserves_previous_current_and_leaves_no_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory); current=out/'Garmin_Amazfit_Training_Normalized.zip'
            current.write_bytes(b'previous export')
            with self.assertRaises(FileNotFoundError): publish_package(out,{'missing.csv':out/'missing.csv'},archive=True)
            self.assertEqual(current.read_bytes(),b'previous export')
            self.assertEqual(list(out.iterdir()),[current])

    def test_snapshot_failure_keeps_new_current_and_removes_partial_snapshot(self):
        import shutil
        copy=shutil.copyfileobj
        def fail_snapshot(source,target,*args):
            if '/archive/' in str(getattr(target,'name','')): raise OSError('copy failed')
            return copy(source,target,*args)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'activity.csv'; source.write_text('new export')
            out=root/'output'
            with patch('preprocess_fit.shutil.copyfileobj',side_effect=fail_snapshot):
                with self.assertRaises(OSError): publish_package(out,{'activity.csv':source},archive=True)
            with zipfile.ZipFile(out/'Garmin_Amazfit_Training_Normalized.zip') as z: self.assertEqual(z.read('activity.csv'),b'new export')
            self.assertEqual(list((out/'archive').iterdir()),[])

    def test_failed_cli_run_does_not_replace_current_or_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); bad=root/'corrupt.fit'; bad.write_bytes(b'not a FIT')
            out=root/'output'; out.mkdir()
            current=out/'Garmin_Amazfit_Training_Normalized.zip'; current.write_bytes(b'previous export')
            with patch('sys.argv',['preprocess_fit.py','--input',str(bad),'--output',str(out),'--archive']), contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(main(),1)
            self.assertEqual(current.read_bytes(),b'previous export')
            self.assertFalse((out/'archive').exists())
            self.assertTrue((out/'data_quality.csv').exists())
            self.assertIn('No snapshot created',stdout.getvalue())

    def test_successful_cli_run_defaults_and_archive_paths(self):
        archive=Path('data/i284770_fit_files.zip')
        if not archive.exists(): self.skipTest('Local archive unavailable')
        with zipfile.ZipFile(archive) as z:
            name=next(n for n in z.namelist() if n.lower().endswith('.fit'))
            content=z.read(name)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/Path(name).name; source.write_bytes(content)
            out=root/'output'
            argv=['preprocess_fit.py','--input',str(source),'--output',str(out)]
            with patch('sys.argv',argv),contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(),0)
            current=out/'Garmin_Amazfit_Training_Normalized.zip'
            self.assertTrue(current.exists()); self.assertFalse((out/'archive').exists())
            with zipfile.ZipFile(current) as z:
                self.assertNotIn('docs/CLAUDE_REVIEW_V2.md',z.namelist())
                self.assertNotIn('docs/CONTEXT_HANDOFF_PENDING_REVIEW.md',z.namelist())
                self.assertNotIn(str(root).encode(),z.read('coverage_report.json'))
            with patch('sys.argv',argv+['--archive']),contextlib.redirect_stdout(io.StringIO()) as stdout: self.assertEqual(main(),0)
            snapshots=list((out/'archive').iterdir()); self.assertEqual(len(snapshots),1)
            self.assertEqual(current.read_bytes(),snapshots[0].read_bytes())
            self.assertIn(str(current),stdout.getvalue()); self.assertIn(str(snapshots[0]),stdout.getvalue())
            self.assertEqual(snapshots[0].suffix,'.zip')

if __name__=='__main__': unittest.main()
