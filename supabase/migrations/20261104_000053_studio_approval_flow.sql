-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
--
-- Mugô Studio: menu Aprovação (funil, pedidos, contatos) + mensagens pelo
-- WhatsApp oficial da Mugô (MugôZap, no CRM).
--
-- 1) Pauta ganha o status "publicado" (última coluna do funil) e published_at.
-- 2) studio_client_contacts: quem aprova/recebe em cada cliente e o que recebe
--    (conteúdo, tráfego pago, resultados). Um contato principal por cliente.
-- 3) studio_messages: histórico de cada mensagem (enviada pelo MugôZap ou
--    link wa.me gerado). Telefone só mascarado; idempotency_key única para
--    nunca reenviar a mesma mensagem por engano.
-- 4) studio_approval_requests.token_ciphertext: o link continua validado pelo
--    hash; o token cifrado (Fernet, chave só no backend) permite reenviar o
--    MESMO link num lembrete. Tabela sem acesso do browser.
--
-- Envio de WhatsApp continua no CRM: o Dados só chama o mugozap-api.

alter table public.studio_calendar_items drop constraint if exists studio_calendar_items_status_check;
alter table public.studio_calendar_items add constraint studio_calendar_items_status_check
  check (status in ('rascunho', 'em_revisao', 'aprovado', 'rejeitado', 'publicado'));
alter table public.studio_calendar_items add column if not exists published_at timestamptz;

alter table public.studio_approval_requests add column if not exists token_ciphertext text;
alter table public.studio_approval_requests add column if not exists contact_id uuid;
alter table public.studio_approval_requests add column if not exists last_reminded_at timestamptz;

create table if not exists public.studio_client_contacts (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(trim(name)) between 1 and 120),
  phone text not null check (phone ~ '^[0-9]{10,15}$'),
  role text check (role is null or length(role) <= 80),
  receives text[] not null default array['conteudo']::text[]
    check (receives <@ array['conteudo', 'trafego', 'resultados']::text[]),
  is_primary boolean not null default false,
  active boolean not null default true,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, phone)
);

create unique index if not exists studio_client_contacts_primary_idx
  on public.studio_client_contacts (client_id) where is_primary and active;

alter table public.studio_client_contacts enable row level security;
revoke all on public.studio_client_contacts from anon, authenticated;
grant select on public.studio_client_contacts to authenticated;
grant all on public.studio_client_contacts to service_role;
drop policy if exists studio_client_contacts_member_read on public.studio_client_contacts;
create policy studio_client_contacts_member_read on public.studio_client_contacts
  for select to authenticated using (public.is_client_member(client_id));
drop trigger if exists studio_client_contacts_updated_at on public.studio_client_contacts;
create trigger studio_client_contacts_updated_at before update on public.studio_client_contacts
  for each row execute function public.set_updated_at();

create table if not exists public.studio_messages (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  contact_id uuid references public.studio_client_contacts(id) on delete set null,
  contact_name text check (contact_name is null or length(contact_name) <= 120),
  phone_masked text check (phone_masked is null or length(phone_masked) <= 20),
  kind text not null check (kind in ('aprovacao', 'lembrete', 'agenda', 'trafego', 'resultados')),
  template_name text check (template_name is null or template_name ~ '^[a-z0-9_]{1,100}$'),
  channel text not null check (channel in ('mugozap', 'wa_link')),
  status text not null check (status in ('enviado', 'falhou', 'link_gerado')),
  error_code text check (error_code is null or length(error_code) <= 80),
  request_id uuid references public.studio_approval_requests(id) on delete set null,
  idempotency_key text not null unique check (length(idempotency_key) between 16 and 120),
  provider_message_id text check (provider_message_id is null or length(provider_message_id) <= 200),
  preview jsonb not null default '{}'::jsonb,
  sent_by text,
  created_at timestamptz not null default now()
);

create index if not exists studio_messages_client_idx on public.studio_messages (client_id, created_at desc);

alter table public.studio_messages enable row level security;
revoke all on public.studio_messages from anon, authenticated;
grant select on public.studio_messages to authenticated;
grant all on public.studio_messages to service_role;
drop policy if exists studio_messages_member_read on public.studio_messages;
create policy studio_messages_member_read on public.studio_messages
  for select to authenticated using (public.is_client_member(client_id));

notify pgrst, 'reload schema';
