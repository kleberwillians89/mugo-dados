-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Comentários nos posts do Calendário. Qualquer pessoa da empresa (inclusive o leitor) comenta no
-- post que vê; a equipe Mugô responde no mesmo lugar. Comentário do cliente vira aviso ao time
-- (studio_team_events, ação "comentario": tarefa no CRM + WhatsApp do time).
-- Acesso só pela API (service_role): o cliente só lê/escreve nos posts que pode ver.

create table if not exists public.studio_item_comments (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  item_id uuid not null references public.studio_calendar_items(id) on delete cascade,
  author_id uuid,
  author_side text not null check (author_side in ('cliente', 'mugo')),
  author_name text check (author_name is null or length(author_name) <= 120),
  body text not null check (length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index if not exists studio_item_comments_item_idx on public.studio_item_comments (client_id, item_id, created_at);
alter table public.studio_item_comments enable row level security;
revoke all on public.studio_item_comments from anon, authenticated;
grant all on public.studio_item_comments to service_role;

alter table public.studio_team_events drop constraint if exists studio_team_events_action_check;
alter table public.studio_team_events add constraint studio_team_events_action_check
  check (action in ('aprovado', 'ajuste_solicitado', 'editado_pelo_cliente', 'comentario'));

notify pgrst, 'reload schema';
