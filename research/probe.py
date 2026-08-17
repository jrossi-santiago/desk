#!/usr/bin/env python3
"""Polite site prober for med spa prospecting.

Fetches a site's key pages (home, about, team, contact), respects robots.txt,
rate limits to ~1 req/sec per domain, and extracts owner/age/contact signals.

Usage: python3 probe.py <url> [<url> ...]
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.robotparser as urp
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (compatible; ProspectResearch/1.0)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PATHS = [
    "", "/about", "/about-us", "/aboutus", "/our-story", "/team", "/our-team",
    "/meet-the-team", "/meet-our-team", "/staff", "/providers", "/our-providers",
    "/contact", "/contact-us", "/locations", "/practitioners",
]

_last_hit = {}
_robots = {}


_delay = {}


def robots_ok(url):
    """Fetch robots.txt with a real UA and parse it.

    RobotFileParser.read() maps a 403 on robots.txt to disallow-all, and plenty
    of hosts serve 403 to urllib's default UA -- so fetch it ourselves and only
    honour an actual Disallow rule.
    """
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = None
        try:
            r = requests.get(base + "/robots.txt", headers=HEADERS, timeout=15)
            if r.status_code == 200 and len(r.text) < 500000:
                rp = urp.RobotFileParser()
                rp.parse(r.text.splitlines())
                m = re.search(r"^\s*crawl-delay:\s*([\d.]+)", r.text,
                              re.I | re.M)
                if m:
                    _delay[p.netloc] = min(float(m.group(1)), 10.0)
        except Exception:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    if rp is None:
        return True  # no usable robots.txt -> allow, still rate limited
    try:
        return rp.can_fetch(UA, url)
    except Exception:
        return True


def throttle(netloc):
    gap = max(1.05, _delay.get(netloc, 0))
    now = time.time()
    prev = _last_hit.get(netloc, 0)
    wait = gap - (now - prev)
    if wait > 0:
        time.sleep(wait)
    _last_hit[netloc] = time.time()


def get(url):
    if not robots_ok(url):
        return None, "robots_disallow"
    netloc = urllib.parse.urlparse(url).netloc
    throttle(netloc)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    except Exception as e:
        return None, f"error:{type(e).__name__}"
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return None, "not_html"
    return r.text, None


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?(\d{3})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})\b")
IG_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.I)
FB_RE = re.compile(r"facebook\.com/([A-Za-z0-9_.\-]+)", re.I)
YEAR_RE = re.compile(
    r"(?:since|established(?:\s+in)?|est\.?|founded(?:\s+in)?|serving[^.]{0,40}?since|opened(?:\s+(?:in|her|his|our))?[^.]{0,25}?in|celebrating[^.]{0,30}?)\s*"
    r"(19[7-9]\d|20[0-2]\d)", re.I)
OWNER_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){0,2})[,\s]+(?:is\s+)?(?:the\s+)?"
    r"(owner|founder|co-owner|co-founder|owner and (?:injector|operator|aesthetic)[a-z\s]*)", re.I)
CRED_RE = re.compile(
    r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-\.]+){0,2}),?\s+"
    r"(FNP-BC|FNP-C|FNP|NP-C|APRN|AGNP|DNP|MSN,?\s*RN|PA-C|MD|DO|RN|NP)\b")
FOUND_PHRASE = re.compile(
    r"[^.]{0,160}(?:founded by|founder|owner|opened (?:her|his|the|their)|"
    r"owns and operates|proud owner|practice owner)[^.]{0,160}\.", re.I)
ROLLUP_RE = re.compile(
    r"(part of the [A-Z][\w\s&]{2,40} family|a [A-Z][\w\s&]{2,30} company|"
    r"family of practices|portfolio company|managed by [A-Z][\w\s&]{2,30}|"
    r"supported by [A-Z][\w\s&]{2,30})", re.I)


def clean_text(html):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    txt = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt), soup


def fmt_phone(m):
    return f"({m[0]}) {m[1]}-{m[2]}"


INTEREST_RE = re.compile(
    r"about|team|staff|provider|practitioner|contact|our-story|meet|owner|"
    r"founder|location|who-we-are|bio", re.I)


def discover(base_url):
    """Find candidate about/team/contact paths from homepage nav and sitemap."""
    found = []
    html, err = get(base_url + "/")
    if html:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http"):
                if urllib.parse.urlparse(href).netloc != urllib.parse.urlparse(base_url).netloc:
                    continue
                href = urllib.parse.urlparse(href).path
            if not href.startswith("/") or href.startswith("//"):
                continue
            href = href.split("#")[0].split("?")[0].rstrip("/")
            if href and INTEREST_RE.search(href) and href not in found:
                found.append(href)
    for sm in ["/sitemap.xml", "/sitemap_index.xml", "/page-sitemap.xml"]:
        xml, err = get(base_url + sm)
        if not xml:
            continue
        for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
            p = urllib.parse.urlparse(loc)
            if p.netloc and p.netloc != urllib.parse.urlparse(base_url).netloc:
                continue
            path = p.path.rstrip("/")
            if path and INTEREST_RE.search(path) and path not in found:
                found.append(path)
        if found:
            break
    return found[:9]


def probe(base_url, paths=None, auto=True):
    base_url = base_url.rstrip("/")
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    out = {
        "url": base_url, "pages_ok": [], "pages_fail": {}, "emails": [], "phones": [],
        "instagram": [], "facebook": [], "years": [], "owner_hits": [], "cred_hits": [],
        "found_phrases": [], "rollup_hits": [], "titles": [],
    }
    if paths is None and auto:
        disc = discover(base_url)
        paths = [""] + disc if disc else PATHS
        out["discovered"] = disc
    for path in (paths or PATHS):
        url = base_url + path
        html, err = get(url)
        if err:
            out["pages_fail"][path or "/"] = err
            continue
        out["pages_ok"].append(path or "/")
        txt, soup = clean_text(html)
        if soup.title and soup.title.string:
            out["titles"].append(soup.title.string.strip()[:120])
        # emails from mailto + text
        for a in soup.select('a[href^="mailto:"]'):
            e = a["href"][7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(e):
                out["emails"].append(e.lower())
        out["emails"] += [e.lower() for e in EMAIL_RE.findall(txt)]
        out["phones"] += [fmt_phone(m) for m in PHONE_RE.findall(txt)]
        for a in soup.find_all("a", href=True):
            out["instagram"] += IG_RE.findall(a["href"])
            out["facebook"] += FB_RE.findall(a["href"])
        out["instagram"] += IG_RE.findall(html)
        out["years"] += YEAR_RE.findall(txt)
        out["owner_hits"] += [" ".join(t).strip() for t in OWNER_RE.findall(txt)]
        out["cred_hits"] += [f"{a} {b}" for a, b in CRED_RE.findall(txt)]
        out["found_phrases"] += [p.strip()[:220] for p in FOUND_PHRASE.findall(txt)]
        out["rollup_hits"] += [h if isinstance(h, str) else h[0] for h in ROLLUP_RE.findall(txt)]
        cf = CACHE / (urllib.parse.quote(base_url + path, safe="") + ".txt")
        cf.write_text(txt[:200000])

    # dedupe, preserve order
    def dd(key, limit=14):
        seen, res = set(), []
        for v in out[key]:
            k = v.lower() if isinstance(v, str) else v
            if k not in seen:
                seen.add(k)
                res.append(v)
        out[key] = res[:limit]

    for k in ["emails", "phones", "instagram", "facebook", "years", "owner_hits",
              "cred_hits", "found_phrases", "rollup_hits", "titles"]:
        dd(k)
    # filter junk instagram handles
    junk = {"p", "explore", "reel", "reels", "accounts", "tv", "stories", "embed"}
    out["instagram"] = [h for h in out["instagram"] if h.lower() not in junk]
    out["emails"] = [e for e in out["emails"]
                     if not re.search(r"\.(png|jpg|jpeg|gif|webp|svg|css|js)$", e)
                     and "sentry" not in e and "example.com" not in e]
    return out


def summarize(r):
    lines = [f"== {r['url']}"]
    if not r["pages_ok"]:
        codes = set(r["pages_fail"].values())
        lines.append(f"   BLOCKED/DEAD: {sorted(codes)[:4]}")
        return "\n".join(lines)
    lines.append(f"   pages: {r['pages_ok']}")
    for k in ["emails", "phones", "instagram", "years", "owner_hits", "cred_hits",
              "rollup_hits"]:
        if r.get(k):
            lines.append(f"   {k}: {json.dumps(r[k])[:400]}")
    for p in r.get("found_phrases", [])[:5]:
        lines.append(f"   ~ {p[:210]}")
    for t in r.get("titles", [])[:3]:
        lines.append(f"   T: {t}")
    return "\n".join(lines)


def main(urls, workers=8):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda u: _safe(u), urls))
    for r in results:
        print(summarize(r))
        print()
    (Path(__file__).parent / "last_probe.json").write_text(json.dumps(results, indent=1))


def _safe(u):
    try:
        return probe(u)
    except Exception as e:
        return {"url": u, "pages_ok": [], "pages_fail": {"/": f"crash:{e}"},
                "emails": [], "phones": [], "instagram": [], "years": [],
                "owner_hits": [], "cred_hits": [], "found_phrases": [],
                "rollup_hits": [], "titles": [], "facebook": []}


if __name__ == "__main__":
    main(sys.argv[1:])
