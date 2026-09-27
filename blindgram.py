#!/usr/bin/env python3
"""
blindgram: a photo-sharing demo site that shows off kagi's two website features.

    python3 central_server.py add-site blindgram Blindgram --out blindgram_credentials.json
    python3 central_server.py serve                  # http://localhost:8000
    python3 blindgram.py                             # http://localhost:8003
    python3 desktop_app.py                           # the user's app, with the key

Sign up: pick a username and password, then prove you're a unique person. The
site asks the central server for a 12-digit code, you type it into the desktop
app and plug in your key, and the site hears back only "new" (account created)
or "existing" (you already have one; one per person).

Reels are 18+: the site asks for an age check the same way. You type the code
into the desktop app and plug in your key, the key answers "over 18?", and the
central server checks the key's proof. The site hears only yes or no,
and remembers "age verified" on your account.

Blindgram never learns anyone's name, birthday or key id. Log-in after sign-up
is a plain username and password.

Demo reset (both halves, the order doesn't matter):
    python3 blindgram.py reset                       # accounts, posts, likes
    python3 central_server.py forget-site blindgram  # lets the same key sign up again

Put .mp4 files in blindgram_media/reels/ to use real videos as reels; without
them the reels are animated placeholders.
"""

import argparse
import json
import math
import os
import random
import re
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from jinja2 import DictLoader
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

HERE = Path(__file__).resolve().parent
DATA = HERE / "blindgram_data"
UPLOADS = DATA / "uploads"
REEL_MEDIA = HERE / "blindgram_media" / "reels"

USERNAME = re.compile(r"[a-z0-9._]{3,30}")
IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
CHECK_TTL = 300          # matches the central server's code lifetime
AGE_LIMIT = 18

# ---------- seed content (not real accounts) ----------

SEED_USERS = {
    "trailmix.jo": "Mountains on weekends, code on weekdays",
    "saltwater.sam": "Chasing the tide",
    "golden.hour.club": "Only sunsets. That's the account.",
    "abstract.ana": "Colour studies",
    "buzz.gt": "Go Jackets",
    "night.owl.nia": "Up late, again",
}

SEED_POSTS = [
    ("s1", "golden.hour.club", "sunset:11", "Tonight's sky did not hold back", 1284, "2h",
     [("trailmix.jo", "unreal colours"), ("night.owl.nia", "where is this??")]),
    ("s2", "saltwater.sam", "waves:4", "Low tide, high spirits", 342, "5h",
     [("golden.hour.club", "the blues here")]),
    ("s3", "abstract.ana", "blobs:7", "Study no. 14: warm against cool", 876, "8h", []),
    ("s4", "trailmix.jo", "sunset:23", "Summit at 6:40am. Worth the alarm.", 2051, "1d",
     [("buzz.gt", "legs still hurt just looking at this"), ("saltwater.sam", "next time I'm in")]),
    ("s5", "buzz.gt", "blobs:31", "Hackathon fuel: 3 coffees and a dream", 4410, "1d",
     [("night.owl.nia", "same"), ("abstract.ana", "the palette though")]),
    ("s6", "night.owl.nia", "waves:17", "Moonlight swim (didn't swim, too cold)", 519, "2d", []),
    ("s7", "golden.hour.club", "sunset:42", "Day 212 of posting sunsets", 3120, "3d",
     [("trailmix.jo", "never stop")]),
]

SEED_REELS = [
    ("buzz.gt", "POV: your demo works on the first try", "🐝", ("#f9d423", "#e65c00"), "Fight song remix"),
    ("saltwater.sam", "Surf check at dawn", "🌊", ("#43cea2", "#185a9d"), "Waves, 4 hours"),
    ("night.owl.nia", "3am debugging energy", "🦉", ("#232526", "#6a3093"), "lofi beats to ship to"),
    ("trailmix.jo", "The last 200 metres", "⛰️", ("#f7797d", "#4a00e0"), "Original audio"),
    ("abstract.ana", "Mixing colours in slow motion", "🎨", ("#fc466b", "#3f5efb"), "Original audio"),
]

PALETTES = [
    ("#ff9a8b", "#ff6a88", "#ff99ac", "#3b1c32"), ("#fbd786", "#f7797d", "#c6ffdd", "#2d1b3d"),
    ("#12c2e9", "#c471ed", "#f64f59", "#1a1033"), ("#00c6ff", "#0072ff", "#a1ffce", "#06243d"),
    ("#f7971e", "#ffd200", "#ff5e62", "#3d1f12"), ("#8e2de2", "#4a00e0", "#ff6cab", "#140a2e"),
    ("#56ccf2", "#2f80ed", "#f2c94c", "#0b2447"), ("#ee9ca7", "#ffdde1", "#a18cd1", "#3a2f4f"),
]


# ---------- generated images ----------

def art_svg(spec: str) -> str:
    """A deterministic 1080x1080 picture for a seed post: sunset, waves or blobs."""
    kind, _, seed = spec.partition(":")
    rnd = random.Random(spec)
    a, b, c, dark = PALETTES[int(seed or 0) % len(PALETTES)]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1080">',
           f'<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="{b}"/><stop offset=".6" stop-color="{a}"/>'
           f'<stop offset="1" stop-color="{c}"/></linearGradient>'
           '<filter id="blur"><feGaussianBlur stdDeviation="60"/></filter></defs>',
           '<rect width="1080" height="1080" fill="url(#sky)"/>']
    if kind == "sunset":
        sx, sy, r = rnd.randint(300, 780), rnd.randint(420, 560), rnd.randint(90, 150)
        out.append(f'<circle cx="{sx}" cy="{sy}" r="{r * 2}" fill="#fff" opacity=".18" filter="url(#blur)"/>')
        out.append(f'<circle cx="{sx}" cy="{sy}" r="{r}" fill="#fff4d6" opacity=".92"/>')
        for layer in range(3):
            base = 640 + layer * 120
            pts = [(0, 1080), (0, base)]
            x = 0
            while x < 1080:
                x += rnd.randint(90, 220)
                pts.append((min(x, 1080), base - rnd.randint(60, 260 - layer * 50)))
            pts.append((1080, 1080))
            path = " ".join(f"{px},{py}" for px, py in pts)
            out.append(f'<polygon points="{path}" fill="{dark}" opacity="{0.45 + layer * 0.25:.2f}"/>')
    elif kind == "waves":
        out.append(f'<circle cx="{rnd.randint(200, 880)}" cy="260" r="70" fill="#fff" opacity=".85"/>')
        for layer in range(6):
            y0 = 520 + layer * 95
            amp, freq, phase = rnd.randint(14, 34), rnd.uniform(1.5, 3.5), rnd.uniform(0, 6.3)
            pts = " ".join(f"L{x},{y0 + amp * math.sin(freq * x / 1080 * 6.28 + phase):.1f}"
                           for x in range(0, 1081, 30))
            out.append(f'<path d="M0,1080 {pts} L1080,1080 Z" fill="{dark}" '
                       f'opacity="{0.25 + layer * 0.12:.2f}"/>')
    else:
        for _ in range(6):
            colour = rnd.choice((a, b, c, "#ffffff"))
            out.append(f'<circle cx="{rnd.randint(0, 1080)}" cy="{rnd.randint(0, 1080)}" '
                       f'r="{rnd.randint(160, 380)}" fill="{colour}" opacity=".8" filter="url(#blur)"/>')
        for _ in range(3):
            out.append(f'<circle cx="{rnd.randint(150, 930)}" cy="{rnd.randint(150, 930)}" '
                       f'r="{rnd.randint(40, 120)}" fill="none" stroke="#fff" stroke-width="10" opacity=".7"/>')
    out.append("</svg>")
    return "".join(out)


def avatar_svg(name: str) -> str:
    a, b, c, _ = PALETTES[sum(map(ord, name)) % len(PALETTES)]
    letter = (name[:1] or "?").upper()
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/>'
            f'<stop offset="1" stop-color="{c}"/></linearGradient></defs>'
            '<circle cx="50" cy="50" r="50" fill="url(#g)"/>'
            f'<text x="50" y="50" dy=".35em" text-anchor="middle" font-family="system-ui,sans-serif" '
            f'font-size="44" font-weight="600" fill="#fff">{letter}</text></svg>')


def ago(ts: float) -> str:
    s = time.time() - ts
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= size:
            return f"{int(s // size)}{unit}"
    return "Just now"


# ---------- storage ----------

class Store:
    """Everything the site knows, in one JSON file. Note what's missing: nothing
    about who any account belongs to."""

    def __init__(self):
        DATA.mkdir(exist_ok=True)
        UPLOADS.mkdir(exist_ok=True)
        self.path = DATA / "state.json"
        self.lock = threading.Lock()
        empty = {"accounts": {}, "posts": [], "likes": {}, "comments": {}}
        self.data = {**empty, **json.loads(self.path.read_text())} if self.path.exists() else empty

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)

    @property
    def accounts(self):
        return self.data["accounts"]

    def taken(self, username: str) -> bool:
        return username in self.accounts or username in SEED_USERS

    def all_posts(self):
        """User posts newest first, then the seed posts."""
        posts = [{"id": p["id"], "user": p["user"], "image": url_for("upload", name=p["file"]),
                  "caption": p["caption"], "base_likes": 0, "when": ago(p["created"]),
                  "seed_comments": []} for p in reversed(self.data["posts"])]
        posts += [{"id": pid, "user": user, "image": url_for("art", spec=spec), "caption": caption,
                   "base_likes": likes, "when": when, "seed_comments": comments}
                  for pid, user, spec, caption, likes, when, comments in SEED_POSTS]
        return posts


# ---------- central server client ----------

class Central:
    def __init__(self, creds: dict):
        self.server, self.api_key = creds["server"].rstrip("/"), creds["api_key"]

    def call(self, method: str, path: str, body: dict = None) -> dict:
        req = urllib.request.Request(
            self.server + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return json.load(e)


# ---------- templates ----------

ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    "reels": '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M3 8h18M8.5 3l3 5M14.5 3l3 5"/>'
             '<path d="m10 11.5 4.5 2.7-4.5 2.6z" fill="currentColor"/>',
    "create": '<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M12 8v8M8 12h8"/>',
    "heart": '<path d="M12 20.5s-7.5-4.6-9.3-9.2C1.4 7.9 3.6 4.5 7 4.5c2.1 0 3.6 1.1 5 3 1.4-1.9 2.9-3 5-3 '
             '3.4 0 5.6 3.4 4.3 6.8-1.8 4.6-9.3 9.2-9.3 9.2z"/>',
    "comment": '<path d="M20.7 16.3A9 9 0 1 0 17 20.1L21 21z"/>',
    "send": '<path d="M22 3 9.2 10.2M22 3l-7 18-4-8.7L2 8.5z"/>',
    "save": '<path d="M19 21 12 15.5 5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1z"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="11" rx="2.5"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "logout": '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H3"/>',
}

BASE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Blindgram{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Grand+Hotel&display=swap" rel="stylesheet">
<style>
  :root { --bg:#fff; --ink:#000; --muted:#737373; --line:#dbdbdb; --field:#fafafa; --card:#fff;
          --accent:#0095f6; --accent-ink:#fff; --like:#ff3040; --good:#16a34a; --bad:#dc2626;
          --hover:rgba(0,0,0,.05); --shade:rgba(0,0,0,.55);
          --ring:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5); }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#000; --ink:#f5f5f5; --muted:#a8a8a8; --line:#262626; --field:#121212; --card:#000;
            --hover:rgba(255,255,255,.08); --shade:rgba(0,0,0,.7); } }
  * { box-sizing:border-box; }
  html, body { margin:0; background:var(--bg); color:var(--ink); }
  body { font:14px/1.45 -apple-system, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif; }
  a { color:inherit; text-decoration:none; }
  button { font:inherit; cursor:pointer; }
  svg.i { width:24px; height:24px; fill:none; stroke:currentColor; stroke-width:1.8;
          stroke-linecap:round; stroke-linejoin:round; flex:none; }
  .wordmark { font-family:"Grand Hotel", "Brush Script MT", cursive; font-size:34px; line-height:1;
              letter-spacing:.01em; }
  .muted { color:var(--muted); }
  .hidden { display:none !important; }
  .btn { display:inline-block; border:0; border-radius:8px; padding:8px 16px; font-weight:600;
         background:var(--accent); color:var(--accent-ink); }
  .btn:disabled { opacity:.5; cursor:default; }
  .btn.wide { width:100%; }
  .btn.plain { background:var(--field); color:var(--ink); border:1px solid var(--line); }
  input[type=text], input[type=password], textarea {
    font:inherit; width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:6px;
    background:var(--field); color:var(--ink); outline:none; }
  input:focus, textarea:focus { border-color:var(--muted); }
  .error { color:var(--bad); min-height:1.4em; margin:10px 0 0; font-size:13px; }
  .avatar { border-radius:50%; display:block; flex:none; }
  .ring { padding:2px; border-radius:50%; background:var(--ring); flex:none; }
  .ring > .avatar { border:2px solid var(--bg); }

  /* app shell */
  .side { position:fixed; inset:0 auto 0 0; width:244px; border-right:1px solid var(--line);
          padding:28px 12px 20px; display:flex; flex-direction:column; gap:4px; background:var(--bg); z-index:5; }
  .side .wordmark { padding:0 12px 28px; }
  .nav { display:flex; align-items:center; gap:16px; padding:12px; border-radius:8px; font-size:16px; }
  .nav:hover { background:var(--hover); }
  .nav.on { font-weight:700; }
  .nav.on svg.i { stroke-width:2.6; }
  .nav img { width:26px; height:26px; }
  .side .spacer { flex:1; }
  .side form { margin:0; }
  .side form button { width:100%; background:none; border:0; color:var(--ink); text-align:left; }
  .main { margin-left:244px; min-height:100vh; }
  .top, .bottom { display:none; }
  @media (max-width: 767px) {
    .side { display:none; }
    .main { margin-left:0; padding-bottom:56px; }
    .top { display:flex; align-items:center; justify-content:space-between; position:sticky; top:0;
           height:56px; padding:0 16px; border-bottom:1px solid var(--line); background:var(--bg); z-index:5; }
    .top .wordmark { font-size:30px; }
    .bottom { display:flex; justify-content:space-around; align-items:center; position:fixed;
              inset:auto 0 0 0; height:52px; border-top:1px solid var(--line); background:var(--bg); z-index:5; }
    .bottom a { padding:10px; }
    .bottom img { width:26px; height:26px; }
  }

  /* kagi check modal */
  .overlay { position:fixed; inset:0; background:var(--shade); display:grid; place-items:center;
             padding:16px; z-index:20; }
  .modal { background:var(--card); color:var(--ink); border-radius:16px; width:100%; max-width:400px;
           padding:32px 28px 20px; text-align:center; border:1px solid var(--line); }
  .modal h2 { margin:0 0 6px; font-size:20px; }
  .modal p { margin:0 0 4px; color:var(--muted); }
  .code { font:600 34px/1.2 ui-monospace, "Cascadia Mono", Consolas, monospace; letter-spacing:.06em;
          margin:22px 0 18px; white-space:nowrap; }
  .steps { text-align:left; margin:0 auto 18px; padding:0; list-style:none; counter-reset:s;
           max-width:280px; color:var(--muted); }
  .steps li { counter-increment:s; display:flex; gap:10px; padding:4px 0; }
  .steps li::before { content:counter(s); width:22px; height:22px; border-radius:50%; flex:none;
                      background:var(--field); border:1px solid var(--line); color:var(--ink);
                      font-size:12px; font-weight:600; display:grid; place-items:center; }
  .wait { display:flex; align-items:center; justify-content:center; gap:10px; color:var(--muted);
          margin-bottom:10px; }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--accent);
         animation:pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity:.25; } }
  .badge-big { width:72px; height:72px; border-radius:50%; display:grid; place-items:center;
               margin:0 auto 16px; color:#fff; }
  .badge-big svg.i { width:40px; height:40px; stroke-width:2.6; }
  .badge-big.ok { background:var(--good); } .badge-big.no { background:var(--bad); }
  .modal .link { background:none; border:0; color:var(--muted); padding:12px; margin-top:6px; }
  .shield { display:flex; gap:8px; align-items:flex-start; text-align:left; font-size:12px;
            color:var(--muted); background:var(--field); border:1px solid var(--line);
            border-radius:10px; padding:10px 12px; margin-top:16px; }
  .shield svg.i { width:18px; height:18px; margin-top:1px; }
</style>
{% block style %}{% endblock %}
</head><body>
{% block body %}{% endblock %}

<div id="overlay" class="overlay hidden">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="mtitle">
    <div id="m-wait">
      <h2 id="mtitle"></h2>
      <p id="msub"></p>
      <div id="mcode" class="code"></div>
      <ol class="steps">
        <li>Open the kagi app on your computer</li>
        <li>Type in this code</li>
        <li id="mstep3">Plug in your key</li>
      </ol>
      <div class="wait"><span class="dot"></span><span id="mleft">Waiting for your key</span></div>
    </div>
    <div id="m-done" class="hidden">
      <div id="mbadge" class="badge-big"></div>
      <h2 id="rtitle"></h2>
      <p id="rsub"></p>
      <button id="mnext" class="btn wide" style="margin-top:20px"></button>
    </div>
    <button id="mclose" class="link">Cancel</button>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const ICON_OK = '<svg class="i" viewBox="0 0 24 24">{{ icons.check|safe }}</svg>';
const ICON_NO = '<svg class="i" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17"/></svg>';
let polling = null;

// Starts a kagi check: POST start -> {token, code}; shows the code and
// polls /api/checks/<token> until the central server has an answer.
async function kagiCheck(start, body, text, onResult) {
  const r = await fetch(start, {method:'POST', headers:{'Content-Type':'application/json'},
                                body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'Something went wrong.');
  $('mtitle').textContent = text.title;
  $('msub').textContent = text.sub;
  $('mstep3').textContent = text.step3 || 'Plug in your key';
  $('mcode').textContent = j.code.replace(/(\d{4})(?=\d)/g, '$1 ');
  $('mleft').textContent = 'Waiting for your key';
  $('m-wait').classList.remove('hidden');
  $('m-done').classList.add('hidden');
  $('mclose').classList.remove('hidden');
  $('overlay').classList.remove('hidden');
  const token = polling = j.token;
  const poll = async () => {
    if (polling !== token) return;
    let s;
    try { s = await (await fetch('/api/checks/' + token)).json(); }
    catch { return setTimeout(poll, 1500); }
    if (polling !== token) return;
    if (s.status === 'waiting') {
      const m = Math.floor(s.expires_in / 60), sec = String(s.expires_in % 60).padStart(2, '0');
      $('mleft').textContent = 'Waiting for your key · ' + m + ':' + sec;
      return setTimeout(poll, 1000);
    }
    polling = null;
    onResult(s);
  };
  poll();
}

function showResult(ok, title, sub, next, onNext) {
  $('m-wait').classList.add('hidden');
  $('m-done').classList.remove('hidden');
  $('mclose').classList.add('hidden');
  $('mbadge').className = 'badge-big ' + (ok ? 'ok' : 'no');
  $('mbadge').innerHTML = ok ? ICON_OK : ICON_NO;
  $('rtitle').textContent = title;
  $('rsub').textContent = sub;
  $('mnext').textContent = next;
  $('mnext').onclick = onNext || (() => $('overlay').classList.add('hidden'));
}

$('mclose').onclick = () => { polling = null; $('overlay').classList.add('hidden'); };
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && polling) $('mclose').click();
});
</script>
{% block script %}{% endblock %}
</body></html>"""

SHELL = r"""{% extends "base.html" %}
{% block body %}
<aside class="side">
  <a href="/" class="wordmark">Blindgram</a>
  <a class="nav {{ 'on' if tab == 'home' }}" href="/">{{ icon('home') }}Home</a>
  <a class="nav {{ 'on' if tab == 'reels' }}" href="/reels">{{ icon('reels') }}Reels</a>
  <a class="nav {{ 'on' if tab == 'create' }}" href="/create">{{ icon('create') }}Create</a>
  <a class="nav {{ 'on' if tab == 'profile' }}" href="/u/{{ me }}">
    <img class="avatar" src="/avatar/{{ me }}.svg" alt="">Profile</a>
  <div class="spacer"></div>
  <form method="post" action="/logout"><button class="nav">{{ icon('logout') }}Log out</button></form>
</aside>
<header class="top">
  <a href="/" class="wordmark">Blindgram</a>
  <form method="post" action="/logout" style="margin:0">
    <button style="background:none;border:0;color:var(--ink);padding:8px" aria-label="Log out">{{ icon('logout') }}</button></form>
</header>
<div class="main">{% block main %}{% endblock %}</div>
<nav class="bottom">
  <a href="/" aria-label="Home">{{ icon('home') }}</a>
  <a href="/reels" aria-label="Reels">{{ icon('reels') }}</a>
  <a href="/create" aria-label="Create">{{ icon('create') }}</a>
  <a href="/u/{{ me }}" aria-label="Profile"><img class="avatar" src="/avatar/{{ me }}.svg" alt=""></a>
</nav>
{% endblock %}"""

AUTH_STYLE = r"""<style>
  .auth { min-height:100vh; display:flex; flex-direction:column; align-items:center; justify-content:center;
          padding:24px 16px; gap:10px; }
  .panel { width:100%; max-width:350px; border:1px solid var(--line); padding:40px 40px 24px;
           text-align:center; background:var(--card); }
  .panel .wordmark { font-size:52px; display:block; margin:0 0 20px; }
  .panel input { margin-bottom:6px; font-size:13px; }
  .panel .btn { margin-top:10px; }
  .panel.small { padding:20px; }
  .panel .accent { color:var(--accent); font-weight:600; }
  .lede { color:var(--muted); font-weight:600; font-size:16px; margin:0 0 18px; line-height:1.3; }
  @media (max-width: 450px) { .panel { border:0; padding:24px 8px; } }
</style>"""

LOGIN = r"""{% extends "base.html" %}
{% block style %}""" + AUTH_STYLE + r"""{% endblock %}
{% block body %}
<div class="auth">
  <form class="panel" method="post" action="/login">
    <span class="wordmark">Blindgram</span>
    <input type="text" name="username" placeholder="Username" autocomplete="username"
           autocapitalize="off" value="{{ username or '' }}" required>
    <input type="password" name="password" placeholder="Password" autocomplete="current-password" required>
    <button class="btn wide">Log in</button>
    <p class="error">{{ error or '' }}</p>
  </form>
  <div class="panel small">Don't have an account? <a class="accent" href="/signup">Sign up</a></div>
</div>
{% endblock %}"""

SIGNUP = r"""{% extends "base.html" %}
{% block style %}""" + AUTH_STYLE + r"""{% endblock %}
{% block body %}
<div class="auth">
  <form class="panel" id="form" autocomplete="off">
    <span class="wordmark">Blindgram</span>
    <p class="lede">Sign up to see photos and videos from your friends.</p>
    <input type="text" id="username" placeholder="Username" autocapitalize="off" maxlength="30" required>
    <input type="password" id="password" placeholder="Password" autocomplete="new-password" required>
    <button class="btn wide" id="go">Sign up with kagi</button>
    <p class="error" id="err"></p>
    <div class="shield">
      <svg class="i" viewBox="0 0 24 24">{{ icons.lock|safe }}</svg>
      <span>One account per person, checked by your kagi. Blindgram never sees your name,
        birthday or ID, only whether you already have an account.</span>
    </div>
  </form>
  <div class="panel small">Have an account? <a class="accent" href="/login">Log in</a></div>
</div>
{% endblock %}
{% block script %}<script>
$('form').onsubmit = async e => {
  e.preventDefault();
  $('err').textContent = '';
  $('go').disabled = true;
  try {
    await kagiCheck('/api/signup/start',
      {username: $('username').value, password: $('password').value},
      {title: 'Prove you\'re one person', sub: 'Blindgram allows one account per person.'},
      s => {
        if (s.status === 'created')
          showResult(true, 'Welcome to Blindgram', 'Your account @' + s.username + ' is ready.',
                     'Continue', () => location.href = '/');
        else if (s.status === 'existing')
          showResult(false, 'You already have an account',
                     'Your key has already been used to sign up here. Blindgram allows one account per person.',
                     'Log in instead', () => location.href = '/login');
        else
          showResult(false, 'That didn\'t work', s.error || 'The code expired or your key\'s answer didn\'t check out. Try again.',
                     'OK');
      });
  } catch (err) {
    $('err').textContent = err.message;
  } finally {
    $('go').disabled = false;
  }
};
</script>{% endblock %}"""

FEED = r"""{% extends "shell.html" %}
{% block style %}<style>
  .feed { max-width:470px; margin:0 auto; padding:24px 0 40px; }
  .stories { display:flex; gap:14px; overflow-x:auto; padding:4px 4px 16px; margin-bottom:8px;
             scrollbar-width:none; }
  .story { display:flex; flex-direction:column; align-items:center; gap:4px; width:68px; font-size:12px; }
  .story span { max-width:68px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .post { border-bottom:1px solid var(--line); padding-bottom:16px; margin-bottom:20px; }
  .post header { display:flex; align-items:center; gap:10px; padding:0 4px 12px; }
  .post header b { font-weight:600; }
  .post .photo { width:100%; aspect-ratio:1; object-fit:cover; display:block; border-radius:4px;
                 background:var(--field); user-select:none; }
  .photo-wrap { position:relative; }
  .pop { position:absolute; inset:0; display:grid; place-items:center; pointer-events:none; opacity:0; }
  .pop svg { width:96px; height:96px; fill:#fff; stroke:none; filter:drop-shadow(0 2px 12px rgba(0,0,0,.35)); }
  .pop.go { animation:pop .9s ease-out; }
  @keyframes pop { 0% { opacity:0; transform:scale(.4); } 15% { opacity:1; transform:scale(1.1); }
                   30% { transform:scale(1); } 80% { opacity:1; } 100% { opacity:0; } }
  .actions { display:flex; gap:14px; padding:10px 4px 6px; }
  .actions button { background:none; border:0; padding:0; color:var(--ink); }
  .actions .push { margin-left:auto; }
  .liked svg.i { fill:var(--like); stroke:var(--like); }
  .likes { font-weight:600; padding:0 4px; }
  .caption, .comment { padding:2px 4px; }
  .caption b, .comment b { font-weight:600; margin-right:4px; }
  .when { font-size:12px; color:var(--muted); padding:4px 4px 0; }
  .add { display:flex; padding:6px 4px 0; }
  .add input { border:0; background:none; padding:6px 0; flex:1; }
  .add button { background:none; border:0; color:var(--accent); font-weight:600; }
  .empty { text-align:center; padding:40px 0; }
  @media (max-width: 767px) { .feed { padding-top:8px; } .post header, .actions, .likes, .caption,
    .comment, .when, .add { padding-left:12px; padding-right:12px; } .post .photo { border-radius:0; } }
</style>{% endblock %}
{% block main %}
<div class="feed">
  <div class="stories">
    {% for u in stories %}
    <a class="story" href="/u/{{ u }}"><span class="ring"><img class="avatar" src="/avatar/{{ u }}.svg"
      width="60" height="60" alt=""></span><span>{{ u }}</span></a>
    {% endfor %}
  </div>
  {% for p in posts %}
  <article class="post" data-id="{{ p.id }}">
    <header><a href="/u/{{ p.user }}"><img class="avatar" src="/avatar/{{ p.user }}.svg" width="32" height="32" alt=""></a>
      <a href="/u/{{ p.user }}"><b>{{ p.user }}</b></a><span class="muted">· {{ p.when }}</span></header>
    <div class="photo-wrap"><img class="photo" src="{{ p.image }}" alt="" loading="lazy">
      <div class="pop"><svg viewBox="0 0 24 24">{{ icons.heart|safe }}</svg></div></div>
    <div class="actions">
      <button class="like {{ 'liked' if p.liked }}" aria-label="Like">{{ icon('heart') }}</button>
      <button aria-label="Comment" onclick="this.closest('.post').querySelector('.add input').focus()">{{ icon('comment') }}</button>
      <button aria-label="Share">{{ icon('send') }}</button>
      <button class="push" aria-label="Save">{{ icon('save') }}</button>
    </div>
    <div class="likes"><span class="n">{{ '{:,}'.format(p.likes) }}</span> likes</div>
    {% if p.caption %}<div class="caption"><b>{{ p.user }}</b>{{ p.caption }}</div>{% endif %}
    <div class="comments">
      {% for who, text in p.comments %}<div class="comment"><b>{{ who }}</b>{{ text }}</div>{% endfor %}
    </div>
    <form class="add"><input type="text" placeholder="Add a comment..." maxlength="300"><button>Post</button></form>
  </article>
  {% else %}
  <p class="empty muted">No posts yet.</p>
  {% endfor %}
</div>
{% endblock %}
{% block script %}<script>
async function like(post, force) {
  const btn = post.querySelector('.like');
  if (force && btn.classList.contains('liked')) return;
  const r = await fetch('/api/posts/' + post.dataset.id + '/like', {method:'POST'});
  if (!r.ok) return;
  const j = await r.json();
  btn.classList.toggle('liked', j.liked);
  post.querySelector('.n').textContent = j.likes.toLocaleString();
}
document.querySelectorAll('.post').forEach(post => {
  post.querySelector('.like').onclick = () => like(post);
  post.querySelector('.photo').ondblclick = () => {
    const pop = post.querySelector('.pop');
    pop.classList.remove('go'); void pop.offsetWidth; pop.classList.add('go');
    like(post, true);
  };
  const form = post.querySelector('.add');
  form.onsubmit = async e => {
    e.preventDefault();
    const input = form.querySelector('input'), text = input.value.trim();
    if (!text) return;
    const r = await fetch('/api/posts/' + post.dataset.id + '/comment', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
    if (!r.ok) return;
    const j = await r.json(), row = document.createElement('div'), who = document.createElement('b');
    row.className = 'comment'; who.textContent = j.user;
    row.append(who, j.text);
    post.querySelector('.comments').append(row);
    input.value = '';
  };
});
</script>{% endblock %}"""

PROFILE = r"""{% extends "shell.html" %}
{% block style %}<style>
  .profile { max-width:935px; margin:0 auto; padding:30px 20px 40px; }
  .head { display:flex; gap:28px; align-items:center; padding:0 0 32px 40px; border-bottom:1px solid var(--line); }
  .head .avatar { width:150px; height:150px; }
  .head h1 { font-size:20px; font-weight:400; margin:0 0 16px; display:flex; align-items:center; gap:8px; }
  .stats { display:flex; gap:32px; margin-bottom:14px; font-size:16px; }
  .stats b { font-weight:600; }
  .badges { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
  .badge { display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600;
           border-radius:999px; padding:4px 10px 4px 6px; border:1px solid var(--line); background:var(--field); }
  .badge svg.i { width:16px; height:16px; stroke-width:2.6; }
  .badge.good { color:var(--good); border-color:color-mix(in srgb, var(--good) 40%, transparent); }
  .badge.off { color:var(--muted); }
  .grid { display:grid; grid-template-columns:repeat(3, 1fr); gap:4px; margin-top:24px; }
  .grid img { width:100%; aspect-ratio:1; object-fit:cover; display:block; background:var(--field); }
  .empty { text-align:center; padding:60px 0; }
  @media (max-width: 767px) {
    .profile { padding:20px 0; }
    .head { padding:0 16px 20px; gap:20px; }
    .head .avatar { width:80px; height:80px; }
    .stats { gap:18px; font-size:14px; }
    .grid { gap:2px; }
  }
</style>{% endblock %}
{% block main %}
<div class="profile">
  <div class="head">
    <img class="avatar" src="/avatar/{{ user }}.svg" alt="">
    <div>
      <h1>{{ user }}</h1>
      <div class="stats"><span><b>{{ posts|length }}</b> posts</span>
        <span><b>{{ followers }}</b> followers</span><span><b>{{ following }}</b> following</span></div>
      <div>{{ bio }}</div>
      {% if account %}
      <div class="badges">
        <span class="badge good">{{ icon('check') }}Unique person</span>
        {% if account.age_verified %}<span class="badge good">{{ icon('check') }}18+ verified</span>
        {% elif user == me %}<a class="badge off" href="/reels">{{ icon('lock') }}Age not verified</a>{% endif %}
      </div>
      {% endif %}
    </div>
  </div>
  {% if posts %}
  <div class="grid">{% for p in posts %}<img src="{{ p.image }}" alt="" loading="lazy">{% endfor %}</div>
  {% else %}
  <p class="empty muted">{{ 'Share your first photo.' if user == me else 'No posts yet.' }}
    {% if user == me %}<br><br><a class="btn" href="/create">Create a post</a>{% endif %}</p>
  {% endif %}
</div>
{% endblock %}"""

CREATE = r"""{% extends "shell.html" %}
{% block style %}<style>
  .create { max-width:470px; margin:0 auto; padding:32px 16px; }
  .create h1 { font-size:20px; margin:0 0 20px; text-align:center; }
  .drop { display:grid; place-items:center; aspect-ratio:1; border:1px dashed var(--line); border-radius:12px;
          background:var(--field); cursor:pointer; overflow:hidden; text-align:center; color:var(--muted); }
  .drop img { width:100%; height:100%; object-fit:cover; }
  .drop input { display:none; }
  .create textarea { margin:16px 0 12px; min-height:80px; resize:vertical; }
</style>{% endblock %}
{% block main %}
<form class="create" method="post" enctype="multipart/form-data">
  <h1>Create new post</h1>
  <label class="drop" id="drop"><span id="hint">{{ icon('create') }}<br>Choose a photo</span>
    <img id="preview" class="hidden" alt="">
    <input type="file" name="photo" id="photo" accept="image/*" required></label>
  <textarea name="caption" placeholder="Write a caption..." maxlength="2200"></textarea>
  <button class="btn wide">Share</button>
  <p class="error">{{ error or '' }}</p>
</form>
{% endblock %}
{% block script %}<script>
$('photo').onchange = () => {
  const f = $('photo').files[0];
  if (!f) return;
  $('preview').src = URL.createObjectURL(f);
  $('preview').classList.remove('hidden');
  $('hint').classList.add('hidden');
};
</script>{% endblock %}"""

REELS_GATE = r"""{% extends "shell.html" %}
{% block style %}<style>
  .gate { min-height:100vh; display:grid; place-items:center; padding:24px 16px; }
  .gate-card { max-width:380px; text-align:center; }
  .lockbig { width:96px; height:96px; border-radius:50%; border:2px solid var(--ink); display:grid;
             place-items:center; margin:0 auto 20px; }
  .lockbig svg.i { width:44px; height:44px; stroke-width:1.5; }
  .gate h1 { font-size:22px; margin:0 0 10px; }
  .gate p { color:var(--muted); margin:0 0 24px; }
  .gate .btn { padding:10px 22px; }
  @media (max-width: 767px) { .gate { min-height:calc(100vh - 110px); } }
</style>{% endblock %}
{% block main %}
<div class="gate"><div class="gate-card">
  <div class="lockbig">{{ icon('lock') }}</div>
  <h1>Reels are for 18+</h1>
  <p>Verify your age with your kagi to watch. Blindgram learns only that you're 18 or
     over: never your name, your birthday or your ID.</p>
  <button class="btn" id="go">Verify with kagi</button>
  <p class="error" id="err"></p>
</div></div>
{% endblock %}
{% block script %}<script>
$('go').onclick = async () => {
  $('err').textContent = '';
  $('go').disabled = true;
  try {
    await kagiCheck('/api/age/start', {},
      {title: 'Verify your age', sub: 'Blindgram will learn only yes or no.',
       step3: 'Plug in your key'},
      s => {
        if (s.status === 'verified')
          showResult(true, 'You\'re verified', 'Your account is now 18+ verified. Enjoy Reels.',
                     'Watch Reels', () => location.reload());
        else
          showResult(false, 'Couldn\'t verify your age',
                     s.status === 'failed' ? 'Your key couldn\'t confirm you\'re 18 or over.'
                                           : 'The code expired. Try again.', 'OK');
      });
  } catch (err) {
    $('err').textContent = err.message;
  } finally {
    $('go').disabled = false;
  }
};
</script>{% endblock %}"""

REELS = r"""{% extends "shell.html" %}
{% block style %}<style>
  .reels { height:100vh; overflow-y:scroll; scroll-snap-type:y mandatory; scrollbar-width:none; }
  .reels::-webkit-scrollbar { display:none; }
  .slot { height:100vh; scroll-snap-align:start; display:flex; align-items:center; justify-content:center;
          gap:16px; padding:16px 0; }
  .reel { position:relative; height:100%; aspect-ratio:9/16; max-width:100%; border-radius:8px;
          overflow:hidden; background:#111; color:#fff; }
  .reel video { width:100%; height:100%; object-fit:cover; display:block; }
  .anim { position:absolute; inset:0; background-size:300% 300%; animation:drift 8s ease-in-out infinite; }
  @keyframes drift { 0%,100% { background-position:0% 0%; } 50% { background-position:100% 100%; } }
  .emoji { position:absolute; inset:0; display:grid; place-items:center; font-size:110px;
           animation:bob 3s ease-in-out infinite; }
  @keyframes bob { 50% { transform:translateY(-18px) rotate(-4deg); } }
  .meta { position:absolute; inset:auto 0 0 0; padding:60px 16px 18px;
          background:linear-gradient(transparent, rgba(0,0,0,.6)); }
  .who { display:flex; align-items:center; gap:8px; font-weight:600; margin-bottom:8px; }
  .who img { width:32px; height:32px; }
  .audio { font-size:12px; opacity:.85; margin-top:6px; }
  .side-actions { display:flex; flex-direction:column; gap:22px; align-items:center; align-self:flex-end;
                  padding-bottom:20px; font-size:12px; }
  .side-actions button { background:none; border:0; color:var(--ink); padding:0; display:flex;
                         flex-direction:column; align-items:center; gap:4px; }
  .side-actions .liked svg.i { fill:var(--like); stroke:var(--like); }
  @media (max-width: 767px) {
    .reels, .slot { height:calc(100vh - 108px); }
    .slot { padding:0; gap:0; }
    .reel { border-radius:0; height:100%; width:100%; aspect-ratio:auto; }
    .side-actions { position:absolute; right:12px; bottom:90px; color:#fff; }
    .side-actions button { color:#fff; }
    .slot { position:relative; }
  }
</style>{% endblock %}
{% block main %}
<div class="reels">
  {% for r in reels %}
  <section class="slot">
    <div class="reel">
      {% if r.video %}<video src="{{ r.video }}" muted loop playsinline preload="metadata"></video>
      {% else %}<div class="anim" style="background-image:linear-gradient(135deg, {{ r.colours[0] }}, {{ r.colours[1] }}, {{ r.colours[0] }})"></div>
      <div class="emoji">{{ r.emoji }}</div>{% endif %}
      <div class="meta">
        <div class="who"><img class="avatar" src="/avatar/{{ r.user }}.svg" alt="">{{ r.user }}</div>
        <div>{{ r.caption }}</div>
        <div class="audio">♫ {{ r.audio }}</div>
      </div>
    </div>
    <div class="side-actions">
      <button onclick="this.classList.toggle('liked')">{{ icon('heart') }}{{ r.likes }}</button>
      <button>{{ icon('comment') }}{{ r.comments }}</button>
      <button>{{ icon('send') }}</button>
    </div>
  </section>
  {% endfor %}
</div>
{% endblock %}
{% block script %}<script>
// Play only the reel on screen.
const io = new IntersectionObserver(entries => entries.forEach(e => {
  const v = e.target.querySelector('video');
  if (v) e.isIntersecting ? v.play().catch(() => {}) : v.pause();
}), {threshold: .6});
document.querySelectorAll('.slot').forEach(s => io.observe(s));
</script>{% endblock %}"""


# ---------- app ----------

def load_secret() -> bytes:
    path = DATA / "session.key"
    if not path.exists():
        DATA.mkdir(exist_ok=True)
        with open(path, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(secrets.token_bytes(32))
    return path.read_bytes()


def create_app(store: Store, central: Central) -> Flask:
    app = Flask(__name__)
    app.secret_key = load_secret()
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.jinja_loader = DictLoader({
        "base.html": BASE, "shell.html": SHELL, "login.html": LOGIN, "signup.html": SIGNUP,
        "feed.html": FEED, "profile.html": PROFILE, "create.html": CREATE,
        "reels_gate.html": REELS_GATE, "reels.html": REELS,
    })
    app.jinja_env.globals["icon"] = lambda name: Markup(
        f'<svg class="i" viewBox="0 0 24 24">{ICONS[name]}</svg>')
    pending = {}          # browser token -> in-flight kagi check; dropped once answered
    lock = threading.Lock()

    def me():
        user = session.get("user")
        return user if user in store.accounts else None

    def page(name, **kw):
        return render_template(name, icons=ICONS, me=me(), **kw)

    def start_check(kind: str, body: dict, **extra):
        """Asks the central server for a code; returns the browser's {token, code}."""
        try:
            j = central.call("POST", "/api/challenges", body)
        except OSError:
            return jsonify({"error": "The kagi service is unreachable."}), 502
        if "code" not in j:
            return jsonify({"error": j.get("error", "kagi service error")}), 502
        token = secrets.token_urlsafe(16)
        with lock:
            now = time.time()
            for t in [t for t, p in pending.items() if p["expires"] < now]:
                del pending[t]
            pending[token] = {"kind": kind, "code": j["code"], "expires": now + CHECK_TTL + 30, **extra}
        session[f"pending_{kind}"] = token      # a retry from this browser replaces it
        return jsonify({"token": token, "code": j["code"]})

    @app.get("/")
    def home():
        user = me()
        if not user:
            return redirect(url_for("login"))
        likes, comments = store.data["likes"], store.data["comments"]
        posts = []
        for p in store.all_posts():
            liked_by = likes.get(p["id"], [])
            posts.append({**p, "likes": p["base_likes"] + len(liked_by), "liked": user in liked_by,
                          "comments": [tuple(c) for c in p["seed_comments"]] + comments.get(p["id"], [])})
        stories = list(SEED_USERS) + [u for u in store.accounts if u != user][:10]
        return page("feed.html", tab="home", posts=posts, stories=stories)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return redirect("/") if me() else page("login.html")
        username = request.form.get("username", "").strip().lower()
        acct = store.accounts.get(username)
        if not acct or not check_password_hash(acct["password"], request.form.get("password", "")):
            return page("login.html", error="Sorry, your username or password was incorrect.",
                        username=username), 401
        session["user"] = username
        return redirect("/")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/signup")
    def signup():
        return redirect("/") if me() else page("signup.html")

    @app.post("/api/signup/start")
    def signup_start():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", "")).strip().lower()
        password = str(body.get("password", ""))
        if not USERNAME.fullmatch(username):
            return jsonify({"error": "Usernames are 3-30 letters, numbers, '.' or '_'."}), 400
        if len(password) < 6:
            return jsonify({"error": "Use a password of at least 6 characters."}), 400
        with lock:
            pending.pop(session.pop("pending_signup", None), None)
            reserved = any(p.get("username") == username and p["kind"] == "signup"
                           for p in pending.values())
        if store.taken(username) or reserved:
            return jsonify({"error": "That username isn't available."}), 409
        return start_check("signup", {"type": "unique_signup"}, username=username,
                           password=generate_password_hash(password))

    @app.post("/api/age/start")
    def age_start():
        user = me()
        if not user:
            return jsonify({"error": "Log in first."}), 401
        return start_check("age", {"type": "age_check", "over": AGE_LIMIT}, username=user)

    @app.get("/api/checks/<token>")
    def check_status(token):
        with lock:
            p = pending.get(token)
        if not p:
            return jsonify({"status": "expired"})
        if p["kind"] == "age" and p["username"] != me():
            abort(404)
        try:
            j = central.call("GET", f"/api/challenges/{p['code']}/result")
        except OSError:
            return jsonify({"status": "waiting", "expires_in": max(0, int(p["expires"] - time.time() - 30))})
        if j.get("status") == "waiting":
            return jsonify(j)
        with lock:
            if pending.pop(token, None) is None:        # another poll got here first
                return jsonify({"status": "expired"})
        if j.get("status") != "complete":
            return jsonify({"status": "failed" if j.get("status") == "failed" else "expired"})

        if p["kind"] == "age":
            with store.lock:
                store.accounts[p["username"]]["age_verified"] = True
                store.save()
            print(f"@{p['username']} is now 18+ verified")
            return jsonify({"status": "verified"})
        if j["result"] == "existing":
            return jsonify({"status": "existing"})
        with store.lock:
            if store.taken(p["username"]):              # can't happen: reserved while pending
                return jsonify({"status": "failed", "error": "That username was taken meanwhile."})
            store.accounts[p["username"]] = {"password": p["password"], "created": time.time(),
                                             "age_verified": False}
            store.save()
        session["user"] = p["username"]
        print(f"created @{p['username']} ({len(store.accounts)} accounts)")
        return jsonify({"status": "created", "username": p["username"]})

    @app.get("/reels")
    def reels():
        user = me()
        if not user:
            return redirect(url_for("login"))
        if not store.accounts[user].get("age_verified"):
            return page("reels_gate.html", tab="reels")
        videos = sorted(REEL_MEDIA.glob("*.mp4")) if REEL_MEDIA.is_dir() else []
        rnd = random.Random(7)
        items = []
        for i, (u, caption, emoji, colours, audio) in enumerate(SEED_REELS):
            items.append({"user": u, "caption": caption, "emoji": emoji, "colours": colours,
                          "audio": audio, "video": url_for("reel_media", name=videos[i % len(videos)].name)
                          if videos else None,
                          "likes": f"{rnd.randint(12, 980)}K", "comments": rnd.randint(100, 4000)})
        return page("reels.html", tab="reels", reels=items)

    @app.get("/reels/media/<path:name>")
    def reel_media(name):
        user = me()
        if not user or not store.accounts[user].get("age_verified"):
            abort(403)
        return send_from_directory(REEL_MEDIA, name)

    @app.get("/u/<user>")
    def profile(user):
        if not me():
            return redirect(url_for("login"))
        account = store.accounts.get(user)
        if not account and user not in SEED_USERS:
            abort(404)
        posts = [p for p in store.all_posts() if p["user"] == user]
        rnd = random.Random(user)
        return page("profile.html", tab="profile" if user == me() else None, user=user,
                    account=account, posts=posts, bio=SEED_USERS.get(user, ""),
                    followers=rnd.randint(40, 9000) if user in SEED_USERS else 0,
                    following=rnd.randint(40, 900) if user in SEED_USERS else 0)

    @app.route("/create", methods=["GET", "POST"])
    def create():
        user = me()
        if not user:
            return redirect(url_for("login"))
        if request.method == "GET":
            return page("create.html", tab="create")
        photo = request.files.get("photo")
        ext = (photo.filename.rsplit(".", 1)[-1].lower() if photo and "." in photo.filename else "")
        if ext not in IMAGE_TYPES:
            return page("create.html", tab="create", error="Choose a JPEG, PNG, GIF or WebP photo."), 400
        name = f"{secrets.token_hex(8)}.{ext}"
        photo.save(UPLOADS / name)
        with store.lock:
            store.data["posts"].append({"id": "u" + secrets.token_hex(6), "user": user, "file": name,
                                        "caption": request.form.get("caption", "").strip()[:2200],
                                        "created": time.time()})
            store.save()
        return redirect("/")

    def known_post(pid):
        return any(p[0] == pid for p in SEED_POSTS) or any(p["id"] == pid for p in store.data["posts"])

    @app.post("/api/posts/<pid>/like")
    def like(pid):
        user = me()
        if not user or not known_post(pid):
            abort(404)
        with store.lock:
            liked_by = store.data["likes"].setdefault(pid, [])
            if user in liked_by:
                liked_by.remove(user)
            else:
                liked_by.append(user)
            store.save()
            liked, n = user in liked_by, len(liked_by)
        base = next((p[4] for p in SEED_POSTS if p[0] == pid), 0)
        return jsonify({"liked": liked, "likes": base + n})

    @app.post("/api/posts/<pid>/comment")
    def comment(pid):
        user = me()
        text = str((request.get_json(silent=True) or {}).get("text", "")).strip()[:300]
        if not user or not known_post(pid) or not text:
            abort(400)
        with store.lock:
            store.data["comments"].setdefault(pid, []).append([user, text])
            store.save()
        return jsonify({"user": user, "text": text})

    @app.get("/art/<spec>.svg")
    def art(spec):
        if not re.fullmatch(r"(sunset|waves|blobs):\d{1,4}", spec):
            abort(404)
        return art_svg(spec), 200, {"Content-Type": "image/svg+xml",
                                    "Cache-Control": "public, max-age=86400"}

    @app.get("/avatar/<name>.svg")
    def avatar(name):
        return avatar_svg(name[:30]), 200, {"Content-Type": "image/svg+xml",
                                            "Cache-Control": "public, max-age=86400"}

    @app.get("/uploads/<name>")
    def upload(name):
        if not me():
            abort(403)
        return send_from_directory(UPLOADS, name)

    return app


def main():
    p = argparse.ArgumentParser(description="Blindgram: kagi sign-up and age checks, demoed")
    p.add_argument("cmd", nargs="?", choices=["serve", "reset"], default="serve",
                   help="reset deletes accounts, posts, likes and comments")
    p.add_argument("--creds", default="blindgram_credentials.json")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8003)
    a = p.parse_args()
    if a.cmd == "reset":
        for path in (DATA / "state.json", UPLOADS):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        print("Blindgram reset. Also run:  python3 central_server.py forget-site blindgram")
        return
    try:
        creds = json.loads(Path(a.creds).read_text())
    except FileNotFoundError:
        raise SystemExit(f"{a.creds} not found: run  python3 central_server.py add-site blindgram "
                         f"Blindgram --out {a.creds}  first")
    store = Store()
    print(f"Blindgram: {len(store.accounts)} account(s); http://{a.host}:{a.port}")
    create_app(store, Central(creds)).run(host=a.host, port=a.port, threaded=True)


if __name__ == "__main__":
    main()
