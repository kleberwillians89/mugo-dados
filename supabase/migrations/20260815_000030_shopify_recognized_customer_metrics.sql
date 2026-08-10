-- Align customer metrics with the recognized Shopify sales rule from 000029.
do $$
begin
  if to_regprocedure('public.refresh_dashboard_read_model_000029(text,date,date,text)') is null then
    alter function public.refresh_dashboard_read_model(text,date,date,text)
      rename to refresh_dashboard_read_model_000029;
  end if;
end $$;

create or replace function public.refresh_dashboard_read_model(
  p_client_id text, p_start date, p_end date, p_provider text default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_result jsonb;
begin
  v_result := public.refresh_dashboard_read_model_000029(
    p_client_id, p_start, p_end, p_provider
  );

  if p_provider is null or p_provider = 'shopify' then
    with recognized_daily as (
      select
        (o.created_at_shopify at time zone 'America/Sao_Paulo')::date metric_date,
        count(distinct nullif(trim(o.customer_id), '')) customers,
        coalesce(
          array_agg(
            distinct ('customer_md5:' || md5(trim(o.customer_id)))
            order by ('customer_md5:' || md5(trim(o.customer_id)))
          ) filter (where nullif(trim(o.customer_id), '') is not null),
          '{}'::text[]
        ) customer_keys
      from shopify_orders o
      where o.client_id = p_client_id
        and o.created_at_shopify is not null
        and o.cancelled_at is null
        and nullif(trim(coalesce(o.cancel_reason, '')), '') is null
        and lower(coalesce(o.financial_status, '')) in ('paid', 'partially_refunded')
        and (o.created_at_shopify at time zone 'America/Sao_Paulo')::date between p_start and p_end
      group by 1
    )
    update dashboard_daily_metrics d set
      shopify_customers = r.customers,
      shopify_customer_keys = r.customer_keys,
      updated_at = now()
    from recognized_daily r
    where d.client_id = p_client_id and d.metric_date = r.metric_date;

    update dashboard_daily_metrics d set
      shopify_customers = 0,
      shopify_customer_keys = '{}'::text[],
      updated_at = now()
    where d.client_id = p_client_id
      and d.metric_date between p_start and p_end
      and coalesce(d.shopify_orders, 0) = 0;
  end if;

  return v_result || jsonb_build_object(
    'shopify_customer_rule', 'recognized_paid_or_partially_refunded'
  );
end;
$$;

revoke all on function public.refresh_dashboard_read_model_000029(text,date,date,text)
  from public, anon, authenticated;
revoke all on function public.refresh_dashboard_read_model(text,date,date,text)
  from public, anon, authenticated;
grant execute on function public.refresh_dashboard_read_model_000029(text,date,date,text)
  to service_role;
grant execute on function public.refresh_dashboard_read_model(text,date,date,text)
  to service_role;

notify pgrst, 'reload schema';
