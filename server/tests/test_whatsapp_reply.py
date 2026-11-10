"""Equipe responde o WhatsApp pelo MUGOVERSO: ponte do CRM da marca, número nativo e erros claros."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services import whatsapp_native as wn
from services import whatsapp_sources as ws
from services.studio_calendar import StudioError

CONV = "11111111-2222-3333-4444-555555555555"


def fake_client(status: int, body: dict):
    resp = MagicMock(status_code=status, content=b"x")
    resp.json.return_value = body
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


class BridgeReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_posts_reply_with_secret(self):
        ctx, client = fake_client(200, {"ok": True, "data": {"status": "sent", "ai_paused_minutes": 240}})
        with patch.object(ws, "bridge_for", return_value={"url": "https://crm/functions/v1/mugoverso-bridge", "key": "k"}), \
             patch.object(ws.httpx, "AsyncClient", return_value=ctx):
            out = await ws.brand_reply("ruah", CONV, " Temos sim ", author="equipe Mugô")
        self.assertEqual(out["status"], "sent")
        kwargs = client.post.await_args.kwargs
        self.assertEqual(kwargs["params"], {"endpoint": "reply"})
        self.assertEqual(kwargs["headers"], {"X-Mugoverso-Key": "k"})
        self.assertEqual(kwargs["json"], {"conversation_id": CONV, "text": "Temos sim", "author": "equipe Mugô"})

    async def test_bridge_errors_are_translated(self):
        for status, body, code in ((422, {"ok": False, "code": "OUTSIDE_REPLY_WINDOW", "message": "24 h"}, "OUTSIDE_WINDOW"),
                                   (405, {"ok": False, "code": "METHOD_NOT_ALLOWED"}, "REPLY_UNSUPPORTED"),
                                   (404, {"ok": False, "code": "CONVERSATION_NOT_FOUND"}, "CONVERSATION_NOT_FOUND"),
                                   (502, {"ok": False, "code": "SEND_FAILED", "message": "x"}, "SEND_FAILED")):
            ctx, _ = fake_client(status, body)
            with patch.object(ws, "bridge_for", return_value={"url": "https://crm", "key": "k"}), patch.object(ws.httpx, "AsyncClient", return_value=ctx):
                with self.assertRaises(StudioError) as err:
                    await ws.brand_reply("ruah", CONV, "oi", author="x")
            self.assertEqual(err.exception.code, code)

    async def test_crm_mugo_number_is_not_answered_here(self):
        with patch.object(ws, "bridge_for", return_value=None), patch.object(ws.whatsapp_native, "active_number_ids", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError) as err:
                await ws.brand_reply("mugo", CONV, "oi", author="x")
        self.assertEqual(err.exception.code, "REPLY_UNSUPPORTED")


class NativeReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_inside_window_and_records(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        async def select(table, **kw):
            if table == "whatsapp_threads":
                return [{"id": CONV, "number_id": "n1", "wa_id": "5511999990000", "last_inbound_at": recent}]
            return [{"id": "n1", "phone_number_id": "123456", "access_token": "t" * 30, "status": "active"}]
        graph, upsert, update = AsyncMock(return_value={"messages": [{"id": "wamid.X"}]}), AsyncMock(), AsyncMock()
        with patch.object(wn, "sb_select", side_effect=select), patch.object(wn, "_graph", graph), \
             patch.object(wn, "sb_upsert", upsert), patch.object(wn, "sb_update", update):
            out = await wn.send_text("cli", CONV, "Oi!")
        self.assertEqual(out["status"], "sent")
        self.assertEqual(graph.await_args.args[1], "123456/messages")
        self.assertEqual(graph.await_args.kwargs["json_body"]["to"], "5511999990000")
        row = upsert.await_args.args[1][0]
        self.assertEqual((row["provider_message_id"], row["direction"], row["text"]), ("wamid.X", "out", "Oi!"))

    async def test_outside_window_blocked_before_meta(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        graph = AsyncMock()
        with patch.object(wn, "sb_select", AsyncMock(return_value=[{"id": CONV, "number_id": "n1", "wa_id": "55", "last_inbound_at": old}])), \
             patch.object(wn, "_graph", graph):
            with self.assertRaises(wn.WhatsAppNativeError) as err:
                await wn.send_text("cli", CONV, "oi")
        self.assertEqual(err.exception.code, "OUTSIDE_WINDOW")
        graph.assert_not_awaited()
