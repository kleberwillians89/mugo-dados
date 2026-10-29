from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_approvals as sa
from services.studio_calendar import StudioError

I1, I2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
TOKEN = "a" * 43


def request_row(**kw):
    return {"id": "req", "client_id": "roove", "month": "2026-11-01", "item_ids": [I1, I2], "contact_name": "Ana Souza",
            "status": "aberto", "expires_at": FUTURE, **kw}


class HelpersTests(unittest.TestCase):
    def test_phone_normalization(self):
        self.assertEqual(sa.normalize_phone("(11) 98888-7777"), "5511988887777")
        self.assertEqual(sa.normalize_phone("+55 11 98888-7777"), "5511988887777")
        self.assertIsNone(sa.normalize_phone(""))
        with self.assertRaises(StudioError):
            sa.normalize_phone("123")

    def test_whatsapp_message_and_url(self):
        text = sa.whatsapp_text(client_name="Roove", contact_name="Ana Souza", month_label="novembro", count=8,
                                link="https://x/aprovar/t", message=None)
        self.assertTrue(text.startswith("Oi, Ana!"))
        self.assertIn("8 pauta(s) de novembro da Roove", text)
        self.assertTrue(sa.whatsapp_url("5511988887777", text).startswith("https://wa.me/5511988887777?text=Oi%2C%20Ana"))


class CreateRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_hash_is_stored_and_items_must_belong_to_client(self):
        items = [{"id": I1, "status": "rascunho"}, {"id": I2, "status": "aprovado"}]
        with patch.object(sa, "sb_select", AsyncMock(side_effect=[items, [{"name": "Roove"}]])), \
             patch.object(sa, "sb_insert", AsyncMock(return_value={"id": "req", "contact_name": "Ana"})) as insert, \
             patch.object(sa, "sb_update", AsyncMock()) as update:
            result = await sa.create_request("roove", month="2026-11", item_ids=[I2, I1], contact_name="Ana",
                                             contact_phone="11988887777", message=None, user_id="u", app_origin="https://dados.example/")
        row = insert.await_args.args[1]
        token = result["link"].rsplit("/", 1)[1]
        self.assertEqual(row["token_hash"], sa.hash_token(token))
        self.assertNotIn(token, str(row))
        self.assertTrue(result["link"].startswith("https://dados.example/aprovar/"))
        self.assertEqual(update.await_args.kwargs["filters"]["id"], f"in.({I1})")  # aprovada não volta para revisão
        self.assertEqual(update.await_args.kwargs["patch"], {"status": "em_revisao"})

    async def test_foreign_or_rejected_items_are_refused(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[{"id": I1, "status": "rejeitado"}])), \
             patch.object(sa, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(StudioError) as err:
                await sa.create_request("roove", month="2026-11", item_ids=[I1, I2], contact_name=None,
                                        contact_phone=None, message=None, user_id="u", app_origin="https://x")
        self.assertEqual(err.exception.code, "ITEMS_INVALID")
        insert.assert_not_awaited()


class PublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_expired_or_cancelled_links_look_the_same(self):
        for rows in ([], [request_row(status="cancelado")], [request_row(expires_at=PAST)]):
            with patch.object(sa, "sb_select", AsyncMock(return_value=rows)):
                with self.assertRaises(StudioError) as err:
                    await sa.public_view(TOKEN)
            self.assertEqual(err.exception.code, "LINK_UNAVAILABLE")
        with self.assertRaises(StudioError):
            await sa.public_view("curto")

    async def test_view_returns_only_editorial_fields(self):
        item = {"id": I1, "scheduled_at": "2026-11-03T22:00:00+00:00", "format": "reels", "pillar": "P", "title": "T",
                "hook": "H", "caption_draft": "C", "status": "em_revisao"}
        reads = AsyncMock(side_effect=[[request_row()], [item], [{"item_id": I1, "action": "aprovado", "comment": None}], [{"name": "Roove"}]])
        art = [{"id": "a1", "kind": "imagem", "url": "https://sb/signed"}]
        attach = AsyncMock(side_effect=lambda cid, items, public: [{**i, "assets": art} for i in items])
        with patch.object(sa, "sb_select", reads), patch.object(sa, "attach_assets", attach):
            view = await sa.public_view(TOKEN)
        self.assertEqual(reads.await_args_list[0].kwargs["filters"], {"token_hash": f"eq.{sa.hash_token(TOKEN)}"})
        self.assertEqual(reads.await_args_list[1].kwargs["filters"]["client_id"], "eq.roove")
        self.assertEqual(attach.await_args.args[0], "roove")
        self.assertTrue(attach.await_args.kwargs["public"])  # arte com campos mínimos e URL assinada curta
        self.assertEqual(set(view["items"][0]), {"id", "scheduled_at", "format", "pillar", "title", "hook", "caption_draft", "assets", "decision", "comment"})
        self.assertEqual(view["items"][0]["assets"], art)
        self.assertEqual(view["items"][0]["decision"], "aprovado")
        self.assertEqual(view["client_name"], "Roove")

    async def test_decision_updates_item_and_closes_request_when_all_decided(self):
        reads = AsyncMock(side_effect=[[request_row()], [{"item_id": I1}, {"item_id": I2}]])
        with patch.object(sa, "sb_select", reads), patch.object(sa, "sb_insert", AsyncMock()) as insert, \
             patch.object(sa, "sb_update", AsyncMock()) as update:
            await sa.public_decide(TOKEN, I2, action="ajuste_solicitado", comment="Trocar a foto", reviewer_name=None)
        self.assertEqual(insert.await_args.args[1]["reviewer_name"], "Ana Souza")
        item_patch = update.await_args_list[0].kwargs
        self.assertEqual(item_patch["filters"], {"client_id": "eq.roove", "id": f"eq.{I2}"})
        self.assertEqual(item_patch["patch"]["status"], "rejeitado")
        self.assertEqual(item_patch["patch"]["review_note"], "Cliente (Ana Souza): Trocar a foto")
        self.assertEqual(update.await_args_list[1].kwargs["patch"]["status"], "concluido")

    async def test_cannot_decide_item_outside_request_or_adjust_without_comment(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[request_row()])), patch.object(sa, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(StudioError) as err:
                await sa.public_decide(TOKEN, "33333333-3333-3333-3333-333333333333", action="aprovado", comment=None, reviewer_name=None)
            self.assertEqual(err.exception.code, "LINK_UNAVAILABLE")
            with self.assertRaises(StudioError) as err:
                await sa.public_decide(TOKEN, I1, action="ajuste_solicitado", comment="  ", reviewer_name=None)
            self.assertEqual(err.exception.code, "COMMENT_REQUIRED")
        insert.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
