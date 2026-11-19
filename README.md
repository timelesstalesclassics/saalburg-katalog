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
| `sonnengrab` | Programm | Pyramiden-Plattformspiel mit Musik (Wayland, Ton, ohne Internet); Quelltext unter `quellen/sonnengrab/` |

## Eine App hinzufügen oder ändern

**Nur öffentliche Apps.** Alles hier ist öffentlich – auch der Inhalt der fertigen Pakete
(bei Python-Programmen also der Quelltext). Private Programme wie aimilling gehören nicht in
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
`ram_max`, `ordner` (nur unter `/daten`), `steuerung = claude`, `verbindung` (MCP-Server).
Jede App läuft in ihrer eigenen Sandbox (eigene Kennung, Landlock, cgroup, seccomp).

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
