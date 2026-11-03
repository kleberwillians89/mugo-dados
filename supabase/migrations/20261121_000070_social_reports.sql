-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Relatório social mensal (modelo "Social Media Report" da Mugô): retrato dos números do mês
-- e os insights revisados pela equipe. Só o backend (service role) lê e grava.
create table if not exists public.social_reports (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month text not null check (month ~ '^\d{4}-\d{2}$'),
  data jsonb not null default '{}'::jsonb,
  insights text[] not null default '{}',
  updated_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, month)
);

alter table public.social_reports enable row level security;
revoke all on public.social_reports from anon, authenticated;

notify pgrst, 'reload schema';
