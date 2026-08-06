"""
Auditoria SOMENTE LEITURA de produção para o cliente "amalie" (Etapa 1).

O que faz:
  - Consulta cron_locks e cron_job_runs do client_id informado.
  - Consulta meta_connections das conexões operacionais informadas.
  - Consulta integration_connections da autorização Meta informada.
  - Conta linhas e intervalo de datas (min/max) das tabelas de dados por
    integração (Instagram orgânico, Meta Ads, GA4).
  - Calcula, por fonte: última sincronização (last_sync_at) x última data
    de dado disponível (max stat_date / max timestamp) x jobs em execução
    ou travados.

O que NUNCA faz:
  - Nenhum INSERT, UPDATE, DELETE ou RPC de mutação.
  - Não chama acquire_client_job_lock / release_client_job_lock / finish_job_run.
  - Não altera nenhuma conexão, lock ou job.
  - Não imprime tokens, secrets, chaves ou headers de autorização — apenas
    metadados operacionais (datas, status, contagens, ids).

Variáveis de ambiente usadas (lidas via server/.env, sem sobrescrever o
ambiente do processo — mesmo carregador que o backend usa em produção):
  - SUPABASE_URL
  - SUPABASE_SERVICE_ROLE_KEY

Uso:
  cd server
  python3 scripts/audit_amalie_diagnostics.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from services.env_loader import ensure_env_loaded  # noqa: E402
import os  # noqa: E402

ensure_env_loaded()

CLIENT_ID = "amalie"
META_ADS_CONNECTION_ID = "b838a254-fb96-4c04-b7b9-bbc4ae9092e6"
IG_ORGANIC_CONNECTION_ID = "00bb094c-337a-49b3-b2bc-5aec75d79da5"
META_AUTHORIZATION_CONNECTION_ID = "0f0020ab-8853-4a75-8fb4-41fbe1a439a7"

# Fragmentos de nome de coluna que jamais devem ser impressos, mesmo que
# apareçam em alguma tabela consultada. Substring, não igualdade exata —
# uma coluna como "encrypted_token" ou "state_secret" deve ser pega mesmo
# sem estar listada literalmente.
_FORBIDDEN_KEY_FRAGMENTS = (
    "token",
    "authorization",
    "apikey",
    "api_key",
    "secret",
    "password",
    "credential",
)


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS)


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _base_url() -> str:
    return _env("SUPABASE_URL").rstrip("/") + "/rest/v1"


def _supabase_headers(api_key: str) -> Dict[str, str]:
    """
    Monta os headers do Supabase suportando os dois formatos de chave:

    - legada (JWT, prefixo "eyJ"): apikey + Authorization: Bearer <chave>
    - nova secret key (prefixo "sb_secret_"): somente apikey, sem
      Authorization: Bearer — enviar Bearer com esse formato retorna 401.

    Rejeita chave vazia, publishable key e qualquer formato não reconhecido.
    """
    key = str(api_key or "").strip()

    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY está vazia.")

    if key.startswith("sb_publishable_"):
        raise RuntimeError(
            "Foi informada uma publishable key. Use a secret key ou service_role."
        )

    headers = {
        "apikey": key,
        "Accept": "application/json",
    }

    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
        print("[audit][supabase_key_type] legacy_service_role_jwt")
    elif key.startswith("sb_secret_"):
        print("[audit][supabase_key_type] new_secret_key")
    else:
        raise RuntimeError(
            "Formato de SUPABASE_SERVICE_ROLE_KEY não reconhecido."
        )

    return headers


def _headers() -> Dict[str, str]:
    return _supabase_headers(_env("SUPABASE_SERVICE_ROLE_KEY"))


def _safe_error_body(exc: "httpx.HTTPStatusError") -> None:
    method = exc.request.method if exc.request is not None else "-"
    path = exc.request.url.path if exc.request is not None else "-"
    status = exc.response.status_code if exc.response is not None else "-"
    body = ""
    if exc.response is not None:
        try:
            body = (exc.response.text or "")[:500]
        except Exception:
            body = "<unreadable>"
    print(f"[audit][supabase_error] method={method} path={path} status={status} body={body}")


def _scrub(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: ("<redacted>" if _is_forbidden_key(k) else v) for k, v in row.items()}


async def _get(
    client: httpx.AsyncClient,
    table: str,
    *,
    params: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Somente GET contra PostgREST. Nenhum outro verbo é usado neste script."""
    url = f"{_base_url()}/{table}"
    resp = await client.get(url, headers=_headers(), params=params, timeout=30)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _safe_error_body(exc)
        raise
    data = resp.json()
    return data if isinstance(data, list) else []


async def _count_and_range(
    client: httpx.AsyncClient,
    table: str,
    *,
    client_id_column: str,
    client_id_value: str,
    date_column: str,
    extra_filters: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    filters = {client_id_column: f"eq.{client_id_value}"}
    if extra_filters:
        filters.update(extra_filters)

    count_resp = await client.get(
        f"{_base_url()}/{table}",
        headers={**_headers(), "Prefer": "count=exact"},
        params={**filters, "select": "id", "limit": "1"},
        timeout=30,
    )
    try:
        count_resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _safe_error_body(exc)
        raise
    content_range = count_resp.headers.get("content-range", "")
    total = int(content_range.split("/")[-1]) if "/" in content_range else None

    min_rows = await client.get(
        f"{_base_url()}/{table}",
        headers=_headers(),
        params={**filters, "select": date_column, "order": f"{date_column}.asc.nullslast", "limit": "1"},
        timeout=30,
    )
    try:
        min_rows.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _safe_error_body(exc)
        raise
    min_data = min_rows.json()
    earliest = min_data[0].get(date_column) if min_data else None

    max_rows = await client.get(
        f"{_base_url()}/{table}",
        headers=_headers(),
        params={**filters, "select": date_column, "order": f"{date_column}.desc.nullslast", "limit": "1"},
        timeout=30,
    )
    try:
        max_rows.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _safe_error_body(exc)
        raise
    max_data = max_rows.json()
    latest = max_data[0].get(date_column) if max_data else None

    return {"table": table, "row_count": total, "earliest": earliest, "latest": latest}


async def main() -> None:
    if not _env("SUPABASE_URL") or not _env("SUPABASE_SERVICE_ROLE_KEY"):
        print("ERRO: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY ausentes no ambiente/`.env`.")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    report: Dict[str, Any] = {"generated_at": now.isoformat(), "client_id": CLIENT_ID}

    async with httpx.AsyncClient() as client:
        # 1) cron_locks da empresa amalie
        locks = await _get(
            client, "cron_locks",
            params={"client_id": f"eq.{CLIENT_ID}", "order": "locked_until.desc", "limit": "50"},
        )
        report["cron_locks"] = [_scrub(r) for r in locks]
        report["cron_locks_still_valid"] = [
            _scrub(r) for r in locks
            if r.get("locked_until") and r["locked_until"] > now.isoformat()
        ]

        # 2) cron_job_runs recentes (empresa amalie)
        job_runs = await _get(
            client, "cron_job_runs",
            params={"client_id": f"eq.{CLIENT_ID}", "order": "started_at.desc", "limit": "50"},
        )
        report["cron_job_runs_recent"] = [_scrub(r) for r in job_runs]
        report["cron_job_runs_running"] = [_scrub(r) for r in job_runs if r.get("status") == "running"]
        # Jobs "running" cujo started_at é antigo (>2h) e nunca ganharam finished_at:
        # candidato forte a job interrompido sem liberar lock/estado.
        stuck_runs = []
        for r in job_runs:
            if r.get("status") != "running" or r.get("finished_at"):
                continue
            started_raw = str(r.get("started_at") or "")
            try:
                started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
                age_hours = (now - started).total_seconds() / 3600
            except ValueError:
                age_hours = None
            if age_hours is None or age_hours > 2:
                stuck_runs.append({**_scrub(r), "age_hours": round(age_hours, 2) if age_hours is not None else None})
        report["cron_job_runs_stuck_candidates"] = stuck_runs

        # 3) meta_connections operacionais (IG orgânico + Meta Ads)
        meta_conn_rows = await _get(
            client, "meta_connections",
            params={"id": f"in.({IG_ORGANIC_CONNECTION_ID},{META_ADS_CONNECTION_ID})"},
        )
        report["meta_connections"] = [_scrub(r) for r in meta_conn_rows]

        # 4) integration_connections da autorização Meta
        integ_conn_rows = await _get(
            client, "integration_connections",
            params={"id": f"eq.{META_AUTHORIZATION_CONNECTION_ID}"},
        )
        report["integration_connections_authorization"] = [_scrub(r) for r in integ_conn_rows]

        # 5) Cobertura de dados por tabela
        coverage_specs = [
            ("ig_profile_snapshots", "client_id", CLIENT_ID, "snapshot_date", None),
            ("ig_media", "client_id", CLIENT_ID, "timestamp", None),
            ("ig_comments", "client_id", CLIENT_ID, "timestamp", None),
            ("ad_account_daily_stats", "client_id", CLIENT_ID, "stat_date", None),
            ("ad_daily_stats", "client_id", CLIENT_ID, "stat_date", None),
            ("promoted_post_daily_stats", "client_id", CLIENT_ID, "stat_date", None),
            ("ga4_daily_stats", "client_id", CLIENT_ID, "stat_date", None),
            ("ga4_channel_stats", "client_id", CLIENT_ID, "stat_date", None),
            ("ga4_campaign_stats", "client_id", CLIENT_ID, "stat_date", None),
            ("ga4_event_stats", "client_id", CLIENT_ID, "stat_date", None),
        ]
        coverage = []
        for table, col, val, date_col, extra in coverage_specs:
            try:
                coverage.append(await _count_and_range(client, table, client_id_column=col, client_id_value=val, date_column=date_col, extra_filters=extra))
            except httpx.HTTPStatusError as exc:
                coverage.append({"table": table, "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"})
        report["data_coverage"] = coverage

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.HTTPStatusError:
        # Já reportado de forma segura por _safe_error_body / _get / _count_and_range.
        sys.exit(1)
    except RuntimeError as exc:
        print(f"ERRO: {exc}")
        sys.exit(1)
