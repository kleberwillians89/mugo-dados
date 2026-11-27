-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- CRM de criadores: status da negociação de cada criador com a empresa
-- (novo → contatado → em negociação → fechado / não fechou), motivo e data da mudança.
-- Quem já tem fechamento registrado nasce como "fechado".

alter table public.creator_media_kits
  add column if not exists status text not null default 'novo',
  add column if not exists status_note text,
  add column if not exists status_at timestamptz;

alter table public.creator_media_kits drop constraint if exists creator_media_kits_status_check;
alter table public.creator_media_kits add constraint creator_media_kits_status_check
  check (status in ('novo', 'contatado', 'negociando', 'fechado', 'nao_fechou'));
alter table public.creator_media_kits drop constraint if exists creator_media_kits_status_note_check;
alter table public.creator_media_kits add constraint creator_media_kits_status_note_check
  check (status_note is null or length(status_note) <= 500);

update public.creator_media_kits set status = 'fechado', status_at = coalesce(status_at, updated_at)
where status = 'novo' and jsonb_array_length(deals) > 0;

create index if not exists creator_media_kits_status_idx on public.creator_media_kits(client_id, status);

notify pgrst, 'reload schema';
