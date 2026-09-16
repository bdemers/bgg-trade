#!/usr/bin/env python3
"""Stage the want list on the OLWLG (bgg.activityclub.org), without submitting it.

    python3 olwlg.py plan      # print what would be sent; touches nothing
    python3 olwlg.py stage     # create dummies and save the wants on the OLWLG
    python3 olwlg.py verify    # compare what the OLWLG holds against the plan

The want list comes from wants_plan.json, so run ./run.sh first. There is
deliberately no submit command: staging saves your wants, and the "Submit My
Wants" button on the OLWLG stays a human click after you have checked them.

Duplicate protection: a game you would accept with more than one copy listed
gets a dummy item. Every copy is a want of the dummy, and the dummy is a want
of your real items, so the trade can hand you at most one copy.

Requests go through curl rather than urllib. The OLWLG server does not send
its Let's Encrypt intermediate certificate, which Python cannot verify but
macOS curl can, and certificate checks stay on either way.
"""
import os
import re
import sys
import json
import time
import argparse
import subprocess

from bgg_match import load_env

BASE = "https://bgg.activityclub.org/olwlg"
PLAN_FILE = "wants_plan.json"
PAUSE = 1.0  # One small volunteer-run server. Be gentle.


def curl(path, form=None, multipart=False):
    """GET, or POST `form` (a list of (name, value) pairs). Returns the body.

    The cookie goes in through a curl config on stdin, so it never shows up in
    the process list.
    """
    # Submitting is the "Submit My Wants" form, which alone carries md5 and
    # submit. Refuse both here, so no code path in this tool can submit.
    if any(name in ("submit", "md5") for name, _ in form or []):
        sys.exit("Refusing to submit. Click 'Submit My Wants' on the OLWLG yourself.")
    cookie = os.environ.get("OLWLG_BGGID", "").strip()
    if not cookie:
        sys.exit("No OLWLG_BGGID in .env. See .env.example.")
    cmd = ["curl", "-sS", "--compressed", "--fail-with-body", "-K", "-", f"{BASE}/{path}"]
    for name, value in form or []:
        if multipart:
            # --form-string: a value starting with @ or < is not a file.
            cmd += ["--form-string", f"{name}={value}"]
        else:
            cmd += ["--data-urlencode", f"{name}={value}"]
    config = f'cookie = "BGGID={cookie}"\n'
    result = subprocess.run(cmd, input=config.encode(), capture_output=True)
    if result.returncode != 0:
        sys.exit(f"curl failed on {path}: {result.stderr.decode().strip()}")
    body = result.stdout.decode("utf-8", "replace")
    if "Logged in as:" not in body and not body.lstrip().startswith("{"):
        sys.exit(f"Not logged in on {path}. Refresh OLWLG_BGGID in .env.")
    return body


def parse_items_page(page):
    """itemts per listitem, plus your own items and dummies, from a viewlist page."""
    # clickwant, not oneclickwant: the 1-click button vanishes once an item is
    # wanted, and the plain add button stays.
    itemts = dict(re.findall(r"(?<![a-z])clickwant\((\d+),(\d+),", page))
    mine, dummies = {}, {}
    # Each tmpobj block is pushed onto mygames or mydummies right after it is built.
    for block, target in re.findall(r"tmpobj = new Object\(\);(.*?)(mygames|mydummies)\.push\(tmpobj\)", page, re.S):
        fields = dict(re.findall(r'tmpobj\.(\w+) = "?(.*?)"?;', block))
        (mine if target == "mygames" else dummies)[fields["itemid"]] = fields
    return itemts, mine, dummies


def dummy_id(title, taken):
    """Short identifier: alphanumeric, at most 7 characters, at least one letter."""
    words = re.sub(r"^(the|a|an)\s+", "", title, flags=re.I)
    base = re.sub(r"[^A-Za-z0-9]", "", words).upper()[:7]
    candidate, n = base, 2
    while candidate in taken:
        candidate = base[:7 - len(str(n))] + str(n)
        n += 1
    return candidate


def build_stage(plan, geeklist, user_id):
    """Turn the accept sets into dummies and per-copy Step 3 wants."""
    # wants_plan.json keys your items by BGG game id; the OLWLG wants the
    # geeklist listitem id of each offering.
    listitem_of = {str(i["item"]["id"]): str(i["id"]) for i in geeklist
                   if i.get("author") == user_id}
    items = [dict(i, listitem=listitem_of[str(i["id"])]) for i in plan["my_items"]]

    stage = {"dummies": [], "wants": []}
    taken = set()
    for c in plan["candidates"]:
        givers = [i["listitem"] for i in items if c["accept"][i["id"]]]
        if not givers:
            continue
        copies = [str(x) for x in c["listitem_ids"]]
        if len(copies) > 1:
            short = dummy_id(c["title"], taken)
            taken.add(short)
            stage["dummies"].append({"short": short, "desc": c["title"][:29],
                                     "title": c["title"], "copies": copies, "givers": givers})
            for copy in copies:
                stage["wants"].append({"item": copy, "title": c["title"], "dummy": short})
        else:
            stage["wants"].append({"item": copies[0], "title": c["title"], "givers": givers})
    return items, stage


def print_stage(items, stage):
    name = {i["listitem"]: i["title"][:20] for i in items}
    print(f"{len(stage['dummies'])} dummies, {len(stage['wants'])} Step 3 wants\n")
    print("Dummies (duplicate protection):")
    for d in stage["dummies"]:
        print(f"  {d['short']:8} {d['title']}: {len(d['copies'])} copies, "
              f"wanted by {len(d['givers'])} of your items")
    print("\nSingle-copy wants:")
    for w in stage["wants"]:
        if "givers" in w:
            print(f"  {w['item']} {w['title']}: {', '.join(name[g] for g in w['givers'])}")


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Stage the want list on the OLWLG. Never submits.")
    parser.add_argument("command", choices=["plan", "stage", "verify"])
    parser.add_argument("--geeklist", default=os.environ.get("GEEKLIST_ID"))
    args = parser.parse_args()

    cache = f"geeklist-{args.geeklist}"
    plan = json.load(open(PLAN_FILE))
    if plan["geeklist"] != str(args.geeklist):
        sys.exit(f"{PLAN_FILE} is for geeklist {plan['geeklist']}, not {args.geeklist}.")
    geeklist = json.load(open(os.path.join(cache, "geeklist_items.json")))
    items, stage = build_stage(plan, geeklist, int(os.environ["BGG_USER_ID"]))

    if args.command == "plan":
        print_stage(items, stage)
        return

    listid = args.geeklist
    page_path = f"viewlist.cgi?listid={listid}&viewall=1"
    print("Reading the Step 3 list (full view, so the new-items marker is left alone)...")
    itemts, mine, dummies = parse_items_page(curl(page_path))
    missing = [w["item"] for w in stage["wants"] if w["item"] not in itemts]
    if missing:
        sys.exit(f"Not on the OLWLG list any more: {missing}. Re-run ./run.sh --refresh-geeklist.")
    if set(mine) != {i["listitem"] for i in items}:
        sys.exit(f"Your items on the OLWLG {sorted(mine)} do not match the plan.")

    if args.command == "stage":
        stage_dummies(listid, stage, dummies)
        itemts, mine, dummies = parse_items_page(curl(page_path))
        stage_wants(listid, stage, itemts, dummies)
        save_grid(listid, stage)

    verify(listid, stage)


def desired_cells(stage):
    """Every Step 4 grid cell the plan wants checked, as '<wanted>-<given>'.

    The grid's rows are what you receive and its columns what you give, and a
    dummy is both: a row wanted by your real items, and a column wanting copies.
    """
    cells = set()
    for d in stage["dummies"]:
        cells |= {f"{d['short']}-{g}" for g in d["givers"]}
    for w in stage["wants"]:
        givers = [w["dummy"]] if "dummy" in w else w["givers"]
        cells |= {f"{w['item']}-{g}" for g in givers}
    return cells


def read_grid(listid):
    """All grid cells and the checked ones, from the Step 4 page."""
    page = curl(f"mywants.cgi?listid={listid}")
    inputs = re.findall(r'<input[^>]*name="want"[^>]*>', page)
    cells = {re.search(r'value="([^"]+)"', i).group(1): bool(re.search(r"\bchecked\b", i))
             for i in inputs}
    return page, cells


def save_grid(listid, stage):
    """Post the complete want set with "Confirm Changes". It replaces, not merges."""
    want = desired_cells(stage)
    _, cells = read_grid(listid)
    absent = want - set(cells)
    if absent:
        sys.exit(f"The OLWLG grid has no cell for {sorted(absent)[:10]}; not saving a partial set.")
    form = [("listid", listid), ("modify", "1"), ("newstyle", "")]
    form += [("want", v) for v in sorted(want)]
    curl(f"mywants.cgi?listid={listid}", form)
    print(f"  saved {len(want)} grid cells (Confirm Changes)")


def verify(listid, stage):
    page, cells = read_grid(listid)
    want = desired_cells(stage)
    have = {v for v, checked in cells.items() if checked}
    print(f"OLWLG has {len(have)} cells checked; the plan wants {len(want)}.")
    for v in sorted(want - have):
        print(f"  missing: {v}")
    for v in sorted(have - want):
        print(f"  extra:   {v}")
    submitted = "have <b>not</b> yet submitted" not in page
    print("Matches the plan." if want == have else "Does NOT match the plan.")
    print("Submitted: yes" if submitted else "Submitted: no. Click 'Submit My Wants' when you are happy.")
    if want != have:
        sys.exit(1)


def dummy_listitem(short, dummies):
    # A dummy's itemid is its short identifier, as typed.
    return short if short in dummies else None


def stage_dummies(listid, stage, dummies):
    for d in stage["dummies"]:
        if dummy_listitem(d["short"], dummies):
            print(f"  dummy {d['short']} already exists")
            continue
        curl(f"mywants.cgi?listid={listid}", [("listid", listid), ("newstyle", ""),
             ("newdummy", d["short"]), ("newdummydesc", d["desc"])])
        print(f"  created dummy {d['short']} for {d['title']}")
        time.sleep(PAUSE)


def stage_wants(listid, stage, itemts, dummies):
    for w in stage["wants"]:
        if "dummy" in w:
            target = dummy_listitem(w["dummy"], dummies)
            if not target:
                sys.exit(f"Dummy {w['dummy']} was not found after creating it. Dummies seen: {dummies}")
            real, pseudo = [], [target]
        else:
            real, pseudo = w["givers"], []
        form = [("version", "3"), ("item", w["item"]), ("itemts", itemts[w["item"]]),
                ("listid", listid)]
        form += [("mine", m) for m in real] + [("stophere", "")]
        form += [("mine", m) for m in pseudo] + [("ivalue", "")]
        body = curl("modifywants.cgi", form, multipart=True)
        res = json.loads(body)
        if res.get("error"):
            sys.exit(f"OLWLG refused {w['title']} ({w['item']}): {res['error']}")
        print(f"  {w['title']} ({w['item']}) -> {w.get('dummy') or len(real)}")
        time.sleep(PAUSE)


if __name__ == "__main__":
    main()
