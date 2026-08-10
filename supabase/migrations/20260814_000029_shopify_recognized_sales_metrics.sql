-- Keep operational order totals separate from commercially recognized Shopify sales.
alter table public.shopify_orders
  add column if not exists current_total_price numeric(18, 2);

alter table public.dashboard_daily_metrics
  add column if not exists shopify_orders_created bigint,
  add column if not exists shopify_orders_non_cancelled bigint,
  add column if not exists shopify_pending_orders bigint,
  add column if not exists shopify_sales_revenue numeric(18, 6);

do $$
begin
  if to_regprocedure('public.refresh_dashboard_read_model_000028(text,date,date,text)') is null then
    alter function public.refresh_dashboard_read_model(text,date,date,text)
      rename to refresh_dashboard_read_model_000028;
  end if;
end $$;

create or replace function public.refresh_dashboard_read_model(
  p_client_id text, p_start date, p_end date, p_provider text default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_result jsonb;
begin
  v_result := public.refresh_dashboard_read_model_000028(
    p_client_id, p_start, p_end, p_provider
  );

  if p_provider is null or p_provider = 'shopify' then
    with refunds as (
      select client_id, shopify_order_id, sum(coalesce(total_refunded, 0)) amount
      from shopify_refunds
      where client_id = p_client_id
      group by client_id, shopify_order_id
    ), daily as (
      select
        (o.created_at_shopify at time zone 'America/Sao_Paulo')::date metric_date,
        count(*) orders_created,
        count(*) filter (
          where o.cancelled_at is null
            and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
        ) orders_non_cancelled,
        count(*) filter (
          where o.cancelled_at is null
            and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
            and lower(coalesce(o.financial_status, '')) in ('paid', 'partially_refunded')
        ) recognized_orders,
        count(*) filter (
          where o.cancelled_at is null
            and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
            and lower(coalesce(o.financial_status, '')) = 'pending'
        ) pending_orders,
        sum(coalesce(o.total_price, 0)) filter (
          where o.cancelled_at is null
            and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
        ) gross_non_cancelled,
        sum(greatest(coalesce(o.total_price, 0) - coalesce(r.amount, 0), 0)) filter (
          where o.cancelled_at is null
            and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
            and lower(coalesce(o.financial_status, '')) in ('paid', 'partially_refunded')
        ) sales_revenue,
        sum(coalesce(r.amount, 0)) filter (
          where o.cancelled_at is null
            and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
            and lower(coalesce(o.financial_status, '')) in ('paid', 'partially_refunded')
        ) recognized_refunds
      from shopify_orders o
      left join refunds r
        on r.client_id = o.client_id and r.shopify_order_id = o.shopify_order_id
      where o.client_id = p_client_id
        and o.created_at_shopify is not null
        and (o.created_at_shopify at time zone 'America/Sao_Paulo')::date between p_start and p_end
      group by 1
    )
    update dashboard_daily_metrics d set
      shopify_orders_created = x.orders_created,
      shopify_orders_non_cancelled = x.orders_non_cancelled,
      shopify_pending_orders = x.pending_orders,
      shopify_sales_revenue = coalesce(x.sales_revenue, 0),
      shopify_net_revenue = coalesce(x.sales_revenue, 0),
      shopify_gross_revenue = coalesce(x.gross_non_cancelled, 0),
      shopify_orders = x.recognized_orders,
      shopify_paid_orders = x.recognized_orders,
      shopify_refunds = coalesce(x.recognized_refunds, 0),
      updated_at = now()
    from daily x
    where d.client_id = p_client_id and d.metric_date = x.metric_date;

    delete from dashboard_product_metrics
    where client_id = p_client_id and metric_date between p_start and p_end;

    insert into dashboard_product_metrics(
      client_id, metric_date, product_id, product_title, variant,
      quantity, orders, net_revenue
    )
    select p_client_id,
      (o.created_at_shopify at time zone 'America/Sao_Paulo')::date,
      coalesce(nullif(i.product_id, ''), nullif(i.sku, ''), i.shopify_line_item_id),
      i.title, coalesce(i.variant_title, ''), sum(i.quantity),
      count(distinct i.shopify_order_id),
      sum((coalesce(i.price, 0) * i.quantity) - coalesce(i.total_discount, 0))
    from shopify_order_items i
    join shopify_orders o
      on o.client_id = i.client_id and o.shopify_order_id = i.shopify_order_id
    where i.client_id = p_client_id
      and o.created_at_shopify is not null
      and o.cancelled_at is null
      and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
      and lower(coalesce(o.financial_status, '')) in ('paid', 'partially_refunded')
      and (o.created_at_shopify at time zone 'America/Sao_Paulo')::date between p_start and p_end
    group by 2, 3, 4, 5
    on conflict (client_id, metric_date, product_id, variant) do update set
      product_title = excluded.product_title,
      quantity = excluded.quantity,
      orders = excluded.orders,
      net_revenue = excluded.net_revenue,
      updated_at = now();
  end if;

  return v_result || jsonb_build_object('shopify_sales_rule', 'paid_or_partially_refunded');
end;
$$;

revoke all on function public.refresh_dashboard_read_model_000028(text,date,date,text)
  from public, anon, authenticated;
revoke all on function public.refresh_dashboard_read_model(text,date,date,text)
  from public, anon, authenticated;
grant execute on function public.refresh_dashboard_read_model_000028(text,date,date,text)
  to service_role;
grant execute on function public.refresh_dashboard_read_model(text,date,date,text)
  to service_role;

notify pgrst, 'reload schema';
