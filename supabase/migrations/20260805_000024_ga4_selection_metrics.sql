-- GA4 metrics and landing/device dimensions required by the OAuth connection flow.
alter table if exists public.ga4_daily_stats
  add column if not exists new_users integer not null default 0,
  add column if not exists engaged_sessions integer not null default 0,
  add column if not exists engagement_rate numeric(12, 8) not null default 0,
  add column if not exists screen_page_views integer not null default 0,
  add column if not exists key_events integer not null default 0,
  add column if not exists transactions integer not null default 0;

create table if not exists public.ga4_landing_page_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete restrict,
  property_id text not null,
  stat_date date not null,
  landing_page text not null,
  device_category text not null default '(not set)',
  source text not null default '',
  medium text not null default '',
  campaign_name text not null default '(not set)',
  sessions integer not null default 0,
  active_users integer not null default 0,
  engaged_sessions integer not null default 0,
  screen_page_views integer not null default 0,
  key_events integer not null default 0,
  transactions integer not null default 0,
  purchase_revenue numeric(18, 2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (
    client_id, property_id, stat_date, landing_page, device_category,
    source, medium, campaign_name
  )
);

create index if not exists idx_ga4_landing_page_stats_client_date
  on public.ga4_landing_page_stats(client_id, stat_date desc);

alter table public.ga4_landing_page_stats enable row level security;
drop policy if exists ga4_landing_page_stats_member_select on public.ga4_landing_page_stats;
create policy ga4_landing_page_stats_member_select on public.ga4_landing_page_stats
for select using (public.is_client_member(client_id));
