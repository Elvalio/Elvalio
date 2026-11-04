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
DAYS = int(os.environ.get("LB_DAYS", "30"))
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
        if len(out) > 20000:
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


def render(theme, top, last, label):
    c = THEMES[theme]
    W, PAD, LH, CW, FS = 1000, 26, 30, 10.2, 17
    rows = max(len(top), 1)
    H = PAD * 2 + LH * (rows + 2) - 6
    y0 = PAD + 18
    track_x = PAD + CW * 4
    artist_x = PAD + CW * 42
    t = []

    def text(x, y, s, fill, bold=False, anchor="start", underline=False):
        attrs = f' font-weight="700"' if bold else ""
        attrs += f' text-anchor="{anchor}"' if anchor != "start" else ""
        attrs += ' text-decoration="underline"' if underline else ""
        t.append(f'<text x="{x:.1f}" y="{y}" fill="{fill}"{attrs}>{html.escape(s)}</text>')

    # prompt: ~/Elvalio ❯ listenbrainz top --tracks --month
    text(PAD, y0, "~/Elvalio", c["blue"], bold=True)
    px = PAD + CW * 10
    t.append(f'<path d="M{px+1:.1f} {y0-11} L{px+8:.1f} {y0-5.5} L{px+1:.1f} {y0}" fill="none" stroke="{c["green"]}" '
             f'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')
    text(PAD + CW * 12, y0, "listenbrainz", c["green"])
    text(PAD + CW * 25, y0, f"top --tracks {label}", c["text"])

    if not top:
        text(PAD, y0 + LH, "# no listens yet this month, press play", c["ov"])
    for i, ((track, artist), n) in enumerate(top):
        y = y0 + LH * (i + 1)
        text(PAD, y, f"{i+1:02d}", c["ranks"][i], bold=True)
        text(track_x, y, clip(track, 36), c["text"], bold=True)
        text(artist_x, y, clip(artist, 28), c["sub"])
        text(W - PAD, y, f"{n} play{'s' if n > 1 else ''}", c["ov"], anchor="end")

    if last:
        y = y0 + LH * (rows + 1)
        text(PAD, y, clip(f"# last played: {last[0]} — {last[1]}", 92), c["ov"])

    style = (font_face(400) + font_face(700) +
             f"text{{font-family:'JBM','JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
             f"font-size:{FS}px;white-space:pre}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
            f"<style>{style}</style>\n"
            f'<rect width="{W}" height="{H}" rx="10" fill="{c["base"]}"/>\n' + "\n".join(t) + "\n</svg>\n")


def main():
    since = int(time.time()) - DAYS * 86400
    listens = fetch_listens(since)
    counts, names = Counter(), {}
    for l in listens:
        m = l["track_metadata"]
        key = (m["track_name"].strip().casefold(), m["artist_name"].strip().casefold())
        counts[key] += 1
        names.setdefault(key, (m["track_name"].strip(), m["artist_name"].strip()))
    top = [(names[k], n) for k, n in counts.most_common(TOP)]
    last = None
    if listens:
        m = listens[0]["track_metadata"]
    else:
        recent = get(f"/user/{USER}/listens?count=1").get("payload", {}).get("listens", [])
        m = recent[0]["track_metadata"] if recent else None
    if m:
        last = (m["track_name"].strip(), m["artist_name"].strip())

    label = "--month" if DAYS == 30 else f"--{DAYS}d"
    for theme in THEMES:
        (ROOT / "assets" / f"music-{theme}.svg").write_text(render(theme, top, last, label), encoding="utf-8")
    print(f"{len(listens)} listens in the last {DAYS} days; top: {top}; last: {last}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo = [(("Bohemian Rhapsody", "Queen"), 14), (("夜に駆ける", "YOASOBI"), 11),
                (("Une chanson très très longue avec un titre interminable", "Un artiste au nom long"), 9),
                (("Get Lucky", "Daft Punk"), 6), (("Kids", "MGMT"), 1)]
        for theme in THEMES:
            (ROOT / "assets" / f"music-{theme}.svg").write_text(
                render(theme, demo, ("Kids", "MGMT"), "--month"), encoding="utf-8")
    else:
        main()
