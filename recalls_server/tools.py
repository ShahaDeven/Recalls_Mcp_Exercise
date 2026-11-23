"""Tool implementations. Kept free of MCP imports so they can be unit tested directly."""
from __future__ import annotations

import datetime as dt

from . import db
from .limits import clamp_limit, fit

SOURCE = "US Consumer Product Safety Commission recalls feed, loaded nightly"

UNITS_CAVEAT = (
    "Units are the number CPSC states for each recall (see units_text). They are usually US units "
    "only, can undercount a recall that covers several products, and can include units from an "
    "earlier recall of the same product. Quote units_text for any recall you single out."
)

MAX_TOP = 20


def _paged(total: int, rows: list[dict], cursor: int, extra: dict | None = None) -> dict:
    """Build a page and set next_cursor from the rows actually returned after trimming."""
    payload = {**(extra or {}), "total": total, "results": rows}
    payload = fit(payload)
    shown = len(payload["results"])
    if cursor + shown < total:
        payload["next_cursor"] = cursor + shown
    return payload


def search_recalls(query: str = "", year: int | None = None, limit: int = 20, cursor: int = 0) -> dict:
    limit = clamp_limit(limit)
    cursor = max(cursor or 0, 0)
    total, rows = db.search(query, year, limit, cursor)
    return _paged(total, rows, cursor)


def count_recalls(query: str = "", year: int | None = None, retailer: str | None = None) -> dict:
    return {"count": db.count(query, year, retailer=retailer or None)}


def recalls_sold_at(
    retailer: str,
    year: int | None = None,
    days: int | None = None,
    limit: int = 20,
    cursor: int = 0,
    today: dt.date | None = None,
) -> dict:
    if not (retailer or "").strip():
        return {"error": "retailer is required, for example 'Amazon' or 'Walmart'"}
    if days is not None:
        days = max(1, min(int(days), 3650))
    limit = clamp_limit(limit)
    cursor = max(cursor or 0, 0)
    total, rows = db.search("", year, limit, cursor, retailer=retailer, days=days, today=today)
    extra = {
        "retailer": retailer,
        "matched_spellings": db.retailer_patterns(retailer),
        "year": year,
        "days": days,
    }
    return _paged(total, rows, cursor, extra)


def units_recalled(
    year: int | None = None,
    retailer: str | None = None,
    days: int | None = None,
    top: int = 5,
    today: dt.date | None = None,
) -> dict:
    if days is not None:
        days = max(1, min(int(days), 3650))
    top = max(0, min(int(top or 0), MAX_TOP))
    retailer = (retailer or "").strip() or None
    summary = db.units_summary(year=year, retailer=retailer, days=days, top=top, today=today)
    filters = {"year": year, "retailer": retailer, "days": days}
    if retailer:
        filters["matched_spellings"] = db.retailer_patterns(retailer)
    return fit({"filters": filters, **summary, "caveat": UNITS_CAVEAT}, key="top_by_units")


def get_recall(recall_number: str) -> dict:
    record = db.get(recall_number)
    if record is None:
        return {"found": False, "recall_number": recall_number}
    record["found"] = True
    return record


def recent_recalls(days: int = 30, today: dt.date | None = None) -> dict:
    days = max(1, min(days or 30, 365))
    rows = db.recent(days, today=today)
    return fit({"days": days, "count": len(rows), "results": rows})


def add_note(recall_number: str, note: str, author: str = "agent") -> dict:
    if not (note or "").strip():
        return {"saved": False, "error": "note is empty"}
    if not db.exists(recall_number):
        return {"saved": False, "error": f"no recall numbered {recall_number!r}"}
    saved = db.add_note(recall_number, note, author or "agent")
    return {"saved": True, **saved}


def server_status() -> dict:
    return {**db.status(), "source": SOURCE}
