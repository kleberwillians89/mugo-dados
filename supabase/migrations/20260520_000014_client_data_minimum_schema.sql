-- cliente local minimum schema for GA4 + Meta Ads.
-- Safe to paste in Supabase SQL Editor. It is intentionally idempotent.

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.clients (
  id text primary key default gen_random_uuid()::text,
  name text not null,
  slug text,
  ig_user_id text,
  ig_access_token text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.clients add column if not exists slug text;
alter table public.clients add column if not exists ig_user_id text;
alter table public.clients add column if not exists ig_access_token text;
alter table public.clients add column if not exists created_at timestamptz not null default now();
alter table public.clients add column if not exists updated_at timestamptz not null default now();

insert into public.clients (id, name, slug)
values ('9cd90217-ccba-4467-a095-eedc21fe6e86', 'cliente', 'client')
on conflict (id) do update
set name = excluded.name,
    slug = excluded.slug,
    updated_at = now();

create unique index if not exists uq_clients_slug
  on public.clients(slug)
  where slug is not null;

drop trigger if exists trg_clients_updated_at on public.clients;
create trigger trg_clients_updated_at
before update on public.clients
for each row execute function public.set_updated_at();

create table if not exists public.meta_connections (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  platform text not null default 'instagram',
  connection_type text not null default 'organic',
  access_token text,
  encrypted_access_token text,
  meta_user_id text,
  ig_user_id text not null default '',
  username text not null default '',
  business_id text not null default '',
  ad_account_id text not null default '',
  ad_account_name text not null default '',
  scopes_json jsonb not null default '[]'::jsonb,
  expires_at timestamptz,
  token_expires_at timestamptz,
  last_refresh_at timestamptz,
  token_last_refreshed_at timestamptz,
  last_validated_at timestamptz,
  last_sync_at timestamptz,
  last_synced_at timestamptz,
  last_sync_status text not null default 'never',
  last_error text,
  requires_reauth boolean not null default false,
  is_active boolean not null default true,
  status text not null default 'active',
  connected_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.meta_connections add column if not exists access_token text;
alter table public.meta_connections add column if not exists encrypted_access_token text;
alter table public.meta_connections add column if not exists connection_type text not null default 'organic';
alter table public.meta_connections add column if not exists meta_user_id text;
alter table public.meta_connections add column if not exists ig_user_id text not null default '';
alter table public.meta_connections add column if not exists username text not null default '';
alter table public.meta_connections add column if not exists business_id text not null default '';
alter table public.meta_connections add column if not exists ad_account_id text not null default '';
alter table public.meta_connections add column if not exists ad_account_name text not null default '';
alter table public.meta_connections add column if not exists scopes_json jsonb not null default '[]'::jsonb;
alter table public.meta_connections add column if not exists expires_at timestamptz;
alter table public.meta_connections add column if not exists token_expires_at timestamptz;
alter table public.meta_connections add column if not exists last_refresh_at timestamptz;
alter table public.meta_connections add column if not exists token_last_refreshed_at timestamptz;
alter table public.meta_connections add column if not exists last_validated_at timestamptz;
alter table public.meta_connections add column if not exists last_sync_at timestamptz;
alter table public.meta_connections add column if not exists last_synced_at timestamptz;
alter table public.meta_connections add column if not exists last_sync_status text not null default 'never';
alter table public.meta_connections add column if not exists last_error text;
alter table public.meta_connections add column if not exists requires_reauth boolean not null default false;
alter table public.meta_connections add column if not exists is_active boolean not null default true;
alter table public.meta_connections add column if not exists status text not null default 'active';
alter table public.meta_connections add column if not exists connected_at timestamptz not null default now();
alter table public.meta_connections add column if not exists created_at timestamptz not null default now();
alter table public.meta_connections add column if not exists updated_at timestamptz not null default now();
alter table public.meta_connections alter column access_token drop not null;

do $$
begin
  if exists (
    select 1 from pg_constraint
    where conname = 'meta_connections_platform_check'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_platform_check;
  end if;
  if exists (
    select 1 from pg_constraint
    where conname = 'meta_connections_status_check'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_status_check;
  end if;
  if exists (
    select 1 from pg_constraint
    where conname = 'meta_connections_last_sync_status_check'
      and conrelid = 'public.meta_connections'::regclass
  ) then
    alter table public.meta_connections drop constraint meta_connections_last_sync_status_check;
  end if;
end $$;

alter table public.meta_connections
  add constraint meta_connections_platform_check
  check (platform in ('instagram', 'meta_ads'));

alter table public.meta_connections
  add constraint meta_connections_status_check
  check (status in ('active', 'needs_reauth', 'error', 'disconnected'));

alter table public.meta_connections
  add constraint meta_connections_last_sync_status_check
  check (last_sync_status in ('never', 'success', 'error', 'partial', 'skipped'));

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

create index if not exists idx_meta_connections_operational_status
  on public.meta_connections(client_id, platform, connection_type, is_active, requires_reauth, updated_at desc);

drop trigger if exists trg_meta_connections_updated_at on public.meta_connections;
create trigger trg_meta_connections_updated_at
before update on public.meta_connections
for each row execute function public.set_updated_at();

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

alter table public.cron_job_runs add column if not exists ad_account_id text;
alter table public.cron_job_runs add column if not exists trigger_source text not null default 'cron';
alter table public.cron_job_runs add column if not exists payload_json jsonb not null default '{}'::jsonb;

do $$
begin
  if exists (
    select 1 from pg_constraint
    where conname = 'cron_job_runs_status_check'
      and conrelid = 'public.cron_job_runs'::regclass
  ) then
    alter table public.cron_job_runs drop constraint cron_job_runs_status_check;
  end if;
end $$;

alter table public.cron_job_runs
  add constraint cron_job_runs_status_check
  check (status in ('running', 'success', 'error', 'partial', 'skipped'));

create index if not exists idx_cron_job_runs_started_at
  on public.cron_job_runs(started_at desc);
create index if not exists idx_cron_job_runs_client_started
  on public.cron_job_runs(client_id, started_at desc);
create index if not exists idx_cron_job_runs_connection_started
  on public.cron_job_runs(connection_id, started_at desc);

create table if not exists public.ga4_daily_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  property_id text not null,
  stat_date date not null,
  sessions integer not null default 0,
  active_users integer not null default 0,
  total_users integer not null default 0,
  event_count integer not null default 0,
  ecommerce_purchases integer not null default 0,
  purchase_revenue numeric(18, 2) not null default 0,
  total_revenue numeric(18, 2) not null default 0,
  view_item_count integer not null default 0,
  add_to_cart_count integer not null default 0,
  begin_checkout_count integer not null default 0,
  purchase_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, property_id, stat_date)
);

create index if not exists idx_ga4_daily_stats_client_date
  on public.ga4_daily_stats(client_id, stat_date desc);
create index if not exists idx_ga4_daily_stats_property_date
  on public.ga4_daily_stats(property_id, stat_date desc);

create table if not exists public.ga4_channel_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  property_id text not null,
  stat_date date not null,
  source_medium text not null,
  source text,
  medium text,
  sessions integer not null default 0,
  active_users integer not null default 0,
  total_users integer not null default 0,
  event_count integer not null default 0,
  ecommerce_purchases integer not null default 0,
  purchase_revenue numeric(18, 2) not null default 0,
  total_revenue numeric(18, 2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, property_id, stat_date, source_medium)
);

create index if not exists idx_ga4_channel_stats_client_date
  on public.ga4_channel_stats(client_id, stat_date desc);
create index if not exists idx_ga4_channel_stats_source_medium
  on public.ga4_channel_stats(client_id, source_medium, stat_date desc);

create table if not exists public.ga4_campaign_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  property_id text not null,
  stat_date date not null,
  campaign_name text not null,
  source_medium text not null default '',
  source text,
  medium text,
  sessions integer not null default 0,
  active_users integer not null default 0,
  total_users integer not null default 0,
  event_count integer not null default 0,
  ecommerce_purchases integer not null default 0,
  purchase_revenue numeric(18, 2) not null default 0,
  total_revenue numeric(18, 2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, property_id, stat_date, campaign_name, source_medium)
);

create index if not exists idx_ga4_campaign_stats_client_date
  on public.ga4_campaign_stats(client_id, stat_date desc);
create index if not exists idx_ga4_campaign_stats_campaign
  on public.ga4_campaign_stats(client_id, campaign_name, stat_date desc);

create table if not exists public.ga4_event_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  property_id text not null,
  stat_date date not null,
  event_name text not null,
  event_count integer not null default 0,
  total_users integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, property_id, stat_date, event_name)
);

create index if not exists idx_ga4_event_stats_client_date
  on public.ga4_event_stats(client_id, stat_date desc);
create index if not exists idx_ga4_event_stats_event
  on public.ga4_event_stats(client_id, event_name, stat_date desc);

drop trigger if exists trg_ga4_daily_stats_updated_at on public.ga4_daily_stats;
create trigger trg_ga4_daily_stats_updated_at
before update on public.ga4_daily_stats
for each row execute function public.set_updated_at();
drop trigger if exists trg_ga4_channel_stats_updated_at on public.ga4_channel_stats;
create trigger trg_ga4_channel_stats_updated_at
before update on public.ga4_channel_stats
for each row execute function public.set_updated_at();
drop trigger if exists trg_ga4_campaign_stats_updated_at on public.ga4_campaign_stats;
create trigger trg_ga4_campaign_stats_updated_at
before update on public.ga4_campaign_stats
for each row execute function public.set_updated_at();
drop trigger if exists trg_ga4_event_stats_updated_at on public.ga4_event_stats;
create trigger trg_ga4_event_stats_updated_at
before update on public.ga4_event_stats
for each row execute function public.set_updated_at();

create table if not exists public.ad_account_daily_stats (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid references public.meta_connections(id) on delete cascade,
  meta_connection_id uuid,
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
  updated_at timestamptz not null default now()
);

alter table public.ad_account_daily_stats add column if not exists connection_id uuid;
alter table public.ad_account_daily_stats add column if not exists meta_connection_id uuid;
alter table public.ad_account_daily_stats add column if not exists ad_account_name text;
alter table public.ad_account_daily_stats add column if not exists spend numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists impressions bigint default 0;
alter table public.ad_account_daily_stats add column if not exists reach bigint default 0;
alter table public.ad_account_daily_stats add column if not exists clicks bigint default 0;
alter table public.ad_account_daily_stats add column if not exists cpc numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists cpm numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists ctr numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists conversions numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists revenue numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists roas numeric(18, 6) default 0;
alter table public.ad_account_daily_stats add column if not exists raw_json jsonb default '{}'::jsonb;
alter table public.ad_account_daily_stats add column if not exists updated_at timestamptz default now();

create unique index if not exists uq_ad_account_daily_stats_client_account_date
  on public.ad_account_daily_stats(client_id, ad_account_id, stat_date);
create unique index if not exists uq_ad_account_daily_stats_client_connection_account_date
  on public.ad_account_daily_stats(client_id, connection_id, ad_account_id, stat_date);
create unique index if not exists uq_ad_account_daily_stats_client_meta_connection_account_date
  on public.ad_account_daily_stats(client_id, meta_connection_id, ad_account_id, stat_date);
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
  updated_at timestamptz not null default now()
);

alter table public.campaign_daily_stats add column if not exists connection_id uuid;
alter table public.campaign_daily_stats add column if not exists ad_account_name text;
alter table public.campaign_daily_stats add column if not exists campaign_name text;
alter table public.campaign_daily_stats add column if not exists campaign_status text;
alter table public.campaign_daily_stats add column if not exists objective text;
alter table public.campaign_daily_stats add column if not exists spend numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists impressions bigint default 0;
alter table public.campaign_daily_stats add column if not exists reach bigint default 0;
alter table public.campaign_daily_stats add column if not exists clicks bigint default 0;
alter table public.campaign_daily_stats add column if not exists cpc numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists cpm numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists ctr numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists conversions numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists revenue numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists roas numeric(18, 6) default 0;
alter table public.campaign_daily_stats add column if not exists raw_json jsonb default '{}'::jsonb;
alter table public.campaign_daily_stats add column if not exists updated_at timestamptz default now();

create unique index if not exists uq_campaign_daily_stats_client_campaign_date
  on public.campaign_daily_stats(client_id, campaign_id, stat_date);
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
  updated_at timestamptz not null default now()
);

alter table public.ad_daily_stats add column if not exists connection_id uuid;
alter table public.ad_daily_stats add column if not exists ad_account_name text;
alter table public.ad_daily_stats add column if not exists campaign_id text;
alter table public.ad_daily_stats add column if not exists campaign_name text;
alter table public.ad_daily_stats add column if not exists adset_id text;
alter table public.ad_daily_stats add column if not exists adset_name text;
alter table public.ad_daily_stats add column if not exists ad_name text;
alter table public.ad_daily_stats add column if not exists ad_status text;
alter table public.ad_daily_stats add column if not exists spend numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists impressions bigint default 0;
alter table public.ad_daily_stats add column if not exists reach bigint default 0;
alter table public.ad_daily_stats add column if not exists clicks bigint default 0;
alter table public.ad_daily_stats add column if not exists cpc numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists cpm numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists ctr numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists conversions numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists revenue numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists roas numeric(18, 6) default 0;
alter table public.ad_daily_stats add column if not exists raw_json jsonb default '{}'::jsonb;
alter table public.ad_daily_stats add column if not exists updated_at timestamptz default now();

create unique index if not exists uq_ad_daily_stats_client_ad_date
  on public.ad_daily_stats(client_id, ad_id, stat_date);
create index if not exists idx_ad_daily_stats_client_date
  on public.ad_daily_stats(client_id, stat_date desc);
create index if not exists idx_ad_daily_stats_campaign
  on public.ad_daily_stats(client_id, campaign_id, stat_date desc);
create index if not exists idx_ad_daily_stats_account
  on public.ad_daily_stats(client_id, ad_account_id, stat_date desc);
create index if not exists idx_ad_daily_stats_connection
  on public.ad_daily_stats(connection_id, stat_date desc);

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
  on public.promoted_post_daily_stats(client_id, connection_id, ad_account_id, post_id, ad_id, stat_date);
create unique index if not exists uq_promoted_post_daily_stats_legacy
  on public.promoted_post_daily_stats(client_id, ad_account_id, post_id, ad_id, stat_date);
create index if not exists idx_promoted_post_daily_stats_client_date
  on public.promoted_post_daily_stats(client_id, stat_date desc);
create index if not exists idx_promoted_post_daily_stats_connection
  on public.promoted_post_daily_stats(connection_id, stat_date desc);
create index if not exists idx_promoted_post_daily_stats_post
  on public.promoted_post_daily_stats(client_id, post_id, stat_date desc);

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
drop trigger if exists trg_promoted_post_daily_stats_updated_at on public.promoted_post_daily_stats;
create trigger trg_promoted_post_daily_stats_updated_at
before update on public.promoted_post_daily_stats
for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
