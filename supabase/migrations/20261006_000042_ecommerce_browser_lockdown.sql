-- Fechamento das tabelas internas de e-commerce para o browser.
--
-- NÃO APLICADA. Criada nesta rodada e deixada pendente de propósito.
--
-- POR QUE
-- O preflight em produção mediu, nestas seis tabelas:
--     RLS = true, anon SELECT = true, authenticated SELECT = true
-- e confirmou em pg_default_acl que objetos criados por postgres/supabase_admin
-- recebem grants para anon, authenticated e service_role por padrão.
--
-- A migration 018 ligou RLS nelas e criou a policy `tenant_member_select`
-- (`using (public.is_client_member(client_id::text))`), mas NÃO revogou os
-- grants. O privilégio de tabela é verificado ANTES da RLS, então hoje:
--   - anon  : tem o privilégio, mas a policy não devolve linha nenhuma
--             (`auth.uid()` é nulo, logo não é membro de nada);
--   - authenticated membro do tenant: lê TODAS as colunas das linhas daquele
--             tenant direto do browser — inclusive `raw_payload` / `raw`.
--
-- Ou seja: não há vazamento entre empresas hoje, e sim duas falhas reais de
-- postura. Primeiro, um `viewer` lê pelo browser o mesmo payload bruto que o
-- backend nunca entrega a ele — a granularidade de papel e a minimização de
-- campos do backend são contornáveis. Segundo, a única barreira é a policy:
-- qualquer policy nova permissiva, ou RLS desligado por engano, transforma o
-- grant em exposição ampla. O grant é o que não deveria existir.
--
-- Mesmo padrão da migration 038, que fechou meta_connections,
-- meta_oauth_handoffs e shopify_refunds, e da 021, que já fechava ai_analyses
-- — é exatamente por ter o revoke explícito que `ai_analyses` aparece no
-- preflight com anon SELECT = false.
--
-- O QUE NÃO MUDA
-- O backend usa service_role, que ignora RLS e recebe grant explícito aqui.
-- Nenhum dado é apagado, nenhuma coluna muda, nenhuma integração muda de
-- comportamento, nenhum KPI é recalculado. Idempotente.
--
-- POLICIES ANTIGAS
-- `tenant_member_select` permanece. Não é prejudicial e passa a ser inócua
-- para anon/authenticated: sem privilégio de tabela, a policy nem é avaliada.
-- Mantida para não alterar migrations já aplicadas e para o dia em que algum
-- acesso de leitura pelo browser volte a ser desejado — aí será uma decisão
-- explícita, com grant de colunas, e não um default herdado.
--
-- SEQUENCES
-- Nenhuma destas seis tabelas usa sequence ou identity: a chave é
-- `uuid primary key default gen_random_uuid()`. Não há sequence relacionada a
-- fechar, e nenhum revoke indiscriminado de sequence é feito aqui.

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'fbits_orders',
    'fbits_order_items',
    'shopify_customers',
    'shopify_orders',
    'shopify_order_items',
    'shopify_webhook_events'
  ]
  loop
    -- `to_regclass` protege o caso de a tabela não existir no ambiente: a
    -- migration não falha, apenas não tem o que fechar.
    if to_regclass('public.' || table_name) is not null then
      execute format('alter table public.%I enable row level security', table_name);
      execute format('revoke all on public.%I from anon, authenticated', table_name);
      execute format('grant all on public.%I to service_role', table_name);
    end if;
  end loop;
end
$$;

-- ---------------------------------------------------------------------------
-- Funções SECURITY DEFINER que leem estas tabelas: AUDITADAS, já fechadas.
--
--   public.refresh_dashboard_read_model(text,date,date,text)
--     lê shopify_customers / shopify_orders / shopify_order_items.
--     Revogada de public, anon, authenticated e concedida a service_role nas
--     migrations 026, 028, 029, 030 e 032 (as revalidações mantêm o
--     fechamento a cada recriação).
--
--   public.delete_platform_company(uuid,text,text)
--     lê e apaga as seis. Revogada de public, anon, authenticated e concedida
--     a service_role na migration 036. A checagem interna usa
--     `is_platform_admin(p_actor_user_id)` sobre um PARÂMETRO, não
--     `auth.uid()` — o que torna o revoke a única proteção efetiva contra
--     chamada direta. Ele existe e está correto.
--
-- Nenhuma função legítima é fechada aqui: não havia o que corrigir, e fechar
-- por precaução quebraria o backend.
-- ---------------------------------------------------------------------------

-- PostgREST precisa recarregar o schema para refletir os grants novos.
notify pgrst, 'reload schema';
