"""Estrutura de campanha igual à do Gerenciador de Anúncios da Meta (ODAX).

Campanha → Conjunto de anúncios → Anúncio, com os mesmos nomes do Gerenciador em português.
Este módulo só descreve e confere as combinações; quem valida de verdade é a Meta, na criação
(a campanha nasce PAUSADA e qualquer recusa volta com a mensagem dela, no nível certo).

O rascunho guarda tudo em ``payload["meta"]``. Rascunhos antigos (8 objetivos "traduzidos")
continuam funcionando: ``from_legacy`` monta o mesmo bloco que a publicação antiga usava.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

# --- Campanha -------------------------------------------------------------------------------

OBJECTIVES: Dict[str, Dict[str, str]] = {
    "OUTCOME_AWARENESS": {"label": "Reconhecimento", "icon": "megaphone",
                          "hint": "Mostre seus anúncios para as pessoas com maior probabilidade de se lembrar deles."},
    "OUTCOME_TRAFFIC": {"label": "Tráfego", "icon": "cursor",
                        "hint": "Envie pessoas para um destino, como seu site, app, perfil do Instagram ou evento do Facebook."},
    "OUTCOME_ENGAGEMENT": {"label": "Engajamento", "icon": "chat",
                           "hint": "Receba mais mensagens, compras por mensagem, visualizações do vídeo, engajamento com a publicação ou curtidas da Página."},
    "OUTCOME_LEADS": {"label": "Cadastros", "icon": "filter",
                      "hint": "Colete cadastros para sua empresa ou marca."},
    "OUTCOME_APP_PROMOTION": {"label": "Promoção do app", "icon": "phone",
                              "hint": "Encontre novas pessoas para instalar seu app e continuar usando-o."},
    "OUTCOME_SALES": {"label": "Vendas", "icon": "bag",
                      "hint": "Encontre pessoas com probabilidade de comprar seu produto ou serviço."},
}

# Categoria especial de anúncio (nomes atuais da API; "CREDIT" virou FINANCIAL_PRODUCTS_SERVICES).
SPECIAL_CATEGORIES: Dict[str, str] = {
    "FINANCIAL_PRODUCTS_SERVICES": "Produtos e serviços financeiros",
    "EMPLOYMENT": "Emprego",
    "HOUSING": "Moradia",
    "ISSUES_ELECTIONS_POLITICS": "Questões sociais, eleições ou política",
}

BID_STRATEGIES: Dict[str, Dict[str, str]] = {
    "LOWEST_COST_WITHOUT_CAP": {"label": "Volume mais alto", "hint": "Obter o maior número de resultados com o orçamento."},
    "COST_CAP": {"label": "Meta de custo por resultado", "hint": "Tentar manter o custo médio por resultado perto do valor informado."},
    "LOWEST_COST_WITH_BID_CAP": {"label": "Limite de lance", "hint": "Definir o lance máximo em cada leilão."},
    "LOWEST_COST_WITH_MIN_ROAS": {"label": "Meta de ROAS", "hint": "Manter um retorno mínimo sobre o investimento em anúncios."},
}
VALUE_BID_STRATEGIES = ("LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_MIN_ROAS")
VOLUME_BID_STRATEGIES = ("LOWEST_COST_WITHOUT_CAP", "COST_CAP", "LOWEST_COST_WITH_BID_CAP")

# --- Conjunto de anúncios -------------------------------------------------------------------

LOCATIONS: Dict[str, str] = {
    "NONE": "Sem local de conversão",
    "WEBSITE": "Site",
    "APP": "App",
    "MESSAGING": "Apps de mensagem",
    "ON_AD": "Formulários instantâneos",
    "ON_POST": "No seu anúncio",
    "PHONE_CALL": "Ligações",
    "ON_PAGE": "Página do Facebook",
    "INSTAGRAM_PROFILE": "Perfil do Instagram",
}
MESSAGING_APPS: Dict[str, str] = {"MESSENGER": "Messenger", "INSTAGRAM_DIRECT": "Instagram", "WHATSAPP": "WhatsApp"}

GOALS: Dict[str, str] = {
    "REACH": "Maximizar o alcance dos anúncios",
    "IMPRESSIONS": "Maximizar o número de impressões",
    "AD_RECALL_LIFT": "Maximizar a lembrança do anúncio",
    "THRUPLAY": "Maximizar ThruPlay",
    "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS": "Maximizar visualizações contínuas de 2 segundos do vídeo",
    "LANDING_PAGE_VIEWS": "Maximizar o número de visualizações da página de destino",
    "LINK_CLICKS": "Maximizar o número de cliques no link",
    "VISIT_INSTAGRAM_PROFILE": "Maximizar visitas ao perfil do Instagram",
    "CONVERSATIONS": "Maximizar o número de conversas",
    "POST_ENGAGEMENT": "Maximizar o engajamento com uma publicação",
    "PAGE_LIKES": "Maximizar o número de curtidas da Página",
    "QUALITY_CALL": "Maximizar o número de ligações",
    "OFFSITE_CONVERSIONS": "Maximizar o número de conversões",
    "VALUE": "Maximizar o valor das conversões",
    "LEAD_GENERATION": "Maximizar o número de leads",
    "QUALITY_LEAD": "Maximizar o número de leads de conversão",
    "APP_INSTALLS": "Maximizar o número de instalações do app",
}

# Objetivo → local de conversão → metas de desempenho, na ordem do Gerenciador (a primeira é a padrão).
MATRIX: Dict[str, Dict[str, List[str]]] = {
    "OUTCOME_AWARENESS": {"NONE": ["REACH", "IMPRESSIONS", "AD_RECALL_LIFT", "THRUPLAY"]},
    "OUTCOME_TRAFFIC": {
        "WEBSITE": ["LANDING_PAGE_VIEWS", "LINK_CLICKS", "IMPRESSIONS", "REACH"],
        "MESSAGING": ["LINK_CLICKS"],
        "INSTAGRAM_PROFILE": ["VISIT_INSTAGRAM_PROFILE"],
        "PHONE_CALL": ["QUALITY_CALL", "LINK_CLICKS"],
    },
    "OUTCOME_ENGAGEMENT": {
        "MESSAGING": ["CONVERSATIONS", "LINK_CLICKS"],
        "ON_POST": ["POST_ENGAGEMENT", "THRUPLAY", "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS", "IMPRESSIONS", "REACH"],
        "PHONE_CALL": ["QUALITY_CALL"],
        "WEBSITE": ["OFFSITE_CONVERSIONS", "LANDING_PAGE_VIEWS", "LINK_CLICKS", "IMPRESSIONS", "REACH"],
        "ON_PAGE": ["PAGE_LIKES"],
    },
    "OUTCOME_LEADS": {
        "WEBSITE": ["OFFSITE_CONVERSIONS", "LANDING_PAGE_VIEWS", "LINK_CLICKS", "IMPRESSIONS", "REACH"],
        "ON_AD": ["LEAD_GENERATION", "QUALITY_LEAD"],
        "MESSAGING": ["CONVERSATIONS", "LEAD_GENERATION"],
        "PHONE_CALL": ["QUALITY_CALL"],
    },
    "OUTCOME_APP_PROMOTION": {"APP": ["APP_INSTALLS", "LINK_CLICKS"]},
    "OUTCOME_SALES": {
        "WEBSITE": ["OFFSITE_CONVERSIONS", "VALUE", "LANDING_PAGE_VIEWS", "LINK_CLICKS", "IMPRESSIONS", "REACH"],
        "MESSAGING": ["CONVERSATIONS"],
        "PHONE_CALL": ["QUALITY_CALL"],
    },
}
# Na ordem em que o Gerenciador mostra os locais.
LOCATION_ORDER = ["NONE", "WEBSITE", "APP", "MESSAGING", "ON_AD", "ON_POST", "INSTAGRAM_PROFILE", "PHONE_CALL", "ON_PAGE"]

# Eventos padrão do pixel (conjunto de dados), com os nomes do Gerenciador.
EVENTS: Dict[str, str] = {
    "PURCHASE": "Compra",
    "ADD_TO_CART": "Adicionar ao carrinho",
    "INITIATE_CHECKOUT": "Iniciar finalização da compra",
    "ADD_PAYMENT_INFO": "Adicionar informações de pagamento",
    "CONTENT_VIEW": "Visualização do conteúdo",
    "ADD_TO_WISHLIST": "Adicionar à lista de desejos",
    "SEARCH": "Pesquisar",
    "LEAD": "Lead",
    "COMPLETE_REGISTRATION": "Concluir cadastro",
    "CONTACT": "Contato",
    "SUBMIT_APPLICATION": "Enviar candidatura",
    "SCHEDULE": "Agendar",
    "SUBSCRIBE": "Assinar",
    "START_TRIAL": "Iniciar avaliação",
}
# Nome do evento como o pixel registra (para marcar os que estão chegando).
EVENT_PIXEL_NAMES: Dict[str, str] = {
    "PURCHASE": "Purchase", "ADD_TO_CART": "AddToCart", "INITIATE_CHECKOUT": "InitiateCheckout",
    "ADD_PAYMENT_INFO": "AddPaymentInfo", "CONTENT_VIEW": "ViewContent", "ADD_TO_WISHLIST": "AddToWishlist",
    "SEARCH": "Search", "LEAD": "Lead", "COMPLETE_REGISTRATION": "CompleteRegistration", "CONTACT": "Contact",
    "SUBMIT_APPLICATION": "SubmitApplication", "SCHEDULE": "Schedule", "SUBSCRIBE": "Subscribe", "START_TRIAL": "StartTrial",
}
EVENT_DEFAULT = {"OUTCOME_SALES": "PURCHASE", "OUTCOME_LEADS": "LEAD", "OUTCOME_ENGAGEMENT": "CONTENT_VIEW"}

# --- Anúncio --------------------------------------------------------------------------------

CTAS: Dict[str, str] = {
    "NO_BUTTON": "Sem botão",
    "LEARN_MORE": "Saiba mais",
    "SHOP_NOW": "Comprar agora",
    "ORDER_NOW": "Pedir agora",
    "GET_OFFER": "Obter oferta",
    "SIGN_UP": "Cadastre-se",
    "SUBSCRIBE": "Assinar",
    "APPLY_NOW": "Candidatar-se",
    "GET_QUOTE": "Solicitar cotação",
    "CONTACT_US": "Fale conosco",
    "BOOK_TRAVEL": "Reservar agora",
    "DOWNLOAD": "Baixar",
    "WATCH_MORE": "Assistir mais",
    "SEE_MENU": "Ver cardápio",
    "SEND_WHATSAPP_MESSAGE": "Enviar mensagem do WhatsApp",
    "WHATSAPP_MESSAGE": "Enviar mensagem do WhatsApp",
    "MESSAGE_PAGE": "Enviar mensagem",
    "INSTAGRAM_MESSAGE": "Enviar mensagem pelo Instagram",
    "CALL_NOW": "Ligar agora",
    "INSTALL_MOBILE_APP": "Instalar agora",
    "USE_APP": "Usar app",
    "LIKE_PAGE": "Curtir Página",
    "VIEW_INSTAGRAM_PROFILE": "Ver perfil do Instagram",
}
_LINK_CTAS = ["LEARN_MORE", "SHOP_NOW", "ORDER_NOW", "GET_OFFER", "SIGN_UP", "SUBSCRIBE", "APPLY_NOW", "GET_QUOTE",
              "CONTACT_US", "BOOK_TRAVEL", "DOWNLOAD", "WATCH_MORE", "SEE_MENU", "NO_BUTTON"]
_FORM_CTAS = ["SIGN_UP", "LEARN_MORE", "SUBSCRIBE", "APPLY_NOW", "GET_QUOTE", "GET_OFFER", "DOWNLOAD", "BOOK_TRAVEL"]


def ctas_for(location: str, apps: List[str]) -> List[str]:
    """Botões que o Gerenciador oferece para o local de conversão."""
    if location == "MESSAGING":
        if apps == ["WHATSAPP"]:
            return ["WHATSAPP_MESSAGE"]
        if apps == ["INSTAGRAM_DIRECT"]:
            return ["INSTAGRAM_MESSAGE"]
        return ["MESSAGE_PAGE"]
    if location == "PHONE_CALL":
        return ["CALL_NOW"]
    if location == "APP":
        return ["INSTALL_MOBILE_APP", "USE_APP", "DOWNLOAD", "SHOP_NOW", "LEARN_MORE", "SIGN_UP"]
    if location == "ON_AD":
        return _FORM_CTAS
    if location == "ON_PAGE":
        return ["LIKE_PAGE"]
    if location == "INSTAGRAM_PROFILE":
        return ["VIEW_INSTAGRAM_PROFILE"]
    return _LINK_CTAS


def catalog() -> Dict[str, Any]:
    """Tudo o que a tela precisa para montar os três níveis com os nomes da Meta."""
    return {
        "objectives": [{"key": k, **v} for k, v in OBJECTIVES.items()],
        "special_categories": [{"key": k, "label": v} for k, v in SPECIAL_CATEGORIES.items()],
        "bid_strategies": [{"key": k, **v} for k, v in BID_STRATEGIES.items()],
        "locations": {k: v for k, v in LOCATIONS.items()},
        "location_order": LOCATION_ORDER,
        "messaging_apps": [{"key": k, "label": v} for k, v in MESSAGING_APPS.items()],
        "matrix": MATRIX,
        "goals": GOALS,
        "events": [{"key": k, "label": v} for k, v in EVENTS.items()],
        "ctas": CTAS,
        "ctas_by_location": {loc: ctas_for(loc, []) for loc in LOCATIONS} | {
            "MESSAGING:WHATSAPP": ctas_for("MESSAGING", ["WHATSAPP"]),
            "MESSAGING:INSTAGRAM_DIRECT": ctas_for("MESSAGING", ["INSTAGRAM_DIRECT"])},
    }


# --- Rascunho -------------------------------------------------------------------------------

def needs_event(goal: str, location: str) -> bool:
    return location == "WEBSITE" and goal in ("OFFSITE_CONVERSIONS", "VALUE")


def needs_video(goal: str) -> bool:
    return goal in ("THRUPLAY", "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS")


def bid_options(goal: str) -> List[str]:
    return list(VALUE_BID_STRATEGIES if goal == "VALUE" else VOLUME_BID_STRATEGIES)


# Rascunho antigo (objetivo "traduzido") → mesmo resultado que a publicação antiga gerava.
LEGACY: Dict[str, Dict[str, Any]] = {
    "trafego": {"objective": "OUTCOME_TRAFFIC", "conversion_location": "WEBSITE", "performance_goal": "LINK_CLICKS"},
    "alcance": {"objective": "OUTCOME_AWARENESS", "conversion_location": "NONE", "performance_goal": "REACH"},
    "engajamento": {"objective": "OUTCOME_ENGAGEMENT", "conversion_location": "ON_POST", "performance_goal": "POST_ENGAGEMENT"},
    "vendas": {"objective": "OUTCOME_SALES", "conversion_location": "WEBSITE", "performance_goal": "OFFSITE_CONVERSIONS",
               "conversion_event": "PURCHASE"},
    "whatsapp": {"objective": "OUTCOME_ENGAGEMENT", "conversion_location": "MESSAGING", "messaging_apps": ["WHATSAPP"],
                 "performance_goal": "CONVERSATIONS"},
    "leads": {"objective": "OUTCOME_LEADS", "conversion_location": "WEBSITE", "performance_goal": "OFFSITE_CONVERSIONS",
              "conversion_event": "LEAD"},
    "retencao": {"objective": "OUTCOME_SALES", "conversion_location": "WEBSITE", "performance_goal": "OFFSITE_CONVERSIONS",
                 "conversion_event": "PURCHASE"},
    "remarketing": {"objective": "OUTCOME_SALES", "conversion_location": "WEBSITE", "performance_goal": "OFFSITE_CONVERSIONS",
                    "conversion_event": "PURCHASE"},
}


def from_legacy(objective: str, daily_budget: float) -> Dict[str, Any]:
    base = LEGACY.get(objective) or LEGACY["trafego"]
    return {"objective": base["objective"], "special_ad_categories": [], "budget_level": "campaign", "budget_type": "daily",
            "budget": daily_budget, "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "bid_amount": None, "roas_floor": None,
            "conversion_location": base["conversion_location"], "messaging_apps": list(base.get("messaging_apps") or []),
            "performance_goal": base["performance_goal"], "conversion_event": base.get("conversion_event"),
            "app": None, "lead_form": None, "phone_number": None, "has_end_date": True, "use_existing_post": False}


def legacy_objective(meta: Dict[str, Any], current: str) -> str:
    """O objetivo "traduzido" equivalente, que o resto da plataforma usa para rótulo e métricas."""
    objective, location = meta["objective"], meta["conversion_location"]
    whatsapp = location == "MESSAGING" and "WHATSAPP" in meta["messaging_apps"]
    if current in ("retencao", "remarketing") and objective == "OUTCOME_SALES" and location == "WEBSITE":
        return current
    if whatsapp and objective in ("OUTCOME_ENGAGEMENT", "OUTCOME_SALES", "OUTCOME_LEADS"):
        return "whatsapp"
    return {"OUTCOME_SALES": "vendas", "OUTCOME_LEADS": "leads", "OUTCOME_TRAFFIC": "trafego", "OUTCOME_AWARENESS": "alcance",
            "OUTCOME_ENGAGEMENT": "engajamento", "OUTCOME_APP_PROMOTION": "trafego"}[objective]


def _money(value: Any) -> Optional[float]:
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _ref(value: Any, *extra: str) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None
    ref_id = str(value.get("id") or "").strip()
    if not re.fullmatch(r"\d{3,30}", ref_id):
        return None
    out = {"id": ref_id, "name": str(value.get("name") or "")[:120]}
    for key in extra:
        out[key] = str(value.get(key) or "")[:500]
    return out


def clean_meta(raw: Any, *, legacy_objective_key: str, daily_budget: float) -> Dict[str, Any]:
    """Normaliza o bloco da estrutura Meta. Combinações que não existem caem na primeira válida (como o Gerenciador faz)."""
    if not isinstance(raw, dict) or raw.get("objective") not in OBJECTIVES:
        return from_legacy(legacy_objective_key, daily_budget)
    objective = str(raw["objective"])
    locations = MATRIX[objective]
    location = str(raw.get("conversion_location") or "")
    if location not in locations:
        location = next(iter(locations))
    goals = locations[location]
    goal = str(raw.get("performance_goal") or "")
    if goal not in goals:
        goal = goals[0]
    apps = [a for a in MESSAGING_APPS if a in (raw.get("messaging_apps") or [])] if location == "MESSAGING" else []
    if location == "MESSAGING" and not apps:
        apps = ["WHATSAPP"]
    event = str(raw.get("conversion_event") or "").upper()
    if needs_event(goal, location):
        if goal == "VALUE":
            event = "PURCHASE"
        elif event not in EVENTS:
            event = EVENT_DEFAULT.get(objective, "PURCHASE")
    else:
        event = ""
    budget_type = "lifetime" if raw.get("budget_type") == "lifetime" else "daily"
    bid = str(raw.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP")
    if bid not in bid_options(goal):
        bid = "LOWEST_COST_WITHOUT_CAP"
    special = [c for c in SPECIAL_CATEGORIES if c in (raw.get("special_ad_categories") or [])]
    phone = re.sub(r"\D", "", str(raw.get("phone_number") or ""))[:15] or None
    has_end = True if budget_type == "lifetime" else bool(raw.get("has_end_date", True))
    return {
        "objective": objective,
        "special_ad_categories": special,
        "budget_level": "adset" if raw.get("budget_level") == "adset" else "campaign",
        "budget_type": budget_type,
        "budget": _money(raw.get("budget")) or 0.0,
        "bid_strategy": bid,
        "bid_amount": _money(raw.get("bid_amount")) if bid in ("COST_CAP", "LOWEST_COST_WITH_BID_CAP") else None,
        "roas_floor": _money(raw.get("roas_floor")) if bid == "LOWEST_COST_WITH_MIN_ROAS" else None,
        "conversion_location": location,
        "messaging_apps": apps,
        "performance_goal": goal,
        "conversion_event": event or None,
        "app": _ref(raw.get("app"), "store_url") if location == "APP" else None,
        "lead_form": _ref(raw.get("lead_form")) if location == "ON_AD" else None,
        "phone_number": phone if location == "PHONE_CALL" else None,
        "has_end_date": has_end,
        "use_existing_post": bool(raw.get("use_existing_post")),
    }


def days_between(start: str, end: str) -> int:
    from datetime import date
    try:
        return max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
    except ValueError:
        return 1


def daily_equivalent(meta: Dict[str, Any], start: str, end: str) -> float:
    """Verba por dia (o resto da plataforma mostra e compara por dia)."""
    if meta["budget_type"] == "lifetime":
        return round(meta["budget"] / days_between(start, end), 2)
    return meta["budget"]


def missing(meta: Dict[str, Any], payload: Dict[str, Any], min_daily: float) -> List[str]:
    """O que falta, no nível em que o Gerenciador pediria."""
    out: List[str] = []
    days = days_between(payload["start_date"], payload["end_date"])
    if meta["budget_type"] == "daily" and meta["budget"] < min_daily:
        out.append(f"Orçamento diário de pelo menos R$ {min_daily:.0f}".replace(".", ","))
    if meta["budget_type"] == "lifetime" and meta["budget"] < min_daily * days:
        out.append(f"Orçamento total de pelo menos R$ {min_daily * days:.0f} para {days} dias".replace(".", ","))
    if meta["bid_strategy"] in ("COST_CAP", "LOWEST_COST_WITH_BID_CAP") and not meta["bid_amount"]:
        out.append("Valor da meta de custo ou do limite de lance")
    if meta["bid_strategy"] == "LOWEST_COST_WITH_MIN_ROAS" and not meta["roas_floor"]:
        out.append("Meta de ROAS")
    location, goal = meta["conversion_location"], meta["performance_goal"]
    if location == "APP" and not (meta["app"] and meta["app"].get("store_url")):
        out.append("App da conta (com link da loja)")
    if location == "ON_AD" and not meta["lead_form"]:
        out.append("Formulário instantâneo da Página")
    if location == "PHONE_CALL" and not (meta["phone_number"] and len(meta["phone_number"]) >= 10):
        out.append("Número de telefone para as ligações (com DDI e DDD)")
    if needs_video(goal) and not any(u.get("media_type") == "video" for u in _units(payload["ad"])):
        out.append("Vídeo no anúncio (a meta escolhida conta visualizações de vídeo)")
    return out


def _units(ad: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [ad, *(ad.get("extra_ads") or [])]


# --- Publicação -----------------------------------------------------------------------------

def destination_type(meta: Dict[str, Any]) -> Optional[str]:
    """destination_type do conjunto, como a API espera."""
    location, goal = meta["conversion_location"], meta["performance_goal"]
    if location == "NONE":
        return None
    if location == "ON_POST":
        return "ON_VIDEO" if needs_video(goal) else "ON_POST"
    if location == "MESSAGING":
        apps = meta["messaging_apps"]
        if len(apps) == 1:
            return apps[0]
        return "MESSAGING_" + "_".join(sorted(apps, key=["INSTAGRAM_DIRECT", "MESSENGER", "WHATSAPP"].index))
    return location


def campaign_fields(meta: Dict[str, Any], name: str) -> Dict[str, str]:
    import json
    data = {"name": name, "objective": meta["objective"], "status": "PAUSED",
            "special_ad_categories": json.dumps(meta["special_ad_categories"])}
    if meta["special_ad_categories"]:
        data["special_ad_category_country"] = json.dumps(["BR"])
    if meta["budget_level"] == "campaign":
        cents = str(int(round(meta["budget"] * 100)))
        data["lifetime_budget" if meta["budget_type"] == "lifetime" else "daily_budget"] = cents
        data["bid_strategy"] = meta["bid_strategy"]
    else:
        # Orçamento por conjunto: a Meta exige dizer se os conjuntos podem dividir verba entre si.
        data["is_adset_budget_sharing_enabled"] = "false"
    return data


def adset_budget_fields(meta: Dict[str, Any]) -> Dict[str, str]:
    import json
    data: Dict[str, str] = {}
    if meta["budget_level"] == "adset":
        cents = str(int(round(meta["budget"] * 100)))
        data["lifetime_budget" if meta["budget_type"] == "lifetime" else "daily_budget"] = cents
        data["bid_strategy"] = meta["bid_strategy"]
    if meta["bid_amount"]:
        data["bid_amount"] = str(int(round(meta["bid_amount"] * 100)))
    if meta["roas_floor"]:
        data["bid_constraints"] = json.dumps({"roas_average_floor": int(round(meta["roas_floor"] * 10000))})
    return data


def billing_event(meta: Dict[str, Any]) -> str:
    return "THRUPLAY" if meta["performance_goal"] == "THRUPLAY" else "IMPRESSIONS"


def promoted_object(meta: Dict[str, Any], *, pixel_id: str, page_id: str, whatsapp_number: Optional[str]) -> Optional[Dict[str, Any]]:
    location, goal = meta["conversion_location"], meta["performance_goal"]
    if needs_event(goal, location):
        return {"pixel_id": pixel_id, "custom_event_type": meta["conversion_event"] or "PURCHASE"}
    if location == "APP" and meta["app"]:
        return {"application_id": meta["app"]["id"], "object_store_url": meta["app"]["store_url"]}
    if location == "MESSAGING":
        po: Dict[str, Any] = {"page_id": page_id}
        if "WHATSAPP" in meta["messaging_apps"] and whatsapp_number:
            po["whatsapp_phone_number"] = whatsapp_number
        return po
    if location in ("ON_AD", "PHONE_CALL", "ON_PAGE") or goal in ("PAGE_LIKES",):
        return {"page_id": page_id}
    return None


ERROR_LEVEL_HINTS = {"campaign": "Campanha", "adset": "Conjunto de anúncios", "ad": "Anúncio"}
