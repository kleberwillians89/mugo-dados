"""Jornada do cliente: identidade unificada (sem ligar por nome) e eventos com evidência declarada."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import customer_journey as cj

PK_ANA = "a" * 32
PK_BIA = "b" * 32


def order(ref, at, *, counts=True, cancelled=False, external_id=None, email=None, phone_keys=(), origin=None, value=100, page=None):
    return {"ref": ref, "provider": "shopify", "label": f"#{ref}", "at": at, "value": value, "counts": counts, "cancelled": cancelled,
            "external_id": external_id, "email": email, "phone_keys": list(phone_keys), "origin": origin or {}, "customer_page": page}


def lead(pk, at, **origin):
    return {"phone_key": pk, "first_seen_at": at, "origin": origin}


class BuildTests(unittest.TestCase):
    def test_same_phone_joins_whatsapp_and_order_into_one_person(self):
        result = cj.build("roove", [order("1", "2026-11-03T12:00:00Z", external_id="c1", phone_keys=[PK_ANA], page="pg1")],
                          [lead(PK_ANA, "2026-11-01T09:00:00Z", ad_id="ad9", ad_headline="Black Friday")])
        persons = {i["person_id"] for i in result["identities"]}
        self.assertEqual(len(persons), 1)
        self.assertEqual(result["stats"]["whatsapp_and_purchase"], 1)
        kinds = [e["kind"] for e in result["events"]]
        self.assertEqual(sorted(kinds), ["conversa_whatsapp", "pedido"])
        conversa = next(e for e in result["events"] if e["kind"] == "conversa_whatsapp")
        self.assertEqual((conversa["ad_id"], conversa["campaign"], conversa["evidence"]), ("ad9", "Black Friday", "observado"))

    def test_order_without_origin_after_conversation_is_linked_by_rule(self):
        result = cj.build("roove", [order("1", "2026-11-05T12:00:00Z", phone_keys=[PK_ANA])], [lead(PK_ANA, "2026-11-01T09:00:00Z")])
        pedido = next(e for e in result["events"] if e["kind"] == "pedido")
        self.assertEqual((pedido["channel"], pedido["evidence"]), ("whatsapp", "regra"))
        self.assertIn("depois_da_conversa", pedido["detail"])
        self.assertEqual(result["stats"]["purchases_after_whatsapp"], 1)

    def test_order_with_utm_keeps_observed_origin_and_outside_window_is_not_linked(self):
        result = cj.build("roove", [
            order("1", "2026-11-03T12:00:00Z", phone_keys=[PK_ANA], origin={"origin_channel": "meta_ads", "utm_campaign": "bf"}),
            order("2", "2026-11-20T12:00:00Z", phone_keys=[PK_BIA]),
        ], [lead(PK_ANA, "2026-11-01T09:00:00Z"), lead(PK_BIA, "2026-11-01T09:00:00Z")])
        by_ref = {e["detail"]["pedido"]: e for e in result["events"] if e["kind"] == "pedido"}
        self.assertEqual((by_ref["#1"]["channel"], by_ref["#1"]["evidence"], by_ref["#1"]["campaign"]), ("meta_ads", "observado", "bf"))
        self.assertIsNone(by_ref["#2"]["channel"])
        self.assertNotIn("depois_da_conversa", by_ref["#2"]["detail"])

    def test_second_valid_purchase_is_repurchase_and_cancelled_does_not_count(self):
        result = cj.build("roove", [
            order("1", "2026-10-01T12:00:00Z", email="Ana@Mail.com"),
            order("2", "2026-10-10T12:00:00Z", email="ana@mail.com", cancelled=True, counts=False),
            order("3", "2026-11-01T12:00:00Z", email=" ana@mail.com", external_id="c1"),
        ], [])
        kinds = [e["kind"] for e in sorted(result["events"], key=lambda e: e["at"])]
        self.assertEqual(kinds, ["pedido", "pedido_cancelado", "recompra"])
        self.assertEqual(result["stats"]["repeat_buyers"], 1)
        self.assertEqual(result["stats"]["persons"], 1)

    def test_identity_chain_merges_and_people_without_shared_key_stay_apart(self):
        result = cj.build("roove", [
            order("1", "2026-10-01T12:00:00Z", external_id="c1", email="ana@mail.com"),
            order("2", "2026-10-02T12:00:00Z", email="ana@mail.com", phone_keys=[PK_ANA]),
            order("3", "2026-10-03T12:00:00Z", phone_keys=[PK_BIA]),
            order("4", "2026-10-04T12:00:00Z"),  # sem identificador: não vira pessoa
        ], [lead(PK_ANA, "2026-09-30T12:00:00Z")])
        persons = {}
        for ident in result["identities"]:
            persons.setdefault(ident["person_id"], set()).add(ident["kind"])
        self.assertEqual(len(persons), 2)
        self.assertIn({"external_id", "email_hash", "phone_key"}, persons.values())
        self.assertEqual(result["stats"]["orders_without_identity"], 1)
        # e-mail nunca é gravado em claro
        self.assertFalse(any("@" in i["value"] for i in result["identities"]))

    def test_person_id_is_stable_across_runs(self):
        a = cj.build("roove", [order("1", "2026-10-01T12:00:00Z", external_id="c1", phone_keys=[PK_ANA])], [])
        b = cj.build("roove", [order("1", "2026-10-01T12:00:00Z", external_id="c1", phone_keys=[PK_ANA])], [lead(PK_ANA, "2026-09-01T12:00:00Z")])
        self.assertEqual({i["person_id"] for i in a["identities"]}, {i["person_id"] for i in b["identities"]})

    def test_summary_counts_purchases_and_days(self):
        events = [
            {"kind": "conversa_whatsapp", "at": "2026-11-01T09:00:00+00:00", "channel": "meta_ads", "value": None, "detail": {}},
            {"kind": "pedido", "at": "2026-11-04T09:00:00+00:00", "channel": "whatsapp", "value": 120, "detail": {"conta_como_venda": True}},
            {"kind": "pedido_cancelado", "at": "2026-11-05T09:00:00+00:00", "channel": None, "value": 50, "detail": {}},
            {"kind": "recompra", "at": "2026-11-10T09:00:00+00:00", "channel": "whatsapp", "value": 80, "detail": {"conta_como_venda": True}},
        ]
        s = cj.summarize_person(events)
        self.assertEqual((s["purchases"], s["revenue"], s["days_to_first_purchase"]), (2, 200.0, 3))
        self.assertEqual(s["channels"], ["meta_ads", "whatsapp"])


class RebuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebuild_upserts_deletes_stale_and_records_run(self):
        upsert, delete = AsyncMock(), AsyncMock(return_value=[])
        orders = [order("1", "2026-11-03T12:00:00Z", phone_keys=[PK_ANA], page="pg1")]
        with patch.object(cj, "_load_orders", AsyncMock(return_value=("shopify", orders))), \
             patch.object(cj, "_load_crm_sales", AsyncMock(side_effect=RuntimeError("bridge"))), \
             patch.object(cj, "_load_leads", AsyncMock(return_value=[lead(PK_ANA, "2026-11-01T09:00:00Z")])), \
             patch.object(cj, "sb_upsert", upsert), patch.object(cj, "sb_delete", delete):
            out = await cj.rebuild("roove")
        tables = [c.args[0] for c in upsert.await_args_list]
        self.assertEqual(tables, [cj.IDENTITIES, cj.EVENTS, cj.RUNS])
        self.assertEqual([c.args[0] for c in delete.await_args_list], [cj.IDENTITIES, cj.EVENTS])
        for c in delete.await_args_list:
            self.assertEqual(c.kwargs["filters"], {"client_id": "eq.roove", "built_at": f"lt.{out['built_at']}"})
        self.assertTrue(all(r["built_at"] == out["built_at"] for r in upsert.await_args_list[1].args[1]))
        self.assertEqual(out["stats"]["provider"], "shopify")
        self.assertEqual(out["stats"]["notes"], ["Vendas do CRM da marca indisponíveis agora."])

    async def test_journey_for_customer_reads_person_timeline(self):
        async def select(table, **kw):
            if table == cj.RUNS:
                return [{"built_at": "2026-11-11T00:00:00Z", "stats": {}}]
            if table == cj.IDENTITIES and kw["filters"].get("kind") == "eq.customer_page":
                return [{"person_id": "p1"}]
            if table == cj.IDENTITIES:
                return [{"kind": "customer_page"}, {"kind": "phone_key"}, {"kind": "external_id"}]
            return [{"kind": "pedido", "at": "2026-11-03T12:00:00+00:00", "channel": "whatsapp", "value": 100, "detail": {"conta_como_venda": True}}]
        with patch.object(cj, "sb_select", side_effect=select):
            out = await cj.journey_for_customer("roove", "pg1")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["identities"], ["external_id", "phone_key"])
        self.assertEqual(out["summary"]["purchases"], 1)

    async def test_journey_not_built_and_not_found(self):
        with patch.object(cj, "sb_select", AsyncMock(return_value=[])):
            self.assertEqual((await cj.journey_for_customer("roove", "x"))["status"], "not_built")

        async def select(table, **kw):
            return [{"built_at": "2026-11-11T00:00:00Z", "stats": {}}] if table == cj.RUNS else []
        with patch.object(cj, "sb_select", side_effect=select):
            self.assertEqual((await cj.journey_for_customer("roove", "x"))["status"], "not_found")


    async def test_run_all_skips_companies_without_store_and_isolates_failures(self):
        companies = [{"id": "roove"}, {"id": "sem-loja"}, {"id": "quebra"}]

        async def provider(cid):
            return {"provider": None if cid == "sem-loja" else "shopify"}

        async def rebuild(cid):
            if cid == "quebra":
                raise RuntimeError("x")
            return {"built_at": "t", "stats": {"persons": 7}}
        with patch("services.integration_center._companies", AsyncMock(return_value=companies)), \
             patch("services.commerce_context.resolve_commerce_provider", side_effect=provider), \
             patch.object(cj, "rebuild", side_effect=rebuild):
            out = await cj.run_all()
        self.assertEqual(out, {"clients": 1, "skipped": 1, "errors": 1, "persons": 7})


if __name__ == "__main__":
    unittest.main()
