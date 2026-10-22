"""Remove identificadores técnicos do texto que chega ao cliente.

O modelo cita evidências por `metric_ids` e `sources` (campos estruturados),
mas às vezes também escreve esses identificadores dentro do texto livre —
por exemplo "Pedidos subiram (metric_ids: orders, new_customers)". Isso não
pode chegar à tela nem ao PDF: o cliente lê "Pedidos" e "Novos clientes",
nunca `orders` ou `new_customers`.

Regras (determinísticas, sem IA):
1. Um trecho entre parênteses/colchetes que só cita identificadores
   ("(metric_ids: orders)", "[sources: meta_ads]") é removido.
2. Uma citação solta ("metric_ids: orders, new_customers") vira os rótulos
   ("Pedidos, Novos clientes").
3. Um identificador com sublinhado conhecido ("new_customers", "meta_ads")
   vira o rótulo. Identificadores de uma palavra só ("orders") são trocados
   apenas dentro de uma citação técnica, para não alterar texto comum.

Os campos estruturados (`metric_ids`, `sources`) não são tocados: continuam
servindo de evidência auditável.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping

# Rótulos de referência quando o snapshot da análise não traz o rótulo (ex.:
# registros antigos, respostas de conversa). O snapshot sempre tem prioridade.
DEFAULT_LABELS: Dict[str, str] = {
    "revenue": "Faturamento",
    "investment": "Investimento",
    "meta_investment": "Investimento Meta",
    "google_ads_investment": "Investimento Google Ads",
    "roas": "ROAS",
    "cpa": "CPA",
    "orders": "Pedidos",
    "average_ticket": "Ticket médio",
    "conversion_rate": "Taxa de conversão",
    "new_customers": "Novos clientes",
    "repeat_customers": "Clientes recorrentes",
    "sessions": "Sessões",
    "followers_growth": "Crescimento de seguidores",
    "instagram_profile_views": "Visitas ao perfil",
    "spend": "Investimento",
    "clicks": "Cliques",
    "impressions": "Impressões",
    "conversions": "Conversões",
    "reach": "Alcance",
    # Fontes
    "meta_ads": "Meta Ads",
    "instagram": "Instagram",
    "instagram_content": "Instagram · publicações",
    "ga4": "Google Analytics 4",
    "google_ads": "Google Ads",
    "shopify": "Shopify",
    "fbits": "FBITS",
    "fbits_official": "FBITS · indicadores oficiais",
    "paid_media": "mídia paga",
    "commerce": "loja",
}

_KEY = r"(?:metric_ids?|metricids?|source_ids?|sources?|evidence_ids?)"
# Pontos só no meio do identificador: o ponto final da frase não entra.
_ID = r"[A-Za-z][A-Za-z0-9_+\-]*(?:\.[A-Za-z0-9_]+)*"
_ID_LIST = rf"{_ID}(?:\s*[,/]\s*{_ID})*"

# "(metric_ids: orders, new_customers)" / "[sources = meta_ads]"
_BRACKETED = re.compile(
    rf"\s*[\(\[]\s*`?{_KEY}`?\s*[:=]\s*`?\[?\s*{_ID_LIST}\s*\]?`?\s*[\)\]]",
    re.IGNORECASE,
)
# "metric_ids: orders, new_customers"
_INLINE = re.compile(
    rf"`?{_KEY}`?\s*[:=]\s*`?\[?\s*(?P<ids>{_ID_LIST})\s*\]?`?",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s*[,/]\s*")
_CLEAN_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_EMPTY_PARENS = re.compile(r"\(\s*\)|\[\s*\]")


def build_labels(
    metrics: Iterable[Mapping[str, Any]] | None = None,
    sources: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, str]:
    """Rótulos por identificador: snapshot da análise primeiro, padrão depois."""
    labels = dict(DEFAULT_LABELS)
    for row in list(sources or []) + list(metrics or []):
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("id") or "").strip()
        label = str(row.get("label") or "").strip()
        if key and label:
            labels[key] = label
    return labels


def _label_list(raw: str, labels: Mapping[str, str]) -> str:
    names: List[str] = []
    for token in _SPLIT.split(raw.strip().strip("[]`")):
        token = token.strip().strip("`'\"")
        if not token:
            continue
        label = labels.get(token) or labels.get(token.lower())
        if not label:
            # Identificador desconhecido sem cara de palavra: some. Palavra
            # comum (sem sublinhado) fica, para não apagar texto do modelo.
            if "_" in token:
                continue
            label = token
        if label not in names:
            names.append(label)
    return ", ".join(names)


def humanize_text(text: Any, labels: Mapping[str, str]) -> Any:
    """Troca identificadores técnicos por rótulos. Não-texto volta igual."""
    if not isinstance(text, str) or not text:
        return text
    out = _BRACKETED.sub("", text)
    out = _INLINE.sub(lambda m: _label_list(m.group("ids"), labels), out)
    # Identificadores com sublinhado (ex.: new_customers) em qualquer lugar.
    for key in sorted((k for k in labels if "_" in k), key=len, reverse=True):
        if key in out:
            out = re.sub(rf"`?(?<![\w]){re.escape(key)}(?![\w])`?", labels[key], out)
    out = _EMPTY_PARENS.sub("", out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    out = _CLEAN_SPACES.sub(" ", out)
    return out.strip()


def has_technical_ids(text: Any, labels: Mapping[str, str]) -> bool:
    if not isinstance(text, str):
        return False
    if _INLINE.search(text):
        return True
    return any(
        re.search(rf"(?<![\w]){re.escape(key)}(?![\w])", text)
        for key in labels if "_" in key
    )


_ANALYSIS_TEXT_FIELDS = {
    "insights": ("title", "interpretation", "action", "reason", "limitations"),
    "actions": ("recommendation", "justification", "impact_expected"),
}
_ANSWER_TEXT_FIELDS = ("direct_answer",)
_ANSWER_LIST_FIELDS = ("evidence", "attention_points", "recommendations", "next_steps")


def humanize_analysis(analysis: Any, labels: Mapping[str, str]) -> Any:
    """Limpa o texto livre de uma análise, mantendo os campos estruturados."""
    if not isinstance(analysis, dict):
        return analysis
    executive = analysis.get("executive")
    if isinstance(executive, dict):
        for key, value in list(executive.items()):
            executive[key] = humanize_text(value, labels)
    for section, fields in _ANALYSIS_TEXT_FIELDS.items():
        for item in analysis.get(section) or []:
            if not isinstance(item, dict):
                continue
            for field in fields:
                if field in item:
                    item[field] = humanize_text(item[field], labels)
    return analysis


def humanize_answer(answer: Any, labels: Mapping[str, str]) -> Any:
    """Limpa o texto livre de uma resposta de conversa."""
    if not isinstance(answer, dict):
        return answer
    for field in _ANSWER_TEXT_FIELDS:
        if field in answer:
            answer[field] = humanize_text(answer[field], labels)
    for field in _ANSWER_LIST_FIELDS:
        values = answer.get(field)
        if isinstance(values, list):
            answer[field] = [humanize_text(value, labels) for value in values]
    return answer


def humanize_analysis_row(row: Any) -> Any:
    """Linha de `ai_analyses` lida do banco: limpa registros antigos também."""
    if not isinstance(row, dict) or not isinstance(row.get("analysis"), dict):
        return row
    labels = build_labels(row.get("metrics_snapshot"), row.get("sources"))
    row["analysis"] = humanize_analysis(row["analysis"], labels)
    return row
