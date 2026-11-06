-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- 1) Histórico de cada pauta (kanban interno): quem fez o quê e quando.
-- 2) Colaboradores do post no Instagram (até 3 @, publicados junto com o post).
create table if not exists public.studio_item_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  item_id uuid not null references public.studio_calendar_items(id) on delete cascade,
  action text not null check (length(action) between 1 and 200),
  actor_name text check (actor_name is null or length(actor_name) <= 80),
  actor_side text not null default 'mugo' check (actor_side in ('mugo', 'cliente', 'sistema')),
  actor_id uuid,
  detail text check (detail is null or length(detail) <= 1000),
  created_at timestamptz not null default now()
);
create index if not exists studio_item_events_item_idx on public.studio_item_events (item_id, created_at desc);
create index if not exists studio_item_events_client_idx on public.studio_item_events (client_id, created_at desc);
alter table public.studio_item_events enable row level security;
revoke all on public.studio_item_events from anon, authenticated;
grant all on public.studio_item_events to service_role;

alter table public.studio_calendar_items add column if not exists collaborators text[] not null default '{}'::text[];
alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_collaborators_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_collaborators_check
  check (cardinality(collaborators) <= 3);

notify pgrst, 'reload schema';
