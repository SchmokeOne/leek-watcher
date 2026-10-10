import contextlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import cyberleek_watcher as engine


class RefreshClockTests(unittest.TestCase):
    def setUp(self):
        self.previous_interval = engine._poll_interval
        self.previous_generation = engine._refresh_generation
        engine._shutdown_event.clear()
        engine._refresh_generation = 0
        engine._refresh_active.clear()

    def tearDown(self):
        engine._shutdown_event.set()
        with engine._refresh_condition:
            engine._refresh_condition.notify_all()
        engine._poll_interval = self.previous_interval
        engine._refresh_generation = self.previous_generation
        engine._refresh_active.clear()
        engine._refresh_clock_running = False
        engine._shutdown_event.clear()

    def test_default_minimum_and_saved_reopen(self):
        self.assertEqual(engine.DEFAULT_POLL_INTERVAL_SECONDS, 15)
        self.assertEqual(engine.normalize_poll_interval(2), 5)
        self.assertEqual(engine.normalize_poll_interval('invalid'), 15)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'config.json')
            self.assertEqual(engine.load_config(path)['poll_interval_seconds'], 15)
            engine._poll_interval = 23
            engine.save_config(path)
            self.assertEqual(engine.load_config(path)['poll_interval_seconds'], 23)

    def test_actual_workers_share_ticks_and_reschedule(self):
        observations = {name: [] for name in ('market', 'on-chain', 'arweave', 'website', 'updates')}
        def record(name, result):
            if engine._refresh_generation:
                observations[name].append((engine._refresh_generation, time.monotonic()))
            return result
        workers = []
        with contextlib.ExitStack() as stack:
            folder = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(contextlib.chdir(folder))
            # Accelerate the clock only; production interval validation is tested above.
            stack.enter_context(patch.object(engine, 'normalize_poll_interval', side_effect=lambda value: value / 100))
            stack.enter_context(patch.object(engine, 'fetch_cyberleek_usd_price', side_effect=lambda **kw: record('market', 0)))
            stack.enter_context(patch.object(engine, 'rpc_call', return_value=None))
            stack.enter_context(patch.object(engine, 'fetch_total_reserve_balance', return_value=(None, {})))
            stack.enter_context(patch.object(engine, 'fetch_program_state', side_effect=lambda: record('on-chain', None)))
            stack.enter_context(patch.object(engine, 'arweave_query', side_effect=lambda q: record('arweave', None)))
            stack.enter_context(patch.object(engine, '_resolve_arns_tx_id', side_effect=lambda name: record('website', (None, None))))
            stack.enter_context(patch.object(engine, 'check_for_update', side_effect=lambda: record('updates', None)))
            stack.enter_context(patch.object(engine, 'log_msg'))
            stack.enter_context(patch.object(engine, 'ARNS_NAMES', ['test']))
            engine._poll_interval = 10
            functions = [engine.market_poller_thread, engine.http_poller_background_thread,
                         engine.arweave_poller_thread, engine.site_poller_thread, engine.update_check_thread]
            for function in functions:
                worker = threading.Thread(target=function, daemon=True)
                workers.append(worker)
                worker.start()
            scheduler = threading.Thread(target=engine.refresh_scheduler_thread, daemon=True)
            workers.append(scheduler)
            scheduler.start()
            try:
                limit = time.monotonic() + 3
                while not all(values for values in observations.values()) and time.monotonic() < limit:
                    time.sleep(.01)
                self.assertTrue(all(values for values in observations.values()), observations)
                first_times = [values[0][1] for values in observations.values()]
                self.assertLess(max(first_times) - min(first_times), .08)
                engine._poll_interval = 30
                changed = time.monotonic()
                while not all(any(g >= 2 for g, _ in values) for values in observations.values()) and time.monotonic() < limit:
                    time.sleep(.01)
                self.assertTrue(all(any(g >= 2 for g, _ in values) for values in observations.values()), observations)
                second_times = [next(t for g, t in values if g >= 2) for values in observations.values()]
                self.assertLess(max(second_times) - min(second_times), .08)
                self.assertGreater(min(second_times) - changed, .25)
            finally:
                engine._shutdown_event.set()
                with engine._refresh_condition:
                    engine._refresh_condition.notify_all()
                for worker in workers:
                    worker.join(2)
                self.assertFalse(any(worker.is_alive() for worker in workers))

    def test_market_cache_cannot_trigger_unscheduled_fetch(self):
        engine._refresh_clock_running = True
        with patch.object(engine.urllib.request, 'urlopen') as network:
            engine.fetch_cyberleek_usd_price()
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
