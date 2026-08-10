-- cron_job_runs observes jobs from both connection catalogs. A single FK on
-- connection_id cannot represent that polymorphic ownership safely.
alter table public.cron_job_runs
  add column if not exists meta_connection_id uuid,
  add column if not exists integration_connection_id uuid;

do $$
declare
  v_constraint_name text;
  v_referenced_table text;
begin
  select c.conname, referenced.relname
    into v_constraint_name, v_referenced_table
  from pg_constraint c
  join pg_class source on source.oid = c.conrelid
  join pg_namespace source_ns on source_ns.oid = source.relnamespace
  join pg_class referenced on referenced.oid = c.confrelid
  where source_ns.nspname = 'public'
    and source.relname = 'cron_job_runs'
    and c.contype = 'f'
    and c.conkey = array[
      (select attnum from pg_attribute
       where attrelid = 'public.cron_job_runs'::regclass and attname = 'connection_id')
    ]::smallint[]
  limit 1;

  if v_constraint_name is not null then
    if v_referenced_table not in ('meta_connections', 'integration_connections') then
      raise exception 'unexpected cron_job_runs.connection_id reference: %', v_referenced_table;
    end if;
    execute format('alter table public.cron_job_runs drop constraint %I', v_constraint_name);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'cron_job_runs_meta_connection_id_fkey'
      and conrelid = 'public.cron_job_runs'::regclass
  ) then
    alter table public.cron_job_runs
      add constraint cron_job_runs_meta_connection_id_fkey
      foreign key (meta_connection_id) references public.meta_connections(id) on delete set null;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'cron_job_runs_integration_connection_id_fkey'
      and conrelid = 'public.cron_job_runs'::regclass
  ) then
    alter table public.cron_job_runs
      add constraint cron_job_runs_integration_connection_id_fkey
      foreign key (integration_connection_id) references public.integration_connections(id) on delete set null;
  end if;
end $$;

create or replace function public.resolve_cron_job_run_connection()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  new.meta_connection_id := null;
  new.integration_connection_id := null;
  if new.connection_id is null then
    return new;
  end if;
  if exists (select 1 from meta_connections where id = new.connection_id) then
    new.meta_connection_id := new.connection_id;
  elsif exists (select 1 from integration_connections where id = new.connection_id) then
    new.integration_connection_id := new.connection_id;
  else
    raise foreign_key_violation using
      message = format('connection_id %s is absent from supported connection catalogs', new.connection_id);
  end if;
  return new;
end;
$$;

drop trigger if exists trg_cron_job_runs_resolve_connection on public.cron_job_runs;
create trigger trg_cron_job_runs_resolve_connection
before insert or update of connection_id on public.cron_job_runs
for each row execute function public.resolve_cron_job_run_connection();

update public.cron_job_runs set connection_id = connection_id
where connection_id is not null;

create index if not exists idx_cron_job_runs_meta_connection_started
  on public.cron_job_runs(meta_connection_id, started_at desc);
create index if not exists idx_cron_job_runs_integration_connection_started
  on public.cron_job_runs(integration_connection_id, started_at desc);

notify pgrst, 'reload schema';
