-- Hardening de upsert paid
-- Garante índices únicos compatíveis com on_conflict do backend:
-- - campaign_daily_stats -> (client_id, campaign_id, stat_date)
-- - ad_account_daily_stats -> (client_id, ad_account_id, stat_date)
-- - ad_daily_stats -> (client_id, ad_id, stat_date)
--
-- Estratégia:
-- 1) remover duplicidades legadas mantendo a maior id por chave
-- 2) criar unique indexes idempotentes

-- =========================================================
-- Deduplicação (mantém registro com maior id por chave)
-- =========================================================

with ranked as (
  select
    id,
    row_number() over (
      partition by client_id, campaign_id, stat_date
      order by id desc
    ) as rn
  from public.campaign_daily_stats
)
delete from public.campaign_daily_stats t
using ranked r
where t.id = r.id
  and r.rn > 1;

with ranked as (
  select
    id,
    row_number() over (
      partition by client_id, ad_account_id, stat_date
      order by id desc
    ) as rn
  from public.ad_account_daily_stats
)
delete from public.ad_account_daily_stats t
using ranked r
where t.id = r.id
  and r.rn > 1;

with ranked as (
  select
    id,
    row_number() over (
      partition by client_id, ad_id, stat_date
      order by id desc
    ) as rn
  from public.ad_daily_stats
)
delete from public.ad_daily_stats t
using ranked r
where t.id = r.id
  and r.rn > 1;

-- =========================================================
-- Unique indexes para on_conflict
-- =========================================================

create unique index if not exists uq_campaign_daily_stats_client_campaign_date
  on public.campaign_daily_stats(client_id, campaign_id, stat_date);

create unique index if not exists uq_ad_account_daily_stats_client_account_date
  on public.ad_account_daily_stats(client_id, ad_account_id, stat_date);

create unique index if not exists uq_ad_daily_stats_client_ad_date
  on public.ad_daily_stats(client_id, ad_id, stat_date);
