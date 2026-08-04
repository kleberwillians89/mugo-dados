from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .audit_supabase import ReadOnlySupabase

LOCK_MIGRATION = "20260305_000001_multi_tenant_and_features.sql"


def _source_checks(migrations_dir: Path) -> Dict[str, bool]:
    canonical = (migrations_dir / LOCK_MIGRATION).read_text(encoding="utf-8").lower()
    source = "\n".join(path.read_text(encoding="utf-8").lower() for path in sorted(migrations_dir.glob("*.sql")))
    return {
        "cron_locks_table": "create table if not exists public.cron_locks" in canonical,
        "cron_job_runs_table": "create table if not exists public.cron_job_runs" in source,
        "cron_locks_unique_constraint": "unique(client_id,job_name)" in canonical.replace(" ", ""),
        "cron_job_runs_client_index": "idx_cron_job_runs_client_started" in source,
        "cron_job_runs_connection_index": "idx_cron_job_runs_connection_started" in source,
        "acquire_rpc": "function public.acquire_client_job_lock" in canonical,
        "release_rpc": "function public.release_client_job_lock" in canonical,
        "lock_expiration": "locked_until < v_now" in canonical,
        "minimum_ttl": "greatest(30, p_ttl_seconds)" in canonical,
        "explicit_release": "locked_until = now() - interval '1 second'" in canonical,
    }


def remediation_sql() -> str:
    return """-- REVIEW ONLY. Generated but never applied by the audit.\n
create table if not exists public.cron_locks (
  id bigserial primary key,
  client_id text not null,
  job_name text not null,
  locked_until timestamptz not null,
  updated_at timestamptz not null default now(),
  unique(client_id, job_name)
);

create or replace function public.acquire_client_job_lock(
  p_client_id text, p_job_name text, p_ttl_seconds integer default 1200
) returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_now timestamptz := now();
begin
  insert into public.cron_locks(client_id, job_name, locked_until, updated_at)
  values (p_client_id, p_job_name, v_now + make_interval(secs => greatest(30, p_ttl_seconds)), v_now)
  on conflict (client_id, job_name) do update
    set locked_until = excluded.locked_until, updated_at = excluded.updated_at
    where public.cron_locks.locked_until < v_now;
  return exists (
    select 1 from public.cron_locks
    where client_id = p_client_id and job_name = p_job_name
      and locked_until >= v_now and updated_at = v_now
  );
end $$;

create or replace function public.release_client_job_lock(
  p_client_id text, p_job_name text
) returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.cron_locks
  set locked_until = now() - interval '1 second', updated_at = now()
  where client_id = p_client_id and job_name = p_job_name;
  return true;
end $$;
"""


async def inspect_lock_infrastructure(client: ReadOnlySupabase, migrations_dir: Path) -> Dict[str, Any]:
    openapi = await client.openapi()
    paths = set((openapi.get("paths") or {}).keys()) if isinstance(openapi.get("paths"), dict) else set()
    resources = {
        "cron_locks": "/cron_locks" in paths,
        "cron_job_runs": "/cron_job_runs" in paths,
        "acquire_client_job_lock": "/rpc/acquire_client_job_lock" in paths,
        "release_client_job_lock": "/rpc/release_client_job_lock" in paths,
    }
    permissions: Dict[str, str] = {}
    for table in ("cron_locks", "cron_job_runs"):
        try:
            await client.select(table, select="client_id", limit=1)
            permissions[table] = "select_allowed"
        except Exception as exc:
            permissions[table] = f"select_denied:{exc.__class__.__name__}"
    source = _source_checks(migrations_dir)
    missing = [name for name, available in resources.items() if not available]
    source_missing = [name for name, available in source.items() if not available]
    client.assert_read_only()
    return {
        "ok": not missing and not source_missing and all(value == "select_allowed" for value in permissions.values()),
        "read_only": True,
        "production_catalog": resources,
        "select_permissions": permissions,
        "repository_contract": source,
        "missing": missing,
        "source_missing": source_missing,
        "rpc_execution_not_invoked": True,
        "rpc_permission_evidence": "OpenAPI visibility only; mutation was intentionally not invoked.",
        "failure_release_evidence": "Repository SQL uses explicit release and TTL; runtime concurrency test covers release after failure.",
    }
