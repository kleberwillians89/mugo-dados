-- Somente cluster descartável criado pelo roteiro local; fixtures opacas.
begin;
insert into auth.users(id) values ('00000000-0000-4000-8000-000000000002');
insert into public.mcp_oauth_clients(id,client_name,redirect_uris) values
 ('00000000-0000-4000-8000-000000000001','Aplicativo de teste','["https://claude.ai/api/mcp/auth_callback"]');
set local role service_role;
do $$
declare c uuid := '00000000-0000-4000-8000-000000000001'; u uuid := '00000000-0000-4000-8000-000000000002';
        redirect text := 'https://claude.ai/api/mcp/auth_callback'; resource text := 'https://api.test/mcp';
begin
  insert into public.mcp_oauth_codes(code_hash,user_id,oauth_client_id,redirect_uri,resource,challenge,company_ids)
    values(repeat('c',64),u,c,redirect,resource,repeat('v',43),array['empresa-a']);
  if public.mcp_exchange_code(repeat('c',64),c,redirect,resource,repeat('x',43),repeat('a',64),repeat('b',64)) then raise exception 'PKCE inválido aceito'; end if;
  if public.mcp_exchange_code(repeat('c',64),c,redirect,'https://other.test/mcp',repeat('v',43),repeat('a',64),repeat('b',64)) then raise exception 'Recurso inválido aceito'; end if;
  if not public.mcp_exchange_code(repeat('c',64),c,redirect,resource,repeat('v',43),repeat('a',64),repeat('b',64)) then raise exception 'Código válido rejeitado'; end if;
  if public.mcp_exchange_code(repeat('c',64),c,redirect,resource,repeat('v',43),repeat('d',64),repeat('e',64)) then raise exception 'Código reutilizado'; end if;
  insert into public.mcp_oauth_codes(code_hash,user_id,oauth_client_id,redirect_uri,resource,challenge,expires_at)
    values(repeat('f',64),u,c,redirect,resource,repeat('v',43),now()-interval '1 second');
  if public.mcp_exchange_code(repeat('f',64),c,redirect,resource,repeat('v',43),repeat('d',64),repeat('e',64)) then raise exception 'Código expirado aceito'; end if;
  if (select company_ids from public.mcp_oauth_tokens where access_hash=repeat('a',64)) is distinct from array['empresa-a'] then raise exception 'Escopo não copiado na troca'; end if;
  if not public.mcp_rotate_refresh(repeat('b',64),c,resource,repeat('d',64),repeat('e',64)) then raise exception 'Refresh válido rejeitado'; end if;
  if (select company_ids from public.mcp_oauth_tokens where access_hash=repeat('d',64)) is distinct from array['empresa-a'] then raise exception 'Escopo não copiado na rotação'; end if;
  if (select revoked_at is null from public.mcp_oauth_tokens where access_hash=repeat('a',64)) then raise exception 'Access antigo não revogado'; end if;
  if public.mcp_rotate_refresh(repeat('b',64),c,resource,repeat('g',64),repeat('h',64)) then raise exception 'Refresh reutilizado'; end if;
  if exists(select 1 from public.mcp_oauth_tokens where revoked_at is null) then raise exception 'Família não revogada'; end if;
  if public.mcp_rotate_refresh(repeat('e',64),c,resource,repeat('g',64),repeat('h',64)) then raise exception 'Família revogada aceita'; end if;
end $$;
reset role;
set local role authenticated;
do $$ begin
  begin perform 1 from public.mcp_oauth_tokens; raise exception 'Leitura browser autorizada'; exception when insufficient_privilege then null; end;
  begin perform public.mcp_revoke_family(repeat('a',64),'00000000-0000-4000-8000-000000000001'); raise exception 'RPC browser autorizada'; exception when insufficient_privilege then null; end;
end $$;
rollback;
