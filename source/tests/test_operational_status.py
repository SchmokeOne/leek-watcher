import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import cyberleek_watcher as engine


class Response(io.BytesIO):
    def __init__(self, body, known_size=True):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))} if known_size else {}


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.saved = (engine._download_jobs, engine._download_totals, engine._rpc_diagnostics,
                      engine._website_state, engine._site_arns_tx_ids, engine._rpc_errors, engine._rpc_cooldowns)
        engine._download_jobs = {}
        engine._download_totals = dict.fromkeys(('completed', 'failed', 'canceled', 'external'), 0)
        engine._rpc_diagnostics = {}
        engine._website_state = {}
        engine._site_arns_tx_ids = {}
        engine._rpc_errors = {}
        engine._rpc_cooldowns = {}

    def tearDown(self):
        (engine._download_jobs, engine._download_totals, engine._rpc_diagnostics,
         engine._website_state, engine._site_arns_tx_ids, engine._rpc_errors, engine._rpc_cooldowns) = self.saved

    def test_download_bytes_completion_failure_and_cancellation(self):
        body = b'\x89PNG\r\n\x1a\n' + b'x' * 100
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, 'log_msg'):
            with patch.object(engine, 'http_open', return_value=Response(body)):
                saved = engine.download_raw_media('https://example.com/a.png', str(Path(folder) / 'asset'))
            self.assertTrue(Path(saved).exists())
            job = next(iter(engine._download_jobs.values()))
            self.assertEqual((job['state'], job['received'], job['total']), ('completed', len(body), len(body)))
            with patch.object(engine, 'http_open', side_effect=OSError('offline')):
                self.assertIsNone(engine.download_raw_media('https://example.com/b.png', str(Path(folder) / 'failed')))
            abort = threading.Event()
            abort.set()
            with patch.object(engine, 'http_open', return_value=Response(body, known_size=False)):
                self.assertIsNone(engine.download_raw_media('https://example.com/c.png', str(Path(folder) / 'canceled'), abort_event=abort))
            self.assertEqual(engine._download_totals, {'completed': 1, 'failed': 1, 'canceled': 1, 'external': 0})

    def test_unsupported_host_fails_without_browser_launch(self):
        with patch.object(engine, 'open_in_browser') as browser:
            engine.download_raw_media('https://gofile.io/d/abc', 'asset')
            browser.assert_not_called()
        self.assertEqual(engine._download_totals['external'], 0)
        self.assertEqual(engine._download_totals['failed'], 1)

    def test_rpc_failover_latency_and_rpc_error_accounting(self):
        with patch.object(engine, 'RPC_ENDPOINTS', ['https://first.test', 'https://second.test']), patch.object(engine, 'http_post_json', side_effect=[(None, OSError('offline')), ({'result': 42}, None)]):
            self.assertEqual(engine.rpc_call('getSlot', []), 42)
        first, second = engine._rpc_diagnostics.values()
        self.assertEqual(first['failures'], 1)
        self.assertEqual(second['successes'], 1)
        self.assertGreaterEqual(second['latency_ms'], 0)
        self.assertIsNotNone(second['last_success'])
        error = {'error': {'code': -32602, 'message': 'Invalid account'}}
        with patch.object(engine, 'RPC_ENDPOINTS', ['https://second.test']), patch.object(engine, 'http_post_json', return_value=(error, None)):
            self.assertEqual(engine.rpc_call('getTokenAccountBalance', [], return_full=True), error)
        self.assertEqual(second['failures'], 1)
        self.assertEqual(second['error'], 'Invalid account')

    def test_website_versions_persist_per_name_and_failed_snapshot_retries(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder), contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(engine, 'ARNS_NAMES', ['cyberleek', 'leek']))
            stack.enter_context(patch.object(engine, 'log_msg'))
            stack.enter_context(patch.object(engine, '_fetch_manifest_asset_texts', return_value=[]))
            stack.enter_context(patch.object(engine, '_scan_text_for_assets', return_value=[]))
            versions = {'cyberleek': 'a' * 43, 'leek': 'b' * 43}
            stack.enter_context(patch.object(engine, '_resolve_arns_tx_id', side_effect=lambda name: (versions[name], 'https://example.com')))
            with patch.object(engine, 'wait_for_refresh', side_effect=[1, None]), patch.object(engine, 'http_get_text', return_value=('<html>snapshot</html>', {}, 'url')):
                engine.site_poller_thread()
            persisted = json.loads(Path('website_history/website_status.json').read_text())
            self.assertEqual(persisted['cyberleek']['archived_version'], versions['cyberleek'])
            self.assertEqual(persisted['leek']['archived_version'], versions['leek'])
            engine._website_state.clear()
            engine._site_arns_tx_ids.clear()
            with patch.object(engine, 'wait_for_refresh', side_effect=[1, None]), patch.object(engine, 'http_get_text') as fetch:
                engine.site_poller_thread()
                fetch.assert_not_called()
            versions['cyberleek'] = 'c' * 43
            with patch.object(engine, 'wait_for_refresh', side_effect=[1, None]), patch.object(engine, 'http_get_text', return_value=None):
                engine.site_poller_thread()
            record = engine._website_state['cyberleek']
            self.assertEqual(record['version'], versions['cyberleek'])
            self.assertEqual(record['archived_version'], 'a' * 43)
            self.assertEqual(record['status'], 'Snapshot unavailable')
            self.assertIsNotNone(record['changed_at'])


if __name__ == '__main__':
    unittest.main()
