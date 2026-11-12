"""Parâmetros declarados por objetivo do Mídia On.

Os campos ficam dentro dos JSONs de estratégia/plano existentes. Este módulo
centraliza a validação sem transformar métricas distintas em equivalentes.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping

from .studio_calendar import StudioError


PARAMETERS = {
    "vendas": {
        "target_revenue": (0.01, 1_000_000_000.0),
        "target_roas": (0.01, 1_000.0),
    },
    "leads": {
        "target_leads": (1.0, 1_000_000_000.0),
        "max_cpl": (0.01, 100_000_000.0),
    },
    "trafego": {
        "target_clicks": (1.0, 1_000_000_000.0),
        "max_cpc": (0.01, 100_000_000.0),
    },
    "alcance": {
        "target_unique_reach": (1.0, 10_000_000_000.0),
        "planned_frequency": (1.0, 100.0),
    },
    "retencao": {
        "target_retention_rate": (0.01, 100.0),
        "customer_base": (1.0, 1_000_000_000.0),
    },
    "remarketing": {
        "target_conversions": (1.0, 1_000_000_000.0),
        "max_cpa": (0.01, 100_000_000.0),
    },
}


def clean_parameters(objective: str, raw: Mapping[str, Any] | None) -> Dict[str, float]:
    """Valida somente campos canônicos do objetivo e rejeita valores ambíguos."""
    allowed = PARAMETERS.get(objective)
    if allowed is None:
        raise StudioError("OBJECTIVE_INVALID")
    if not raw:
        return {}
    if not isinstance(raw, Mapping) or set(raw) - set(allowed):
        raise StudioError("OBJECTIVE_PARAMETERS_INVALID")
    clean: Dict[str, float] = {}
    for key, value in raw.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            raise StudioError("OBJECTIVE_PARAMETERS_INVALID")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise StudioError("OBJECTIVE_PARAMETERS_INVALID") from None
        lower, upper = allowed[key]
        if not math.isfinite(number) or not lower <= number <= upper:
            raise StudioError("OBJECTIVE_PARAMETERS_INVALID")
        clean[key] = round(number, 4)
    return clean


def target_metric(objective: str, params: Mapping[str, float]) -> tuple[str, float] | None:
    """Retorna apenas metas que correspondem às métricas modeladas.

    Leads e remarketing não usam automaticamente ``conversions`` porque esse
    evento pode representar outra ação. Retenção também exige dados de coorte,
    ausentes no modelo atual. Alcance usa impressões somente como proxy quando a
    própria equipe declara a frequência planejada.
    """
    if objective == "vendas" and params.get("target_revenue"):
        return "revenue", params["target_revenue"]
    if objective == "trafego" and params.get("target_clicks"):
        return "clicks", params["target_clicks"]
    if objective == "alcance" and params.get("target_unique_reach") and params.get("planned_frequency"):
        return "impressions", params["target_unique_reach"] * params["planned_frequency"]
    return None


def projection_limitation(objective: str, params: Mapping[str, float]) -> str | None:
    if not params:
        return None
    if objective == "leads":
        return "A meta de leads foi registrada, mas conversões da plataforma não comprovam leads sem uma definição de evento validada."
    if objective == "remarketing":
        return "A meta de remarketing foi registrada, mas o histórico agregado não isola público e conversões de remarketing."
    if objective == "retencao":
        return "A meta de retenção foi registrada, mas receita atribuída não comprova retenção sem dados de coorte e recompra."
    if objective == "alcance" and not (params.get("target_unique_reach") and params.get("planned_frequency")):
        return "Alcance único e impressões são métricas diferentes; informe também a frequência planejada para estimar a pressão de mídia."
    return None
