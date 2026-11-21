#!/usr/bin/env python3
"""Baut aus apps/<kennung>/ signierte App-Pakete (.osapp) und den signierten
Katalog (katalog.osk) für den App-Store von Saalburg.

  python3 werkzeug/katalog_bauen.py <ausgabe-ordner>

Der geheime Schlüssel kommt aus der Umgebungsvariable OSAPP_SCHLUESSEL (eine
Zeile „ed25519-geheim <64 Hex> <name>“, auf GitHub als Secret hinterlegt).
Formate wie apps/app/paket.zig und apps/app/store.zig im OS:

  Paket:   OSAPP1 / schluessel / signatur (Ed25519 über "OSAPP1-SIGNATUR\\0" + SHA-256 des tar)
  Katalog: OSKAT1 / schluessel / signatur (Ed25519 über "OSKAT1-SIGNATUR\\0" + SHA-256 des Inhalts)

Das tar enthält nur Dateien und Ordner (ustar, Besitzer 0, Zeit 0, sortiert):
gleicher Inhalt ergibt dasselbe Paket.

Für die Store-Seite (nicht im Paket) aus store/<kennung>/:
  info.conf   kategorie = Büro, empfohlen = ja
  text.txt    lange Beschreibung (höchstens 1200 Zeichen)
  *.png       Bildschirmfotos (höchstens 4, je höchstens 2 MB), alphabetisch
Dazu kommt die app.conf als Base64 in den Katalog (Symbol, Farbe, Rechte, Mindestversion).
"""
import base64
import shutil
import hashlib
import os
import re
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEKANNT = {"kennung", "version", "beschreibung", "name", "symbol", "farbe", "art", "start", "url", "reihe",
           "netzwerk", "gpu", "ton", "ram_max", "ordner", "steuerung", "verbindung",
           "hintergrund", "kategorie", "saalburg"}
NAME_RE = re.compile(r"^[a-z0-9-]{1,31}$")
VERSION_RE = re.compile(r"^[0-9][0-9a-z.-]{0,30}$")
PFAD_RE = re.compile(r"^[A-Za-z0-9._+-]+$")


def fehler(text):
    print("FEHLER:", text, file=sys.stderr)
    sys.exit(1)


def conf_lesen(text, ordnername):
    werte = {}
    for nr, roh in enumerate(text.splitlines(), 1):
        z = roh.strip()
        if not z or z.startswith("#"):
            continue
        if "=" not in z:
            fehler(f"{ordnername}/app.conf Zeile {nr}: ohne „=“")
        k, w = (t.strip() for t in z.split("=", 1))
        if k not in BEKANNT:
            fehler(f"{ordnername}/app.conf: unbekannte Angabe {k}")
        if k in werte:
            fehler(f"{ordnername}/app.conf: {k} doppelt")
        if "|" in w or "\n" in w:
            fehler(f"{ordnername}/app.conf: „|“ nicht erlaubt ({k})")
        werte[k] = w
    if werte.get("kennung") != ordnername or not NAME_RE.match(ordnername):
        fehler(f"{ordnername}: kennung muss dem Ordnernamen entsprechen")
    if not VERSION_RE.match(werte.get("version", "")):
        fehler(f"{ordnername}: version fehlt oder ungültig")
    if len(text.encode()) > 4000:
        fehler(f"{ordnername}: app.conf größer als 4000 Bytes")
    return werte


def oktal(wert, laenge):
    return (b"%0*o" % (laenge - 1, wert)) + b"\0"


def kopf(pfad, ordner, ausfuehrbar, groesse):
    b = bytearray(512)
    p = pfad.encode()
    if len(p) <= 100:
        b[0:len(p)] = p
    else:
        schnitt = next((i for i in range(len(p)) if p[i:i + 1] == b"/" and i <= 155 and len(p) - i - 1 <= 100), None)
        if schnitt is None:
            fehler(f"Pfad zu lang: {pfad}")
        b[345:345 + schnitt] = p[:schnitt]
        b[0:len(p) - schnitt - 1] = p[schnitt + 1:]
    b[100:108] = oktal(0o755 if (ordner or ausfuehrbar) else 0o644, 8)
    b[108:116] = oktal(0, 8)
    b[116:124] = oktal(0, 8)
    b[124:136] = oktal(groesse, 12)
    b[136:148] = oktal(0, 12)
    b[156:157] = b"5" if ordner else b"0"
    b[257:263] = b"ustar\0"
    b[263:265] = b"00"
    b[148:156] = b" " * 8
    summe = sum(b)
    b[148:156] = (b"%06o" % summe) + b"\0 "
    return bytes(b)


def tar_bauen(ordner):
    teile = []

    def gehen(rel):
        voll = os.path.join(ordner, rel) if rel else ordner
        for name in sorted(os.listdir(voll)):
            pfad = f"{rel}/{name}" if rel else name
            ganz = os.path.join(ordner, pfad)
            if not PFAD_RE.match(name):
                fehler(f"Name nicht erlaubt: {pfad} (nur Buchstaben, Ziffern, . _ - +)")
            if os.path.islink(ganz):
                fehler(f"Links nicht erlaubt: {pfad}")
            if os.path.isdir(ganz):
                teile.append(kopf(pfad, True, True, 0))
                gehen(pfad)
            elif os.path.isfile(ganz):
                with open(ganz, "rb") as f:
                    daten = f.read()
                teile.append(kopf(pfad, False, os.access(ganz, os.X_OK), len(daten)))
                teile.append(daten + b"\0" * ((512 - len(daten) % 512) % 512))
            else:
                fehler(f"Nur Dateien und Ordner: {pfad}")

    gehen("")
    teile.append(b"\0" * 1024)
    return b"".join(teile)


def store_zusatz(kennung, aus):
    """Zeilen aus store/<kennung>/ (Kategorie, Text, Bilder); Bilder nach aus/bilder/<kennung>/"""
    ordner = os.path.join(WURZEL, "store", kennung)
    if not os.path.isdir(ordner):
        return []
    zeilen = []
    info = os.path.join(ordner, "info.conf")
    if os.path.exists(info):
        for nr, roh in enumerate(open(info, encoding="utf-8").read().splitlines(), 1):
            z = roh.strip()
            if not z or z.startswith("#"):
                continue
            if "=" not in z:
                fehler(f"store/{kennung}/info.conf Zeile {nr}: ohne „=“")
            k, w = (t.strip() for t in z.split("=", 1))
            if k == "kategorie":
                if not w or len(w.encode()) > 23 or "|" in w or "\t" in w:
                    fehler(f"store/{kennung}: kategorie leer, zu lang oder mit |")
                zeilen.append(f"kategorie = {kennung}|{w}")
            elif k == "empfohlen":
                if w not in ("ja", "nein"):
                    fehler(f"store/{kennung}: empfohlen = ja oder nein")
                zeilen.append(f"empfohlen = {kennung}|{w}")
            else:
                fehler(f"store/{kennung}/info.conf: unbekannte Angabe {k}")
    text = os.path.join(ordner, "text.txt")
    if os.path.exists(text):
        t = open(text, encoding="utf-8").read().strip()
        if len(t) > 1200 or "|" in t:
            fehler(f"store/{kennung}/text.txt: höchstens 1200 Zeichen, ohne |")
        zeilen.append(f"text = {kennung}|" + t.replace("\r", "").replace("\n", "\\n"))
    bilder = sorted(n for n in os.listdir(ordner) if n.lower().endswith(".png"))
    if len(bilder) > 4:
        fehler(f"store/{kennung}: höchstens 4 Bilder")
    eintraege = []
    for name in bilder:
        if not PFAD_RE.match(name):
            fehler(f"store/{kennung}/{name}: Name nicht erlaubt")
        daten = open(os.path.join(ordner, name), "rb").read()
        if len(daten) > 2 * 1024 * 1024 or not daten.startswith(b"\x89PNG"):
            fehler(f"store/{kennung}/{name}: kein PNG oder größer als 2 MB")
        ziel = os.path.join(aus, "bilder", kennung)
        os.makedirs(ziel, exist_ok=True)
        shutil.copyfile(os.path.join(ordner, name), os.path.join(ziel, name))
        eintraege.append(f"bilder/{kennung}/{name}:" + hashlib.sha256(daten).hexdigest())
    if eintraege:
        zeilen.append(f"bilder = {kennung}|" + ",".join(eintraege))
    return zeilen


def schluessel_laden():
    zeile = os.environ.get("OSAPP_SCHLUESSEL", "").strip()
    teile = zeile.split()
    if len(teile) != 3 or teile[0] != "ed25519-geheim" or len(teile[1]) != 64:
        fehler("OSAPP_SCHLUESSEL fehlt oder ist kein geheimer Schlüssel (ed25519-geheim <hex> <name>)")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(teile[1])), teile[2]


def signiert(vorsatz, magie, name, inhalt, geheim):
    sig = geheim.sign(vorsatz + hashlib.sha256(inhalt).digest())
    return magie + f"schluessel: {name}\nsignatur: {sig.hex()}\n\n".encode() + inhalt


def main():
    if len(sys.argv) != 2:
        fehler("Aufruf: katalog_bauen.py <ausgabe-ordner>")
    aus = sys.argv[1]
    os.makedirs(os.path.join(aus, "pakete"), exist_ok=True)
    geheim, name = schluessel_laden()
    oeffentlich = geheim.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    erwartet = open(os.path.join(WURZEL, "schluessel", f"{name}.pub")).read().split()
    if erwartet[1] != oeffentlich:
        fehler("Geheimer Schlüssel passt nicht zu schluessel/*.pub")

    zeilen = []
    zusatz = []
    apps = os.path.join(WURZEL, "apps")
    for kennung in sorted(os.listdir(apps)):
        quelle = os.path.join(apps, kennung)
        if not os.path.isdir(quelle):
            continue
        werte = conf_lesen(open(os.path.join(quelle, "app.conf"), encoding="utf-8").read(), kennung)
        tar = tar_bauen(quelle)
        paket = signiert(b"OSAPP1-SIGNATUR\0", b"OSAPP1\n", name, tar, geheim)
        datei = f"pakete/{kennung}-{werte['version']}.osapp"
        with open(os.path.join(aus, datei), "wb") as f:
            f.write(paket)
        zeilen.append("app = " + "|".join([kennung, werte["version"], werte.get("name", kennung)[:39],
                                            str(len(paket)), hashlib.sha256(paket).hexdigest(), datei,
                                            werte.get("beschreibung", "")[:200]]))
        conf_roh = open(os.path.join(quelle, "app.conf"), "rb").read()
        zusatz.append(f"conf = {kennung}|" + base64.b64encode(conf_roh).decode())
        zusatz.extend(store_zusatz(kennung, aus))
        print(f"  {datei}  {len(paket)} Bytes")

    inhalt = (f"katalog = Saalburg-Apps\nstand = {int(time.time()):012d}\n" + "\n".join(zeilen + zusatz) + "\n").encode()
    with open(os.path.join(aus, "katalog.osk"), "wb") as f:
        f.write(signiert(b"OSKAT1-SIGNATUR\0", b"OSKAT1\n", name, inhalt, geheim))
    print(f"katalog.osk: {len(zeilen)} Apps, signiert von „{name}“")


if __name__ == "__main__":
    main()
