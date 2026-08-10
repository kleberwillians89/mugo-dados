from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.ads_sync import (
    _synthetic_boosted_rows_from_maximum_insights,
    extract_canonical_purchase_metrics,
)
from services.dashboard_paid import _sum_grouped_rows, compute_mer, compute_roas


class ComputeRoasTests(unittest.TestCase):
    def test_sums_revenue_and_investment_before_dividing(self):
        # Campanha A: investimento 100, receita 500 (ROAS 5)
        # Campanha B: investimento 900, receita 900 (ROAS 1)
        # Total correto: (500+900)/(100+900) = 1.4 — nunca média (5+1)/2=3.
        total_revenue = 500 + 900
        total_investment = 100 + 900
        self.assertAlmostEqual(compute_roas(total_revenue, total_investment), 1.4)

    def test_zero_investment_is_none_not_zero(self):
        self.assertIsNone(compute_roas(500, 0))

    def test_missing_revenue_is_none(self):
        self.assertIsNone(compute_roas(None, 916.91))

    def test_non_finite_result_is_none(self):
        self.assertIsNone(compute_roas(float("nan"), 100))

    def test_real_zero_revenue_with_investment_is_zero_not_none(self):
        self.assertEqual(compute_roas(0, 100), 0.0)

    def test_reported_production_case_no_longer_inflates(self):
        # Regressão do caso real: investimento R$916,91 não pode gerar 25x.
        roas = compute_roas(22_922.75, 916.91)
        self.assertIsNotNone(roas)
        self.assertGreater(roas, 24.9)  # a conta em si está certa...
        # ...o bug nunca foi a divisão, e sim receita de outro período
        # entrando no numerador (coberto pelo teste abaixo).


class ComputeMerTests(unittest.TestCase):
    def test_mer_uses_shopify_revenue_over_total_paid_spend(self):
        # Receita real da loja: 10.000. Investimento Meta+Google: 2.000.
        self.assertAlmostEqual(compute_mer(10_000, 2_000), 5.0)

    def test_mer_is_none_without_paid_spend(self):
        self.assertIsNone(compute_mer(10_000, 0))

    def test_mer_never_reuses_platform_attributed_revenue(self):
        # MER não deve ser confundido com ROAS Meta: mesmo com receita
        # atribuída pela Meta de 5x o investimento, o MER usa apenas a
        # receita real da loja informada explicitamente.
        shopify_revenue = 1_000
        meta_attributed_revenue = 5_000
        total_paid_spend = 500
        mer = compute_mer(shopify_revenue, total_paid_spend)
        roas_meta = compute_roas(meta_attributed_revenue, total_paid_spend)
        self.assertAlmostEqual(mer, 2.0)
        self.assertAlmostEqual(roas_meta, 10.0)
        self.assertNotEqual(mer, roas_meta)


class CanonicalMetaPurchaseTests(unittest.TestCase):
    def test_competing_purchase_aliases_are_not_added(self):
        aliases = (
            "offsite_conversion.fb_pixel_purchase",
            "omni_purchase",
            "onsite_web_app_purchase",
            "onsite_web_purchase",
            "purchase",
            "web_in_store_purchase",
        )
        result = extract_canonical_purchase_metrics(
            [{"action_type": action_type, "value": "1"} for action_type in aliases],
            [{"action_type": action_type, "value": "500"} for action_type in aliases],
        )
        self.assertEqual(result["purchase_count"], 1)
        self.assertEqual(result["purchase_value"], 500)
        self.assertEqual(
            result["purchase_action_type_selected"],
            "offsite_conversion.fb_pixel_purchase",
        )

    def test_falls_back_to_omni_then_purchase(self):
        omni = extract_canonical_purchase_metrics(
            [{"action_type": "omni_purchase", "value": "1"}],
            [{"action_type": "omni_purchase", "value": "500"}],
        )
        purchase = extract_canonical_purchase_metrics(
            [{"action_type": "purchase", "value": "1"}],
            [{"action_type": "purchase", "value": "500"}],
        )
        self.assertEqual(omni, {
            "purchase_count": 1.0,
            "purchase_value": 500.0,
            "purchase_action_type_selected": "omni_purchase",
        })
        self.assertEqual(purchase, {
            "purchase_count": 1.0,
            "purchase_value": 500.0,
            "purchase_action_type_selected": "purchase",
        })

    def test_does_not_mix_count_and_value_from_different_aliases(self):
        result = extract_canonical_purchase_metrics(
            [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "1"}],
            [{"action_type": "omni_purchase", "value": "500"}],
        )
        self.assertEqual(result["purchase_count"], 1)
        self.assertEqual(result["purchase_value"], 0)
        self.assertEqual(
            result["purchase_action_type_selected"],
            "offsite_conversion.fb_pixel_purchase",
        )


class SumGroupedRowsRoasTests(unittest.TestCase):
    """_sum_grouped_rows alimenta a listagem de campanhas/anúncios Meta e
    precisa usar a mesma fonte única de cálculo de ROAS (compute_roas),
    nunca uma divisão bruta com fallback 0.0 (zero falso quando não há
    investimento na campanha)."""

    def test_campaign_without_spend_reports_none_not_zero(self):
        rows = [
            {
                "campaign_id": "c1",
                "campaign_name": "Sem gasto",
                "stat_date": "2026-08-01",
                "spend": 0,
                "revenue": 0,
            }
        ]
        result = _sum_grouped_rows(rows, "campaign_id", "campaign_name")
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["roas"])

    def test_campaign_roas_sums_before_dividing(self):
        rows = [
            {
                "campaign_id": "c1",
                "campaign_name": "Campanha A",
                "stat_date": "2026-08-01",
                "spend": 100,
                "revenue": 500,
            },
            {
                "campaign_id": "c1",
                "campaign_name": "Campanha A",
                "stat_date": "2026-08-02",
                "spend": 900,
                "revenue": 900,
            },
        ]
        result = _sum_grouped_rows(rows, "campaign_id", "campaign_name")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["roas"], 1.4)


class SyntheticBoostedRowsNeverCarryAllTimeRevenueTests(unittest.TestCase):
    def test_all_time_financial_fields_are_zeroed_for_period_row(self):
        # Linha vinda de uma consulta date_preset="maximum" (todo o
        # histórico da conta), reaproveitada apenas para descobrir quais
        # anúncios existem quando o período pedido não retorna nada.
        all_time_row = {
            "ad_id": "ad-1",
            "date_start": "2024-01-01",
            "date_stop": "2026-08-05",
            "spend": 25_000.0,
            "actions": [{"action_type": "purchase", "value": "40"}],
            "action_values": [{"action_type": "purchase", "value": "22922.75"}],
        }
        synthetic = _synthetic_boosted_rows_from_maximum_insights(
            insight_rows=[all_time_row],
            since="2026-07-30",
            until="2026-08-05",
        )
        self.assertEqual(len(synthetic), 1)
        row = synthetic[0]
        self.assertEqual(row["spend"], 0.0)
        self.assertEqual(row["actions"], [])
        self.assertEqual(row["action_values"], [])
        # Identidade do anúncio é preservada para fins de descoberta.
        self.assertEqual(row["ad_id"], "ad-1")


if __name__ == "__main__":
    unittest.main()
