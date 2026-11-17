"""Marca que aprende: WhatsApp e documentos nos prompts, aprender com o uso, saúde do contexto e OCR.

Sem chamada real de IA: ``llm_json`` é sempre simulado."""
import asyncio
import base64
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from routes import studio
from services import brand_context_health as health_mod
from services import brand_learning as bl
from services import brand_ocr
from services import brand_signals as bs
from services import studio_intelligence as si
from services.studio_calendar import StudioError, normalize_profile
from services.team_access import route_module


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- WhatsApp → pacote da IA

WA_ROWS = [
    {"text": "Oi, bom dia", "thread_id": "t1"},
    {"text": "Vocês entregam em Campinas? Qual o prazo?", "thread_id": "t1"},
    {"text": "Qual o prazo de entrega para Campinas?", "thread_id": "t2"},
    {"text": "vocês entregam em campinas? qual o prazo?", "thread_id": "t3"},  # repetida (sem acento/maiúscula)
    {"text": "Meu telefone é 11 98765-4321, me liga", "thread_id": "t4"},       # dado pessoal: sai inteiro
    {"text": "Tem o perfume de baunilha em 50ml?", "thread_id": "t5"},
    {"text": "Quero saber do frete do perfume", "thread_id": "t5"},
    {"text": "ok obrigado", "thread_id": "t5"},
]


def test_whatsapp_vira_perguntas_sem_dado_de_pessoa():
    out = bs.summarize_whatsapp(WA_ROWS)
    assert out["mensagens_recebidas"] == 8 and out["conversas"] == 5
    questions = out["perguntas_recentes"]
    assert "Vocês entregam em Campinas? Qual o prazo?" in questions
    assert "Tem o perfume de baunilha em 50ml?" in questions
    assert sum("campinas" in q.lower() and "vocês entregam" in q.lower() for q in questions) == 1
    assert not any("98765" in q for q in questions)
    assert "perfume" in out["assuntos_mais_citados"]
    assert bs.summarize_whatsapp([]) == {}


def test_pacote_da_ia_tem_whatsapp_e_ele_vai_no_prompt():
    async def select(table, select="*", filters=None, order=None, limit=None, offset=None):
        if table == "whatsapp_messages":
            assert filters["client_id"] == "eq.ruah" and filters["direction"] == "eq.in"
            return WA_ROWS
        return []
    with patch.object(bs, "sb_select", select):
        section = run(si._whatsapp("ruah"))
    assert section["perguntas_recentes"]
    text = si.to_prompt({"marca": {"tone_of_voice": "leve"}, "whatsapp": section})
    assert "perguntas_recentes" in text
    assert "whatsapp" in si.PROMPT_ORDER
    assert "whatsapp" in si.PLANS_RULE


def test_whatsapp_indisponivel_nao_derruba():
    with patch.object(bs, "sb_select", AsyncMock(side_effect=RuntimeError("sem tabela"))):
        assert run(bs.whatsapp_section("ruah")) == {}


def test_trechos_dos_documentos_levam_o_nome_do_documento():
    rows = [{"document_id": "d1", "content": "Pilares: Origem (40%), Preparo (35%)."}, {"document_id": "d9", "content": "Sem nome guardado."}]

    async def select(table, select="*", filters=None, order=None, limit=None, offset=None):
        assert table == "brand_documents" and filters["client_id"] == "eq.aurora"
        return [{"id": "d1", "name": "Planejamento Aurora 2027.pdf"}]
    with patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=rows)), patch.object(si, "sb_select", select):
        text = run(si.passages_for("aurora", "pilares"))
    assert "- [Planejamento Aurora 2027.pdf] Pilares: Origem (40%)" in text
    assert "- Sem nome guardado." in text


def test_briefing_usa_trechos_dos_documentos_ligados_ao_pedido():
    from services import studio_briefs
    llm = AsyncMock(return_value={})
    with patch("services.studio_engines.throttle"), \
         patch.object(studio_briefs, "load_profile", AsyncMock(return_value={"profile": normalize_profile({})})), \
         patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={"marca": {"tone_of_voice": "leve"}})), \
         patch("services.studio_intelligence.passages_for", AsyncMock(return_value="- [Brand book] Nunca usar a palavra barato.")) as passages, \
         patch("services.studio_llm.llm_json", llm):
        with pytest.raises(StudioError):  # resposta vazia da IA simulada: o que importa aqui é o prompt
            run(studio_briefs.generate_brief("aurora", "Campanha de Natal com foco em presente", []))
    assert passages.await_args.args[0] == "aurora"
    prompt = llm.await_args.kwargs["prompt"]
    assert "TRECHOS DOS DOCUMENTOS DA MARCA" in prompt and "Nunca usar a palavra barato" in prompt
    assert "palavras a evitar" in prompt


# ---------------------------------------------------------------- aprender com o uso

SIGNALS = {"desde": "2026-10-01T00:00:00+00:00",
           "ajustes_pedidos": [{"pauta": "Post Natal", "pedido": "Tirem os emojis, a marca não usa"},
                               {"pauta": "Post Dia das Mães", "pedido": "Sem emoji, por favor"}],
           "comentarios_do_cliente": [], "textos_reescritos_pelo_cliente": [], "aprovados_pelo_cliente": [],
           "whatsapp": {"perguntas_recentes": ["Qual o prazo de entrega para Campinas?"]}}


def test_sugestao_limpa_repetidos_e_o_que_a_memoria_ja_sabe():
    data = {"fatos": [
        {"fato": "A marca não usa emojis nas legendas.", "origem": "ajuste", "evidencia": "Tirem os emojis", "confianca": "alta"},
        {"fato": "a marca não usa emojis nas legendas", "origem": "ajuste", "evidencia": "", "confianca": "media"},
        {"fato": "Tom leve e sensorial.", "origem": "comentario", "evidencia": "", "confianca": "media"},
        {"fato": "Curto", "origem": "ajuste", "evidencia": "", "confianca": "alta"},
        {"fato": "Clientes perguntam muito do prazo de entrega.", "origem": "inventada", "evidencia": "", "confianca": "alta"},
        {"fato": "Os clientes perguntam com frequência sobre prazo de entrega.", "origem": "whatsapp", "evidencia": "Qual o prazo", "confianca": "media"},
    ]}
    facts = bl.clean_facts(data, "Empresa: Aurora\n- Tom leve e sensorial.")
    assert [f["fato"] for f in facts] == ["A marca não usa emojis nas legendas.", "Os clientes perguntam com frequência sobre prazo de entrega."]
    assert facts[1]["origem_rotulo"] == "Perguntas no WhatsApp"


def test_sugestao_chama_a_ia_uma_vez_e_nao_grava():
    llm = AsyncMock(return_value={"fatos": [{"fato": "A marca não usa emojis nas legendas.", "origem": "ajuste", "evidencia": "Tirem os emojis", "confianca": "alta"}]})
    with patch.object(bl, "last_learning_at", AsyncMock(return_value=None)), patch.object(bl, "usage_signals", AsyncMock(return_value=SIGNALS)), \
         patch("services.brand_knowledge.load_knowledge", AsyncMock(return_value={"knowledge": "Empresa: Aurora", "sources": 1})), \
         patch("services.studio_llm.llm_json", llm), patch("services.brand_knowledge.add_facts", AsyncMock()) as add:
        out = run(bl.suggest("aurora"))
    llm.assert_awaited_once()
    assert llm.await_args.kwargs["client_id"] == "aurora" and "model" not in llm.await_args.kwargs
    assert "Tirem os emojis" in llm.await_args.kwargs["prompt"] and "Campinas" in llm.await_args.kwargs["prompt"]
    assert out["facts"][0]["fato"].startswith("A marca não usa emojis")
    add.assert_not_awaited()


def test_sem_sinais_suficientes_nao_chama_a_ia():
    empty = {**SIGNALS, "ajustes_pedidos": [], "whatsapp": {}}
    with patch.object(bl, "last_learning_at", AsyncMock(return_value=None)), patch.object(bl, "usage_signals", AsyncMock(return_value=empty)), \
         patch("services.studio_llm.llm_json", AsyncMock()) as llm:
        out = run(bl.suggest("aurora"))
    llm.assert_not_awaited()
    assert out["facts"] == [] and out["message"]


def test_confirmar_grava_em_lotes_e_marca_o_aprendizado():
    batches = []

    async def add_facts(cid, facts, user_id):
        batches.append(list(facts))
        return {"document": {"id": f"doc{len(batches)}"}, "knowledge": "x", "sources": 2}
    mark = AsyncMock()
    facts = [f"Fato número {i} sobre a marca" for i in range(7)]
    with patch("services.brand_knowledge.add_facts", add_facts), patch("services.brand_knowledge._mark", mark):
        out = run(bl.confirm("aurora", facts, user_id="u1"))
    assert [len(b) for b in batches] == [5, 2]
    assert out["saved"] == 7
    assert mark.await_count == 2
    assert mark.await_args.args[2]["name"].startswith(bs.LEARNING_PREFIX)


def test_ultimo_aprendizado_e_lido_pelo_nome_marcado():
    sel = AsyncMock(return_value=[{"created_at": "2026-11-01T10:00:00+00:00"}])
    with patch.object(bs, "sb_select", sel):
        assert run(bs.last_learning_at("aurora")) == "2026-11-01T10:00:00+00:00"
    assert sel.await_args.kwargs["filters"] == {"client_id": "eq.aurora", "name": f"like.{bs.LEARNING_PREFIX}*"}


def test_sinais_de_uso_so_da_empresa_e_desde_o_ultimo_aprendizado():
    seen = []

    async def select(table, select="*", filters=None, order=None, limit=None, offset=None):
        seen.append((table, filters))
        if table == "studio_calendar_items" and filters.get("status") == "eq.rejeitado":
            return [{"title": "Post", "review_note": "Sem emoji"}, {"title": "Post 2", "review_note": "Ligue 11 98765-4321"}]
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with patch.object(bs, "sb_select", select):
        out = run(bs.usage_signals("aurora", since=since))
    assert all(f["client_id"] == "eq.aurora" for _, f in seen)
    assert out["desde"] == since
    assert out["ajustes_pedidos"] == [{"pauta": "Post", "pedido": "Sem emoji"}]  # o com telefone sai


# ---------------------------------------------------------------- saúde do contexto

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def _eval(**over):
    base = dict(profile=normalize_profile({"tone_of_voice": "Leve", "audience": "Mulheres", "personality": "Sofisticada",
                                            "pillars": [{"name": "A", "weight": 60}, {"name": "B", "weight": 40}]}),
                profile_saved=True, business={f"f{i}": "x" for i in range(6)}, knowledge="Empresa: X", knowledge_max=6000,
                documents=[{"kind": "institucional", "status": "aprendido", "created_at": "2026-10-01T00:00:00+00:00"}],
                competitors=3, new_signals=0, now=NOW)
    base.update(over)
    return health_mod.evaluate(**base)


def test_contexto_completo_fica_em_100():
    out = _eval()
    assert out["score"] == 100
    assert all(i["level"] == "ok" for i in out["items"])


def test_saude_aponta_o_que_falta_e_o_que_esta_velho():
    out = _eval(profile=normalize_profile({"pillars": [{"name": "A", "weight": 70}]}), business={},
                documents=[{"kind": "institucional", "status": "falhou", "created_at": "2026-01-01T00:00:00+00:00"}],
                knowledge="", competitors=0, new_signals=5)
    by = {i["id"]: i for i in out["items"]}
    assert by["perfil"]["level"] == "falta" and "tom de voz" in by["perfil"]["detail"]
    assert by["pesos"]["level"] == "atencao" and "70%" in by["pesos"]["detail"]
    assert by["negocio"]["level"] == "falta"
    assert by["documentos"]["level"] == "atencao" and "dias" in by["documentos"]["detail"]
    assert by["falhas"]["level"] == "atencao"
    assert by["memoria"]["level"] == "falta"
    assert by["concorrentes"]["action"] == {"route": "benchmark"}
    assert by["aprender"]["title"].startswith("5 sinais")
    assert out["score"] < 40
    assert out["items"][0]["level"] == "falta"  # o mais grave primeiro


def test_sem_documento_e_falta():
    by = {i["id"]: i for i in _eval(documents=[])["items"]}
    assert by["documentos"]["level"] == "falta" and by["documentos"]["action"] == {"tab": "documentos"}


# ---------------------------------------------------------------- OCR (PDF escaneado)

def _scanned_pdf(pages=2, size=(1240, 1754)):
    from PIL import Image, ImageDraw
    images = []
    for n in range(pages):
        img = Image.new("RGB", size, "white")
        ImageDraw.Draw(img).text((100, 100), f"Pagina {n + 1}: Tom de voz acolhedor", fill="black")
        images.append(img)
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
    return buf.getvalue()


def test_grade_de_recortes_cabe_no_limite():
    assert brand_ocr.grid(1400, 1980) == (2, 4)   # A4 retrato
    assert brand_ocr.grid(1400, 787) == (2, 2)    # slide
    assert brand_ocr.grid(1401, 1981) == (2, 4)   # arredondamento da renderização
    cols, rows = brand_ocr.grid(1400, 9000)
    assert cols * rows <= brand_ocr.MAX_TILES


def test_ocr_le_cada_pagina_em_recortes_e_junta_o_texto():
    llm = AsyncMock(side_effect=lambda **kw: {"texto": f"Texto transcrito da {kw['prompt'][:9]}"})
    with patch("services.studio_llm.llm_json", llm):
        out = run(brand_ocr.ocr_pdf("aurora", _scanned_pdf(3)))
    assert llm.await_count == 3
    call = llm.await_args_list[0].kwargs
    assert call["client_id"] == "aurora" and "model" not in call
    assert len(call["images"]) == 8 and call["images"][0].startswith("data:image/jpeg;base64,")
    assert out["pages_read"] == 3 and out["pages_total"] == 3 and not out["partial"]
    assert "[Página 1]" in out["text"] and "[Página 3]" in out["text"]


def test_ocr_respeita_limite_de_paginas_e_pagina_com_falha():
    calls = {"n": 0}

    async def llm(**kw):
        calls["n"] += 1
        if "Página 2" in kw["prompt"]:
            raise StudioError("AI_PROVIDER_TIMEOUT")
        return {"texto": "Texto legível da página com mais de vinte caracteres."}
    with patch("services.studio_llm.llm_json", llm):
        out = run(brand_ocr.ocr_pdf("aurora", _scanned_pdf(4, size=(600, 800)), max_pages=3))
    assert calls["n"] == 3
    assert out["pages_read"] == 2 and out["pages_total"] == 4 and out["partial"]


def test_pdf_sem_texto_oferece_ocr_e_ocr_so_no_pedido():
    raw = _scanned_pdf(1)
    body = studio.KnowledgeDocInput(file_name="brandbook.pdf", kind="institucional", content_base64=base64.b64encode(raw).decode())
    with patch.object(studio, "require_client_role", AsyncMock(return_value="aurora")), \
         patch.object(studio, "require_user_id", AsyncMock(return_value="u1")), \
         patch("services.brand_ocr.ocr_pdf", AsyncMock()) as ocr, patch("services.brand_knowledge.learn", AsyncMock()) as learn:
        with pytest.raises(HTTPException) as err:
            run(studio.add_knowledge_document("aurora", body, authorization="Bearer x"))
    assert err.value.status_code == 422 and err.value.detail["code"] == "DOC_NEEDS_OCR"
    ocr.assert_not_awaited()
    learn.assert_not_awaited()

    body.ocr = True
    with patch.object(studio, "require_client_role", AsyncMock(return_value="aurora")), \
         patch.object(studio, "require_user_id", AsyncMock(return_value="u1")), patch("services.studio_engines.throttle"), \
         patch("services.brand_ocr.ocr_pdf", AsyncMock(return_value={"text": "[Página 1]\nTom de voz acolhedor e próximo.", "pages_read": 1,
                                                                    "pages_total": 1, "pages_limit": 20, "partial": False})), \
         patch("services.brand_knowledge.learn", AsyncMock(return_value={"document": {"id": "d1"}, "knowledge": "k", "sources": 1})) as learn:
        out = run(studio.add_knowledge_document("aurora", body, authorization="Bearer x"))
    assert "Tom de voz acolhedor" in learn.await_args.kwargs["text"]
    assert out["ocr"]["pages_read"] == 1 and "text" not in out["ocr"]


def test_ocr_so_para_pdf():
    body = studio.KnowledgeDocInput(file_name="deck.pptx", content_base64=base64.b64encode(b"x" * 100).decode(), ocr=True)
    with patch.object(studio, "require_client_role", AsyncMock(return_value="aurora")), \
         patch.object(studio, "require_user_id", AsyncMock(return_value="u1")):
        with pytest.raises(HTTPException) as err:
            run(studio.add_knowledge_document("aurora", body, authorization="Bearer x"))
    assert err.value.status_code == 422


# ---------------------------------------------------------------- rotas: permissão e empresa

def test_rotas_novas_seguem_o_modulo_da_marca():
    base = "/api/clients/aurora/studio/knowledge"
    assert route_module("GET", f"{base}/health") == ("brand_ai", "brand_ai.view")
    assert route_module("POST", f"{base}/learn/suggest") == ("brand_ai", "brand_ai.edit")
    assert route_module("POST", f"{base}/learn/confirm") == ("brand_ai", "brand_ai.edit")


def test_leitor_nao_aprende_nem_grava():
    deny = AsyncMock(side_effect=HTTPException(status_code=403))
    with patch.object(studio, "require_client_role", deny), \
         patch("services.brand_learning.suggest", AsyncMock()) as sug, patch("services.brand_learning.confirm", AsyncMock()) as conf:
        with pytest.raises(HTTPException):
            run(studio.brand_learning_suggest("aurora", authorization="Bearer leitor"))
        with pytest.raises(HTTPException):
            run(studio.brand_learning_confirm("aurora", studio.LearningConfirmInput(facts=["A marca não usa emoji."]), authorization="Bearer leitor"))
    sug.assert_not_awaited()
    conf.assert_not_awaited()


def test_saude_usa_a_empresa_autorizada():
    with patch.object(studio, "require_client_read", AsyncMock(return_value="aurora")), \
         patch("services.brand_context_health.health", AsyncMock(return_value={"score": 50, "items": [], "learning": {}})) as h:
        run(studio.brand_context_health("outra-marca", authorization="Bearer x"))
    h.assert_awaited_once_with("aurora")
