"""Recalls MCP server (stdio).

Run:  python server.py
Agents connect to it as an MCP server named "recalls". See README.md for client setup.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from recalls_server import tools  # noqa: E402

mcp = FastMCP(
    "recalls",
    instructions=(
        "Product recall lookups for the marketplace-safety team. Data comes from the US Consumer "
        "Product Safety Commission and is refreshed nightly. Use count_recalls for 'how many' "
        "questions instead of paging search_recalls. Use recalls_sold_at for 'what was sold at X' "
        "(it matches only where the product was sold), and units_recalled for 'how many units' "
        "questions, totals and the biggest recalls. Years are calendar years of the recall date. "
        "Call server_status first and mention any known_data_issues that affect the answer."
    ),
)


@mcp.tool()
def search_recalls(query: str = "", year: int | None = None, limit: int = 20, cursor: int = 0) -> dict:
    """Search product recalls, newest first.

    `query` matches the recall title, product name, hazard and where the product was sold.
    For "sold at <retailer>" questions use recalls_sold_at instead. `year` is the calendar year
    the recall was announced. Returns `total` (all matches), up to
    `limit` results (max 50), and `next_cursor` when there are more: pass it back as `cursor`.
    """
    return tools.search_recalls(query, year, limit, cursor)


@mcp.tool()
def count_recalls(query: str = "", year: int | None = None, retailer: str | None = None) -> dict:
    """Count recalls matching `query`, `year` (calendar year) and/or `retailer`.

    `query` follows search_recalls. `retailer` matches only where the product was sold, with the
    same spellings as recalls_sold_at.
    """
    return tools.count_recalls(query, year, retailer)


@mcp.tool()
def recalls_sold_at(
    retailer: str, year: int | None = None, days: int | None = None, limit: int = 20, cursor: int = 0
) -> dict:
    """List recalls of products sold at a retailer, newest first.

    Matches only the "sold at" field, not titles or hazards, and covers the usual spellings
    (for example Walmart, Wal-Mart and walmart.com; Amazon and Amazon.com). Optional `year`
    (calendar year of the recall) and `days` (announced in the last N days). Returns `total`
    (all matches), up to `limit` results (max 50) and `next_cursor` when there are more.
    """
    return tools.recalls_sold_at(retailer, year, days, limit, cursor)


@mcp.tool()
def units_recalled(
    year: int | None = None, retailer: str | None = None, days: int | None = None, top: int = 5
) -> dict:
    """Total units recalled, and the recalls that covered the most units.

    Filter by `year` (calendar year of the recall), `retailer` (where it was sold, same matching
    as recalls_sold_at) and/or `days` (announced in the last N days). Returns the number of
    recalls, `total_units`, and the `top` recalls by units (max 20). Read `caveat` before
    quoting a total.
    """
    return tools.units_recalled(year, retailer, days, top)


@mcp.tool()
def get_recall(recall_number: str) -> dict:
    """Get one recall with all its details and any notes the team has added.

    Accepts the number with or without the dash (for example 26-123 or 26123).
    """
    return tools.get_recall(recall_number)


@mcp.tool()
def recent_recalls(days: int = 30, limit: int = 50, cursor: int = 0) -> dict:
    """List recalls announced in the last `days` days (default 30, max 365), newest first.

    Returns `total` (all recalls in the window), `returned` (on this page), `next_cursor` when
    there are more, and `data_through` (the newest recall date loaded). If `data_through` is well
    before today, recent recalls are missing: say so. For "sold at X" use recalls_sold_at with `days`.
    """
    return tools.recent_recalls(days, limit, cursor)


@mcp.tool()
def add_note(recall_number: str, note: str, author: str = "agent") -> dict:
    """Attach a short note to a recall so teammates and their agents can see it on get_recall.

    Accepts the number with or without the dash. Fails if no recall has that number.
    """
    return tools.add_note(recall_number, note, author)


@mcp.tool()
def server_status() -> dict:
    """Report how many recalls are loaded, how fresh the data is, and when the nightly load last ran.

    Also returns `earliest_recall_date`, `latest_recall_date` and `known_data_issues`: problems in
    the loaded data that make some counts, unit totals and retailer lookups lower bounds. Check
    `warnings` and `known_data_issues` before answering, and mention the ones that affect the answer.
    """
    return tools.server_status()


if __name__ == "__main__":
    mcp.run()
