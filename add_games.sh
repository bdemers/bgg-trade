#!/bin/bash
# shellcheck disable=SC2016

# ==========================================================================
# BGG Geeklist Math Trade Importer
# Generated from games.md by generate_curl_script.py -- do not edit by hand.
# Credentials and the geeklist ID live in .env, which is gitignored.
# See .env.example for the expected keys.
# ==========================================================================

# --- CONFIGURATION ---
# Work from the repo root so .env resolves no matter where this is invoked from.
cd "$(dirname "$0")" || exit 1

# Load environment variables from .env if it exists (same loader as run.sh)
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    eval "export $line"
  done < .env
fi

if [ -z "$GEEKLIST_ID" ]; then
  echo "Error: GEEKLIST_ID is not set. Add it to .env (see .env.example)."
  exit 1
fi

# The GEEK_SESSION cookie is preferred; BGA_TOKEN is the bearer alternative.
if [ -n "$GEEK_SESSION" ]; then
  AUTH_HEADER="GeekAuth $GEEK_SESSION"
elif [ -n "$BGA_TOKEN" ]; then
  AUTH_HEADER="Bearer $BGA_TOKEN"
else
  echo "Error: set GEEK_SESSION or BGA_TOKEN in .env (see .env.example)."
  exit 1
fi

# --- HELPER FUNCTION ---
add_item() {
  local title="$1"
  local bgg_id="$2"
  local comment="$3"
  local json_payload="$4"

  echo "Adding: $title (BGG ID: $bgg_id)..."
  local response
  response=$(curl -w "\nHTTP_STATUS:%{http_code}" -s -X POST "https://api.geekdo.com/api/geeklist/$GEEKLIST_ID/listitem" \
    -H "Content-Type: application/json" \
    -H "Authorization: $AUTH_HEADER" \
    -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36" \
    -H "Accept: application/json, text/plain, *\/*" \
    -H "Origin: https://boardgamegeek.com" \
    -H "Referer: https://boardgamegeek.com/" \
    -d "$json_payload")
  echo "Response from server:"
  echo "$response"

  local status
  status=$(echo "$response" | sed -n 's/^HTTP_STATUS://p' | tail -1)
  # Sessions expire mid-run, so stop immediately rather than failing every
  # remaining game one 5-second sleep at a time.
  if [ "$status" = "401" ]; then
    echo "  ERROR: 401 Unauthorized. GEEK_SESSION has expired."
    echo "  Refresh the cookie in .env, then re-run. Nothing was posted for this game."
    exit 1
  fi
  if [ "$status" != "201" ] && [ "$status" != "200" ]; then
    echo "  WARNING: unexpected status $status for $title"
  fi

  echo "  Done. Waiting 5 seconds to comply with BGG rate limits..."
  sleep 5
}

echo "Starting import of games to BGG Geeklist $GEEKLIST_ID..."


# Game: Santorini
add_item 'Santorini' '194655' 'Excellent condition
First edition
Contains the Golden Fleece expansion
(non-smoking household)

Fun game! (It just doesn'\''t get to the table.)

Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "194655"}, "imageid": null, "imageOverridden": false, "body": "Excellent condition\nFirst edition\nContains the Golden Fleece expansion\n(non-smoking household)\n\nFun game! (It just doesn'\''t get to the table.)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

# Game: Pandemic
add_item 'Pandemic' '30549' 'New in Shrink
2013 version
(non-smoking household)

Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "30549"}, "imageid": null, "imageOverridden": false, "body": "New in Shrink\n2013 version\n(non-smoking household)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

# Game: 5-Minute Marvel
add_item '5-Minute Marvel' '253618' 'Like new
Played twice
(non-smoking household)

Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "253618"}, "imageid": null, "imageOverridden": false, "body": "Like new\nPlayed twice\n(non-smoking household)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

# Game: Pandemic: Hot Zone – North America
add_item 'Pandemic: Hot Zone – North America' '301919' 'New in Shrink
(non-smoking household)

Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "301919"}, "imageid": null, "imageOverridden": false, "body": "New in Shrink\n(non-smoking household)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

# Game: Moongha Invaders: Mad Scientists and Atomic Monsters Attack the Earth!
add_item 'Moongha Invaders: Mad Scientists and Atomic Monsters Attack the Earth!' '64826' 'New in Shrink
(non-smoking household)

Will cover first $10 outside of CONUS' '{"item": {"type": "thing", "id": "64826"}, "imageid": null, "imageOverridden": false, "body": "New in Shrink\n(non-smoking household)\n\nWill cover first $10 outside of CONUS", "rollsEnabled": false}'

# Game: Infinity Gauntlet: A Love Letter Game
add_item 'Infinity Gauntlet: A Love Letter Game' '304285' 'Like new!
Comes in the standard purple Marvel Infinity Gauntlet bag

(non-smoking household)

Will cover first $10 outside of CONUS' '{"item": {"type": "thing", "id": "304285"}, "imageid": null, "imageOverridden": false, "body": "Like new!\nComes in the standard purple Marvel Infinity Gauntlet bag\n\n(non-smoking household)\n\nWill cover first $10 outside of CONUS", "rollsEnabled": false}'

# Game: Rumble in the House
add_item 'Rumble in the House' '99437' 'New in Shrink
(non-smoking household)

Will cover first $10 outside of CONUS' '{"item": {"type": "thing", "id": "99437"}, "imageid": null, "imageOverridden": false, "body": "New in Shrink\n(non-smoking household)\n\nWill cover first $10 outside of CONUS", "rollsEnabled": false}'

# Game: Monopoly: The Card Game
# ON HOLD: my wife still wants to try this one
# add_item 'Monopoly: The Card Game' '684' 'Cards in Shrink
# (non-smoking household)
# 
# Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "684"}, "imageid": null, "imageOverridden": false, "body": "Cards in Shrink\n(non-smoking household)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

# Game: BattleCON: War of Indines
add_item 'BattleCON: War of Indines' '89409' 'New in Shrink
(non-smoking household)

Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "89409"}, "imageid": null, "imageOverridden": false, "body": "New in Shrink\n(non-smoking household)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

# Game: A Game of Thrones: The Board Game
add_item 'A Game of Thrones: The Board Game' '103343' 'Great condition, very minor shelf corner wear; the game was played a couple of times.

Great game, not getting played though.
(non-smoking household)

Will cover the first $10 outside of CONUS' '{"item": {"type": "thing", "id": "103343"}, "imageid": null, "imageOverridden": false, "body": "Great condition, very minor shelf corner wear; the game was played a couple of times.\n\nGreat game, not getting played though.\n(non-smoking household)\n\nWill cover the first $10 outside of CONUS", "rollsEnabled": false}'

echo "All games processed."
