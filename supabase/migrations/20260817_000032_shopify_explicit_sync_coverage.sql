-- Coverage is the completed Shopify query boundary, not the latest sale date.
do $$
begin
  if to_regprocedure('public.refresh_dashboard_read_model_000030(text,date,date,text)') is null then
    alter function public.refresh_dashboard_read_model(text,date,date,text)
      rename to refresh_dashboard_read_model_000030;
  end if;
end $$;

create or replace function public.refresh_dashboard_read_model(
  p_client_id text, p_start date, p_end date, p_provider text default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_result jsonb;
begin
  v_result := public.refresh_dashboard_read_model_000030(
    p_client_id, p_start, p_end, p_provider
  );

  if p_provider = 'shopify' then
    insert into public.dashboard_source_snapshots(
      client_id, provider, last_success_at, data_min_available, data_max_available
    ) values (
      p_client_id, 'shopify', now(), p_start, p_end
    )
    on conflict (client_id, provider) do update set
      last_success_at = excluded.last_success_at,
      data_min_available = case
        when dashboard_source_snapshots.data_min_available is null then excluded.data_min_available
        else least(dashboard_source_snapshots.data_min_available, excluded.data_min_available)
      end,
      data_max_available = greatest(
        coalesce(dashboard_source_snapshots.data_max_available, excluded.data_max_available),
        excluded.data_max_available
      ),
      updated_at = now();
  end if;

  return v_result || jsonb_build_object(
    'shopify_coverage_through', case when p_provider = 'shopify' then p_end else null end
  );
end;
$$;

revoke all on function public.refresh_dashboard_read_model_000030(text,date,date,text)
  from public, anon, authenticated;
revoke all on function public.refresh_dashboard_read_model(text,date,date,text)
  from public, anon, authenticated;
grant execute on function public.refresh_dashboard_read_model_000030(text,date,date,text)
  to service_role;
grant execute on function public.refresh_dashboard_read_model(text,date,date,text)
  to service_role;

notify pgrst, 'reload schema';
