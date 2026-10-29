-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Aprovação do CLIENTE por link (sem login), fase 1 do fluxo de aprovação.
--
-- A equipe escolhe as pautas e gera um link. O cliente abre, vê só aquelas
-- pautas e aprova ou pede ajuste em cada uma. O link é um token aleatório de
-- 32 bytes; o banco guarda apenas o hash SHA-256 (quem lê a tabela não
-- consegue montar o link). Expira em 14 dias e pode ser cancelado.
--
-- Nenhuma tabela é lida pelo browser: tudo passa pelo backend, inclusive a
-- página pública, que só recebe os campos editoriais das pautas do pedido.

create table if not exists public.studio_approval_requests (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  month date not null,
  token_hash text not null unique check (length(token_hash) = 64),
  item_ids uuid[] not null check (cardinality(item_ids) between 1 and 200),
  contact_name text check (contact_name is null or length(contact_name) <= 120),
  contact_phone text check (contact_phone is null or contact_phone ~ '^[0-9]{10,15}$'),
  message text check (message is null or length(message) <= 1000),
  status text not null default 'aberto' check (status in ('aberto', 'concluido', 'cancelado')),
  expires_at timestamptz not null,
  created_by text not null,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists studio_approval_requests_client_idx
  on public.studio_approval_requests (client_id, created_at desc);

create table if not exists public.studio_approval_events (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.studio_approval_requests(id) on delete cascade,
  client_id text not null references public.clients(id) on delete cascade,
  item_id uuid not null references public.studio_calendar_items(id) on delete cascade,
  action text not null check (action in ('aprovado', 'ajuste_solicitado')),
  comment text check (comment is null or length(comment) <= 1000),
  reviewer_name text check (reviewer_name is null or length(reviewer_name) <= 120),
  created_at timestamptz not null default now()
);

create index if not exists studio_approval_events_item_idx
  on public.studio_approval_events (item_id, created_at desc);

alter table public.studio_approval_requests enable row level security;
alter table public.studio_approval_events enable row level security;
revoke all on public.studio_approval_requests from anon, authenticated;
revoke all on public.studio_approval_events from anon, authenticated;
grant all on public.studio_approval_requests to service_role;
grant all on public.studio_approval_events to service_role;

drop trigger if exists studio_approval_requests_updated_at on public.studio_approval_requests;
create trigger studio_approval_requests_updated_at before update on public.studio_approval_requests
  for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
