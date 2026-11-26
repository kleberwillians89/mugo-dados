"""Enviar o briefing da peça para alguém da equipe (ou o cliente/dono) como TAREFA dessa pessoa.

Cada função recebe só o que precisa do briefing (o designer não precisa da estratégia inteira; o gestor de tráfego
precisa do público e do CTA). A tarefa nasce com a pessoa como responsável: ela vê no quadro dela e manda para a
aprovação interna quando terminar. Fica registrado no histórico do post.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .studio_calendar import SAO_PAULO, StudioError

ROLES: Dict[str, str] = {
    "designer": "Designer", "trafego": "Gestor de tráfego", "estrategista": "Estrategista", "desenvolvedor": "Desenvolvedor",
    "social_media": "Social media", "redator": "Redator", "produtor": "Produtor (foto/vídeo)", "cliente": "Cliente", "dono": "Dono",
}
FORMAT_LABEL = {"reels": "Reels", "carrossel": "Carrossel", "imagem": "Imagem", "stories": "Stories", "video": "Vídeo"}

# (campo, rótulo) na ordem em que cada função lê. "b." = campo do briefing (signals.briefing).
FIELDS: Dict[str, List[Tuple[str, str]]] = {
    "designer": [("b.summary", "Resumo"), ("hook", "Texto da capa / gancho"), ("visual_idea", "Direção da arte"),
                 ("b.deliverables", "Entregáveis"), ("b.tech_requirements", "Requisitos técnicos"), ("script", "Roteiro / slides"), ("b.tone", "Tom")],
    "trafego": [("b.objective", "Objetivo"), ("b.target_audience", "Público"), ("b.key_message", "Mensagem central"),
                ("hook", "Gancho"), ("caption_draft", "Legenda"), ("products", "Produtos marcados"), ("rationale", "Por que este post")],
    "estrategista": [("b.summary", "Resumo"), ("b.objective", "Objetivo"), ("b.angle", "Ângulo"), ("b.target_audience", "Público"),
                     ("b.key_message", "Mensagem central"), ("pillar", "Pilar"), ("rationale", "Por que este post")],
    "desenvolvedor": [("b.objective", "Objetivo"), ("b.tech_requirements", "Requisitos técnicos"), ("b.deliverables", "Entregáveis"),
                      ("caption_draft", "Legenda (links e CTA)"), ("products", "Produtos marcados")],
    "social_media": [("hook", "Gancho"), ("caption_draft", "Legenda"), ("collaborators", "Colaboradores"), ("products", "Produtos marcados"),
                     ("b.key_message", "Mensagem central"), ("b.tone", "Tom")],
    "redator": [("b.key_message", "Mensagem central"), ("b.tone", "Tom"), ("b.target_audience", "Público"), ("hook", "Gancho"),
                ("caption_draft", "Legenda atual"), ("script", "Roteiro")],
    "produtor": [("b.summary", "Resumo"), ("script", "Roteiro"), ("visual_idea", "Direção da arte"), ("b.deliverables", "Entregáveis"),
                 ("b.tech_requirements", "Requisitos técnicos")],
    "cliente": [("b.summary", "Resumo"), ("b.objective", "Objetivo"), ("hook", "Gancho"), ("caption_draft", "Legenda")],
    "dono": [("b.summary", "Resumo"), ("b.objective", "Objetivo"), ("b.key_message", "Mensagem central"), ("b.target_audience", "Público"),
             ("hook", "Gancho"), ("caption_draft", "Legenda"), ("visual_idea", "Direção da arte"), ("rationale", "Por que este post")],
}


def _value(item: Dict[str, Any], key: str) -> str:
    if key.startswith("b."):
        raw = ((item.get("signals") or {}).get("briefing") or {}).get(key[2:])
    elif key == "products":
        raw = [t.get("name") or t.get("product_id") for t in item.get("product_tags") or [] if isinstance(t, dict)]
    elif key == "collaborators":
        raw = [f"@{c}" for c in item.get("collaborators") or []]
    else:
        raw = item.get(key)
    if isinstance(raw, list):
        return "\n".join(f"- {str(x).strip()}" for x in raw if str(x or "").strip())
    return str(raw or "").strip()


# Direcionamento Criativo da peça (escrito pela equipe no Calendário): vale para toda função e vem primeiro.
DIRECTION_FIELDS: Tuple[Tuple[str, str], ...] = (("concept", "Título / conceito"), ("texts", "Textos necessários"),
                                                  ("references", "Referências"), ("instructions", "Instruções para a peça"))


def direction_text(item: Dict[str, Any]) -> str:
    d = item.get("creative_direction") if isinstance(item.get("creative_direction"), dict) else {}
    lines = []
    for key, label in DIRECTION_FIELDS:
        value = str(d.get(key) or "").strip()
        if value:
            lines.append(f"{label}:\n{value}" if "\n" in value or len(value) > 80 else f"{label}: {value}")
    return ("DIRECIONAMENTO CRIATIVO\n" + "\n".join(lines))[:1800] if lines else ""


def reference_text(brief: Optional[Dict[str, Any]]) -> str:
    """Briefing da campanha como referência (não substitui o direcionamento da peça)."""
    b = (brief or {}).get("brief") if isinstance((brief or {}).get("brief"), dict) else (brief or {})
    if not b or not (b.get("title") or b.get("summary")):
        return ""
    parts = [f"BRIEFING DE REFERÊNCIA: {str(b.get('title') or '').strip()}".rstrip(": ")]
    for key, label in (("summary", "Resumo"), ("objective", "Objetivo"), ("key_message", "Mensagem"), ("audience", "Público"), ("deadline", "Prazo")):
        if str(b.get(key) or "").strip():
            parts.append(f"{label}: {str(b[key]).strip()}")
    for key, label in (("deliverables", "Entregáveis"), ("avoid", "Não fazer")):
        values = [str(x).strip() for x in b.get(key) or [] if str(x or "").strip()]
        if values:
            parts.append(f"{label}: " + " · ".join(values))
    return "\n".join(parts)[:1000]


def build_text(item: Dict[str, Any], role: str, note: Optional[str] = None, reference: Optional[Dict[str, Any]] = None) -> str:
    """Briefing para a função, em texto curto (vai na observação da tarefa).
    Ordem: post → pedido → direcionamento criativo → o que a função precisa → briefing de referência."""
    when = ""
    try:
        at = datetime.fromisoformat(str(item.get("scheduled_at")).replace("Z", "+00:00")).astimezone(SAO_PAULO)
        when = at.strftime("%d/%m às %H:%M")
    except (TypeError, ValueError):
        pass
    head = f"Post: {item.get('title') or ''} · {FORMAT_LABEL.get(item.get('format') or '', item.get('format') or '')}" + (f" · publica {when}" if when else "")
    parts = [head]
    if note and note.strip():
        parts.append(f"Pedido: {note.strip()[:600]}")
    direction = direction_text(item)
    if direction:
        parts.append(direction)
    ref = reference_text(reference)
    body: List[str] = []
    for key, label in FIELDS[role]:
        value = _value(item, key)
        if value:
            body.append(f"{label}:\n{value}" if "\n" in value or len(value) > 80 else f"{label}: {value}")
    # O briefing de referência sempre cabe: o que corta, se passar de 4000, é o fim dos campos da função.
    room = 4000 - len("\n\n".join(parts)) - (len(ref) + 2 if ref else 0) - 2
    text = "\n\n".join(body)
    if body and room > 0:
        parts.append(text[:room])
    if ref:
        parts.append(ref)
    return "\n\n".join(parts)[:4000]


async def reference_brief(client_id: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Briefing existente que acompanha a peça: o escolhido no Direcionamento Criativo ou, se a pauta veio da
    Matriz, o briefing vinculado à Matriz (só leitura). Sem briefing ou em falha: None (a tarefa sai igual)."""
    from .ig_supabase import sb_select
    direction = item.get("creative_direction") if isinstance(item.get("creative_direction"), dict) else {}
    try:
        if direction.get("brief_id"):
            rows = await sb_select("studio_briefs", select="id,brief", limit=1,
                                   filters={"client_id": f"eq.{client_id}", "id": f"eq.{direction['brief_id']}"})
            if rows:
                return rows[0]
        if item.get("matrix_opportunity_id"):
            ops = await sb_select("studio_matrix_opportunities", select="matrix_id", limit=1,
                                  filters={"client_id": f"eq.{client_id}", "id": f"eq.{item['matrix_opportunity_id']}"})
            if ops and ops[0].get("matrix_id"):
                matrices = await sb_select("studio_content_matrices", select="brief_snapshot", limit=1,
                                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{ops[0]['matrix_id']}"})
                if matrices and isinstance(matrices[0].get("brief_snapshot"), dict):
                    return matrices[0]["brief_snapshot"]
    except Exception as exc:  # noqa: BLE001 — referência é bônus; nunca impede o envio
        print(f"[studio][briefing_send] reference_unavailable client_id={client_id} {type(exc).__name__}")
    return None


def default_due(item: Dict[str, Any], *, today: Optional[date] = None) -> Optional[str]:
    """Dois dias antes da publicação (nunca antes de hoje)."""
    today = today or datetime.now(SAO_PAULO).date()
    try:
        day = datetime.fromisoformat(str(item.get("scheduled_at")).replace("Z", "+00:00")).astimezone(SAO_PAULO).date()
    except (TypeError, ValueError):
        return None
    return max(today, day - timedelta(days=2)).isoformat()


async def send_briefing(client_id: str, item_id: str, *, role: str, user_id: str, assignee_user_id: Optional[str],
                        assignee_name: Optional[str], due_date: Optional[str], note: Optional[str], actor_name: str) -> Dict[str, Any]:
    from .ig_supabase import sb_select
    from .studio_history import record
    from .studio_tasks import create_task
    if role not in ROLES:
        raise StudioError("ROLE_INVALID", "Escolha para quem vai o briefing.")
    rows = await sb_select("studio_calendar_items", select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    if not rows:
        raise StudioError("ITEM_NOT_FOUND")
    item = rows[0]
    reference = await reference_brief(client_id, item)
    who = (assignee_name or "").strip()[:80] or ROLES[role]
    task = await create_task(client_id, {
        "title": f"{ROLES[role]}: {str(item.get('title') or 'post')[:150]}",
        "notes": build_text(item, role, note, reference), "category": ROLES[role], "status": "pending", "priority": "medium",
        "due_date": due_date or default_due(item), "assignee_name": who, "assignee_user_id": assignee_user_id,
        "visible_to_client": role in ("cliente", "dono"), "needs_client_approval": False,
    }, user_id=user_id, client_view=False)
    await record(client_id, item_id, f"enviou o briefing para {who} ({ROLES[role]})", actor_name=actor_name, side="mugo")
    return task
