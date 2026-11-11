-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Esteira de agentes (como na iAgência, sem a parte de arte): pesquisador → estrategista → redator →
-- diretor de arte (briefing visual) → revisor de marca → agendador → aprovação interna. Cada execução e
-- o andamento de cada agente ficam em studio_agent_runs (a tela acompanha ao vivo).
-- Pedido de ajuste do cliente: a IA prepara uma nova versão como SUGESTÃO no post (ai_suggestion);
-- a equipe aplica com um clique ou descarta.

create table if not exists public.studio_agent_runs (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  status text not null default 'rodando' check (status in ('rodando', 'concluida', 'falhou')),
  steps jsonb not null default '[]'::jsonb check (jsonb_typeof(steps) = 'array'),
  matrix_id uuid,
  item_ids jsonb not null default '[]'::jsonb check (jsonb_typeof(item_ids) = 'array'),
  summary text check (summary is null or length(summary) <= 2000),
  error text check (error is null or length(error) <= 1000),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists studio_agent_runs_client_idx on public.studio_agent_runs (client_id, created_at desc);

alter table public.studio_agent_runs enable row level security;
revoke all on public.studio_agent_runs from anon, authenticated;
grant all on public.studio_agent_runs to service_role;

alter table public.studio_calendar_items add column if not exists ai_suggestion jsonb
  check (ai_suggestion is null or jsonb_typeof(ai_suggestion) = 'object');

notify pgrst, 'reload schema';
