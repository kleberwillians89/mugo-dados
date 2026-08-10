from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"


class MigrationBootstrapContractTests(unittest.TestCase):
    def test_snapshot_table_precedes_its_first_index_and_rls(self):
        sql = (MIGRATIONS / "20260305_000001_multi_tenant_and_features.sql").read_text()
        create_pos = sql.index("create table if not exists public.ig_profile_snapshots")
        index_pos = sql.index("create index if not exists idx_ig_profile_snapshots_client_date")
        rls_pos = sql.index("alter table public.ig_profile_snapshots enable row level security")
        self.assertLess(create_pos, index_pos)
        self.assertLess(create_pos, rls_pos)

    def test_uuid_backfill_uses_supported_aggregation(self):
        sql = (MIGRATIONS / "20260413_000008_ig_media_connection_alignment.sql").read_text()
        self.assertNotIn("max(mc.id)", sql.lower())
        self.assertIn("min(mc.id::text)::uuid", sql.lower())

    def test_fk_detection_is_schema_rendering_agnostic(self):
        for name in (
            "20260409_000004_paid_schema_completion.sql",
            "20260413_000008_ig_media_connection_alignment.sql",
            "20260523_000017_instagram_organic_persistence_alignment.sql",
        ):
            sql = (MIGRATIONS / name).read_text().lower()
            self.assertNotIn(
                "references public.meta_connections(id)%",
                sql,
                msg=f"{name} voltou a depender da renderização textual do schema",
            )

    def test_auth_oauth_migration_is_nineteenth(self):
        names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
        self.assertEqual(len(names), 26)
        self.assertEqual(names[18], "20260731_000019_auth_oauth_connections.sql")
        self.assertEqual(names[-3], "20260805_000024_ga4_selection_metrics.sql")
        self.assertEqual(names[-2], "20260810_000025_google_ads_daily_stats.sql")
        self.assertEqual(names[-1], "20260811_000026_dashboard_read_model.sql")

    def test_versions_are_unique_and_logical_numbers_are_ordered(self):
        names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
        versions = [name.split("_", 1)[0] for name in names]
        logical_numbers = [int(name.split("_", 2)[1]) for name in names]
        self.assertEqual(len(versions), len(set(versions)))
        self.assertEqual(logical_numbers, list(range(1, 27)))

    def test_dashboard_read_model_is_tenant_scoped_read_only_and_incremental(self):
        sql = (MIGRATIONS / "20260811_000026_dashboard_read_model.sql").read_text().lower()
        for table in (
            "dashboard_daily_metrics", "dashboard_campaign_metrics",
            "dashboard_product_metrics", "dashboard_source_snapshots",
        ):
            self.assertIn(f"create table if not exists public.{table}", sql)
            self.assertIn(f"alter table public.{table} enable row level security", sql)
            self.assertIn("public.is_client_member(client_id)", sql)
        self.assertIn("grant select on public.dashboard_daily_metrics", sql)
        self.assertIn("from anon, authenticated", sql)
        self.assertIn("grant execute on function public.refresh_dashboard_read_model", sql)
        self.assertIn("to service_role", sql)
        refresh_body = sql.split("create or replace function public.refresh_dashboard_read_model", 1)[1]
        self.assertNotIn("delete from dashboard_", refresh_body)


if __name__ == "__main__":
    unittest.main()
