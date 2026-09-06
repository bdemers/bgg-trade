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

Output report is generated as [matching_report.md](matching_report.md).

### 2. Importing Your Games to the Trade

1. Edit [games.md](games.md) with the list of games you wish to put up for trade.
2. Run `generate_curl_script.py` to update `add_games.sh`.
3. Set your BGG `GEEK_SESSION` cookie in `add_games.sh`.
4. Run `add_games.sh` to add the items to the BGG Geeklist.
