"""Radar do evento: clima e notícias da região do evento, para a produção se planejar.

Com o local (``inputs.location``) e a data alvo do evento:

* Clima (Open-Meteo, sem chave):
  - até 15 dias à frente → PREVISÃO do dia: máxima, mínima, chance de chuva, chuva prevista, vento e condição;
  - mais longe (ou sem data) → CLIMA TÍPICO da época: média dos 3 últimos anos na mesma semana (máxima, mínima e
    em quantos dias choveu), deixando claro que é histórico, não previsão;
  - data que já passou → só avisa.
* Notícias da região (Google Notícias, últimos 7 dias): chuva, temporal, alagamento e Defesa Civil; trânsito,
  interdição, greve e manifestação. Só manchete, fonte, data e link.
* Alertas para a produção (regras simples e explicáveis): chuva provável → plano B coberto; calor forte →
  hidratação e sombra; frio → aquecimento; vento forte → atenção a tendas, estruturas e som.

O resultado fica salvo no evento (``studio_projects.radar``) e entra no plano da IA (riscos, checklist e plano B)
e no copiloto. Fonte fora do ar vira aviso; o radar nunca derruba o evento.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from .studio_calendar import SAO_PAULO, StudioError

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 15
CLIMATE_YEARS = 3
CLIMATE_WINDOW = 3          # dias antes e depois da data, em cada ano
RAIN_MM = 1.0               # dia "com chuva"
TIMEOUT = 12.0
NEWS_QUERIES = (
    ("clima", "chuva OR temporal OR alagamento OR \"Defesa Civil\" OR alerta"),
    ("cidade", "trânsito OR interdição OR greve OR manifestação OR bloqueio"),
)
NEWS_PER_QUERY = 6
_GEO_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}

# Códigos WMO usados pelo Open-Meteo → texto curto.
WEATHER_CODES: Dict[int, str] = {
    0: "céu limpo", 1: "quase limpo", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina com geada",
    51: "garoa fraca", 53: "garoa", 55: "garoa forte", 56: "garoa congelante", 57: "garoa congelante forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte", 66: "chuva congelante", 67: "chuva congelante forte",
    71: "neve fraca", 73: "neve", 75: "neve forte", 77: "grãos de neve", 80: "pancadas fracas", 81: "pancadas de chuva",
    82: "pancadas fortes", 85: "pancadas de neve", 86: "pancadas de neve fortes", 95: "trovoadas",
    96: "trovoadas com granizo", 99: "trovoadas com granizo forte",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("resposta inválida")
    return data


def _num(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ local

def place_candidates(location: str) -> List[str]:
    """'Loja Jardins, Rua Oscar Freire 100, São Paulo - SP' → tenta a cidade antes do endereço."""
    text = " ".join(str(location or "").split())[:200]
    if not text:
        return []
    parts = [p.strip(" -") for chunk in text.split(",") for p in chunk.split(" - ") if p.strip(" -")]
    candidates = [p for p in reversed(parts) if len(p) > 2 and not p.isupper()] + [p for p in parts if p.isupper() and len(p) > 2] + [text]
    return list(dict.fromkeys(candidates))[:5]


async def geocode(location: str) -> Optional[Dict[str, Any]]:
    key = location.strip().lower()
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    found: Optional[Dict[str, Any]] = None
    for name in place_candidates(location):
        data = await _json(GEOCODE, {"name": name, "count": 1, "language": "pt", "format": "json"})
        hit = (data.get("results") or [None])[0]
        if hit and _num(hit.get("latitude")) is not None:
            found = {"name": hit.get("name"), "region": hit.get("admin1"), "country": hit.get("country"),
                     "latitude": float(hit["latitude"]), "longitude": float(hit["longitude"]), "timezone": hit.get("timezone")}
            break
    _GEO_CACHE[key] = found
    return found


# ------------------------------------------------------------------ clima

async def forecast(place: Dict[str, Any], day: date) -> Dict[str, Any]:
    data = await _json(FORECAST, {
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
        "start_date": day.isoformat(), "end_date": day.isoformat(),
    })
    daily = data.get("daily") or {}

    def first(key: str) -> Optional[float]:
        values = daily.get(key) or []
        return _num(values[0]) if values else None
    code = first("weather_code")
    return {"tipo": "previsao", "data": day.isoformat(), "condicao": WEATHER_CODES.get(int(code), "sem descrição") if code is not None else None,
            "max": first("temperature_2m_max"), "min": first("temperature_2m_min"),
            "chance_chuva": first("precipitation_probability_max"), "chuva_mm": first("precipitation_sum"),
            "vento_kmh": first("wind_speed_10m_max")}


async def typical_climate(place: Dict[str, Any], day: date, today: date) -> Dict[str, Any]:
    """Mesma semana nos 3 últimos anos que já terminaram (histórico, não previsão)."""
    years = []
    for back in range(1, CLIMATE_YEARS + 1):
        try:
            center = day.replace(year=day.year - back)
        except ValueError:  # 29/02
            center = day.replace(year=day.year - back, day=28)
        if center + timedelta(days=CLIMATE_WINDOW) >= today:
            center = center.replace(year=center.year - 1)
        years.append(center)

    async def one(center: date) -> Dict[str, Any]:
        return await _json(ARCHIVE, {"latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
                                     "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                                     "start_date": (center - timedelta(days=CLIMATE_WINDOW)).isoformat(),
                                     "end_date": (center + timedelta(days=CLIMATE_WINDOW)).isoformat()})
    results = await asyncio.gather(*(one(c) for c in years), return_exceptions=True)
    highs, lows, rain = [], [], []
    for r in results:
        if isinstance(r, Exception):
            continue
        d = r.get("daily") or {}
        highs += [v for v in (_num(x) for x in d.get("temperature_2m_max") or []) if v is not None]
        lows += [v for v in (_num(x) for x in d.get("temperature_2m_min") or []) if v is not None]
        rain += [v for v in (_num(x) for x in d.get("precipitation_sum") or []) if v is not None]
    if not highs:
        raise ValueError("sem histórico")
    return {"tipo": "clima_tipico", "data": day.isoformat(), "anos": len([r for r in results if not isinstance(r, Exception)]),
            "max": round(mean(highs), 1), "min": round(mean(lows), 1) if lows else None,
            "dias_com_chuva_pct": round(sum(1 for v in rain if v >= RAIN_MM) / len(rain) * 100) if rain else None,
            "chuva_media_mm": round(mean(rain), 1) if rain else None}


def alerts(weather: Dict[str, Any]) -> List[Dict[str, str]]:
    """Regras simples para a produção. Clima típico conta como tendência (gravidade menor)."""
    if not weather or weather.get("tipo") not in ("previsao", "clima_tipico"):
        return []
    typical = weather["tipo"] == "clima_tipico"
    out: List[Dict[str, str]] = []
    rain = weather.get("dias_com_chuva_pct") if typical else weather.get("chance_chuva")
    if rain is not None and rain >= (40 if typical else 50):
        out.append({"tipo": "chuva", "gravidade": "media" if typical else ("alta" if rain >= 70 else "media"),
                    "texto": (f"Chove em {int(rain)}% dos dias nesta época" if typical else f"Chance de chuva de {int(rain)}%")
                    + ": tenha plano B coberto (tenda, área interna) e proteja equipamento e cenografia."})
    hi, lo = weather.get("max"), weather.get("min")
    if hi is not None and hi >= 32:
        out.append({"tipo": "calor", "gravidade": "alta" if hi >= 36 else "media",
                    "texto": f"Máxima de {hi:.0f}°C: água para equipe e convidados, sombra, ventilação e cuidado com produto e maquiagem."})
    if lo is not None and lo <= 8:
        out.append({"tipo": "frio", "gravidade": "media", "texto": f"Mínima de {lo:.0f}°C: aquecimento, área coberta e figurino adequado."})
    wind = weather.get("vento_kmh")
    if wind is not None and wind >= 40:
        out.append({"tipo": "vento", "gravidade": "alta" if wind >= 60 else "media",
                    "texto": f"Vento de até {wind:.0f} km/h: amarre tendas, banners e estruturas; atenção ao som externo e drone."})
    return out


# ------------------------------------------------------------------ notícias

async def region_news(city: str) -> List[Dict[str, Any]]:
    from . import news_engine
    out: List[Dict[str, Any]] = []
    for kind, words in NEWS_QUERIES:
        query = f'"{city}" ({words}) when:7d'
        xml = await news_engine._get(news_engine.GOOGLE_NEWS.format(q=quote_plus(query)))
        for item in news_engine.parse_feed(xml or "", limit=NEWS_PER_QUERY):
            out.append({"tema": kind, "manchete": " ".join(str(item.get("title") or "").split())[:180],
                        "fonte": item.get("source"), "data": str(item.get("published_at") or "")[:10] or None, "link": item.get("url")})
    unique = news_engine.dedupe([{**i, "title": i["manchete"], "url": i["link"]} for i in out if i["manchete"] and i["link"]])
    return [{k: v for k, v in i.items() if k not in ("title", "url", "url_hash")} for i in unique][:10]


# ------------------------------------------------------------------ radar

async def build_radar(location: str, target: Optional[date], *, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or datetime.now(SAO_PAULO).date()
    warnings: List[str] = []
    location = " ".join(str(location or "").split())
    if not location:
        raise StudioError("EVENT_LOCATION_REQUIRED", "Coloque o local do evento (cidade ou endereço) para puxar clima e notícias.")
    try:
        place = await geocode(location)
    except Exception as exc:  # noqa: BLE001
        print(f"[event_radar] geocode_failed error_type={type(exc).__name__}")
        place = None
        warnings.append("Não deu para localizar a cidade agora.")
    if place is None and not warnings:
        warnings.append("Não encontramos a cidade. Escreva o local com a cidade (ex.: Rua X, São Paulo).")

    weather: Dict[str, Any] = {}
    if place:
        try:
            if target and target < today:
                weather = {"tipo": "passou", "data": target.isoformat()}
            elif target and (target - today).days <= FORECAST_DAYS:
                weather = await forecast(place, target)
            else:
                weather = await typical_climate(place, target or today + timedelta(days=30), today)
        except Exception as exc:  # noqa: BLE001
            print(f"[event_radar] weather_failed error_type={type(exc).__name__}")
            warnings.append("Clima indisponível agora. Tente atualizar mais tarde.")
    news: List[Dict[str, Any]] = []
    city = (place or {}).get("name") or (place_candidates(location) or [location])[0]
    try:
        news = await region_news(city)
    except Exception as exc:  # noqa: BLE001
        print(f"[event_radar] news_failed error_type={type(exc).__name__}")
        warnings.append("Notícias da região indisponíveis agora.")
    return {"local": {k: place.get(k) for k in ("name", "region", "country", "latitude", "longitude")} if place else {"name": city},
            "clima": weather, "alertas": alerts(weather), "noticias": news, "avisos": warnings,
            "atualizado_em": _now().isoformat()}


def radar_text(radar: Dict[str, Any]) -> str:
    """Resumo do radar para a IA do plano e o copiloto."""
    if not radar:
        return ""
    w, place = radar.get("clima") or {}, (radar.get("local") or {}).get("name") or "região"
    lines = [f"Local: {place}"]
    if w.get("tipo") == "previsao":
        lines.append(f"Previsão para {w.get('data')}: {w.get('condicao') or ''}, máx {w.get('max')}°C, mín {w.get('min')}°C, "
                     f"chance de chuva {w.get('chance_chuva')}%, vento até {w.get('vento_kmh')} km/h.")
    elif w.get("tipo") == "clima_tipico":
        lines.append(f"Clima típico da época (histórico de {w.get('anos')} anos, não é previsão): máx {w.get('max')}°C, "
                     f"mín {w.get('min')}°C, chove em {w.get('dias_com_chuva_pct')}% dos dias.")
    for a in radar.get("alertas") or []:
        lines.append(f"Alerta ({a.get('tipo')}): {a.get('texto')}")
    for n in (radar.get("noticias") or [])[:6]:
        lines.append(f"Notícia da região: {n.get('manchete')} ({n.get('fonte') or 'fonte'}, {n.get('data') or 's/d'})")
    return "\n".join(lines)[:2500]


async def refresh(client_id: str, project_id: str) -> Dict[str, Any]:
    from .ig_supabase import sb_update
    from .studio_projects import TABLE, get_project
    project = await get_project(client_id, project_id)
    if project.get("kind") != "evento":
        raise StudioError("PROJECT_KIND_INVALID", "Clima e notícias são do Evento.")
    target = None
    if project.get("target_date"):
        target = date.fromisoformat(str(project["target_date"])[:10])
    radar = await build_radar((project.get("inputs") or {}).get("location") or "", target)
    if len(json.dumps(radar, ensure_ascii=False, default=str)) > 30000:
        radar["noticias"] = radar["noticias"][:5]
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"}, patch={"radar": radar})
    return rows[0] if rows else {**project, "radar": radar}

