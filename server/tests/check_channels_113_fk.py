"""Reproduce merged migration 000113 type mismatch without touching remote databases.

The correction is evaluated in memory, without rewriting the integrated SQL
before every remote environment's applied migration history is verified.
"""
from pathlib import Path
import os
import psycopg
from psycopg import errors

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20270104_000113_channels_tiktok_pinterest_clarity.sql"
ORIGINAL = "client_id uuid not null references public.clients(id) on delete cascade"
CORRECTED = "client_id text not null references public.clients(id) on delete cascade"

def main():
    with psycopg.connect(os.environ["CHANNELS_TEST_DATABASE_URL"], autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
              create extension if not exists pgcrypto;
              create table public.clients(id text primary key);
              create table public.integration_connections(
                id uuid primary key default gen_random_uuid(),
                provider text not null,
                constraint integration_connections_provider_check check(provider in ('meta','google_ads'))
              );
              create table public.oauth_sessions(
                id uuid primary key default gen_random_uuid(),
                provider text not null,
                constraint oauth_sessions_provider_check check(provider in ('meta','google'))
              );
              insert into public.clients(id) values ('tenant-a'), ('legacy-customer-123');
            """)
        original = MIGRATION.read_text(encoding="utf-8")
        assert original.count(ORIGINAL) == 1, "the 113 migration changed; review expected definition"
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(original)
        except errors.DatatypeMismatch as exc:
            assert "incompatible" in str(exc).lower() or "cannot be implemented" in str(exc).lower(), str(exc)
        else:
            raise AssertionError("Expected 000113 FK UUID -> TEXT incompatibility did not occur")

        fixed = original.replace(ORIGINAL, CORRECTED)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(fixed)
                cur.execute("""
                   select data_type from information_schema.columns
                   where table_schema='public' and table_name='channel_daily_metrics' and column_name='client_id'
                """)
                assert cur.fetchone() == ("text",)
                cur.execute("""
                  select count(*) from pg_constraint c
                  where c.conrelid='public.channel_daily_metrics'::regclass
                    and c.contype='f' and c.confrelid='public.clients'::regclass
                """)
                assert cur.fetchone() == (1,)
                cur.execute("""
                  insert into public.channel_daily_metrics(client_id,provider,level,metric_date)
                  values ('legacy-customer-123','pinterest','account','2026-11-12')
                """)
                cur.execute("select client_id from public.channel_daily_metrics")
                assert cur.fetchone() == ("legacy-customer-123",)
                cur.execute("""
                  select relrowsecurity from pg_class
                  where oid='public.channel_daily_metrics'::regclass
                """)
                assert cur.fetchone() == (True,)
                cur.execute("select id from public.clients order by id")
                assert [row[0] for row in cur.fetchall()] == ["legacy-customer-123","tenant-a"]

    print("PASS: original channels 000113 fails on UUID/TEXT FK; proposed TEXT FK passes without rewriting IDs")

if __name__ == "__main__":
    main()
