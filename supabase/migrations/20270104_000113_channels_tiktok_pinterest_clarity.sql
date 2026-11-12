-- LOCAL: NÃO APLICADA
-- Novas fontes: TikTok Ads, TikTok orgânico, Pinterest e LinkedIn (anúncios e orgânico) e Microsoft Clarity.
-- Aditiva: amplia os provedores aceitos e cria a tabela diária das métricas desses canais.

alter table public.integration_connections drop constraint if exists integration_connections_provider_check;
alter table public.integration_connections add constraint integration_connections_provider_check
  check (provider in ('meta', 'instagram', 'google_ads', 'ga4', 'shopify', 'fbits',
                      'tiktok_ads', 'tiktok', 'pinterest', 'linkedin', 'clarity'));

alter table public.oauth_sessions drop constraint if exists oauth_sessions_provider_check;
alter table public.oauth_sessions add constraint oauth_sessions_provider_check
  check (provider in ('meta', 'google', 'shopify', 'google_calendar', 'tiktok_ads', 'tiktok', 'pinterest', 'linkedin'));

-- Uma linha por empresa, canal, nível (conta, campanha, conteúdo, página), item e dia.
-- spend/impressions/clicks/conversions servem para somar entre canais; o resto fica em metrics.
create table if not exists public.channel_daily_metrics (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  provider text not null check (provider in ('tiktok_ads', 'tiktok', 'pinterest_ads', 'pinterest', 'linkedin_ads', 'linkedin', 'clarity')),
  level text not null check (level in ('account', 'campaign', 'content', 'page')),
  account_id text not null default '',
  entity_id text not null default '',
  entity_name text,
  metric_date date not null,
  spend numeric(14, 2),
  impressions bigint,
  clicks bigint,
  conversions numeric(14, 2),
  metrics jsonb not null default '{}'::jsonb,
  collected_at timestamptz not null default now(),
  unique (client_id, provider, level, account_id, entity_id, metric_date)
);

create index if not exists channel_daily_metrics_client_date_idx
  on public.channel_daily_metrics (client_id, provider, metric_date desc);

alter table public.channel_daily_metrics enable row level security;
-- Leitura e escrita só pelo backend (service role), como as demais tabelas de dados de canal.
