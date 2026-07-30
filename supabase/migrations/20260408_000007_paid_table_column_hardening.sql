-- Paid schema hardening: garante colunas esperadas pelo backend nos upserts.
-- Cenário alvo: projetos legados onde tabelas paid já existiam sem todos os campos
-- (ex.: campaign_status), causando erro 400 no PostgREST.

-- =========================================================
-- ad_account_daily_stats
-- =========================================================
alter table if exists public.ad_account_daily_stats
  add column if not exists connection_id uuid;
alter table if exists public.ad_account_daily_stats
  add column if not exists meta_connection_id uuid;
alter table if exists public.ad_account_daily_stats
  add column if not exists ad_account_name text;
alter table if exists public.ad_account_daily_stats
  add column if not exists spend numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists impressions bigint default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists reach bigint default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists clicks bigint default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists cpc numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists cpm numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists ctr numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists conversions numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists revenue numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists roas numeric(18, 6) default 0;
alter table if exists public.ad_account_daily_stats
  add column if not exists raw_json jsonb default '{}'::jsonb;
alter table if exists public.ad_account_daily_stats
  add column if not exists updated_at timestamptz default now();

-- =========================================================
-- campaign_daily_stats
-- =========================================================
alter table if exists public.campaign_daily_stats
  add column if not exists connection_id uuid;
alter table if exists public.campaign_daily_stats
  add column if not exists ad_account_name text;
alter table if exists public.campaign_daily_stats
  add column if not exists campaign_name text;
alter table if exists public.campaign_daily_stats
  add column if not exists campaign_status text;
alter table if exists public.campaign_daily_stats
  add column if not exists objective text;
alter table if exists public.campaign_daily_stats
  add column if not exists spend numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists impressions bigint default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists reach bigint default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists clicks bigint default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists cpc numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists cpm numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists ctr numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists conversions numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists revenue numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists roas numeric(18, 6) default 0;
alter table if exists public.campaign_daily_stats
  add column if not exists raw_json jsonb default '{}'::jsonb;
alter table if exists public.campaign_daily_stats
  add column if not exists updated_at timestamptz default now();

-- =========================================================
-- ad_daily_stats
-- =========================================================
alter table if exists public.ad_daily_stats
  add column if not exists connection_id uuid;
alter table if exists public.ad_daily_stats
  add column if not exists ad_account_name text;
alter table if exists public.ad_daily_stats
  add column if not exists campaign_id text;
alter table if exists public.ad_daily_stats
  add column if not exists campaign_name text;
alter table if exists public.ad_daily_stats
  add column if not exists adset_id text;
alter table if exists public.ad_daily_stats
  add column if not exists adset_name text;
alter table if exists public.ad_daily_stats
  add column if not exists ad_name text;
alter table if exists public.ad_daily_stats
  add column if not exists ad_status text;
alter table if exists public.ad_daily_stats
  add column if not exists spend numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists impressions bigint default 0;
alter table if exists public.ad_daily_stats
  add column if not exists reach bigint default 0;
alter table if exists public.ad_daily_stats
  add column if not exists clicks bigint default 0;
alter table if exists public.ad_daily_stats
  add column if not exists cpc numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists cpm numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists ctr numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists conversions numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists revenue numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists roas numeric(18, 6) default 0;
alter table if exists public.ad_daily_stats
  add column if not exists raw_json jsonb default '{}'::jsonb;
alter table if exists public.ad_daily_stats
  add column if not exists updated_at timestamptz default now();

-- Refresh do cache de schema do PostgREST (Supabase)
notify pgrst, 'reload schema';
