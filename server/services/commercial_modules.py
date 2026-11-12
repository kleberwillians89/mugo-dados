"""Catálogo e resolução comercial por tenant, sem enforcement de acesso.

Permissões individuais continuam em ``team_access``. Este módulo descreve somente
o que foi contratado e não é chamado pelas guardas de rota nesta etapa.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Optional, Tuple


@dataclass(frozen=True)
class CommercialModule:
    key: str
    label: str
    capabilities: FrozenSet[str]
    permission_modules: FrozenSet[str]
    routes: Tuple[str, ...]


BASIC_CAPABILITIES: FrozenSet[str] = frozenset({"briefing", "tasks"})


COMMERCIAL_MODULES: Dict[str, CommercialModule] = {
    "social_media": CommercialModule("social_media", "Social Media + Redação", frozenset({"social_media", "redacao"}),
                                     frozenset({"social_media"}), ("campaigns", "redacao")),
    "meta": CommercialModule("meta", "Meta", frozenset({"meta"}), frozenset({"meta"}), ("meta",)),
    "google": CommercialModule("google", "Google", frozenset({"google"}), frozenset({"google"}), ("google",)),
    "ecommerce": CommercialModule("ecommerce", "Ecommerce", frozenset({"ecommerce"}), frozenset({"ecommerce"}), ("ecommerce",)),
    "crm": CommercialModule("crm", "CRM", frozenset({"crm"}), frozenset({"origins", "customers"}),
                            ("origins", "customers", "customer_value")),
    "whatsapp": CommercialModule("whatsapp", "WhatsApp", frozenset({"whatsapp"}), frozenset({"origins"}), ("whatsapp",)),
    "email_marketing": CommercialModule("email_marketing", "E-mail Marketing", frozenset({"email_marketing"}),
                                        frozenset({"customers"}), ("email_marketing",)),
    "media": CommercialModule("media", "Mídia On", frozenset({"media"}), frozenset({"media"}), ("media",)),
    "engagement": CommercialModule("engagement", "Comentários", frozenset({"engagement"}),
                                   frozenset({"engagement"}), ("engagement",)),
    "clipping": CommercialModule("clipping", "Clipping", frozenset({"clipping"}), frozenset({"clipping"}),
                                 ("clipping", "radar", "brand_health")),
    "benchmark": CommercialModule("benchmark", "Benchmarking", frozenset({"benchmark"}), frozenset({"clipping"}), ("benchmark",)),
    "reports": CommercialModule("reports", "Relatórios", frozenset({"reports"}), frozenset({"social_report"}), ("social_report",)),
    "planning": CommercialModule("planning", "Planejamento", frozenset({"planning"}), frozenset({"tasks"}), ("planning",)),
    "creators": CommercialModule("creators", "Criadores", frozenset({"creators"}), frozenset({"creators"}), ("creators",)),
}

# Compatibilidade de dados: Redação nunca vira produto independente.
FEATURE_ALIASES = {"redacao": "social_media"}
ALL_OPTIONAL_MODULES: FrozenSet[str] = frozenset(COMMERCIAL_MODULES)
MAX_PLAN_FEATURES = max(32, len(COMMERCIAL_MODULES))
LEGACY_FEATURE_LABELS: FrozenSet[str] = frozenset({
    "dashboards de meta, google, ga4 e loja",
    "crm com jornada do cliente",
    "e-mail marketing e carrinho abandonado",
    "benchmarking de instagram",
    "tudo do essencial",
    "fluxos automáticos",
    "ações da ia",
    "ltv, cac e coortes",
    "preços dos concorrentes",
    "tudo do crescimento",
    "mais volume de envio",
    "mais concorrentes e produtos monitorados",
    "suporte prioritário da mugô",
})


def normalize_module_keys(features: Iterable[Any]) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    recognized = set()
    unknown = set()
    for raw in features:
        value = str(raw or "").strip().lower()
        if not value:
            continue
        value = FEATURE_ALIASES.get(value, value)
        if value in COMMERCIAL_MODULES:
            recognized.add(value)
        else:
            unknown.add(value)
    return frozenset(recognized), frozenset(unknown)


def _result(client_id: str, modules: FrozenSet[str], *, source: str, configured: bool,
            resolution_error: Optional[str] = None) -> Dict[str, Any]:
    capabilities = set(BASIC_CAPABILITIES)
    for key in modules:
        capabilities.update(COMMERCIAL_MODULES[key].capabilities)
    return {
        "client_id": client_id,
        "basic_capabilities": sorted(BASIC_CAPABILITIES),
        "commercial_modules": sorted(modules),
        "capabilities": sorted(capabilities),
        "source": source,
        "configured": configured,
        "resolution_error": resolution_error,
        "enforcement_enabled": False,
    }


def resolve_from_subscription(client_id: str, subscription: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve direitos declarados sem alterar autorização ou bloquear rotas.

    Ausência de assinatura, lista vazia ou textos legados preservam todos os
    módulos opcionais. Uma configuração explícita usa apenas códigos canônicos.
    """
    if not subscription:
        return _result(client_id, ALL_OPTIONAL_MODULES, source="legacy_without_subscription", configured=False)
    plan = subscription.get("plan")
    if not isinstance(plan, dict):
        return _result(client_id, frozenset(), source="unavailable", configured=False,
                       resolution_error="commercial_plan_unavailable")
    features = plan.get("features") or []
    if not isinstance(features, (list, tuple, set, frozenset)):
        return _result(client_id, frozenset(), source="unavailable", configured=False,
                       resolution_error="commercial_features_invalid")
    recognized, unknown = normalize_module_keys(features)
    if not features or (not recognized and unknown and unknown.issubset(LEGACY_FEATURE_LABELS)):
        return _result(client_id, ALL_OPTIONAL_MODULES, source="legacy_plan_features", configured=False)
    if unknown:
        return _result(client_id, frozenset(), source="unavailable", configured=False,
                       resolution_error="commercial_features_unknown")
    return _result(client_id, recognized, source="subscription", configured=True)


async def resolve_tenant_modules(client_id: str) -> Dict[str, Any]:
    """Configuração explícita tem prioridade; ausência conserva comportamento legado.

    Esta função é somente declarativa: nenhuma guarda de rota ou menu a consome.
    Uma falha de leitura jamais equivale a uma configuração ausente ou irrestrita.
    """
    from .tenant_commercial_config import get_configuration
    from .saas import get_subscription
    try:
        config = await get_configuration(client_id)
        if config["configured"]:
            modules = frozenset(config["module_keys"])
            return _result(client_id, modules, source="tenant_configuration", configured=True)
        subscription = await get_subscription(client_id)
    except Exception as exc:  # noqa: BLE001 — sem enforcement, falha declarativa
        print(f"[commercial_modules] client_id={client_id} status=unavailable error_type={type(exc).__name__}")
        return _result(client_id, frozenset(), source="unavailable", configured=False,
                       resolution_error="commercial_modules_unavailable")
    return resolve_from_subscription(client_id, subscription)
