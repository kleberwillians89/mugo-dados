"""Ações da IA: detectores certos, nada executa sem aprovação, aprovação usa as ferramentas reais, falha registrada."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import ai_actions as aa

BASE = {"provider": "shopify", "sender_ready": True, "inactive_with_consent": 340, "recent_reactivation_campaign": False,
        "flows_enabled": [], "cart_enabled": False, "orders_30d": 420, "carts_30d": 0, "customers": 6000, "repeat_rate": 22.5,
        "median_days_to_second": 41, "cac_last_month": 95.0, "cac_avg_prev": 70.0}


class DetectTests(unittest.TestCase):
    def test_all_signals(self):
        kinds = {p["kind"]: p for p in aa.detect(BASE, month="2026-11")}
        self.assertEqual(set(kinds), {"campanha_reativacao", "ligar_fluxo", "ligar_carrinho", "alerta_cac"})
        self.assertEqual(kinds["ligar_fluxo"]["payload"], {"flow": "segunda_compra", "delay_days": 41})
        self.assertEqual(kinds["alerta_cac"]["evidence"]["increase_pct"], 35.7)
        self.assertEqual(kinds["campanha_reativacao"]["dedupe_key"], "campanha_reativacao:2026-11")

    def test_no_noise_when_healthy_or_not_ready(self):
        healthy = {**BASE, "inactive_with_consent": 10, "repeat_rate": 41, "cart_enabled": True, "cac_last_month": 72.0}
        self.assertEqual(aa.detect(healthy, month="2026-11"), [])
        no_sender = {**BASE, "sender_ready": False}
        self.assertEqual({p["kind"] for p in aa.detect(no_sender, month="2026-11")}, {"alerta_cac"})
        self.assertNotIn("campanha_reativacao", {p["kind"] for p in aa.detect({**BASE, "recent_reactivation_campaign": True}, month="m")})
        self.assertNotIn("ligar_carrinho", {p["kind"] for p in aa.detect({**BASE, "provider": "fbits"}, month="m")})


class DecideTests(unittest.IsolatedAsyncioTestCase):
    def action(self, **extra):
        return {"id": "a1", "kind": "ligar_fluxo", "status": "proposta", "payload": {"flow": "segunda_compra", "delay_days": 41}, **extra}

    async def test_approve_executes_with_real_tool(self):
        update = AsyncMock()
        with patch.object(aa, "_get", AsyncMock(side_effect=[self.action(), self.action(status="executada")])), \
             patch.object(aa, "sb_update", update), \
             patch("services.commercial_flows.save_flow", AsyncMock(return_value={"kind": "segunda_compra", "delay_days": 41})) as save_flow:
            out = await aa.decide("roove", "a1", "aprovar", user_id="u1")
        self.assertEqual(out["status"], "executada")
        self.assertEqual(save_flow.await_args.args[2], {"enabled": True, "channel": "email", "delay_days": 41})
        self.assertEqual(update.await_args.kwargs["patch"]["result"], {"flow": "segunda_compra", "delay_days": 41})

    async def test_reject_does_nothing_else(self):
        update = AsyncMock()
        with patch.object(aa, "_get", AsyncMock(side_effect=[self.action(), self.action(status="rejeitada")])), patch.object(aa, "sb_update", update), \
             patch.object(aa, "execute", AsyncMock()) as execute:
            await aa.decide("roove", "a1", "rejeitar", user_id="u1")
        execute.assert_not_awaited()
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "rejeitada")

    async def test_failure_is_recorded_and_decided_twice_is_blocked(self):
        update = AsyncMock()
        boom = AsyncMock(side_effect=RuntimeError("x"))
        with patch.object(aa, "_get", AsyncMock(side_effect=[self.action(), self.action(status="falhou")])), patch.object(aa, "sb_update", update), \
             patch.object(aa, "execute", boom):
            await aa.decide("roove", "a1", "aprovar", user_id="u1")
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "falhou")
        with patch.object(aa, "_get", AsyncMock(return_value=self.action(status="executada"))):
            with self.assertRaises(aa.ActionError):
                await aa.decide("roove", "a1", "aprovar", user_id="u1")

    async def test_generate_skips_existing_and_falls_back_without_ai(self):
        insert = AsyncMock()
        with patch.object(aa, "snapshot", AsyncMock(return_value=BASE)), \
             patch.object(aa, "sb_select", AsyncMock(return_value=[{"dedupe_key": f"alerta_cac:{aa._now().strftime('%Y-%m')}"}])), \
             patch("services.email_marketing.get_settings", AsyncMock(return_value={"from_name": "Roove"})), \
             patch("services.studio_llm.llm_json", AsyncMock(side_effect=RuntimeError("sem chave"))), patch.object(aa, "sb_insert", insert):
            out = await aa.generate("roove")
        self.assertEqual(out["created"], 3)
        first = insert.await_args_list[0].args[1]
        self.assertEqual(first["title"], "Reativar 340 clientes que pararam de comprar")
        self.assertIn("{{primeiro_nome}}", first["payload"]["subject"])


if __name__ == "__main__":
    unittest.main()
