-- Bootstrap mínimo + compatível para boosted posts no pipeline paid.
-- Idempotente para rodar em ambientes onde a tabela ainda não existe.

create table if not exists public.promoted_post_daily_stats (
  id bigserial primary key,
  client_id text not null,
  connection_id uuid references public.meta_connections(id) on delete cascade,
  ad_account_id text not null,
  ad_id text not null,
  post_id text not null,
  stat_date date not null,
  spend numeric(18, 6) not null default 0,
  impressions bigint not null default 0,
  reach bigint not null default 0,
  clicks bigint not null default 0,
  cpc numeric(18, 6) not null default 0,
  cpm numeric(18, 6) not null default 0,
  ctr numeric(18, 6) not null default 0,
  created_at timestamptz not null default now()
);

-- Campos extras de compatibilidade com o payload atual do sync
-- (evitam erro de coluna inexistente no upsert de boosted).
alter table if exists public.promoted_post_daily_stats
  add column if not exists ad_account_name text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists campaign_id text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists campaign_name text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists adset_id text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists adset_name text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists ad_name text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists story_id text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists source_platform text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists objective text;
alter table if exists public.promoted_post_daily_stats
  add column if not exists conversions numeric(18, 6) not null default 0;
alter table if exists public.promoted_post_daily_stats
  add column if not exists revenue numeric(18, 6) not null default 0;
alter table if exists public.promoted_post_daily_stats
  add column if not exists roas numeric(18, 6) not null default 0;
alter table if exists public.promoted_post_daily_stats
  add column if not exists raw_json jsonb not null default '{}'::jsonb;

-- Índices pedidos
create index if not exists idx_promoted_post_daily_stats_client_connection_date
  on public.promoted_post_daily_stats(client_id, connection_id, stat_date desc);

create index if not exists idx_promoted_post_daily_stats_account_date
  on public.promoted_post_daily_stats(ad_account_id, stat_date desc);

-- Constraints para suportar on_conflict usado no backend.
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
