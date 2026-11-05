-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Conhecimento da marca: documentos alimentam a IA e são descartados (o arquivo não é guardado).
-- brand_knowledge: um texto consolidado por empresa (tamanho fixo). brand_documents: só o registro do que entrou.
create table if not exists public.brand_knowledge (
  client_id text primary key references public.clients(id) on delete cascade,
  knowledge text not null default '' check (length(knowledge) <= 8000),
  sources integer not null default 0,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.brand_documents (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(name) <= 160),
  kind text not null default 'outro' check (kind in ('institucional', 'produto', 'campanha', 'tom_de_voz', 'restricao', 'outro')),
  summary text check (summary is null or length(summary) <= 600),
  facts_added integer not null default 0,
  chars_read integer not null default 0,
  truncated boolean not null default false,
  created_by uuid,
  created_at timestamptz not null default now()
);
create index if not exists brand_documents_client_idx on public.brand_documents (client_id, created_at desc);

alter table public.brand_knowledge enable row level security;
alter table public.brand_documents enable row level security;
revoke all on public.brand_knowledge from anon, authenticated;
revoke all on public.brand_documents from anon, authenticated;
grant all on public.brand_knowledge to service_role;
grant all on public.brand_documents to service_role;

notify pgrst, 'reload schema';
