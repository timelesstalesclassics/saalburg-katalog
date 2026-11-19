# Sonnengrab – Quelltext

Plattformspiel im Geiste der 8-Bit-Pyramidenklassiker (Spielprinzip wie „Tom“ von Kingsoft,
Grafik, Figuren, Musik und Pyramidenplan sind eigene Werke).

| Datei | Inhalt |
|---|---|
| `src/game.c` | Spiel: Physik, Gegner, Fallen, Software-Renderer mit dynamischem Licht, Menüs |
| `src/audio.c` | Synthesizer: Musik (Oud, Ney, Darbuka) und Effekte |
| `src/sprites.h`, `src/level.h` | Pixelgrafiken, Schrift; Pyramidenplan (erzeugt von `werkzeug/mapgen.py`) |
| `src/main_saalburg.c` | Saalburg: eigener schlanker Wayland-Klient (wl_shm, xdg-shell, Tastatur), Ton über ALSA |
| `src/main_win32.c` | Windows: Fenster, Tastatur, Xbox-Gamepad, Ton |
| `src/main_test.c` | Prüfprogramm: Lösbarkeit aller Durchgänge, Bildschirmfotos, Ton |
| `werkzeug/mock_compositor.py` | nachgebaute Oberfläche für Tests ohne Saalburg |

Ton auf Saalburg: über ALSA (`default`, also dmix mit dem Lautstärkeregler des Systems).
alsa-lib wird zur Laufzeit geladen; fehlt sie oder ist das Recht `ton` abgeschaltet, läuft das
Spiel stumm und blendet Musik und Effekte im Menü aus.

Bauen: `ZIG=… ./bauen.sh` (Zig 0.16), danach `version` in `apps/sonnengrab/app.conf` erhöhen.
