-- Autenticação por convite e OAuth multiempresa.
-- Idempotente, sem usuários, memberships ou credenciais embutidas.

create table if not exists public.user_invitations (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  client_id text not null references public.clients(id) on delete restrict,
  role text not null check (role in ('agency_admin', 'client_admin', 'viewer')),
  token_hash text not null unique,
  invited_by uuid not null,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  accepted_by uuid,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists user_invitations_client_email_idx
  on public.user_invitations(client_id, lower(email), created_at desc);
alter table public.user_invitations enable row level security;

create table if not exists public.oauth_sessions (
  id uuid primary key default gen_random_uuid(),
  provider text not null check (provider in ('meta', 'google', 'shopify')),
  state_hash text not null unique,
  nonce_hash text not null,
  user_id uuid not null,
  client_id text not null references public.clients(id) on delete restrict,
  redirect_uri text not null,
  context jsonb not null default '{}'::jsonb,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists oauth_sessions_expiry_idx on public.oauth_sessions(expires_at);
alter table public.oauth_sessions enable row level security;

alter table public.integration_connections
  add column if not exists external_key text,
  add column if not exists encrypted_token text,
  add column if not exists scopes text[] not null default '{}',
  add column if not exists connected_by uuid,
  add column if not exists disconnected_at timestamptz;

alter table public.integration_connections
  drop constraint if exists integration_connections_status_check;
alter table public.integration_connections
  add constraint integration_connections_status_check check (
    status in (
      'not_configured', 'awaiting_authorization', 'selection_required', 'connecting',
      'importing', 'connected', 'updated', 'stale', 'token_expired',
      'reauth_required', 'sync_error', 'disconnected'
    )
  );

create unique index if not exists integration_connections_external_key_uq
  on public.integration_connections(client_id, provider, external_key)
  where external_key is not null;

create table if not exists public.connection_audit_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete restrict,
  connection_id uuid,
  user_id uuid,
  event_type text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists connection_audit_client_created_idx
  on public.connection_audit_events(client_id, created_at desc);
alter table public.connection_audit_events enable row level security;
drop policy if exists connection_audit_member_select on public.connection_audit_events;
create policy connection_audit_member_select on public.connection_audit_events
for select using (public.is_client_member(client_id));

create table if not exists public.sync_checkpoints (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete restrict,
  connection_id uuid not null,
  resource text not null,
  cursor_value text,
  checkpoint jsonb not null default '{}'::jsonb,
  last_success_at timestamptz,
  last_attempt_at timestamptz,
  retry_count integer not null default 0,
  next_retry_at timestamptz,
  last_error text,
  updated_at timestamptz not null default now(),
  unique(client_id, connection_id, resource)
);
alter table public.sync_checkpoints enable row level security;
drop policy if exists sync_checkpoints_member_select on public.sync_checkpoints;
create policy sync_checkpoints_member_select on public.sync_checkpoints
for select using (public.is_client_member(client_id));

create table if not exists public.shopify_stores (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete restrict,
  connection_id uuid not null,
  shop_id text,
  shop_domain text not null unique,
  shop_name text,
  currency text,
  timezone text,
  status text not null default 'active',
  installed_at timestamptz not null default now(),
  uninstalled_at timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists shopify_stores_client_idx on public.shopify_stores(client_id, updated_at desc);
alter table public.shopify_stores enable row level security;
drop policy if exists shopify_stores_member_select on public.shopify_stores;
create policy shopify_stores_member_select on public.shopify_stores
for select using (public.is_client_member(client_id));

revoke all on public.oauth_sessions, public.user_invitations from anon, authenticated;
revoke all on public.integration_connections from anon, authenticated;
grant select (
  id, client_id, provider, status, account_id, account_name, token_expires_at,
  last_sync_at, next_sync_at, historical_start, historical_end, last_error,
  metadata, created_at, updated_at, external_key, scopes, disconnected_at
) on public.integration_connections to authenticated;

create or replace function public.accept_pending_user_invitation()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  invitation public.user_invitations%rowtype;
begin
  if tg_op = 'UPDATE' and old.email_confirmed_at is not null then
    return new;
  end if;
  select *
  into invitation
  from public.user_invitations
  where lower(email) = lower(new.email)
    and accepted_at is null
    and revoked_at is null
    and expires_at > now()
  order by created_at desc
  for update skip locked
  limit 1;

  if invitation.id is null then
    return new;
  end if;

  insert into public.client_memberships(user_id, client_id, role)
  values(new.id, invitation.client_id, invitation.role)
  on conflict(user_id, client_id) do update set role = excluded.role;

  update public.user_invitations
  set accepted_at = now(), accepted_by = new.id
  where id = invitation.id and accepted_at is null;
  return new;
end;
$$;

drop trigger if exists on_auth_user_accept_invitation on auth.users;
create trigger on_auth_user_accept_invitation
after insert or update of email_confirmed_at on auth.users
for each row
when (new.email_confirmed_at is not null)
execute function public.accept_pending_user_invitation();
