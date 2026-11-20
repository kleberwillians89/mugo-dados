"""Relatório mensal: fecha como rascunho, cliente só vê depois de liberado, link só de mês liberado."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import monthly_report as mr
from services.studio_calendar import StudioError


def test_midia_paga_do_mes_com_melhores():
    stats = [{"ad_id": str(i), "ad_name": f"Ad {i}", "campaign_name": "BF", "spend": 100, "impressions": 1000, "clicks": 10 * (i + 1),
              "conversions": i, "revenue": 100 * i} for i in range(6)]

    async def select(table, **kw):
        return stats if kw.get("offset", 0) == 0 else []
    with patch.object(mr, "sb_select", AsyncMock(side_effect=select)):
        out = asyncio.run(mr._paid("roove", *mr._bounds("2026-10")))
    assert out["investimento"] == 600 and out["receita"] == 1500 and out["roas"] == 2.5
    assert out["melhores"][0]["anuncio"] == "Ad 5" and len(out["piores"]) == 2


def test_fechar_cria_rascunho_e_mantem_status_depois():
    rows = {}

    async def get_row(cid, month):
        return rows.get(month)

    async def upsert(table, items, **kw):
        for it in items:
            rows[it["month"]] = {**rows.get(it["month"], {}), **it, "id": "r1"}
    with patch.object(mr, "build_business", AsyncMock(return_value={"month": "2026-10", "midia": {"investimento": 10}})), \
            patch.object(mr, "_summary", AsyncMock(return_value="Resumo")), patch.object(mr, "get_row", AsyncMock(side_effect=get_row)), \
            patch.object(mr, "sb_upsert", AsyncMock(side_effect=upsert)):
        out = asyncio.run(mr.close("roove", "2026-10", refresh_social=False))
        assert out["status"] == "rascunho" and out["summary"] == "Resumo"
        rows["2026-10"]["status"] = "liberado"
        out = asyncio.run(mr.close("roove", "2026-10", refresh_social=False))
        assert out["status"] == "liberado"


def test_cliente_ve_so_liberado_ou_mes_antigo():
    with patch.object(mr, "get_row", AsyncMock(return_value=None)):
        assert asyncio.run(mr.client_can_see("roove", "2026-08")) is True
    with patch.object(mr, "get_row", AsyncMock(return_value={"status": "rascunho"})):
        assert asyncio.run(mr.client_can_see("roove", "2026-10")) is False
    with patch.object(mr, "get_row", AsyncMock(return_value={"status": "liberado"})):
        assert asyncio.run(mr.client_can_see("roove", "2026-10")) is True


def test_link_so_de_mes_liberado():
    with patch.object(mr, "get_row", AsyncMock(return_value={"id": "r1", "status": "rascunho"})):
        try:
            asyncio.run(mr.share("roove", "2026-10"))
            raise AssertionError("não deveria criar link de rascunho")
        except StudioError as exc:
            assert exc.code == "REPORT_NOT_RELEASED"
    update = AsyncMock()
    with patch.object(mr, "get_row", AsyncMock(return_value={"id": "r1", "status": "liberado"})), patch.object(mr, "sb_update", update):
        token = asyncio.run(mr.share("roove", "2026-10"))
    assert len(token) >= 24 and update.await_args.kwargs["patch"] == {"share_token": token}


def test_link_publico_so_busca_liberado():
    select = AsyncMock(return_value=[])
    with patch.object(mr, "sb_select", select):
        try:
            asyncio.run(mr.public("x" * 32))
            raise AssertionError("link inválido")
        except StudioError as exc:
            assert exc.code == "REPORT_NOT_FOUND"
    assert select.await_args.kwargs["filters"]["status"] == "eq.liberado"


def test_dia_primeiro_fecha_mes_anterior_sem_refazer():
    with patch.object(mr, "sb_select", AsyncMock(return_value=[{"id": "a"}, {"id": "b"}])), \
            patch.object(mr, "get_row", AsyncMock(side_effect=[None, {"id": "x"}])), patch.object(mr, "close", AsyncMock()) as close:
        out = asyncio.run(mr.close_all(datetime(2026, 12, 1, 13, tzinfo=timezone.utc)))
    assert out == {"month": "2026-11", "closed": 1, "skipped": 1, "errors": 0}
    assert close.await_args.args == ("a", "2026-11")
