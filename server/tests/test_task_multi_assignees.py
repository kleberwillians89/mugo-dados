"""Multi-assignee task regression: backwards compatibility and tenant boundary."""
import asyncio
from uuid import UUID

import pytest

from services import studio_tasks
from services.studio_calendar import StudioError


ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
OUTSIDE = "33333333-3333-4333-8333-333333333333"


def test_legacy_and_multiple_assignees_view():
    old = studio_tasks.task_view({"id": "t1", "title": "Tarefa", "assignee_name": "Alice", "assignee_user_id": ALICE})
    assert old["assignee"]["user_id"] == ALICE
    assert len(old["assignees"]) == 1

    multi = studio_tasks.task_view({
        "id": "t2", "title": "Tarefa", "assignee_user_id": ALICE,
        "assignee_name": "Alice", "assignee_user_ids": [ALICE, BOB],
        "assignee_names": ["Alice", "Bob"],
    })
    assert [p["name"] for p in multi["assignees"]] == ["Alice", "Bob"]
    assert studio_tasks._mine({"assignee_user_ids": [ALICE, BOB]}, BOB)
    assert not studio_tasks._mine({"assignee_user_ids": [ALICE, BOB]}, OUTSIDE)


def test_duplicate_or_malformed_ids_are_rejected():
    with pytest.raises(StudioError):
        studio_tasks._clean({"assignee_user_ids": [ALICE, ALICE]}, partial=True)
    with pytest.raises(StudioError):
        studio_tasks._clean({"assignee_user_ids": ["not-a-user-id"]}, partial=True)


def test_membership_is_checked_against_current_tenant(monkeypatch):
    from services import team_admin

    async def members(client_id):
        assert client_id == "client-a"
        return {"items": [
            {"user_id": ALICE, "status": "active", "name": "Alice"},
            {"user_id": BOB, "status": "active", "name": "Bob"},
            {"user_id": OUTSIDE, "status": "inactive", "name": "Outside"},
        ]}

    monkeypatch.setattr(team_admin, "list_members", members)
    row = {"assignee_user_ids": [ALICE, BOB]}
    asyncio.run(studio_tasks._normalize_assignees("client-a", row))
    assert row["assignee_user_id"] == ALICE
    assert row["assignee_names"] == ["Alice", "Bob"]

    with pytest.raises(StudioError):
        asyncio.run(studio_tasks._normalize_assignees("client-a", {"assignee_user_ids": [ALICE, OUTSIDE]}))
    with pytest.raises(StudioError):
        asyncio.run(studio_tasks._normalize_assignees("client-a", {"assignee_user_ids": [ALICE, BOB]}, only_user=ALICE))
