import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import diagnostics as dg


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_codes(self):
        with patch("services.external_research.get_provider", return_value=None):
            self.assertEqual((await dg.research_check("c"))["exit_code"], 10)
        broken = MagicMock(find_market_signals=AsyncMock(side_effect=RuntimeError("401")))
        with patch("services.external_research.get_provider", return_value=broken):
            self.assertEqual((await dg.research_check("c"))["exit_code"], 11)
        empty = MagicMock(find_market_signals=AsyncMock(return_value=[]))
        with patch("services.external_research.get_provider", return_value=empty):
            self.assertEqual((await dg.research_check("c"))["exit_code"], 12)
        ok = MagicMock(find_market_signals=AsyncMock(return_value=[{"source_url": "https://x"}]))
        with patch("services.external_research.get_provider", return_value=ok):
            self.assertEqual((await dg.research_check("c"))["exit_code"], 0)

    async def test_competitor_codes(self):
        for rows, code in (([], 21), ([{"competitor_terms": []}], 20), ([{"competitor_terms": ["Wine"]}], 0)):
            with patch.object(dg, "sb_select", AsyncMock(return_value=rows)):
                self.assertEqual((await dg.competitors_check("c"))["exit_code"], code)


if __name__ == "__main__":
    unittest.main()
