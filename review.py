#!/usr/bin/env python3
"""Serve the trade matrix as a clickable page, and save decisions into the repo.

    python3 review.py            # opens http://127.0.0.1:8765 in your browser

The page starts from what the floor rule decided, so an untouched list is
already a valid want list. Every click is a deviation, and only deviations are
written to matrix_overrides.json, which means re-pricing a game or editing a
floor in games.md still moves the cells you never touched.

Everything is stdlib: http.server for the loop back into the repo, and no
JavaScript beyond what is inlined below. No build step, no dependency, no
copy-paste of a downloaded file.
"""
import os
import re
import json
import html
import argparse
import webbrowser
import http.server

PLAN_FILE = "wants_plan.json"
OVERRIDES_FILE = "matrix_overrides.json"

PAGE = None      # Rendered once at startup, from the plan.
OVERRIDES = {}   # {candidate_id: {my_item_id: bool}}
CONFIRMED = {}   # {candidate_id: signature of the suggestion you signed off on}


def short_labels(items):
    """Chip labels: distinct, short, and still recognizable.

    'Pandemic' and 'Pandemic: Hot Zone - North America' both reduce to
    'Pandemic', so collisions grow back toward the full title until they part.
    """
    labels = {}
    for item in items:
        base = item['title'].split(':')[0].strip()
        labels[item['id']] = base if len(base) <= 15 else base[:14] + "…"
    seen = {}
    for item in items:
        seen.setdefault(labels[item['id']], []).append(item['id'])
    for label, ids in seen.items():
        if len(ids) < 2:
            continue
        for gid in ids:
            title = next(i['title'] for i in items if i['id'] == gid)
            labels[gid] = title if len(title) <= 22 else title[:21] + "…"
    return labels


def thumbnail(bgg_id, cache_dir):
    path = os.path.join(cache_dir, "game_details", f"{bgg_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            images = (json.load(f).get('item') or {}).get('images') or {}
        return images.get('thumb') or images.get('micro')
    except Exception:
        return None


def build_payload(plan, cache_dir):
    items = [{'id': i['id'], 'title': i['title'], 'floor': i['floor']}
             for i in plan['my_items']]
    labels = short_labels(items)
    for item in items:
        item['label'] = labels[item['id']]

    candidates = []
    for c in plan['candidates']:
        candidates.append({
            'id': c['id'],
            'title': c['title'],
            'price': c['price'],
            'score': c['score'],
            'rating': round(float(c['bgg_rating'] or 0), 1),
            'wish': c['match_type'] == 'wishlist',
            'copies': c['copies'],
            'reason': re.sub(r'[*_]', '', c.get('reason') or ''),
            'thumb': thumbnail(c['id'], cache_dir),
            'default': c['default'],
        })
    return {'items': items, 'candidates': candidates,
            'geeklist': plan.get('geeklist', ''),
            'cells': OVERRIDES, 'confirmed': CONFIRMED}


def render(payload):
    data = json.dumps(payload).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", data).replace(
        "__GEEKLIST__", html.escape(str(payload['geeklist'])))


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="text/html; charset=utf-8"):
        raw = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE)
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path != "/save":
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get('Content-Length') or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception as e:
            self._send(400, json.dumps({'error': str(e)}), "application/json")
            return

        cells = {cid: {k: bool(v) for k, v in (row or {}).items()}
                 for cid, row in (payload.get('cells') or {}).items()}
        cells = {cid: row for cid, row in cells.items() if row}
        confirmed = {cid: str(s) for cid, s in (payload.get('confirmed') or {}).items() if s}
        saved = {
            'geeklist': payload.get('geeklist', ''),
            'note': "Written by review.py. 'cells' holds only deviations from the "
                    "floor rule; everything else follows games.md. 'confirmed' maps a "
                    "game to the suggestion you signed off on, so a changed floor "
                    "retires the confirmation instead of keeping a stale one.",
            'cells': cells,
            'confirmed': confirmed,
        }
        # Write via a temporary file so an interrupted save cannot leave a
        # half-written file where the matcher expects JSON.
        tmp = OVERRIDES_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(saved, f, indent=1, sort_keys=True)
        os.replace(tmp, OVERRIDES_FILE)
        total = sum(len(v) for v in cells.values())
        print(f"  saved {total} hand-set cells, {len(confirmed)} confirmed "
              f"to {OVERRIDES_FILE}")
        self._send(200, json.dumps({'ok': True, 'cells': total,
                                    'confirmed': len(confirmed)}), "application/json")

    def log_message(self, *args):
        pass  # The saves print themselves; the request log is noise.


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trade Matrix</title>
<style>
:root { color-scheme: light dark; --fg:#1a1a1a; --bg:#fff; --muted:#666;
        --line:#e2e2e2; --head:#f6f6f6; --link:#0b62c4; --on:#1a7f37;
        --onbg:#e7f5ec; --off:#8a8a8a; --offbg:#f2f2f2; --edit:#b8860b; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6e6e6; --bg:#161616; --muted:#9a9a9a; --line:#333;
          --head:#212121; --link:#6fb2ff; --on:#4ac26b; --onbg:#12301c;
          --off:#777; --offbg:#232323; --edit:#e3b341; }
}
* { box-sizing:border-box; }
body { margin:0; color:var(--fg); background:var(--bg);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
header { position:sticky; top:0; z-index:10; background:var(--head);
         border-bottom:1px solid var(--line); padding:.6rem .9rem; }
h1 { font-size:1rem; margin:0 0 .45rem; display:flex; gap:.6rem; align-items:baseline; flex-wrap:wrap; }
h1 small { font-weight:400; color:var(--muted); font-size:.82rem; }
#status { margin-left:auto; font-size:.8rem; color:var(--muted); }
#status.dirty { color:var(--edit); }
.controls { display:flex; gap:.9rem; align-items:center; flex-wrap:wrap; font-size:.85rem; }
.controls label { display:flex; gap:.3rem; align-items:center; color:var(--muted); }
input[type=search] { padding:.25rem .5rem; border:1px solid var(--line);
                     border-radius:5px; background:var(--bg); color:var(--fg); min-width:11rem; }
main { padding:.5rem .9rem 4rem; max-width:1250px; }
.row { display:grid; grid-template-columns:56px 1fr; gap:.7rem; padding:.6rem 0;
       border-bottom:1px solid var(--line); }
.row.sel { background:color-mix(in srgb, var(--head) 60%, transparent); }
.row img { width:56px; height:56px; object-fit:contain; border-radius:4px; background:var(--offbg); }
.t { font-weight:600; }
.t a { color:var(--link); text-decoration:none; }
.meta { color:var(--muted); font-size:.82rem; margin:.1rem 0 .35rem; }
.chips { display:flex; gap:.3rem; flex-wrap:wrap; align-items:center; }
.chip { border:1px solid var(--line); border-radius:999px; padding:.16rem .55rem;
        font-size:.78rem; cursor:pointer; user-select:none; white-space:nowrap;
        background:var(--offbg); color:var(--off); }
.chip.on { background:var(--onbg); color:var(--on); border-color:var(--on); font-weight:600; }
.chip.edited { box-shadow:inset 0 0 0 2px var(--edit); }
.chip .f { opacity:.65; font-weight:400; }
.bulk { font-size:.75rem; color:var(--muted); cursor:pointer; padding:.16rem .4rem;
        border:1px dashed var(--line); border-radius:5px; }
.ok-btn { font-size:.78rem; cursor:pointer; padding:.16rem .7rem; margin-left:.3rem;
          border:1px solid var(--on); color:var(--on); border-radius:5px;
          user-select:none; font-weight:600; }
.ok-btn.on { background:var(--on); color:var(--bg); }
.ok { font-size:.75rem; color:var(--on); font-weight:600; }
.row.done { opacity:.62; }
.row.done:hover, .row.sel { opacity:1; }
.wish { color:var(--edit); }
.legend { color:var(--muted); font-size:.78rem; margin:.3rem 0 0; }
.empty { padding:2rem .2rem; color:var(--muted); }
</style>
</head>
<body>
<header>
  <h1>Trade Matrix <small>geeklist __GEEKLIST__</small>
      <small id="counts"></small><span id="status">saved</span></h1>
  <div class="controls">
    <label>sort
      <select id="sort">
        <option value="score">score</option>
        <option value="price">price</option>
        <option value="title">name</option>
      </select>
    </label>
    <label><input type="checkbox" id="fwish"> wishlist only</label>
    <label><input type="checkbox" id="fedit"> my edits only</label>
    <label><input type="checkbox" id="ftodo"> not reviewed yet</label>
    <input type="search" id="q" placeholder="search games (/)">
  </div>
  <p class="legend">Click a chip to flip one cell. Drag across chips to set a run.
     Hit <b>ok</b> to confirm the suggestion as it stands.
     Keys: j/k move, space confirm and advance, 1-9 toggle, a all, n none, / search.</p>
</header>
<main><div id="list"></div></main>
<script>
const DATA = __DATA__;
const cells = DATA.cells || {};
const confirmed = DATA.confirmed || {};
const items = DATA.items;
let sel = 0, dragging = null, timer = null;

const eff = (c, iid) => {
  const row = cells[c.id];
  return (row && iid in row) ? row[iid] : c.default[iid];
};
const edited = (c, iid) => eff(c, iid) !== c.default[iid];
const anyEdited = c => items.some(i => edited(c, i.id));
const money = v => v == null ? "—" : "$" + (Number.isInteger(v) ? v : v.toFixed(2));

// A confirmation is only good for the suggestion it confirmed. Storing the
// suggestion's fingerprint means a re-priced game or a changed floor drops the
// row back into the queue instead of staying signed off against a stale answer.
const sig = c => items.map(i => c.default[i.id] ? '1' : '0').join('');
const isConfirmed = c => confirmed[c.id] === sig(c);
const reviewed = c => isConfirmed(c) || anyEdited(c);

function setCell(c, iid, val) {
  if (val === c.default[iid]) {                 // Back in line with the rule,
    if (cells[c.id]) {                          // so stop storing it at all.
      delete cells[c.id][iid];
      if (!Object.keys(cells[c.id]).length) delete cells[c.id];
    }
  } else {
    (cells[c.id] = cells[c.id] || {})[iid] = val;
  }
  save();
}

function setConfirmed(c, on) {
  if (on) confirmed[c.id] = sig(c); else delete confirmed[c.id];
  save();
}

function save() {
  const el = document.getElementById('status');
  el.textContent = 'saving…'; el.className = 'dirty';
  clearTimeout(timer);
  timer = setTimeout(() => {
    fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({geeklist: DATA.geeklist, cells, confirmed})})
      .then(r => r.json())
      .then(r => { el.textContent = 'saved'; el.className = ''; })
      .catch(() => { el.textContent = 'save failed, is review.py still running?';
                     el.className = 'dirty'; });
  }, 350);
  counts();
}

function counts() {
  const per = items.map(i => DATA.candidates.filter(c => eff(c, i.id)).length);
  const n = Object.values(cells).reduce((a, r) => a + Object.keys(r).length, 0);
  const done = DATA.candidates.filter(reviewed).length;
  document.getElementById('counts').textContent =
    done + ' of ' + DATA.candidates.length + ' reviewed · ' + n + ' hand-set cells · accepts ' +
    Math.min(...per) + '–' + Math.max(...per);
}

function visible() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const sort = document.getElementById('sort').value;
  let list = DATA.candidates.slice();
  if (document.getElementById('fwish').checked) list = list.filter(c => c.wish);
  if (document.getElementById('fedit').checked) list = list.filter(anyEdited);
  if (document.getElementById('ftodo').checked) list = list.filter(c => !reviewed(c));
  if (q) list = list.filter(c => c.title.toLowerCase().includes(q));
  list.sort(sort === 'price' ? (a, b) => (b.price ?? -1) - (a.price ?? -1)
          : sort === 'title' ? (a, b) => a.title.localeCompare(b.title)
          : (a, b) => (b.wish - a.wish) || (b.score - a.score));
  return list;
}

function render() {
  const list = visible();
  if (sel >= list.length) sel = Math.max(0, list.length - 1);
  const el = document.getElementById('list');
  if (!list.length) { el.innerHTML = '<p class="empty">Nothing matches those filters.</p>'; return; }
  el.innerHTML = list.map((c, n) => `
    <div class="row ${n === sel ? 'sel' : ''} ${reviewed(c) ? 'done' : ''}" data-id="${c.id}">
      <div>${c.thumb ? `<img loading="lazy" src="${c.thumb}" alt="">` : '<img alt="">'}</div>
      <div>
        <div class="t"><a href="https://boardgamegeek.com/boardgame/${c.id}" target="_blank"
           rel="noreferrer">${c.title}</a>${c.wish ? ' <span class="wish">🎯</span>' : ''}${
           isConfirmed(c) ? ' <span class="ok">✓ confirmed</span>'
           : anyEdited(c) ? ' <span class="ok">✍️ edited</span>' : ''}</div>
        <div class="meta">${money(c.price)} · score ${c.score} · BGG ${c.rating} ·
             ${c.copies} cop${c.copies === 1 ? 'y' : 'ies'}${c.reason ? ' · ' + c.reason : ''}</div>
        <div class="chips">
          ${items.map(i => `<span class="chip ${eff(c, i.id) ? 'on' : ''} ${edited(c, i.id) ? 'edited' : ''}"
              data-item="${i.id}" title="${i.title} — floor ${money(i.floor)}">${i.label}
              <span class="f">${money(i.floor)}</span></span>`).join('')}
          <span class="bulk" data-bulk="all">all</span><span class="bulk" data-bulk="none">none</span>
          <span class="ok-btn ${isConfirmed(c) ? 'on' : ''}" data-confirm="1"
                title="Confirm these suggestions as they stand">${isConfirmed(c) ? '✓ ok' : 'ok'}</span>
        </div>
      </div>
    </div>`).join('');
  counts();
}

const byId = id => DATA.candidates.find(c => c.id === id);

document.addEventListener('pointerdown', e => {
  const chip = e.target.closest('.chip');
  if (chip) {
    const c = byId(chip.closest('.row').dataset.id);
    dragging = !eff(c, chip.dataset.item);
    setCell(c, chip.dataset.item, dragging);
    render();
    e.preventDefault();
    return;
  }
  const bulk = e.target.closest('.bulk');
  if (bulk) {
    const c = byId(bulk.closest('.row').dataset.id);
    items.forEach(i => setCell(c, i.id, bulk.dataset.bulk === 'all'));
    render();
    return;
  }
  const ok = e.target.closest('.ok-btn');
  if (ok) {
    const c = byId(ok.closest('.row').dataset.id);
    setConfirmed(c, !isConfirmed(c));
    render();
  }
});
document.addEventListener('pointerover', e => {
  if (dragging === null) return;
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const c = byId(chip.closest('.row').dataset.id);
  if (eff(c, chip.dataset.item) !== dragging) { setCell(c, chip.dataset.item, dragging); render(); }
});
document.addEventListener('pointerup', () => { dragging = null; });

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  const list = visible();
  const c = list[sel];
  if (e.key === '/') { e.preventDefault(); document.getElementById('q').focus(); return; }
  if (e.key === 'j' || e.key === 'ArrowDown') { sel = Math.min(sel + 1, list.length - 1); }
  else if (e.key === 'k' || e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); }
  else if (c && (e.key === ' ' || e.key === 'c')) {
    setConfirmed(c, !isConfirmed(c));
    // Confirming means "done with this one", so move on. With the
    // "not reviewed yet" filter on, the row leaves the list and the next one
    // takes this index; without it, step forward.
    if (!document.getElementById('ftodo').checked) sel = Math.min(sel + 1, list.length - 1);
  }
  else if (c && e.key >= '1' && e.key <= '9' && items[+e.key - 1]) {
    const iid = items[+e.key - 1].id;
    setCell(c, iid, !eff(c, iid));
  }
  else if (c && e.key === 'a') { items.forEach(i => setCell(c, i.id, true)); }
  else if (c && e.key === 'n') { items.forEach(i => setCell(c, i.id, false)); }
  else return;
  e.preventDefault();
  render();
  document.querySelector('.row.sel')?.scrollIntoView({block:'nearest'});
});

['sort','fwish','fedit','ftodo','q'].forEach(id =>
  document.getElementById(id).addEventListener('input', () => { sel = 0; render(); }));
render();
</script>
</body>
</html>
"""


def main():
    global PAGE, OVERRIDES, CONFIRMED
    parser = argparse.ArgumentParser(description="Review and edit the trade matrix in a browser.")
    parser.add_argument("--plan", default=PLAN_FILE, help="Plan written by bgg_match.py")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    args = parser.parse_args()

    if not os.path.exists(args.plan):
        parser.error(f"{args.plan} not found. Run ./run.sh first to build the plan.")
    with open(args.plan, 'r', encoding='utf-8') as f:
        plan = json.load(f)

    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        OVERRIDES = saved.get('cells') or {}
        CONFIRMED = saved.get('confirmed') or {}

    cache_dir = os.environ.get("CACHE_DIR") or f"geeklist-{plan.get('geeklist', '')}"
    PAGE = render(build_payload(plan, cache_dir))

    url = f"http://127.0.0.1:{args.port}/"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Trade matrix: {len(plan['candidates'])} games x {len(plan['my_items'])} of yours")
    print(f"Serving {url}   (Ctrl-C to stop; edits save to {OVERRIDES_FILE} as you click)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Run ./run.sh to fold your edits into the report.")


if __name__ == "__main__":
    main()
