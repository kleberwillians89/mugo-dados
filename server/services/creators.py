"""Creator Intelligence: busca, banco de criadores, comparação, shortlists e orçamento.

O banco de criadores (creators/creator_metrics) guarda só dados públicos e é
reaproveitado entre empresas. Shortlists são sempre filtradas por client_id.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from . import creators_providers as providers
from .business_context import load_business_context
from .ig_supabase import sb_delete, sb_get_one, sb_get_one_by, sb_insert, sb_select, sb_update, sb_upload_public, sb_upsert
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


AVATAR_MAX_BYTES = 2 * 1024 * 1024


def _stored(url: Optional[str]) -> bool:
    return bool(url) and "/storage/v1/object/public/" in str(url)


async def persist_avatar(network: str, handle: str, url: Optional[str]) -> Optional[str]:
    """A foto do Instagram/TikTok vem com link assinado que expira em poucos dias: guarda uma cópia no storage do
    MUGOVERSO e devolve o link permanente. Se não der (timeout, não é imagem, sem storage), fica o link original."""
    if not url or _stored(url) or not str(url).startswith("https://"):
        return url
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(str(url))
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if response.status_code >= 400 or not kind.startswith("image/") or len(response.content) > AVATAR_MAX_BYTES:
            return url
        ext = {"image/png": "png", "image/webp": "webp"}.get(kind, "jpg")
        return await sb_upload_public(f"creators/{network}/{handle}.{ext}", response.content, kind)
    except Exception as exc:  # noqa: BLE001 — a foto não pode impedir de salvar o criador
        print(f"[creators] avatar_not_stored network={network} {type(exc).__name__}")
        return url


async def save_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Grava perfil + snapshot. Um resultado parcial nunca apaga dado completo já salvo."""
    metrics = providers.compute_engagement(profile)
    row = {**{k: profile.get(k) for k in CREATOR_FIELDS}, **metrics, "collected_at": _now().isoformat()}
    existing = await get_by_handle(row["network"], row["handle"])
    if not row.get("avatar_url") and existing and existing.get("avatar_url"):
        row["avatar_url"] = existing["avatar_url"]  # busca por hashtag não traz foto: não apaga a que já existe
    row["avatar_url"] = await persist_avatar(row["network"], row["handle"], row.get("avatar_url"))
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


async def remove_creator(client_id: str, creator_id: str, *, agency: bool) -> bool:
    """Excluir criador. Cliente: sai só da lista da própria empresa (o perfil segue no banco das outras).
    Agência: sai do banco inteiro (métricas e itens de shortlist vão junto, por cascade)."""
    if agency:
        rows = await sb_delete("creators", filters={"id": f"eq.{creator_id}"})
    else:
        rows = await sb_delete("creator_client_links", filters={"client_id": f"eq.{client_id}", "creator_id": f"eq.{creator_id}"})
    return bool(rows)


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


async def repair_avatars(client_id: str, rows: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    """Foto que não está no storage do MUGOVERSO (vazia ou link do Instagram que já expirou): busca de novo na Meta
    (grátis) e guarda a cópia permanente. Poucas por vez, para a lista não demorar."""
    todo = [r for r in rows if r.get("network") == "instagram" and r.get("handle") and not _stored(r.get("avatar_url"))][:limit]

    async def fix(row: Dict[str, Any]) -> None:
        try:
            profile = await asyncio.wait_for(_meta_profile(client_id, row["handle"]), timeout=8)
            stored = await persist_avatar("instagram", row["handle"], profile.get("avatar_url"))
            if stored and _stored(stored):
                row["avatar_url"] = stored
                await sb_update("creators", filters={"id": f"eq.{row['id']}"}, patch={"avatar_url": stored}, returning="minimal")
        except Exception as exc:  # noqa: BLE001 - sem foto, o criador aparece com a inicial
            print(f"[creators] avatar_repair_failed {type(exc).__name__}")
    await asyncio.gather(*(fix(r) for r in todo))
    return rows


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
    "que existam hoje e combinem com a marca descrita no CÉREBRO DA MARCA. Só @ que você tem alta confiança de que existem; "
    "prefira contas profissionais (Business/Criador), criadores brasileiros e perfis ativos com audiência de verdade "
    "(nada de contas recém-criadas ou de nicho vazio). Misture portes (micro, médio, grande) conforme o tipo de campanha. "
    "Use o HISTÓRICO: busque perfis parecidos com quem FECHOU, evite o perfil de quem NÃO FECHOU e nunca repita quem já "
    "está na base. Nunca indique a própria marca nem concorrentes diretos. "
    "Em reason, uma frase objetiva sobre a afinidade com a marca, sem números de seguidores ou engajamento: "
    "as métricas serão conferidas depois na Meta."
)
FIT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["profiles"],
    "properties": {"profiles": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["handle", "fit", "reason"],
        "properties": {"handle": {"type": "string"}, "fit": {"type": "integer"}, "reason": {"type": "string"}},
    }}},
}
FIT_INSTRUCTIONS = (
    "Você avalia criadores REAIS para uma marca. Para cada perfil, leia a bio e as legendas recentes e dê fit de 0 a 10: "
    "o quanto o conteúdo dele conversa com a marca (assunto, estética, público, tom). Perfil que não fala do assunto, "
    "que é loja/revenda, concorrente ou conta institucional fica abaixo de 5. Em reason, uma frase citando o que você viu "
    "no conteúdo dele (não invente nada que não esteja na bio ou nas legendas)."
)
MIN_FOLLOWERS = {"ugc": 1000, "influencer": 5000}
STALE_DAYS = 90
MIN_FIT = 5
MAX_CANDIDATES = 24  # teto de conferências na Meta por clique


def suggestion_gate(creator: Dict[str, Any], posts: List[Dict[str, Any]], campaign_type: str,
                    today: Optional[datetime] = None) -> Optional[str]:
    """Motivo para descartar um perfil conferido (None = passa). Puro, para teste."""
    floor = MIN_FOLLOWERS["ugc" if campaign_type == "ugc" else "influencer"]
    followers = creator.get("followers")
    if followers is None or followers < floor:
        return "poucos seguidores"
    stamps = sorted((str(p.get("timestamp") or "") for p in posts or [] if p.get("timestamp")), reverse=True)
    if stamps:
        try:
            last = datetime.fromisoformat(stamps[0].replace("Z", "+00:00").replace("+0000", "+00:00"))
            now = today or datetime.now(timezone.utc)
            if (now - last).days > STALE_DAYS:
                return "sem posts recentes"
        except ValueError:
            pass
    if (creator.get("engagement_rate") or 0) <= 0 and creator.get("engagement_rate") is not None:
        return "sem engajamento"
    return None


def _brief_number(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "?"
    return f"{n / 1_000_000:.1f} mi".replace(".", ",") if n >= 1_000_000 else f"{n / 1000:.0f} mil" if n >= 1000 else str(int(n))


async def creator_history(client_id: str) -> Dict[str, List[str]]:
    """O que já aconteceu com criadores desta marca, para a IA aprender: quem fechou, quem não, quem já está na base."""
    from .creator_media_kits import list_kits
    out: Dict[str, List[str]] = {"fecharam": [], "nao_fecharam": [], "em_conversa": [], "na_base": []}
    try:
        ids = await linked_ids(client_id)
        rows = await sb_select("creators", select="id,handle,followers", filters={"id": f"in.({','.join(list(ids)[:400])})"},
                               limit=400) if ids else []
        by_id = {str(r["id"]): r for r in rows}
        kits = await list_kits(client_id)
    except Exception as exc:  # noqa: BLE001 — sem histórico a sugestão segue
        print(f"[creators][history_unavailable] client_id={client_id} error_type={type(exc).__name__}")
        return out
    seen = set()
    for kit in kits:
        creator = by_id.get(str(kit.get("creator_id")))
        if not creator:
            continue
        seen.add(creator["handle"])
        label = f"@{creator['handle']} ({_brief_number(creator.get('followers'))} seguidores)"
        status = kit.get("status")
        if status == "fechado":
            deal = next(iter(kit.get("deals") or []), {}) or {}
            what = str(deal.get("what") or "").strip()
            out["fecharam"].append(label + (f": {what[:60]}" if what else ""))
        elif status == "nao_fechou":
            note = str(kit.get("status_note") or "").strip()
            out["nao_fecharam"].append(label + (f": {note[:80]}" if note else ""))
        elif status in ("contatado", "negociando"):
            out["em_conversa"].append(label)
    out["na_base"] = sorted(r["handle"] for r in rows if r.get("handle"))
    return {k: v[:40] for k, v in out.items()}


def _history_lines(history: Dict[str, List[str]]) -> List[str]:
    lines = []
    for key, title in (("fecharam", "FECHARAM com a marca (busque perfis parecidos)"),
                       ("nao_fecharam", "NÃO FECHARAM (evite esse perfil)"),
                       ("em_conversa", "Em conversa agora"),
                       ("na_base", "Já estão na base (não repita)")):
        if history.get(key):
            lines.append(f"{title}: " + ", ".join(history[key] if key != "na_base" else (f"@{h}" for h in history[key])))
    return ["HISTÓRICO DE CRIADORES DESTA MARCA:", *lines] if lines else []


async def _recent_posts(creator_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    if not creator_ids:
        return {}
    try:
        rows = await sb_select("creator_metrics", select="creator_id,recent_posts,collected_at",
                               filters={"creator_id": f"in.({','.join(creator_ids)})"}, order="collected_at.desc", limit=len(creator_ids) * 3)
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r.get("creator_id")), r.get("recent_posts") or [])
    return out


async def _rate_fit(client_id: str, candidates: List[Dict[str, Any]], posts: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """A IA lê bio e legendas reais de quem passou na Meta e dá nota de afinidade. Falhou → todos passam com o motivo antigo."""
    from .studio_llm import llm_json, profile_model
    blocks = []
    for c in candidates:
        captions = [str(p.get("caption") or "").replace("\n", " ")[:160] for p in posts.get(str(c.get("id")), []) if p.get("caption")][:5]
        blocks.append(f"@{c['handle']} | {c.get('display_name') or ''} | bio: {str(c.get('biography') or '')[:200]} | "
                      f"legendas: {' // '.join(captions) or 'sem legenda disponível'}")
    try:
        data = await llm_json(client_id=client_id, brand="criadores", instructions=FIT_INSTRUCTIONS, prompt="\n".join(blocks),
                              schema_name="creator_fit", schema=FIT_SCHEMA, temperature=0.2, timeout=60, model=profile_model(),
                              guidance=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[creators][fit_unavailable] client_id={client_id} error_type={type(exc).__name__}")
        return {}
    out = {}
    for item in data.get("profiles") or []:
        handle = str(item.get("handle") or "").lstrip("@").lower()
        if handle:
            out[handle] = {"fit": int(item.get("fit") or 0), "reason": str(item.get("reason") or "")[:300]}
    return out


async def suggest(client_id: str, campaign_type: str, brief: Optional[str], count: int) -> Dict[str, Any]:
    """IA indica com o cérebro da marca e o histórico de criadores; a Meta confirma que existe; filtros de porte e
    atividade; a IA lê bio e legendas reais e só fica quem tem afinidade de verdade."""
    from .studio_llm import llm_json, profile_model

    context = await load_business_context(client_id)
    client = await sb_get_one("clients", f"id=eq.{client_id}") or {}
    history = await creator_history(client_id)
    lines = [f"Marca: {client.get('name') or client_id}"]
    lines += _history_lines(history)
    if brief:
        lines.append(f"Briefing da campanha: {brief[:1000]}")
    lines.append(f"Tipo de campanha: {'UGC (conteúdo para a marca usar)' if campaign_type == 'ugc' else 'influência (alcance na audiência do criador)'}")
    lines.append(f"Indique {min(count * 3, MAX_CANDIDATES)} perfis do Instagram.")
    data = await llm_json(client_id=client_id, brand="criadores", instructions=SUGGEST_INSTRUCTIONS, prompt="\n".join(lines),
                          schema_name="creator_suggestions", schema=SUGGEST_SCHEMA, temperature=0.4, timeout=90,
                          model=profile_model())

    connection = await get_active_connection_for_client(client_id) or {}
    own = str(connection.get("username") or "").lstrip("@").lower()
    skip = {own, *history.get("na_base", [])}
    candidates: Dict[str, str] = {}
    for item in data.get("suggestions") or []:
        try:
            handle = providers.normalize_handle("instagram", item.get("handle") or "")
        except ValueError:
            continue
        if handle not in skip and handle not in candidates:
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

    handles = list(candidates)[: min(count * 3, MAX_CANDIDATES)]
    results = await asyncio.gather(*(verify(h) for h in handles))
    found = [(h, c) for h, c in zip(handles, results) if c]
    discarded = [h for h, c in zip(handles, results) if not c]
    posts = await _recent_posts([str(c["id"]) for _, c in found if c.get("id")])
    filtered: Dict[str, List[str]] = {}
    passed = []
    for h, c in found:
        why = suggestion_gate(c, posts.get(str(c.get("id")), []), campaign_type)
        if why:
            filtered.setdefault(why, []).append(h)
        else:
            passed.append((h, c))
    fit = await _rate_fit(client_id, [c for _, c in passed], posts) if passed else {}
    ranked = []
    for h, c in passed:
        score = fit.get(h)
        if score and score["fit"] < MIN_FIT:
            filtered.setdefault("pouca afinidade com a marca", []).append(h)
            continue
        ranked.append(({"creator": c, "reason": (score or {}).get("reason") or candidates[h], "fit": (score or {}).get("fit")},
                       (score or {}).get("fit") or 0, c.get("followers") or 0))
    ranked.sort(key=lambda r: (r[1], r[2]), reverse=True)
    # A conferência vincula o perfil à marca; quem a IA descartou não deve aparecer na lista de criadores dela.
    dropped = {h for hs in filtered.values() for h in hs}
    drop_ids = [str(c["id"]) for h, c in found if h in dropped and c.get("id")]
    if drop_ids:
        try:
            await sb_delete("creator_client_links", filters={"client_id": f"eq.{client_id}", "creator_id": f"in.({','.join(drop_ids)})"})
        except Exception:  # noqa: BLE001
            pass
    return {
        "suggestions": [r[0] for r in ranked][:count],
        "discarded": discarded,
        "filtered": filtered,
        "context_available": context["available"],
    }



# ---------------------------------------------------------------- achar o @ certo enquanto digita

_PREVIEW_CACHE: Dict[str, tuple] = {}
PREVIEW_TTL = 3600


def handle_variants(handle: str, limit: int = 4) -> List[str]:
    """@ parecidos com o digitado (o jeito mais comum de errar ou de o perfil oficial ser outro): com/sem ponto e
    sublinhado, com "oficial", sem números no fim. Só formatos válidos do Instagram."""
    import re
    base = handle.lower().strip("._")
    core = re.sub(r"[._]", "", base)
    stem = re.sub(r"\d+$", "", base).strip("._")
    out: List[str] = []
    for v in (core, base.replace(".", "_"), base.replace("_", "."), f"{base}oficial", f"{base}.oficial", f"{base}_oficial",
              f"{core}oficial", stem, f"oficial{core}", f"{base}_", f"_{base}"):
        v = v[:30]
        if v and v != handle and re.fullmatch(r"[a-z0-9._]{2,30}", v) and v not in out:
            out.append(v)
    return out[:limit]


async def similar_profiles(client_id: str, handle: str, only_ids: Visible, skip: set) -> List[Dict[str, Any]]:
    """Perfis que existem com @ parecido: variações conferidas na Meta (grátis) e criadores do banco com o mesmo começo."""
    found: List[Dict[str, Any]] = []
    prefix = handle[:5]
    if len(prefix) >= 3:
        for c in await list_creators(network="instagram", q=prefix, min_followers=None, limit=5, offset=0, only_ids=only_ids):
            if c.get("handle") not in skip:
                skip.add(c["handle"])
                found.append({k: c.get(k) for k in ("id", "network", "handle", "display_name", "avatar_url", "followers")})

    async def check(variant: str) -> Optional[Dict[str, Any]]:
        key = f"{client_id}:{variant}"
        hit = _PREVIEW_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < PREVIEW_TTL:
            return hit[1] if hit[1] and not hit[1].get("missing") else None
        try:
            profile = await asyncio.wait_for(_meta_profile(client_id, variant), timeout=6)
            view = {k: profile.get(k) for k in ("network", "handle", "display_name", "avatar_url", "followers", "biography")}
        except (IntegrationError, asyncio.TimeoutError):
            view = {"network": "instagram", "handle": variant, "missing": True}
        _PREVIEW_CACHE[key] = (time.monotonic(), view)
        return None if view.get("missing") else view

    for view in await asyncio.gather(*(check(v) for v in handle_variants(handle) if v not in skip)):
        if view and view["handle"] not in skip:
            skip.add(view["handle"])
            found.append(view)
    return sorted(found, key=lambda c: -(c.get("followers") or 0))[:6]


async def resolve(client_id: str, network: str, query: str, only_ids: Visible) -> Dict[str, Any]:
    """Sugestões enquanto a pessoa digita: criadores já salvos (nome ou @, com foto) e, quando o texto já é um @
    válido do Instagram, a prévia oficial da Meta (grátis). Nada é salvo aqui: salvar é o "Analisar"."""
    text = str(query or "").strip()
    if len(text.lstrip("@")) < 2:
        return {"saved": [], "exact": None}
    saved = await list_creators(network=network, q=text.lstrip("@"), min_followers=None, limit=6, offset=0, only_ids=only_ids)
    exact = None
    try:
        handle = providers.normalize_handle(network, text)
    except ValueError:
        handle = None
    if handle and network == "instagram" and not any(c.get("handle") == handle for c in saved) and " " not in text:
        key = f"{client_id}:{handle}"
        hit = _PREVIEW_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < PREVIEW_TTL:
            exact = hit[1]
        else:
            try:
                profile = await _meta_profile(client_id, handle)
                exact = {k: profile.get(k) for k in ("network", "handle", "display_name", "avatar_url", "followers", "biography")}
            except IntegrationError as exc:
                exact = {"network": network, "handle": handle, "missing": True,
                         "reason": "Não é conta profissional ou não existe." if exc.code == "CREATOR_NOT_FOUND" else "A Meta não respondeu agora."}
            _PREVIEW_CACHE[key] = (time.monotonic(), exact)
    similar: List[Dict[str, Any]] = []
    if handle and len(handle) >= 4 and network == "instagram" and " " not in text:
        skip = {c.get("handle") for c in saved} | {handle}
        try:
            similar = await similar_profiles(client_id, handle, only_ids, skip)
        except Exception:  # noqa: BLE001 - sugestão extra; a busca principal segue
            similar = []
    return {"saved": [{k: c.get(k) for k in ("id", "network", "handle", "display_name", "avatar_url", "followers", "engagement_rate")} for c in saved],
            "exact": exact, "similar": similar}


async def people_search(client_id: str, query: str, limit: int = 8) -> Dict[str, Any]:
    """Busca por NOME no Instagram (a Meta só consulta pelo @ exato). Usa 1 execução da Apify, dentro do teto."""
    text = " ".join(str(query or "").split())[:60]
    if len(text) < 2:
        raise ValueError("Digite pelo menos 2 letras do nome.")
    items = await _apify(client_id, "instagram_people", {"search": text, "searchType": "user", "searchLimit": max(1, min(limit, 10))}, max(1, min(limit, 10)))
    return {"query": text, "people": providers.instagram_people_items(items)[:limit]}
