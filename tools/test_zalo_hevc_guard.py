#!/usr/bin/env python3
"""Test launch policy without starting Zalo or submitting GPU work."""
import contextlib
import io
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zalo_hevc_guard as guard


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Path(self.tmp.name)/'Zalo.app'
        self.info=self.app/'Contents/Info.plist';self.info.parent.mkdir(parents=True)
        self.info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.vng.zalo','CFBundleExecutable':'Zalo',
                                            'CFBundleVersion':'test','CFBundleShortVersionString':'test'}))
        fw=self.app/'Contents/Frameworks/Electron Framework.framework'
        (fw/'Resources').mkdir(parents=True);(fw/'Versions/A').mkdir(parents=True)
        self.meta=fw/'Resources/Info.plist';self.meta.write_bytes(plistlib.dumps({'CFBundleVersion':'22.3.9'}))
        self.binary=fw/'Versions/A/Electron Framework';self.binary.write_bytes(b'fixture\0PlatformHEVCDecoderSupport\0')

    def test_default_inspection_never_launches(self):
        with patch('sys.argv',['guard','--app',str(self.app)]),patch.object(guard.subprocess,'Popen',side_effect=AssertionError('unexpected launch')),contextlib.redirect_stdout(io.StringIO()):
            guard.main()

    def test_unreviewed_runtime_refused(self):
        self.meta.write_bytes(plistlib.dumps({'CFBundleVersion':'99.0'}))
        with self.assertRaises(ValueError):guard.plan(self.app)

    def test_enabled_experiment_requires_run_and_acknowledgement(self):
        for flags in [[], ['--run'], ['--launch','--yes']]:
            with self.subTest(flags=flags),patch('sys.argv',['guard','--app',str(self.app),'--test-hevc-enabled',*flags]),patch.object(guard.subprocess,'Popen',side_effect=AssertionError('unexpected launch')),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):guard.main()

    def test_wrong_application_refused(self):
        self.info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'other'}))
        with self.assertRaises(ValueError):guard.plan(self.app)

    def test_missing_feature_refused(self):
        self.binary.write_bytes(b'no matching control')
        with self.assertRaises(ValueError):guard.plan(self.app)

    def test_existing_unguarded_app_is_not_reused_or_killed(self):
        row={'browser_main':True,'GPU_helper':False,'HEVC_feature_disable_forwarded':False}
        with patch.object(guard,'processes',return_value=[row]),patch.object(guard.subprocess,'Popen',side_effect=AssertionError('unexpected launch')):
            with self.assertRaises(ValueError):guard.activate_or_launch(self.app,guard.plan(self.app))

    def test_guarded_existing_app_is_activated_without_new_instance(self):
        row={'browser_main':True,'GPU_helper':False,'HEVC_feature_disable_forwarded':True}
        with patch.object(guard,'processes',return_value=[row]),patch.object(guard.subprocess,'Popen',side_effect=AssertionError('unexpected launch')),patch.object(guard.subprocess,'run') as run:
            self.assertTrue(guard.activate_or_launch(self.app,guard.plan(self.app))['activated_existing_guarded_Zalo'])
            run.assert_called_once_with(['/usr/bin/open','-a',str(self.app)],check=True)

    def test_exact_feature_name_and_process_prefix(self):
        text=f'''101 1 {self.app}/Contents/MacOS/Zalo --disable-features=PlatformHEVCDecoderSupportExtra
102 101 {self.app}/Contents/Frameworks/Zalo Helper (GPU).app/Contents/MacOS/Zalo Helper (GPU) --disable-features=Other,PlatformHEVCDecoderSupport --enable-features=PlatformHEVCDecoderSupport
103 1 /other/app --note={self.app}/Contents/MacOS/Zalo
'''
        with patch.object(guard.subprocess,'run',return_value=SimpleNamespace(stdout=text)):
            rows=guard.processes(self.app)
        self.assertEqual(len(rows),2)
        self.assertFalse(rows[0]['HEVC_feature_disable_forwarded'])
        self.assertTrue(rows[1]['HEVC_feature_disable_forwarded'])
        self.assertTrue(rows[1]['HEVC_feature_enable_forwarded'])


if __name__=='__main__':unittest.main()
