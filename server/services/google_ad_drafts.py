"""Google Ads campaign drafts in Mídia ON.

Phase one deliberately does not call Google Ads mutate APIs: drafts can be
created/edited/assigned tasks without a real ad account. Publication requires
a separate, reviewed implementation with OAuth, permissions and safeguards.
Drafts coexist in studio_ad_drafts with legacy Meta drafts, differentiated by
payload.platform. All DB reads and writes are scoped to client_id.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .studio_calendar import StudioError

TABLE = "studio_ad_drafts"
PLATFORM = "google_ads"
OBJECTIVES = ("vendas", "leads", "trafego")
MAX_DAILY_BUDGET = 1000000


def clean_payload(value: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise StudioError("AD_OBJECTIVE_INVALID")
    objective = str(value.get("objective") or "vendas").strip()
    if objective not in OBJECTIVES:
        raise StudioError("AD_OBJECTIVE_INVALID")
    name = str(value.get("name") or "").strip()[:120]
    if not name:
        raise StudioError("AD_NOT_READY", "Informe um nome para a campanha.")
    try:
        budget = float(value.get("daily_budget") or 0)
    except (TypeError, ValueError):
        budget = 0
    if not (6 <= budget <= MAX_DAILY_BUDGET):
        raise StudioError("AD_NOT_READY", "Informe uma verba diária entre R$ 6 e R$ 1.000.000.")
    try:
        start = date.fromisoformat(str(value.get("start_date") or ""))
        end = date.fromisoformat(str(value.get("end_date") or ""))
    except ValueError:
        raise StudioError("AD_NOT_READY", "Informe datas válidas.")
    if start > end:
        raise StudioError("AD_NOT_READY", "O início deve ser anterior ou igual ao fim.")
    if (end - start).days > 365:
        raise StudioError("AD_NOT_READY", "O período não pode ultrapassar 365 dias.")
    url = str(value.get("final_url") or "").strip()[:1000]
    if url and not url.startswith("https://"):
        raise StudioError("AD_NOT_READY", "Use um link HTTPS para o destino.")
    def clean_list(key: str, limit: int, length: int) -> List[str]:
        raw = value.get(key) or []
        if not isinstance(raw, list):
            raise StudioError("AD_NOT_READY", f"Lista inválida: {key}")
        return list(dict.fromkeys(str(v).strip()[:length] for v in raw if str(v).strip()))[:limit]
    networks = value.get("networks") or {}
    if not isinstance(networks, dict):
        raise StudioError("AD_NOT_READY", "Configuração de redes Google inválida.")
    if networks.get("google_search", True) is not True:
        raise StudioError("AD_NOT_READY", "Campanhas SEARCH exigem Pesquisa Google.")
    if any(k in networks and not isinstance(networks[k], bool) for k in ("search_partners","display_network")):
        raise StudioError("AD_NOT_READY", "Selecione redes válidas para a campanha.")
    return {
        "networks": {"google_search": True,
                     "search_partners": networks.get("search_partners", False),
                     "display_network": networks.get("display_network", False)},
        "platform": PLATFORM,
        "name": name,
        "objective": objective,
        "type": "SEARCH",
        "daily_budget": round(budget, 2),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "final_url": url,
        "locations": clean_list("locations", 20, 80),
        "keywords": clean_list("keywords", 50, 80),
        "headlines": clean_list("headlines", 15, 30),
        "descriptions": clean_list("descriptions", 4, 90),
        "contains_eu_political_advertising": (
            value.get("contains_eu_political_advertising")
            if isinstance(value.get("contains_eu_political_advertising"), bool) else None
        ),
        "notes": str(value.get("notes") or "")[:1000],
        "status": "rascunho",
    }


def view(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("payload") or {}
    ids = row.get("meta_ids") or {}
    campaign_id = str(ids.get("campaign_id") or "")
    customer_id = str(ids.get("customer_id") or "")
    return {
        "id": str(row["id"]), "status": str(row.get("status") or "rascunho"),
        "payload": payload,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "publication_available": True,
        "external_ids": ids,
        "error": row.get("error"),
        "published_at": row.get("published_at"),
        "ads_manager_url": (
            f"https://ads.google.com/aw/campaigns?campaignId={campaign_id}&__c={customer_id}"
            if campaign_id and customer_id else None
        ),
        "message": "A campanha é criada pausada e só veicula após ativação explícita.",
    }


async def list_drafts(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(TABLE, select="id,client_id,payload,created_at,updated_at",
                           filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=200)
    return [view(row) for row in rows if (row.get("payload") or {}).get("platform") == PLATFORM]


async def owned(client_id: str, draft_id: str) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}, limit=1)
    if not rows or (rows[0].get("payload") or {}).get("platform") != PLATFORM:
        raise StudioError("AD_DRAFT_NOT_FOUND")
    return rows[0]


async def create(client_id: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = clean_payload(data)
    created = await sb_insert(TABLE, {"client_id": client_id, "payload": payload,
                                      "status": "rascunho", "created_by": user_id})
    if not created:
        raise StudioError("AD_SAVE_FAILED")
    return view(created)


async def update(client_id: str, draft_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    row = await owned(client_id, draft_id)
    if row.get("status") in {"publicando", "publicada"}:
        raise StudioError("AD_DRAFT_LOCKED")
    payload = clean_payload(data)
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"},
                           patch={"payload": payload, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise StudioError("AD_DRAFT_NOT_FOUND")
    return view(rows[0])


async def delete(client_id: str, draft_id: str) -> None:
    row = await owned(client_id, draft_id)
    if row.get("status") in {"publicando", "publicada"}:
        raise StudioError("AD_DRAFT_LOCKED")
    await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}, returning="minimal")
