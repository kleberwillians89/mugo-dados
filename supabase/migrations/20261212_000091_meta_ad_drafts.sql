-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Mídia On publica campanhas no Meta Ads. Cada rascunho guarda a campanha completa (objetivo, verba,
-- período, público, texto e criativo) e, depois de publicado, os ids criados no Meta. Tudo é criado
-- PAUSADO: a equipe confere no Gerenciador de Anúncios e ativa. Só o backend (service_role) lê e grava.

create table if not exists public.studio_ad_drafts (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month date,
  source_campaign text check (source_campaign is null or length(source_campaign) <= 200),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'rascunho' check (status in ('rascunho', 'publicando', 'publicada', 'erro')),
  meta_ids jsonb not null default '{}'::jsonb,
  error text check (error is null or length(error) <= 600),
  created_by uuid,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_ad_drafts_client_idx on public.studio_ad_drafts (client_id, created_at desc);

alter table public.studio_ad_drafts enable row level security;
revoke all on public.studio_ad_drafts from anon, authenticated;
grant all on public.studio_ad_drafts to service_role;

notify pgrst, 'reload schema';
