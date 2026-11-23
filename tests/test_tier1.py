"""Tests for the retailer lookup, units totals, calendar-year filter and note numbering.

Uses the shared fixture plus rows that the original fixture never exercised: recalls announced
in Oct-Dec (so the fiscal-year recall number disagrees with the calendar year), a retailer
spelled "Wal-Mart", and a retailer named in a title but not in "sold at".
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recalls_server import db, limits, tools  # noqa: E402
from tests import fixture  # noqa: E402

EXTRA_ROWS = [
    # number, title, date, product, hazard, units_text, units, sold_at
    # FY2026 number, announced in calendar 2025.
    ("26001", "Kilo Recalls Lamps Due to Shock Hazard", "2025-11-06", "Lamp", "Shock", "About 5,000", 5000,
     "Wal-Mart stores nationwide and online at Amazon.com"),
    # Walmart is the recalling firm, not a place it was sold.
    ("26002", "Walmart Recalls Grill Brushes Due to Ingestion Hazard", "2025-12-01", "Grill Brush", "Ingestion",
     "About 300", 300, "Target stores nationwide"),
]


class Tier1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "recalls.db")
        fixture.build(cls.path)
        con = sqlite3.connect(cls.path)
        start = len(fixture.ROWS) + 1
        for i, (number, title, date, product, hazard, units_text, units, sold_at) in enumerate(EXTRA_ROWS, start=start):
            con.execute(
                "INSERT INTO recalls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (i, number, title, date, date, f"This recall involves {product}.", hazard, "Refund.", "Refund",
                 product, "Household", units_text, units, sold_at, "China", "", f"https://example.test/{number}"),
            )
        con.commit()
        con.close()
        os.environ["RECALLS_DB"] = cls.path

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("RECALLS_DB", None)
        cls.tmp.cleanup()

    # Calendar year -----------------------------------------------------------------------

    def test_year_is_calendar_year_not_recall_number_prefix(self):
        # 25201, 25202 (prefix 25) and 26001, 26002 (prefix 26, announced Nov/Dec 2025).
        self.assertEqual(tools.count_recalls(year=2025)["count"], 4)
        self.assertEqual(tools.count_recalls(year=2026)["count"], 8)

    def test_year_filter_does_not_wrap_centuries(self):
        self.assertEqual(tools.count_recalls(year=1925)["count"], 0)

    # Retailer lookup ---------------------------------------------------------------------

    def test_sold_at_matches_only_where_sold(self):
        out = tools.recalls_sold_at("Walmart")
        numbers = {r["recall_number"] for r in out["results"]}
        self.assertNotIn("26002", numbers)  # "Walmart" only in the title
        self.assertEqual(numbers, {"25201", "26106", "26001"})
        self.assertEqual(out["total"], 3)

    def test_sold_at_spellings_are_equivalent(self):
        for name in ("Walmart", "walmart", "Wal-Mart", "walmart.com", "www.walmart.com"):
            self.assertEqual(tools.recalls_sold_at(name)["total"], 3, name)

    def test_sold_at_with_year_and_days(self):
        self.assertEqual(tools.recalls_sold_at("Amazon", year=2026)["total"], 2)
        out = tools.recalls_sold_at("Amazon", days=30, today=dt.date(2026, 3, 25))
        self.assertEqual([r["recall_number"] for r in out["results"]], ["26105"])

    def test_count_recalls_by_retailer(self):
        self.assertEqual(tools.count_recalls(retailer="Amazon")["count"], 4)

    def test_sold_at_requires_retailer(self):
        self.assertIn("error", tools.recalls_sold_at("  "))

    def test_like_wildcards_are_literal(self):
        self.assertEqual(tools.recalls_sold_at("%")["total"], 0)
        self.assertEqual(tools.count_recalls("_")["count"], 0)

    def test_sold_at_paging_does_not_skip_trimmed_rows(self):
        original = limits.MAX_RESPONSE_CHARS
        limits.MAX_RESPONSE_CHARS = 900  # forces fit() to drop rows from every page
        try:
            seen, cursor = [], 0
            while True:
                out = tools.recalls_sold_at("Amazon", limit=50, cursor=cursor)
                self.assertGreater(len(out["results"]), 0)
                seen += [r["recall_number"] for r in out["results"]]
                if "next_cursor" not in out:
                    break
                cursor = out["next_cursor"]
        finally:
            limits.MAX_RESPONSE_CHARS = original
        self.assertEqual(sorted(seen), ["25202", "26001", "26101", "26105"])

    # Units -------------------------------------------------------------------------------

    def test_units_for_a_year(self):
        out = tools.units_recalled(year=2025)
        self.assertEqual(out["recalls"], 4)
        self.assertEqual(out["total_units"], 1200 + 900 + 5000 + 300)
        self.assertEqual(out["top_by_units"][0]["recall_number"], "26001")
        self.assertIn("caveat", out)

    def test_units_for_a_retailer(self):
        out = tools.units_recalled(retailer="Wal-Mart")
        self.assertEqual(out["total_units"], 1200 + 8000 + 5000)

    def test_units_year_and_retailer(self):
        self.assertEqual(tools.units_recalled(year=2026, retailer="Amazon")["total_units"], 4000 + 3300)

    def test_units_top_n(self):
        out = tools.units_recalled(year=2026, top=3)
        self.assertEqual([r["units"] for r in out["top_by_units"]], [15000, 8000, 6100])
        self.assertEqual(len(tools.units_recalled(top=500)["top_by_units"]), len(fixture.ROWS) + len(EXTRA_ROWS))

    def test_units_with_no_matches(self):
        out = tools.units_recalled(retailer="Nowhere Mart")
        self.assertEqual((out["recalls"], out["total_units"], out["top_by_units"]), (0, 0, []))

    def test_units_response_is_json_serializable(self):
        json.dumps(tools.units_recalled(year=2026))

    # Notes -------------------------------------------------------------------------------

    def test_note_added_with_dash_shows_on_get_recall(self):
        saved = tools.add_note("26-103", "Legal is reviewing our listings.")
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["recall_number"], "26103")
        bodies = [n["body"] for n in tools.get_recall("26103")["notes"]]
        self.assertIn("Legal is reviewing our listings.", bodies)
        self.assertEqual(tools.get_recall("26-103")["notes"], tools.get_recall("26103")["notes"])

    def test_note_on_unknown_recall_is_rejected(self):
        out = tools.add_note("99-999", "Should not be saved.")
        self.assertFalse(out["saved"])
        self.assertIn("error", out)

    def test_normalize_recall_number(self):
        for raw in ("26-103", "26103", "Recall 26-103", "Recall 26-103 (2026)", " 26 - 103 "):
            self.assertEqual(db.normalize_recall_number(raw), "26103", raw)


if __name__ == "__main__":
    unittest.main()
