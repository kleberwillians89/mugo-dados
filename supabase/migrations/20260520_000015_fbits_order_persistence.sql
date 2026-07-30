-- FBits order persistence and daily official sales rollups.
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

create table if not exists public.fbits_order_daily_stats (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  stat_date date not null,
  receita_oficial numeric default 0,
  pedidos integer default 0,
  ticket_medio numeric default 0,
  clientes integer default 0,
  produtos_vendidos integer default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(client_id, stat_date)
);

create table if not exists public.fbits_orders (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  order_id text not null,
  order_code text,
  customer_id text,
  customer_name text,
  customer_email text,
  status_id text,
  status_name text,
  order_date timestamptz,
  approved_at timestamptz,
  total_value numeric default 0,
  products_count integer default 0,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(client_id, order_id)
);

alter table public.fbits_order_daily_stats add column if not exists receita_oficial numeric default 0;
alter table public.fbits_order_daily_stats add column if not exists pedidos integer default 0;
alter table public.fbits_order_daily_stats add column if not exists ticket_medio numeric default 0;
alter table public.fbits_order_daily_stats add column if not exists clientes integer default 0;
alter table public.fbits_order_daily_stats add column if not exists produtos_vendidos integer default 0;
alter table public.fbits_order_daily_stats add column if not exists created_at timestamptz default now();
alter table public.fbits_order_daily_stats add column if not exists updated_at timestamptz default now();

alter table public.fbits_orders add column if not exists order_code text;
alter table public.fbits_orders add column if not exists customer_id text;
alter table public.fbits_orders add column if not exists customer_name text;
alter table public.fbits_orders add column if not exists customer_email text;
alter table public.fbits_orders add column if not exists status_id text;
alter table public.fbits_orders add column if not exists status_name text;
alter table public.fbits_orders add column if not exists order_date timestamptz;
alter table public.fbits_orders add column if not exists approved_at timestamptz;
alter table public.fbits_orders add column if not exists total_value numeric default 0;
alter table public.fbits_orders add column if not exists products_count integer default 0;
alter table public.fbits_orders add column if not exists raw jsonb default '{}'::jsonb;
alter table public.fbits_orders add column if not exists created_at timestamptz default now();
alter table public.fbits_orders add column if not exists updated_at timestamptz default now();

create index if not exists idx_fbits_order_daily_stats_client_date
  on public.fbits_order_daily_stats(client_id, stat_date);

create index if not exists idx_fbits_orders_client_order_date
  on public.fbits_orders(client_id, order_date);

create index if not exists idx_fbits_orders_client_status
  on public.fbits_orders(client_id, status_id);

create unique index if not exists uq_fbits_order_daily_stats_client_date
  on public.fbits_order_daily_stats(client_id, stat_date);

create unique index if not exists uq_fbits_orders_client_order
  on public.fbits_orders(client_id, order_id);

drop trigger if exists trg_fbits_order_daily_stats_updated_at on public.fbits_order_daily_stats;
create trigger trg_fbits_order_daily_stats_updated_at
before update on public.fbits_order_daily_stats
for each row execute function public.set_updated_at();

drop trigger if exists trg_fbits_orders_updated_at on public.fbits_orders;
create trigger trg_fbits_orders_updated_at
before update on public.fbits_orders
for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
