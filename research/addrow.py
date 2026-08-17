#!/usr/bin/env python3
"""Append rows to prospects.csv / rejected.csv from a JSON batch file.

Builds the Meta Ad Library URL automatically and enforces the column order.
Dedupes on phone, then domain, then fuzzy name.

Usage: python3 addrow.py batch.json
JSON: {"prospects":[{...}], "rejected":[{"business_name":..,"city":..,"reason":..}]}
"""
import csv
import difflib
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCSV = ROOT / "prospects.csv"
RCSV = ROOT / "rejected.csv"

COLS = ["business_name", "owner_name", "owner_role", "phone", "email", "email_type",
        "city", "metro", "state", "website", "instagram", "est_year", "age_source",
        "ad_library_url", "locations", "notes"]

ROLES = {"owner", "founder", "co-owner", "owner_np", "owner_rn",
         "medical_director_unverified", "unknown", ""}
ETYPES = {"direct", "general", ""}
ASOURCES = {"website", "whois", "first_google_review", "state_registry",
            "instagram_first_post", "bbb", ""}


def adlib(name):
    q = urllib.parse.quote_plus(name)
    return ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
            f"&country=US&q={q}&search_type=keyword_unordered")


def norm_phone(p):
    d = re.sub(r"\D", "", p or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else (p or "")


def domain(url):
    if not url:
        return ""
    u = url.lower().replace("https://", "").replace("http://", "")
    u = u.split("/")[0]
    return u[4:] if u.startswith("www.") else u


def norm_name(n):
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def load_existing():
    rows = []
    if PCSV.exists():
        with PCSV.open() as f:
            rows = list(csv.DictReader(f))
    return rows


def main(path):
    batch = json.loads(Path(path).read_text())
    existing = load_existing()
    ex_phones = {re.sub(r"\D", "", r["phone"]) for r in existing if r.get("phone")}
    ex_doms = {domain(r["website"]) for r in existing if r.get("website")}
    ex_names = [norm_name(r["business_name"]) for r in existing]

    added, skipped, problems = [], [], []
    new_rows = []
    for p in batch.get("prospects", []):
        r = {c: str(p.get(c, "") or "").strip() for c in COLS}
        if not r["business_name"]:
            problems.append("row with no business_name")
            continue
        r["phone"] = norm_phone(r["phone"])
        if r["owner_role"] not in ROLES:
            problems.append(f"{r['business_name']}: bad owner_role {r['owner_role']!r}")
        if r["email_type"] not in ETYPES:
            problems.append(f"{r['business_name']}: bad email_type {r['email_type']!r}")
        if r["age_source"] not in ASOURCES:
            problems.append(f"{r['business_name']}: bad age_source {r['age_source']!r}")
        if r["email"] and not r["email_type"]:
            problems.append(f"{r['business_name']}: email without email_type")
        if r["owner_name"] and not r["owner_role"]:
            problems.append(f"{r['business_name']}: owner_name without role")
        if not r["est_year"] or not r["age_source"]:
            problems.append(f"{r['business_name']}: missing est_year/age_source")
        # dedupe
        ph = re.sub(r"\D", "", r["phone"])
        dm = domain(r["website"])
        nm = norm_name(r["business_name"])
        why = None
        if ph and ph in ex_phones:
            why = "dup phone"
        elif dm and dm in ex_doms:
            why = "dup domain"
        else:
            close = difflib.get_close_matches(nm, ex_names, n=1, cutoff=0.92)
            if close:
                why = f"dup name ~{close[0]}"
        if why:
            skipped.append(f"{r['business_name']} ({why})")
            continue
        if not r["ad_library_url"]:
            r["ad_library_url"] = adlib(r["business_name"])
        if ph:
            ex_phones.add(ph)
        if dm:
            ex_doms.add(dm)
        ex_names.append(nm)
        new_rows.append(r)
        added.append(r["business_name"])

    if new_rows:
        with PCSV.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, quoting=csv.QUOTE_MINIMAL)
            for r in new_rows:
                w.writerow(r)

    rej = batch.get("rejected", [])
    if rej:
        with RCSV.open("a", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            for x in rej:
                w.writerow([x.get("business_name", ""), x.get("city", ""),
                            x.get("reason", "")])

    total = len(load_existing())
    print(f"added {len(added)} | skipped {len(skipped)} | rejected+{len(rej)} | total {total}")
    for s in skipped:
        print("  SKIP:", s)
    for p in problems:
        print("  WARN:", p)


if __name__ == "__main__":
    main(sys.argv[1])
