-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- Um app Shopify por loja: a Shopify só instala app de distribuição personalizada na loja para a qual ele foi
-- gerado. Cada cliente novo ganha o app dele no Dev Dashboard; aqui fica o Client ID e o segredo (criptografado
-- com a chave do servidor). Sem linha para a loja, vale o app padrão das variáveis de ambiente (o da Roove).
create table if not exists public.shopify_app_credentials (
  shop_domain text primary key check (shop_domain ~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.myshopify\.com$'),
  client_id text not null,
  app_client_id text not null check (char_length(app_client_id) between 8 and 120),
  client_secret_encrypted text not null,
  updated_by uuid,
  updated_at timestamptz not null default now()
);
create index if not exists shopify_app_credentials_client_idx on public.shopify_app_credentials (client_id);
alter table public.shopify_app_credentials enable row level security;
revoke all on public.shopify_app_credentials from anon, authenticated;
grant all on public.shopify_app_credentials to service_role;
notify pgrst, 'reload schema';

-- Reversão:
-- drop table if exists public.shopify_app_credentials;
