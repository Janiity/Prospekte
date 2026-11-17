# Prospekte Bad Marienberg

Lädt jeden Montag früh die aktuellen Prospekte von **Lidl, Aldi Süd, REWE, Netto und EDEKA**
für 56470 Bad Marienberg und legt sie auf dem Branch `prospekte` ab.

Die Prospekt-URLs wechseln jede Woche. Deshalb ermittelt das Skript sie bei jedem Lauf neu:

| Händler  | Offizielle Quelle (Filiale)                                 | Ersatzweg, falls die Seite GitHub blockt |
|----------|-------------------------------------------------------------|------------------------------------------|
| Lidl     | Lidl-Prospekt-API, Filiale DE06535 (Jahnstraße 40)          | –                                        |
| Aldi Süd | aldi-sued.de/prospekte → „kw<KW>-<JJ>…“                     | Prospekt-Server direkt (bekannte Namen)  |
| REWE     | REWE-Prospekt für Markt 1761545 (An der Lehmkaute 2)        | –                                        |
| Netto    | netto-online.de, Filiale 6835 (Jahnstr. 9a)                 | wochenprospekt…/hz<KW>_kess              |
| EDEKA    | Marktseite 070380 (Osterkamp) → Blätterkatalog „Komplettes PDF“ | bekannte Katalogordner 0380 / SUUPER_Angebote |

Alles kommt als PDF. Scheitert ein Händler komplett, werden nur die kaufDA-Angebotstexte als Notlösung gespeichert.

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
  index.json        Übersicht: was geklappt hat, Hinweise und Fehler
  lidl/       lidl_kw47.pdf
  aldi-sued/  aldi-sued_kw47.pdf
  rewe/       rewe_kw47.pdf
  netto/      netto_kw47.pdf
  edeka/      edeka_0380_kw47.pdf, edeka_SUUPER_Angebote_kw47.pdf
```

## Hinweise

* Wenn ein Händler seine Seite umbaut, scheitert nur dieser eine Händler; die anderen laufen weiter.
  `index.json` zeigt im Feld `fehler`, was schiefging.
* GitHub pausiert geplante Workflows in Repos, in denen 60 Tage lang nichts passiert. Falls das
  passiert, unter **Actions** einfach wieder aktivieren.
* Die Daten stammen von den Händlerseiten bzw. kaufDA und sind nur für den privaten Gebrauch gedacht.
