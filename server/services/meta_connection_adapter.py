from __future__ import annotations

from typing import Any, Dict

from .connection_resolver import resolve_connection_for_scope, resolve_generic_connection
from .ig_supabase import sb_select
from .integration_errors import IntegrationError


def _text(value: Any) -> str:
    return str(value or "").strip()


def _metadata(row: Dict[str, Any] | None) -> Dict[str, Any]:
    value = (row or {}).get("metadata")
    return value if isinstance(value, dict) else {}


class MetaConnectionAdapter:
    """Single read policy for Meta authorization and operational projection."""

    async def resolve_authorization(self, client_id: str, connection_id: str | None = None) -> Dict[str, Any]:
        return await resolve_generic_connection(
            client_id=client_id, provider="meta",
            requested_connection_id=connection_id, require_token=True,
        )

    async def resolve_operational(
        self, client_id: str, *, capability: str, connection_id: str | None = None,
    ) -> Dict[str, Any]:
        mapping = {
            "organic": ("instagram", "organic", False),
            "paid": ("meta_ads", "paid", True),
        }
        if capability not in mapping:
            raise IntegrationError(
                "Capacidade Meta inválida.", status_code=400,
                code="CONNECTION_CAPABILITY_MISMATCH", provider="meta",
            )
        platform, connection_type, require_ad = mapping[capability]
        result = await resolve_connection_for_scope(
            client_id=client_id, platform=platform, connection_type=connection_type,
            requested_connection_id=connection_id, require_ad_account=require_ad,
        )
        if not result.get("resolved"):
            raise IntegrationError(
                "A projeção operacional Meta não está configurada.", status_code=409,
                code="CONNECTION_ASSET_REQUIRED", provider="meta",
            )
        return dict(result.get("row") or {})

    async def detect_drift(self, client_id: str) -> Dict[str, Any]:
        authorizations = await sb_select(
            "integration_connections",
            filters={"client_id": f"eq.{_text(client_id)}", "provider": "eq.meta"},
            order="updated_at.desc", limit=200,
        )
        projections = await sb_select(
            "meta_connections",
            filters={"client_id": f"eq.{_text(client_id)}"},
            order="updated_at.desc", limit=500,
        )
        active_auth = [r for r in authorizations if _text(r.get("status")).lower() in {"connected", "selection_required"} and not _text(r.get("disconnected_at"))]
        active_projection = [r for r in projections if _text(r.get("status")).lower() in {"active", "connected", "ok"} and r.get("is_active") is not False]
        issues: list[Dict[str, Any]] = []
        if len(active_auth) > 1:
            issues.append({"code": "META_CONNECTION_DRIFT", "reason": "multiple_active_authorizations", "count": len(active_auth)})
        if active_projection and not active_auth:
            issues.append({"code": "META_CONNECTION_DRIFT", "reason": "projection_without_authorization", "count": len(active_projection)})
        if active_auth and not active_projection:
            issues.append({"code": "META_CONNECTION_DRIFT", "reason": "authorization_without_projection", "count": len(active_auth)})
        organic = [r for r in active_projection if _text(r.get("platform")).lower() == "instagram"]
        paid = [r for r in active_projection if _text(r.get("platform")).lower() == "meta_ads"]
        if len(organic) > 1:
            issues.append({"code": "META_CONNECTION_DRIFT", "reason": "multiple_active_organic", "count": len(organic)})
        if len(paid) > 1:
            issues.append({"code": "META_CONNECTION_DRIFT", "reason": "multiple_active_paid", "count": len(paid)})
        if len(active_auth) == 1:
            meta = _metadata(active_auth[0])
            comparisons = (
                ("selected_instagram_id", organic, "ig_user_id"),
                ("selected_page_id", organic, "business_id"),
                ("selected_ad_account_id", paid, "ad_account_id"),
            )
            for field, rows, projection_field in comparisons:
                expected = _text(meta.get(field))
                actual = {_text(row.get(projection_field)) for row in rows if _text(row.get(projection_field))}
                if expected and actual and expected not in actual:
                    issues.append({"code": "META_CONNECTION_DRIFT", "reason": f"{field}_mismatch"})
            if not _text(active_auth[0].get("encrypted_token")):
                issues.append({"code": "META_CONNECTION_DRIFT", "reason": "authorization_token_unavailable"})
        return {
            "client_id": _text(client_id), "drift_detected": bool(issues),
            "issues": issues, "authorization_count": len(active_auth),
            "operational_count": len(active_projection),
        }

    async def health(self, client_id: str) -> Dict[str, Any]:
        drift = await self.detect_drift(client_id)
        if drift["drift_detected"]:
            return {**drift, "status": "drift", "code": "META_CONNECTION_DRIFT"}
        return {**drift, "status": "connected" if drift["authorization_count"] else "not_connected", "code": None}


meta_connection_adapter = MetaConnectionAdapter()
