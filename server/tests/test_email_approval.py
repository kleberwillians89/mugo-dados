import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import email_approval as review
from services import email_marketing as email


class CampaignApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.campaign = {
            "id": "campaign", "name": "Novembro", "subject": "Novidades", "preheader": "Veja a seleção",
            "custom_html": '<div><img src="https://example.com/a.png" alt="Oferta"></div>',
            "design": {"blocks": []}, "audience": {"segment": "consentimento"},
            "status": "rascunho", "updated_at": "initial", "scheduled_at": None,
            "internal_review": {"status": "draft", "versions": []},
        }
        self.settings = {"from_email": "mugo@example.com", "updated_at": "sender1"}
        for module in (email, review):
            self.enterContext(patch.object(module, "get_campaign", AsyncMock(side_effect=lambda *_: copy.deepcopy(self.campaign))))
            self.enterContext(patch.object(module, "get_settings", AsyncMock(return_value=self.settings)))
        self.enterContext(patch.object(email, "sb_update", AsyncMock(side_effect=self.update)))

    async def update(self, _table, *, filters, patch):
        self.assertEqual(filters["client_id"], "eq.roove")
        if filters["updated_at"] != f"eq.{self.campaign['updated_at']}":
            return []
        self.campaign.update(patch)
        return [copy.deepcopy(self.campaign)]

    async def test_submit_review_html_without_schedule_then_adjust_approve_and_invalidate(self):
        first = await review.submit("roove", "campaign", "writer", "initial")
        self.assertEqual(first["status"], "pending")
        self.assertIsNone(self.campaign["scheduled_at"])
        with patch.object(review, "sb_select", AsyncMock(return_value=[self.campaign])) as select:
            entry, = await review.queue("roove")
        self.assertNotIn("scheduled_at", select.await_args.kwargs["filters"])
        self.assertIn('https://example.com/a.png', entry["preview"]["html"])
        self.assertEqual(entry["preheader"], "Veja a seleção")
        with self.assertRaises(email.EmailError):
            await review.decide("roove", "campaign", "reviewer", 1, "changes_requested", "")
        await review.decide("roove", "campaign", "reviewer", 1, "changes_requested", "Trocar a oferta")
        await email.save_campaign("roove", {"subject": "Nova oferta"}, user_id="writer", campaign_id="campaign")
        await review.submit("roove", "campaign", "writer", self.campaign["updated_at"])
        with self.assertRaises(email.EmailError):
            await review.decide("roove", "campaign", "reviewer", 1, "approved", "")
        result = await review.decide("roove", "campaign", "reviewer", 2, "approved", "")
        self.assertEqual(result["versions"][0]["comment"], "Trocar a oferta")
        self.assertEqual(result["versions"][1]["decided_by"], "reviewer")
        self.assertEqual(self.campaign["status"], "rascunho")
        self.assertTrue(email.approval_valid(self.campaign, self.settings))
        self.assertFalse(email.approval_valid(self.campaign, {**self.settings, "from_email": "new@example.com"}))
        await email.save_campaign("roove", {"audience": {"segment": "compraram"}}, user_id="writer", campaign_id="campaign")
        self.assertFalse(email.approval_valid(self.campaign, self.settings))
        self.assertEqual(len(self.campaign["internal_review"]["versions"]), 2)

    async def test_schedule_and_worker_block_unapproved_version(self):
        with self.assertRaises(email.EmailError) as caught:
            await email.schedule("roove", "campaign", None)
        self.assertEqual(caught.exception.code, "APPROVAL_REQUIRED")
        self.campaign["status"] = "agendada"
        with patch.object(email.email_resend, "send_batch", AsyncMock()) as send:
            self.assertEqual(await email._process_campaign(self.campaign.copy(), "roove"), {"sent": 0})
        send.assert_not_awaited()
        self.assertEqual(self.campaign["status"], "rascunho")

    async def test_test_message_has_same_image_as_preview_and_does_not_enqueue_campaign(self):
        photo = "https://bucket.example/email-marketing/client/vinhos.png"
        self.campaign["custom_html"] = None
        self.campaign["design"] = {
            "blocks": [{"type": "imagem", "url": photo, "alt": "Vinhos naturais", "href": "https://shop.example/oferta"}],
        }
        send = AsyncMock(return_value=["resend-test"])
        with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": "teste-chave"}), \
             patch.object(email.email_resend, "send_batch", send), patch.object(email, "_insert_ignore", AsyncMock()) as log:
            preview = await email.preview("roove", self.campaign)
            result = await email.send_test("roove", self.campaign, "equipe@example.com")
        self.assertEqual(result, {"status": "enviado"})
        message, = send.await_args.args[0]
        image = f'<img src="{photo}" alt="Vinhos naturais"'
        self.assertIn(image, preview["html"])
        self.assertIn(image, message["html"])
        self.assertIn('href="https://shop.example/oferta"', message["html"])
        self.assertEqual(message["to"], ["equipe@example.com"])
        self.assertTrue(message["subject"].startswith("[TESTE] "))
        self.assertEqual(log.await_args.args[0][0]["kind"], "teste")
        self.assertEqual(self.campaign["internal_review"]["status"], "draft")
        self.assertEqual(self.campaign["status"], "rascunho")

    async def test_stale_save_conflicts(self):
        with self.assertRaises(email.EmailError) as caught:
            await email.save_campaign("roove", {"subject": "outro", "expected_updated_at": "stale"},
                                      user_id="writer", campaign_id="campaign")
        self.assertEqual(caught.exception.code, "STALE_CAMPAIGN")
        self.assertEqual(self.campaign["subject"], "Novidades")


class InternalReviewPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_role_cannot_open_queue_or_review(self):
        from fastapi import HTTPException
        from server.routes import email_marketing as route

        with patch.object(route, "require_client_read", AsyncMock(return_value="roove")), \
             patch.object(route, "is_agency_user", AsyncMock(return_value=False)), \
             patch.object(route.email_approval, "queue", AsyncMock()) as queue:
            with self.assertRaises(HTTPException) as caught:
                await route.email_approval_queue("roove", None, "client")
            self.assertEqual(caught.exception.status_code, 403)
            queue.assert_not_awaited()

    async def test_membership_rejection_precedes_internal_role_or_campaign_lookup(self):
        from fastapi import HTTPException
        from server.routes import email_marketing as route

        with patch.object(route, "require_client_read", AsyncMock(side_effect=HTTPException(status_code=403))), \
             patch.object(route, "is_agency_user", AsyncMock(return_value=True)) as is_agency, \
             patch.object(route.email_approval, "decide", AsyncMock()) as decide:
            with self.assertRaises(HTTPException) as caught:
                await route.email_decide_approval("campaign", route.EmailReviewDecision(version=1, decision="approved"),
                                                  "other-tenant", None, "token")
            self.assertEqual(caught.exception.status_code, 403)
            is_agency.assert_not_awaited()
            decide.assert_not_awaited()
