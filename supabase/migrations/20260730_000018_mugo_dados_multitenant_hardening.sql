-- Mugô Dados: hardening multiempresa, perfis oficiais e clientes iniciais.
-- Idempotente e sem vínculos automáticos com usuários.

alter table public.client_memberships
  drop constraint if exists client_memberships_role_check;

update public.client_memberships set role = 'client_admin' where role in ('owner', 'admin');

alter table public.client_memberships
  add constraint client_memberships_role_check
  check (role in ('agency_admin', 'client_admin', 'viewer'));

insert into public.clients (id, name)
select seed.id, seed.name
from (
  values
    ('amalie', 'Amalie'),
    ('roove', 'Roove'),
    ('ruah-parfums', 'Ruah Parfums')
) as seed(id, name)
where not exists (
  select 1 from public.clients c where lower(c.name) = lower(seed.name)
)
on conflict (id) do nothing;

create table if not exists public.integration_connections (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete restrict,
  provider text not null check (provider in ('meta', 'instagram', 'google_ads', 'ga4', 'shopify', 'fbits')),
  status text not null default 'not_configured' check (
    status in (
      'not_configured', 'connecting', 'importing', 'connected', 'updated',
      'stale', 'token_expired', 'reauth_required', 'sync_error', 'disconnected'
    )
  ),
  account_id text,
  account_name text,
  encrypted_access_token text,
  encrypted_refresh_token text,
  token_expires_at timestamptz,
  last_sync_at timestamptz,
  next_sync_at timestamptz,
  historical_start date,
  historical_end date,
  last_error text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, provider, account_id)
);

create index if not exists integration_connections_client_provider_idx
  on public.integration_connections (client_id, provider, updated_at desc);

drop trigger if exists trg_integration_connections_updated_at on public.integration_connections;
create trigger trg_integration_connections_updated_at
before update on public.integration_connections
for each row execute function public.set_updated_at();

alter table public.integration_connections enable row level security;
drop policy if exists integration_connections_member_select on public.integration_connections;
create policy integration_connections_member_select on public.integration_connections
for select using (public.is_client_member(client_id));

revoke all on public.integration_connections from anon, authenticated;
grant select (
  id, client_id, provider, status, account_id, account_name, token_expires_at,
  last_sync_at, next_sync_at, historical_start, historical_end, last_error,
  metadata, created_at, updated_at
) on public.integration_connections to authenticated;

-- Garante RLS de leitura em toda tabela tenant já criada pelas migrações anteriores.
do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'meta_connections', 'meta_token_events', 'cron_job_runs', 'cron_locks',
    'ad_account_daily_stats', 'campaign_daily_stats', 'ad_daily_stats',
    'promoted_post_daily_stats', 'shopify_webhook_events', 'shopify_orders',
    'shopify_order_items', 'shopify_customers', 'ga4_daily_stats',
    'ga4_channel_stats', 'ga4_campaign_stats', 'ga4_event_stats',
    'fbits_order_daily_stats', 'fbits_orders', 'fbits_order_items'
  ]
  loop
    if to_regclass('public.' || table_name) is not null then
      execute format('alter table public.%I enable row level security', table_name);
      execute format('drop policy if exists tenant_member_select on public.%I', table_name);
      execute format(
        'create policy tenant_member_select on public.%I for select using (public.is_client_member(client_id::text))',
        table_name
      );
    end if;
  end loop;
end
$$;
