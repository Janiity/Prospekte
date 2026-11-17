#!/usr/bin/env python3
"""
Lädt jeden Montag die aktuellen Prospekte für 56470 Bad Marienberg herunter:
Lidl, Aldi Süd, REWE, Netto Marken-Discount, EDEKA.

Die Prospekt-URLs ändern sich wöchentlich. Deshalb werden sie bei jedem Lauf
neu ermittelt, nie fest eingetragen:

  * EDEKA:    Marktseite edeka.de/maerkte/070380/prospekte/ -> Blätterkatalog -> komplettes PDF
  * Lidl:     Prospekt-API endpoints.leaflets.schwarz -> PDF
  * Aldi Süd: aldi-sued.de/prospekte -> Link "kw<KW>-<JJ>..." -> PDF (Publitas)
  * REWE:     services.publitas.com/rewe/publications?week=<KW>&wwident=1761545 -> PDF
  * Netto:    netto-online.de Prospektseite für Filiale 6835 -> wochenprospekt... -> PDF
  * Reserve:  kaufDA-Händlerseite für Bad Marienberg (nur wenn die offizielle Quelle scheitert)

Ausgabe:  out/<JJJJ>-KW<ww>/<händler>/...  plus out/<JJJJ>-KW<ww>/index.json
Jede Quelle ist einzeln abgesichert: Fällt eine aus, laufen die anderen weiter.
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
CITY_SLUG = "Bad-Marienberg"          # kaufDA-Ortsname
EDEKA_MARKET_ID = "070380"            # EDEKA Steffen Osterkamp
REWE_MARKET_ID = "1761545"            # REWE Familie Hundertmark, An der Lehmkaute 2
NETTO_STORE_ID = "6835"               # Netto, Jahnstr. 9a
MAX_PAGES = int(os.environ.get("MAX_PAGES", "40"))   # max. Seiten je Prospekt
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))

# kaufDA-Händler-IDs (p-r<ID>). Fehlt eine ID oder stimmt sie nicht mehr,
# sucht das Skript sie auf der Ortsseite von kaufDA neu.
RETAILERS = {
    "lidl":     {"name": "Lidl",                  "kaufda": ("Lidl", 74),                   "match": r"lidl"},
    "aldi-sued": {"name": "ALDI SÜD",             "kaufda": ("Aldi-Sued", None),            "match": r"aldi[\s\-_]*s(ü|ue|u)d"},
    "rewe":     {"name": "REWE",                  "kaufda": ("REWE", 101),                  "match": r"rewe"},
    "netto":    {"name": "Netto Marken-Discount", "kaufda": ("Netto-Marken-Discount", 9),   "match": r"netto"},
    "edeka":    {"name": "EDEKA",                 "kaufda": ("EDEKA", 107),                 "match": r"edeka"},
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"})

TODAY = dt.date.today()
YEAR, WEEK, _ = TODAY.isocalendar()
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


def is_image(r):
    return r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 2000


def download_pages(url_for_page, dest: Path, prefix: str) -> list[str]:
    """Lädt Seite 1, 2, 3 ... bis eine Seite fehlt (oder MAX_PAGES erreicht)."""
    files = []
    for n in range(1, MAX_PAGES + 1):
        r = get(url_for_page(n))
        if not is_image(r):
            break
        ext = ".png" if "png" in r.headers.get("content-type", "") else ".jpg"
        f = dest / f"{prefix}_seite_{n:02d}{ext}"
        f.write_bytes(r.content)
        files.append(str(f))
    return files


# ------------------------------------------------------------------- EDEKA direkt
def fetch_edeka(dest: Path) -> dict:
    url = f"https://www.edeka.de/maerkte/{EDEKA_MARKET_ID}/prospekte/"
    html = get(url).text
    bases = sorted(set(re.findall(r"https://blaetterkatalog\.edeka\.de/[A-Za-z0-9_\-/]+?/(?=index\.html|blaetterkatalog/)", html)))
    if not bases:
        raise RuntimeError("Keine Blätterkatalog-Links auf der EDEKA-Marktseite gefunden")
    result = {"quelle": url, "prospekte": []}
    for base in bases:
        name = base.rstrip("/").split("/")[-1]
        # 1) Komplettes PDF (Option "Speichern als PDF -> Komplettes PDF" im Katalog)
        pdf_url = f"{base}blaetterkatalog/pdf/complete.pdf"
        r = get(pdf_url, timeout=180)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            f = dest / f"edeka_{name}.pdf"
            f.write_bytes(r.content)
            log(f"   EDEKA {name}: PDF ({len(r.content)//1024} KB)")
            result["prospekte"].append({"name": name, "pdf": pdf_url, "datei": str(f)})
            continue
        # 2) Reserve: einzelne Seitenbilder
        files = download_pages(lambda n: f"{base}blaetterkatalog/large/bk_{n}.jpg", dest, f"edeka_{name}")
        log(f"   EDEKA {name}: kein PDF, {len(files)} Seitenbilder")
        result["prospekte"].append({"name": name, "basis": base, "dateien": files})
    if not any(p.get("datei") or p.get("dateien") for p in result["prospekte"]):
        raise RuntimeError("EDEKA-Blätterkatalog gefunden, aber weder PDF noch Seitenbilder ladbar")
    return result


# -------------------------------------------------------------------- Lidl direkt
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
    url = "https://endpoints.leaflets.schwarz/v4/overview?client_locale=lidl/de-DE"
    data = get(url).json()
    flyers = []
    for d in _walk(data):
        pdf = d.get("pdfUrl")
        if not pdf:
            continue
        start = _date(d, "offerStartDate", "startDate")
        end = _date(d, "offerEndDate", "endDate")
        # nur Prospekte, die diese Woche gelten
        if start and start > TODAY + dt.timedelta(days=6):
            continue
        if end and end < TODAY:
            continue
        title = " ".join(str(d.get(k, "")) for k in ("name", "title", "subtitle"))
        flyers.append({"titel": title.strip(), "pdf": pdf, "von": str(start), "bis": str(end)})
    if not flyers:
        raise RuntimeError("Lidl-API lieferte keinen aktuellen Prospekt mit PDF")
    # Aktionsprospekt(e) zuerst, insgesamt max. 3 PDFs
    flyers.sort(key=lambda f: 0 if re.search(r"aktion|filial|lohnt", f["titel"], re.I) else 1)
    flyers = flyers[:3]
    for i, f in enumerate(flyers, 1):
        r = get(f["pdf"], timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            p = dest / f"lidl_prospekt_{i}.pdf"
            p.write_bytes(r.content)
            f["datei"] = str(p)
            log(f"   Lidl PDF {i}: {f['titel'][:60]} ({len(r.content)//1024} KB)")
    if not any("datei" in f for f in flyers):
        raise RuntimeError("Lidl-PDFs gefunden, aber nicht ladbar")
    return {"quelle": url, "prospekte": flyers}


# ------------------------------------------------- Publitas (Aldi Süd, REWE, Netto)
PDF_RE = re.compile(r"https?://[^\"'\s\\<>]+?/pdfs/[0-9a-f\-]+\.pdf[^\"'\s\\<>]*", re.I)


def publitas_pdf(viewer_url: str, dest: Path, filename: str) -> dict:
    """Öffnet einen Publitas-Prospekt und lädt das dort verlinkte PDF."""
    r = get(viewer_url, allow_redirects=True)
    if r.status_code != 200:
        raise RuntimeError(f"Prospektseite {viewer_url} antwortete mit {r.status_code}")
    m = PDF_RE.search(r.text)
    if not m:
        raise RuntimeError(f"Kein PDF-Link auf {r.url}")
    pdf_url = m.group(0).replace("&amp;", "&")
    p = get(pdf_url, timeout=180)
    if p.status_code != 200 or p.content[:4] != b"%PDF":
        raise RuntimeError(f"PDF nicht ladbar ({p.status_code})")
    f = dest / filename
    f.write_bytes(p.content)
    log(f"   PDF: {filename} ({len(p.content)//1024} KB) von {r.url}")
    return {"prospekt": r.url, "pdf": pdf_url, "datei": str(f)}


def fetch_aldi(dest: Path) -> dict:
    url = "https://www.aldi-sued.de/prospekte"
    html = get(url).text
    yy = f"{YEAR % 100:02d}"
    links = list(dict.fromkeys(re.findall(r"https://prospekt\.aldi-sued\.de/[a-z0-9\-]+", html, re.I)))
    week = [l for l in links if re.search(rf"/kw0?{WEEK}-{yy}\b", l, re.I)]
    if not week:
        raise RuntimeError(f"Kein Aldi-Prospekt für KW{WEEK} gefunden (Links: {links[:6]})")
    return {"quelle": url, "prospekte": [publitas_pdf(week[0], dest, f"aldi-sued_kw{WEEK:02d}.pdf")]}


def fetch_rewe(dest: Path) -> dict:
    viewer = (f"https://services.publitas.com/rewe/publications"
              f"?week={WEEK}&wwident={REWE_MARKET_ID}&feature=download")
    return {"quelle": viewer, "prospekte": [publitas_pdf(viewer, dest, f"rewe_kw{WEEK:02d}.pdf")]}


def fetch_netto(dest: Path) -> dict:
    url = f"https://www.netto-online.de/ueber-netto/Online-Prospekte.chtm?stores_id={NETTO_STORE_ID}"
    r = get(url)
    m = re.search(r"https://wochenprospekt\.netto-online\.de/[a-z0-9_\-]+/\?storeid=\d+", r.text, re.I)
    if not m:
        raise RuntimeError(f"Kein Netto-Wochenprospekt auf der Prospektseite (HTTP {r.status_code})")
    return {"quelle": url, "prospekte": [publitas_pdf(m.group(0), dest, f"netto_kw{WEEK:02d}.pdf")]}


# ----------------------------------------------------------------------- kaufDA
def kaufda_url(key: str) -> str:
    slug, rid = RETAILERS[key]["kaufda"]
    if rid:
        return f"https://www.kaufda.de/{CITY_SLUG}/{slug}/p-r{rid}"
    # ID unbekannt: auf Orts- und Discounter-Seite suchen
    pat = re.compile(rf"/{CITY_SLUG}/([^/\"']+)/p-r(\d+)")
    for page in (f"https://www.kaufda.de/{CITY_SLUG}",
                 f"https://www.kaufda.de/{CITY_SLUG}/Discounter/p-c5",
                 f"https://www.kaufda.de/{CITY_SLUG}/Supermarkt/p-c11"):
        html = get(page).text
        for s, i in pat.findall(html):
            if re.search(RETAILERS[key]["match"], s, re.I):
                return f"https://www.kaufda.de/{CITY_SLUG}/{s}/p-r{i}"
    raise RuntimeError(f"kaufDA-Seite für {key} in {CITY_SLUG} nicht gefunden")


def fetch_kaufda(key: str, dest: Path) -> dict:
    url = kaufda_url(key)
    r = get(url)
    if r.status_code != 200:
        raise RuntimeError(f"kaufDA antwortete mit {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    match = re.compile(RETAILERS[key]["match"], re.I)

    # 1) Angebotstexte der Seite sichern (Produkt, Marke, Preis ...)
    text = soup.get_text("\n", strip=True)
    (dest / f"{key}_kaufda_angebote.txt").write_text(text, encoding="utf-8")

    # 2) Prospekt-IDs aus den Vorschaubildern (content-media.bonial.biz/<uuid>/...)
    uuid_re = re.compile(r"content-media\.bonial\.biz/([0-9a-f\-]{36})/", re.I)
    ours, others = [], []
    for img in soup.find_all("img"):
        src = " ".join(filter(None, [img.get("src"), img.get("data-src"), img.get("srcset")]))
        m = uuid_re.search(src)
        if not m:
            continue
        label = " ".join(filter(None, [img.get("alt"), img.get("title")]))
        (ours if match.search(label) else others).append(m.group(1))
    if not ours and not others:   # Bilder evtl. nur im Skript-JSON
        others = uuid_re.findall(r.text)
    uuids = list(dict.fromkeys(ours or others[:1]))[:3]
    if not uuids:
        raise RuntimeError("Keine Prospekt-Bilder auf der kaufDA-Seite gefunden")

    prospekte = []
    for i, u in enumerate(uuids, 1):
        files = download_pages(
            lambda n: f"https://content-media.bonial.biz/{u}/zoomlarge_page_{n}.jpg",
            dest, f"{key}_kaufda_{i}")
        log(f"   {key} kaufDA-Prospekt {i} ({u[:8]}…): {len(files)} Seiten")
        prospekte.append({"id": u, "dateien": files, "zuordnung": "sicher" if ours else "geraten"})
    return {"quelle": url, "prospekte": prospekte}


# ------------------------------------------------------------------------ Ablauf
def main() -> int:
    WEEK_DIR.mkdir(parents=True, exist_ok=True)
    index = {"erstellt": dt.datetime.now().isoformat(timespec="seconds"),
             "kalenderwoche": f"{YEAR}-KW{WEEK:02d}", "ort": "56470 Bad Marienberg",
             "haendler": {}}

    plan = {
        "lidl":      [("lidl-api", fetch_lidl), ("kaufda", None)],
        "aldi-sued": [("aldi-direkt", fetch_aldi), ("kaufda", None)],
        "rewe":      [("rewe-direkt", fetch_rewe), ("kaufda", None)],
        "netto":     [("netto-direkt", fetch_netto), ("kaufda", None)],
        "edeka":     [("edeka-direkt", fetch_edeka), ("kaufda", None)],
    }

    for key, sources in plan.items():
        log(f"== {RETAILERS[key]['name']}")
        dest = WEEK_DIR / key
        dest.mkdir(exist_ok=True)
        entry = {"name": RETAILERS[key]["name"], "quellen": {}, "fehler": {}}
        for label, fn in sources:
            try:
                res = fn(dest) if fn else fetch_kaufda(key, dest)
                entry["quellen"][label] = res
                if any(p.get("dateien") or p.get("datei") for p in res.get("prospekte", [])):
                    break           # offizielle Quelle hat geklappt -> keine Reserve nötig
            except Exception as e:  # eine Quelle darf scheitern
                entry["fehler"][label] = f"{type(e).__name__}: {e}"
                log(f"   {label} fehlgeschlagen: {e}")
        entry["ok"] = any(
            p.get("dateien") or p.get("datei")
            for q in entry["quellen"].values() for p in q.get("prospekte", []))
        index["haendler"][key] = entry

    (WEEK_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = [k for k, v in index["haendler"].items() if v["ok"]]
    log(f"\nFertig: {len(ok)}/{len(plan)} Händler mit Prospekt ({', '.join(ok) or '-'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
