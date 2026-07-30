-- Persistência de handoff OAuth da Meta
-- Objetivo:
-- 1) sobreviver a restart do backend
-- 2) suportar múltiplas instâncias
-- 3) manter TTL curto no banco com limpeza pelo backend

create extension if not exists pgcrypto;

create table if not exists public.meta_oauth_handoffs (
  handoff uuid primary key,
  user_id text not null,
  client_id text not null,
  encrypted_access_token text not null,
  expires_at timestamptz,
  meta_user_json jsonb not null default '{}'::jsonb,
  instagram_accounts_json jsonb not null default '[]'::jsonb,
  ad_accounts_json jsonb not null default '[]'::jsonb,
  scopes_json jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

alter table if exists public.meta_oauth_handoffs
  add column if not exists user_id text;
alter table if exists public.meta_oauth_handoffs
  add column if not exists client_id text;
alter table if exists public.meta_oauth_handoffs
  add column if not exists encrypted_access_token text;
alter table if exists public.meta_oauth_handoffs
  add column if not exists expires_at timestamptz;
alter table if exists public.meta_oauth_handoffs
  add column if not exists meta_user_json jsonb default '{}'::jsonb;
alter table if exists public.meta_oauth_handoffs
  add column if not exists instagram_accounts_json jsonb default '[]'::jsonb;
alter table if exists public.meta_oauth_handoffs
  add column if not exists ad_accounts_json jsonb default '[]'::jsonb;
alter table if exists public.meta_oauth_handoffs
  add column if not exists scopes_json jsonb default '[]'::jsonb;
alter table if exists public.meta_oauth_handoffs
  add column if not exists created_at timestamptz default now();

update public.meta_oauth_handoffs
set meta_user_json = coalesce(meta_user_json, '{}'::jsonb)
where meta_user_json is null;

update public.meta_oauth_handoffs
set instagram_accounts_json = coalesce(instagram_accounts_json, '[]'::jsonb)
where instagram_accounts_json is null;

update public.meta_oauth_handoffs
set ad_accounts_json = coalesce(ad_accounts_json, '[]'::jsonb)
where ad_accounts_json is null;

update public.meta_oauth_handoffs
set scopes_json = coalesce(scopes_json, '[]'::jsonb)
where scopes_json is null;

alter table public.meta_oauth_handoffs
  alter column meta_user_json set default '{}'::jsonb;

alter table public.meta_oauth_handoffs
  alter column instagram_accounts_json set default '[]'::jsonb;

alter table public.meta_oauth_handoffs
  alter column ad_accounts_json set default '[]'::jsonb;

alter table public.meta_oauth_handoffs
  alter column scopes_json set default '[]'::jsonb;

create index if not exists idx_meta_oauth_handoffs_user_created
  on public.meta_oauth_handoffs(user_id, created_at desc);

create index if not exists idx_meta_oauth_handoffs_client_created
  on public.meta_oauth_handoffs(client_id, created_at desc);

create index if not exists idx_meta_oauth_handoffs_created
  on public.meta_oauth_handoffs(created_at desc);

notify pgrst, 'reload schema';
