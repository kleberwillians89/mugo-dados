-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Biblioteca (como na iAgência): arquivos e links da marca por categoria; o cliente também envia material.
-- Os posts aprovados/publicados entram sozinhos (lidos do Calendário, sem duplicar aqui).
create table if not exists public.studio_library (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null default 'arquivo' check (kind in ('arquivo', 'link')),
  category text not null default 'outro' check (category in ('produto', 'logo', 'referencia', 'foto', 'video', 'documento', 'outro')),
  title text not null check (length(title) between 1 and 200),
  url text not null check (url ~ '^https://' and length(url) <= 1000),
  mime_type text check (mime_type is null or length(mime_type) <= 120),
  size_bytes bigint check (size_bytes is null or size_bytes >= 0),
  note text check (note is null or length(note) <= 500),
  side text not null default 'mugo' check (side in ('mugo', 'cliente')),
  created_by uuid,
  created_by_name text check (created_by_name is null or length(created_by_name) <= 120),
  created_at timestamptz not null default now()
);
create index if not exists studio_library_client_idx on public.studio_library (client_id, created_at desc);

-- Planejamento (estratégia do job) e Evento (produção RTV/eventos: cronograma, equipe, orçamento, riscos).
create table if not exists public.studio_projects (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null check (kind in ('planejamento', 'evento')),
  title text not null check (length(title) between 1 and 200),
  status text not null default 'fila' check (status in ('fila', 'em_andamento', 'aprovacao_interna', 'finalizado')),
  format text check (format is null or length(format) <= 60),
  target_date date,
  inputs jsonb not null default '{}'::jsonb check (jsonb_typeof(inputs) = 'object'),
  plan jsonb not null default '{}'::jsonb check (jsonb_typeof(plan) = 'object'),
  chat jsonb not null default '[]'::jsonb check (jsonb_typeof(chat) = 'array'),
  brief_id uuid,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_projects_client_idx on public.studio_projects (client_id, kind, updated_at desc);

alter table public.studio_library enable row level security;
alter table public.studio_projects enable row level security;
revoke all on public.studio_library, public.studio_projects from anon, authenticated;
grant all on public.studio_library, public.studio_projects to service_role;

notify pgrst, 'reload schema';
