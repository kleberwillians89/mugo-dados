-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Social Media → Redação (trazida da iAgência): editor de texto estilo Word por marca.
-- Cada documento guarda o HTML do editor (formatação) e o texto puro (busca, IA e Calendário).
-- Mesmo padrão das tabelas do Studio: RLS ligado, só o service_role (backend) lê e grava,
-- e o backend sempre filtra por client_id.

create table if not exists public.studio_documents (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  title text not null check (length(title) between 1 and 200),
  kind text not null default 'livre'
    check (kind in ('livre', 'post', 'legenda', 'roteiro', 'artigo', 'email', 'release', 'campanha')),
  content_html text not null default '' check (length(content_html) <= 300000),
  content_text text not null default '' check (length(content_text) <= 100000),
  status text not null default 'rascunho' check (status in ('rascunho', 'arquivado')),
  calendar_item_id uuid references public.studio_calendar_items(id) on delete set null,
  created_by uuid,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_documents_client_idx on public.studio_documents (client_id, updated_at desc);

alter table public.studio_documents enable row level security;
revoke all on public.studio_documents from anon, authenticated;
grant all on public.studio_documents to service_role;

notify pgrst, 'reload schema';
