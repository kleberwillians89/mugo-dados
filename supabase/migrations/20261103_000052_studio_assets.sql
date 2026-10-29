-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Mugô Studio, fase 3: Biblioteca de mídia + arte anexada à pauta.
--
-- Bucket studio-assets: PRIVADO. Sem policy em storage.objects, então nem
-- anon nem authenticated leem ou gravam direto; só o backend (service_role).
-- O arquivo não passa pelo Render: o backend gera uma URL assinada de upload,
-- o navegador envia direto ao bucket e o backend confere o objeto depois.
-- Leitura só por URL assinada de curta duração gerada pelo backend.
-- O teto do bucket (200 MB) é o do vídeo; imagem (15 MB) e PDF (30 MB) têm
-- teto menor aplicado pelo backend. O limite global de upload do projeto
-- (Storage → Settings) precisa ser >= 200 MB.
--
-- studio_assets: um arquivo da biblioteca. Nasce "pendente" quando a URL de
-- upload é emitida e só vira "pronto" depois que o backend lê o objeto real
-- (existe, tamanho, tipo, assinatura dos primeiros bytes). Pendentes com mais
-- de 24 h são apagados pelo job studio-assets-cleanup (GitHub Actions).
--
-- studio_calendar_item_assets: 1..N mídias por pauta; position = ordem dos
-- slides do carrossel.
--
-- Browser só lê (membros da empresa). Toda escrita passa pelo backend.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'studio-assets', 'studio-assets', false, 209715200,
  array['image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'video/quicktime', 'application/pdf']
)
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

create table if not exists public.studio_assets (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  storage_path text not null unique,
  thumb_path text,
  kind text not null check (kind in ('imagem', 'video', 'pdf')),
  mime_type text not null
    check (mime_type in ('image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'video/quicktime', 'application/pdf')),
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 209715200),
  name text not null check (length(trim(name)) between 1 and 160),
  folder text check (folder is null or length(folder) <= 80),
  tags text[] not null default '{}'::text[] check (cardinality(tags) <= 20),
  width integer check (width is null or width between 1 and 20000),
  height integer check (height is null or height between 1 and 20000),
  duration_seconds numeric(8, 2) check (duration_seconds is null or duration_seconds >= 0),
  status text not null default 'pendente' check (status in ('pendente', 'pronto')),
  created_by text,
  confirmed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists studio_assets_client_status_idx
  on public.studio_assets (client_id, status, created_at desc);

alter table public.studio_assets enable row level security;
revoke all on public.studio_assets from anon, authenticated;
grant select on public.studio_assets to authenticated;
grant all on public.studio_assets to service_role;
drop policy if exists studio_assets_member_read on public.studio_assets;
create policy studio_assets_member_read on public.studio_assets
  for select to authenticated using (public.is_client_member(client_id));
drop trigger if exists studio_assets_updated_at on public.studio_assets;
create trigger studio_assets_updated_at before update on public.studio_assets
  for each row execute function public.set_updated_at();

create table if not exists public.studio_calendar_item_assets (
  item_id uuid not null references public.studio_calendar_items(id) on delete cascade,
  asset_id uuid not null references public.studio_assets(id) on delete cascade,
  client_id text not null references public.clients(id) on delete cascade,
  position smallint not null check (position between 0 and 19),
  created_at timestamptz not null default now(),
  primary key (item_id, asset_id)
);

create index if not exists studio_calendar_item_assets_asset_idx
  on public.studio_calendar_item_assets (asset_id);
create index if not exists studio_calendar_item_assets_client_idx
  on public.studio_calendar_item_assets (client_id, item_id, position);

alter table public.studio_calendar_item_assets enable row level security;
revoke all on public.studio_calendar_item_assets from anon, authenticated;
grant select on public.studio_calendar_item_assets to authenticated;
grant all on public.studio_calendar_item_assets to service_role;
drop policy if exists studio_calendar_item_assets_member_read on public.studio_calendar_item_assets;
create policy studio_calendar_item_assets_member_read on public.studio_calendar_item_assets
  for select to authenticated using (public.is_client_member(client_id));

notify pgrst, 'reload schema';
