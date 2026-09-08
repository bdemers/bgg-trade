# BGG Math Trade Helper

This repository contains tools for participating in BoardGameGeek (BGG) Math Trades, specifically optimized for importing games and matching trade lists against your personal preferences and wishlist.

## Features

1. **Trade List Matching (`bgg_match.py` / `run.sh`)**
   - Matches a math trade geeklist against your personal collection and wishlist.
   - Builds a preference profile based on your highly rated and owned games.
   - Generates a tailored recommendation report listing **Wishlist Matches** and **Similar Game Recommendations** (highlighting matching mechanics and why you'd like them).
   - Caches BGG game details locally to avoid rate-limiting and enable instant re-running.

2. **Geeklist Importer (`add_games.sh` / `generate_curl_script.py` / `games.md`)**
   - Automates uploading your own games to the BGG Math Trade Geeklist.

---

## Requirements

Python 3.11 or newer, for `tomllib`. No third-party packages; everything uses
the standard library, so there is nothing to `pip install`.

---

## Setup

### 1. Credentials and IDs

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored, so
credentials never land in a commit.

```properties
GEEKLIST_ID=383775      # the number in the geeklist URL
BGG_USERNAME=yourname   # your BGG account name
BGG_USER_ID=1234567     # your BGG numeric user ID
GEEK_SESSION=...        # GeekSession cookie value from your browser
BGA_TOKEN=              # optional bearer token, used only if GEEK_SESSION is empty
```

Both tools prefer `GEEK_SESSION` and fall back to `BGA_TOKEN`.

Two things that will bite you if you skip them:

* **`GEEK_SESSION` expires within hours.** Grab it right before a posting run,
  not in advance. `add_games.sh` aborts on the first 401 rather than failing
  every remaining game.
* **`BGG_USER_ID` is the numeric ID, not your username.** It is how the matcher
  recognizes your own listings and keeps the games you are giving away out of
  your taste profile. BGG's `xmlapi2/user` lookup returns 401 for everyone now,
  so this cannot be discovered automatically. Find it in the `author` field of
  any geeklist item you have posted.

### 2. Preferences

`preferences.toml` holds everything the recommender believes about your taste:
mechanic weights, the games you consider favorites, and rules for downranking
genres you have enough of. It ships with one person's settings as a worked
example, so **edit it before trusting the output**. Every section is commented.

Scoring is entirely local, so re-running after an edit takes about 15 seconds.

---

## Usage

### 1. Matching Trade List Games to Your Likes

A helper script `run.sh` is provided to run the matching tool:

* **Match using cached data (instant):**
  ```bash
  ./run.sh
  ```
* **Refresh Math Trade geeklist entries and match:**
  ```bash
  ./run.sh --refresh-geeklist
  ```
* **Refresh your collection data and match:**
  ```bash
  ./run.sh --refresh-collection
  ```
* **Refresh everything:**
  ```bash
  ./run.sh --refresh-collection --refresh-geeklist
  ```

Two reports are written on every run, with identical content. Both are
gitignored, since they are regenerated output:

* `matching_report.md` for reading in an editor.
* `matching_report.html`, a standalone page with styled tables and dark mode.
  Open it with `open matching_report.html`.

Cached BGG data lands in `geeklist-<ID>/`, also gitignored. A first run against
a busy trade fetches details for every candidate game and takes several minutes;
after that, re-running is instant.

### 2. Importing Your Games to the Trade

1. Edit [games.md](games.md) with the list of games you wish to put up for trade.
2. Run `python3 generate_curl_script.py` to regenerate `add_games.sh`.
3. Run `./add_games.sh` to post the items to the geeklist named by `GEEKLIST_ID`.

`add_games.sh` is generated, so do not hand-edit it. Anything you change there is
lost on the next regenerate.

To keep a game in `games.md` but out of the trade, add a `Hold` line to its section:

```markdown
## Monopoly: The Card Game

- BGG Link: https://boardgamegeek.com/boardgame/684/monopoly-the-card-game
- Hold: my wife still wants to try this one
```

Held games are emitted as commented-out `add_item` calls, so a regenerate cannot
silently put them back up for trade.
