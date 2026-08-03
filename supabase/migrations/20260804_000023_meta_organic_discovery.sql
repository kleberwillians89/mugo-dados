-- Preserve every accessible Facebook Page during Meta organic discovery,
-- including Pages that do not have a professional Instagram account linked.
alter table if exists public.meta_oauth_handoffs
  add column if not exists pages_json jsonb not null default '[]'::jsonb;

alter table if exists public.ig_profile_snapshots
  add column if not exists metrics_available jsonb not null default '[]'::jsonb,
  add column if not exists metrics_unavailable jsonb not null default '[]'::jsonb;
