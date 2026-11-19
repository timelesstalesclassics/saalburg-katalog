# App-Katalog des OS-Prototyps

Apps für den App-Store des [OS-Prototyps](https://github.com/timelesstalesclassics) (eigenes
schlankes Linux-System mit Claude Code). Jede App liegt als Quelle unter `apps/<kennung>/`;
GitHub baut daraus bei jeder Änderung signierte Pakete und einen signierten Katalog und legt
sie im Zweig [`veroeffentlicht`](../../tree/veroeffentlicht) ab.

Der App-Store lädt
`https://raw.githubusercontent.com/timelesstalesclassics/os-prototyp-katalog/veroeffentlicht/katalog.osk`,
prüft die Signatur mit dem öffentlichen Schlüssel `schluessel/osproto-katalog.pub` (im System
mitgeliefert) sowie Größe und SHA-256 jedes Pakets. Installiert wird erst, wenn der Nutzer am
Bildschirm zustimmt; dabei zeigt das System Name, Version, Herausgeber und die Rechte der App.

## Apps

| Kennung | Art | Inhalt |
|---|---|---|
| `github` | Web-App | GitHub im eigenen Fenster; Steuerung durch Claude möglich (aus, bis eingeschaltet) |
| `claude-web` | Web-App | claude.ai im eigenen Fenster |
| `notizen` | Terminal | eine Notizdatei mit nano, ohne Internet |
| `rechner` | Terminal | Taschenrechner bc, ohne Internet |

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
`art` (`terminal`, `web`, `programm`), `start` bzw. `url`, `reihe`, `netzwerk`, `gpu`,
`ram_max`, `ordner` (nur unter `/daten`), `steuerung = claude`, `verbindung` (MCP-Server).
Jede App läuft in ihrer eigenen Sandbox (eigene Kennung, Landlock, cgroup, seccomp).

## Signierschlüssel

Der geheime Schlüssel liegt nur als GitHub-Secret `OSAPP_SCHLUESSEL` im Repo; der Ablauf prüft,
dass er zu `schluessel/osproto-katalog.pub` passt. Formate: `werkzeug/katalog_bauen.py`.
