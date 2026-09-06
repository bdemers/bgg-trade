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

# Configuration
CACHE_DIR = "june-2026-us-math-trade--379213"
GAME_DETAILS_DIR = os.path.join(CACHE_DIR, "game_details")
GEEKLIST_ID = "379213"
USER_COLLECTION_FILE = os.path.join(CACHE_DIR, "user_collection.xml")
GEEKLIST_ITEMS_FILE = os.path.join(CACHE_DIR, "geeklist_items.json")

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

def extract_geek_session():
    """Extract GeekSession cookie value from add_games.sh if it exists."""
    script_path = "add_games.sh"
    if os.path.exists(script_path):
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'GEEK_SESSION="([^"]*)"', content)
        if match:
            return match.group(1).strip()
    return ""

def get_auth_headers():
    """Determine the authentication headers to use based on env variables or add_games.sh."""
    bga_token = os.environ.get("BGA_TOKEN")
    if bga_token:
        print("Using BGA_TOKEN from environment/dotenv for Bearer authentication.")
        return {"Authorization": f"Bearer {bga_token}"}
        
    geek_session = extract_geek_session()
    if geek_session:
        print("Using GEEK_SESSION from add_games.sh for GeekAuth authentication.")
        return {"Authorization": f"GeekAuth {geek_session}"}
        
    print("Warning: No authentication credentials found (no BGA_TOKEN in env or GEEK_SESSION in add_games.sh).")
    return {}

def get_geeklist_title_from_items(items):
    """Try to extract a clean title from the items in the geeklist."""
    for item in items:
        href = item.get('href', '')
        if href:
            # Format: /geeklist/379213/june-2026-us-math-trade?itemid=12869765#12869765
            parts = [p for p in href.split('/') if p]
            if len(parts) >= 3:
                slug_part = parts[2]
                slug = slug_part.split('?')[0].split('#')[0]
                title = slug.replace('-', ' ').replace('_', ' ').strip().title()
                title = re.sub(r'\bUs\b', 'US', title)
                return title
    return f"Geeklist {GEEKLIST_ID}"

def get_bgg_user_id(username, auth_headers):
    """Retrieve the BGG numeric user ID for a username."""
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
        
        collection[objectid] = {
            'name': name,
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
            print(f"Failed to download/parse page {page} after 3 attempts. Stopping.")
            break
            
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
    
    # 1. Calculate positive weight for each game in the collection
    candidate_weights = {}
    for gid, info in collection.items():
        multiplier = 0.0
        
        # A. Wishlist / Want / Want to Play / Want to Buy (Strongest signal)
        is_wanted = info.get('wishlist') or info.get('want') or info.get('wanttoplay') or info.get('wanttobuy')
        if is_wanted:
            prio = info.get('wishlist_priority', 0)
            prio_boost = max(0.5, (6 - prio) * 0.5) if prio > 0 else 1.0
            multiplier += 3.0 * prio_boost
            
        # B. Rating signal
        if info['rating'] is not None:
            if info['rating'] >= 7.5:
                multiplier += max(1.0, (info['rating'] - 6.0) * 1.5)
            elif info['rating'] <= 5.5:
                # Poor ratings are ignored for positive profile
                pass
                
        # C. Ownership signal (only if not offered in trade, not marked for trade, not prevowned)
        is_offered = gid in offered_game_ids
        is_for_trade = info.get('fortrade', False)
        is_prevowned = info.get('prevowned', False)
        
        if info['own'] and not is_offered and not is_for_trade and not is_prevowned:
            multiplier += 1.0
            
        if multiplier > 0.0:
            candidate_weights[gid] = multiplier
            
    # Sort positive candidate IDs by multiplier descending
    sorted_candidates = sorted(candidate_weights.items(), key=lambda x: x[1], reverse=True)
    
    # Cap positive profile IDs to 80 to keep it efficient but rich
    profile_ids = [x[0] for x in sorted_candidates[:80]]
    
    print(f"  Selected {len(profile_ids)} representative games to build positive profile.")
    
    category_weights = {}
    mechanic_weights = {}
    designer_weights = {}
    user_games_data = {}
    
    for gid in profile_ids:
        details = get_game_details(gid, auth_headers)
        if not details or 'item' not in details:
            continue
            
        item = details['item']
        links = item.get('links', {})
        multiplier = candidate_weights[gid]
        
        user_games_data[gid] = {
            'name': collection[gid]['name'],
            'categories': [cat['name'] for cat in links.get('boardgamecategory', [])],
            'mechanics': [mech['name'] for mech in links.get('boardgamemechanic', [])],
            'designers': [des['name'] for des in links.get('boardgamedesigner', [])]
        }
            
        for cat in links.get('boardgamecategory', []):
            name = cat['name']
            category_weights[name] = category_weights.get(name, 0) + multiplier
            
        # Define user mechanic preferences (Tier-based weights)
        mechanic_prefs = {
            # Tier 1: Love (2.5x)
            "Variable Player Powers": 2.5,
            "Worker Placement": 2.5,
            "Scenario / Mission / Campaign Game": 2.5,
            # Tier 2: Like (1.5x)
            "Deck, Bag, and Pool Building": 1.5,
            "Pattern Building": 1.5,
            "Modular Board": 1.5,
            # Tier 3: Neutral/Accepted (1.0x)
            "Hand Management": 1.0,
            "Dice Rolling": 1.0,
            "Set Collection": 1.0,
            "Tile Placement": 1.0,
            "Variable Set-up": 1.0,
            "Area Movement": 1.0,
            "Hexagon Grid": 1.0
        }
        
        for mech in links.get('boardgamemechanic', []):
            name = mech['name']
            pref_mult = mechanic_prefs.get(name, 0.2) # Suppress unselected mechanics to 0.2x
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
                    
            # Widen candidate criteria to find more recommendations (~100)
            if game['bgg_rating'] >= 6.0 and rank_val <= 6000:
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
        for mech in game_mechs:
            mech_score += profile['mechanics'].get(mech, 0.0)
        for des in game_des:
            des_score += profile['designers'].get(des, 0.0)
            
        # Normalize category/mechanic/designer components
        cat_comp = (cat_score / len(game_cats)) if game_cats else 0.0
        mech_comp = (mech_score / len(game_mechs)) if game_mechs else 0.0
        des_comp = max([profile['designers'].get(d, 0.0) for d in game_des]) if game_des else 0.0
        
        # Total similarity score (weighted average)
        # Designer match gets high weight if present, else category/mechanic
        similarity_score = (cat_comp * 0.4) + (mech_comp * 0.4) + (des_comp * 0.2)
        similarity_score *= 10.0 # Scale to 10
        
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
        
        avoidance_score = (neg_cat_comp * 0.4) + (neg_mech_comp * 0.4) + (neg_des_comp * 0.2)
        avoidance_score *= 10.0
        
        # Penalize similarity score if it is a recommendation candidate (not explicit wishlist/want item)
        if match_type == "recommendation":
            similarity_score = max(0.0, similarity_score - (avoidance_score * 0.25))
        
        # Find the most similar game in the user's collection
        best_similar_game = None
        best_overlap_score = -1
        
        for ugid, ugame in profile.get('user_games_data', {}).items():
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
            recommendation_score += 3.0 # Big boost for expansions of owned games
            
        # Add rating bonus (higher quality games get higher priority)
        rating_factor = max(0.5, (game['bgg_rating'] - 5.0) / 3.0) # multiplier
        final_score = recommendation_score * rating_factor
        
        # Cap final score at 10.0 for recommendations, unless it has boosts
        final_score = round(min(12.0, final_score), 2)
        
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
            'reason': reason
        })
        
    # Sort results
    # Priority 1: Wishlist/Wants (sorted by priority 1 -> 5, then final score)
    # Priority 2: Recommendations (sorted by final score descending)
    wishlist_results = [r for r in matched_results if r['match_type'] == "wishlist"]
    wishlist_results.sort(key=lambda x: (x['wishlist_priority'] if x['wishlist_priority'] > 0 else 99, -x['final_score']))
    
    recommendation_results = [r for r in matched_results if r['match_type'] == "recommendation"]
    recommendation_results.sort(key=lambda x: x['final_score'], reverse=True)
    
    return wishlist_results, recommendation_results

def generate_reports(wishlist, recommendations, username, geeklist_title=None):
    """Write markdown matching reports to the workspace and the artifact directory."""
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
                
            instances_str = ", ".join([f"[{inst['author']}]({inst['href']})" for inst in r['trade_instances']])
            report_content += f"| **{r['final_score']}** | **{game_link}** | {reason} | {r['bgg_rating']} | {instances_str} |\n"
        report_content += "\n"
        
    # Write to local file
    local_report_path = "matching_report.md"
    with open(local_report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"Saved matching report to workspace: {local_report_path}")
    
    # Also write to artifact directory if running in Antigravity environment
    # Determine the conversation ID dynamically from the environment
    conversation_id = "fa6d65c1-cc17-40f0-8262-979c87035836" # default/fallback
    metadata_str = os.environ.get("ANTIGRAVITY_SOURCE_METADATA")
    if metadata_str:
        try:
            metadata = json.loads(metadata_str)
            cid = metadata.get("tool", {}).get("conversationId")
            if cid:
                conversation_id = cid
        except Exception:
            pass
            
    artifact_dir = f"/Users/bdemers/.gemini/antigravity-cli/brain/{conversation_id}"
    if os.path.exists(artifact_dir):
        artifact_path = os.path.join(artifact_dir, "matching_report.md")
        with open(artifact_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        print(f"Saved matching report to artifact directory: {artifact_path}")

def main():
    global GEEKLIST_ID, CACHE_DIR, GAME_DETAILS_DIR, USER_COLLECTION_FILE, GEEKLIST_ITEMS_FILE
    
    # Load env variables (e.g. from .env file or environment)
    load_env()
    
    parser = argparse.ArgumentParser(description="Match BGG Math Trade items to user likes.")
    parser.add_argument("--username", default="bdemers", help="BGG Username")
    parser.add_argument("--geeklist", default="379213", help="BGG Geeklist ID for the Math Trade")
    parser.add_argument("--cache-dir", default=None, help="Custom cache directory")
    parser.add_argument("--refresh-collection", action="store_true", help="Force refresh of user collection")
    parser.add_argument("--refresh-geeklist", action="store_true", help="Force refresh of math trade geeklist items")
    args = parser.parse_args()
    
    GEEKLIST_ID = args.geeklist
    if args.cache_dir:
        CACHE_DIR = args.cache_dir
    elif GEEKLIST_ID == "379213":
        CACHE_DIR = "june-2026-us-math-trade--379213"
    else:
        CACHE_DIR = f"geeklist-{GEEKLIST_ID}"
        
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
