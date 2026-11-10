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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .meta_config import META_GRAPH_BASE_URL
from .studio_calendar import StudioError

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


def _names(value: Any, limit: int = 12) -> List[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    return [s for s in dict.fromkeys(str(i).strip()[:60] for i in items) if s][:limit]


# ---------------------------------------------------------------- rascunho

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
    ad = data.get("ad") if isinstance(data.get("ad"), dict) else {}
    cta = str(ad.get("cta") or "LEARN_MORE")
    return {
        "name": _text(data.get("name"), LIMITS["name"]) or "Campanha Mídia On",
        "objective": objective,
        "daily_budget": budget,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "audience": {"age_min": age_min, "age_max": age_max, "gender": gender if gender in GENDERS else "todos",
                     "regions": _names(aud.get("regions")), "interests": _names(aud.get("interests")),
                     "advantage": bool(aud.get("advantage", True))},
        "ad": {"primary_text": _text(ad.get("primary_text"), LIMITS["primary_text"]),
               "headline": _text(ad.get("headline"), LIMITS["headline"]),
               "description": _text(ad.get("description"), LIMITS["description"]),
               "cta": cta if cta in CTAS else "LEARN_MORE",
               "link": _text(ad.get("link"), LIMITS["link"]),
               "image_url": _text(ad.get("image_url"), LIMITS["image_url"]),
               "calendar_item_id": _text(ad.get("calendar_item_id"), 60) or None},
    }


def readiness(payload: Dict[str, Any]) -> List[str]:
    """O que falta para publicar (mostrado na tela antes do botão)."""
    missing = []
    if payload["daily_budget"] < MIN_DAILY_BRL:
        missing.append(f"Orçamento diário de pelo menos R$ {MIN_DAILY_BRL:.0f}".replace(".", ","))
    ad = payload["ad"]
    if not ad["primary_text"]:
        missing.append("Texto principal do anúncio")
    if not ad["image_url"]:
        missing.append("Imagem do anúncio (post do Calendário com arte ou link da imagem)")
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
            "published_at": row.get("published_at"), "updated_at": row.get("updated_at")}


async def list_drafts(client_id: str) -> List[Dict[str, Any]]:
    try:
        rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=50)
    except Exception as exc:  # noqa: BLE001 — tabela ainda não criada
        print(f"[meta_ads_publish] list client_id={client_id} unavailable error_type={type(exc).__name__}")
        raise StudioError("AD_MIGRATION_PENDING") from None
    return [_view(r) for r in rows]


async def _draft(client_id: str, draft_id: str) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}, limit=1)
    if not rows:
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
    schema = obj({"name": STR, "primary_text": STR, "headline": STR, "description": STR, "cta": STR,
                  "age_min": INT, "age_max": INT, "gender": STR, "regions": arr(STR), "interests": arr(STR)})
    prompt = (f"CAMPANHA DO PLANO (Mídia On): {json.dumps({k: campaign.get(k) for k in ('campaign', 'action', 'why', 'planned_budget')}, ensure_ascii=False)}\n"
              f"OBJETIVO NO META: {OBJECTIVES[obj_key]['label']}\n"
              f"PERFIL DA MARCA: {json.dumps({k: profile.get(k) for k in ('tone_of_voice', 'personality', 'audience', 'keywords_use', 'keywords_avoid', 'restrictions')}, ensure_ascii=False)}\n"
              f"NEGÓCIO: {json.dumps(business, ensure_ascii=False, default=str)[:2500]}\n"
              f"BOTÕES POSSÍVEIS (cta): {', '.join(CTAS)}\n"
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


async def _context(client_id: str) -> Dict[str, Any]:
    """Conta de anúncios + token (conexão paga) e página/Instagram (conexão orgânica)."""
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
    page_id, ig_id = "", ""
    try:
        from .ig_engagement import credentials
        creds = await credentials(client_id)
        page_id, ig_id = creds.get("page_id") or "", creds.get("ig_user_id") or ""
    except StudioError:
        pass
    if not page_id:
        raise StudioError("AD_PAGE_MISSING")
    return {"token": token, "act": act if act.startswith("act_") else f"act_{act}", "page_id": page_id, "ig_id": ig_id}


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
    ids["ad_account_id"] = ctx["act"]
    cfg = OBJECTIVES[payload["objective"]]
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}
    await sb_update(TABLE, filters=filters, patch={"status": "publicando", "error": None, "updated_at": _now()})
    try:
        token, act, ad = ctx["token"], ctx["act"], payload["ad"]
        if not ids.get("campaign_id"):
            camp = await _graph("POST", f"/{act}/campaigns", token=token, data={
                "name": payload["name"], "objective": cfg["objective"], "status": "PAUSED", "special_ad_categories": "[]",
                "daily_budget": str(int(round(payload["daily_budget"] * 100))), "bid_strategy": "LOWEST_COST_WITHOUT_CAP"})
            ids["campaign_id"] = str(camp["id"])
        if not ids.get("adset_id"):
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
            adset = {"name": f"{payload['name']} · público", "campaign_id": ids["campaign_id"], "status": "PAUSED",
                     "billing_event": "IMPRESSIONS", "optimization_goal": cfg["optimization"],
                     "targeting": json.dumps(targeting),
                     "start_time": _ts(payload["start_date"]), "end_time": _ts(payload["end_date"], end=True)}
            if cfg.get("destination"):
                adset["destination_type"] = cfg["destination"]
            if cfg.get("event"):
                adset["promoted_object"] = json.dumps({"pixel_id": pixel, "custom_event_type": cfg["event"]})
            ids["adset_id"] = str((await _graph("POST", f"/{act}/adsets", token=token, data=adset))["id"])
        if not ids.get("creative_id"):
            image_hash = await _image_hash(act, ad["image_url"], token)
            link = ad["link"] or f"https://www.facebook.com/{ctx['page_id']}"
            link_data: Dict[str, Any] = {"link": link, "message": ad["primary_text"], "image_hash": image_hash,
                                         "call_to_action": {"type": ad["cta"], "value": {"link": link}}}
            if ad["headline"]:
                link_data["name"] = ad["headline"]
            if ad["description"]:
                link_data["description"] = ad["description"]
            spec: Dict[str, Any] = {"page_id": ctx["page_id"], "link_data": link_data}
            if ctx["ig_id"]:
                spec["instagram_user_id"] = ctx["ig_id"]
            creative = await _graph("POST", f"/{act}/adcreatives", token=token,
                                    data={"name": f"{payload['name']} · criativo", "object_story_spec": json.dumps(spec)})
            ids["creative_id"] = str(creative["id"])
        if not ids.get("ad_id"):
            made = await _graph("POST", f"/{act}/ads", token=token, data={
                "name": f"{payload['name']} · anúncio", "adset_id": ids["adset_id"], "status": "PAUSED",
                "creative": json.dumps({"creative_id": ids["creative_id"]})})
            ids["ad_id"] = str(made["id"])
    except StudioError as exc:
        message = str(exc) if str(exc) != exc.code else exc.code
        await sb_update(TABLE, filters=filters, patch={"status": "erro", "meta_ids": ids, "error": str(message)[:600], "updated_at": _now()})
        raise
    rows = await sb_update(TABLE, filters=filters, patch={"status": "publicada", "meta_ids": ids, "error": None,
                                                          "published_at": _now(), "updated_at": _now()})
    print(f"[meta_ads_publish] client_id={client_id} draft={draft_id} status=published campaign={ids.get('campaign_id')}")
    return _view(rows[0] if rows else {**row, "status": "publicada", "meta_ids": ids})
