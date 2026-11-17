"""Contexto da Marca: quem consulta, quem altera e de qual empresa (documentos e conhecimento)."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from routes import studio
from services.team_access import route_module


def run(coro):
    return asyncio.run(coro)


def test_rotas_de_conhecimento_pertencem_ao_modulo_da_marca():
    base = "/api/clients/ruah/studio"
    assert route_module("GET", f"{base}/knowledge") == ("brand_ai", "brand_ai.view")
    assert route_module("POST", f"{base}/knowledge/documents") == ("brand_ai", "brand_ai.edit")
    assert route_module("PUT", f"{base}/knowledge") == ("brand_ai", "brand_ai.edit")
    assert route_module("POST", f"{base}/knowledge/documents/abc/retry") == ("brand_ai", "brand_ai.edit")


def test_leitor_nao_corrige_o_conhecimento():
    body = studio.KnowledgeInput(knowledge="Empresa: Ruah")
    with patch.object(studio, "require_client_role", AsyncMock(side_effect=HTTPException(status_code=403))), \
         patch("services.brand_knowledge.save_manual", AsyncMock()) as save:
        with pytest.raises(HTTPException) as err:
            run(studio.write_knowledge("ruah", body, authorization="Bearer leitor"))
    assert err.value.status_code == 403
    save.assert_not_awaited()


def test_leitor_nao_envia_documento():
    body = studio.KnowledgeDocInput(file_name="plano.txt", text="Planejamento 2027 da marca com pilares e tom de voz.")
    with patch.object(studio, "require_client_role", AsyncMock(side_effect=HTTPException(status_code=403))), \
         patch("services.brand_knowledge.learn", AsyncMock()) as learn:
        with pytest.raises(HTTPException):
            run(studio.add_knowledge_document("ruah", body, authorization="Bearer leitor"))
    learn.assert_not_awaited()


def test_escrita_usa_os_papeis_de_admin():
    body = studio.KnowledgeInput(knowledge="Empresa: Ruah")
    with patch.object(studio, "require_client_role", AsyncMock(return_value="ruah")) as require, \
         patch.object(studio, "require_user_id", AsyncMock(return_value="u1")), \
         patch("services.brand_knowledge.save_manual", AsyncMock(return_value={"knowledge": "Empresa: Ruah", "sources": 1})):
        run(studio.write_knowledge("ruah", body, authorization="Bearer admin"))
    assert require.await_args.kwargs["allowed_roles"] == ("agency_admin", "client_admin")


def test_leitura_usa_a_empresa_autorizada_e_nao_a_da_url():
    """Pedir /clients/roove/... com acesso só à Ruah devolve a Ruah (o backend resolve a empresa)."""
    with patch.object(studio, "require_client_read", AsyncMock(return_value="ruah")), \
         patch("services.brand_knowledge.load_knowledge", AsyncMock(return_value={"knowledge": "", "sources": 0, "updated_at": None})) as load, \
         patch("services.brand_knowledge.list_documents", AsyncMock(return_value=[])) as docs:
        run(studio.read_knowledge("roove", authorization="Bearer ruah"))
    load.assert_awaited_once_with("ruah")
    docs.assert_awaited_once_with("ruah")
