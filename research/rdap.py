#!/usr/bin/env python3
"""Domain creation date via RDAP (free, no auth). Usage: python3 rdap.py domain [domain...]"""
import json
import sys
import time
import urllib.parse

import requests

H = {"User-Agent": "ProspectResearch/1.0", "Accept": "application/rdap+json, application/json"}


def creation(domain):
    d = domain.lower().strip()
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    tld = d.rsplit(".", 1)[-1]
    urls = []
    if tld == "com":
        urls.append(f"https://rdap.verisign.com/com/v1/domain/{d}")
    elif tld == "net":
        urls.append(f"https://rdap.verisign.com/net/v1/domain/{d}")
    urls.append(f"https://rdap.org/domain/{d}")
    for u in urls:
        try:
            r = requests.get(u, headers=H, timeout=20)
            if r.status_code != 200:
                continue
            j = r.json()
            for ev in j.get("events", []):
                if ev.get("eventAction") == "registration":
                    return d, ev.get("eventDate", "")[:10]
        except Exception:
            continue
        finally:
            time.sleep(0.4)
    return d, ""


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        dom, date = creation(arg)
        print(f"{dom}\t{date or 'NOT_FOUND'}")
