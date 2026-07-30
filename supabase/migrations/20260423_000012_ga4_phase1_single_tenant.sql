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
  raw_payload jsonb not null default '{}'::jsonb,
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
  raw_payload jsonb not null default '{}'::jsonb,
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
  raw_payload jsonb not null default '{}'::jsonb,
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
  raw_payload jsonb not null default '{}'::jsonb,
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
