import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from run_research import (
    DataQualityError,
    enforce_data_quality_gate,
    equity_return_stats,
    reconstruct_continuous_session_paths,
)


class DataQualityGateTests(unittest.TestCase):
    def test_blocks_extreme_price_discontinuity(self):
        quality = {
            "equity_one_minute_median_absolute_return_pct": 62.685,
            "equity_one_minute_fraction_absolute_return_over_20pct": 0.80488,
        }
        with self.assertRaises(DataQualityError) as context:
            enforce_data_quality_gate(quality)
        self.assertTrue(quality["backtest_blocked"])
        self.assertEqual(len(quality["backtest_block_reasons"]), 2)
        self.assertIn("DATA-QUALITY GATE FAILED", str(context.exception))

    def test_allows_data_inside_thresholds(self):
        quality = {
            "equity_one_minute_median_absolute_return_pct": 0.35,
            "equity_one_minute_fraction_absolute_return_over_20pct": 0.001,
        }
        result = enforce_data_quality_gate(quality)
        self.assertFalse(result["backtest_blocked"])
        self.assertEqual(result["backtest_block_reasons"], [])

    def test_blocks_missing_diagnostics(self):
        with self.assertRaises(DataQualityError):
            enforce_data_quality_gate({})

    def test_reconstruction_stitches_within_bar_returns(self):
        raw = pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2025-11-10 09:30", "2025-11-10 09:31", "2025-11-11 09:30",
            ]),
            "date": ["2025-11-10", "2025-11-10", "2025-11-11"],
            "minute": [0, 1, 0],
            "ticker": ["T0001", "T0001", "T0001"],
            "open": [100.0, 50.0, 80.0],
            "high": [101.0, 51.0, 81.0],
            "low": [99.0, 49.0, 79.0],
            "close": [100.5, 50.5, 80.4],
            "adj_close": [100.5, 50.5, 80.4],
            "bid": [100.4, 50.4, 80.3],
            "ask": [100.6, 50.6, 80.5],
        })
        out = reconstruct_continuous_session_paths(raw)
        first = out.iloc[0]
        second = out.iloc[1]
        next_session = out.iloc[2]
        self.assertAlmostEqual(first["close"], 100.5)
        self.assertAlmostEqual(second["open"], first["close"])
        self.assertAlmostEqual(second["close"] / second["open"] - 1, 50.5 / 50.0 - 1)
        raw_spread = (50.6 - 50.4) / ((50.6 + 50.4) / 2)
        new_mid = (second["ask"] + second["bid"]) / 2
        new_spread = (second["ask"] - second["bid"]) / new_mid
        self.assertAlmostEqual(new_spread, raw_spread)
        self.assertAlmostEqual(next_session["open"], 80.0)
        stats = equity_return_stats(out)
        self.assertLess(stats["equity_one_minute_median_absolute_return_pct"], 2.0)
        self.assertLess(stats["equity_one_minute_fraction_absolute_return_over_20pct"], 0.01)


if __name__ == "__main__":
    unittest.main()
