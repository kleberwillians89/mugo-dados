"""CAC, LTV e coortes: conta certa de novos/recorrentes, CAC misturado, LTV só de quem completou a janela."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import customer_value as cv

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def at(y, m, d=10):
    return datetime(y, m, d, tzinfo=timezone.utc)


class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.purchases = [
            ("ana", at(2026, 8), 200), ("ana", at(2026, 9), 100), ("ana", at(2026, 9, 20), 50),
            ("bia", at(2026, 8), 300),
            ("caio", at(2026, 9), 150), ("caio", at(2026, 11), 150),
            ("duda", at(2026, 11), 80),
        ]
        self.spend = {"2026-08": 1000.0, "2026-09": 500.0, "2026-11": 400.0}

    def test_monthly_new_returning_and_cac(self):
        out = cv.compute(self.purchases, self.spend, now=NOW)
        months = {r["month"]: r for r in out["months"]}
        self.assertEqual((months["2026-08"]["new"], months["2026-08"]["cac"]), (2, 500.0))
        self.assertEqual((months["2026-09"]["new"], months["2026-09"]["returning"], months["2026-09"]["revenue_returning"]), (1, 1, 150.0))
        self.assertEqual((months["2026-11"]["new"], months["2026-11"]["returning"], months["2026-11"]["cac"]), (1, 1, 400.0))
        self.assertIsNone(months["2026-10"]["cac"])
        self.assertEqual(len(out["months"]), 12)

    def test_cohorts_retention_and_ltv_curve(self):
        out = cv.compute(self.purchases, self.spend, now=NOW)
        aug = next(c for c in out["cohorts"] if c["month"] == "2026-08")
        self.assertEqual(aug["size"], 2)
        self.assertEqual(aug["retention"][:2], [100.0, 50.0])
        self.assertEqual(aug["ltv"][:2], [250.0, 325.0])
        self.assertEqual(len(aug["ltv"]), 4)  # ago, set, out, nov

    def test_ltv_only_counts_who_completed_window(self):
        out = cv.compute(self.purchases, self.spend, now=NOW)
        # 90 dias: ana (350), bia (300) completaram; caio (set/10 → 66 dias) e duda não
        self.assertEqual(out["ltv"]["90"], 325.0)
        self.assertIsNone(out["ltv"]["365"])
        s = out["summary"]
        self.assertEqual((s["customers"], s["repeat_rate"]), (4, 50.0))
        self.assertEqual(s["cac_6m"], round(1900 / 4, 2))

    def test_margin_changes_ratio_basis(self):
        old = [(f"o{i}", NOW - timedelta(days=200), 1000.0) for i in range(10)]   # dão o LTV de 180 dias
        recent = [(f"n{i}", NOW - timedelta(days=30), 500.0) for i in range(10)]  # dão o CAC dos últimos 6 meses
        out = cv.compute(old + recent, {cv._month(NOW - timedelta(days=30)): 2000.0}, now=NOW, margin=50)
        self.assertEqual(out["ltv_basis"], "margem")
        self.assertEqual(out["summary"]["cac_6m"], 200.0)
        self.assertEqual(out["summary"]["ltv_cac"], round(1000 * 0.5 / 200, 2))

    def test_month_helpers(self):
        self.assertEqual(cv._shift("2026-01", -1), "2025-12")
        self.assertEqual(cv._shift("2026-11", 3), "2027-02")
        self.assertEqual(cv._diff("2025-12", "2026-02"), 2)


if __name__ == "__main__":
    unittest.main()
