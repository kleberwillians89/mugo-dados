-- Correct Shopify commercial metrics without changing raw provider data.
-- Opaque customer keys allow exact period unions in the existing browser read.
alter table public.dashboard_daily_metrics
  add column if not exists shopify_customer_keys text[] not null default '{}'::text[];

create or replace function public.refresh_dashboard_read_model(
  p_client_id text, p_start date, p_end date, p_provider text default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_rows bigint := 0;
begin
  if p_client_id is null or p_start is null or p_end is null or p_start > p_end then
    raise exception 'invalid dashboard read model scope';
  end if;

  if p_provider is null or p_provider = 'shopify' then
    update dashboard_daily_metrics set
      shopify_net_revenue=null, shopify_gross_revenue=null, shopify_orders=null,
      shopify_paid_orders=null, shopify_customers=null, shopify_customer_keys='{}'::text[],
      shopify_refunds=null, updated_at=now()
    where client_id=p_client_id and metric_date between p_start and p_end;

    delete from dashboard_product_metrics
    where client_id=p_client_id and metric_date between p_start and p_end;

    with refunds as (
      select client_id, shopify_order_id, sum(coalesce(total_refunded, 0)) amount
      from shopify_refunds where client_id = p_client_id group by client_id, shopify_order_id
    ), valid_orders as (
      select o.*
      from shopify_orders o
      where o.client_id = p_client_id and o.created_at_shopify is not null
        and o.cancelled_at is null
        and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
        and (o.created_at_shopify at time zone 'America/Sao_Paulo')::date between p_start and p_end
    ), daily as (
      select (o.created_at_shopify at time zone 'America/Sao_Paulo')::date metric_date,
        sum(coalesce(o.total_price, 0)) gross_revenue,
        sum(coalesce(o.total_price, 0) - coalesce(r.amount, 0)) net_revenue,
        count(*) orders,
        count(*) filter (where lower(coalesce(o.financial_status, '')) in ('paid','partially_refunded')) paid_orders,
        count(distinct nullif(trim(o.customer_id), '')) customers,
        coalesce(
          array_agg(distinct ('customer_md5:' || md5(trim(o.customer_id))) order by ('customer_md5:' || md5(trim(o.customer_id))))
            filter (where nullif(trim(o.customer_id), '') is not null),
          '{}'::text[]
        ) customer_keys,
        sum(coalesce(r.amount, 0)) refunds
      from valid_orders o left join refunds r
        on r.client_id=o.client_id and r.shopify_order_id=o.shopify_order_id
      group by 1
    ) insert into dashboard_daily_metrics(client_id, metric_date, shopify_net_revenue,
      shopify_gross_revenue, shopify_orders, shopify_paid_orders, shopify_customers,
      shopify_customer_keys, shopify_refunds)
    select p_client_id, metric_date, net_revenue, gross_revenue, orders, paid_orders,
      customers, customer_keys, refunds from daily
    on conflict (client_id, metric_date) do update set
      shopify_net_revenue=excluded.shopify_net_revenue, shopify_gross_revenue=excluded.shopify_gross_revenue,
      shopify_orders=excluded.shopify_orders, shopify_paid_orders=excluded.shopify_paid_orders,
      shopify_customers=excluded.shopify_customers, shopify_customer_keys=excluded.shopify_customer_keys,
      shopify_refunds=excluded.shopify_refunds, updated_at=now();

    insert into dashboard_product_metrics(client_id, metric_date, product_id, product_title, variant, quantity, orders, net_revenue)
    select p_client_id, (o.created_at_shopify at time zone 'America/Sao_Paulo')::date,
      coalesce(nullif(i.product_id,''), nullif(i.sku,''), i.shopify_line_item_id), i.title, coalesce(i.variant_title,''),
      sum(i.quantity), count(distinct i.shopify_order_id), sum((coalesce(i.price,0) * i.quantity) - coalesce(i.total_discount,0))
    from shopify_order_items i join shopify_orders o
      on o.client_id=i.client_id and o.shopify_order_id=i.shopify_order_id
    where i.client_id=p_client_id and o.created_at_shopify is not null
      and o.cancelled_at is null
      and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
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
    on conflict (client_id, metric_date) do update set google_ads_spend=excluded.google_ads_spend,
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
