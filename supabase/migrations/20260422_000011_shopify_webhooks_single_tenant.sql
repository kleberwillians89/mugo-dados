create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.shopify_webhook_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  webhook_id text,
  topic text not null,
  shop_domain text not null,
  payload_json jsonb not null default '{}'::jsonb,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  status text not null default 'received',
  error_message text
);

create index if not exists idx_shopify_webhook_events_received_at
  on public.shopify_webhook_events(received_at desc);

create index if not exists idx_shopify_webhook_events_client_received
  on public.shopify_webhook_events(client_id, received_at desc);

create index if not exists idx_shopify_webhook_events_topic_received
  on public.shopify_webhook_events(topic, received_at desc);

create index if not exists idx_shopify_webhook_events_status_received
  on public.shopify_webhook_events(status, received_at desc);

create unique index if not exists idx_shopify_webhook_events_client_webhook_unique
  on public.shopify_webhook_events(client_id, webhook_id)
  where webhook_id is not null;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'shopify_webhook_events_status_check'
      and conrelid = 'public.shopify_webhook_events'::regclass
  ) then
    alter table public.shopify_webhook_events drop constraint shopify_webhook_events_status_check;
  end if;
end $$;

alter table public.shopify_webhook_events
  add constraint shopify_webhook_events_status_check
  check (status in ('received', 'processing', 'processed', 'ignored', 'error'));

create table if not exists public.shopify_orders (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  shopify_order_id text not null,
  shop_domain text not null default '',
  order_number text,
  name text,
  email text,
  customer_id text,
  currency text,
  financial_status text,
  fulfillment_status text,
  subtotal_price numeric(18, 2),
  total_discounts numeric(18, 2),
  total_shipping_price numeric(18, 2),
  total_price numeric(18, 2),
  total_tax numeric(18, 2),
  cancelled_at timestamptz,
  cancel_reason text,
  created_at_shopify timestamptz,
  updated_at_shopify timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, shopify_order_id)
);

create index if not exists idx_shopify_orders_client_updated
  on public.shopify_orders(client_id, updated_at_shopify desc nulls last);

create index if not exists idx_shopify_orders_client_customer
  on public.shopify_orders(client_id, customer_id);

create index if not exists idx_shopify_orders_shop_domain
  on public.shopify_orders(shop_domain, updated_at_shopify desc nulls last);

create table if not exists public.shopify_order_items (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  shopify_order_id text not null,
  shopify_line_item_id text not null,
  product_id text,
  variant_id text,
  sku text,
  title text,
  variant_title text,
  vendor text,
  quantity integer not null default 0,
  price numeric(18, 2),
  total_discount numeric(18, 2),
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, shopify_line_item_id)
);

create index if not exists idx_shopify_order_items_client_order
  on public.shopify_order_items(client_id, shopify_order_id);

create table if not exists public.shopify_customers (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  shopify_customer_id text not null,
  shop_domain text not null default '',
  email text,
  first_name text,
  last_name text,
  phone text,
  orders_count integer not null default 0,
  total_spent numeric(18, 2),
  state text,
  created_at_shopify timestamptz,
  updated_at_shopify timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, shopify_customer_id)
);

create index if not exists idx_shopify_customers_client_updated
  on public.shopify_customers(client_id, updated_at_shopify desc nulls last);

create index if not exists idx_shopify_customers_email
  on public.shopify_customers(client_id, email);

create table if not exists public.shopify_refunds (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  shopify_refund_id text not null,
  shopify_order_id text,
  shop_domain text not null default '',
  note text,
  total_refunded numeric(18, 2),
  created_at_shopify timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, shopify_refund_id)
);

create index if not exists idx_shopify_refunds_client_order
  on public.shopify_refunds(client_id, shopify_order_id, created_at_shopify desc nulls last);

create index if not exists idx_shopify_refunds_client_created
  on public.shopify_refunds(client_id, created_at_shopify desc nulls last);

drop trigger if exists trg_shopify_orders_updated_at on public.shopify_orders;
create trigger trg_shopify_orders_updated_at
before update on public.shopify_orders
for each row execute function public.set_updated_at();

drop trigger if exists trg_shopify_order_items_updated_at on public.shopify_order_items;
create trigger trg_shopify_order_items_updated_at
before update on public.shopify_order_items
for each row execute function public.set_updated_at();

drop trigger if exists trg_shopify_customers_updated_at on public.shopify_customers;
create trigger trg_shopify_customers_updated_at
before update on public.shopify_customers
for each row execute function public.set_updated_at();

drop trigger if exists trg_shopify_refunds_updated_at on public.shopify_refunds;
create trigger trg_shopify_refunds_updated_at
before update on public.shopify_refunds
for each row execute function public.set_updated_at();
