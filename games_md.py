"""Parser for games.md, the hand-maintained list of games you are offering.

Both tools read this file, so the parsing lives in one place:

* generate_curl_script.py turns it into add_games.sh, the geeklist importer.
* bgg_match.py reads the per-game money lines to floor what it will accept.

The recognized lines under a `## Title` heading are:

    - BGG Link: https://boardgamegeek.com/boardgame/194655/santorini
    - Value: 15         what the game itself is worth, before postage
    - Shipping: 12      what this particular box costs to mail
    - Floor: 35         the finished floor; postage is NOT added on top
    - Hold: reason      keep it in this file but out of the trade

Value and Floor are two different jobs. Value replaces the marketplace median
and still gets postage added, so it is the one to reach for when the market
median is simply wrong. Floor replaces the whole calculation and is the one to
reach for when you already know the number you want to see.
"""
import os
import re


def _money(text):
    """Read '35', '$35', '35.00' or '$35.00' as a float, else None.

    A trailing '# why this number' comment is stripped first. The reason a
    price was chosen is worth keeping next to the price, and markdown has
    nowhere else to put it.
    """
    text = (text or '').split('#', 1)[0].strip()
    match = re.match(r'\$?\s*(\d+(?:\.\d+)?)\s*$', text)
    return float(match.group(1)) if match else None


def parse_games(md_path):
    """Return one dict per `## Title` section that carries a BGG link."""
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

        # Everything before "### Description" is metadata about the game.
        # Everything after it is the body posted to BGG verbatim, and is never
        # read for metadata. Scanning the whole section used to mean a sentence
        # like "- Hold: the promo cards are missing" inside a description
        # quietly pulled the game out of the trade while reading as prose.
        head, description_lines, in_desc = [], [], False
        for line in lines[1:]:
            if line.strip().startswith('### Description'):
                in_desc = True
                continue
            (description_lines if in_desc else head).append(line)

        # Extract BGG ID and Link
        bgg_id = None
        bgg_link = None
        for line in head:
            match = re.search(r'https://boardgamegeek\.com/boardgame[a-z]*/(\d+)', line)
            if match:
                bgg_id = match.group(1)
                bgg_link = line.strip().replace('- BGG Link: ', '')
                break

        if not bgg_id:
            # Fallback for simpler links
            for line in head:
                match = re.search(r'boardgamegeek\.com/boardgame/(\d+)', line)
                if match:
                    bgg_id = match.group(1)
                    break

        # A "- Hold: reason" line keeps the game in this file but out of the trade.
        # The generated add_item stays commented out so a regenerate cannot re-list it.
        hold = None
        for line in head:
            match = re.match(r'-\s*Hold:\s*(.*)', line.strip(), flags=re.IGNORECASE)
            if match:
                hold = match.group(1).strip() or "on hold"
                break

        # A metadata line that ended up below the heading is almost always a
        # mistake, and it is one that fails silently. Say so rather than ignore it.
        for line in description_lines:
            match = re.match(r'-\s*(Hold|Value|Shipping|Floor)\s*:',
                             line.strip(), flags=re.IGNORECASE)
            if match:
                print(f"Warning: '{line.strip()}' sits below '### Description' for "
                      f"'{title}', so it is being posted as body text and ignored as "
                      f"metadata. Move it above the heading if you meant it to count.")

        # Money lines. Anything unparseable is reported and ignored, rather than
        # silently becoming a floor of zero.
        money = {'value': None, 'shipping': None, 'floor': None}
        for line in head:
            match = re.match(r'-\s*(Value|Shipping|Floor)\s*:\s*(.*)',
                             line.strip(), flags=re.IGNORECASE)
            if not match:
                continue
            key = match.group(1).lower()
            amount = _money(match.group(2))
            if amount is None:
                print(f"Warning: could not read '- {match.group(1)}: {match.group(2)}' "
                      f"for '{title}'; ignoring it.")
            else:
                money[key] = amount

        description = '\n'.join(description_lines).strip()

        if bgg_id:
            games.append({
                'title': title,
                'id': bgg_id,
                'link': bgg_link,
                'description': description,
                'hold': hold,
                'value': money['value'],
                'shipping': money['shipping'],
                'floor': money['floor'],
            })
        else:
            print(f"Warning: Could not find BGG ID for game '{title}'")

    return games


def index_by_id(md_path):
    """The same games, keyed by BGG id, for callers that look games up."""
    return {g['id']: g for g in parse_games(md_path)}
