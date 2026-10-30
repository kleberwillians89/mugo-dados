"""Briefing do mês no Mídia On: o que a equipe precisa para a conta, em texto livre.

A IA transforma o texto em instruções VALIDADAS que o motor aplica nos números:

* datas do mês (lançamento, promoção, evento) → entram no calendário de
  investimento e puxam verba para os dias anteriores;
* campanhas (escalar, manter, otimizar, pausar) → só campanhas que existem na
  conta; a ação vem marcada "pedido no briefing";
* ênfase por canal (mais/menos Meta ou Google) → muda os limites da divisão;
* teto de verba → vira a verba do mês quando a equipe não informou outra.

O texto também vai para a leitura estratégica da IA. Se a interpretação falhar,
o briefing segue só como texto e a estratégia sai normalmente.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any, Dict, List, Optional

from .studio_calendar import StudioError

MAX_CHARS = 2000
CAMPAIGN_ACTIONS = ("escalar", "manter", "otimizar", "pausar")
EMPHASIS_SHARE = {"mais": 0.45, "menos": 0.20}  # "mais": ao menos 45% da verba · "menos": no máximo 20%


def clean(text: Optional[str]) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "")).strip()[:MAX_CHARS]


async def parse_briefing(client_id: str, text: str, *, month: date, campaigns: List[str],
                         channels: Dict[str, str]) -> Dict[str, Any]:
    from .studio_engines import throttle
    from .studio_llm import INT, STR, arr, llm_json, obj

    text = clean(text)
    if not text:
        return empty()
    throttle(client_id)
    names = sorted(set(campaigns))[:150]
    schema = obj({
        "summary": STR,
        "channel_emphasis": arr(obj({"channel": {"type": "string", "enum": list(channels)}, "emphasis": {"type": "string", "enum": ["mais", "menos"]}})),
        "campaigns": arr(obj({"campaign": {"type": "string", "enum": names or ["-"]}, "action": {"type": "string", "enum": list(CAMPAIGN_ACTIONS)}, "reason": STR})),
        "dates": arr(obj({"day": INT, "label": STR})),
        "budget_cap": INT,
    })
    last = calendar.monthrange(month.year, month.month)[1]
    data = await llm_json(
        instructions=("Você interpreta o briefing de mídia paga do mês escrito pela equipe da agência e extrai SÓ o que está "
                      "explícito. Não invente datas, campanhas ou valores."),
        prompt=(f"MÊS: {month.strftime('%Y-%m')} (dias 1 a {last})\nCANAIS: {channels}\nCAMPANHAS DA CONTA: {names}\n\n"
                f"BRIEFING:\n{text}\n\n"
                "Extraia: summary (1 frase do que a equipe precisa); channel_emphasis (só se o texto pedir mais ou menos de um canal); "
                "campaigns (só campanhas da lista citadas no texto, com a ação pedida e o motivo); dates (dias do mês citados, com o rótulo, "
                "ex.: lançamento, promoção, evento); budget_cap (verba máxima do mês em reais se o texto disser; senão 0)."),
        schema_name="media_briefing", schema=schema, temperature=0.1, timeout=45)
    return validate(data, month=month, campaigns=names, channels=channels)


def empty() -> Dict[str, Any]:
    return {"summary": "", "channel_emphasis": {}, "campaigns": {}, "dates": [], "budget_cap": None}


def validate(data: Dict[str, Any], *, month: date, campaigns: List[str], channels: Dict[str, str]) -> Dict[str, Any]:
    """A IA não decide nada fora do que existe: campanha da conta, dia do mês, canal conhecido."""
    last = calendar.monthrange(month.year, month.month)[1]
    known = set(campaigns)
    out = empty()
    out["summary"] = str(data.get("summary") or "")[:300]
    for row in data.get("channel_emphasis") or []:
        if row.get("channel") in channels and row.get("emphasis") in EMPHASIS_SHARE:
            out["channel_emphasis"][row["channel"]] = row["emphasis"]
    for row in data.get("campaigns") or []:
        if row.get("campaign") in known and row.get("action") in CAMPAIGN_ACTIONS:
            out["campaigns"][row["campaign"]] = {"action": row["action"], "reason": str(row.get("reason") or "")[:200]}
    seen = set()
    for row in data.get("dates") or []:
        try:
            day = int(row.get("day"))
        except (TypeError, ValueError):
            continue
        label = str(row.get("label") or "").strip()[:80]
        if 1 <= day <= last and label and day not in seen:
            seen.add(day)
            out["dates"].append({"date": date(month.year, month.month, day).isoformat(), "label": label})
    try:
        cap = float(data.get("budget_cap") or 0)
    except (TypeError, ValueError):
        cap = 0
    out["budget_cap"] = round(cap, 2) if 0 < cap <= 100_000_000 else None
    return out


def apply_to_campaigns(rows: List[Dict[str, Any]], directives: Dict[str, Any]) -> List[str]:
    applied = []
    for r in rows:
        wish = (directives.get("campaigns") or {}).get(r["campaign"])
        if not wish:
            continue
        before = r["action"]
        r["action"] = wish["action"]
        r["why"] = f"Pedido no briefing: {wish['reason'] or wish['action']} (a análise indicava {before})." if before != wish["action"] \
            else f"{r['why']}; confirmado no briefing"
        r["briefing"] = True
        applied.append(f"{r['campaign']}: {wish['action']}" + (f" (era {before})" if before != wish["action"] else ""))
    return applied


def describe(directives: Dict[str, Any], channels: Dict[str, str], campaign_changes: List[str], used_cap: bool) -> List[str]:
    """Como o briefing virou número, para a equipe conferir na tela."""
    out = []
    for c, emphasis in (directives.get("channel_emphasis") or {}).items():
        share = int(EMPHASIS_SHARE[emphasis] * 100)
        out.append(f"{channels[c]}: {'ao menos' if emphasis == 'mais' else 'no máximo'} {share}% da verba.")
    for d in directives.get("dates") or []:
        out.append(f"{d['label']} em {d['date'][8:10]}/{d['date'][5:7]}: verba reforçada nos dias anteriores.")
    out += [f"Campanha {c}." for c in campaign_changes]
    if used_cap:
        out.append(f"Verba do mês limitada a R$ {directives['budget_cap']:,.0f} (teto do briefing).".replace(",", "."))
    return out


def require_text(text: Optional[str]) -> str:
    value = clean(text)
    if len(value) > MAX_CHARS:
        raise StudioError("BRIEFING_TOO_LONG")
    return value
