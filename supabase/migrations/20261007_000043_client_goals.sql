-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
create table if not exists public.client_goals (
 id uuid primary key default gen_random_uuid(),
 client_id text not null references public.clients(id) on delete cascade,
 metric text not null check (metric in ('revenue','orders','average_ticket','ad_spend','roas','conversions','followers','reach','impressions','engagement')),
 label text not null check (length(trim(label)) between 1 and 100),
 target_value numeric not null check (target_value > 0 and target_value <= 1000000000000000),
 period_start date not null,
 period_end date not null check (period_end >= period_start and period_end-period_start <= 365),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 created_by text not null
);
create index if not exists client_goals_tenant_period_idx on public.client_goals(client_id,period_start,period_end);
alter table public.client_goals enable row level security;
revoke all on public.client_goals from anon, authenticated;
grant select on public.client_goals to authenticated;
grant all on public.client_goals to service_role;
drop policy if exists client_goals_member_read on public.client_goals;
create policy client_goals_member_read on public.client_goals for select to authenticated using (public.is_client_member(client_id));
-- Nenhum grant/policy de escrita para browser, inclusive admin. Escrita passa
-- pelo backend com require_client_role e filtros client_id + id.
drop trigger if exists client_goals_updated_at on public.client_goals;
create trigger client_goals_updated_at before update on public.client_goals for each row execute function public.set_updated_at();
notify pgrst, 'reload schema';
