-- Client-facing, tenant-scoped read model. Raw provider tables remain the source of truth.
create table if not exists public.dashboard_daily_metrics (
  client_id text not null,
  metric_date date not null,
  shopify_net_revenue numeric(18,6), shopify_gross_revenue numeric(18,6),
  shopify_orders bigint, shopify_paid_orders bigint, shopify_customers bigint, shopify_refunds numeric(18,6),
  meta_spend numeric(18,6), meta_attributed_revenue numeric(18,6), meta_purchases numeric(18,6),
  meta_impressions bigint, meta_reach bigint, meta_clicks bigint, meta_link_clicks bigint, meta_video_views bigint,
  google_ads_spend numeric(18,6), google_ads_conversion_value numeric(18,6), google_ads_conversions numeric(18,6),
  google_ads_impressions bigint, google_ads_clicks bigint,
  ga4_sessions bigint, ga4_users bigint, ga4_revenue numeric(18,6), ga4_purchases bigint, ga4_events bigint,
  instagram_reach bigint, instagram_impressions bigint, instagram_interactions bigint,
  instagram_profile_views bigint, instagram_website_clicks bigint, instagram_followers bigint,
  updated_at timestamptz not null default now(),
  primary key (client_id, metric_date)
);

create index if not exists dashboard_daily_metrics_client_date_idx
  on public.dashboard_daily_metrics(client_id, metric_date desc);

create table if not exists public.dashboard_campaign_metrics (
  client_id text not null, metric_date date not null, provider text not null,
  campaign_id text not null, campaign_name text, status text,
  spend numeric(18,6), revenue numeric(18,6), conversion_value numeric(18,6), conversions numeric(18,6),
  impressions bigint, reach bigint, clicks bigint, link_clicks bigint,
  updated_at timestamptz not null default now(),
  primary key (client_id, metric_date, provider, campaign_id),
  constraint dashboard_campaign_provider_check check (provider in ('meta', 'google_ads'))
);
create index if not exists dashboard_campaign_metrics_client_date_idx
  on public.dashboard_campaign_metrics(client_id, metric_date desc);
create index if not exists dashboard_campaign_metrics_client_provider_campaign_idx
  on public.dashboard_campaign_metrics(client_id, provider, campaign_id);

create table if not exists public.dashboard_product_metrics (
  client_id text not null, metric_date date not null, product_id text not null,
  product_title text, variant text, quantity bigint, orders bigint, net_revenue numeric(18,6),
  updated_at timestamptz not null default now(),
  primary key (client_id, metric_date, product_id, variant)
);
create index if not exists dashboard_product_metrics_client_date_idx
  on public.dashboard_product_metrics(client_id, metric_date desc);

create table if not exists public.dashboard_source_snapshots (
  client_id text not null, provider text not null, last_success_at timestamptz,
  data_max_available date, data_min_available date, last_error_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (client_id, provider)
);

alter table public.dashboard_daily_metrics enable row level security;
alter table public.dashboard_campaign_metrics enable row level security;
alter table public.dashboard_product_metrics enable row level security;
alter table public.dashboard_source_snapshots enable row level security;

revoke all on public.dashboard_daily_metrics, public.dashboard_campaign_metrics,
  public.dashboard_product_metrics, public.dashboard_source_snapshots from anon, authenticated;
grant select on public.dashboard_daily_metrics, public.dashboard_campaign_metrics,
  public.dashboard_product_metrics, public.dashboard_source_snapshots to authenticated;

drop policy if exists dashboard_daily_member_select on public.dashboard_daily_metrics;
create policy dashboard_daily_member_select on public.dashboard_daily_metrics for select
  using (public.is_client_member(client_id));
drop policy if exists dashboard_campaign_member_select on public.dashboard_campaign_metrics;
create policy dashboard_campaign_member_select on public.dashboard_campaign_metrics for select
  using (public.is_client_member(client_id));
drop policy if exists dashboard_product_member_select on public.dashboard_product_metrics;
create policy dashboard_product_member_select on public.dashboard_product_metrics for select
  using (public.is_client_member(client_id));
drop policy if exists dashboard_sources_member_select on public.dashboard_source_snapshots;
create policy dashboard_sources_member_select on public.dashboard_source_snapshots for select
  using (public.is_client_member(client_id));

create or replace function public.refresh_dashboard_read_model(
  p_client_id text, p_start date, p_end date, p_provider text default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_rows bigint := 0;
begin
  if p_client_id is null or p_start is null or p_end is null or p_start > p_end then
    raise exception 'invalid dashboard read model scope';
  end if;

  if p_provider is null or p_provider = 'shopify' then
    with refunds as (
      select shopify_order_id, sum(coalesce(total_refunded, 0)) amount
      from shopify_refunds where client_id = p_client_id group by shopify_order_id
    ), daily as (
      select (o.created_at_shopify at time zone 'America/Sao_Paulo')::date metric_date,
        sum(coalesce(o.total_price, 0)) gross_revenue,
        sum(coalesce(o.total_price, 0) - coalesce(r.amount, 0)) net_revenue,
        count(*) orders,
        count(*) filter (where lower(coalesce(o.financial_status, '')) in ('paid','partially_refunded')) paid_orders,
        count(distinct coalesce(nullif(o.customer_id, ''), nullif(o.email, ''), o.shopify_order_id)) customers,
        sum(coalesce(r.amount, 0)) refunds
      from shopify_orders o left join refunds r using (shopify_order_id)
      where o.client_id = p_client_id and o.created_at_shopify is not null
        and (o.created_at_shopify at time zone 'America/Sao_Paulo')::date between p_start and p_end
      group by 1
    ) insert into dashboard_daily_metrics(client_id, metric_date, shopify_net_revenue,
      shopify_gross_revenue, shopify_orders, shopify_paid_orders, shopify_customers, shopify_refunds)
    select p_client_id, metric_date, net_revenue, gross_revenue, orders, paid_orders, customers, refunds from daily
    on conflict (client_id, metric_date) do update set
      shopify_net_revenue=excluded.shopify_net_revenue, shopify_gross_revenue=excluded.shopify_gross_revenue,
      shopify_orders=excluded.shopify_orders, shopify_paid_orders=excluded.shopify_paid_orders,
      shopify_customers=excluded.shopify_customers, shopify_refunds=excluded.shopify_refunds, updated_at=now();

    insert into dashboard_product_metrics(client_id, metric_date, product_id, product_title, variant, quantity, orders, net_revenue)
    select p_client_id, (o.created_at_shopify at time zone 'America/Sao_Paulo')::date,
      coalesce(nullif(i.product_id,''), nullif(i.sku,''), i.shopify_line_item_id), i.title, coalesce(i.variant_title,''),
      sum(i.quantity), count(distinct i.shopify_order_id), sum((coalesce(i.price,0) * i.quantity) - coalesce(i.total_discount,0))
    from shopify_order_items i join shopify_orders o
      on o.client_id=i.client_id and o.shopify_order_id=i.shopify_order_id
    where i.client_id=p_client_id and o.created_at_shopify is not null
      and (o.created_at_shopify at time zone 'America/Sao_Paulo')::date between p_start and p_end
    group by 2,3,4,5
    on conflict (client_id, metric_date, product_id, variant) do update set
      product_title=excluded.product_title, quantity=excluded.quantity, orders=excluded.orders,
      net_revenue=excluded.net_revenue, updated_at=now();
  end if;

  if p_provider is null or p_provider = 'meta' then
    insert into dashboard_daily_metrics(client_id, metric_date, meta_spend, meta_attributed_revenue,
      meta_purchases, meta_impressions, meta_reach, meta_clicks)
    select p_client_id, stat_date, sum(spend), sum(revenue), sum(conversions), sum(impressions), sum(reach), sum(clicks)
    from ad_account_daily_stats where client_id=p_client_id and stat_date between p_start and p_end group by stat_date
    on conflict (client_id, metric_date) do update set meta_spend=excluded.meta_spend,
      meta_attributed_revenue=excluded.meta_attributed_revenue, meta_purchases=excluded.meta_purchases,
      meta_impressions=excluded.meta_impressions, meta_reach=excluded.meta_reach,
      meta_clicks=excluded.meta_clicks, updated_at=now();

    insert into dashboard_campaign_metrics(client_id,metric_date,provider,campaign_id,campaign_name,status,
      spend,revenue,conversions,impressions,reach,clicks)
    select p_client_id,stat_date,'meta',campaign_id,max(campaign_name),max(campaign_status),sum(spend),sum(revenue),
      sum(conversions),sum(impressions),sum(reach),sum(clicks)
    from campaign_daily_stats where client_id=p_client_id and stat_date between p_start and p_end group by stat_date,campaign_id
    on conflict (client_id,metric_date,provider,campaign_id) do update set campaign_name=excluded.campaign_name,
      status=excluded.status,spend=excluded.spend,revenue=excluded.revenue,conversions=excluded.conversions,
      impressions=excluded.impressions,reach=excluded.reach,clicks=excluded.clicks,updated_at=now();
  end if;

  if p_provider is null or p_provider = 'google_ads' then
    insert into dashboard_daily_metrics(client_id,metric_date,google_ads_spend,google_ads_conversion_value,
      google_ads_conversions,google_ads_impressions,google_ads_clicks)
    select p_client_id,stat_date,sum(cost),sum(conversion_value),sum(conversions),sum(impressions),sum(clicks)
    from google_ads_daily_stats where client_id=p_client_id and stat_date between p_start and p_end group by stat_date
    on conflict (client_id,metric_date) do update set google_ads_spend=excluded.google_ads_spend,
      google_ads_conversion_value=excluded.google_ads_conversion_value,google_ads_conversions=excluded.google_ads_conversions,
      google_ads_impressions=excluded.google_ads_impressions,google_ads_clicks=excluded.google_ads_clicks,updated_at=now();

    insert into dashboard_campaign_metrics(client_id,metric_date,provider,campaign_id,campaign_name,
      spend,conversion_value,conversions,impressions,clicks)
    select p_client_id,stat_date,'google_ads',campaign_id,max(campaign_name),sum(cost),sum(conversion_value),
      sum(conversions),sum(impressions),sum(clicks)
    from google_ads_daily_stats where client_id=p_client_id and stat_date between p_start and p_end group by stat_date,campaign_id
    on conflict (client_id,metric_date,provider,campaign_id) do update set campaign_name=excluded.campaign_name,
      spend=excluded.spend,conversion_value=excluded.conversion_value,conversions=excluded.conversions,
      impressions=excluded.impressions,clicks=excluded.clicks,updated_at=now();
  end if;

  if p_provider is null or p_provider = 'ga4' then
    insert into dashboard_daily_metrics(client_id,metric_date,ga4_sessions,ga4_users,ga4_revenue,ga4_purchases,ga4_events)
    select p_client_id,stat_date,sum(sessions),sum(total_users),sum(total_revenue),sum(ecommerce_purchases),sum(event_count)
    from ga4_daily_stats where client_id=p_client_id and stat_date between p_start and p_end group by stat_date
    on conflict (client_id,metric_date) do update set ga4_sessions=excluded.ga4_sessions,ga4_users=excluded.ga4_users,
      ga4_revenue=excluded.ga4_revenue,ga4_purchases=excluded.ga4_purchases,ga4_events=excluded.ga4_events,updated_at=now();
  end if;

  if p_provider is null or p_provider = 'instagram' then
    insert into dashboard_daily_metrics(client_id,metric_date,instagram_reach,instagram_impressions,
      instagram_interactions,instagram_profile_views,instagram_website_clicks,instagram_followers)
    select p_client_id,snapshot_date,max(reach_day),max(impressions_day),max(total_interactions_day),
      max(profile_views_day),max(website_clicks_day),max(followers_count)
    from ig_profile_snapshots where client_id=p_client_id and snapshot_date between p_start and p_end group by snapshot_date
    on conflict (client_id,metric_date) do update set instagram_reach=excluded.instagram_reach,
      instagram_impressions=excluded.instagram_impressions,instagram_interactions=excluded.instagram_interactions,
      instagram_profile_views=excluded.instagram_profile_views,instagram_website_clicks=excluded.instagram_website_clicks,
      instagram_followers=excluded.instagram_followers,updated_at=now();
  end if;

  get diagnostics v_rows = row_count;
  insert into dashboard_source_snapshots(client_id,provider,last_success_at,data_min_available,data_max_available)
  select p_client_id, coalesce(p_provider,'all'), now(), min(metric_date), max(metric_date)
  from dashboard_daily_metrics where client_id=p_client_id and (
    p_provider is null
    or (p_provider='shopify' and (shopify_net_revenue is not null or shopify_orders is not null))
    or (p_provider='meta' and meta_spend is not null)
    or (p_provider='google_ads' and google_ads_spend is not null)
    or (p_provider='ga4' and ga4_sessions is not null)
    or (p_provider='instagram' and instagram_reach is not null)
  )
  on conflict (client_id,provider) do update set last_success_at=excluded.last_success_at,
    data_min_available=excluded.data_min_available,data_max_available=excluded.data_max_available,updated_at=now();
  return jsonb_build_object('ok',true,'client_id',p_client_id,'provider',coalesce(p_provider,'all'),
    'start',p_start,'end',p_end,'rows',v_rows);
end;
$$;

revoke all on function public.refresh_dashboard_read_model(text,date,date,text) from public, anon, authenticated;
grant execute on function public.refresh_dashboard_read_model(text,date,date,text) to service_role;
notify pgrst, 'reload schema';
