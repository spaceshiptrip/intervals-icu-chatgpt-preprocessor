import json
"""Inventory checks use activity times, distinguish index-only Garmin exports and retain missing IDs."""
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from source_coverage import coverage_report, inventory, timestamp


class CoverageTests(unittest.TestCase):
    def test_csv_bom_local_times_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fresh.csv'
            path.write_text('\ufeff"id",Date,Type,Distance\ni2,2026-10-06T13:06:18,Run,4466\ni1,2026-08-11T08:09:38,Run,7902\ni2,2026-10-06T13:06:18,Run,4466\n')
            summary,rows,_=inventory(path,'intervals_activities_csv')
            self.assertEqual(summary['activity_count'],3)
            self.assertEqual(summary['unique_activity_count'],2)
            self.assertEqual(summary['duplicate_activity_keys'],['i2'])
            self.assertEqual(summary['newest_start_utc'],'2026-10-06T20:06:18+00:00')
            self.assertEqual(summary['oldest_start_local'],'2026-08-11T08:09:38-07:00')

    def test_garmin_zip_is_index_only_and_end_marker_not_a_workout(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'garmin.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('ActivitySummary.csv','ActivityID,time,activityType,activityName,distance\n1,2026-10-05T16:48:58Z,running,Run,5671\n1,2026-10-05T17:27:09Z,No Activity,END,\n')
            summary,rows,_=inventory(path,'garmin_local')
            self.assertEqual(summary['format'],'garmin_index_only_no_fit')
            self.assertEqual(summary['fit_file_count'],0)
            self.assertEqual(summary['csv_row_count'],2)
            self.assertEqual(summary['activity_count'],1)
            self.assertFalse(summary['used_for_activity_detail'])

    def test_missing_ids_and_freshness_are_checked_not_download_time(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.zip'
            with zipfile.ZipFile(path,'w'): pass
            csvpath=Path(folder)/'index.csv';csvpath.write_text('id,Date,Type,Distance\ni1,2026-10-05T09:00:00,Run,1000\ni2,2026-10-06T13:06:18,Run,4466\n')
            rows=[{'activity_id':'fit1','intervals_activity_id':'i1','start_utc':'2026-10-05T16:00:00+00:00','sport':'running','distance_m':1000}]
            report,_=coverage_report(path,csvpath,parsed_rows=rows,fit_count=1)
            self.assertEqual(report['csv_without_fit_ids'],['i2'])
            self.assertTrue(any('newest activity timestamps disagree' in w for w in report['warnings']))
            self.assertTrue(any('Garmin FIT source not located' in w for w in report['warnings']))

    def test_stale_garmin_index_and_repeated_snapshots_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fit=root/'fit.zip'
            with zipfile.ZipFile(fit,'w'): pass
            garmin=root/'garmin.zip'
            with zipfile.ZipFile(garmin,'w') as z:
                z.writestr('ActivitySummary.csv','ActivityID,time,activityType,activityName,distance\n1,2026-10-05T16:48:58Z,running,Run,5671\n')
            rows=[{'activity_id':'fit1','intervals_activity_id':'i1','start_utc':'2026-10-06T20:06:18+00:00','sport':'running','distance_m':3953}]
            report,_=coverage_report(fit,garmin_paths=[garmin,garmin],parsed_rows=rows,fit_count=1)
            self.assertEqual(report['garmin_unique_activity_count'],1)
            self.assertTrue(any('stale relative to Intervals' in w for w in report['warnings']))
            self.assertTrue(any('repeat across snapshots' in w for w in report['warnings']))
            self.assertTrue(any('no close start/distance match' in w for w in report['warnings']))

    def test_naive_and_offset_timestamps_handle_dst(self):
        self.assertEqual(timestamp('2026-01-01T08:00:00').hour,16)
        self.assertEqual(timestamp('2026-08-01T08:00:00').hour,15)
        self.assertEqual(timestamp('2026-08-01T08:00:00+00:00').hour,8)

if __name__=='__main__': unittest.main()


class ShareableCoverageTests(unittest.TestCase):
    def test_paths_are_redacted_without_mutating_inventory_or_hashes(self):
        from source_coverage import shareable_coverage
        report={'sources':[{'source_path':'/Users/jtorres/private/input.zip','source_sha256':'abc'}],
                'auxiliary_inputs':[{'source_path':'/Users/jtorres/private/resolutions.json'}]}
        out=shareable_coverage(report)
        self.assertEqual(out['sources'][0]['source_path'],'input.zip')
        self.assertEqual(out['sources'][0]['source_sha256'],'abc')
        self.assertNotIn('/Users',json.dumps(out))
        self.assertEqual(report['sources'][0]['source_path'],'/Users/jtorres/private/input.zip')
