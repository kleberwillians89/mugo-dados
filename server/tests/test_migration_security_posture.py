"""Postura de segurança das migrations: RLS, grants e SECURITY DEFINER.

Testes estáticos sobre o SQL. Não tocam banco: provam o que o repositório
garante. O que só o banco real pode dizer (grants efetivos, policies alteradas
pelo painel) fica fora daqui de propósito e precisa do preflight de produção.

A regra que estes testes protegem: tabela nova em `public` que guarde PII ou
credencial nasce fechada — RLS ligado, nada para anon/authenticated, tudo para
service_role — como as migrations 038 e 039 estabeleceram.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

MIGRATIONS = SERVER_DIR.parent / "supabase" / "migrations"

IDENTITY = MIGRATIONS / "20261004_000040_fbits_customer_identity.sql"
BUSINESS_CONTEXT = MIGRATIONS / "20261003_000039_client_business_context.sql"
LOCKDOWN = MIGRATIONS / "20261002_000038_browser_credential_lockdown.sql"
INDEXES = MIGRATIONS / "20261005_000041_customer_360_indexes.sql"
ECOMMERCE_LOCKDOWN = MIGRATIONS / "20261006_000042_ecommerce_browser_lockdown.sql"

# As seis tabelas internas de e-commerce que a 042 fecha. Produção mediu
# anon/authenticated SELECT = true nelas antes da 042.
ECOMMERCE_TABLES = (
    "fbits_orders",
    "fbits_order_items",
    "shopify_customers",
    "shopify_orders",
    "shopify_order_items",
    "shopify_webhook_events",
)


def sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def statements(path: Path) -> str:
    """SQL sem comentários: evita um teste passar por causa de um comentário."""
    return "\n".join(
        line for line in sql(path).splitlines() if not line.strip().startswith("--")
    )


class FbitsCustomersIsBornClosedTests(unittest.TestCase):
    """A tabela de PII do Customer 360 não pode nascer aberta."""

    def body(self) -> str:
        return statements(IDENTITY)

    def test_row_level_security_is_enabled(self):
        self.assertIn(
            "alter table public.fbits_customers enable row level security", self.body(),
        )

    def test_anon_and_authenticated_lose_every_privilege(self):
        self.assertIn(
            "revoke all on public.fbits_customers from anon, authenticated", self.body(),
        )

    def test_service_role_keeps_access(self):
        self.assertIn("grant all on public.fbits_customers to service_role", self.body())

    def test_no_grant_is_handed_to_the_browser(self):
        body = self.body()
        for role in ("anon", "authenticated"):
            self.assertIsNone(
                re.search(
                    rf"grant\s+[^;]*on\s+public\.fbits_customers\s+to[^;]*\b{role}\b",
                    body,
                    re.IGNORECASE | re.DOTALL,
                ),
                role,
            )

    def test_no_policy_opens_the_table_to_the_browser(self):
        # Acesso é só pelo backend tenant-scoped: RLS ligado sem policy fecha
        # para todo papel sujeito a RLS.
        self.assertNotIn("create policy", self.body().lower())

    def test_the_lockdown_comes_before_the_indexes(self):
        body = self.body()
        self.assertLess(
            body.index("enable row level security"),
            body.index("create index"),
            "a tabela não pode ficar aberta entre instruções da própria migration",
        )

    def test_the_lockdown_follows_the_project_pattern(self):
        # Mesmo trio que a 039 aplica em client_business_context.
        reference = statements(BUSINESS_CONTEXT)
        for template in (
            "enable row level security",
            "revoke all on public.{table} from anon, authenticated",
            "grant all on public.{table} to service_role",
        ):
            self.assertIn(template.format(table="client_business_context"), reference)
            self.assertIn(template.format(table="fbits_customers"), self.body())


class DestructiveRpcIsClosedTests(unittest.TestCase):
    def body(self) -> str:
        return statements(IDENTITY)

    def test_forget_fbits_customer_is_revoked_from_public_anon_and_authenticated(self):
        match = re.search(
            r"revoke all on function public\.forget_fbits_customer\(text, text\)\s*from\s*([^;]+);",
            self.body(),
            re.IGNORECASE,
        )
        self.assertIsNotNone(match, "a RPC destrutiva precisa de revoke explícito")
        revoked = {item.strip().lower() for item in match.group(1).split(",")}
        self.assertEqual(revoked, {"public", "anon", "authenticated"})

    def test_forget_fbits_customer_is_executable_by_service_role(self):
        self.assertIn(
            "grant execute on function public.forget_fbits_customer(text, text)",
            self.body(),
        )
        self.assertIn("to service_role", self.body())

    def test_revoking_from_public_alone_is_not_enough(self):
        # Guarda contra a regressão exata que motivou esta rodada: o default
        # privilege do Supabase concede execute a anon/authenticated
        # explicitamente, e `revoke from public` não remove isso.
        body = self.body()
        for name in ("forget_fbits_customer", "purge_fbits_customers_for_client"):
            revokes = re.findall(
                rf"revoke all on function public\.{name}\([^)]*\)\s*from\s*([^;]+);",
                body,
                re.IGNORECASE,
            )
            self.assertTrue(revokes, name)
            for clause in revokes:
                roles = {item.strip().lower() for item in clause.split(",")}
                self.assertIn("anon", roles, name)
                self.assertIn("authenticated", roles, name)

    def test_the_trigger_function_is_also_closed(self):
        self.assertIn(
            "revoke all on function public.purge_fbits_customers_for_client()",
            self.body(),
        )

    def test_every_security_definer_function_pins_the_search_path(self):
        # search_path injection: sem `set search_path`, uma função SECURITY
        # DEFINER pode ser levada a resolver objetos de outro schema.
        body = sql(IDENTITY)
        definers = [
            match.start() for match in re.finditer(r"security definer", body, re.IGNORECASE)
            if not body[:match.start()].rstrip().endswith("--")
        ]
        self.assertGreaterEqual(len(definers), 2)
        for position in definers:
            window = body[position: position + 200]
            self.assertRegex(window, r"set search_path\s*=\s*public,\s*pg_temp")


class TriggerKeepsWorkingTests(unittest.TestCase):
    """Fechar as funções não pode quebrar a limpeza automática de PII."""

    def test_the_purge_trigger_is_declared_on_clients(self):
        body = statements(IDENTITY)
        self.assertIn("after delete on public.clients", body)
        self.assertIn("execute function public.purge_fbits_customers_for_client()", body)

    def test_the_trigger_function_runs_as_definer_so_revokes_do_not_block_it(self):
        # O PostgreSQL verifica EXECUTE na função do trigger no CREATE TRIGGER,
        # não a cada disparo; e a função é SECURITY DEFINER. Por isso o revoke
        # de anon/authenticated não impede o trigger de limpar a PII.
        body = sql(IDENTITY)
        start = body.index("create or replace function public.purge_fbits_customers_for_client")
        header = body[start: body.index("as $$", start)]
        self.assertIn("security definer", header)
        self.assertIn("returns trigger", header)

    def test_the_trigger_deletes_only_the_deleted_tenant(self):
        self.assertIn(
            "delete from public.fbits_customers where client_id = old.id",
            statements(IDENTITY),
        )


class PostgrestReloadTests(unittest.TestCase):
    def test_the_identity_migration_notifies_postgrest(self):
        self.assertIn("notify pgrst, 'reload schema'", statements(IDENTITY))

    def test_it_is_the_last_statement(self):
        body = [
            line.strip() for line in statements(IDENTITY).splitlines() if line.strip()
        ]
        self.assertEqual(body[-1], "notify pgrst, 'reload schema';")

    def test_the_project_pattern_is_followed(self):
        for path in (LOCKDOWN, BUSINESS_CONTEXT):
            self.assertIn("notify pgrst, 'reload schema'", statements(path))


class MinimizationIsPreservedTests(unittest.TestCase):
    """A correção de segurança não pode ter afrouxado a minimização."""

    def table_body(self) -> str:
        body = sql(IDENTITY)
        start = body.index("create table if not exists public.fbits_customers")
        return body[start: body.index(");", start)].lower()

    def test_only_the_declared_columns_exist(self):
        columns = self.table_body()
        for expected in (
            "client_id", "fbits_customer_id", "name", "email", "phone",
            "created_at_provider", "updated_at_provider", "synced_at",
        ):
            self.assertIn(expected, columns)

    def test_no_column_for_cpf_address_or_credentials(self):
        columns = self.table_body()
        for forbidden in ("cpf", "endereco", "address", "token", "raw_payload", "document", "cep"):
            self.assertNotIn(forbidden, columns)

    def test_the_tenant_unique_key_is_preserved(self):
        self.assertIn("unique (client_id, fbits_customer_id)", self.table_body())

    def test_every_index_starts_with_the_tenant(self):
        for line in sql(IDENTITY).splitlines():
            if "on public.fbits_customers (" in line:
                self.assertIn("(client_id", line.replace(" ", "").replace("(client_id", "(client_id"))

    def test_the_purpose_is_still_declared(self):
        self.assertIn("comment on table public.fbits_customers", statements(IDENTITY))


class UntouchedMigrationsTests(unittest.TestCase):
    """039 e 041 não foram alteradas nesta rodada."""

    def test_039_keeps_its_own_lockdown(self):
        body = statements(BUSINESS_CONTEXT)
        self.assertIn(
            "alter table public.client_business_context enable row level security", body,
        )
        self.assertIn(
            "revoke all on public.client_business_context from anon, authenticated", body,
        )

    def test_041_is_still_indexes_only(self):
        body = statements(INDEXES).lower()
        self.assertNotIn("create table", body)
        self.assertNotIn("grant", body)
        self.assertNotIn("revoke", body)
        for statement in body.split(";"):
            if statement.strip():
                self.assertTrue(
                    statement.strip().startswith("create index"), statement.strip()[:60],
                )

    def test_038_is_not_modified_in_this_round(self):
        # A 038 é a referência do padrão; auditada, não alterada.
        body = statements(LOCKDOWN)
        self.assertIn("revoke all on public.clients from anon, authenticated", body)
        self.assertIn("'meta_connections', 'meta_oauth_handoffs', 'shopify_refunds'", body)


class SensitiveTableInventoryTests(unittest.TestCase):
    """Inventário auditável do que o repositório garante por tabela.

    Documenta o estado conhecido e falha se ele mudar sem revisão. Não afirma
    nada sobre o banco real: grants efetivos e policies alteradas fora das
    migrations só o preflight de produção mostra.
    """

    # Tabelas fechadas por completo: RLS + revoke de anon/authenticated.
    FULLY_CLOSED = ("client_business_context", "fbits_customers")
    # Fechadas pela 038 via bloco dinâmico.
    CLOSED_BY_038 = ("meta_connections", "meta_oauth_handoffs", "shopify_refunds")
    # RLS ligado pela 018 com policy de membro; o revoke que faltava chega na
    # 042. Produção confirmou anon/authenticated SELECT = true antes dela.
    MEMBER_READABLE = ECOMMERCE_TABLES

    def all_sql(self) -> str:
        return "\n".join(
            statements(path) for path in sorted(MIGRATIONS.glob("*.sql"))
        )

    def test_the_fully_closed_tables_have_rls_and_revoke(self):
        body = self.all_sql()
        for table in self.FULLY_CLOSED:
            with self.subTest(table=table):
                self.assertIn(f"alter table public.{table} enable row level security", body)
                self.assertIn(f"revoke all on public.{table} from anon, authenticated", body)
                self.assertIn(f"grant all on public.{table} to service_role", body)

    def test_the_038_tables_are_closed_dynamically(self):
        body = statements(LOCKDOWN)
        for table in self.CLOSED_BY_038:
            self.assertIn(f"'{table}'", body)
        self.assertIn("enable row level security", body)
        self.assertIn("revoke all on public.%I from anon, authenticated", body)
        self.assertIn("grant all on public.%I to service_role", body)

    def test_the_member_readable_tables_have_rls_from_018(self):
        hardening = statements(MIGRATIONS / "20260730_000018_mugo_dados_multitenant_hardening.sql")
        for table in self.MEMBER_READABLE:
            with self.subTest(table=table):
                self.assertIn(f"'{table}'", hardening)
        self.assertIn("enable row level security", hardening)
        self.assertIn("tenant_member_select", hardening)

    def test_the_member_policy_requires_a_real_membership(self):
        hardening = statements(MIGRATIONS / "20260730_000018_mugo_dados_multitenant_hardening.sql")
        self.assertIn("public.is_client_member(client_id::text)", hardening)
        # is_client_member compara com auth.uid(): anon não é membro de nada.
        base = statements(MIGRATIONS / "20260305_000001_multi_tenant_and_features.sql")
        self.assertIn("m.user_id = auth.uid()", base)

    def test_the_member_readable_tables_are_closed_by_042(self):
        # O achado da rodada anterior, agora fechado: o revoke chega pela 042,
        # em bloco dinâmico, no mesmo molde da 038.
        body = statements(ECOMMERCE_LOCKDOWN)
        for table in self.MEMBER_READABLE:
            with self.subTest(table=table):
                self.assertIn(f"'{table}'", body)
        self.assertIn("revoke all on public.%I from anon, authenticated", body)


if __name__ == "__main__":
    unittest.main()


class EcommerceBrowserLockdownTests(unittest.TestCase):
    """042: fecha as seis tabelas internas de e-commerce para o browser."""

    def body(self) -> str:
        return statements(ECOMMERCE_LOCKDOWN)

    def test_the_migration_exists_and_is_not_applied_by_us(self):
        self.assertTrue(ECOMMERCE_LOCKDOWN.exists())
        self.assertIn("NÃO APLICADA", sql(ECOMMERCE_LOCKDOWN))

    def test_every_table_is_named(self):
        body = self.body()
        for table in ECOMMERCE_TABLES:
            with self.subTest(table=table):
                self.assertIn(f"'{table}'", body)

    def test_no_other_table_is_touched(self):
        quoted = set(re.findall(r"'([a-z_]+)'", self.body()))
        # Além das seis, só aparece o prefixo do to_regclass.
        self.assertTrue(quoted <= set(ECOMMERCE_TABLES) | {"public."}, quoted)

    def test_row_level_security_is_enabled_for_each(self):
        self.assertIn(
            "alter table public.%I enable row level security", self.body(),
        )

    def test_anon_is_revoked(self):
        self.assertRegex(
            self.body(),
            r"revoke all on public\.%I from[^;']*\banon\b",
        )

    def test_authenticated_is_revoked(self):
        self.assertRegex(
            self.body(),
            r"revoke all on public\.%I from[^;']*\bauthenticated\b",
        )

    def test_service_role_keeps_full_access(self):
        self.assertIn("grant all on public.%I to service_role", self.body())

    def test_no_new_permissive_policy_is_created(self):
        body = self.body().lower()
        self.assertNotIn("create policy", body)
        self.assertNotIn("using (true)", body)

    def test_nothing_is_dropped_or_deleted(self):
        body = self.body().lower()
        for destructive in ("drop table", "drop column", "drop policy", "truncate", "delete from", "alter column"):
            self.assertNotIn(destructive, body)

    def test_no_sequence_is_revoked_indiscriminately(self):
        self.assertNotIn("sequence", self.body().lower())

    def test_a_missing_table_does_not_break_the_migration(self):
        self.assertIn("to_regclass('public.' || table_name) is not null", self.body())

    def test_postgrest_is_notified_at_the_end(self):
        lines = [line.strip() for line in self.body().splitlines() if line.strip()]
        self.assertEqual(lines[-1], "notify pgrst, 'reload schema';")

    def test_it_follows_the_038_pattern(self):
        reference = statements(LOCKDOWN)
        for template in (
            "alter table public.%I enable row level security",
            "revoke all on public.%I from anon, authenticated",
            "grant all on public.%I to service_role",
        ):
            self.assertIn(template, reference)
            self.assertIn(template, self.body())


class NoBrowserDependencyTests(unittest.TestCase):
    """O revoke só é seguro porque o browser não lê estas tabelas."""

    SRC = SERVER_DIR.parent / "src"

    def frontend_sources(self) -> list[Path]:
        return [
            path for path in self.SRC.rglob("*.ts*")
            if ".test." not in path.name and "design-review" not in str(path)
        ]

    def test_the_browser_never_selects_from_the_closed_tables(self):
        for path in self.frontend_sources():
            body = path.read_text(encoding="utf-8")
            for table in ECOMMERCE_TABLES:
                with self.subTest(path=path.name, table=table):
                    self.assertNotIn(f'from("{table}")', body)
                    self.assertNotIn(f"from('{table}')", body)

    def test_the_browser_only_reads_the_allowed_tables(self):
        allowed = {
            "platform_admins", "client_memberships", "clients",
            "dashboard_daily_metrics", "dashboard_source_snapshots",
            "dashboard_campaign_metrics", "dashboard_product_metrics",
        }
        found: set[str] = set()
        for path in self.frontend_sources():
            found.update(
                re.findall(r'supabase\s*\.\s*from\(\s*["\x27]([a-z_]+)["\x27]', path.read_text(encoding="utf-8"))
            )
        self.assertTrue(found, "nenhuma leitura encontrada: a busca quebrou")
        self.assertTrue(found <= allowed, found - allowed)

    def test_the_browser_calls_no_rpc(self):
        for path in self.frontend_sources():
            body = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("supabase.rpc(", body)

    def test_the_backend_reaches_the_tables_through_service_role(self):
        # O backend lê por sb_select/sb_upsert, que usam a service role key.
        supabase_client = (SERVER_DIR / "services" / "ig_supabase.py").read_text(encoding="utf-8")
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", supabase_client)


class SecurityDefinerFunctionsAreClosedTests(unittest.TestCase):
    """As funções que leem as seis tabelas já estavam fechadas; travado aqui."""

    CLOSED = (
        ("public.refresh_dashboard_read_model", "text,date,date,text"),
        ("public.delete_platform_company", "uuid,text,text"),
    )

    def all_sql(self) -> str:
        return "\n".join(statements(path) for path in sorted(MIGRATIONS.glob("*.sql")))

    def squashed(self) -> str:
        """Todo espaço em branco colapsado: o SQL quebra linha no meio do
        statement e a asserção não deve depender da formatação."""
        return re.sub(r"\s+", "", self.all_sql())

    def test_each_function_is_revoked_from_the_browser(self):
        body = self.squashed()
        for name, args in self.CLOSED:
            with self.subTest(function=name):
                self.assertIn(
                    f"revokeallonfunction{name}({args})frompublic,anon,authenticated",
                    body,
                )

    def test_each_function_is_granted_to_service_role(self):
        body = self.squashed()
        for name, args in self.CLOSED:
            with self.subTest(function=name):
                self.assertIn(
                    f"grantexecuteonfunction{name}({args})toservice_role", body,
                )

    def test_the_destructive_function_authorizes_on_a_parameter(self):
        # Documenta por que o revoke é indispensável nela: a checagem usa o
        # parâmetro, não auth.uid(). Sem revoke, qualquer um chamaria passando
        # o uuid de um platform admin.
        deletion = statements(MIGRATIONS / "20260929_000036_platform_company_permanent_deletion.sql")
        self.assertIn("public.is_platform_admin(p_actor_user_id)", deletion)

    def test_042_does_not_touch_these_functions(self):
        body = statements(ECOMMERCE_LOCKDOWN)
        self.assertNotIn("revoke all on function", body)
        self.assertNotIn("grant execute", body)
