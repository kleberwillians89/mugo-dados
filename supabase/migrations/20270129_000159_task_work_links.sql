-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- Rastreabilidade Kanban → produção: o que foi criado a partir de cada tarefa (ex.: campanha de E-mail Marketing).
-- Cliente → tarefa → entregável → módulo → registro. Só o backend (service_role) lê e grava; o tenant vem da rota.
create table if not exists public.task_work_links (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  task_id uuid not null,
  brief_id uuid,
  deliverable text not null default '' check (char_length(deliverable) <= 160),
  module text not null check (module in ('email_marketing', 'social_media', 'midia_on', 'redacao', 'calendar', 'whatsapp')),
  record_id text not null check (char_length(record_id) between 1 and 80),
  created_by uuid,
  created_at timestamptz not null default now(),
  unique (client_id, module, record_id)
);
create index if not exists task_work_links_task_idx on public.task_work_links (client_id, task_id, module);
alter table public.task_work_links enable row level security;
revoke all on public.task_work_links from anon, authenticated;
grant all on public.task_work_links to service_role;
notify pgrst, 'reload schema';

-- Reversão:
-- drop table if exists public.task_work_links;
