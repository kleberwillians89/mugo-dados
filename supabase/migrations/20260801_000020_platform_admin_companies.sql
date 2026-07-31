-- Administração global da plataforma Mugô Dados.
-- Esta migration não concede privilégios de escrita a usuários autenticados:
-- as mutações são feitas exclusivamente pelo backend com service_role.

create table if not exists public.platform_admins (
  user_id uuid primary key references auth.users(id) on delete restrict,
  role text not null default 'platform_admin' check (role = 'platform_admin'),
  granted_by uuid references auth.users(id) on delete set null,
  granted_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

alter table public.platform_admins enable row level security;
revoke all on public.platform_admins from anon, authenticated;
grant select (user_id, role, granted_at) on public.platform_admins to authenticated;

drop policy if exists platform_admins_select_self on public.platform_admins;
create policy platform_admins_select_self on public.platform_admins
for select using (auth.uid() = user_id);

-- O primeiro administrador deve ser concedido explicitamente depois que o
-- usuário existir no Supabase Auth. Não vinculamos autorização a e-mail nem
-- gravamos UUID de pessoa/ambiente no histórico versionado.

create or replace function public.is_platform_admin(p_user_id uuid default auth.uid())
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.platform_admins
    where user_id = p_user_id and role = 'platform_admin'
  );
$$;
revoke all on function public.is_platform_admin(uuid) from public, anon;
grant execute on function public.is_platform_admin(uuid) to authenticated, service_role;

alter table public.clients
  add column if not exists trade_name text,
  add column if not exists cnpj text,
  add column if not exists responsible_email text,
  add column if not exists status text not null default 'active',
  add column if not exists created_by uuid references auth.users(id) on delete set null,
  add column if not exists updated_at timestamptz not null default now();

alter table public.clients drop constraint if exists clients_status_check;
alter table public.clients add constraint clients_status_check
  check (status in ('active', 'invitation_pending', 'inactive'));

create unique index if not exists clients_cnpj_uq
  on public.clients(cnpj) where cnpj is not null;

drop trigger if exists trg_clients_updated_at on public.clients;
create trigger trg_clients_updated_at
before update on public.clients
for each row execute function public.set_updated_at();

alter table public.client_memberships
  drop constraint if exists client_memberships_role_check;
alter table public.client_memberships
  add constraint client_memberships_role_check
  check (role in ('owner', 'agency_admin', 'client_admin', 'viewer'));

alter table public.user_invitations
  drop constraint if exists user_invitations_role_check;
alter table public.user_invitations
  add constraint user_invitations_role_check
  check (role in ('owner', 'agency_admin', 'client_admin', 'viewer'));

-- Complementa o trigger da migration 019: ao aceitar o primeiro convite,
-- a empresa deixa de ficar pendente sem alterar o fluxo de memberships.
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
  select * into invitation
  from public.user_invitations
  where lower(email) = lower(new.email)
    and accepted_at is null and revoked_at is null and expires_at > now()
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
  update public.clients
  set status = 'active'
  where id = invitation.client_id and status = 'invitation_pending';
  return new;
end;
$$;

create table if not exists public.platform_audit_events (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  client_id text references public.clients(id) on delete set null,
  event_type text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists platform_audit_actor_created_idx
  on public.platform_audit_events(actor_user_id, created_at desc);
create index if not exists platform_audit_client_created_idx
  on public.platform_audit_events(client_id, created_at desc);
alter table public.platform_audit_events enable row level security;
revoke all on public.platform_audit_events from anon, authenticated;

drop policy if exists clients_platform_admin_select on public.clients;
create policy clients_platform_admin_select on public.clients
for select using (public.is_platform_admin(auth.uid()));

create or replace function public.create_platform_company(
  p_actor_user_id uuid,
  p_name text,
  p_trade_name text,
  p_cnpj text,
  p_responsible_email text,
  p_token_hash text,
  p_expires_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_client public.clients%rowtype;
  v_invitation public.user_invitations%rowtype;
begin
  if not public.is_platform_admin(p_actor_user_id) then
    raise exception 'platform_admin_required' using errcode = '42501';
  end if;
  if length(trim(coalesce(p_name, ''))) < 2 then
    raise exception 'invalid_company_name' using errcode = '22023';
  end if;
  if position('@' in coalesce(p_responsible_email, '')) < 2 then
    raise exception 'invalid_responsible_email' using errcode = '22023';
  end if;

  insert into public.clients (
    name, trade_name, cnpj, responsible_email, status, created_by
  ) values (
    trim(p_name), nullif(trim(p_trade_name), ''), nullif(trim(p_cnpj), ''),
    lower(trim(p_responsible_email)), 'invitation_pending', p_actor_user_id
  )
  returning * into v_client;

  insert into public.user_invitations (
    email, client_id, role, token_hash, invited_by, expires_at
  ) values (
    lower(trim(p_responsible_email)), v_client.id, 'owner',
    p_token_hash, p_actor_user_id, p_expires_at
  )
  returning * into v_invitation;

  insert into public.platform_audit_events(actor_user_id, client_id, event_type, details)
  values (
    p_actor_user_id, v_client.id, 'company_created',
    jsonb_build_object('invitation_id', v_invitation.id, 'responsible_email', v_invitation.email)
  );

  return jsonb_build_object(
    'client', to_jsonb(v_client),
    'invitation', to_jsonb(v_invitation)
  );
end;
$$;

create or replace function public.rollback_platform_company_creation(
  p_actor_user_id uuid,
  p_client_id text,
  p_invitation_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_platform_admin(p_actor_user_id) then
    raise exception 'platform_admin_required' using errcode = '42501';
  end if;
  if exists (select 1 from public.client_memberships where client_id = p_client_id) then
    raise exception 'company_already_has_membership' using errcode = '23514';
  end if;
  delete from public.user_invitations
  where id = p_invitation_id and client_id = p_client_id and accepted_at is null;
  if not found then
    raise exception 'pending_invitation_not_found' using errcode = 'P0002';
  end if;
  delete from public.clients where id = p_client_id and created_by = p_actor_user_id;
  return found;
end;
$$;

create or replace function public.audit_platform_company_access(
  p_actor_user_id uuid,
  p_client_id text
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_platform_admin(p_actor_user_id) then
    raise exception 'platform_admin_required' using errcode = '42501';
  end if;
  if not exists (select 1 from public.clients where id = p_client_id) then
    raise exception 'company_not_found' using errcode = 'P0002';
  end if;
  insert into public.platform_audit_events(actor_user_id, client_id, event_type)
  values (p_actor_user_id, p_client_id, 'support_access_opened');
  return true;
end;
$$;

revoke all on function public.create_platform_company(uuid,text,text,text,text,text,timestamptz) from public, anon, authenticated;
revoke all on function public.rollback_platform_company_creation(uuid,text,uuid) from public, anon, authenticated;
revoke all on function public.audit_platform_company_access(uuid,text) from public, anon, authenticated;
grant execute on function public.create_platform_company(uuid,text,text,text,text,text,timestamptz) to service_role;
grant execute on function public.rollback_platform_company_creation(uuid,text,uuid) to service_role;
grant execute on function public.audit_platform_company_access(uuid,text) to service_role;
