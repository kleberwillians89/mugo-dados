"""Publicacao controlada de rascunhos SEARCH no Google Ads.

O servico reutiliza ``studio_ad_drafts`` e a conexao OAuth tenant-scoped. A
criacao e enviada em uma unica mutacao atomica, primeiro com ``validateOnly`` e
depois em estado PAUSED. Nenhuma ativacao acontece neste fluxo.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import httpx

from .google_ads import resolve_google_ads_context
from .google_oauth import _google_ads_error_details, get_google_access_token, google_ads_api_error
from .ig_supabase import sb_update
from .integration_errors import IntegrationError
from .studio_calendar import StudioError
from . import google_ad_drafts as drafts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def readiness(payload: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not str(payload.get("final_url") or "").startswith("https://"):
        missing.append("URL final HTTPS")
    if not payload.get("keywords"):
        missing.append("ao menos uma palavra-chave")
    if len(payload.get("headlines") or []) < 3:
        missing.append("ao menos três títulos")
    if len(payload.get("descriptions") or []) < 2:
        missing.append("ao menos duas descrições")
    if not payload.get("locations"):
        missing.append("ao menos uma localização")
    try:
        if date.fromisoformat(str(payload.get("start_date") or "")) < datetime.now(timezone.utc).date():
            missing.append("data inicial igual ou posterior a hoje")
    except ValueError:
        missing.append("datas válidas")
    if payload.get("contains_eu_political_advertising") is None:
        missing.append("declaração sobre publicidade política na União Europeia")
    return missing


def _version() -> str:
    version = str(os.getenv("GOOGLE_ADS_API_VERSION") or "v25").strip()
    if not re.fullmatch(r"v\d+", version):
        raise StudioError("GOOGLE_ADS_API_VERSION_INVALID")
    return version


def _headers(access_token: str, login_customer_id: str | None) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    # Desde 09/09/2026 o Google ignora este header e usa o nivel de acesso do
    # projeto Cloud. Mantemos o envio opcional para compatibilidade transitória.
    developer_token = str(os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or "").strip()
    if developer_token:
        headers["developer-token"] = developer_token
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id
    return headers


def _google_error(response: httpx.Response, operation: str) -> StudioError:
    details = _google_ads_error_details(response)
    mapped = google_ads_api_error(response, details, operation=operation, provider="google_ads")
    error = StudioError("GOOGLE_ADS_REJECTED", mapped.public_message)
    error.diagnostics = {
        "upstream_status": response.status_code,
        "request_id": details.get("google_request_id") or None,
        "upstream_reason": ",".join(details.get("reasons") or []) or None,
    }
    return error


async def _suggest_geo_targets(
    *, http: httpx.AsyncClient, version: str, headers: Dict[str, str], names: List[str],
) -> List[str]:
    response = await http.post(
        f"https://googleads.googleapis.com/{version}/geoTargetConstants:suggest",
        headers=headers,
        json={"locale": "pt_BR", "countryCode": "BR", "locationNames": {"names": names}},
    )
    if response.status_code >= 400:
        raise _google_error(response, "validar as localizações da campanha")
    payload = response.json() if response.content else {}
    suggestions = payload.get("geoTargetConstantSuggestions") if isinstance(payload, dict) else []
    resources = [
        str((item.get("geoTargetConstant") or {}).get("resourceName") or "").strip()
        for item in (suggestions or []) if isinstance(item, dict)
    ]
    resources = list(dict.fromkeys(resource for resource in resources if resource))
    if not resources:
        raise StudioError("AD_NOT_READY", "Nenhuma localização informada foi reconhecida pelo Google Ads.")
    return resources


def _operations(customer_id: str, draft_id: str, payload: Dict[str, Any], geo_resources: List[str]) -> List[Dict[str, Any]]:
    budget = f"customers/{customer_id}/campaignBudgets/-1"
    campaign = f"customers/{customer_id}/campaigns/-2"
    ad_group = f"customers/{customer_id}/adGroups/-3"
    suffix = draft_id.replace("-", "")[-8:]
    operations: List[Dict[str, Any]] = [
        {"campaignBudgetOperation": {"create": {
            "resourceName": budget, "name": f"{payload['name']} · verba · {suffix}",
            "amountMicros": str(int(round(float(payload["daily_budget"]) * 1_000_000))),
            "deliveryMethod": "STANDARD", "explicitlyShared": False,
        }}},
        {"campaignOperation": {"create": {
            "resourceName": campaign, "name": f"{payload['name']} · {suffix}", "status": "PAUSED",
            "advertisingChannelType": "SEARCH", "campaignBudget": budget, "manualCpc": {},
            "networkSettings": {
                "targetGoogleSearch": True,
                "targetSearchNetwork": payload.get("networks", {}).get("search_partners", False),
                "targetContentNetwork": payload.get("networks", {}).get("display_network", False),
            },
            "containsEuPoliticalAdvertising": (
                "CONTAINS_EU_POLITICAL_ADVERTISING"
                if payload["contains_eu_political_advertising"] else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
            ),
            "startDate": str(payload["start_date"]).replace("-", ""),
            "endDate": str(payload["end_date"]).replace("-", ""),
        }}},
        {"adGroupOperation": {"create": {
            "resourceName": ad_group, "name": f"{payload['name']} · grupo · {suffix}",
            "campaign": campaign, "status": "PAUSED", "type": "SEARCH_STANDARD",
        }}},
    ]
    operations.extend({"campaignCriterionOperation": {"create": {
        "campaign": campaign, "location": {"geoTargetConstant": resource}, "negative": False,
    }}} for resource in geo_resources)
    operations.extend({"adGroupCriterionOperation": {"create": {
        "adGroup": ad_group, "status": "PAUSED", "keyword": {"text": keyword, "matchType": "PHRASE"},
    }}} for keyword in payload["keywords"])
    operations.append({"adGroupAdOperation": {"create": {
        "adGroup": ad_group, "status": "PAUSED", "ad": {
            "finalUrls": [payload["final_url"]],
            "responsiveSearchAd": {
                "headlines": [{"text": text} for text in payload["headlines"]],
                "descriptions": [{"text": text} for text in payload["descriptions"]],
            },
        },
    }}})
    return operations


def _external_ids(results: List[Dict[str, Any]], customer_id: str, connection_id: str) -> Dict[str, Any]:
    resources: Dict[str, str] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            if isinstance(value, dict) and value.get("resourceName"):
                resources[key] = str(value["resourceName"])
    campaign_resource = resources.get("campaignResult", "")
    return {
        "platform": "google_ads", "connection_id": connection_id, "customer_id": customer_id,
        "campaign_id": campaign_resource.rsplit("/", 1)[-1] if campaign_resource else None,
        "resources": resources,
    }


async def publication_context(client_id: str) -> Dict[str, Any]:
    context = await resolve_google_ads_context(client_id)
    return {
        "connection_id": context.connection_id,
        "account": f"•••• {context.customer_id[-4:]}",
        "customer_id_suffix": context.customer_id[-4:],
    }


async def publish(client_id: str, draft_id: str) -> Dict[str, Any]:
    row = await drafts.owned(client_id, draft_id)
    if row.get("status") == "publicada":
        return drafts.view(row)
    if row.get("status") == "publicando":
        raise StudioError("AD_PUBLICATION_IN_PROGRESS")
    payload = drafts.clean_payload(row.get("payload") or {})
    missing = readiness(payload)
    if missing:
        raise StudioError("AD_NOT_READY", "Falta: " + "; ".join(missing))

    context = await resolve_google_ads_context(client_id)
    claim = await sb_update(
        drafts.TABLE,
        filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}", "status": "in.(rascunho,erro)"},
        patch={"status": "publicando", "error": None, "updated_at": _now()},
    )
    if not claim:
        raise StudioError("AD_PUBLICATION_IN_PROGRESS")

    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"}
    stage = "preflight"
    try:
        token = await get_google_access_token(client_id, context.connection_id)
        version = _version()
        headers = _headers(token, context.login_customer_id)
        async with httpx.AsyncClient(timeout=60) as http:
            geos = await _suggest_geo_targets(
                http=http, version=version, headers=headers, names=payload["locations"],
            )
            operations = _operations(context.customer_id, draft_id, payload, geos)
            url = f"https://googleads.googleapis.com/{version}/customers/{context.customer_id}/googleAds:mutate"
            request = {"mutateOperations": operations, "partialFailure": False, "responseContentType": "RESOURCE_NAME_ONLY"}
            validation = await http.post(url, headers=headers, json={**request, "validateOnly": True})
            if validation.status_code >= 400:
                raise _google_error(validation, "validar a campanha de pesquisa")
            stage = "mutate"
            response = await http.post(url, headers=headers, json={**request, "validateOnly": False})
            if response.status_code >= 400:
                if response.status_code >= 500:
                    raise StudioError(
                        "AD_PUBLICATION_UNCERTAIN",
                        "O Google não confirmou o resultado. Verifique a conta antes de tentar novamente.",
                    )
                raise _google_error(response, "criar a campanha de pesquisa pausada")
        body = response.json() if response.content else {}
        ids = _external_ids(body.get("mutateOperationResponses") or [], context.customer_id, context.connection_id)
        if not ids.get("campaign_id"):
            raise StudioError(
                "AD_PUBLICATION_UNCERTAIN",
                "O Google criou recursos, mas não confirmou a campanha. Verifique a conta antes de tentar novamente.",
            )
        stage = "complete"
    except (StudioError, IntegrationError, httpx.RequestError) as exc:
        uncertain = stage == "mutate"
        code = str(getattr(exc, "code", "GOOGLE_ADS_PUBLICATION_FAILED"))
        if uncertain:
            code = "AD_PUBLICATION_UNCERTAIN"
        message = str(exc) if str(exc) != code else code
        await sb_update(drafts.TABLE, filters=filters, patch={
            # Resultado incerto nunca volta automaticamente a um estado que
            # aceite retry: isso evita duplicidade após timeout do mutate.
            "status": "publicando" if uncertain else "erro",
            "error": f"{code}: {message}"[:600], "updated_at": _now(),
        })
        if isinstance(exc, httpx.RequestError):
            raise StudioError(
                code,
                "O Google não confirmou o resultado. Verifique a conta antes de tentar novamente."
                if uncertain else "Não foi possível comunicar com o Google Ads.",
            ) from None
        raise
    rows = await sb_update(drafts.TABLE, filters=filters, patch={
        "status": "publicada", "meta_ids": ids, "error": None,
        "published_at": _now(), "updated_at": _now(),
    })
    print(f"[google_ads_publish] client_id={client_id} draft={draft_id} status=published")
    return drafts.view(rows[0] if rows else {**row, "status": "publicada", "meta_ids": ids})
