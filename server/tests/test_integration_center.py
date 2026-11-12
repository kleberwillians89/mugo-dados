"""Central de saúde das integrações: todas as empresas, estado de cada fonte, falhas da semana e fila."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import integration_center as ic


def src(provider, state, connected=True, **extra):
    return {"provider": provider, "state": state, "connected": connected, "last_successful_sync_at": "2026-11-11T10:00:00Z", **extra}


class CenterTests(unittest.IsolatedAsyncioTestCase):
    async def test_overview_orders_by_severity_and_counts(self):
        health = {
            "roove": {"sources": [src("shopify", "synced"), src("meta_ads", "reauth_required", error_code="REAUTH_REQUIRED"),
                                  src("ga4", "no_data", connected=False)]},
            "ruah": {"sources": [src("shopify", "synced"), src("instagram", "stale")]},
            "curavino": {"sources": [src("fbits", "synced")]},
        }

        async def read(cid, start, end):
            return health[cid]
        companies = [{"id": "curavino", "name": "Curavino", "status": "active"}, {"id": "roove", "name": "Roove", "status": "active"},
                     {"id": "ruah", "name": "Ruah", "status": "invitation_pending"}]
        with patch.object(ic, "_companies", AsyncMock(return_value=companies)), \
             patch.object(ic, "client_data_health", side_effect=read), \
             patch.object(ic, "_failures", AsyncMock(return_value={("roove", "meta_ads"): 3})), \
             patch.object(ic, "_outbox", AsyncMock(return_value={"ruah": {"waiting": 2, "failed": 1}})):
            out = await ic.overview()
        self.assertEqual([c["id"] for c in out["companies"]], ["roove", "ruah", "curavino"])
        roove = out["companies"][0]
        self.assertEqual(roove["sources"][0]["provider"], "meta_ads")
        self.assertEqual(roove["sources"][0]["action"], "reconnect")
        self.assertEqual(roove["sources"][0]["failures_7d"], 3)
        self.assertEqual(roove["sources"][-1]["state"], "not_connected")
        s = out["summary"]
        self.assertEqual((s["connections"], s["ok"], s["reauth"], s["stale"], s["problems"], s["failures_7d"]), (5, 3, 1, 1, 1, 3))
        self.assertEqual(s["companies_with_problem"], 2)
        self.assertEqual(out["queue"], {"waiting": 2, "failed": 1})

    async def test_one_unreadable_company_does_not_break_the_center(self):
        async def read(cid, start, end):
            if cid == "x":
                raise RuntimeError("timeout")
            return {"sources": [src("shopify", "synced")]}
        companies = [{"id": "x", "name": "X", "status": "active"}, {"id": "y", "name": "Y", "status": "active"}]
        with patch.object(ic, "_companies", AsyncMock(return_value=companies)), patch.object(ic, "client_data_health", side_effect=read), \
             patch.object(ic, "_failures", AsyncMock(side_effect=RuntimeError("db"))), patch.object(ic, "_outbox", AsyncMock(return_value={})):
            out = await ic.overview()
        self.assertEqual(out["companies"][0]["id"], "x")
        self.assertIn("Não foi possível", out["companies"][0]["error"])
        self.assertEqual(out["companies"][1]["sources"][0]["state"], "synced")

    def test_disconnected_source_is_neutral(self):
        row = ic.row_for(src("ga4", "attention", connected=False), failures=0)
        self.assertEqual((row["state"], row["action"]), ("not_connected", "none"))


if __name__ == "__main__":
    unittest.main()
