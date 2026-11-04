import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from routes import studio


def test_brand_context_returns_shared_package_sections():
    intel = {"marca": {"tone_of_voice": "leve"}, "campanhas_ativas": [{"campanha": "Black Friday"}],
             "plano_de_midia": {"objetivo": "vendas"}, "referencias_do_cliente": [{"link": "https://pin.it/x"}],
             "posts": {"interno": True}, "lacunas": ["sem_metas_no_mes"]}
    with patch.object(studio, "require_client_role", AsyncMock(return_value="latinas")), \
         patch.object(studio, "_agency_only", AsyncMock()), \
         patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value=intel)) as build:
        out = asyncio.run(studio.brand_context("latinas", authorization="Bearer x"))
    build.assert_awaited_once_with("latinas")
    assert out["campanhas_ativas"] == [{"campanha": "Black Friday"}]
    assert out["referencias_do_cliente"] == [{"link": "https://pin.it/x"}]
    assert "posts" not in out  # só as seções do painel


def test_brand_context_is_team_only():
    with patch.object(studio, "require_client_role", AsyncMock(return_value="latinas")), \
         patch.object(studio, "_agency_only", AsyncMock(side_effect=HTTPException(status_code=403))), \
         patch("services.studio_intelligence.build_content_intelligence", AsyncMock()) as build:
        with pytest.raises(HTTPException):
            asyncio.run(studio.brand_context("latinas", authorization="Bearer cliente"))
    build.assert_not_awaited()
