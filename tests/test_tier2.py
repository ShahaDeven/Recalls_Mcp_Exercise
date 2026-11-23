"""Tests for data freshness in server_status and honest totals in recent_recalls.

Fixture: newest recall 2026-03-20, last load 2026-03-25T02:00:07Z, status 'ok'.
"""
import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recalls_server import limits, tools  # noqa: E402
from tests import fixture  # noqa: E402

UTC = dt.timezone.utc


class Tier2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "recalls.db")
        fixture.build(cls.path)
        os.environ["RECALLS_DB"] = cls.path

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("RECALLS_DB", None)
        cls.tmp.cleanup()

    # Freshness ---------------------------------------------------------------------------

    def test_status_fresh_right_after_load(self):
        out = tools.server_status(now=dt.datetime(2026, 3, 25, 12, 0, tzinfo=UTC))
        self.assertEqual(out["earliest_recall_date"], "2025-03-01")
        self.assertEqual(out["latest_recall_date"], "2026-03-20")
        self.assertEqual(out["days_since_newest_recall"], 5)
        self.assertTrue(out["data_fresh"])
        self.assertEqual(out["warnings"], [])

    def test_status_flags_stale_recalls_even_when_load_says_ok(self):
        out = tools.server_status(now=dt.datetime(2026, 4, 10, 12, 0, tzinfo=UTC))
        self.assertEqual(out["last_load_status"], "ok")
        self.assertFalse(out["data_fresh"])
        self.assertEqual(out["days_since_newest_recall"], 21)
        joined = " ".join(out["warnings"])
        self.assertIn("2026-03-20", joined)
        self.assertIn("can't be trusted", joined)
        self.assertIn("overdue", joined)

    def test_status_flags_failed_load(self):
        con = sqlite3.connect(self.path)
        con.execute("INSERT INTO load_log VALUES ('2026-03-26T02:00:07Z', 'error', 0)")
        con.commit()
        con.close()
        try:
            out = tools.server_status(now=dt.datetime(2026, 3, 26, 12, 0, tzinfo=UTC))
            self.assertFalse(out["data_fresh"])
            self.assertTrue(any("'error'" in w for w in out["warnings"]))
        finally:
            con = sqlite3.connect(self.path)
            con.execute("DELETE FROM load_log WHERE run_at = '2026-03-26T02:00:07Z'")
            con.commit()
            con.close()

    def test_status_lists_known_data_issues(self):
        issues = tools.server_status(now=dt.datetime(2026, 3, 25, 12, 0, tzinfo=UTC))["known_data_issues"]
        text = " ".join(i["issue"] + " " + i["example"] for i in issues)
        for expected in ("millions", "24281", "cut off", "25392", "24018", "Data ends 2026-03-20."):
            self.assertIn(expected, text)
        for issue in issues:
            self.assertEqual(set(issue), {"issue", "example", "effect"})

    # recent_recalls totals ---------------------------------------------------------------

    def test_recent_reports_true_total_and_pages(self):
        today = dt.date(2026, 3, 25)
        out = tools.recent_recalls(365, limit=3, today=today)
        # The window starts 2025-03-25, so 25201 (2025-03-01) is outside it: 9 of the 10 rows.
        self.assertEqual(out["total"], 9)
        self.assertEqual(out["returned"], 3)
        self.assertEqual(out["next_cursor"], 3)
        self.assertEqual(out["data_through"], "2026-03-20")
        seen, cursor = [], 0
        while True:
            page = tools.recent_recalls(365, limit=3, cursor=cursor, today=today)
            seen += [r["recall_number"] for r in page["results"]]
            if "next_cursor" not in page:
                break
            cursor = page["next_cursor"]
        self.assertEqual(len(seen), 9)
        self.assertEqual(len(set(seen)), 9)
        self.assertNotIn("25201", seen)

    def test_recent_returned_matches_results_after_trimming(self):
        original = limits.MAX_RESPONSE_CHARS
        limits.MAX_RESPONSE_CHARS = 900
        try:
            out = tools.recent_recalls(365, today=dt.date(2026, 3, 25))
        finally:
            limits.MAX_RESPONSE_CHARS = original
        self.assertEqual(out["returned"], len(out["results"]))
        self.assertLess(out["returned"], out["total"])
        self.assertEqual(out["next_cursor"], out["returned"])

    def test_days_queries_report_data_through(self):
        today = dt.date(2026, 3, 25)
        self.assertEqual(tools.recalls_sold_at("Amazon", days=30, today=today)["data_through"], "2026-03-20")
        self.assertEqual(tools.units_recalled(days=30, today=today)["data_through"], "2026-03-20")
        self.assertNotIn("data_through", tools.units_recalled(year=2026))


if __name__ == "__main__":
    unittest.main()
