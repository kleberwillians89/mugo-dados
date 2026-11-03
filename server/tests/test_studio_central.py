"""Central da marca: blocos independentes, versão do cliente filtrada e alertas só com dado real."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_central as sc


class CentralTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, agency: bool, **overrides):
        values = {"_numbers": {"investimento": 1000.0, "faturamento": 9000.0, "retorno": 9.0}, "_calendar": {"counts": {}, "waiting_client": 2, "off_brand": [{"id": "x"}]},
                  "_media": {"elapsed_days": 10, "channels": [{"label": "Meta Ads", "pace": 1.3}, {"label": "Google Ads", "pace": 0.5}]},
                  "_clipping": {"week": {"current": {"negativo": 1, "total": 3}}, "latest": []},
                  "_tasks": {"available": True, "open": 3, "late": 1, "next": []},
                  "_campaigns": [{"name": "Black Friday", "status": "rascunho", "posts_no_calendario": 0}]}
        values.update(overrides)
        patches = [patch.object(sc, k, AsyncMock(side_effect=v) if isinstance(v, Exception) else AsyncMock(return_value=v)) for k, v in values.items()]
        for p in patches:
            p.start()
        try:
            with redirect_stdout(io.StringIO()):
                return await sc.build_central("ruah", date(2026, 11, 1), agency=agency), {k: v for k, v in zip(values, patches)}
        finally:
            for p in patches:
                p.stop()

    async def test_agency_sees_everything_and_alerts_come_from_the_data(self):
        out, _ = await self.build(True)
        self.assertEqual(out["campaigns"][0]["name"], "Black Friday")
        texts = " | ".join(a["text"] for a in out["alerts"])
        self.assertIn("2 post(s) com o cliente há mais de 2 dias", texts)
        self.assertIn("fidelidade à marca", texts)
        self.assertIn("Meta Ads: no ritmo atual, gasta 30% acima", texts)
        self.assertIn("Google Ads: investindo 50% abaixo", texts)
        self.assertIn("1 notícia(s) negativa(s)", texts)
        self.assertIn("Black Friday", texts)
        self.assertIn("1 tarefa(s) atrasada(s)", texts)

    async def test_client_version_has_no_campaigns_nor_internal_alerts(self):
        out, _ = await self.build(False)
        self.assertNotIn("campaigns", out)
        texts = " | ".join(a["text"] for a in out["alerts"])
        self.assertNotIn("fidelidade", texts)
        self.assertNotIn("Black Friday", texts)

    async def test_a_block_that_fails_is_null_and_the_page_still_loads(self):
        out, _ = await self.build(True, _media=RuntimeError("fora"))
        self.assertIsNone(out["media"])
        self.assertEqual(out["numbers"]["retorno"], 9.0)


if __name__ == "__main__":
    unittest.main()
