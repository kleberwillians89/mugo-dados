-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Aprendizado semanal da marca: o job brand-learning-weekly lê os sinais da semana (retorno do cliente,
-- WhatsApp, CRM de criadores, respostas da equipe, resultados) e deixa os fatos sugeridos pendentes.
-- A equipe revisa em Contexto da Marca → Aprender com o uso; só o que ela aprova entra na memória.
create table if not exists public.brand_learning_suggestions (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  week text not null check (week ~ '^\d{4}-W\d{2}$'),
  facts jsonb not null default '[]'::jsonb,
  signals integer not null default 0 check (signals >= 0),
  status text not null default 'pendente' check (status in ('pendente', 'revisada', 'descartada', 'substituida')),
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (client_id, week)
);
create index if not exists brand_learning_suggestions_pending_idx
  on public.brand_learning_suggestions (client_id, created_at desc) where status = 'pendente';

alter table public.brand_learning_suggestions enable row level security;
revoke all on public.brand_learning_suggestions from anon, authenticated;
grant all on public.brand_learning_suggestions to service_role;
