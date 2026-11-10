-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Direct do Instagram no MUGOVERSO (sem ManyChat): o webhook do Instagram (Edge Function instagram-webhook)
-- grava cada mensagem; o backend manda o oi no primeiro Direct (pode ser só para quem segue o perfil) e,
-- se a marca ligar, a IA responde o Direct no tom da marca. Equipe respondeu pelo app → a IA para naquela conversa.
-- Só o backend e a Edge Function (service_role) leem e gravam.

create table if not exists public.ig_dm_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  welcome_enabled boolean not null default false,
  welcome_followers_only boolean not null default true,
  welcome_content text check (welcome_content is null or length(welcome_content) <= 1000),
  ai_enabled boolean not null default false,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.ig_dm_messages (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  ig_user_id text not null,
  sender_id text not null,
  mid text not null unique,
  direction text not null check (direction in ('in', 'out')),
  text text check (text is null or length(text) <= 2000),
  by_app boolean not null default false,
  status text not null default 'registrado'
    check (status in ('registrado', 'pendente', 'processando', 'respondido', 'simulado', 'revisao', 'ignorado', 'falhou')),
  reply_kind text check (reply_kind is null or reply_kind in ('oi', 'ia')),
  follows boolean,
  username text check (username is null or length(username) <= 120),
  error text check (error is null or length(error) <= 300),
  created_at timestamptz not null default now(),
  processed_at timestamptz
);
create index if not exists ig_dm_messages_thread_idx on public.ig_dm_messages (client_id, sender_id, created_at desc);
create index if not exists ig_dm_messages_pending_idx on public.ig_dm_messages (status, created_at) where status = 'pendente';

alter table public.ig_dm_settings enable row level security;
alter table public.ig_dm_messages enable row level security;
revoke all on public.ig_dm_settings from anon, authenticated;
revoke all on public.ig_dm_messages from anon, authenticated;
grant all on public.ig_dm_settings to service_role;
grant all on public.ig_dm_messages to service_role;

notify pgrst, 'reload schema';
