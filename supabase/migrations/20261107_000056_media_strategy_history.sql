-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Mídia On: histórico das estratégias geradas.
--
-- Antes, a estratégia só era gravada quando a equipe clicava em "Salvar
-- rascunho" ou "Aprovar plano"; ao sair da página, a última estratégia gerada
-- se perdia. Agora cada geração é gravada aqui na hora (com a leitura da IA),
-- a página abre na mais recente e a equipe pode voltar a uma anterior.
-- O plano aprovado continua em studio_media_plans.
--
-- Browser só lê (membros da empresa). Escrita pelo backend.

create table if not exists public.studio_media_strategies (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month date not null check (extract(day from month) = 1),
  objective text not null check (objective in ('vendas', 'leads', 'trafego', 'alcance')),
  margin numeric(5, 4) check (margin is null or (margin > 0 and margin < 1)),
  custom_budget numeric(14, 2) check (custom_budget is null or custom_budget > 0),
  selected text,
  budget numeric(14, 2),
  headline text check (headline is null or length(headline) <= 300),
  strategy jsonb not null,
  created_by text,
  created_at timestamptz not null default now()
);

create index if not exists studio_media_strategies_client_month_idx
  on public.studio_media_strategies (client_id, month, created_at desc);

alter table public.studio_media_strategies enable row level security;
revoke all on public.studio_media_strategies from anon, authenticated;
grant select on public.studio_media_strategies to authenticated;
grant all on public.studio_media_strategies to service_role;
drop policy if exists studio_media_strategies_member_read on public.studio_media_strategies;
create policy studio_media_strategies_member_read on public.studio_media_strategies
  for select to authenticated using (public.is_client_member(client_id));

notify pgrst, 'reload schema';
