import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cyberleek_watcher as engine


class BackfillTests(unittest.TestCase):
    def test_automatic_retrieval_never_launches_external_apps(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, 'open_in_browser') as browser, patch.object(engine.os, 'startfile', create=True) as launch, patch.object(engine, 'log_msg'), patch.object(engine, '_auto_open', True), patch.object(engine, '_browser_fallback', True):
            engine.retrieve_asset({'pda': 'test', 'title': 'test', 'mirrors': [{'label': 'torrent', 'url': 'magnet:?xt=urn:btih:abc'}, {'label': 'host', 'url': 'https://gofile.io/d/abc'}]}, folder)
            browser.assert_not_called()
            launch.assert_not_called()

    def test_auto_open_defaults_off(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(engine.load_config(str(Path(folder) / 'config.json'))['auto_open_media'])

    def test_saved_files_skip_missing_files_download_quietly(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'saved.png').write_bytes(b'content')
            Path(folder, 'manifest.json').write_text(json.dumps({'saved': {'saved_file': 'saved.png'}}))
            with patch.object(engine, '_download_dir', folder), patch.object(engine, '_watch_only', False), patch.object(engine._shutdown_event, 'is_set', return_value=False), patch.object(engine, 'retrieve_asset') as retrieve, patch.object(engine, 'log_msg'):
                engine.backfill_assets([{'pda': 'saved'}, {'pda': 'missing'}])
                retrieve.assert_called_once_with({'pda': 'missing', 'quiet': True}, folder)

    def test_failed_scan_reports_and_does_not_download(self):
        with patch.object(engine, '_watch_only', False), patch.object(engine, 'fetch_program_state', return_value=None), patch.object(engine, 'retrieve_asset') as retrieve, patch.object(engine, 'log_msg') as log:
            engine.backfill_assets()
            retrieve.assert_not_called()
            self.assertIn('scan failed', log.call_args.args[0])

    def test_disabled_downloads_do_not_scan(self):
        with patch.object(engine, '_watch_only', True), patch.object(engine, 'fetch_program_state') as scan, patch.object(engine, 'log_msg'):
            engine.backfill_assets()
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
