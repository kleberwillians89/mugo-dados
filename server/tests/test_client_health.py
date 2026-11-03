import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import client_health as ch

DATA = {
    "clients": [{"id": "roove", "name": "Roove"}, {"id": "cura", "name": "Curavino"}],
    "studio_brand_profiles": [{"client_id": "roove", "profile": {"tone_of_voice": "leve", "audience": "mulheres 30+", "pillars": [{"name": "x"}], "keywords_use": ["skin"]}}],
    "client_business_context": [{"client_id": "roove", "segment": "moda", "product_description": "skinwear", "positioning": "premium"}],
    "meta_connections": [{"client_id": "roove", "platform": "instagram", "status": "active", "scopes_json": ["instagram_basic", "instagram_manage_comments"]}],
    "studio_client_contacts": [{"client_id": "roove", "receives": ["conteudo"], "email": None, "active": True}],
    "studio_messages": [{"client_id": "roove", "status": "enviado", "delivery_status": "read"},
                        {"client_id": "roove", "status": "falhou", "error_code": "RECIPIENT_NOT_IN_CRM"}],
    "ig_engagement_settings": [],
}


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_checks_and_whatsapp(self):
        async def select(table, **kwargs):
            if table == "ig_engagement_settings":
                raise Exception("relation does not exist")  # migração não aplicada não derruba a tela
            return DATA.get(table, [])
        with patch.object(ch, "sb_select", AsyncMock(side_effect=select)):
            out = await ch.overview()
        names = [c["name"] for c in out["clients"]]
        self.assertEqual(names[0], "Curavino")  # pior nota primeiro
        roove = next(c for c in out["clients"] if c["client_id"] == "roove")
        status = {c["label"].split(" (")[0]: c["ok"] for c in roove["checks"]}
        self.assertTrue(status["Perfil da marca"] and status["Contexto de negócio"] and status["Instagram conectado"])
        self.assertFalse(status["Permissão de publicar"])
        self.assertFalse(status["E-mail dos contatos"])
        self.assertEqual(roove["whatsapp"], {"sent": 1, "failed": 1, "read": 1, "errors": [("RECIPIENT_NOT_IN_CRM", 1)]})
        self.assertFalse(roove["ai_comments"])


if __name__ == "__main__":
    unittest.main()
