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
        self.assertEqual(len(names), 39)
        self.assertEqual(names[18], "20260731_000019_auth_oauth_connections.sql")
        self.assertEqual(names[-9], "20260816_000031_cron_job_runs_polymorphic_connections.sql")
        self.assertEqual(names[-8], "20260817_000032_shopify_explicit_sync_coverage.sql")
        self.assertEqual(names[-7], "20260818_000033_meta_ads_backfill_queue.sql")
        self.assertEqual(names[-6], "20260819_000034_multi_tenant_invitation_acceptance.sql")
        self.assertEqual(names[-5], "20260820_000035_company_creation_idempotency.sql")
        self.assertEqual(names[-4], "20260929_000036_platform_company_permanent_deletion.sql")
        self.assertEqual(names[-3], "20261001_000037_fbits_order_financials.sql")
        self.assertEqual(names[-2], "20261002_000038_browser_credential_lockdown.sql")
        self.assertEqual(names[-1], "20261003_000039_client_business_context.sql")

    def test_versions_are_unique_and_logical_numbers_are_ordered(self):
        names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
        versions = [name.split("_", 1)[0] for name in names]
        logical_numbers = [int(name.split("_", 2)[1]) for name in names]
        self.assertEqual(len(versions), len(set(versions)))
        self.assertEqual(logical_numbers, list(range(1, 40)))

    def test_shopify_coverage_uses_completed_query_end(self):
        sql = (
            MIGRATIONS / "20260817_000032_shopify_explicit_sync_coverage.sql"
        ).read_text().lower()
        self.assertIn("refresh_dashboard_read_model_000030", sql)
        self.assertIn("if p_provider = 'shopify'", sql)
        self.assertIn("p_client_id, 'shopify', now(), p_start, p_end", sql)
        self.assertIn("data_max_available = greatest", sql)
        self.assertNotIn("max(metric_date)", sql)

    def test_meta_backfill_queue_is_service_only_and_restartable(self):
        sql = (MIGRATIONS / "20260818_000033_meta_ads_backfill_queue.sql").read_text().lower()
        self.assertIn("meta_ads_backfill_jobs", sql)
        self.assertIn("meta_ads_backfill_slices", sql)
        self.assertIn("for update of s skip locked", sql)
        self.assertIn("worker interrompido; slice retomado", sql)
        self.assertIn("unique(backfill_job_id, slice_since, slice_until)", sql)
        self.assertIn("revoke all on public.meta_ads_backfill_jobs from anon, authenticated", sql)
        self.assertIn("grant execute on function public.claim_meta_ads_backfill_slice(integer) to service_role", sql)

    def test_cron_job_runs_supports_both_connection_catalogs(self):
        sql = (
            MIGRATIONS / "20260816_000031_cron_job_runs_polymorphic_connections.sql"
        ).read_text().lower()
        self.assertIn("references public.meta_connections(id)", sql)
        self.assertIn("references public.integration_connections(id)", sql)
        self.assertIn("unexpected cron_job_runs.connection_id reference", sql)
        self.assertIn("trg_cron_job_runs_resolve_connection", sql)
        self.assertIn("new.meta_connection_id := new.connection_id", sql)

    def test_shopify_recognized_sales_are_separate_from_non_cancelled_orders(self):
        sql = (
            MIGRATIONS / "20260814_000029_shopify_recognized_sales_metrics.sql"
        ).read_text().lower()
        self.assertIn("current_total_price numeric(18, 2)", sql)
        self.assertIn("shopify_orders_created", sql)
        self.assertIn("shopify_orders_non_cancelled", sql)
        self.assertIn("shopify_pending_orders", sql)
        self.assertIn("shopify_sales_revenue", sql)
        self.assertIn("in ('paid', 'partially_refunded')", sql)
        self.assertIn("shopify_net_revenue = coalesce(x.sales_revenue, 0)", sql)
        self.assertIn("shopify_orders = x.recognized_orders", sql)
        self.assertNotIn("delete from shopify_", sql)
        self.assertIn("from public, anon, authenticated", sql)

    def test_shopify_read_model_excludes_cancelled_orders_and_materializes_customer_keys(self):
        sql = (
            MIGRATIONS / "20260813_000028_shopify_read_model_canonical_metrics.sql"
        ).read_text().lower()
        self.assertIn("o.cancelled_at is null", sql)
        self.assertIn("nullif(trim(coalesce(o.cancel_reason, '')), '') is null", sql)
        self.assertIn("shopify_customer_keys text[]", sql)
        self.assertIn("count(distinct nullif(trim(o.customer_id), ''))", sql)
        self.assertIn("array_agg(distinct ('customer_md5:' || md5(trim(o.customer_id)))", sql)
        self.assertNotIn("o.email", sql)
        self.assertIn("at time zone 'america/sao_paulo'", sql)
        self.assertIn("between p_start and p_end", sql)
        self.assertIn("update dashboard_daily_metrics set", sql)
        self.assertIn("delete from dashboard_product_metrics", sql)
        self.assertNotIn("delete from shopify_", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)

    def test_shopify_customer_metrics_follow_recognized_sales_rule(self):
        sql = (
            MIGRATIONS / "20260815_000030_shopify_recognized_customer_metrics.sql"
        ).read_text().lower()
        self.assertIn("refresh_dashboard_read_model_000029", sql)
        self.assertIn("in ('paid', 'partially_refunded')", sql)
        self.assertIn("shopify_customer_keys = r.customer_keys", sql)
        self.assertIn("shopify_customers = 0", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)

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

    def test_dashboard_read_model_platform_admin_select_is_additive(self):
        member_sql = (MIGRATIONS / "20260811_000026_dashboard_read_model.sql").read_text().lower()
        admin_sql = (
            MIGRATIONS / "20260812_000027_dashboard_read_model_platform_admin_select.sql"
        ).read_text().lower()
        policy_names = (
            "dashboard_daily_platform_admin_select",
            "dashboard_campaign_platform_admin_select",
            "dashboard_product_platform_admin_select",
            "dashboard_sources_platform_admin_select",
        )
        self.assertEqual(member_sql.count("using (public.is_client_member(client_id))"), 4)
        self.assertNotIn("drop policy", admin_sql)
        for policy_name in policy_names:
            self.assertIn(f"create policy {policy_name}", admin_sql)
        self.assertEqual(admin_sql.count("for select to authenticated"), 4)
        self.assertEqual(admin_sql.count("using (public.is_platform_admin())"), 4)

    def test_dashboard_read_model_browser_roles_remain_read_only(self):
        sql = (
            MIGRATIONS / "20260812_000027_dashboard_read_model_platform_admin_select.sql"
        ).read_text().lower()
        self.assertIn("from anon, authenticated", sql)
        self.assertIn("to authenticated", sql)
        self.assertNotIn("for insert", sql)
        self.assertNotIn("for update", sql)
        self.assertNotIn("for delete", sql)
        self.assertIn(
            "revoke all on function public.refresh_dashboard_read_model(text, date, date, text)",
            sql,
        )
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)


if __name__ == "__main__":
    unittest.main()
