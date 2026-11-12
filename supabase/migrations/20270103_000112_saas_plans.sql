-- LOCAL: NÃO APLICADA (000112). Revisão/aplicação remota manual; feature aditiva.
-- Estrutura de SaaS: planos com limites, assinatura por empresa, faturas e uso do mês.
-- Empresa SEM assinatura continua sem limite nenhum (os clientes atuais da Mugô não mudam nada).
-- Cobrança começa "manual" (a Mugô marca a fatura como paga); o provedor de pagamento entra depois sem mudar estas tabelas.
-- Só o service role lê e escreve.

create table if not exists public.saas_plans (
  id text primary key check (id ~ '^[a-z0-9_]{2,40}$'),
  name text not null check (length(name) between 2 and 60),
  price_month_cents integer not null check (price_month_cents >= 0),
  limits jsonb not null default '{}'::jsonb,
  features jsonb not null default '[]'::jsonb,
  active boolean not null default true,
  sort integer not null default 0
);

insert into public.saas_plans (id, name, price_month_cents, limits, features, sort) values
  ('essencial', 'Essencial', 49700,
   '{"users": 3, "email_sends_month": 10000, "whatsapp_month": 500, "ai_actions_month": 10, "competitors": 3, "monitored_products": 20}',
   '["Dashboards de Meta, Google, GA4 e loja", "CRM com jornada do cliente", "E-mail marketing e carrinho abandonado", "Benchmarking de Instagram"]', 1),
  ('crescimento', 'Crescimento', 99700,
   '{"users": 8, "email_sends_month": 50000, "whatsapp_month": 3000, "ai_actions_month": 40, "competitors": 8, "monitored_products": 80}',
   '["Tudo do Essencial", "Fluxos automáticos", "Ações da IA", "LTV, CAC e coortes", "Preços dos concorrentes"]', 2),
  ('escala', 'Escala', 199700,
   '{"users": 25, "email_sends_month": 200000, "whatsapp_month": 15000, "ai_actions_month": 200, "competitors": 20, "monitored_products": 200}',
   '["Tudo do Crescimento", "Mais volume de envio", "Mais concorrentes e produtos monitorados", "Suporte prioritário da Mugô"]', 3)
on conflict (id) do nothing;

create table if not exists public.client_subscriptions (
  client_id text primary key references public.clients(id) on delete cascade,
  plan_id text not null references public.saas_plans(id),
  status text not null default 'teste' check (status in ('teste', 'ativa', 'atrasada', 'cancelada', 'cortesia')),
  trial_ends_at timestamptz,
  current_period_end date,
  billing_day integer not null default 5 check (billing_day between 1 and 28),
  billing_provider text not null default 'manual' check (billing_provider in ('manual', 'asaas', 'stripe')),
  provider_customer_id text,
  provider_subscription_id text,
  notes text check (notes is null or length(notes) <= 1000),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.billing_invoices (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  period text not null check (period ~ '^\d{4}-\d{2}$'),
  plan_id text not null,
  amount_cents integer not null check (amount_cents >= 0),
  status text not null default 'aberta' check (status in ('aberta', 'paga', 'vencida', 'cancelada')),
  due_date date not null,
  paid_at timestamptz,
  provider_id text,
  payment_url text check (payment_url is null or payment_url ~* '^https://'),
  created_at timestamptz not null default now(),
  unique (client_id, period)
);
create index if not exists billing_invoices_client_idx on public.billing_invoices (client_id, period desc);

alter table public.saas_plans enable row level security;
alter table public.client_subscriptions enable row level security;
alter table public.billing_invoices enable row level security;
revoke all on public.saas_plans, public.client_subscriptions, public.billing_invoices from anon, authenticated;
grant all on public.saas_plans, public.client_subscriptions, public.billing_invoices to service_role;

notify pgrst, 'reload schema';
