"""Audience source regression: landing lead opt-ins remain distinct from send authorization."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import whatsapp_campaign_drafts as campaigns


class WhatsAppCapturedSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_captured_leads_are_previewed_for_selected_tenant_only(self):
        rows = [
            {"client_id": "roove", "phone_hash": "h1", "email_hash": "e1",
             "consent_whatsapp_claimed": True, "consent_verified": False},
            {"client_id": "roove", "phone_hash": "h2", "email_hash": "e2",
             "consent_whatsapp_claimed": False, "consent_verified": False},
            {"client_id": "roove", "phone_hash": "h1", "email_hash": "e1",
             "consent_whatsapp_claimed": True, "consent_verified": False},
        ]
        with patch.object(campaigns, "sb_select", new_callable=AsyncMock, return_value=rows) as lookup:
            summary = await campaigns.audience_preview("roove", "capture")
        self.assertEqual(summary["total_contacts"], 2)
        self.assertEqual(summary["consent_claimed_count"], 1)
        self.assertEqual(summary["consent_verified_count"], 0)
        self.assertEqual(summary["sendable_count"], 0)
        self.assertFalse(summary["truncated"])
        self.assertEqual(lookup.await_args.kwargs["filters"]["client_id"], "eq.roove")
        self.assertEqual(lookup.await_args.args[0], "lead_capture_events")

    async def test_claimed_consent_does_not_verify_or_send(self):
        rows = [{"client_id": "roove", "phone_hash": "hash",
                 "consent_whatsapp_claimed": True, "consent_verified": False}]
        with patch.object(campaigns, "sb_select", new_callable=AsyncMock, return_value=rows):
            summary = await campaigns.audience_preview("roove", "capture")
        self.assertEqual(summary["consent_claimed_count"], 1)
        self.assertEqual(summary["consent_verified_count"], 0)
        self.assertEqual(summary["sendable_count"], 0)

    async def test_all_sources_adds_landing_source_without_unverified_send(self):
        async def lookup(table, **kwargs):
            if table == "relationship_contacts":
                return [{"client_id": "roove", "provider": "shopify", "identity_hash": "a",
                         "marketing_whatsapp_verified": False}]
            return [{"client_id": "roove", "phone_hash": "b", "email_hash": "c",
                     "consent_whatsapp_claimed": True, "consent_verified": False}]
        with patch.object(campaigns, "sb_select", new_callable=AsyncMock, side_effect=lookup):
            summary = await campaigns.audience_preview("roove", "all")
        self.assertEqual(summary["total_contacts"], 2)
        self.assertEqual(summary["consent_claimed_count"], 1)
        self.assertEqual(summary["sendable_count"], 0)

    async def test_capture_draft_records_correct_origin(self):
        with patch.object(campaigns, "audience_preview", new_callable=AsyncMock,
                          return_value={"truncated": False, "sendable_count": 0}), \
             patch.object(campaigns, "sb_insert", new_callable=AsyncMock,
                          return_value={"id": "example"}) as insert:
            result = await campaigns.save_draft("roove", {
                "name": "Black Friday Roove", "template_name": "bf_roove",
                "language": "pt_BR", "provider": "capture"
            }, approved=True)
        self.assertEqual(insert.await_args.args[1]["audience_source"], "lead_capture_events")
        self.assertEqual(insert.await_args.args[1]["client_id"], "roove")
        self.assertEqual(result["messages_sent"], 0)

    async def test_unknown_origin_is_rejected(self):
        with self.assertRaises(ValueError):
            await campaigns.audience_preview("roove", "unknown")


if __name__ == "__main__":
    unittest.main()
