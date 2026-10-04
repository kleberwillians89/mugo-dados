"""Nenhum segredo de integração chega ao browser.

O browser fala com o Supabase só com a anon key + JWT do usuário; o backend
usa service_role. Estes testes travam três coisas, sem banco remoto:
  1. a migration 038 fecha as tabelas/colunas com credenciais e as RPCs de job;
  2. toda coluna de credencial das migrations fica fora do alcance de
     anon/authenticated depois da 038;
  3. o frontend só consulta tabelas e colunas liberadas.

Validação contra o RLS REMOTO continua pendente: aqui é contrato de SQL/código.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
LOCKDOWN = MIGRATIONS / "20261002_000038_browser_credential_lockdown.sql"
SRC = ROOT / "src"

SECRET_COLUMN = re.compile(r"(token|secret|api_key|apikey|password|private_key|credential)", re.I)
NOT_SECRET = {"token_expires_at", "token_last_refreshed_at", "token_hash_algorithm"}

# O que o browser pode ler (tabela -> colunas; None = todas as liberadas por grant).
BROWSER_TABLES = {
    "clients": {"id", "name", "trade_name"},
    "client_memberships": None,
    "platform_admins": None,
    "dashboard_daily_metrics": None,
    "dashboard_campaign_metrics": None,
    "dashboard_product_metrics": None,
    "dashboard_source_snapshots": None,
}


def _sql() -> str:
    return LOCKDOWN.read_text(encoding="utf-8")


def _all_migrations() -> list[tuple[str, str]]:
    return [(path.name, path.read_text(encoding="utf-8")) for path in sorted(MIGRATIONS.glob("*.sql"))]


def _secret_columns_by_table() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for _name, sql in _all_migrations():
        for match in re.finditer(r"create table (?:if not exists )?public\.(\w+)\s*\((.*?)\n\);", sql, re.S | re.I):
            for line in match.group(2).splitlines():
                column = line.strip().split(" ")[0].strip('",')
                if column and SECRET_COLUMN.search(column) and column not in NOT_SECRET:
                    found.setdefault(match.group(1), set()).add(column)
        for match in re.finditer(r"alter table (?:if exists )?public\.(\w+)\s+add column (?:if not exists )?(\w+)", sql, re.I):
            if SECRET_COLUMN.search(match.group(2)) and match.group(2) not in NOT_SECRET:
                found.setdefault(match.group(1), set()).add(match.group(2))
    return found


def _final_browser_access() -> dict[str, object]:
    """Estado final, por tabela, depois de todas as migrations em ordem:
    "none" (revogado), conjunto de colunas (grant por coluna) ou "default"."""
    access: dict[str, object] = {}
    for _name, sql in _all_migrations():
        statements = re.split(r";\s*\n", sql)
        for statement in statements:
            flat = " ".join(statement.split())
            revoke = re.search(r"revoke all on ((?:public\.\w+(?:, )?)+) from (?:public, )?anon, authenticated", flat, re.I)
            if revoke:
                for table in re.findall(r"public\.(\w+)", revoke.group(1)):
                    access[table] = "none"
            grant = re.search(r"grant select \((.*?)\) on public\.(\w+) to authenticated", flat, re.I)
            if grant:
                access[grant.group(2)] = {c.strip() for c in grant.group(1).split(",")}
            whole = re.search(r"grant select on ((?:public\.\w+(?:, )?)+) to authenticated", flat, re.I)
            if whole:
                for table in re.findall(r"public\.(\w+)", whole.group(1)):
                    access[table] = "all"
        # Revoke em laço (array de tabelas + format('revoke all ...')).
        for array in re.findall(r"foreach table_name in array array\[(.*?)\]\s*loop(.*?)end loop", sql, re.S | re.I):
            if "revoke all on public.%I from anon, authenticated" in array[1]:
                for table in re.findall(r"'(\w+)'", array[0]):
                    access[table] = "none"
    return access


def _frontend_queries() -> list[tuple[str, str, str]]:
    queries = []
    for path in SRC.rglob("*.ts*"):
        if ".test." in path.name or "design-review" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'\.from\("(\w+)"\)\s*\.select\("([^"]*)"', text):
            queries.append((str(path.relative_to(ROOT)), match.group(1), match.group(2)))
        for match in re.finditer(r'\.from\("(\w+)"\)(?!\s*\.select)', text):
            queries.append((str(path.relative_to(ROOT)), match.group(1), "?"))
    return queries


class LockdownMigrationContractTests(unittest.TestCase):
    def test_migration_is_local_and_idempotent(self):
        sql = _sql()
        self.assertIn("MIGRATION LOCAL", sql)
        self.assertIn("to_regclass", sql)
        self.assertNotRegex(sql.lower(), r"\bdrop table\b|\bdelete from\b|\btruncate\b|\bdrop column\b")

    def test_clients_uses_a_column_allowlist_without_tokens(self):
        sql = " ".join(_sql().split())
        self.assertIn("revoke all on public.clients from anon, authenticated", sql)
        self.assertIn("grant select (id, name, trade_name) on public.clients to authenticated", sql)

    def test_backend_only_tables_are_closed_with_rls(self):
        sql = _sql()
        for table in ("meta_connections", "meta_oauth_handoffs", "shopify_refunds"):
            self.assertIn(f"'{table}'", sql)
        self.assertIn("enable row level security", sql)
        self.assertIn("revoke all on public.%I from anon, authenticated", sql)

    def test_job_lock_rpcs_are_service_role_only(self):
        sql = " ".join(_sql().split())
        for signature in ("acquire_client_job_lock(text, text, integer)", "release_client_job_lock(text, text)"):
            self.assertIn(f"revoke all on function public.{signature} from public, anon, authenticated", sql)
            self.assertIn(f"grant execute on function public.{signature} to service_role", sql)


class NoCredentialColumnReachesTheBrowserTests(unittest.TestCase):
    def test_every_credential_column_is_closed_for_authenticated(self):
        access = _final_browser_access()
        secrets = _secret_columns_by_table()
        self.assertTrue(secrets, "o inventário de colunas sensíveis não pode vir vazio")
        for table, columns in sorted(secrets.items()):
            state = access.get(table, "default")
            with self.subTest(table=table):
                self.assertNotEqual(state, "default", f"{table} guarda {sorted(columns)} sem revoke para o browser")
                self.assertNotEqual(state, "all", f"{table} concede todas as colunas ao browser")
                if isinstance(state, set):
                    self.assertFalse(columns & state, f"{table} concede {sorted(columns & state)} ao browser")

    def test_known_credential_tables_are_in_the_inventory(self):
        secrets = _secret_columns_by_table()
        self.assertIn("ig_access_token", secrets.get("clients", set()))
        self.assertTrue({"access_token", "encrypted_access_token"} <= secrets.get("meta_connections", set()))
        self.assertIn("encrypted_access_token", secrets.get("meta_oauth_handoffs", set()))
        self.assertIn("encrypted_refresh_token", secrets.get("integration_connections", set()))


class FrontendReadsOnlyAllowedDataTests(unittest.TestCase):
    def test_browser_queries_only_allowed_tables_and_columns(self):
        queries = _frontend_queries()
        self.assertTrue(queries, "nenhuma consulta Supabase encontrada no frontend")
        for file, table, columns in queries:
            with self.subTest(file=file, table=table):
                self.assertIn(table, BROWSER_TABLES, f"{file} lê {table} direto do browser")
                if columns == "?":
                    continue
                self.assertIsNone(SECRET_COLUMN.search(columns), f"{file} seleciona coluna sensível em {table}")
                allowed = BROWSER_TABLES[table]
                if allowed is None:
                    # select=* só onde a tabela não guarda credencial alguma.
                    self.assertNotIn(table, _secret_columns_by_table(), f"{file} lê {table}, que guarda credenciais")
                else:
                    self.assertNotEqual(columns.strip(), "*", f"{file} usa select=* em {table}")
                    requested = {c.strip() for c in columns.split(",") if c.strip()}
                    self.assertTrue(requested <= allowed, f"{file} pede {sorted(requested - allowed)} de {table}")

    def test_browser_bundle_never_references_the_service_role(self):
        for path in SRC.rglob("*.ts*"):
            if ".test." in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=str(path.relative_to(ROOT))):
                self.assertNotRegex(text, r"SERVICE_ROLE|service_role")

    def test_browser_client_uses_the_anon_key(self):
        text = (SRC / "app" / "supabase.ts").read_text(encoding="utf-8")
        self.assertIn("VITE_SUPABASE_ANON_KEY", text)


if __name__ == "__main__":
    unittest.main()
