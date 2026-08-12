import unittest

from services.instagram_organic_history import aggregate_instagram_content, aggregate_instagram_months


def media(kind="FEED", timestamp="2026-08-05T12:00:00Z", **metrics):
    available = list(metrics)
    return {
        "media_product_type": kind,
        "timestamp": timestamp,
        "insights_json": {**metrics, "available_metrics": available} if metrics else {},
    }


class InstagramOrganicHistoryTests(unittest.TestCase):
    def test_stories_do_not_reduce_content_coverage_or_become_zero(self):
        rows = [media("REELS", reach=100) for _ in range(4)] + [media("FEED", reach=50)] + [media("STORY") for _ in range(6)]
        result = aggregate_instagram_content(rows)
        self.assertEqual(result["eligible_content_count"], 5)
        self.assertEqual(result["metrics"]["reach"]["available_count"], 5)
        self.assertEqual(result["metrics"]["reach"]["eligible_count"], 5)
        self.assertEqual(result["stories"]["published_count"], 6)
        self.assertFalse(result["stories"]["historical_insights_available"])

    def test_available_metrics_distinguishes_zero_from_unavailable(self):
        result = aggregate_instagram_content([media(likes=0), media(reach=20)])
        self.assertEqual(result["metrics"]["likes"]["value"], 0)
        self.assertEqual(result["metrics"]["likes"]["available_count"], 1)
        self.assertIsNone(result["metrics"]["views"]["value"])

    def test_month_fixtures_keep_content_reach_and_interactions(self):
        may = [media(timestamp="2026-05-10T12:00:00Z", reach=3385, total_interactions=184) for _ in range(6)]
        may.append(media(timestamp="2026-05-20T12:00:00Z", reach=3385, total_interactions=189))
        july = [media(timestamp="2026-07-10T12:00:00Z", reach=1792, total_interactions=141) for _ in range(6)]
        july.append(media(timestamp="2026-07-20T12:00:00Z", reach=1793, total_interactions=142))
        months = aggregate_instagram_months(may + july)
        self.assertEqual(months[0]["metrics"]["reach"]["value"], 23695)
        self.assertEqual(months[0]["metrics"]["total_interactions"]["value"], 1293)
        self.assertEqual(months[1]["metrics"]["reach"]["value"], 12545)
        self.assertEqual(months[1]["metrics"]["total_interactions"]["value"], 988)
