import re
import os
import json
import argparse

def parse_games(md_path):
    if not os.path.exists(md_path):
        print(f"Error: {md_path} not found.")
        return []

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by sections starting with ## (at the beginning of a line)
    sections = re.split(r'^##\s+', content, flags=re.MULTILINE)
    
    games = []
    # Skip sections[0] as it contains the main title `# Games for trade`
    for section in sections[1:]:
        lines = section.split('\n')
        if not lines:
            continue
        
        title = lines[0].strip()
        
        # Extract BGG ID and Link
        bgg_id = None
        bgg_link = None
        for line in lines:
            match = re.search(r'https://boardgamegeek\.com/boardgame[a-z]*/(\d+)', line)
            if match:
                bgg_id = match.group(1)
                bgg_link = line.strip().replace('- BGG Link: ', '')
                break
        
        if not bgg_id:
            # Fallback for simpler links
            for line in lines:
                match = re.search(r'boardgamegeek\.com/boardgame/(\d+)', line)
                if match:
                    bgg_id = match.group(1)
                    break
        
        # A "- Hold: reason" line keeps the game in this file but out of the trade.
        # The generated add_item stays commented out so a regenerate cannot re-list it.
        hold = None
        for line in lines:
            match = re.match(r'-\s*Hold:\s*(.*)', line.strip(), flags=re.IGNORECASE)
            if match:
                hold = match.group(1).strip() or "on hold"
                break

        # Extract description / comments
        description_lines = []
        in_desc = False
        for line in lines:
            if line.strip().startswith('### Description'):
                in_desc = True
                continue
            if in_desc:
                description_lines.append(line)
        
        description = '\n'.join(description_lines).strip()
        
        if bgg_id:
            games.append({
                'title': title,
                'id': bgg_id,
                'link': bgg_link,
                'description': description,
                'hold': hold
            })
        else:
            print(f"Warning: Could not find BGG ID for game '{title}'")
            
    return games

def generate_bash_script(games, output_path="add_games.sh"):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("#!/bin/bash\n")
        f.write("# shellcheck disable=SC2016\n\n")
        f.write("# ==========================================================================\n")
        f.write("# BGG Geeklist Math Trade Importer\n")
        f.write("# Generated from games.md by generate_curl_script.py -- do not edit by hand.\n")
        f.write("# Credentials and the geeklist ID live in .env, which is gitignored.\n")
        f.write("# See .env.example for the expected keys.\n")
        f.write("# ==========================================================================\n\n")

        f.write("# --- CONFIGURATION ---\n")
        f.write("# Work from the repo root so .env resolves no matter where this is invoked from.\n")
        f.write("cd \"$(dirname \"$0\")\" || exit 1\n\n")
        f.write("# Load environment variables from .env if it exists (same loader as run.sh)\n")
        f.write("if [ -f .env ]; then\n")
        f.write("  while IFS= read -r line || [ -n \"$line\" ]; do\n")
        f.write("    [[ \"$line\" =~ ^#.*$ ]] && continue\n")
        f.write("    [[ -z \"$line\" ]] && continue\n")
        f.write("    eval \"export $line\"\n")
        f.write("  done < .env\n")
        f.write("fi\n\n")

        f.write("if [ -z \"$GEEKLIST_ID\" ]; then\n")
        f.write("  echo \"Error: GEEKLIST_ID is not set. Add it to .env (see .env.example).\"\n")
        f.write("  exit 1\n")
        f.write("fi\n\n")

        f.write("# The GEEK_SESSION cookie is preferred; BGA_TOKEN is the bearer alternative.\n")
        f.write("if [ -n \"$GEEK_SESSION\" ]; then\n")
        f.write("  AUTH_HEADER=\"GeekAuth $GEEK_SESSION\"\n")
        f.write("elif [ -n \"$BGA_TOKEN\" ]; then\n")
        f.write("  AUTH_HEADER=\"Bearer $BGA_TOKEN\"\n")
        f.write("else\n")
        f.write("  echo \"Error: set GEEK_SESSION or BGA_TOKEN in .env (see .env.example).\"\n")
        f.write("  exit 1\n")
        f.write("fi\n\n")

        # Define the DRY helper function in the shell script
        f.write("# --- HELPER FUNCTION ---\n")
        f.write("add_item() {\n")
        f.write("  local title=\"$1\"\n")
        f.write("  local bgg_id=\"$2\"\n")
        f.write("  local comment=\"$3\"\n")
        f.write("  local json_payload=\"$4\"\n\n")
        f.write("  echo \"Adding: $title (BGG ID: $bgg_id)...\"\n")
        f.write("  local response\n")
        f.write("  response=$(curl -w \"\\nHTTP_STATUS:%{http_code}\" -s -X POST \"https://api.geekdo.com/api/geeklist/$GEEKLIST_ID/listitem\" \\\n")
        f.write("    -H \"Content-Type: application/json\" \\\n")
        f.write("    -H \"Authorization: $AUTH_HEADER\" \\\n")
        f.write("    -H \"User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36\" \\\n")
        f.write("    -H \"Accept: application/json, text/plain, *\\/*\" \\\n")
        f.write("    -H \"Origin: https://boardgamegeek.com\" \\\n")
        f.write("    -H \"Referer: https://boardgamegeek.com/\" \\\n")
        f.write("    -d \"$json_payload\")\n")
        f.write("  echo \"Response from server:\"\n")
        f.write("  echo \"$response\"\n\n")
        f.write("  local status\n")
        f.write("  status=$(echo \"$response\" | sed -n 's/^HTTP_STATUS://p' | tail -1)\n")
        f.write("  # Sessions expire mid-run, so stop immediately rather than failing every\n")
        f.write("  # remaining game one 5-second sleep at a time.\n")
        f.write("  if [ \"$status\" = \"401\" ]; then\n")
        f.write("    echo \"  ERROR: 401 Unauthorized. GEEK_SESSION has expired.\"\n")
        f.write("    echo \"  Refresh the cookie in .env, then re-run. Nothing was posted for this game.\"\n")
        f.write("    exit 1\n")
        f.write("  fi\n")
        f.write("  if [ \"$status\" != \"201\" ] && [ \"$status\" != \"200\" ]; then\n")
        f.write("    echo \"  WARNING: unexpected status $status for $title\"\n")
        f.write("  fi\n\n")
        f.write("  echo \"  Done. Waiting 5 seconds to comply with BGG rate limits...\"\n")
        f.write("  sleep 5\n")
        f.write("}\n\n")
        
        f.write("echo \"Starting import of games to BGG Geeklist $GEEKLIST_ID...\"\n\n")
        
        for game in games:
            title = game['title']
            bgg_id = game['id']
            description = game['description']
            
            # Escape single quotes for bash single-quoted arguments
            escaped_title = title.replace("'", "'\\''")
            escaped_desc = description.replace("'", "'\\''")
            
            # Generate JSON payload according to api.geekdo.com schema
            payload = {
                "item": {
                    "type": "thing",
                    "id": bgg_id
                },
                "imageid": None,
                "imageOverridden": False,
                "body": description,
                "rollsEnabled": False
            }
            json_payload = json.dumps(payload, ensure_ascii=False)
            escaped_json_payload = json_payload.replace("'", "'\\''")
            
            call = f"add_item '{escaped_title}' '{bgg_id}' '{escaped_desc}' '{escaped_json_payload}'"

            f.write(f"\n# Game: {title}\n")
            if game.get('hold'):
                # The call spans several lines because descriptions are multi-line,
                # so every one of them needs its own '#' to stay inert.
                f.write(f"# ON HOLD: {game['hold']}\n")
                for call_line in call.split('\n'):
                    f.write(f"# {call_line}\n")
            else:
                f.write(f"{call}\n")

        f.write("\necho \"All games processed.\"\n")

    held = sum(1 for g in games if g.get('hold'))
    print(f"Generated {output_path} successfully with {len(games) - held} games ({held} on hold).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate add_games.sh from games.md")
    parser.add_argument("--games", default="games.md", help="Markdown file listing the games for trade")
    parser.add_argument("--output", default="add_games.sh", help="Bash script to generate")
    args = parser.parse_args()

    games = parse_games(args.games)
    generate_bash_script(games, args.output)
