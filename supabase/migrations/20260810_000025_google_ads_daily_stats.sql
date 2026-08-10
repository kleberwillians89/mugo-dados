create table if not exists public.google_ads_daily_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  connection_id uuid not null references public.integration_connections(id) on delete cascade,
  customer_id text not null,
  stat_date date not null,
  campaign_id text not null,
  campaign_name text,
  cost numeric(18,6) not null default 0,
  impressions bigint not null default 0,
  clicks bigint not null default 0,
  ctr numeric(18,8) not null default 0,
  cpc numeric(18,6) not null default 0,
  conversions numeric(18,6) not null default 0,
  conversion_value numeric(18,6) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, connection_id, customer_id, campaign_id, stat_date)
);

create index if not exists google_ads_daily_stats_scope_date_idx
  on public.google_ads_daily_stats (client_id, connection_id, customer_id, stat_date desc);

alter table public.google_ads_daily_stats enable row level security;
revoke all on public.google_ads_daily_stats from anon, authenticated;
