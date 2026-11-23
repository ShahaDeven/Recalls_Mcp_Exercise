# Submission note: Deven Shah

About 40 minutes. Recording: 5:54, unedited.

## Ready for Monday? No.

The server now answers Dana's two questions, but the data underneath is wrong. I compared the whole snapshot with CPSC's official feed (1,579 recalls since 2023):

- **104 recalls are missing**, including all 40 with units written in millions. The biggest 2024 recall (24281, MGA Miniverse, ~21M units) isn't loaded, so "most units" returns Samsung at 1.12M.
- **395 "sold at" texts are cut off** at "and online at…" (e.g. 27065), losing Amazon from 138 and Walmart from 29.
- **Nothing after 2026-11-05**, while the loader logs "ok" nightly.

Net effect: 2025 recalls 411 vs 420; Walmart 162 vs 222; Amazon in the last 30 days 1 vs 27. These are loader bugs, in a repo I don't have. Until it's fixed and reloaded, every count is a lower bound. Fine for exploration, not for figures the team quotes.

## What I built

`recalls_sold_at` and `units_recalled` (SQL totals, top N, by year/retailer/days). Fixed: calendar-year filter (was fiscal-year prefix, 341 → 411), `add_note` numbering (`27-010` was saved but never shown), paging that skipped 372 of 585 Amazon rows, `recent_recalls` totals, freshness warnings. 25 new tests, 40 passing. `known_data_issues` in `server_status` is a hand-written list from my comparison, not detection. The agent names MGA in Q3 only because that list uses 24281 as its example.

## Not checked

Loader code; unit parsing beyond spot checks (24018 "17, 370" → 17); Canada units and re-announced recalls; other MCP clients; concurrent note writes. `data/recalls.db` includes the 27-010 note from the recording.

## Questions for Dana (assumption)

- Calendar or fiscal year? (Calendar.)
- Include Canada units or earlier-recall units? (US as stated, no de-duplication.)
- Does "sold at Amazon" include third-party sellers? (Any mention.)
- Who owns the loader, and can it be fixed before Monday?
- Should notes record the real author? (Left as "agent".)

## AI tools

Claude Code (Claude Opus 5.5) for code, tests, data checks and the recording session.
