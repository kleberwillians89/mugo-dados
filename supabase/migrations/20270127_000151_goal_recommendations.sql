-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão: drop table public.goal_recommendations).
-- Recomendações da IA para uma meta: o que foi pedido, o que a IA respondeu (com evidência e justificativa) e quais
-- viraram tarefa no Kanban (task_id em cada item). Nada é executado sozinho; a tarefa só nasce com confirmação.
create table if not exists public.goal_recommendations (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  goal_id uuid not null,
  goal_snapshot jsonb not null default '{}'::jsonb,
  constraints text check (constraints is null or length(constraints) <= 1000),
  items jsonb not null default '[]'::jsonb,
  created_by text,
  created_at timestamptz not null default now()
);
create index if not exists goal_recommendations_goal_idx on public.goal_recommendations(goal_id, created_at desc);
alter table public.goal_recommendations enable row level security;
revoke all on public.goal_recommendations from anon, authenticated;
grant all on public.goal_recommendations to service_role;
