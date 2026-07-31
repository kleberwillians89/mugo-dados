-- Central versionada de Inteligência IA.
-- Toda escrita e leitura acontece no backend com service_role. Não há acesso
-- direto pelo navegador; a API reaplica autorização e filtro de tenant.

create table if not exists public.ai_analyses (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  requested_by uuid not null references auth.users(id) on delete restrict,
  period_start date not null,
  period_end date not null,
  status text not null check (
    status in ('completed', 'configuration_pending', 'failed')
  ),
  provider text,
  model text,
  sources jsonb not null default '[]'::jsonb,
  data_quality jsonb not null default '{}'::jsonb,
  metrics_snapshot jsonb not null default '[]'::jsonb,
  analysis jsonb,
  error_code text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists ai_analyses_client_created_idx
  on public.ai_analyses(client_id, created_at desc);
create index if not exists ai_analyses_client_period_idx
  on public.ai_analyses(client_id, period_start, period_end, created_at desc);

create table if not exists public.ai_conversations (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ai_conversations_tenant_user_idx
  on public.ai_conversations(client_id, user_id, updated_at desc);

create table if not exists public.ai_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.ai_conversations(id) on delete cascade,
  client_id text not null references public.clients(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  analysis_id uuid references public.ai_analyses(id) on delete set null,
  role text not null check (role in ('user', 'assistant')),
  content jsonb not null,
  period_start date not null,
  period_end date not null,
  sources jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists ai_messages_conversation_created_idx
  on public.ai_messages(conversation_id, created_at asc);
create index if not exists ai_messages_tenant_user_idx
  on public.ai_messages(client_id, user_id, created_at desc);

alter table public.ai_analyses enable row level security;
alter table public.ai_conversations enable row level security;
alter table public.ai_messages enable row level security;

revoke all on public.ai_analyses from anon, authenticated;
revoke all on public.ai_conversations from anon, authenticated;
revoke all on public.ai_messages from anon, authenticated;

-- Nenhuma policy authenticated é criada deliberadamente. service_role acessa
-- as tabelas pelo backend e toda consulta exige client_id e, nas conversas,
-- também user_id.
