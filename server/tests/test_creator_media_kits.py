"""Mídia kit e valores por criador, isolados por empresa."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import creators as route
from services import creator_media_kits as kits

CREATOR = "0b6f2c1e-6a43-4b7e-9d1a-3f0f0c9d2a11"


class CleanTests(unittest.TestCase):
    def test_prices_keep_only_valid_rows(self):
        out = kits.clean_prices([{"deliverable": " Reels ", "amount": "1500.555"}, {"deliverable": "", "amount": 10},
                                 {"deliverable": "Stories", "amount": -5, "notes": "3 telas"}, "lixo"])
        self.assertEqual(out, [{"deliverable": "Reels", "amount": 1500.56, "notes": None}, {"deliverable": "Stories", "amount": None, "notes": "3 telas"}])

    def test_files_only_https(self):
        out = kits.clean_files([{"url": "https://x.supabase.co/a.pdf", "name": "Kit"}, {"url": "http://x/b.pdf"}, {"url": "javascript:alert(1)"}])
        self.assertEqual([f["url"] for f in out], ["https://x.supabase.co/a.pdf"])


    def test_email_and_phone(self):
        self.assertEqual(kits.clean_email(" Ana@Agencia.com "), "ana@agencia.com")
        self.assertIsNone(kits.clean_email(""))
        with self.assertRaises(kits.StudioError):
            kits.clean_email("ana-agencia.com")
        self.assertEqual(kits.clean_phone("+55 11 99999-0000"), "+55 11 99999-0000")
        with self.assertRaises(kits.StudioError):
            kits.clean_phone("123")

    def test_deals_keep_history_with_date_and_what(self):
        out = kits.clean_deals([{"closed_at": "2026-11-24", "what": "1 Reels Black Friday", "amount": "1800", "closed_by": "Kleber"},
                                {"closed_at": "24/11/2026", "what": "x"}, {"closed_at": "2026-11-20", "what": ""}])
        self.assertEqual(len(out), 1)
        self.assertEqual({k: out[0][k] for k in ("closed_at", "what", "amount", "closed_by")},
                         {"closed_at": "2026-11-24", "what": "1 Reels Black Friday", "amount": 1800.0, "closed_by": "Kleber"})
        self.assertTrue(out[0]["id"])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_is_scoped_by_client_and_visible_creators(self):
        select = AsyncMock(return_value=[{"creator_id": CREATOR}, {"creator_id": "outro"}])
        with patch.object(kits, "sb_select", select):
            rows = await kits.list_kits("ruah", {CREATOR})
        self.assertEqual(rows, [{"creator_id": CREATOR}])
        self.assertEqual(select.await_args.kwargs["filters"], {"client_id": "eq.ruah"})

    async def test_save_upserts_one_row_per_client_and_creator(self):
        upsert = AsyncMock(return_value={"ok": True})
        with patch.object(kits, "sb_upsert", upsert), patch.object(kits, "sb_select", AsyncMock(return_value=[])):
            row = await kits.save_kit("ruah", CREATOR, {"prices": [{"deliverable": "Reels", "amount": 2000}], "contact": " @agencia ",
                                                     "email": "ana@x.com", "phone": "11 99999-0000", "deals": [{"closed_at": "2026-11-24", "what": "Reels", "amount": 2000}]}, user_id="u")
        self.assertEqual(upsert.await_args.kwargs["on_conflict"], "client_id,creator_id")
        self.assertEqual(row["client_id"], "ruah")
        self.assertEqual(row["contact"], "@agencia")
        self.assertEqual((row["email"], row["phone"], row["deals"][0]["what"]), ("ana@x.com", "11 99999-0000", "Reels"))
        self.assertEqual(row["status"], "fechado")  # com fechamento e sem status escolhido: fechado
        self.assertEqual(row["prices"], [{"deliverable": "Reels", "amount": 2000.0, "notes": None}])

    async def test_status_date_only_changes_when_status_changes(self):
        same = AsyncMock(return_value=[{"status": "contatado", "status_at": "2026-11-20T10:00:00+00:00"}])
        with patch.object(kits, "sb_upsert", AsyncMock()), patch.object(kits, "sb_select", same):
            row = await kits.save_kit("ruah", CREATOR, {"status": "contatado", "notes": "x"}, user_id="u")
        self.assertEqual(row["status_at"], "2026-11-20T10:00:00+00:00")
        with patch.object(kits, "sb_upsert", AsyncMock()), patch.object(kits, "sb_select", same):
            row = await kits.save_kit("ruah", CREATOR, {"status": "nao_fechou", "status_note": "Fora do orçamento"}, user_id="u")
        self.assertNotEqual(row["status_at"], "2026-11-20T10:00:00+00:00")
        self.assertEqual((row["status"], row["status_note"]), ("nao_fechou", "Fora do orçamento"))
        self.assertEqual(same.await_args.kwargs["filters"], {"client_id": "eq.ruah", "creator_id": f"eq.{CREATOR}"})

    def test_invalid_status(self):
        with self.assertRaises(kits.StudioError):
            kits.clean_status("ganhou", [])
        self.assertEqual(kits.clean_status(None, []), "novo")

    async def test_upload_rejects_other_types(self):
        with self.assertRaises(kits.StudioError):
            await kits.upload_target("ruah", "application/zip")


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_cannot_save_kit_for_creator_outside_company(self):
        with patch.object(route, "actor", AsyncMock(return_value=("ruah", set()))), \
             patch.object(route.creators, "get_creator", AsyncMock(return_value=None)), \
             patch.object(route.kits, "save_kit", AsyncMock()) as save:
            with self.assertRaises(HTTPException) as ctx:
                await route.save_media_kit("ruah", CREATOR, route.MediaKitInput(), authorization="Bearer x")
        self.assertEqual(ctx.exception.status_code, 404)
        save.assert_not_awaited()

    async def test_save_links_creator_to_company(self):
        body = route.MediaKitInput(prices=[route.PriceInput(deliverable="Reels", amount=1500)])
        with patch.object(route, "actor", AsyncMock(return_value=("ruah", None))), \
             patch.object(route.creators, "get_creator", AsyncMock(return_value={"id": CREATOR})), \
             patch.object(route, "require_user_id", AsyncMock(return_value="u")), \
             patch.object(route.kits, "save_kit", AsyncMock(return_value={"creator_id": CREATOR})) as save, \
             patch.object(route.creators, "link_creators", AsyncMock()) as link:
            await route.save_media_kit("ruah", CREATOR, body, authorization="Bearer x")
        self.assertEqual(save.await_args.args[:2], ("ruah", CREATOR))
        link.assert_awaited_once_with("ruah", [CREATOR])

    def test_media_kits_route_comes_before_creator_id(self):
        paths = [r.path for r in route.router.routes if "GET" in getattr(r, "methods", set())]
        self.assertLess(paths.index("/api/clients/{client_id}/creators/media-kits"), paths.index("/api/clients/{client_id}/creators/{creator_id}"))


if __name__ == "__main__":
    unittest.main()
