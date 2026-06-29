#!/usr/bin/env python3
"""VeggieToons competitor tracker — daily pull via Invidious (YT bot-block safe).

Pulls subs + best + latest upload for the tracked + emerging channels, saves a
dated JSON snapshot under data/tracker/, then regenerates tracker.html.

Run:  python3 tools/competitor_pull.py
Designed to be headless/cron-safe: it tries multiple Invidious instances and
degrades gracefully (keeps last-known values if an instance is flaky).
"""
import json, os, sys, time, urllib.request, datetime, html, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "data", "tracker")
os.makedirs(SNAP_DIR, exist_ok=True)

CHANNELS = [
    ("Dugu Baba TV",      "UCdLwcmuQrHo0l40d7HnMPkQ", "tracked"),
    ("Little Kids Hindi",  "UCvCHO3BETUu6PmZrae-T1jg", "tracked"),
    ("Bagu Baba TV",       "UCiTEJZ5IxYeWoygSaa_Majg", "tracked"),
    ("Apna Mini Gaon",     "UC3TZwPRd5cDwGoaIuCFYuZQ", "tracked"),
    ("Momo Toons",         "UCDOWGA4XsPmHFX3oopUOc_w", "tracked"),
    ("Funtoo Baba TV",     "UCuN8KlvqOiozVwhYcrVsuAA", "rival"),
    ("Sabji Toon TV",      "UC7VH5e2I11IW7f_NATDUjAA", "rival"),
    ("Zigloo Cartoons",    "UCAPmPlUz9RGrNYPzVwfzDmw", "rival"),
]

# Known-good instances first; the script also auto-discovers more.
SEED_INSTANCES = ["https://inv.zoomerville.com", "https://iv.melmac.space",
                  "https://invidious.nerdvpn.de", "https://yewtu.be"]

UA = {"User-Agent": "Mozilla/5.0 (compatible; VeggieToonsTracker/1.0)"}

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def discover_instances():
    insts = list(SEED_INSTANCES)
    try:
        data = get("https://api.invidious.io/instances.json?sort_by=type,users", 20)
        for name, info in data:
            uri = (info or {}).get("uri", "")
            if info.get("type") == "https" and uri and uri not in insts:
                insts.append(uri)
    except Exception as e:
        print("instance discovery failed:", e, file=sys.stderr)
    return insts

_LIVE = []  # validated instances, rotated through on failure

def validate_instances(insts):
    """Keep only instances whose channels endpoint actually returns real data
    (a /stats ping is not enough — instances rate-limit the channels API)."""
    probe = CHANNELS[0][1]
    live = []
    for base in insts:
        try:
            ch = get(f"{base}/api/v1/channels/{probe}", 15)
            if ch.get("subCount"):
                live.append(base)
                print("validated instance:", base, file=sys.stderr)
                if len(live) >= 3:
                    break
        except Exception:
            continue
        time.sleep(1.0)
    return live

def get_rotating(path):
    """GET path trying each live instance until one returns valid JSON."""
    last = None
    for base in list(_LIVE):
        try:
            return get(base + path)
        except Exception as e:
            last = e
            # demote a failing instance to the back of the queue
            if base in _LIVE and len(_LIVE) > 1:
                _LIVE.remove(base); _LIVE.append(base)
    raise last or RuntimeError("no live instance")

def pull_channel(base, ucid):
    out = {"subCount": None, "best": None, "latest": None}
    try:
        ch = get_rotating(f"/api/v1/channels/{ucid}")
        out["subCount"] = ch.get("subCount")
        out["author"] = ch.get("author")
    except Exception as e:
        print(f"  channel {ucid} failed: {e}", file=sys.stderr)
    time.sleep(2.5)
    try:
        pop = get_rotating(f"/api/v1/channels/{ucid}/videos?sort_by=popular")
        vids = pop.get("videos", pop if isinstance(pop, list) else [])
        if vids:
            b = max(vids, key=lambda v: v.get("viewCount") or 0)
            out["best"] = {"title": b.get("title"), "views": b.get("viewCount"),
                           "len": b.get("lengthSeconds"), "id": b.get("videoId")}
    except Exception as e:
        print(f"  popular {ucid} failed: {e}", file=sys.stderr)
    time.sleep(2.5)
    try:
        new = get_rotating(f"/api/v1/channels/{ucid}/videos?sort_by=newest")
        vids = new.get("videos", new if isinstance(new, list) else [])
        if vids:
            n = vids[0]
            out["latest"] = {"title": n.get("title"), "views": n.get("viewCount"),
                             "len": n.get("lengthSeconds"), "id": n.get("videoId"),
                             "published": n.get("publishedText")}
    except Exception as e:
        print(f"  newest {ucid} failed: {e}", file=sys.stderr)
    return out

def fmt_n(n):
    if n is None: return "—"
    n = int(n)
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(n)

def fmt_len(s):
    if not s: return "—"
    s = int(s); return f"{s//60}:{s%60:02d}"

def main():
    today = datetime.date.today().isoformat()
    global _LIVE
    _LIVE = validate_instances(discover_instances())
    if not _LIVE:
        print("No Invidious instance returning channel data — aborting (keeping previous snapshots).", file=sys.stderr)
        sys.exit(2)

    snap = {"date": today, "instances": list(_LIVE), "channels": {}}
    got = 0
    for name, ucid, role in CHANNELS:
        print("pulling", name, file=sys.stderr)
        res = pull_channel(None, ucid)
        if res.get("subCount"): got += 1
        snap["channels"][ucid] = {"name": name, "role": role, **res}
        time.sleep(2.0)
    snap["ok"] = got
    if got == 0:
        print("All channels returned empty — NOT overwriting; keeping previous snapshots.", file=sys.stderr)
        sys.exit(3)

    with open(os.path.join(SNAP_DIR, f"{today}.json"), "w") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print("saved snapshot", today, file=sys.stderr)
    render()

def render():
    snaps = []
    for p in sorted(glob.glob(os.path.join(SNAP_DIR, "*.json"))):
        try: snaps.append(json.load(open(p)))
        except Exception: pass
    if not snaps: return
    latest = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None

    rows = []
    for name, ucid, role in CHANNELS:
        c = latest["channels"].get(ucid, {})
        sub = c.get("subCount")
        delta = ""
        if prev:
            p = prev["channels"].get(ucid, {}).get("subCount")
            if p and sub:
                d = int(sub) - int(p)
                if d: delta = f'<span class="d {"up" if d>0 else "dn"}">{"+" if d>0 else ""}{fmt_n(abs(d)) if abs(d)>=1000 else d}</span>'
        best = c.get("best") or {}
        latest_v = c.get("latest") or {}
        badge = '<span class="badge win">tracked</span>' if role=="tracked" else '<span class="badge">rival</span>'
        lv_link = f'https://youtu.be/{latest_v.get("id")}' if latest_v.get("id") else "#"
        rows.append(f'''<tr>
<td><b>{html.escape(name)}</b><br>{badge}</td>
<td class="num">{fmt_n(sub)} {delta}</td>
<td class="num">{fmt_n(best.get("views"))}</td>
<td><a href="{lv_link}" target="_blank" rel="noopener" class="hi" style="font-size:13px">{html.escape((latest_v.get("title") or "—")[:70])}</a><br><span class="rank">{fmt_n(latest_v.get("views"))} views · {html.escape(latest_v.get("published") or "")}</span></td>
</tr>''')

    hist = " · ".join(s["date"] for s in snaps[-8:])
    page = f'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Live Competitor Tracker — VeggieToons</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/style.css">
<style>.d{{font-size:11px;font-weight:700;padding:1px 6px;border-radius:999px;margin-left:5px}}.d.up{{color:var(--leaf);background:rgba(91,208,122,.12)}}.d.dn{{color:var(--chili);background:rgba(255,90,90,.12)}}</style>
</head><body>
<nav class="toc"><div class="wrap"><a class="brand" href="index.html">🥔 Veg<span>Toon</span> Studio</a><a href="index.html#channels">Channels</a><a href="index.html#titleformula">🏆 Titles</a><a href="index.html#stories">Scripts</a><a href="tracker.html" style="color:var(--ink);background:var(--panel);border-color:var(--line2)">📊 Tracker</a></div></nav>
<header class="hero"><div class="wrap">
<span class="kicker">📊 Auto-updated · Invidious pull</span>
<h1>Live Competitor Tracker</h1>
<p class="lede">Latest snapshot <b>{latest["date"]}</b>. Sub-count deltas compare to the previous snapshot. "Latest upload" is each channel's newest video — your daily read on what the competition just shipped.</p>
</div></header>
<section><div class="wrap">
<div class="tbl-wrap"><table><thead><tr><th>Channel</th><th>Subs (Δ)</th><th>Best ever</th><th>Latest upload</th></tr></thead><tbody>
{''.join(rows)}
</tbody></table></div>
<p class="sub" style="margin-top:12px">Snapshots on file: {hist}</p>
</div></section>
<footer class="foot"><div class="wrap">VeggieToons — auto-generated by tools/competitor_pull.py</div></footer>
</body></html>'''
    with open(os.path.join(ROOT, "tracker.html"), "w") as f:
        f.write(page)
    print("rendered tracker.html", file=sys.stderr)

if __name__ == "__main__":
    if "--render-only" in sys.argv:
        render()
    else:
        main()
