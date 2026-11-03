-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Engajamento no Instagram (tipo ManyChat): gatilhos por palavra-chave em comentários e o registro
-- de tudo que foi respondido (manual ou automático). Os comentários continuam em ig_comments
-- (sincronização existente). Nada aqui é lido pelo navegador: só o backend (service_role), papel de agência.

create table if not exists public.ig_engagement_rules (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(trim(name)) between 1 and 80),
  keywords text[] not null check (cardinality(keywords) between 1 and 20),
  media_id text check (media_id is null or media_id ~ '^[0-9]{5,40}$'),
  public_reply text check (public_reply is null or length(public_reply) between 1 and 300),
  dm_message text check (dm_message is null or length(dm_message) between 1 and 1000),
  active boolean not null default false,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (public_reply is not null or dm_message is not null)
);
create index if not exists ig_engagement_rules_client_idx on public.ig_engagement_rules (client_id) where active;

create table if not exists public.ig_engagement_actions (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  comment_id text not null check (comment_id ~ '^[0-9]{5,40}$'),
  media_id text,
  rule_id uuid references public.ig_engagement_rules(id) on delete set null,
  kind text not null check (kind in ('resposta_publica', 'direct', 'resposta_manual')),
  status text not null check (status in ('enviado', 'simulado', 'falhou')),
  text text not null check (length(text) between 1 and 1000),
  error text check (error is null or length(error) <= 200),
  external_id text,
  actor text,
  created_at timestamptz not null default now()
);
-- Um gatilho responde cada comentário uma vez só (por tipo), mesmo que o job rode de novo.
create unique index if not exists ig_engagement_actions_once_idx
  on public.ig_engagement_actions (client_id, comment_id, kind, coalesce(rule_id::text, 'manual'))
  where status in ('enviado', 'simulado');
create index if not exists ig_engagement_actions_client_idx on public.ig_engagement_actions (client_id, created_at desc);

alter table public.ig_engagement_rules enable row level security;
alter table public.ig_engagement_actions enable row level security;
revoke all on public.ig_engagement_rules, public.ig_engagement_actions from anon, authenticated;
