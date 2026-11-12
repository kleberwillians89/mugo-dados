-- LOCAL ONLY — do not apply remotely until PR approval.
-- Tenant-scoped commercial selections; not referenced by access guards.
create table if not exists public.tenant_commercial_modules (
  client_id text primary key references public.clients(id) on delete cascade,
  module_keys jsonb not null default '[]'::jsonb
    check (jsonb_typeof(module_keys) = 'array'),
  version bigint not null default 1 check (version > 0),
  updated_by uuid not null references auth.users(id) on delete restrict,
  updated_at timestamptz not null default now()
);

create table if not exists public.tenant_commercial_module_audit (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  previous_module_keys jsonb,
  module_keys jsonb not null,
  previous_version bigint,
  version bigint not null,
  changed_at timestamptz not null default now()
);
create index if not exists tenant_commercial_module_audit_history_idx
  on public.tenant_commercial_module_audit(client_id, changed_at desc);

alter table public.tenant_commercial_modules enable row level security;
alter table public.tenant_commercial_module_audit enable row level security;
revoke all on public.tenant_commercial_modules, public.tenant_commercial_module_audit from anon, authenticated;
grant select, insert, update, delete on public.tenant_commercial_modules to service_role;
grant select, insert on public.tenant_commercial_module_audit to service_role;

-- Single transaction: optimistic concurrency check, write and audit.
-- RPC is only callable with the backend service role; actor is additionally verified.
create or replace function public.save_tenant_commercial_modules(
  p_client_id text,
  p_module_keys jsonb,
  p_expected_version bigint,
  p_actor_user_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_existing public.tenant_commercial_modules%rowtype;
  v_saved public.tenant_commercial_modules%rowtype;
begin
  if not (
    public.is_platform_admin(p_actor_user_id)
    or exists (select 1 from public.client_memberships where user_id = p_actor_user_id and role = 'agency_admin')
  ) then
    raise exception 'commercial_admin_required' using errcode = '42501';
  end if;
  if not exists (select 1 from public.clients where id = p_client_id) then
    raise exception 'commercial_client_not_found' using errcode = 'P0002';
  end if;
  if p_module_keys is null or jsonb_typeof(p_module_keys) <> 'array'
    or exists (
      select 1 from jsonb_array_elements(p_module_keys) as item
      where jsonb_typeof(item) <> 'string'
         or trim(both '"' from item::text) not in (
           'social_media','meta','google','ecommerce','crm','whatsapp',
           'email_marketing','media','engagement','clipping','benchmark',
           'reports','planning','creators'
         )
    )
    or (select count(*) from jsonb_array_elements_text(p_module_keys)) <>
       (select count(distinct key) from jsonb_array_elements_text(p_module_keys) as key)
  then
    raise exception 'commercial_modules_invalid' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_client_id, 2081));
  select * into v_existing from public.tenant_commercial_modules
    where client_id = p_client_id for update;
  if found then
    if p_expected_version is distinct from v_existing.version then
      raise exception 'commercial_config_conflict' using errcode = 'P0001';
    end if;
    update public.tenant_commercial_modules
       set module_keys = p_module_keys, version = v_existing.version + 1,
           updated_by = p_actor_user_id, updated_at = now()
     where client_id = p_client_id returning * into v_saved;
  else
    if p_expected_version is not null then
      raise exception 'commercial_config_conflict' using errcode = 'P0001';
    end if;
    insert into public.tenant_commercial_modules(client_id, module_keys, updated_by)
      values (p_client_id, p_module_keys, p_actor_user_id)
      returning * into v_saved;
  end if;
  insert into public.tenant_commercial_module_audit
    (client_id, actor_user_id, previous_module_keys, module_keys, previous_version, version)
  values (p_client_id, p_actor_user_id,
          case when v_existing.client_id is null then null else v_existing.module_keys end,
          v_saved.module_keys,
          case when v_existing.client_id is null then null else v_existing.version end,
          v_saved.version);
  return to_jsonb(v_saved);
end;
$$;
revoke all on function public.save_tenant_commercial_modules(text,jsonb,bigint,uuid) from public, anon, authenticated;
grant execute on function public.save_tenant_commercial_modules(text,jsonb,bigint,uuid) to service_role;
notify pgrst, 'reload schema';
