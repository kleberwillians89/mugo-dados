"""Job de sexta: aprendizado por campanha + resumo semanal no WhatsApp de cada cliente.

Para cada empresa com Meta Ads ou Google Ads conectado:

1. grava a semana de cada campanha em ``studio_campaign_learnings`` (memória do Mídia On);
2. monta o resumo da semana com os números do painel e o que foi aprendido;
3. envia pelo MugôZap para cada contato que recebe "tráfego pago".

Sem MugôZap configurado ou sem contato cadastrado, nada é enviado: a mensagem fica
registrada como "aguardando" e o aprendizado é gravado mesmo assim. Quando o WhatsApp
for ligado e os números forem cadastrados, a mensagem passa a sair sozinha.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from .client_lifecycle import operational_connections
from .ig_supabase import sb_get_active_meta_connections, sb_select
from .studio_calendar import StudioError

JOB_USER = "job:studio-weekly-digest"


async def paid_clients() -> List[str]:
    clients: Set[str] = set()
    try:
        meta = await operational_connections(await sb_get_active_meta_connections(platform="meta_ads", connection_type="paid"))
        clients |= {str(c.get("client_id")) for c in meta if c.get("client_id")}
    except Exception as exc:
        print(f"[weekly] meta_indisponivel erro={exc.__class__.__name__}")
    try:
        google = await operational_connections(await sb_select("integration_connections", order="updated_at.asc", limit=500,
                                                               filters={"provider": "eq.google_ads", "status": "eq.connected"}))
        clients |= {str(c.get("client_id")) for c in google if c.get("client_id")}
    except Exception as exc:
        print(f"[weekly] google_indisponivel erro={exc.__class__.__name__}")
    return sorted(clients)


async def run_client(client_id: str) -> Dict[str, Any]:
    from .campaign_learning import snapshot_week
    from .studio_messages import list_contacts, send_message

    result: Dict[str, Any] = {"client_id": client_id}
    try:
        summary = await snapshot_week(client_id)
        result.update(campaigns=len(summary["campaigns"]), notes=len(summary["notes"]), new=len(summary["new"]))
    except Exception as exc:
        result.update(ok=False, stage="aprendizado", error=exc.__class__.__name__)
        return result
    if not summary["channels"]:
        result.update(ok=True, message="sem_investimento_na_semana")
        return result
    contacts = [c for c in await list_contacts(client_id) if "trafego" in (c.get("receives") or [])]
    if not contacts:
        result.update(ok=True, message="sem_contato")  # aprendizado gravado; mensagem sai quando houver número
        return result
    sent = []
    for contact in contacts:
        try:
            out = await send_message(client_id, "semanal", user_id=JOB_USER, contact_id=str(contact["id"]), automatic=True)
            sent.append(out["status"])
        except StudioError as exc:
            sent.append(f"erro:{exc.code}")
    result.update(ok=all(not s.startswith("erro") for s in sent), message=sent)
    return result


async def run_weekly_digest(client_id: str | None = None) -> Dict[str, Any]:
    clients = [client_id] if client_id else await paid_clients()
    results = [await run_client(c) for c in clients]
    statuses = [s for r in results if isinstance(r.get("message"), list) for s in r["message"]]
    # Log público do Actions: só contagens, sem id de empresa (o detalhe fica em studio_messages).
    return {"ok": all(r.get("ok", True) for r in results), "clients": len(clients),
            "sent": statuses.count("enviado"), "waiting": statuses.count("aguardando"),
            "errors": sum(1 for s in statuses if s.startswith("erro")) + sum(1 for r in results if r.get("ok") is False and r.get("stage")),
            "learned_campaigns": sum(r.get("campaigns", 0) for r in results)}
