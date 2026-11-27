from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20270131_000165_task_work_links_integrity.sql"
PREFLIGHT = ROOT / "supabase/preflight/20270131_000165_task_work_links_integrity.sql"


class TaskWorkLinkMigrationTests(unittest.TestCase):
    def test_foreign_keys_include_tenant_and_preserve_history(self):
        sql = MIGRATION.read_text().lower()
        self.assertIn("foreign key (client_id, task_id)", sql)
        self.assertIn("references public.studio_tasks (client_id, id)", sql)
        self.assertIn("foreign key (client_id, brief_id)", sql)
        self.assertIn("references public.studio_briefs (client_id, id)", sql)
        self.assertEqual(sql.count("on delete restrict"), 2)
        self.assertNotIn("on delete cascade", sql)
        self.assertNotIn("delete from", sql)
        self.assertIn("not valid", sql)
        self.assertEqual(sql.count("validate constraint"), 2)

    def test_preflight_reports_missing_and_cross_tenant_relations_read_only(self):
        sql = PREFLIGHT.read_text().lower()
        self.assertIn("missing_task", sql)
        self.assertIn("task_tenant_mismatch", sql)
        self.assertIn("missing_brief", sql)
        self.assertIn("brief_tenant_mismatch", sql)
        statements = [part.strip() for part in sql.split(";") if part.strip()]
        self.assertTrue(all(re.search(r"(?:^|\n)select\s", part) for part in statements))
        for mutation in ("insert into", "update ", "delete from", "alter table", "create ", "drop "):
            self.assertNotIn(mutation, sql)


if __name__ == "__main__":
    unittest.main()
