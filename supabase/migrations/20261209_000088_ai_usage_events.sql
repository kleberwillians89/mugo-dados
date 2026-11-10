-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Consumo de IA por cliente (Administração → Consumo de IA): cada chamada à OpenAI grava tokens,
-- modelo, recurso e, se falhou, o código do erro (ex.: http_429:insufficient_quota = sem crédito).
-- Só metadados: nunca prompt, resposta ou chave. Custo em dólar é estimativa pela tabela de preços.
-- RLS ligado; só o service_role (backend) lê e grava; a leitura é só para a equipe Mugô.

create table if not exists public.ai_usage_events (
  id bigint generated always as identity primary key,
  client_id text check (client_id is null or length(client_id) <= 120),
  feature text not null default 'ia' check (length(feature) <= 80),
  model text not null default '' check (length(model) <= 80),
  input_tokens integer not null default 0 check (input_tokens >= 0),
  output_tokens integer not null default 0 check (output_tokens >= 0),
  total_tokens integer not null default 0 check (total_tokens >= 0),
  cost_usd numeric(12, 6),
  status text not null default 'ok' check (status in ('ok', 'erro')),
  error_code text check (error_code is null or length(error_code) <= 80),
  created_at timestamptz not null default now()
);
create index if not exists ai_usage_events_created_idx on public.ai_usage_events (created_at);
create index if not exists ai_usage_events_client_idx on public.ai_usage_events (client_id, created_at);

alter table public.ai_usage_events enable row level security;
revoke all on public.ai_usage_events from anon, authenticated;
grant all on public.ai_usage_events to service_role;

notify pgrst, 'reload schema';
