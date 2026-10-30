-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Clipping da marca e Redação de campanha (trazidos do iAgência). Só a equipe Mugô usa:
-- as tabelas ficam fechadas para authenticated; o acesso é só pela API (service_role),
-- que exige agency_admin.
--
-- studio_clipping_settings: termos da marca, dos concorrentes e palavras para ignorar.
-- studio_clippings: notícias do Google Notícias (feed público), uma vez cada (url_hash),
--   com a leitura da IA (sentimento, resumo de 1 linha, relevância) e o que virou pauta.
-- studio_campaigns: briefing + pacote de peças gerado pela IA e editado pela equipe.

create table if not exists public.studio_clipping_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  brand_terms text[] not null default '{}',
  competitor_terms text[] not null default '{}',
  exclude_terms text[] not null default '{}',
  active boolean not null default true,
  last_run_at timestamptz,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.studio_clippings (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  url text not null check (length(url) <= 2000),
  url_hash text not null check (length(url_hash) = 40),
  title text not null check (length(title) between 1 and 400),
  source text check (source is null or length(source) <= 160),
  published_at timestamptz,
  kind text not null check (kind in ('marca', 'concorrente')),
  term text not null check (length(term) between 1 and 120),
  sentiment text check (sentiment is null or sentiment in ('positivo', 'neutro', 'negativo')),
  summary text check (summary is null or length(summary) <= 300),
  relevant boolean,
  status text not null default 'novo' check (status in ('novo', 'lido', 'arquivado', 'pauta')),
  calendar_item_id uuid references public.studio_calendar_items(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (client_id, url_hash)
);
create index if not exists studio_clippings_client_idx on public.studio_clippings (client_id, published_at desc nulls last);

create table if not exists public.studio_campaigns (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(name) between 1 and 160),
  briefing jsonb not null default '{}'::jsonb,
  package jsonb not null default '{}'::jsonb,
  status text not null default 'rascunho' check (status in ('rascunho', 'pronta', 'arquivada')),
  calendar_item_ids uuid[] not null default '{}',
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_campaigns_client_idx on public.studio_campaigns (client_id, created_at desc);

alter table public.studio_clipping_settings enable row level security;
alter table public.studio_clippings enable row level security;
alter table public.studio_campaigns enable row level security;
revoke all on public.studio_clipping_settings, public.studio_clippings, public.studio_campaigns from anon, authenticated;
grant all on public.studio_clipping_settings, public.studio_clippings, public.studio_campaigns to service_role;

notify pgrst, 'reload schema';
