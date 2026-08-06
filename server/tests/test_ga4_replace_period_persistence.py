from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import ga4_sync


class ReplacePeriodRowsPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_inserts_new_rows_before_deleting_old_ones(self):
        """
        _replace_period_rows é o fallback usado quando o upsert falha por
        constraint ausente. Não há transação entre insert e delete — se a
        ordem fosse delete-then-insert e o processo caísse entre as duas
        chamadas, a tabela ficaria sem nenhuma linha para o período
        (perda de dado real). A ordem correta é insert-then-delete: na
        pior falha sobra uma duplicata temporária, nunca dado perdido.
        """
        call_order: list[str] = []

        async def fake_insert_many(table, rows, returning="minimal"):
            call_order.append("insert")
            return {"ok": True, "count": len(rows)}

        async def fake_delete(table, *, filters, returning="representation"):
            call_order.append("delete")
            return []

        rows = [
            {"client_id": "amalie", "property_id": "p1", "stat_date": "2026-08-01", "sessions": 10},
        ]

        with (
            patch.object(ga4_sync, "sb_insert_many", fake_insert_many),
            patch.object(ga4_sync, "sb_delete", fake_delete),
        ):
            await ga4_sync._replace_period_rows(table="ga4_daily_stats", rows=rows)

        self.assertEqual(call_order, ["insert", "delete"])

    async def test_data_survives_if_delete_step_fails(self):
        """Se o delete falhar após o insert, os dados novos já persistidos continuam no banco (nenhuma exceção deve apagar o que já foi inserido)."""
        inserted = {"done": False}

        async def fake_insert_many(table, rows, returning="minimal"):
            inserted["done"] = True
            return {"ok": True, "count": len(rows)}

        async def failing_delete(table, *, filters, returning="representation"):
            raise RuntimeError("simulated delete failure")

        rows = [{"client_id": "amalie", "property_id": "p1", "stat_date": "2026-08-01"}]

        with (
            patch.object(ga4_sync, "sb_insert_many", fake_insert_many),
            patch.object(ga4_sync, "sb_delete", failing_delete),
        ):
            with self.assertRaises(RuntimeError):
                await ga4_sync._replace_period_rows(table="ga4_daily_stats", rows=rows)

        # O insert já havia sido concluído antes da falha do delete — os
        # dados novos não foram perdidos, mesmo com a exceção subsequente.
        self.assertTrue(inserted["done"])

    async def test_delete_filter_excludes_just_inserted_rows_by_created_at_cutoff(self):
        captured = {}

        async def fake_insert_many(table, rows, returning="minimal"):
            return {"ok": True, "count": len(rows)}

        async def fake_delete(table, *, filters, returning="representation"):
            captured["filters"] = filters
            return []

        rows = [{"client_id": "amalie", "property_id": "p1", "stat_date": "2026-08-01"}]

        with (
            patch.object(ga4_sync, "sb_insert_many", fake_insert_many),
            patch.object(ga4_sync, "sb_delete", fake_delete),
        ):
            await ga4_sync._replace_period_rows(table="ga4_daily_stats", rows=rows)

        self.assertIn("created_at", captured["filters"])
        self.assertTrue(captured["filters"]["created_at"].startswith("lt."))


if __name__ == "__main__":
    unittest.main()
