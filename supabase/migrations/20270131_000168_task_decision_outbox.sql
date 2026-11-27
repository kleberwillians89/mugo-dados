-- LOCAL: NAO APLICADA. Depende de 000167.
-- Decisoes de tarefa passam a gravar estado + historico na mesma transacao.
-- Sincronizacoes com Calendario/CRM sao identificadas por uma chave idempotente
-- e permanecem observaveis/reexecutaveis sem transformar o CRM em fonte de trabalho.

create table if not exists public.studio_task_sync_outbox (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  task_id uuid references public.studio_tasks(id) on delete restrict,
  kind text not null check (kind in ('calendar_sync', 'crm_notification')),
  operation_key text not null check (length(operation_key) between 1 and 240),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed')),
  attempts integer not null default 0 check (attempts >= 0),
  last_error text check (last_error is null or length(last_error) <= 120),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  sent_at timestamptz,
  unique (client_id, kind, operation_key)
);
create index if not exists studio_task_sync_pending_idx
  on public.studio_task_sync_outbox (status, created_at) where status in ('pending', 'failed');
alter table public.studio_task_sync_outbox enable row level security;
revoke all on public.studio_task_sync_outbox from anon, authenticated;
grant all on public.studio_task_sync_outbox to service_role;

create or replace function public.enqueue_studio_task_sync(
  p_client_id text, p_kind text, p_operation_key text, p_payload jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_row public.studio_task_sync_outbox;
begin
  if p_kind not in ('calendar_sync', 'crm_notification') then
    raise exception 'TASK_SYNC_KIND_INVALID';
  end if;
  insert into public.studio_task_sync_outbox(client_id, kind, operation_key, payload)
  values (p_client_id, p_kind, left(p_operation_key, 240), coalesce(p_payload, '{}'::jsonb))
  on conflict (client_id, kind, operation_key) do update
    set updated_at = now()
  returning * into v_row;
  return to_jsonb(v_row);
end $$;

create or replace function public.apply_studio_task_decision(
  p_client_id text, p_task_id uuid, p_expected_status text, p_action text,
  p_comment text, p_actor_id uuid, p_actor_name text, p_actor_side text,
  p_internal boolean
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_task public.studio_tasks;
  v_now timestamptz := now();
  v_destination text;
  v_kind text;
  v_outbox jsonb;
  v_operation text;
begin
  select * into v_task from public.studio_tasks
   where client_id = p_client_id and id = p_task_id for update;
  if not found then raise exception 'TASK_NOT_FOUND'; end if;
  if v_task.status <> p_expected_status then raise exception 'STAGE_INVALID'; end if;

  case p_action
    when 'submit' then v_destination := 'internal_review'; v_kind := 'enviado_interno';
    when 'internal_approve' then
      if v_task.visible_to_client and v_task.needs_client_approval then v_destination := 'client_review';
      else v_destination := 'completed'; end if;
      v_kind := 'aprovado_interno';
    when 'internal_changes' then v_destination := 'changes'; v_kind := 'ajuste_interno';
    when 'client_approve' then v_destination := 'completed'; v_kind := 'aprovado_cliente';
    when 'client_changes' then v_destination := 'changes'; v_kind := 'ajuste_cliente';
    when 'comment' then v_destination := null; v_kind := 'comentario';
    else raise exception 'ACTION_INVALID';
  end case;

  if v_destination is not null then
    update public.studio_tasks set
      status = v_destination,
      updated_at = v_now,
      completed_at = case when v_destination = 'completed' then v_now else null end,
      approved_at = case when v_destination = 'completed' then v_now else approved_at end,
      approval_round = case when p_action = 'submit' then approval_round + 1 else approval_round end
    where id = v_task.id returning * into v_task;
  end if;

  insert into public.studio_task_events(client_id, task_id, kind, internal, comment,
    actor_id, actor_name, actor_side, created_at)
  values (p_client_id, p_task_id, v_kind, p_internal, nullif(left(trim(coalesce(p_comment, '')), 2000), ''),
    p_actor_id, left(p_actor_name, 120), p_actor_side, v_now);
  if v_destination = 'client_review' then
    insert into public.studio_task_events(client_id, task_id, kind, internal, actor_id, actor_name, actor_side, created_at)
    values (p_client_id, p_task_id, 'enviado_cliente', false, p_actor_id, left(p_actor_name, 120), p_actor_side, v_now);
  end if;

  if p_action in ('client_approve', 'client_changes') then
    v_operation := p_task_id::text || ':' || v_task.approval_round::text || ':' || p_action || ':' || p_expected_status;
    v_outbox := public.enqueue_studio_task_sync(p_client_id, 'crm_notification', v_operation,
      jsonb_build_object('task_id', p_task_id, 'title', v_task.title, 'action', p_action,
        'comment', nullif(left(trim(coalesce(p_comment, '')), 2000), ''), 'actor_name', left(p_actor_name, 120)));
  end if;
  return jsonb_build_object('task', to_jsonb(v_task), 'outbox', v_outbox);
end $$;

create or replace function public.process_calendar_task_sync(p_outbox_id uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_job public.studio_task_sync_outbox;
  v_task public.studio_tasks;
  v_item_id uuid;
  v_target text;
  v_kind text;
  v_result text := 'unchanged';
  v_now timestamptz := now();
begin
  select * into v_job from public.studio_task_sync_outbox where id = p_outbox_id for update;
  if not found or v_job.kind <> 'calendar_sync' then raise exception 'TASK_SYNC_NOT_FOUND'; end if;
  if v_job.status = 'sent' then return to_jsonb(v_job); end if;
  v_item_id := (v_job.payload->>'item_id')::uuid;
  v_target := v_job.payload->>'target';
  if v_target not in ('changes', 'internal_review', 'client_review', 'completed', 'in_progress', 'cancelled') then
    raise exception 'TASK_SYNC_TARGET_INVALID';
  end if;

  select * into v_task from public.studio_tasks
   where client_id = v_job.client_id and calendar_item_id = v_item_id for update;
  if not found and v_target = 'changes' then
    begin
      insert into public.studio_tasks(client_id, title, status, category, notes, visible_to_client,
        needs_client_approval, calendar_item_id, due_date, approval_round, origin_key)
      values (v_job.client_id, left(v_job.payload->>'title', 200), 'changes', 'Calendário',
        nullif(left(v_job.payload->>'comment', 4000), ''), false, true, v_item_id,
        nullif(v_job.payload->>'due_date', '')::date, 1, 'calendar:' || v_item_id::text)
      returning * into v_task;
      v_result := 'created';
      insert into public.studio_task_events(client_id, task_id, kind, internal, comment, actor_name, actor_side, created_at)
      values (v_job.client_id, v_task.id,
        case when (v_job.payload->>'by_client')::boolean then 'ajuste_cliente' else 'ajuste_interno' end,
        not (v_job.payload->>'by_client')::boolean, nullif(left(v_job.payload->>'comment', 2000), ''),
        left(v_job.payload->>'actor_name', 120),
        case when (v_job.payload->>'by_client')::boolean then 'cliente' else 'mugo' end, v_now);
    exception when unique_violation then
      select * into v_task from public.studio_tasks
       where client_id = v_job.client_id and calendar_item_id = v_item_id for update;
    end;
  end if;

  if v_task.id is not null and v_task.status <> 'cancelled' and v_task.status <> v_target then
    update public.studio_tasks set status = v_target, updated_at = v_now,
      completed_at = case when v_target = 'completed' then v_now else null end,
      approved_at = case when v_target = 'completed' then v_now else approved_at end,
      approval_round = case when v_target = 'changes' then approval_round + 1 else approval_round end
    where id = v_task.id returning * into v_task;
    if v_result <> 'created' then v_result := 'updated'; end if;
    v_kind := case v_target
      when 'changes' then case when (v_job.payload->>'by_client')::boolean then 'ajuste_cliente' else 'ajuste_interno' end
      when 'internal_review' then 'enviado_interno'
      when 'client_review' then 'enviado_cliente'
      when 'completed' then case when (v_job.payload->>'by_client')::boolean then 'aprovado_cliente' else 'aprovado_interno' end
      when 'cancelled' then 'cancelado'
      else null end;
    if v_kind is not null then
      insert into public.studio_task_events(client_id, task_id, kind, internal, comment, actor_name, actor_side, created_at)
      values (v_job.client_id, v_task.id, v_kind, not (v_job.payload->>'by_client')::boolean,
        nullif(left(v_job.payload->>'comment', 2000), ''), left(v_job.payload->>'actor_name', 120),
        case when (v_job.payload->>'by_client')::boolean then 'cliente' else 'mugo' end, v_now);
    end if;
  end if;

  update public.studio_task_sync_outbox set task_id = v_task.id, status = 'sent', attempts = attempts + 1,
    last_error = null, sent_at = v_now, updated_at = v_now where id = v_job.id returning * into v_job;
  return to_jsonb(v_job) || jsonb_build_object('result', v_result);
end $$;

revoke all on function public.enqueue_studio_task_sync(text,text,text,jsonb) from public, anon, authenticated;
revoke all on function public.apply_studio_task_decision(text,uuid,text,text,text,uuid,text,text,boolean) from public, anon, authenticated;
revoke all on function public.process_calendar_task_sync(uuid) from public, anon, authenticated;
grant execute on function public.enqueue_studio_task_sync(text,text,text,jsonb) to service_role;
grant execute on function public.apply_studio_task_decision(text,uuid,text,text,text,uuid,text,text,boolean) to service_role;
grant execute on function public.process_calendar_task_sync(uuid) to service_role;

notify pgrst, 'reload schema';
