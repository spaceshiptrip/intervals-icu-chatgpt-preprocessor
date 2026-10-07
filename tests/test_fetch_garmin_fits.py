"""Operational wrapper guards dates, retention configuration and credential-safe failures."""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('fetch_garmin_fits',Path(__file__).resolve().parents[1]/'scripts/fetch_garmin_fits.py')
wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)


class RetrievalTests(unittest.TestCase):
    def config(self,folder):
        return {'services':{'garmin-fetch-data':{'environment':{'KEEP_FIT_FILES':'True','FIT_FILE_STORAGE_LOCATION':'/home/appuser/fit_filestore','GARMIN_PASSWORD':'private-secret'},
            'volumes':[{'type':'bind','source':str(folder),'target':'/home/appuser/fit_filestore'}]}}}

    def test_retention_and_writable_mount_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            config=self.config(folder)
            with patch.object(wrapper,'run_json',return_value=config): self.assertEqual(wrapper.retained_path(Path(folder)),Path(folder))
            config['services']['garmin-fetch-data']['volumes'][0]['read_only']=True
            with patch.object(wrapper,'run_json',return_value=config),self.assertRaisesRegex(RuntimeError,'read-only'): wrapper.retained_path(Path(folder))
            config['services']['garmin-fetch-data']['environment']['KEEP_FIT_FILES']='False'
            with patch.object(wrapper,'run_json',return_value=config),self.assertRaisesRegex(RuntimeError,'not enabled'): wrapper.retained_path(Path(folder))

    def test_config_failure_does_not_expose_resolved_credentials(self):
        result=SimpleNamespace(returncode=1,stdout='GARMIN_PASSWORD=private-secret',stderr='private-secret')
        with patch.object(wrapper.subprocess,'run',return_value=result),self.assertRaises(RuntimeError) as raised:
            wrapper.run_json(['docker','compose','config','--format','json'],Path('.'))
        self.assertNotIn('private-secret',str(raised.exception))

    def test_fetch_failure_suppresses_sensitive_child_logs(self):
        process=SimpleNamespace(stdout=io.StringIO('password=private-secret\nlogin=private-email\n'),wait=lambda:1)
        output=io.StringIO()
        with patch.object(wrapper.subprocess,'Popen',return_value=process),contextlib.redirect_stdout(output),self.assertRaises(RuntimeError) as raised:
            wrapper.fetch(Path('.'),wrapper.day('2026-10-06'),wrapper.day('2026-10-06'))
        self.assertNotIn('private-secret',output.getvalue()+str(raised.exception))
        self.assertNotIn('private-email',output.getvalue()+str(raised.exception))

    def test_bad_range_fails_before_docker(self):
        with patch.object(wrapper,'run_json') as docker,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            wrapper.main(['--start','2026-10-07','--end','2026-10-06'])
        docker.assert_not_called()

    def test_check_is_read_only_and_reports_activity_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            config=self.config(folder); output=io.StringIO()
            summary={'fit_file_count':1,'activity_count':1,'oldest_start_local':'2026-10-06T13:06:18-07:00','newest_start_local':'2026-10-06T13:06:18-07:00','failed_file_count':0}
            with patch.object(wrapper,'run_json',return_value=config),patch.object(wrapper,'inventory',return_value=(summary,[],[])),patch.object(wrapper,'fetch') as fetch,contextlib.redirect_stdout(output):
                result=wrapper.main(['--repo',folder,'--check'])
            self.assertEqual(result,0);fetch.assert_not_called()
            self.assertIn('2026-10-06T13:06:18-07:00',output.getvalue())
            self.assertNotIn('private-secret',output.getvalue())

if __name__=='__main__': unittest.main()
