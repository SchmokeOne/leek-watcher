import tempfile
from pathlib import Path
import os
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from cyberleek_dashboard import Dashboard, engine


class LoadingTests(unittest.TestCase):
    def test_refresh_survives_missing_supply_then_displays_cap(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            try:
                os.chdir(folder)
                app = Dashboard(root, offline=True)
                with patch.object(engine, '_market_data', {'price_usd': .007, 'market_cap_usd': None, 'market_cap_estimated': True, 'market_cap_source': 'DexScreener price x CoinGecko supply', 'observed_at': time.time()}):
                    app.refresh()
                    self.assertEqual(app.values['mcap'].cget('text'), '--')
                    engine._market_data.update(market_cap_usd=5110000, circulating_supply_used=730000000, supply_observed_at=time.time())
                    app.refresh()
                    self.assertEqual(app.values['mcap'].cget('text'), '$5,110,000')
                callbacks = root.tk.call('after', 'info')
                self.assertTrue(callbacks)
            finally:
                root.destroy()
                os.chdir(previous)
