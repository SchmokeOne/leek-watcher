import json
import unittest
from unittest.mock import patch, MagicMock
import cyberleek_watcher as engine


def pair(price='0.01', liquidity=100, cap=7000000, mint=None):
    return {'chainId': 'solana', 'baseToken': {'address': mint or engine.TOKEN_MINT},
            'priceUsd': price, 'liquidity': {'usd': liquidity}, 'marketCap': cap}


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.saved = (engine._market_data, list(engine._market_history), engine._market_last_attempt,
                      engine._token_price_usd, engine._token_price_last_ts, engine._poll_interval)
        engine._market_data = {}
        engine._market_history.clear()
        engine._market_last_attempt = 0
        engine._poll_interval = 2

    def tearDown(self):
        (engine._market_data, history, engine._market_last_attempt, engine._token_price_usd,
         engine._token_price_last_ts, engine._poll_interval) = self.saved
        engine._market_history.clear()
        engine._market_history.extend(history)

    def test_coingecko_market_cap_never_uses_fdv(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps([{'id': 'cyberleek', 'market_cap': 5000000, 'fully_diluted_valuation': 9000000}]).encode()
        with patch.object(engine.urllib.request, 'urlopen', return_value=response):
            result = engine.fetch_coingecko_market_cap()
            self.assertEqual(result['market_cap_usd'], 5000000)
            self.assertEqual(result['market_cap_source'], 'CoinGecko')
            response.read.return_value = json.dumps([{'id': 'cyberleek', 'market_cap': None, 'fully_diluted_valuation': 9000000}]).encode()
            with self.assertRaises(ValueError):
                engine.fetch_coingecko_market_cap()

    def test_failed_supply_refresh_does_not_block_price_updates(self):
        engine._market_data = {'price_usd': .01, 'market_cap_usd': 5000000, 'basis': 'CoinGecko reported'}
        engine._token_price_usd = .01
        engine._token_price_last_ts = 100
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'pairs': [pair(price='0.02', cap=9000000)]}).encode()
        with patch.object(engine.urllib.request, 'urlopen', return_value=response), patch.object(engine, 'refresh_supply_cache', return_value={'supply': 700000000, 'observed_at': 100, 'error': 'CoinGecko rate limited'}):
            engine.fetch_cyberleek_usd_price(force=True)
        self.assertEqual(engine._market_data['market_cap_usd'], 14000000)
        self.assertGreater(engine._token_price_last_ts, 100)
        self.assertEqual(len(engine._market_history), 1)
        self.assertIn('rate limited', engine._market_data['supply_error'])

    def test_missing_supply_does_not_use_fdv_or_static_estimate(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'pairs': [pair()]}).encode()
        with patch.object(engine.urllib.request, 'urlopen', return_value=response), patch.object(engine, 'refresh_supply_cache', return_value={}):
            engine.fetch_cyberleek_usd_price(force=True)
        self.assertIsNone(engine._market_data['market_cap_usd'])
        self.assertEqual(engine.current_market_cap(.01), 0)
        self.assertEqual(len(engine._market_history), 0)

    def test_supply_worker_waits_61_seconds_and_avoids_duplicate_fetch(self):
        from types import SimpleNamespace
        shutdown = MagicMock()
        shutdown.is_set.return_value = False
        shutdown.wait.return_value = True
        lock = engine.threading.Lock()
        with patch.object(engine, '_supply_cache', {}), patch.object(engine, '_supply_next_refresh', 0), patch.object(engine, '_supply_refresh_lock', lock), patch.object(engine, '_shutdown_event', shutdown), patch.object(engine.time, 'time', return_value=100), patch.object(engine, 'fetch_coingecko_market_cap', return_value={'coingecko_circulating_supply': 730000000}) as fetch, patch.object(engine.threading, 'Thread', side_effect=lambda target, daemon: SimpleNamespace(start=target)):
            engine.refresh_supply_cache()
            engine.refresh_supply_cache()
            fetch.assert_called_once()
            shutdown.wait.assert_called_once_with(61)
            self.assertEqual(engine._supply_next_refresh, 161)
            self.assertFalse(lock.locked())

    def test_correct_mint_and_deepest_pool(self):
        data = engine.select_market_pair([pair(liquidity=99999, mint='other'), pair(), pair('0.02', 500, 123456)])
        self.assertEqual(data['price_usd'], .02)
        self.assertEqual(data['market_cap_usd'], 123456)
        engine._market_data = data
        self.assertEqual(engine.calculate_mcap_and_milestones(.02)['market_cap_usd'], 123456)

    def test_reported_cap_equal_to_fdv_uses_labeled_supply_estimate(self):
        source = pair(price='0.0071', cap=7100542)
        source['fdv'] = 7100542
        market = engine.select_market_pair([source])
        self.assertAlmostEqual(market['market_cap_usd'], .0071 * engine.CIRCULATING_SUPPLY)
        self.assertTrue(market['market_cap_estimated'])
        self.assertTrue(market['reported_cap_equals_fdv'])
        self.assertEqual(market['reported_market_cap_usd'], 7100542)
        self.assertEqual(market['fdv_usd'], 7100542)
        engine._market_data = market
        self.assertEqual(engine.calculate_mcap_and_milestones(.0071)['market_cap_usd'], market['market_cap_usd'])

    def test_distinct_reported_cap_remains_reported(self):
        source = pair(cap=5200000)
        source['fdv'] = 7100000
        market = engine.select_market_pair([source])
        self.assertEqual(market['market_cap_usd'], 5200000)
        self.assertFalse(market['market_cap_estimated'])

    def test_fallback_and_invalid_prices(self):
        data = engine.select_market_pair([pair(cap=None)])
        self.assertAlmostEqual(data['market_cap_usd'], .01 * engine.CIRCULATING_SUPPLY)
        self.assertIn('Estimate', data['basis'])
        with self.assertRaises(ValueError):
            engine.select_market_pair([pair('NaN'), pair('inf'), pair('-1')])

    def test_optional_metrics_preserve_zero_and_signed_changes(self):
        source = pair()
        source.update({'volume': {'h24': 0}, 'priceChange': {'m5': -3.5},
                       'txns': {'h24': {'buys': 0, 'sells': 12}}, 'fdv': 9000000})
        data = engine.select_market_pair([source])
        self.assertEqual(data['volume']['h24'], 0)
        self.assertIsNone(data['volume']['h1'])
        self.assertEqual(data['price_change']['m5'], -3.5)
        self.assertEqual(data['transactions']['h24']['buys'], 0)
        self.assertEqual(data['fdv_usd'], 9000000)
        self.assertEqual(data['market_cap_usd'], 7000000)

    def test_refresh_after_cache_and_preserve_failed_observation(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'pairs': [pair()]}).encode()
        with patch.object(engine.time, 'time', return_value=100), patch.object(engine.urllib.request, 'urlopen', return_value=response) as network, patch.object(engine, 'refresh_supply_cache', return_value={'supply': 700000000, 'observed_at': 100}):
            engine.fetch_cyberleek_usd_price()
            engine.fetch_cyberleek_usd_price()
            self.assertEqual(network.call_count, 1)
        response.read.return_value = json.dumps({'pairs': [pair('0.02', cap=14000000)]}).encode()
        with patch.object(engine.time, 'time', return_value=106), patch.object(engine.urllib.request, 'urlopen', return_value=response), patch.object(engine, 'refresh_supply_cache', return_value={'supply': 700000000, 'observed_at': 100}):
            self.assertEqual(engine.fetch_cyberleek_usd_price(), .02)
        with patch.object(engine.time, 'time', return_value=112), patch.object(engine.urllib.request, 'urlopen', side_effect=OSError('offline')):
            self.assertEqual(engine.fetch_cyberleek_usd_price(), .02)
        self.assertEqual(len(engine._market_history), 2)
        self.assertEqual(engine._token_price_last_ts, 106)
        self.assertEqual(engine._market_data['error'], 'offline')


if __name__ == '__main__':
    unittest.main()
