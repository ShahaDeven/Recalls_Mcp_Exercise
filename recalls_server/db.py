"""Read and write access to the recalls snapshot (SQLite)."""
from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import sqlite3
from typing import Any, Iterator

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "recalls.db")

SUMMARY_COLUMNS = (
    "recall_number, title, recall_date, product_name, hazard, units, sold_at, url"
)

# Spellings CPSC uses for the same retailer. Keys are the retailer name lowercased with
# everything but letters and digits removed (so "Wal-Mart", "walmart.com" and "Walmart" all
# land on "walmart"). Anything not listed is matched as typed.
RETAILER_ALIASES: dict[str, list[str]] = {
    "walmart": ["walmart", "wal-mart", "wal mart"],
    "amazon": ["amazon"],
    "homedepot": ["home depot", "homedepot"],
    "lowes": ["lowe's", "lowes", "lowe’s"],
    "target": ["target"],
    "costco": ["costco"],
    "bestbuy": ["best buy", "bestbuy"],
}


def db_path() -> str:
    return os.environ.get("RECALLS_DB", DEFAULT_DB)


@contextlib.contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def normalize_recall_number(value: str) -> str:
    """Accept '26-123', '26123' or 'Recall 26-123 (2026)' and return the stored form ('26123')."""
    value = value or ""
    match = re.search(r"(?<!\d)(\d{2})\s*-?\s*(\d{3})(?!\d)", value)
    if match:
        return match.group(1) + match.group(2)
    return re.sub(r"\D", "", value)


def _like(term: str) -> str:
    """A LIKE pattern that matches `term` literally anywhere (escapes %, _ and \\)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def retailer_patterns(retailer: str) -> list[str]:
    """The spellings to look for in `sold_at` for one retailer name."""
    name = (retailer or "").strip().lower()
    name = re.sub(r"^(https?://)?(www\.)?", "", name)
    name = re.sub(r"\.com$", "", name)
    key = re.sub(r"[^a-z0-9]", "", name)
    if not key:
        return []
    return RETAILER_ALIASES.get(key, [name])


def _where(
    query: str = "",
    year: int | None = None,
    retailer: str | None = None,
    days: int | None = None,
    today: dt.date | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    query = (query or "").strip()
    if query:
        like = _like(query)
        clauses.append(
            "(title LIKE ? ESCAPE '\\' OR product_name LIKE ? ESCAPE '\\' "
            "OR hazard LIKE ? ESCAPE '\\' OR sold_at LIKE ? ESCAPE '\\')"
        )
        params += [like, like, like, like]
    if year is not None:
        # Calendar year of the announcement. (Recall numbers start with CPSC's fiscal year,
        # which begins on 1 October, so they can't be used for this.)
        year = int(year)
        clauses.append("recall_date >= ? AND recall_date < ?")
        params += [f"{year:04d}-01-01", f"{year + 1:04d}-01-01"]
    if retailer is not None:
        patterns = retailer_patterns(retailer)
        if not patterns:
            clauses.append("0")
        else:
            clauses.append("(" + " OR ".join("sold_at LIKE ? ESCAPE '\\'" for _ in patterns) + ")")
            params += [_like(p) for p in patterns]
    if days is not None:
        since = ((today or dt.date.today()) - dt.timedelta(days=int(days))).isoformat()
        clauses.append("recall_date >= ?")
        params.append(since)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def search(
    query: str = "",
    year: int | None = None,
    limit: int = 20,
    offset: int = 0,
    *,
    retailer: str | None = None,
    days: int | None = None,
    today: dt.date | None = None,
) -> tuple[int, list[dict]]:
    where, params = _where(query, year, retailer, days, today)
    with connect() as con:
        total = con.execute(f"SELECT COUNT(*) FROM recalls{where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT {SUMMARY_COLUMNS} FROM recalls{where} ORDER BY recall_date DESC, recall_number DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return total, [dict(r) for r in rows]


def count(
    query: str = "",
    year: int | None = None,
    *,
    retailer: str | None = None,
    days: int | None = None,
    today: dt.date | None = None,
) -> int:
    where, params = _where(query, year, retailer, days, today)
    with connect() as con:
        return con.execute(f"SELECT COUNT(*) FROM recalls{where}", params).fetchone()[0]


def units_summary(
    year: int | None = None,
    retailer: str | None = None,
    days: int | None = None,
    top: int = 5,
    today: dt.date | None = None,
) -> dict:
    """Total units over the matching recalls, plus the `top` recalls by units."""
    where, params = _where("", year, retailer, days, today)
    with connect() as con:
        agg = con.execute(
            f"SELECT COUNT(*) AS recalls, COUNT(units) AS with_units, COALESCE(SUM(units), 0) AS total "
            f"FROM recalls{where}",
            params,
        ).fetchone()
        top_rows = con.execute(
            f"SELECT recall_number, title, recall_date, units, units_text, sold_at, url FROM recalls{where} "
            f"{'AND' if where else 'WHERE'} units IS NOT NULL "
            f"ORDER BY units DESC, recall_date DESC LIMIT ?",
            params + [top],
        ).fetchall()
    return {
        "recalls": agg["recalls"],
        "recalls_with_units": agg["with_units"],
        "total_units": agg["total"],
        "top_by_units": [dict(r) for r in top_rows],
    }


def exists(recall_number: str) -> bool:
    with connect() as con:
        return con.execute(
            "SELECT 1 FROM recalls WHERE recall_number = ? LIMIT 1", [normalize_recall_number(recall_number)]
        ).fetchone() is not None


def get(recall_number: str) -> dict | None:
    number = normalize_recall_number(recall_number)
    with connect() as con:
        row = con.execute("SELECT * FROM recalls WHERE recall_number = ?", [number]).fetchone()
        if row is None:
            return None
        record = dict(row)
        notes = con.execute(
            "SELECT author, body, created_at FROM notes WHERE recall_number = ? ORDER BY created_at",
            [number],
        ).fetchall()
    record["notes"] = [dict(n) for n in notes]
    return record


def recent(days: int, today: dt.date | None = None, limit: int = 50) -> list[dict]:
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    with connect() as con:
        rows = con.execute(
            f"SELECT {SUMMARY_COLUMNS} FROM recalls WHERE recall_date >= ? ORDER BY recall_date DESC, recall_number DESC LIMIT ?",
            [since, limit],
        ).fetchall()
    return [dict(r) for r in rows]


def add_note(recall_number: str, body: str, author: str) -> dict:
    """Store a note against the normalized recall number (the form get() looks up)."""
    number = normalize_recall_number(recall_number)
    created = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as con:
        cur = con.execute(
            "INSERT INTO notes (recall_number, author, body, created_at) VALUES (?, ?, ?, ?)",
            [number, author, body.strip(), created],
        )
        con.commit()
        note_id = cur.lastrowid
    return {"id": note_id, "recall_number": number, "author": author, "created_at": created}


def status() -> dict:
    with connect() as con:
        rows = con.execute("SELECT COUNT(*) FROM recalls").fetchone()[0]
        last = con.execute("SELECT run_at, status FROM load_log ORDER BY run_at DESC LIMIT 1").fetchone()
    return {
        "recalls_loaded": rows,
        "last_load_at": last["run_at"] if last else None,
        "last_load_status": last["status"] if last else "never",
    }
