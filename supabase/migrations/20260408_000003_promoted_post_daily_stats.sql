-- Complemento paid: estatísticas diárias de posts turbinados/promovidos
-- Mantém compatibilidade com pipeline de Ads clássico.

create extension if not exists pgcrypto;

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
