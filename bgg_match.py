#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# Configuration. All of these are replaced in main() from .env / CLI flags;
# the values here are only placeholders so module-level imports work.
GEEKLIST_ID = ""
CACHE_DIR = ""
GAME_DETAILS_DIR = ""
USER_COLLECTION_FILE = ""
GEEKLIST_ITEMS_FILE = ""

def load_env():
    """Load variables from .env file if it exists."""
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    os.environ[key] = val

PREFS = {}

# Fallbacks so the tool still runs if preferences.toml is missing or partial.
DEFAULT_PREFS = {
    "profile": {"max_games": 80, "owned": 1.0, "wishlist": 3.0, "rating_min": 7.5,
                "plays_per_play": 0.25, "plays_cap": 3.0, "favorites": {}},
    "weights": {"mechanic_default": 0.2, "category_share": 0.4,
                "mechanic_share": 0.4, "designer_share": 0.2, "mechanics": {}},
    "gateway": {"enabled": False, "penalty": 1.0, "categories": [], "mechanics": [],
                "exceptional": {"min_rating": 7.0, "max_rank": 2500, "patterns": []}},
    "scoring": {"scale": 10.0, "avoidance_share": 0.25,
                "expansion_bonus": 3.0, "score_cap": 12.0},
    "candidates": {"min_bgg_rating": 6.0, "max_bgg_rank": 6000},
}


def _merge(base, override):
    """Recursive dict merge so a partial preferences.toml still works."""
    out = dict(base)
    for k, v in (override or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_preferences(path="preferences.toml"):
    """Load tunable taste settings. Everything the recommender believes lives here."""
    global PREFS
    PREFS = DEFAULT_PREFS
    if os.path.exists(path):
        try:
            import tomllib  # stdlib on Python 3.11+
        except ImportError:
            print(f"Warning: Python {sys.version_info.major}.{sys.version_info.minor} "
                  f"has no tomllib, so {path} is being ignored and built-in defaults "
                  f"are used. Python 3.11+ is needed to tune preferences.")
            return PREFS
        try:
            with open(path, "rb") as f:
                PREFS = _merge(DEFAULT_PREFS, tomllib.load(f))
            print(f"Loaded preferences from {path}")
        except Exception as e:
            print(f"Warning: could not read {path} ({e}); using built-in defaults.")
    else:
        print(f"Warning: {path} not found; using built-in defaults.")
    return PREFS


def get_auth_headers():
    """Build auth headers from .env: the GEEK_SESSION cookie first, BGA_TOKEN as the alternative."""
    geek_session = os.environ.get("GEEK_SESSION", "").strip()
    if geek_session:
        print("Using GEEK_SESSION for GeekAuth authentication.")
        return {"Authorization": f"GeekAuth {geek_session}"}

    bga_token = os.environ.get("BGA_TOKEN", "").strip()
    if bga_token:
        print("Using BGA_TOKEN for Bearer authentication.")
        return {"Authorization": f"Bearer {bga_token}"}

    print("Warning: No credentials found. Set GEEK_SESSION or BGA_TOKEN in .env (see .env.example).")
    return {}

def get_geeklist_title_from_items(items):
    """Try to extract a clean title from the items in the geeklist."""
    for item in items:
        href = item.get('href', '')
        if href:
            # Format: /geeklist/<id>/<slug>?itemid=<itemid>#<itemid>
            parts = [p for p in href.split('/') if p]
            if len(parts) >= 3:
                slug_part = parts[2]
                slug = slug_part.split('?')[0].split('#')[0]
                title = slug.replace('-', ' ').replace('_', ' ').strip().title()
                title = re.sub(r'\bUs\b', 'US', title)
                return title
    return f"Geeklist {GEEKLIST_ID}"

def get_bgg_user_id(username, auth_headers):
    """Resolve the BGG numeric user ID, preferring .env over the API.

    xmlapi2/user is locked down and returns 401 with or without credentials,
    so BGG_USER_ID is the reliable path. Without an ID the matcher cannot tell
    which listings are yours, and the games you are giving away quietly stay
    in your own preference profile.
    """
    configured = os.environ.get("BGG_USER_ID", "").strip()
    if configured:
        try:
            user_id = int(configured)
            print(f"Using BGG_USER_ID from .env for '{username}': {user_id}")
            return user_id
        except ValueError:
            print(f"Warning: BGG_USER_ID='{configured}' is not a number; falling back to the API.")

    url = f"https://boardgamegeek.com/xmlapi2/user?name={urllib.parse.quote(username)}"
    try:
        data_bytes, _ = make_bgg_request(url, headers=auth_headers)
        root = ET.fromstring(data_bytes)
        user_id = root.get("id")
        if user_id:
            print(f"Retrieved BGG User ID for '{username}': {user_id}")
            return int(user_id)
    except Exception as e:
        print(f"Warning: Could not retrieve user ID for {username}: {e}")
    return None

def get_offered_game_ids(geeklist, user_id):
    """Get the set of BGG object IDs for games the user is offering in this trade."""
    offered_ids = set()
    if not user_id:
        return offered_ids
        
    for item in geeklist:
        author_val = item.get('author')
        if author_val == user_id:
            bgg_id = item.get('item', {}).get('id')
            if bgg_id:
                offered_ids.add(bgg_id)
    return offered_ids

def make_bgg_request(url, headers=None, retries=3, delay=2):
    """Utility to make HTTP requests with retries and custom headers."""
    if headers is None:
        headers = {}
    
    # Set default user agent if not provided
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    req = urllib.request.Request(url, headers=headers)
    
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                status = response.status
                if status == 202:
                    # BGG Queueing response - wait and retry
                    print(f"  [BGG Queue] Received HTTP 202 (Accepted). Retrying in 5 seconds...")
                    time.sleep(5)
                    continue
                return response.read(), status
        except urllib.error.HTTPError as e:
            if e.code == 202:
                print(f"  [BGG Queue] Received HTTP 202. Retrying in 5 seconds...")
                time.sleep(5)
                continue
            print(f"  HTTP Error {e.code} on {url}: {e.reason}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise
        except Exception as e:
            print(f"  Error on {url}: {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise
    
    raise Exception(f"Failed to retrieve data from {url} after {retries} attempts (possibly queued).")

def download_collection(username, auth_headers, force=False):
    """Download the user's BGG collection XML, handling HTTP 202."""
    if not force and os.path.exists(USER_COLLECTION_FILE) and os.path.getsize(USER_COLLECTION_FILE) > 0:
        print(f"Using cached collection: {USER_COLLECTION_FILE}")
        return USER_COLLECTION_FILE
    
    print(f"Downloading collection for user '{username}'...")
    url = f"https://boardgamegeek.com/xmlapi2/collection?username={urllib.parse.quote(username)}&stats=1"
    headers = auth_headers.copy() if auth_headers else {}
        
    try:
        data, status = make_bgg_request(url, headers, retries=5)
        with open(USER_COLLECTION_FILE, 'wb') as f:
            f.write(data)
        print(f"Successfully saved collection to {USER_COLLECTION_FILE}")
        return USER_COLLECTION_FILE
    except Exception as e:
        print(f"Error downloading collection: {e}")
        if os.path.exists(USER_COLLECTION_FILE):
            print("Falling back to cached collection file.")
            return USER_COLLECTION_FILE
        raise

def parse_collection():
    """Parse user collection XML and extract wantlist and rating profile."""
    if not os.path.exists(USER_COLLECTION_FILE):
        raise FileNotFoundError(f"Collection file {USER_COLLECTION_FILE} not found. Please download it first.")
        
    tree = ET.parse(USER_COLLECTION_FILE)
    root = tree.getroot()
    
    collection = {}
    for item in root.findall('item'):
        objectid = item.get('objectid')
        name_elem = item.find('name')
        name = name_elem.text if name_elem is not None else "Unknown"
        
        status_elem = item.find('status')
        own = status_elem.get('own') == "1" if status_elem is not None else False
        prevowned = status_elem.get('prevowned') == "1" if status_elem is not None else False
        wishlist = status_elem.get('wishlist') == "1" if status_elem is not None else False
        want = status_elem.get('want') == "1" if status_elem is not None else False
        wanttoplay = status_elem.get('wanttoplay') == "1" if status_elem is not None else False
        wanttobuy = status_elem.get('wanttobuy') == "1" if status_elem is not None else False
        fortrade = status_elem.get('fortrade') == "1" if status_elem is not None else False
        wishlist_priority = int(status_elem.get('wishlistpriority', '0')) if status_elem is not None else 0
        
        rating = None
        stats_elem = item.find('stats')
        if stats_elem is not None:
            rating_elem = stats_elem.find('rating')
            if rating_elem is not None:
                val = rating_elem.get('value')
                if val and val != "N/A":
                    try:
                        rating = float(val)
                    except ValueError:
                        pass
        
        # Plays are the best evidence of what actually works at the table.
        numplays = 0
        plays_elem = item.find('numplays')
        if plays_elem is not None and plays_elem.text:
            try:
                numplays = int(plays_elem.text)
            except ValueError:
                pass

        collection[objectid] = {
            'name': name,
            'numplays': numplays,
            'own': own,
            'prevowned': prevowned,
            'wishlist': wishlist,
            'want': want,
            'wanttoplay': wanttoplay,
            'wanttobuy': wanttobuy,
            'fortrade': fortrade,
            'wishlist_priority': wishlist_priority,
            'rating': rating
        }
    
    return collection

def download_geeklist(geeklist_id, auth_headers, force=False):
    """Download geeklist items page by page and cache them."""
    if not force and os.path.exists(GEEKLIST_ITEMS_FILE):
        print(f"Using cached geeklist: {GEEKLIST_ITEMS_FILE}")
        with open(GEEKLIST_ITEMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    print(f"Downloading geeklist {geeklist_id}...")
    headers = auth_headers.copy() if auth_headers else {}
        
    all_items = []
    page = 1
    total_pages = 1
    
    while page <= total_pages:
        print(f"  Downloading page {page}...")
        url = f"https://api.geekdo.com/api/listitem?listid={geeklist_id}&page={page}"
        
        success = False
        for attempt in range(3):
            try:
                data_bytes, _ = make_bgg_request(url, headers)
                page_data = json.loads(data_bytes.decode('utf-8', errors='replace'))
                
                items = page_data.get('data', [])
                all_items.extend(items)
                
                pagination = page_data.get('pagination', {})
                total = pagination.get('total', 0)
                per_page = pagination.get('perPage', 25)
                if per_page > 0:
                    total_pages = (total + per_page - 1) // per_page
                
                print(f"    Fetched {len(items)} items. Total so far: {len(all_items)} / {total}")
                success = True
                break
            except Exception as e:
                print(f"    [Attempt {attempt+1}/3] Error downloading/parsing page {page}: {e}")
                time.sleep(2)
                
        if not success:
            # Do NOT save a truncated list over a good cache: a timeout on page 100
            # of 135 would silently shrink the trade list on every later run.
            print(f"Failed to download/parse page {page} after 3 attempts.")
            if os.path.exists(GEEKLIST_ITEMS_FILE):
                print("Keeping the existing cache rather than overwriting it with a partial download.")
                with open(GEEKLIST_ITEMS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            print("No existing cache; returning the partial download without saving it.")
            return all_items

        page += 1
        time.sleep(0.3)  # Be polite to BGG API

    if all_items:
        with open(GEEKLIST_ITEMS_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_items, f, indent=2, ensure_ascii=False)
        print(f"Successfully saved {len(all_items)} geeklist items to {GEEKLIST_ITEMS_FILE}")
    else:
        if os.path.exists(GEEKLIST_ITEMS_FILE):
            print("Failed to download geeklist, falling back to cached file.")
            with open(GEEKLIST_ITEMS_FILE, 'r', encoding='utf-8') as f:
                all_items = json.load(f)
                
    return all_items

def get_game_details(bgg_id, auth_headers=None):
    """Retrieve details for a specific game, utilizing the local cache first."""
    cache_path = os.path.join(GAME_DETAILS_DIR, f"{bgg_id}.json")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass # Re-fetch if corrupt
            
    # Fetch from BGG
    url = f"https://api.geekdo.com/api/geekitems?objectid={bgg_id}&objecttype=thing"
    try:
        data_bytes, status = make_bgg_request(url, headers=auth_headers, retries=2, delay=1)
        data = json.loads(data_bytes.decode('utf-8', errors='replace'))
        
        # Save to cache
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        time.sleep(0.2)  # Short pause to prevent rate limiting
        return data
    except Exception as e:
        print(f"  Failed to get details for game {bgg_id}: {e}")
        return None

def build_user_profile(collection, offered_game_ids, auth_headers=None):
    """Build a profile of the user's liked mechanics, categories, and designers, as well as disliked ones."""
    print("Building user preference profile...")
    
    p = PREFS['profile']
    favorites = p.get('favorites', {})

    # 1. Calculate positive weight for each game in the collection
    candidate_weights = {}
    for gid, info in collection.items():
        multiplier = 0.0

        is_offered = gid in offered_game_ids
        is_for_trade = info.get('fortrade', False)
        is_prevowned = info.get('prevowned', False)

        # A. Wishlist / Want / Want to Play / Want to Buy (Strongest signal)
        is_wanted = info.get('wishlist') or info.get('want') or info.get('wanttoplay') or info.get('wanttobuy')
        if is_wanted:
            prio = info.get('wishlist_priority', 0)
            prio_boost = max(0.5, (6 - prio) * 0.5) if prio > 0 else 1.0
            multiplier += p['wishlist'] * prio_boost

        # B. Rating signal. Skipped for games leaving in this trade: a game you
        # rated 8 but are trading away should not also define what you want.
        if info['rating'] is not None and not is_offered and not is_for_trade:
            if info['rating'] >= p['rating_min']:
                multiplier += max(1.0, (info['rating'] - 6.0) * 1.5)

        # C. Ownership signal (only if not offered in trade, not marked for trade, not prevowned)
        if info['own'] and not is_offered and not is_for_trade and not is_prevowned:
            multiplier += p['owned']

            # D. Plays. Without this, 133 owned games tie at exactly 1.0 and the
            # 80-game cut is decided by dict order, dropping Splendor (35 plays)
            # while keeping Bananagrams (0 plays).
            plays = info.get('numplays', 0)
            if plays > 0:
                multiplier += min(p['plays_cap'], plays * p['plays_per_play'])

        # E. Declared favorites override everything. Play count measures what is
        # easy to schedule, not what you love: Root and Terraforming Mars rank
        # #42 and #36 by plays.
        if gid in favorites:
            multiplier += float(favorites[gid])

        if multiplier > 0.0:
            candidate_weights[gid] = multiplier

    # Sort positive candidate IDs by multiplier descending
    sorted_candidates = sorted(candidate_weights.items(), key=lambda x: x[1], reverse=True)

    profile_ids = [x[0] for x in sorted_candidates[:p['max_games']]]

    print(f"  Selected {len(profile_ids)} representative games to build positive profile.")
    top_preview = [f"{collection[g]['name']} ({candidate_weights[g]:.1f})" for g in profile_ids[:6]]
    print(f"  Top of profile: {', '.join(top_preview)}")
    
    category_weights = {}
    mechanic_weights = {}
    designer_weights = {}
    user_games_data = {}

    # Hoisted out of the per-game loop; this table now lives in preferences.toml.
    mechanic_prefs = PREFS['weights'].get('mechanics', {})
    mechanic_default = PREFS['weights']['mechanic_default']

    for gid in profile_ids:
        details = get_game_details(gid, auth_headers)
        if not details or 'item' not in details:
            continue
            
        item = details['item']
        links = item.get('links', {})
        multiplier = candidate_weights[gid]
        
        info = collection[gid]
        user_games_data[gid] = {
            'name': info['name'],
            # "Similar to X" should only ever cite a game you own and have played.
            # Citing a wishlist game is circular: it recommends things like things
            # you already want.
            'owned_and_played': bool(info.get('own')) and info.get('numplays', 0) > 0,
            'numplays': info.get('numplays', 0),
            'categories': [cat['name'] for cat in links.get('boardgamecategory', [])],
            'mechanics': [mech['name'] for mech in links.get('boardgamemechanic', [])],
            'designers': [des['name'] for des in links.get('boardgamedesigner', [])]
        }

        for cat in links.get('boardgamecategory', []):
            name = cat['name']
            category_weights[name] = category_weights.get(name, 0) + multiplier

        for mech in links.get('boardgamemechanic', []):
            name = mech['name']
            pref_mult = mechanic_prefs.get(name, mechanic_default)
            mechanic_weights[name] = mechanic_weights.get(name, 0) + multiplier * pref_mult
            
        for des in links.get('boardgamedesigner', []):
            name = des['name']
            designer_weights[name] = designer_weights.get(name, 0) + multiplier
            
    # Normalize helper
    def normalize_dict(d):
        if not d:
            return {}
        max_val = max(d.values())
        return {k: v / max_val for k, v in d.items()}
        
    normalized_categories = normalize_dict(category_weights)
    normalized_mechanics = normalize_dict(mechanic_weights)
    normalized_designers = normalize_dict(designer_weights)
    
    # 2. Build negative profile from offered games and fortrade games
    print("Building user avoidance profile (from games offered in trade or marked 'for trade')...")
    negative_ids = list(dict.fromkeys(list(offered_game_ids) + [gid for gid, info in collection.items() if info.get('fortrade')]))
    
    # Cap negative profile to 30 games to keep execution fast
    negative_ids = negative_ids[:30]
    
    negative_categories = {}
    negative_mechanics = {}
    negative_designers = {}
    
    for gid in negative_ids:
        details = get_game_details(gid, auth_headers)
        if not details or 'item' not in details:
            continue
            
        item = details['item']
        links = item.get('links', {})
        
        # All negative games are weighted equally (1.0)
        for cat in links.get('boardgamecategory', []):
            name = cat['name']
            negative_categories[name] = negative_categories.get(name, 0) + 1.0
        for mech in links.get('boardgamemechanic', []):
            name = mech['name']
            negative_mechanics[name] = negative_mechanics.get(name, 0) + 1.0
        for des in links.get('boardgamedesigner', []):
            name = des['name']
            negative_designers[name] = negative_designers.get(name, 0) + 1.0
            
    normalized_neg_categories = normalize_dict(negative_categories)
    normalized_neg_mechanics = normalize_dict(negative_mechanics)
    normalized_neg_designers = normalize_dict(negative_designers)
    
    print(f"  Avoidance profile built: Tracked {len(normalized_neg_categories)} avoided categories, {len(normalized_neg_mechanics)} avoided mechanics.")
    
    return {
        'categories': normalized_categories,
        'mechanics': normalized_mechanics,
        'designers': normalized_designers,
        'negative_categories': normalized_neg_categories,
        'negative_mechanics': normalized_neg_mechanics,
        'negative_designers': normalized_neg_designers,
        'user_games_data': user_games_data
    }

def is_junior_kids_version(candidate_title, owned_titles):
    """Check if the candidate game is a junior/kids version of a game the user already owns."""
    def normalize(t):
        return re.sub(r'[^a-z0-9]', '', t.lower())
        
    cand_norm = normalize(candidate_title)
    
    # Common words indicating simplified/junior/kids versions of base games
    junior_keywords = ["junior", "kids", "myfirst", "firstjourney", "childrens", "forchildren", "toddler"]
    
    # Check if candidate name has any of the junior keywords
    has_junior_keyword = any(kw in cand_norm for kw in junior_keywords)
    if not has_junior_keyword:
        return False
        
    # Check if there is an owned game that is the parent game
    for owned in owned_titles:
        own_norm = normalize(owned)
        if len(own_norm) < 3:
            continue
            
        # 1. Candidate starts with owned (e.g., Catan -> Catan: Junior)
        if cand_norm.startswith(own_norm):
            return True
            
        # 2. Candidate ends with owned (e.g., Carcassonne -> My First Carcassonne)
        if cand_norm.endswith(own_norm):
            return True
            
        # 3. Stripping the junior keyword leaves the owned game
        for kw in junior_keywords:
            if kw in cand_norm:
                stripped = cand_norm.replace(kw, "")
                if stripped == own_norm or (len(stripped) >= 3 and (stripped.startswith(own_norm) or own_norm.startswith(stripped))):
                    return True
                    
    return False

def is_exceptional_edition(title, bgg_rating, bgg_rank):
    """True for a rare/premium printing or a Legacy variant worth an exception.

    A word match alone is not enough: "Deluxe Camping" (rank 17472) and
    "Halloween: Limited Edition Dice" both match on title only.
    """
    exc = PREFS['gateway'].get('exceptional', {})
    patterns = exc.get('patterns', [])
    if not any(re.search(pat, title, re.I) for pat in patterns):
        return False

    try:
        rank = int(bgg_rank)
    except (TypeError, ValueError):
        rank = 999999
    if rank <= 0:
        rank = 999999

    return (bgg_rating or 0) >= exc.get('min_rating', 7.0) or rank <= exc.get('max_rank', 2500)


def is_gateway_game(categories, mechanics):
    """True for family/party/dexterity fare, of which there is already enough.

    Detection is by category and mechanic, deliberately NOT by playtime:
    Splendor is a 30-minute game that is explicitly wanted, so a length
    rule would misfire on exactly the wrong games.
    """
    g = PREFS['gateway']
    if not g.get('enabled'):
        return False
    return (bool(set(categories) & set(g.get('categories', [])))
            or bool(set(mechanics) & set(g.get('mechanics', []))))


def match_geeklist(geeklist, collection, profile, auth_headers=None):
    """Match the geeklist items to the user profile and return recommendations."""
    print("Matching geeklist items to user preferences...")
    
    matched_results = []
    
    # Process unique boardgames in the geeklist to avoid repeated detail fetches
    unique_geeklist_games = {}
    for item in geeklist:
        bgg_id = item.get('item', {}).get('id')
        if not bgg_id:
            continue
        
        title = item.get('item', {}).get('name', 'Unknown')
        listitem_id = item.get('id')
        body = item.get('body', '')
        author = item.get('links', [{}])[2].get('uri', '').split('/')[-1] if len(item.get('links', [])) > 2 else 'Unknown'
        
        # BGG average rating and rank
        stats = item.get('stats') or {}
        bgg_rating = stats.get('average', 0.0) or 0.0
        bgg_rank = stats.get('rank', 999999) or 999999
        
        if bgg_id not in unique_geeklist_games:
            unique_geeklist_games[bgg_id] = {
                'id': bgg_id,
                'title': title,
                'bgg_rating': bgg_rating,
                'bgg_rank': bgg_rank,
                'trade_instances': []
            }
            
        unique_geeklist_games[bgg_id]['trade_instances'].append({
            'listitem_id': listitem_id,
            'author': author,
            'body': body,
            'href': f"https://boardgamegeek.com/geeklist/{GEEKLIST_ID}/item/{listitem_id}#{listitem_id}"
        })
        
    print(f"Found {len(unique_geeklist_games)} unique games in the geeklist.")
    
    # Filter candidates:
    # 1. We want games the user does NOT own (unless they are wishlist/wants).
    # 2. To avoid fetching details for all 1000+ unique games, we filter to:
    #    - Games explicitly on wishlist/want list
    #    - Games with BGG rating >= 6.8 AND BGG rank <= 2000 (candidates for recommendations)
    #    This ensures we only run API calls for high-quality recommendations.
    
    # Build list of owned game titles to check for junior versions
    owned_titles = [info['name'] for info in collection.values() if info['own']]
    
    candidates = []
    for gid, game in unique_geeklist_games.items():
        user_info = collection.get(gid)
        
        is_wishlist = False
        is_owned = False
        is_prevowned = False
        wishlist_prio = 0
        
        if user_info:
            is_owned = user_info['own']
            is_prevowned = user_info.get('prevowned', False)
            is_wishlist = user_info['wishlist'] or user_info['want'] or user_info['wanttoplay'] or user_info['wanttobuy']
            wishlist_prio = user_info['wishlist_priority']
            
        # Condition: Wishlist items are always candidates.
        # Owned or previously owned items are NOT candidates (unless wishlisted).
        # Recommend candidates must meet quality criteria.
        if is_wishlist:
            candidates.append((gid, game, "wishlist", wishlist_prio))
        elif is_owned or is_prevowned:
            # Skip owned or previously owned games
            continue
        else:
            # Potential recommendation candidate
            # Skip if it is a junior/kids version of a game they already own
            if is_junior_kids_version(game['title'], owned_titles):
                continue
                
            # Let's filter to ranks <= 2500 and rating >= 6.7 to avoid trash games
            rank_val = game['bgg_rank']
            if isinstance(rank_val, str):
                try:
                    rank_val = int(rank_val)
                except ValueError:
                    rank_val = 999999
                    
            if (game['bgg_rating'] >= PREFS['candidates']['min_bgg_rating']
                    and rank_val <= PREFS['candidates']['max_bgg_rank']):
                candidates.append((gid, game, "recommendation", 0))
                
    print(f"Filtered to {len(candidates)} candidate games to analyze details.")
    
    # Now fetch details for the candidate games (if not cached, this will download them)
    analyzed_count = 0
    start_time = time.time()
    
    for idx, (gid, game, match_type, wishlist_prio) in enumerate(candidates):
        # Print progress indicator periodically
        if idx % 20 == 0 and idx > 0:
            elapsed = time.time() - start_time
            rate = idx / elapsed
            rem = (len(candidates) - idx) / rate if rate > 0 else 0
            print(f"  Analyzing candidate details: {idx}/{len(candidates)} (Estimated time remaining: {int(rem)}s)...")
            
        details = get_game_details(gid, auth_headers)
        if not details or 'item' not in details:
            continue
            
        item = details['item']
        links = item.get('links', {})
        
        # Calculate similarity score based on profile
        cat_score = 0.0
        mech_score = 0.0
        des_score = 0.0
        
        game_cats = [c['name'] for c in links.get('boardgamecategory', [])]
        game_mechs = [m['name'] for m in links.get('boardgamemechanic', [])]
        game_des = [d['name'] for d in links.get('boardgamedesigner', [])]
        
        for cat in game_cats:
            cat_score += profile['categories'].get(cat, 0.0)

        # Pairing: mechanics flagged "meh by itself" only count fully when the
        # game also brings a core mechanic. Set Collection in an engine builder
        # is worth more than Set Collection in a bland filler.
        pair = PREFS.get('pairing', {})
        if pair.get('enabled'):
            supporting = set(pair.get('supporting', []))
            has_core = bool(set(game_mechs) & set(pair.get('core', [])))
            unpaired = pair.get('unpaired_factor', 0.4)
        else:
            supporting, has_core, unpaired = set(), True, 1.0

        for mech in game_mechs:
            value = profile['mechanics'].get(mech, 0.0)
            if not has_core and mech in supporting:
                value *= unpaired
            mech_score += value

        for des in game_des:
            des_score += profile['designers'].get(des, 0.0)
            
        # Normalize category/mechanic/designer components
        cat_comp = (cat_score / len(game_cats)) if game_cats else 0.0
        mech_comp = (mech_score / len(game_mechs)) if game_mechs else 0.0
        des_comp = max([profile['designers'].get(d, 0.0) for d in game_des]) if game_des else 0.0
        
        # Total similarity score (weighted average)
        # Designer match gets high weight if present, else category/mechanic
        w = PREFS['weights']
        similarity_score = ((cat_comp * w['category_share'])
                            + (mech_comp * w['mechanic_share'])
                            + (des_comp * w['designer_share']))
        similarity_score *= PREFS['scoring']['scale']
        
        # Calculate avoidance penalty
        neg_cat_score = 0.0
        neg_mech_score = 0.0
        neg_des_score = 0.0
        
        for cat in game_cats:
            neg_cat_score += profile.get('negative_categories', {}).get(cat, 0.0)
        for mech in game_mechs:
            neg_mech_score += profile.get('negative_mechanics', {}).get(mech, 0.0)
        for des in game_des:
            neg_des_score += profile.get('negative_designers', {}).get(des, 0.0)
            
        neg_cat_comp = (neg_cat_score / len(game_cats)) if game_cats else 0.0
        neg_mech_comp = (neg_mech_score / len(game_mechs)) if game_mechs else 0.0
        neg_des_comp = max([profile.get('negative_designers', {}).get(d, 0.0) for d in game_des]) if game_des else 0.0
        
        avoidance_score = ((neg_cat_comp * w['category_share'])
                           + (neg_mech_comp * w['mechanic_share'])
                           + (neg_des_comp * w['designer_share']))
        avoidance_score *= PREFS['scoring']['scale']

        # Penalize similarity score if it is a recommendation candidate (not explicit wishlist/want item)
        if match_type == "recommendation":
            similarity_score = max(
                0.0, similarity_score - (avoidance_score * PREFS['scoring']['avoidance_share']))

        # Find the most similar game in the user's collection.
        # Only games actually owned and played are eligible to be cited.
        best_similar_game = None
        best_overlap_score = -1

        for ugid, ugame in profile.get('user_games_data', {}).items():
            if not ugame.get('owned_and_played'):
                continue
            cat_overlap = set(game_cats) & set(ugame['categories'])
            mech_overlap = set(game_mechs) & set(ugame['mechanics'])
            des_overlap = set(game_des) & set(ugame['designers'])
            
            # Weighted overlap score
            overlap_score = len(cat_overlap) + len(mech_overlap) * 1.5 + len(des_overlap) * 3.0
            if overlap_score > best_overlap_score:
                best_overlap_score = overlap_score
                best_similar_game = ugame['name']
                
        # Find matching mechanics that user highly values
        matching_mechs = [m for m in game_mechs if m in profile['mechanics']]
        matching_mechs.sort(key=lambda x: profile['mechanics'].get(x, 0.0), reverse=True)
        
        # Build reason string
        reason_parts = []
        if best_similar_game and best_overlap_score > 1.5:
            reason_parts.append(f"Similar to *{best_similar_game}*")
        
        # Limit matching mechanics to the top 2
        valuable_mechs = [m for m in matching_mechs if profile['mechanics'].get(m, 0.0) >= 0.3]
        if valuable_mechs:
            reason_parts.append(f"features {', '.join(valuable_mechs[:2])}")
            
        reason = "; ".join(reason_parts) if reason_parts else "Matches your general style"
        
        # Check if it expands an owned game
        is_expansion_of_owned = False
        owned_base_games = []
        for parent in links.get('expandsboardgame', []):
            parent_id = parent['objectid']
            if parent_id in collection and collection[parent_id]['own']:
                is_expansion_of_owned = True
                owned_base_games.append(collection[parent_id]['name'])
                
        # Calculate final recommendation score
        # Boost score if it expands an owned game
        recommendation_score = similarity_score
        if is_expansion_of_owned:
            recommendation_score += PREFS['scoring']['expansion_bonus']

        # Add rating bonus (higher quality games get higher priority)
        rating_factor = max(0.5, (game['bgg_rating'] - 5.0) / 3.0) # multiplier
        final_score = recommendation_score * rating_factor

        # Gateway / family fare is a "no" by default, unless this particular
        # copy is an exceptional edition (anniversary, Legacy, deluxe, ...).
        flags = []

        # Mechanics you said to avoid. The strongest dislike wins rather than
        # stacking, so a game with three of them is not penalized three times.
        disliked = PREFS.get('dislikes', {}).get('mechanics', {})
        hits = {m: float(disliked[m]) for m in game_mechs if m in disliked}
        if hits:
            worst = min(hits, key=hits.get)
            final_score *= hits[worst]
            flags.append(f"disliked: {worst}")

        if not has_core and (supporting & set(game_mechs)):
            flags.append("supporting mechanics unpaired")

        gateway = is_gateway_game(game_cats, game_mechs)
        exceptional = is_exceptional_edition(game['title'], game['bgg_rating'], game['bgg_rank'])
        if exceptional:
            flags.append("exceptional edition")

        # Redoes something already on the shelf. Demoted, never filtered.
        reimp = PREFS.get('reimplementation', {})
        if reimp.get('enabled') and match_type == "recommendation":
            redone = []
            for link_type in reimp.get('link_types', []):
                for entry in links.get(link_type, []):
                    parent_id = str(entry.get('objectid'))
                    if parent_id in collection and collection[parent_id].get('own'):
                        redone.append(collection[parent_id]['name'])
            if redone:
                if exceptional and reimp.get('exempt_exceptional', True):
                    flags.append(f"reimplements {redone[0]}, exempt")
                else:
                    final_score *= reimp.get('penalty', 0.5)
                    flags.append(f"reimplements {redone[0]} (owned)")
        if gateway and match_type == "recommendation":
            if exceptional:
                flags.append("gateway penalty waived")
            else:
                final_score *= PREFS['gateway']['penalty']
                flags.append("gateway penalty")

        final_score = round(min(PREFS['scoring']['score_cap'], final_score), 2)

        matched_results.append({
            'id': gid,
            'title': game['title'],
            'match_type': match_type,
            'wishlist_priority': wishlist_prio,
            'bgg_rating': game['bgg_rating'],
            'bgg_rank': game['bgg_rank'],
            'similarity_score': round(similarity_score, 2),
            'final_score': final_score,
            'is_expansion': is_expansion_of_owned,
            'expands': owned_base_games,
            'trade_instances': game['trade_instances'],
            'genres': game_cats[:3],
            'mechanics': game_mechs[:3],
            'designers': game_des[:2],
            'reason': reason,
            'flags': flags
        })
        
    # Sort results
    # Priority 1: Wishlist/Wants (sorted by priority 1 -> 5, then final score)
    # Priority 2: Recommendations (sorted by final score descending)
    wishlist_results = [r for r in matched_results if r['match_type'] == "wishlist"]
    wishlist_results.sort(key=lambda x: (x['wishlist_priority'] if x['wishlist_priority'] > 0 else 99, -x['final_score']))
    
    recommendation_results = [r for r in matched_results if r['match_type'] == "recommendation"]
    recommendation_results.sort(key=lambda x: x['final_score'], reverse=True)
    
    return wishlist_results, recommendation_results

HTML_STYLE = """
:root { color-scheme: light dark; --fg:#1a1a1a; --bg:#fff; --muted:#666;
        --line:#e2e2e2; --head:#f6f6f6; --link:#0b62c4; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6e6e6; --bg:#161616; --muted:#9a9a9a;
          --line:#333; --head:#212121; --link:#6fb2ff; }
}
body { margin:0 auto; padding:2rem 1.25rem; max-width:1200px; color:var(--fg);
       background:var(--bg); font:15px/1.55 -apple-system, BlinkMacSystemFont,
       "Segoe UI", Helvetica, Arial, sans-serif; }
h1 { font-size:1.6rem; margin:0 0 .75rem; }
h2 { font-size:1.2rem; margin:2rem 0 .75rem; padding-bottom:.3rem;
     border-bottom:1px solid var(--line); }
a { color:var(--link); text-decoration:none; }
a:hover { text-decoration:underline; }
p { margin:.5rem 0; }
ul { margin:.5rem 0 .5rem 1.25rem; padding:0; }
em { color:var(--muted); }
.table-wrap { overflow-x:auto; margin:1rem 0; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { border:1px solid var(--line); padding:.45rem .6rem;
         text-align:left; vertical-align:top; }
th { background:var(--head); font-weight:600; white-space:nowrap; }
tr:nth-child(even) td { background:color-mix(in srgb, var(--head) 45%, transparent); }
"""


def _inline(text):
    """Convert the inline markdown the report uses: links, bold, italics, <br>."""
    out = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    out = out.replace("&lt;br&gt;", "<br>")  # the report emits literal <br>
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                 r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return out


def markdown_to_html(md, title):
    """Render the report's markdown subset to a standalone HTML page.

    Deliberately narrow: it handles only what generate_reports emits
    (headings, paragraphs, bullets, and pipe tables).
    """
    body = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("## "):
            body.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            body.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            body.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            # Row 1 is the header, row 2 is the :---: alignment separator.
            head, sep, data = rows[0], rows[1] if len(rows) > 1 else [], rows[2:]
            aligns = ["center" if c.startswith(":") and c.endswith(":")
                      else "right" if c.endswith(":") else "left" for c in sep]
            html = ["<div class='table-wrap'><table><thead><tr>"]
            for n, c in enumerate(head):
                a = aligns[n] if n < len(aligns) else "left"
                html.append(f"<th style='text-align:{a}'>{_inline(c)}</th>")
            html.append("</tr></thead><tbody>")
            for row in data:
                html.append("<tr>")
                for n, c in enumerate(row):
                    a = aligns[n] if n < len(aligns) else "left"
                    html.append(f"<td style='text-align:{a}'>{_inline(c)}</td>")
                html.append("</tr>")
            html.append("</tbody></table></div>")
            body.append("".join(html))
            continue
        else:
            body.append(f"<p>{_inline(stripped)}</p>")
        i += 1

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{_inline(title)}</title>\n"
        f"<style>{HTML_STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


def generate_reports(wishlist, recommendations, username, geeklist_title=None):
    """Write the matching report to markdown and to a standalone HTML page."""
    if not geeklist_title:
        geeklist_title = f"Geeklist {GEEKLIST_ID}"
    report_content = f"# BGG Math Trade Matching Report\n\n"
    report_content += f"**BGG User:** {username}  \n"
    report_content += f"**Math Trade List:** [{geeklist_title} (Geeklist {GEEKLIST_ID})](https://boardgamegeek.com/geeklist/{GEEKLIST_ID})  \n"
    report_content += f"**Generated on:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    report_content += "This report matches items from the Math Trade against your BoardGameGeek collection.\n"
    report_content += "- **Wishlist Matches** are items explicitly on your wishlist or want list.\n"
    report_content += "- **Recommendations** are other highly-rated games in the trade that match the mechanics, categories, and designers of games you highly rate or own.\n\n"
    
    # 1. Wishlist Matches Table
    report_content += "## 🎯 Wishlist & Want List Matches\n\n"
    if not wishlist:
        report_content += "*No wishlist matches found in this trade list.*\n\n"
    else:
        report_content += "| Game | Priority | BGG Rating | Trade Instances (Author & Item Link) |\n"
        report_content += "| :--- | :---: | :---: | :--- |\n"
        for r in wishlist:
            prio_str = f"Prio {r['wishlist_priority']}" if r['wishlist_priority'] > 0 else "Want"
            game_link = f"[{r['title']}](https://boardgamegeek.com/boardgame/{r['id']})"
            instances_str = ", ".join([f"[{inst['author']}]({inst['href']})" for inst in r['trade_instances']])
            report_content += f"| {game_link} | `{prio_str}` | {r['bgg_rating']} | {instances_str} |\n"
        report_content += "\n"
        
    # 2. Recommendations Table
    report_content += "## ✨ Recommended Games for You\n\n"
    report_content += "These are games in the trade that you do not own, sorted by recommendation score (calculated from similarity to your collection & BGG ratings).\n\n"
    
    if not recommendations:
        report_content += "*No recommendations found meeting the quality criteria.*\n\n"
    else:
        # Show top 100 recommendations
        top_recs = recommendations[:100]
        report_content += "| Score | Game | Why you'd like it | BGG Rating | Trade Instances |\n"
        report_content += "| :---: | :--- | :--- | :---: | :--- |\n"
        for r in top_recs:
            game_link = f"[{r['title']}](https://boardgamegeek.com/boardgame/{r['id']})"
            
            # Format reason
            reason = r['reason']
            if r['is_expansion']:
                reason = f"🔌 **Expansion of {', '.join(r['expands'])}**<br>" + reason
            if r.get('flags'):
                reason += f"<br>*{'; '.join(r['flags'])}*"
                
            instances_str = ", ".join([f"[{inst['author']}]({inst['href']})" for inst in r['trade_instances']])
            report_content += f"| **{r['final_score']}** | **{game_link}** | {reason} | {r['bgg_rating']} | {instances_str} |\n"
        report_content += "\n"
        
    local_report_path = "matching_report.md"
    with open(local_report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"Saved matching report: {local_report_path}")

    html_report_path = "matching_report.html"
    title = f"BGG Math Trade Matches - {geeklist_title}"
    with open(html_report_path, 'w', encoding='utf-8') as f:
        f.write(markdown_to_html(report_content, title))
    print(f"Saved matching report: {html_report_path}")

def main():
    global GEEKLIST_ID, CACHE_DIR, GAME_DETAILS_DIR, USER_COLLECTION_FILE, GEEKLIST_ITEMS_FILE
    
    # Load env variables (e.g. from .env file or environment)
    load_env()
    load_preferences()

    parser = argparse.ArgumentParser(description="Match BGG Math Trade items to user likes.")
    parser.add_argument("--username", default=os.environ.get("BGG_USERNAME"),
                        help="BGG Username (defaults to BGG_USERNAME in .env)")
    parser.add_argument("--geeklist", default=os.environ.get("GEEKLIST_ID"),
                        help="BGG Geeklist ID for the Math Trade (defaults to GEEKLIST_ID in .env)")
    parser.add_argument("--cache-dir", default=None, help="Custom cache directory")
    parser.add_argument("--refresh-collection", action="store_true", help="Force refresh of user collection")
    parser.add_argument("--refresh-geeklist", action="store_true", help="Force refresh of math trade geeklist items")
    args = parser.parse_args()
    
    if not args.geeklist:
        parser.error("No geeklist ID. Set GEEKLIST_ID in .env (see .env.example) or pass --geeklist.")
    if not args.username:
        parser.error("No BGG username. Set BGG_USERNAME in .env (see .env.example) or pass --username.")

    GEEKLIST_ID = args.geeklist
    CACHE_DIR = args.cache_dir or f"geeklist-{GEEKLIST_ID}"

    GAME_DETAILS_DIR = os.path.join(CACHE_DIR, "game_details")
    USER_COLLECTION_FILE = os.path.join(CACHE_DIR, "user_collection.xml")
    GEEKLIST_ITEMS_FILE = os.path.join(CACHE_DIR, "geeklist_items.json")
    
    os.makedirs(GAME_DETAILS_DIR, exist_ok=True)
    
    print("==================================================")
    print("BGG Math Trade Matching System")
    print("==================================================")
    
    auth_headers = get_auth_headers()
        
    try:
        # 1. Download/Load Collection
        download_collection(args.username, auth_headers, force=args.refresh_collection)
        collection = parse_collection()
        print(f"Loaded {len(collection)} items from BGG collection.")
        
        # 2. Download/Load Geeklist
        geeklist = download_geeklist(GEEKLIST_ID, auth_headers, force=args.refresh_geeklist)
        
        # Get BGG User ID and Offered Game IDs
        user_id = get_bgg_user_id(args.username, auth_headers)
        offered_game_ids = get_offered_game_ids(geeklist, user_id)
        if offered_game_ids:
            print(f"Identified {len(offered_game_ids)} games offered by you in this trade (to exclude/avoid).")
        
        # 3. Build Profile
        profile = build_user_profile(collection, offered_game_ids, auth_headers)
        
        # 4. Match Geeklist Items
        wishlist, recommendations = match_geeklist(geeklist, collection, profile, auth_headers)
        
        # Extract title from geeklist
        geeklist_title = get_geeklist_title_from_items(geeklist)
        
        # 5. Generate Reports
        generate_reports(wishlist, recommendations, args.username, geeklist_title)
        
        print("\nSuccessfully finished matching!")
        print(f"  - Wishlist matches: {len(wishlist)}")
        print(f"  - Top recommendations generated. See matching_report.md for details.")
        print("==================================================")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
