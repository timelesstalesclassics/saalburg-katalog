"""MCP-Server der App „zig“: Claude baut und testet Zig-Projekte in den Dokumenten der App.

Start (app.conf): verbindung = exec python3 -I -B /daten/apps/zig/aktuell/werkzeug/zig_mcp.py
Läuft in der Sandbox der App (ohne Netz); die laufende App (Terminal) wird nicht gebraucht.
"""
import hashlib
import os
import shutil
import stat
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import werkzeug_mcp as wm  # noqa: E402
import zig_dist  # noqa: E402
from werkzeug_mcp import WerkzeugFehler  # noqa: E402

KENNUNG = "zig"
ZEIT_STANDARD = 600
ZEIT_MAX = 3600
OPTIMIERUNG = ["Debug", "ReleaseSafe", "ReleaseFast", "ReleaseSmall"]
SAALBURG_ZIEL = ("x86_64-linux-musl", "x86_64_v2")

ANLEITUNG = f"""Zig {zig_dist.VERSION} auf Saalburg, in der Sandbox der App „zig“ (ohne Netz).
Gearbeitet wird nur in den Dokumenten der App (Ort app.zig:/ im Dateidienst).

Ablauf:
1. Projekt hinbringen: `app datei kopieren claude:/<pfad>/<projekt> app.zig:/`
   Der Dateidienst überschreibt nicht: gibt es app.zig:/<projekt> schon, vorher
   `app datei loeschen app.zig:/<projekt>` (wandert in den Papierkorb der App).
   Ohne Freigabe „Dokumente“ für Claude fragt Saalburg bei jedem Zugriff am Bildschirm.
2. `zig_bauen` bzw. `zig_test` mit projekt="<projekt>" (Ordner mit build.zig oder eine .zig-Datei).
   Für Saalburg-Apps ziel="saalburg" (= -target x86_64-linux-musl -mcpu x86_64_v2).
   `zig_bauen` mit schritt="run" baut und startet; `programm_ausfuehren` startet Gebautes.
3. Ergebnis zurückholen: `app datei kopieren app.zig:/<projekt>/zig-out claude:/<ziel>/`
   (das Ausführbar-Bit geht beim Kopieren verloren: danach `chmod +x`).
Neues Projekt direkt hier: `zig` mit argumente=["init"], ordner="<name>".
Abhängigkeiten mit url in build.zig.zon lädt Zig hier nicht (kein Netz): als .path-Abhängigkeit
ins Projekt legen. Caches liegen außerhalb der Dokumente (cache_leeren gibt Platz frei).
Jeder Befehl hat ein Zeitlimit (zeitlimit_s, Standard {ZEIT_STANDARD} s, höchstens {ZEIT_MAX} s)."""

server = wm.Server(KENNUNG, zig_dist.VERSION, ANLEITUNG)

ZEITLIMIT = {"type": "integer", "minimum": 1, "maximum": ZEIT_MAX,
             "description": f"Sekunden bis zum Abbruch (Standard {ZEIT_STANDARD})"}
PROJEKT = {"type": "string",
           "description": "Ordner mit build.zig oder .zig-Datei, relativ zu den Dokumenten der App (z. B. \"hallo\" oder \"hallo/main.zig\")"}
OPT = {"type": "string", "enum": OPTIMIERUNG, "description": "Optimierung (-Doptimize bzw. -O)"}
ZIEL = {"type": "string",
        "description": "\"saalburg\" (x86_64-linux-musl, x86_64_v2: für Saalburg-Apps), \"nativ\" (Standard) oder ein Zig-Ziel wie \"x86_64-windows-gnu\""}
CPU = {"type": "string", "description": "CPU-Modell (-Dcpu bzw. -mcpu), z. B. \"x86_64_v3\"; überschreibt das von ziel"}
ARGUMENTE = {"type": "array", "items": {"type": "string"},
             "description": "weitere Argumente, unverändert an zig angehängt"}


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def zig():
    try:
        return zig_dist.einrichten(lambda text: print(text, file=sys.stderr))
    except zig_dist.ZigFehler as e:
        raise WerkzeugFehler(f"Zig ist nicht einsatzbereit: {e}")


def cache_basis():
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(wm.home(), ".cache"), "zig-projekte")


def lokaler_cache(projektordner):
    rel = wm.relativ(projektordner) or "_dokumente"
    kurz = "".join(c if c.isalnum() or c in "-_" else "_" for c in rel)[:40]
    marke = hashlib.sha256(rel.encode()).hexdigest()[:8]
    return os.path.join(cache_basis(), f"{kurz}-{marke}")


def umgebung(projektordner):
    return {"ZIG_LOCAL_CACHE_DIR": lokaler_cache(projektordner)}


def zeitlimit(a):
    z = a.get("zeitlimit_s", ZEIT_STANDARD)
    if not isinstance(z, int) or isinstance(z, bool) or not 1 <= z <= ZEIT_MAX:
        raise WerkzeugFehler(f"zeitlimit_s: ganze Zahl von 1 bis {ZEIT_MAX}")
    return z


def liste(a, schluessel):
    w = a.get(schluessel, [])
    if not isinstance(w, list) or not all(isinstance(x, str) for x in w):
        raise WerkzeugFehler(f"{schluessel}: Liste aus Texten erwartet")
    return w


def text_arg(a, schluessel, erlaubt=None):
    w = a.get(schluessel)
    if w is None:
        return None
    if not isinstance(w, str) or not w.strip():
        raise WerkzeugFehler(f"{schluessel}: Text erwartet")
    w = w.strip()
    if erlaubt and w not in erlaubt:
        raise WerkzeugFehler(f"{schluessel}: eines von {', '.join(erlaubt)}")
    return w


def ziel_und_cpu(a):
    ziel = text_arg(a, "ziel")
    cpu = text_arg(a, "cpu")
    if ziel in (None, "nativ", "native"):
        ziel = None
    elif ziel == "saalburg":
        ziel, ziel_cpu = SAALBURG_ZIEL
        cpu = cpu or ziel_cpu
    return ziel, cpu


def projekt(a):
    """(pfad, ordner, art): art = "build" (Ordner mit build.zig) oder "datei" (.zig-Datei)."""
    pfad = wm.in_dokumente(a.get("projekt"))
    if os.path.isdir(pfad):
        if not os.path.isfile(os.path.join(pfad, "build.zig")):
            zig_dateien = sorted(n for n in os.listdir(pfad) if n.endswith(".zig"))
            tipp = (" – eine Datei angeben, z. B. projekt=\"" + os.path.join(wm.relativ(pfad), zig_dateien[0]) + "\""
                    if zig_dateien else " – neues Projekt mit dem Werkzeug zig, argumente=[\"init\"]")
            raise WerkzeugFehler(f"„{wm.relativ(pfad) or '.'}“ hat kein build.zig{tipp}")
        return pfad, pfad, "build"
    if not pfad.endswith(".zig"):
        raise WerkzeugFehler("projekt muss ein Ordner mit build.zig oder eine .zig-Datei sein")
    return pfad, os.path.dirname(pfad), "datei"


def groesse(n):
    for einheit in ("B", "KB", "MB", "GB"):
        if n < 1024 or einheit == "GB":
            return f"{n:.0f} {einheit}" if einheit == "B" else f"{n:.1f} {einheit}"
        n /= 1024


def erzeugnisse(ordner, seit):
    """Dateien unter zig-out (neu = in diesem Lauf geschrieben)."""
    aus = os.path.join(ordner, "zig-out")
    if not os.path.isdir(aus):
        return ""
    zeilen = []
    for wurzel, ordner_namen, dateien in os.walk(aus):
        ordner_namen.sort()
        for name in sorted(dateien):
            p = os.path.join(wurzel, name)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            neu = " (neu)" if st.st_mtime >= seit - 1 else ""
            x = " ausführbar" if st.st_mode & stat.S_IXUSR else ""
            zeilen.append(f"  app.{KENNUNG}:/{wm.relativ(p)}  {groesse(st.st_size)}{x}{neu}")
            if len(zeilen) >= 60:
                zeilen.append("  …")
                return "Erzeugnisse:\n" + "\n".join(zeilen)
    return ("Erzeugnisse:\n" + "\n".join(zeilen)) if zeilen else ""


def ordner_groesse(pfad):
    summe = 0
    for wurzel, _, dateien in os.walk(pfad):
        for name in dateien:
            try:
                summe += os.lstat(os.path.join(wurzel, name)).st_size
            except OSError:
                pass
    return summe


# ---------------------------------------------------------------------------
# Werkzeuge
# ---------------------------------------------------------------------------

@server.werkzeug("zig_version", "Zig-Version, Pfade, Ziel für Saalburg-Apps und Belegung der Caches.")
def zig_version(a, takt):
    z = zig()
    erg = wm.ausfuehren([z, "version"], wm.dokumente(), 60)
    env = wm.ausfuehren([z, "env"], wm.dokumente(), 60)
    caches = []
    for name, pfad in (("Projekt-Caches", cache_basis()),
                       ("globaler Cache", os.path.join(os.environ.get("XDG_CACHE_HOME") or
                                                       os.path.join(wm.home(), ".cache"), "zig"))):
        caches.append(f"{name}: {groesse(ordner_groesse(pfad)) if os.path.isdir(pfad) else 'leer'}")
    text = "\n".join([
        f"zig {erg.ausgabe.strip()} ({z})",
        f"Dokumente der App: {wm.dokumente()} (Ort app.{KENNUNG}:/ im Dateidienst)",
        f"Saalburg-Apps: ziel=\"saalburg\" → -target {SAALBURG_ZIEL[0]} -mcpu {SAALBURG_ZIEL[1]}",
        "Netz: keines (Abhängigkeiten als .path ins Projekt legen)",
        *caches,
        "",
        "zig env:",
        env.ausgabe.strip(),
    ])
    return text, not erg.ok


@server.werkzeug("projekte", "Zeigt die Projekte in den Dokumenten der App (Ordner mit build.zig, .zig-Dateien, zig-out).")
def projekte(a, takt):
    wurzel = wm.dokumente()
    zeilen = []
    for name in sorted(os.listdir(wurzel)):
        if name.startswith("."):
            continue
        p = os.path.join(wurzel, name)
        if os.path.isdir(p):
            inhalt = set(os.listdir(p))
            merkmale = []
            if "build.zig" in inhalt:
                merkmale.append("build.zig")
            if "build.zig.zon" in inhalt:
                merkmale.append("build.zig.zon")
            zigs = [n for n in inhalt if n.endswith(".zig") and n != "build.zig"]
            if zigs:
                merkmale.append(f"{len(zigs)} .zig")
            if "zig-out" in inhalt:
                merkmale.append("zig-out")
            zeilen.append(f"{name}/  " + (", ".join(merkmale) or "–"))
        elif name.endswith(".zig"):
            zeilen.append(name)
    if not zeilen:
        return (f"Die Dokumente der App sind leer. Projekt hinbringen: "
                f"`app datei kopieren claude:/<pfad>/<projekt> app.{KENNUNG}:/` "
                f"oder neu anlegen: zig mit argumente=[\"init\"], ordner=\"<name>\"."), False
    return "Dokumente der App (app." + KENNUNG + ":/):\n" + "\n".join(zeilen), False


@server.werkzeug(
    "zig_bauen",
    "Baut ein Zig-Projekt in den Dokumenten der App: Ordner mit build.zig → `zig build [schritt]`, "
    ".zig-Datei → `zig build-exe` nach zig-out/bin/. Gibt Ausgabe, Rückgabewert und die Dateien in zig-out zurück.",
    {"projekt": PROJEKT,
     "schritt": {"type": "string", "description": "Build-Schritt bei build.zig (Standard install; z. B. run, test)"},
     "optimierung": OPT, "ziel": ZIEL, "cpu": CPU, "argumente": ARGUMENTE, "zeitlimit_s": ZEITLIMIT},
    ["projekt"])
def zig_bauen(a, takt):
    pfad, ordner, art = projekt(a)
    opt = text_arg(a, "optimierung", OPTIMIERUNG)
    ziel, cpu = ziel_und_cpu(a)
    schritt = text_arg(a, "schritt")
    z = zig()
    if art == "build":
        befehl = [z, "build"] + ([schritt] if schritt else []) + ["--summary", "all", "--color", "off"]
        if opt:
            befehl.append(f"-Doptimize={opt}")
        if ziel:
            befehl.append(f"-Dtarget={ziel}")
        if cpu:
            befehl.append(f"-Dcpu={cpu}")
    else:
        if schritt:
            raise WerkzeugFehler("schritt gibt es nur bei Projekten mit build.zig")
        name = os.path.splitext(os.path.basename(pfad))[0]
        os.makedirs(os.path.join(ordner, "zig-out", "bin"), exist_ok=True)
        endung = ".exe" if ziel and "windows" in ziel else ""
        befehl = [z, "build-exe", os.path.basename(pfad), "--color", "off",
                  f"-femit-bin=zig-out/bin/{name}{endung}"]
        if opt:
            befehl += ["-O", opt]
        if ziel:
            befehl += ["-target", ziel]
        if cpu:
            befehl += ["-mcpu", cpu]
    befehl += liste(a, "argumente")
    t0 = time.time()
    erg = wm.ausfuehren(befehl, ordner, zeitlimit(a), umgebung=umgebung(ordner), takt=takt)
    if art == "datei" and not erg.ok:
        for leer in ("zig-out/bin", "zig-out"):  # nichts gebaut: keine leeren Ordner hinterlassen
            try:
                os.rmdir(os.path.join(ordner, leer))
            except OSError:
                break
    anzeige = ["zig"] + befehl[1:]
    return wm.bericht(f"Bauen {wm.relativ(pfad)}", anzeige, erg, erzeugnisse(ordner, t0)), not erg.ok


@server.werkzeug(
    "zig_test",
    "Testet ein Zig-Projekt: Ordner mit build.zig → `zig build test`, .zig-Datei → `zig test`. "
    "filter (nur bei Dateien) wählt Tests nach Namen.",
    {"projekt": PROJEKT, "filter": {"type": "string", "description": "--test-filter (nur bei .zig-Dateien)"},
     "optimierung": OPT, "ziel": ZIEL, "cpu": CPU, "argumente": ARGUMENTE, "zeitlimit_s": ZEITLIMIT},
    ["projekt"])
def zig_test(a, takt):
    pfad, ordner, art = projekt(a)
    opt = text_arg(a, "optimierung", OPTIMIERUNG)
    ziel, cpu = ziel_und_cpu(a)
    filt = text_arg(a, "filter")
    z = zig()
    if art == "build":
        if filt:
            raise WerkzeugFehler("filter geht nur bei .zig-Dateien; bei build.zig über argumente, falls das Projekt eine Option dafür hat")
        befehl = [z, "build", "test", "--summary", "all", "--color", "off"]
        if opt:
            befehl.append(f"-Doptimize={opt}")
        if ziel:
            befehl.append(f"-Dtarget={ziel}")
        if cpu:
            befehl.append(f"-Dcpu={cpu}")
    else:
        befehl = [z, "test", os.path.basename(pfad), "--color", "off"]
        if filt:
            befehl += ["--test-filter", filt]
        if opt:
            befehl += ["-O", opt]
        if ziel:
            befehl += ["-target", ziel]
        if cpu:
            befehl += ["-mcpu", cpu]
    befehl += liste(a, "argumente")
    erg = wm.ausfuehren(befehl, ordner, zeitlimit(a), umgebung=umgebung(ordner), takt=takt)
    return wm.bericht(f"Testen {wm.relativ(pfad)}", ["zig"] + befehl[1:], erg), not erg.ok


@server.werkzeug(
    "programm_ausfuehren",
    "Startet ein gebautes Programm in der Sandbox der App (ohne Netz, ohne Fenster), mit Argumenten, "
    "Eingabe auf stdin und Zeitlimit. Arbeitsordner ist der Projektordner.",
    {"projekt": {"type": "string", "description": "Projektordner relativ zu den Dokumenten"},
     "programm": {"type": "string", "description": "Pfad relativ zum Projektordner (Standard: das einzige Programm in zig-out/bin)"},
     "argumente": {"type": "array", "items": {"type": "string"}, "description": "Argumente für das Programm"},
     "eingabe": {"type": "string", "description": "Text für stdin"},
     "zeitlimit_s": ZEITLIMIT},
    ["projekt"])
def programm_ausfuehren(a, takt):
    ordner = wm.in_dokumente(a.get("projekt"))
    if not os.path.isdir(ordner):
        ordner = os.path.dirname(ordner)
    prog = text_arg(a, "programm")
    if prog is None:
        binordner = os.path.join(ordner, "zig-out", "bin")
        kandidaten = sorted(n for n in os.listdir(binordner) if os.path.isfile(os.path.join(binordner, n))) \
            if os.path.isdir(binordner) else []
        if len(kandidaten) != 1:
            raise WerkzeugFehler("programm angeben (zig-out/bin enthält " +
                                 (", ".join(kandidaten) if kandidaten else "nichts") + ")")
        prog = os.path.join("zig-out", "bin", kandidaten[0])
    pfad = wm.in_dokumente(os.path.join(wm.relativ(ordner), prog))
    if not os.path.isfile(pfad):
        raise WerkzeugFehler(f"„{prog}“ ist keine Datei")
    hinweis = ""
    st = os.stat(pfad)
    if not st.st_mode & stat.S_IXUSR:
        os.chmod(pfad, st.st_mode | stat.S_IXUSR)
        hinweis = "Hinweis: war nicht ausführbar (z. B. nach dem Kopieren mit dem Dateidienst), jetzt chmod u+x.\n"
    eingabe = a.get("eingabe")
    if eingabe is not None and not isinstance(eingabe, str):
        raise WerkzeugFehler("eingabe: Text erwartet")
    befehl = [pfad] + liste(a, "argumente")
    erg = wm.ausfuehren(befehl, ordner, zeitlimit(a), eingabe=eingabe, takt=takt)
    anzeige = [os.path.relpath(pfad, ordner)] + befehl[1:]
    return hinweis + wm.bericht(f"Ausführen {wm.relativ(pfad)}", anzeige, erg), not erg.ok


@server.werkzeug(
    "zig_fmt",
    "Prüft die Formatierung (zig fmt --check) eines Projekts oder einer Datei; mit aendern=true wird formatiert.",
    {"projekt": PROJEKT, "aendern": {"type": "boolean", "description": "Dateien formatieren statt nur prüfen"}},
    ["projekt"])
def zig_fmt(a, takt):
    pfad = wm.in_dokumente(a.get("projekt"))
    aendern = a.get("aendern", False)
    if not isinstance(aendern, bool):
        raise WerkzeugFehler("aendern: true oder false")
    ordner = pfad if os.path.isdir(pfad) else os.path.dirname(pfad)
    befehl = [zig(), "fmt", "--color", "off"] + ([] if aendern else ["--check"])
    befehl += ["--exclude", "zig-out"] if os.path.isdir(os.path.join(ordner, "zig-out")) and os.path.isdir(pfad) else []
    befehl.append(os.path.relpath(pfad, ordner))
    erg = wm.ausfuehren(befehl, ordner, 120)
    titel = "Formatieren" if aendern else "Formatierung prüfen"
    if not aendern and erg.rc == 1 and erg.ausgabe.strip():
        return wm.bericht(titel, ["zig"] + befehl[1:], erg,
                          "Die genannten Dateien sind nicht nach zig fmt formatiert (aendern=true formatiert sie)."), True
    return wm.bericht(titel, ["zig"] + befehl[1:], erg), not erg.ok


@server.werkzeug(
    "zig",
    "Beliebiger zig-Befehl (z. B. [\"init\"], [\"build-lib\", …], [\"cc\", …], [\"translate-c\", …], [\"targets\"]) "
    "in einem Ordner der Dokumente. Bei [\"init\"] wird der Ordner angelegt, wenn es ihn nicht gibt.",
    {"argumente": {"type": "array", "items": {"type": "string"}, "minItems": 1, "description": "Argumente nach zig"},
     "ordner": {"type": "string", "description": "Arbeitsordner relativ zu den Dokumenten (Standard: Dokumente selbst)"},
     "zeitlimit_s": ZEITLIMIT},
    ["argumente"])
def zig_befehl(a, takt):
    argumente = liste(a, "argumente")
    if not argumente:
        raise WerkzeugFehler("argumente: mindestens ein Eintrag")
    rel = a.get("ordner") or ""
    if not isinstance(rel, str):
        raise WerkzeugFehler("ordner: Text erwartet")
    ordner = wm.in_dokumente(rel, muss_existieren=False)
    if not os.path.isdir(ordner):
        if argumente[0] == "init" and not os.path.exists(ordner):
            os.makedirs(ordner, mode=0o755)
        else:
            raise WerkzeugFehler(f"Ordner „{rel}“ gibt es in den Dokumenten nicht")
    befehl = [zig()] + argumente
    t0 = time.time()
    erg = wm.ausfuehren(befehl, ordner, zeitlimit(a), umgebung=umgebung(ordner), takt=takt)
    zusatz = erzeugnisse(ordner, t0)
    if argumente[0] == "init" and erg.ok:
        zusatz = "Angelegt in app.zig:/" + wm.relativ(ordner) + ": " + ", ".join(sorted(os.listdir(ordner)))
    return wm.bericht("zig " + argumente[0], ["zig"] + argumente, erg, zusatz), not erg.ok


@server.werkzeug(
    "cache_leeren",
    "Löscht Zig-Caches (liegen außerhalb der Dokumente): den eines Projekts oder mit alles=true alle "
    "(Projekt-Caches und globaler Cache). Nächster Bau dauert dann länger.",
    {"projekt": {"type": "string", "description": "Projektordner relativ zu den Dokumenten"},
     "alles": {"type": "boolean"}})
def cache_leeren(a, takt):
    alles = a.get("alles", False)
    if not isinstance(alles, bool):
        raise WerkzeugFehler("alles: true oder false")
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(wm.home(), ".cache")
    if alles:
        ziele = [cache_basis(), os.path.join(cache, "zig")]
    elif a.get("projekt"):
        ordner = wm.in_dokumente(a.get("projekt"), muss_existieren=False)
        if ordner.endswith(".zig"):
            ordner = os.path.dirname(ordner)
        ziele = [lokaler_cache(ordner)]
    else:
        raise WerkzeugFehler("projekt angeben oder alles=true")
    frei = 0
    for z in ziele:
        if os.path.isdir(z):
            frei += ordner_groesse(z)
            shutil.rmtree(z, ignore_errors=True)
    return f"Cache geleert: {groesse(frei)} frei.", False


if __name__ == "__main__":
    print(f"{time.strftime('%H:%M:%S')} zig-MCP {zig_dist.VERSION} gestartet", file=sys.stderr)
    server.laufen()
