-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Tarefas com aprovação (como no iAgência): produção → aprovação interna (equipe Mugô) → aprovação do
-- cliente → aprovada. Pedido de ajuste (interno ou do cliente) volta para "Ajustes" com o comentário.
-- O histórico (envios, aprovações, ajustes, comentários) fica em studio_task_events; o cliente vê só o que
-- não é interno.

alter table public.studio_tasks drop constraint if exists studio_tasks_status_check;
alter table public.studio_tasks add constraint studio_tasks_status_check
  check (status in ('pending', 'in_progress', 'internal_review', 'client_review', 'changes', 'completed', 'cancelled'));
alter table public.studio_tasks
  add column if not exists deliverable_url text check (deliverable_url is null or (length(deliverable_url) <= 1000 and deliverable_url ~ '^https://')),
  add column if not exists needs_client_approval boolean not null default true,
  add column if not exists approval_round integer not null default 0 check (approval_round >= 0),
  add column if not exists approved_at timestamptz;

create table if not exists public.studio_task_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  task_id uuid not null references public.studio_tasks(id) on delete cascade,
  kind text not null check (kind in ('enviado_interno', 'aprovado_interno', 'ajuste_interno', 'enviado_cliente',
                                     'aprovado_cliente', 'ajuste_cliente', 'comentario')),
  internal boolean not null default false,
  comment text check (comment is null or length(comment) <= 2000),
  actor_id uuid,
  actor_name text check (actor_name is null or length(actor_name) <= 120),
  actor_side text not null check (actor_side in ('mugo', 'cliente')),
  created_at timestamptz not null default now()
);
create index if not exists studio_task_events_task_idx on public.studio_task_events (task_id, created_at);

alter table public.studio_task_events enable row level security;
revoke all on public.studio_task_events from anon, authenticated;
grant all on public.studio_task_events to service_role;

notify pgrst, 'reload schema';
