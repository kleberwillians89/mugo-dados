-- LOCAL: NÃO APLICADA (000111). Revisão/aplicação remota manual; feature aditiva. Depende da 000106.
-- Benchmarking automático: preços públicos de produtos (concorrentes e a própria marca), com histórico diário,
-- e a página do Facebook do concorrente para abrir a Biblioteca de Anúncios direto nele.

alter table public.benchmark_competitors add column if not exists facebook_page text
  check (facebook_page is null or length(facebook_page) <= 200);

create table if not exists public.benchmark_products (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  competitor_id uuid,  -- null = produto da própria marca (para comparar)
  url text not null check (length(url) between 12 and 1000 and url ~* '^https://'),
  title text check (title is null or length(title) <= 300),
  image text check (image is null or length(image) <= 1000),
  price numeric(14, 2),
  compare_at numeric(14, 2),
  currency text check (currency is null or length(currency) <= 8),
  available boolean,
  source text check (source is null or source in ('shopify', 'json_ld', 'meta_tag')),
  checked_at timestamptz,
  error text check (error is null or length(error) <= 300),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (client_id, url)
);
create index if not exists benchmark_products_client_idx on public.benchmark_products (client_id, active);

create table if not exists public.benchmark_price_points (
  product_id uuid not null references public.benchmark_products(id) on delete cascade,
  observed_on date not null,
  price numeric(14, 2),
  compare_at numeric(14, 2),
  available boolean,
  primary key (product_id, observed_on)
);

alter table public.benchmark_products enable row level security;
alter table public.benchmark_price_points enable row level security;
revoke all on public.benchmark_products, public.benchmark_price_points from anon, authenticated;
grant all on public.benchmark_products, public.benchmark_price_points to service_role;

notify pgrst, 'reload schema';
