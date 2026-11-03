-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Sugestão mensal do perfil da marca (IA avançada). O job brand-profile-monthly grava uma por marca
-- por mês, pendente; a equipe Mugô revisa no Perfil da marca e marca como aplicada ou descartada.
-- Nada aqui altera o perfil salvo (studio_brand_profiles).
create table if not exists public.studio_profile_suggestions (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month text not null check (month ~ '^\d{4}-\d{2}$'),
  suggestion jsonb not null default '{}'::jsonb,
  status text not null default 'pendente' check (status in ('pendente', 'aplicada', 'descartada')),
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (client_id, month)
);
create index if not exists studio_profile_suggestions_pending_idx
  on public.studio_profile_suggestions (client_id, created_at desc) where status = 'pendente';

alter table public.studio_profile_suggestions enable row level security;
revoke all on public.studio_profile_suggestions from anon, authenticated;
