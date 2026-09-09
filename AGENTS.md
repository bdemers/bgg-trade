# Agent Handover Notes

Hello! If you are an AI assistant working on this repository, please review these notes on the project architecture and integration with BoardGameGeek APIs.

## Project Structure
* `bgg_match.py`: The core python script that runs the matching algorithm.
* `run.sh`: Shell wrapper for the python script (makes running matches easy).
* `games.md`: The hand-maintained list of games you are offering. Source of truth
  for the importer *and* for what each item is worth.
* `games_md.py`: The `games.md` parser. Shared: `generate_curl_script.py` needs
  the descriptions and holds, `bgg_match.py` needs the money lines. It used to
  live inside the generator; do not fork a second copy.
* `generate_curl_script.py`: Turns `games.md` into `add_games.sh`.
* `add_games.sh`: **Generated.** Posts each game to the geeklist. Never hand-edit it.
* `.env`: Credentials and the active geeklist ID. Gitignored (`.gitignore:6-8`).
* `.env.example`: The committed template. Keep it in sync when you add a key.
* `preferences.toml`: All taste tuning. Mechanic weights, declared favorites,
  gateway and edition rules. Committed as a worked example; users edit it.
* Cache directory, named after the geeklist:
  * `geeklist-<ID>/`, always. Gitignored via the `geeklist-*/` pattern.
    Override with `--cache-dir`.
  * `user_collection.xml`: Cached BGG user collection XML.
  * `geeklist_items.json`: Cache of geeklist listitems.
  * `game_details/`: Cached game details (categories, mechanics, designers) per BGG ID.
  * `prices.json`: Median USD marketplace price per BGG ID. See "Valuing a trade".
* `wants_plan.json`: **Generated.** The whole matrix, written next to the
  reports and gitignored like them. `my_items` carries the floors and the
  accepted candidate ids; `candidates` carries each game once, with `default`
  (what the floor rule said) and `accept` (what you ended up with) keyed by
  your item ids.
* `review.py` / `review.sh`: The matrix review page. Serves a clickable grid on
  127.0.0.1 and writes your decisions back into the repo.
* `matrix_overrides.json`: Your hand-set cells. **Committed**, because these are
  decisions rather than derived data. Only deviations from the floor rule are
  stored, so untouched cells keep following `games.md`. It records the geeklist
  it belongs to and is ignored, with a warning, against any other trade.

No cache directory exists in the working tree right now, so the next `./run.sh`
will do a full download before it can match anything.

## Configuration
Everything environment-specific lives in `.env`. There are exactly three keys
(`.env.example:5-14`):

* `GEEKLIST_ID`: the single source of truth for which math trade is active.
  `bgg_match.py` uses it as the default for `--geeklist` and refuses to run when
  neither is set (`bgg_match.py:811-819`). The generated `add_games.sh` exits 1
  without it (`add_games.sh:21-24`), and it is the only place the POST URL gets
  its list from (`add_games.sh:45`).
* `GEEK_SESSION`: the `GeekSession` cookie value from a logged-in browser.
* `BGA_TOKEN`: an optional bearer token, used only when `GEEK_SESSION` is empty.

The current trade is geeklist **383775, "September 2026 US Math Trade"**. The
previous one was 379213 (June 2026). Pointing both tools at a new trade is a
one-line edit to `.env`.

There used to be a `BEARER_TOKEN` key. It is gone. Do not reintroduce it.

## Authentication
Both tools now resolve auth identically, so there is only one rule to remember:

1. If `GEEK_SESSION` is set, send `Authorization: GeekAuth <value>`.
2. Otherwise, if `BGA_TOKEN` is set, send `Authorization: Bearer <value>`.
3. Otherwise fail.

See `bgg_match.py:34-47` and `add_games.sh:26-34`. `bgg_match.py` no longer
scrapes the cookie out of `add_games.sh`; the old `extract_geek_session()`
helper was deleted, and `add_games.sh` carries no credentials at all.

BGG locked down the XML APIs, so the collection endpoint needs these headers
even though the geeklist JSON endpoints do not.

## Session Expiry Is The Main Hazard
The `GeekSession` cookie is short-lived. Observed this session: a cookie that
posted successfully at 21:05 UTC was returning 401 roughly five hours later.

What an expired session looks like:

* **Every** endpoint 401s, including plain authenticated GETs. It is not
  specific to writes.
* The response body is empty, and the response carries `www-authenticate: GeekAuth`.
* 401 is all-or-nothing, so nothing is half-written. A run that dies mid-way has
  posted exactly the games it reported before the failure.

Practical advice: grab a fresh cookie immediately before a posting run, not the
night before. `add_games.sh` aborts with exit 1 on the first 401 rather than
grinding through the remaining games one five-second sleep at a time
(`add_games.sh:58-64`).

## BGG API Integration

**Collection (authenticated):**
`https://boardgamegeek.com/xmlapi2/collection?username=<user>&stats=1`
(`bgg_match.py:139`). Returns HTTP 202 while BGG builds the export; the request
helper sleeps 5s and retries (`bgg_match.py:107-116`).

**Geeklist items (public):**
`https://api.geekdo.com/api/listitem?listid=<ID>&page=<n>` (`bgg_match.py:222`).
This one cost real time to work out, so the shape is written down here:

* The query parameter is `page`, **not** `pageid`.
* The response is `{"data": [...], "pagination": {...}}`. The array key is
  `data`. There is no `listitems` key and no `items` key (`bgg_match.py:230`).
* `pagination` looks like `{"pageid": 1, "perPage": 25, "total": 3357}`. `total`
  is a **total item count, not a page count**. Compute pages as
  `ceil(total / perPage)` (`bgg_match.py:233-237`).
* It is public. It returns 200 with no `Authorization` header at all.
* Geeklist 383775 had 3357 items as of this session, so a full walk is roughly
  135 requests. That count is a live number and will have drifted; it cannot be
  re-checked from the repo.

**Single geeklist item (public):**
`https://api.geekdo.com/api/listitem/<itemid>`. When you already know the item
IDs, fetch them directly. It is far cheaper than paging the whole list.

**Game details (public):**
`https://api.geekdo.com/api/geekitems?objectid=<bgg_id>&objecttype=thing`
(`bgg_match.py:276`).

**Posting a list item (authenticated):**
`POST https://api.geekdo.com/api/geeklist/<GEEKLIST_ID>/listitem` returns
**201 Created** on success. The created object comes back under a `listitem`
key holding `id`, `listid`, and `item.name`. `add_games.sh` treats 201 and 200
as success and warns on anything else (`add_games.sh:65-67`).

**Marketplace prices (public):**
`https://api.geekdo.com/api/market/products?objectid=<bgg_id>&objecttype=thing&showcount=25`
(`bgg_match.py`, `fetch_market_price`). Worth writing down:

* It is **public**. No `Authorization` header, no cookie, unlike `xmlapi2`,
  which now 401s even for `thing`. This is the only price source that still
  answers, and `geekitems` carries no price data at all.
* `products[]` entries hold `price`, `currency`, `prettycondition`,
  `itemlocation`. `config.numitems` is the total listing count.
* Only USD listings are used. A median across mixed currencies is meaningless,
  and dropping the rest still leaves ~20 listings for most games.
* `showcount` caps the page. Every listing drags a full image set with it, so
  the default 50 is close to a megabyte per game. 25 halves that and moved the
  median by at most $2.50 on the games it was checked against.
* Responses are **chunked and sometimes truncate**, which surfaces as
  `json.JSONDecodeError: Expecting value: line 1 column 446034`. It is transient.
  The JSON parse therefore sits *inside* the retry loop, not after it. Thirteen
  of 170 games failed on the first build of this, and none did after the fix.

**Rate limiting:** keep a small sleep between calls to `api.geekdo.com` to avoid
Cloudflare challenges and 429s. The reader uses 0.3s between geeklist pages
(`bgg_match.py:251`) and 0.2s between detail fetches (`bgg_match.py:285`). The
importer waits a much more conservative 5s between posts (`add_games.sh:70`).

## games.md -> add_games.sh
`add_games.sh` is generated. Regenerate it with:

```bash
python3 generate_curl_script.py
```

`generate_curl_script.py` takes `--games` and `--output` only
(`generate_curl_script.py:192-195`). It deliberately has no `--geeklist` flag:
the list ID never appears in a payload, it only selects the POST URL, so it is
a runtime concern that belongs in `.env`.

### The money lines
`bgg_match.py` reads three optional lines per game, all parsed in `games_md.py`
and all ignored by the importer:

```markdown
## A Game of Thrones: The Board Game

- BGG Link: https://boardgamegeek.com/boardgame/103343/a-game-of-thrones-the-board-game-second-edition
- Value: 25       # replaces the marketplace median; shipping is still added
- Shipping: 15    # this box, not the trade.postage default
- Floor: 40       # replaces the whole sum; nothing is added on top
```

`$25`, `25` and `25.00` all parse, and a trailing `# why` comment is stripped.
Anything else prints a warning and is ignored, rather than quietly becoming a
floor of zero.

**Metadata is only read above `### Description`.** That boundary matters. The
parser used to scan the whole section, so a description containing a sentence
like `- Hold: the promo cards are missing` pulled the game out of the trade
while still reading as ordinary prose, and the same text was posted to BGG. It
is the same silent un-listing the `Hold` convention exists to prevent, with a
different cause. A metadata-looking line below the heading now prints a warning
naming the line and the game.

Markdown was kept over TOML deliberately. The description is not metadata, it
is the payload: it is POSTed to BGG verbatim, blank lines and BGG markup
included, and prose belongs in a prose format. TOML is the only real
alternative (`tomllib` is stdlib, `preferences.toml` already uses it) and would
delete most of this parser; it is worth revisiting if per-game metadata ever
grows past a handful of scalars. YAML is out: no stdlib parser, and the README
promises no third-party packages.

### The Hold convention
To keep a game in `games.md` but out of the trade, add a `Hold` line to its
section:

```markdown
## Monopoly: The Card Game

- BGG Link: https://boardgamegeek.com/boardgame/684/monopoly-the-card-game
- Hold: my wife still wants to try this one
```

The generator parses it (`generate_curl_script.py:44-51`) and emits the
`add_item` call commented out, preceded by an `# ON HOLD: <reason>` line
(`generate_curl_script.py:177-182`, rendered at `add_games.sh:126-131`).

One detail worth keeping in mind if you touch that code: descriptions are
multi-line, so the generated call spans several lines, and **every** line needs
its own `#`. Commenting only the first line leaves the rest as live shell and
breaks the script.

Before this convention existed, the only way to hold a game was to comment out
`add_games.sh` by hand, and the next regenerate silently threw that away. Two
games got un-held and posted that way. That is the bug the `Hold` line exists to
prevent, so route every hold through `games.md`.

## Matching Algorithm Notes
- **Preference profile:** each collection entry gets a weight from wishlist or
  want status, rating, and ownership, then the top 80 are fetched and their
  categories, mechanics, and designers are accumulated and normalized
  (`bgg_match.py:295-397`). Mechanics carry a hand-tuned preference table, and
  anything outside it is damped to 0.2x (`bgg_match.py:360-381`).
- **Avoidance profile:** games you are offering in this trade, plus anything
  marked `fortrade`, build a negative profile that penalizes recommendations
  (`bgg_match.py:399-433`, applied at `bgg_match.py:642-643`).
- **Wishlist matches** are always candidates and are reported first
  (`bgg_match.py:552-553`, `bgg_match.py:741`).
- **Recommendations** are drawn from trade items meeting BGG rating >= 6.0 and
  rank <= 6000 (`bgg_match.py:572`). Each gets a "Why you'd like it" note naming
  the closest game in your collection and the matching mechanics
  (`bgg_match.py:645-674`).
- Junior and kids editions of games you already own are filtered out
  (`bgg_match.py:445-481`).

## Valuing a Trade

`[trade]` in `preferences.toml` decides what you will accept for each item you
are offering:

```
floor = max(market price x ratio, absolute_min) + postage
```

The reasoning behind that shape, so nobody re-litigates it:

* **Postage is in the formula because you ship a box either way.** Trading a $20
  game for an $18 game and paying $10 to mail it is a loss, however much you
  like the $18 game. A `- Shipping:` line in `games.md` raises it for the heavy
  boxes; `trade.postage` is only the default.
* **`games.md` beats the marketplace wherever it has an opinion.** The median is
  a starting point, and you know your own copy better than it does. `- Value:`
  replaces the median and still gets shipping added. `- Floor:` replaces the
  whole sum and gets nothing added. Both exist on purpose: one is an input, the
  other is an answer. The report marks hand-set numbers with ✍️.
* **Price comes from the marketplace, not from a heuristic.** A tier function
  over BGG rank, rating, year and play time was built first and thrown away.
  Rank measures quality, not price: it put Pandemic at $40 and Santorini at $25
  when the marketplace says $18 and $15. Popular evergreen games are cheap
  because they are printed forever. Do not reintroduce rank as a price proxy.
* **Only the shortlist gets priced**, `price_top_n` recommendations plus every
  wishlist match plus your own items. The trade has thousands of items and
  almost none are candidates.
* **`accept_below_floor` is the escape hatch**, by BGG ID, for a game you want
  regardless of what it sells for. Keep it short. It exists because a wishlisted
  game can be genuinely cheap: House of Danger sells for $5.
* **An item with no USD listings** falls back to `unpriced_floor` rather than to
  postage alone, and the report flags it with ⚠️.

### The review page
`review.py` is deliberately dependency-free: `http.server` plus inlined CSS and
JavaScript, no build step and no CDN. It exists because the matrix is 161 games
by 9 items, and no CSV or markdown table is a reasonable place to make 1,449
decisions.

Two design points worth keeping:

* **Only deviations are stored.** A cell that agrees with the floor is deleted
  from `matrix_overrides.json` rather than written as `true`. That is what lets
  a change to a floor in `games.md` still move the untouched parts of the grid.
* **The page starts from the rule, not from blank.** An untouched list is
  already a valid want list, so the review is opt-in per row.
* **Confirmations carry a fingerprint of what they confirmed.** The signature is
  the row's default vector, `'1'`/`'0'` per item in `my_items` order, built
  identically in `review.py` (JS `sig()`) and `bgg_match.py`
  (`build_trade_plan`). If a price moves or a floor changes, the signature stops
  matching and the row is un-reviewed again. Keep those two in step.

The saved shape is:

```json
{"geeklist": "383775",
 "cells": {"<candidate id>": {"<my item id>": true}},
 "confirmed": {"<candidate id>": "110010011"}}
```

"Reviewed" means confirmed or edited. The report prints the coverage, so an
untouched list is visibly untouched rather than quietly assumed.

Order inside an accept set does not matter. This trade runs TradeMaximizer with
no priority scheme (`379213-officialwants.txt` lists `ALLOW-DUMMIES
REQUIRE-COLONS REQUIRE-USERNAMES HIDE-NONTRADES SHOW-ELAPSED-TIME ITERATIONS=75
SEED=20260621 METRIC=Users-Trading`, and TradeMaximizer defaults to no
priorities). So a want list is a **set, not a ranking**: everything you list is
equally likely, which is why the floor has to do the work.

## Known Rough Edges
- The geeklist item author is read by fixed index, `links[2]`
  (`bgg_match.py:499`). If BGG reorders that array the report will attribute
  items to the wrong user rather than fail loudly.
- `preferences.toml` weights are multipliers on what is already in your
  collection, not standalone scores. A high weight on a mechanic you own
  nothing of has no effect. See the `[weights.mechanics]` comments.
- `[reimplementation]` is present but disabled. It was tried and rejected:
  BGG's `reimplements` link conflates "reskin of a game you own" with
  "descendant design worth playing", and no cheap signal separated them.
