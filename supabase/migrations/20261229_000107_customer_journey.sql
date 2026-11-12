-- LOCAL: NÃO APLICADA (000107). Revisão/aplicação remota manual; feature aditiva.
-- Fundação da jornada (Customer 360): cada pessoa da empresa com todos os seus identificadores e uma linha do
-- tempo de eventos confirmados (conversa no WhatsApp, pedido, recompra...). É a base para a jornada, a
-- recuperação de carrinho, as automações comerciais e o LTV.
--
-- Privacidade: telefone nunca é gravado aqui (só a phone_key, um hash; a mesma do WhatsApp/CRM); e-mail entra
-- como hash. O id do cliente da loja entra como está (não é dado pessoal sozinho). Só o service role lê.

create table if not exists public.customer_identities (
  client_id text not null references public.clients(id) on delete cascade,
  kind text not null check (kind in ('external_id', 'email_hash', 'phone_key', 'customer_page')),
  value text not null check (length(value) between 1 and 200),
  person_id text not null check (length(person_id) = 32),
  source text,
  built_at timestamptz not null default now(),
  primary key (client_id, kind, value)
);
create index if not exists customer_identities_person_idx on public.customer_identities (client_id, person_id);

create table if not exists public.customer_events (
  client_id text not null references public.clients(id) on delete cascade,
  event_key text not null check (length(event_key) between 3 and 300),
  person_id text not null check (length(person_id) = 32),
  kind text not null check (kind in ('conversa_whatsapp', 'pedido', 'recompra', 'pedido_cancelado',
                                     'carrinho_abandonado', 'mensagem_enviada', 'carrinho_recuperado')),
  at timestamptz not null,
  source text not null,
  channel text,
  campaign text,
  ad_id text,
  value numeric(18, 2),
  evidence text not null default 'observado' check (evidence in ('observado', 'regra')),
  detail jsonb not null default '{}'::jsonb check (jsonb_typeof(detail) = 'object'),
  built_at timestamptz not null default now(),
  primary key (client_id, event_key)
);
create index if not exists customer_events_person_idx on public.customer_events (client_id, person_id, at);
create index if not exists customer_events_kind_idx on public.customer_events (client_id, kind, at desc);

-- Quando a jornada de cada empresa foi montada e o que entrou (a tela mostra).
create table if not exists public.customer_journey_runs (
  client_id text primary key references public.clients(id) on delete cascade,
  built_at timestamptz not null default now(),
  stats jsonb not null default '{}'::jsonb check (jsonb_typeof(stats) = 'object')
);

alter table public.customer_identities enable row level security;
alter table public.customer_events enable row level security;
alter table public.customer_journey_runs enable row level security;
revoke all on public.customer_identities, public.customer_events, public.customer_journey_runs from anon, authenticated;
grant all on public.customer_identities, public.customer_events, public.customer_journey_runs to service_role;

notify pgrst, 'reload schema';
