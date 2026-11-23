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

# CPSC announces recalls most weeks, usually on Thursdays. If the newest recall in the snapshot is
# older than this, the feed or the loader has probably stopped delivering new recalls.
STALE_AFTER_DAYS = 10
# The loader runs nightly; allow for a late or slow run before calling the load overdue.
LOAD_OVERDUE_HOURS = 36

# Problems in the snapshot that the nightly loader (in the data-platform repo) introduces. Found by
# comparing data/recalls.db with the live CPSC feed on 2026-11-23. Remove an entry once the loader
# is fixed and a reload confirms it.
KNOWN_DATA_ISSUES = [
    {
        "issue": "Recalls whose unit count is written in millions (for example 'About 21 million') are "
                 "missing from the database.",
        "example": "24281 (MGA Miniverse, about 21 million units) is not loaded.",
        "effect": "Counts and unit totals for every period are too low, and 'largest recall' answers "
                  "can be wrong. Treat them as lower bounds.",
    },
    {
        "issue": "Some 'sold at' text is cut off, usually at '... and online at', so retailers named "
                 "after that point are lost.",
        "example": "25392 is stored as 'Bikes with the recalled batteries were sold'; CPSC lists "
                   "amazon.com and walmart.com after that.",
        "effect": "Retailer lookups (recalls_sold_at, retailer filters) miss recalls. Treat them as "
                  "lower bounds.",
    },
    {
        "issue": "Some unit counts are misparsed from the CPSC wording.",
        "example": "24018: 'About 17, 370' is stored as 17 units.",
        "effect": "Unit totals can be off. Check units_text for any recall you single out.",
    },
]


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
    if days is not None:
        extra["data_through"] = db.newest_recall_date()
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
    payload = {"filters": filters, **summary, "caveat": UNITS_CAVEAT}
    if days is not None:
        payload["data_through"] = db.newest_recall_date()
    return fit(payload, key="top_by_units")


def get_recall(recall_number: str) -> dict:
    record = db.get(recall_number)
    if record is None:
        return {"found": False, "recall_number": recall_number}
    record["found"] = True
    return record


def recent_recalls(days: int = 30, limit: int = 50, cursor: int = 0, today: dt.date | None = None) -> dict:
    days = max(1, min(days or 30, 365))
    limit = clamp_limit(limit if limit else 50)
    cursor = max(cursor or 0, 0)
    total, rows = db.search("", None, limit, cursor, days=days, today=today)
    payload = _paged(total, rows, cursor, {"days": days, "data_through": db.newest_recall_date()})
    payload["returned"] = len(payload["results"])
    return payload


def add_note(recall_number: str, note: str, author: str = "agent") -> dict:
    if not (note or "").strip():
        return {"saved": False, "error": "note is empty"}
    if not db.exists(recall_number):
        return {"saved": False, "error": f"no recall numbered {recall_number!r}"}
    saved = db.add_note(recall_number, note, author or "agent")
    return {"saved": True, **saved}


def _parse_utc(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def server_status(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    status = db.status()
    warnings: list[str] = []

    newest = status["latest_recall_date"]
    days_since_newest = (now.date() - dt.date.fromisoformat(newest)).days if newest else None
    if days_since_newest is None:
        warnings.append("No recalls are loaded.")
    elif days_since_newest > STALE_AFTER_DAYS:
        warnings.append(
            f"The newest recall is from {newest}, {days_since_newest} days ago. CPSC announces recalls "
            "most weeks, so recalls announced since then are probably missing. Treat 'recent' and "
            "count answers as incomplete."
        )

    last_run = _parse_utc(status["last_load_at"]) if status["last_load_at"] else None
    hours_since_load = round((now - last_run).total_seconds() / 3600, 1) if last_run else None
    if last_run is None:
        warnings.append("No nightly load has been recorded.")
    elif hours_since_load > LOAD_OVERDUE_HOURS:
        warnings.append(f"The last nightly load ran {hours_since_load} hours ago; it looks overdue.")
    if status["last_load_status"] not in ("ok", "never"):
        warnings.append(f"The last nightly load reported status {status['last_load_status']!r}.")
    if status["last_load_status"] == "ok" and days_since_newest is not None and days_since_newest > STALE_AFTER_DAYS:
        warnings.append("The loader reports 'ok', but no new recalls have arrived, so its status can't be trusted.")

    issues = list(KNOWN_DATA_ISSUES)
    if newest:
        issues.append({
            "issue": f"Data ends {newest}.",
            "example": f"No recall announced after {newest} is loaded.",
            "effect": "Questions about recent recalls, or about periods that run past that date, "
                      "are incomplete.",
        })

    return {
        **status,
        "days_since_newest_recall": days_since_newest,
        "hours_since_last_load": hours_since_load,
        "data_fresh": not warnings,
        "warnings": warnings,
        "known_data_issues": issues,
        "source": SOURCE,
    }
