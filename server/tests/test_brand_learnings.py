"""Ciclo fechado da IA: o post publicado vira conclusão (acima/na média/abaixo) e a IA lê."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import brand_learnings as bl

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def _media(i, reach, saved=0, ts="2026-11-10T22:00:00+0000"):
    return {"media_id": f"17900000000{i:02d}", "media_type": "IMAGE", "media_product_type": "FEED", "timestamp": ts,
            "caption": "x", "insights_json": {"reach": reach, "likes": 10, "comments": 1, "saved": saved, "shares": 3}}


def test_post_acima_da_media_vira_aprendizado_com_pauta():
    media = [_media(i, 100) for i in range(10)] + [_media(10, 400, saved=38)]
    calendar = [{"published_media_id": "1790000000010", "title": "Como lavar a legging", "hook": "Você lava errado",
                 "pillar": "Educação", "scheduled_at": "2026-11-10T22:00:00+00:00"}]
    upserts = []

    async def select(table, **kw):
        return {"studio_calendar_items": calendar, "brand_learnings": [], "ig_media": media}[table]
    with patch.object(bl, "sb_select", AsyncMock(side_effect=select)), \
            patch.object(bl, "sb_upsert", AsyncMock(side_effect=lambda t, rows, **kw: upserts.extend(rows))):
        assert asyncio.run(bl.learn_posts("roove", NOW)) == 1
    row = upserts[0]
    assert row["verdict"] == "acima" and row["ref_id"] == "1790000000010"
    assert "Como lavar a legging" in row["lesson"] and "38 salvamentos" in row["lesson"] and "Repetir" in row["lesson"]
    assert row["lesson"].count("×") == 1


def test_ja_aprendido_nao_repete():
    calendar = [{"published_media_id": "1790000000010", "title": "x", "scheduled_at": "2026-11-10T22:00:00+00:00"}]

    async def select(table, **kw):
        return {"studio_calendar_items": calendar, "brand_learnings": [{"ref_id": "1790000000010"}]}[table]
    with patch.object(bl, "sb_select", AsyncMock(side_effect=select)), patch.object(bl, "sb_upsert", AsyncMock()) as up:
        assert asyncio.run(bl.learn_posts("roove", NOW)) == 0
    up.assert_not_awaited()


def test_anuncio_do_midia_on_contra_a_mediana_da_conta():
    stats = [{"ad_id": str(i), "ad_name": f"Ad {i}", "stat_date": "2026-10-01", "spend": 100, "impressions": 1000, "clicks": 10,
              "conversions": 2} for i in range(4)]
    stats.append({"ad_id": "9", "ad_name": "Legging", "stat_date": "2026-10-01", "spend": 100, "impressions": 1000, "clicks": 30, "conversions": 5})
    copies = {"9": {"formato": "imagem", "titulo": "Compre já", "texto": "Sua legging"}}

    async def select(table, **kw):
        return {"brand_learnings": [], "ad_daily_stats": stats}[table]
    upserts = []
    with patch("services.studio_intelligence._mugo_ad_copies", AsyncMock(return_value=copies)), \
            patch.object(bl, "sb_select", AsyncMock(side_effect=select)), \
            patch.object(bl, "sb_upsert", AsyncMock(side_effect=lambda t, rows, **kw: upserts.extend(rows))):
        assert asyncio.run(bl.learn_ads("roove", NOW)) == 1
    assert upserts[0]["verdict"] == "acima" and "custo por resultado" in upserts[0]["lesson"]


def test_ia_le_fora_da_media_primeiro():
    rows = [{"kind": "post", "verdict": "na_media", "lesson": "a", "published_at": "2026-11-15"},
            {"kind": "ad", "verdict": "abaixo", "lesson": "b", "published_at": "2026-11-01"},
            {"kind": "post", "verdict": "acima", "lesson": "c", "published_at": "2026-11-10"}]
    with patch.object(bl, "sb_select", AsyncMock(return_value=rows)):
        out = asyncio.run(bl.recent("roove"))
    assert [o["aprendizado"] for o in out] == ["c", "b", "a"] and out[1]["tipo"] == "anúncio"
