-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Origem de cada pedido (UTM, domínio de referência, canal) em Shopify e FBITS.
-- Só colunas novas e nulas: nenhuma linha existente muda, nenhuma permissão
-- muda (as duas tabelas seguem com o RLS e os grants que já tinham).
-- O backend grava sem estas colunas enquanto a migration não for aplicada.

alter table public.shopify_orders add column if not exists utm_source text;
alter table public.shopify_orders add column if not exists utm_medium text;
alter table public.shopify_orders add column if not exists utm_campaign text;
alter table public.shopify_orders add column if not exists utm_content text;
alter table public.shopify_orders add column if not exists utm_term text;
alter table public.shopify_orders add column if not exists origin_channel text;
alter table public.shopify_orders add column if not exists origin_detail text;
alter table public.shopify_orders add column if not exists referrer_domain text;
alter table public.shopify_orders add column if not exists attribution_source text;

alter table public.fbits_orders add column if not exists utm_source text;
alter table public.fbits_orders add column if not exists utm_medium text;
alter table public.fbits_orders add column if not exists utm_campaign text;
alter table public.fbits_orders add column if not exists utm_content text;
alter table public.fbits_orders add column if not exists utm_term text;
alter table public.fbits_orders add column if not exists origin_channel text;
alter table public.fbits_orders add column if not exists origin_detail text;
alter table public.fbits_orders add column if not exists referrer_domain text;
alter table public.fbits_orders add column if not exists attribution_source text;

-- Relatório "Vendas por origem": filtra por empresa e período, agrupa por canal/campanha.
create index if not exists idx_shopify_orders_client_origin
  on public.shopify_orders(client_id, created_at_shopify, origin_channel, utm_campaign);
create index if not exists idx_fbits_orders_client_origin
  on public.fbits_orders(client_id, order_date, origin_channel, utm_campaign);

notify pgrst, 'reload schema';
