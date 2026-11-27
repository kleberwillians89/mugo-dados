"""Criar público como no Gerenciador e barrar público criado com o perfil de um parceiro."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import meta_ad_publisher as pub

ACCOUNT = {"token": "t", "act": "act_1"}
BRAND = {"page_id": "111", "ig_id": "999"}


def test_publico_de_parceiro_fica_bloqueado():
    rule = json.dumps({"inclusions": {"rules": [{"event_sources": [{"id": "555", "type": "ig_business"}]}]}})
    own = json.dumps({"inclusions": {"rules": [{"event_sources": [{"id": "999", "type": "ig_business"}]}]}})
    rows = [{"id": "100001", "name": "Engajou Gabi", "subtype": "ENGAGEMENT", "rule": rule},
            {"id": "100002", "name": "Engajou Ruah", "subtype": "ENGAGEMENT", "rule": own}]
    with patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
            patch.object(pub, "_paged", AsyncMock(side_effect=[rows, []])), \
            patch.object(pub, "_brand_profiles", AsyncMock(return_value=BRAND)):
        out = asyncio.run(pub.list_account_audiences("ruah"))
    by = {a["name"]: a for a in out["custom"]}
    assert by["Engajou Gabi"]["ready"] is False and by["Engajou Gabi"]["foreign"] is True
    assert "outro perfil do Instagram" in by["Engajou Gabi"]["status"]
    assert by["Engajou Ruah"]["ready"] is True and not by["Engajou Ruah"].get("foreign")


def test_cria_engajamento_no_instagram_da_marca():
    graph = AsyncMock(return_value={"id": "777"})
    with patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
            patch.object(pub, "_brand_profiles", AsyncMock(return_value=BRAND)), patch.object(pub, "_graph", graph):
        out = asyncio.run(pub.create_account_audience("ruah", {"kind": "instagram", "event": "visitou_perfil", "days": 90}))
    data = graph.await_args.kwargs["data"]
    rule = json.loads(data["rule"])["inclusions"]["rules"][0]
    assert rule["event_sources"] == [{"id": "999", "type": "ig_business"}]
    assert rule["retention_seconds"] == 90 * 86400
    assert rule["filter"]["filters"][0]["value"] == "ig_business_profile_visit"
    assert out["id"] == "777" and "Instagram" in out["name"]


def test_cria_semelhante_no_brasil():
    graph = AsyncMock(return_value={"id": "778"})
    with patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), patch.object(pub, "_graph", graph):
        asyncio.run(pub.create_account_audience("ruah", {"kind": "semelhante", "origin_audience_id": "123456", "ratio": 3}))
    data = graph.await_args.kwargs["data"]
    assert data["subtype"] == "LOOKALIKE" and data["origin_audience_id"] == "123456"
    assert json.loads(data["lookalike_spec"]) == {"type": "custom_ratio", "ratio": 0.03, "country": "BR"}


def test_lista_manda_so_hash():
    rows = [["a" * 64, ""]] * 150
    graph = AsyncMock(return_value={"id": "779"})
    with patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), patch.object(pub, "_graph", graph), \
            patch.object(pub, "_customer_rows", AsyncMock(return_value=rows)):
        out = asyncio.run(pub.create_account_audience("ruah", {"kind": "lista"}))
    users = graph.await_args_list[-1]
    assert users.args[1] == "/779/users"
    payload = json.loads(users.kwargs["data"]["payload"])
    assert payload["schema"] == ["EMAIL_SHA256", "PHONE_SHA256"] and len(payload["data"]) == 150
    assert "150 clientes" in out["note"]
