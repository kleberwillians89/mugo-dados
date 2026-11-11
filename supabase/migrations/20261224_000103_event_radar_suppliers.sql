-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Evento: radar (clima e notícias da região) e fornecedores.
-- * studio_projects.radar guarda o último radar do evento (previsão ou clima típico, alertas e notícias da região);
-- * studio_suppliers é o cadastro de fornecedores da empresa (aba Fornecedores do Evento);
-- * studio_project_suppliers liga fornecedor ↔ evento com o que faz, status e valor (vai para o orçamento).

alter table public.studio_projects add column if not exists radar jsonb not null default '{}'::jsonb
  check (jsonb_typeof(radar) = 'object');

create table if not exists public.studio_suppliers (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(name) between 1 and 120),
  category text not null default 'outros' check (category in ('buffet', 'bebidas', 'fotografia', 'video', 'som_luz', 'estrutura',
    'decoracao', 'espaco', 'seguranca', 'limpeza', 'transporte', 'staff', 'brindes', 'impressao', 'talentos', 'outros')),
  contact_name text check (contact_name is null or length(contact_name) <= 120),
  phone text check (phone is null or length(phone) <= 40),
  email text check (email is null or length(email) <= 200),
  website text check (website is null or length(website) <= 300),
  city text check (city is null or length(city) <= 120),
  price_note text check (price_note is null or length(price_note) <= 200),
  rating smallint check (rating is null or rating between 1 and 5),
  notes text check (notes is null or length(notes) <= 1000),
  active boolean not null default true,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists studio_suppliers_client_idx on public.studio_suppliers (client_id, category, name);

create table if not exists public.studio_project_suppliers (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  project_id uuid not null references public.studio_projects(id) on delete cascade,
  supplier_id uuid not null references public.studio_suppliers(id) on delete cascade,
  item text check (item is null or length(item) <= 160),
  status text not null default 'cotando' check (status in ('cotando', 'contratado', 'confirmado', 'cancelado')),
  value numeric(14, 2) check (value is null or value >= 0),
  notes text check (notes is null or length(notes) <= 500),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, supplier_id)
);
create index if not exists studio_project_suppliers_project_idx on public.studio_project_suppliers (client_id, project_id);

alter table public.studio_suppliers enable row level security;
alter table public.studio_project_suppliers enable row level security;
revoke all on public.studio_suppliers, public.studio_project_suppliers from anon, authenticated;
grant all on public.studio_suppliers, public.studio_project_suppliers to service_role;

notify pgrst, 'reload schema';
