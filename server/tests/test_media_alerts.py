"""Alertas da Mídia On: regras e uma tarefa por alerta, sem repetir no mesmo dia."""
import asyncio
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import media_alerts as ma

TODAY = date(2026, 11, 20)
PAYLOAD = {"objective": "vendas", "start_date": "2026-11-01", "end_date": "2026-12-20"}
BUY = ("offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase")


def kinds(status, recent, total, payload=PAYLOAD):
    return [a["kind"] for a in ma.detect("BF", payload, status, recent, total, BUY, TODAY)]


def test_reprovada_e_problema():
    assert kinds("DISAPPROVED", {}, {}) == ["reprovada"]
    assert kinds("WITH_ISSUES", {}, {}) == ["com_problema"]


def test_ligada_sem_entrega():
    assert "sem_entrega" in kinds("ACTIVE", {"impressions": "0"}, {"spend": "100"})


def test_custo_subiu():
    recent = {"spend": "60", "impressions": "1000", "actions": [{"action_type": "purchase", "value": "1"}]}
    total = {"spend": "300", "impressions": "9000", "actions": [{"action_type": "purchase", "value": "10"}]}
    assert kinds("ACTIVE", recent, total) == ["custo_alto"]
    calm = {"spend": "60", "impressions": "1000", "actions": [{"action_type": "purchase", "value": "2"}]}
    assert kinds("ACTIVE", calm, total) == []


def test_fim_proximo():
    assert kinds("ACTIVE", {"impressions": "10"}, {}, {**PAYLOAD, "end_date": "2026-11-21"}) == ["fim_proximo"]


def test_um_alerta_vira_uma_tarefa_e_nao_repete():
    draft = {"id": "d1", "meta_ids": {"campaign_id": "c1"}, "payload": {**PAYLOAD, "name": "BF"}}
    graph = AsyncMock(side_effect=[{"effective_status": "DISAPPROVED"}, {"data": []}, {"effective_status": "DISAPPROVED"}, {"data": []}])
    inserted = []

    async def insert(table, row, **kw):
        if table == "media_alerts" and any(r[0] == "media_alerts" for r in inserted):
            raise RuntimeError("duplicate key")
        inserted.append((table, row))
        return {"id": "x"}
    with patch("services.meta_ad_publisher.list_drafts", AsyncMock(return_value=[draft])), \
            patch("services.meta_ad_publisher._ad_account", AsyncMock(return_value={"token": "t", "act": "act_1"})), \
            patch("services.meta_ad_publisher._graph", graph), patch.object(ma, "sb_insert", AsyncMock(side_effect=insert)):
        assert asyncio.run(ma.check_client("ruah", TODAY)) == 1
        assert asyncio.run(ma.check_client("ruah", TODAY)) == 0
    task = [r for t, r in inserted if t == "studio_tasks"][0]
    assert task["priority"] == "high" and task["visible_to_client"] is False and "reprovou" in task["title"]
