-- READ ONLY: every statement in this file is SELECT/WITH SELECT.
-- Run with the same database role used by the audit, never in a migration runner.

select
  to_regclass('public.cron_locks') is not null as cron_locks_exists,
  to_regclass('public.cron_job_runs') is not null as cron_job_runs_exists;

select
  p.proname,
  pg_get_function_identity_arguments(p.oid) as arguments,
  has_function_privilege(current_user, p.oid, 'EXECUTE') as current_role_can_execute,
  pg_get_functiondef(p.oid) ilike '%locked_until < v_now%' as has_expiration_guard,
  pg_get_functiondef(p.oid) ilike '%greatest(30, p_ttl_seconds)%' as has_minimum_ttl,
  pg_get_functiondef(p.oid) ilike '%locked_until = now() - interval ''1 second''%' as has_explicit_release
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in ('acquire_client_job_lock', 'release_client_job_lock')
order by p.proname;

select
  c.conname,
  pg_get_constraintdef(c.oid) as definition
from pg_constraint c
where c.conrelid = 'public.cron_locks'::regclass
order by c.conname;

select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename in ('cron_locks', 'cron_job_runs')
order by tablename, indexname;

select
  current_user as audit_role,
  has_table_privilege(current_user, 'public.cron_locks', 'SELECT') as can_select_cron_locks,
  has_table_privilege(current_user, 'public.cron_job_runs', 'SELECT') as can_select_cron_job_runs;

with stale_locks as (
  select client_id, job_name, locked_until, updated_at
  from public.cron_locks
  where locked_until < now()
)
select count(*) as expired_lock_rows, min(locked_until) as oldest_expired_lock
from stale_locks;

select client_id, job_name, locked_until, updated_at
from public.cron_locks
where locked_until >= now()
order by locked_until
limit 100;
