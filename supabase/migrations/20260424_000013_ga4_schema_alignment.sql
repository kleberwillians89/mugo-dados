alter table if exists public.ga4_daily_stats
  drop column if exists raw_payload;

alter table if exists public.ga4_channel_stats
  drop column if exists raw_payload;

alter table if exists public.ga4_campaign_stats
  drop column if exists raw_payload;

alter table if exists public.ga4_event_stats
  drop column if exists raw_payload;

do $$
begin
  if to_regclass('public.ga4_channel_stats') is null then
    return;
  end if;

  with ranked as (
    select
      id,
      row_number() over (
        partition by client_id, property_id, stat_date, source_medium
        order by updated_at desc nulls last, id desc
      ) as rn
    from public.ga4_channel_stats
  )
  delete from public.ga4_channel_stats target
  using ranked
  where target.id = ranked.id
    and ranked.rn > 1;

  if to_regclass('public.idx_ga4_channel_stats_upsert') is null then
    execute '
      create unique index idx_ga4_channel_stats_upsert
      on public.ga4_channel_stats (client_id, property_id, stat_date, source_medium)
    ';
  end if;
end
$$;

do $$
begin
  if to_regclass('public.ga4_campaign_stats') is null then
    return;
  end if;

  with ranked as (
    select
      id,
      row_number() over (
        partition by client_id, property_id, stat_date, campaign_name, source_medium
        order by updated_at desc nulls last, id desc
      ) as rn
    from public.ga4_campaign_stats
  )
  delete from public.ga4_campaign_stats target
  using ranked
  where target.id = ranked.id
    and ranked.rn > 1;

  if to_regclass('public.idx_ga4_campaign_stats_upsert') is null then
    execute '
      create unique index idx_ga4_campaign_stats_upsert
      on public.ga4_campaign_stats (client_id, property_id, stat_date, campaign_name, source_medium)
    ';
  end if;
end
$$;
