"""“A Mugô IA notou”: alertas do Início, calculados por regras fixas (sem IA decidindo nada).

Regras (todas por números do banco, conferíveis):
- custo_subindo: campanha Meta ativa com o custo por resultado subindo 3 dias seguidos e o último dia 20%+ acima
  da média dos 14 dias anteriores, com pelo menos R$ 50 gastos nesses 3 dias;
- aprovacao_parada: posts esperando o cliente há mais de 48 h num pedido de aprovação aberto;
- publicacao_falhou: post que falhou ao publicar nos últimos 7 dias (urgente: vai também por WhatsApp);
- data_com_rascunho: post dos próximos 3 dias ainda em rascunho ou ajuste, ou e-mail dos próximos 5 dias em rascunho;
- integracao_caida: conexão que pede reconexão ou está com erro;
- conta_sem_saldo: conta de anúncios com pagamento pendente, desativada ou no limite de gastos (urgente).

A frase é montada a partir desses números, sem texto livre de IA. O job ``mugo-notices`` roda de hora em hora,
guarda o que vale agora em ``mugo_notices`` e marca como resolvido o que parou de valer. Dispensar é por pessoa e
só volta se a situação piorar (o ``level`` sobe). A equipe Mugô vê todas as empresas; o cliente vê só os da empresa
dele que ele mesmo pode resolver (aprovações).
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select, sb_update, sb_upsert

NOTICES = "mugo_notices"
DISMISSALS = "mugo_notice_dismissals"
TEAM_ROLES = {"agency_admin", "platform_admin", "account_manager"}
MAX_SHOWN = 3
URGENCY = {"publicacao_falhou": 100, "conta_sem_saldo": 95, "custo_subindo": 80, "aprovacao_parada": 70,
           "integracao_caida": 60, "data_com_rascunho": 50}
ICON = {"publicacao_falhou": "🚫", "conta_sem_saldo": "💳", "custo_subindo": "⚠️", "aprovacao_parada": "⏰",
        "integracao_caida": "🔌", "data_com_rascunho": "📅"}
URGENT = {"publicacao_falhou", "conta_sem_saldo"}
COST_MIN_SPEND_3D = 50.0
COST_JUMP = 1.2
APPROVAL_HOURS = 48
SAO_PAULO = timezone(timedelta(hours=-3))
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
PROVIDER = {"meta_ads": "Meta Ads", "instagram": "Instagram", "facebook": "Facebook", "ga4": "Google Analytics",
            "google_ads": "Google Ads", "shopify": "Shopify", "fbits": "FBITS", "tiktok": "TikTok", "pinterest": "Pinterest"}
ACCOUNT_STATUS = {2: "desativada", 3: "com pagamento pendente", 8: "com pagamento pendente", 9: "no período de carência do pagamento"}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def brl(value: float) -> str:
    return f"R$ {value:,.0f}".replace(",", ".") if value >= 100 else f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _when(iso: str) -> str:
    """'sexta às 19h' (horário de São Paulo)."""
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(SAO_PAULO)
    except ValueError:
        return ""
    hour = f"{moment.hour}h" + (f"{moment.minute:02d}" if moment.minute else "")
    return f"{WEEKDAYS[moment.weekday()]} ({moment.strftime('%d/%m')}) às {hour}"


def notice(kind: str, ref: str, *, level: int, message: str, actions: List[Dict[str, Any]], data: Dict[str, Any],
           client_visible: bool = False, extra_urgency: int = 0) -> Dict[str, Any]:
    return {"key": f"{kind}:{ref}", "kind": kind, "level": max(1, int(level)), "urgency": URGENCY[kind] + extra_urgency,
            "icon": ICON[kind], "message": message, "actions": actions, "data": data,
            "client_visible": client_visible, "urgent": kind in URGENT}


# ------------------------------------------------------------------ regras puras (testáveis)

def result_of(row: Dict[str, Any]) -> float:
    """Resultado do dia conforme o objetivo da campanha (compras/cadastros, cliques ou mil impressões)."""
    objective = str(row.get("objective") or "").upper()
    if any(k in objective for k in ("SALES", "LEADS", "CONVERSIONS", "PRODUCT_CATALOG")):
        return _num(row.get("conversions"))
    if any(k in objective for k in ("TRAFFIC", "LINK_CLICKS", "ENGAGEMENT", "MESSAGES")):
        return _num(row.get("clicks"))
    return _num(row.get("impressions")) / 1000


def cost_rising(rows: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """Campanhas ativas com custo por resultado subindo 3 dias seguidos e 20%+ acima da média anterior."""
    by_campaign: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    meta: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        cid = str(row.get("campaign_id") or "")
        day = str(row.get("stat_date") or "")[:10]
        if not cid or not day:
            continue
        cur = by_campaign[cid].setdefault(day, {"spend": 0.0, "result": 0.0})
        cur["spend"] += _num(row.get("spend"))
        cur["result"] += result_of(row)
        if day >= meta.get(cid, {}).get("day", ""):
            meta[cid] = {"day": day, "name": row.get("campaign_name") or "Campanha", "status": str(row.get("campaign_status") or "").upper()}
    last3 = [(today - timedelta(days=n)).isoformat() for n in (3, 2, 1)]  # dias completos
    before = [(today - timedelta(days=n)).isoformat() for n in range(4, 18)]
    monday = (today - timedelta(days=today.weekday())).isoformat()
    out = []
    for cid, days in by_campaign.items():
        if meta[cid]["status"] not in ("ACTIVE", ""):
            continue
        window = [days.get(d) for d in last3]
        if any(w is None or w["result"] <= 0 or w["spend"] <= 0 for w in window):
            continue
        costs = [w["spend"] / w["result"] for w in window]
        spend3 = sum(w["spend"] for w in window)
        prior = [days[d] for d in before if d in days]
        prior_spend, prior_result = sum(p["spend"] for p in prior), sum(p["result"] for p in prior)
        if spend3 < COST_MIN_SPEND_3D or not prior_result or not (costs[0] < costs[1] < costs[2]):
            continue
        average = prior_spend / prior_result
        if costs[2] < average * COST_JUMP:
            continue
        week_spend = sum(v["spend"] for d, v in days.items() if d >= monday)
        out.append({"campaign_id": cid, "name": meta[cid]["name"], "from": costs[0], "to": costs[2], "average": average,
                    "jump": costs[2] / average - 1, "week_spend": week_spend})
    return out


def approval_waiting(requests: List[Dict[str, Any]], items: List[Dict[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    """Posts de pedidos abertos há mais de 48 h que ainda esperam o cliente."""
    old = [r for r in requests if _dt(r.get("created_at")) and _dt(r["created_at"]) <= now - timedelta(hours=APPROVAL_HOURS)
           and (_dt(r.get("expires_at")) or now) >= now]
    wanted = {str(i) for r in old for i in r.get("item_ids") or []}
    waiting = sorted([i for i in items if str(i.get("id")) in wanted and i.get("status") == "em_revisao"],
                     key=lambda i: str(i.get("scheduled_at") or ""))
    if not waiting:
        return None
    hours = int((now - min(_dt(r["created_at"]) for r in old)).total_seconds() // 3600)
    request = max(old, key=lambda r: str(r.get("created_at")))
    return {"count": len(waiting), "hours": hours, "first_at": waiting[0].get("scheduled_at"),
            "request_id": str(request.get("id")), "contact_id": request.get("contact_id")}


def _dt(value: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def build(client_id: str, *, now: datetime, stats: List[Dict[str, Any]], requests: List[Dict[str, Any]],
          review_items: List[Dict[str, Any]], failed: List[Dict[str, Any]], soon_posts: List[Dict[str, Any]],
          soon_emails: List[Dict[str, Any]], connections: List[Dict[str, Any]],
          account: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Todas as regras de uma empresa, a partir do que já foi lido. Sem rede e sem IA."""
    today = now.astimezone(SAO_PAULO).date()
    out: List[Dict[str, Any]] = []
    for c in cost_rising(stats, today):
        level = 1 + int(c["jump"] // 0.25)
        out.append(notice("custo_subindo", c["campaign_id"], level=level, data=c,
            message=(f"Campanha \"{c['name']}\" está com o custo por resultado subindo há 3 dias "
                     f"({brl(c['from'])} → {brl(c['to'])}). Gastou {brl(c['week_spend'])} desde segunda."),
            actions=[{"label": "Ver campanha", "route": "media"}]))
    waiting = approval_waiting(requests, review_items, now)
    if waiting:
        when = _when(waiting.get("first_at") or "")
        first = f" O primeiro sai {when}." if when else ""
        plural = "posts esperam" if waiting["count"] > 1 else "post espera"
        out.append(notice("aprovacao_parada", "cliente", level=waiting["count"] + waiting["hours"] // 48, data=waiting,
            client_visible=True,
            message=f"{waiting['count']} {plural} aprovação do cliente há mais de {max(48, waiting['hours'] // 24 * 24)}h.{first}",
            actions=[{"label": "Ir para Aprovação Final", "route": "final_approval"},
                     {"label": "Cobrar o cliente no WhatsApp", "kind": "remind", "team_only": True,
                      "request_id": waiting["request_id"], "contact_id": waiting.get("contact_id")}]))
    for item in failed:
        out.append(notice("publicacao_falhou", str(item.get("id")), level=1, data={"title": item.get("title"),
                          "scheduled_at": item.get("scheduled_at")},
            message=f"O post \"{item.get('title') or 'sem título'}\" falhou ao publicar" + (f" ({_when(item.get('scheduled_at'))})." if _when(item.get("scheduled_at") or "") else ".")
                    + (f" Motivo: {str(item['publish_error'])[:140]}" if item.get("publish_error") else ""),
            actions=[{"label": "Abrir no Calendário", "route": "calendar"}]))
    if soon_posts:
        first = soon_posts[0]
        out.append(notice("data_com_rascunho", "posts", level=len(soon_posts), data={"count": len(soon_posts)},
            message=(f"{len(soon_posts)} post{'s' if len(soon_posts) > 1 else ''} dos próximos 3 dias ainda "
                     f"{'estão' if len(soon_posts) > 1 else 'está'} em rascunho ou ajuste."
                     + (f" O primeiro é {_when(first.get('scheduled_at') or '')}." if _when(first.get("scheduled_at") or "") else "")),
            actions=[{"label": "Abrir no Calendário", "route": "calendar"}]))
    for email in soon_emails:
        days = max(0, ((_dt(email.get("scheduled_at")) or now).astimezone(SAO_PAULO).date() - today).days)
        out.append(notice("data_com_rascunho", f"email:{email.get('id')}", level=6 - min(days, 5), data={"days": days},
            message=f"O e-mail \"{email.get('name') or 'sem nome'}\" sai em {days} dia{'s' if days != 1 else ''} e ainda está em rascunho.",
            actions=[{"label": "Abrir e-mail", "route": "email_marketing"}]))
    for conn in connections:
        name = PROVIDER.get(str(conn.get("provider") or ""), str(conn.get("provider") or "Integração"))
        out.append(notice("integracao_caida", str(conn.get("provider")), level=1, data={"status": conn.get("status")},
            message=f"A integração com {name} caiu ({conn.get('label') or 'precisa reconectar'}). Os números dela param de atualizar.",
            actions=[{"label": "Reconectar", "route": "integrations"}]))
    if account:
        status = int(_num(account.get("account_status")))
        cap, spent = _num(account.get("spend_cap")), _num(account.get("amount_spent"))
        if status in ACCOUNT_STATUS:
            out.append(notice("conta_sem_saldo", "status", level=2, data={"account_status": status},
                message=f"A conta de anúncios está {ACCOUNT_STATUS[status]}. As campanhas podem parar de rodar.",
                actions=[{"label": "Ver na Mídia On", "route": "media"}]))
        elif cap > 0 and spent >= cap * 0.95:
            out.append(notice("conta_sem_saldo", "limite", level=1, data={"used": spent / cap},
                message=f"A conta de anúncios usou {round(spent / cap * 100)}% do limite de gastos. Ao chegar a 100%, tudo para.",
                actions=[{"label": "Ver na Mídia On", "route": "media"}]))
    return out


# ------------------------------------------------------------------ leitura do banco e da Meta

async def _safe(coro, default):
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — uma fonte fora do ar não derruba as outras
        print(f"[mugo_notices] source_failed {type(exc).__name__}")
        return default


async def _account(client_id: str) -> Optional[Dict[str, Any]]:
    from . import meta_ad_publisher as pub
    account = await pub._ad_account(client_id)
    return await pub._graph("GET", f"/{account['act']}", token=account["token"],
                            params={"fields": "account_status,spend_cap,amount_spent"})


async def compute(client_id: str, *, now: Optional[datetime] = None, with_account: bool = True) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(SAO_PAULO).date()
    cid = {"client_id": f"eq.{client_id}"}
    iso = lambda d: d.isoformat()  # noqa: E731
    stats_q = sb_select("campaign_daily_stats", limit=3000,
                        select="stat_date,campaign_id,campaign_name,campaign_status,objective,spend,clicks,impressions,conversions",
                        filters={**cid, "stat_date": f"gte.{iso(today - timedelta(days=18))}"})
    requests_q = sb_select("studio_approval_requests", select="id,item_ids,created_at,expires_at,contact_id",
                           filters={**cid, "status": "eq.aberto"}, limit=50)
    review_q = sb_select("studio_calendar_items", select="id,scheduled_at,status",
                         filters={**cid, "status": "eq.em_revisao", "deleted_at": "is.null"}, limit=300)
    failed_q = sb_select("studio_calendar_items", select="id,title,scheduled_at,publish_error",
                         filters={**cid, "publish_status": "eq.falhou", "deleted_at": "is.null",
                                  "scheduled_at": f"gte.{(now - timedelta(days=7)).isoformat()}"}, limit=20)
    soon_q = sb_select("studio_calendar_items", select="id,scheduled_at,status", order="scheduled_at.asc", limit=50,
                       filters={**cid, "status": "in.(rascunho,rejeitado)", "deleted_at": "is.null",
                                "and": f"(scheduled_at.gte.{now.isoformat()},scheduled_at.lte.{(now + timedelta(days=3)).isoformat()})"})
    emails_q = sb_select("email_campaigns", select="id,name,scheduled_at", order="scheduled_at.asc", limit=10,
                         filters={**cid, "status": "eq.rascunho",
                                  "and": f"(scheduled_at.gte.{now.isoformat()},scheduled_at.lte.{(now + timedelta(days=5)).isoformat()})"})
    meta_q = sb_select("meta_connections", select="platform,connection_type,status",
                       filters={**cid, "status": "in.(needs_reauth,error,disconnected)"}, limit=10)
    other_q = sb_select("integration_connections", select="provider,status",
                        filters={**cid, "status": "in.(token_expired,reauth_required,sync_error,disconnected)"}, limit=20)
    stats, requests, review, failed, soon, emails, meta_conns, others = await asyncio.gather(
        _safe(stats_q, []), _safe(requests_q, []), _safe(review_q, []), _safe(failed_q, []), _safe(soon_q, []),
        _safe(emails_q, []), _safe(meta_q, []), _safe(other_q, []))
    labels = {"needs_reauth": "precisa reconectar", "token_expired": "acesso expirado", "reauth_required": "precisa reconectar",
              "error": "com erro", "sync_error": "erro ao sincronizar", "disconnected": "desconectada"}
    connections: Dict[str, Dict[str, Any]] = {}
    for row in meta_conns:
        provider = "meta_ads" if row.get("connection_type") == "paid" else str(row.get("platform") or "instagram")
        connections[provider] = {"provider": provider, "status": row.get("status"), "label": labels.get(str(row.get("status")))}
    for row in others:
        provider = str(row.get("provider") or "")
        connections.setdefault(provider, {"provider": provider, "status": row.get("status"), "label": labels.get(str(row.get("status")))})
    account = await _safe(_account(client_id), None) if with_account else None
    return build(client_id, now=now, stats=stats, requests=requests, review_items=review, failed=failed, soon_posts=soon,
                 soon_emails=emails, connections=list(connections.values()), account=account)


# ------------------------------------------------------------------ job: grava, resolve e avisa urgentes

async def scan_client(client_id: str, *, now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or datetime.now(timezone.utc)
    current = await compute(client_id, now=now)
    stamp = now.isoformat()
    existing = await sb_select(NOTICES, select="key,level,whatsapp_level",
                               filters={"client_id": f"eq.{client_id}", "resolved_at": "is.null"}, limit=200)
    previous = {str(r["key"]): r for r in existing}
    if current:
        await sb_upsert(NOTICES, [{"client_id": client_id, "key": n["key"], "kind": n["kind"], "level": n["level"],
                                   "urgency": n["urgency"], "message": n["message"], "actions": n["actions"],
                                   "data": json.loads(json.dumps(n["data"], default=str)), "client_visible": n["client_visible"],
                                   "urgent": n["urgent"], "last_seen_at": stamp, "resolved_at": None} for n in current],
                        on_conflict="client_id,key")
    gone = [k for k in previous if k not in {n["key"] for n in current}]
    for key in gone:
        await sb_update(NOTICES, filters={"client_id": f"eq.{client_id}", "key": f"eq.{key}"},
                        patch={"resolved_at": stamp, "whatsapp_level": 0}, returning="minimal")
    sent = 0
    for n in current:
        if n["urgent"] and n["level"] > int(_num((previous.get(n["key"]) or {}).get("whatsapp_level"))):
            if await _send_urgent(client_id, n):
                sent += 1
            await sb_update(NOTICES, filters={"client_id": f"eq.{client_id}", "key": f"eq.{n['key']}"},
                            patch={"whatsapp_level": n["level"], "whatsapp_sent_at": stamp}, returning="minimal")
    return {"notices": len(current), "resolved": len(gone), "whatsapp": sent}


async def _send_urgent(client_id: str, n: Dict[str, Any]) -> int:
    """Urgente vai por WhatsApp para quem cuida da conta: equipe Mugô da empresa que ativou o aviso por WhatsApp."""
    from .clients import list_clients_for_user
    from .task_assignment_notifications import PREFERENCES, _whatsapp_dispatch
    prefs = await sb_select(PREFERENCES, select="user_id", filters={"client_id": f"eq.{client_id}", "opted_in": "eq.true"}, limit=20)
    names = await sb_select("clients", select="name,trade_name", filters={"id": f"eq.{client_id}"}, limit=1)
    brand = (names[0].get("trade_name") or names[0].get("name")) if names else "empresa"
    body = f"Mugô IA notou em {brand}: {n['message']}"
    sent = 0
    for pref in prefs:
        uid = str(pref.get("user_id") or "")
        listed = await _safe(list_clients_for_user(uid), {})
        role = next((c.get("role") for c in listed.get("clients") or [] if str(c.get("client_id")) == client_id), None)
        if role not in TEAM_ROLES:
            continue
        status, _ = await _whatsapp_dispatch(client_id, uid, body, f"notice-{n['key']}-{n['level']}")
        sent += status == "sent"
    return sent


async def run_all() -> Dict[str, Any]:
    rows = await sb_select("clients", select="id,status", limit=1000)
    from .clients import is_operational
    clients = [str(r["id"]) for r in rows if r.get("id") and is_operational(r)]
    total = {"clients": len(clients), "notices": 0, "resolved": 0, "whatsapp": 0, "errors": 0}
    for cid in clients:
        try:
            result = await scan_client(cid)
            for k in ("notices", "resolved", "whatsapp"):
                total[k] += result[k]
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[mugo_notices] scan_failed {type(exc).__name__}")
    return total


# ------------------------------------------------------------------ leitura para a tela

def _view(row: Dict[str, Any], client_name: str, *, team: bool) -> Dict[str, Any]:
    actions = [a for a in (row.get("actions") or []) if team or not a.get("team_only")]
    return {"id": f"{row['client_id']}|{row['key']}", "client_id": row["client_id"], "client_name": client_name,
            "kind": row["kind"], "icon": ICON.get(str(row["kind"]), "•"), "message": row["message"], "level": row["level"],
            "urgency": row["urgency"], "critical": row["kind"] in URGENT, "actions": actions, "since": row.get("first_seen_at")}


async def for_user(user_id: str, *, client_id: Optional[str] = None, limit: int = MAX_SHOWN) -> Dict[str, Any]:
    """Alertas que esta pessoa vê, os mais urgentes primeiro, tirando os que ela dispensou (e não pioraram)."""
    from .clients import list_clients_for_user
    listed = (await list_clients_for_user(user_id)).get("clients") or []
    scope = {str(c["client_id"]): c for c in listed if c.get("client_id") and (not client_id or str(c["client_id"]) == client_id)}
    if not scope:
        return {"notices": [], "total": 0}
    ids = ",".join(json.dumps(c) for c in scope)
    rows = await sb_select(NOTICES, select="client_id,key,kind,level,urgency,message,actions,client_visible,first_seen_at",
                           filters={"client_id": f"in.({ids})", "resolved_at": "is.null"},
                           order="urgency.desc,first_seen_at.asc", limit=300)
    dismissed = await sb_select(DISMISSALS, select="client_id,notice_key,level",
                                filters={"user_id": f"eq.{user_id}", "client_id": f"in.({ids})"}, limit=500)
    hidden = {(str(d["client_id"]), str(d["notice_key"])): int(_num(d.get("level"))) for d in dismissed}
    out = []
    for row in rows:
        info = scope.get(str(row["client_id"]))
        team = str(info.get("role") or "") in TEAM_ROLES
        if not team and not row.get("client_visible"):
            continue
        if hidden.get((str(row["client_id"]), str(row["key"])), -1) >= int(_num(row.get("level"))):
            continue
        out.append(_view(row, str(info.get("name") or ""), team=team))
    out.sort(key=lambda notice: not notice["critical"])
    return {"notices": out[:limit], "total": len(out)}


async def dismiss(user_id: str, notice_id: str, *, completed: bool = False) -> bool:
    from .clients import list_clients_for_user
    client_id, _, key = notice_id.partition("|")
    listed = (await list_clients_for_user(user_id)).get("clients") or []
    if not key or client_id not in {str(c.get("client_id")) for c in listed}:
        return False
    rows = await sb_select(NOTICES, select="level", filters={"client_id": f"eq.{client_id}", "key": f"eq.{key}"}, limit=1)
    if not rows:
        return False
    await sb_upsert(DISMISSALS, [{"client_id": client_id, "notice_key": key, "user_id": user_id, "level": rows[0]["level"],
                                  "dismissed_at": datetime.now(timezone.utc).isoformat(),
                                  **({"disposition": "completed"} if completed else {})}],
                    on_conflict="client_id,notice_key,user_id")
    return True
