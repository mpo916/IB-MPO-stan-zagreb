#!/usr/bin/env python3
"""Eurovilla (eurovilla.hr) -> data/eurovilla_all.json + data/eurovilla_new_today.json

Prodaja stanova, Grad Zagreb. Pokreće se jednom dnevno (npr. u 5:00).
Pokretanje:  pip install requests beautifulsoup4 && python eurovilla_scraper.py
Napomena: skripta je pisana prema strukturi naslovnice i NIJE testirana na živoj stranici
pretrage. Ako nešto ne radi, pošalji ispis (log) pa ću prilagoditi.
"""
import datetime
import json
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://eurovilla.hr"
START = BASE + "/pretraga/prodaja-stan-zagreb/"
HEADERS = {"User-Agent": "Mozilla/5.0 (osobni alat za praćenje oglasa)", "Accept-Language": "hr"}
DELAY = 2.0           # sekunde između zahtjeva (budi pristojan prema stranici)
MAX_PAGES = 15
M2_MIN, M2_MAX = 50, 110   # unaprijed odbaci stanove izvan ovog raspona
AGENCY_PHONES = {"38514815111", "38598367582"}  # opći brojevi iz podnožja stranice

OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)
TODAY = datetime.date.today().isoformat()
session = requests.Session()
session.headers.update(HEADERS)


def get(url):
    time.sleep(DELAY)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def num(s):
    return float(s.replace(".", "").replace(",", ".")) if "," in s and "." in s else float(s.replace(",", "."))


def dedupe_title(title):
    w = title.split()
    n = len(w)
    return " ".join(w[: n // 2]) if n % 2 == 0 and w[: n // 2] == w[n // 2:] else title


def kvart(title):
    parts = [p.strip() for p in title.split(",")]
    return parts[1] if parts[0].lower() == "zagreb" and len(parts) > 1 else parts[0]


def parse_cards(soup):
    cards = {}
    for a in soup.select('a[href*="/nekretnina/"]'):
        href = a.get("href", "")
        m = re.search(r"/nekretnina/.+?/(\d+)/?$", href)
        text = a.get_text(" ", strip=True)
        price = re.search(r"Cijena:\s*€\s*([\d.]+)", text)
        area = re.search(r"Površina:\s*([\d.,]+)", text)
        if not (m and price and area):
            continue
        title = dedupe_title(text.split("Cijena:")[0].strip())
        cards[m.group(1)] = {
            "url": href if href.startswith("http") else BASE + href,
            "title": title,
            "price": int(price.group(1).replace(".", "")),
            "m2": num(area.group(1)),
        }
    return cards


def next_page(soup):
    a = soup.select_one("a[rel=next]")
    if not a:
        for x in soup.find_all("a"):
            if x.get_text(strip=True) in ("Sljedeća", "Dalje", "›", "»", "Next"):
                a = x
                break
    return (a["href"] if a.get("href", "").startswith("http") else BASE + a["href"]) if a and a.get("href") else None


def details(url):
    soup = get(url)
    text = soup.get_text(" ", strip=True)
    low = text.lower()
    phones = []
    for a in soup.select('a[href^="tel:"]'):
        d = re.sub(r"\D", "", a["href"])
        if d and d not in phones:
            phones.append(d)
    agent = [p for p in phones if p not in AGENCY_PHONES]
    tel = ("+" + (agent or phones)[0]) if phones else ""
    fl = None
    m = re.search(r"\bKat\b[:\s]+(Prizemlje|Suteren|\d+)", text, re.I)
    if m:
        fl = 0 if not m.group(1).isdigit() else int(m.group(1))
    yr = re.search(r"Godina izgradnje[:\s]+(\d{4})", text, re.I)
    neto = re.search(r"Neto površina[:\s]+([\d.,]+)", text, re.I)
    return {
        "tel": tel,
        "fl": fl,
        "lift": int("lift" in low and "bez lifta" not in low),
        "yr": int(yr.group(1)) if yr else 0,
        "balc": int(bool(re.search(r"balkon|lođa|loggia|terasa", low))),
        "park": int(bool(re.search(r"parking|parkirno|garaž", low))),
        "neto": num(neto.group(1)) if neto else None,
    }


def main():
    prev_file = OUT / "eurovilla_all.json"
    prev = {r["id"]: r for r in json.loads(prev_file.read_text("utf-8"))} if prev_file.exists() else {}

    url, seen_pages, cards = START, 0, {}
    while url and seen_pages < MAX_PAGES:
        soup = get(url)
        found = parse_cards(soup)
        if not set(found) - set(cards):
            break
        cards.update(found)
        seen_pages += 1
        url = next_page(soup)
    print(f"Ukupno kartica: {len(cards)} na {seen_pages} stranica")
    if len(cards) and seen_pages == 1:
        print("UPOZORENJE: pronađena samo jedna stranica; provjeri straničenje (next_page).")

    rows = []
    for cid, c in cards.items():
        rid = "ev-" + cid
        if rid in prev:
            r = prev[rid]
            r["price"] = c["price"]
        else:
            if not (M2_MIN <= c["m2"] <= M2_MAX):
                continue
            d = details(c["url"])
            m2 = d.pop("neto") or c["m2"]
            low = c["title"].lower()
            r = {
                "id": rid, "src": "eurovilla.hr", "ag": "Eurovilla", "url": c["url"], "title": c["title"],
                "area": kvart(c["title"]), "m2": m2, "price": c["price"],
                "cond": "Novogradnja" if "novogradnj" in low else "Za preuređenje" if "preuređenj" in low else "Nepoznato",
                "first_seen": TODAY, **d,
            }
        r["pm"] = round(r["price"] / r["m2"])
        rows.append(r)

    prev_file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    today = [r for r in rows if r["first_seen"] == TODAY]
    (OUT / "eurovilla_new_today.json").write_text(json.dumps(today, ensure_ascii=False, indent=1), "utf-8")
    print(f"Spremljeno {len(rows)} oglasa, od toga {len(today)} novih danas.")


if __name__ == "__main__":
    main()
