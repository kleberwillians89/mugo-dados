from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.meta_reprocessing import recalculate_purchase_columns


class MetaRawReprocessingTests(unittest.TestCase):
    def test_recalculates_persisted_raw_without_adding_aliases(self):
        aliases = (
            "offsite_conversion.fb_pixel_purchase",
            "omni_purchase",
            "onsite_web_purchase",
            "purchase",
            "web_in_store_purchase",
        )
        raw_json = [{
            "actions": [{"action_type": alias, "value": "1"} for alias in aliases],
            "action_values": [{"action_type": alias, "value": "1067"} for alias in aliases],
        }]
        result = recalculate_purchase_columns(raw_json, 100)
        self.assertEqual(result["conversions"], 1)
        self.assertEqual(result["revenue"], 1067)
        self.assertEqual(result["roas"], 10.67)
        self.assertEqual(
            result["purchase_action_types_selected"],
            ["offsite_conversion.fb_pixel_purchase"],
        )

    def test_is_idempotent_for_already_canonical_raw(self):
        raw_json = [{
            "actions": [{"action_type": "omni_purchase", "value": "3"}],
            "action_values": [{"action_type": "omni_purchase", "value": "1317.94"}],
        }]
        first = recalculate_purchase_columns(raw_json, 400)
        second = recalculate_purchase_columns(raw_json, 400)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
