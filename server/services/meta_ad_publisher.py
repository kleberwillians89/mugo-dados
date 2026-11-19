"""Mídia On → Meta Ads: rascunho completo da campanha (com IA) e publicação PAUSADA na conta do cliente.

Fluxo de publicação (Graph API, conta de anúncios da conexão paga do cliente):
  1. campanha (objetivo + orçamento diário na campanha, status PAUSED)
  2. conjunto de anúncios (público, período, otimização, PAUSED)
  3. imagem (enviada para a conta: image_hash) e criativo (página + Instagram + texto + link + botão)
  4. anúncio (PAUSED)

Nada é ativado aqui: a equipe confere no Gerenciador de Anúncios e liga. Se um passo falha, o que já foi
criado fica guardado no rascunho (pausado, sem gasto) e o erro do Meta aparece na tela.
Exige a permissão ads_management na conexão do Meta (o cliente reconecta uma vez em Integrações).
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .meta_config import META_GRAPH_BASE_URL
from .studio_calendar import StudioError
from .ads_tracking import clean_tracking, tracking_suffix

TABLE = "studio_ad_drafts"
ADS_SCOPE = "ads_management"
MIN_DAILY_BRL = 6.0

# Objetivo do Mídia On → objetivo do Meta (ODAX) + otimização do conjunto.
OBJECTIVES: Dict[str, Dict[str, Any]] = {
    "trafego": {"label": "Tráfego para o site", "objective": "OUTCOME_TRAFFIC", "optimization": "LINK_CLICKS", "destination": "WEBSITE"},
    "alcance": {"label": "Alcance", "objective": "OUTCOME_AWARENESS", "optimization": "REACH"},
    "engajamento": {"label": "Engajamento", "objective": "OUTCOME_ENGAGEMENT", "optimization": "POST_ENGAGEMENT"},
    "vendas": {"label": "Vendas no site (pixel)", "objective": "OUTCOME_SALES", "optimization": "OFFSITE_CONVERSIONS", "event": "PURCHASE", "destination": "WEBSITE"},
    "leads": {"label": "Cadastros no site (pixel)", "objective": "OUTCOME_LEADS", "optimization": "OFFSITE_CONVERSIONS", "event": "LEAD", "destination": "WEBSITE"},
    # Públicos personalizados criados pelo pixel (ou reaproveitados se já existem com o mesmo nome).
    "retencao": {"label": "Retenção: compradores 180 dias (pixel)", "objective": "OUTCOME_SALES", "optimization": "OFFSITE_CONVERSIONS",
                 "event": "PURCHASE", "destination": "WEBSITE", "audience": "compradores_180"},
    "remarketing": {"label": "Remarketing: visitantes do site 30 dias (pixel)", "objective": "OUTCOME_SALES", "optimization": "OFFSITE_CONVERSIONS",
                    "event": "PURCHASE", "destination": "WEBSITE", "audience": "visitantes_30"},
}
AUDIENCES = {
    "compradores_180": {"name": "Mugô · Compradores 180 dias", "days": 180, "event": "Purchase"},
    "visitantes_30": {"name": "Mugô · Visitantes do site 30 dias", "days": 30, "event": None, "exclude": "compradores_180"},
}
CTAS = {"LEARN_MORE": "Saiba mais", "SHOP_NOW": "Comprar agora", "SIGN_UP": "Cadastre-se", "CONTACT_US": "Fale conosco",
        "SEND_WHATSAPP_MESSAGE": "Enviar mensagem no WhatsApp", "GET_OFFER": "Ver oferta", "BOOK_TRAVEL": "Reservar", "SUBSCRIBE": "Assinar"}
GENDERS = {"todos": None, "mulheres": [2], "homens": [1]}
LIMITS = {"name": 120, "primary_text": 2000, "headline": 120, "description": 200, "link": 500, "image_url": 1000}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _ref(value: Any) -> Optional[Dict[str, str]]:
    """Público da conta escolhido na tela: só o id (número do Meta) e o nome para mostrar."""
    if not isinstance(value, dict):
        return None
    audience_id = str(value.get("id") or "").strip()
    if not re.fullmatch(r"\d{5,30}", audience_id):
        return None
    return {"id": audience_id, "name": _text(value.get("name"), 120) or audience_id}


def _refs(value: Any, limit: int = 20) -> List[Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for item in value if isinstance(value, list) else []:
        ref = _ref(item)
        if ref and ref["id"] not in out:
            out[ref["id"]] = ref
    return list(out.values())[:limit]


def _names(value: Any, limit: int = 12) -> List[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    return [s for s in dict.fromkeys(str(i).strip()[:60] for i in items) if s][:limit]


# ---------------------------------------------------------------- rascunho

AD_FORMATS = ("single", "carousel", "multi")
MAX_CARDS = 10


def clean_cards(value: Any) -> List[Dict[str, str]]:
    """Imagens do carrossel (ou dos anúncios separados), na ordem escolhida. Só HTTPS, sem repetir, até 10."""
    cards: List[Dict[str, str]] = []
    seen = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        url = _text(raw.get("image_url"), LIMITS["image_url"])
        if not url.startswith("https://") or url in seen:
            continue
        seen.add(url)
        link = _text(raw.get("link"), LIMITS["link"])
        cards.append({"image_url": url, "headline": _text(raw.get("headline"), 45), "description": _text(raw.get("description"), 20),
                      "link": link if link.startswith(("http://", "https://")) else ""})
        if len(cards) >= MAX_CARDS:
            break
    return cards


MAX_ADS = 10


def clean_creative(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Só a parte visual de um anúncio: imagem única, vídeo ou carrossel."""
    fmt = "carousel" if raw.get("format") == "carousel" else "single"
    return {"format": fmt, "image_url": _text(raw.get("image_url"), LIMITS["image_url"]),
            "media_type": "video" if raw.get("media_type") == "video" and fmt == "single" else "image",
            "video_url": _text(raw.get("video_url"), LIMITS["image_url"]),
            "instagram_post_id": _text(raw.get("instagram_post_id"), 70) or None,
            "calendar_item_id": _text(raw.get("calendar_item_id"), 60) or None,
            "cards": clean_cards(raw.get("cards"))}


def ad_units(ad: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Todos os anúncios que vão para o conjunto, na ordem. O formato antigo "multi" vira um anúncio de imagem por cartão."""
    if ad.get("format") == "multi":
        return [{"format": "single", "image_url": c["image_url"], "media_type": "image", "video_url": "", "cards": [],
                 "headline": c.get("headline") or "", "link": c.get("link") or ""} for c in ad.get("cards") or []]
    first = {"format": ad.get("format") if ad.get("format") == "carousel" else "single", "image_url": ad.get("image_url") or "",
             "media_type": ad.get("media_type") or "image", "video_url": ad.get("video_url") or "", "cards": ad.get("cards") or []}
    return [first, *(ad.get("extra_ads") or [])]


def unit_missing(unit: Dict[str, Any]) -> Optional[str]:
    if unit["format"] == "carousel":
        return None if len(unit["cards"]) >= 2 else "pelo menos 2 imagens no carrossel"
    if unit["media_type"] == "video":
        return None if unit["video_url"].startswith("https://") else "URL HTTPS do vídeo"
    return None if unit["image_url"] else "imagem"


def clean_placements(value: Any) -> Dict[str, Any]:
    """Validate explicit Meta placement filters without silently adding platforms."""
    p = value if isinstance(value, dict) else {}
    mode = str(p.get("mode") or "automatic")
    if mode not in ("automatic", "manual"):
        raise StudioError("AD_PLACEMENTS_INVALID")
    allowed = {"platforms": ("instagram", "facebook"),
               "instagram": ("stream", "story", "reels"),
               "facebook": ("feed", "story", "facebook_reels")}
    result: Dict[str, Any] = {"mode": mode}
    for key, options in allowed.items():
        items = p.get(key, list(options))
        if not isinstance(items, list) or any(not isinstance(x, str) or x not in options for x in items):
            raise StudioError("AD_PLACEMENTS_INVALID")
        result[key] = list(dict.fromkeys(items))
    if mode == "manual" and (not result["platforms"] or any(
        not result[platform] for platform in result["platforms"])):
        raise StudioError("AD_PLACEMENTS_INVALID")
    return result


def clean_payload(data: Dict[str, Any], *, today: Optional[date] = None) -> Dict[str, Any]:
    """Confere e normaliza o rascunho (vale para o que a IA sugere e para o que a equipe edita)."""
    today = today or datetime.now(timezone.utc).date()
    objective = str(data.get("objective") or "trafego")
    if objective not in OBJECTIVES:
        raise StudioError("AD_OBJECTIVE_INVALID")
    try:
        budget = round(float(data.get("daily_budget") or 0), 2)
    except (TypeError, ValueError):
        budget = 0.0
    try:
        start = date.fromisoformat(str(data.get("start_date") or "")[:10])
    except ValueError:
        start = today + timedelta(days=1)
    try:
        end = date.fromisoformat(str(data.get("end_date") or "")[:10])
    except ValueError:
        end = start + timedelta(days=13)
    start = max(start, today)
    if end <= start:
        end = start + timedelta(days=7)
    aud = data.get("audience") if isinstance(data.get("audience"), dict) else {}
    try:
        age_min = max(18, min(65, int(aud.get("age_min") or 18)))
        age_max = max(age_min, min(65, int(aud.get("age_max") or 65)))
    except (TypeError, ValueError):
        age_min, age_max = 18, 65
    gender = str(aud.get("gender") or "todos")
    excluded = _refs(aud.get("excluded_audiences"))
    skip = {a["id"] for a in excluded}  # o mesmo público nos dois lados: vale a exclusão
    ad = data.get("ad") if isinstance(data.get("ad"), dict) else {}
    cta = str(ad.get("cta") or "LEARN_MORE")
    try:
        tracking = clean_tracking(data.get("tracking"))
    except ValueError as exc:
        raise StudioError("AD_NOT_READY", str(exc)) from None
    return {
        "tracking": tracking,
        "name": _text(data.get("name"), LIMITS["name"]) or "Campanha Mídia On",
        "objective": objective,
        "daily_budget": budget,
        "placements": clean_placements(data.get("placements")),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "audience": {"age_min": age_min, "age_max": age_max, "gender": gender if gender in GENDERS else "todos",
                     "regions": _names(aud.get("regions")), "interests": _names(aud.get("interests")),
                     "advantage": bool(aud.get("advantage", True)),
                     # Públicos que já existem na conta de anúncios do cliente (lista em /studio/ads/audiences).
                     "saved_audience": _ref(aud.get("saved_audience")),
                     "custom_audiences": [a for a in _refs(aud.get("custom_audiences")) if a["id"] not in skip],
                     "excluded_audiences": excluded},
        "ad": {"primary_text": _text(ad.get("primary_text"), LIMITS["primary_text"]),
               "headline": _text(ad.get("headline"), LIMITS["headline"]),
               "description": _text(ad.get("description"), LIMITS["description"]),
               "cta": cta if cta in CTAS else "LEARN_MORE",
               "link": _text(ad.get("link"), LIMITS["link"]),
               "image_url": _text(ad.get("image_url"), LIMITS["image_url"]),
               "calendar_item_id": _text(ad.get("calendar_item_id"), 60) or None,
                "media_type": "video" if ad.get("media_type") == "video" else "image",
                "video_url": _text(ad.get("video_url"), LIMITS["image_url"]),
                "instagram_post_id": _text(ad.get("instagram_post_id"), 70) or None,
                # Vários criativos: "carousel" = um anúncio em carrossel; "multi" = um anúncio por imagem no mesmo conjunto.
                "format": ad.get("format") if ad.get("format") in AD_FORMATS else "single",
                "cards": clean_cards(ad.get("cards")),
                # Anúncios 2, 3… do mesmo conjunto (mesma verba), cada um com o seu formato. Texto e link são os do anúncio 1.
                "extra_ads": [clean_creative(x) for x in (ad.get("extra_ads") if isinstance(ad.get("extra_ads"), list) else [])
                              if isinstance(x, dict)][:MAX_ADS - 1]},
    }


def readiness(payload: Dict[str, Any]) -> List[str]:
    """O que falta para publicar (mostrado na tela antes do botão)."""
    missing = []
    if payload["daily_budget"] < MIN_DAILY_BRL:
        missing.append(f"Orçamento diário de pelo menos R$ {MIN_DAILY_BRL:.0f}".replace(".", ","))
    ad = payload["ad"]
    if not ad["primary_text"]:
        missing.append("Texto principal do anúncio")
    units = ad_units(ad)
    if ad["format"] == "multi" and len(units) < 2:
        missing.append("Pelo menos 2 imagens para os anúncios")
    for index, unit in enumerate(units):
        problem = unit_missing(unit)
        if problem:
            label = "Imagem do anúncio" if problem == "imagem" and len(units) == 1 else \
                ("URL HTTPS do vídeo" if problem.startswith("URL") and len(units) == 1 else f"Anúncio {index + 1}: {problem}")
            missing.append(label)
    if OBJECTIVES[payload["objective"]].get("destination") == "WEBSITE" and not ad["link"].startswith(("http://", "https://")):
        missing.append("Link do site (começando com https://)")
    return missing


def _view(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = clean_payload(row.get("payload") or {})
    ids = row.get("meta_ids") or {}
    act = str(ids.get("ad_account_id") or "").removeprefix("act_")
    link = (f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={act}&selected_campaign_ids={ids['campaign_id']}"
            if act and ids.get("campaign_id") else None)
    return {"id": str(row["id"]), "month": row.get("month"), "source_campaign": row.get("source_campaign"), "status": row.get("status"),
            "payload": payload, "missing": readiness(payload), "meta_ids": ids, "ads_manager_url": link, "error": row.get("error"),
            "published_at": row.get("published_at"), "updated_at": row.get("updated_at"), "joined": bool(ids.get("joined"))}


async def list_drafts(client_id: str) -> List[Dict[str, Any]]:
    try:
        rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=50)
    except Exception as exc:  # noqa: BLE001 — tabela ainda não criada
        print(f"[meta_ads_publish] list client_id={client_id} unavailable error_type={type(exc).__name__}")
        raise StudioError("AD_MIGRATION_PENDING") from None
    # Shared draft table: never expose or publish Google drafts as Meta campaigns.
    return [_view(r) for r in rows if (r.get("payload") or {}).get("platform", "meta") == "meta"]


async def _draft(client_id: str, draft_id: str) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}, limit=1)
    if not rows or (rows[0].get("payload") or {}).get("platform", "meta") != "meta":
        raise StudioError("AD_DRAFT_NOT_FOUND")
    return rows[0]


async def _calendar_art(client_id: str, item_id: Optional[str]) -> str:
    if not item_id:
        return ""
    rows = await sb_select("studio_calendar_items", select="art_url", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    first = str((rows[0] if rows else {}).get("art_url") or "").split("\n")[0].strip()
    return first


AD_SCHEMA_KEYS = ("name", "primary_text", "headline", "description", "cta", "age_min", "age_max", "gender", "regions", "interests")


async def generate_draft(client_id: str, *, user_id: str, month: Optional[str], campaign: Dict[str, Any],
                         objective: str, days_left: int) -> Dict[str, Any]:
    """A IA monta a campanha completa a partir da linha do plano do Mídia On e do perfil da marca."""
    from .studio_calendar import language_rule, load_profile
    from .studio_engines import throttle
    from .studio_llm import INT, STR, arr, llm_json, obj
    throttle(client_id)
    profile = (await load_profile(client_id))["profile"]
    rows = await sb_select("client_business_context", select="*", filters={"client_id": f"eq.{client_id}"}, limit=1)
    business = {k: v for k, v in (rows[0] if rows else {}).items() if k not in ("client_id", "id", "created_at", "updated_at", "updated_by") and v}
    obj_key = objective if objective in OBJECTIVES else "trafego"
    from .brand_health import audience_voice
    from .brand_knowledge import knowledge_for_prompt
    voice = await audience_voice(client_id)
    try:
        knowledge = (await knowledge_for_prompt(client_id, 1500)).strip()
    except Exception:  # noqa: BLE001 — memória indisponível não impede o rascunho
        knowledge = ""
    schema = obj({"name": STR, "primary_text": STR, "headline": STR, "description": STR, "cta": STR,
                  "age_min": INT, "age_max": INT, "gender": STR, "regions": arr(STR), "interests": arr(STR)})
    prompt = (f"CAMPANHA DO PLANO (Mídia On): {json.dumps({k: campaign.get(k) for k in ('campaign', 'action', 'why', 'planned_budget')}, ensure_ascii=False)}\n"
              f"OBJETIVO NO META: {OBJECTIVES[obj_key]['label']}\n"
              f"PERFIL DA MARCA: {json.dumps({k: profile.get(k) for k in ('tone_of_voice', 'personality', 'audience', 'keywords_use', 'keywords_avoid', 'restrictions')}, ensure_ascii=False)}\n"
              f"NEGÓCIO: {json.dumps(business, ensure_ascii=False, default=str)[:2500]}\n"
              + (f"CONHECIMENTO DA MARCA (documentos): {knowledge}\n" if knowledge else "")
              + (f"COMO O PÚBLICO FALA DA MARCA (Saúde da marca; use para escolher o gancho, responder o que mais perguntam "
                 f"e não prometer o que gera reclamação): {voice}\n" if voice else "")
              + f"BOTÕES POSSÍVEIS (cta): {', '.join(CTAS)}\n"
              "Monte o anúncio: name (nome interno curto), primary_text (até 3 frases, gancho na primeira, no tom da marca), "
              "headline (até 40 caracteres), description (até 30), cta (um dos botões), público: age_min/age_max (18 a 65), "
              "gender (todos, mulheres ou homens), regions (estados do Brasil só se o negócio for local; senão vazio), "
              "interests (3 a 6 interesses do Meta, em português, ligados ao público). Sem travessão. "
              "Não invente preço, desconto ou prazo que não esteja no NEGÓCIO.\n" + language_rule(profile))
    data = await llm_json(client_id=client_id, instructions="Você é gestor de tráfego sênior de agência e escreve anúncios do Meta Ads.",
                          prompt=prompt, schema_name="meta_ad_draft", schema=schema, temperature=0.6)
    days = max(1, int(days_left or 14))
    planned = float(campaign.get("planned_budget") or 0)
    payload = clean_payload({
        "name": data.get("name") or campaign.get("campaign"), "objective": obj_key,
        "daily_budget": round(planned / days, 2) if planned else 30,
        "start_date": (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(),
        "end_date": (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat(),
        "audience": {"age_min": data.get("age_min"), "age_max": data.get("age_max"), "gender": data.get("gender"),
                     "regions": data.get("regions"), "interests": data.get("interests"), "advantage": True},
        "ad": {"primary_text": data.get("primary_text"), "headline": data.get("headline"), "description": data.get("description"),
               "cta": data.get("cta"), "link": str(business.get("website") or business.get("site") or "")},
    })
    created = await sb_insert(TABLE, {"client_id": client_id, "month": f"{month}-01" if month else None,
                                      "source_campaign": _text(campaign.get("campaign"), 200) or None,
                                      "payload": payload, "status": "rascunho", "created_by": user_id})
    if not created:
        raise StudioError("AD_SAVE_FAILED")
    return _view(created)


async def save_draft(client_id: str, draft_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    row = await _draft(client_id, draft_id)
    if row.get("status") in ("publicando", "publicada"):
        raise StudioError("AD_ALREADY_PUBLISHED")
    payload = clean_payload(data)
    if payload["ad"]["calendar_item_id"] and not payload["ad"]["image_url"]:
        payload["ad"]["image_url"] = await _calendar_art(client_id, payload["ad"]["calendar_item_id"])
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"},
                           patch={"payload": payload, "status": "rascunho", "error": None, "updated_at": _now()})
    return _view(rows[0] if rows else {**row, "payload": payload})


async def duplicate_draft(client_id: str, draft_id: str, user_id: str, *, into_campaign: bool = False) -> Dict[str, Any]:
    """Cópia para testar.
    - padrão: campanha NOVA (verba própria). IDs da Meta, status e erros não passam para a cópia.
    - into_campaign: só um anúncio novo dentro do MESMO conjunto da campanha já criada — mesma verba, mesmo público."""
    original = await _draft(client_id, draft_id)
    new_payload = clean_payload(original.get("payload") or {})
    meta_ids: Dict[str, Any] = {}
    if into_campaign:
        ids = original.get("meta_ids") or {}
        if original.get("status") != "publicada" or not ids.get("adset_id"):
            raise StudioError("AD_NOT_PUBLISHED_YET",
                              "Crie a campanha no Meta antes. Enquanto é rascunho, use o formato Vários anúncios.")
        meta_ids = {"ad_account_id": ids.get("ad_account_id"), "campaign_id": ids["campaign_id"], "adset_id": ids["adset_id"],
                    "joined": True, "joined_from": str(original["id"])}
        name = _text(new_payload["name"] + " · novo anúncio", LIMITS["name"])
    else:
        name = _text(new_payload["name"] + " · cópia", LIMITS["name"])
    new_payload["name"] = name
    inserted = await sb_insert(TABLE, {
        "client_id": client_id,
        "month": original.get("month"),
        "source_campaign": original.get("source_campaign"),
        "payload": new_payload,
        "status": "rascunho",
        "created_by": user_id,
        **({"meta_ids": meta_ids} if meta_ids else {}),
    })
    if not inserted:
        raise StudioError("AD_SAVE_FAILED")
    return _view(inserted)


async def live_delivery_status(client_id: str, draft_id: str) -> Dict[str, Any]:
    """Read provider campaign/adset/ad statuses for an owned draft. Never changes delivery."""
    row = await _draft(client_id, draft_id)
    ids = row.get("meta_ids") or {}
    ad_ids = {key: str(ids.get(key) or "") for key in ("campaign_id", "adset_id", "ad_id")}
    for n, extra in enumerate(_ads_of(ids)[1:], start=2):
        ad_ids[f"ad_{n}"] = extra
    if not ad_ids["campaign_id"]:
        raise StudioError("AD_NOT_READY", "Campanha ainda não foi criada na Meta.")
    account = await _ad_account(client_id)
    attached_account = str(ids.get("ad_account_id") or "")
    if attached_account and attached_account.removeprefix("act_") != account["act"].removeprefix("act_"):
        raise StudioError("AD_ACCOUNT_MISSING")
    parts: Dict[str, Dict[str, str]] = {}
    for kind, object_id in ad_ids.items():
        if not object_id:
            continue
        remote = await _graph("GET", f"/{object_id}", token=account["token"],
                              params={"fields": "id,name,status,effective_status,account_id"})
        returned_account = str(remote.get("account_id") or "")
        if returned_account and returned_account.removeprefix("act_") != account["act"].removeprefix("act_"):
            raise StudioError("AD_ACCOUNT_MISSING")
        parts[kind] = {
            "id": object_id,
            "name": _text(remote.get("name"), 120),
            "status": _text(remote.get("status"), 40),
            "effective_status": _text(remote.get("effective_status"), 40),
        }
    return {"draft_id": draft_id, "client_id": client_id, "source": "meta_graph",
            "checked_at": _now(), "objects": parts, "read_only": True,
            "delivery": ids.get("delivery"), "joined": bool(ids.get("joined"))}


# ---------------------------------------------------------------- ativar / pausar / resultados

RESULT_ACTIONS = {
    "leads": ("offsite_conversion.fb_pixel_lead", "lead", "onsite_conversion.lead_grouped"),
    "vendas": ("offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase"),
    "retencao": ("offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase"),
    "remarketing": ("offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase"),
    "trafego": ("link_click",),
    "engajamento": ("post_engagement",),
}
RESULT_LABEL = {"leads": "Cadastros", "vendas": "Compras", "retencao": "Compras", "remarketing": "Compras",
                "trafego": "Cliques no link", "engajamento": "Engajamentos", "alcance": "Pessoas alcançadas"}


async def _published(client_id: str, draft_id: str) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    row = await _draft(client_id, draft_id)
    ids = row.get("meta_ids") or {}
    if row.get("status") != "publicada" or not ids.get("campaign_id"):
        raise StudioError("AD_NOT_READY", "Crie a campanha no Meta antes de ativar.")
    account = await _ad_account(client_id)
    if str(ids.get("ad_account_id") or account["act"]).removeprefix("act_") != account["act"].removeprefix("act_"):
        raise StudioError("AD_ACCOUNT_MISSING")
    return row, ids, account


def _ads_of(ids: Dict[str, Any]) -> List[str]:
    return [str(x) for x in (ids.get("ad_ids") or ([ids["ad_id"]] if ids.get("ad_id") else []))]


async def set_delivery(client_id: str, draft_id: str, *, active: bool, user_name: str,
                       confirm_daily_budget: Optional[float] = None) -> Dict[str, Any]:
    """Liga ou pausa a entrega na Meta. Ligar exige confirmar a verba diária (começa a gastar).
    Pausar desliga a campanha inteira na hora; os anúncios ficam como estão para religar com um clique.
    Anúncio que entrou numa campanha já existente ("novo anúncio nesta campanha") liga/pausa só ele."""
    row, ids, account = await _published(client_id, draft_id)
    payload = clean_payload(row.get("payload") or {})
    joined = bool(ids.get("joined"))
    if active and not joined and (confirm_daily_budget is None or abs(float(confirm_daily_budget) - payload["daily_budget"]) > 0.009):
        raise StudioError("AD_CONFIRM_BUDGET", "Confirme a verba diária para ativar.")
    status = "ACTIVE" if active else "PAUSED"
    ads = _ads_of(ids)
    if active:
        # De baixo para cima: anúncios, conjunto e campanha — quando a campanha liga, tudo já está pronto.
        targets = ads if joined else [*ads, str(ids["adset_id"]), str(ids["campaign_id"])]
    else:
        targets = ads if joined else [str(ids["campaign_id"])]
    for object_id in targets:
        await _graph("POST", f"/{object_id}", token=account["token"], data={"status": status})
    ids = {**ids, "delivery": {"state": "ativa" if active else "pausada", "by": (user_name or "")[:120], "at": _now()}}
    await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"},
                    patch={"meta_ids": ids, "updated_at": _now()})
    print(f"[meta_ads_delivery] client_id={client_id} draft={draft_id} status={status} objects={len(targets)}")
    return await live_delivery_status(client_id, draft_id)


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def live_results(client_id: str, draft_id: str, period: str = "maximum") -> Dict[str, Any]:
    """Números da campanha direto da Meta (somente leitura): gasto, alcance, cliques e o resultado do objetivo."""
    row, ids, account = await _published(client_id, draft_id)
    payload = clean_payload(row.get("payload") or {})
    preset = period if period in ("today", "yesterday", "last_7d", "maximum") else "maximum"
    fields = "spend,impressions,reach,clicks,inline_link_clicks,ctr,cpc,cpm,frequency,actions"
    objects = _ads_of(ids) if ids.get("joined") else [str(ids["campaign_id"])]
    total = {"spend": 0.0, "impressions": 0.0, "reach": 0.0, "clicks": 0.0, "link_clicks": 0.0, "results": 0.0}
    wanted = RESULT_ACTIONS.get(payload["objective"], ())
    for object_id in objects:
        body = await _graph("GET", f"/{object_id}/insights", token=account["token"], params={"fields": fields, "date_preset": preset})
        for line in body.get("data") or []:
            total["spend"] += _num(line.get("spend"))
            total["impressions"] += _num(line.get("impressions"))
            total["reach"] += _num(line.get("reach"))
            total["clicks"] += _num(line.get("clicks"))
            total["link_clicks"] += _num(line.get("inline_link_clicks"))
            actions = {a.get("action_type"): _num(a.get("value")) for a in line.get("actions") or []}
            total["results"] += next((actions[k] for k in wanted if k in actions), 0.0)
    if payload["objective"] == "alcance":
        total["results"] = total["reach"]
    impressions = total["impressions"]
    return {"draft_id": draft_id, "period": preset, "checked_at": _now(), "currency": "BRL",
            "spend": round(total["spend"], 2), "impressions": int(impressions), "reach": int(total["reach"]),
            "clicks": int(total["clicks"]), "link_clicks": int(total["link_clicks"]),
            "ctr": round(total["clicks"] / impressions * 100, 2) if impressions else 0.0,
            "cpc": round(total["spend"] / total["clicks"], 2) if total["clicks"] else None,
            "results": int(total["results"]), "result_label": RESULT_LABEL.get(payload["objective"], "Resultados"),
            "cost_per_result": round(total["spend"] / total["results"], 2) if total["results"] else None,
            "daily_budget": payload["daily_budget"], "read_only": True}


async def delete_draft(client_id: str, draft_id: str) -> None:
    row = await _draft(client_id, draft_id)
    if row.get("status") == "publicando":
        raise StudioError("AD_ALREADY_PUBLISHED")
    await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}, returning="minimal")


# ---------------------------------------------------------------- Graph API

class MetaAdError(StudioError):
    pass


async def _graph(method: str, path: str, *, token: str, data: Optional[Dict[str, Any]] = None,
                 params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(method, f"{META_GRAPH_BASE_URL}{path}", params={**(params or {}), "access_token": token}, data=data)
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {}
    if response.status_code >= 400:
        err = (body or {}).get("error") or {}
        msg = str(err.get("error_user_msg") or err.get("message") or f"HTTP {response.status_code}")[:400]
        print(f"[meta_ads_publish] graph_error path={path.split('?')[0].split('/')[-1]} status={response.status_code} code={err.get('code')} sub={err.get('error_subcode')}")
        if str(err.get("code")) in ("10", "200", "190") or "permission" in msg.lower():
            raise MetaAdError("AD_PERMISSION_MISSING", msg)
        raise MetaAdError("AD_META_REJECTED", msg)
    return body


async def _ad_account(client_id: str) -> Dict[str, str]:
    """Conta de anúncios + token da conexão paga (sem exigir página: serve para ler os públicos)."""
    from .connection_resolver import resolve_connection_for_scope
    from .meta_tokens import ensure_valid_meta_token
    paid = await resolve_connection_for_scope(client_id=client_id, platform="meta_ads", connection_type="paid", require_ad_account=True)
    connection_id = str(paid.get("connection_id") or "").strip()
    row = paid.get("row") or {}
    act = str(row.get("ad_account_id") or "").strip()
    if not connection_id or not act:
        raise StudioError("AD_ACCOUNT_MISSING")
    scopes = {str(s) for s in (row.get("scopes_json") or []) if s}
    if scopes and ADS_SCOPE not in scopes:
        raise StudioError("AD_PERMISSION_MISSING")
    token = await ensure_valid_meta_token(client_id, connection_id=connection_id, platform="meta_ads", connection_type="paid", persisted_only=True)
    return {"token": token, "act": act if act.startswith("act_") else f"act_{act}"}


async def _context(client_id: str) -> Dict[str, Any]:
    """Conta de anúncios + token (conexão paga) e página/Instagram (conexão orgânica)."""
    account = await _ad_account(client_id)
    page_id, ig_id = "", ""
    try:
        from .ig_engagement import credentials
        creds = await credentials(client_id)
        page_id, ig_id = creds.get("page_id") or "", creds.get("ig_user_id") or ""
    except StudioError:
        pass
    if not page_id:
        raise StudioError("AD_PAGE_MISSING")
    return {**account, "page_id": page_id, "ig_id": ig_id}


async def publication_preflight(client_id: str, objective: str = "leads") -> Dict[str, Any]:
    """Read-only account readiness for creating one PAUSED Meta ad.

    No credentials, pixel IDs or other private Meta connection values are returned.
    The publish endpoint revalidates permissions and prerequisites at write time.
    """
    if objective not in OBJECTIVES:
        raise StudioError("AD_OBJECTIVE_INVALID")
    checks: List[Dict[str, Any]] = []
    def record(key: str, ok: bool, message: str, label: str = "") -> None:
        checks.append({"key": key, "ok": ok, "message": message, "label": label})

    try:
        account = await _ad_account(client_id)
    except StudioError as exc:
        record("account", False, {
            "AD_ACCOUNT_MISSING": "Conecte uma conta Meta Ads desta empresa em Integrações.",
            "AD_PERMISSION_MISSING": "Reconecte a conta com permissão ads_management.",
        }.get(exc.code, "A conexão Meta Ads não está disponível; confira Integrações."))
        return {"ready": False, "checks": checks, "objective": objective}

    act, token = account["act"], account["token"]
    try:
        remote = await _graph("GET", f"/{act}", token=token,
                              params={"fields": "id,name,account_status,currency,timezone_name"})
        status = int(remote.get("account_status") or 0)
        record("account", status == 1, "Conta ativa e disponível para preparar anúncios." if status == 1
               else "A conta Meta não está ativa para anúncios. Confira o Gerenciador.",
               _text(remote.get("name"), 120))
    except (StudioError, ValueError, TypeError):
        record("account", False, "Não foi possível verificar o status da conta Meta.")

    try:
        from .ig_engagement import credentials
        creds = await credentials(client_id)
        page = bool(creds.get("page_id"))
        record("page", page, "Página do Facebook conectada." if page
               else "Conecte a Página do Facebook desta marca em Integrações.")
        record("instagram", bool(creds.get("ig_user_id")),
               "Instagram conectado." if creds.get("ig_user_id")
               else "Instagram não conectado: revise os posicionamentos que exigem Instagram.")
    except StudioError:
        record("page", False, "Conecte a Página do Facebook desta marca em Integrações.")
        record("instagram", False, "Instagram não pôde ser verificado.")

    if OBJECTIVES[objective].get("event"):
        try:
            pixel = await _graph("GET", f"/{act}/adspixels", token=token,
                                 params={"fields": "id,name", "limit": 5})
            found = pixel.get("data") or []
            record("pixel", bool(found), "Pixel associado à conta de anúncios." if found
                   else "Nenhum pixel associado. É necessário para otimizar esta campanha por evento.",
                   _text(found[0].get("name"), 120) if found else "")
        except StudioError:
            record("pixel", False, "Não foi possível consultar os pixels da conta.")
    else:
        record("pixel", True, "O objetivo selecionado não exige pixel.")

    # Instagram is advisory: Facebook-only placements can still publish.
    ready = all(item["ok"] for item in checks if item["key"] != "instagram")
    return {"ready": ready, "checks": checks, "objective": objective}


async def _interest_ids(names: List[str], token: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for name in names[:8]:
        try:
            found = await _graph("GET", "/search", token=token, params={"type": "adinterest", "q": name, "limit": 1, "locale": "pt_BR"})
        except MetaAdError:
            continue
        for item in (found.get("data") or [])[:1]:
            if item.get("id"):
                out.append({"id": str(item["id"]), "name": str(item.get("name") or name)})
    return out


async def _region_keys(names: List[str], token: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for name in names[:10]:
        try:
            found = await _graph("GET", "/search", token=token, params={"type": "adgeolocation", "location_types": '["region"]',
                                                                          "country_code": "BR", "q": name, "limit": 1})
        except MetaAdError:
            continue
        for item in (found.get("data") or [])[:1]:
            if item.get("key"):
                out.append({"key": str(item["key"])})
    return out


def targeting_for(payload: Dict[str, Any], interests: List[Dict[str, str]], regions: List[Dict[str, str]]) -> Dict[str, Any]:
    aud = payload["audience"]
    geo: Dict[str, Any] = {"regions": regions} if regions else {"countries": ["BR"]}
    targeting: Dict[str, Any] = {"geo_locations": geo, "age_min": aud["age_min"], "age_max": aud["age_max"],
                                 "targeting_automation": {"advantage_audience": 1 if aud["advantage"] else 0}}
    if GENDERS.get(aud["gender"]):
        targeting["genders"] = GENDERS[aud["gender"]]
    if interests:
        targeting["flexible_spec"] = [{"interests": interests}]
    return targeting


async def _image_hash(act: str, url: str, token: str) -> str:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code >= 400 or not response.content:
        raise StudioError("AD_IMAGE_UNREACHABLE")
    if not str(response.headers.get("content-type", "")).startswith("image/"):
        raise StudioError("AD_IMAGE_UNREACHABLE")
    body = await _graph("POST", f"/{act}/adimages", token=token, data={"bytes": base64.b64encode(response.content).decode()})
    images = body.get("images") or {}
    first = next(iter(images.values()), {}) if isinstance(images, dict) else {}
    if not first.get("hash"):
        raise MetaAdError("AD_META_REJECTED", "O Meta não devolveu a imagem enviada.")
    return str(first["hash"])


async def _pixel_id(act: str, token: str) -> str:
    body = await _graph("GET", f"/{act}/adspixels", token=token, params={"fields": "id,name", "limit": 5})
    pixels = body.get("data") or []
    if not pixels:
        raise StudioError("AD_PIXEL_MISSING")
    return str(pixels[0]["id"])


def audience_rule(pixel_id: str, days: int, event: Optional[str]) -> Dict[str, Any]:
    """Regra do público pelo pixel: todo visitante (event=None) ou quem disparou o evento (ex.: Purchase)."""
    filters = [{"field": "event", "operator": "eq", "value": event}] if event else [{"field": "url", "operator": "i_contains", "value": ""}]
    return {"inclusions": {"operator": "or", "rules": [{"event_sources": [{"id": pixel_id, "type": "pixel"}],
                                                          "retention_seconds": days * 86400,
                                                          "filter": {"operator": "and", "filters": filters}}]}}


async def ensure_audience(act: str, token: str, key: str, pixel_id: str) -> str:
    """Público personalizado do Mugô na conta: reaproveita pelo nome; senão cria pelo pixel."""
    spec = AUDIENCES[key]
    found = await _graph("GET", f"/{act}/customaudiences", token=token, params={"fields": "id,name", "limit": 200})
    for item in found.get("data") or []:
        if item.get("name") == spec["name"] and item.get("id"):
            return str(item["id"])
    made = await _graph("POST", f"/{act}/customaudiences", token=token, data={
        "name": spec["name"], "description": "Criado pelo Mídia On (Mugoverso)", "prefill": "1",
        "rule": json.dumps(audience_rule(pixel_id, spec["days"], spec["event"]))})
    return str(made["id"])


# ---------------------------------------------------------------- públicos da conta do cliente

AUDIENCE_KINDS = {"LOOKALIKE": "Semelhante", "WEBSITE": "Visitantes do site", "ENGAGEMENT": "Engajamento",
                  "CUSTOM": "Lista de clientes", "VIDEO": "Quem viu vídeo", "APP": "App", "OFFLINE_CONVERSION": "Compras offline",
                  "IG_BUSINESS": "Instagram", "FB_EVENT": "Evento", "LEAD_AD": "Formulário de cadastro", "SHOPPING": "Loja"}


def _people(value: Any) -> str:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} mi".replace(".", ",").replace(",0 ", " ")
    if n >= 1_000:
        return f"{round(n / 1_000):.0f} mil"
    return str(n)


def size_label(lower: Any, upper: Any) -> str:
    """Faixa de tamanho que o Meta informa (-1 ou nada = pequeno demais para estimar)."""
    try:
        low = int(lower)
    except (TypeError, ValueError):
        low = -1
    if low < 1000:
        return "menos de 1 mil pessoas"
    high = _people(upper)
    return f"{_people(low)} a {high} pessoas" if high and high != _people(low) else f"{_people(low)} pessoas"


async def _paged(path: str, token: str, fields: str, pages: int = 3) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {"fields": fields, "limit": 200}
    for _ in range(pages):
        body = await _graph("GET", path, token=token, params=params)
        rows.extend(body.get("data") or [])
        after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (body.get("paging") or {}).get("next"):
            break
        params = {**params, "after": after}
    return rows


def audience_view(row: Dict[str, Any], saved: bool = False) -> Dict[str, Any]:
    status = (row.get("delivery_status") or {}) if isinstance(row.get("delivery_status"), dict) else {}
    code = int(status.get("code") or 200) if str(status.get("code") or "200").isdigit() else 200
    kind = "SAVED" if saved else str(row.get("subtype") or "CUSTOM").upper()
    return {"id": str(row.get("id") or ""), "name": _text(row.get("name"), 120) or "Sem nome",
            "kind": kind, "kind_label": "Público salvo" if saved else AUDIENCE_KINDS.get(kind, "Personalizado"),
            "size": size_label(row.get("approximate_count_lower_bound"), row.get("approximate_count_upper_bound")),
            # 200 = pronto; 300 = pequeno demais; o resto o Meta ainda está preparando ou bloqueou.
            "ready": code == 200, "status": _text(status.get("description"), 200) if code != 200 else ""}


async def list_account_audiences(client_id: str) -> Dict[str, Any]:
    """Públicos que já existem na conta de anúncios do cliente, para escolher em vez de escrever o público."""
    account = await _ad_account(client_id)
    token, act = account["token"], account["act"]
    size = "approximate_count_lower_bound,approximate_count_upper_bound"
    custom = await _paged(f"/{act}/customaudiences", token, f"id,name,subtype,delivery_status,{size}")
    try:
        saved = await _paged(f"/{act}/saved_audiences", token, f"id,name,{size}", pages=1)
    except MetaAdError:
        saved = []  # algumas contas não liberam a leitura de públicos salvos; os personalizados seguem
    views = [audience_view(row) for row in custom if row.get("id")]
    views.sort(key=lambda a: (not a["ready"], a["kind"] != "LOOKALIKE", a["name"].lower()))
    return {"account": act, "saved": [audience_view(row, saved=True) for row in saved if row.get("id")], "custom": views}


async def saved_targeting(saved_id: str, token: str) -> Dict[str, Any]:
    """Segmentação de um público salvo (idade, locais, interesses…) para usar no conjunto de anúncios."""
    body = await _graph("GET", f"/{saved_id}", token=token, params={"fields": "targeting"})
    targeting = body.get("targeting")
    if not isinstance(targeting, dict) or not targeting:
        raise MetaAdError("AD_META_REJECTED", "O Meta não devolveu a segmentação do público salvo escolhido.")
    return dict(targeting)


def apply_account_audiences(targeting: Dict[str, Any], audience: Dict[str, Any]) -> Dict[str, Any]:
    """Soma os públicos escolhidos da conta aos que a campanha já usa (sem repetir) e aplica as exclusões."""
    def merged(key: str, extra: List[Dict[str, str]]) -> List[Dict[str, str]]:
        current = [a for a in targeting.get(key) or [] if isinstance(a, dict) and a.get("id")]
        seen = {str(a["id"]) for a in current}
        return current + [{"id": a["id"]} for a in extra if a["id"] not in seen]
    excluded = merged("excluded_custom_audiences", audience.get("excluded_audiences") or [])
    skip = {str(a["id"]) for a in excluded}
    included = [a for a in merged("custom_audiences", audience.get("custom_audiences") or []) if str(a["id"]) not in skip]
    if included:
        targeting["custom_audiences"] = included
    if excluded:
        targeting["excluded_custom_audiences"] = excluded
    return targeting


def _ts(day: str, end: bool = False) -> str:
    return f"{day}T{'23:59:00' if end else '08:00:00'}-0300"


async def publish(client_id: str, draft_id: str) -> Dict[str, Any]:
    """Cria campanha, conjunto, criativo e anúncio PAUSADOS. Retoma de onde parou se um passo falhou antes."""
    row = await _draft(client_id, draft_id)
    if row.get("status") == "publicada":
        raise StudioError("AD_ALREADY_PUBLISHED")
    payload = clean_payload(row.get("payload") or {})
    missing = readiness(payload)
    if missing:
        raise StudioError("AD_NOT_READY", "Falta: " + "; ".join(missing))
    ctx = await _context(client_id)
    ids: Dict[str, Any] = dict(row.get("meta_ids") or {})
    if ids.get("joined") and ids.get("ad_account_id") and ids["ad_account_id"] != ctx["act"]:
        raise StudioError("AD_ACCOUNT_CHANGED", "A conta de anúncios mudou desde a campanha original. Use Duplicar campanha.")
    ids["ad_account_id"] = ctx["act"]
    cfg = OBJECTIVES[payload["objective"]]
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}
    await sb_update(TABLE, filters=filters, patch={"status": "publicando", "error": None, "updated_at": _now()})
    async def checkpoint() -> None:
        # Persist provider IDs after EACH successful create to resume safely on failure.
        # This avoids creating a second campaign when a later adset/creative request is rejected.
        await sb_update(TABLE, filters=filters, patch={"meta_ids": ids, "updated_at": _now()})

    try:
        token, act, ad = ctx["token"], ctx["act"], payload["ad"]
        if not ids.get("campaign_id"):
            camp = await _graph("POST", f"/{act}/campaigns", token=token, data={
                "name": payload["name"], "objective": cfg["objective"], "status": "PAUSED", "special_ad_categories": "[]",
                "daily_budget": str(int(round(payload["daily_budget"] * 100))), "bid_strategy": "LOWEST_COST_WITHOUT_CAP"})
            ids["campaign_id"] = str(camp["id"])
            await checkpoint()
        if not ids.get("adset_id"):
            saved = payload["audience"].get("saved_audience")
            if saved:
                # Público salvo da conta: usa a segmentação dele (idade, locais, interesses) no lugar da escrita.
                targeting = await saved_targeting(saved["id"], token)
            else:
                interests = await _interest_ids(payload["audience"]["interests"], token)
                regions = await _region_keys(payload["audience"]["regions"], token)
                targeting = targeting_for(payload, interests, regions)
            pixel = await _pixel_id(act, token) if cfg.get("event") else ""
            if cfg.get("audience"):
                # Retenção/remarketing: o público é a lista (não amplia com Advantage+ nem interesses).
                key = cfg["audience"]
                ids.setdefault("audiences", {})[key] = await ensure_audience(act, token, key, pixel)
                targeting.pop("flexible_spec", None)
                targeting["targeting_automation"] = {"advantage_audience": 0}
                targeting["custom_audiences"] = [{"id": ids["audiences"][key]}]
                exclude = AUDIENCES[key].get("exclude")
                if exclude:
                    ids["audiences"][exclude] = await ensure_audience(act, token, exclude, pixel)
                    targeting["excluded_custom_audiences"] = [{"id": ids["audiences"][exclude]}]
            targeting = apply_account_audiences(targeting, payload["audience"])
            placements = payload["placements"]
            if placements["mode"] == "manual":
                targeting["publisher_platforms"] = placements["platforms"]
                if "instagram" in placements["platforms"]:
                    if not ctx["ig_id"]:
                        raise StudioError("AD_INSTAGRAM_MISSING")
                    targeting["instagram_positions"] = placements["instagram"]
                if "facebook" in placements["platforms"]:
                    targeting["facebook_positions"] = placements["facebook"]
                targeting.pop("messenger_positions", None)
                targeting.pop("audience_network_positions", None)
            adset = {"name": f"{payload['name']} · público", "campaign_id": ids["campaign_id"], "status": "PAUSED",
                     "billing_event": "IMPRESSIONS", "optimization_goal": cfg["optimization"],
                     "targeting": json.dumps(targeting),
                     "start_time": _ts(payload["start_date"]), "end_time": _ts(payload["end_date"], end=True)}
            if cfg.get("destination"):
                adset["destination_type"] = cfg["destination"]
            if cfg.get("event"):
                adset["promoted_object"] = json.dumps({"pixel_id": pixel, "custom_event_type": cfg["event"]})
            ids["adset_id"] = str((await _graph("POST", f"/{act}/adsets", token=token, data=adset))["id"])
            await checkpoint()
        link = ad["link"] or f"https://www.facebook.com/{ctx['page_id']}"
        tags = {"url_tags": tracking_suffix(payload["tracking"])} if payload["tracking"] else {}

        async def make_creative(name: str, link_or_video: Dict[str, Any]) -> str:
            spec = {"page_id": ctx["page_id"], **link_or_video}
            if ctx["ig_id"]:
                spec["instagram_user_id"] = ctx["ig_id"]
            made = await _graph("POST", f"/{act}/adcreatives", token=token,
                                data={"name": name, "object_story_spec": json.dumps(spec), **tags})
            return str(made["id"])

        async def make_ad(name: str, creative_id: str) -> str:
            made = await _graph("POST", f"/{act}/ads", token=token, data={
                "name": name, "adset_id": ids["adset_id"], "status": "PAUSED",
                "creative": json.dumps({"creative_id": creative_id})})
            return str(made["id"])

        def link_data_for(image_hash: str, headline: str, target: str) -> Dict[str, Any]:
            data: Dict[str, Any] = {"link": target, "message": ad["primary_text"], "image_hash": image_hash,
                                    "call_to_action": {"type": ad["cta"], "value": {"link": target}}}
            if headline:
                data["name"] = headline
            if ad["description"]:
                data["description"] = ad["description"]
            return {"link_data": data}

        async def body_for(unit: Dict[str, Any], index: int) -> Dict[str, Any]:
            headline = unit.get("headline") or ad["headline"]
            target = unit.get("link") or link
            if unit["format"] == "carousel":
                children = []
                for card in unit["cards"]:
                    card_link = card["link"] or link
                    child: Dict[str, Any] = {"link": card_link, "image_hash": await _image_hash(act, card["image_url"], token),
                                             "call_to_action": {"type": ad["cta"], "value": {"link": card_link}}}
                    if card["headline"] or ad["headline"]:
                        child["name"] = card["headline"] or ad["headline"]
                    if card["description"]:
                        child["description"] = card["description"]
                    children.append(child)
                return {"link_data": {
                    "link": link, "message": ad["primary_text"], "child_attachments": children,
                    "multi_share_optimized": False, "multi_share_end_card": False,
                    "call_to_action": {"type": ad["cta"], "value": {"link": link}}}}
            if unit["media_type"] == "video":
                videos = dict(ids.get("video_ids") or ({"0": ids["video_id"]} if ids.get("video_id") else {}))
                video_id = videos.get(str(index))
                if not video_id:
                    uploaded = await _graph("POST", f"/{act}/advideos", token=token,
                                            data={"file_url": unit["video_url"], "name": f"{payload['name']} · vídeo {index + 1}"})
                    video_id = str(uploaded.get("id") or "")
                    if not video_id:
                        raise MetaAdError("AD_META_REJECTED", "A Meta não devolveu o ID do vídeo.")
                    videos[str(index)] = video_id
                    ids["video_ids"] = videos
                    if index == 0:
                        ids["video_id"] = video_id
                    await checkpoint()
                return {"video_data": {"video_id": video_id, "message": ad["primary_text"], "title": headline or payload["name"],
                                       "call_to_action": {"type": ad["cta"], "value": {"link": target}}}}
            return link_data_for(await _image_hash(act, unit["image_url"], token), headline, target)

        # Todos os anúncios do conjunto (1 ou vários; cada um imagem, vídeo ou carrossel). Retoma de onde parou.
        units = ad_units(ad)
        single = len(units) == 1
        creatives: List[str] = list(ids.get("creative_ids") or ([ids["creative_id"]] if ids.get("creative_id") else []))
        ads_made: List[str] = list(ids.get("ad_ids") or ([ids["ad_id"]] if ids.get("ad_id") else []))
        for index, unit in enumerate(units):
            suffix = "" if single else f" {index + 1}"
            if index >= len(creatives):
                creatives.append(await make_creative(f"{payload['name']} · criativo{suffix}", await body_for(unit, index)))
                ids["creative_ids"] = creatives
                ids["creative_id"] = creatives[0]
                await checkpoint()
            if index >= len(ads_made):
                ads_made.append(await make_ad(f"{payload['name']} · anúncio{suffix}", creatives[index]))
                ids["ad_ids"] = ads_made
                ids["ad_id"] = ads_made[0]
                await checkpoint()
    except StudioError as exc:
        message = str(exc) if str(exc) != exc.code else exc.code
        await sb_update(TABLE, filters=filters, patch={"status": "erro", "meta_ids": ids, "error": str(message)[:600], "updated_at": _now()})
        raise
    rows = await sb_update(TABLE, filters=filters, patch={"status": "publicada", "meta_ids": ids, "error": None,
                                                          "published_at": _now(), "updated_at": _now()})
    print(f"[meta_ads_publish] client_id={client_id} draft={draft_id} status=published campaign={ids.get('campaign_id')}")
    return _view(rows[0] if rows else {**row, "status": "publicada", "meta_ids": ids})
