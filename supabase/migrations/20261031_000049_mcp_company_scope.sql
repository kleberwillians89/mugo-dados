-- Aplicação manual. APLICAR ANTES do deploy do backend que lê company_ids.
-- Escopo por empresa no conector do Claude: na autorização a pessoa escolhe
-- quais empresas o token pode ler. O escopo nasce no código de autorização e
-- é copiado para cada token da família (troca e rotação), nunca ampliado.
-- company_ids nulo = conexão criada antes deste escopo (vale o acesso da conta).
begin;
alter table public.mcp_oauth_codes add column if not exists company_ids text[];
alter table public.mcp_oauth_tokens add column if not exists company_ids text[];

create or replace function public.mcp_exchange_code(
  p_code_hash text, p_client_id uuid, p_redirect_uri text, p_resource text,
  p_challenge text, p_access_hash text, p_refresh_hash text
) returns boolean language plpgsql security invoker set search_path=public,pg_temp as $fn$
declare c public.mcp_oauth_codes; f uuid := gen_random_uuid();
begin
  perform 1 from public.mcp_oauth_codes where code_hash=p_code_hash for update;
  c := (select x from public.mcp_oauth_codes x where x.code_hash=p_code_hash);
  if c.code_hash is null or c.expires_at<=now() or c.oauth_client_id<>p_client_id
     or c.redirect_uri<>p_redirect_uri or c.resource<>p_resource or c.challenge<>p_challenge then
    return false;
  end if;
  delete from public.mcp_oauth_codes where code_hash=p_code_hash;
  insert into public.mcp_oauth_tokens(id,family_id,user_id,oauth_client_id,resource,access_hash,refresh_hash,access_expires_at,refresh_expires_at,company_ids)
    values(f,f,c.user_id,p_client_id,p_resource,p_access_hash,p_refresh_hash,now()+interval '1 hour',now()+interval '30 days',c.company_ids);
  return true;
end $fn$;

create or replace function public.mcp_rotate_refresh(
  p_refresh_hash text, p_client_id uuid, p_resource text, p_access_hash text, p_new_refresh_hash text
) returns boolean language plpgsql security invoker set search_path=public,pg_temp as $fn$
declare cur public.mcp_oauth_tokens; fam public.mcp_oauth_tokens;
begin
  cur := (select x from public.mcp_oauth_tokens x where x.refresh_hash=p_refresh_hash);
  if cur.id is null then return false; end if;
  perform 1 from public.mcp_oauth_tokens where id=cur.family_id for update;
  fam := (select x from public.mcp_oauth_tokens x where x.id=cur.family_id);
  if fam.id is null or fam.refresh_expires_at<=now() or cur.oauth_client_id<>p_client_id or cur.resource<>p_resource then return false; end if;
  cur := (select x from public.mcp_oauth_tokens x where x.refresh_hash=p_refresh_hash);
  if cur.rotated_at is not null then
    update public.mcp_oauth_tokens set revoked_at=coalesce(revoked_at,now()) where family_id=cur.family_id;
    return false;
  end if;
  if cur.revoked_at is not null or cur.refresh_expires_at<=now() then return false; end if;
  update public.mcp_oauth_tokens set rotated_at=now(),revoked_at=now() where id=cur.id;
  insert into public.mcp_oauth_tokens(id,family_id,user_id,oauth_client_id,resource,access_hash,refresh_hash,access_expires_at,refresh_expires_at,company_ids)
    values(gen_random_uuid(),cur.family_id,cur.user_id,p_client_id,p_resource,p_access_hash,p_new_refresh_hash,
           least(now()+interval '1 hour',fam.refresh_expires_at),fam.refresh_expires_at,cur.company_ids);
  return true;
end $fn$;

revoke all on function public.mcp_exchange_code(text,uuid,text,text,text,text,text),public.mcp_rotate_refresh(text,uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.mcp_exchange_code(text,uuid,text,text,text,text,text),public.mcp_rotate_refresh(text,uuid,text,text,text) to service_role;
commit;
