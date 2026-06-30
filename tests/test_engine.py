from __future__ import annotations

import unittest

from cryptoagents.strategy.strategies import S1EMATrend, S2RSIReversal, S3MACDResonance, S4Martingale, S5EMAScalping, S6TD9
from cryptoagents.backtest.engine import BacktestEngine, SPEEDS
from cryptoagents.data.kline_converter import ConvertedKline, KlineConverter


def _make_df(prices):
    import pandas as pd
    return pd.DataFrame({"open": prices, "high": [p * 1.02 for p in prices],
                         "low": [p * 0.98 for p in prices], "close": prices,
                         "volume": [1000.0] * len(prices)})


class StrategyTest(unittest.TestCase):
    def test_s1(self): self.assertIn(S1EMATrend().calculate(_make_df(list(range(100, 200)))).signal, ("BUY", "SELL", "HOLD"))
    def test_s2(self): self.assertIn(S2RSIReversal().calculate(_make_df([100.0] * 50)).signal, ("BUY", "SELL", "HOLD"))
    def test_s3(self): self.assertIn(S3MACDResonance().calculate(_make_df(list(range(100, 200)))).signal, ("BUY", "SELL", "HOLD"))
    def test_s4(self): self.assertIn(S4Martingale().calculate(_make_df(list(range(100, 200)))).signal, ("BUY", "SELL", "HOLD"))
    def test_s5(self): self.assertIn(S5EMAScalping().calculate(_make_df(list(range(100, 200)))).signal, ("BUY", "SELL", "HOLD"))
    def test_s6(self): self.assertIn(S6TD9().calculate(_make_df(list(range(100, 200)))).signal, ("BUY", "SELL", "HOLD"))


class KlineConverterTest(unittest.TestCase):
    def setUp(self): self.cv = KlineConverter()

    def test_realtime(self):
        k = self.cv.convert_realtime({"close": 1.0023, "low": 0.9910, "high": 1.0120, "timestamp": 1710000000}, {"close": 0.9950})
        self.assertEqual(k.F, 1.0023)
        self.assertEqual(k.S, 0.9950)
        self.assertEqual(k.direction, "")

    def test_closed_up(self):
        k = self.cv.convert_closed({"close": 1.0050, "open": 1.0000, "low": 0.9910, "high": 1.0120, "timestamp": 1710000000}, {"close": 0.9950})
        self.assertEqual(k.direction, "U")

    def test_closed_down(self):
        k = self.cv.convert_closed({"close": 0.9900, "open": 1.0000, "low": 0.9800, "high": 1.0050, "timestamp": 1710000000}, {"close": 0.9950})
        self.assertEqual(k.direction, "D")

    def test_string(self):
        k = ConvertedKline(F=1.0023, S=0.9950, L=0.9910, H=1.0120, timestamp=1710000000, direction="U")
        self.assertIn("F1.0023", k.to_standard_string())
        self.assertIn("| U", k.to_standard_string())


class BacktestSpeedTest(unittest.TestCase):
    def test_defaults(self):
        e = BacktestEngine("ETH/USDT", "2024-01-01", "2024-01-31", S1EMATrend(), speed=1)
        self.assertEqual(e.speed, 1)
        self.assertFalse(e._cancelled)

    def test_set_speed(self):
        e = BacktestEngine("ETH/USDT", "2024-01-01", "2024-01-31", S1EMATrend(), speed=1)
        e.set_speed(10)
        self.assertEqual(e.speed, 10)
        e.set_speed(500)
        self.assertEqual(e.speed, 100)

    def test_cancel(self):
        e = BacktestEngine("ETH/USDT", "2024-01-01", "2024-01-31", S1EMATrend())
        e.cancel()
        self.assertTrue(e._cancelled)

    def test_progress_callback(self):
        e = BacktestEngine("ETH/USDT", "2024-01-01", "2024-01-31", S1EMATrend(), speed=1)
        calls = []
        e.progress_callback = lambda d: calls.append(d)
        e._report(5, 100)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["current_step"], 5)

    def test_speeds(self):
        self.assertEqual(SPEEDS, [1, 2, 5, 10, 20, 100])


if __name__ == "__main__":
    unittest.main()
