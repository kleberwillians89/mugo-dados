"""Nenhum identificador técnico chega ao texto que o cliente lê."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.technical_text import (  # noqa: E402
    build_labels,
    has_technical_ids,
    humanize_analysis,
    humanize_analysis_row,
    humanize_answer,
    humanize_text,
)

METRICS = [
    {"id": "orders", "label": "Pedidos"},
    {"id": "new_customers", "label": "Novos clientes"},
    {"id": "revenue", "label": "Faturamento"},
]
SOURCES = [{"id": "shopify", "label": "Shopify"}, {"id": "meta_ads", "label": "Meta Ads"}]
LABELS = build_labels(METRICS, SOURCES)


class HumanizeTextTests(unittest.TestCase):
    def test_roove_executive_summary_case(self):
        text = "Os pedidos cresceram no período. metric_ids: orders, new_customers"
        out = humanize_text(text, LABELS)
        self.assertNotIn("metric_ids", out)
        self.assertNotIn("new_customers", out)
        self.assertIn("Pedidos, Novos clientes", out)

    def test_bracketed_citation_is_removed(self):
        text = "Os pedidos cresceram (metric_ids: orders, new_customers) no período."
        self.assertEqual(humanize_text(text, LABELS), "Os pedidos cresceram no período.")

    def test_square_bracket_sources_removed(self):
        text = "Investimento estável [sources: meta_ads]."
        self.assertEqual(humanize_text(text, LABELS), "Investimento estável.")

    def test_underscore_id_alone_becomes_label(self):
        out = humanize_text("A base de new_customers caiu.", LABELS)
        self.assertEqual(out, "A base de Novos clientes caiu.")

    def test_backticked_id_becomes_label(self):
        out = humanize_text("Acompanhe `new_customers` na semana.", LABELS)
        self.assertEqual(out, "Acompanhe Novos clientes na semana.")

    def test_single_word_ids_outside_citation_are_kept(self):
        # "orders" fora de uma citação técnica não é trocado: pode ser texto comum.
        self.assertEqual(humanize_text("Revise as orders.", LABELS), "Revise as orders.")

    def test_trailing_period_kept(self):
        out = humanize_text("Veja metric_ids: orders.", LABELS)
        self.assertEqual(out, "Veja Pedidos.")

    def test_snapshot_label_wins_over_default(self):
        labels = build_labels([{"id": "roas", "label": "Retorno real geral"}])
        self.assertEqual(humanize_text("metric_id: roas", labels), "Retorno real geral")

    def test_unknown_underscore_id_is_dropped_from_citation(self):
        out = humanize_text("Campanha forte (metric_ids: meta_campaign_abc_spend).", LABELS)
        self.assertEqual(out, "Campanha forte.")

    def test_plain_text_untouched(self):
        text = "Faturamento subiu com mais pedidos e ticket estável."
        self.assertEqual(humanize_text(text, LABELS), text)
        self.assertFalse(has_technical_ids(text, LABELS))

    def test_non_string_returned_as_is(self):
        self.assertIsNone(humanize_text(None, LABELS))
        self.assertEqual(humanize_text(3, LABELS), 3)


class HumanizeStructuresTests(unittest.TestCase):
    def analysis(self):
        return {
            "executive": {"overall": "Vendas fortes. metric_ids: orders, new_customers", "priority_action": "Manter."},
            "insights": [{
                "title": "Novos clientes (new_customers)", "interpretation": "Base cresceu [metric_ids: new_customers].",
                "action": "Acompanhar new_customers.", "reason": "ok", "metric_ids": ["new_customers"], "sources": ["shopify"],
            }],
            "actions": [{"recommendation": "Testar oferta para new_customers", "justification": "x", "impact_expected": "y",
                         "metric_id": "new_customers", "sources": ["shopify"]}],
        }

    def test_analysis_text_clean_and_structure_kept(self):
        out = humanize_analysis(self.analysis(), LABELS)
        for value in [*out["executive"].values(), out["insights"][0]["title"], out["insights"][0]["interpretation"],
                      out["insights"][0]["action"], out["actions"][0]["recommendation"]]:
            self.assertFalse(has_technical_ids(value, LABELS), value)
        self.assertEqual(out["insights"][0]["metric_ids"], ["new_customers"])
        self.assertEqual(out["actions"][0]["metric_id"], "new_customers")

    def test_stored_row_uses_its_own_snapshot(self):
        row = {"analysis": self.analysis(), "metrics_snapshot": METRICS, "sources": SOURCES}
        out = humanize_analysis_row(row)
        self.assertIn("Pedidos, Novos clientes", out["analysis"]["executive"]["overall"])

    def test_answer_lists_cleaned(self):
        answer = {"direct_answer": "Cresceu (metric_ids: orders).", "metric_ids": ["orders"],
                  "evidence": ["new_customers subiu"], "attention_points": [], "recommendations": ["Ver meta_ads"],
                  "next_steps": []}
        out = humanize_answer(answer, LABELS)
        self.assertEqual(out["direct_answer"], "Cresceu.")
        self.assertEqual(out["evidence"], ["Novos clientes subiu"])
        self.assertEqual(out["recommendations"], ["Ver Meta Ads"])
        self.assertEqual(out["metric_ids"], ["orders"])


if __name__ == "__main__":
    unittest.main()
