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
           "keywords_avoid": ["barato"], "content_language": "pt-BR", "posts_per_week": 1,
           "editorial_platforms": ["instagram", "tiktok"], "posts_per_week_by_platform": {}}


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

    def test_uses_profile_and_ignores_legacy_generation_overrides(self):
        req = mx.normalize_request({"week_start": "2026-11-18", "platforms": ["tiktok", "orkut", "tiktok"], "pillars": ["produto", "x"],
                                    "per_week": 9}, PROFILE, today=date(2026, 11, 9))
        self.assertEqual(req["week_start"], date(2026, 11, 16))
        self.assertEqual(req["platforms"], ["instagram", "tiktok"])
        self.assertEqual(req["pillars"], ["Bastidores", "Produto"])
        self.assertEqual(req["posts_per_week"], 1)

    def test_default_is_next_monday(self):
        self.assertEqual(mx.normalize_request({}, PROFILE, today=date(2026, 11, 9))["week_start"], date(2026, 11, 16))

    def test_requires_editorial_platforms(self):
        with self.assertRaises(StudioError) as ctx:
            mx.normalize_request({}, {**PROFILE, "editorial_platforms": []})
        self.assertEqual(ctx.exception.code, "MATRIX_PLATFORMS_REQUIRED")

    def test_specific_platform_frequency_replaces_global_total(self):
        req = mx.normalize_request({}, {**PROFILE, "posts_per_week": 2,
                                         "posts_per_week_by_platform": {"instagram": 2, "tiktok": 1}})
        self.assertEqual(req["posts_per_week"], 3)
        self.assertEqual(req["platform_quotas"], {"instagram": 2, "tiktok": 1})

    def test_partial_platform_frequency_preserves_global_total(self):
        req = mx.normalize_request({}, {**PROFILE, "posts_per_week": 3,
                                         "posts_per_week_by_platform": {"instagram": 1}})
        self.assertEqual(req["posts_per_week"], 3)
        self.assertEqual(req["platform_quotas"], {"instagram": 1})


class PeriodTests(unittest.TestCase):
    TODAY = date(2026, 11, 11)  # quarta

    def test_default_is_four_weeks_from_next_monday(self):
        req = mx.normalize_request({}, PROFILE, today=self.TODAY)
        self.assertEqual((req["weeks"], req["week_start"]), (4, date(2026, 11, 16)))

    def test_weeks_and_start_snap_to_monday(self):
        req = mx.normalize_request({"weeks": 2, "start": "2026-11-26"}, PROFILE, today=self.TODAY)
        self.assertEqual((req["weeks"], req["week_start"]), (2, date(2026, 11, 23)))

    def test_invalid_period(self):
        for data in ({"weeks": 9}, {"weeks": 0}, {"weeks": "x"}, {"start": "2026-01-01"}, {"start": "ontem"}):
            with self.assertRaises(StudioError) as ctx:
                mx.normalize_request(data, PROFILE, today=self.TODAY)
            self.assertEqual(ctx.exception.code, "MATRIX_PERIOD_INVALID", data)

    def test_briefing_alias_for_focus(self):
        self.assertEqual(mx.normalize_request({"briefing": "Natal"}, PROFILE, today=self.TODAY)["focus"], "Natal")

    def test_deadline_to_weeks(self):
        self.assertEqual(mx.weeks_for_deadline("2026-11-27", self.TODAY), 2)
        self.assertEqual(mx.weeks_for_deadline("2026-11-12", self.TODAY), 1)
        self.assertEqual(mx.weeks_for_deadline("2027-06-01", self.TODAY), 8)
        self.assertIsNone(mx.weeks_for_deadline(None, self.TODAY))

    def test_clean_respects_period(self):
        self.assertIsNotNone(mx.clean_opportunity(op(semana=6), platforms=["instagram"], pillars=["Produto"], weeks=6))
        self.assertIsNone(mx.clean_opportunity(op(semana=3), platforms=["instagram"], pillars=["Produto"], weeks=2))

    def test_prompt_lists_every_week(self):
        req = mx.normalize_request({"weeks": 6}, PROFILE, today=self.TODAY)
        prompt = mx.build_prompt(req, PROFILE, {})
        self.assertIn("6 semanas", prompt)
        self.assertIn("Semana 6", prompt)
        self.assertIn("semana (1 a 6)", prompt)


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

    def test_total_frequency_is_not_multiplied_by_platforms(self):
        items = [mx.clean_opportunity(op(titulo=f"ig{i}"), platforms=self.P, pillars=self.PL) for i in range(3)]
        items += [mx.clean_opportunity(op(plataforma="tiktok", formato="video", titulo=f"tt{i}"), platforms=self.P, pillars=self.PL) for i in range(3)]
        capped = mx.cap_to_plan(items, {"posts_per_week": 3, "platform_quotas": {}})
        self.assertEqual(len(capped), 3)

    def test_specific_frequency_caps_each_platform(self):
        items = [mx.clean_opportunity(op(titulo=f"ig{i}"), platforms=self.P, pillars=self.PL) for i in range(3)]
        items += [mx.clean_opportunity(op(plataforma="tiktok", formato="video", titulo=f"tt{i}"), platforms=self.P, pillars=self.PL) for i in range(3)]
        capped = mx.cap_to_plan(items, {"posts_per_week": 3, "platform_quotas": {"instagram": 2, "tiktok": 1}})
        self.assertEqual([item["platform"] for item in capped], ["instagram", "instagram", "tiktok"])

    def test_partial_frequency_leaves_remaining_slots_for_other_platforms(self):
        items = [mx.clean_opportunity(op(titulo=f"ig{i}"), platforms=self.P, pillars=self.PL) for i in range(3)]
        items += [mx.clean_opportunity(op(plataforma="tiktok", formato="video", titulo=f"tt{i}"), platforms=self.P, pillars=self.PL) for i in range(3)]
        capped = mx.cap_to_plan(items, {"posts_per_week": 3, "platform_quotas": {"instagram": 1}})
        self.assertEqual([item["platform"] for item in capped], ["instagram", "tiktok", "tiktok"])


class GenerateTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_saves_matrix_and_validated_opportunities(self):
        llm = AsyncMock(return_value={"resumo": "Mês de lançamento.", "oportunidades": [
            op(semana=1), op(plataforma="tiktok", formato="video", semana=2), op(semana=3),
            op(plataforma="tiktok", formato="video", semana=4), op(plataforma="linkedin"), "lixo"]})
        insert = AsyncMock(return_value={"id": "m1"})
        many = AsyncMock()
        with patch.object(mx, "load_profile", AsyncMock(return_value={"profile": PROFILE})), \
             patch.object(mx, "build_content_intelligence", AsyncMock(return_value={"marca": {}})), \
             patch.object(mx, "llm_json", llm), patch.object(mx, "sb_insert", insert), patch.object(mx, "sb_insert_many", many), \
             patch.object(mx, "get_matrix", AsyncMock(return_value={"id": "m1", "opportunities": []})), patch.object(mx, "throttle"):
            out = await mx.generate("ruah", {"platforms": ["linkedin"], "per_week": 5}, user_id="u1", today=date(2026, 11, 9))
        self.assertEqual(out["id"], "m1")
        saved = insert.await_args.args[1]
        self.assertEqual(saved["client_id"], "ruah")
        self.assertEqual(saved["week_start"], "2026-11-16")
        self.assertIn("descartada", saved["notes"][0])  # o LinkedIn não foi pedido
        rows = many.await_args.args[1]
        self.assertEqual([(r["platform"], r["week"]) for r in rows], [("instagram", 1), ("tiktok", 2), ("instagram", 3), ("tiktok", 4)])
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


class PartialGenerateTests(unittest.IsolatedAsyncioTestCase):
    def patches(self, llm, insert, many):
        return [patch.object(mx, "load_profile", AsyncMock(return_value={"profile": PROFILE})),
                patch.object(mx, "build_content_intelligence", AsyncMock(return_value={})), patch.object(mx, "throttle"),
                patch.object(mx, "llm_json", llm), patch.object(mx, "sb_insert", insert), patch.object(mx, "sb_insert_many", many),
                patch.object(mx, "get_matrix", AsyncMock(return_value={"id": "m1", "opportunities": []}))]

    async def run_generate(self, llm):
        from contextlib import ExitStack
        insert, many = AsyncMock(return_value={"id": "m1"}), AsyncMock()
        with ExitStack() as stack:
            for p in self.patches(llm, insert, many):
                stack.enter_context(p)
            await mx.generate("ruah", {}, user_id="u1", today=date(2026, 11, 9))
        return insert.await_args.args[1], many.await_args.args[1]

    async def test_short_answer_retries_once_and_keeps_the_better_one(self):
        llm = AsyncMock(side_effect=[{"oportunidades": [op(semana=1)]}, {"oportunidades": [op(semana=1), op(semana=2)]}])
        saved, rows = await self.run_generate(llm)
        self.assertEqual(llm.await_count, 2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("Complete à mão" in n for n in saved["notes"]))

    async def test_partial_matrix_is_saved_instead_of_refused(self):
        llm = AsyncMock(return_value={"oportunidades": [op(semana=1), op(semana=3)]})
        saved, rows = await self.run_generate(llm)
        self.assertEqual([r["week"] for r in rows], [1, 3])
        self.assertIn("de", saved["notes"][0])


class CreateContentTests(unittest.IsolatedAsyncioTestCase):
    CURRENT = {"id": "o1", "client_id": "ruah", "status": "sugerida", "platform": "instagram", "format": "carrossel",
               "pillar": "Produto", "title": "Como escolher o perfume certo", "hook": None}

    async def test_ai_writes_caption_script_and_image_idea(self):
        llm = AsyncMock(return_value={"gancho": "Você erra o perfume?", "legenda": "Legenda com CTA", "roteiro": "Slide 1: capa",
                                      "ideia_imagem": "Frasco em fundo neutro"})
        update = AsyncMock(return_value=[{**self.CURRENT, "script": "Slide 1: capa"}])
        with patch.object(mx, "_opportunity", AsyncMock(return_value=self.CURRENT)), patch.object(mx, "throttle"), \
             patch.object(mx, "load_profile", AsyncMock(return_value={"profile": PROFILE})), \
             patch.object(mx, "build_content_intelligence", AsyncMock(return_value={})), patch.object(mx, "llm_json", llm), \
             patch.object(mx, "sb_update", update):
            await mx.create_content("ruah", "o1", instruction="tom leve")
        saved = update.await_args.kwargs["patch"]
        self.assertEqual((saved["script"], saved["visual_idea"], saved["caption_draft"]), ("Slide 1: capa", "Frasco em fundo neutro", "Legenda com CTA"))
        self.assertIn("slide", llm.await_args.kwargs["prompt"].lower())  # roteiro no formato do carrossel
        self.assertIn("tom leve", llm.await_args.kwargs["prompt"])
        self.assertEqual(update.await_args.kwargs["filters"]["status"], "neq.exportada")

    async def test_exported_cannot_be_recreated(self):
        with patch.object(mx, "_opportunity", AsyncMock(return_value={**self.CURRENT, "status": "exportada"})):
            with self.assertRaises(StudioError) as raised:
                await mx.create_content("ruah", "o1")
        self.assertEqual(raised.exception.code, "OPPORTUNITY_EXPORTED")

    def test_calendar_row_carries_script_and_image_idea(self):
        row = mx._calendar_row({**self.CURRENT, "script": "S", "visual_idea": "V", "caption_draft": "C", "rationale": None, "angle": None},
                               datetime(2026, 11, 18, 19, tzinfo=timezone.utc), None)
        self.assertEqual((row["script"], row["visual_idea"]), ("S", "V"))


class RetitleExportedTests(unittest.IsolatedAsyncioTestCase):
    async def test_title_of_exported_changes_here_and_in_calendar(self):
        current = {"id": "o1", "client_id": "ruah", "status": "exportada", "calendar_item_id": "i1", "title": "Velho"}
        update = AsyncMock(return_value=[{**current, "title": "Novo"}])
        with patch.object(mx, "_opportunity", AsyncMock(return_value=current)), patch.object(mx, "sb_update", update):
            out = await mx.update_opportunity("ruah", "o1", {"title": "Novo"})
        self.assertEqual(out["title"], "Novo")
        tables = [c.args[0] for c in update.await_args_list]
        self.assertEqual(tables, [mx.OPPORTUNITIES, mx.ITEMS])
        self.assertEqual(update.await_args_list[1].kwargs["filters"], {"client_id": "eq.ruah", "id": "eq.i1"})

    async def test_other_fields_of_exported_stay_locked(self):
        with patch.object(mx, "_opportunity", AsyncMock(return_value={"id": "o1", "status": "exportada"})):
            with self.assertRaises(StudioError):
                await mx.update_opportunity("ruah", "o1", {"title": "Novo", "format": "reels"})


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

    async def test_exported_cannot_be_edited_beyond_the_text(self):
        with patch.object(mx, "_opportunity", AsyncMock(return_value={**self.CURRENT, "status": "exportada"})):
            with self.assertRaises(StudioError) as ctx:
                await mx.update_opportunity("ruah", "o1", {"hook": "x"})
        self.assertEqual(ctx.exception.code, "OPPORTUNITY_EXPORTED")

    async def test_wrong_format_for_platform_is_refused(self):
        with patch.object(mx, "_opportunity", AsyncMock(return_value=self.CURRENT)):
            with self.assertRaises(StudioError) as ctx:
                await mx.update_opportunity("ruah", "o1", {"platform": "tiktok", "format": "carrossel"})
        self.assertEqual(ctx.exception.code, "FORMAT_INVALID")

    async def test_add_and_delete_use_tenant_and_preserve_exported(self):
        matrix = {"id": "m1", "status": "ativa", "platforms": ["instagram"], "pillars": [{"name": "Produto"}],
                  "opportunities": [{"position": 2}]}
        insert = AsyncMock(return_value={"id": "o2"})
        delete = AsyncMock(return_value=[{"id": "o2"}])
        payload = {"platform": "instagram", "pillar": "Produto", "week": 2, "weekday": 3, "format": "imagem", "title": "Nova"}
        with patch.object(mx, "get_matrix", AsyncMock(return_value=matrix)), patch.object(mx, "sb_insert", insert):
            await mx.create_opportunity("ruah", "m1", payload)
        self.assertEqual((insert.await_args.args[1]["client_id"], insert.await_args.args[1]["position"]), ("ruah", 3))
        with patch.object(mx, "_opportunity", AsyncMock(return_value={"id": "o2", "matrix_id": "m1", "status": "sugerida"})), patch.object(mx, "sb_delete", delete):
            await mx.delete_opportunity("ruah", "m1", "o2")
        self.assertEqual(delete.await_args.kwargs["filters"]["client_id"], "eq.ruah")
        with patch.object(mx, "_opportunity", AsyncMock(return_value={"id": "o3", "matrix_id": "m1", "status": "exportada", "calendar_item_id": "i1"})), patch.object(mx, "sb_delete", delete):
            with self.assertRaises(StudioError) as ctx:
                await mx.delete_opportunity("ruah", "m1", "o3")
        self.assertEqual(ctx.exception.code, "OPPORTUNITY_EXPORTED")

    async def test_delete_refuses_opportunity_from_another_matrix(self):
        delete = AsyncMock()
        with patch.object(mx, "_opportunity", AsyncMock(return_value={"id": "o2", "matrix_id": "other", "status": "sugerida"})), \
             patch.object(mx, "sb_delete", delete):
            with self.assertRaises(StudioError) as ctx:
                await mx.delete_opportunity("ruah", "m1", "o2")
        self.assertEqual(ctx.exception.code, "OPPORTUNITY_NOT_FOUND")
        delete.assert_not_awaited()


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

    async def test_pinterest_is_planned_but_never_published_automatically(self):
        setter = AsyncMock(return_value=True)
        publish = AsyncMock()
        with patch.object(ig_publish, "_set", setter), patch.object(ig_publish, "publish", publish):
            result = await ig_publish.publish_item({"id": "i1", "client_id": "ruah", "channel": "pinterest", "format": "imagem"}, creds_cache={})
        self.assertEqual(result, "manual")
        self.assertIn("Pinterest", setter.await_args.args[1]["publish_error"])
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
