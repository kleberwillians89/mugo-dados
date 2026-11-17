-- LOCAL: NÃO APLICADA. Aplicação manual após revisão/homologação.
-- Listas internas do Relacionamento: dados minimizados, sem e-mail/telefone em claro.
-- Pertencer à lista NÃO comprova consentimento. O envio exige opt-in verificado na fonte.
create table if not exists public.relationship_lists (
  id uuid not null default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(name) between 1 and 100),
  description text check (description is null or length(description) <= 300),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (id),
  unique (id, client_id)
);
create index if not exists relationship_lists_tenant_idx on public.relationship_lists(client_id, created_at desc);

create table if not exists public.relationship_list_members (
  client_id text not null references public.clients(id) on delete cascade,
  list_id uuid not null,
  email_hash text not null check (length(email_hash) = 32),
  added_at timestamptz not null default now(),
  primary key (client_id, list_id, email_hash),
  foreign key (list_id, client_id) references public.relationship_lists(id, client_id) on delete cascade
);
create index if not exists relationship_members_tenant_email_idx
  on public.relationship_list_members(client_id, email_hash);

alter table public.relationship_lists enable row level security;
alter table public.relationship_list_members enable row level security;
revoke all on public.relationship_lists, public.relationship_list_members from anon, authenticated;
grant all on public.relationship_lists, public.relationship_list_members to service_role;
notify pgrst, 'reload schema';
