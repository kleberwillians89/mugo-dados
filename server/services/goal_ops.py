"""Metas conectadas à operação: diagnóstico do desvio, recomendações da IA e tarefa no Kanban.

* Diagnóstico (sem IA): compara a primeira e a segunda metade do período observado nos indicadores que compõem a
  meta. Separa FATO (números) de HIPÓTESE (qual componente parece explicar) e não afirma causa.
* Recomendações (IA, só no clique): leem a meta, o diagnóstico, as metas relacionadas, a mídia, o planejamento e o
  cérebro da marca; cada item traz evidência, justificativa e o tipo (recomendação ou estimativa). Ficam registradas.
* Tarefa: só quando a pessoa confirma um item; usa o mesmo serviço do Kanban, guarda o vínculo e não duplica.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .goals import ADDITIVE, DRIVERS, RELATION, evaluate_goal, resolve_goal_actual, unavailable
from .ig_supabase import sb_insert, sb_select, sb_update

STABLE = 5.0     # variação até ±5%: estável
RELEVANT = 10.0  # variação a partir de 10%: relevante
TABLE = "goal_recommendations"


def _halves(start: date, observed_end: date) -> Optional[tuple]:
    days = (observed_end - start).days + 1
    if days < 6:
        return None
    mid = start + timedelta(days=days // 2 - 1)
    return (start, mid), (mid + timedelta(days=1), observed_end)


def compare(metric: str, first: Dict[str, Any], second: Dict[str, Any], len1: int, len2: int) -> Optional[Dict[str, Any]]:
    """Variação entre as metades: por dia para o que soma, nível para razões. Puro, para teste."""
    if not (first.get("available") and second.get("available")):
        return None
    a, b = float(first["actual"]), float(second["actual"])
    if metric in ADDITIVE:
        a, b = a / max(len1, 1), b / max(len2, 1)
    if a == 0:
        return None
    change = (b - a) / abs(a) * 100
    return {"before": a, "after": b, "change_percent": change, "per_day": metric in ADDITIVE,
            "trend": "estável" if abs(change) <= STABLE else "subiu" if change > 0 else "caiu"}


def explain(goal_metric: str, parts: Dict[str, Dict[str, Any]], labels: Dict[str, str]) -> Dict[str, Any]:
    """Fatos e, só quando os números sustentam, uma hipótese. Nunca afirma causa. Puro, para teste."""
    facts, moved, stable = [], [], []
    for key, c in parts.items():
        if not c:
            continue
        unit = " por dia" if c["per_day"] else ""
        facts.append(f"{labels[key]}{unit}: {c['trend']} ({c['change_percent']:+.0f}% entre a primeira e a segunda metade do período).")
        if abs(c["change_percent"]) >= RELEVANT:
            moved.append(key)
        elif abs(c["change_percent"]) <= STABLE:
            stable.append(key)
    hypothesis = None
    if len(moved) == 1 and stable:
        m = parts[moved[0]]
        hypothesis = (f"O desvio parece vir de {labels[moved[0]].lower()} ({m['trend']}), já que {', '.join(labels[s].lower() for s in stable)} "
                      "ficou estável. É uma leitura dos números, não uma causa comprovada.")
    return {"facts": facts, "hypothesis": hypothesis}


async def diagnosis(client_id: str, goal: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = today or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start, end = date.fromisoformat(str(goal["period_start"])), date.fromisoformat(str(goal["period_end"]))
    observed_end = min(end, today - timedelta(days=1))  # só dias fechados
    split = _halves(start, observed_end) if observed_end >= start else None
    drivers = DRIVERS.get(goal["metric"], [])
    if not split or not drivers:
        return {"available": False, "reason": ("O período observado ainda é curto (menos de 6 dias fechados) para comparar." if drivers
                                               else "Este indicador não tem componentes com dados para comparar.")}
    (a1, b1), (a2, b2) = split
    labels = {goal["metric"]: goal.get("label") or goal["metric"], **dict(drivers)}
    parts: Dict[str, Any] = {}
    for key in [goal["metric"], *[k for k, _ in drivers]]:
        try:
            first = await resolve_goal_actual(client_id, key, a1.isoformat(), b1.isoformat())
            second = await resolve_goal_actual(client_id, key, a2.isoformat(), b2.isoformat())
        except Exception:  # noqa: BLE001
            first = second = unavailable("leitura indisponível")
        parts[key] = compare(key, first, second, (b1 - a1).days + 1, (b2 - a2).days + 1)
    main = parts.pop(goal["metric"])
    out = explain(goal["metric"], parts, labels)
    if main:
        unit = " por dia" if main["per_day"] else ""
        out["facts"].insert(0, f"{labels[goal['metric']]}{unit}: {main['trend']} ({main['change_percent']:+.0f}%).")
    if not out["facts"]:
        return {"available": False, "reason": "Os componentes da meta não têm dados nas duas metades do período."}
    return {"available": True, "relation": RELATION.get(goal["metric"]), "periods": [[a1.isoformat(), b1.isoformat()], [a2.isoformat(), b2.isoformat()]], **out}


# ---------------------------------------------------------------- recomendações (IA, só no clique)

def _schema() -> Dict[str, Any]:
    from .studio_llm import STR, arr, obj
    return obj({"leitura": STR, "itens": arr(obj({"titulo": STR, "tipo": {"type": "string", "enum": ["recomendacao", "estimativa", "investigacao"]},
                                                     "evidencia": STR, "justificativa": STR, "acao": STR}))})


INSTRUCTIONS = (
    "Você é o estrategista da agência ajudando o profissional a decidir o que fazer com uma meta. Escreva em português, direto. "
    "Regras: use SOMENTE os dados recebidos; diferencie fato (o que os números mostram), hipótese e recomendação; não afirme causa "
    "quando há só correlação; faturamento total não é receita atribuída à mídia, e ROAS de uma plataforma não se aplica à outra; "
    "não estime investimento necessário se os dados não sustentarem; não proponha nada que exija dado que não foi informado. "
    "Respeite as RESTRIÇÕES do profissional. De 2 a 5 itens, cada um com evidência (número dos dados), justificativa e uma ação "
    "concreta que alguém do time possa executar (ex.: revisar verba entre campanhas X e Y, investigar a queda de conversão, "
    "refazer a peça Z). 'leitura' resume em 1 ou 2 frases. Nada é executado: o profissional escolhe."
)


async def _context(client_id: str, goal: Dict[str, Any], diag: Dict[str, Any]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"meta": {k: goal.get(k) for k in ("label", "metric", "direction", "target_value", "actual", "remaining", "status", "days_left",
                                                            "required_daily", "observed_daily", "origin", "period_start", "period_end")},
                           "diagnostico": diag}
    try:
        from .goals import list_goals
        related = (await list_goals(client_id, str(goal["period_start"]), str(goal["period_end"])))["goals"]
        ctx["metas_relacionadas"] = [{k: g.get(k) for k in ("label", "metric", "direction", "target_value", "actual", "status")}
                                     for g in related if g.get("id") != goal.get("id")][:8]
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = await sb_select("dashboard_daily_metrics", select="metric_date,meta_spend,meta_purchases,meta_attributed_revenue,google_ads_spend,google_ads_conversions,google_ads_conversion_value",
                               filters={"client_id": f"eq.{client_id}", "metric_date": f"gte.{goal['period_start']}", "and": f"(metric_date.lte.{goal['period_end']})"}, limit=400)
        def total(key: str) -> Optional[float]:
            vals = [float(r[key]) for r in rows if r.get(key) is not None]
            return round(sum(vals), 2) if vals else None
        ctx["midia_no_periodo"] = {"meta": {"investimento": total("meta_spend"), "compras_atribuidas": total("meta_purchases"), "receita_atribuida": total("meta_attributed_revenue")},
                                   "google": {"investimento": total("google_ads_spend"), "conversoes": total("google_ads_conversions"), "valor_conversao": total("google_ads_conversion_value")},
                                   "aviso": "Receitas atribuídas por cada plataforma, com metodologias diferentes; não somar e não confundir com o faturamento da loja."}
    except Exception:  # noqa: BLE001
        pass
    try:
        plans = await sb_select("studio_projects", select="title,plan,status,updated_at", filters={"client_id": f"eq.{client_id}", "kind": "eq.planejamento"},
                                order="updated_at.desc", limit=1)
        if plans:
            p = plans[0].get("plan") or {}
            ctx["planejamento_atual"] = {"titulo": plans[0].get("title"), "estrategia": p.get("strategy"), "grande_ideia": p.get("big_idea"),
                                         "kpis": p.get("kpis")}
    except Exception:  # noqa: BLE001
        pass
    return ctx


async def recommend(client_id: str, goal: Dict[str, Any], constraints: Optional[str], *, user_id: str) -> Dict[str, Any]:
    from .studio_llm import llm_json
    diag = await diagnosis(client_id, goal)
    ctx = await _context(client_id, goal, diag)
    prompt = (f"DADOS (JSON):\n{json.dumps(ctx, ensure_ascii=False, default=str)}\n\n"
              f"RESTRIÇÕES DO PROFISSIONAL: {(constraints or 'nenhuma informada').strip()[:1000]}")
    data = await llm_json(brand="estrategia", client_id=client_id, instructions=INSTRUCTIONS, prompt=prompt, schema_name="goal_recommendations",
                          schema=_schema(), temperature=0.3, timeout=90, guidance=False)
    items = [{"titulo": str(i.get("titulo") or "")[:160], "tipo": i.get("tipo") or "recomendacao", "evidencia": str(i.get("evidencia") or "")[:600],
              "justificativa": str(i.get("justificativa") or "")[:600], "acao": str(i.get("acao") or "")[:400], "task_id": None}
             for i in data.get("itens") or [] if str(i.get("titulo") or "").strip()][:5]
    row = {"client_id": client_id, "goal_id": str(goal["id"]), "goal_snapshot": ctx["meta"], "constraints": (constraints or "").strip()[:1000] or None,
           "items": items, "created_by": user_id}
    saved = None
    try:
        saved = await sb_insert(TABLE, row)
    except Exception as exc:  # noqa: BLE001 — sem a migração 000151 a recomendação aparece, mas não vira tarefa
        print(f"[goal_ops] recommendation_not_saved client_id={client_id} error_type={type(exc).__name__}")
    return {"id": (saved or {}).get("id"), "saved": bool(saved), "leitura": str(data.get("leitura") or "")[:600], "items": items, "diagnosis": diag}


async def to_task(client_id: str, goal: Dict[str, Any], rec_id: str, index: int, *, assignee_user_ids: List[str], due_date: Optional[str],
                  user_id: str, client_view: bool, only_user: Optional[str]) -> Dict[str, Any]:
    """Item aprovado vira tarefa no Kanban (mesmo serviço), ligada à meta. Repetir devolve a mesma tarefa."""
    from .studio_calendar import StudioError
    from .studio_tasks import create_task
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{rec_id}", "goal_id": f"eq.{goal['id']}"}, limit=1)
    if not rows or rows[0].get("client_id") != client_id:
        raise StudioError("RECOMMENDATION_NOT_FOUND", "Recomendação não encontrada para esta meta.")
    items = list(rows[0].get("items") or [])
    if not 0 <= index < len(items):
        raise StudioError("RECOMMENDATION_NOT_FOUND", "Item não encontrado.")
    item = items[index]
    if item.get("task_id"):
        return {"task_id": item["task_id"], "created": False}
    notes = (f"Meta: {goal.get('label')} ({goal.get('period_start')} a {goal.get('period_end')})\n"
             f"Recomendação: {item.get('titulo')}\nAção: {item.get('acao')}\nEvidência: {item.get('evidencia')}\nPor quê: {item.get('justificativa')}\n"
             f"[meta:{goal['id']}] [recomendação:{rec_id}#{index}]")
    data: Dict[str, Any] = {"title": str(item.get("titulo") or "Ação da meta")[:200], "notes": notes, "category": "Metas"}
    if assignee_user_ids:
        data["assignee_user_ids"] = assignee_user_ids
    if due_date:
        data["due_date"] = due_date
    task = await create_task(client_id, data, user_id=user_id, client_view=client_view, only_user=only_user)
    items[index] = {**item, "task_id": task.get("id")}
    await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{rec_id}"}, patch={"items": items}, returning="minimal")
    return {"task_id": task.get("id"), "created": True}


async def latest_recommendations(client_id: str, goal_id: str) -> List[Dict[str, Any]]:
    try:
        rows = await sb_select(TABLE, select="id,items,constraints,created_at,client_id", filters={"client_id": f"eq.{client_id}", "goal_id": f"eq.{goal_id}"},
                               order="created_at.desc", limit=5)
    except Exception:  # noqa: BLE001
        return []
    return [r for r in rows if r.get("client_id") == client_id]


# ---------------------------------------------------------------- alertas internos

def alerts(goals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Alertas para o Mugoverso (sem WhatsApp/e-mail): desempenho e falha de dado separados. Puro, para teste."""
    out = []
    for g in goals:
        status = g.get("status")
        kind = ("dado" if status == "INDISPONIVEL" else "atingida" if status == "META_ATINGIDA"
                else "desempenho" if status in ("ABAIXO_DO_RITMO", "ABAIXO_DA_META", "ACIMA_DO_TETO", "RISCO_DE_PASSAR") else None)
        if not kind:
            continue
        out.append({"goal_id": g.get("id"), "label": g.get("label"), "status": status, "kind": kind, "key": f"{g.get('id')}:{status}",
                    "text": (f"Dados indisponíveis: {g.get('reason') or 'a fonte não respondeu'}" if kind == "dado"
                             else "Meta atingida." if kind == "atingida" else g.get("pace_note") or "Fora do ritmo necessário.")})
    order = {"desempenho": 0, "dado": 1, "atingida": 2}
    return sorted(out, key=lambda a: order[a["kind"]])
