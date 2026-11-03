"""Saúde dos clientes (equipe Mugô): o que falta preencher para a IA ser fiel à marca e como está o WhatsApp.

Uma linha por empresa, com itens "ok / falta" e o que fazer. Só leitura, lida em lote (uma consulta por
tabela) para não pesar com muitas empresas.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from .ig_supabase import sb_select

PROFILE_FIELDS = ("tone_of_voice", "audience", "pillars", "keywords_use", "restrictions")
BUSINESS_FIELDS = ("segment", "product_description", "audience", "positioning", "differentiators")
PUBLISH_SCOPE = "instagram_content_publish"
COMMENT_SCOPE = "instagram_manage_comments"


async def _rows(table: str, select: str, **kwargs: Any) -> List[Dict[str, Any]]:
    try:
        return await sb_select(table, select=select, limit=5000, **kwargs)
    except Exception:  # noqa: BLE001 — tabela de uma migração ainda não aplicada: o item fica "sem dado"
        return []


def _filled(value: Any) -> bool:
    return bool(value) and (not isinstance(value, str) or bool(value.strip()))


def check(ok: bool, label: str, fix: str) -> Dict[str, Any]:
    return {"ok": bool(ok), "label": label, "fix": None if ok else fix}


async def overview() -> Dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    clients = await _rows("clients", "id,name", order="name.asc")
    profiles = {r["client_id"]: (r.get("profile") or {}) for r in await _rows("studio_brand_profiles", "client_id,profile")}
    business = {r["client_id"]: r for r in await _rows("client_business_context", "client_id," + ",".join(BUSINESS_FIELDS))}
    connections = defaultdict(list)
    for r in await _rows("meta_connections", "client_id,platform,status,scopes_json", filters={"platform": "eq.instagram"}):
        connections[r["client_id"]].append(r)
    contacts = defaultdict(list)
    for r in await _rows("studio_client_contacts", "client_id,receives,email,active", filters={"active": "eq.true"}):
        contacts[r["client_id"]].append(r)
    messages = defaultdict(list)
    for r in await _rows("studio_messages", "client_id,status,error_code,delivery_status", filters={"created_at": f"gte.{since}"}):
        messages[r["client_id"]].append(r)
    ai = {r["client_id"]: bool(r.get("ai_autoreply")) for r in await _rows("ig_engagement_settings", "client_id,ai_autoreply")}

    out = []
    for client in clients:
        cid = client["id"]
        profile = profiles.get(cid, {})
        biz = business.get(cid, {})
        conns = [c for c in connections.get(cid, []) if c.get("status") == "active"]
        scopes = {str(s) for c in conns for s in (c.get("scopes_json") or [])}
        people = contacts.get(cid, [])
        sent = messages.get(cid, [])
        failures = Counter(m.get("error_code") or "erro" for m in sent if m.get("status") == "falhou" or m.get("delivery_status") == "failed")
        profile_done = sum(1 for f in PROFILE_FIELDS if _filled(profile.get(f)))
        business_done = sum(1 for f in BUSINESS_FIELDS if _filled(biz.get(f)))
        checks = [
            check(profile_done >= 4, f"Perfil da marca ({profile_done}/{len(PROFILE_FIELDS)})", "Calendário → Perfil da marca: tom de voz, público, pilares, palavras e restrições."),
            check(business_done >= 3, f"Contexto de negócio ({business_done}/{len(BUSINESS_FIELDS)})", "Empresas → editar → Contexto de negócio."),
            check(bool(conns), "Instagram conectado", "Integrações → conectar o Instagram da marca."),
            check(not conns or not scopes or PUBLISH_SCOPE in scopes, "Permissão de publicar", "Reconectar o Instagram para liberar a publicação automática."),
            check(not conns or not scopes or COMMENT_SCOPE in scopes, "Permissão de comentários", "Reconectar o Instagram para responder comentários."),
            check(any("conteudo" in (p.get("receives") or []) for p in people), "Contato que aprova conteúdo", "Aprovação → Contatos: quem aprova os posts (WhatsApp)."),
            check(not people or all(p.get("email") for p in people), "E-mail dos contatos", "Preencha o e-mail para reconhecer as reuniões do Google Calendar."),
            check(not failures, "WhatsApp sem falhas (30 dias)", "Veja os erros: telefone não cadastrado no CRM, template não aprovado etc."),
        ]
        out.append({
            "client_id": cid, "name": client.get("name") or cid, "score": round(100 * sum(c["ok"] for c in checks) / len(checks)),
            "checks": checks,
            "whatsapp": {"sent": sum(1 for m in sent if m.get("status") == "enviado"), "failed": sum(failures.values()),
                         "read": sum(1 for m in sent if m.get("delivery_status") == "read"), "errors": failures.most_common(3)},
            "ai_comments": ai.get(cid, False),
        })
    out.sort(key=lambda r: (r["score"], r["name"].lower()))
    return {"clients": out}
