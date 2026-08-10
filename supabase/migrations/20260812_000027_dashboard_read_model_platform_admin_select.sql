-- Platform administrators may inspect every tenant's dashboard read model.
-- PostgreSQL combines these permissive SELECT policies with the existing
-- membership policies using OR. No browser role receives write privileges.

alter table public.dashboard_daily_metrics enable row level security;
alter table public.dashboard_campaign_metrics enable row level security;
alter table public.dashboard_product_metrics enable row level security;
alter table public.dashboard_source_snapshots enable row level security;

revoke all on public.dashboard_daily_metrics, public.dashboard_campaign_metrics,
  public.dashboard_product_metrics, public.dashboard_source_snapshots from anon, authenticated;
grant select on public.dashboard_daily_metrics, public.dashboard_campaign_metrics,
  public.dashboard_product_metrics, public.dashboard_source_snapshots to authenticated;

create policy dashboard_daily_platform_admin_select
on public.dashboard_daily_metrics
for select to authenticated
using (public.is_platform_admin());

create policy dashboard_campaign_platform_admin_select
on public.dashboard_campaign_metrics
for select to authenticated
using (public.is_platform_admin());

create policy dashboard_product_platform_admin_select
on public.dashboard_product_metrics
for select to authenticated
using (public.is_platform_admin());

create policy dashboard_sources_platform_admin_select
on public.dashboard_source_snapshots
for select to authenticated
using (public.is_platform_admin());

revoke all on function public.refresh_dashboard_read_model(text, date, date, text)
  from public, anon, authenticated;
grant execute on function public.refresh_dashboard_read_model(text, date, date, text)
  to service_role;
