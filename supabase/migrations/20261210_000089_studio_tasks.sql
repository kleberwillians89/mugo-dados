-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Tarefas passam a morar no Mugoverso (antes eram só lidas do CRM Mugô).
-- Equipe Mugô vê e gerencia todas as tarefas da empresa; o cliente vê só as marcadas como
-- visíveis ao cliente e, com permissão "Gerenciar tarefas", cria e altera essas.
-- Mesmo padrão do Studio: RLS ligado, só o service_role (backend) lê e grava, sempre por client_id.

create table if not exists public.studio_tasks (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  title text not null check (length(trim(title)) between 1 and 200),
  notes text check (notes is null or length(notes) <= 4000),
  status text not null default 'pending' check (status in ('pending', 'in_progress', 'completed', 'cancelled')),
  priority text check (priority is null or priority in ('low', 'medium', 'high', 'urgent')),
  due_date date,
  due_time time,
  category text check (category is null or length(category) <= 60),
  assignee_name text check (assignee_name is null or length(assignee_name) <= 80),
  visible_to_client boolean not null default false,
  created_by uuid,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_tasks_client_idx on public.studio_tasks (client_id, status, due_date);

alter table public.studio_tasks enable row level security;
revoke all on public.studio_tasks from anon, authenticated;
grant all on public.studio_tasks to service_role;

notify pgrst, 'reload schema';
