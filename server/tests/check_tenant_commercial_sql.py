"""Integration contract for migration 000113 against disposable PostgreSQL only.

Run through GitHub Actions with an ephemeral PostgreSQL container.
No Supabase credentials or production client data are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID

import psycopg

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20270104_000113_tenant_commercial_modules.sql"
PG = os.environ["COMMERCIAL_TEST_DATABASE_URL"]
ADMIN = "11111111-1111-4111-8111-111111111111"
AGENCY = "22222222-2222-4222-8222-222222222222"
CUSTOMER = "33333333-3333-4333-8333-333333333333"


def connect():
    return psycopg.connect(PG, autocommit=True)


def query(conn, sql, values=()):
    with conn.cursor() as cursor:
        if values:
            cursor.execute(sql, values)
        else:
            cursor.execute(sql)
        if cursor.description:
            return cursor.fetchall()


def write(client_id, keys, version, actor=ADMIN):
    with connect() as conn:
        query(conn, "set role service_role")
        return query(conn, "select public.save_tenant_commercial_modules(%s,%s::jsonb,%s,%s::uuid)",
                     (client_id, json.dumps(keys), version, actor))[0][0]


def rejects(fn, expected):
    try:
        fn()
    except psycopg.Error as exc:
        assert expected in str(exc), f"expected {expected!r} got {exc!r}"
    else:
        raise AssertionError(f"expected DB rejection: {expected}")


def main():
    with connect() as conn:
        # Intentionally minimal prerequisites matching migration 000020/000112.
        query(conn, """
          create schema auth;
          create table auth.users(id uuid primary key);
          create table public.clients(id text primary key);
          create table public.platform_admins(user_id uuid primary key references auth.users(id), role text not null);
          create table public.client_memberships(user_id uuid not null references auth.users(id),
                                                client_id text not null references public.clients(id),
                                                role text not null);
          create role service_role bypassrls;
          create role anon;
          create role authenticated;
          grant select on public.clients, public.platform_admins, public.client_memberships to service_role;
          create function public.is_platform_admin(p_user_id uuid)
          returns boolean language sql stable security definer set search_path = public
          as $$ select exists(select 1 from public.platform_admins
                              where user_id = p_user_id and role = 'platform_admin') $$;
          grant execute on function public.is_platform_admin(uuid) to service_role;
          insert into auth.users values
            ('11111111-1111-4111-8111-111111111111'),
            ('22222222-2222-4222-8222-222222222222'),
            ('33333333-3333-4333-8333-333333333333');
          insert into public.clients values ('tenant-a'), ('tenant-b');
          insert into public.platform_admins values ('11111111-1111-4111-8111-111111111111', 'platform_admin');
          insert into public.client_memberships values
            ('22222222-2222-4222-8222-222222222222', 'tenant-a', 'agency_admin'),
            ('33333333-3333-4333-8333-333333333333', 'tenant-a', 'client_admin');
        """)
        query(conn, MIGRATION.read_text(encoding="utf-8"))
        # Config inexistente: nenhuma linha criada por migration.
        assert query(conn, "select count(*) from public.tenant_commercial_modules")[0][0] == 0
        assert query(conn, "select count(*) from public.tenant_commercial_module_audit")[0][0] == 0

    # Isolated tenants and explicit empty are distinct from missing rows.
    a = write("tenant-a", ["meta"], None)
    b = write("tenant-b", ["social_media"], None, AGENCY)
    assert (a["version"], b["version"]) == (1, 1)
    assert a["module_keys"] == ["meta"] and b["module_keys"] == ["social_media"]
    with connect() as conn:
        assert query(conn, "select count(*) from public.tenant_commercial_modules")[0][0] == 2
    a2 = write("tenant-a", [], 1)
    assert a2["module_keys"] == [] and a2["version"] == 2
    with connect() as conn:
        row = query(conn, """select previous_module_keys, module_keys, previous_version, version
                             from public.tenant_commercial_module_audit
                             where client_id='tenant-a' order by version""")
        assert row == [(None, ["meta"], None, 1), (["meta"], [], 1, 2)]
        assert query(conn, "select module_keys from public.tenant_commercial_modules where client_id='tenant-b'")[0][0] == ["social_media"]
    rejects(lambda: write("tenant-a", ["meta"], 1), "commercial_config_conflict")
    rejects(lambda: write("tenant-a", ["invalid"], 2), "commercial_modules_invalid")
    rejects(lambda: write("tenant-a", ["meta", "meta"], 2), "commercial_modules_invalid")
    rejects(lambda: write("tenant-a", ["redacao"], 2), "commercial_modules_invalid")
    rejects(lambda: write("tenant-a", ["meta"], 2, CUSTOMER), "commercial_admin_required")
    rejects(lambda: write("missing-tenant", ["meta"], None), "commercial_client_not_found")
    rejects(lambda: write("tenant-a", "meta", 2), "commercial_modules_invalid")

    # Simulate a failed audit write: transaction must roll back module update.
    with connect() as conn:
        query(conn, """
          create function public.reject_crm_audit() returns trigger language plpgsql as $$
          begin
            if new.module_keys @> '["crm"]'::jsonb then
              raise exception 'audit_insert_failed';
            end if;
            return new;
          end $$;
          create trigger block_crm_audit before insert on public.tenant_commercial_module_audit
            for each row execute function public.reject_crm_audit();
        """)
    rejects(lambda: write("tenant-a", ["crm"], 2), "audit_insert_failed")
    with connect() as conn:
        assert query(conn, "select module_keys,version from public.tenant_commercial_modules where client_id='tenant-a'") == [([], 2)]
        assert query(conn, "select count(*) from public.tenant_commercial_module_audit where client_id='tenant-a'")[0][0] == 2
        query(conn, "drop trigger block_crm_audit on public.tenant_commercial_module_audit")

    # Two simultaneous admins with stale expected_version: exactly one succeeds.
    gate = Barrier(2)

    def contender(keys):
        gate.wait(timeout=10)
        try:
            return ("ok", write("tenant-a", keys, 2))
        except psycopg.Error as exc:
            return ("conflict", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, (["google"], ["ecommerce"])))
    assert sorted(x[0] for x in results) == ["conflict", "ok"], results
    assert "commercial_config_conflict" in next(x[1] for x in results if x[0] == "conflict")
    with connect() as conn:
        assert query(conn, "select version from public.tenant_commercial_modules where client_id='tenant-a'")[0][0] == 3
        assert query(conn, "select count(*) from public.tenant_commercial_module_audit where client_id='tenant-a'")[0][0] == 3
        # Data API cannot be used by untrusted roles directly.
        assert query(conn, "select has_table_privilege('authenticated', 'public.tenant_commercial_modules', 'INSERT')")[0][0] is False
        assert query(conn, "select has_function_privilege('authenticated', 'public.save_tenant_commercial_modules(text,jsonb,bigint,uuid)', 'EXECUTE')")[0][0] is False
    print("PASS isolated PostgreSQL: 000113, explicit empty, tenant scope, roles, audit rollback, concurrency")


if __name__ == "__main__":
    main()
