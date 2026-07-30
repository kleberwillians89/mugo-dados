-- Paid schema completion/hardening (idempotent)
-- Objetivo:
-- 1) garantir promoted_post_daily_stats
-- 2) garantir connection_id nas tabelas paid legadas
-- 3) índices/constraints mínimos para leitura por client_id + connection_id + stat_date
-- 4) manter compatibilidade com dados existentes (backfill sem destruir dados)

create extension if not exists pgcrypto;

-- =========================================================
-- promoted_post_daily_stats (boosted/promoted posts)
-- =========================================================

create table if not exists public.promoted_post_daily_stats (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid references public.meta_connections(id) on delete cascade,
  stat_date date not null,
  ad_account_id text not null,
  ad_account_name text,
  campaign_id text,
  campaign_name text,
  adset_id text,
  adset_name text,
  ad_id text not null,
  ad_name text,
  post_id text not null,
  story_id text,
  source_platform text,
  objective text,
  spend numeric(18, 6) not null default 0,
  impressions bigint not null default 0,
  reach bigint not null default 0,
  clicks bigint not null default 0,
  cpc numeric(18, 6) not null default 0,
  cpm numeric(18, 6) not null default 0,
  ctr numeric(18, 6) not null default 0,
  conversions numeric(18, 6) not null default 0,
  revenue numeric(18, 6) not null default 0,
  roas numeric(18, 6) not null default 0,
  raw_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists uq_promoted_post_daily_stats_connection
  on public.promoted_post_daily_stats(
    client_id,
    connection_id,
    ad_account_id,
    post_id,
    ad_id,
    stat_date
  );

create unique index if not exists uq_promoted_post_daily_stats_legacy
  on public.promoted_post_daily_stats(
    client_id,
    ad_account_id,
    post_id,
    ad_id,
    stat_date
  );

create index if not exists idx_promoted_post_daily_stats_client_date
  on public.promoted_post_daily_stats(client_id, stat_date desc);

create index if not exists idx_promoted_post_daily_stats_connection
  on public.promoted_post_daily_stats(connection_id, stat_date desc);

create index if not exists idx_promoted_post_daily_stats_client_connection_date
  on public.promoted_post_daily_stats(client_id, connection_id, stat_date desc);

create index if not exists idx_promoted_post_daily_stats_campaign
  on public.promoted_post_daily_stats(client_id, campaign_id, stat_date desc);

create index if not exists idx_promoted_post_daily_stats_post
  on public.promoted_post_daily_stats(client_id, post_id, stat_date desc);

alter table public.promoted_post_daily_stats enable row level security;

drop policy if exists promoted_post_daily_stats_member_select on public.promoted_post_daily_stats;
create policy promoted_post_daily_stats_member_select on public.promoted_post_daily_stats
for select using (public.is_client_member(client_id));

drop trigger if exists trg_promoted_post_daily_stats_updated_at on public.promoted_post_daily_stats;
create trigger trg_promoted_post_daily_stats_updated_at
before update on public.promoted_post_daily_stats
for each row execute function public.set_updated_at();

-- =========================================================
-- connection_id columns on legacy paid tables
-- =========================================================

alter table if exists public.ad_account_daily_stats
  add column if not exists connection_id uuid;

alter table if exists public.campaign_daily_stats
  add column if not exists connection_id uuid;

alter table if exists public.ad_daily_stats
  add column if not exists connection_id uuid;

-- FK constraints (NOT VALID para preservar compat com legado)
do $$
begin
  if to_regclass('public.ad_account_daily_stats') is not null then
    if not exists (
      select 1
      from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'ad_account_daily_stats'
        and c.contype = 'f'
        and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references public.meta_connections(id)%'
    ) then
      alter table public.ad_account_daily_stats
        add constraint fk_ad_account_daily_stats_connection_id
        foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
    end if;
  end if;

  if to_regclass('public.campaign_daily_stats') is not null then
    if not exists (
      select 1
      from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'campaign_daily_stats'
        and c.contype = 'f'
        and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references public.meta_connections(id)%'
    ) then
      alter table public.campaign_daily_stats
        add constraint fk_campaign_daily_stats_connection_id
        foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
    end if;
  end if;

  if to_regclass('public.ad_daily_stats') is not null then
    if not exists (
      select 1
      from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'ad_daily_stats'
        and c.contype = 'f'
        and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references public.meta_connections(id)%'
    ) then
      alter table public.ad_daily_stats
        add constraint fk_ad_daily_stats_connection_id
        foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
    end if;
  end if;
end $$;

-- Índices de leitura por client_id + connection_id + stat_date
create index if not exists idx_ad_account_daily_stats_client_connection_date
  on public.ad_account_daily_stats(client_id, connection_id, stat_date desc);

create index if not exists idx_campaign_daily_stats_client_connection_date
  on public.campaign_daily_stats(client_id, connection_id, stat_date desc);

create index if not exists idx_ad_daily_stats_client_connection_date
  on public.ad_daily_stats(client_id, connection_id, stat_date desc);

-- =========================================================
-- Backfill connection_id (compat com dados existentes)
-- Resolve por client_id + ad_account_id normalizado (com/sem prefixo act_)
-- =========================================================

with mapped as (
  select
    s.id as row_id,
    mc.id as resolved_connection_id,
    row_number() over (
      partition by s.id
      order by mc.updated_at desc nulls last, mc.created_at desc nulls last, mc.id desc
    ) as rn
  from public.ad_account_daily_stats s
  join public.meta_connections mc
    on mc.client_id = s.client_id
   and mc.platform = 'meta_ads'
   and mc.connection_type = 'paid'
   and regexp_replace(coalesce(mc.ad_account_id, ''), '^act_', '') = regexp_replace(coalesce(s.ad_account_id, ''), '^act_', '')
  where s.connection_id is null
)
update public.ad_account_daily_stats t
set connection_id = m.resolved_connection_id
from mapped m
where t.id = m.row_id
  and m.rn = 1;

with mapped as (
  select
    s.id as row_id,
    mc.id as resolved_connection_id,
    row_number() over (
      partition by s.id
      order by mc.updated_at desc nulls last, mc.created_at desc nulls last, mc.id desc
    ) as rn
  from public.campaign_daily_stats s
  join public.meta_connections mc
    on mc.client_id = s.client_id
   and mc.platform = 'meta_ads'
   and mc.connection_type = 'paid'
   and regexp_replace(coalesce(mc.ad_account_id, ''), '^act_', '') = regexp_replace(coalesce(s.ad_account_id, ''), '^act_', '')
  where s.connection_id is null
)
update public.campaign_daily_stats t
set connection_id = m.resolved_connection_id
from mapped m
where t.id = m.row_id
  and m.rn = 1;

with mapped as (
  select
    s.id as row_id,
    mc.id as resolved_connection_id,
    row_number() over (
      partition by s.id
      order by mc.updated_at desc nulls last, mc.created_at desc nulls last, mc.id desc
    ) as rn
  from public.ad_daily_stats s
  join public.meta_connections mc
    on mc.client_id = s.client_id
   and mc.platform = 'meta_ads'
   and mc.connection_type = 'paid'
   and regexp_replace(coalesce(mc.ad_account_id, ''), '^act_', '') = regexp_replace(coalesce(s.ad_account_id, ''), '^act_', '')
  where s.connection_id is null
)
update public.ad_daily_stats t
set connection_id = m.resolved_connection_id
from mapped m
where t.id = m.row_id
  and m.rn = 1;

with mapped as (
  select
    s.id as row_id,
    mc.id as resolved_connection_id,
    row_number() over (
      partition by s.id
      order by mc.updated_at desc nulls last, mc.created_at desc nulls last, mc.id desc
    ) as rn
  from public.promoted_post_daily_stats s
  join public.meta_connections mc
    on mc.client_id = s.client_id
   and mc.platform = 'meta_ads'
   and mc.connection_type = 'paid'
   and regexp_replace(coalesce(mc.ad_account_id, ''), '^act_', '') = regexp_replace(coalesce(s.ad_account_id, ''), '^act_', '')
  where s.connection_id is null
)
update public.promoted_post_daily_stats t
set connection_id = m.resolved_connection_id
from mapped m
where t.id = m.row_id
  and m.rn = 1;
