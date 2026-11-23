# saalburg-katalog – Anleitung für Claude

Öffentlicher App-Katalog von **Saalburg** (ein eigenes Linux-System mit Claude Code). Antworte auf Deutsch. Keine Namen, Geräte oder Orte des Eigentümers in Dateien, PRs oder Commits. Formate, `app.conf`-Angaben und der Bau stehen in
`README.md` – zuerst lesen. Was eine App auf Saalburg vorfindet und darf (Umgebung, Sandbox,
Wayland, GPU, Ton, Lebenszyklus, Claude-Anbindung, Bibliotheken, Mindestversion), steht in
`PLATTFORM.md` – vor dem Bauen einer App lesen.

## Grundregeln

- **Alles hier ist öffentlich.** Keine privaten Programme, keine Schlüssel,
  Tokens oder Zugangsdaten, keine privaten Daten in Texten oder Bildern (Namen, Nummern,
  Chats, Kontodaten, QR-Codes zum Anmelden).
- **Ablauf:** Branch `claude/<kennung>`, Pull Request gegen `main`, **nicht selbst
  zusammenführen** – das entscheidet der Eigentümer. Signiert wird nur durch den GitHub-Ablauf
  „Katalog bauen“; nie selbst Pakete signieren oder `veroeffentlicht` anfassen.
- Bei jeder Änderung an einer App `version` in `app.conf` erhöhen.
- `saalburg = JJJJMMTTHHMM` setzen, wenn die App eine bestimmte Saalburg-Version braucht
  (z. B. Saalburg-Aussehen für Web-Apps: ab `202611221801`). Die passende Nummer steht in `PLATTFORM.md` (Versionstabelle).
- Dateien tauschen Apps nur über ihren Ordner „Dokumente“ und den Dateidienst aus; keine
  gemeinsamen Ordner per `ordner =` für den Austausch mit anderen Apps oder mit Claude.
- Steuerung durch Claude nur über die Saalburg-Verbindung (`steuerung = claude`,
  `verbindung = <MCP-Server>`); sie ist aus, bis der Eigentümer sie einschaltet.

## Web-Apps: Saalburg-Aussehen

- Optional `apps/<kennung>/aussehen.css` (und nur wenn nötig `aussehen.js`). Saalburg lädt
  daraus eine Erweiterung ohne Rechte, nur für den Host der App; der Nutzer kann sie in den
  Einstellungen abschalten („An Saalburg angleichen“).
- Alle Farben und Schriften kommen zentral aus Saalburgs `saalburg.css` als
  `var(--saalburg-…)`. Im `aussehen.css` **keine eigenen Farbwerte** (`#…`, `rgb()`, `rgba()`,
  `hsl()`, Farbnamen außer `transparent`/`currentColor`/`inherit`) und **keine eigene
  `font-family`/`@font-face`** – nur Saalburg-Variablen, höchstens mit allgemeiner
  Ersatzfamilie als Rückfall, z. B. `var(--saalburg-schrift-text, sans-serif)`.
- Schrift: `--saalburg-schrift-text` für Fließtext (Standard), `--saalburg-schrift-fest` nur
  für Code/Monospace. Keine eigene Schriftgröße, kein Zoom – Saalburg skaliert selbst.
- Wenige, robuste Regeln: Ändert die Seite etwas, soll sie normal aussehen, nicht kaputt.
- `aussehen.js` minimal, ohne Netz, liest oder verschickt keine Inhalte der Seite.

## Native Apps: Saalburg-Aussehen

- Grundflächen, Text, Rahmen, Akzent, Auswahl, Meldungsfarben, Schriften der Bedienelemente und
  die Größe kommen aus `/daten/system/aussehen/saalburg.conf` (Rückfall
  `/usr/lib/osproto/aussehen/saalburg.conf`, dann eingebaute Ausweichwerte) – keine eigenen
  Werte dafür. Eigene Farben und Schriften nur für Inhalte (Dokument, Zellen, Diagramme,
  Spielgrafik); Spiele gleichen nur Menüs, Dialoge und Rahmen an.
- Einlesen mit `beispiele/saalburg_aussehen.zig`; inotify auf den Ordner, wenn Änderungen
  sofort wirken sollen. Rollen und Regeln: `PLATTFORM.md`, Abschnitt 5 „Aussehen für native Apps“.
- Wer die Datei nutzt, setzt `saalburg = @VERSION@` (oder neuer).

## Store-Seite

`store/<kennung>/`: `info.conf` (`kategorie`, `empfohlen` nur nach Absprache), `text.txt`
(≤ 1200 Zeichen, ohne `|`), bis zu 4 PNG in 16:9 (≤ 2 MB, alphabetisch = Reihenfolge).
Nur echte Ansichten der App mit Beispielinhalten; Bilder nicht aus dem Netz holen.

## Testen

Getestet wird mit der privaten Testumgebung `timelesstalesclassics/saalburg-test`
(veröffentlichtes Saalburg in QEMU, installiert die App aus dem PR, prüft Rechte und Aussehen,
macht Bildschirmfotos). Anleitung in deren `README.md`/`CLAUDE.md`. Für Web-Apps braucht die
Sitzung Netzwerkfreigabe für die Domains der App. Was ein Konto braucht (Anmelden), wird nur
auf dem Mini-PC geprüft, nie mit echten Zugangsdaten in einer Testumgebung.

**Testergebnisse bleiben privat.** Aus Tests kommt in dieses öffentliche Repo nichts außer den
Store-Bildern unter `store/<kennung>/`: keine Zahlen, Protokolle, Testberichte oder sonstigen
Bildschirmfotos in PR-Texten oder Kommentaren. Den Testbericht als Issue im privaten Repo
`timelesstalesclassics/saalburg-test` ablegen (Titel „Test: <kennung> – saalburg-katalog PR #<n>“,
Format dort in `CLAUDE.md`). Im PR selbst nur: was geändert, offene Punkte, und der Satz
„Getestet mit saalburg-test, Bericht privat“.

**Testplatz (echter Rechner):** `/testplatz` im eigenen PR kommentieren, dann den Auftragsblock
im privaten Repo `saalburg-test` als Issue mit Label `testplatz` (Ablauf und Befehle:
`PLATTFORM.md`, Abschnitt 15). Geht nur, solange der Eigentümer den Testplatz freigeschaltet
hat. Im PR höchstens „Getestet auf dem Testplatz, Bericht privat“.
