-- LOCAL: NAO APLICADA. Migration 000122 aditiva de IA por empresa.
-- A ausencia de linha preserva o comportamento legado: chave da plataforma.

create table if not exists public.client_ai_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  mode text not null default 'platform_managed' check (mode in ('platform_managed', 'byok')),
  provider text not null default 'openai' check (provider = 'openai'),
  model text not null default 'gpt-4.1-mini' check (
    model in ('gpt-4.1-mini', 'gpt-4.1', 'gpt-4o-mini', 'gpt-4o', 'gpt-5', 'gpt-5-mini')
  ),
  encrypted_api_key text,
  credential_status text not null default 'missing' check (
    credential_status in ('missing', 'valid', 'invalid', 'unchecked')
  ),
  credential_updated_at timestamptz,
  validated_at timestamptz,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint client_ai_settings_byok_key_check check (
    mode <> 'byok' or encrypted_api_key is not null
  )
);

create index if not exists client_ai_settings_mode_idx
  on public.client_ai_settings (mode, updated_at desc);

alter table public.client_ai_settings enable row level security;
alter table public.client_ai_settings force row level security;
revoke all on public.client_ai_settings from public, anon, authenticated;
grant all on public.client_ai_settings to service_role;

alter table public.ai_usage_events
  add column if not exists credential_mode text not null default 'platform_managed'
  check (credential_mode in ('platform_managed', 'byok'));

notify pgrst, 'reload schema';
