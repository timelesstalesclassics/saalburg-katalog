# Saalburg für App-Entwickler

Was eine App auf Saalburg vorfindet, was sie darf und wie sie sich gut einfügt.
Diese Beschreibung stammt aus dem Code von Saalburg, sie zeigt nicht den Code selbst.
**Stand: Saalburg 202611221801.**

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
| `/dev/null`, `zero`, `full`, `random`, `urandom`, `tty`, `ptmx`, `/dev/pts` | lesen, schreiben |
| `/dev/shm` | lesen, schreiben, anlegen (ohne Ausführen) |
| `/daten/apps/<kennung>` (Paket) | lesen, ausführen |
| `$HOME` = `/daten/appdaten/<kennung>` | alles außer Gerätedateien |
| `$XDG_RUNTIME_DIR` = `/run/user/<uid>` | alles außer Gerätedateien |
| `/tmp` (eigenes, siehe unten) | alles außer Gerätedateien |
| `/dev/dri` | nur mit Recht `gpu` |
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
| `DRUCKEN <Name>` + Datei als Deskriptor (`SCM_RIGHTS`) | nur PDF, JPEG, PNG bis 100 MB, Recht `drucken`; der Nutzer bestätigt am Bildschirm (passt der Inhalt nicht zur Endung, gleich `FEHLER`, ohne Frage). Die Datei geht unverändert an den Drucker (keine Umwandlung); nimmt der Drucker das Format nicht direkt, ist es ein Fehler. | `OK`, `ABBRUCH` oder `FEHLER …` |

- **Warten**: Öffnen und Speichern antworten erst, wenn der Nutzer gewählt hat (auch nach
  Minuten). Die App sollte dabei ihre Ereignisschleife weiterlaufen lassen (Thread), sonst zeigt
  die Oberfläche „reagiert nicht“. Es ist immer nur eine Auswahl offen; eine zweite bekommt
  `FEHLER beschäftigt`.
- **Ton**: Meldungen sind stumm. Wer einen Ton will, spielt ihn selbst (Recht `ton`).
- **Drucken** braucht `drucken = ja` in `app.conf`; der Nutzer kann es in den Einstellungen
  (Spalte „Drucken“) abschalten, das gilt sofort. Einen Drucker richtet der Nutzer mit Claude
  ein (`drucken --drucker …`); fehlt er, antwortet der Dienst mit einem Fehler.

### Zwischenablage, Ziehen und Ablegen

Beides läuft über das Wayland-Protokoll `wl_data_device` (Version 3, siehe 5):
- **Zwischenablage** zwischen Programmen: beliebige MIME-Typen, höchstens 8 je Quelle.
- **Mit Terminals**: Text, also `text/plain;charset=utf-8`, `text/plain`, `UTF8_STRING`.
- **Bildschirmfotos** des Nutzers (Druck-Taste) bietet die Ablage als `image/png` an, als Text
  den Pfad.
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
| `zwp_linux_dmabuf_v1` | 3 | GPU-Puffer |
| `wp_viewporter` | 1 | Ausschnitt und Zielgröße einer Fläche ² |
| `wp_fractional_scale_manager_v1` | 1 | bevorzugte Skalierung immer 120 (= 1,0) ² |
| `zwp_pointer_constraints_v1` | 1 | Zeiger sperren oder auf die Fläche begrenzen ² |
| `zwp_relative_pointer_manager_v1` | 1 | relative Mausbewegung (Spiele, 3D-Ansichten) ² |
| `wp_cursor_shape_manager_v1` | 1 | Zeigerformen ohne eigenes Bild ² |
| `zwp_idle_inhibit_manager_v1` | 1 | Bildschirm wach halten ² |

² ab Saalburg 202611230126 (Abschnitt 13).

Verhalten:
- **Fenster** bekommen per `configure` die Größe ihres Platzes und die Zustände „maximiert“
  und „an allen Rändern angelegt“, „aktiv“ nur mit Fokus.
- **`wm_capabilities`**: Vollbild und Minimieren ². `set_fullscreen` gibt dem Fenster den ganzen
  Bildschirm (auch über der Leiste, Zustand `fullscreen`), solange es den Fokus hat; wechselt der
  Fokus, steht es wieder in seinem Platz, mit Fokus wieder im Vollbild, bis `unset_fullscreen`.
  `set_minimized` nimmt das Fenster vom Platz; es läuft weiter (und schläft nach 10 s, siehe 8)
  und steht in der Übersicht. Maximieren ist immer; ein Fenstermenü gibt es nicht.
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
- **Ohne Recht `gpu`**: Programme zeichnen per Software in `wl_shm`-Puffer.

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
  Betrieb ändern (DHCP), deshalb nicht dauerhaft zwischenspeichern.
- **TLS**: Die Wurzelzertifikate liegen in `/etc/ssl/certs/ca-certificates.crt`
  (Paket ca-certificates).
- **Kein mDNS oder Avahi**, keine Firewall-Regeln pro App: Mit Netzrecht ist das Netz offen.

---

## 8. Lebenszyklus

| Ereignis | Was passiert | Was die App tun sollte |
|---|---|---|
| Start | Ladeanzeige („startet …“) bis zum ersten Fenster | schnell ein erstes Fenster zeigen |
| Unsichtbar seit 10 s | `cgroup.freeze`: keine Rechenzeit, Speicher bleibt | Zeitgeber und Netzverbindungen müssen ein Einfrieren überstehen |
| Unsichtbar seit 2 min oder Speicher knapp | Speicher wird ausgelagert (`memory.reclaim`, verschlüsselte Auslagerung auf der SSD) | nichts, die Seiten kommen bei Bedarf zurück |
| Wieder sichtbar | sofort aufgetaut | |
| Fenster schließen (Windows-Taste+Q, Entf in der Übersicht) | `xdg_toplevel.close` bzw. `SIGHUP` beim Terminal; reagiert die App nach 3 s nicht, endet ihre cgroup hart (`cgroup.kill`) | `close` beachten, Stand speichern, beenden |
| Ausschalten oder Neustart | `SIGTERM`, bis zu **12 s** Frist, danach hart | auf `SIGTERM` speichern und enden |
| Nach dem Neustart | Saalburg öffnet die App wieder auf ihrem Platz (Web-Apps mit der letzten Seite derselben Herkunft) | Stand beim Start wiederherstellen |
| Speichermangel | Der Kernel beendet zuerst schlafende Apps (oom_score_adj 800), dann wache (300), dann Claude (-500); Dienste haben -900 | regelmäßig speichern |

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
- **`steuerung = claude`**: Die App bietet Claude die Steuerung an. Wirksam wird sie erst, wenn
  der Nutzer sie in den Einstellungen einschaltet; bis dahin ist sie aus.
  - Claude erreicht den Server dann als `app verbinden <kennung>`.
  - Die Leiste zeigt „⇄ <App>“ bzw. „Claude steuert <App>“.
- **Web-Apps** brauchen keinen eigenen Server, sie bekommen die Browser-Steuerung des Systems:
  - Werkzeuge: `seite_lesen`, `bildschirmfoto`, `klicken`, `eingeben`, `taste`, `oeffnen`,
    `scrollen`, `warten`, `zurueck`, `javascript`;
  - Technik: DevTools-Pipe über ein Relais nur in der Sandbox der App, nie ein offener Port.
    Sie gilt erst nach einem Neustart der App.
- **Claude kann nicht**:
  - Bestätigungen am Bildschirm geben (Installationen, Rechte, Dateizugriffe);
  - Tastatur oder Maus der Oberfläche bedienen;
  - Bildschirmfotos fremder Fenster machen;
  - die Daten einer App ohne Freigabe lesen.

  Was Claude mit der App tun soll, muss die App als MCP-Werkzeug anbieten.

---

## 10. Web-Apps

- **Chromium 158** im App-Modus (ohne Browserleiste), Wayland, GPU-Beschleunigung, Sprache
  Deutsch.
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

  Die Schriftwahl des Nutzers (Einstellungen → Darstellung) steht in
  `/daten/system/schrift/fonts.conf` und gilt für Web-Apps beim nächsten Start. Eigene
  Schriftnamen oder `@font-face` in `aussehen.css` lehnt die Katalogprüfung ab.

  `saalburg.css` setzt außerdem `color-scheme: dark`, Bildlaufleisten, Markierung und
  Fokusrahmen.
- **Einschränkungen**:
  - Ein Dateidialog öffnet nur die Ordner der App, praktisch `Dokumente` (Lesezeichen in der
    Seitenleiste). Andere Dateien holt der Nutzer mit Windows-Taste+O dorthin.
  - Keine Web-Benachrichtigungen ans System (Chromium kennt den Dienst nicht), kein
    Teilen-Dialog, keine Kamera, kein Mikrofon.
  - Keine Erweiterungen aus dem Web Store.

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
| `app liste`, `app zurueck <k>`, `app entfernen <k>` | installierte Apps; Änderungen nur mit Bestätigung |
| `app einstellung [<k> <recht> ja\|nein]` | Rechte ansehen; Änderungen nur mit Bestätigung |
| `app verbindungen`, `app verbinden <k>` | MCP-Verbindungen zu Apps |
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
- [ ] Was Claude tun können soll, ist ein MCP-Werkzeug (`verbindung`, `steuerung = claude`);
      gefährliche Schritte fragen in der App selbst nach. Der MCP-Server spricht mit der
      laufenden App über `$SAALBURG_APP_SOCKET` und meldet, wenn sie nicht läuft.
- [ ] Store-Text und Bilder ohne private Daten; mit `saalburg-test` getestet.
