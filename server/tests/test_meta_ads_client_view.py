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
    status = {"d1": "PAUSED", "d3": "ACTIVE"}
    with patch.object(pub, "list_drafts", AsyncMock(return_value=rows)), \
            patch.object(pub, "live_delivery_status", AsyncMock(side_effect=lambda cid, did: {"objects": {"campaign": {"effective_status": status[did]}}})), \
            patch.object(pub, "live_results", AsyncMock(return_value={"spend": 3.59, "reach": 539, "results": 15, "result_label": "Cliques no link",
                                                                      "cost_per_result": 0.24, "secret": "x"})):
        out = asyncio.run(pub.client_overview("ruah"))
    names = [c["name"] for c in out["campaigns"]]
    assert names == ["Camp 3", "Camp 1"]
    first = out["campaigns"][0]
    assert first["state"] == "no_ar" and first["creatives"][0]["image_url"] == "https://x/a.jpg"
    assert first["results"]["reach"] == 539 and "secret" not in first["results"]
    assert "meta_ids" not in first and out["read_only"] is True


def test_sem_numeros_da_meta_a_campanha_aparece_mesmo_assim():
    with patch.object(pub, "list_drafts", AsyncMock(return_value=[_row(1, "c1")])), \
            patch.object(pub, "live_delivery_status", AsyncMock(side_effect=pub.StudioError("AD_ACCOUNT_MISSING"))), \
            patch.object(pub, "live_results", AsyncMock(side_effect=RuntimeError("meta fora"))):
        out = asyncio.run(pub.client_overview("ruah"))
    assert out["campaigns"][0]["state"] == "desconhecido" and out["campaigns"][0]["results"] is None
