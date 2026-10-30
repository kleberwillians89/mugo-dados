"""
Redação de campanha (trazida do iAgência) — só a equipe Mugô usa.

Briefing -> pacote de peças pela IA, com o Perfil de Marca e os dados reais da conta (posts que
alcançaram, campanhas que venderam, Origem das vendas). Limites de caracteres são conferidos AQUI,
não confiados à IA: cada peça volta com contagem e alerta. Clichês e palavras proibidas da marca
viram ``flags`` para a revisão.

Só os posts (post, Reels e Stories) vão para o Calendário e seguem a aprovação do cliente; os
anúncios, o WhatsApp e o e-mail ficam com a equipe (copiar e subir).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select, sb_update
from .studio_calendar import StudioError, create_item, load_profile
from .studio_engines import throttle
from .studio_intelligence import build_content_intelligence, to_prompt
from .studio_llm import INT, STR, arr, flag_words, llm_json, obj

CAMPAIGNS = "studio_campaigns"
CHANNELS = ("meta_ads", "google_ads", "post", "reels", "stories", "whatsapp", "email")
CHANNEL_LABELS = {"meta_ads": "Anúncio Meta", "google_ads": "Anúncio Google", "post": "Post do feed", "reels": "Reels",
                  "stories": "Stories", "whatsapp": "WhatsApp", "email": "E-mail"}
# Limites oficiais (Google Ads RSA) e recomendados (Meta) para o texto não ser cortado.
LIMITS = {"google_title": 30, "google_description": 90, "meta_headline": 40, "meta_description": 30,
          "meta_primary": 125, "email_subject": 60, "email_preheader": 90, "whatsapp": 1000}
CALENDAR_CHANNELS = ("post", "reels", "stories")

SCENE = obj({"segundos": STR, "visual": STR, "texto_tela": STR, "narracao": STR})
CHANNEL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "meta_ads": arr(obj({"angulo": STR, "texto_principal": STR, "titulo": STR, "descricao": STR, "cta": STR})),
    "google_ads": obj({"titulos": arr(STR), "descricoes": arr(STR)}),
    "post": obj({"legenda": STR, "cta": STR, "ideia_visual": STR}),
    "reels": obj({"duracao_segundos": INT, "gancho": STR, "texto_capa": STR, "cenas": arr(SCENE), "cta": STR}),
    "stories": arr(obj({"quadro": INT, "texto": STR, "visual": STR, "acao": STR})),
    "whatsapp": obj({"mensagem": STR}),
    "email": obj({"assunto": STR, "preheader": STR, "corpo": STR}),
}
CHANNEL_TASKS = {
    "meta_ads": "2 anúncios Meta com ângulos diferentes: texto principal (até 125 caracteres antes do 'ver mais'), título até 40, descrição até 30, CTA do botão.",
    "google_ads": "Anúncio responsivo de pesquisa Google: EXATAMENTE 10 títulos de até 30 caracteres e 4 descrições de até 90. Conte os caracteres.",
    "post": "Post do feed: legenda com abertura forte, corpo curto e CTA; descreva a ideia visual.",
    "reels": "Roteiro de Reels de 15 a 30 s: gancho na 1ª cena, cenas com tempo ('0-3s'), visual, texto na tela e narração; texto de capa; CTA.",
    "stories": "Sequência de 3 a 5 Stories: texto de cada quadro, visual e ação (enquete, caixinha, link, contagem regressiva).",
    "whatsapp": "Mensagem de WhatsApp para a base de clientes: curta, pessoal, com o CTA e sem parecer spam.",
    "email": "E-mail: assunto até 60 caracteres, preheader até 90 e corpo curto em parágrafos, com o CTA.",
}
ROLE = ("Você é redator publicitário sênior e estrategista de campanha de uma agência. Escreve a campanha para a marca "
        "descrita nos DADOS, a partir do que já vendeu e do que o cliente aprovou, respeitando o briefing.")


def _clip(value: Any, limit: int = 4000) -> str:
    return re.sub(r"\s*[—–]\s*", ", ", str(value or "")).strip()[:limit]


def normalize_briefing(data: Dict[str, Any]) -> Dict[str, Any]:
    channels = [c for c in (data.get("channels") or []) if c in CHANNELS]
    brief = {"name": _clip(data.get("name"), 160), "objective": _clip(data.get("objective"), 400),
             "offer": _clip(data.get("offer"), 600), "audience": _clip(data.get("audience"), 400),
             "start": str(data.get("start") or "")[:10], "end": str(data.get("end") or "")[:10],
             "notes": _clip(data.get("notes"), 1000), "channels": channels or ["post", "reels", "meta_ads"]}
    if not brief["name"] or not brief["objective"]:
        raise StudioError("BRIEFING_REQUIRED")
    for key in ("start", "end"):
        if brief[key]:
            try:
                date.fromisoformat(brief[key])
            except ValueError:
                raise StudioError("BRIEFING_DATE_INVALID") from None
    return brief


def check_limits(channel: str, content: Any) -> List[Dict[str, Any]]:
    """Cada texto com limite volta com o tamanho; acima do limite vira alerta na tela."""
    out: List[Dict[str, Any]] = []

    def add(field: str, text: str, limit: int, index: Optional[int] = None) -> None:
        n = len(text or "")
        out.append({"field": field, "index": index, "length": n, "limit": limit, "over": n > limit})
    if channel == "google_ads" and isinstance(content, dict):
        for i, t in enumerate(content.get("titulos") or []):
            add("titulos", t, LIMITS["google_title"], i)
        for i, d in enumerate(content.get("descricoes") or []):
            add("descricoes", d, LIMITS["google_description"], i)
    elif channel == "meta_ads" and isinstance(content, list):
        for i, ad in enumerate(content):
            add("titulo", ad.get("titulo", ""), LIMITS["meta_headline"], i)
            add("descricao", ad.get("descricao", ""), LIMITS["meta_description"], i)
            add("texto_principal", ad.get("texto_principal", ""), LIMITS["meta_primary"], i)
    elif channel == "email" and isinstance(content, dict):
        add("assunto", content.get("assunto", ""), LIMITS["email_subject"])
        add("preheader", content.get("preheader", ""), LIMITS["email_preheader"])
    elif channel == "whatsapp" and isinstance(content, dict):
        add("mensagem", content.get("mensagem", ""), LIMITS["whatsapp"])
    return out


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def _piece(channel: str, content: Any, avoid: List[str]) -> Dict[str, Any]:
    if channel == "google_ads" and isinstance(content, dict):
        content = {"titulos": [t for t in content.get("titulos") or [] if t][:15], "descricoes": [d for d in content.get("descricoes") or [] if d][:4]}
    return {"channel": channel, "label": CHANNEL_LABELS[channel], "content": content, "limits": check_limits(channel, content),
            "flags": flag_words(json.dumps(content, ensure_ascii=False), avoid)}


async def _context(client_id: str) -> Dict[str, Any]:
    intel = await build_content_intelligence(client_id)
    profile = (await load_profile(client_id))["profile"]
    sales: Dict[str, Any] = {}
    try:
        from .studio_messages import _store_sales
        today = datetime.now(timezone.utc).date()
        sales = await _store_sales(client_id, today - timedelta(days=30), today - timedelta(days=1), {})
    except Exception as exc:  # noqa: BLE001 — sem origem das vendas a campanha sai só com o resto dos dados
        print(f"[studio][campaign] client_id={client_id} sales_context_failed={type(exc).__name__}")
    return {"intel": intel, "avoid": list(profile.get("keywords_avoid") or []),
            "sales": {k: sales.get(k) for k in ("revenue", "orders", "top_campaign", "channels")} if sales else {}}


async def generate(client_id: str, briefing: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    brief = normalize_briefing(briefing)
    throttle(client_id)
    ctx = await _context(client_id)
    channels = brief["channels"]
    schema = obj({"conceito": obj({"nome": STR, "ideia": STR, "por_que": STR}), "titulos": arr(STR),
                  **{c: CHANNEL_SCHEMAS[c] for c in channels}})
    prompt = (f"BRIEFING:\n{json.dumps({k: v for k, v in brief.items() if k != 'channels'}, ensure_ascii=False)}\n"
              f"\nPEÇAS PEDIDAS:\n" + "\n".join(f"- {c}: {CHANNEL_TASKS[c]}" for c in channels)
              + "\n\nAlém das peças: o conceito da campanha (nome, ideia em 2 frases e por que funciona, citando um dado) "
                "e 3 títulos de campanha. Sem travessão."
              + f"\n\nVENDAS DOS ÚLTIMOS 30 DIAS (Origem das vendas):\n{json.dumps(ctx['sales'], ensure_ascii=False, default=str)}"
              + f"\n\nDADOS DA MARCA:\n{to_prompt(ctx['intel'])}")
    data = _clean(await llm_json(instructions=ROLE, prompt=prompt, schema_name="studio_campaign", schema=schema, temperature=0.7, timeout=120))
    package = {"concept": data.get("conceito") or {}, "titles": (data.get("titulos") or [])[:3],
               "pieces": {c: _piece(c, data.get(c), ctx["avoid"]) for c in channels},
               "generated_at": datetime.now(timezone.utc).isoformat()}
    row = await sb_insert(CAMPAIGNS, {"client_id": client_id, "name": brief["name"], "briefing": brief, "package": package,
                                      "created_by": user_id})
    return row or {"briefing": brief, "package": package}


async def regenerate_piece(client_id: str, campaign_id: str, channel: str, *, instruction: Optional[str]) -> Dict[str, Any]:
    if channel not in CHANNELS:
        raise StudioError("CHANNEL_INVALID")
    campaign = await get_campaign(client_id, campaign_id)
    throttle(client_id)
    ctx = await _context(client_id)
    current = (campaign["package"].get("pieces") or {}).get(channel, {}).get("content")
    prompt = (f"BRIEFING:\n{json.dumps(campaign['briefing'], ensure_ascii=False)}\n"
              f"CONCEITO:\n{json.dumps(campaign['package'].get('concept') or {}, ensure_ascii=False)}\n"
              f"PEÇA: {channel}: {CHANNEL_TASKS[channel]}\n"
              f"VERSÃO ATUAL (reescreva com outro ângulo):\n{json.dumps(current, ensure_ascii=False)}\n"
              + (f"PEDIDO DA EQUIPE: {_clip(instruction, 600)}\n" if instruction and instruction.strip() else "")
              + f"\nDADOS DA MARCA:\n{to_prompt(ctx['intel'])}")
    data = _clean(await llm_json(instructions=ROLE, prompt=prompt, schema_name=f"studio_campaign_{channel}",
                                 schema=obj({"peca": CHANNEL_SCHEMAS[channel]}), temperature=0.8))
    package = dict(campaign["package"])
    package["pieces"] = {**(package.get("pieces") or {}), channel: _piece(channel, data.get("peca"), ctx["avoid"])}
    return await _save_package(client_id, campaign_id, package)


async def get_campaign(client_id: str, campaign_id: str) -> Dict[str, Any]:
    rows = await sb_select(CAMPAIGNS, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"}, limit=1)
    if not rows:
        raise StudioError("CAMPAIGN_NOT_FOUND")
    return rows[0]


async def list_campaigns(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(CAMPAIGNS, select="id,name,status,briefing,created_at,updated_at,calendar_item_ids",
                           filters={"client_id": f"eq.{client_id}", "status": "neq.arquivada"}, order="created_at.desc", limit=50)


async def _save_package(client_id: str, campaign_id: str, package: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    rows = await sb_update(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"},
                           patch={"package": package, "updated_at": datetime.now(timezone.utc).isoformat(), **extra})
    if not rows:
        raise StudioError("CAMPAIGN_NOT_FOUND")
    return rows[0]


async def edit_piece(client_id: str, campaign_id: str, channel: str, content: Any) -> Dict[str, Any]:
    """A equipe edita o texto à mão: os limites são recalculados no servidor."""
    if channel not in CHANNELS:
        raise StudioError("CHANNEL_INVALID")
    campaign = await get_campaign(client_id, campaign_id)
    pieces = dict(campaign["package"].get("pieces") or {})
    if channel not in pieces:
        raise StudioError("CHANNEL_INVALID")
    profile = (await load_profile(client_id))["profile"]
    pieces[channel] = {**_piece(channel, _clean(content), list(profile.get("keywords_avoid") or [])), "edited": True}
    return await _save_package(client_id, campaign_id, {**campaign["package"], "pieces": pieces})


async def set_status(client_id: str, campaign_id: str, status: str) -> Dict[str, Any]:
    if status not in ("rascunho", "pronta", "arquivada"):
        raise StudioError("STATUS_INVALID")
    rows = await sb_update(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"},
                           patch={"status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise StudioError("CAMPAIGN_NOT_FOUND")
    return rows[0]


def _calendar_rows(campaign: Dict[str, Any]) -> List[Dict[str, Any]]:
    brief, pieces = campaign["briefing"], campaign["package"].get("pieces") or {}
    start = date.fromisoformat(brief["start"]) if brief.get("start") else datetime.now(timezone.utc).date() + timedelta(days=3)
    name = brief.get("name") or campaign.get("name") or "Campanha"
    why = f"Campanha {name}: {(campaign['package'].get('concept') or {}).get('ideia', '')}"[:1200]
    rows: List[Dict[str, Any]] = []
    post = (pieces.get("post") or {}).get("content")
    if isinstance(post, dict) and post.get("legenda"):
        rows.append({"scheduled_at": f"{(start + timedelta(days=1)).isoformat()}T19:00:00-03:00", "format": "imagem",
                     "title": f"{name}: post"[:200], "hook": None,
                     "caption_draft": "\n\n".join(x for x in (post.get("legenda"), post.get("cta")) if x)[:4000],
                     "rationale": f"{why} Ideia visual: {post.get('ideia_visual', '')}"[:1200], "pillar": name[:120]})
    reels = (pieces.get("reels") or {}).get("content")
    if isinstance(reels, dict) and reels.get("cenas"):
        script = "\n".join(f"[{c.get('segundos')}] {c.get('visual')} | Tela: {c.get('texto_tela')} | Narração: {c.get('narracao')}"
                           for c in reels["cenas"])
        rows.append({"scheduled_at": f"{start.isoformat()}T19:00:00-03:00", "format": "reels", "title": f"{name}: Reels"[:200],
                     "hook": (reels.get("gancho") or "")[:400] or None, "caption_draft": f"{script}\n\nCTA: {reels.get('cta', '')}"[:4000],
                     "rationale": why, "pillar": name[:120]})
    stories = (pieces.get("stories") or {}).get("content")
    if isinstance(stories, list) and stories:
        seq = "\n".join(f"Quadro {s.get('quadro')}: {s.get('texto')} ({s.get('visual')}; ação: {s.get('acao')})" for s in stories)
        rows.append({"scheduled_at": f"{start.isoformat()}T12:00:00-03:00", "format": "stories", "title": f"{name}: Stories"[:200],
                     "hook": None, "caption_draft": seq[:4000], "rationale": why, "pillar": name[:120]})
    return rows


async def to_calendar(client_id: str, campaign_id: str, *, user_id: str) -> Dict[str, Any]:
    """Posts, Reels e Stories viram rascunho no Calendário (e seguem a aprovação de sempre). Não duplica."""
    campaign = await get_campaign(client_id, campaign_id)
    if campaign.get("calendar_item_ids"):
        return {"created": 0, "calendar_item_ids": campaign["calendar_item_ids"], "already": True}
    rows = _calendar_rows(campaign)
    if not rows:
        raise StudioError("NOTHING_FOR_CALENDAR")
    ids = []
    for row in rows:
        item = await create_item(client_id, row, user_id=user_id)
        ids.append(item.get("id"))
    await sb_update(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"},
                    patch={"calendar_item_ids": [i for i in ids if i], "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"created": len(ids), "calendar_item_ids": ids, "already": False}
