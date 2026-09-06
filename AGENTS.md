# Agent Handover Notes

Hello! If you are an AI assistant working on this repository, please review these notes on the project architecture and integration with BoardGameGeek APIs.

## Project Structure
* `bgg_match.py`: The core python script that runs the matching algorithm.
* `run.sh`: Shell wrapper for the python script (makes running matches easy).
* `june-2026-us-math-trade--379213/`: The local cache directory.
  * `user_collection.xml`: Cached BGG user collection XML.
  * `geeklist_items.json`: Cache of geeklist listitems.
  * `game_details/`: Subfolder containing cached game details (categories, mechanics, designers) for BGG IDs.

## BGG API Integration
BGG recently locked down their XML APIs, making authentication mandatory. The script works around this as follows:

1. **Authentication:**
   - Extracts the `GEEK_SESSION` cookie value from `add_games.sh`.
   - Passes it as `Authorization: GeekAuth <SESSION_TOKEN>` for XML API2 calls (e.g. collection).

2. **Endpoints Used:**
   - **Collection:** `https://boardgamegeek.com/xmlapi2/collection?username=bdemers&stats=1` (Authenticated via `GeekAuth`).
   - **Geeklist Items:** `https://api.geekdo.com/api/listitem?listid=379213&page=<page>` (Public, JSON, query parameter is `page` and NOT `pageid`).
   - **Game Details:** `https://api.geekdo.com/api/geekitems?objectid=<bgg_id>&objecttype=thing` (Public, JSON).

3. **Rate Limiting:**
   - Always keep a small sleep delay (0.2s - 0.3s) between calls to `api.geekdo.com` to prevent Cloudflare challenges or 429 rate limiting.

## Matching Algorithm Notes
- **User Preference Profile:** Built from the user's top-rated games (or owned games if rating is absent). Computes normalized weights for categories, mechanics, and designers.
- **Wants/Wishlist Match:** Direct BGG ID matches against user's BGG wishlist are automatically placed at the top of the report.
- **Recommendations:** Analyzes candidates in the math trade meeting quality criteria ($BGG \ge 6.0$, $rank \le 6,000$). For each candidate, it calculates a similarity score and finds the most similar game in the user's collection, providing a clear "Why you'd like it" note in the output.
