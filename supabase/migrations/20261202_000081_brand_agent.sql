-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- IA da marca vira agente:
-- 1. Todo material enviado é GUARDADO antes de a IA ler (brand_chunks, texto em trechos). Se a IA falhar,
--    o conteúdo fica salvo com status 'falhou' e pode ser reprocessado. Nada se perde.
-- 2. O agente conversa sobre a marca buscando só os trechos relevantes (busca textual em português),
--    em vez de mandar documentos inteiros para a IA: poucos tokens por pergunta.
-- 3. brand_agent_messages guarda a conversa de cada pessoa com o agente (privada por usuário).

alter table public.brand_documents add column if not exists status text not null default 'aprendido';
alter table public.brand_documents add column if not exists error text;
alter table public.brand_documents add column if not exists chars_total integer not null default 0;

alter table public.brand_documents drop constraint if exists brand_documents_status_check;
alter table public.brand_documents add constraint brand_documents_status_check
  check (status in ('pendente', 'aprendido', 'falhou'));
alter table public.brand_documents drop constraint if exists brand_documents_error_check;
alter table public.brand_documents add constraint brand_documents_error_check
  check (error is null or length(error) <= 200);
-- 'conversa': fatos que a equipe confirmou durante a conversa com o agente.
alter table public.brand_documents drop constraint if exists brand_documents_kind_check;
alter table public.brand_documents add constraint brand_documents_kind_check
  check (kind in ('institucional', 'produto', 'campanha', 'tom_de_voz', 'restricao', 'outro', 'conversa'));

create table if not exists public.brand_chunks (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  document_id uuid not null references public.brand_documents(id) on delete cascade,
  position integer not null check (position >= 0),
  content text not null check (length(content) between 1 and 2000),
  tsv tsvector generated always as (to_tsvector('portuguese', content)) stored,
  created_at timestamptz not null default now(),
  unique (document_id, position)
);

create table if not exists public.brand_agent_messages (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null check (length(content) between 1 and 6000),
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.brand_chunks enable row level security;
alter table public.brand_agent_messages enable row level security;
revoke all on public.brand_chunks from anon, authenticated;
revoke all on public.brand_agent_messages from anon, authenticated;
grant all on public.brand_chunks to service_role;
grant all on public.brand_agent_messages to service_role;

create index if not exists brand_chunks_tsv_idx on public.brand_chunks using gin (tsv);
create index if not exists brand_chunks_client_idx on public.brand_chunks (client_id, document_id, position);
create index if not exists brand_agent_messages_user_idx on public.brand_agent_messages (client_id, user_id, created_at desc);

-- Busca dos trechos mais relevantes de UMA empresa. Só o backend (service_role) chama.
create or replace function public.brand_chunk_search(p_client_id text, p_query text, p_limit integer default 4)
returns table (id uuid, document_id uuid, content text, rank real)
language sql
stable
set search_path = public, pg_temp
as $$
  select c.id, c.document_id, c.content, ts_rank(c.tsv, q) as rank
  from public.brand_chunks c, websearch_to_tsquery('portuguese', p_query) q
  where c.client_id = p_client_id and c.tsv @@ q
  order by rank desc, c.position
  limit least(greatest(coalesce(p_limit, 4), 1), 8);
$$;
revoke all on function public.brand_chunk_search(text, text, integer) from public, anon, authenticated;
grant execute on function public.brand_chunk_search(text, text, integer) to service_role;

notify pgrst, 'reload schema';
