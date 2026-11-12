"""Novas fontes: TikTok Ads, TikTok orgânico, Pinterest e LinkedIn (anúncios e orgânico) e Microsoft Clarity.

Cada empresa liga a própria conta (OAuth para TikTok e Pinterest; token do projeto para o Clarity). O token fica
cifrado em integration_connections, como Meta e Google. As métricas diárias vão para channel_daily_metrics,
sempre com o client_id da empresa: nada de uma marca aparece na outra.

Reconectar não apaga histórico: a conexão é atualizada no lugar e as métricas já gravadas ficam.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import channel_providers as api
from .crypto import decrypt_secret
from .generic_connections import upsert_connection
from .ig_supabase import sb_select, sb_update, sb_upsert
from .integration_errors import IntegrationError

TABLE = "channel_daily_metrics"
CONFLICT = "client_id,provider,level,account_id,entity_id,metric_date"
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "tiktok_ads": {"label": "TikTok Ads", "auth": "oauth", "every_hours": 3, "first_days": 30, "days": 7},
    "tiktok": {"label": "TikTok orgânico", "auth": "oauth", "every_hours": 6, "first_days": 1, "days": 1},
    "pinterest": {"label": "Pinterest (anúncios e orgânico)", "auth": "oauth", "every_hours": 6, "first_days": 90, "days": 7},
    "linkedin": {"label": "LinkedIn (anúncios e página)", "auth": "oauth", "every_hours": 6, "first_days": 90, "days": 7},
    "clarity": {"label": "Microsoft Clarity", "auth": "token", "every_hours": 20, "first_days": 1, "days": 1},
}
# Pinterest grava em dois "providers" de métrica: orgânico e anúncios.
METRIC_PROVIDERS = {"tiktok_ads": ["tiktok_ads"], "tiktok": ["tiktok"], "pinterest": ["pinterest", "pinterest_ads"],
                    "linkedin": ["linkedin", "linkedin_ads"], "clarity": ["clarity"]}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check(provider: str) -> Dict[str, Any]:
    if provider not in PROVIDERS:
        raise IntegrationError("Canal desconhecido.", status_code=404, code="CHANNEL_UNKNOWN", provider=provider)
    return PROVIDERS[provider]


def redirect_uri(provider: str) -> str:
    from .email_resend import public_api_url
    base = public_api_url()
    if not base:
        raise IntegrationError("Configure API_PUBLIC_URL no servidor para o retorno do login.", status_code=503,
                               code="CHANNEL_REDIRECT_UNCONFIGURED", provider=provider)
    return f"{base}/api/channels/{provider}/callback"


def _expires_at(seconds: Any) -> Optional[str]:
    try:
        return (_now() + timedelta(seconds=int(seconds))).isoformat()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- ligar
async def start(provider: str, *, client_id: str, user_id: str) -> str:
    meta = _check(provider)
    if meta["auth"] != "oauth":
        raise IntegrationError("Este canal liga com token, não com login.", status_code=400, code="CHANNEL_NO_OAUTH", provider=provider)
    if not api.configured(provider):
        raise IntegrationError(f"{meta['label']} ainda não tem o app configurado no servidor.", status_code=503,
                               code="CHANNEL_APP_UNCONFIGURED", provider=provider)
    from .oauth_state import create_oauth_state
    uri = redirect_uri(provider)
    state = await create_oauth_state(provider=provider, user_id=user_id, client_id=client_id, redirect_uri=uri)
    return api.authorize_url(provider, redirect_uri=uri, state=state)


async def _save(provider: str, *, client_id: str, user_id: str, token: Dict[str, Any], account_id: str, account_name: str,
                metadata: Dict[str, Any]) -> Dict[str, Any]:
    payload = {"access_token": token.get("access_token"), "refresh_token": token.get("refresh_token"),
               "expires_at": _expires_at(token.get("expires_in")), "open_id": token.get("open_id")}
    return await upsert_connection(
        client_id=client_id, provider=provider, external_key=f"{provider}:{account_id or 'conta'}", token_payload=json.dumps(payload),
        user_id=user_id, status="connected", account_id=account_id or None, account_name=account_name,
        token_expires_at=payload["expires_at"], scopes=[s for s in str(token.get("scope") or "").replace(" ", ",").split(",") if s],
        metadata=metadata)


async def finish_oauth(provider: str, *, code: str, state: str) -> Dict[str, Any]:
    _check(provider)
    from .oauth_state import consume_oauth_state
    from .tenant import require_user_client_access
    session = await consume_oauth_state(state, provider=provider)
    uri = redirect_uri(provider)
    if str(session.get("redirect_uri") or "") != uri:
        raise RuntimeError("O retorno do login não corresponde ao endereço configurado.")
    client_id, user_id = str(session.get("client_id") or ""), str(session.get("user_id") or "")
    await require_user_client_access(user_id, client_id)
    token = await api.exchange_code(provider, code=code, redirect_uri=uri)
    account_id, name, metadata = await api.account_info(provider, token)
    saved = await _save(provider, client_id=client_id, user_id=user_id, token=token, account_id=account_id, account_name=name, metadata=metadata)
    return {"client_id": client_id, "connection": saved}


async def connect_clarity(client_id: str, *, user_id: str, token: str, project_name: Optional[str]) -> Dict[str, Any]:
    value = str(token or "").strip()
    if len(value) < 20:
        raise IntegrationError("Cole o token de exportação do projeto do Clarity.", status_code=400, code="CHANNEL_TOKEN_INVALID", provider="clarity")
    rows = await api.collect_clarity({"access_token": value}, {}, 1)  # valida o token e já traz o primeiro dia
    saved = await _save("clarity", client_id=client_id, user_id=user_id, token={"access_token": value}, account_id="projeto",
                        account_name=(project_name or "Projeto do Clarity")[:120], metadata={})
    await _store(client_id, "clarity", rows)
    await _mark(client_id, "clarity", saved["id"], ok=True, rows=len(rows), metadata={})
    return {**saved, "rows": len(rows)}


# ---------------------------------------------------------------- sincronizar
async def _connection(client_id: str, provider: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select("integration_connections", filters={"client_id": f"eq.{client_id}", "provider": f"eq.{provider}",
                                                              "status": "neq.disconnected"}, order="updated_at.desc", limit=1)
    return rows[0] if rows else None


def _token(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = str(row.get("encrypted_token") or "")
    try:
        return json.loads(decrypt_secret(raw)) if raw else {}
    except (ValueError, TypeError):
        return {}


async def _store(client_id: str, provider: str, rows: List[Dict[str, Any]]) -> None:
    clean = []
    for r in rows:
        if not r.get("metric_date"):
            continue
        clean.append({**r, "client_id": client_id, "provider": r.get("provider") or provider, "collected_at": _now().isoformat()})
    for i in range(0, len(clean), 500):
        await sb_upsert(TABLE, clean[i:i + 500], on_conflict=CONFLICT)


async def _mark(client_id: str, provider: str, connection_id: str, *, ok: bool, rows: int = 0, error: Optional[str] = None,
                code: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    patch: Dict[str, Any] = {"updated_at": _now().isoformat()}
    meta = dict(metadata or {})
    if ok:
        patch.update({"status": "connected", "last_sync_at": _now().isoformat(), "last_error": None})
        meta.update({"last_success_at": _now().isoformat(), "last_rows": rows, "last_sync_error_code": None})
    else:
        patch.update({"status": "reauth_required" if code == "CHANNEL_REAUTH_REQUIRED" else "sync_error", "last_error": (error or "")[:300]})
        meta.update({"last_sync_error_code": code})
    patch["metadata"] = meta
    await sb_update("integration_connections", filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"}, patch=patch, returning="minimal")


async def sync(client_id: str, provider: str, *, force: bool = False) -> Dict[str, Any]:
    meta = _check(provider)
    row = await _connection(client_id, provider)
    if not row:
        return {"status": "not_connected"}
    metadata = dict(row.get("metadata") or {})
    last = metadata.get("last_success_at")
    if not force and last:
        try:
            if _now() - datetime.fromisoformat(str(last).replace("Z", "+00:00")) < timedelta(hours=meta["every_hours"]):
                return {"status": "recent"}
        except ValueError:
            pass
    token = _token(row)
    try:
        expires = token.get("expires_at")
        if expires and datetime.fromisoformat(str(expires)) - _now() < timedelta(hours=2):
            fresh = await api.refresh_token(provider, token)
            if fresh and fresh.get("access_token"):
                token = {**token, **fresh, "expires_at": _expires_at(fresh.get("expires_in")) or expires}
                await _save(provider, client_id=client_id, user_id=str(row.get("connected_by") or ""), token=token,
                            account_id=str(row.get("account_id") or ""), account_name=str(row.get("account_name") or ""), metadata=metadata)
        days = meta["days"] if last else meta["first_days"]
        rows = await api.COLLECTORS[provider](token, metadata, days)
        await _store(client_id, provider, rows)
    except IntegrationError as exc:
        await _mark(client_id, provider, row["id"], ok=False, error=str(exc), code=exc.code, metadata=metadata)
        print(f"[channels][sync] client_id={client_id} provider={provider} status=error code={exc.code}")
        return {"status": "error", "code": exc.code, "message": str(exc)}
    await _mark(client_id, provider, row["id"], ok=True, rows=len(rows), metadata=metadata)
    print(f"[channels][sync] client_id={client_id} provider={provider} status=ok rows={len(rows)}")
    return {"status": "ok", "rows": len(rows)}


async def run_all() -> Dict[str, Any]:
    """Cron: todas as conexões ativas destes canais, respeitando o intervalo de cada um."""
    rows = await sb_select("integration_connections", select="client_id,provider",
                           filters={"provider": f"in.({','.join(PROVIDERS)})", "status": "neq.disconnected"}, limit=2000)
    report: Dict[str, int] = {}
    for r in rows:
        try:
            out = await sync(str(r["client_id"]), str(r["provider"]))
        except Exception as exc:  # noqa: BLE001 — uma empresa nunca derruba as outras
            print(f"[channels][run_all] client_id={r.get('client_id')} provider={r.get('provider')} error={type(exc).__name__}")
            out = {"status": "error"}
        report[out["status"]] = report.get(out["status"], 0) + 1
    return {"connections": len(rows), **report}


async def disconnect(client_id: str, provider: str, *, user_id: str) -> Dict[str, Any]:
    _check(provider)
    row = await _connection(client_id, provider)
    if not row:
        return {"ok": True}
    from .generic_connections import disconnect_generic_connection
    await disconnect_generic_connection(client_id, str(row["id"]), user_id)
    return {"ok": True}  # histórico de métricas fica


# ---------------------------------------------------------------- ler
def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Totais por provider de métrica no período. Orgânico do TikTok usa o retrato mais recente."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = out.setdefault(r["provider"], {"spend": 0.0, "impressions": 0, "clicks": 0, "conversions": 0.0, "days": set(), "latest": None, "top": {}})
        p["days"].add(r["metric_date"])
        if r["provider"] in ("tiktok", "clarity") and r["level"] == "account":
            if not p["latest"] or r["metric_date"] > p["latest"]["metric_date"]:
                p["latest"] = {"metric_date": r["metric_date"], **(r.get("metrics") or {})}
            continue
        if r["provider"] == "linkedin" and r["level"] == "content":
            if not p["latest"] or r["metric_date"] >= p["latest"]["metric_date"]:
                p["latest"] = {"metric_date": r["metric_date"], **(r.get("metrics") or {})}
            continue
        if r["provider"] == "tiktok" and r["level"] == "content":
            cur = p["top"].get(r["entity_id"])
            if not cur or r["metric_date"] > cur["metric_date"]:
                p["top"][r["entity_id"]] = {"metric_date": r["metric_date"], "name": r.get("entity_name"), "value": r.get("impressions") or 0}
            continue
        if r["level"] == "page":
            cur = p["top"].setdefault(r["entity_id"], {"name": r.get("entity_name"), "value": 0, "metric_date": r["metric_date"]})
            cur["value"] += (r.get("metrics") or {}).get("totalSessionCount") or 0
            continue
        for k in ("spend", "conversions"):
            p[k] += float(r.get(k) or 0)
        for k in ("impressions", "clicks"):
            p[k] += int(r.get(k) or 0)
        if r["level"] == "campaign":
            cur = p["top"].setdefault(r["entity_id"], {"name": r.get("entity_name"), "value": 0.0, "metric_date": r["metric_date"]})
            cur["value"] += float(r.get("spend") or 0)
    for p in out.values():
        p["days"] = len(p["days"])
        p["spend"] = round(p["spend"], 2)
        p["top"] = sorted(p["top"].values(), key=lambda t: -(t["value"] or 0))[:5]
    return out


async def overview(client_id: str, *, start: str, end: str) -> Dict[str, Any]:
    conns = await sb_select("integration_connections", select="provider,status,account_name,last_sync_at,last_error,metadata",
                            filters={"client_id": f"eq.{client_id}", "provider": f"in.({','.join(PROVIDERS)})"}, order="updated_at.desc", limit=20)
    by_provider: Dict[str, Dict[str, Any]] = {}
    for c in conns:
        by_provider.setdefault(c["provider"], c)
    rows = await sb_select(TABLE, select="provider,level,entity_id,entity_name,metric_date,spend,impressions,clicks,conversions,metrics",
                           filters={"client_id": f"eq.{client_id}", "and": f"(metric_date.gte.{start},metric_date.lte.{end})"},
                           order="metric_date.asc", limit=20000)
    totals = summarize(rows)
    channels = []
    for key, meta in PROVIDERS.items():
        c = by_provider.get(key) or {}
        status = str(c.get("status") or "not_connected")
        channels.append({
            "provider": key, "label": meta["label"], "auth": meta["auth"], "app_configured": meta["auth"] == "token" or api.configured(key),
            "status": "not_connected" if status == "disconnected" else status, "account_name": c.get("account_name"),
            "last_sync_at": c.get("last_sync_at"), "last_error": c.get("last_error"),
            "metrics": {mp: totals.get(mp) for mp in METRIC_PROVIDERS[key] if totals.get(mp)},
        })
    return {"start": start, "end": end, "channels": channels}


def default_period(days: int = 7) -> tuple[str, str]:
    end = date.today()
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()
