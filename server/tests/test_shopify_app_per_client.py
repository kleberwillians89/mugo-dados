"""Um app Shopify por loja: conexão, callback e webhooks usam o app da loja; sem cadastro, o app padrão (Roove)."""
import base64
import hashlib
import hmac
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "teste-chave-para-criptografia-local-123456")

from services import shopify_app_credentials as cred  # noqa: E402
from services import shopify_oauth  # noqa: E402
from services import shopify_webhooks  # noqa: E402

ENV = {"SHOPIFY_CLIENT_ID": "roove-app-id-000", "SHOPIFY_CLIENT_SECRET": "roove-secret-0000000000",
       "SHOPIFY_OAUTH_REDIRECT_URI": "https://api.dados.mugoagencia.com.br/api/oauth/shopify/callback",
       "SHOPIFY_APP_SECRET": "roove-secret-0000000000"}


class Store:
    def __init__(self):
        self.rows = {}

    async def select(self, table, select=None, filters=None, limit=None, **_):
        shop = (filters or {}).get("shop_domain", "")[3:]
        if shop:
            return [self.rows[shop]] if shop in self.rows else []
        cid = (filters or {}).get("client_id", "")[3:]
        return [r for r in self.rows.values() if r["client_id"] == cid]

    async def upsert(self, table, rows, on_conflict):
        for r in rows:
            self.rows[r["shop_domain"]] = r


class PerShopAppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cred.clear_cache()
        self.store = Store()
        self.patches = [patch.object(cred, "sb_select", self.store.select), patch.object(cred, "sb_upsert", self.store.upsert),
                        patch.dict(os.environ, ENV)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    async def save_ruah(self):
        return await cred.save("ruah", shop_domain="ruah-parfums", app_client_id="ruah-app-client-123456",
                               client_secret="shpss_ruahsegredo1234567890", actor_id="u1")

    async def test_secret_is_encrypted_and_never_returned(self):
        out = await self.save_ruah()
        row = self.store.rows["ruah-parfums.myshopify.com"]
        self.assertNotIn("shpss_ruah", row["client_secret_encrypted"])
        self.assertEqual(out, {"apps": [{"shop_domain": "ruah-parfums.myshopify.com", "client_id_hint": "...123456", "updated_at": None}]})
        self.assertNotIn("shpss", str(out))

    async def test_oauth_uses_the_shop_app_and_falls_back_to_default(self):
        await self.save_ruah()
        own = await shopify_oauth.settings_for_shop("ruah-parfums.myshopify.com")
        self.assertEqual((own["client_id"], own["client_secret"]), ("ruah-app-client-123456", "shpss_ruahsegredo1234567890"))
        default = await shopify_oauth.settings_for_shop("roove.myshopify.com")
        self.assertEqual(default["client_id"], "roove-app-id-000")
        with patch.object(shopify_oauth, "create_oauth_state", AsyncMock(return_value="st")):
            url = await shopify_oauth.authorization_url(user_id="u", client_id="ruah", shop_domain="ruah-parfums")
        self.assertIn("client_id=ruah-app-client-123456", url)

    async def test_callback_and_webhook_signatures_use_the_shop_secret(self):
        await self.save_ruah()
        secret = (await shopify_oauth.settings_for_shop("ruah-parfums.myshopify.com"))["client_secret"]
        params = {"shop": "ruah-parfums.myshopify.com", "code": "c", "state": "s", "timestamp": "1"}
        msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        params["hmac"] = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(shopify_oauth.verify_callback_hmac(params, secret))
        self.assertFalse(shopify_oauth.verify_callback_hmac(params))  # o segredo padrão não serve
        body = b'{"id":1}'
        sig = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        self.assertTrue(shopify_webhooks.validate_shopify_hmac(body, sig, secret)[0])
        self.assertFalse(shopify_webhooks.validate_shopify_hmac(body, sig)[0])

    async def test_a_shop_cannot_be_taken_by_another_company_and_inputs_are_checked(self):
        await self.save_ruah()
        with self.assertRaises(cred.CredentialError):
            await cred.save("roove", shop_domain="ruah-parfums.myshopify.com", app_client_id="outro-app-123456",
                            client_secret="shpss_outrosegredo123456789", actor_id="u2")
        with self.assertRaises(cred.CredentialError):
            await cred.save("ruah", shop_domain="https://ruah.com.br", app_client_id="x" * 10, client_secret="y" * 20, actor_id="u")
        with self.assertRaises(cred.CredentialError):
            await cred.save("ruah", shop_domain="ruah-parfums", app_client_id="ok-client-123", client_secret="curto", actor_id="u")

    async def test_missing_table_means_default_app(self):
        cred.clear_cache()
        with patch.object(cred, "sb_select", AsyncMock(side_effect=RuntimeError("relation does not exist"))):
            self.assertIsNone(await cred.for_shop("ruah-parfums.myshopify.com"))
            self.assertEqual((await shopify_oauth.settings_for_shop("ruah-parfums.myshopify.com"))["client_id"], "roove-app-id-000")


if __name__ == "__main__":
    unittest.main()
