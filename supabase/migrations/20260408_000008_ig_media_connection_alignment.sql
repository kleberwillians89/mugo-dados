-- Legacy alignment: ig_media com escopo por connection_id
-- Objetivo:
-- 1) adicionar connection_id para leitura/sync por conexão
-- 2) manter compatibilidade com dados existentes
-- 3) melhorar performance de filtros client_id + connection_id + timestamp

alter table if exists public.ig_media
  add column if not exists connection_id uuid;

do $$
begin
  if to_regclass('public.ig_media') is not null then
    if not exists (
      select 1
      from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'ig_media'
        and c.contype = 'f'
        and pg_get_constraintdef(c.oid) ilike '%foreign key (connection_id)%references public.meta_connections(id)%'
    ) then
      alter table public.ig_media
        add constraint fk_ig_media_connection_id
        foreign key (connection_id) references public.meta_connections(id) on delete cascade not valid;
    end if;
  end if;
end $$;

create index if not exists idx_ig_media_connection_ts
  on public.ig_media(connection_id, timestamp desc);

create index if not exists idx_ig_media_client_connection_ts
  on public.ig_media(client_id, connection_id, timestamp desc);

-- Backfill seguro: só preenche quando o cliente possui exatamente 1 conexão orgânica.
with single_organic_connection as (
  select
    mc.client_id,
    max(mc.id) as connection_id
  from public.meta_connections mc
  where mc.platform = 'instagram'
    and mc.connection_type = 'organic'
  group by mc.client_id
  having count(*) = 1
)
update public.ig_media m
set connection_id = s.connection_id
from single_organic_connection s
where m.client_id = s.client_id
  and m.connection_id is null;

notify pgrst, 'reload schema';
