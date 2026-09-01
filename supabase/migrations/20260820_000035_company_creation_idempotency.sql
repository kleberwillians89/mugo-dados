-- Bloco 1.2 — idempotência server-side na criação de empresa.
--
-- Retry da mesma operação devolve SEMPRE a mesma empresa; double-click e
-- requests concorrentes com o mesmo id nunca criam duplicata. A chave é por
-- REQUEST (não por e-mail/CNPJ/nome), então duas empresas legítimas com o
-- mesmo responsável continuam possíveis. Idempotente (create or replace,
-- add column if not exists). NADA é apagado.
--
-- MIGRATION LOCAL — revisar e aplicar remotamente só depois de validada.

-- ---------------------------------------------------------------------------
-- 1) Chave de idempotência por request na criação da empresa.
--    Linhas antigas ficam com NULL; o índice único permite múltiplos NULL
--    (NULLS DISTINCT, padrão do Postgres) e não afeta empresas existentes.
-- ---------------------------------------------------------------------------
alter table public.clients
  add column if not exists creation_request_id text;

create unique index if not exists clients_creation_request_id_uq
  on public.clients (creation_request_id);

-- ---------------------------------------------------------------------------
-- 2) RPC de criação idempotente (8 args — implementação real).
--    Novo parâmetro p_creation_request_id (OBRIGATÓRIO, sem DEFAULT — ver shim
--    abaixo: é o "sem DEFAULT" que garante a resolução exclusiva no PostgREST).
--    Concorrência: `insert ... on conflict (creation_request_id) do nothing`
--    faz o 2º request com o mesmo id BLOQUEAR até o 1º commitar e então NÃO
--    inserir — o 2º re-lê a linha commitada e devolve a mesma empresa.
--    A autoridade continua sendo `is_platform_admin` (inalterada).
-- ---------------------------------------------------------------------------
-- Remove só o CORPO antigo de 020 (7 args); a assinatura de 7 args volta logo
-- abaixo como shim retrocompatível.
drop function if exists public.create_platform_company(uuid,text,text,text,text,text,timestamptz);

create or replace function public.create_platform_company(
  p_actor_user_id uuid,
  p_name text,
  p_trade_name text,
  p_cnpj text,
  p_responsible_email text,
  p_token_hash text,
  p_expires_at timestamptz,
  p_creation_request_id text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_client public.clients%rowtype;
  v_invitation public.user_invitations%rowtype;
  v_request_id text := nullif(trim(coalesce(p_creation_request_id, '')), '');
begin
  if not public.is_platform_admin(p_actor_user_id) then
    raise exception 'platform_admin_required' using errcode = '42501';
  end if;
  if v_request_id is null then
    raise exception 'creation_request_id_required' using errcode = '22023';
  end if;
  if length(trim(coalesce(p_name, ''))) < 2 then
    raise exception 'invalid_company_name' using errcode = '22023';
  end if;
  if position('@' in coalesce(p_responsible_email, '')) < 2 then
    raise exception 'invalid_responsible_email' using errcode = '22023';
  end if;

  -- Replay idempotente (caminho rápido): este request_id já criou uma empresa.
  select * into v_client from public.clients where creation_request_id = v_request_id;
  if v_client.id is not null then
    select * into v_invitation
    from public.user_invitations
    where client_id = v_client.id
    order by created_at asc
    limit 1;
    return jsonb_build_object(
      'client', to_jsonb(v_client),
      'invitation', to_jsonb(v_invitation),
      'idempotent_replay', true
    );
  end if;

  -- Primeira vez. O ON CONFLICT serializa requests concorrentes com o mesmo id.
  insert into public.clients (
    name, trade_name, cnpj, responsible_email, status, created_by, creation_request_id
  ) values (
    trim(p_name), nullif(trim(p_trade_name), ''), nullif(trim(p_cnpj), ''),
    lower(trim(p_responsible_email)), 'invitation_pending', p_actor_user_id, v_request_id
  )
  on conflict (creation_request_id) do nothing
  returning * into v_client;

  if v_client.id is null then
    -- Um request concorrente com o mesmo id venceu a corrida e já commitou.
    select * into v_client from public.clients where creation_request_id = v_request_id;
    select * into v_invitation
    from public.user_invitations
    where client_id = v_client.id
    order by created_at asc
    limit 1;
    return jsonb_build_object(
      'client', to_jsonb(v_client),
      'invitation', to_jsonb(v_invitation),
      'idempotent_replay', true
    );
  end if;

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
    jsonb_build_object(
      'invitation_id', v_invitation.id,
      'responsible_email', v_invitation.email,
      'creation_request_id', v_request_id
    )
  );

  return jsonb_build_object(
    'client', to_jsonb(v_client),
    'invitation', to_jsonb(v_invitation),
    'idempotent_replay', false
  );
end;
$$;

revoke all on function public.create_platform_company(uuid,text,text,text,text,text,timestamptz,text)
  from public, anon, authenticated;
grant execute on function public.create_platform_company(uuid,text,text,text,text,text,timestamptz,text)
  to service_role;

-- ---------------------------------------------------------------------------
-- 3) Shim retrocompatível (7 args — assinatura antiga de 020).
--    Não contém lógica de criação: apenas delega para a implementação nova,
--    gerando uma chave por chamada para backends ainda sem idempotency_key.
-- ---------------------------------------------------------------------------
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
language sql
security definer
set search_path = public
as $$
  select public.create_platform_company(
    p_actor_user_id => p_actor_user_id,
    p_name => p_name,
    p_trade_name => p_trade_name,
    p_cnpj => p_cnpj,
    p_responsible_email => p_responsible_email,
    p_token_hash => p_token_hash,
    p_expires_at => p_expires_at,
    p_creation_request_id => gen_random_uuid()::text
  );
$$;

revoke all on function public.create_platform_company(uuid,text,text,text,text,text,timestamptz)
  from public, anon, authenticated;
grant execute on function public.create_platform_company(uuid,text,text,text,text,text,timestamptz)
  to service_role;
