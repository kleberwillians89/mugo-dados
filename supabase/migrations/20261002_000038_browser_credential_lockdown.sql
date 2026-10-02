-- Fechamento de credenciais no browser.
--
-- O browser usa só a anon key + JWT do usuário e lê apenas:
--   clients (id, name, trade_name), client_memberships, platform_admins
--   e o read model dashboard_*.
-- Tudo o mais passa pelo backend, que usa service_role (ignora RLS e estes
-- revokes). Nenhum dado é apagado; nenhuma integração muda de comportamento.
--
-- MIGRATION LOCAL — revisar e aplicar remotamente só depois de validada.
-- Idempotente.

-- ---------------------------------------------------------------------------
-- 1) clients: allowlist de colunas para o browser.
--    ig_access_token (e qualquer coluna legada de token que exista só no
--    banco remoto) deixa de ser legível por membros. Allowlist, e não revoke
--    de coluna, porque revoke de coluna não remove o SELECT de tabela.
-- ---------------------------------------------------------------------------
revoke all on public.clients from anon, authenticated;
grant select (id, name, trade_name) on public.clients to authenticated;

-- ---------------------------------------------------------------------------
-- 2) Tabelas só do backend: nenhum acesso do browser.
--    meta_connections: access_token / encrypted_access_token.
--    meta_oauth_handoffs: encrypted_access_token + ativos descobertos; não
--      tinha RLS nas migrations (anon key lia qualquer tenant).
--    shopify_refunds: payload bruto com dados de cliente; não tinha RLS.
-- ---------------------------------------------------------------------------
do $$
declare
  table_name text;
begin
  foreach table_name in array array['meta_connections', 'meta_oauth_handoffs', 'shopify_refunds']
  loop
    if to_regclass('public.' || table_name) is not null then
      execute format('alter table public.%I enable row level security', table_name);
      execute format('revoke all on public.%I from anon, authenticated', table_name);
      execute format('grant all on public.%I to service_role', table_name);
    end if;
  end loop;
end
$$;

-- ---------------------------------------------------------------------------
-- 3) RPCs security definer de jobs: só o backend (service_role).
--    Sem isto, qualquer pessoa com a anon key travava/soltava locks de sync.
-- ---------------------------------------------------------------------------
revoke all on function public.acquire_client_job_lock(text, text, integer)
  from public, anon, authenticated;
grant execute on function public.acquire_client_job_lock(text, text, integer)
  to service_role;

revoke all on function public.release_client_job_lock(text, text)
  from public, anon, authenticated;
grant execute on function public.release_client_job_lock(text, text)
  to service_role;

notify pgrst, 'reload schema';
