import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from services import tenant


def run(coro):
    return asyncio.run(coro)


MEMBERSHIPS = [{"client_id": "m2", "role": "account_manager"}, {"client_id": "roove", "role": "viewer"}]


class AccountManagerTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(tenant, "require_user_id", AsyncMock(return_value="duda")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=MEMBERSHIPS)),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(tenant, "resolve_client_id", AsyncMock(side_effect=lambda cid, auth: cid)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_is_team_only_on_own_company(self):
        self.assertTrue(run(tenant.is_agency_user("Bearer x", "m2")))
        self.assertFalse(run(tenant.is_agency_user("Bearer x", "roove")))
        self.assertFalse(run(tenant.is_agency_user("Bearer x")))

    def test_request_company_is_used_when_not_passed(self):
        async def flow(cid):
            await tenant.require_client_read(cid, "Bearer x")
            return await tenant.is_agency_user("Bearer x")
        self.assertTrue(run(flow("m2")))
        self.assertFalse(run(flow("roove")))

    def test_can_write_as_agency_on_own_company_only(self):
        self.assertEqual(run(tenant.require_client_role("m2", "Bearer x", allowed_roles=("agency_admin",))), "m2")
        self.assertEqual(run(tenant.require_client_role("m2", "Bearer x", allowed_roles=("agency_admin", "client_admin"))), "m2")
        with self.assertRaises(HTTPException):
            run(tenant.require_client_role("roove", "Bearer x", allowed_roles=("agency_admin", "client_admin")))

    def test_not_global_agency(self):
        self.assertFalse(run(tenant._has_agency_admin_membership("duda")))


if __name__ == "__main__":
    unittest.main()
