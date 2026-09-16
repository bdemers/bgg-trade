# Handoff — September 2026 US Math Trade (geeklist 383775)

Written 2026-09-09, updated 2026-09-16. Delete this file once the trade is over.

## Where this is up to

The want list is **staged on the OLWLG and verified, but not submitted**.
Submitting is Brian's click, after he has looked it over.

* Geeklist refreshed 2026-09-16 after posting closed: 6,015 items.
* Collection refreshed the same day, by curl (see AGENTS.md, Configuration).
* `matrix_overrides.json` holds the reviewed matrix: 162 of 163 rows confirmed,
  23 games wanted. Capital Lux 2: Generations is the one row never reviewed, so
  it follows the floors and every item accepts it.
* `python3 olwlg.py stage` created 10 dummies for the multi-copy games, added
  46 Step 3 wants and saved 209 grid cells. `python3 olwlg.py verify` reports
  "Matches the plan".

## Dates that drive the rest of it

* **Sun 20 Sep 2026, 03:30 EDT** — trade ends. Want lists must be submitted
  before this. Confirmed on the OLWLG page on 2026-09-16.

## What is left

1. Brian checks the Summary tab on the OLWLG, and decides on Capital Lux 2.
2. If the matrix changes: `./review.sh`, then `./run.sh`, then
   `python3 olwlg.py stage`. The grid save replaces the whole set.
3. `python3 olwlg.py verify`, then Brian clicks **Submit My Wants**.

## Things that will bite

* `GEEK_SESSION` in `.env` expires within hours. Refresh it immediately before
  any run that talks to BGG, not the night before.
* `./run.sh --refresh-collection` gets 403 and silently uses the cache.
* `OLWLG_BGGID` is the OLWLG login and is separate from `GEEK_SESSION`.
* Restart `./review.sh` after any `./run.sh` that changes floors or prices. The
  page loads the plan once and does not reload.

## Prompt to start the next session

> This is the bgg-trade repo for the September 2026 US Math Trade, geeklist
> 383775. Read AGENTS.md and HANDOFF.md first. The want list is staged on the
> OLWLG but not submitted. Run `python3 olwlg.py verify` and tell me whether it
> still matches the plan.
