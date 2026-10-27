-- Origem das vendas pelo GA4: para cada transação (ID do pedido enviado no
-- evento purchase), a origem/mídia e a campanha da sessão que o GA4 registrou.
--
-- Uso: pedido da loja SEM UTM (ex.: anúncio do Google com marcação automática)
-- herda, na leitura, a origem que o GA4 atribuiu à mesma transação. Nada é
-- gravado no pedido; a tela de origem combina as duas fontes.
--
-- - Sem dado pessoal: só ID da transação (número do pedido), datas, origem,
--   campanha e valores.
-- - Uma linha por transação e empresa/propriedade (eventos purchase repetidos
--   do GA4 não duplicam).
-- - Acesso só pelo backend (service_role); RLS ligado sem políticas.

create table if not exists public.ga4_transaction_attribution (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  property_id text not null,
  transaction_id text not null,
  stat_date date not null,
  source_medium text not null default '',
  source text,
  medium text,
  campaign_name text,
  purchases integer not null default 0,
  purchase_revenue numeric(18, 2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, property_id, transaction_id)
);

create index if not exists idx_ga4_transaction_attribution_client_date
  on public.ga4_transaction_attribution (client_id, stat_date);

alter table public.ga4_transaction_attribution enable row level security;
revoke all on public.ga4_transaction_attribution from public, anon, authenticated;
grant select, insert, update, delete on public.ga4_transaction_attribution to service_role;

notify pgrst, 'reload schema';
