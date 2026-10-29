-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Mugô Studio, fase 1: perfil de marca + calendário editorial.
--
-- studio_brand_profiles: o "DNA" que o iAgência guardava em arquivos no disco
-- do Render (apagado a cada deploy). Uma linha por empresa, em jsonb para
-- acompanhar pilares, tom, hashtags e datas próprias sem migration nova.
--
-- studio_calendar_items: cada post planejado. Nasce como "rascunho" (IA ou
-- manual), passa por revisão humana e só então vira "aprovado". Nada aqui
-- publica em rede social.
--
-- Browser só lê (membros da empresa). Toda escrita passa pelo backend, que
-- aplica papel e empresa — mesma linha de client_goals.

create table if not exists public.studio_brand_profiles (
  client_id text primary key references public.clients(id) on delete cascade,
  profile jsonb not null default '{}'::jsonb,
  updated_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.studio_brand_profiles enable row level security;
revoke all on public.studio_brand_profiles from anon, authenticated;
grant select on public.studio_brand_profiles to authenticated;
grant all on public.studio_brand_profiles to service_role;
drop policy if exists studio_brand_profiles_member_read on public.studio_brand_profiles;
create policy studio_brand_profiles_member_read on public.studio_brand_profiles
  for select to authenticated using (public.is_client_member(client_id));
drop trigger if exists studio_brand_profiles_updated_at on public.studio_brand_profiles;
create trigger studio_brand_profiles_updated_at before update on public.studio_brand_profiles
  for each row execute function public.set_updated_at();

create table if not exists public.studio_calendar_items (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month date not null check (extract(day from month) = 1),
  scheduled_at timestamptz not null,
  channel text not null default 'instagram' check (channel in ('instagram')),
  format text not null check (format in ('reels', 'carrossel', 'imagem', 'stories', 'video')),
  pillar text check (pillar is null or length(pillar) <= 120),
  title text not null check (length(trim(title)) between 1 and 200),
  hook text check (hook is null or length(hook) <= 400),
  caption_draft text check (caption_draft is null or length(caption_draft) <= 4000),
  rationale text check (rationale is null or length(rationale) <= 1200),
  signals jsonb not null default '{}'::jsonb,
  status text not null default 'rascunho'
    check (status in ('rascunho', 'em_revisao', 'aprovado', 'rejeitado')),
  review_note text check (review_note is null or length(review_note) <= 1000),
  origin text not null default 'manual' check (origin in ('ia', 'manual')),
  batch_id uuid,
  created_by text,
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists studio_calendar_items_client_month_idx
  on public.studio_calendar_items (client_id, month, scheduled_at);

alter table public.studio_calendar_items enable row level security;
revoke all on public.studio_calendar_items from anon, authenticated;
grant select on public.studio_calendar_items to authenticated;
grant all on public.studio_calendar_items to service_role;
drop policy if exists studio_calendar_items_member_read on public.studio_calendar_items;
create policy studio_calendar_items_member_read on public.studio_calendar_items
  for select to authenticated using (public.is_client_member(client_id));
drop trigger if exists studio_calendar_items_updated_at on public.studio_calendar_items;
create trigger studio_calendar_items_updated_at before update on public.studio_calendar_items
  for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
