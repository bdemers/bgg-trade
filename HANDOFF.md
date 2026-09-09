# Handoff — September 2026 US Math Trade (geeklist 383775)

Written 2026-09-09. Delete this file once the trade is over.

## Where this is up to

The matcher, the valuation and the review page are all built and working. The
want list has not been submitted to the OLWLG, and the code to do that has not
been written.

* `games.md` carries a hand-set `- Floor:` line per game, reviewed one by one
  against the per-condition marketplace split on 2026-09-09.
* `matrix_overrides.json` is **deliberately empty**. A first pass through the
  review page was thrown away as too hasty; the real pass happens after the
  offering window closes.
* Everything else regenerates: `./run.sh` for the report and the plan,
  `./review.sh` for the matrix page.

## Dates that drive the rest of it

Read off the OLWLG on 2026-09-08, so re-check them rather than trusting them:

* **Sun 13 Sep 2026, 04:30 EDT** — offering window closes, no more items added.
* **Sun 20 Sep 2026, 03:30 EDT** — trade ends. Want lists must be in before this.

The want list submission window opens somewhere between those two, once the
organizer resyncs. The OLWLG home page shows an arrow icon against a trade whose
submission window is open.

## The plan for the next session

1. `./run.sh --refresh-geeklist` once the offering window has closed, so the
   candidate list covers everything that was added at the last minute.
2. `./run.sh --refresh-prices` if the last pricing run is more than a week old.
   Prices cache in `geeklist-383775/prices.json` and never expire on their own.
3. Walk `games.md` again if any floor now looks wrong.
4. `./review.sh`, filter to **not reviewed yet**, and work the queue. Wishlist
   rows first; they are the ones the floor is most likely to be wrong about.
5. Then build the OLWLG submitter. See "OLWLG: Submitting the Want List" in
   AGENTS.md for the endpoints, the two-post flow, and the one unknown that
   needs an authenticated page capture.

## Things that will bite

* `GEEK_SESSION` in `.env` expires within hours. Refresh it immediately before
  any run that talks to BGG, not the night before.
* The OLWLG login cookie is separate from `GEEK_SESSION` and arrives by geekmail.
* Restart `./review.sh` after any `./run.sh` that changes floors or prices. The
  page loads the plan once and does not reload.

## Prompt to start the next session

> This is the bgg-trade repo for the September 2026 US Math Trade, geeklist
> 383775. Read AGENTS.md and HANDOFF.md first. The offering window has closed,
> so refresh the geeklist and the prices, then walk me through any floors in
> games.md that now look wrong. After that I want to work through the review
> page, and then build the OLWLG want list submitter.
