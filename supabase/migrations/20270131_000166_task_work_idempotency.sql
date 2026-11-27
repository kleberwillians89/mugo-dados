-- LOCAL: NAO APLICADA. Depende de 000165.
-- Reserva e conclui operacoes de producao usando task_work_links como vinculo
-- canonico. A reserva evita artefatos duplicados em retries concorrentes.

alter table public.task_work_links add column if not exists operation_key text;
alter table public.task_work_links add column if not exists link_status text not null default 'linked';
alter table public.task_work_links add column if not exists claim_token uuid;
alter table public.task_work_links add column if not exists updated_at timestamptz not null default now();

update public.task_work_links
set operation_key = 'legacy:' || id::text
where operation_key is null;

alter table public.task_work_links alter column operation_key set not null;
alter table public.task_work_links alter column record_id drop not null;
alter table public.task_work_links
  add constraint task_work_links_operation_key_check
  check (char_length(operation_key) between 1 and 160);
alter table public.task_work_links
  add constraint task_work_links_status_check
  check (link_status in ('pending', 'linked', 'failed'));
alter table public.task_work_links
  add constraint task_work_links_record_state_check
  check ((link_status = 'linked' and record_id is not null) or link_status <> 'linked');

create unique index task_work_links_operation_idx
  on public.task_work_links (client_id, task_id, module, operation_key);

alter table public.studio_tasks add column if not exists origin_key text;
alter table public.studio_tasks
  add constraint studio_tasks_origin_key_check
  check (origin_key is null or char_length(origin_key) between 1 and 240);
create unique index studio_tasks_origin_key_idx
  on public.studio_tasks (client_id, origin_key)
  where origin_key is not null;

create or replace function public.task_work_record_belongs_to_tenant(
  p_client_id text,
  p_module text,
  p_record_id text
) returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
  v_found boolean := false;
begin
  begin
    v_id := p_record_id::uuid;
  exception when invalid_text_representation then
    return false;
  end;
  case p_module
    when 'email_marketing' then select exists(select 1 from public.email_campaigns where id = v_id and client_id = p_client_id) into v_found;
    when 'social_media' then select exists(select 1 from public.studio_content_matrices where id = v_id and client_id = p_client_id) into v_found;
    when 'midia_on' then select exists(select 1 from public.studio_ad_drafts where id = v_id and client_id = p_client_id) into v_found;
    when 'redacao' then select exists(select 1 from public.studio_documents where id = v_id and client_id = p_client_id) into v_found;
    when 'calendar' then select exists(select 1 from public.studio_calendar_items where id = v_id and client_id = p_client_id) into v_found;
    when 'whatsapp' then select exists(select 1 from public.whatsapp_campaign_drafts where id = v_id and client_id = p_client_id) into v_found;
    else return false;
  end case;
  return v_found;
end;
$$;

create or replace function public.claim_task_work_link(
  p_client_id text,
  p_task_id uuid,
  p_brief_id uuid,
  p_module text,
  p_deliverable text,
  p_operation_key text,
  p_claim_token uuid,
  p_created_by uuid
) returns table(link_id uuid, link_status text, record_id text, acquired boolean)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_link public.task_work_links%rowtype;
begin
  if p_module not in ('email_marketing', 'social_media', 'midia_on', 'redacao', 'calendar', 'whatsapp')
     or char_length(coalesce(p_operation_key, '')) not between 1 and 160 then
    raise exception 'invalid task work operation';
  end if;
  if not exists(select 1 from public.studio_tasks where client_id = p_client_id and id = p_task_id) then
    raise exception 'task not found for tenant';
  end if;
  if p_brief_id is not null and not exists(
    select 1 from public.studio_briefs where client_id = p_client_id and id = p_brief_id
  ) then
    raise exception 'brief not found for tenant';
  end if;

  insert into public.task_work_links(
    client_id, task_id, brief_id, deliverable, module, record_id,
    operation_key, link_status, claim_token, created_by, updated_at
  ) values (
    p_client_id, p_task_id, p_brief_id, left(coalesce(p_deliverable, ''), 160),
    p_module, null, p_operation_key, 'pending', p_claim_token, p_created_by, now()
  )
  on conflict (client_id, task_id, module, operation_key) do nothing;

  select * into v_link
  from public.task_work_links
  where client_id = p_client_id and task_id = p_task_id
    and module = p_module and operation_key = p_operation_key
  for update;

  if v_link.link_status = 'failed'
     or (v_link.link_status = 'pending' and v_link.updated_at < now() - interval '15 minutes') then
    update public.task_work_links
    set link_status = 'pending', claim_token = p_claim_token, record_id = null,
        brief_id = p_brief_id, deliverable = left(coalesce(p_deliverable, ''), 160),
        created_by = p_created_by, updated_at = now()
    where id = v_link.id
    returning * into v_link;
  end if;

  return query select v_link.id, v_link.link_status, v_link.record_id,
    v_link.link_status = 'pending' and v_link.claim_token = p_claim_token;
end;
$$;

create or replace function public.complete_task_work_link(
  p_link_id uuid,
  p_claim_token uuid,
  p_record_id text
) returns public.task_work_links
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_link public.task_work_links%rowtype;
begin
  select * into v_link from public.task_work_links where id = p_link_id for update;
  if v_link.id is null or v_link.link_status <> 'pending' or v_link.claim_token is distinct from p_claim_token then
    raise exception 'task work claim is not active';
  end if;
  if not public.task_work_record_belongs_to_tenant(v_link.client_id, v_link.module, p_record_id) then
    raise exception 'record not found for tenant and module';
  end if;
  update public.task_work_links
  set record_id = p_record_id, link_status = 'linked', claim_token = null, updated_at = now()
  where id = v_link.id
  returning * into v_link;
  return v_link;
end;
$$;

create or replace function public.fail_task_work_link(
  p_link_id uuid,
  p_claim_token uuid
) returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  update public.task_work_links
  set link_status = 'failed', claim_token = null, updated_at = now()
  where id = p_link_id and link_status = 'pending' and claim_token = p_claim_token;
$$;

create or replace function public.append_studio_brief_task(
  p_client_id text,
  p_brief_id uuid,
  p_task_id uuid,
  p_entry jsonb
) returns public.studio_briefs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_brief public.studio_briefs%rowtype;
begin
  if not exists(select 1 from public.studio_tasks where client_id = p_client_id and id = p_task_id) then
    raise exception 'task not found for tenant';
  end if;
  update public.studio_briefs
  set tasks = case
        when exists(select 1 from jsonb_array_elements(tasks) entry where entry->>'task_id' = p_task_id::text)
          then tasks
        else tasks || jsonb_build_array(p_entry || jsonb_build_object('task_id', p_task_id::text))
      end,
      status = 'distribuido',
      updated_at = now()
  where client_id = p_client_id and id = p_brief_id
  returning * into v_brief;
  if v_brief.id is null then raise exception 'brief not found for tenant'; end if;
  return v_brief;
end;
$$;

revoke all on function public.task_work_record_belongs_to_tenant(text, text, text) from public, anon, authenticated;
revoke all on function public.claim_task_work_link(text, uuid, uuid, text, text, text, uuid, uuid) from public, anon, authenticated;
revoke all on function public.complete_task_work_link(uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.fail_task_work_link(uuid, uuid) from public, anon, authenticated;
revoke all on function public.append_studio_brief_task(text, uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function public.task_work_record_belongs_to_tenant(text, text, text) to service_role;
grant execute on function public.claim_task_work_link(text, uuid, uuid, text, text, text, uuid, uuid) to service_role;
grant execute on function public.complete_task_work_link(uuid, uuid, text) to service_role;
grant execute on function public.fail_task_work_link(uuid, uuid) to service_role;
grant execute on function public.append_studio_brief_task(text, uuid, uuid, jsonb) to service_role;

notify pgrst, 'reload schema';
