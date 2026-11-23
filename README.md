# App-Katalog von Saalburg

Apps für den App-Store von Saalburg (eigenes
schlankes Linux-System mit Claude Code). Jede App liegt als Quelle unter `apps/<kennung>/`;
GitHub baut daraus bei jeder Änderung signierte Pakete und einen signierten Katalog und legt
sie im Zweig [`veroeffentlicht`](../../tree/veroeffentlicht) ab.

Der App-Store lädt
`https://raw.githubusercontent.com/timelesstalesclassics/saalburg-katalog/veroeffentlicht/katalog.osk`,
prüft die Signatur mit dem öffentlichen Schlüssel `schluessel/saalburg-katalog.pub` (im System
mitgeliefert) sowie Größe und SHA-256 jedes Pakets. Installiert wird erst, wenn der Nutzer am
Bildschirm zustimmt; dabei zeigt das System Name, Version, Herausgeber und die Rechte der App.

## Apps

| Kennung | Art | Inhalt |
|---|---|---|
| `github` | Web-App | GitHub im eigenen Fenster; Steuerung durch Claude möglich (aus, bis eingeschaltet) |
| `claude-web` | Web-App | claude.ai im eigenen Fenster |
| `notizen` | Terminal | eine Notizdatei mit nano, ohne Internet |
| `rechner` | Terminal | Taschenrechner bc, ohne Internet |
| `sonnengrab` | Programm | Pyramiden-Plattformspiel mit Musik (Wayland, Ton, ohne Internet) |
| `eisen-und-blut` | Programm | Rundenstrategie 1864–1871 mit 3D-Gefechtsfeld (Godot 4.5, Wayland, OpenGL ES über die GPU, Ton, ohne Internet) |
| `mercurius` | Terminal | E-Mail über IMAP/SMTP, nur verschlüsselt (TLS/STARTTLS); Lesen, Antworten, Weiterleiten, Anhänge über „Dokumente“ (Internet) |
| `stilus` | Programm | Textverarbeitung: Word-Dateien (.docx) öffnen, bearbeiten und Word-lesbar speichern, auch .txt (Wayland, ohne Internet) |
| `tabula` | Programm | Tabellenkalkulation: Excel-Mappen (.xlsx) und CSV öffnen, bearbeiten und Excel-lesbar speichern, Formeln wie im deutschen Excel (Wayland, ohne Internet) |
| `whatsapp` | Web-App | WhatsApp Web im eigenen Fenster, Kopplung per QR-Code mit dem Handy; Downloads in den Dokumenten der App |
| `youtube` | Web-App | YouTube im eigenen Fenster, mit Saalburg-Aussehen (`aussehen.css`, ab Saalburg mit Aussehen-Unterstützung) |

## Eine App hinzufügen oder ändern

**Vor dem Bauen [`PLATTFORM.md`](PLATTFORM.md) lesen**: was eine App auf Saalburg vorfindet
(Umgebung, Dateisystem, Sandbox, Wayland, GPU, Ton, Netz, Lebenszyklus, Claude-Anbindung,
Bibliotheken, Mindestversion).

**Nur öffentliche Apps.** Alles hier ist öffentlich – auch der Inhalt der fertigen Pakete
(bei Python-Programmen also der Quelltext). Private Programme gehören nicht in
dieses Repo: Sie baut Claude auf dem Mini-PC aus dem privaten Repo und legt sie in den lokalen
Katalog (`/daten/claude/katalog`, `app katalog …`), den der App-Store zusätzlich liest.


1. Ordner `apps/<kennung>/` mit `app.conf` (Pflicht: `kennung` = Ordnername, `version`) und
   ggf. Programmdateien. Erlaubt sind nur Dateien und Ordner (Namen aus Buchstaben, Ziffern,
   `. _ - +`), keine Links.
2. Für ein Update `version` erhöhen; das System nimmt nur neuere Versionen vom selben
   Herausgeber an.
3. Nach `main` bringen; der Ablauf „Katalog bauen“ erledigt den Rest.

Angaben in `app.conf`: `kennung`, `version`, `name`, `beschreibung`, `symbol`, `farbe`,
`art` (`terminal`, `web`, `programm`), `start` bzw. `url`, `reihe`, `netzwerk`, `gpu`, `ton`,
`ram_max`, `ordner` (nur unter `/daten`), `steuerung = claude`, `verbindung` (MCP-Server),
`hintergrund = ja` (läuft weiter, wenn nicht zu sehen; abschaltbar in den Einstellungen),
`drucken = ja` (darf über Saalburg drucken, jeder Auftrag mit Bestätigung am Bildschirm; erst
ab Saalburg 202611230126, also mit `saalburg = 202611230126`),
`saalburg = JJJJMMTTHHMM` (Mindestversion von Saalburg in UTC, z. B. `202611211629`; ältere
Systeme zeigen „Braucht Saalburg vom …“ und installieren erst nach dem System-Update),
`kategorie` (wie in `store/`).

Für die Store-Seite (nicht im Paket) optional `store/<kennung>/`:
`info.conf` (`kategorie = Büro`, `empfohlen = ja`), `text.txt` (lange Beschreibung, höchstens
1200 Zeichen) und bis zu 4 Bildschirmfotos `*.png` (je höchstens 2 MB, alphabetisch). Sie
kommen mit Prüfsumme in den signierten Katalog; ältere Saalburg-Versionen überspringen diese
Zeilen.
### Web-Apps im Saalburg-Aussehen (`aussehen.css`)

Eine Web-App kann `aussehen.css` (optional `aussehen.js`) im Ordner `apps/<kennung>/`
mitbringen. Saalburg legt es mit seinem zentralen `saalburg.css` als Erweiterung ohne Rechte
über die Seiten der App (abschaltbar in den Einstellungen: „An Saalburg angleichen“).

Regel, damit alle Apps gleich aussehen: **Farben und Schriften kommen nur von Saalburg.**
`aussehen.css` ordnet die Elemente bzw. CSS-Variablen der Seite den Variablen aus
`saalburg.css` zu (`var(--saalburg-grund)`, `--saalburg-karte`, `--saalburg-text`,
`--saalburg-akzent` …; Schrift: `var(--saalburg-schrift-text)` für Fließtext,
`var(--saalburg-schrift-fest)` für Code). Nicht erlaubt und vom Katalog abgewiesen:
eigene Farbwerte (`#…`, `rgb()`, `hsl()`, Farbnamen), eigene Schriften (`font-family` mit
Namen, `@font-face`) und `@import`. Erlaubt: `transparent`, `currentColor`, allgemeine
Schriftfamilien als Rückfall in `var()`, `color-mix()` aus Saalburg-Variablen.
Prüfen ohne Schlüssel: `python3 werkzeug/katalog_bauen.py --pruefen` (läuft auch bei jedem
Pull Request).

Jede App läuft in ihrer eigenen Sandbox (eigene Kennung, Landlock, cgroup, seccomp).
Ist eine App 10 s nicht zu sehen, friert Saalburg sie ein und lagert sie später aus;
beim Ausschalten bekommt sie SIGTERM und bis zu 12 s, um ihren Stand zu speichern.

## System-Updates

Saalburg aktualisiert sich selbst übers Netz (`app system aktualisieren`, mit Bestätigung am
Bildschirm). Das System wird in inhaltsabhängige Teile zerlegt (im Mittel ~1 MB); im Zweig
`system` liegen sie unter `teile/<sha256>`, dazu `eingang/manifest.txt`. Der Ablauf
„System freigeben“ prüft alle Teile und signiert das Manifest (`system/aktuell.osm` im Zweig
`veroeffentlicht`). Der Mini-PC lädt nur die Teile, die er noch nicht hat. Das sind fertige
Programme, keine Quelltexte; der Quelltext von Saalburg bleibt privat.

## Signierschlüssel

Der geheime Schlüssel liegt nur als GitHub-Secret `OSAPP_SCHLUESSEL` im Repo; der Ablauf prüft,
dass er zu `schluessel/saalburg-katalog.pub` passt. System-Updates signiert er mit eigenem
Vorsatz; Saalburg nimmt sie nur mit diesem mitgelieferten Schlüssel an, nie mit später vertrauten. Formate: `werkzeug/katalog_bauen.py`.
