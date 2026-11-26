"""Internal campaign review. Version snapshots and decisions are committed with the campaign CAS."""
from . import email_builder
from .email_marketing import (
    CAMPAIGNS, CAMPAIGN_FIELDS, EmailError, SAMPLE, _now, campaign_transition,
    get_campaign, get_settings, render_campaign, review_snapshot, sb_select,
)


def review_summary(campaign: dict) -> dict:
    state = campaign.get("internal_review") or {"status": "draft", "versions": []}
    return {
        "status": state["status"],
        "versions": [{key: value for key, value in entry.items() if key != "snapshot"}
                     for entry in state["versions"]],
    }


async def submit(client_id: str, campaign_id: str, user_id: str, expected: str, *, actor_name: str | None = None) -> dict:
    campaign = await get_campaign(client_id, campaign_id)
    if campaign["status"] != "rascunho" or campaign["updated_at"] != expected:
        raise EmailError("STALE_CAMPAIGN", "A campanha mudou. Reabra o editor e confira a última versão.", 409)
    state = campaign["internal_review"]
    if not campaign["subject"].strip():
        raise EmailError("NO_SUBJECT", "Escreva o assunto da campanha.")
    blocks = email_builder.normalize_design(campaign.get("design"))["blocks"]
    has_content = any(
        (b["type"] in ("texto", "titulo") and b.get("text"))
        or (b["type"] == "imagem" and str(b.get("url", "")).startswith("https://"))
        or (b["type"] == "botao" and b.get("label") and b.get("href"))
        for b in blocks
    )
    if campaign.get("custom_html"):
        html = campaign["custom_html"]
        has_content = bool(email_builder.to_text(html).strip() or "<img " in html.lower())
    if not has_content:
        raise EmailError("EMPTY_CONTENT", "Adicione conteúdo à campanha antes de solicitar aprovação.")
    settings = await get_settings(client_id)
    snapshot = review_snapshot(campaign, settings)
    if state["status"] == "pending" and state["versions"][-1]["snapshot"] == snapshot:
        raise EmailError("ALREADY_PENDING", "Esta versão já está em aprovação.", 409)
    entry = {"version": len(state["versions"]) + 1, "requested_by": user_id,
             "requested_at": _now().isoformat(), "requested_by_name": actor_name, "snapshot": snapshot}
    updated = await campaign_transition(client_id, campaign, {
        "internal_review": {"status": "pending", "versions": [*state["versions"], entry]},
    })
    return review_summary(updated)


async def queue(client_id: str) -> list[dict]:
    campaigns = await sb_select(CAMPAIGNS, select=CAMPAIGN_FIELDS, filters={
        "client_id": f"eq.{client_id}", "internal_review->>status": "eq.pending",
    }, order="updated_at.asc", limit=200)
    output = []
    for campaign in campaigns:
        state = review_summary(campaign)
        entry = campaign["internal_review"]["versions"][-1]
        snapshot = entry["snapshot"]
        subject, html, _ = render_campaign(snapshot["campaign"], snapshot["settings"], SAMPLE, client_id)
        output.append({"id": campaign["id"], "version": entry["version"], "name": snapshot["campaign"]["name"],
                       "preheader": snapshot["campaign"]["preheader"], "preview": {"subject": subject, "html": html},
                       "audience": snapshot["campaign"]["audience"], "sender": snapshot["settings"]["from_email"], **state})
    return output


async def decide(client_id: str, campaign_id: str, user_id: str, version: int, decision: str, comment: str, *, actor_name: str | None = None) -> dict:
    if decision not in ("approved", "changes_requested") or (decision == "changes_requested" and not comment):
        raise EmailError("INVALID_DECISION", "Informe o motivo ao solicitar ajustes.")
    campaign = await get_campaign(client_id, campaign_id)
    state = campaign["internal_review"]
    if state["status"] != "pending" or state["versions"][-1]["version"] != version:
        raise EmailError("STALE_REVIEW", "A versão já foi alterada ou revisada. Atualize a fila.", 409)
    entry = state["versions"][-1]
    if decision == "approved" and review_snapshot(campaign, await get_settings(client_id)) != entry["snapshot"]:
        raise EmailError("STALE_REVIEW", "O conteúdo ou remetente mudou. Solicite ajustes para receber uma nova versão.", 409)
    decided = {**entry, "decision": decision, "decided_by": user_id, "decided_by_name": actor_name,
               "decided_at": _now().isoformat(), "comment": comment}
    updated = await campaign_transition(client_id, campaign, {
        "internal_review": {"status": decision, "versions": [*state["versions"][:-1], decided]},
    })
    return review_summary(updated)
