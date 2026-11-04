import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services import studio_references as sr
from services.studio_calendar import StudioError


def test_only_https_links_are_accepted():
    assert sr.clean_url(" https://www.instagram.com/p/abc ") == "https://www.instagram.com/p/abc"
    for bad in ("http://x.com/a", "javascript:alert(1)", "https://x .com", ""):
        with pytest.raises(StudioError):
            sr.clean_url(bad)


def test_client_reference_notifies_team_and_agency_does_not():
    insert = AsyncMock(return_value={"id": "r1"})
    notify = AsyncMock()
    with patch.object(sr, "sb_insert", insert), patch("services.studio_team.notify_team", notify):
        asyncio.run(sr.add_reference("latinas", url="https://pin.it/x", note="cores", kind="link", agency=False, user_id="u1"))
        asyncio.run(sr.add_reference("latinas", url="https://pin.it/y", note=None, kind="link", agency=True, user_id="u2"))
    assert insert.await_args_list[0].args[1]["author_side"] == "cliente"
    assert insert.await_args_list[1].args[1]["author_side"] == "mugo"
    assert notify.await_count == 1
    assert notify.await_args.args[1]["id"] is None  # referência não é de um post


def test_art_reference_must_live_in_this_company_storage():
    with patch.object(sr, "sb_insert", AsyncMock(return_value={})):
        with pytest.raises(StudioError):
            asyncio.run(sr.add_reference("latinas", url="https://x.supabase.co/storage/v1/object/public/ig-media/studio-refs/roove/a.jpg",
                                         note=None, kind="arte", agency=True, user_id="u"))
        asyncio.run(sr.add_reference("latinas", url="https://x.supabase.co/storage/v1/object/public/ig-media/studio-refs/latinas/a.jpg",
                                     note=None, kind="arte", agency=True, user_id="u"))


def test_client_deletes_only_own_reference_agency_any():
    select = AsyncMock(return_value=[{"id": "r1"}])
    request = AsyncMock()
    with patch.object(sr, "sb_select", select), patch.object(sr, "_request", request):
        asyncio.run(sr.delete_reference("latinas", "r1", agency=False, user_id="u1"))
        assert select.await_args.kwargs["filters"]["author_id"] == "eq.u1"
        asyncio.run(sr.delete_reference("latinas", "r1", agency=True, user_id="u2"))
        assert "author_id" not in select.await_args.kwargs["filters"]
    assert all(call.kwargs["params"]["client_id"] == "eq.latinas" for call in request.await_args_list)


def test_missing_reference_is_not_found():
    with patch.object(sr, "sb_select", AsyncMock(return_value=[])), pytest.raises(StudioError):
        asyncio.run(sr.delete_reference("latinas", "r9", agency=False, user_id="u1"))
