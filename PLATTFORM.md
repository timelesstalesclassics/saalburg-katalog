# Saalburg für App-Entwickler

Was eine App auf Saalburg vorfindet, was sie darf und wie sie sich gut einfügt.
Diese Beschreibung stammt aus dem Code von Saalburg, sie zeigt nicht den Code selbst.
**Stand: Saalburg 202611251640.**

Regeln für dieses Repo (Ablauf, Store, `aussehen.css`) stehen in `CLAUDE.md` und `README.md`.
Ändert sich in Saalburg etwas, das Apps betrifft, wird diese Datei mitgezogen.

---

## 1. Überblick

| | |
|---|---|
| Kernel | Linux 6.18 (eigene Konfiguration, x86_64) |
| Basis | Alpine Linux 3.24, **musl** libc 1.2.6. glibc-Programme laufen nicht. |
| Init | eigenes Init-Programm (kein systemd, kein OpenRC, **kein D-Bus**) |
| Oberfläche | eigener Compositor (Zig) mit eigenem Wayland-Server, Terminal-Emulator und Systemseiten |
| Zielgerät | Mini-PC mit Intel N100 (Grafik i915), 16 GB RAM, SSD |
| Sprache/Zeit | `LANG=C.UTF-8` (keine weiteren Locales), `TZ=Europe/Berlin`, deutsche Tastaturbelegung |

Der Bildschirm ist in **Plätze** geteilt: Vollbild, 1:1 oder 1:1 mit Leiste unten. Eine App
bekommt immer genau einen Platz in voller Größe. Die Größe bestimmt die Oberfläche, nicht die App.

---

## 2. App-Arten und Start

Eine App ist ein Ordner `apps/<kennung>/` mit `app.conf` (Angaben siehe `README.md`).
Installiert liegt er unter `/daten/apps/<kennung>/aktuell/`, root gehört er und für die App ist
er **nur lesbar**.

| `art` | Was startet | Ein- und Ausgabe |
|---|---|---|
| `terminal` | `start` per `/bin/sh -c` in einem Terminal der Oberfläche | Pseudo-Terminal, `TERM=xterm-256color` |
| `programm` | `start` per `/bin/sh -c`, eigenes Wayland-Fenster | stdin, stdout und stderr auf `/dev/null`; Protokoll bitte selbst nach `$HOME` schreiben |
| `web` | Chromium im App-Modus mit `url` (nur `https://` oder lokal `http://127.0.0.1`, `http://localhost`) | eigenes Chromium-Profil je App |

Eine weitere Art, `browser`, gibt es nur für den mitgelieferten Browser (Abschnitt 10); die
Kennung `browser` ist für ihn reserviert, Pakete damit lehnt die App-Verwaltung ab (ab Saalburg 202611231841).

`start` und `verbindung` dürfen höchstens 255 Zeichen lang sein. Programmdateien adressiert
man absolut: `exec /daten/apps/<kennung>/aktuell/<datei>`.

### Kennung, Gruppen, Umgebung

- **Eigene Linux-Kennung je App**: Die UID wird beim ersten Start vergeben (ab 20000) und
  bleibt dann fest. GID wie UID.
- **Zusatzgruppen**: `wayland` (9000), mit Recht `ton` zusätzlich `audio` (18). Mehr gibt es
  nicht: kein `video`, kein `input`.
- **Arbeitsordner beim Start**: `$HOME`.
- **Umgebung** (vollständig, sonst nichts):

  | Variable | Wert |
  |---|---|
  | `HOME` | `/daten/appdaten/<kennung>` |
  | `USER`, `LOGNAME` | `<kennung>` |
  | `XDG_RUNTIME_DIR` | `/run/user/<uid>` |
  | `TMPDIR` | `/tmp` (eigenes `/tmp` der App, siehe 3) ¹ |
  | `XDG_CACHE_HOME` | `$HOME/.cache` |
  | `PATH` | `/usr/local/bin:/usr/bin:/bin` |
  | `LANG` | `C.UTF-8` |
  | `TZ` | `Europe/Berlin` |
  | `TERM` | `xterm-256color` |
  | `WAYLAND_DISPLAY` | `/run/wayland/wayland-0` (absoluter Pfad) |
  | `SHELL` | `/bin/sh` |
  | `SAALBURG_DIENST` | `/run/wayland/saalburg-dienst`: Dienst der Oberfläche (Öffnen, Speichern, Meldungen, Drucken, siehe 3) ¹ |
  | `SAALBURG_APP_SOCKET` | `$XDG_RUNTIME_DIR/app.sock`: Kanal zwischen laufender App und ihrem MCP-Server (siehe 9) ¹ |

  ¹ ab Saalburg 202611230126 (Abschnitt 13); vorher `TMPDIR=/daten/appdaten/<kennung>/tmp`.

  Web-Apps setzen zusätzlich `XDG_CONFIG_HOME=$HOME/.config` und
  `DBUS_SESSION_BUS_ADDRESS=disabled:`, ihre Downloads und Dokumente zeigen auf
  `$HOME/Dokumente`.

### Terminal-Apps

Der Terminal-Emulator ist xterm-256color-kompatibel, genug für bash, nano, less und Claude Code:
- 256 Farben und Truecolor, fett, kursiv, unterstrichen, invers, durchgestrichen;
- zweiter Bildschirm und Verlauf;
- breite Zeichen und Zeilenumbruch.

Schließt der Nutzer das Fenster, bekommt das Programm `SIGHUP`.

---

## 3. Dateisystem aus Sicht der App

Landlock sperrt alles, was nicht ausdrücklich freigegeben ist:

| Pfad | Recht |
|---|---|
| `/usr`, `/lib`, `/bin`, `/sbin`, `/etc` | lesen, ausführen |
| `/sys`, `/dev` (Verzeichnisse), `/var/cache/fontconfig` | lesen |
| `/proc` | lesen, eigene Einträge schreiben |
| `/run/netz` (DNS) | lesen |
| `/daten/system/schrift` (Schriftwahl, fontconfig) | lesen |
| `/daten/system/aussehen` (Aussehen für native Apps, Abschnitt 5; ab Saalburg 202611240808) | lesen |
| `/dev/null`, `zero`, `full`, `random`, `urandom`, `tty`, `ptmx`, `/dev/pts` | lesen, schreiben |
| `/dev/shm` | lesen, schreiben, anlegen (ohne Ausführen) |
| `/daten/apps/<kennung>` (Paket) | lesen, ausführen |
| `$HOME` = `/daten/appdaten/<kennung>` | alles außer Gerätedateien |
| `$XDG_RUNTIME_DIR` = `/run/user/<uid>` | alles außer Gerätedateien |
| `/tmp` (eigenes, siehe unten) | alles außer Gerätedateien |
| `/dev/dri/renderD*` (Render-Knoten; nie `card*`/KMS) | nur mit Recht `gpu` (vor 202611241046: ganz `/dev/dri`, `card*` gehört aber der Gruppe video) |
| `/dev/snd`, `/daten/system/ton` | nur mit Recht `ton` (siehe 6) |
| `ordner = /daten/x, /daten/y (lesen)` | schreiben bzw. lesen; nur unter `/daten`, nie unter `/daten/claude`, `/daten/system`, `/daten/appdaten`, `/daten/apps`; höchstens 4 |

**Nicht** erreichbar sind unter anderem das `/tmp` des Systems, `/daten/claude`, die Daten
anderer Apps und der Rest von `/run`.

**Eigenes `/tmp`**: Jede App hat einen eigenen Mount-Namensraum, in dem `$HOME/tmp` über `/tmp`
liegt (`nosuid`, `nodev`). App und ihr MCP-Server (Abschnitt 9) sehen dasselbe `/tmp`. Es wird
geleert, wenn die App startet und nichts von ihr läuft. Einhängungen des Systems (z. B.
USB-Sticks) kommen im Namensraum weiter an; was die App sieht, ändert sich sonst nicht.

Feste Unterordner in `$HOME`, die die Oberfläche anlegt (Rechte 0700):
- `tmp/`: liegt als `/tmp` vor der App;
- `Dokumente/`: **der einzige Ordner, der geteilt werden kann** (siehe unten).

### Dateien zwischen Apps, Claude und Nutzer

Saalburg folgt iOS: Jede App teilt nur `$HOME/Dokumente`, der Rest bleibt privat.
- **Übertragen** wird über den Dateidienst, nie über gemeinsame Ordner. Der Nutzer nutzt dafür
  die Dateien-App (Windows-Taste+E), Claude `app datei …`.
- **Claude** sieht die Dokumente einer App nur, wenn der Nutzer sie in den Einstellungen
  freigibt (Spalte „Dokumente“). Ohne Freigabe fragt Saalburg bei jedem Zugriff am Bildschirm.
- **Downloads** von Web-Apps landen in `Dokumente`. Zum Hochladen wählt man im Dateidialog
  `Dokumente` (dort als Lesezeichen); Dateien von anderswo holt der Nutzer mit
  Windows-Taste+O in die Dokumente der App mit Fokus.
- **Öffnen und Speichern** für eigene Programme: über den Dienst der Oberfläche (unten). Der
  Nutzer wählt in Saalburgs Dateien-Seite, übertragen wird über den Dateidienst. Die App sieht
  nie fremde Pfade, nur ihre Kopie in `Dokumente`.
- **Gelöscht** wird in `.Papierkorb` des Bereichs, erst das Leeren des Papierkorbs ist
  endgültig.

### Dienst der Oberfläche: Öffnen, Speichern, Meldungen, Drucken

Ein Unix-Socket unter `$SAALBURG_DIENST` (nur für Apps in der Sandbox; die Oberfläche erkennt
die App an ihrem Prozess). Kein xdg-desktop-portal: Saalburg hat keinen D-Bus, und das Portal
gäbe Apps Pfade außerhalb ihrer `Dokumente`.

Am einfachsten über den Befehl `saalburg` oder das Python-Modul:

```sh
pfad=$(saalburg oeffnen "Bild wählen")        # Kopie in ~/Dokumente; Rückgabe 1 = abgebrochen
saalburg speichern export.pdf "Export sichern" # Datei aus ~/Dokumente an einen gewählten Ort
saalburg melden "Fertig" "Export abgeschlossen"
saalburg drucken ~/Dokumente/bericht.pdf       # Recht drucken, Bestätigung am Bildschirm
notify-send "Titel" "Text"                     # geht als Meldung (Optionen werden übergangen)
```

```python
import sys; sys.path.insert(0, "/usr/lib/osproto")
import saalburg_dienst as sb   # oeffnen(titel), speichern(datei, titel), melden(titel, text), drucken(pfad)
```

Rückgabe von `saalburg`: 0 = OK (Pfad bzw. Ziel auf stdout), 1 = abgebrochen, 2 = Fehler
(Grund auf stderr). Das Protokoll für andere Sprachen: **eine Verbindung = eine Anfrage**, eine
UTF-8-Zeile mit `\n`, die Antwort ist eine Zeile (`OK …`, `ABBRUCH`, `FEHLER <Grund>`).

| Anfrage | Was passiert | Antwort |
|---|---|---|
| `OEFFNEN [Titel]` | Die Dateien-Seite geht auf; der Nutzer wählt eine Datei (Enter). Der Dateidienst kopiert sie nach `$HOME/Dokumente/<Name>` (eine gleichnamige alte Kopie wandert in deren `.Papierkorb`). Wählt er eine Datei aus den eigenen Dokumenten, wird nichts kopiert. | `OK <Pfad>` oder `ABBRUCH` |
| `SPEICHERN <Datei>[\t<Titel>]` | `<Datei>` ist ein Pfad relativ zu `Dokumente` und muss dort liegen. Der Nutzer öffnet den Zielordner und drückt F5. Gibt es das Ziel schon, bleibt die Auswahl offen (nie überschreiben). | `OK <Ort>/<Name>` oder `ABBRUCH` |
| `MELDEN <Titel>\t<Text>` | Meldung kurz in der Leiste (8 s, ohne Ton, höchstens eine je Sekunde und App) | `OK` |
| `DRUCKEN <Name>` + Datei als Deskriptor (`SCM_RIGHTS`) | nur PDF, JPEG, PNG bis 100 MB, Recht `drucken`; der Nutzer bestätigt am Bildschirm (passt der Inhalt nicht zur Endung, gleich `FEHLER`, ohne Frage). Nimmt der Drucker das Format direkt an, geht die Datei unverändert hin; sonst wandelt Saalburg PDF und PNG in einem eingesperrten Prozess (ohne Netz, nur eigener Arbeitsordner, Zeit- und Speichergrenzen) in JPEG-Seiten um (300 dpi, höchstens 100 Seiten; ab Saalburg 202611241934, vorher Fehler). Geht die Umwandlung nicht, antwortet der Dienst mit `FEHLER`. | `OK`, `ABBRUCH` oder `FEHLER …` |

- **Warten**: Öffnen und Speichern antworten erst, wenn der Nutzer gewählt hat (auch nach
  Minuten). Die App sollte dabei ihre Ereignisschleife weiterlaufen lassen (Thread), sonst zeigt
  die Oberfläche „reagiert nicht“. Es ist immer nur eine Auswahl offen; eine zweite bekommt
  `FEHLER beschäftigt`.
- **Ton**: Meldungen sind stumm. Wer einen Ton will, spielt ihn selbst (Recht `ton`).
- **Drucken** braucht `drucken = ja` in `app.conf`; der Nutzer kann es in den Einstellungen
  (Spalte „Drucken“) abschalten, das gilt sofort. Einen Drucker richtet der Nutzer mit Claude
  ein (`drucken --drucker …`); fehlt er, antwortet der Dienst mit einem Fehler.
- **Test-Apps auf dem Testplatz** (ab Saalburg 202611241934): `MELDEN` und `DRUCKEN` (mit
  `drucken = ja`) gehen, `OEFFNEN`/`SPEICHERN` nicht (Abschnitt 15).

### Zwischenablage, Ziehen und Ablegen

Beides läuft über das Wayland-Protokoll `wl_data_device` (Version 3, siehe 5):
- **Zwischenablage** zwischen Programmen: beliebige MIME-Typen, höchstens 8 je Quelle.
- **Mit Terminals**: Text, also `text/plain;charset=utf-8`, `text/plain`, `UTF8_STRING`.
- **Bildschirmfotos** des Nutzers (Druck-Taste) bietet die Ablage als `image/png` an, als Text
  den Pfad. Jedes neue Foto ist ein neues Angebot (`wl_data_device.selection`) an das Fenster
  mit Fokus, auch mehrere Fotos in derselben Sekunde (eigene Datei je Foto). Fragt eine App
  nach einem anderen Typ (z. B. `text/uri-list`, `text/html`), bekommt sie nichts (ab Saalburg
  202611241934; vorher den Pfad als Text).
- **Ziehen und Ablegen**: Text aus Terminals, und von Programmen `text/uri-list` bzw. Text;
  Dateien erscheinen als Pfade.

---

## 4. Sandbox

Jede installierte App läuft eingesperrt. Das lässt sich nicht abschalten.

- **`no_new_privs`**: setuid-Programme bringen keine Rechte.
- **seccomp**: Diese Systemaufrufe antworten mit `EPERM`, x32-Aufrufe ebenso:
  - Debuggen, Kernel, Start: `ptrace` (101), `acct` (163), `reboot` (169), `init_module` (175),
    `delete_module` (176), `finit_module` (313), `kexec_load` (246), `kexec_file_load` (320),
    `perf_event_open` (298), `bpf` (321), `userfaultfd` (323)
  - Einhängen und Dateisysteme: `pivot_root` (155), `mount` (165), `umount2` (166),
    `swapon` (167), `swapoff` (168), `open_tree` (428), `move_mount` (429), `fsopen` (430),
    `fsconfig` (431), `fsmount` (432), `fspick` (433)
  - Schlüssel und fremde Prozesse: `add_key` (248), `request_key` (249), `keyctl` (250),
    `name_to_handle_at` (303), `open_by_handle_at` (304), `process_vm_readv` (310),
    `process_vm_writev` (311)
  - `io_uring_setup`, `_enter`, `_register` (425–427)
  - Andere Architekturen als x86_64 beendet das System sofort.
- **Landlock** wie in Abschnitt 3, ab Kernel-ABI 6 zusätzlich: abstrakte Unix-Sockets und
  Signale nur innerhalb der eigenen App.
- **Netz**: Ohne Recht `netzwerk` bekommt die App einen eigenen Netz-Namensraum mit nur `lo`.
  Lokale Server auf 127.0.0.1 gehen also, nach außen nichts.
- **cgroup** `/sys/fs/cgroup/apps/<kennung>`:
  - `memory.max` aus `ram_max` (Standard 1024 MB, Web-Apps 2048 MB, erlaubt 16–16384 MB);
  - `pids.max` 512, Web-Apps 4096;
  - `memory.oom.group = 1`: Bei Speichermangel endet die ganze App, nicht einzelne Prozesse.
- **Geräte**: nur die aus Abschnitt 3. Kein Zugriff auf Tastatur oder Maus (`/dev/input`),
  keine Kamera, **kein Mikrofon**.
- **Fremde Prozesse**: Andere Apps und claude laufen unter anderen UIDs und sind tabu.

Der Nutzer kann jedes Recht in den Einstellungen abschalten (Netzwerk, GPU, Ton, Drucken,
Hintergrund, Aussehen) und die Steuerung durch Claude einschalten. Eine App muss damit leben, dass ein
Recht fehlt.

---

## 5. Grafik und Fenster

### Wayland

- **Socket**: `/run/wayland/wayland-0`, erreichbar über die Gruppe `wayland`.
- **Kein X11** und kein Xwayland.
- **Tastatur**: deutsche Belegung (xkb kommt vom Compositor), Wiederholung 30/s nach 500 ms.

| Schnittstelle | Version | Bemerkung |
|---|---|---|
| `wl_compositor` | 6 | |
| `wl_subcompositor` | 1 | |
| `wl_shm` | 1 | ARGB8888, XRGB8888 |
| `wl_seat` | 7 | Zeiger, Tastatur, Touch (`seat0`) |
| `wl_output` | 4 | Skalierung 1 |
| `xdg_wm_base` | 5 | Fenster und Popups, Ping/Pong |
| `zxdg_decoration_manager_v1` | 1 | Den Rahmen zeichnet die Oberfläche (serverseitig) |
| `wl_data_device_manager` | 3 | Zwischenablage, Ziehen und Ablegen |
| `zwp_linux_dmabuf_v1` | 4 | GPU-Puffer; Rückmeldung (`get_default_feedback`/`get_surface_feedback`) mit Render-Knoten als `main_device` und Formattabelle (ab 202611241046; vorher 3) |
| `wp_viewporter` | 1 | Ausschnitt und Zielgröße einer Fläche ² |
| `wp_fractional_scale_manager_v1` | 1 | bevorzugte Skalierung immer 120 (= 1,0) ² |
| `zwp_pointer_constraints_v1` | 1 | Zeiger sperren oder auf die Fläche begrenzen ² |
| `zwp_relative_pointer_manager_v1` | 1 | relative Mausbewegung (Spiele, 3D-Ansichten) ² |
| `wp_cursor_shape_manager_v1` | 1 | Zeigerformen ohne eigenes Bild ² |
| `zwp_idle_inhibit_manager_v1` | 1 | Bildschirm wach halten ² |
| `zxdg_exporter_v2`, `zxdg_importer_v2` | 1 | xdg-foreign: Elternfenster über Verbindungen hinweg (z. B. GTK-Dialog von Chromium) ³ |
| `zxdg_exporter_v1`, `zxdg_importer_v1` | 1 | dasselbe in Version 1 (GTK 3 importiert nur darüber); Griffe gelten für beide ³ |

² ab Saalburg 202611230126 (Abschnitt 13). ³ ab Saalburg 202611241934.

Verhalten:
- **Fenster** bekommen per `configure` die Größe ihres Platzes und die Zustände „maximiert“
  und „an allen Rändern angelegt“, „aktiv“ nur mit Fokus.
- **`wm_capabilities`**: Vollbild und Minimieren ². `set_fullscreen` gibt dem Fenster den ganzen
  Bildschirm (auch über der Leiste, Zustand `fullscreen`), solange es den Fokus hat; wechselt der
  Fokus, steht es wieder in seinem Platz, mit Fokus wieder im Vollbild, bis `unset_fullscreen`.
  `set_minimized` nimmt das Fenster vom Platz; es läuft weiter (und schläft nach 10 s, siehe 8)
  und steht in der Übersicht. Maximieren ist immer; ein Fenstermenü gibt es nicht.
- **Tastaturfokus**: Bekommt ein Fenster den Fokus, bevor es sein erstes Bild zeigt, meldet
  Saalburg ihn mit dem ersten Puffer noch einmal (`wl_keyboard.leave`, dann `enter`; ab Saalburg 202611231841). Eine App
  sollte beides jederzeit vertragen.
- **Dialoge** ³: Ein Fenster mit Elternfenster (`xdg_toplevel.set_parent` oder xdg-foreign
  `set_parent_of`) erscheint auf dem Platz seines Elternfensters und bekommt den Tastaturfokus;
  das Elternfenster wartet darunter und kommt zurück, wenn der Dialog zugeht. Holt der Nutzer
  das Elternfenster über die Übersicht zurück, steht dort wieder der Dialog; ein Klick ins
  Elternfenster (z. B. bei 1:1 auf dem anderen Platz) gibt dem Dialog den Fokus und erreicht
  die App nicht. Gilt nur innerhalb derselben App; xdg-foreign-Griffe sind zufällig.
- **Ping/Pong**: Antwortet eine App 5 s lang nicht auf `xdg_wm_base.ping`, zeigt die Oberfläche
  „reagiert nicht“. Deshalb die Ereignisschleife nie lange blockieren.
- **Mauszeiger**: Eigene Zeiger über `wl_pointer.set_cursor` sind erlaubt. Mit
  `wp_cursor_shape` zeigt Saalburg eigene Bilder für Text, Hand (pointer), Kreuz, Bewegen und
  waagrechtes/senkrechtes Ändern; alle anderen Formen als normalen Pfeil.
- **Zeigersperre**: aktiv, solange der Zeiger über der Fläche steht (`locked`/`confined`).
  Gesperrt bleibt der Zeiger stehen, die App bekommt nur relative Bewegung. Regionen werden
  übergangen (gilt die ganze Fläche), `set_cursor_position_hint` ebenso. Die Windows-Taste
  löst jede Sperre sofort (einmalige Sperren enden damit, dauerhafte greifen erst wieder, wenn
  der Zeiger die Fläche verlassen und neu betreten hat).
- **Viewport und Skalierung**: Saalburg skaliert nicht (`wl_output` Skalierung 1, bevorzugt
  120/120). Der Viewport streckt Puffer auf die Zielgröße; Eingaben kommen in Koordinaten der
  Zielgröße.
- **Wach halten**: wird angenommen; Saalburg schaltet den Bildschirm bisher nie ab. Sichtbare
  Apps schlafen ohnehin nicht (siehe 8).

**Nicht vorhanden** (nicht darauf verlassen):
- Layer-Shell, xdg-activation;
- Text-Input bzw. Eingabemethoden (`zwp_text_input_v3`; Saalburg hat keine Eingabemethode,
  Text kommt über die Tastatur mit xkb), Primary Selection;
- Screencopy, Unterflächen-Synchronisation.

### GPU

- **Treiber**: Mesa 26 mit Iris für Intel (i915) über `/dev/dri`, nur mit Recht `gpu`
  (Web-Apps: Standard an).
- **Schnittstellen**: EGL und OpenGL ES (`mesa-egl`, `mesa-gles`), dazu GBM.
- **Vulkan**: Ein Vulkan-Treiber ist nicht installiert. Der Lader kommt nur als Abhängigkeit
  von Chromium mit.
- **Gerät finden**: Die Oberfläche nennt ihren Render-Knoten über linux-dmabuf Version 4
  (`main_device` der Rückmeldung); daran erkennt Mesa (EGL auf Wayland) die GPU, Apps müssen
  nichts tun. Vor Saalburg 202611241046 fehlte diese Angabe: native Apps mit `gpu = ja` (EGL über
  `wl_display`) fanden kein Gerät und zeichneten per Software (im Protokoll
  „libEGL warning: failed to get driver name for fd -1“). Web-Apps waren nicht betroffen.
  Wer EGL direkt auf GBM oder `EGL_PLATFORM_DEVICE` nutzt, öffnet `/dev/dri/renderD128`.
- **Nur Render-Knoten**: zeichnen und rechnen ja, Anzeige (`card*`, KMS, Modus) nie.
- **Ohne Recht `gpu`**: Programme zeichnen per Software in `wl_shm`-Puffer.

### Aussehen für native Apps (ab Saalburg 202611240808)

Native Apps (`art = programm`, eigene Fenster) zeichnen selbst. Damit sie wie Saalburg aussehen,
legt Saalburg Farben, Schriften und Maße in eine einfache Datei. Sie kommt aus derselben Quelle
wie die Farben der Oberfläche und `saalburg.css` der Web-Apps, die drei können nicht
auseinanderlaufen.

| Pfad | Inhalt |
|---|---|
| `/daten/system/aussehen/saalburg.conf` | **zuerst lesen**: aktuelle Werte mit Schrift und Schriftgröße aus den Einstellungen; von der Oberfläche geschrieben, für jede App lesbar (Landlock) |
| `/usr/lib/osproto/aussehen/saalburg.conf` | Vorgaben ab Werk im selben Format, falls die erste Datei fehlt |

**Format**: UTF-8, eine Angabe je Zeile `schluessel = wert`, `#` leitet Kommentarzeilen ein.
Unbekannte Schlüssel überspringen (neue Rollen kommen ohne neue Formatnummer dazu). Beispiel
(Schriftgröße 32, Vorgabe):

```
format = 1
farbschema = dunkel
schrift_fest = Terminess Nerd Font Mono
schrift_fest_datei = /usr/share/fonts/saalburg/Terminess-Regular.ttf
schrift_fest_fett_datei = /usr/share/fonts/saalburg/Terminess-Bold.ttf
schrift_text = DejaVu Sans
schrift_text_datei = /usr/share/fonts/dejavu/DejaVuSans.ttf
schrift_text_fett_datei = /usr/share/fonts/dejavu/DejaVuSans-Bold.ttf
zeilenhoehe = 32
skalierung = 1.14
abstand = 8
rundung = 10
grund = #111218
karte = #1a1b26
…
```

| Schlüssel | Bedeutung |
|---|---|
| `format` | Formatnummer, derzeit `1`. Ändert sich nur, wenn sich die Bedeutung vorhandener Schlüssel ändert |
| `farbschema` | `dunkel` (derzeit immer) |
| `schrift_fest`, `schrift_text` | Familienname der festen Schrift (Code, Tabellenraster, Terminal) bzw. der Fließtext-Schrift, wie der Nutzer sie gewählt hat; dieselben Namen liefert fontconfig für `monospace` bzw. `sans-serif` |
| `schrift_…_datei`, `schrift_…_fett_datei` | TTF-Dateien dazu (normal, fett) für FreeType, ohne fontconfig |
| `zeilenhoehe` | Schriftgröße der Oberfläche als Zeilenhöhe in Pixeln (20, 24, 28, 32). Die Oberfläche wählt die Pixelgröße der Schrift so, dass Ober- plus Unterlänge genau eine Zeile füllen |
| `skalierung` | `zeilenhoehe / 28`, zwei Nachkommastellen (28 px = 1.00, 32 px = 1.14), wie der Seitenzoom der Web-Apps. Feste Pixelmaße der App damit malnehmen |
| `abstand` | Abstand-Grundmaß in Pixeln, schon skaliert (7 bei 100 %); Ränder und Lücken als Vielfache |
| `rundung` | Eckenradius von Karten und Knöpfen in Pixeln, schon skaliert (9 bei 100 %) |

**Farbrollen** (`#rrggbb`, deckend):

| Rolle | Bedeutung | Vorgabe |
|---|---|---|
| `grund` | Hintergrund des Fensters | `#111218` |
| `seite` | Seitenleisten, dunkler als der Grund | `#0b0c11` |
| `karte` | Flächen: Karten, Eingabefelder, Werkzeugleisten | `#1a1b26` |
| `flaeche_hoch` | hervorgehobene Fläche: unter dem Zeiger, gewählt, Menüs | `#24283b` |
| `rahmen` | Trennlinien, Ränder | `#2a2e42` |
| `text` | Text | `#c0caf5` |
| `text_hell` | betonter Text, Überschriften | `#f2f4fb` |
| `text_gedaempft` | leiser Text, Hinweise, Tastenkürzel | `#8089b0` |
| `text_aus` | deaktiviert | `#565f89` |
| `akzent` | Fokus, Links, Hauptknopf, Fortschritt | `#7aa2f7` |
| `akzent_hell` | Akzent unter dem Zeiger | `#9db8fa` |
| `akzent_flaeche` | große Akzentflächen (Titel, Symbol), Saalburg-Blau | `#3d59a1` |
| `akzent_text` | Text auf `akzent` (Hauptknopf, Fokuszeile) | `#0c0d13` |
| `auswahl` | markierter Text, gewählte Zeile (Hintergrund) | `#364466` |
| `erfolg`, `warnung`, `fehler` | Erfolg, Warnung/Rückfrage, Fehler/Löschen | `#9ece6a`, `#e0af68`, `#f7768e` |
| `info` | Hinweis, läuft gerade | `#7dcfff` |
| `terminal_grund`, `terminal_text` | Standardfarben im Terminal (Terminal-Apps: dort nichts übermalen) | `#1a1b26`, `#c0caf5` |

Dieselben Farben haben Web-Apps unter `--saalburg-…` (Abschnitt 10): `grund` = `--saalburg-grund`,
`karte` = `--saalburg-karte`, `flaeche_hoch` = `--saalburg-karte-hell`, `rahmen` =
`--saalburg-linie`, `text_gedaempft` = `--saalburg-leise`, `erfolg`/`warnung` = `--saalburg-gut`/`-warn` usw.

**Regeln**
- **Aus Saalburg kommen**: Grundflächen (`grund`, `seite`, `karte`, `flaeche_hoch`), Text,
  Rahmen, Akzent und Auswahl, Meldungsfarben, die Schriften der Bedienelemente und die Größe
  (`zeilenhoehe`/`skalierung`). Keine eigene Hintergrundfarbe fürs Fenster, kein eigenes
  Farbschema, keine eigene Schriftgröße.
- **Eigene Farben erlaubt** für Inhalte: Dokument- und Seitenfarben (Stilus), Zellen- und
  Diagrammfarben (Tabula), Spielgrafik, Bilder, Syntaxfarben, Farben, die der Nutzer selbst
  wählt. Ebenso eigene Schriften für erzeugten Inhalt (z. B. Dokumentschriften).
- **Spiele**: Menüs, Dialoge und Rahmen um das Spielfeld nach Saalburg; die Spielgrafik bleibt.
- Die `farbe` in `app.conf` ist nur die Kachelfarbe der Übersicht, kein Aussehen der App.

**Ausweichwerte**: Fehlt `/daten/system/aussehen/saalburg.conf` (älteres Saalburg, noch nicht
geschrieben), die Vorgaben aus `/usr/lib/osproto/…` lesen; fehlt auch die oder ein Schlüssel,
die Vorgaben aus den Tabellen oben verwenden. Eine App muss ohne beide Dateien laufen.

**Änderungen**: Die Oberfläche schreibt die Datei beim Start und bei jeder Änderung von Schrift
oder Schriftgröße neu, immer als neue Datei (`saalburg.conf.neu`, dann `rename`): Eine App sieht
nie eine halbe Datei. Mindestens beim nächsten Start der App gilt der neue Stand. Wer laufend
mitgehen will, beobachtet den **Ordner** `/daten/system/aussehen` mit inotify (`IN_MOVED_TO`,
Name `saalburg.conf`; nicht die Datei selbst, sie wird ersetzt), liest neu und zeichnet neu.
Die Farben ändern sich nur mit einem System-Update.

**Baustein zum Einlesen**: `beispiele/saalburg_aussehen.zig` in diesem Repo (Zig 0.16, nur
Systemaufrufe, mit Test): Laufzeit-Datei, Vorgaben, Ausweichwerte, inotify. Kurzform:

```zig
const aussehen = @import("saalburg_aussehen.zig");

var a = aussehen.laden();                    // a.farben.grund, a.zeilenhoehe, a.schrift_text_datei.t() …
const beobachter = aussehen.beobachten();    // ?i32, mit poll() in die Ereignisschleife
// bei POLLIN: if (aussehen.geaendert(fd)) { a = aussehen.laden(); neu_zeichnen(); }
```

Terminal-Apps (`art = terminal`) lesen dieselbe Datei. Sie lassen den Standardhintergrund des
Terminals stehen (`terminal_grund`) und setzen Text-, Akzent- und Meldungsfarben als 24-Bit-Farben
(`ESC[38;2;r;g;bm`).

---

## 6. Ton

- **ALSA direkt**, ohne Tondienst: kein PulseAudio, kein PipeWire-Dienst, keine JACK-Brücke.
  Die PipeWire-Bibliotheken liegen nur für Chromium bei.
- **Recht `ton`** (Web-Apps: Standard an) gibt die Gruppe `audio` und Zugriff auf `/dev/snd`.
- **Gerät `default`**: Mischt per `dmix`, alle Apps spielen gleichzeitig. Die Ausgabe
  (analog, HDMI, USB) wählt der Nutzer mit `ton ausgabe …`, die Konfiguration liegt in
  `/daten/system/ton/ton.conf`. Deshalb immer `default` öffnen, **nie** `hw:X,Y`.
- **Lautstärke** regelt das System (Regler „Saalburg“, Tasten der Tastatur). Eine App sollte
  keine Hardware-Regler stellen.
- **Aufnahme ist für alle gesperrt**, auch für Claude.
- **Neue Geräte**: Steckt der Nutzer im Betrieb USB-Lautsprecher ein, wählt Saalburg die
  Ausgabe neu. Eine App sollte ihr PCM-Gerät nach einem Fehler neu öffnen, statt abzubrechen.
- **Wach durch Ton**: Eine App, die gerade Ton abspielt, wird nicht eingefroren (siehe 8).

---

## 7. Netz

- Nur mit Recht `netzwerk` (Web-Apps: Standard an), sonst nur `lo`.
- **DNS**: `/etc/resolv.conf` zeigt auf `/run/netz/resolv.conf`. Die Datei kann sich im
  Betrieb ändern (Netzwechsel, Schalter), deshalb nicht dauerhaft zwischenspeichern.
- **Schutz vor Schadseiten** (ab Saalburg 202611241046, Standard an, nur der Nutzer schaltet ihn
  ab): Saalburg fragt Quad9 (9.9.9.9, 149.112.112.112, mit IPv6 auch 2620:fe::fe/::9), das
  bekannte Schad- und Betrugsseiten nicht auflöst (NXDOMAIN). Sperrt ein Netz Quad9, gelten
  die DNS-Server des Netzes. Folgen für Apps: Namen aus dem lokalen Netz (`fritz.box`,
  Rechnernamen ohne Punkt, `.local`) lösen in der Regel nicht auf – Geräte im LAN über ihre
  IP-Adresse ansprechen (wie bei `netz_ziele`); Netzlaufwerke mit Rechnernamen löst Saalburg
  selbst auf (Abschnitt 16). Zustand lesbar in `/run/netz/schutz`
  (`zustand aktiv|rueckfall|aus|wartet`), nur zur Anzeige.
- **TLS**: Die Wurzelzertifikate liegen in `/etc/ssl/certs/ca-certificates.crt`
  (Paket ca-certificates).
- **Kein mDNS oder Avahi**, keine Firewall-Regeln pro App: Mit Netzrecht ist das Netz offen.
- **Begrenztes Netz**: Ohne `netzwerk = ja` kann eine App einzelne LAN-Ziele bekommen
  (`netz_ziele`, `netzwerk = lan:<adresse>:<port>`); sie erreicht dann nur diese
  (Abschnitt 16).

---

## 8. Lebenszyklus

| Ereignis | Was passiert | Was die App tun sollte |
|---|---|---|
| Start | Ladeanzeige („startet …“) bis zum ersten Fenster | schnell ein erstes Fenster zeigen |
| Unsichtbar seit 10 s | `cgroup.freeze`: keine Rechenzeit, Speicher bleibt | Zeitgeber und Netzverbindungen müssen ein Einfrieren überstehen |
| Unsichtbar seit 2 min oder Speicher knapp | Speicher wird ausgelagert (`memory.reclaim`, verschlüsselte Auslagerung auf der SSD) | nichts, die Seiten kommen bei Bedarf zurück |
| Wieder sichtbar | sofort aufgetaut | |
| Fenster schließen (Windows-Taste+Q, Entf in der Übersicht) | `xdg_toplevel.close` bzw. `SIGHUP` beim Terminal; reagiert die App nach 3 s nicht, endet ihre cgroup hart (`cgroup.kill`) | `close` beachten, Stand speichern, beenden |
| Entfernen (Store-Seite³ oder `app entfernen`) | Der Nutzer wählt „Daten behalten“ (Standard) oder „Auch Daten löschen“. Läuft die App, wird sie vorher wie beim Schließen beendet (erst freundlich, nach 3 s hart); nach der Bestätigung am Bildschirm wird `/daten/apps/<kennung>` gelöscht, `$HOME` bleibt bzw. wird mit gelöscht | Daten so in `$HOME` ablegen, dass eine Neuinstallation sie wieder nutzen kann (Version mitspeichern, ältere Stände lesen können) |
| Ausschalten oder Neustart | `SIGTERM`, bis zu **12 s** Frist, danach hart | auf `SIGTERM` speichern und enden |
| Nach dem Neustart | Saalburg öffnet die App wieder auf ihrem Platz (Web-Apps mit der letzten Seite derselben Herkunft) | Stand beim Start wiederherstellen |
| Speichermangel | Der Kernel beendet zuerst schlafende Apps (oom_score_adj 800), dann wache (300), dann Claude (-500); Dienste haben -900 | regelmäßig speichern |

³ Knopf „Entfernen“ auf der Store-Seite ab Saalburg 202611230257 (Abschnitt 13); in der Übersicht öffnet
Strg+I die Store-Seite der markierten App. Mitgelieferte Apps haben keinen Knopf.

**Wach bleiben** Apps, wenn:
- ein Platz sie zeigt;
- sie Ton abspielen;
- Claude mit ihnen verbunden ist;
- sie `hintergrund = ja` haben. Das ist der Standard aus der app.conf, der Nutzer kann es
  abschalten. Nur verwenden, wenn die App unsichtbar wirklich weiterarbeiten muss, z. B. bei
  langen Rechnungen oder Synchronisation.

---

## 9. Claude-Anbindung

- **`verbindung = <Befehl>`**: Startet einen **MCP-Server über stdio**.
  - Der Server läuft **in der Sandbox der App**, unter ihrer Kennung und mit ihren Rechten.
    Er ist ein eigener Prozess, getrennt von der laufenden App.
  - Arbeitsordner ist `$HOME`, die Umgebung wie in Abschnitt 2, stderr geht nach
    `$HOME/verbindung.log`.
  - **Kanal zur laufenden App**: `$SAALBURG_APP_SOCKET` (= `$XDG_RUNTIME_DIR/app.sock`). Die
    laufende App hört dort (Unix-Socket, Rechte 0600), der MCP-Server verbindet sich bei jedem
    Werkzeugaufruf neu. Das Protokoll wählt die App (z. B. eine JSON-Zeile hin, eine zurück).
    Beide Prozesse haben dieselbe Kennung; claude und andere Apps kommen nicht an den Socket.
    Über `127.0.0.1` geht es **nicht**: App und MCP-Server haben ohne Netzrecht je einen eigenen
    Netz-Namensraum, abstrakte Unix-Sockets trennt Landlock.
  - Läuft die App nicht, soll das Werkzeug das klar sagen („… läuft gerade nicht – bitte
    öffnen“), statt zu warten. Der Server übersteht Neustarts der App, weil er je Aufruf neu
    verbindet.
  - Warum ein fester Socket und nicht „die laufende App ist selbst der MCP-Server“: Der
    MCP-Server lebt so lange wie die Sitzung in Claude Code, die App nicht. Schließt der Nutzer
    die App, bliebe Claude sonst mit einer toten Verbindung zurück (`/mcp` neu verbinden); so
    meldet das Werkzeug nur, dass die App zu ist, und klappt nach dem Öffnen wieder.
- **`steuerung = claude`**: Die App bietet Claude die Steuerung an. Der Nutzer stellt sie in den
  Einstellungen je App auf eine von drei Stufen:
  - **nein**: keine Verbindung;
  - **bei Bedarf** (Voreinstellung, ab Saalburg 202611251640; davor war die Steuerung bis zum
    Einschalten aus): Claude fordert die Steuerung mit einer kurzen Begründung an, der Nutzer
    bestätigt sie jedes Mal im Bestätigungsdialog am Bildschirm (Claude kann das nicht). Sie endet,
    wenn Claude sie zurückgibt, nach 10 Minuten ohne Befehl oder wenn der Nutzer sie beendet (Klick
    auf „Claude steuert …“ in der Leiste, Windows-Taste+Esc);
  - **ja**: immer an (wie vor 202611251640 nach dem Einschalten).

  Bestehende Einstellungen bleiben, wie sie sind.
  - Claude erreicht den Server als `app verbinden <kennung>`. Bei Bedarf bietet die Verbindung
    zusätzlich die Werkzeuge `steuerung_anfordern` (Argument `begruendung`) und
    `steuerung_zurueckgeben` an; im Terminal `app steuerung anfordern|zurueckgeben|stand`.
  - **Eigener MCP-Server bei Bedarf**: Er startet erst mit der Freigabe und wird an ihrem Ende
    beendet (SIGTERM an seine Prozessgruppe). Bis dahin beantwortet die Verbindung `initialize` und
    `tools/list` selbst (nur die zwei Werkzeuge oben); danach meldet sie Claude Code
    `notifications/tools/list_changed` und reicht das `initialize` des Clients an den Server
    weiter. Der Server muss dafür nichts Besonderes können. Die Zeit ohne Befehl misst Saalburg an
    der Ein- und Ausgabe des Servers.
  - Die Leiste zeigt „⇄ <App>“ bzw. „Claude steuert <App>“ (bei Bedarf, solange erteilt, mit
    Restzeit; ein Klick darauf beendet die Steuerung).
- **Web-Apps** brauchen keinen eigenen Server, sie bekommen die Browser-Steuerung des Systems:
  - Werkzeuge: `seite_lesen`, `bildschirmfoto`, `klicken`, `eingeben`, `taste`, `oeffnen`,
    `scrollen`, `warten`, `zurueck`, `javascript`;
  - Technik: DevTools-Pipe über ein Relais nur in der Sandbox der App, nie ein offener Port.
    Sie gilt erst nach einem Neustart der App.
  - **Mit Pipe melden Seiten `navigator.webdriver = true`**, manche Dienste sperren dann
    (z. B. Reddit). Saalburg versteckt das bewusst nicht. Bei Bedarf läuft Chromium deshalb im
    Alltag ohne Pipe (`navigator.webdriver = false`); nach der Freigabe startet Saalburg die App
    mit Pipe neu und am Ende wieder ohne. Das Profil bleibt dabei, also Anmeldungen, Cookies und
    die zuletzt offene Seite bzw. beim Browser die Tabs. Ein sichtbares Fenster kommt auf seinen
    Platz zurück; eine nicht sichtbare App wird am Ende nur beendet (sie öffnet beim nächsten
    Start ohne Pipe). Web-Apps sollten den Neustart daher vertragen (Zustand nicht nur im
    Speicher der Seite halten).
- **Claude kann nicht**:
  - Bestätigungen am Bildschirm geben (Installationen, Rechte, Dateizugriffe);
  - Tastatur oder Maus der Oberfläche bedienen;
  - Bildschirmfotos fremder Fenster machen;
  - die Daten einer App ohne Freigabe lesen.

  Was Claude mit der App tun soll, muss die App als MCP-Werkzeug anbieten.

---

## 10. Web-Apps

- **Chromium 158** im App-Modus (ohne Browserleiste), Wayland, GPU-Beschleunigung, Sprache
  Deutsch (Oberfläche und `Accept-Language`; vor Saalburg 202611231841 fehlte die deutsche
  Sprachdatei, Chromium war englisch).
- **Profil je App** in `$HOME/.cache/profil`, mit getrennten Anmeldungen. Passwörter speichert
  Chromium im eigenen Speicher (`--password-store=basic`), einen Schlüsselbund gibt es nicht.
- **Flags, die Saalburg setzt**:
  - `--force-dark-mode`: Seiten sehen `prefers-color-scheme: dark`;
  - Grundzoom passend zur Schriftgröße der Oberfläche (28 px = 100 %), als **Seitenzoom** im
    Profil (`partition.default_zoom_level`), nicht als erzwungener Gerätefaktor: Der Puffer
    passt genau zum Fenster, `devicePixelRatio` folgt dem Zoom (z. B. 1,14). Eigene
    Zoomstufen je Seite (Strg+Plus/Minus) bleiben erhalten. Seiten daher mit relativen Größen
    und Media Queries bauen, nicht mit festen Pixelbreiten fürs Fenster;
  - `--disable-background-networking`, `--disable-component-update`;
  - Übersetzen und MediaRouter sind aus.
- **Erweiterungen**: keine eigenen. Die einzige ist das Saalburg-Aussehen.
- **Saalburg-Aussehen**: Bringt das Paket ein `aussehen.css` (optional `aussehen.js`) mit,
  baut Saalburg daraus eine Erweiterung ohne Rechte, nur für den Host der Start-URL und seine
  Unterdomänen, geladen bei `document_start` in allen Frames.
  - **Abschalten**: Der Nutzer kann es in den Einstellungen („An Saalburg angleichen“)
    abschalten. Mit `angleichen = nein` in der app.conf ist es für die App aus und erscheint
    dort nicht; Voreinstellung `ja`. Nur `ja`/`nein`, ab Saalburg 202611221956 (ältere
    Versionen lehnen den Schlüssel als unbekannt ab, also `saalburg` mindestens so setzen).
  - **Regeln**: nur `var(--saalburg-…)`, keine eigenen Farbwerte oder Schriften (siehe
    `CLAUDE.md`).
  - **Variablen** aus `/usr/lib/osproto/aussehen/saalburg.css`:

  | Variable | Bedeutung |
  |---|---|
  | `--saalburg-grund` | Hintergrund der Seite |
  | `--saalburg-seite` | Seitenleisten, dunkler als der Grund |
  | `--saalburg-karte`, `--saalburg-karte-hell` | Flächen, Karten bzw. hervorgehobene Karte |
  | `--saalburg-linie` | Trennlinien, Ränder |
  | `--saalburg-text`, `--saalburg-hell`, `--saalburg-leise`, `--saalburg-aus` | Text normal, betont, leise, deaktiviert |
  | `--saalburg-akzent`, `--saalburg-akzent-hell`, `--saalburg-blau` | Akzent (Links, Knöpfe), Hover, Flächen-Akzent |
  | `--saalburg-gut`, `--saalburg-warn`, `--saalburg-fehler` | Erfolg, Warnung, Fehler |
  | `--saalburg-wasch`, `--saalburg-wasch-mehr`, `--saalburg-akzent-wasch` | halbdurchsichtige Hover- und Auswahlflächen |
  | `--saalburg-schrift-text` | Fließtext-Schrift (Nutzerwahl, über fontconfig `sans-serif`) |
  | `--saalburg-schrift-fest` | feste Schrift für Code und Terminal (Nutzerwahl, `monospace`) |
  | `--saalburg-schrift` | wie `--saalburg-schrift-text` (älterer Name, bleibt gültig) |
  | `--saalburg-akzent-text`, `--saalburg-auswahl`, `--saalburg-info` | Text auf Akzentfläche, Markierung, Hinweis (ab Saalburg 202611240808) |
  | `--saalburg-abstand`, `--saalburg-rundung` | Abstand-Grundmaß und Eckenradius bei 100 % (der Seitenzoom skaliert sie; ab Saalburg 202611240808) |

  Die Schriftwahl des Nutzers (Einstellungen → Darstellung) steht in
  `/daten/system/schrift/fonts.conf` und gilt für Web-Apps beim nächsten Start. Eigene
  Schriftnamen oder `@font-face` in `aussehen.css` lehnt die Katalogprüfung ab.

  `saalburg.css` setzt außerdem `color-scheme: dark`, Bildlaufleisten, Markierung und
  Fokusrahmen.
- **Einschränkungen**:
  - Ein Dateidialog öffnet nur die Ordner der App, praktisch `Dokumente` (Lesezeichen in der
    Seitenleiste). Andere Dateien holt der Nutzer mit Windows-Taste+O dorthin. Ab Saalburg
    202611241934 erscheint der Dialog (GTK) sofort auf dem Platz der Web-App, hat die Tastatur und ist
    deutsch.
  - Keine Web-Benachrichtigungen ans System (Chromium kennt den Dienst nicht), kein
    Teilen-Dialog, keine Kamera, kein Mikrofon.
  - Keine Erweiterungen aus dem Web Store.

### Mitgelieferter Browser (ab Saalburg 202611231841)

Saalburg bringt einen allgemeinen Browser mit (Kachel „Browser“): Chromium mit Tabs und
Adressleiste, kein App-Modus. Er ist Teil des Systems und wird mit dem System-Update
aktualisiert, nicht über den Katalog.
- **Sandbox wie eine Web-App**: Kennung `browser`, Daten `/daten/appdaten/browser`, eigenes
  Profil; kein Zugriff auf die Profile und Anmeldungen der Web-Apps, auf Claudes Dateien oder auf
  den Rest von `/daten`. Rechte (Netz, GPU, Ton, Hintergrund, Dokumente für Claude) wie bei
  Web-Apps in den Einstellungen.
- **Eigene Chromium-Richtlinien**, nur für den Browser: Suche über Google (deutsch) ohne
  Vorschläge beim Tippen (vor Saalburg 202611240808: DuckDuckGo), Übersetzen nur auf Anfrage
  (Chromium bietet es an, Rechtsklick → „Übersetzen“; nie automatisch, ab Saalburg 202611240808),
  kein Safe Browsing (ab Saalburg 202611241046 abgeschaltet und ohne Netz im Hintergrund wie bei
  Web-Apps: Google gibt dem mitgelieferten Chromium die Listen nicht, die Schnittstelle ist nur
  nicht-kommerziell frei; vor Schadseiten schützt der DNS-Schutz, Abschnitt 7), kein
  Passwortspeicher und kein Autofill,
  Drittanbieter-Cookies gesperrt, keine Telemetrie,
  kein Hintergrundbetrieb, keine Komponenten-Updates, keine Erweiterungen, Benachrichtigungen,
  Standort, Kamera und Mikrofon gesperrt, `file://` nur für die Startseite und die eigenen
  Dokumente. Die Web-Apps behalten ihre bisherigen Richtlinien.
- **Darstellung**: dunkel (`--force-dark-mode`, Seiten sehen `prefers-color-scheme: dark`),
  Oberfläche in Saalburg-Blau, Systemtitelleiste (Rahmen von Saalburg, keine eigenen Knöpfe für
  Minimieren, Maximieren, Schließen; ab Saalburg 202611240808), Seitenzoom nach Schriftgröße wie bei Web-Apps; Webseiten selbst
  bleiben unverändert (kein Saalburg-Aussehen).
- **Startseite und Neuer Tab**: lokale Seite ohne Skript und ohne Netz. Nach einem Neustart
  öffnet er die Tabs der letzten Sitzung.
- **Downloads** landen in `/daten/appdaten/browser/Dokumente`; weitergegeben wird wie bei allen
  Apps über den Dateidienst.
- **Steuerung durch Claude**: angeboten, Stufen wie bei Web-Apps (Abschnitt 9; ab Saalburg
  202611251640 Voreinstellung „bei Bedarf“, davor aus bis zum Einschalten). Die Werkzeuge wirken
  auf den sichtbaren Tab; dazu `tabs`, `tab_wechseln`, `tab_neu`, `tab_schliessen`. Beim Neustart
  für die Steuerung kommen alle Tabs wieder.
- Apps können den Browser nicht aufrufen (kein `xdg-open`); Links für den Nutzer als Text
  zeigen oder in die Zwischenablage legen.


---

## 11. Laufzeiten und Bibliotheken

Im System sind unter anderem diese Pakete (Alpine 3.24, Stand des Images):

| Bereich | Pakete |
|---|---|
| Shell, Werkzeuge | busybox 1.37, bash 5.3, nano, less, git, curl, ripgrep, poppler-utils (pdftoppm), alsa-utils |
| Python | **python3 3.14** mit numpy 2.4, scipy 1.17, Pillow 12.2, PyYAML, requests, pip; **numba 0.68** und llvmlite (selbst gebaut, gegen LLVM 22) |
| Grafik | Mesa 26.1 (EGL, GLES, GBM, Iris), libdrm, libxkbcommon, cairo, pango, harfbuzz, freetype 2.14, fontconfig |
| GUI-Toolkits | GTK 3.24 und GTK 4.22 (als Abhängigkeit von Chromium; Wayland-Backend) |
| Ton | alsa-lib 1.2 |
| Medien | gstreamer 1.28 (Grundpaket), ffmpeg-Teile über Chromium |
| Sonstiges | sqlite, zlib, libpng, libjpeg-turbo, libgomp (OpenMP), ca-certificates |
| Schriften | DejaVu, Open Sans, Terminess (Nerd Font Mono, `monospace`); `fc-match monospace`/`sans-serif` folgt der Nutzerwahl |

Prüfen lässt sich das auf Saalburg:
- Paketliste: `apk info -v` im Systemabbild ist lesbar, `apk add` geht nicht;
- Python-Pakete: `python3 -c "import numpy; print(numpy.__version__)"`.

Hinweise:
- **Eigene Abhängigkeiten** gehören ins Paket der App:
  - statisch gelinkte Programme (z. B. Zig, Go) oder musl-Builds;
  - Python-Pakete als reine Python-Dateien oder als musllinux-Wheels, entpackt im Paket.
  - `pip install` zur Laufzeit geht nur mit Netzrecht und nur nach `$HOME`, PEP 668 sperrt
    das System-Python.
- **Größe**: Ein Paket darf bis 1 GB groß sein und bis 20 000 Einträge haben, `app.conf` bis
  4000 Bytes.
- **Neue Systempakete**: Was nur im System fehlt (Bibliothek, Schrift), als Issue im
  Saalburg-Repo beantragen, nicht im Paket nachbauen.

### Prozessor: Befehlssatz

Alle Rechner, auf denen Saalburg läuft, haben AVX2 und FMA (`x86_64_v3`). Nutzt es, wo es
wirklich rechnet (Bildverarbeitung, Geometrie, Simulation); für alles andere bringt es kaum
etwas.

- **Normale Apps**: für `x86_64_v2` bauen – Zig `-target x86_64-linux-musl -mcpu x86_64_v2`
  (bzw. `-Dcpu=x86_64_v2` mit `build.zig`), GCC/Clang `-march=x86-64-v2`, Rust
  `-C target-cpu=x86-64-v2`.
- **Rechenintensive Apps**: am besten beides – die heißen Funktionen zusätzlich mit AVX2
  übersetzen und per `cpuid` zur Laufzeit wählen. Ein reiner `x86_64_v3`-Build ist erlaubt.
- **Testen**: Das Testsystem ohne KVM (saalburg-test, QEMU) hat AVX2 standardmäßig **aus**
  (QEMU rechnet AVX2-Gather falsch; Chromium stürzte daran ab). Ein reiner v3-Build stürzt dort
  mit `SIGILL` (Illegal instruction) ab. Dann mit `SAALBURG_TEST_CPU=max` prüfen (nur für native
  Apps sinnvoll) oder auf dem Testplatz (Abschnitt 15) am echten Rechner.
- Numba/llvmlite im System erkennen die CPU selbst und brauchen nichts davon.

---

## 12. Befehle für Entwickler

Diese Befehle laufen als claude (oder ein anderer Benutzer), ohne root:

| Befehl | Zweck |
|---|---|
| `app schluessel-erzeugen <name>` | Schlüsselpaar für eigene Pakete (`~/.osapp/<name>.key/.pub`) |
| `app packen <ordner> <name.key> <ziel.osapp>` | Ordner mit `app.conf` signiert packen; prüft das Format |
| `app pruefen <paket.osapp>` | Paket und Rechte ansehen, ohne zu installieren |
| `app katalog <ordner> <name.key> [titel]` | lokalen Katalog bauen (mit `store/<kennung>/` für die Store-Seite) |
| `app store liste` bzw. `app store daten` | Kataloge lesen (lesbar bzw. maschinenlesbar) |
| `app installieren <paket.osapp>`, `app store installieren <k>` | installieren; **der Nutzer bestätigt am Bildschirm** |
| `app liste`, `app zurueck <k>`, `app entfernen <k> [--daten]` | installierte Apps; Änderungen nur mit Bestätigung (`--daten` löscht auch `$HOME` der App) |
| `app einstellung [<k> <recht> ja\|nein]` | Rechte ansehen; Änderungen nur mit Bestätigung (`steuerung` auch `bedarf`) |
| `app verbindungen`, `app verbinden <k>` | MCP-Verbindungen zu Apps |
| `app steuerung anfordern <k> "<Begründung>"`, `app steuerung zurueckgeben <k>`, `app steuerung stand [k]` | Steuerung bei Bedarf (der Nutzer bestätigt am Bildschirm) |
| `app datei …` | Dateidienst (siehe 3) |
| `app system version` | laufende Saalburg-Version |
| `ton …`, `drucken …`, `webfenster <url>` | Ton, Drucken per IPP (claude; Apps über den Dienst), Web-Fenster neben Claude |
| `saalburg oeffnen\|speichern\|melden\|drucken …`, `notify-send` | Dienst der Oberfläche (nur in der Sandbox einer App, siehe 3) |

Einem neuen Herausgeber vertraut das System erst nach `app schluessel-vertrauen <name.pub>`
und einer Bestätigung am Bildschirm. Der öffentliche Katalog ist mit dem mitgelieferten
Schlüssel `saalburg-katalog` signiert.

---

## 13. Mindestversion (`saalburg = JJJJMMTTHHMM`, UTC)

Braucht eine App eine Fähigkeit aus der Tabelle, setzt sie `saalburg` auf die Version, mit der
diese Fähigkeit kam. Ältere Systeme zeigen dann „Braucht Saalburg vom …“ und installieren erst
nach dem Update.

| Version | Neu für Apps |
|---|---|
| 202611191237 | Grundstand für Updates übers Netz: Sandbox, App-Verwaltung, Store, Web-Apps, Verbindungen, Ton, Drucken |
| 202611191904 | Dateidienst und Dateien-App, `Dokumente` je App |
| 202611200024 | USB-Sticks, Papierkorb, Hochladen in Web-Apps |
| 202611201315 | Einfrieren und Auslagern, `hintergrund`, Sitzung über Neustarts, SIGTERM mit 12 s |
| 202611201726 | Ladeanzeige, Ping/Pong-Anzeige „reagiert nicht“ |
| 202611211743 | Store-Seite: `kategorie`, `saalburg`, Store-Texte und -Bilder |
| 202611212155 | Ton über USB-Lautsprecher |
| 202611212226 | DNS und Ton bleiben nach Netz- und Gerätewechseln in laufenden Apps gültig |
| 202611220151 | Web-Apps dunkel (`--force-dark-mode`) |
| 202611221801 | Saalburg-Aussehen (`aussehen.css`/`.js`), Web-Zoom nach Schriftgröße, Zwischenablage mit `image/png` |
| 202611221956 | Wählbare Schriften (`--saalburg-schrift-fest`/`-text`, fontconfig), app.conf `angleichen = ja\|nein` |
| 202611222058 | Web-Zoom als Seitenzoom statt erzwungenem Geräte-Faktor (Fenster nicht mehr abgeschnitten, `devicePixelRatio` folgt dem Zoom) |
| 202611230126 | App-Lücken: Dienst der Oberfläche (Öffnen, Speichern, Meldungen, Drucken mit `drucken = ja`), eigenes `/tmp`, `SAALBURG_APP_SOCKET`, Wayland: Vollbild, Minimieren, Viewporter, Fractional Scale, Pointer-Constraints, Relative-Pointer, Cursor-Shape, Idle-Inhibit |
| 202611230257 | Entfernen auf der Store-Seite (Wahl: Daten behalten oder `$HOME` mitlöschen; laufende App wird vorher wie beim Schließen beendet), Strg+I in der Übersicht öffnet die Store-Seite einer App |
| 202611231526 | Fernzugriff (`fernzugriff`, `fernzugriff_sicher`, `$SAALBURG_FERN_SOCKET`, Abschnitt 16), begrenztes Netz (`netz_ziele`, `netzwerk = lan:…`), Netzlaufwerke (`netzlaufwerk`), Testplatz (Abschnitt 15) |
| 202611231841 | Mitgelieferter Browser (Tabs, eigene Sandbox und Richtlinien, Kennung `browser` reserviert); Wayland: Tastaturfokus wird mit dem ersten Bild eines Fensters noch einmal gemeldet; Chromium-Oberfläche und Accept-Language deutsch (Browser und Web-Apps) |
| 202611240808 | Aussehen für native Apps (`/daten/system/aussehen/saalburg.conf`, Vorgaben in `/usr/lib/osproto/aussehen/`, Abschnitt 5; neue CSS-Variablen `--saalburg-akzent-text`, `-auswahl`, `-info`, `-abstand`, `-rundung`); Testplatz: Testpaket unter `/daten/apps/<kennung>/aktuell` (Katalog-Pfade laufen); Browser: Google-Suche, Übersetzen auf Anfrage, Systemtitelleiste |
| 202611241046 | DNS über Quad9 (Schutz vor Schadseiten, Standard an; lokale Namen lösen nicht mehr auf, Abschnitt 7); Netzlaufwerke mit Rechnernamen; linux-dmabuf Version 4 mit Rückmeldung (native Apps mit `gpu = ja` finden die GPU über Mesa/EGL auf Wayland), `gpu` gibt nur die Render-Knoten frei; Browser ohne Safe Browsing und ohne Netz im Hintergrund; Store-Beschreibung bis 1200 Zeichen statt Bytes (Umlaute zählen einfach) |
| 202611241934 | Dialoge (`xdg_toplevel.set_parent`, xdg-foreign v1/v2) auf dem Platz ihres Elternfensters mit Fokus, GTK-Dateidialog der Web-Apps deutsch; Bildschirmfotos: jedes Foto ein neues Ablage-Angebot, andere Typen als `image/png`/Text liefern nichts; Testplatz: Test-Apps dürfen melden und (mit `drucken = ja`) drucken; Drucken: PDF/PNG für Drucker ohne diese Formate eingesperrt in JPEG-Seiten umgewandelt, ipps:// wenn der Drucker TLS verlangt |
| 202611251640 | Steuerung durch Claude in drei Stufen (nein / bei Bedarf / ja), Voreinstellung „bei Bedarf“: Claude fordert mit Begründung an (`steuerung_anfordern`, `app steuerung anfordern`), der Nutzer bestätigt am Bildschirm; Web-Apps und Browser laufen im Alltag ohne DevTools-Pipe (`navigator.webdriver = false`) und starten für die Steuerung mit Pipe neu (Profil und Tabs bleiben); Ende durch Rückgabe, nach 10 min ohne Befehl oder durch den Nutzer (Leiste, Windows-Taste+Esc); eigener MCP-Server bei Bedarf erst mit der Freigabe |
| 202611251957 | Weitere Hardware: AMD-Grafik (amdgpu, Mesa radeonsi) nutzbar wie Intel; ohne passenden Grafiktreiber läuft die Oberfläche über das Bild der Firmware (simpledrm) ohne GPU – dann gibt es keinen Render-Knoten, Apps mit `gpu = ja` zeichnen per Software. Bildschirmauflösung kann je Gerät abweichen |

---

## 14. Checkliste: eine App, die sich gut einfügt

- [ ] Kennung aus Kleinbuchstaben, Ziffern, Bindestrich; `version` bei jeder Änderung erhöht.
- [ ] Nur die Rechte, die nötig sind (`netzwerk`, `gpu`, `ton`, `drucken`, `ordner`, `hintergrund`).
- [ ] Läuft unter musl, ohne glibc, ohne X11, ohne D-Bus und ohne Tondienst.
- [ ] Schreibt nur nach `$HOME`, `$TMPDIR` und `$XDG_RUNTIME_DIR`. Was der Nutzer sehen oder
      weitergeben soll, kommt nach `$HOME/Dokumente`; Öffnen/Speichern woanders über
      `saalburg oeffnen|speichern`.
- [ ] Nimmt jede Fenstergröße an, die `configure` vorgibt, und blockiert die
      Ereignisschleife nie lange (Ping/Pong).
- [ ] Speichert auf `SIGTERM` und `xdg_toplevel.close` binnen weniger Sekunden und stellt den
      Stand beim Start wieder her.
- [ ] Übersteht Einfrieren, Auftauen und Netzwechsel; öffnet ALSA `default` nach einem Fehler
      neu.
- [ ] Ton über ALSA `default`, nie über feste Hardware-Geräte.
- [ ] Web-Apps: `aussehen.css` nur mit `var(--saalburg-…)`.
- [ ] Native Apps: Grundflächen, Text, Rahmen, Akzent, Schrift und Größe aus
      `saalburg.conf` (Abschnitt 5, „Aussehen für native Apps“), mit Ausweichwerten; eigene
      Farben nur für Inhalte.
- [ ] Was Claude tun können soll, ist ein MCP-Werkzeug (`verbindung`, `steuerung = claude`);
      gefährliche Schritte fragen in der App selbst nach. Der MCP-Server spricht mit der
      laufenden App über `$SAALBURG_APP_SOCKET` und meldet, wenn sie nicht läuft.
- [ ] Fernzugriff nur über `$SAALBURG_FERN_SOCKET`, relative Links, Steuerfunktionen in
      `fernzugriff_sicher`; LAN-Ziele über `netz_ziele`, nie eine Adresse raten (Abschnitt 16).
- [ ] Store-Text und Bilder ohne private Daten; mit `saalburg-test` getestet, bei Bedarf auch auf dem
      Testplatz (Abschnitt 15).

---

## 15. Testplatz: auf dem echten Rechner testen

Zusätzlich zur QEMU-Umgebung (`saalburg-test`) kann ein App-Chat seine App auf dem echten
Rechner testen, in einem Fenster mit gelb-schwarzem TEST-Rahmen. Das geht nur, solange der
Eigentümer den Testplatz am Bildschirm freigeschaltet hat (1, 4 oder 8 Stunden; die Leiste zeigt
„TESTPLATZ h:mm“). Sonst lehnt Saalburg jeden Auftrag ab.

**Ablauf**
1. Im Pull Request dieses Repos `/testplatz` kommentieren, bei mehreren geänderten Apps
   `/testplatz <kennung>`. Der Ablauf „Testpaket“ baut `apps/<kennung>/` aus dem PR, signiert
   mit dem **Testschlüssel** und antwortet mit einer Zeile
   `paket kennung=<k> pr=<n> sha256=<…>`. Angenommen werden nur Kommentare des
   Eigentümer-Kontos und nur PRs aus diesem Repo.
2. Im privaten Repo `timelesstalesclassics/saalburg-test` ein Issue mit dem Label
   `testplatz` anlegen (Titel „Testplatz: <kennung> – saalburg-katalog PR #<n>“) und einen
   Auftragsblock als Codeblock mit der Sprache `testplatz` schreiben, als Text des Issues oder
   als Kommentar. Jeder Block läuft genau einmal.
3. Nach einigen Sekunden antwortet der Testplatz als Kommentar: je Befehl `ok` oder `FEHLER: …`,
   Messwerte, gefilterte Protokolle; Fotos als PNG im Zweig `testplatz-ergebnisse`, verlinkt.

Beispiel:

````
```testplatz
paket kennung=youtube pr=12 sha256=<aus dem PR-Kommentar>
installieren
starten
foto start
klicken 640 400
tippen Suchbegriff
taste Enter
warten 2
foto ergebnis
messwerte
protokoll 100
beenden
```
````

**Befehle** (höchstens 60 je Block, zusammen höchstens 3 Minuten):

| Befehl | Wirkung |
|---|---|
| `paket kennung=<k> pr=<n> [sha256=<hex>]` | welche App, Quelle Katalog-PR; zuerst |
| `paket kennung=<k> quelle=privat release=<tag> [sha256=<hex>]` | Quelle: privates Testpaket (siehe unten) |
| `installieren` | Testpaket prüfen (Testsignatur, Prüfsumme) und in den Testplatz legen |
| `starten`, `beenden`, `neu-laden`, `warten-auf-fenster` | Lebenszyklus; `starten` wartet aufs Fenster |
| `entfernen [daten]` | Test-App entfernen, mit `daten` auch ihre Testdaten |
| `warten <s>` | höchstens 30 s |
| `foto [name]` | Bild **nur des Testfensters** (ohne Rahmen, ohne Rest des Bildschirms) |
| `klicken <x> <y> [rechts\|doppelt\|mitte]`, `ziehen <x1> <y1> <x2> <y2>`, `rad <x> <y> <n>` | Maus, Koordinaten im Testfenster |
| `tippen <text>`, `taste <Name>` | Tastatur (deutsche Belegung); Namen: Enter, Tab, Esc, Rueck, Entf, Links/Rechts/Hoch/Runter, Pos1, Ende, BildAuf/BildAb, Leer, F1–F12, Buchstaben, mit `Strg+`, `Umschalt+`, `Alt+` |
| `protokoll [zeilen]` | stdout/stderr der App (`$HOME/testplatz.log`), bei Web-Apps `chromium.log`, dazu `verbindung.log`; gefiltert |
| `messwerte` | RAM, Spitze, Prozesse, CPU, Fenstergröße, Bilder je Sekunde |
| `ton` | spielt die App gerade Ton ab? |
| `mcp <methode> [json]` | an den MCP-Server der App (`tools/list`, `tools/call`, `resources/…`); Web-Apps: die Browser-Steuerung. Gleiche Schutzregeln wie `foto`/Eingaben/`protokoll` (unten) |

Eingaben gehen nur an das Testfenster, nie an andere Fenster; Systemkürzel (Windows-Taste)
gibt es nicht.

**Die Test-App** läuft getrennt von echten Apps: eigene Kennung (UID ab 30000), Daten unter
`/daten/testplatz/daten/<kennung>` statt `/daten/appdaten`, keine `ordner =`, kein Dateidienst,
nicht in der Übersicht. Rechte genau wie die `app.conf` verlangt (Netz, GPU, Ton, Drucken). Web-Apps
bekommen die Browser-Steuerung immer (nur der Testplatz verbindet sich).
**Dienst der Oberfläche** (`$SAALBURG_DIENST`, ab Saalburg 202611241934): `MELDEN` erscheint in der
Leiste als „TEST <Name>: …“. `DRUCKEN` geht mit `drucken = ja`; der Bestätigungsdialog heißt
„TEST: <Name> möchte drucken“, bestätigen kann nur der Nutzer am Bildschirm (Antwort `OK`,
`ABBRUCH` oder `FEHLER …` wie bei echten Apps). `OEFFNEN` und `SPEICHERN` antworten
`FEHLER auf dem Testplatz nicht verfügbar`. Vorher bekam jede Anfrage einer Test-App
`FEHLER Nur für Apps in der Sandbox`.
**Pfade wie bei echter Installation** (ab Saalburg 202611240808): Das Testpaket liegt auf dem
Rechner unter `/daten/testplatz/apps/<kennung>`, erscheint für die Test-App und ihren MCP-Server
aber unter `/daten/apps/<kennung>/aktuell` (nur lesbar). Eine `app.conf` mit absoluten Pfaden
wie im Katalog (`start = exec /daten/apps/<kennung>/aktuell/<datei>`, ebenso `verbindung`) läuft
damit unverändert. Andere installierte Apps sieht die Test-App dort nicht; ist dieselbe Kennung
echt installiert, sieht sie nur ihr Testpaket, die echte Installation bleibt unberührt. Vorher
fand die Test-App solche Pfade nicht („not found“).

**Netz der Test-App** (`netzwerk = ja`): eigener Netz-Namensraum.
- `127.0.0.1`/`::1` sind die eigene Schleife der App: Ein Server der App auf 127.0.0.1 (z. B.
  WebDriver einer eingebauten Browser-Engine) ist für die App und ihren MCP-Server erreichbar,
  für niemanden sonst. Dienste des Rechners (SSH …) sind von dort nicht zu erreichen – weder
  über 127.0.0.1 noch über seine LAN-Adresse.
- Nach außen nur **Internet** (IPv4, NAT). LAN, private, Link-lokale und Multicast-Adressen
  sind gesperrt. Namensauflösung geht über die DNS-Server des Rechners aus
  `/run/netz/resolv.conf` (Quad9 oder die des Netzes; nur Port 53 an genau diesen Adressen).
- Ohne `netzwerk = ja`: nur die eigene Schleife, kein Weg nach außen.
- LAN-Ziele (`netz_ziele`, `netzwerk = lan:…`), Netzlaufwerke und Fernzugriff (Abschnitt 16)
  bekommen Test-Apps nie, auch wenn ihre `app.conf` sie nennt.

**Private oder große Testpakete** (keine Katalog-App, private App, Paket über 100 MB): im
privaten `saalburg-test` einen Zweig `testpaket/<name>` pushen mit `testpaket.conf`
(`kennung = <k>`, `sha256 = <sha256 von app.tar>`) und dem App-Ordner als tar in Teilen:
`tar -cf app.tar -C <app-ordner> . && split -b 50M app.tar teile/app.tar.` Der Ablauf dort
prüft wie dieser Katalog, signiert mit dem Testschlüssel, legt ein Release mit Anhang
`<k>.ostest` (bis 1 GB) an, löscht den Zweig und schreibt die Auftragszeile
`paket kennung=<k> quelle=privat release=<tag> sha256=<…>` in den Release-Text
(`gh api repos/timelesstalesclassics/saalburg-test/releases/tags/<tag>`).

**MCP** unterliegt denselben Regeln wie `foto`, Eingaben und `protokoll`: im Sichtschutz
abgelehnt; Argumente mit 4–8-stelligen Ziffernfolgen werden nicht übergeben (bei Web-Apps
auch keine Eingabe in Passwort-/Code-Felder); in Antworten werden Bilder, Ton und
Binärdaten entfernt (für Bilder `foto` benutzen), Werte unter `cookie`, `token`, `password`,
`authorization`, `session` u. Ä. ersetzt und alle Texte gefiltert; was kein JSON ist, kommt
nicht an.

**Anmeldung**: Je App stellt der Eigentümer eine Stufe ein.
- *abgemeldet* (Standard): alles kommt beim Chat an.
- *Testkonto*: Der Eigentümer meldet sich selbst im Testfenster an. Solange er dort tippt oder
  klickt (und 15 s danach) oder den Knopf „Sichtschutz“ gedrückt hat, lehnt der Testplatz Fotos
  und Eingaben ab – einfach später wiederholen.
- *echtes Konto*: keine Fotos, nur Text (ok/Fehler, Messwerte, streng gefilterte Protokolle;
  MCP-Antworten nur „erfolgreich“ oder „Fehler“, außer `tools/list`). Ein `foto` landet beim Eigentümer zum
  Schwärzen; erst nach seiner Freigabe kommt es als eigener Kommentar ins Issue.

**Nie** (Saalburg lehnt ab): Passwörter oder Codes tippen (Ziffernfolgen mit 4–8 Stellen, auch
über MCP; bei Web-Apps nichts in Passwort- oder Code-Felder; bei anderen Engines kann Saalburg
Passwortfelder nicht erkennen – Anmeldefelder dort nicht ansteuern), Anmelde-QR-Codes weitergeben (jeder QR-Code
im Foto wird geschwärzt), Zwei-Faktor-Abfragen bestätigen. Zugangsdaten gehören weder in
Blöcke noch in Repos; Protokolle werden vor dem Senden gefiltert.

**Öffentlich bleibt nur**: im PR die Zeile mit der Prüfsumme und höchstens
„Getestet auf dem Testplatz, Bericht privat“. Store-Bilder dürfen aus Fotos der Stufe
*abgemeldet* stammen, wenn sie nur Beispielinhalte zeigen.

---

## 16. Fernzugriff, begrenztes Netz, Netzlaufwerke

### Fernzugriff (gekoppelte Geräte im LAN)

Ein mit Saalburg gekoppeltes Gerät (gedacht: iPhone mit Safari) erreicht im lokalen Netz die
Web-Oberfläche einer App. Der Nutzer schaltet den Fernzugriff in den Einstellungen ein (Standard:
aus), koppelt Geräte per QR-Code (Einmalcode, danach ein Gerätetoken) und kann sie jederzeit
entfernen. Saalburg spricht HTTPS auf **einem Port** (8443): Startseite unter `/`, jede App unter
`/apps/<kennung>/`.

- **app.conf**:
  - `fernzugriff = /, /api` – Pfade, die gekoppelte Geräte erreichen dürfen (Präfixe; `/` = alles).
  - `fernzugriff_sicher = /werkstatt` – heikle Pfade: brauchen je Gerät eine eigene Freigabe am
    Bildschirm (Standard: aus). Heikle Pfade gehen vor: was darunter liegt, ist heikel, auch
    wenn `fernzugriff = /` gesetzt ist. Höchstens 8 Pfade je Zeile, nur `A–Z a–z 0–9 / - _ .`,
    kein `..`, kein `//`, kein `/` am Ende. Beides erscheint im Installationsdialog.
- **Verbindung zur App**: Saalburg setzt `SAALBURG_FERN_SOCKET=$XDG_RUNTIME_DIR/fern.sock`.
  Die App betreibt dort einen **HTTP/1.1-Server am Unix-Socket** (kein Netzrecht nötig, kein
  Port, kein 127.0.0.1). Socket beim Start anlegen (alte Datei vorher löschen). Jede Anfrage
  kommt auf einer **eigenen Verbindung** mit `Connection: close`; kurze Anfragen warten also nie
  hinter langen (Longpoll, große Downloads).
- **Pfade**: Das Gerät ruft `https://<adresse>:8443/apps/<kennung>/<pfad>` auf; die App
  bekommt `/<pfad>` (ohne Präfix) und dazu `X-Forwarded-Prefix: /apps/<kennung>`. Am besten
  **relative Links** benutzen (`api/x`, `../werkstatt/`); wer absolute Pfade braucht, setzt das
  Präfix davor. Weiterleitungen der App (`Location: /x`) legt Saalburg unter das Präfix.
  `fernzugriff`/`fernzugriff_sicher` beziehen sich auf die Pfade ohne Präfix.
- **Kopfzeilen** (vom Gerät gesendete gleichnamige werden immer entfernt):

  | Kopf | Inhalt |
  |---|---|
  | `X-Saalburg-Geraet` | feste ID des Geräts (8 Hex-Zeichen) |
  | `X-Saalburg-Geraet-Name` | Name, den der Nutzer beim Koppeln gab (UTF-8, Prozent-kodiert) |
  | `X-Saalburg-Bereich` | `normal` oder `sicher` (Anfrage liegt in `fernzugriff_sicher`) |
  | `X-Forwarded-Prefix` | `/apps/<kennung>` |
  | `X-Forwarded-Proto`, `-For`, `-Host` | `https`, Adresse des Geräts, Host der Anfrage |

  Die Anmeldung macht Saalburg: Kommt eine Anfrage an, ist das Gerät gekoppelt und für diesen
  Bereich freigegeben. Eigene Passwörter braucht die App nicht.
- **Cookies**: Alle Apps teilen sich einen Ursprung. Saalburg setzt deshalb vor jeden
  Cookie-Namen der App ihre Kennung, legt `Path` unter `/apps/<kennung>/`, entfernt `Domain` und
  gibt ihr nur ihre eigenen zurück (für die App unsichtbar). `__Host-` wird zu `__Secure-`.
- **Was Saalburg ablehnt**: Anfragen fremder Seiten (`Sec-Fetch-Site` same-site/cross-site außer
  Navigation, fremder `Origin` bei POST/PUT/…), Abrufe aus der Seite einer anderen App (Referer
  unter `/apps/<andere>/`, außer Navigation), Pfade mit `..`, `%2F`, `%00`. Die App bekommt sie
  nie zu sehen. Eine vollständige Trennung wie zwischen fremden Websites ist das nicht (gleicher
  Ursprung): Fernzugriff nur für Apps, denen der Nutzer vertraut; Steuerfunktionen immer in
  `fernzugriff_sicher`.
- **Fehler, die das Gerät sieht** (Seite plus Kopf `X-Saalburg-Fehler`): `401` nicht gekoppelt,
  `403` Bereich nicht freigegeben bzw. heikel ohne Freigabe, `404` App ohne Fernzugriff, `502`
  App läuft nicht (oder kein `fern.sock`), `503` Fernzugriff aus, `504` App antwortet 300 s nicht.
- **Längen**: Longpoll bis 300 s je Antwortkopf; danach wird gestreamt, ohne Puffern und ohne
  Größengrenze (große Binärdateien gehen). Hochladen ebenso (Content-Length oder chunked).
  WebSocket (`Upgrade: websocket`) wird durchgereicht.
- **Schlaf**: Eine App, die aus der Ferne benutzt wird, bleibt wach (40 s nach der letzten
  Anfrage); eine schlafende wird bei einer Anfrage aufgetaut.
- **Grenzen** (in der eigenen Oberfläche deutlich sagen): Ein Stopp über das Netz ersetzt
  **nie den physischen Not-Halt** an der Maschine (WLAN, Akku, Ruhezustand des Telefons).
  Bestätigungen am Bildschirm (Installationen, Rechte) gibt es aus der Ferne nicht. Nur
  Gegenstellen mit privaten Adressen (LAN, auch über ein VPN wie WireGuard ins Heimnetz); kein offener Port ins Internet.

### Begrenztes Netz (`netz_ziele`, `netzwerk = lan:…`)

Für Apps ohne Internet, die einzelne Rechner im LAN brauchen (z. B. eine Maschinensteuerung).
Die App lebt dann in einem eigenen Netz-Raum (Netz-Namensraum mit veth-Paar zum System,
nftables-Regel), den alle ihre Prozesse (Fenster, MCP-Server) teilen.

- **app.conf**: `netz_ziele = steuerung (Maschinensteuerung), pc2` – nur Namen
  (`a–z 0–9 -`, höchstens 4), optional mit Beschreibung in Klammern. Die Adresse steht nicht im
  Paket: der Nutzer trägt sie in den Einstellungen ein (`192.168.1.50:8080`, nur private
  IPv4-Adressen). Erscheint im Installationsdialog.
- **Feste Ziele**: `netzwerk = lan:192.168.1.50:8080, lan:192.168.1.51:502` – nur private
  IPv4-Adressen, höchstens 4; erscheinen im Installationsdialog. Nur für Ziele, deren Adresse
  wirklich feststeht; sonst `netz_ziele`. Zusammen höchstens 4 Ziele.
- **In der App**: `SAALBURG_ZIEL_STEUERUNG=192.168.1.50:8080` (Name groß, `-` wird `_`), feste
  Ziele als `SAALBURG_ZIEL_LAN1`, `…_LAN2`. Die App verbindet sich ganz normal per TCP mit genau
  dieser Adresse und diesem Port. Alles andere (andere Ports, Internet, DNS, UDP, IPv6, Saalburg
  selbst) geht nicht. Fehlt die Variable, ist kein Ziel eingetragen: der App-Oberfläche einen
  Hinweis zeigen („in den Einstellungen eintragen“), nie eine Adresse raten.
- Die Prozesse der App teilen sich im Raum ihre eigene Schleife (`127.0.0.1`); für Fenster und
  MCP-Server trotzdem `$SAALBURG_APP_SOCKET` nehmen (Abschnitt 9), das geht immer.
- Änderungen gelten beim nächsten Start der App. Nur TCP/IPv4.

### Netzlaufwerke (`netzlaufwerk`)

Saalburg verbindet Windows-Freigaben (SMB) selbst; Zugangsdaten gibt nur der Nutzer am
Bildschirm ein, sie sind für Apps und Claude unsichtbar.

- **app.conf**: `netzlaufwerk = gcode (G-Code-Ablage)` – ein Name. Der Nutzer richtet das
  Laufwerk mit diesem Namen in den Einstellungen ein und gibt es der App frei („darf schreiben“,
  Standard: aus).
- **In der App**: `SAALBURG_NETZLAUFWERK=/daten/netz/<name>` (nur gesetzt, wenn freigegeben
  und eingerichtet). Lesen und schreiben, nichts ausführen. Zusätzlich die Gruppe des Laufwerks.
- **Rechnernamen** (`//RECHNER/freigabe`, `nas.fritz.box`, `pc.local`) löst Saalburg selbst im
  LAN auf (DNS-Server des Routers, NetBIOS, mDNS), auch wenn der DNS-Schutz aktiv ist (ab
  202611241046). Findet es den Rechner nicht, steht das in den Einstellungen; dann die IP eintragen.
- **Fehlt das Laufwerk** (Rechner aus, Netz weg), schlagen Zugriffe fehl (`EACCES`, `EIO`,
  `EHOSTDOWN`). Die App sagt das klar und versucht es später wieder; Saalburg verbindet von
  selbst neu. Erst schreiben, dann umbenennen (`datei.tmp` → `datei.nc`), damit die Gegenseite
  nie halbe Dateien sieht.
- Claude sieht ein Laufwerk nur, wenn der Nutzer „Claude darf schreiben“ einschaltet (eigener
  Schalter, unabhängig von dem der App). Ohne Freigabe ist es für Claude bzw. die App unsichtbar.

### Beispiel: Maschinen-App mit Werkstatt-Monitor

1. app.conf: `fernzugriff = /` (bzw. die Seiten), `fernzugriff_sicher = /werkstatt` (Monitor mit
   Notstop/Stop/Pause und alles, was die Maschine betrifft), `netz_ziele = steuerung
   (Maschinensteuerung)`, `netzlaufwerk = gcode (G-Code für die Steuerung)`, `hintergrund = ja`,
   `saalburg = <Version mit diesen Fähigkeiten>`. Kein `netzwerk = ja`.
2. Den lokalen Server statt an `127.0.0.1:<port>` an `$SAALBURG_FERN_SOCKET` binden (Unix-Socket;
   z. B. `socketserver.UnixStreamServer` oder `aiohttp.web.UnixSite`). Für das eigene Fenster
   kann er zusätzlich weiter auf 127.0.0.1 hören.
3. Alle Links und `fetch`-Pfade relativ (oder mit `X-Forwarded-Prefix` davor); die Seite liegt
   am Gerät unter `https://<Saalburg>:8443/apps/<kennung>/`.
4. Gerät aus `X-Saalburg-Geraet`/`-Name` anzeigen (z. B. „Stopp vom iPhone“), Bereich
   aus `X-Saalburg-Bereich` prüfen: Steuerknöpfe nur bei `sicher`.
5. Notstop/Stop/Pause: kurze POST-Anfrage, sofort antworten (`200` mit Ergebnis, nicht erst nach
   der Maschine), Zeitstempel zurückgeben; die Seite zeigt Erfolg/Fehler sofort. Start, Resume,
   Open und Close nie über den Fernzugriff anbieten.
6. Steuerung über `$SAALBURG_ZIEL_STEUERUNG` (nur Notstop, Stop, Pause), G-Code ins
   `$SAALBURG_NETZLAUFWERK` (erst `.tmp`, dann umbenennen) – nur geprüften G-Code; ungeprüfter
   bleibt in einem Entwurfsordner.
7. Auf der Monitorseite gut sichtbar: „Ersetzt nie den Not-Halt an der Maschine.“
