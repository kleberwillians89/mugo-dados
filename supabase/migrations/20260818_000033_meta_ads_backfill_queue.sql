-- Durable Meta Ads backfill queue. The API only enqueues; a Render cron claims
-- one slice atomically. Browser roles receive no table or RPC privileges.
create table if not exists public.meta_ads_backfill_jobs (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  connection_id uuid not null references public.meta_connections(id) on delete cascade,
  requested_since date not null,
  requested_until date not null,
  status text not null default 'queued' check (status in ('queued','running','waiting','needs_review','success','error')),
  total_slices integer not null,
  completed_slices integer not null default 0,
  skipped_slices integer not null default 0,
  failed_slice date,
  rows_upserted integer not null default 0,
  actual_first_date date,
  actual_last_date date,
  error text,
  summary_json jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  check (requested_since <= requested_until)
);

create table if not exists public.meta_ads_backfill_slices (
  id uuid primary key default gen_random_uuid(),
  backfill_job_id uuid not null references public.meta_ads_backfill_jobs(id) on delete cascade,
  slice_index integer not null,
  slice_since date not null,
  slice_until date not null,
  status text not null default 'pending' check (status in ('pending','running','waiting','success','skipped','needs_review','error')),
  attempts integer not null default 0,
  next_attempt_at timestamptz not null default now(),
  rows_upserted integer not null default 0,
  reconciliation_json jsonb not null default '{}'::jsonb,
  error text,
  started_at timestamptz,
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  unique(backfill_job_id, slice_index),
  unique(backfill_job_id, slice_since, slice_until),
  check (slice_since <= slice_until)
);

create unique index if not exists uq_meta_ads_backfill_active_connection
  on public.meta_ads_backfill_jobs(connection_id)
  where status in ('queued','running','waiting');
create index if not exists idx_meta_ads_backfill_slices_claim
  on public.meta_ads_backfill_slices(status,next_attempt_at,slice_index);

alter table public.meta_ads_backfill_jobs enable row level security;
alter table public.meta_ads_backfill_slices enable row level security;
revoke all on public.meta_ads_backfill_jobs from anon, authenticated;
revoke all on public.meta_ads_backfill_slices from anon, authenticated;
grant all on public.meta_ads_backfill_jobs to service_role;
grant all on public.meta_ads_backfill_slices to service_role;

create or replace function public.claim_meta_ads_backfill_slice(p_stale_minutes integer default 75)
returns setof public.meta_ads_backfill_slices
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare v_slice public.meta_ads_backfill_slices;
begin
  update public.meta_ads_backfill_slices
     set status='pending', error='Worker interrompido; slice retomado.', updated_at=now(), next_attempt_at=now()
   where status='running' and updated_at < now() - make_interval(mins => greatest(p_stale_minutes, 15));

  select s.* into v_slice
    from public.meta_ads_backfill_slices s
    join public.meta_ads_backfill_jobs j on j.id=s.backfill_job_id
   where s.status in ('pending','waiting') and s.next_attempt_at <= now()
     and j.status in ('queued','running','waiting')
     and not exists (
       select 1 from public.meta_ads_backfill_slices earlier
       where earlier.backfill_job_id=s.backfill_job_id
         and earlier.slice_index < s.slice_index
         and earlier.status not in ('success','skipped')
     )
   order by j.created_at, s.slice_index
   for update of s skip locked limit 1;
  if not found then return; end if;

  update public.meta_ads_backfill_slices set status='running', attempts=attempts+1,
    started_at=coalesce(started_at,now()), updated_at=now(), error=null where id=v_slice.id returning * into v_slice;
  update public.meta_ads_backfill_jobs set status='running', started_at=coalesce(started_at,now()), updated_at=now() where id=v_slice.backfill_job_id;
  return next v_slice;
end $$;

revoke all on function public.claim_meta_ads_backfill_slice(integer) from public, anon, authenticated;
grant execute on function public.claim_meta_ads_backfill_slice(integer) to service_role;
