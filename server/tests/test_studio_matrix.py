"""Social Media: Matriz de Conteúdo, calendário multiplataforma e o módulo liberado pela Mugô."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import ig_publish
from services import studio_calendar as cal
from services import studio_matrix as mx
from services import team_access as ta
from services import team_admin as tadmin
from services.studio_calendar import StudioError

PROFILE = {"pillars": [{"name": "Bastidores", "weight": 40, "description": ""}, {"name": "Produto", "weight": 60, "description": ""}],
           "keywords_avoid": ["barato"], "content_language": "pt-BR"}


def op(**kw):
    base = {"plataforma": "instagram", "pilar": "Produto", "semana": 1, "dia_semana": 2, "formato": "reels",
            "titulo": "Como nasce o perfume", "gancho": "Você sabia?", "angulo": "processo", "legenda": "Legenda", "por_que": "Reels alcançam mais"}
    base.update(kw)
    return base


class NormalizeTests(unittest.TestCase):
    def test_requires_pillars(self):
        with self.assertRaises(StudioError) as ctx:
            mx.normalize_request({}, {"pillars": []})
        self.assertEqual(ctx.exception.code, "MATRIX_PILLARS_REQUIRED")

    def test_starts_on_monday_and_keeps_only_known_platforms_and_pillars(self):
        req = mx.normalize_request({"week_start": "2026-11-18", "platforms": ["tiktok", "orkut", "tiktok"], "pillars": ["produto", "x"],
                                    "per_week": 9}, PROFILE, today=date(2026, 11, 9))
        self.assertEqual(req["week_start"], date(2026, 11, 16))
        self.assertEqual(req["platforms"], ["tiktok"])
        self.assertEqual(req["pillars"], ["Produto"])
        self.assertEqual(req["per_week"], mx.MAX_PER_WEEK)

    def test_default_is_next_monday_and_past_week_is_refused(self):
        self.assertEqual(mx.normalize_request({}, PROFILE, today=date(2026, 11, 9))["week_start"], date(2026, 11, 16))
        with self.assertRaises(StudioError):
            mx.normalize_request({"week_start": "2026-10-01"}, PROFILE, today=date(2026, 11, 9))


class CleanTests(unittest.TestCase):
    P = ["instagram", "tiktok"]
    PL = ["Produto", "Bastidores"]

    def test_discards_out_of_scope_items(self):
        self.assertIsNone(mx.clean_opportunity(op(plataforma="linkedin"), platforms=self.P, pillars=self.PL))
        self.assertIsNone(mx.clean_opportunity(op(pilar="Inventado"), platforms=self.P, pillars=self.PL))
        self.assertIsNone(mx.clean_opportunity(op(semana=5), platforms=self.P, pillars=self.PL))
        self.assertIsNone(mx.clean_opportunity(op(titulo=" "), platforms=self.P, pillars=self.PL))

    def test_fixes_format_for_platform_and_pillar_case(self):
        out = mx.clean_opportunity(op(plataforma="TikTok", formato="carrossel", pilar="produto", titulo="A — B"), platforms=self.P, pillars=self.PL)
        self.assertEqual((out["platform"], out["format"], out["pillar"]), ("tiktok", "video", "Produto"))
        self.assertEqual(out["title"], "A, B")  # sem travessão

    def test_cap_per_platform_and_week(self):
        items = [mx.clean_opportunity(op(titulo=f"t{i}"), platforms=self.P, pillars=self.PL) for i in range(5)]
        items.append(mx.clean_opportunity(op(semana=2), platforms=self.P, pillars=self.PL))
        capped = mx.cap_per_slot(items, 2)
        self.assertEqual([(i["week"], i["title"]) for i in capped], [(1, "t0"), (1, "t1"), (2, "Como nasce o perfume")])


class GenerateTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_saves_matrix_and_validated_opportunities(self):
        llm = AsyncMock(return_value={"resumo": "Mês de lançamento.", "oportunidades": [
            op(), op(plataforma="tiktok", formato="video", semana=3), op(plataforma="linkedin"), "lixo"]})
        insert = AsyncMock(return_value={"id": "m1"})
        many = AsyncMock()
        with patch.object(mx, "load_profile", AsyncMock(return_value={"profile": PROFILE})), \
             patch.object(mx, "build_content_intelligence", AsyncMock(return_value={"marca": {}})), \
             patch.object(mx, "llm_json", llm), patch.object(mx, "sb_insert", insert), patch.object(mx, "sb_insert_many", many), \
             patch.object(mx, "get_matrix", AsyncMock(return_value={"id": "m1", "opportunities": []})), patch.object(mx, "throttle"):
            out = await mx.generate("ruah", {"platforms": ["instagram", "tiktok"]}, user_id="u1", today=date(2026, 11, 9))
        self.assertEqual(out["id"], "m1")
        saved = insert.await_args.args[1]
        self.assertEqual(saved["client_id"], "ruah")
        self.assertEqual(saved["week_start"], "2026-11-16")
        self.assertIn("descartada", saved["notes"][0])  # o LinkedIn não foi pedido
        rows = many.await_args.args[1]
        self.assertEqual([(r["platform"], r["week"]) for r in rows], [("instagram", 1), ("tiktok", 3)])
        self.assertTrue(all(r["client_id"] == "ruah" and r["matrix_id"] == "m1" and r["status"] == "sugerida" for r in rows))
        self.assertIn("Bastidores", llm.await_args.kwargs["prompt"])

    async def test_nothing_valid_from_ai_is_an_error_and_nothing_is_saved(self):
        insert = AsyncMock()
        with patch.object(mx, "load_profile", AsyncMock(return_value={"profile": PROFILE})), \
             patch.object(mx, "build_content_intelligence", AsyncMock(return_value={})), patch.object(mx, "throttle"), \
             patch.object(mx, "llm_json", AsyncMock(return_value={"oportunidades": [op(plataforma="orkut")]})), \
             patch.object(mx, "sb_insert", insert):
            with self.assertRaises(StudioError) as ctx:
                await mx.generate("ruah", {}, user_id="u1", today=date(2026, 11, 9))
        self.assertEqual(ctx.exception.code, "AI_INVALID_OUTPUT")
        insert.assert_not_awaited()


class EditTests(unittest.IsolatedAsyncioTestCase):
    CURRENT = {"id": "o1", "client_id": "ruah", "status": "sugerida", "platform": "instagram", "format": "reels"}

    async def test_edit_marks_edited_and_switching_platform_fixes_format(self):
        update = AsyncMock(return_value=[{"id": "o1"}])
        with patch.object(mx, "_opportunity", AsyncMock(return_value=self.CURRENT)), patch.object(mx, "sb_update", update):
            await mx.update_opportunity("ruah", "o1", {"platform": "tiktok", "title": "Novo", "status": "selecionada"})
        filters, patch_ = update.await_args.kwargs["filters"], update.await_args.kwargs["patch"]
        self.assertEqual(filters["client_id"], "eq.ruah")
        self.assertEqual(filters["status"], "neq.exportada")
        self.assertEqual((patch_["format"], patch_["status"], patch_["edited"]), ("video", "selecionada", True))

    async def test_exported_cannot_be_edited(self):
        with patch.object(mx, "_opportunity", AsyncMock(return_value={**self.CURRENT, "status": "exportada"})):
            with self.assertRaises(StudioError) as ctx:
                await mx.update_opportunity("ruah", "o1", {"title": "x"})
        self.assertEqual(ctx.exception.code, "OPPORTUNITY_EXPORTED")

    async def test_wrong_format_for_platform_is_refused(self):
        with patch.object(mx, "_opportunity", AsyncMock(return_value=self.CURRENT)):
            with self.assertRaises(StudioError) as ctx:
                await mx.update_opportunity("ruah", "o1", {"platform": "tiktok", "format": "carrossel"})
        self.assertEqual(ctx.exception.code, "FORMAT_INVALID")


class ExportTests(unittest.IsolatedAsyncioTestCase):
    def matrix(self, *ops):
        return {"id": "m1", "client_id": "ruah", "week_start": "2026-11-16", "summary": "s", "opportunities": list(ops)}

    def opp(self, oid, **kw):
        base = {"id": oid, "status": "selecionada", "platform": "tiktok", "format": "video", "week": 1, "weekday": 2,
                "title": f"Pauta {oid}", "pillar": "Produto", "hook": None, "caption_draft": "c", "rationale": "r", "angle": None,
                "calendar_item_id": None}
        base.update(kw)
        return base

    async def run_export(self, matrix, *, create=None, existing=None, ids=None):
        create = create or AsyncMock(side_effect=lambda cid, row, **kw: {"id": f"item-{kw['matrix_opportunity_id']}"})
        update = AsyncMock(return_value=[{}])
        with patch.object(mx, "get_matrix", AsyncMock(return_value=matrix)), patch.object(mx, "_posting_times", AsyncMock(return_value={})), \
             patch.object(mx, "create_item", create), patch.object(mx, "_existing_item", existing or AsyncMock(return_value=None)), \
             patch.object(mx, "sb_update", update), patch.object(mx, "_now", lambda: datetime(2026, 11, 9, 12, tzinfo=timezone.utc)):
            out = await mx.export_to_calendar("ruah", "m1", user_id="u1", ids=ids)
        return out, create, update

    async def test_only_selected_become_matrix_drafts_with_platform(self):
        out, create, update = await self.run_export(self.matrix(self.opp("a"), self.opp("b", status="sugerida"), self.opp("c", status="descartada")))
        self.assertEqual((out["created"], out["already"], out["created_ids"]), (1, 0, ["item-a"]))
        args, kw = create.await_args
        self.assertEqual((args[0], kw["origin"], kw["matrix_opportunity_id"]), ("ruah", "matriz", "a"))
        self.assertEqual((args[1]["channel"], args[1]["format"]), ("tiktok", "video"))
        self.assertTrue(args[1]["scheduled_at"].startswith("2026-11-18T"))  # semana 1, quarta
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "exportada")

    async def test_repeating_does_not_duplicate(self):
        out, create, _ = await self.run_export(self.matrix(self.opp("a", status="exportada", calendar_item_id="i1"), self.opp("b")),
                                               ids=["a", "b"], existing=AsyncMock(return_value={"id": "i2"}))
        create.assert_not_awaited()  # "a" já tinha pauta; "b" já existia no Calendário (índice único)
        self.assertEqual((out["created"], out["already"], out["calendar_item_ids"]), (0, 2, ["i1", "i2"]))

    async def test_race_on_unique_index_reuses_existing_item(self):
        conflict = httpx.HTTPStatusError("409", request=httpx.Request("POST", "http://x"), response=httpx.Response(409))
        existing = AsyncMock(side_effect=[None, {"id": "i9"}])
        out, _, _ = await self.run_export(self.matrix(self.opp("a")), create=AsyncMock(side_effect=conflict), existing=existing)
        self.assertEqual((out["created"], out["already"], out["calendar_item_ids"]), (0, 1, ["i9"]))

    async def test_nothing_selected(self):
        with self.assertRaises(StudioError) as ctx:
            await self.run_export(self.matrix(self.opp("a", status="sugerida")))
        self.assertEqual(ctx.exception.code, "MATRIX_NOTHING_SELECTED")

    def test_past_day_moves_to_tomorrow(self):
        when = mx.schedule_for({"week": 1, "weekday": 0}, date(2026, 11, 2), {}, now=datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(when.date(), date(2026, 11, 10))


class CalendarChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_item_keeps_platform_origin_and_link(self):
        insert = AsyncMock(return_value=[{"id": "i1"}])
        with patch.object(cal, "sb_insert_many", insert):
            await cal.create_item("ruah", {"scheduled_at": "2026-11-18T19:00:00-03:00", "format": "video", "title": "t", "channel": "tiktok"},
                                  user_id="u1", origin="matriz", matrix_opportunity_id="o1")
        row = insert.await_args.args[1][0]
        self.assertEqual((row["channel"], row["origin"], row["matrix_opportunity_id"]), ("tiktok", "matriz", "o1"))

    async def test_unknown_platform_is_refused(self):
        with self.assertRaises(StudioError) as ctx:
            await cal.create_item("ruah", {"scheduled_at": "2026-11-18T19:00:00-03:00", "format": "video", "title": "t", "channel": "orkut"}, user_id="u1")
        self.assertEqual(ctx.exception.code, "CHANNEL_INVALID")

    async def test_generate_month_only_replaces_ia_drafts(self):
        # A Matriz exporta com origem "matriz": o "Gerar mês" (que apaga rascunhos com origem "ia") não toca nelas.
        source = Path(cal.__file__).read_text(encoding="utf-8")
        self.assertIn('"origin": "eq.ia", "status": "eq.rascunho"', source)
        self.assertNotIn('"origin": "eq.matriz"', source)

    async def test_other_platforms_are_never_published_automatically(self):
        setter = AsyncMock(return_value=True)
        publish = AsyncMock()
        with patch.object(ig_publish, "_set", setter), patch.object(ig_publish, "publish", publish):
            result = await ig_publish.publish_item({"id": "i1", "client_id": "ruah", "channel": "tiktok", "format": "video"}, creds_cache={})
        self.assertEqual(result, "manual")
        self.assertIn("TikTok", setter.await_args.args[1]["publish_error"])
        publish.assert_not_awaited()

    async def test_schedule_on_other_platform_does_not_check_instagram_art(self):
        row = {"id": "i1", "client_id": "ruah", "status": "aprovado", "channel": "linkedin", "format": "imagem",
               "scheduled_at": "2099-01-01T12:00:00+00:00", "art_url": None}
        with patch.object(cal, "sb_select", AsyncMock(return_value=[row])), patch.object(cal, "sb_update", AsyncMock(return_value=[row])), \
             patch("services.ig_publish.media_for", side_effect=AssertionError("não deveria conferir arte do Instagram")):
            out = await cal.confirm_schedule("ruah", "i1", user_id="u1")
        self.assertEqual(out["id"], "i1")


class OptInModuleTests(unittest.IsolatedAsyncioTestCase):
    def test_social_media_is_not_given_by_total_view_all_or_presets(self):
        total = ta.resolve_codes(status="active", preset="administrador", view_all=True, access_total=True)
        self.assertNotIn("social_media.view", total)
        self.assertNotIn("social_media.view", ta.resolve_codes(status="active", preset="gestor", view_all=True, access_total=False))
        self.assertNotIn("social_media.edit", ta.base_codes("marketing"))
        legacy = ta._legacy_access("client_admin")["codes"]
        self.assertNotIn("social_media.edit", legacy)

    def test_granted_override_counts_even_with_total_access(self):
        codes = ta.resolve_codes(status="active", preset="administrador", view_all=True, access_total=True,
                                 overrides=[("social_media.view", True), ("social_media.edit", True)])
        self.assertTrue({"social_media.view", "social_media.edit"} <= codes)
        self.assertEqual(ta.overrides_for("administrador", True, ta.TOTAL_CODES | {"social_media.view"}), [("social_media.view", True)])

    def test_catalog_flags_opt_in(self):
        flags = {p["code"]: p["opt_in"] for p in ta.catalog_payload()["permissions"]}
        self.assertTrue(flags["social_media.edit"])
        self.assertFalse(flags["calendar.edit"])

    async def test_client_admin_cannot_grant_or_remove_social_media(self):
        actor = {"user_id": "admin", "team": False, "access_total": True, "codes": set(ta.TOTAL_CODES)}
        saved = AsyncMock()
        with patch.object(tadmin, "_target", AsyncMock(return_value={"role": "viewer"})), patch.object(tadmin, "sb_update", AsyncMock()), \
             patch.object(tadmin, "_save_overrides", saved), \
             patch.object(ta, "member_access", AsyncMock(return_value={"codes": {"calendar.view", "social_media.view"}})), \
             redirect_stdout(io.StringIO()):
            out = await tadmin.update_permissions(client_id="ruah", actor=actor, user_id="u2", preset="personalizado", view_all=False,
                                                  access_total=False, codes=["calendar.view", "social_media.edit"])
        self.assertIn("social_media.view", out["codes"])       # o que a Mugô liberou fica
        self.assertNotIn("social_media.edit", out["codes"])    # e o cliente não libera mais nada

    async def test_team_grants_social_media(self):
        actor = {"user_id": "mugo", "team": True, "access_total": True, "codes": set(ta.ALL_CODES)}
        with patch.object(tadmin, "_target", AsyncMock(return_value={"role": "viewer"})), patch.object(tadmin, "sb_update", AsyncMock()), \
             patch.object(tadmin, "_save_overrides", AsyncMock()), redirect_stdout(io.StringIO()):
            out = await tadmin.update_permissions(client_id="ruah", actor=actor, user_id="u2", preset="marketing", view_all=False,
                                                  access_total=False, codes=sorted(ta.base_codes("marketing") | {"social_media.view", "social_media.edit"}))
        self.assertTrue({"social_media.view", "social_media.edit"} <= set(out["codes"]))


if __name__ == "__main__":
    unittest.main()
