"""Zig 0.16.0 für die App: liegt fertig entpackt im Paket (zig/), root-eigen und nur lesbar.

Der Katalog baut das Paket aus dem unveränderten offiziellen Archiv von ziglang.org
(SHA-256 unten, steht auch in entpacken.conf); Saalburg prüft die Signatur des Pakets und
packt es bei der Installation aus. Die App entpackt nichts mehr selbst.

Version 1.0 der App hatte das Archiv beim ersten Start nach $XDG_CACHE_HOME/zig-werkzeug/
entpackt (~400 MB); einrichten() räumt diese alte Fassung einmal weg.

Andere Apps nutzen Zig mit `werkzeuge = zig >=1.1` in ihrer app.conf: Saalburg blendet das
installierte Paket nur lesbar in ihre Sandbox ein, der Pfad steht in $SAALBURG_WERKZEUG_ZIG
(Programm: $SAALBURG_WERKZEUG_ZIG/zig/zig).
"""
import hashlib
import os
import shutil

VERSION = "0.16.0"
ARCHIV = "zig-x86_64-linux-0.16.0.tar.xz"
# https://ziglang.org/download/index.json → "0.16.0" → "x86_64-linux" → "shasum"
# (Signatur mit minisign geprüft, Schlüssel RWSGOq2NVecA2UPNdBUZykf1CCb147pkmdtYxgb3Ti+JO/wCYvhbAb/U)
ARCHIV_SHA256 = "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00"

PAKET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIG_ORDNER = os.path.join(PAKET, "zig")


class ZigFehler(Exception):
    pass


def zig_ordner():
    return ZIG_ORDNER


def zig_datei():
    return os.path.join(ZIG_ORDNER, "zig")


def bereit():
    return os.access(zig_datei(), os.X_OK)


def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def alte_fassung():
    """Ordner, in den Version 1.0 der App Zig entpackt hatte"""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(cache, "zig-werkzeug")


def einrichten(melden=None):
    """Gibt den Pfad des zig-Programms zurück (räumt die alte entpackte Fassung weg)."""
    melden = melden or (lambda text: None)
    alt = alte_fassung()
    if os.path.isdir(alt) and not os.path.islink(alt):
        melden("Alte entpackte Fassung von Zig wird entfernt (~400 MB) …")
        shutil.rmtree(alt, ignore_errors=True)
    if not bereit():
        raise ZigFehler(f"zig fehlt im Paket ({zig_datei()}) – App bitte neu installieren")
    return zig_datei()


if __name__ == "__main__":
    import sys
    try:
        print(einrichten(lambda t: print(t, file=sys.stderr)))
    except ZigFehler as e:
        print("FEHLER:", e, file=sys.stderr)
        sys.exit(1)
