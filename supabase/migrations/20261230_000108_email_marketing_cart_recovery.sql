-- LOCAL: NÃO APLICADA (000108). Revisão/aplicação remota manual; feature aditiva.
-- E-mail marketing (Resend) e recuperação de carrinho abandonado (Shopify → e-mail e WhatsApp).
--
-- Privacidade:
-- - destinatário de e-mail aparece só como hash (email_hash, o mesmo da jornada); o e-mail em claro vem da base
--   de clientes na hora do envio;
-- - carrinho abandonado guarda e-mail/telefone CRIPTOGRAFADOS (contact_enc, mesma chave dos tokens), só enquanto
--   a recuperação está aberta: recuperou, expirou ou a pessoa saiu → o campo é apagado;
-- - telefone nunca em claro (phone_key para cruzar com WhatsApp/jornada).
-- Só o service role lê e escreve (RLS ligado, sem policy para anon/authenticated).

create table if not exists public.email_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  from_name text check (from_name is null or length(from_name) <= 80),
  from_email text check (from_email is null or length(from_email) <= 160),
  reply_to text check (reply_to is null or length(reply_to) <= 160),
  brand_color text check (brand_color is null or brand_color ~ '^#[0-9a-fA-F]{6}$'),
  logo_url text check (logo_url is null or length(logo_url) <= 600),
  footer_text text check (footer_text is null or length(footer_text) <= 600),
  store_url text check (store_url is null or length(store_url) <= 300),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.email_suppressions (
  client_id text not null references public.clients(id) on delete cascade,
  email_hash text not null check (length(email_hash) = 32),
  reason text not null check (reason in ('descadastro', 'bounce', 'spam', 'manual')),
  at timestamptz not null default now(),
  primary key (client_id, email_hash)
);

create table if not exists public.email_campaigns (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  name text not null check (length(name) between 1 and 120),
  subject text not null default '' check (length(subject) <= 200),
  preheader text not null default '' check (length(preheader) <= 200),
  design jsonb not null default '{"blocks": []}'::jsonb,
  custom_html text check (custom_html is null or length(custom_html) <= 300000),
  audience jsonb not null default '{"segment": "consentimento"}'::jsonb,
  status text not null default 'rascunho' check (status in ('rascunho', 'agendada', 'enviando', 'enviada', 'falhou', 'cancelada')),
  scheduled_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  stats jsonb not null default '{}'::jsonb,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists email_campaigns_client_idx on public.email_campaigns (client_id, created_at desc);
create index if not exists email_campaigns_due_idx on public.email_campaigns (status, scheduled_at) where status in ('agendada', 'enviando');

-- Uma linha por e-mail enviado (campanha, carrinho ou teste). idem_key = a mesma em toda nova tentativa.
create table if not exists public.email_sends (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null check (kind in ('campanha', 'carrinho', 'teste')),
  campaign_id uuid references public.email_campaigns(id) on delete cascade,
  checkout_id text,
  email_hash text not null check (length(email_hash) = 32),
  idem_key text not null check (length(idem_key) between 3 and 200),
  resend_id text,
  status text not null default 'na_fila' check (status in ('na_fila', 'enviado', 'entregue', 'bounce', 'spam', 'falhou', 'bloqueado', 'simulado')),
  opened_at timestamptz,
  clicked_at timestamptz,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, idem_key)
);
create index if not exists email_sends_campaign_idx on public.email_sends (campaign_id, status);
create index if not exists email_sends_resend_idx on public.email_sends (resend_id) where resend_id is not null;

create table if not exists public.cart_recovery_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  enabled boolean not null default false,
  -- [{"channel": "email"|"whatsapp", "delay_minutes": 60}], na ordem de envio
  steps jsonb not null default '[{"channel": "email", "delay_minutes": 60}, {"channel": "whatsapp", "delay_minutes": 1440}]'::jsonb,
  email_subject text not null default 'Você esqueceu alguns itens no carrinho' check (length(email_subject) <= 200),
  email_design jsonb not null default '{"blocks": []}'::jsonb,
  email_custom_html text check (email_custom_html is null or length(email_custom_html) <= 300000),
  email_consent text not null default 'todos' check (email_consent in ('todos', 'consentimento')),
  whatsapp_number_id uuid,
  whatsapp_template text check (whatsapp_template is null or length(whatsapp_template) <= 512),
  whatsapp_language text not null default 'pt_BR' check (length(whatsapp_language) <= 12),
  -- variáveis do corpo do template, na ordem: nome | produto | valor | link
  whatsapp_variables jsonb not null default '["nome", "link"]'::jsonb,
  whatsapp_consent text not null default 'consentimento' check (whatsapp_consent in ('consentimento', 'consentimento_ou_conversa')),
  attribution_days integer not null default 7 check (attribution_days between 1 and 30),
  webhooks_registered_at timestamptz,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.abandoned_carts (
  client_id text not null references public.clients(id) on delete cascade,
  checkout_id text not null check (length(checkout_id) between 1 and 80),
  checkout_token text,
  cart_token text,
  created_at_shop timestamptz,
  updated_at_shop timestamptz,
  completed_at timestamptz,
  value numeric(14, 2) not null default 0,
  currency text,
  items jsonb not null default '[]'::jsonb,
  recovery_url text,
  email_hash text,
  phone_key text,
  contact_enc text,
  accepts_marketing boolean not null default false,
  status text not null default 'aberto' check (status in ('aberto', 'recuperado', 'comprou_sem_contato', 'expirado', 'sem_contato', 'pausado')),
  steps_done integer not null default 0,
  next_step_at timestamptz,
  last_touch_at timestamptz,
  recovered_order_id text,
  recovered_value numeric(14, 2),
  recovered_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (client_id, checkout_id)
);
create index if not exists abandoned_carts_due_idx on public.abandoned_carts (status, next_step_at) where status = 'aberto';
create index if not exists abandoned_carts_token_idx on public.abandoned_carts (client_id, checkout_token);
create index if not exists abandoned_carts_recent_idx on public.abandoned_carts (client_id, created_at_shop desc);

create table if not exists public.cart_recovery_touches (
  client_id text not null references public.clients(id) on delete cascade,
  checkout_id text not null,
  step integer not null check (step between 0 and 9),
  channel text not null check (channel in ('email', 'whatsapp')),
  status text not null check (status in ('enviado', 'simulado', 'pulado', 'falhou')),
  reason text,
  provider_id text,
  at timestamptz not null default now(),
  primary key (client_id, checkout_id, step)
);

alter table public.email_settings enable row level security;
alter table public.email_suppressions enable row level security;
alter table public.email_campaigns enable row level security;
alter table public.email_sends enable row level security;
alter table public.cart_recovery_settings enable row level security;
alter table public.abandoned_carts enable row level security;
alter table public.cart_recovery_touches enable row level security;

revoke all on public.email_settings, public.email_suppressions, public.email_campaigns, public.email_sends,
  public.cart_recovery_settings, public.abandoned_carts, public.cart_recovery_touches from anon, authenticated;
grant all on public.email_settings, public.email_suppressions, public.email_campaigns, public.email_sends,
  public.cart_recovery_settings, public.abandoned_carts, public.cart_recovery_touches to service_role;

notify pgrst, 'reload schema';
