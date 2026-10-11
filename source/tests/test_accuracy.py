import time
import unittest
from unittest.mock import patch
import cyberleek_watcher as engine


class AccuracyTests(unittest.TestCase):
    def test_nullable_ui_amount_uses_precise_string(self):
        with patch.object(engine, 'rpc_call', return_value={'result': {'value': {'uiAmount': None, 'uiAmountString': '123.456'}}}):
            self.assertEqual(engine.fetch_token_balance('account'), 123.456)

    def test_settings_failure_is_reported(self):
        with patch.object(engine.os, 'replace', side_effect=OSError('disk full')), patch.object(engine, 'log_msg') as log:
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as folder:
                self.assertFalse(engine.save_config(str(Path(folder) / 'config.json')))
            self.assertIn('could not be saved', log.call_args.args[0])

    def test_partial_program_snapshot_is_rejected(self):
        with patch.object(engine, 'PROGRAM_IDS', ['one', 'two']), patch.object(engine, 'rpc_call', side_effect=[[], None]):
            self.assertIsNone(engine.fetch_program_state())

    def test_rpc_server_error_fails_over(self):
        with patch.object(engine, 'RPC_ENDPOINTS', ['https://a.test', 'https://b.test']), patch.object(engine, '_rpc_cooldowns', {}), patch.object(engine, 'http_post_json', side_effect=[({'error': {'code': -32005, 'message': 'unhealthy'}}, None), ({'result': 123}, None)]):
            self.assertEqual(engine.rpc_call('getSlot', []), 123)

    def test_failed_reserve_refresh_does_not_commit_partial_values(self):
        accounts = {'a': {'balance': 10}, 'b': {'balance': 20}}
        with patch.object(engine, '_monitored_reserve_atas', accounts), patch.object(engine, 'fetch_token_balance', side_effect=[99, None]):
            self.assertEqual(engine.fetch_total_reserve_balance(), (None, {}))
            self.assertEqual(accounts['a']['balance'], 10)

    def test_failed_vote_refresh_preserves_last_complete_snapshot(self):
        previous = {'pda': 'poll', 'balances': [10, 20], 'total': 30}
        proposal = {'pda': 'poll', 'poll_id': 'id', 'choices': ['a', 'b'], 'ends_at': time.time() + 3600, 'finalized': [False, False]}
        with patch.object(engine, '_active_poll_info', previous), patch.object(engine, 'get_or_derive_option_atas', return_value=[('a', 'ata-a'), ('b', 'ata-b')]), patch.object(engine, 'fetch_cyberleek_usd_price', return_value=1), patch.object(engine, 'fetch_token_balance', side_effect=[99, None]):
            engine.poll_active_proposals([proposal])
            self.assertEqual(engine._active_poll_info['balances'], [10, 20])
            self.assertEqual(engine._active_poll_info['total'], 30)
            self.assertTrue(engine._active_poll_info['stale'])


if __name__ == '__main__':
    unittest.main()
