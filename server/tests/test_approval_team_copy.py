import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import automations as au
from services import studio_messages as sm
from services.studio_calendar import StudioError


class TeamCopyTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_message_and_link_for_each_team_member(self):
        team = [{"name": "Kleber Willians", "phone": "5511911110000"}, {"name": "Julia", "phone": "5511922220000"}]
        params = AsyncMock(side_effect=lambda cid, kind, rid, contact, brand: ({"_template": "mugo_conteudo_aprovacao", "nome": contact["name"].split()[0],
                                                                              "quantidade": "3", "mes": "novembro", "marca": brand, "validade": "17/11"},
                                                                             {"button_suffix": "tok123"}))
        deliver = AsyncMock(side_effect=[{"status": "enviado", "provider_message_id": "wamid.K"}, StudioError("RECIPIENT_NOT_IN_CRM")])
        with patch.object(sm, "sb_select", AsyncMock(return_value=team)), patch.object(sm, "_client_name", AsyncMock(return_value="Origami")), \
             patch.object(sm, "_approval_params", params), patch.object(sm, "deliver", deliver):
            out = await sm.send_approval_to_team("origami", "req1", user_id="u1")
        self.assertEqual([o["status"] for o in out], ["enviado", "falhou"])
        first = deliver.await_args_list[0].kwargs
        self.assertEqual((first["button_suffix"], first["request_id"], first["params"]["nome"]), ("tok123", "req1", "Kleber"))
        keys = {c.kwargs["key"] for c in deliver.await_args_list}
        self.assertEqual(len(keys), 2)  # uma chave por pessoa: reenvio não duplica

    async def test_no_team_table_means_no_copy(self):
        with patch.object(sm, "sb_select", AsyncMock(side_effect=Exception("relation does not exist"))):
            self.assertEqual(await sm.send_approval_to_team("origami", "req1", user_id="u1"), [])


class StudioDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_reaches_studio_messages_when_not_in_outbox(self):
        async def select(table, **kwargs):
            return [] if table == au.OUTBOX else [{"id": "m1", "delivery_status": "sent"}]
        update = AsyncMock()
        with patch.object(au, "sb_select", AsyncMock(side_effect=select)), patch.object(au, "sb_update", update):
            out = await au.apply_status("wamid.K", "read")
        self.assertEqual((out["table"], update.await_args.kwargs["patch"]["delivery_status"]), ("studio_messages", "read"))


if __name__ == "__main__":
    unittest.main()
