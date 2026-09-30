-- FBITS/Wake multiempresa — campos financeiros e marcador incremental.
--
-- Somente aditiva: nenhuma coluna existente é alterada ou removida, nenhum
-- dado é apagado. Linhas antigas ficam com NULL/0 nas colunas novas.
-- As colunas de cliente/PII legadas (customer_name, customer_email) não são
-- preenchidas pelo fluxo novo; continuam existindo apenas por compatibilidade.
--
-- MIGRATION LOCAL — revisar e aplicar remotamente só com autorização.

alter table public.fbits_orders
  add column if not exists subtotal_value numeric,
  add column if not exists discount_value numeric default 0,
  add column if not exists freight_value numeric default 0,
  add column if not exists coupon_code text,
  add column if not exists is_valid boolean,
  add column if not exists first_purchase boolean,
  add column if not exists sales_channel text,
  add column if not exists source_updated_at timestamptz;

alter table public.fbits_order_items
  add column if not exists discount_value numeric default 0,
  add column if not exists is_gift boolean default false;

create index if not exists idx_fbits_orders_client_source_updated
  on public.fbits_orders(client_id, source_updated_at);

notify pgrst, 'reload schema';
