-- Detailed FBits order items for product ranking and order drilldown.
-- Idempotent for repeated Supabase SQL Editor runs.

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

alter table public.fbits_orders
  add column if not exists payment_method text,
  add column if not exists payment_status text;

create table if not exists public.fbits_order_items (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  order_id text not null,
  item_id text not null,
  product_id text,
  sku text,
  product_name text,
  product_image_url text,
  quantity integer default 0,
  unit_value numeric default 0,
  total_value numeric default 0,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(client_id, order_id, item_id)
);

alter table public.fbits_order_items
  add column if not exists product_image_url text;

create index if not exists idx_fbits_order_items_client_order
  on public.fbits_order_items(client_id, order_id);

create index if not exists idx_fbits_order_items_client_product
  on public.fbits_order_items(client_id, product_id);

drop trigger if exists trg_fbits_order_items_updated_at on public.fbits_order_items;
create trigger trg_fbits_order_items_updated_at
before update on public.fbits_order_items
for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
