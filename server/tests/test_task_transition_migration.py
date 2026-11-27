from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20270131_000167_task_transition_history.sql"


class TaskTransitionMigrationTests(unittest.TestCase):
    def test_manual_events_are_auditable_and_task_deletion_is_restricted(self):
        sql = MIGRATION.read_text().lower()
        for kind in ("movido_manual", "reaberto", "cancelado"):
            self.assertIn(f"'{kind}'", sql)
        self.assertIn("foreign key (task_id) references public.studio_tasks(id)", sql)
        self.assertIn("on delete restrict", sql)
        self.assertNotIn("on delete cascade", sql)


if __name__ == "__main__":
    unittest.main()
