-- Não aplicar automaticamente: revisão e homologação antes da produção.
-- Captura universal por fonte: credencial SHA-256, PII criptografada no backend,
-- consentimento declarado mas NÃO verificado (nenhum disparo habilitado).
create table if not exists public.lead_capture_sources (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(name) between 1 and 100),
  kind text not null check (kind in ('custom_form','shopify','ecommerce','meta_leads','other')),
  token_hash text not null check (length(token_hash) = 64),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  last_received_at timestamptz,
  unique (id, client_id)
);
create index if not exists lead_capture_sources_tenant_idx
  on public.lead_capture_sources(client_id, created_at desc);

create table if not exists public.lead_capture_events (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  source_id uuid not null,
  event_id text not null check (length(event_id) between 1 and 160),
  email_hash text check (email_hash is null or length(email_hash) = 64),
  phone_hash text check (phone_hash is null or length(phone_hash) = 64),
  email_ciphertext text,
  phone_ciphertext text,
  origin_label text check (origin_label is null or length(origin_label) <= 100),
  consent_email_claimed boolean,
  consent_whatsapp_claimed boolean,
  consent_verified boolean not null default false,
  status text not null default 'captured' check (status in ('captured','reviewed','rejected')),
  created_at timestamptz not null default now(),
  unique(client_id,source_id,event_id),
  foreign key (source_id,client_id) references public.lead_capture_sources(id,client_id)
);
create index if not exists lead_capture_events_tenant_created_idx
  on public.lead_capture_events(client_id,created_at desc);
create index if not exists lead_capture_events_tenant_email_idx
  on public.lead_capture_events(client_id,email_hash) where email_hash is not null;
create index if not exists lead_capture_events_tenant_phone_idx
  on public.lead_capture_events(client_id,phone_hash) where phone_hash is not null;

alter table public.lead_capture_sources enable row level security;
alter table public.lead_capture_events enable row level security;
revoke all on public.lead_capture_sources, public.lead_capture_events from anon, authenticated;
grant all on public.lead_capture_sources, public.lead_capture_events to service_role;
notify pgrst, 'reload schema';
