-- Benchmarking competitor watchlist and auditable external observations.
-- Additive migration, to be applied in Supabase after review. No client-side writes.
create table if not exists public.benchmark_competitors (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(trim(name)) between 2 and 120),
  website text check (website is null or length(website) <= 500),
  instagram_handle text check (instagram_handle is null or length(instagram_handle) <= 80),
  youtube_handle text check (youtube_handle is null or length(youtube_handle) <= 100),
  keywords text[] not null default '{}',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(client_id, name),
  unique(client_id, id)
);
create index if not exists benchmark_competitors_client_idx on public.benchmark_competitors(client_id, created_at desc);

create table if not exists public.benchmark_evidence (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  competitor_id uuid not null,
  category text not null check (category in ('ads','search','ecommerce','content')),
  title text not null check (length(trim(title)) between 3 and 240),
  source_url text not null check (length(source_url) between 12 and 2000 and source_url ~* '^https://'),
  observation text check (observation is null or length(observation) <= 2000),
  metric_name text check (metric_name is null or length(metric_name) <= 80),
  metric_value numeric,
  unit text check (unit is null or length(unit) <= 40),
  observed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  foreign key (client_id, competitor_id) references public.benchmark_competitors(client_id,id) on delete cascade
);
create index if not exists benchmark_evidence_client_idx on public.benchmark_evidence(client_id, observed_at desc);
create index if not exists benchmark_evidence_competitor_idx on public.benchmark_evidence(client_id, competitor_id, category, observed_at desc);

alter table public.benchmark_competitors enable row level security;
alter table public.benchmark_evidence enable row level security;
revoke all on public.benchmark_competitors, public.benchmark_evidence from anon, authenticated;
grant all on public.benchmark_competitors, public.benchmark_evidence to service_role;
notify pgrst, 'reload schema';
