#!/usr/bin/env python3
"""Prüft ein System-Update (Zweig „system“: eingang/manifest.txt und teile/<sha256>)
und signiert das Manifest für Saalburg.

  python3 werkzeug/system_signieren.py <system-checkout> <ausgabe.osm> [<bisheriges.osm>]

Prüft: jede Teil-Datei vorhanden, Größe und SHA-256 stimmen, die Teile ergeben
zusammen genau die angegebene Datei (Größe und SHA-256), die Version ist neuer
als die bisher veröffentlichte. Signiert wird mit OSAPP_SCHLUESSEL, aber mit
eigenem Vorsatz (SAALBURG-SYSTEM-SIGNATUR) – Format wie apps/app/system.zig.
"""
import hashlib
import os
import re
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MAGIC = b"SAALBURG-SYSTEM1\n"
VORSATZ = b"SAALBURG-SYSTEM-SIGNATUR\0"
HEX = re.compile(r"^[0-9a-f]{64}$")


def fehler(text):
    print("FEHLER:", text, file=sys.stderr)
    sys.exit(1)


def version_aus(text):
    m = re.search(r"^version = (\d+)$", text, re.M)
    return int(m.group(1)) if m else 0


def main():
    if len(sys.argv) < 3:
        fehler("Aufruf: system_signieren.py <system-checkout> <ausgabe.osm> [<bisheriges.osm>]")
    wurzel, ausgabe = sys.argv[1], sys.argv[2]
    inhalt = open(os.path.join(wurzel, "eingang", "manifest.txt"), "rb").read()
    text = inhalt.decode()
    version = version_aus(text)
    if not version:
        fehler("version fehlt")
    if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
        alt = version_aus(open(sys.argv[3], encoding="utf-8", errors="replace").read())
        if version <= alt:
            fehler(f"Version {version} ist nicht neuer als die veröffentlichte {alt}")

    datei = None
    dateien = {}
    for zeile in text.splitlines():
        if zeile.startswith("datei = "):
            art, groesse, sha = zeile[8:].split()
            datei = dateien[art] = {"groesse": int(groesse), "sha": sha, "h": hashlib.sha256(), "summe": 0}
        elif zeile.startswith("t = "):
            if datei is None:
                fehler("Teil vor der ersten Datei")
            sha, laenge = zeile[4:].split()
            if not HEX.match(sha):
                fehler(f"Teilname ungültig: {sha}")
            daten = open(os.path.join(wurzel, "teile", sha), "rb").read()
            if len(daten) != int(laenge) or hashlib.sha256(daten).hexdigest() != sha:
                fehler(f"Teil {sha[:12]} passt nicht")
            datei["h"].update(daten)
            datei["summe"] += len(daten)
    if set(dateien) != {"system", "kernel"}:
        fehler("system und kernel müssen im Manifest stehen")
    for art, d in dateien.items():
        if d["summe"] != d["groesse"] or d["h"].hexdigest() != d["sha"]:
            fehler(f"{art}: Teile ergeben nicht die angegebene Datei")
        print(f"  {art}: {d['groesse']} Bytes, Teile geprüft")

    zeile = os.environ.get("OSAPP_SCHLUESSEL", "").split()
    if len(zeile) != 3 or zeile[0] != "ed25519-geheim":
        fehler("OSAPP_SCHLUESSEL fehlt")
    geheim = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(zeile[1]))
    sig = geheim.sign(VORSATZ + hashlib.sha256(inhalt).digest())
    os.makedirs(os.path.dirname(ausgabe) or ".", exist_ok=True)
    with open(ausgabe, "wb") as f:
        f.write(MAGIC + f"schluessel: {zeile[2]}\nsignatur: {sig.hex()}\n\n".encode() + inhalt)
    print(f"Version {version} signiert von „{zeile[2]}“ → {ausgabe}")


if __name__ == "__main__":
    main()
