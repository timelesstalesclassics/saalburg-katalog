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

Große Pakete und Werkzeug-Apps (ab Saalburg mit Paketformat OSAPP2):

  apps/<kennung>/entpacken.conf   Archive, die beim Bauen geprüft und ins Paket entpackt
                                  werden (statt sie in Git abzulegen bzw. beim ersten Start
                                  in $HOME zu entpacken), je Zeile:
      entpacken = <datei im App-Ordner oder https-Adresse> sha256=<hex> [aus=<ordner im archiv>] [nach=<ordner im paket>]
  Paket über 90 MB (tar) oder über 20 000 Einträge  → OSAPP2: tar mit zstd komprimiert,
      Kopf mit SHA-256 und Größe des tar; signiert wird SHA-256(komprimiert) ‖ SHA-256(tar) ‖
      Größe (u64 LE) mit Vorsatz "OSAPP2-SIGNATUR\\0". Braucht `saalburg` ≥ OSAPP2_AB.
  Paket über 90 MB oder Werkzeug-App (werkzeug = ja) → Release-Anhang statt Zweig
      veroeffentlicht (Tag <kennung>-<version>, unveränderlich); der Katalog führt Adresse,
      Größe und SHA-256 wie sonst. Liste aller Anhänge: anhaenge.txt im Zweig veroeffentlicht.
  werkzeuge = zig, wine =11.0-1   Version, die eine App bindet (=), bleibt im Katalog als
      weitere app-Zeile erreichbar (ältere Saalburg-Versionen sehen nur die neueste).

  python3 werkzeug/katalog_bauen.py <ausgabe-ordner> [--bisher <anhaenge.txt>]
  python3 werkzeug/katalog_bauen.py --paket <app-ordner> <ziel.osapp>   ein Paket (Tests)
  python3 werkzeug/katalog_bauen.py --pruefen
"""
import base64
import shutil
import hashlib
import os
import re
import struct
import sys
import tarfile
import tempfile
import time
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEKANNT = {"kennung", "version", "beschreibung", "name", "symbol", "farbe", "art", "start", "url", "reihe",
           "netzwerk", "gpu", "ton", "ram_max", "ordner", "steuerung", "verbindung",
           "hintergrund", "kategorie", "saalburg",
           # wie BEKANNT in Saalburgs app.conf-Leser (Werte prüft Saalburg beim Installieren)
           "angleichen", "drucken", "fernzugriff", "fernzugriff_sicher", "netz_ziele", "netzlaufwerk", "kvm", "laeufer",
           "schliessen_frist", "werkzeug", "werkzeuge"}
NAME_RE = re.compile(r"^[a-z0-9-]{1,31}$")
VERSION_RE = re.compile(r"^[0-9][0-9a-z.-]{0,30}$")
PFAD_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
WERKZEUG_RE = re.compile(r"^([a-z0-9-]{1,31})\s*(?:(>=|=)\s*([0-9][0-9a-z.-]{0,30}))?$")

# Saalburg-Version, ab der OSAPP2 (komprimierte Pakete) und werkzeug/werkzeuge gelten.
# NEUE_VERSION: beim Veröffentlichen des System-Updates eintragen (Versionstabelle in PLATTFORM.md)
OSAPP2_AB = 0
# OSAPP1 bleibt für alles, was ältere Saalburg-Versionen lesen können und was als eine
# Datei in Git passt; erst darüber (oder über 20 000 Einträge) wird komprimiert
TAR_GRENZE = 90 * 1024 * 1024
EINTRAEGE_ALT = 20000
EINTRAEGE_MAX = 100000
ENTPACKT_MAX = 4 * 1024 * 1024 * 1024
# Dateien im Zweig veroeffentlicht: GitHub nimmt höchstens 100 MB je Datei
GIT_GRENZE = 90 * 1024 * 1024
ANHANG_MAX = 2 * 1024 * 1024 * 1024
ZSTD_STUFE = 19


def fehler(text):
    print("FEHLER:", text, file=sys.stderr)
    sys.exit(1)


# --- Saalburg-Aussehen: aussehen.css darf nur Saalburgs Variablen verwenden ---
# Farben und Schriften stehen zentral in saalburg.css (im System) als
# var(--saalburg-…). Eine App ordnet nur ihre eigenen Elemente zu; eigene
# Farbwerte und Schriften würden Saalburgs Aussehen unterlaufen.
FARBNAMEN = set("""aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan
darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen
darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey
darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite
forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink
indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral
lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen
lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta
maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin
navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen
paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red
rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue
slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white
whitesmoke yellow yellowgreen canvas canvastext linktext visitedtext activetext buttonface
buttontext buttonborder field fieldtext highlight highlighttext selecteditem selecteditemtext mark
marktext graytext accentcolor accentcolortext""".split())
FARBFUNKTIONEN = re.compile(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|light-dark)\s*\(", re.I)
HEXFARBE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
SCHRIFT_GENERISCH = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif",
                     "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji", "fangsong",
                     "inherit", "initial", "unset", "revert"}
DEKLARATION = re.compile(r"([-\w]+)\s*:\s*([^;{}]*?)\s*(?=[;}])")


def aussehen_pruefen(pfad):
    """Fehlerliste (Zeile, Grund) für ein aussehen.css"""
    roh = open(pfad, encoding="utf-8").read()
    # Kommentare entfernen, Zeilenumbrüche behalten (für die Zeilennummern)
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), roh, flags=re.S)
    funde = []

    def zeile(pos):
        return text.count("\n", 0, pos) + 1

    for m in re.finditer(r"@(font-face|import)\b", text, re.I):
        funde.append((zeile(m.start()), f"@{m.group(1)} ist nicht erlaubt (Schriften und Stile kommen von Saalburg)"))
    tiefe = 0
    for i, z in enumerate(text):
        if z == "{":
            tiefe += 1
        elif z == "}":
            tiefe -= 1
    if tiefe != 0:
        funde.append((1, "Klammern { } stimmen nicht"))
    for m in DEKLARATION.finditer(text):
        # Nur Deklarationen in einem Block (davor ein „{“ oder „;“, kein Selektor)
        vorher = text[:m.start()].rstrip()
        if not vorher or vorher[-1] not in "{;":
            continue
        name, wert = m.group(1).lower(), m.group(2)
        ohne_var = re.sub(r"var\(\s*--saalburg-[-\w]*\s*(,[^()]*(\([^()]*\))?[^()]*)?\)", "", wert)
        nr = zeile(m.start())
        if re.search(r"var\(\s*--(?!saalburg-)", wert):
            # Variablen der Seite selbst sind erlaubt, aber keine eigenen Werte darin
            pass
        if HEXFARBE.search(ohne_var):
            funde.append((nr, f"{name}: eigener Farbwert {HEXFARBE.search(ohne_var).group(0)} – nur var(--saalburg-…)"))
        f = FARBFUNKTIONEN.search(ohne_var)
        if f:
            funde.append((nr, f"{name}: eigene Farbe {f.group(1)}(…) – nur var(--saalburg-…)"))
        for w in re.findall(r"[A-Za-z][-A-Za-z]*", re.sub(r"var\([^()]*\)", "", ohne_var)):
            if w.lower() in FARBNAMEN:
                funde.append((nr, f"{name}: Farbname „{w}“ – nur var(--saalburg-…), transparent, currentColor"))
                break
        if name in ("font-family", "font"):
            rest = ohne_var
            if '"' in rest or "'" in rest:
                funde.append((nr, f"{name}: eigene Schrift ({rest.strip()}) – nur var(--saalburg-schrift-…)"))
            elif name == "font-family":
                for teil in [t.strip().lower() for t in rest.split(",") if t.strip()]:
                    if teil not in SCHRIFT_GENERISCH and not teil.startswith("!important"):
                        funde.append((nr, f"font-family: eigene Schrift „{teil}“ – nur var(--saalburg-schrift-…)"))
                        break
            elif name == "font" and rest.strip() and rest.strip().lower() not in SCHRIFT_GENERISCH:
                funde.append((nr, "font: Kurzform mit eigener Schrift – font-family: var(--saalburg-schrift-…) verwenden"))
    return funde


def aussehen_aller(apps):
    """Alle apps/*/aussehen.css prüfen; True, wenn alles passt"""
    gut = True
    for kennung in sorted(os.listdir(apps)):
        pfad = os.path.join(apps, kennung, "aussehen.css")
        if not os.path.isfile(pfad):
            continue
        for nr, grund in aussehen_pruefen(pfad):
            print(f"FEHLER: apps/{kennung}/aussehen.css Zeile {nr}: {grund}", file=sys.stderr)
            gut = False
    return gut


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
    if ordnername == "browser":
        fehler("browser: Kennung ist für den mitgelieferten Browser von Saalburg reserviert")
    if not VERSION_RE.match(werte.get("version", "")):
        fehler(f"{ordnername}: version fehlt oder ungültig")
    if len(text.encode()) > 4000:
        fehler(f"{ordnername}: app.conf größer als 4000 Bytes")
    if "saalburg" in werte and not re.match(r"^[0-9]{12}$", werte["saalburg"]):
        fehler(f"{ordnername}: saalburg = JJJJMMTTHHMM (Mindestversion; „{werte['saalburg']}“ – Nummer aus PLATTFORM.md eintragen)")
    # Virtuelle Maschinen (KVM): ja/nein, nie mit LAN-Zielen (Saalburg prüft beim Installieren ebenso)
    if werte.get("kvm", "nein") not in ("ja", "nein"):
        fehler(f"{ordnername}: kvm = ja oder nein")
    if werte.get("kvm") == "ja" and (werte.get("netzwerk", "").startswith("lan:") or "netz_ziele" in werte):
        fehler(f"{ordnername}: kvm = ja geht nicht mit LAN-Zielen (netzwerk = lan:…, netz_ziele)")
    # Schließ-Frist: Sekunden 1–120 (wie Saalburg beim Installieren prüft)
    if "schliessen_frist" in werte:
        zahl = werte["schliessen_frist"].rstrip("sS ")
        if not zahl.isdigit() or not 1 <= int(zahl) <= 120:
            fehler(f"{ordnername}: schliessen_frist = Sekunden (1–120)")
    # Läufer-Apps (laufen nur mit Freigabe am Bildschirm, ohne Fenster): wie Saalburg prüft
    if werte.get("laeufer", "nein") not in ("ja", "nein"):
        fehler(f"{ordnername}: laeufer = ja oder nein")
    if werte.get("laeufer") == "ja":
        if werte.get("art", "terminal") != "terminal":
            fehler(f"{ordnername}: laeufer = ja nur mit art = terminal")
        for k in ("steuerung", "verbindung", "fernzugriff", "fernzugriff_sicher", "ordner", "netzlaufwerk"):
            if k in werte and not (k == "steuerung" and werte[k] == "nein"):
                fehler(f"{ordnername}: laeufer = ja geht nicht mit {k}")
    # Werkzeuge (wie Saalburg prüft): werkzeug = ja|nein, werkzeuge = zig, wine =11.0-1, bau >=2
    if werte.get("werkzeug", "nein") not in ("ja", "nein"):
        fehler(f"{ordnername}: werkzeug = ja oder nein")
    if "werkzeuge" in werte:
        werkzeuge_lesen(werte["werkzeuge"], ordnername)
    if ("werkzeuge" in werte or werte.get("werkzeug") == "ja") and saalburg_von(werte) < OSAPP2_AB:
        fehler(f"{ordnername}: werkzeug/werkzeuge brauchen saalburg = {OSAPP2_AB} (oder neuer)")
    return werte


def saalburg_von(werte):
    w = werte.get("saalburg", "")
    return int(w) if re.match(r"^[0-9]{12}$", w) else 0


def werkzeuge_lesen(wert, ordnername):
    """[(kennung, bedingung, version)], bedingung „“, „=“ oder „>=“"""
    liste = []
    for teil in wert.split(","):
        m = WERKZEUG_RE.match(teil.strip())
        if not m:
            fehler(f"{ordnername}: werkzeuge = zig, wine =11.0-1, bau >=2.0 („{teil.strip()}“ ungültig)")
        k, bed, ver = m.group(1), m.group(2) or "", m.group(3) or ""
        if k == ordnername or any(k == x[0] for x in liste):
            fehler(f"{ordnername}: werkzeuge: {k} doppelt oder die App selbst")
        liste.append((k, bed, ver))
    if not 1 <= len(liste) <= 4:
        fehler(f"{ordnername}: werkzeuge: höchstens 4")
    return liste


def version_vergleich(a, b):
    """Wie Saalburg: Teile zwischen . und - numerisch, sonst als Text; -1, 0, 1"""
    ta, tb = re.split(r"[.-]", a), re.split(r"[.-]", b)
    for i in range(max(len(ta), len(tb))):
        if i >= len(ta):
            return -1
        if i >= len(tb):
            return 1
        x, y = ta[i], tb[i]
        if x.isdigit() and y.isdigit():
            x, y = int(x), int(y)
        if x != y:
            return -1 if x < y else 1
    return 0


def passt(bed, ver, version):
    if bed == "=":
        return version == ver
    if bed == ">=":
        return version_vergleich(version, ver) >= 0
    return True


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


def tar_schreiben(ordner, ziel):
    """tar wie tar_bauen, aber in die offene Datei `ziel` (große Pakete);
    gibt (sha256-Bytes, Größe, Einträge) zurück"""
    h = hashlib.sha256()
    stand = {"groesse": 0, "eintraege": 0}

    def raus(b):
        h.update(b)
        ziel.write(b)
        stand["groesse"] += len(b)

    def gehen(rel):
        voll = os.path.join(ordner, rel) if rel else ordner
        for name in sorted(os.listdir(voll)):
            pfad = f"{rel}/{name}" if rel else name
            ganz = os.path.join(ordner, pfad)
            if not PFAD_RE.match(name):
                fehler(f"Name nicht erlaubt: {pfad} (nur Buchstaben, Ziffern, . _ - +)")
            if os.path.islink(ganz):
                fehler(f"Links nicht erlaubt: {pfad}")
            stand["eintraege"] += 1
            if os.path.isdir(ganz):
                raus(kopf(pfad, True, True, 0))
                gehen(pfad)
            elif os.path.isfile(ganz):
                groesse = os.path.getsize(ganz)
                raus(kopf(pfad, False, os.access(ganz, os.X_OK), groesse))
                with open(ganz, "rb") as f:
                    rest = groesse
                    while rest > 0:
                        b = f.read(min(rest, 1 << 20))
                        if not b:
                            fehler(f"{pfad} änderte sich beim Lesen")
                        raus(b)
                        rest -= len(b)
                raus(b"\0" * ((512 - groesse % 512) % 512))
            else:
                fehler(f"Nur Dateien und Ordner: {pfad}")

    gehen("")
    raus(b"\0" * 1024)
    return h.digest(), stand["groesse"], stand["eintraege"]


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


# --- Archive beim Bauen entpacken (entpacken.conf) -------------------------------

def entpacken_lesen(quelle, kennung):
    """[(archiv, sha256, aus, nach)] aus apps/<kennung>/entpacken.conf"""
    pfad = os.path.join(quelle, "entpacken.conf")
    if not os.path.exists(pfad):
        return []
    liste = []
    for nr, roh in enumerate(open(pfad, encoding="utf-8").read().splitlines(), 1):
        z = roh.strip()
        if not z or z.startswith("#"):
            continue
        k, _, w = (t.strip() for t in z.partition("="))
        if k != "entpacken" or not w:
            fehler(f"{kennung}/entpacken.conf Zeile {nr}: entpacken = <archiv> sha256=<hex> [aus=…] [nach=…]")
        teile = w.split()
        archiv, opt = teile[0], {}
        for t in teile[1:]:
            a, _, b = t.partition("=")
            if a not in ("sha256", "aus", "nach") or not b or a in opt:
                fehler(f"{kennung}/entpacken.conf Zeile {nr}: unbekannt oder doppelt: {t}")
            opt[a] = b
        if not re.match(r"^[0-9a-f]{64}$", opt.get("sha256", "")):
            fehler(f"{kennung}/entpacken.conf Zeile {nr}: sha256=<64 Hex-Zeichen> fehlt")
        if archiv.startswith("https://"):
            pass
        elif not PFAD_RE.match(archiv) or not os.path.isfile(os.path.join(quelle, archiv)):
            fehler(f"{kennung}/entpacken.conf Zeile {nr}: Archiv {archiv} fehlt im App-Ordner (oder https-Adresse)")
        for o in ("aus", "nach"):
            if o in opt and not all(PFAD_RE.match(t) and t not in (".", "..") for t in opt[o].split("/")):
                fehler(f"{kennung}/entpacken.conf Zeile {nr}: {o}= ungültig")
        liste.append((archiv, opt["sha256"], opt.get("aus", ""), opt.get("nach", "")))
    return liste


def datei_sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def archiv_holen(quelle, archiv, sha, cache):
    """Pfad des geprüften Archivs (https: einmal in den Cache laden)"""
    if archiv.startswith("https://"):
        os.makedirs(cache, exist_ok=True)
        pfad = os.path.join(cache, sha)
        if not (os.path.exists(pfad) and datei_sha256(pfad) == sha):
            print(f"  lade {archiv}", flush=True)
            with urllib.request.urlopen(archiv, timeout=300) as r, open(pfad + ".neu", "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            os.replace(pfad + ".neu", pfad)
    else:
        pfad = os.path.join(quelle, archiv)
    ist = datei_sha256(pfad)
    if ist != sha:
        fehler(f"{archiv}: SHA-256 {ist} statt {sha}")
    return pfad


def archiv_entpacken(pfad, aus, ziel):
    """Nur Dateien und Ordner unter `aus/` nach `ziel` (Rechte: nur das Ausführen-Bit zählt)"""
    praefix = aus.rstrip("/") + "/" if aus else ""
    n = 0
    with tarfile.open(pfad, "r:*") as t:
        for m in t:
            name = m.name[2:] if m.name.startswith("./") else m.name
            if praefix:
                if name.rstrip("/") == praefix.rstrip("/"):
                    continue
                if not name.startswith(praefix):
                    fehler(f"{os.path.basename(pfad)}: Eintrag außerhalb von aus={aus}: {m.name}")
                name = name[len(praefix):]
            name = name.rstrip("/")
            if not name:
                continue
            if not all(PFAD_RE.match(t) and t not in (".", "..") for t in name.split("/")):
                fehler(f"{os.path.basename(pfad)}: Name nicht erlaubt: {m.name}")
            if not (m.isfile() or m.isdir()):
                fehler(f"{os.path.basename(pfad)}: nur Dateien und Ordner erlaubt (Link o. Ä.): {m.name}")
            voll = os.path.join(ziel, name)
            if m.isdir():
                os.makedirs(voll, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(voll), exist_ok=True)
                if os.path.exists(voll):
                    fehler(f"{os.path.basename(pfad)}: doppelt: {name}")
                with t.extractfile(m) as q, open(voll, "wb") as f:
                    shutil.copyfileobj(q, f, 1 << 20)
                os.chmod(voll, 0o755 if m.mode & 0o111 else 0o644)
            n += 1
    return n


def bauordner(quelle, kennung, arbeit, cache):
    """Ordner, aus dem das Paket entsteht: der App-Ordner selbst oder (mit
    entpacken.conf) eine Kopie ohne die Archive, mit deren Inhalt"""
    liste = entpacken_lesen(quelle, kennung)
    if not liste:
        return quelle
    ziel = os.path.join(arbeit, kennung)
    lokale = {a for a, _, _, _ in liste if not a.startswith("https://")}

    def ohne_archive(ordner, namen):
        return [n for n in namen if ordner == quelle and n in lokale]
    shutil.copytree(quelle, ziel, ignore=ohne_archive, symlinks=True)
    for archiv, sha, aus, nach in liste:
        pfad = archiv_holen(quelle, archiv, sha, cache)
        unter = os.path.join(ziel, nach) if nach else ziel
        os.makedirs(unter, exist_ok=True)
        print(f"  {kennung}: {archiv} → {nach or '.'} ({archiv_entpacken(pfad, aus, unter)} Einträge)", flush=True)
    return ziel


def zstd_komprimieren(ein, aus):
    """tar-Datei → zstd (Stufe 19, Fenster 8 MiB: so viel hält Saalburgs Entpacker vor)"""
    try:
        import zstandard
    except ImportError:
        fehler("Python-Modul zstandard fehlt (pip install zstandard)")
    p = zstandard.ZstdCompressionParameters.from_level(ZSTD_STUFE, window_log=23, write_checksum=0, threads=-1)
    c = zstandard.ZstdCompressor(compression_params=p)
    with open(ein, "rb") as q, open(aus, "wb") as z:
        c.copy_stream(q, z, read_size=1 << 20, write_size=1 << 20)


def paket_bauen(ordner, kennung, werte, name, geheim, arbeit, bekannt=None):
    """Paket (Datei unter arbeit) bauen; gibt (pfad, osapp2, inhalt-sha256-hex, einträge) zurück.
    `bekannt`: Inhalt eines schon veröffentlichten Release-Anhangs dieser Version – ist das tar
    gleich, wird nicht neu komprimiert (pfad None)"""
    tar_pfad = os.path.join(arbeit, f"{kennung}.tar")
    with open(tar_pfad, "wb") as f:
        inhalt, groesse, eintraege = tar_schreiben(ordner, f)
    if bekannt is not None and bekannt == inhalt.hex():
        os.remove(tar_pfad)
        return None, None, inhalt.hex(), eintraege
    ziel = os.path.join(arbeit, f"{kennung}-{werte['version']}.osapp")
    gross = groesse > TAR_GRENZE or eintraege > EINTRAEGE_ALT
    if not gross:
        with open(tar_pfad, "rb") as f:
            tar = f.read()
        with open(ziel, "wb") as f:
            f.write(signiert(b"OSAPP1-SIGNATUR\0", b"OSAPP1\n", name, tar, geheim))
        os.remove(tar_pfad)
        return ziel, False, inhalt.hex(), eintraege
    if eintraege > EINTRAEGE_MAX or groesse > ENTPACKT_MAX:
        fehler(f"{kennung}: {eintraege} Einträge / {groesse >> 20} MB – höchstens {EINTRAEGE_MAX} bzw. 4 GB")
    if saalburg_von(werte) < OSAPP2_AB:
        fehler(f"{kennung}: großes Paket ({groesse >> 20} MB, {eintraege} Einträge) wird komprimiert (OSAPP2) "
               f"und braucht saalburg = {OSAPP2_AB} (oder neuer) in app.conf")
    zst = tar_pfad + ".zst"
    zstd_komprimieren(tar_pfad, zst)
    os.remove(tar_pfad)
    komp = bytes.fromhex(datei_sha256(zst))
    digest = hashlib.sha256(komp + inhalt + struct.pack("<Q", groesse)).digest()
    sig = geheim.sign(b"OSAPP2-SIGNATUR\0" + digest)
    kopf_text = (f"OSAPP2\nschluessel: {name}\nsignatur: {sig.hex()}\ninhalt: {inhalt.hex()}\n"
                 f"groesse: {groesse}\n\n").encode()
    with open(ziel, "wb") as f, open(zst, "rb") as q:
        f.write(kopf_text)
        shutil.copyfileobj(q, f, 1 << 20)
    os.remove(zst)
    return ziel, True, inhalt.hex(), eintraege


# --- Release-Anhänge --------------------------------------------------------------

def anhaenge_lesen(pfad):
    """{(kennung, version): (bytes, sha256, url, inhalt)} aus anhaenge.txt"""
    liste = {}
    if pfad and os.path.exists(pfad):
        for z in open(pfad, encoding="utf-8").read().splitlines():
            if not z.strip() or z.startswith("#"):
                continue
            k, v, b, sha, url, inhalt = z.split("|")
            liste[(k, v)] = (int(b), sha, url, inhalt)
    return liste


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


def werkzeuge_pruefen(alle):
    """werkzeuge-Angaben gegen den Katalog: Werkzeug muss es geben, mit werkzeug = ja"""
    for kennung, werte in alle.items():
        if "werkzeuge" not in werte:
            continue
        for k, bed, ver in werkzeuge_lesen(werte["werkzeuge"], kennung):
            if k not in alle or alle[k].get("werkzeug") != "ja":
                fehler(f"{kennung}: werkzeuge nennt {k}, das ist keine Werkzeug-App im Katalog (werkzeug = ja)")


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--pruefen":
        # Nur prüfen (ohne Schlüssel), z. B. vor einem Pull Request: app.conf aller Apps
        # (bricht mit FEHLER ab), entpacken.conf, werkzeuge und aussehen.css
        apps = os.path.join(WURZEL, "apps")
        alle = {}
        for kennung in sorted(os.listdir(apps)):
            conf = os.path.join(apps, kennung, "app.conf")
            if os.path.isfile(conf):
                alle[kennung] = conf_lesen(open(conf, encoding="utf-8").read(), kennung)
                entpacken_lesen(os.path.join(apps, kennung), kennung)
        werkzeuge_pruefen(alle)
        sys.exit(0 if aussehen_aller(apps) else 1)
    if len(sys.argv) == 4 and sys.argv[1] == "--paket":
        # Ein Paket bauen (Tests): Schlüssel aus OSAPP_SCHLUESSEL, ohne Abgleich mit schluessel/
        quelle = os.path.abspath(sys.argv[2])
        kennung = os.path.basename(quelle.rstrip("/"))
        werte = conf_lesen(open(os.path.join(quelle, "app.conf"), encoding="utf-8").read(), kennung)
        geheim, name = schluessel_laden()
        with tempfile.TemporaryDirectory() as arbeit:
            ordner = bauordner(quelle, kennung, arbeit, os.path.join(tempfile.gettempdir(), "katalog-cache"))
            pfad, zwei, inhalt, eintraege = paket_bauen(ordner, kennung, werte, name, geheim, arbeit)
            shutil.move(pfad, sys.argv[3])
        print(f"{sys.argv[3]}: {'OSAPP2' if zwei else 'OSAPP1'}, {eintraege} Einträge, {os.path.getsize(sys.argv[3])} Bytes")
        return
    args = sys.argv[1:]
    bisher = None
    if "--bisher" in args:
        i = args.index("--bisher")
        bisher = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        fehler("Aufruf: katalog_bauen.py <ausgabe-ordner> [--bisher <anhaenge.txt>] | --paket <ordner> <ziel> | --pruefen")
    if not aussehen_aller(os.path.join(WURZEL, "apps")):
        fehler("aussehen.css verstößt gegen die Regeln (siehe oben)")
    aus = args[0]
    os.makedirs(os.path.join(aus, "pakete"), exist_ok=True)
    geheim, name = schluessel_laden()
    oeffentlich = geheim.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    erwartet = open(os.path.join(WURZEL, "schluessel", f"{name}.pub")).read().split()
    if erwartet[1] != oeffentlich:
        fehler("Geheimer Schlüssel passt nicht zu schluessel/*.pub")
    repo = os.environ.get("GITHUB_REPOSITORY", "timelesstalesclassics/saalburg-katalog")
    anhaenge = anhaenge_lesen(bisher)
    hochladen = []
    arbeit = tempfile.mkdtemp(prefix="katalog-")
    cache = os.environ.get("KATALOG_CACHE", os.path.join(tempfile.gettempdir(), "katalog-cache"))

    zeilen = []
    zusatz = []
    apps = os.path.join(WURZEL, "apps")
    alle = {}
    for kennung in sorted(os.listdir(apps)):
        if os.path.isdir(os.path.join(apps, kennung)):
            alle[kennung] = conf_lesen(open(os.path.join(apps, kennung, "app.conf"), encoding="utf-8").read(), kennung)
    werkzeuge_pruefen(alle)
    for kennung, werte in alle.items():
        quelle = os.path.join(apps, kennung)
        ordner = bauordner(quelle, kennung, arbeit, cache)
        alt = anhaenge.get((kennung, werte["version"]))
        pfad, zwei, inhalt, eintraege = paket_bauen(ordner, kennung, werte, name, geheim, arbeit, alt[3] if alt else None)
        if ordner != quelle:
            shutil.rmtree(ordner)
        groesse = os.path.getsize(pfad) if pfad else 0
        datei = f"{kennung}-{werte['version']}.osapp"
        if alt or groesse > GIT_GRENZE or werte.get("werkzeug") == "ja":
            # Release-Anhang: je Version einmal und unveränderlich
            if groesse > ANHANG_MAX:
                fehler(f"{kennung}: Paket größer als 2 GB")
            if alt:
                if alt[3] != inhalt:
                    fehler(f"{kennung} {werte['version']} ist schon veröffentlicht, mit anderem Inhalt – version erhöhen")
                bytes_, sha, adresse, _ = alt
                print(f"  {datei}  Release-Anhang (unverändert)")
            else:
                tag = f"{kennung}-{werte['version']}"
                os.makedirs(os.path.join(aus, "..", "anhang"), exist_ok=True)
                ziel = os.path.join(os.path.dirname(os.path.abspath(aus)), "anhang", datei)
                shutil.move(pfad, ziel)
                bytes_, sha = groesse, datei_sha256(ziel)
                adresse = f"https://github.com/{repo}/releases/download/{tag}/{datei}"
                anhaenge[(kennung, werte["version"])] = (bytes_, sha, adresse, inhalt)
                hochladen.append(f"{tag}|{ziel}")
                print(f"  {datei}  {bytes_} Bytes → Release-Anhang {tag} ({'OSAPP2' if zwei else 'OSAPP1'}, {eintraege} Einträge)")
        else:
            ziel = os.path.join(aus, "pakete", datei)
            shutil.move(pfad, ziel)
            bytes_, sha, adresse = groesse, datei_sha256(ziel), f"pakete/{datei}"
            print(f"  pakete/{datei}  {bytes_} Bytes{' (OSAPP2)' if zwei else ''}")
        zeilen.append("app = " + "|".join([kennung, werte["version"], werte.get("name", kennung)[:39],
                                            str(bytes_), sha, adresse, werte.get("beschreibung", "")[:200]]))
        conf_roh = open(os.path.join(quelle, "app.conf"), "rb").read()
        zusatz.append(f"conf = {kennung}|" + base64.b64encode(conf_roh).decode())
        zusatz.extend(store_zusatz(kennung, aus))
    # Gebundene ältere Werkzeug-Versionen bleiben installierbar (weitere app-Zeile)
    gebunden = set()
    for kennung, werte in alle.items():
        for k, bed, ver in (werkzeuge_lesen(werte["werkzeuge"], kennung) if "werkzeuge" in werte else []):
            if bed == "=" and ver != alle[k]["version"]:
                if (k, ver) not in anhaenge:
                    fehler(f"{kennung} bindet {k} ={ver}; diese Version ist nicht als Release-Anhang veröffentlicht")
                gebunden.add((k, ver))
    for k, ver in sorted(gebunden):
        bytes_, sha, adresse, _ = anhaenge[(k, ver)]
        zeilen.append("app = " + "|".join([k, ver, alle[k].get("name", k)[:39], str(bytes_), sha, adresse,
                                            alle[k].get("beschreibung", "")[:200]]))
        print(f"  {k} {ver}: gebundene Version bleibt im Katalog")
    shutil.rmtree(arbeit, ignore_errors=True)

    with open(os.path.join(aus, "anhaenge.txt"), "w", encoding="utf-8") as f:
        f.write("# kennung|version|bytes|sha256|adresse|inhalt-sha256 (Release-Anhänge, unveränderlich)\n")
        for (k, v), (b, sha, url, inhalt) in sorted(anhaenge.items()):
            f.write(f"{k}|{v}|{b}|{sha}|{url}|{inhalt}\n")
    with open(os.path.join(os.path.dirname(os.path.abspath(aus)), "hochladen.txt"), "w", encoding="utf-8") as f:
        f.write("".join(z + "\n" for z in hochladen))

    inhalt = (f"katalog = Saalburg-Apps\nstand = {int(time.time()):012d}\n" + "\n".join(zeilen + zusatz) + "\n").encode()
    with open(os.path.join(aus, "katalog.osk"), "wb") as f:
        f.write(signiert(b"OSKAT1-SIGNATUR\0", b"OSKAT1\n", name, inhalt, geheim))
    print(f"katalog.osk: {len(alle)} Apps, signiert von „{name}“; neue Release-Anhänge: {len(hochladen)}")


if __name__ == "__main__":
    main()
