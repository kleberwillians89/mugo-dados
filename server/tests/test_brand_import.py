"""Importar configurações do planejamento: prévia com origem, nada inventado, só o aprovado é gravado.

Sem chamada real de IA: ``llm_json`` é sempre simulado."""
import asyncio
import copy
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import studio
from services import brand_import as bi
from services.studio_calendar import StudioError, normalize_profile
from services.team_access import route_module


def run(coro):
    return asyncio.run(coro)


# Brand book fictício (marca inventada), já extraído e guardado em trechos pelo Conhecimento da marca.
BRAND_BOOK = [
    "Aurora Cafés Especiais — Planejamento de Comunicação 2027. Somos uma torrefação de cafés especiais de Minas Gerais "
    "que vende online e em duas lojas próprias em Belo Horizonte.",
    "Público-alvo: adultos de 28 a 45 anos, apreciadores de café, que compram pela internet e valorizam origem e "
    "rastreabilidade. Tom de voz: acolhedor, curioso e didático, sem jargão técnico excessivo.",
    "Pilares editoriais: Origem (40%), Preparo (35%) e Comunidade (25%). Publicaremos 4 posts por semana no Instagram "
    "e 2 vídeos por semana no TikTok. Formatos prioritários: Reels e carrossel.",
    "Concorrentes de referência: Café Serra Alta e Grão Paulista. Evitar as palavras 'gourmet' e 'barato'. "
    "Objetivo: aumentar em 30% as vendas do e-commerce em 2027.",
]
DOC = {"id": "11111111-1111-1111-1111-111111111111", "name": "planejamento-aurora-2027.pdf", "kind": "institucional",
       "status": "aprendido", "chars_total": 900, "truncated": False}


def f(status, value, evidence="", note=""):
    return {"status": status, "value": value, "evidence": evidence, "note": note}


def ai_reply(**overrides):
    fields = {key: f("missing", [] if kind not in ("text", "int") else None) for key, (_, _, kind, _) in bi.CATALOG.items()}
    fields.update({
        "audience": f("found", "Adultos de 28 a 45 anos, apreciadores de café, que compram online e valorizam origem.",
                      "Público-alvo: adultos de 28 a 45 anos, apreciadores de café"),
        "tone_of_voice": f("found", "Acolhedor, curioso e didático, sem jargão técnico excessivo.",
                           "Tom de voz: acolhedor, curioso e didático"),
        "pillars": f("found", [{"name": "Origem", "weight": 40, "description": ""}, {"name": "Preparo", "weight": 35, "description": ""},
                               {"name": "Comunidade", "weight": 25, "description": ""}],
                     "Pilares editoriais: Origem (40%), Preparo (35%) e Comunidade (25%)"),
        "posts_per_week_by_platform": f("found", [{"platform": "instagram", "per_week": 4}, {"platform": "tiktok", "per_week": 2}],
                                        "Publicaremos 4 posts por semana no Instagram e 2 vídeos por semana no TikTok"),
        "editorial_platforms": f("found", ["instagram", "tiktok"], "4 posts por semana no Instagram e 2 vídeos por semana no TikTok"),
        "formats_enabled": f("found", ["reels", "carrossel"], "Formatos prioritários: Reels e carrossel"),
        "competitors": f("found", ["Café Serra Alta", "Grão Paulista"], "Concorrentes de referência: Café Serra Alta e Grão Paulista"),
        "keywords_avoid": f("found", ["gourmet", "barato"], "Evitar as palavras 'gourmet' e 'barato'"),
        "goals": f("found", "Aumentar em 30% as vendas do e-commerce em 2027.", "Objetivo: aumentar em 30% as vendas do e-commerce em 2027"),
        # A IA "inventou" um posicionamento com citação que não está no documento → tem que virar ambíguo.
        "positioning": f("found", "A marca mais premium do Brasil.", "a marca de café mais premium do Brasil"),
        # Frequência total sem número no trecho → ambíguo.
        "posts_per_week": f("found", 6, "foco forte nas redes sociais"),
    })
    fields.update(overrides)
    return {"fields": fields}


CURRENT_PROFILE = normalize_profile({
    "tone_of_voice": "Tom atual definido pela equipe", "audience": "", "pillars": [{"name": "Antigo", "weight": 100}],
    "keywords_avoid": ["promoção"], "posts_per_week": 3, "editorial_platforms": ["instagram"],
    "posts_per_week_by_platform": {"instagram": 3}, "formats_enabled": ["imagem"],
    "custom_dates": [{"date": "05-10", "label": "Aniversário da loja"}], "content_language": "pt-BR",
    "restrictions": "Não citar preço em post orgânico.",
})
CURRENT_BUSINESS = {"segment": "Cafés especiais", "product_description": None, "audience": None, "positioning": "Posicionamento atual",
                    "differentiators": None, "commercial_context": "Ticket médio R$ 120", "goals": None,
                    "strategic_notes": "Sazonalidade forte no inverno."}


class Harness:
    """Banco falso por empresa: o documento só existe para a empresa dona dele."""

    def __init__(self, chunks=BRAND_BOOK, owner="aurora", reply=None):
        self.chunks, self.owner = chunks, owner
        self.llm = AsyncMock(return_value=reply or ai_reply())
        self.save_profile = AsyncMock(side_effect=lambda cid, profile, user_id: {"profile": normalize_profile(profile), "saved": True})
        self.save_business = AsyncMock(side_effect=lambda client_id, user_id, payload: {"available": True, "context": payload})
        self.profile = copy.deepcopy(CURRENT_PROFILE)
        self.business = copy.deepcopy(CURRENT_BUSINESS)

    async def select(self, table, select="*", filters=None, order=None, limit=None, offset=None):
        if (filters or {}).get("client_id") != f"eq.{self.owner}":
            return []
        if table == bi.DOCUMENTS:
            return [DOC]
        if table == bi.CHUNKS:
            return [{"content": c, "position": i} for i, c in enumerate(self.chunks)]
        return []

    def patches(self):
        return [patch.object(bi, "sb_select", self.select), patch("services.studio_llm.llm_json", self.llm),
                patch.object(bi, "load_profile", AsyncMock(return_value={"profile": self.profile, "saved": True})),
                patch.object(bi, "load_business_context", AsyncMock(return_value={"context": self.business})),
                patch.object(bi, "save_profile", self.save_profile), patch.object(bi, "save_business_context", self.save_business)]

    def __enter__(self):
        self._ps = self.patches()
        for p in self._ps:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._ps):
            p.stop()


def by_key(result):
    return {field["key"]: field for field in result["fields"]}


# ---------------------------------------------------------------- prévia

def test_schema_estrito_cobre_todos_os_campos():
    schema = bi.extraction_schema()
    fields = schema["properties"]["fields"]
    assert set(fields["required"]) == set(bi.CATALOG)
    assert fields["additionalProperties"] is False
    assert fields["properties"]["pillars"]["properties"]["value"]["items"]["properties"]["weight"]["type"] == ["integer", "null"]


def test_previa_extrai_brand_book_com_origem_e_nao_grava_nada():
    with Harness() as h:
        result = run(bi.preview("aurora", DOC["id"]))
    fields = by_key(result)
    assert fields["tone_of_voice"]["status"] == "found"
    assert fields["tone_of_voice"]["current"] == "Tom atual definido pela equipe"
    assert fields["tone_of_voice"]["source"]["verified"] is True
    assert fields["tone_of_voice"]["source"]["location"] == "Trecho 2 de 4"
    assert fields["pillars"]["value"][0] == {"name": "Origem", "weight": 40, "description": ""}
    assert fields["posts_per_week_by_platform"]["value"] == {"instagram": 4, "tiktok": 2}
    assert fields["audience"]["targets"] == ["profile.audience", "business.audience"]
    assert fields["pillars"]["operational"] is True and fields["audience"]["operational"] is False
    assert "Diferenciais" in result["missing"]
    # uma chamada, com a empresa (BYOK/consumo por tenant) e sem forçar modelo caro
    h.llm.assert_awaited_once()
    assert h.llm.await_args.kwargs["client_id"] == "aurora"
    assert "model" not in h.llm.await_args.kwargs
    assert "Aurora Cafés" in h.llm.await_args.kwargs["prompt"]
    h.save_profile.assert_not_awaited()
    h.save_business.assert_not_awaited()


def test_citacao_que_nao_esta_no_documento_vira_ambigua():
    with Harness():
        fields = by_key(run(bi.preview("aurora", DOC["id"])))
    assert fields["positioning"]["status"] == "ambiguous"
    assert fields["positioning"]["source"]["verified"] is False
    assert any("Não localizei" in n for n in fields["positioning"]["notes"])


def test_frequencia_sem_numero_explicito_nao_vira_regra():
    with Harness():
        fields = by_key(run(bi.preview("aurora", DOC["id"])))
    assert fields["posts_per_week"]["status"] == "ambiguous"
    assert any("número" in n for n in fields["posts_per_week"]["notes"])


def test_pesos_que_nao_fecham_100_pedem_revisao_sem_normalizar():
    reply = ai_reply(pillars=f("found", [{"name": "Origem", "weight": 50, "description": ""}, {"name": "Preparo", "weight": 30, "description": ""}],
                               "Pilares editoriais: Origem (40%), Preparo (35%)"))
    with Harness(reply=reply):
        fields = by_key(run(bi.preview("aurora", DOC["id"])))
    assert [p["weight"] for p in fields["pillars"]["value"]] == [50, 30]
    assert any("somam 80%" in n for n in fields["pillars"]["notes"])


def test_pilares_sem_peso_ficam_sem_peso():
    reply = ai_reply(pillars=f("found", [{"name": "Origem", "weight": None, "description": ""}, {"name": "Preparo", "weight": None, "description": ""}],
                               "Pilares editoriais: Origem (40%), Preparo (35%)"))
    with Harness(reply=reply):
        fields = by_key(run(bi.preview("aurora", DOC["id"])))
    assert [p["weight"] for p in fields["pillars"]["value"]] == [None, None]
    assert any("peso de todos os pilares" in n for n in fields["pillars"]["notes"])


def test_campo_sem_valor_e_nao_encontrado_mesmo_que_a_ia_diga_found():
    with Harness(reply=ai_reply(differentiators=f("found", None, "qualquer coisa"))):
        fields = by_key(run(bi.preview("aurora", DOC["id"])))
    assert fields["differentiators"]["status"] == "missing"
    assert fields["differentiators"]["source"] is None


def test_pdf_sem_texto_recebe_orientacao_e_nao_chama_ia():
    with Harness(chunks=["Página 1", "Página 2"]) as h:
        with pytest.raises(StudioError) as err:
            run(bi.preview("aurora", DOC["id"]))
    assert err.value.code == "IMPORT_TEXT_TOO_SHORT"
    h.llm.assert_not_awaited()
    assert "OCR" in studio.ERRORS["IMPORT_TEXT_TOO_SHORT"][1]
    assert "OCR" in studio.ERRORS["DOC_EMPTY"][1]


def test_documento_de_outra_empresa_nao_e_lido():
    with Harness(owner="aurora") as h:
        with pytest.raises(StudioError) as err:
            run(bi.preview("outra-marca", DOC["id"]))
    assert err.value.code == "DOC_NOT_FOUND"
    h.llm.assert_not_awaited()


# ---------------------------------------------------------------- aplicar

def test_aplica_so_os_campos_aprovados_e_preserva_o_resto():
    with Harness() as h:
        result = run(bi.apply("aurora", {"tone_of_voice": {"value": "Acolhedor e didático.", "mode": "replace"},
                                         "audience": {"value": "Adultos de 28 a 45 anos.", "mode": "replace"}}, user_id="u1"))
    saved_profile = h.save_profile.await_args.args[1]
    assert saved_profile["tone_of_voice"] == "Acolhedor e didático."
    assert saved_profile["audience"] == "Adultos de 28 a 45 anos."
    # não aprovados: exatamente como estavam
    assert saved_profile["pillars"] == CURRENT_PROFILE["pillars"]
    assert saved_profile["posts_per_week"] == 3
    assert saved_profile["formats_enabled"] == ["imagem"]
    assert saved_profile["keywords_avoid"] == ["promoção"]
    assert saved_profile["custom_dates"] == CURRENT_PROFILE["custom_dates"]
    assert saved_profile["restrictions"] == "Não citar preço em post orgânico."
    business = h.save_business.await_args.kwargs["payload"]
    assert business["audience"] == "Adultos de 28 a 45 anos."
    assert business["positioning"] == "Posicionamento atual"
    assert business["commercial_context"] == "Ticket médio R$ 120"
    assert business["strategic_notes"] == "Sazonalidade forte no inverno."
    assert result["applied"] == ["Tom de voz", "Público-alvo"]


def test_so_contexto_estrategico_nao_regrava_o_perfil():
    with Harness() as h:
        run(bi.apply("aurora", {"goals": {"value": "Vender 30% mais online.", "mode": "replace"}}, user_id="u1"))
    h.save_profile.assert_not_awaited()
    assert h.save_business.await_args.kwargs["payload"]["goals"] == "Vender 30% mais online."


def test_pesos_diferentes_de_100_sao_recusados_sem_gravar():
    with Harness() as h:
        with pytest.raises(StudioError) as err:
            run(bi.apply("aurora", {"pillars": {"value": [{"name": "Origem", "weight": 50, "description": ""},
                                                          {"name": "Preparo", "weight": 30, "description": ""}]},
                                    "tone_of_voice": {"value": "Novo tom"}}, user_id="u1"))
    assert err.value.code == "PILLARS_WEIGHT_TOTAL"
    assert "80%" in str(err.value)
    h.save_profile.assert_not_awaited()
    h.save_business.assert_not_awaited()


def test_pilar_sem_peso_e_recusado():
    with Harness() as h:
        with pytest.raises(StudioError) as err:
            run(bi.apply("aurora", {"pillars": {"value": [{"name": "Origem", "weight": None, "description": ""}]}}, user_id="u1"))
    assert err.value.code == "IMPORT_FIELD_INVALID"
    h.save_profile.assert_not_awaited()


def test_pilares_e_frequencia_confirmados_vao_para_o_calendario():
    with Harness() as h:
        result = run(bi.apply("aurora", {
            "pillars": {"value": [{"name": "Origem", "weight": 40, "description": ""}, {"name": "Preparo", "weight": 35, "description": ""},
                                  {"name": "Comunidade", "weight": 25, "description": ""}]},
            "editorial_platforms": {"value": ["instagram", "tiktok"]},
            "posts_per_week_by_platform": {"value": {"instagram": 4, "tiktok": 2}},
            "formats_enabled": {"value": ["reels", "carrossel"]},
        }, user_id="u1"))
    profile = result["profile"]
    assert [p["weight"] for p in profile["pillars"]] == [40, 35, 25]
    assert profile["posts_per_week_by_platform"] == {"instagram": 4, "tiktok": 2}
    assert profile["formats_enabled"] == ["reels", "carrossel"]
    # o perfil salvo é o mesmo formato que o Calendário e os agentes leem
    assert normalize_profile(profile) == profile
    h.save_business.assert_not_awaited()


def test_frequencia_de_canal_fora_das_plataformas_pede_revisao():
    with Harness() as h:
        with pytest.raises(StudioError) as err:
            run(bi.apply("aurora", {"posts_per_week_by_platform": {"value": {"instagram": 4, "tiktok": 2}}}, user_id="u1"))
    assert err.value.code == "FREQUENCY_PLATFORM_MISSING"
    assert "TikTok" in str(err.value)
    h.save_profile.assert_not_awaited()


def test_acrescentar_mantem_o_texto_atual_e_lista_soma_sem_repetir():
    with Harness() as h:
        run(bi.apply("aurora", {"tone_of_voice": {"value": "Didático.", "mode": "append"},
                                "keywords_avoid": {"value": ["gourmet", "Promoção"], "mode": "append"}}, user_id="u1"))
    saved = h.save_profile.await_args.args[1]
    assert saved["tone_of_voice"] == "Tom atual definido pela equipe\nDidático."
    assert saved["keywords_avoid"] == ["promoção", "gourmet"]


def test_concorrentes_entram_nas_observacoes_sem_apagar_o_que_havia():
    with Harness() as h:
        run(bi.apply("aurora", {"competitors": {"value": ["Café Serra Alta", "Grão Paulista"]}}, user_id="u1"))
    notes = h.save_business.await_args.kwargs["payload"]["strategic_notes"]
    assert notes == "Sazonalidade forte no inverno.\nConcorrentes citados no planejamento: Café Serra Alta, Grão Paulista."


def test_valor_invalido_nao_e_ajustado_em_silencio():
    with Harness() as h:
        for bad in ({"posts_per_week": {"value": 30}}, {"formats_enabled": {"value": ["podcast"]}},
                    {"tone_of_voice": {"value": "x" * 1001}}, {"segment": {"value": ""}}, {"campo_novo": {"value": "x"}}):
            with pytest.raises(StudioError):
                run(bi.apply("aurora", bad, user_id="u1"))
        with pytest.raises(StudioError) as err:
            run(bi.apply("aurora", {}, user_id="u1"))
    assert err.value.code == "IMPORT_NOTHING_APPROVED"
    h.save_profile.assert_not_awaited()
    h.save_business.assert_not_awaited()


# ---------------------------------------------------------------- rotas: permissão, empresa e confirmação

def test_rotas_de_importacao_exigem_edicao_do_modulo_da_marca():
    base = "/api/clients/aurora/studio/knowledge/import"
    assert route_module("POST", f"{base}/preview") == ("brand_ai", "brand_ai.edit")
    assert route_module("POST", f"{base}/apply") == ("brand_ai", "brand_ai.edit")


def test_leitor_nao_importa_nem_aplica():
    deny = AsyncMock(side_effect=HTTPException(status_code=403))
    with patch.object(studio, "require_client_role", deny), \
         patch("services.brand_import.preview", AsyncMock()) as prev, patch("services.brand_import.apply", AsyncMock()) as app:
        with pytest.raises(HTTPException):
            run(studio.brand_import_preview("aurora", studio.BrandImportPreviewInput(document_id=DOC["id"]), authorization="Bearer leitor"))
        with pytest.raises(HTTPException):
            body = studio.BrandImportApplyInput(fields={"segment": {"value": "Cafés"}}, confirm=True)
            run(studio.brand_import_apply("aurora", body, authorization="Bearer leitor"))
    prev.assert_not_awaited()
    app.assert_not_awaited()


def test_aplicar_exige_confirmacao_explicita():
    with pytest.raises(ValidationError):
        studio.BrandImportApplyInput(fields={"segment": {"value": "Cafés"}}, confirm=False)
    with pytest.raises(ValidationError):
        studio.BrandImportApplyInput(fields={"segment": {"value": "Cafés"}})


def test_rota_usa_a_empresa_autorizada_e_traduz_erro_de_pesos():
    with patch.object(studio, "require_client_role", AsyncMock(return_value="aurora")), \
         patch.object(studio, "require_user_id", AsyncMock(return_value="u1")), \
         patch("services.brand_import.apply", AsyncMock(side_effect=StudioError("PILLARS_WEIGHT_TOTAL", "Os pesos somam 80%. Ajuste para 100% antes de aplicar."))) as app:
        body = studio.BrandImportApplyInput(fields={"pillars": {"value": [{"name": "A", "weight": 80}]}}, confirm=True)
        with pytest.raises(HTTPException) as err:
            run(studio.brand_import_apply("outra-marca", body, authorization="Bearer x"))
    assert app.await_args.args[0] == "aurora"
    assert err.value.status_code == 422
    assert "80%" in err.value.detail


def test_previa_respeita_o_limite_de_chamadas_de_ia():
    with patch.object(studio, "require_client_role", AsyncMock(return_value="aurora")), \
         patch("services.studio_engines.throttle", side_effect=StudioError("AI_RATE_LIMIT")), \
         patch("services.brand_import.preview", AsyncMock()) as prev:
        with pytest.raises(HTTPException) as err:
            run(studio.brand_import_preview("aurora", studio.BrandImportPreviewInput(document_id=DOC["id"]), authorization="Bearer x"))
    assert err.value.status_code == 429
    prev.assert_not_awaited()
