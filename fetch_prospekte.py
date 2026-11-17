#!/usr/bin/env python3
"""
Lädt jeden Montag die aktuellen Prospekte für 56470 Bad Marienberg als PDF:
Lidl, Aldi Süd, REWE, Netto Marken-Discount, EDEKA.

Die Prospekt-URLs ändern sich wöchentlich. Deshalb werden sie bei jedem Lauf
neu ermittelt. Jede Quelle hat einen Ersatzweg, falls die Händler-Webseite
Zugriffe von GitHub-Servern blockiert:

  * Lidl:     Prospekt-API mit Filiale DE06535 (Jahnstraße 40) -> PDF
  * Aldi Süd: aldi-sued.de/prospekte -> "kw<KW>-<JJ>..."; Ersatz: bekannte Namensmuster
  * REWE:     services.publitas.com/rewe/publications?week=<KW>&wwident=1761545 -> PDF
  * Netto:    netto-online.de für Filiale 6835; Ersatz: wochenprospekt.../hz<KW>_<Region>/
  * EDEKA:    Marktseite 070380 -> Blätterkatalog -> complete.pdf; Ersatz: bekannte Katalogordner
  * kaufDA:   nur noch Angebotstexte als letzte Notlösung (zählt nicht als Erfolg)

Ausgabe:  out/<JJJJ>-KW<ww>/<händler>/...  plus out/<JJJJ>-KW<ww>/index.json
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------- Einstellungen
CITY_SLUG = "Bad-Marienberg"                 # kaufDA-Ortsname
LIDL_STORE_ID = "DE06535"                    # Lidl, Jahnstraße 40
EDEKA_MARKET_ID = "070380"                   # EDEKA Steffen Osterkamp
EDEKA_KATALOGE = ["RHEINRUHR/0380", "RHEINRUHR/SUUPER_Angebote"]   # Ersatz, falls Marktseite blockt
REWE_MARKET_ID = "1761545"                   # REWE Familie Hundertmark, An der Lehmkaute 2
NETTO_STORE_ID = "6835"                      # Netto, Jahnstr. 9a
NETTO_REGION = "kess"                        # Regionalausgabe dieser Filiale (hz<KW>_kess)
ALDI_SUFFIXE = ["op-mp", "op", "vop", "mp", ""]   # Ersatz: übliche Namensendungen
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))

RETAILERS = {
    "lidl":      {"name": "Lidl",                  "kaufda": ("Lidl", 74)},
    "aldi-sued": {"name": "ALDI SÜD",              "kaufda": ("ALDI-SUeD", 90)},
    "rewe":      {"name": "REWE",                  "kaufda": ("REWE", 101)},
    "netto":     {"name": "Netto Marken-Discount", "kaufda": ("Netto-Marken-Discount", 9)},
    "edeka":     {"name": "EDEKA",                 "kaufda": ("EDEKA", 107)},
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9",
                  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})

TODAY = dt.date.today()
YEAR, WEEK, _ = TODAY.isocalendar()
YY = f"{YEAR % 100:02d}"
WEEK_DIR = OUT_DIR / f"{YEAR}-KW{WEEK:02d}"


def log(*a):
    print(*a, flush=True)


def get(url, **kw):
    kw.setdefault("timeout", 30)
    for attempt in range(3):
        try:
            r = S.get(url, **kw)
            if r.status_code in (429, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return r
        except requests.RequestException as e:
            if attempt == 2:
                raise
            log(f"   Wiederhole nach Fehler: {e}")
            time.sleep(3)
    return r


def save_pdf(url: str, dest: Path, filename: str) -> dict | None:
    """Lädt ein PDF; gibt None zurück, wenn unter der Adresse kein PDF liegt."""
    r = get(url, timeout=240)
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return None
    f = dest / filename
    f.write_bytes(r.content)
    log(f"   PDF: {filename} ({len(r.content) // 1024} KB)")
    return {"pdf": url, "datei": str(f)}


# ------------------------------------------------- Publitas (Aldi Süd, REWE, Netto)
PDF_RE = re.compile(r"https?://[^\"'\s\\<>]+?/pdfs/[0-9a-f\-]+\.pdf[^\"'\s\\<>]*", re.I)


def publitas_pdf(viewer_url: str, dest: Path, filename: str) -> dict:
    """Öffnet einen Publitas-Prospekt und lädt das dort verlinkte PDF."""
    r = get(viewer_url, allow_redirects=True)
    if r.status_code != 200:
        raise RuntimeError(f"{viewer_url} -> HTTP {r.status_code}")
    m = PDF_RE.search(r.text)
    if not m:
        raise RuntimeError(f"Kein PDF-Link auf {r.url}")
    res = save_pdf(m.group(0).replace("&amp;", "&"), dest, filename)
    if not res:
        raise RuntimeError(f"PDF-Link auf {r.url} lieferte kein PDF")
    res["prospekt"] = r.url
    return res


# ------------------------------------------------------------------------- Lidl
def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _date(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
            return dt.date.fromisoformat(v[:10])
    return None


def fetch_lidl(dest: Path) -> dict:
    # store_id filtert auf die Prospekte dieser Filiale (sonst ~40 Regionalausgaben)
    url = f"https://endpoints.leaflets.schwarz/v4/overview?client_locale=lidl/de-DE&store_id={LIDL_STORE_ID}"
    r = get(url)
    if r.status_code != 200:
        raise RuntimeError(f"Lidl-API -> HTTP {r.status_code}")
    candidates = []
    for d in _walk(r.json()):
        if not d.get("pdfUrl") or d.get("name") != "Aktionsprospekt":
            continue
        start = _date(d, "offerStartDate", "startDate")
        end = _date(d, "offerEndDate", "endDate")
        # Montag früh: der Prospekt, der diese Woche gilt (nicht die Vorschau auf nächste Woche)
        if start and end and start <= TODAY + dt.timedelta(days=1) and end >= TODAY:
            candidates.append((start, d))
    if not candidates:
        raise RuntimeError("Lidl-API: kein Aktionsprospekt für diese Woche")
    start, d = max(candidates, key=lambda c: c[0])
    res = save_pdf(d.get("hiResPdfUrl") or d["pdfUrl"], dest, f"lidl_kw{WEEK:02d}.pdf")
    if not res:
        raise RuntimeError("Lidl-PDF nicht ladbar")
    res["titel"] = f"{d.get('name')} {d.get('title')}"
    return {"quelle": url, "prospekte": [res]}


# --------------------------------------------------------------------- Aldi Süd
def fetch_aldi(dest: Path) -> dict:
    url = "https://www.aldi-sued.de/prospekte"
    tried, note = [], ""
    try:
        r = get(url)
        links = list(dict.fromkeys(re.findall(r"https://prospekt\.aldi-sued\.de/[a-z0-9\-]+", r.text, re.I)))
        tried = [l for l in links if re.search(rf"/kw0?{WEEK}-{YY}\b", l, re.I)]
        note = f"Übersicht HTTP {r.status_code}, {len(links)} Links"
    except requests.RequestException as e:
        note = f"Übersicht nicht erreichbar: {e}"
    # Ersatz: übliche Namensmuster direkt beim Prospekt-Server probieren
    for suf in ALDI_SUFFIXE:
        cand = f"https://prospekt.aldi-sued.de/kw{WEEK}-{YY}" + (f"-{suf}" if suf else "")
        if cand not in tried:
            tried.append(cand)
    errors = []
    for viewer in tried:
        try:
            res = publitas_pdf(viewer, dest, f"aldi-sued_kw{WEEK:02d}.pdf")
            return {"quelle": url, "hinweis": note, "prospekte": [res]}
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(f"{note}; nichts gefunden: {errors[:4]}")


# ------------------------------------------------------------------------- REWE
def fetch_rewe(dest: Path) -> dict:
    viewer = (f"https://services.publitas.com/rewe/publications"
              f"?week={WEEK}&wwident={REWE_MARKET_ID}&feature=download")
    return {"quelle": viewer, "prospekte": [publitas_pdf(viewer, dest, f"rewe_kw{WEEK:02d}.pdf")]}


# ------------------------------------------------------------------------ Netto
def fetch_netto(dest: Path) -> dict:
    url = f"https://www.netto-online.de/ueber-netto/Online-Prospekte.chtm?stores_id={NETTO_STORE_ID}"
    viewers, note = [], ""
    try:
        r = get(url)
        m = re.search(r"https://wochenprospekt\.netto-online\.de/[a-z0-9_\-]+/\?storeid=\d+", r.text, re.I)
        if m:
            viewers.append(m.group(0))
        note = f"netto-online.de HTTP {r.status_code}"
    except requests.RequestException as e:
        note = f"netto-online.de nicht erreichbar: {e}"
    # Ersatz: Prospekt-Server direkt (Regionalausgabe der Filiale)
    viewers.append(f"https://wochenprospekt.netto-online.de/hz{WEEK}_{NETTO_REGION}/?storeid={NETTO_STORE_ID}")
    errors = []
    for v in dict.fromkeys(viewers):
        try:
            return {"quelle": url, "hinweis": note,
                    "prospekte": [publitas_pdf(v, dest, f"netto_kw{WEEK:02d}.pdf")]}
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(f"{note}; {errors}")


# ------------------------------------------------------------------------ EDEKA
def fetch_edeka(dest: Path) -> dict:
    url = f"https://www.edeka.de/maerkte/{EDEKA_MARKET_ID}/prospekte/"
    bases, note = [], ""
    try:
        r = get(url)
        bases = re.findall(r"https://blaetterkatalog\.edeka\.de/([A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+)/(?:index\.html|blaetterkatalog/)", r.text)
        note = f"Marktseite HTTP {r.status_code}, {len(set(bases))} Kataloge"
    except requests.RequestException as e:
        note = f"Marktseite nicht erreichbar: {e}"
    bases = list(dict.fromkeys(bases or EDEKA_KATALOGE))
    prospekte = []
    for b in bases:
        name = b.split("/")[-1]
        res = save_pdf(f"https://blaetterkatalog.edeka.de/{b}/blaetterkatalog/pdf/complete.pdf",
                       dest, f"edeka_{name}_kw{WEEK:02d}.pdf")
        if res:
            res["name"] = name
            prospekte.append(res)
    if not prospekte:
        raise RuntimeError(f"{note}; kein complete.pdf ladbar für {bases}")
    return {"quelle": url, "hinweis": note, "prospekte": prospekte}


# ----------------------------------------------------------------------- kaufDA
def fetch_kaufda_text(key: str, dest: Path) -> dict:
    """Notlösung: nur die Angebotstexte der kaufDA-Seite speichern."""
    slug, rid = RETAILERS[key]["kaufda"]
    url = f"https://www.kaufda.de/{CITY_SLUG}/{slug}/p-r{rid}"
    r = get(url)
    if r.status_code != 200:
        raise RuntimeError(f"kaufDA -> HTTP {r.status_code}")
    text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
    f = dest / f"{key}_kaufda_angebote.txt"
    f.write_text(text, encoding="utf-8")
    return {"quelle": url, "textdatei": str(f)}


# ------------------------------------------------------------------------ Ablauf
def main() -> int:
    WEEK_DIR.mkdir(parents=True, exist_ok=True)
    index = {"erstellt": dt.datetime.now().isoformat(timespec="seconds"),
             "kalenderwoche": f"{YEAR}-KW{WEEK:02d}", "ort": "56470 Bad Marienberg",
             "haendler": {}}
    plan = {"lidl": fetch_lidl, "aldi-sued": fetch_aldi, "rewe": fetch_rewe,
            "netto": fetch_netto, "edeka": fetch_edeka}

    for key, fn in plan.items():
        log(f"== {RETAILERS[key]['name']}")
        dest = WEEK_DIR / key
        dest.mkdir(exist_ok=True)
        entry = {"name": RETAILERS[key]["name"], "ok": False, "fehler": None}
        try:
            entry.update(fn(dest))
            entry["ok"] = True
        except Exception as e:
            entry["fehler"] = f"{type(e).__name__}: {e}"
            log(f"   fehlgeschlagen: {e}")
            try:
                entry["notloesung"] = fetch_kaufda_text(key, dest)
                log("   kaufDA-Angebotstexte als Notlösung gespeichert")
            except Exception as e2:
                entry["notloesung"] = f"auch kaufDA fehlgeschlagen: {e2}"
        index["haendler"][key] = entry

    (WEEK_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = [k for k, v in index["haendler"].items() if v["ok"]]
    log(f"\nFertig: {len(ok)}/{len(plan)} Händler mit PDF ({', '.join(ok) or '-'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
