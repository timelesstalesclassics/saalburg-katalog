"""Zig 0.16.0 für die App einrichten: das offizielle Archiv aus dem Paket prüfen und
einmal nach $XDG_CACHE_HOME/zig-werkzeug/ entpacken.

Warum entpacken statt fertig im Paket: Zig besteht aus über 20 000 Dateien (Paketgrenze
20 000 Einträge) und ist entpackt ~400 MB groß (der Katalog liegt bei GitHub, Dateien dort
höchstens 100 MB). Das Paket enthält deshalb das unveränderte Archiv von ziglang.org
(55 MB, SHA-256 unten); jeder kann nachprüfen, dass es Byte für Byte das offizielle ist.

Gleichzeitige Aufrufe (Terminal und MCP-Server) warten über eine Sperrdatei aufeinander;
entpackt wird in einen Zwischenordner, der erst am Ende umbenannt wird.
"""
import fcntl
import hashlib
import os
import shutil
import tarfile

VERSION = "0.16.0"
ARCHIV = "zig-x86_64-linux-0.16.0.tar.xz"
# https://ziglang.org/download/index.json → "0.16.0" → "x86_64-linux" → "shasum"
# (Signatur mit minisign geprüft, Schlüssel RWSGOq2NVecA2UPNdBUZykf1CCb147pkmdtYxgb3Ti+JO/wCYvhbAb/U)
ARCHIV_SHA256 = "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00"
ORDNER = "zig-x86_64-linux-0.16.0"
EINTRAEGE = 20832          # Einträge im Archiv (für die Fortschrittsanzeige)
PLATZ_NOETIG = 450 << 20   # entpackt ~400 MB

PAKET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKE = ".saalburg-fertig"


class ZigFehler(Exception):
    pass


def basis():
    home = os.environ.get("HOME") or os.path.expanduser("~")
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(cache, "zig-werkzeug")


def zig_ordner():
    return os.path.join(basis(), ORDNER)


def zig_datei():
    return os.path.join(zig_ordner(), "zig")


def bereit():
    try:
        with open(os.path.join(zig_ordner(), MARKE), encoding="ascii") as f:
            return f.read().strip() == ARCHIV_SHA256 and os.access(zig_datei(), os.X_OK)
    except OSError:
        return False


def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def einrichten(melden=None):
    """Gibt den Pfad des zig-Programms zurück; entpackt beim ersten Mal (melden(text))."""
    if bereit():
        return zig_datei()
    melden = melden or (lambda text: None)
    b = basis()
    os.makedirs(b, mode=0o700, exist_ok=True)
    with open(os.path.join(b, ".sperre"), "w") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)
        if bereit():  # ein anderer Prozess war schneller
            return zig_datei()
        archiv = os.path.join(PAKET, ARCHIV)
        if not os.path.isfile(archiv):
            raise ZigFehler(f"Archiv fehlt im Paket: {archiv}")
        frei = shutil.disk_usage(b).free
        if frei < PLATZ_NOETIG:
            raise ZigFehler(f"zu wenig Platz: Zig braucht ~450 MB, frei sind {frei >> 20} MB")
        melden(f"Zig {VERSION} wird eingerichtet: Prüfsumme …")
        ist = sha256(archiv)
        if ist != ARCHIV_SHA256:
            raise ZigFehler(f"Prüfsumme des Archivs falsch ({ist}) – Paket beschädigt, bitte neu installieren")
        # Reste älterer Versionen und abgebrochener Läufe entfernen
        for name in os.listdir(b):
            if name in (".sperre",):
                continue
            pfad = os.path.join(b, name)
            if os.path.isdir(pfad) and not os.path.islink(pfad):
                shutil.rmtree(pfad, ignore_errors=True)
        zwischen = os.path.join(b, ".entpacken")
        os.makedirs(zwischen, mode=0o700)
        anzahl = 0
        with tarfile.open(archiv, "r:xz") as t:
            for eintrag in t:
                if not (eintrag.name == ORDNER or eintrag.name.startswith(ORDNER + "/")):
                    raise ZigFehler(f"unerwarteter Eintrag im Archiv: {eintrag.name}")
                if not (eintrag.isfile() or eintrag.isdir()):
                    raise ZigFehler(f"nur Dateien und Ordner erwartet: {eintrag.name}")
                t.extract(eintrag, zwischen, filter="data")
                anzahl += 1
                if anzahl % 2000 == 0:
                    melden(f"Zig {VERSION} wird entpackt: {anzahl * 100 // EINTRAEGE} %")
        fertig = os.path.join(zwischen, ORDNER)
        if not os.access(os.path.join(fertig, "zig"), os.X_OK):
            raise ZigFehler("zig fehlt nach dem Entpacken")
        with open(os.path.join(fertig, MARKE), "w", encoding="ascii") as f:
            f.write(ARCHIV_SHA256 + "\n")
        os.rename(fertig, zig_ordner())
        os.rmdir(zwischen)
        melden(f"Zig {VERSION} ist eingerichtet ({anzahl} Einträge).")
    return zig_datei()


if __name__ == "__main__":
    import sys
    try:
        print(einrichten(lambda t: print(t, file=sys.stderr)))
    except ZigFehler as e:
        print("FEHLER:", e, file=sys.stderr)
        sys.exit(1)
