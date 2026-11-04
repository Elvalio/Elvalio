"""Build the "top tracks" terminal card from ListenBrainz listens.

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
from pathlib import Path

USER = os.environ.get("LB_USER", "Elvalio")
WEEK_DAYS = 7
TOP = 5
API = "https://api.listenbrainz.org/1"
ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"

THEMES = {
    "dark": dict(base="#1e1e2e", text="#cdd6f4", sub="#a6adc8", ov="#6c7086", blue="#89b4fa", green="#a6e3a1",
                 ranks=["#cba6f7", "#f5c2e7", "#fab387", "#f9e2af", "#94e2d5"]),
    "light": dict(base="#eff1f5", text="#4c4f69", sub="#5c5f77", ov="#8c8fa1", blue="#1e66f5", green="#40a02b",
                  ranks=["#8839ef", "#ea76cb", "#fe640b", "#df8e1d", "#179299"]),
}


def get(path):
    req = urllib.request.Request(f"{API}{path}", headers={"User-Agent": "elvalio-profile-card"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(int(e.headers.get("X-RateLimit-Reset-In", "5")) + 1)
                continue
            raise
    return {}


def fetch_listens(since):
    """All listens newer than `since` (unix ts), newest first."""
    out, max_ts = [], None
    while True:
        q = f"/user/{USER}/listens?count=1000" + (f"&max_ts={max_ts}" if max_ts else "")
        batch = get(q).get("payload", {}).get("listens", [])
        if not batch:
            break
        for l in batch:
            if l["listened_at"] < since:
                return out
            out.append(l)
        max_ts = batch[-1]["listened_at"]
        if len(out) > 200000:
            break
    return out


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


def font_face(weight):
    data = base64.b64encode((FONTS / f"jetbrains-mono-latin-{weight}-normal.woff2").read_bytes()).decode()
    return (f"@font-face{{font-family:'JBM';font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")


def render(theme, sections, last):
    """sections: list of (flag, top) where top is [((track, artist), n), ...]."""
    c = THEMES[theme]
    W, PAD, LH, CW, FS = 1000, 26, 30, 10.2, 17
    lines = sum(1 + max(len(top), 1) for _, top in sections) + (len(sections) - 1) * 0.6 + (1 if last else 0)
    H = int(PAD * 2 + LH * lines - 6)
    track_x = PAD + CW * 4
    artist_x = PAD + CW * 42
    t = []

    def text(x, y, s, fill, bold=False, anchor="start"):
        attrs = ' font-weight="700"' if bold else ""
        attrs += f' text-anchor="{anchor}"' if anchor != "start" else ""
        t.append(f'<text x="{x:.1f}" y="{y:.0f}" fill="{fill}"{attrs}>{html.escape(s)}</text>')

    y = PAD + 18
    for si, (flag, top) in enumerate(sections):
        if si:
            y += LH * 0.6
        text(PAD, y, "~/Elvalio", c["blue"], bold=True)
        px = PAD + CW * 10
        t.append(f'<path d="M{px+1:.1f} {y-11:.0f} L{px+8:.1f} {y-5.5:.1f} L{px+1:.1f} {y:.0f}" fill="none" '
                 f'stroke="{c["green"]}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')
        text(PAD + CW * 12, y, "listenbrainz", c["green"])
        text(PAD + CW * 25, y, f"top --tracks {flag}", c["text"])
        if not top:
            y += LH
            text(PAD, y, "# nothing here yet, press play", c["ov"])
        for i, ((track, artist), n) in enumerate(top):
            y += LH
            text(PAD, y, f"{i+1:02d}", c["ranks"][i], bold=True)
            text(track_x, y, clip(track, 36), c["text"], bold=True)
            text(artist_x, y, clip(artist, 28), c["sub"])
            text(W - PAD, y, f"{n} play{'s' if n > 1 else ''}", c["ov"], anchor="end")
        y += LH
    if last:
        text(PAD, y, clip(f"# last played: {last[0]} \u2014 {last[1]}", 92), c["ov"])

    style = (font_face(400) + font_face(700) +
             f"text{{font-family:'JBM','JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
             f"font-size:{FS}px;white-space:pre}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
            f"<style>{style}</style>\n"
            f'<rect width="{W}" height="{H}" rx="10" fill="{c["base"]}"/>\n' + "\n".join(t) + "\n</svg>\n")


def top_of(listens):
    counts, names = Counter(), {}
    for l in listens:
        m = l["track_metadata"]
        key = (m["track_name"].strip().casefold(), m["artist_name"].strip().casefold())
        counts[key] += 1
        names.setdefault(key, (m["track_name"].strip(), m["artist_name"].strip()))
    return [(names[k], n) for k, n in counts.most_common(TOP)]


def main():
    listens = fetch_listens(0)  # whole history, newest first
    week_start = int(time.time()) - WEEK_DAYS * 86400
    week = [l for l in listens if l["listened_at"] >= week_start]
    sections = [("--all-time", top_of(listens)), ("--week", top_of(week))]
    last = None
    if listens:
        m = listens[0]["track_metadata"]
        last = (m["track_name"].strip(), m["artist_name"].strip())
    for theme in THEMES:
        (ROOT / "assets" / f"music-{theme}.svg").write_text(render(theme, sections, last), encoding="utf-8")
    print(f"{len(listens)} listens total, {len(week)} this week")
    for flag, top in sections:
        print(flag, top)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo = [(("Bohemian Rhapsody", "Queen"), 140), (("夜に駆ける", "YOASOBI"), 111),
                (("Une chanson très très longue avec un titre interminable", "Un artiste au nom long"), 90),
                (("Get Lucky", "Daft Punk"), 61), (("Kids", "MGMT"), 40)]
        for theme in THEMES:
            (ROOT / "assets" / f"music-{theme}.svg").write_text(
                render(theme, [("--all-time", demo), ("--week", demo[:3])], ("Kids", "MGMT")), encoding="utf-8")
    else:
        main()
