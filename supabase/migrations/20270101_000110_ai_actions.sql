-- LOCAL: NÃO APLICADA (000110). Revisão/aplicação remota manual; feature aditiva. Depende de 000108/000109.
-- Ações da IA: a IA propõe (com a evidência nos dados), alguém da marca ou da Mugô aprova, o MUGOVERSO executa
-- com as ferramentas que já existem (campanha, fluxo, carrinho) e mede o resultado depois.
-- dedupe_key impede repropor a mesma ação enquanto ela estiver aberta ou recém-decidida.

create table if not exists public.ai_actions (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null check (kind in ('campanha_reativacao', 'ligar_fluxo', 'ligar_carrinho', 'alerta_cac')),
  dedupe_key text not null check (length(dedupe_key) between 3 and 160),
  title text not null check (length(title) between 3 and 200),
  rationale text not null default '' check (length(rationale) <= 2000),
  evidence jsonb not null default '{}'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'proposta' check (status in ('proposta', 'executada', 'rejeitada', 'falhou', 'expirada', 'ciente')),
  proposed_at timestamptz not null default now(),
  decided_by uuid,
  decided_at timestamptz,
  executed_at timestamptz,
  result jsonb not null default '{}'::jsonb,
  error text,
  unique (client_id, dedupe_key)
);
create index if not exists ai_actions_client_idx on public.ai_actions (client_id, proposed_at desc);

alter table public.ai_actions enable row level security;
revoke all on public.ai_actions from anon, authenticated;
grant all on public.ai_actions to service_role;

notify pgrst, 'reload schema';
