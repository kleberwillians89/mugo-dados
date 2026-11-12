-- LOCAL: NÃO APLICADA (000109). Revisão/aplicação remota manual; feature aditiva. Depende da 000108.
-- Fluxos comerciais automáticos por marca: boas-vindas, pós-venda, segunda compra e reativação (e-mail ou WhatsApp).
-- flow_sends garante 1 envio por pessoa, fluxo e pedido de referência (rodar de novo nunca duplica).
-- Destinatário só como hash do e-mail; telefone nunca gravado. Só o service role lê e escreve.

create table if not exists public.commercial_flows (
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null check (kind in ('boas_vindas', 'pos_venda', 'segunda_compra', 'reativacao')),
  enabled boolean not null default false,
  channel text not null default 'email' check (channel in ('email', 'whatsapp')),
  delay_days integer not null check (delay_days between 0 and 365),
  consent text not null default 'consentimento' check (consent in ('consentimento', 'todos')),
  subject text not null default '' check (length(subject) <= 200),
  preheader text not null default '' check (length(preheader) <= 200),
  design jsonb not null default '{"blocks": []}'::jsonb,
  custom_html text check (custom_html is null or length(custom_html) <= 300000),
  whatsapp_template text check (whatsapp_template is null or length(whatsapp_template) <= 512),
  whatsapp_language text not null default 'pt_BR' check (length(whatsapp_language) <= 12),
  whatsapp_variables jsonb not null default '["nome"]'::jsonb,
  updated_by uuid,
  updated_at timestamptz not null default now(),
  primary key (client_id, kind)
);

create table if not exists public.flow_sends (
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null,
  email_hash text not null check (length(email_hash) = 32),
  ref text not null check (length(ref) between 1 and 40),
  channel text not null check (channel in ('email', 'whatsapp')),
  status text not null check (status in ('enviado', 'simulado', 'pulado', 'falhou')),
  reason text,
  provider_id text,
  at timestamptz not null default now(),
  primary key (client_id, kind, email_hash, ref)
);
create index if not exists flow_sends_recent_idx on public.flow_sends (client_id, at desc);

alter table public.commercial_flows enable row level security;
alter table public.flow_sends enable row level security;
revoke all on public.commercial_flows, public.flow_sends from anon, authenticated;
grant all on public.commercial_flows, public.flow_sends to service_role;

notify pgrst, 'reload schema';
