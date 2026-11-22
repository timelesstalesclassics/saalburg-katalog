#!/usr/bin/env python3
"""Testpaket (.ostest) für den Testplatz von Saalburg bauen und signieren.

  python3 werkzeug/testpaket.py <apps-ordner> <kennung> <ziel.ostest>
  python3 werkzeug/testpaket.py --kennung <datei mit geänderten Pfaden>

Der Ablauf „Testpaket“ (.github/workflows/testplatz.yml) ruft das Werkzeug aus
dem Zweig main auf; der Stand des Pull Requests wird nur als Daten gelesen
(apps/<kennung>/), nichts daraus wird ausgeführt.

Format wie ein App-Paket, aber mit eigenem Kopf und eigenem Vorsatz:

  OSTEST1 / schluessel / signatur (Ed25519 über "OSTEST1-SIGNATUR\\0" + SHA-256 des tar)

Saalburg nimmt Testpakete nur auf dem Testplatz an und nur mit dem dort
eingerichteten Testschlüssel; die App-Verwaltung lehnt sie ab, und eine
Testsignatur gilt nie als App-Signatur. Der geheime Testschlüssel kommt aus
der Umgebungsvariable TESTPLATZ_SCHLUESSEL (GitHub-Secret, nie im Repo).
"""
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from katalog_bauen import NAME_RE, aussehen_pruefen, conf_lesen, fehler, signiert, tar_bauen  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

VORSATZ = b"OSTEST1-SIGNATUR\0"
MAGIE = b"OSTEST1\n"
SCHLUESSEL_NAME = "saalburg-test"


def fingerabdruck(oeffentlich):
    """Wie Saalburg: erste 10 Bytes von SHA-256, in Vierergruppen"""
    h = hashlib.sha256(oeffentlich).hexdigest()[:20]
    return " ".join(h[i:i + 4] for i in range(0, 20, 4))


def schluessel_laden():
    teile = os.environ.get("TESTPLATZ_SCHLUESSEL", "").strip().split()
    if len(teile) != 3 or teile[0] != "ed25519-geheim" or len(teile[1]) != 64 or teile[2] != SCHLUESSEL_NAME:
        fehler("TESTPLATZ_SCHLUESSEL fehlt oder passt nicht (ed25519-geheim <hex> saalburg-test) – "
               "auf dem Rechner unter Übersicht → Testplatz → Testschlüssel erzeugen und als Secret anlegen")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(teile[1]))


def kennung_aus_pfaden(pfade):
    """Genau eine App unter apps/<kennung>/ geändert? Dann diese."""
    kennungen = set()
    for p in pfade:
        m = re.match(r"^apps/([a-z0-9-]{1,31})/", p.strip())
        if m:
            kennungen.add(m.group(1))
    if len(kennungen) != 1:
        return None
    return kennungen.pop()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--kennung":
        k = kennung_aus_pfaden(open(sys.argv[2], encoding="utf-8").read().splitlines())
        if not k:
            fehler("Der PR ändert nicht genau eine App – Kennung angeben: „/testplatz <kennung>“")
        print(k)
        return
    if len(sys.argv) != 4:
        fehler("Aufruf: testpaket.py <apps-ordner> <kennung> <ziel.ostest> | --kennung <pfadliste>")
    apps, kennung, ziel = sys.argv[1:]
    if not NAME_RE.match(kennung):
        fehler("Kennung ungültig")
    quelle = os.path.join(apps, kennung)
    if os.path.islink(quelle) or not os.path.isdir(quelle):
        fehler(f"apps/{kennung}/ gibt es im Pull Request nicht")
    conf_pfad = os.path.join(quelle, "app.conf")
    if os.path.islink(conf_pfad):
        fehler("app.conf darf kein Link sein")
    werte = conf_lesen(open(conf_pfad, encoding="utf-8").read(), kennung)
    css = os.path.join(quelle, "aussehen.css")
    if os.path.isfile(css) and not os.path.islink(css):
        funde = aussehen_pruefen(css)
        for nr, grund in funde:
            print(f"FEHLER: apps/{kennung}/aussehen.css Zeile {nr}: {grund}", file=sys.stderr)
        if funde:
            fehler("aussehen.css verstößt gegen die Regeln")
    geheim = schluessel_laden()
    oeffentlich = geheim.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    paket = signiert(VORSATZ, MAGIE, SCHLUESSEL_NAME, tar_bauen(quelle), geheim)
    with open(ziel, "wb") as f:
        f.write(paket)
    print(f"kennung={kennung}")
    print(f"version={werte['version']}")
    print(f"sha256={hashlib.sha256(paket).hexdigest()}")
    print(f"groesse={len(paket)}")
    print(f"fingerabdruck={fingerabdruck(oeffentlich)}")


if __name__ == "__main__":
    main()
