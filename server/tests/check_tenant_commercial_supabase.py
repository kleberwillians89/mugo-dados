"""Supabase CLI integration: real GoTrue Auth + PostgREST + commercial FastAPI routes.

Only for an ephemeral local stack started by GitHub Actions. Does not connect
to Supabase hosted projects and never emits keys or auth tokens into test logs.
"""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import os
import subprocess
import sys
from pathlib import Path

import httpx
import psycopg
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def local_config():
    # Capture locally generated keys in memory. Never print the status output.
    proc = subprocess.run(["supabase", "status", "-o", "env"], capture_output=True, text=True, check=True)
    result = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        result[key] = val.strip().strip('"')
    api = result.get("API_URL")
    anon = result.get("ANON_KEY")
    service = result.get("SERVICE_ROLE_KEY")
    db = result.get("DB_URL")
    if not all((api, anon, service, db)):
        raise RuntimeError("Local stack did not expose expected API_URL/ANON_KEY/SERVICE_ROLE_KEY/DB_URL")
    if not api.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("SECURITY: Supabase API URL is not loopback")
    if not db.startswith(("postgresql://postgres:", "postgres://postgres:")):
        raise RuntimeError("SECURITY: DB URL is not the Supabase CLI local connection")
    os.environ.update({
        "SUPABASE_URL": api, "SUPABASE_ANON_KEY": anon,
        "SUPABASE_SERVICE_ROLE_KEY": service,
        "APP_ENV": "test", "ALLOW_NO_AUTH": "false",
        "ALLOW_UNVERIFIED_JWT_DEV": "false",
    })
    return api, anon, service, db


def must(response, code):
    assert response.status_code == code, f"Unexpected response status: {response.status_code} != {code}"
    return response.json()


async def integration():
    api, anon, service, db_url = local_config()
    # All identities are synthetically created in local GoTrue. No real emails.
    actors = {
        "platform": "platform@homolog.invalid",
        "agency": "agency@homolog.invalid",
        "client": "client@homolog.invalid",
    }
    password = "local-fixture-Only-2026!"
    headers_service = {"apikey": service, "Authorization": f"Bearer {service}"}
    headers_anon = {"apikey": anon}
    actor_ids = {}
    tokens = {}

    async with httpx.AsyncClient(timeout=30) as http:
        for label, email in actors.items():
            created = must(await http.post(
                f"{api}/auth/v1/admin/users", headers=headers_service,
                json={"email": email, "password": password, "email_confirm": True},
            ), 200)
            actor_ids[label] = created["id"]
            auth = must(await http.post(
                f"{api}/auth/v1/token?grant_type=password", headers=headers_anon,
                json={"email": email, "password": password},
            ), 200)
            tokens[label] = auth["access_token"]

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into public.clients(id,name) values ('tenant-a','Tenant A'),('tenant-b','Tenant B')")
            cur.execute("insert into public.platform_admins(user_id,role) values (%s,'platform_admin')", (actor_ids["platform"],))
            cur.execute(
                "insert into public.client_memberships(user_id,client_id,role) "
                "values (%s,'tenant-a','agency_admin'),(%s,'tenant-b','client_admin')",
                (actor_ids["agency"], actor_ids["client"]),
            )
            cur.execute("""
                select
                  (select count(*) from public.saas_plans) >= 3,
                  (select count(*) from public.tenant_commercial_modules) = 0,
                  (select count(*) from public.tenant_commercial_module_audit) = 0
            """)
            assert cur.fetchone() == (True, True, True), "Migration ordering / empty initial state"
            cur.execute("""
                select c.relrowsecurity from pg_class c where c.oid in
                ('public.tenant_commercial_modules'::regclass,
                 'public.tenant_commercial_module_audit'::regclass)
            """)
            assert cur.fetchall() == [(True,), (True,)]
            cur.execute("""
                select has_table_privilege('authenticated','public.tenant_commercial_modules','SELECT'),
                       has_table_privilege('authenticated','public.tenant_commercial_modules','INSERT'),
                       has_table_privilege('authenticated','public.tenant_commercial_module_audit','SELECT'),
                       has_function_privilege('authenticated',
                         'public.save_tenant_commercial_modules(text,jsonb,bigint,uuid)','EXECUTE')
            """)
            assert cur.fetchone() == (False, False, False, False)

    # Exercise actual backend handlers, auth bearer verification and PostgREST
    # against the local GoTrue and Kong services.
    from routes.saas import router
    app = FastAPI()
    app.include_router(router)
    log = StringIO()

    def headers(label):
        return {"Authorization": f"Bearer {tokens[label]}"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-api") as client:
        with redirect_stdout(log), redirect_stderr(log):
            r = await client.get("/api/admin/commercial-modules/catalog", headers=headers("agency"))
            assert must(r, 200)["enforcement_enabled"] is False
            assert must(await client.get("/api/admin/commercial-modules/catalog", headers=headers("client")), 403)
            assert must(await client.get("/api/admin/commercial-modules/catalog"), 401)

            url_a = "/api/admin/commercial-modules/tenant-a"
            url_b = "/api/admin/commercial-modules/tenant-b"
            absent = must(await client.get(url_a, headers=headers("platform")), 200)["configuration"]
            assert absent["state"] == "not_configured" and absent["module_keys"] is None
            assert absent["configured"] is False
            assert must(await client.get(url_b, headers=headers("client")), 403)

            first = must(await client.put(url_a, headers=headers("platform"), json={
                "module_keys": ["meta"], "expected_version": None,
            }), 200)["configuration"]
            assert first["state"] == "selected" and first["module_keys"] == ["meta"] and first["version"] == 1

            second = must(await client.put(url_b, headers=headers("agency"), json={
                "module_keys": ["social_media"], "expected_version": None,
            }), 200)["configuration"]
            assert second["module_keys"] == ["social_media"] and second["version"] == 1
            again = must(await client.get(url_a, headers=headers("agency")), 200)["configuration"]
            assert again["module_keys"] == ["meta"] and again["version"] == 1

            emptied = must(await client.put(url_a, headers=headers("agency"), json={
                "module_keys": [], "expected_version": 1,
            }), 200)["configuration"]
            assert emptied["state"] == "explicitly_empty" and emptied["module_keys"] == []
            assert emptied["version"] == 2
            assert must(await client.put(url_a, headers=headers("client"), json={
                "module_keys": ["google"], "expected_version": 2,
            }), 403)
            assert must(await client.put(url_a, headers=headers("platform"), json={
                "module_keys": ["redacao"], "expected_version": 2,
            }), 400)

            # Two admins see version 2 and attempt simultaneous writes.
            payloads = [
                client.put(url_a, headers=headers("agency"), json={
                    "module_keys": ["google"], "expected_version": 2,
                }),
                client.put(url_a, headers=headers("platform"), json={
                    "module_keys": ["ecommerce"], "expected_version": 2,
                }),
            ]
            races = await asyncio.gather(*payloads)
            assert sorted(r.status_code for r in races) == [200, 409]
            updated = must(await client.get(url_a, headers=headers("platform")), 200)["configuration"]
            assert updated["version"] == 3
            b_reloaded = must(await client.get(url_b, headers=headers("agency")), 200)["configuration"]
            assert b_reloaded["module_keys"] == ["social_media"]

            # Real GoTrue credentials must never be present in route output.
            captured = log.getvalue()
            for secret in [anon, service, password, *tokens.values(), *actors.values()]:
                assert secret not in captured, "Sensitive value found in backend stdout/stderr"
            assert "enforcement_enabled" not in captured or "True" not in captured

    # Transactional audit after all API operations; no data from other tenants.
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select previous_module_keys, module_keys, previous_version, version
                from public.tenant_commercial_module_audit where client_id = 'tenant-a'
                order by version
            """)
            entries = cur.fetchall()
            assert len(entries) == 3 and entries[0] == (None, ["meta"], None, 1)
            assert entries[1] == (["meta"], [], 1, 2)
            assert entries[2][2:] == (2, 3)
            cur.execute("select count(*) from public.tenant_commercial_module_audit where client_id='tenant-b'")
            assert cur.fetchone()[0] == 1

    # Keep stdout entirely free of credentials, tokens and user identifiers.
    print("PASS Supabase CLI local: GoTrue Auth, PostgREST, FastAPI, A-B-A, empty, roles, CAS, audit, ACL/RLS, logs")


if __name__ == "__main__":
    asyncio.run(integration())
