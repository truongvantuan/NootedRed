#!/usr/bin/env python3
"""Check trace interpretation and original-app launch policy without GPU work."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import capture_zalo_startup as capture
from vcn_context_trace import summarize


class TraceCaptureTests(unittest.TestCase):
    def test_repeated_ring_snapshots_do_not_multiply_operations(self):
        begin = '[ 217.1]: prefix NootedRed VCNTrace: @ begin op=newContext pid=30 event=5'
        end = '[ 217.2]: NootedRed VCNTrace: @ end op=newContext pid=30 result=0x0 event=5'
        result = summarize('\n'.join([begin, end, begin, end]))
        self.assertEqual(len(result['completed']), 1)
        self.assertFalse(result['native_errors'] or result['conflicts'])

    def test_incomplete_capture_is_not_a_completed_call(self):
        result = summarize('VCNTrace: @ begin op=removeContext pid=30 event=6')
        self.assertFalse(result['completed'])
        self.assertEqual(len(result['unmatched_begins']), 1)

    def test_native_error_is_preserved(self):
        result = summarize('VCNTrace: @ end op=newContext pid=30 result=0xE00002C2 event=5')
        self.assertEqual(result['native_errors'][0]['native_status'], 0xe00002c2)
        self.assertEqual(len(result['end_without_begin']), 1)

    def test_conflicting_event_reuse_is_reported(self):
        result = summarize('VCNTrace: @ begin op=newContext pid=30 event=5\nVCNTrace: @ end op=removeContext pid=30 result=0x0 event=5')
        self.assertTrue(result['conflicts'])

    def test_original_launcher_has_no_feature_disable_switch(self):
        app = Path('/Applications/Zalo.app')
        with patch.object(capture, 'processes', return_value=[]), patch.object(capture, 'command', return_value=SimpleNamespace(returncode=0)) as run:
            capture.launch_original_app(app)
        run.assert_called_once_with(['/usr/bin/open', '-a', str(app)])

    def test_existing_app_prevents_second_launch(self):
        with patch.object(capture, 'processes', return_value=[{'browser_main': True}]), patch.object(capture, 'command') as run:
            with self.assertRaises(RuntimeError):
                capture.launch_original_app(Path('/Applications/Zalo.app'))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
