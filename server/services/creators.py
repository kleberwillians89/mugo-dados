"""Creator Intelligence: busca, banco de criadores, comparação, shortlists e orçamento.

O banco de criadores (creators/creator_metrics) guarda só dados públicos e é
reaproveitado entre empresas. Shortlists são sempre filtradas por client_id.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import creators_providers as providers
from .business_context import load_business_context
from .ig_supabase import sb_get_one, sb_get_one_by, sb_insert, sb_select, sb_upsert
from .integration_errors import IntegrationError
from .meta_tokens import ensure_valid_meta_token, get_active_connection_for_client

CREATOR_FIELDS = (
    "network", "handle", "external_id", "display_name", "profile_url", "avatar_url", "biography",
    "followers", "media_count", "avg_likes", "avg_comments", "avg_views", "engagement_rate",
    "engagement_method", "sample_size", "missing_fields", "source", "collected_at",
)
MAX_COMPARE = 5
MAX_ENRICH = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def cache_hours() -> float:
    return _float_env("CREATORS_CACHE_HOURS", 24)


def apify_monthly_budget() -> float:
    return _float_env("CREATORS_APIFY_MONTHLY_BUDGET_USD", 5)


def apify_run_estimate() -> float:
    return _float_env("CREATORS_APIFY_ESTIMATED_RUN_USD", 0.25)


def youtube_daily_units() -> float:
    return _float_env("CREATORS_YOUTUBE_DAILY_UNITS", 9000)


def is_fresh(row: Optional[Dict[str, Any]]) -> bool:
    if not row or not row.get("collected_at"):
        return False
    collected = datetime.fromisoformat(str(row["collected_at"]).replace("Z", "+00:00"))
    return _now() - collected < timedelta(hours=cache_hours())


# ---------------------------------------------------------------- consumo


async def record_usage(client_id: Optional[str], provider: str, operation: str, *, units: float = 0, cost_usd: float = 0, ok: bool = True) -> None:
    try:
        await sb_insert("creator_api_usage", {
            "client_id": client_id, "provider": provider, "operation": operation,
            "units": units, "cost_usd": cost_usd, "ok": ok,
        }, returning="minimal")
    except Exception as exc:  # consumo é observabilidade: nunca derruba a consulta
        print(f"[creators][usage_record_failed] provider={provider} error={str(exc)[:200]}")


async def _usage_sum(provider: str, since: datetime, column: str, client_id: Optional[str] = None) -> float:
    filters = {"provider": f"eq.{provider}", "created_at": f"gte.{since.isoformat()}"}
    if client_id:
        filters["client_id"] = f"eq.{client_id}"
    rows = await sb_select("creator_api_usage", select=column, filters=filters, limit=10000)
    return round(sum(float(r.get(column) or 0) for r in rows), 4)


def _month_start() -> datetime:
    return _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start() -> datetime:
    return _now().replace(hour=0, minute=0, second=0, microsecond=0)


async def apify_budget_guard() -> float:
    """Bloqueia antes de gastar. Retorna o teto restante para a execução."""
    spent = await _usage_sum("apify", _month_start(), "cost_usd")
    remaining = round(apify_monthly_budget() - spent, 4)
    if remaining < apify_run_estimate():
        raise IntegrationError(
            f"Orçamento mensal da Apify atingido (US$ {spent:.2f} de US$ {apify_monthly_budget():.2f}). "
            "Novas pesquisas ficam bloqueadas até o próximo mês ou até o teto ser revisto.",
            status_code=402, code="CREATORS_BUDGET_EXCEEDED", provider="apify",
        )
    return remaining


async def youtube_quota_guard(units_needed: int) -> None:
    used = await _usage_sum("youtube", _day_start(), "units")
    if used + units_needed > youtube_daily_units():
        raise IntegrationError(
            "Cota diária do YouTube reservada para o Mugô atingida. Tente amanhã.",
            status_code=429, code="YOUTUBE_QUOTA", provider="youtube", retryable=True,
        )


async def usage_summary(client_id: str) -> Dict[str, Any]:
    apify_spent = await _usage_sum("apify", _month_start(), "cost_usd")
    return {
        "apify": {"month_spent_usd": apify_spent, "month_budget_usd": apify_monthly_budget(),
                  "blocked": apify_monthly_budget() - apify_spent < apify_run_estimate()},
        "youtube": {"today_units": await _usage_sum("youtube", _day_start(), "units"),
                    "daily_units_limit": youtube_daily_units()},
        "meta": {"month_calls_this_client": await _usage_sum("meta", _month_start(), "units", client_id)},
    }


# ---------------------------------------------------------------- persistência


async def get_by_handle(network: str, handle: str) -> Optional[Dict[str, Any]]:
    return await sb_get_one_by("creators", filters={"network": f"eq.{network}", "handle": f"eq.{handle}"})


async def save_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Grava perfil + snapshot. Um resultado parcial nunca apaga dado completo já salvo."""
    metrics = providers.compute_engagement(profile)
    row = {**{k: profile.get(k) for k in CREATOR_FIELDS}, **metrics, "collected_at": _now().isoformat()}
    existing = await get_by_handle(row["network"], row["handle"])
    if existing and row["followers"] is None and existing.get("followers") is not None:
        return existing
    await sb_upsert("creators", [row], on_conflict="network,handle")
    saved = await get_by_handle(row["network"], row["handle"]) or row
    if saved.get("id"):
        await sb_insert("creator_metrics", {
            "creator_id": saved["id"], "source": row["source"], "collected_at": row["collected_at"],
            **{k: metrics[k] for k in ("followers", "avg_likes", "avg_comments", "avg_views", "engagement_rate", "engagement_method", "sample_size")},
            "recent_posts": (profile.get("posts") or [])[:providers.SAMPLE_POSTS],
        }, returning="minimal")
    return saved


# ---------------------------------------------------------------- fontes


async def _meta_credentials(client_id: str) -> tuple[str, str]:
    connection = await get_active_connection_for_client(client_id)
    if not connection:
        raise IntegrationError(
            "Conecte o Instagram da empresa em Integrações para consultar criadores.",
            status_code=409, code="META_CONNECTION_REQUIRED", provider="meta",
        )
    ig_user_id = str(connection.get("ig_user_id") or "").strip()
    if not ig_user_id:
        client = await sb_get_one("clients", f"id=eq.{client_id}")
        ig_user_id = str((client or {}).get("ig_user_id") or "").strip()
    if not ig_user_id:
        raise IntegrationError(
            "A conexão Meta da empresa ainda não tem conta Instagram selecionada.",
            status_code=409, code="META_CONNECTION_REQUIRED", provider="meta",
        )
    token = await ensure_valid_meta_token(client_id, persisted_only=True)
    return ig_user_id, token


async def _meta_profile(client_id: str, handle: str) -> Dict[str, Any]:
    ig_user_id, token = await _meta_credentials(client_id)
    try:
        profile = await providers.meta_business_discovery(ig_user_id, token, handle)
    except IntegrationError:
        await record_usage(client_id, "meta", "business_discovery", units=1, ok=False)
        raise
    await record_usage(client_id, "meta", "business_discovery", units=1)
    return profile


async def _youtube_profile(client_id: str, handle: str) -> Dict[str, Any]:
    await youtube_quota_guard(3)
    profile, units = await providers.youtube_channel(handle)
    await record_usage(client_id, "youtube", "channel", units=units)
    return profile


async def _apify(client_id: str, kind: str, run_input: Dict[str, Any], max_items: int) -> List[Dict[str, Any]]:
    remaining = await apify_budget_guard()
    try:
        items, cost = await providers.apify_run(providers.apify_actor(kind), run_input, max_items=max_items, max_charge_usd=remaining)
    except IntegrationError as exc:
        # Execução que chegou a rodar consome crédito; recusa/configuração ausente, não.
        spent = exc.diagnostics.get("cost_usd")
        if spent is None:
            spent = apify_run_estimate() if exc.code == "APIFY_RUN_INCOMPLETE" else 0
        await record_usage(client_id, "apify", kind, cost_usd=float(spent), ok=False)
        raise
    # Sem custo informado, contabiliza a estimativa para o teto continuar valendo.
    await record_usage(client_id, "apify", kind, units=len(items), cost_usd=cost if cost is not None else apify_run_estimate())
    return items


async def _tiktok_profile(client_id: str, handle: str) -> Dict[str, Any]:
    items = await _apify(client_id, "tiktok", {"profiles": [handle], "resultsPerPage": providers.SAMPLE_POSTS}, providers.SAMPLE_POSTS)
    found = [p for p in providers.group_tiktok_items(items) if p["handle"] == handle]
    if not found:
        raise IntegrationError("Perfil do TikTok não encontrado.", status_code=404, code="CREATOR_NOT_FOUND", provider="apify")
    return found[0]


async def link_creators(client_id: str, creator_ids: List[str]) -> None:
    """Registra que a empresa consultou esses criadores (é o que o cliente enxerga)."""
    rows = [{"client_id": client_id, "creator_id": cid} for cid in dict.fromkeys(creator_ids) if cid]
    if not rows:
        return
    try:
        await sb_upsert("creator_client_links", rows, on_conflict="client_id,creator_id")
    except Exception as exc:  # sem a migração 000061 o vínculo falha, mas a consulta segue
        print(f"[creators][link_failed] client_id={client_id} error={str(exc)[:200]}")


async def linked_ids(client_id: str) -> set[str]:
    rows = await sb_select("creator_client_links", select="creator_id", filters={"client_id": f"eq.{client_id}"}, limit=5000)
    return {str(r["creator_id"]) for r in rows if r.get("creator_id")}


async def lookup(client_id: str, network: str, raw_handle: str, *, force: bool = False) -> Dict[str, Any]:
    handle = providers.normalize_handle(network, raw_handle)
    cached = await get_by_handle(network, handle)
    if not force and is_fresh(cached) and cached.get("followers") is not None:
        result = {**cached, "cached": True}
    else:
        fetcher = {"instagram": _meta_profile, "youtube": _youtube_profile, "tiktok": _tiktok_profile}[network]
        result = {**await save_profile(await fetcher(client_id, handle)), "cached": False}
    await link_creators(client_id, [result.get("id")])
    return result


async def search(client_id: str, network: str, query: str, limit: int) -> Dict[str, Any]:
    term = str(query or "").strip().lstrip("#")
    if not term:
        raise ValueError("Informe uma palavra-chave ou hashtag.")
    notes: List[str] = []
    if network == "youtube":
        await youtube_quota_guard(101)
        profiles, units = await providers.youtube_search(term, limit)
        await record_usage(client_id, "youtube", "search", units=units)
        notes.append("Engajamento do YouTube é calculado ao abrir/atualizar cada canal.")
    elif network == "tiktok":
        items = await _apify(client_id, "tiktok", {"hashtags": [term], "resultsPerPage": limit * 3}, limit * 3)
        profiles = providers.group_tiktok_items(items)[:limit]
    else:
        items = await _apify(client_id, "instagram_hashtag", {"hashtags": [term], "resultsLimit": limit * 3}, limit * 3)
        profiles = providers.group_instagram_hashtag_items(items)[:limit]
        # Seguidores vêm da Meta (grátis); contas pessoais ficam sem seguidores.
        enriched = 0
        for index, profile in enumerate(profiles[:MAX_ENRICH]):
            try:
                profiles[index] = await _meta_profile(client_id, profile["handle"])
                enriched += 1
            except IntegrationError as exc:
                if exc.code in {"META_CONNECTION_REQUIRED", "META_REAUTH_REQUIRED", "META_RATE_LIMITED"}:
                    notes.append(exc.public_message)
                    break
        if len(profiles) > enriched:
            notes.append("Perfis sem seguidores não são contas profissionais ou não foram enriquecidos pela Meta.")
    saved = [await save_profile(p) for p in profiles]
    await link_creators(client_id, [c.get("id") for c in saved])
    return {"network": network, "query": term, "creators": saved, "notes": notes}


# ---------------------------------------------------------------- leitura


# only_ids: None = agência (banco inteiro); conjunto = cliente (só os criadores da empresa).
Visible = Optional[set]


def _visible(creator_id: str, only_ids: Visible) -> bool:
    return only_ids is None or creator_id in only_ids


async def list_creators(*, network: Optional[str], q: Optional[str], min_followers: Optional[int], limit: int, offset: int, only_ids: Visible = None) -> List[Dict[str, Any]]:
    filters: Dict[str, str] = {}
    if only_ids is not None:
        if not only_ids:
            return []
        filters["id"] = f"in.({','.join(sorted(only_ids))})"
    if network:
        filters["network"] = f"eq.{network}"
    if min_followers:
        filters["followers"] = f"gte.{int(min_followers)}"
    if q:
        safe = "".join(ch for ch in q.lower() if ch.isalnum() or ch in "._ -")[:60]
        if safe:
            filters["or"] = f"(handle.ilike.*{safe}*,display_name.ilike.*{safe}*)"
    return await sb_select("creators", filters=filters, order="followers.desc.nullslast", limit=limit, offset=offset)


async def get_creator(creator_id: str, only_ids: Visible = None) -> Optional[Dict[str, Any]]:
    if not _visible(creator_id, only_ids):
        return None
    creator = await sb_get_one_by("creators", filters={"id": f"eq.{creator_id}"})
    if not creator:
        return None
    history = await sb_select("creator_metrics", filters={"creator_id": f"eq.{creator_id}"}, order="collected_at.desc", limit=10)
    return {**creator, "recent_posts": (history[0].get("recent_posts") if history else []) or [],
            "history": [{k: h.get(k) for k in ("collected_at", "source", "followers", "engagement_rate")} for h in history]}


async def refresh(client_id: str, creator_id: str, only_ids: Visible = None) -> Dict[str, Any]:
    creator = await sb_get_one_by("creators", filters={"id": f"eq.{creator_id}"}) if _visible(creator_id, only_ids) else None
    if not creator:
        raise IntegrationError("Criador não encontrado.", status_code=404, code="CREATOR_NOT_FOUND", provider="creators")
    return await lookup(client_id, creator["network"], creator["handle"], force=True)


async def compare(creator_ids: List[str], only_ids: Visible = None) -> List[Dict[str, Any]]:
    ids = [i for i in dict.fromkeys(creator_ids) if _visible(i, only_ids)]
    if not 2 <= len(ids) <= MAX_COMPARE:
        raise ValueError(f"Compare de 2 a {MAX_COMPARE} criadores.")
    rows = await sb_select("creators", filters={"id": f"in.({','.join(ids)})"}, limit=MAX_COMPARE)
    by_id = {r["id"]: r for r in rows}
    return [{k: by_id[i].get(k) for k in ("id", *CREATOR_FIELDS)} for i in ids if i in by_id]


# ---------------------------------------------------------------- shortlists


async def list_shortlists(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select("creator_shortlists", filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=200)
    return [r for r in rows if r.get("client_id") == client_id]


async def get_shortlist(client_id: str, shortlist_id: str) -> Optional[Dict[str, Any]]:
    shortlist = await sb_get_one_by("creator_shortlists", filters={"id": f"eq.{shortlist_id}", "client_id": f"eq.{client_id}"})
    if not shortlist or shortlist.get("client_id") != client_id:
        return None
    items = await sb_select(
        "creator_shortlist_items",
        select="id,status,notes,created_at,creator_id,creators(*)",
        filters={"shortlist_id": f"eq.{shortlist_id}", "client_id": f"eq.{client_id}"},
        order="created_at.asc", limit=500,
    )
    return {**shortlist, "items": items}


# ---------------------------------------------------------------- sugestões com IA

SUGGEST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["suggestions"],
    "properties": {"suggestions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["handle", "reason"],
        "properties": {"handle": {"type": "string"}, "reason": {"type": "string"}},
    }}},
}
SUGGEST_INSTRUCTIONS = (
    "Você é estrategista de marketing de influência no Brasil. Indique perfis REAIS do Instagram "
    "que existam hoje e combinem com a marca. Só @ que você tem alta confiança de que existem; "
    "prefira contas profissionais (Business/Criador) e criadores brasileiros. Misture portes "
    "(micro, médio, grande) conforme o tipo de campanha. Nunca indique a própria marca nem concorrentes diretos. "
    "Em reason, uma frase objetiva sobre a afinidade com a marca, sem números de seguidores ou engajamento: "
    "as métricas serão conferidas depois na Meta."
)


async def suggest(client_id: str, campaign_type: str, brief: Optional[str], count: int) -> Dict[str, Any]:
    """IA indica, Meta confirma: só volta @ que existe e é conta profissional, com métricas reais."""
    from .studio_llm import llm_json

    context = await load_business_context(client_id)
    client = await sb_get_one("clients", f"id=eq.{client_id}") or {}
    lines = [f"Marca: {client.get('name') or client_id}"]
    lines += [f"{field}: {value}" for field, value in context["context"].items() if value]
    if brief:
        lines.append(f"Briefing da campanha: {brief[:1000]}")
    lines.append(f"Tipo de campanha: {'UGC (conteúdo para a marca usar)' if campaign_type == 'ugc' else 'influência (alcance na audiência do criador)'}")
    lines.append(f"Indique {count * 2} perfis do Instagram.")
    data = await llm_json(instructions=SUGGEST_INSTRUCTIONS, prompt="\n".join(lines),
                          schema_name="creator_suggestions", schema=SUGGEST_SCHEMA, temperature=0.3, timeout=60)

    connection = await get_active_connection_for_client(client_id) or {}
    own = str(connection.get("username") or "").lstrip("@").lower()
    candidates: Dict[str, str] = {}
    for item in data.get("suggestions") or []:
        try:
            handle = providers.normalize_handle("instagram", item.get("handle") or "")
        except ValueError:
            continue
        if handle != own and handle not in candidates:
            candidates[handle] = str(item.get("reason") or "")[:300]

    # Conferência na Meta em paralelo (poucas por vez): sequencial estourava o tempo da requisição.
    gate = asyncio.Semaphore(4)

    async def verify(handle: str) -> Optional[Dict[str, Any]]:
        async with gate:
            try:
                return await lookup(client_id, "instagram", handle)
            except IntegrationError as exc:
                if exc.code in {"META_CONNECTION_REQUIRED", "META_REAUTH_REQUIRED", "META_RATE_LIMITED", "META_PERMISSION_MISSING"}:
                    raise
                return None

    handles = list(candidates)[: count * 2]
    results = await asyncio.gather(*(verify(h) for h in handles))
    verified = [{"creator": c, "reason": candidates[h]} for h, c in zip(handles, results) if c][:count]
    discarded = [h for h, c in zip(handles, results) if not c]
    return {
        "suggestions": verified,
        "discarded": discarded,
        "context_available": context["available"],
    }
