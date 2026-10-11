#!/usr/bin/env python3
"""Opereta + okvir za ostale agencije + spajanje svih izvora (s oznakom duplikata).

Pokretanje:   pip install requests beautifulsoup4
              python eurovilla_scraper.py
              python agencije_scraper.py
Dijagnostika: DEBUG=1 python agencije_scraper.py   (sprema sirovi HTML u mapu debug/)
Izlaz:        data/<agencija>_all.json, data/ponuda.json (svi izvori), data/ponuda_new_today.json
NAPOMENA: pisano prema strukturi stranice pretrage Opereta; nije testirano uživo.
"""
import datetime
import json
import os
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (osobni alat za praćenje oglasa)", "Accept-Language": "hr"}
DELAY = 2.0
MAX_PAGES = 8
M2_MIN, M2_MAX = 50, 110
TODAY = datetime.date.today().isoformat()
OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)
session = requests.Session()
session.headers.update(HEADERS)


def get(url):
    time.sleep(DELAY)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    if os.environ.get("DEBUG"):
        d = pathlib.Path("debug")
        d.mkdir(exist_ok=True)
        (d / (re.sub(r"\W+", "_", url)[-80:] + ".html")).write_text(r.text, "utf-8")
    return BeautifulSoup(r.text, "html.parser")


def num(s):
    s = s.strip()
    if "," in s and "." in s:
        return float(s.replace(".", "").replace(",", "."))
    return float(s.replace(",", "."))


def details(url, general_phones):
    """Telefon, kat, lift, godina, balkon, parking, neto površina s stranice oglasa."""
    soup = get(url)
    text = soup.get_text(" ", strip=True)
    low = text.lower()
    phones = []
    for a in soup.select('a[href^="tel:"]'):
        d = re.sub(r"\D", "", a["href"])
        if d and d not in phones:
            phones.append(d)
    agent = [p for p in phones if p not in general_phones]
    tel = ("+" + (agent or phones)[0]) if phones else ""
    fl = None
    m = re.search(r"\bKat\b[:\s]+(Prizemlje|Suteren|\d+)", text, re.I)
    if m:
        fl = int(m.group(1)) if m.group(1).isdigit() else 0
    yr = re.search(r"Godina izgradnje[:\s]+(\d{4})", text, re.I)
    neto = re.search(r"Neto površina[:\s]+([\d.,]+)", text, re.I)
    return {
        "tel": tel,
        "fl": fl,
        "lift": int(("lift" in low or "dizalo" in low) and "bez lifta" not in low),
        "yr": int(yr.group(1)) if yr else 0,
        "balc": int(bool(re.search(r"balkon|lođa|loggia|terasa", low))),
        "park": int(bool(re.search(r"parking|parkirno|garaž", low))),
        "neto": num(neto.group(1)) if neto else None,
    }


# ---------------------------------------------------------------- Opereta
OPERETA_BASE = "https://www.opereta.hr"
OPERETA_PHONES = {"38513820050", "385428445588", "385214455588", "38552600006", "3858001177"}


def opereta_cards(soup):
    """Kartica: 'Trešnjevka - Sjever, Trešnjevka Stan, 55 m2 250.000 €'. Stranica miješa vrste i gradove
    pa filtriramo po adresi oglasa: samo prodaja stana u Gradu Zagrebu."""
    cards = {}
    for a in soup.select('a[href*="/nekretnina/stan/"]'):
        href = a.get("href", "")
        m = re.search(r"/nekretnina/stan/(\d+)-prodaja-stan-(.*)", href)
        if not m or "grad-zagreb" not in m.group(2):
            continue
        t = re.sub(r"\s+", " ", re.sub(r"OPERETA\s*\d+", "", a.get_text(" ", strip=True)))
        x = re.search(r"^(.*?)\s*Stan,\s*([\d.,]+)\s*m\s*[2²]\s*([\d.]+)\s*€", t)
        if not x:
            continue
        loc = [p.strip() for p in x.group(1).split(",") if p.strip()]
        cards[m.group(1)] = {
            "url": href if href.startswith("http") else OPERETA_BASE + href,
            "title": t,
            "area": loc[-1] if loc else "",   # npr. 'Trešnjevka - Sjever, Rudeš' -> 'Rudeš'
            "m2": num(x.group(2)),
            "price": int(x.group(3).replace(".", "")),
        }
    return cards


AGENCIJE = [
    {"key": "opereta", "ag": "Opereta nekretnine", "src": "opereta.hr",
     "list_url": OPERETA_BASE + "/nekretnine/stan/grad-zagreb",
     "cards": opereta_cards, "phones": OPERETA_PHONES},
    # TODO Regent, Roel, Bonus: dodati nakon što potvrdimo adrese stranica s ponudom
    # {"key": "regent", "ag": "Regent Real Estate", "src": "regent.hr", "list_url": "...", "cards": ..., "phones": set()},
]


def collect(cfg):
    f = OUT / f"{cfg['key']}_all.json"
    prev = {r["id"]: r for r in json.loads(f.read_text("utf-8"))} if f.exists() else {}
    cards = {}
    for p in range(1, MAX_PAGES + 1):
        url = cfg["list_url"] if p == 1 else f"{cfg['list_url']}?page={p}"
        try:
            found = cfg["cards"](get(url))
        except requests.RequestException as e:
            print(f"[{cfg['key']}] greška na {url}: {e}")
            break
        print(f"[{cfg['key']}] stranica {p}: {len(found)} stanova")
        if not set(found) - set(cards):
            break
        cards.update(found)
    if len(cards) == 0:
        print(f"[{cfg['key']}] UPOZORENJE: nije pronađen nijedan oglas, pokreni s DEBUG=1 i pošalji mi ispis.")
    elif p == 1 or len(cards) <= 14:
        print(f"[{cfg['key']}] provjeri straničenje: možda postoje stranice koje skripta ne vidi.")

    rows = []
    for cid, c in cards.items():
        rid = f"{cfg['key']}-{cid}"
        if rid in prev:
            r = prev[rid]
            r["price"] = c["price"]
        else:
            if not (M2_MIN <= c["m2"] <= M2_MAX):
                continue
            d = details(c["url"], cfg["phones"])
            m2 = d.pop("neto") or c["m2"]
            low = c["title"].lower()
            r = {"id": rid, "src": cfg["src"], "ag": cfg["ag"], "url": c["url"], "title": c["title"],
                 "area": c["area"], "m2": m2, "price": c["price"],
                 "cond": "Novogradnja" if "novogradnj" in low else "Nepoznato",
                 "first_seen": TODAY, **d}
        r["pm"] = round(r["price"] / r["m2"])
        rows.append(r)
    f.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    print(f"[{cfg['key']}] spremljeno {len(rows)} oglasa")


def merge():
    """Spaja sve izvore; isti stan u različitim izvorima dobiva zajedničku oznaku 'dup' (D1, D2...)."""
    rows = []
    for f in sorted(OUT.glob("*_all.json")):
        rows += json.loads(f.read_text("utf-8"))
    for r in rows:
        r["dup"] = ""
    gid = 0
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if (a["src"] != b["src"] and a["area"].lower() == b["area"].lower()
                    and abs(a["m2"] - b["m2"]) <= 1.5 and abs(a["price"] - b["price"]) <= 0.08 * a["price"]):
                if not a["dup"]:
                    gid += 1
                    a["dup"] = f"D{gid}"
                b["dup"] = a["dup"]
    (OUT / "ponuda.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    today = [r for r in rows if r["first_seen"] == TODAY]
    (OUT / "ponuda_new_today.json").write_text(json.dumps(today, ensure_ascii=False, indent=1), "utf-8")
    print(f"Ukupno {len(rows)} oglasa, {len(today)} novih danas, {gid} skupina duplikata.")


if __name__ == "__main__":
    for cfg in AGENCIJE:
        collect(cfg)
    merge()
