-- Leitura leve do GA4: o banco devolve canais, campanhas, eventos e landing
-- pages JÁ SOMADOS no período, em vez de o backend baixar milhares de linhas
-- diárias (em páginas de 1.000) e somar em Python.
--
-- - Só leitura, sem alterar dados nem RLS.
-- - Isolamento: filtra sempre por client_id + property_id recebidos; execução
--   restrita ao service_role (o backend), como refresh_dashboard_read_model.
-- - Mesmas regras de agrupamento de services/ga4_reporting.py: chaves com
--   trim, origem/mídia da primeira linha (stat_date, id) e o primeiro canal
--   não vazio. row_count devolve quantas linhas diárias entraram na soma.
-- - Usa os índices existentes (client_id, stat_date) de cada tabela.
-- - Sem plpgsql (language sql) e em funções curtas: o SQL Editor do Supabase
--   cortava o corpo de uma função única longa ("unterminated dollar-quoted").

alter table public.ga4_campaign_stats add column if not exists channel_group text;

create or replace function public.ga4_rollup_channels(p_client_id text, p_property_id text, p_start date, p_end date)
returns jsonb language sql stable security invoker set search_path = public
as $fn$
  select coalesce(jsonb_agg(c order by c.purchase_revenue desc, c.sessions desc, lower(c.source_medium)), '[]'::jsonb)
  from (
    select
      trim(s.source_medium) as source_medium,
      trim(coalesce((array_agg(s.source order by s.stat_date, s.id))[1], '')) as source,
      trim(coalesce((array_agg(s.medium order by s.stat_date, s.id))[1], '')) as medium,
      sum(s.sessions)::bigint as sessions,
      sum(s.active_users)::bigint as active_users,
      sum(s.total_users)::bigint as total_users,
      sum(s.event_count)::bigint as event_count,
      sum(s.ecommerce_purchases)::bigint as ecommerce_purchases,
      sum(s.purchase_revenue) as purchase_revenue,
      sum(s.total_revenue) as total_revenue,
      count(*)::bigint as row_count
    from public.ga4_channel_stats s
    where s.client_id = p_client_id and s.property_id = p_property_id
      and s.stat_date between p_start and p_end
      and trim(coalesce(s.source_medium, '')) <> ''
    group by trim(s.source_medium)
  ) c
$fn$;

create or replace function public.ga4_rollup_campaigns(p_client_id text, p_property_id text, p_start date, p_end date)
returns jsonb language sql stable security invoker set search_path = public
as $fn$
  select coalesce(jsonb_agg(c order by c.purchase_revenue desc, c.sessions desc, lower(c.campaign_name)), '[]'::jsonb)
  from (
    select
      coalesce(nullif(trim(coalesce(s.campaign_name, '')), ''), '(not set)') as campaign_name,
      trim(coalesce(s.source_medium, '')) as source_medium,
      trim(coalesce((array_agg(s.source order by s.stat_date, s.id))[1], '')) as source,
      trim(coalesce((array_agg(s.medium order by s.stat_date, s.id))[1], '')) as medium,
      (array_agg(trim(s.channel_group) order by s.stat_date, s.id)
        filter (where nullif(trim(s.channel_group), '') is not null))[1] as channel_group,
      sum(s.sessions)::bigint as sessions,
      sum(s.active_users)::bigint as active_users,
      sum(s.total_users)::bigint as total_users,
      sum(s.event_count)::bigint as event_count,
      sum(s.ecommerce_purchases)::bigint as ecommerce_purchases,
      sum(s.purchase_revenue) as purchase_revenue,
      sum(s.total_revenue) as total_revenue,
      count(*)::bigint as row_count
    from public.ga4_campaign_stats s
    where s.client_id = p_client_id and s.property_id = p_property_id
      and s.stat_date between p_start and p_end
    group by trim(coalesce(s.campaign_name, '')), trim(coalesce(s.source_medium, ''))
  ) c
$fn$;

create or replace function public.ga4_rollup_events(p_client_id text, p_property_id text, p_start date, p_end date)
returns jsonb language sql stable security invoker set search_path = public
as $fn$
  select coalesce(jsonb_agg(e order by e.event_count desc, e.total_users desc, lower(e.event_name)), '[]'::jsonb)
  from (
    select
      trim(s.event_name) as event_name,
      sum(s.event_count)::bigint as event_count,
      sum(s.total_users)::bigint as total_users,
      min(s.stat_date) as first_seen_at,
      max(s.stat_date) as last_seen_at,
      count(*)::bigint as row_count
    from public.ga4_event_stats s
    where s.client_id = p_client_id and s.property_id = p_property_id
      and s.stat_date between p_start and p_end
      and trim(coalesce(s.event_name, '')) <> ''
    group by trim(s.event_name)
  ) e
$fn$;

create or replace function public.ga4_rollup_landing_pages(p_client_id text, p_property_id text, p_start date, p_end date)
returns jsonb language sql stable security invoker set search_path = public
as $fn$
  select coalesce(jsonb_agg(l order by l.sessions desc, l.landing_page), '[]'::jsonb)
  from (
    select s.landing_page, sum(s.sessions)::bigint as sessions, count(*)::bigint as row_count
    from public.ga4_landing_page_stats s
    where s.client_id = p_client_id and s.property_id = p_property_id
      and s.stat_date between p_start and p_end
      and coalesce(s.landing_page, '') <> ''
    group by s.landing_page
  ) l
$fn$;

create or replace function public.ga4_report_rollup(
  p_client_id text, p_property_id text, p_start date, p_end date,
  p_parts text[] default array['channels', 'campaigns', 'events']
) returns jsonb language sql stable security invoker set search_path = public
as $fn$
  select jsonb_build_object(
    'client_id', p_client_id, 'property_id', p_property_id, 'start', p_start, 'end', p_end,
    'channels', case when 'channels' = any(p_parts) then public.ga4_rollup_channels(p_client_id, p_property_id, p_start, p_end) end,
    'campaigns', case when 'campaigns' = any(p_parts) then public.ga4_rollup_campaigns(p_client_id, p_property_id, p_start, p_end) end,
    'events', case when 'events' = any(p_parts) then public.ga4_rollup_events(p_client_id, p_property_id, p_start, p_end) end,
    'landing_pages', case when 'landing_pages' = any(p_parts) then public.ga4_rollup_landing_pages(p_client_id, p_property_id, p_start, p_end) end
  )
$fn$;

revoke all on function public.ga4_rollup_channels(text, text, date, date) from public, anon, authenticated;
grant execute on function public.ga4_rollup_channels(text, text, date, date) to service_role;
revoke all on function public.ga4_rollup_campaigns(text, text, date, date) from public, anon, authenticated;
grant execute on function public.ga4_rollup_campaigns(text, text, date, date) to service_role;
revoke all on function public.ga4_rollup_events(text, text, date, date) from public, anon, authenticated;
grant execute on function public.ga4_rollup_events(text, text, date, date) to service_role;
revoke all on function public.ga4_rollup_landing_pages(text, text, date, date) from public, anon, authenticated;
grant execute on function public.ga4_rollup_landing_pages(text, text, date, date) to service_role;
revoke all on function public.ga4_report_rollup(text, text, date, date, text[]) from public, anon, authenticated;
grant execute on function public.ga4_report_rollup(text, text, date, date, text[]) to service_role;

notify pgrst, 'reload schema';
