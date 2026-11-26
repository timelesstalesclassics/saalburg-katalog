"""Gemeinsamer Baustein für Werkzeug-Apps auf Saalburg (Zig, später weitere Entwicklungs-
werkzeuge): ein kleiner MCP-Server über stdio und das Ausführen von Befehlen mit Zeitlimit.

Muster „Werkzeug-App mit MCP“:
  - Die App bringt ihr Werkzeug im Paket mit; der MCP-Server (app.conf `verbindung`) läuft
    in ihrer Sandbox und braucht die laufende App nicht.
  - Gearbeitet wird nur in den Dokumenten der App ($HOME/Dokumente). Claude bringt Projekte
    mit dem Dateidienst hin (`app datei kopieren claude:/… app.<kennung>:/`) und holt
    Ergebnisse genauso zurück. Caches liegen außerhalb der Dokumente in $XDG_CACHE_HOME.
  - Jeder Befehl läuft in einer eigenen Prozessgruppe mit Zeitlimit; Ausgabe (stdout und
    stderr zusammen) und Rückgabewert gehen als Text an Claude zurück, zu lange Ausgaben
    gekürzt (Anfang und Ende bleiben).

Nur Standardbibliothek (python3 des Systems), JSON-RPC 2.0 mit einer Nachricht je Zeile.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time

PROTOKOLL = "2025-06-18"
AUSGABE_MAX = 40_000        # Zeichen Ausgabe an Claude
ROH_MAX = 8 << 20           # Bytes, die höchstens gesammelt werden (Anfang + Ende)


class WerkzeugFehler(Exception):
    """Fehler, den Claude als Text bekommt (isError), z. B. falscher Projektname."""


# ---------------------------------------------------------------------------
# Dokumente der App
# ---------------------------------------------------------------------------

def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def dokumente():
    pfad = os.path.join(home(), "Dokumente")
    os.makedirs(pfad, mode=0o700, exist_ok=True)
    return os.path.realpath(pfad)


def in_dokumente(rel, muss_existieren=True):
    """Pfad relativ zu den Dokumenten; nie außerhalb (auch nicht über Links), nie im Papierkorb."""
    rel = (rel or "").strip()
    if rel.startswith("app.") and ":/" in rel:      # Ort des Dateidienstes: app.zig:/projekt
        rel = rel.split(":/", 1)[1]
    rel = rel.lstrip("/")
    wurzel = dokumente()
    pfad = os.path.realpath(os.path.join(wurzel, rel))
    if pfad != wurzel and not pfad.startswith(wurzel + os.sep):
        raise WerkzeugFehler(f"„{rel}“ liegt nicht in den Dokumenten der App")
    teile = os.path.relpath(pfad, wurzel).split(os.sep)
    if ".Papierkorb" in teile:
        raise WerkzeugFehler("im Papierkorb wird nicht gearbeitet")
    if muss_existieren and not os.path.exists(pfad):
        raise WerkzeugFehler(f"„{rel}“ gibt es in den Dokumenten nicht – zuerst mit "
                             f"`app datei kopieren claude:/… app.<kennung>:/` hinbringen")
    return pfad


def relativ(pfad):
    r = os.path.relpath(pfad, dokumente())
    return "" if r == "." else r


# ---------------------------------------------------------------------------
# Befehle ausführen
# ---------------------------------------------------------------------------

class Ergebnis:
    def __init__(self, rc, ausgabe, dauer, zeitueberschreitung):
        self.rc = rc
        self.ausgabe = ausgabe
        self.dauer = dauer
        self.zeitueberschreitung = zeitueberschreitung

    @property
    def ok(self):
        return self.rc == 0 and not self.zeitueberschreitung


def kuerzen(text, grenze=AUSGABE_MAX):
    if len(text) <= grenze:
        return text
    vorne = grenze // 3
    hinten = grenze - vorne
    weg = len(text) - grenze
    return f"{text[:vorne]}\n… ({weg} Zeichen ausgelassen) …\n{text[-hinten:]}"


def _beenden(gruppe):
    for sig, warten in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 0)):
        try:
            os.killpg(gruppe, sig)
        except ProcessLookupError:
            return
        ende = time.monotonic() + warten
        while time.monotonic() < ende:
            try:
                os.killpg(gruppe, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)


def ausfuehren(befehl, cwd, zeitlimit, eingabe=None, umgebung=None, takt=None):
    """Startet befehl (Liste) in eigener Prozessgruppe. takt(sekunden) wird alle 15 s gerufen."""
    env = dict(os.environ)
    env.update({"NO_COLOR": "1", "TERM": "dumb"})
    if umgebung:
        env.update(umgebung)
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(befehl, cwd=cwd, env=env, start_new_session=True,
                             stdin=subprocess.PIPE if eingabe is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        raise WerkzeugFehler(f"{befehl[0]} lässt sich nicht starten: {e}")
    anfang, ende, gesamt = bytearray(), bytearray(), [0]

    def lesen():
        while True:
            block = p.stdout.read1(65536)
            if not block:
                return
            gesamt[0] += len(block)
            if len(anfang) < ROH_MAX // 2:
                anfang.extend(block)
            else:
                ende.extend(block)
                if len(ende) > ROH_MAX:
                    del ende[:len(ende) - ROH_MAX // 2]

    leser = threading.Thread(target=lesen, daemon=True)
    leser.start()
    if eingabe is not None:
        def schreiben():
            try:
                p.stdin.write(eingabe.encode())
                p.stdin.close()
            except OSError:
                pass
        threading.Thread(target=schreiben, daemon=True).start()
    zeitueberschreitung = False
    naechster_takt = t0 + 15
    while True:
        try:
            p.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            pass
        jetzt = time.monotonic()
        if jetzt - t0 > zeitlimit:
            zeitueberschreitung = True
            _beenden(p.pid)
            p.wait()
            break
        if takt and jetzt >= naechster_takt:
            naechster_takt = jetzt + 15
            takt(int(jetzt - t0))
    # Kinder, die noch an der Ausgabe hängen (z. B. ein Hintergrundprozess), mit beenden
    _beenden(p.pid)
    leser.join(timeout=5)
    p.stdout.close()
    roh = bytes(anfang)
    if ende:
        roh += f"\n… ({gesamt[0] - len(anfang) - len(ende)} Bytes ausgelassen) …\n".encode() + bytes(ende)
    text = roh.decode("utf-8", errors="replace")
    return Ergebnis(p.returncode, text, time.monotonic() - t0, zeitueberschreitung)


def bericht(titel, befehl, erg, zusatz=""):
    """Text für Claude: Kopf (Befehl, Ergebnis, Dauer), Ausgabe, Zusatz (z. B. erzeugte Dateien)."""
    if erg.zeitueberschreitung:
        status = f"ABGEBROCHEN nach Zeitlimit ({erg.dauer:.0f} s)"
    elif erg.rc == 0:
        status = "OK"
    else:
        status = f"FEHLER (Rückgabewert {erg.rc})"
    zeilen = [f"{titel}: {status} in {erg.dauer:.1f} s",
              "Befehl: " + " ".join(befehl)]
    ausgabe = erg.ausgabe.strip()
    zeilen.append("\n--- Ausgabe ---\n" + (kuerzen(ausgabe) if ausgabe else "(keine)"))
    if zusatz:
        zeilen.append("\n" + zusatz)
    return "\n".join(zeilen)


# ---------------------------------------------------------------------------
# MCP-Server
# ---------------------------------------------------------------------------

class Server:
    def __init__(self, name, version, anleitung=""):
        self.name = name
        self.version = version
        self.anleitung = anleitung
        self.werkzeuge = {}
        self._schreiben = threading.Lock()
        self._aus = sys.stdout

    def werkzeug(self, name, beschreibung, eigenschaften=None, pflicht=()):
        def eintragen(funktion):
            self.werkzeuge[name] = {
                "beschreibung": beschreibung,
                "schema": {"type": "object", "properties": eigenschaften or {},
                           "required": list(pflicht), "additionalProperties": False},
                "funktion": funktion,
            }
            return funktion
        return eintragen

    def senden(self, nachricht):
        zeile = json.dumps(nachricht, ensure_ascii=False) + "\n"
        with self._schreiben:
            self._aus.write(zeile)
            self._aus.flush()

    def _antwort(self, nr, ergebnis=None, fehler=None):
        n = {"jsonrpc": "2.0", "id": nr}
        if fehler is not None:
            n["error"] = fehler
        else:
            n["result"] = ergebnis
        self.senden(n)

    def _aufruf(self, nr, p):
        name = p.get("name")
        w = self.werkzeuge.get(name)
        if not w:
            return self._antwort(nr, fehler={"code": -32602, "message": f"unbekanntes Werkzeug: {name}"})
        argumente = p.get("arguments") or {}
        if not isinstance(argumente, dict):
            return self._antwort(nr, fehler={"code": -32602, "message": "arguments muss ein Objekt sein"})
        erlaubt = w["schema"]["properties"]
        fremd = sorted(set(argumente) - set(erlaubt))
        fehlt = [k for k in w["schema"]["required"] if k not in argumente]
        if fremd or fehlt:
            text = []
            if fremd:
                text.append("unbekannte Argumente: " + ", ".join(fremd))
            if fehlt:
                text.append("es fehlt: " + ", ".join(fehlt))
            return self._antwort(nr, {"content": [{"type": "text", "text": "; ".join(text)}], "isError": True})
        marke = (p.get("_meta") or {}).get("progressToken")

        def takt(sekunden):
            if marke is not None:
                self.senden({"jsonrpc": "2.0", "method": "notifications/progress",
                             "params": {"progressToken": marke, "progress": sekunden,
                                        "message": f"läuft seit {sekunden} s"}})

        try:
            text, fehler = w["funktion"](argumente, takt)
        except WerkzeugFehler as e:
            text, fehler = str(e), True
        except Exception as e:  # nie den Server verlieren
            text, fehler = f"interner Fehler: {type(e).__name__}: {e}", True
            print(f"{time.strftime('%H:%M:%S')} {name}: {type(e).__name__}: {e}", file=sys.stderr)
        ergebnis = {"content": [{"type": "text", "text": text}]}
        if fehler:
            ergebnis["isError"] = True
        self._antwort(nr, ergebnis)

    def behandeln(self, n):
        if not isinstance(n, dict) or "id" not in n:
            return  # Benachrichtigungen (initialized, cancelled …)
        nr, m, p = n["id"], n.get("method"), n.get("params") or {}
        if m == "initialize":
            erg = {"protocolVersion": p.get("protocolVersion") or PROTOKOLL,
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": self.name, "version": self.version}}
            if self.anleitung:
                erg["instructions"] = self.anleitung
            self._antwort(nr, erg)
        elif m == "tools/list":
            self._antwort(nr, {"tools": [{"name": k, "description": w["beschreibung"],
                                          "inputSchema": w["schema"]}
                                         for k, w in self.werkzeuge.items()]})
        elif m == "tools/call":
            self._aufruf(nr, p)
        elif m == "ping":
            self._antwort(nr, {})
        else:
            self._antwort(nr, fehler={"code": -32601, "message": f"unbekannte Methode: {m}"})

    def laufen(self, eingang=None):
        for zeile in (eingang or sys.stdin):
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                n = json.loads(zeile)
            except ValueError:
                self.senden({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "kein gültiges JSON"}})
                continue
            self.behandeln(n)
