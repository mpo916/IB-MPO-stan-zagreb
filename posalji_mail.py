#!/usr/bin/env python3
"""Šalje dnevni e-mail s novim stanovima (data/ponuda_new_today.json), sortiranim po ocjeni.

Postavke se čitaju iz varijabli okruženja (u GitHubu: Settings > Secrets and variables > Actions):
  SMTP_USER   Gmail adresa s koje se šalje
  SMTP_PASS   Gmail "lozinka za aplikacije" (ne obična lozinka)
  SITE_URL    adresa web servisa (npr. https://korisnik.github.io/stan-zagreb/)
  MAIL_TO     primatelji odvojeni zarezom (čuva se kao tajna da adrese ne budu javne)
Ocjena koristi iste težine kao web servis (kriteriji su ovdje početni; promjene u web CMS-u
vrijede samo u pregledniku).
"""
import json
import os
import pathlib
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

C = {
    "min": 58, "max": 80, "opt": 100, "maxFloor": 6, "noLift": 1, "maxPrice": 380000,
    "p1": "Horvati, Jarun, Knežija, Srednjaci, Vrbani, Bundek, Središće, Cvjetno naselje, Kanal, Kruge, Martinovka, Savica, Sigečica, Trnje, Vrbik, Špansko, Trešnjevka, Rudeš",
    "p2": "Britanac, Centar, Gupčeva zvijezda, Ksaver, Medveščak, Pantovčak, Prekrižje, Ribnjak, Šalata, Tuškanac, Voćarsko naselje, Svetice, Lanište",
    "p3": "Mirogoj, Zelengaj, Donji Bukovac, Maksimir, Srebrnjak, Mlinovi, Šestine, Črnomerec, Bijenik, Sveti Duh, Šestinski dol, Vrhovec, Završje, Gračani",
}
P1, P2, P3 = ([x.strip().lower() for x in C[k].split(",")] for k in ("p1", "p2", "p3"))


def score(l):
    a = l["area"].lower()
    loc = 1 if a in P1 else .7 if a in P2 else .4 if a in P3 else .1
    m2 = l["m2"]
    size = 1 if C["min"] <= m2 <= C["max"] else .6 if C["max"] < m2 <= C["opt"] else .1
    fl = l.get("fl")
    fs = .5 if fl is None else 1 if (fl <= C["noLift"] or (fl <= C["maxFloor"] and l.get("lift"))) else 0
    yr = l.get("yr") or 0
    era = 1 if (yr >= 2021 or l.get("cond") == "Novogradnja") else .7 if yr >= 1970 else .4 if yr >= 1920 else .1
    ex = (.5 if l.get("balc") else 0) + (.5 if l.get("park") else 0)
    mp = C["maxPrice"]
    pr = 1 if not mp or l["price"] <= mp else .4 if l["price"] <= mp * 1.1 else 0
    return 1 + 4 * (.3 * loc + .25 * size + .15 * fs + .1 * era + .1 * ex + .1 * pr)


def eur(n):
    return f"{n:,.0f}".replace(",", ".") + " €"


def build():
    f = pathlib.Path("data/ponuda_new_today.json")
    rows = json.loads(f.read_text("utf-8")) if f.exists() else []
    for r in rows:
        r["sc"] = score(r)
    rows.sort(key=lambda r: (-r["sc"], r["pm"]))
    site = os.environ.get("SITE_URL", "")
    link = f'<p><a href="{escape(site)}">Otvori web servis</a></p>' if site else ""
    if not rows:
        return "Danas nema novih stanova", f"<p>Danas nema novih stanova koji odgovaraju prikupljenim izvorima.</p>{link}"
    tr = "".join(
        f"<tr><td><b>{r['sc']:.2f}</b></td><td>{escape(r['area'])}</td><td>{r['m2']:g} m²</td>"
        f"<td><b>{eur(r['price'])}</b></td><td>{eur(r['pm'])}</td>"
        f"<td><a href=\"{escape(r.get('url', ''))}\">{escape(r['ag'])}</a>{' (duplikat ' + r['dup'] + ')' if r.get('dup') else ''}</td>"
        f"<td>{escape(r.get('tel', ''))}</td></tr>"
        for r in rows[:40])
    body = (f"<p>Novih stanova danas: <b>{len(rows)}</b>, poredano od najbolje ocjene.</p>{link}"
            "<table border='1' cellpadding='6' style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
            "<tr><th>Ocjena</th><th>Kvart</th><th>m²</th><th>Cijena</th><th>€/m²</th><th>Agencija</th><th>Kontakt</th></tr>"
            f"{tr}</table>")
    return f"Stanovi u Zagrebu: {len(rows)} novih", body


def main():
    subject, body = build()
    to = os.environ["MAIL_TO"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["SMTP_USER"], to
    msg.set_content("Otvori poruku u HTML prikazu.")
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)
    print("Mail poslan:", subject)


if __name__ == "__main__":
    main()
