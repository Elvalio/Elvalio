"""Build the music dashboard (Hyprland-style tiling, 4 windows) from ListenBrainz listens.

Writes assets/music-dark.svg (Catppuccin Mocha) and assets/music-light.svg (Catppuccin Latte).
Stdlib only, so the GitHub Action needs no install step.
"""
import base64
import html
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

USER = os.environ.get("LB_USER", "Elvalio")
TZ = ZoneInfo(os.environ.get("LB_TZ", "Europe/Paris"))
TOP = 5
API = "https://api.listenbrainz.org/1"
ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
AVG_TRACK_MS = 3.4 * 60 * 1000  # used when a listen carries no duration

THEMES = {
    "dark": dict(crust="#11111b", base="#1e1e2e", s0="#313244", s1="#45475a", ov="#6c7086", text="#cdd6f4",
                 sub="#a6adc8", mauve="#cba6f7", blue="#89b4fa", green="#a6e3a1", peach="#fab387",
                 on_accent="#1e1e2e",
                 ranks=["#cba6f7", "#f5c2e7", "#fab387", "#f9e2af", "#94e2d5"],
                 heat=["#313244", "#4b3f63", "#7a5ea0", "#a983d6", "#cba6f7"]),
    "light": dict(crust="#dce0e8", base="#eff1f5", s0="#ccd0da", s1="#bcc0cc", ov="#8c8fa1", text="#4c4f69",
                  sub="#5c5f77", mauve="#8839ef", blue="#1e66f5", green="#40a02b", peach="#fe640b",
                  on_accent="#eff1f5",
                  ranks=["#8839ef", "#ea76cb", "#fe640b", "#df8e1d", "#179299"],
                  heat=["#ccd0da", "#d9c3f5", "#bb94f2", "#a067f0", "#8839ef"]),
}


# ---------------------------------------------------------------- data
def get(path):
    req = urllib.request.Request(f"{API}{path}", headers={"User-Agent": "elvalio-profile-card"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(int(e.headers.get("X-RateLimit-Reset-In", "5")) + 1)
                continue
            raise
    return {}


def fetch_listens():
    """Whole history, newest first."""
    out, max_ts = [], None
    while True:
        q = f"/user/{USER}/listens?count=1000" + (f"&max_ts={max_ts}" if max_ts else "")
        batch = get(q).get("payload", {}).get("listens", [])
        if not batch:
            break
        out.extend(batch)
        max_ts = batch[-1]["listened_at"]
        if len(out) > 300000:
            break
    return out


def norm(m):
    return m["track_name"].strip(), m["artist_name"].strip()


def top_tracks(listens):
    counts, names = Counter(), {}
    for l in listens:
        t, a = norm(l["track_metadata"])
        k = (t.casefold(), a.casefold())
        counts[k] += 1
        names.setdefault(k, (t, a))
    return [(names[k][0], names[k][1], n) for k, n in counts.most_common(TOP)]


def top_artists(listens):
    counts, names = Counter(), {}
    for l in listens:
        a = norm(l["track_metadata"])[1]
        counts[a.casefold()] += 1
        names.setdefault(a.casefold(), a)
    return [(names[k], n) for k, n in counts.most_common(TOP)]


def heatmap(listens):
    grid = [[0] * 24 for _ in range(7)]
    for l in listens:
        d = datetime.fromtimestamp(l["listened_at"], TZ)
        grid[d.weekday()][d.hour] += 1
    return grid


def hours_played(listens):
    ms, guessed = 0, False
    for l in listens:
        dur = (l["track_metadata"].get("additional_info") or {}).get("duration_ms")
        if isinstance(dur, (int, float)) and dur > 0:
            ms += dur
        else:
            ms += AVG_TRACK_MS
            guessed = True
    return round(ms / 3_600_000), guessed


# ---------------------------------------------------------------- drawing
def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def clip(s, cols):
    if width(s) <= cols:
        return s
    out = ""
    for c in s:
        if width(out + c) > cols - 1:
            break
        out += c
    return out.rstrip() + "…"


def fmt(n):
    return f"{n:,}".replace(",", " ")


def font_face(weight):
    data = base64.b64encode((FONTS / f"jetbrains-mono-latin-{weight}-normal.woff2").read_bytes()).decode()
    return (f"@font-face{{font-family:'JBM';font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")


FS, CW = 14, 8.4


class Canvas:
    def __init__(self):
        self.p = []

    def t(self, x, y, txt, fill, bold=False, anchor="start", size=FS):
        a = ' font-weight="700"' if bold else ""
        a += f' text-anchor="{anchor}"' if anchor != "start" else ""
        a += f' font-size="{size}"' if size != FS else ""
        self.p.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}"{a}>{html.escape(txt)}</text>')

    def r(self, x, y, w, h, fill, rx=0, extra=""):
        self.p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" {extra}/>')

    def raw(self, s):
        self.p.append(s)


def pane_tracks(c, th, x, y, w, rows):
    if not rows:
        c.t(x, y + 18, "# nothing here yet, press play", th["ov"])
    for i, (tr, ar, n) in enumerate(rows):
        yy = y + 18 + i * 28
        c.t(x, yy, f"{i+1:02d}", th["ranks"][i], bold=True)
        c.t(x + CW * 4, yy, clip(tr, 22), th["text"], bold=True)
        c.t(x + CW * 27, yy, clip(ar, 15), th["sub"])
        c.t(x + w, yy, fmt(n), th["ov"], anchor="end")


def pane_artists(c, th, x, y, w, rows):
    if not rows:
        c.t(x, y + 18, "# nothing here yet, press play", th["ov"])
        return
    mx = rows[0][1]
    bar_x, bar_w = x + CW * 22, w - CW * 22 - CW * 6
    for i, (a, n) in enumerate(rows):
        yy = y + 18 + i * 28
        c.t(x, yy, f"{i+1:02d}", th["ranks"][i], bold=True)
        c.t(x + CW * 4, yy, clip(a, 17), th["text"], bold=True)
        c.r(bar_x, yy - 10, bar_w, 9, th["s0"], rx=4.5)
        c.r(bar_x, yy - 10, max(9, bar_w * n / mx), 9, th["ranks"][i], rx=4.5)
        c.t(x + w, yy, fmt(n), th["ov"], anchor="end")


def pane_activity(c, th, x, y, w, grid, total, hours, guessed, week_n):
    cell, gap = (w - CW * 4) / 24, 2.5
    mx = max(max(r) for r in grid) or 1
    for d, lab in enumerate("MTWTFSS"):
        yy = y + 6 + d * cell
        c.t(x, yy + cell * 0.72, lab, th["ov"], size=12)
        for h in range(24):
            v = grid[d][h] / mx
            lvl = 0 if grid[d][h] == 0 else min(4, 1 + int(v ** 0.6 * 4))
            c.r(x + CW * 2 + h * cell, yy, cell - gap, cell - gap, th["heat"][lvl], rx=3)
    yb = y + 6 + 7 * cell + 16
    for h, lab in ((0, "0h"), (6, "6h"), (12, "12h"), (18, "18h")):
        c.t(x + CW * 2 + h * cell, yb, lab, th["ov"], size=11)
    yy = yb + 26
    stats = [(fmt(total), "listens", th["mauve"]), (("~" if guessed else "") + fmt(hours) + " h", "played", th["blue"]),
             (fmt(week_n), "this week", th["green"])]
    sx = x
    for v, lab, col in stats:
        c.t(sx, yy, v, col, bold=True)
        c.t(sx + CW * (len(v) + 1), yy, lab, th["sub"])
        sx += CW * (len(v) + len(lab) + 4)


def render(theme, d):
    th = THEMES[theme]
    W, H = 1000, 500
    c = Canvas()
    c.raw(f'<defs><linearGradient id="act" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{th["mauve"]}"/>'
          f'<stop offset="1" stop-color="{th["blue"]}"/></linearGradient>'
          f'<pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse">'
          f'<circle cx="8" cy="8" r="1.1" fill="{th["s0"]}"/></pattern></defs>')
    c.r(0, 0, W, H, th["crust"], rx=14)
    c.r(0, 0, W, H, "url(#dots)", rx=14)

    # waybar
    bar = 34
    c.r(10, 8, W - 20, bar - 6, th["base"], rx=9, extra=f'stroke="{th["s0"]}"')
    for i in range(4):
        active = i == 1
        c.r(18 + i * 30, 12, 24, 20, th["mauve"] if active else th["s0"], rx=6)
        c.t(30 + i * 30, 26.5, str(i + 1), th["on_accent"] if active else th["sub"], bold=active,
            anchor="middle", size=12)
    if d["last"]:
        c.t(W / 2, 26.5, clip(f"♫  last played · {d['last'][0]} — {d['last'][1]}", 52), th["text"],
            anchor="middle", size=13)
    c.t(W - 22, 26.5, f"listenbrainz  ·  {d['stamp']}", th["sub"], anchor="end", size=13)

    gap, top = 10, bar + 12
    ww, wh = (W - gap * 3) / 2, (H - top - gap * 2) / 2
    tint = [th["mauve"], th["green"], th["peach"], th["blue"]]
    panes = [
        ("top tracks", "--all-time", lambda x, y, w: pane_tracks(c, th, x, y, w, d["all"])),
        ("top tracks", "--week", lambda x, y, w: pane_tracks(c, th, x, y, w, d["week"])),
        ("top artists", "--all-time", lambda x, y, w: pane_artists(c, th, x, y, w, d["artists"])),
        ("activity", "--heatmap", lambda x, y, w: pane_activity(c, th, x, y, w, d["grid"], d["total"], d["hours"],
                                                                d["guessed"], d["week_n"])),
    ]
    ACTIVE = 1
    for k, (name, flag, fn) in enumerate(panes):
        x = gap + (k % 2) * (ww + gap)
        y = top + (k // 2) * (wh + gap)
        act = k == ACTIVE
        c.r(x, y, ww, wh, th["base"], rx=10,
            extra=f'stroke="{"url(#act)" if act else th["s1"]}" stroke-width="{2.5 if act else 1.5}"')
        c.r(x + 14, y + 12, 8, 8, tint[k], rx=2)
        c.t(x + 30, y + 21, name, tint[k], bold=True, size=13)
        c.t(x + 30 + 8.4 * (len(name) + 1), y + 21, flag, th["ov"], size=13)
        fn(x + 16, y + 30, ww - 32)

    style = (font_face(400) + font_face(700) +
             f"text{{font-family:'JBM','JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
             f"font-size:{FS}px;white-space:pre}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
            f"<style>{style}</style>\n" + "\n".join(c.p) + "\n</svg>\n")


def build(listens):
    now = time.time()
    week = [l for l in listens if l["listened_at"] >= now - 7 * 86400]
    hours, guessed = hours_played(listens)
    return dict(all=top_tracks(listens), week=top_tracks(week), artists=top_artists(listens), grid=heatmap(listens),
                total=len(listens), hours=hours, guessed=guessed, week_n=len(week),
                last=norm(listens[0]["track_metadata"]) if listens else None,
                stamp=datetime.now(TZ).strftime("%a %H:%M").lower())


def write(d):
    for theme in THEMES:
        (ROOT / "assets" / f"music-{theme}.svg").write_text(render(theme, d), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        import random
        random.seed(1)
        base = int(time.time())
        demo_tracks = [("Vizioz (Titre Bonus)", "Casseurs Flowters"), ("BELLE CHANSON", "HOUDI"), ("POOL", "Rusui"),
                       ("夜に駆ける", "YOASOBI"), ("Butterflies and Hurricanes", "Muse"), ("AKANIZER", "Laylow")]
        fake = [{"listened_at": base - random.randint(0, 90 * 86400),
                 "track_metadata": {"track_name": t, "artist_name": a, "additional_info": {}}}
                for t, a in random.choices(demo_tracks, k=900)]
        fake.sort(key=lambda l: -l["listened_at"])
        write(build(fake))
    else:
        listens = fetch_listens()
        d = build(listens)
        write(d)
        print(f"{d['total']} listens, {d['week_n']} this week, ~{d['hours']} h")
        for k in ("all", "week", "artists"):
            print(k, d[k])
