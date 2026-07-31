-- OAuth hardening: finalize audit state and invalidate pending sessions created
-- before this security rollout. Idempotent and free of embedded credentials.

alter table if exists public.meta_oauth_handoffs
  add column if not exists consumed_at timestamptz,
  add column if not exists finalized_at timestamptz;

create index if not exists meta_oauth_handoffs_pending_idx
  on public.meta_oauth_handoffs(client_id, created_at desc)
  where finalized_at is null;

-- Authorization codes are single-use, but pending signed states visible in old
-- access logs must not remain consumable after this rollout.
update public.oauth_sessions
set consumed_at = now()
where consumed_at is null
  and created_at < now();

notify pgrst, 'reload schema';
