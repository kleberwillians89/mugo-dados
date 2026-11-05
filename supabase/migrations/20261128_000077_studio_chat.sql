-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Conversa da marca no Calendário: canal "cliente" (cliente + equipe Mugô) e canal "equipe" (só Mugô).
-- Mensagem pode citar um post do calendário. Leituras guardam até onde cada pessoa leu (contador de não lidas).
create table if not exists public.studio_chat_messages (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  channel text not null check (channel in ('cliente', 'equipe')),
  author_id uuid,
  author_side text not null check (author_side in ('cliente', 'mugo')),
  author_name text check (author_name is null or length(author_name) <= 80),
  body text not null check (length(body) between 1 and 4000),
  item_id uuid references public.studio_calendar_items(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists studio_chat_messages_client_idx on public.studio_chat_messages (client_id, channel, created_at desc);

create table if not exists public.studio_chat_reads (
  user_id uuid not null,
  client_id text not null references public.clients(id) on delete cascade,
  channel text not null check (channel in ('cliente', 'equipe')),
  last_read_at timestamptz not null default now(),
  primary key (user_id, client_id, channel)
);

alter table public.studio_chat_messages enable row level security;
alter table public.studio_chat_reads enable row level security;
revoke all on public.studio_chat_messages from anon, authenticated;
revoke all on public.studio_chat_reads from anon, authenticated;
grant all on public.studio_chat_messages to service_role;
grant all on public.studio_chat_reads to service_role;

notify pgrst, 'reload schema';
