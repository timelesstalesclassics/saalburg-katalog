"""Terminal der App „zig“: richtet Zig beim ersten Start ein und öffnet eine Shell in den
Dokumenten der App, mit zig im PATH.

Farben für Text und Akzent kommen aus Saalburgs Aussehen (PLATTFORM.md, Abschnitt 5); der
Hintergrund des Terminals bleibt unverändert.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import zig_dist  # noqa: E402

WERKZEUG = os.path.dirname(os.path.abspath(__file__))
AUSSEHEN = ("/daten/system/aussehen/saalburg.conf", "/usr/lib/osproto/aussehen/saalburg.conf")
VORGABEN = {"text": "#c0caf5", "text_hell": "#f2f4fb", "text_gedaempft": "#8089b0",
            "akzent": "#7aa2f7", "erfolg": "#9ece6a", "warnung": "#e0af68", "fehler": "#f7768e"}


def farben():
    werte = dict(VORGABEN)
    for pfad in AUSSEHEN:
        try:
            with open(pfad, encoding="utf-8") as f:
                for zeile in f:
                    if "=" in zeile and not zeile.lstrip().startswith("#"):
                        k, w = (t.strip() for t in zeile.split("=", 1))
                        if k in werte and len(w) == 7 and w.startswith("#"):
                            int(w[1:], 16)
                            werte[k] = w
            break
        except (OSError, ValueError):
            continue
    return {k: "\033[38;2;%d;%d;%dm" % (int(w[1:3], 16), int(w[3:5], 16), int(w[5:7], 16))
            for k, w in werte.items()}


def main():
    f = farben()
    aus, fett = "\033[0m", "\033[1m"
    print(f"{f['text_hell']}{fett}Zig {zig_dist.VERSION}{aus} {f['text_gedaempft']}– Compiler und Build-System für Saalburg{aus}\n")
    try:
        zig = zig_dist.einrichten(lambda t: print(f"{f['text_gedaempft']}{t}{aus}", flush=True))
    except zig_dist.ZigFehler as e:
        print(f"{f['fehler']}Zig ließ sich nicht einrichten: {e}{aus}")
        input("Enter beendet.")
        return 1
    doku = os.path.join(os.environ.get("HOME", "."), "Dokumente")
    os.makedirs(doku, mode=0o700, exist_ok=True)
    a, g, t = f["akzent"], f["text_gedaempft"], f["text"]
    print(f"""{t}Arbeitsordner: {a}~/Dokumente{t} (Projekte bringt die Dateien-App oder Claude hierher)

  {a}zig init{g}                neues Projekt im aktuellen Ordner
  {a}zig build{g}               bauen (Ergebnis in zig-out/)
  {a}zig build run{g}           bauen und starten
  {a}zig build test{g}          Tests
  {a}zig fmt .{g}               formatieren

{t}Für Saalburg-Apps: {a}-Dtarget=x86_64-linux-musl -Dcpu=x86_64_v2{t}
Claude baut über die Verbindung der App (Einstellungen → Steuerung durch Claude).
Kein Internet: Abhängigkeiten als .path ins Projekt legen.  {g}exit beendet.{aus}
""", flush=True)
    os.chdir(doku)
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(zig) + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    env["ZIG_AKZENT"] = a
    env["ZIG_AUS"] = aus
    env.setdefault("HISTFILE", os.path.join(env.get("HOME", "."), ".bash_history"))
    rc = os.path.join(WERKZEUG, "bashrc")
    for shell, argv in (("/bin/bash", ["bash", "--rcfile", rc, "-i"]), ("/bin/sh", ["sh", "-i"])):
        if os.access(shell, os.X_OK):
            if shell == "/bin/sh":
                env["ENV"] = rc
            os.execve(shell, argv, env)
    print("keine Shell gefunden")
    return 1


if __name__ == "__main__":
    sys.exit(main())
