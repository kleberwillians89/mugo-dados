import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import brand_guard, studio_llm, tenant_guard
from services.studio_calendar import StudioError


def run(coro):
    return asyncio.run(coro)


CLIENTS = [{"id": "latinas", "name": "Latinas Tapas"}, {"id": "roove", "name": "Roove"}, {"id": "ruah", "name": "Ruah Parfums"},
           {"id": "mugo", "name": "Mugo Agencia"}, {"id": "orig", "name": "Origami Investimentos"}]
CONNS = [{"client_id": "roove", "username": "roove.oficial"}, {"client_id": "latinas", "username": "latinas_tapasbrasilenas"}]


async def fake_select(table, **kw):
    return CLIENTS if table == "clients" else CONNS


class TenantGuardTests(unittest.TestCase):
    def setUp(self):
        tenant_guard.clear_cache()
        self.p = patch.object(tenant_guard, "sb_select", fake_select)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        tenant_guard.clear_cache()

    def test_terms_skip_generic_words(self):
        self.assertEqual(tenant_guard.terms_for("Latinas Tapas", ["@latinas_tapasbrasilenas"]),
                         {"latinas tapas", "latinas", "latinas_tapasbrasilenas"})
        self.assertNotIn("investimentos", tenant_guard.terms_for("Origami Investimentos"))

    def test_forbidden_excludes_own_and_mugo(self):
        terms = run(tenant_guard.leak_terms("latinas"))
        self.assertIn("roove", terms)
        self.assertIn("roove.oficial", terms)
        self.assertIn("ruah", terms)
        self.assertNotIn("latinas", terms)
        self.assertFalse(any("mugo" in t for t in terms))

    def test_find_leaks_whole_word_no_accent_case(self):
        terms = run(tenant_guard.leak_terms("latinas"))
        self.assertEqual(tenant_guard.find_leaks("Inspirado na ROOVE e na @roove.oficial", terms), ["roove", "roove.oficial"])
        self.assertEqual(tenant_guard.find_leaks("groove e roovers não são marca", terms), [])
        self.assertEqual(tenant_guard.find_leaks("Equipe Mugô agradece!", terms), [])

    def test_brand_guard_flags_leak(self):
        issues = brand_guard.check("Igual à Origami faz", leak_terms=run(tenant_guard.leak_terms("latinas")))
        self.assertEqual([i["type"] for i in issues], ["vazamento_cliente"])

    def test_llm_retries_then_blocks(self):
        once = AsyncMock(side_effect=[{"caption": "Como a Roove faz"}, {"caption": "Do jeito da Latinas"}])
        with patch.object(studio_llm, "_llm_json_once", once):
            out = run(studio_llm.llm_json(instructions="x", prompt="y", schema_name="s", schema={}, client_id="latinas"))
        self.assertEqual(out, {"caption": "Do jeito da Latinas"})
        self.assertIn("NUNCA cite", once.call_args_list[1].kwargs["instructions"])
        self.assertIn("roove", once.call_args_list[1].kwargs["instructions"])
        bad = AsyncMock(return_value={"caption": "Roove de novo"})
        with patch.object(studio_llm, "_llm_json_once", bad):
            with self.assertRaises(StudioError) as ctx:
                run(studio_llm.llm_json(instructions="x", prompt="y", schema_name="s", schema={}, client_id="latinas"))
        self.assertEqual(ctx.exception.code, "AI_TENANT_LEAK")

    def test_llm_without_brand_or_disabled_skips(self):
        once = AsyncMock(return_value={"caption": "Roove"})
        with patch.object(studio_llm, "_llm_json_once", once):
            self.assertEqual(run(studio_llm.llm_json(instructions="x", prompt="y", schema_name="s", schema={})), {"caption": "Roove"})
            self.assertEqual(run(studio_llm.llm_json(instructions="x", prompt="y", schema_name="s", schema={}, client_id="latinas", leak_check=False)),
                             {"caption": "Roove"})
        self.assertEqual(once.await_count, 2)

    def test_calendar_drops_leaking_item(self):
        from services.studio_calendar import validate_items
        slots = [{"slot_id": "s1", "date": "2026-12-01", "time": "08:00", "format": "reels", "basis": {}},
                 {"slot_id": "s2", "date": "2026-12-02", "time": "08:00", "format": "reels", "basis": {}}]
        raw = {"items": [{"slot_id": "s1", "pillar": "", "title": "Ideia da Roove", "hook": "h", "caption_draft": "c", "rationale": "r", "trend_id": ""},
                         {"slot_id": "s2", "pillar": "", "title": "Coxinha vegana", "hook": "h", "caption_draft": "c", "rationale": "r", "trend_id": ""}]}
        items, warnings = validate_items(raw, slots=slots, profile={}, trends=[], leak_terms=["roove"])
        self.assertEqual([i["title"] for i in items], ["Coxinha vegana"])
        self.assertTrue(any("outra marca" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
