"""Variedade das pautas geradas pela IA (calendário do mês e Matriz).

Por que existe: gerando o mês inteiro num pedido só, sem ver o que já foi planejado antes,
a IA repetia temas, aberturas de gancho e chamadas para ação. Aqui ficam:

* ``ANGLES``: o "jeito" de cada pauta (bastidor, educativo, produto em detalhe...). A IA escolhe
  um por pauta e as regras pedem rodízio.
* ``recent_content``: títulos e ganchos dos últimos ~75 dias da marca, para a IA não repetir.
* ``find_repetitions``: conferência no código (sem IA) de gancho com a mesma abertura, pauta
  parecida com outra do mês ou com uma recente, e a mesma chamada para ação usada demais.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Sequence

ANGLES = {
    "bastidor": "bastidor (como é feito, quem faz, o dia a dia da marca)",
    "educativo": "educativo (ensina algo útil sobre o produto ou o tema)",
    "produto_em_detalhe": "produto em detalhe (um produto, uma característica real)",
    "uso_no_dia_a_dia": "uso no dia a dia (o produto na rotina de quem compra)",
    "comparacao": "comparação ou antes e depois (só com fatos dos dados)",
    "curiosidade": "curiosidade ou fato surpreendente sobre o tema",
    "pergunta_ao_publico": "pergunta ou enquete que puxa conversa",
    "prova_social": "prova social (só se houver depoimento ou resultado real nos dados)",
    "oferta": "oferta ou campanha ativa (só a que está nos dados)",
    "tendencia": "assunto em alta que combina com a marca",
    "data_comemorativa": "data do mês tratada do jeito da marca",
    "lifestyle": "estilo de vida e desejo (o universo da marca)",
}

VARIETY_RULES = (
    "- VARIEDADE (obrigatório):\n"
    "  * angle: escolha um ângulo da lista para cada pauta. Nunca o mesmo ângulo em duas pautas seguidas, "
    "e no máximo 2 pautas com o mesmo ângulo por semana.\n"
    "  * Cada gancho começa de um jeito diferente: as 3 primeiras palavras não podem se repetir no mês. "
    "Alterne entre pergunta, afirmação forte, cena, número real dos dados, contraste e convite.\n"
    "  * Nada de pauta parecida com outra do mês nem com as de 'ja_planejado_recente' (mesmo tema com outras palavras conta como repetição).\n"
    "  * Varie a chamada para ação: a mesma CTA no máximo 2 vezes no mês.\n"
    "  * Legenda enxuta: até 600 caracteres, parágrafos curtos, sem repetir o gancho palavra por palavra.\n"
)

BRIEFING_RULES = (
    "- BRIEFING (para quem vai produzir a peça, curto e direto):\n"
    "  * objective: o que esta peça precisa fazer, em 1 frase (ex.: gerar conversa, mostrar o produto em uso, levar ao link).\n"
    "  * key_message: a única ideia que o público deve guardar, em 1 frase.\n"
    "  * script: conforme o formato. Reels/vídeo: cenas numeradas (o que aparece e o que se fala), gancho nos 3 primeiros segundos, CTA no fim. "
    "Carrossel: texto de cada slide numerado (Slide 1 = capa com o gancho, último com CTA). Stories: telas numeradas com a interação. "
    "Imagem: o texto que vai na arte. No máximo 6 itens, frases curtas.\n"
    "  * visual_idea: direção da arte em 2 a 4 linhas: cena ou composição, enquadramento, o que aparece, luz e cores da marca, texto na arte.\n"
)

STOPWORDS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "um", "uma", "para", "pra",
             "com", "que", "por", "se", "seu", "sua", "seus", "suas", "como", "mais", "ao", "aos", "ou", "the", "and", "of", "to", "in", "your"}


def _plain(text: Any) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", value).strip()


def _words(text: Any) -> List[str]:
    return [w for w in _plain(text).split() if w]


def opening(hook: Any, size: int = 3) -> str:
    return " ".join(_words(hook)[:size])


def topic_tokens(text: Any) -> set:
    return {w for w in _words(text) if w not in STOPWORDS and len(w) > 2}


def similarity(a: Any, b: Any) -> float:
    ta, tb = topic_tokens(a), topic_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def cta_of(caption: Any) -> str:
    """Última frase da legenda sem hashtags (onde fica a chamada para ação)."""
    text = re.sub(r"#\S+", " ", str(caption or "")).strip()
    parts = [p for p in re.split(r"(?<=[.!?])\s+|\n+", text) if _words(p)]
    return " ".join(_words(parts[-1])[:5]) if parts else ""


def find_repetitions(items: Sequence[Dict[str, Any]], previous: Iterable[Dict[str, Any]] = (), *,
                     title_threshold: float = 0.6, max_cta: int = 2) -> Dict[int, List[str]]:
    """Índice da pauta → motivos de repetição. A primeira ocorrência fica; as seguintes são marcadas."""
    previous = list(previous)
    out: Dict[int, List[str]] = {}
    seen_openings: Dict[str, int] = {}
    cta_count: Dict[str, int] = {}
    for i, item in enumerate(items):
        reasons: List[str] = []
        op = opening(item.get("hook"))
        if op and len(op.split()) >= 2:
            if op in seen_openings:
                reasons.append(f"gancho começa igual a outra pauta do mês (\"{op}\")")
            else:
                seen_openings[op] = i
        title = item.get("title")
        for j in range(i):
            if similarity(title, items[j].get("title")) >= title_threshold:
                reasons.append(f"pauta parecida com \"{items[j].get('title')}\"")
                break
        for old in previous:
            if similarity(title, old.get("title")) >= title_threshold or (op and len(op.split()) >= 3 and op == opening(old.get("hook"))):
                reasons.append(f"repete conteúdo recente (\"{old.get('title')}\")")
                break
        cta = cta_of(item.get("caption_draft"))
        if cta and len(cta.split()) >= 2:
            cta_count[cta] = cta_count.get(cta, 0) + 1
            if cta_count[cta] > max_cta:
                reasons.append(f"chamada para ação repetida (\"{cta}\")")
        if reasons:
            out[i] = reasons
    return out


async def recent_content(client_id: str, *, days: int = 75, exclude_month: str | None = None, limit: int = 80) -> List[Dict[str, Any]]:
    """Títulos e ganchos planejados ou publicados nos últimos dias (fora os rascunhos da IA do mês que vai ser refeito)."""
    from .ig_supabase import sb_select
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = await sb_select("studio_calendar_items", select="title,hook,month,origin,status",
                               filters={"client_id": f"eq.{client_id}", "scheduled_at": f"gte.{since}"},
                               order="scheduled_at.desc", limit=limit * 2)
    except Exception as error:  # contexto opcional: sem ele a geração segue (só sem a lista do que já foi planejado)
        print(f"[studio][variety] recent_content indisponível: {type(error).__name__}")
        return []
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if exclude_month and str(row.get("month"))[:7] == exclude_month[:7] and row.get("origin") == "ia" and row.get("status") == "rascunho":
            continue
        if row.get("title"):
            out.append({"title": str(row["title"])[:160], "hook": str(row.get("hook") or "")[:160]})
        if len(out) >= limit:
            break
    return out
