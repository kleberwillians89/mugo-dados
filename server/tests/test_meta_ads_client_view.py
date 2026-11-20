"""Visão do cliente na Mídia On: o que está no ar, com criativo e números, sem nada editável."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import meta_ad_publisher as pub


def _row(i, campaign_id):
    return {"id": f"d{i}", "meta_ids": {"campaign_id": campaign_id} if campaign_id else {},
            "payload": pub.clean_payload({"name": f"Camp {i}", "objective": "trafego", "daily_budget": 30,
                                          "ad": {"primary_text": "Texto", "headline": "Título", "image_url": "https://x/a.jpg",
                                                 "link": "https://loja"}})}


def test_so_campanhas_no_meta_com_estado_e_numeros_no_ar_primeiro():
    rows = [_row(1, "c1"), _row(2, None), _row(3, "c3")]
    status = {"/c1": "PAUSED", "/c3": "ACTIVE"}

    async def graph(method, path, **kw):
        return {"effective_status": status[path], "insights": {"data": [{"spend": "3.59", "reach": "539", "impressions": "1000",
                                                                         "clicks": "20", "inline_link_clicks": "15",
                                                                         "actions": [{"action_type": "link_click", "value": "15"}]}]}}
    graph_mock = AsyncMock(side_effect=graph)
    with patch.object(pub, "list_drafts", AsyncMock(return_value=rows)), \
            patch.object(pub, "_ad_account", AsyncMock(return_value={"token": "t", "act": "act_1"})), patch.object(pub, "_graph", graph_mock):
        out = asyncio.run(pub.client_overview("ruah"))
    assert graph_mock.await_count == 2  # uma chamada por campanha
    names = [c["name"] for c in out["campaigns"]]
    assert names == ["Camp 3", "Camp 1"]
    first = out["campaigns"][0]
    assert first["state"] == "no_ar" and first["creatives"][0]["image_url"] == "https://x/a.jpg"
    assert first["results"]["reach"] == 539 and first["results"]["cost_per_result"] == 0.24
    assert "meta_ids" not in first and out["read_only"] is True


def test_sem_numeros_da_meta_a_campanha_aparece_mesmo_assim():
    with patch.object(pub, "list_drafts", AsyncMock(return_value=[_row(1, "c1")])), \
            patch.object(pub, "_ad_account", AsyncMock(return_value={"token": "t", "act": "act_1"})), \
            patch.object(pub, "_graph", AsyncMock(side_effect=RuntimeError("meta fora"))):
        out = asyncio.run(pub.client_overview("ruah"))
    assert out["campaigns"][0]["state"] == "desconhecido" and out["campaigns"][0]["results"] is None
