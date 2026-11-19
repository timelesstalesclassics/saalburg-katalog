#!/bin/sh
# Baut Sonnengrab für Saalburg (statisch gegen musl, ohne weitere Bibliotheken)
# und legt das Programm in apps/sonnengrab/ des Katalogs.
#   ZIG=/pfad/zu/zig ./bauen.sh            Saalburg
#   ZIG=/pfad/zu/zig ./bauen.sh windows    zusätzlich Sonnengrab.exe (Windows, mit Ton)
#   ./bauen.sh pruefen                      Lösbarkeit aller Durchgänge prüfen (gcc)
set -e
HIER="$(cd "$(dirname "$0")" && pwd)"
ZIG="${ZIG:-zig}"
cd "$HIER"
python3 werkzeug/mapgen.py src/level.h
case "$1" in
  pruefen)
    mkdir -p bau shots
    cc -O2 -Wno-unused-function -o bau/sgtest src/main_test.c -lm
    ./bau/sgtest validate
    exit 0 ;;
esac
"$ZIG" cc -target x86_64-linux-musl -static -O2 -std=gnu11 -DSAALBURG -Wno-unused-function -s \
  -o "$HIER/../../apps/sonnengrab/sonnengrab" src/game.c src/main_saalburg.c
echo "fertig: apps/sonnengrab/sonnengrab"
echo "Test mit nachgebauter Oberfläche: python3 werkzeug/mock_compositor.py ../../apps/sonnengrab/sonnengrab /tmp/sonnengrab-test"
if [ "$1" = windows ]; then
  mkdir -p bau
  "$ZIG" cc -target x86_64-windows-gnu -O2 -std=gnu11 -Wno-unused-function \
    -o bau/Sonnengrab.exe src/game.c src/main_win32.c -lgdi32 -luser32 -lwinmm -Wl,--subsystem,windows -municode
  echo "fertig: quellen/sonnengrab/bau/Sonnengrab.exe"
fi
