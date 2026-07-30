-- Meta Ads operational hardening:
-- - richer connection lifecycle fields
-- - cron/job observability table

create extension if not exists pgcrypto;

alter table public.meta_connections
  add column if not exists token_expires_at timestamptz;

alter table public.meta_connections
  add column if not exists last_validated_at timestamptz;

alter table public.meta_connections
  add column if not exists last_sync_at timestamptz;

alter table public.meta_connections
  add column if not exists last_sync_status text;

alter table public.meta_connections
  add column if not exists requires_reauth boolean;

alter table public.meta_connections
  add column if not exists is_active boolean;

update public.meta_connections
set token_expires_at = coalesce(token_expires_at, expires_at)
where token_expires_at is null;

update public.meta_connections
set last_sync_at = coalesce(last_sync_at, last_synced_at)
where last_sync_at is null;

update public.meta_connections
set requires_reauth = coalesce(requires_reauth, status = 'needs_reauth')
where requires_reauth is null;

update public.meta_connections
set is_active = coalesce(is_active, status <> 'disconnected')
where is_active is null;

update public.meta_connections
set last_sync_status = coalesce(
  last_sync_status,
  case
    when coalesce(last_sync_at, last_synced_at) is not null and status = 'active' then 'success'
    when status in ('error', 'needs_reauth') then 'error'
    else 'never'
  end
)
where last_sync_status is null;

alter table public.meta_connections
  alter column last_sync_status set default 'never';

alter table public.meta_connections
  alter column last_sync_status set not null;

alter table public.meta_connections
  alter column requires_reauth set default false;

alter table public.meta_connections
  alter column requires_reauth set not null;

alter table public.meta_connections
  alter column is_active set default true;

alter table public.meta_connections
  alter column is_active set not null;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'meta_connections_last_sync_status_check'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_last_sync_status_check;
  end if;
end $$;

alter table public.meta_connections
  add constraint meta_connections_last_sync_status_check
  check (last_sync_status in ('never', 'success', 'error', 'partial', 'skipped'));

create index if not exists idx_meta_connections_token_expires_at
  on public.meta_connections(token_expires_at);

create index if not exists idx_meta_connections_operational_status
  on public.meta_connections(client_id, platform, connection_type, is_active, requires_reauth, updated_at desc);

create table if not exists public.cron_job_runs (
  id uuid primary key default gen_random_uuid(),
  job_name text not null,
  client_id text,
  connection_id uuid references public.meta_connections(id) on delete set null,
  ad_account_id text,
  trigger_source text not null default 'cron',
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running',
  rows_upserted integer not null default 0,
  error text,
  payload_json jsonb not null default '{}'::jsonb
);

create index if not exists idx_cron_job_runs_started_at
  on public.cron_job_runs(started_at desc);

create index if not exists idx_cron_job_runs_client_started
  on public.cron_job_runs(client_id, started_at desc);

create index if not exists idx_cron_job_runs_connection_started
  on public.cron_job_runs(connection_id, started_at desc);

create index if not exists idx_cron_job_runs_job_started
  on public.cron_job_runs(job_name, started_at desc);

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'cron_job_runs_status_check'
      and conrelid = 'public.cron_job_runs'::regclass
  ) then
    alter table public.cron_job_runs drop constraint cron_job_runs_status_check;
  end if;
end $$;

alter table public.cron_job_runs
  add constraint cron_job_runs_status_check
  check (status in ('running', 'success', 'error', 'partial', 'skipped'));
