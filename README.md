# Prospekte Bad Marienberg

Lädt jeden Montag früh die aktuellen Prospekte von **Lidl, Aldi Süd, REWE, Netto und EDEKA**
für 56470 Bad Marienberg und legt sie auf dem Branch `prospekte` ab.

Die Prospekt-URLs wechseln jede Woche. Deshalb ermittelt das Skript sie bei jedem Lauf neu:

| Händler  | Offizielle Quelle                                                     | Ergebnis   | Reserve |
|----------|------------------------------------------------------------------------|------------|---------|
| EDEKA    | edeka.de, Markt 070380 (Osterkamp) → Blätterkatalog „Komplettes PDF“  | PDF        | Seitenbilder, kaufDA |
| Lidl     | Lidl-Prospekt-API                                                      | PDF        | kaufDA  |
| Aldi Süd | aldi-sued.de/prospekte → Prospekt „kw<KW>-<JJ>…“                       | PDF        | kaufDA  |
| REWE     | REWE-Prospekt für Markt 1761545 (An der Lehmkaute 2)                   | PDF        | kaufDA  |
| Netto    | netto-online.de, Filiale 6835 (Jahnstr. 9a) → Wochenprospekt           | PDF        | kaufDA  |

kaufDA wird nur genutzt, wenn die offizielle Quelle in dieser Woche scheitert.

## Einrichtung

1. Auf GitHub ein neues **privates** Repository anlegen, z. B. `prospekte-bad-marienberg`.
2. Diese Dateien hochladen (Struktur beibehalten):
   ```
   fetch_prospekte.py
   requirements.txt
   README.md
   .github/workflows/prospekte.yml
   ```
3. Unter **Settings → Actions → General → Workflow permissions** „Read and write permissions“ wählen.
4. Unter **Actions → Prospekte Bad Marienberg → Run workflow** einmal von Hand starten.
   Danach sollte es den Branch `prospekte` mit dem Ordner `<JJJJ>-KW<ww>/` und der Datei `index.json` geben.

## Ergebnis

```
<JJJJ>-KW<ww>/
  index.json                 Übersicht: welche Quelle hat geklappt, welche nicht
  lidl/       lidl_prospekt_1.pdf
  aldi-sued/  aldi-sued_kw47.pdf
  rewe/       rewe_kw47.pdf
  netto/      netto_kw47.pdf
  edeka/      edeka_0380.pdf, edeka_SUUPER_Angebote.pdf
```

## Hinweise

* Wenn ein Händler seine Seite umbaut, scheitert nur dieser eine Händler; die anderen laufen weiter.
  `index.json` zeigt im Feld `fehler`, was schiefging.
* `MAX_PAGES` im Workflow begrenzt die Seiten je Prospekt (Standard 40).
* GitHub pausiert geplante Workflows in Repos, in denen 60 Tage lang nichts passiert. Falls das
  passiert, unter **Actions** einfach wieder aktivieren.
* Die Daten stammen von den Händlerseiten bzw. kaufDA und sind nur für den privaten Gebrauch gedacht.
