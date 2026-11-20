"""Criadores: @ parecidos na busca e foto guardada no MUGOVERSO (o link do Instagram expira)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import creators
from services.integration_errors import IntegrationError


def _missing():
    return IntegrationError("não existe", status_code=404, code="CREATOR_NOT_FOUND", provider="meta")


def test_variacoes_do_arroba():
    out = creators.handle_variants("mel.maia")
    out = creators.handle_variants("mel.maia", limit=6)
    assert "melmaia" in out and "mel_maia" in out and "mel.maiaoficial" in out
    assert "mel.maia" not in out and len(out) <= 6
    assert "ana" in creators.handle_variants("ana123", limit=10)


def test_parecidos_so_os_que_existem_na_meta_maiores_primeiro():
    creators._PREVIEW_CACHE.clear()

    async def meta(client_id, handle):
        if handle in ("melmaia", "mel.maiaoficial"):
            return {"network": "instagram", "handle": handle, "followers": 100 if handle == "melmaia" else 5000}
        raise _missing()
    with patch.object(creators, "_meta_profile", AsyncMock(side_effect=meta)), \
            patch.object(creators, "list_creators", AsyncMock(return_value=[])):
        with patch.object(creators, "handle_variants", lambda h: ["melmaia", "mel_maia", "mel.maiaoficial"]):
            out = asyncio.run(creators.similar_profiles("roove", "mel.maia", None, {"mel.maia"}))
    assert [p["handle"] for p in out] == ["mel.maiaoficial", "melmaia"]


def test_conserta_foto_que_nao_esta_no_storage():
    rows = [{"id": "c1", "network": "instagram", "handle": "nanda", "avatar_url": None},
            {"id": "c2", "network": "instagram", "handle": "ok", "avatar_url": "https://x.supabase.co/storage/v1/object/public/a.jpg"}]
    update = AsyncMock()
    with patch.object(creators, "_meta_profile", AsyncMock(return_value={"avatar_url": "https://scontent/n.jpg"})) as meta, \
            patch.object(creators, "persist_avatar", AsyncMock(return_value="https://x.supabase.co/storage/v1/object/public/creators/instagram/nanda.jpg")), \
            patch.object(creators, "sb_update", update):
        out = asyncio.run(creators.repair_avatars("roove", rows))
    assert meta.await_count == 1
    assert out[0]["avatar_url"].endswith("nanda.jpg")
    assert update.await_args.kwargs["filters"] == {"id": "eq.c1"}
