-- Customer 360: índices de performance sobre tabelas que já existem.
--
-- NÃO APLICADA. Criada nesta rodada e deixada pendente de propósito.
--
-- Separada da 040 de propósito: 040 cria o armazenamento novo
-- (public.fbits_customers, com os índices da própria tabela e a exclusão de
-- PII); esta só acrescenta índices em tabelas preexistentes. Schema e
-- performance têm riscos diferentes na hora de aplicar — se um índice
-- precisar ser recriado com CONCURRENTLY, isso não deve arrastar a criação da
-- tabela. Este arquivo era a 040 até esta rodada; a renumeração não tem
-- impacto porque nunca foi commitada nem aplicada em nenhum ambiente.
--
-- CONTEXTO
-- A página Clientes agrega o que os syncs já persistem: uma leitura por
-- tabela, filtrada por client_id, agregada no backend. Sem N+1 e sem chamar
-- FBITS/Shopify ao abrir a página.
--
-- O QUE JÁ EXISTE (e por isso não é recriado aqui)
--   shopify_orders    (client_id, customer_id)            idx_shopify_orders_client_customer
--   shopify_orders    (client_id, updated_at_shopify)     idx_shopify_orders_client_updated
--   shopify_customers (client_id, email)                  idx_shopify_customers_email
--   shopify_customers (client_id, updated_at_shopify)     idx_shopify_customers_client_updated
--   fbits_orders      (client_id, order_date)             idx_fbits_orders_client_order_date
--   fbits_orders      (client_id, status_id)              idx_fbits_orders_client_status
--
-- O QUE FALTA
-- fbits_orders não tem índice por cliente. A listagem varre os pedidos do
-- tenant ordenados por order_date (já coberto), mas o agrupamento por cliente
-- e o detalhe de um cliente específico se beneficiam de (client_id,
-- customer_id). Shopify já tem o equivalente.
--
-- CONCURRENTLY fica de fora porque não roda dentro de transação, e o runner de
-- migrations deste projeto aplica cada arquivo em uma. Em tabela grande,
-- aplique manualmente com CONCURRENTLY fora da transação.

create index if not exists idx_fbits_orders_client_customer
  on public.fbits_orders (client_id, customer_id);

-- Detalhe de um cliente: pedidos daquele cliente em ordem cronológica.
create index if not exists idx_fbits_orders_client_customer_date
  on public.fbits_orders (client_id, customer_id, order_date desc);

-- Shopify: o detalhe também ordena por data dentro do cliente.
create index if not exists idx_shopify_orders_client_customer_created
  on public.shopify_orders (client_id, customer_id, created_at_shopify desc);

-- PRÓXIMO PASSO, SE A BASE CRESCER (não incluído aqui de propósito)
-- Acima de ~20 mil pedidos por tenant a agregação em memória atinge o teto
-- CUSTOMER_ORDER_SCAN_LIMIT e o contrato devolve truncated=true. A evolução
-- natural é uma view materializada por tenant com orders_count,
-- total_revenue, first_order_at e last_order_at já agregados, refrescada
-- pelos mesmos crons de sync. Isso muda o caminho de leitura e merece a
-- própria migration, com a regra de receita de cada provider replicada em SQL
-- — hoje ela vive no Python (_counts_as_revenue e _is_recognized_order) e
-- duplicá-la sem necessidade criaria duas fontes de verdade.
