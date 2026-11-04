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


def test_references_reach_the_calendar_prompt_and_intelligence():
    from services import studio_calendar, studio_intelligence
    refs = [{"link": "https://pin.it/x", "tipo": "link", "o_que_gostou": "luz natural", "de_quem": "cliente"}]
    text = studio_intelligence.to_prompt({"marca": {"tone_of_voice": "leve"}, "referencias_do_cliente": refs})
    assert "luz natural" in text
    prompt = studio_calendar.build_prompt(slots=[], profile={}, business={}, top=[], trends=[], seasonal=[],
                                          month=__import__("datetime").date(2026, 12, 1),
                                          signals={"referencias_do_cliente": refs})
    assert "referencias_do_cliente" in prompt and "luz natural" in prompt
    assert "rationale qual" in prompt


def test_reference_rows_become_prompt_items():
    from services import studio_intelligence
    rows = [{"url": "https://x.supabase.co/storage/v1/object/public/ig-media/studio-refs/l/a.jpg", "kind": "arte",
             "note": "cores quentes", "author_side": "cliente", "created_at": "2026-11-04"}]
    with patch.object(studio_intelligence, "sb_select", AsyncMock(return_value=rows)):
        out = asyncio.run(studio_intelligence._references("latinas"))
    assert out == [{"link": rows[0]["url"], "tipo": "imagem", "o_que_gostou": "cores quentes", "de_quem": "cliente"}]


def test_item_references_filter_and_brand_tab_excludes_post_refs():
    select = AsyncMock(return_value=[])
    with patch.object(sr, "sb_select", select):
        asyncio.run(sr.list_references("latinas", "it-1"))
        assert select.await_args.kwargs["filters"]["item_id"] == "eq.it-1"
        asyncio.run(sr.list_references("latinas"))
        assert select.await_args.kwargs["filters"]["item_id"] == "is.null"


def test_brand_tab_survives_before_item_migration():
    select = AsyncMock(side_effect=[RuntimeError("column item_id does not exist"), [{"id": "r1"}]])
    with patch.object(sr, "sb_select", select):
        assert asyncio.run(sr.list_references("latinas")) == [{"id": "r1"}]


def test_post_reference_is_saved_on_the_post_and_notifies_with_it():
    insert = AsyncMock(return_value={"id": "r1"})
    notify = AsyncMock()
    item = {"id": "it-1", "title": "Coxinha vegana", "status": "em_revisao", "scheduled_at": None}
    with patch.object(sr, "sb_insert", insert), patch("services.studio_team.notify_team", notify):
        asyncio.run(sr.add_reference("latinas", url="https://pin.it/z", note="luz", kind="link", agency=False, user_id="u", item=item))
    assert insert.await_args.args[1]["item_id"] == "it-1"
    assert notify.await_args.args[1]["id"] == "it-1"


def test_assist_prompt_includes_post_references():
    from services import studio_engines as se
    seen = {}

    async def llm(**kw):
        seen["prompt"] = kw["prompt"]
        return {}

    with patch.object(se, "build_content_intelligence", AsyncMock(return_value={})), \
         patch.object(se, "_post_references", AsyncMock(return_value=[{"link": "https://pin.it/z", "o_que_gostou": "luz"}])), \
         patch.object(se, "llm_json", llm), patch.object(se, "_clean_assist", lambda a, d: d), patch.object(se, "throttle", lambda c: None):
        try:
            asyncio.run(se.assist("latinas", "legenda" if "legenda" in se.ASSIST_ACTIONS else next(iter(se.ASSIST_ACTIONS)),
                                  {"title": "Coxinha", "format": "reels"}, item_id="it-1"))
        except Exception:
            pass
    assert "REFERÊNCIAS DESTE POST" in seen["prompt"] and "https://pin.it/z" in seen["prompt"]
