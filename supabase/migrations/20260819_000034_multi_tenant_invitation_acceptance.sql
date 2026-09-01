-- Bloco 2.1 — usuário já existente + multi-tenant no fluxo de convite.
--
-- Um mesmo usuário Mugô pode pertencer a múltiplos tenants, sempre com
-- autorização explícita por invitation. NADA é removido: nenhuma membership
-- é apagada, nenhuma tabela é dropada. Idempotente (create or replace).
--
-- MIGRATION LOCAL — revisar e aplicar remotamente só depois de validada.

-- ---------------------------------------------------------------------------
-- 1) Trigger do usuário NOVO (primeira confirmação de e-mail).
--    Agora prefere a invitation EXPLÍCITA carregada em
--    raw_user_meta_data->>'invitation_id' (vinda do generate_link / invite).
--    Sem escolha implícita: só cai no fallback "mais recente utilizável por
--    e-mail" quando não há id explícito válido (compatibilidade).
--    O guard "só primeira confirmação" é preservado: usuário JÁ confirmado
--    nunca é vinculado por aqui — usa a RPC explícita abaixo.
-- ---------------------------------------------------------------------------
create or replace function public.accept_pending_user_invitation()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  invitation public.user_invitations%rowtype;
  v_invitation_id uuid;
begin
  if tg_op = 'UPDATE' and old.email_confirmed_at is not null then
    return new;
  end if;

  begin
    v_invitation_id := nullif(new.raw_user_meta_data ->> 'invitation_id', '')::uuid;
  exception when others then
    v_invitation_id := null;
  end;

  if v_invitation_id is not null then
    select * into invitation
    from public.user_invitations
    where id = v_invitation_id
      and lower(email) = lower(new.email)
      and accepted_at is null and revoked_at is null and expires_at > now()
    for update skip locked
    limit 1;
  end if;

  if invitation.id is null then
    select * into invitation
    from public.user_invitations
    where lower(email) = lower(new.email)
      and accepted_at is null and revoked_at is null and expires_at > now()
    order by created_at desc
    for update skip locked
    limit 1;
  end if;

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

drop trigger if exists on_auth_user_accept_invitation on auth.users;
create trigger on_auth_user_accept_invitation
after insert or update of email_confirmed_at on auth.users
for each row
when (new.email_confirmed_at is not null)
execute function public.accept_pending_user_invitation();

-- ---------------------------------------------------------------------------
-- 2) Aceitação EXPLÍCITA para usuário JÁ autenticado (conta existente).
--    Chamada só pelo backend com service_role; o ator (p_actor_user_id) vem
--    de require_user_id (JWT verificado). O e-mail é derivado de auth.users e
--    precisa bater com o da invitation. tenant e role vêm SOMENTE da
--    invitation — nenhum client_id/role é aceito como parâmetro.
-- ---------------------------------------------------------------------------
create or replace function public.accept_user_invitation(
  p_actor_user_id uuid,
  p_invitation_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  invitation public.user_invitations%rowtype;
  v_actor_email text;
begin
  select email into v_actor_email from auth.users where id = p_actor_user_id;
  if v_actor_email is null then
    raise exception 'actor_not_found' using errcode = 'PT401';
  end if;

  select * into invitation
  from public.user_invitations
  where id = p_invitation_id
  for update;

  if invitation.id is null then
    raise exception 'invitation_not_found' using errcode = 'PT404';
  end if;
  if lower(invitation.email) <> lower(v_actor_email) then
    raise exception 'invitation_email_mismatch' using errcode = 'PT403';
  end if;
  if invitation.revoked_at is not null then
    raise exception 'invitation_revoked' using errcode = 'PT409';
  end if;
  if invitation.accepted_at is not null then
    raise exception 'invitation_already_accepted' using errcode = 'PT409';
  end if;
  if invitation.expires_at <= now() then
    raise exception 'invitation_expired' using errcode = 'PT409';
  end if;

  -- Aditivo: preserva qualquer membership existente do usuário em outros tenants.
  insert into public.client_memberships(user_id, client_id, role)
  values(p_actor_user_id, invitation.client_id, invitation.role)
  on conflict(user_id, client_id) do update set role = excluded.role;

  update public.user_invitations
  set accepted_at = now(), accepted_by = p_actor_user_id
  where id = invitation.id and accepted_at is null;

  update public.clients
  set status = 'active'
  where id = invitation.client_id and status = 'invitation_pending';

  insert into public.platform_audit_events(actor_user_id, client_id, event_type, details)
  values (
    p_actor_user_id, invitation.client_id, 'invitation_accepted',
    jsonb_build_object('invitation_id', invitation.id, 'role', invitation.role)
  );

  return jsonb_build_object('client_id', invitation.client_id, 'role', invitation.role);
end;
$$;

revoke all on function public.accept_user_invitation(uuid, uuid) from public, anon, authenticated;
grant execute on function public.accept_user_invitation(uuid, uuid) to service_role;
