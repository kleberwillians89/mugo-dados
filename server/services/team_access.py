"""Equipe e acessos por módulo (modelo do CRM Ruah).

Cada membro de cliente tem, em ``client_memberships``:

- ``permission_preset``: ponto de partida (administrador, gestor, marketing, comercial, visualizacao,
  personalizado);
- ``view_all``: vê todas as telas (menos Usuários);
- ``access_total``: pode tudo na empresa;
- ``status``: ``active`` ou ``inactive`` (inativo não entra em nada da empresa).

E em ``client_member_permissions`` os ajustes finos (código concedido ou retirado em relação ao preset).

Ordem de resolução (igual ao CRM): inativo nega tudo → acesso total concede tudo → ver tudo concede
``*.view`` (menos ``team.view``) → preset + ajustes.

Módulos "liberados pela Mugô" (``OPT_IN_CODES``, hoje o Social Media): não vêm de acesso total, de ver tudo
nem de preset. Só existem para o membro quando a equipe Mugô concede o código na tela de Usuários
(ajuste fino em ``client_member_permissions``); quem é do cliente não concede nem retira esses códigos.

Membro antigo (sem preset gravado) segue o papel: client_admin/owner/admin = acesso total; viewer = ver tudo.
Equipe Mugô (platform_admin, agency_admin, gestora da conta) não passa por aqui: pode tudo.

O papel gravado em ``role`` continua coerente para o resto do backend: ``client_admin`` quando há acesso
total, ``viewer`` nos demais. Quem tem ``<módulo>.edit`` sem acesso total é liberado módulo a módulo pela
checagem de rota (``enforce_route``), sem ganhar escrita no resto da empresa.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .ig_supabase import sb_select

# ------------------------------------------------------------------ catálogo

MODULES: List[Tuple[str, str]] = [
    ("central", "Central da marca"),
    ("ecommerce", "Ecommerce"),
    ("customers", "Clientes"),
    ("meta", "Meta"),
    ("google", "Google"),
    ("origins", "Origem das vendas"),
    ("calendar", "Calendário"),
    ("social_media", "Social Media"),
    ("brand_ai", "IA da marca"),
    ("media", "Mídia On"),
    ("social_report", "Relatório social"),
    ("tasks", "Tarefas"),
    ("clipping", "Clipping"),
    ("creators", "Criadores"),
    ("engagement", "Comentários"),
    ("integrations", "Integrações"),
    ("team", "Usuários"),
]
MODULE_LABEL = dict(MODULES)

# Telas só de leitura não têm ".edit".
_EDIT_LABEL = {
    "central": "Editar metas",
    "calendar": "Criar, editar e aprovar pautas",
    "social_media": "Gerar matriz de conteúdo e campanhas e enviar ao Calendário",
    "brand_ai": "Editar perfil e conhecimento da marca",
    "media": "Editar plano de mídia",
    "social_report": "Gerar relatório social",
    "tasks": "Gerenciar tarefas",
    "clipping": "Gerenciar clipping",
    "creators": "Analisar, selecionar e excluir criadores",
    "engagement": "Responder comentários e criar gatilhos",
    "team": "Gerenciar usuários e permissões",
}

CATALOG: List[Dict[str, str]] = []
for _module, _label in MODULES:
    CATALOG.append({"code": f"{_module}.view", "module": _module, "label": f"Ver {_label}"})
    if _module in _EDIT_LABEL:
        CATALOG.append({"code": f"{_module}.edit", "module": _module, "label": _EDIT_LABEL[_module]})
# Tarefas por pessoa: sem "tasks.all" o membro vê só as tarefas dele (responsável ou quem criou);
# "tasks.approve" faz a aprovação interna (equipe), liberado só pela Mugô.
CATALOG.append({"code": "tasks.all", "module": "tasks", "label": "Ver e gerenciar as tarefas de todos"})
CATALOG.append({"code": "tasks.approve", "module": "tasks", "label": "Aprovar internamente (equipe)"})
ALL_CODES: Set[str] = {entry["code"] for entry in CATALOG}
# Liberados só pela equipe Mugô, código a código (custo de IA e trabalho da agência).
OPT_IN_CODES: Set[str] = {"social_media.view", "social_media.edit", "tasks.approve"}
for _entry in CATALOG:
    _entry["opt_in"] = _entry["code"] in OPT_IN_CODES  # type: ignore[assignment]
# O que "acesso total" concede sozinho.
TOTAL_CODES: Set[str] = ALL_CODES - OPT_IN_CODES
VIEW_ALL_EXCLUDED = {"team.view"} | OPT_IN_CODES
VIEW_CODES: Set[str] = {c for c in ALL_CODES if c.endswith(".view") and c not in VIEW_ALL_EXCLUDED}


def _codes(*items: str) -> Set[str]:
    return {c for c in items if c in ALL_CODES}


PRESETS: Dict[str, Dict[str, Any]] = {
    "administrador": {"label": "Administrador", "view_all": True, "access_total": True, "codes": set(TOTAL_CODES)},
    "gestor": {"label": "Gestor", "view_all": True, "access_total": False, "codes": VIEW_CODES | _codes(
        "central.edit", "calendar.edit", "brand_ai.edit", "media.edit", "social_report.edit", "tasks.edit",
        "clipping.edit", "creators.edit", "engagement.edit")},
    "marketing": {"label": "Marketing / Conteúdo", "view_all": False, "access_total": False, "codes": _codes(
        "central.view", "meta.view", "google.view", "origins.view", "calendar.view", "calendar.edit",
        "brand_ai.view", "brand_ai.edit", "media.view", "media.edit", "social_report.view", "social_report.edit",
        "clipping.view", "creators.view", "creators.edit", "engagement.view", "engagement.edit")},
    "comercial": {"label": "Comercial", "view_all": False, "access_total": False, "codes": _codes(
        "central.view", "ecommerce.view", "customers.view", "origins.view", "meta.view", "google.view",
        "tasks.view", "tasks.edit")},
    "visualizacao": {"label": "Visualização", "view_all": True, "access_total": False, "codes": set(VIEW_CODES)},
    "personalizado": {"label": "Personalizado", "view_all": False, "access_total": False, "codes": set()},
}
LEGACY_ADMIN_ROLES = {"client_admin", "owner", "admin"}


def catalog_payload() -> Dict[str, Any]:
    return {
        "modules": [{"code": code, "label": label} for code, label in MODULES],
        "permissions": CATALOG,
        "presets": [{"code": code, "label": p["label"], "view_all": p["view_all"], "access_total": p["access_total"],
                     "codes": sorted(p["codes"])} for code, p in PRESETS.items()],
    }


# ------------------------------------------------------------------ cálculo

def base_codes(preset: Optional[str]) -> Set[str]:
    return set(PRESETS.get(str(preset or ""), PRESETS["personalizado"])["codes"])


def resolve_codes(*, status: str, preset: Optional[str], view_all: bool, access_total: bool,
                  overrides: Iterable[Tuple[str, bool]] = ()) -> Set[str]:
    if status != "active":
        return set()
    if access_total:
        # Acesso total = tudo menos os módulos liberados pela Mugô, que só valem quando concedidos.
        codes = set(TOTAL_CODES)
        codes |= {c for c, granted in overrides if granted and c in OPT_IN_CODES}
        return codes
    codes = base_codes(preset)
    if view_all:
        codes |= VIEW_CODES
    for code, granted in overrides:
        if code not in ALL_CODES:
            continue
        if granted:
            codes.add(code)
        else:
            codes.discard(code)
    return codes


def overrides_for(preset: Optional[str], view_all: bool, wanted: Iterable[str]) -> List[Tuple[str, bool]]:
    """Diferença entre o que a tela marcou e o que o preset (+ ver tudo) já dá."""
    base = base_codes(preset) | (VIEW_CODES if view_all else set())
    if preset == "administrador":
        base = set(TOTAL_CODES)
    target = {c for c in wanted if c in ALL_CODES}
    return sorted([(c, True) for c in target - base] + [(c, False) for c in base - target])


def role_for(access_total: bool) -> str:
    return "client_admin" if access_total else "viewer"


def legacy_flags(role: str) -> Dict[str, Any]:
    admin = role in LEGACY_ADMIN_ROLES
    return {"preset": "administrador" if admin else "visualizacao", "view_all": True, "access_total": admin}


# ------------------------------------------------------------------ leitura (com cache curto)

_CACHE_SECONDS = 15
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def invalidate(client_id: str, user_id: Optional[str] = None) -> None:
    for key in list(_cache):
        if key[0] == client_id and (user_id is None or key[1] == user_id):
            _cache.pop(key, None)


def _legacy_access(role: str) -> Dict[str, Any]:
    flags = legacy_flags(role)
    return {"role": role, "status": "active", **flags, "overrides": [],
            "codes": resolve_codes(status="active", preset=flags["preset"], view_all=flags["view_all"],
                                   access_total=flags["access_total"])}


async def member_access(client_id: str, user_id: str, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Acesso efetivo do membro nesta empresa, ou None se não for membro.

    Sem a migração 000083 (colunas novas ausentes), cai no comportamento antigo pelo papel. Se o banco
    não responder e o papel já for conhecido (``role``), também vale o papel: nunca mais restrito nem mais
    aberto que antes desta tela existir."""
    try:
        return await _member_access(client_id, user_id)
    except Exception as exc:  # noqa: BLE001
        if role is None:
            raise
        print(f"[team_access] fallback_role client_id={client_id} error_type={type(exc).__name__}")
        return _legacy_access(str(role).strip().lower())


async def _member_access(client_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    key = (client_id, user_id)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    filters = {"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"}
    overrides: List[Tuple[str, bool]] = []
    try:
        rows = await sb_select("client_memberships", select="role,status,permission_preset,view_all,access_total",
                               filters=filters, limit=1)
        modern = True
    except Exception:  # noqa: BLE001 — schema antigo
        rows = await sb_select("client_memberships", select="role", filters=filters, limit=1)
        modern = False
    if not rows:
        return None
    row = rows[0]
    role = str(row.get("role") or "").strip().lower()
    if modern and row.get("permission_preset"):
        flags = {"preset": row.get("permission_preset"), "view_all": bool(row.get("view_all")),
                 "access_total": bool(row.get("access_total"))}
        try:
            perm_rows = await sb_select("client_member_permissions", select="permission_code,granted", filters=filters, limit=500)
            overrides = [(str(r.get("permission_code")), bool(r.get("granted"))) for r in perm_rows]
        except Exception:  # noqa: BLE001
            overrides = []
    else:
        flags = legacy_flags(role)
    status = str(row.get("status") or "active") if modern else "active"
    access = {"role": role, "status": status, **flags, "overrides": overrides,
              "codes": resolve_codes(status=status, preset=flags["preset"], view_all=flags["view_all"],
                                     access_total=flags["access_total"], overrides=overrides)}
    if len(_cache) > 5000:
        _cache.clear()
    _cache[key] = (time.monotonic() + _CACHE_SECONDS, access)
    return access


# ------------------------------------------------------------------ checagem por rota

# Rota atual (método, caminho), gravada pelo middleware em app.py.
REQUEST_ROUTE: ContextVar[Optional[Tuple[str, str]]] = ContextVar("mugo_request_route", default=None)

# Segmento depois de /api/clients/{id}/ (ou de /api/clients/{id}/studio/) → (módulo, exige .view no GET).
# GET compartilhado entre telas (ex.: perfil e contexto da marca) não exige .view; só a escrita é checada.
_CLIENT_SEGMENTS: Dict[str, Tuple[str, bool]] = {
    "creators": ("creators", True),
    "crm": ("tasks", True),
    "goals": ("central", False),
    "sales-by-origin": ("origins", True),
    "whatsapp": ("origins", True),
    # Integrações (conexões, sincronização, OAuth) seguem só para quem tem acesso total (papel client_admin).
}
_STUDIO_SEGMENTS: Dict[str, Tuple[str, bool]] = {
    "calendar": ("calendar", True),
    "campaigns": ("social_media", True),
    "matrix": ("social_media", True),
    "agents": ("social_media", True),
    "briefs": ("tasks", True),
    "projects": ("tasks", True),
    "library": ("calendar", True),
    "documents": ("social_media", True),
    "approvals": ("calendar", True),
    "assist": ("calendar", False),
    "references": ("calendar", False),
    "publisher": ("calendar", True),
    "timeline": ("calendar", False),
    "contacts": ("calendar", False),
    "messages": ("calendar", False),
    "engagement": ("engagement", True),
    "clipping": ("clipping", True),
    "social-report": ("social_report", True),
    "media": ("media", True),
    "strategy": ("media", True),
    "brand-agent": ("brand_ai", True),
    "knowledge": ("brand_ai", True),
    "brand-profile": ("brand_ai", False),
}
_TOP_LEVEL: Dict[str, Tuple[str, bool]] = {
    "customers": ("customers", True),
    "client-access": ("team", True),
    "team": ("team", True),
}


def route_module(method: str, path: str) -> Optional[Tuple[str, str]]:
    """(módulo, código exigido) para a rota, ou None quando a rota não pertence a um módulo."""
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) < 2 or parts[0] != "api":
        return None
    entry: Optional[Tuple[str, bool]] = None
    if parts[1] == "clients" and len(parts) >= 4:
        if parts[3] == "studio" and len(parts) >= 5:
            entry = _STUDIO_SEGMENTS.get(parts[4])
        else:
            entry = _CLIENT_SEGMENTS.get(parts[3])
    elif parts[1] in _TOP_LEVEL:
        entry = _TOP_LEVEL[parts[1]]
        if parts[1] == "team" and len(parts) >= 3 and parts[2] in ("me", "catalog"):
            return None  # cada membro lê o próprio acesso e o catálogo
    if not entry:
        return None
    module, view_enforced = entry
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return (module, f"{module}.view") if view_enforced else None
    return module, f"{module}.edit"


def current_requirement() -> Optional[Tuple[str, str]]:
    route = REQUEST_ROUTE.get()
    return route_module(*route) if route else None


def denied_message(code: str) -> str:
    module = code.split(".", 1)[0]
    action = "ver" if code.endswith(".view") else "alterar"
    return f"Seu usuário não tem permissão para {action} {MODULE_LABEL.get(module, module)} nesta empresa."
