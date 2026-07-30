-- Meta OAuth + multi-asset connections + paid media stats
-- Compatível com schema legado existente.

create extension if not exists pgcrypto;

-- =========================================================
-- meta_connections: expande para suportar orgânico + paid
-- =========================================================

alter table public.meta_connections add column if not exists connection_type text;
alter table public.meta_connections add column if not exists meta_user_id text;
alter table public.meta_connections add column if not exists ig_user_id text;
alter table public.meta_connections add column if not exists username text;
alter table public.meta_connections add column if not exists business_id text;
alter table public.meta_connections add column if not exists ad_account_id text;
alter table public.meta_connections add column if not exists ad_account_name text;
alter table public.meta_connections add column if not exists scopes_json jsonb;
alter table public.meta_connections add column if not exists encrypted_access_token text;
alter table public.meta_connections add column if not exists token_last_refreshed_at timestamptz;
alter table public.meta_connections add column if not exists last_synced_at timestamptz;
alter table public.meta_connections add column if not exists last_error text;
alter table public.meta_connections add column if not exists connected_at timestamptz;

update public.meta_connections
set connection_type = coalesce(connection_type, 'organic')
where connection_type is null;

update public.meta_connections
set scopes_json = coalesce(scopes_json, '[]'::jsonb)
where scopes_json is null;

update public.meta_connections
set ig_user_id = coalesce(ig_user_id, '')
where ig_user_id is null;

update public.meta_connections
set ad_account_id = coalesce(ad_account_id, '')
where ad_account_id is null;

update public.meta_connections
set ad_account_name = coalesce(ad_account_name, '')
where ad_account_name is null;

update public.meta_connections
set token_last_refreshed_at = coalesce(token_last_refreshed_at, last_refresh_at)
where token_last_refreshed_at is null;

update public.meta_connections
set connected_at = coalesce(connected_at, created_at, now())
where connected_at is null;

alter table public.meta_connections
  alter column connection_type set default 'organic';

alter table public.meta_connections
  alter column connection_type set not null;

alter table public.meta_connections
  alter column ig_user_id set default '';

alter table public.meta_connections
  alter column ig_user_id set not null;

alter table public.meta_connections
  alter column ad_account_id set default '';

alter table public.meta_connections
  alter column ad_account_id set not null;

alter table public.meta_connections
  alter column ad_account_name set default '';

alter table public.meta_connections
  alter column ad_account_name set not null;

alter table public.meta_connections
  alter column scopes_json set default '[]'::jsonb;

alter table public.meta_connections
  alter column scopes_json set not null;

alter table public.meta_connections
  alter column connected_at set default now();

alter table public.meta_connections
  alter column connected_at set not null;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'meta_connections_platform_check'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_platform_check;
  end if;
end $$;

alter table public.meta_connections
  add constraint meta_connections_platform_check
  check (platform in ('instagram', 'meta_ads'));

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'meta_connections_status_check'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_status_check;
  end if;
end $$;

alter table public.meta_connections
  add constraint meta_connections_status_check
  check (status in ('active', 'needs_reauth', 'error', 'disconnected'));

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'meta_connections_client_id_platform_key'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_client_id_platform_key;
  end if;
end $$;

create unique index if not exists uq_meta_connections_asset
  on public.meta_connections (
    client_id,
    platform,
    connection_type,
    coalesce(ig_user_id, ''),
    coalesce(ad_account_id, '')
  );

create index if not exists idx_meta_connections_client_status
  on public.meta_connections(client_id, status, updated_at desc);

create index if not exists idx_meta_connections_asset_lookup
  on public.meta_connections(client_id, platform, connection_type, status);

-- =========================================================
-- Paid daily stats
-- =========================================================

create table if not exists public.ad_account_daily_stats (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid references public.meta_connections(id) on delete cascade,
  stat_date date not null,
  ad_account_id text not null,
  ad_account_name text,
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
  updated_at timestamptz not null default now(),
  unique(client_id, ad_account_id, stat_date)
);

create index if not exists idx_ad_account_daily_stats_client_date
  on public.ad_account_daily_stats(client_id, stat_date desc);
create index if not exists idx_ad_account_daily_stats_connection
  on public.ad_account_daily_stats(connection_id, stat_date desc);

create table if not exists public.campaign_daily_stats (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid references public.meta_connections(id) on delete cascade,
  stat_date date not null,
  ad_account_id text not null,
  ad_account_name text,
  campaign_id text not null,
  campaign_name text,
  campaign_status text,
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
  updated_at timestamptz not null default now(),
  unique(client_id, campaign_id, stat_date)
);

create index if not exists idx_campaign_daily_stats_client_date
  on public.campaign_daily_stats(client_id, stat_date desc);
create index if not exists idx_campaign_daily_stats_account
  on public.campaign_daily_stats(client_id, ad_account_id, stat_date desc);
create index if not exists idx_campaign_daily_stats_connection
  on public.campaign_daily_stats(connection_id, stat_date desc);

create table if not exists public.ad_daily_stats (
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
  ad_status text,
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
  updated_at timestamptz not null default now(),
  unique(client_id, ad_id, stat_date)
);

create index if not exists idx_ad_daily_stats_client_date
  on public.ad_daily_stats(client_id, stat_date desc);
create index if not exists idx_ad_daily_stats_campaign
  on public.ad_daily_stats(client_id, campaign_id, stat_date desc);
create index if not exists idx_ad_daily_stats_account
  on public.ad_daily_stats(client_id, ad_account_id, stat_date desc);
create index if not exists idx_ad_daily_stats_connection
  on public.ad_daily_stats(connection_id, stat_date desc);

drop trigger if exists trg_ad_account_daily_stats_updated_at on public.ad_account_daily_stats;
create trigger trg_ad_account_daily_stats_updated_at
before update on public.ad_account_daily_stats
for each row execute function public.set_updated_at();

drop trigger if exists trg_campaign_daily_stats_updated_at on public.campaign_daily_stats;
create trigger trg_campaign_daily_stats_updated_at
before update on public.campaign_daily_stats
for each row execute function public.set_updated_at();

drop trigger if exists trg_ad_daily_stats_updated_at on public.ad_daily_stats;
create trigger trg_ad_daily_stats_updated_at
before update on public.ad_daily_stats
for each row execute function public.set_updated_at();

-- RLS (select por membership)
alter table public.ad_account_daily_stats enable row level security;
alter table public.campaign_daily_stats enable row level security;
alter table public.ad_daily_stats enable row level security;

drop policy if exists ad_account_daily_stats_member_select on public.ad_account_daily_stats;
create policy ad_account_daily_stats_member_select on public.ad_account_daily_stats
for select using (public.is_client_member(client_id));

drop policy if exists campaign_daily_stats_member_select on public.campaign_daily_stats;
create policy campaign_daily_stats_member_select on public.campaign_daily_stats
for select using (public.is_client_member(client_id));

drop policy if exists ad_daily_stats_member_select on public.ad_daily_stats;
create policy ad_daily_stats_member_select on public.ad_daily_stats
for select using (public.is_client_member(client_id));
