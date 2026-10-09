import unittest
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).resolve().parents[1] / "monitor.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TestFluidMonitor(unittest.TestCase):
    def test_numeric_zero(self):
        self.assertEqual(m.numeric(0), 0)
        self.assertIsNone(m.numeric(None))
        self.assertIsNone(m.numeric(float("nan")))
        self.assertIsNone(m.numeric(True))

    def test_percentage(self):
        self.assertEqual(m.percentage(150, 100), 50)
        self.assertIsNone(m.percentage(10, 0))
        self.assertIsNone(m.percentage(None, 100))

    def test_extract_flow(self):
        self.assertEqual(m.extract_flow({"total30d":0})["total_30d_usd"], 0)
        self.assertEqual(m.extract_flow({})["status"], "UNKNOWN")

    def test_tvl_does_not_add_borrowed(self):
        raw = {"tvl":[{"date":1760000000,"totalLiquidityUSD":123}], "currentChainTvls":{"Ethereum":123,"Ethereum-borrowed":500}}
        x=m.extract_tvl(raw)
        self.assertEqual(x["tvl_usd"],123)
        self.assertNotIn("Ethereum-borrowed", x["chain_tvl_usd_non_additive"])

    def test_observation(self):
        self.assertIsNone(m.last_observation([]))
        self.assertIsNotNone(m.last_observation([[1760000000, 1]]))

if __name__ == "__main__":
    unittest.main()
