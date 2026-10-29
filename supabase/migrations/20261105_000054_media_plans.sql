-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Mídia On: plano mensal de mídia paga por empresa.
--
-- Um plano por empresa e mês: objetivo, verba, divisão por canal (% da verba)
-- e as premissas usadas na simulação (CPM, CPC, conversão e valor por
-- conversão), que nascem dos dados reais de Meta Ads e Google Ads da própria
-- empresa e podem ser ajustadas pela equipe. O realizado não é guardado aqui:
-- é lido na hora das tabelas de mídia paga, para planejado x realizado.
--
-- Browser só lê (membros da empresa). Escrita pelo backend.

create table if not exists public.studio_media_plans (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month date not null check (extract(day from month) = 1),
  objective text not null check (objective in ('vendas', 'leads', 'trafego', 'alcance')),
  budget numeric(14, 2) not null check (budget > 0 and budget <= 100000000),
  allocation jsonb not null default '{}'::jsonb,
  assumptions jsonb not null default '{}'::jsonb,
  notes text check (notes is null or length(notes) <= 2000),
  status text not null default 'rascunho' check (status in ('rascunho', 'aprovado')),
  created_by text,
  updated_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, month)
);

alter table public.studio_media_plans enable row level security;
revoke all on public.studio_media_plans from anon, authenticated;
grant select on public.studio_media_plans to authenticated;
grant all on public.studio_media_plans to service_role;
drop policy if exists studio_media_plans_member_read on public.studio_media_plans;
create policy studio_media_plans_member_read on public.studio_media_plans
  for select to authenticated using (public.is_client_member(client_id));
drop trigger if exists studio_media_plans_updated_at on public.studio_media_plans;
create trigger studio_media_plans_updated_at before update on public.studio_media_plans
  for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
