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

    def test_correct_mint_and_deepest_pool(self):
        data = engine.select_market_pair([pair(liquidity=99999, mint='other'), pair(), pair('0.02', 500, 123456)])
        self.assertEqual(data['price_usd'], .02)
        self.assertEqual(data['market_cap_usd'], 123456)
        engine._market_data = data
        self.assertEqual(engine.calculate_mcap_and_milestones(.02)['market_cap_usd'], 123456)

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
        with patch.object(engine.time, 'time', return_value=100), patch.object(engine.urllib.request, 'urlopen', return_value=response) as network:
            engine.fetch_cyberleek_usd_price()
            engine.fetch_cyberleek_usd_price()
            self.assertEqual(network.call_count, 1)
        response.read.return_value = json.dumps({'pairs': [pair('0.02', cap=14000000)]}).encode()
        with patch.object(engine.time, 'time', return_value=106), patch.object(engine.urllib.request, 'urlopen', return_value=response):
            self.assertEqual(engine.fetch_cyberleek_usd_price(), .02)
        with patch.object(engine.time, 'time', return_value=112), patch.object(engine.urllib.request, 'urlopen', side_effect=OSError('offline')):
            self.assertEqual(engine.fetch_cyberleek_usd_price(), .02)
        self.assertEqual(len(engine._market_history), 2)
        self.assertEqual(engine._token_price_last_ts, 106)
        self.assertEqual(engine._market_data['error'], 'offline')


if __name__ == '__main__':
    unittest.main()
