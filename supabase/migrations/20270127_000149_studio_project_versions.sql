-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Versões do Planejamento e do Evento. Refazer com IA, aprovar ou restaurar grava uma versão nova; a anterior
-- fica inteira (plano, entradas, título e etapa), com número, data e autor. Nada é apagado ao refazer.
create table if not exists public.studio_project_versions (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  project_id uuid not null references public.studio_projects(id) on delete cascade,
  version integer not null check (version >= 1),
  origin text not null check (origin in ('ia', 'edicao', 'aprovada', 'restaurada')),
  title text,
  status text,
  inputs jsonb not null default '{}'::jsonb,
  plan jsonb not null default '{}'::jsonb,
  note text check (note is null or length(note) <= 600),
  created_by text,
  created_by_name text check (created_by_name is null or length(created_by_name) <= 120),
  created_at timestamptz not null default now(),
  unique (project_id, version)
);
create index if not exists studio_project_versions_project_idx on public.studio_project_versions (project_id, version desc);

alter table public.studio_project_versions enable row level security;
revoke all on public.studio_project_versions from anon, authenticated;
grant all on public.studio_project_versions to service_role;
