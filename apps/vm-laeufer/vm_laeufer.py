#!/usr/bin/env python3
"""VM-Läufer: Saalburg-Tests in virtuellen Maschinen (QEMU mit KVM) auf diesem Rechner.

Läuft nur, solange der Nutzer ihn in den Einstellungen (Apps & Rechte) freigibt; Saalburg
startet und beendet ihn selbst (app.conf „laeufer = ja“, ohne Fenster). Er holt Aufträge
aus GitHub, testet nur fertig gebaute Abbilder (SHA-256 geprüft), baut selbst nichts und
schreibt die Ergebnisse zurück.

Ablauf eines Auftrags (Issue mit Label „vm-laeufer“ im Auftrags-Repo, Codeblock
„vm-laeufer“, nur vom Konto des Token-Besitzers):
  1. Kommentar „angenommen“.
  2. Quelltext des Commits als Archiv holen (Lese-Token), Abbild (Artefakt eines
     Werkstatt-Laufs) holen und prüfen: abbild.sha256 muss die Prüfsumme aus dem Auftrag
     haben, jede Datei darin ihre.
  3. werkzeug/laeufer/lauf.py --raum sandbox aus dem Commit ausführen – eingesperrt
     (einsperren.py, Landlock): die Tests kommen weder an die Tokens noch an diesen Prozess.
  4. Protokolle und Bildschirmfotos in den Zweig „vm-laeufer-ergebnisse“ des Auftrags-Repos,
     Kommentar „fertig“ mit der Zusammenfassung, Issue schließen.

Zustand von Saalburg: /run/laeufer/<kennung>/zustand (Freigabe, Pause, Ressourcen, Recht kvm).
Rückmeldung an Saalburg: $XDG_RUNTIME_DIR/laeufer.status (zeigt die Einstellungsseite).
Pause (jemand arbeitet am Rechner, „Drosseln“/„Anhalten“): keine neuen Aufträge; lauf.py
startet keine neuen Tests. Bei „Weiterarbeiten“ (prioritaet=niedrig) geht es nachrangig weiter.

Ohne nutzbares KVM nimmt der Läufer keinen Test an (Rückmeldung rc=kvm mit dem Grund, z. B.
„VT-x im BIOS einschalten“) – Tests in TCG wären auf dem Rechner viel zu langsam.
"""
import base64
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
KENNUNG = os.environ.get("USER") or "vm-laeufer"
HOME = os.environ.get("HOME") or os.getcwd()
ZUSTAND = os.environ.get("VM_LAEUFER_ZUSTAND") or f"/run/laeufer/{KENNUNG}/zustand"
TOKENS = os.environ.get("VM_LAEUFER_TOKENS") or f"/daten/system/laeufer/{KENNUNG}"
STATUS = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or HOME, "laeufer.status")
API = os.environ.get("VM_LAEUFER_API") or "https://api.github.com"
CODE_REPO = os.environ.get("VM_LAEUFER_CODE_REPO") or "timelesstalesclassics/saalburg"
AUFTRAG_REPO = os.environ.get("VM_LAEUFER_AUFTRAG_REPO") or "timelesstalesclassics/saalburg-test"
KATALOG_ARCHIV = "https://codeload.github.com/timelesstalesclassics/saalburg-katalog/tar.gz/main"
LABEL = "vm-laeufer"
ERGEBNIS_ZWEIG = "vm-laeufer-ergebnisse"
ARBEIT = os.path.join(HOME, "arbeit")
ABBILDER = os.path.join(HOME, "abbilder")
TAGEBUCH = os.path.join(HOME, "auftraege.json")
ABFRAGE_S = 30
ERGEBNIS_MAX = 40 * 1024 * 1024
DATEI_MAX = 8 * 1024 * 1024

MARKE_AN = "<!-- vm-laeufer:angenommen -->"
MARKE_FERTIG = "<!-- vm-laeufer:fertig"

NAME_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,200}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TESTS_RE = re.compile(r"^[A-Za-z0-9_.,:=/+\-; ]*$")


def sag(text):
    print(time.strftime("%H:%M:%S ") + text, flush=True)


# ---------------------------------------------------------------------------
# Zustand von Saalburg, Rückmeldung
# ---------------------------------------------------------------------------

def zustand():
    try:
        with open(ZUSTAND) as f:
            return dict(z.split("=", 1) for z in f.read().splitlines() if "=" in z)
    except OSError:
        return {}


def status(*zeilen):
    """Wenige Zeilen für die Einstellungsseite (atomar ersetzt)"""
    text = "\n".join(z[:200] for z in zeilen[:6]) + "\n"
    try:
        neu = STATUS + ".neu"
        with open(neu, "w") as f:
            f.write(text)
        os.replace(neu, STATUS)
    except OSError:
        pass


def token(name):
    """Token aus der Datei (nur diese App kann sie lesen); None, wenn er fehlt"""
    try:
        with open(os.path.join(TOKENS, f"token-{name}")) as f:
            t = f.read().strip()
        return t if re.fullmatch(r"[A-Za-z0-9_]{20,255}", t) else None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# GitHub (REST). Der Token geht nur an die API, nie an Umleitungsziele.
# ---------------------------------------------------------------------------

class GhFehler(Exception):
    def __init__(self, text, status=None):
        super().__init__(text)
        self.status = status


def anfrage(pfad, tok, methode="GET", daten=None, roh=False, ziel=None, zeit=60):
    url = pfad if pfad.startswith("http") else API + pfad
    body = json.dumps(daten).encode() if daten is not None else None
    req = urllib.request.Request(url, data=body, method=methode)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "saalburg-vm-laeufer")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if tok and url.startswith(API):
        # nicht weitergeben, wenn GitHub auf den Speicher umleitet (Artefakte, Archive)
        req.add_unredirected_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=zeit) as r:
            if ziel is not None:
                h = hashlib.sha256()
                with open(ziel, "wb") as f:
                    while True:
                        stueck = r.read(1 << 20)
                        if not stueck:
                            break
                        h.update(stueck)
                        f.write(stueck)
                return h.hexdigest()
            inhalt = r.read()
    except urllib.error.HTTPError as e:
        text = e.read(2000).decode(errors="replace")
        raise GhFehler(f"HTTP {e.code} {methode} {pfad}: {text[:300]}", e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise GhFehler(f"{methode} {pfad}: {e}") from None
    if roh:
        return inhalt
    return json.loads(inhalt) if inhalt.strip() else {}


# ---------------------------------------------------------------------------
# Aufträge
# ---------------------------------------------------------------------------

BLOCK_RE = re.compile(r"```vm-laeufer[ \t]*\r?\n(.*?)```", re.S)
ERLAUBT = {"kennung", "ref", "commit", "abbild_lauf", "abbild_artefakt", "abbild_manifest", "abbild_zip_sha256",
           "tests", "parallel", "kerne", "ram", "zeitlimit", "ohne_ssd", "katalog"}


class AuftragFehler(ValueError):
    pass


def auftrag_lesen(text):
    """Block „vm-laeufer“ aus einem Issue-Text: dict mit geprüften Werten"""
    m = BLOCK_RE.search(text or "")
    if not m:
        raise AuftragFehler("kein Block ```vm-laeufer")
    a = {}
    for zeile in m.group(1).splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        if "=" not in zeile:
            raise AuftragFehler(f"Zeile ohne „=“: {zeile[:60]}")
        k, w = (t.strip() for t in zeile.split("=", 1))
        if k not in ERLAUBT:
            raise AuftragFehler(f"unbekannt: {k}")
        a[k] = w
    for pflicht in ("kennung", "ref", "commit", "abbild_artefakt", "abbild_manifest", "tests"):
        if not a.get(pflicht):
            raise AuftragFehler(f"fehlt: {pflicht}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,40}", a["kennung"]):
        raise AuftragFehler("kennung ungültig")
    if not NAME_RE.match(a["ref"]) or ".." in a["ref"]:
        raise AuftragFehler("ref ungültig")
    if not HEX40.match(a["commit"]):
        raise AuftragFehler("commit: 40 Hex-Ziffern")
    if not a["abbild_artefakt"].isdigit() or not a.get("abbild_lauf", "0").isdigit():
        raise AuftragFehler("abbild_artefakt/abbild_lauf: Zahl")
    if not HEX64.match(a["abbild_manifest"]):
        raise AuftragFehler("abbild_manifest: SHA-256")
    if a.get("abbild_zip_sha256") and not HEX64.match(a["abbild_zip_sha256"]):
        raise AuftragFehler("abbild_zip_sha256: SHA-256")
    if not TESTS_RE.match(a["tests"]) or len(a["tests"]) > 2000:
        raise AuftragFehler("tests: nur werkzeug/<name>.py [argumente], mit ; getrennt")
    for k, lo, hi in (("parallel", 1, 3), ("kerne", 0, 8), ("zeitlimit", 1, 240)):
        if k in a:
            if not a[k].isdigit() or not lo <= int(a[k]) <= hi:
                raise AuftragFehler(f"{k}: {lo}–{hi}")
    if a.get("ram") and not re.fullmatch(r"\d{3,5}M|\d{1,2}G", a["ram"]):
        raise AuftragFehler("ram: z. B. 3G")
    for k in ("ohne_ssd", "katalog"):
        if a.get(k, "nein") not in ("ja", "nein"):
            raise AuftragFehler(f"{k}: ja oder nein")
    return a


def tagebuch():
    try:
        with open(TAGEBUCH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def tagebuch_setzen(schluessel, wert):
    t = tagebuch()
    t[schluessel] = wert
    # nur die letzten 200 Einträge
    if len(t) > 200:
        for k in list(t)[:-200]:
            t.pop(k)
    neu = TAGEBUCH + ".neu"
    with open(neu, "w") as f:
        json.dump(t, f)
    os.replace(neu, TAGEBUCH)


# ---------------------------------------------------------------------------
# Quelltext und Abbild
# ---------------------------------------------------------------------------

def archiv_passt(t, oben, commit):
    """Ist das GitHub-Archiv t vom Commit? GitHub schreibt (wie git archive) die volle Commit-ID
    in den globalen pax-Kopf („comment“) – das ist maßgeblich. Der Name des obersten Ordners
    (<owner>-<repo>-<sha>) wechselt dagegen zwischen kurzer und voller SHA; ohne pax-Kopf muss
    seine SHA (7–40 Hex-Ziffern) ein Anfang des Commits sein."""
    kommentar = (t.pax_headers or {}).get("comment", "").strip()
    if kommentar:
        return kommentar == commit
    sha = oben.rsplit("-", 1)[-1] if "-" in oben else ""
    return 7 <= len(sha) <= 40 and re.fullmatch(r"[0-9a-f]+", sha) is not None and commit.startswith(sha)


def archiv_entpacken(datei, ziel, commit=None):
    """tar.gz eines GitHub-Archivs ohne die oberste Ebene nach ziel (nur Dateien und Ordner);
    mit commit: muss von diesem Commit sein (archiv_passt)"""
    os.makedirs(ziel, exist_ok=True)
    with tarfile.open(datei, "r:gz") as t:
        mitglieder = []
        oben = None
        for m in t.getmembers():
            teile = m.name.split("/", 1)
            if oben is None:
                oben = teile[0]
                if commit and not archiv_passt(t, oben, commit):
                    k = (t.pax_headers or {}).get("comment", "")
                    raise AuftragFehler(f"Archiv passt nicht zum Commit {commit[:10]} (Ordner {oben}"
                                        + (f", Commit im Archiv {k[:10]}" if k else "") + ")")
            if teile[0] != oben or len(teile) < 2 or not teile[1]:
                continue
            if not (m.isfile() or m.isdir()):
                continue  # keine Links, Geräte
            m.name = teile[1]
            mitglieder.append(m)
        t.extractall(ziel, members=mitglieder, filter="data")


def code_holen(a, tok, ziel):
    datei = ziel + ".tar.gz"
    anfrage(f"/repos/{CODE_REPO}/tarball/{a['commit']}", tok, ziel=datei, zeit=300)
    archiv_entpacken(datei, ziel, a["commit"])
    os.remove(datei)


def manifest_pruefen(ordner, manifest_sha):
    """abbild.sha256 muss die erwartete Prüfsumme haben, jede Datei darin die ihre; keine
    Dateien außer den aufgeführten. Fehler: AuftragFehler"""
    pfad = os.path.join(ordner, "abbild.sha256")
    with open(pfad, "rb") as f:
        inhalt = f.read()
    if hashlib.sha256(inhalt).hexdigest() != manifest_sha:
        raise AuftragFehler("abbild.sha256 hat nicht die Prüfsumme aus dem Auftrag")
    erwartet = {}
    for zeile in inhalt.decode().splitlines():
        summe, _, name = zeile.partition("  ")
        if not HEX64.match(summe) or not name or name.startswith("/") or ".." in name.split("/"):
            raise AuftragFehler(f"abbild.sha256: Zeile ungültig: {zeile[:80]}")
        erwartet[name] = summe
    gefunden = set()
    for wurzel, _, dateien in os.walk(ordner):
        for d in dateien:
            rel = os.path.relpath(os.path.join(wurzel, d), ordner)
            if rel == "abbild.sha256":
                continue
            gefunden.add(rel)
            if rel not in erwartet:
                raise AuftragFehler(f"Datei nicht im Manifest: {rel}")
            h = hashlib.sha256()
            with open(os.path.join(wurzel, d), "rb") as f:
                for stueck in iter(lambda: f.read(1 << 20), b""):
                    h.update(stueck)
            if h.hexdigest() != erwartet[rel]:
                raise AuftragFehler(f"Prüfsumme falsch: {rel}")
    fehlt = set(erwartet) - gefunden
    if fehlt:
        raise AuftragFehler(f"fehlt im Abbild: {sorted(fehlt)[:3]}")
    for noetig in ("bzImage", "stick/osproto/system.sqfs", "stick/EFI/BOOT/BOOTX64.EFI"):
        if noetig not in erwartet:
            raise AuftragFehler(f"Abbild ohne {noetig}")


def abbild_holen(a, tok):
    """Ordner mit geprüftem Abbild (aus dem Zwischenspeicher oder neu geladen)"""
    ziel = os.path.join(ABBILDER, a["abbild_manifest"])
    if os.path.exists(os.path.join(ziel, ".geprueft")):
        return ziel
    os.makedirs(ABBILDER, exist_ok=True)
    # Platz: höchstens zwei Abbilder behalten
    alte = sorted((os.path.getmtime(os.path.join(ABBILDER, d)), d) for d in os.listdir(ABBILDER))
    for _, d in alte[:-1]:
        shutil.rmtree(os.path.join(ABBILDER, d), ignore_errors=True)
    zipdatei = os.path.join(ABBILDER, "laden.zip")
    teil = ziel + ".neu"
    shutil.rmtree(teil, ignore_errors=True)
    try:
        status("Lade Abbild (Artefakt " + a["abbild_artefakt"] + ") …")
        summe = anfrage(f"/repos/{CODE_REPO}/actions/artifacts/{a['abbild_artefakt']}/zip", tok, ziel=zipdatei, zeit=1800)
        if a.get("abbild_zip_sha256") and summe != a["abbild_zip_sha256"]:
            raise AuftragFehler("Artefakt hat nicht die Prüfsumme aus dem Auftrag")
        with zipfile.ZipFile(zipdatei) as z:
            for info in z.infolist():
                name = info.filename
                if name.startswith("/") or ".." in name.split("/") or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise AuftragFehler(f"unsicherer Eintrag im Artefakt: {name}")
            z.extractall(teil)
        manifest_pruefen(teil, a["abbild_manifest"])
        if a.get("commit"):
            try:
                c = open(os.path.join(teil, "commit.txt")).read().strip()
            except OSError:
                c = ""
            if c and c != a["commit"]:
                raise AuftragFehler(f"Abbild ist von Commit {c[:10]}, Auftrag will {a['commit'][:10]}")
        for wurzel, ordner, dateien in os.walk(teil):
            for d in dateien:
                os.chmod(os.path.join(wurzel, d), 0o444)
        open(os.path.join(teil, ".geprueft"), "w").close()
        os.replace(teil, ziel)
        return ziel
    finally:
        if os.path.exists(zipdatei):
            os.remove(zipdatei)
        shutil.rmtree(teil, ignore_errors=True)


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

laufend = None  # subprocess.Popen des Laufs


KVM_GET_API_VERSION = 0xAE00  # _IO(0xAE, 0x00)


def cpu_flags():
    """Flags der ersten CPU aus /proc/cpuinfo (None, wenn nicht lesbar)"""
    try:
        with open("/proc/cpuinfo") as f:
            for zeile in f:
                if zeile.startswith("flags"):
                    return set(zeile.split(":", 1)[1].split())
    except OSError:
        pass
    return None


def kvm_pruefen(geraet=None):
    """(nutzbar, Grund) – öffnet /dev/kvm wirklich und fragt die API-Version ab"""
    geraet = geraet or os.environ.get("VM_LAEUFER_KVM_GERAET") or "/dev/kvm"  # Umgebung: nur Tests
    try:
        fd = os.open(geraet, os.O_RDWR | os.O_CLOEXEC)
    except FileNotFoundError:
        flags = cpu_flags()
        if flags is not None and not flags & {"vmx", "svm"}:
            # Linux löscht vmx aus den Flags, wenn die Firmware VT-x gesperrt hat
            return False, ("der Prozessor meldet keine Virtualisierung – im BIOS/UEFI „Intel Virtualization "
                           "Technology“ (VT-x) einschalten, dann neu starten")
        return False, "/dev/kvm fehlt (Kernel ohne KVM, oder VT-x im BIOS/UEFI aus)"
    except OSError as e:
        try:
            gid = os.stat(geraet).st_gid
        except OSError:
            gid = None
        if gid is not None and gid not in os.getgroups():
            return False, ("kein Zugriff auf /dev/kvm: Recht „Virtuelle Maschinen“ aus oder erst nach dem Start "
                           "des Läufers eingeschaltet")
        return False, f"kein Zugriff auf /dev/kvm ({e.strerror})"
    try:
        version = fcntl.ioctl(fd, KVM_GET_API_VERSION)
    except OSError as e:
        return False, f"/dev/kvm antwortet nicht ({e.strerror})"
    finally:
        os.close(fd)
    if version != 12:
        return False, f"/dev/kvm: unerwartete API-Version {version}"
    return True, "KVM"


def kvm_nutzbar():
    return kvm_pruefen()[0]


def ohne_kvm_erlaubt():
    """Nur für Tests ohne KVM (VM_LAEUFER_TCG=ja): dann rechnen die VMs in TCG"""
    return os.environ.get("VM_LAEUFER_TCG") == "ja"


def befehl_bauen(a, z, repo, erg, abbild, tmp):
    parallel = min(int(a.get("parallel", "1")), int(z.get("vms", "1") or 1))
    kerne = int(a.get("kerne", "0")) or int(z.get("kerne", "2") or 2)
    kerne = min(kerne, int(z.get("kerne", "2") or 2))
    ram = a.get("ram") or f"{z.get('ram_mb', '3072')}M"
    lauf = [sys.executable, "-I", os.path.join(repo, "werkzeug", "laeufer", "lauf.py"),
            "--raum", "sandbox", "--wurzel", repo, "--ergebnis", erg, "--ref", a["ref"], "--commit", a["commit"],
            "--tests", a["tests"], "--parallel", str(parallel), "--kerne", str(kerne), "--ram", ram,
            "--zeitlimit", a.get("zeitlimit", "60"), "--kvm", "1" if kvm_nutzbar() else "auto"]
    if a.get("ohne_ssd") == "ja":
        lauf.append("--ohne-ssd")
    sperre = [sys.executable, "-I", os.path.join(HIER, "einsperren.py")]
    for p in ("/usr", "/lib", "/bin", "/sbin", "/etc", "/sys", "/run/netz", os.path.dirname(ZUSTAND), abbild, HIER):
        sperre += ["--lesen", p]
    sperre += ["--lesen", "/proc"]
    for p in (os.path.dirname(repo), tmp, "/dev/shm", "/dev/pts"):
        sperre += ["--schreiben", p]
    for p in ("/dev/kvm", "/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom", "/dev/tty", "/dev/ptmx"):
        sperre += ["--geraet", p]
    return sperre + ["--"] + lauf


def lauf_ausfuehren(a, z, tok_lesen, auftrag_ordner):
    """Code und Abbild holen, lauf.py eingesperrt ausführen. (Rückgabe, Ergebnisordner)"""
    global laufend
    shutil.rmtree(auftrag_ordner, ignore_errors=True)
    os.makedirs(auftrag_ordner)
    repo = os.path.join(auftrag_ordner, "saalburg")
    erg = os.path.join(auftrag_ordner, "ergebnis")
    tmp = os.path.join(auftrag_ordner, "tmp")
    os.makedirs(erg)
    os.makedirs(tmp)
    status(f"Auftrag {a['kennung']}: Quelltext {a['ref']} ({a['commit'][:10]}) …")
    code_holen(a, tok_lesen, repo)
    if not os.path.exists(os.path.join(repo, "werkzeug", "laeufer", "lauf.py")) or \
            "--raum" not in open(os.path.join(repo, "werkzeug", "laeufer", "lauf.py")).read():
        raise AuftragFehler("lauf.py dieses Stands kennt --raum sandbox nicht (Zweig auf main bringen)")
    abbild = abbild_holen(a, tok_lesen)
    # bau/minipc und bau/programme zeigen auf das geprüfte Abbild (nur lesbar)
    os.makedirs(os.path.join(repo, "bau", "minipc"), exist_ok=True)
    os.symlink(os.path.join(abbild, "bzImage"), os.path.join(repo, "bau", "minipc", "bzImage"))
    os.symlink(os.path.join(abbild, "stick"), os.path.join(repo, "bau", "minipc", "stick"))
    if os.path.isdir(os.path.join(abbild, "programme")):
        os.symlink(os.path.join(abbild, "programme"), os.path.join(repo, "bau", "programme"))
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C.UTF-8", "TZ": "Europe/Berlin",
           "HOME": auftrag_ordner, "TMPDIR": tmp, "SAALBURG_LAEUFER_ZUSTAND": ZUSTAND}
    if a.get("katalog", "ja") == "ja":
        try:
            ziel = os.path.join(auftrag_ordner, "katalog")
            anfrage(KATALOG_ARCHIV, None, ziel=ziel + ".tar.gz", zeit=300)
            archiv_entpacken(ziel + ".tar.gz", ziel)
            os.remove(ziel + ".tar.gz")
            env["KATALOG_REPO"] = ziel
        except (GhFehler, OSError, tarfile.TarError) as fehler:
            sag(f"Katalog nicht geladen ({fehler}) – Tests ohne KATALOG_REPO")
    befehl = befehl_bauen(a, z, repo, erg, abbild, tmp)
    status(f"Auftrag {a['kennung']}: Tests laufen …", a["tests"][:180])
    with open(os.path.join(erg, "lauf.log"), "wb") as log:
        laufend = subprocess.Popen(befehl, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        while laufend.poll() is None:
            time.sleep(5)
            z2 = zustand()
            if z2.get("freigabe") != "ja":
                break
            stand = fortschritt(erg)
            zusatz = " · Pause" if z2.get("pause") == "ja" else " · niedrige Priorität" if z2.get("prioritaet") == "niedrig" else ""
            status(f"Auftrag {a['kennung']}: {stand}{zusatz}", a["tests"][:180])
        rc = laufend.poll()
        if rc is None:
            lauf_beenden()
            rc = 130
    laufend = None
    return rc, erg


def fortschritt(erg):
    try:
        with open(os.path.join(erg, "ergebnis.json")) as f:
            d = json.load(f)
        fertig = len(d.get("tests", []))
        fehl = sum(1 for t in d["tests"] if t.get("status") != "ok")
        return f"{fertig} Test(s) fertig, {fehl} nicht ok"
    except (OSError, ValueError, KeyError):
        return "startet …"


def lauf_beenden():
    global laufend
    if laufend is None or laufend.poll() is not None:
        return
    try:
        os.killpg(laufend.pid, signal.SIGTERM)
        laufend.wait(10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(laufend.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        laufend.wait()


# ---------------------------------------------------------------------------
# Ergebnisse ablegen (Git-Daten-API: ein Commit für alle Dateien)
# ---------------------------------------------------------------------------

def ergebnis_dateien(erg):
    dateien, summe, ausgelassen = [], 0, []
    for wurzel, _, namen in os.walk(erg):
        for n in sorted(namen):
            p = os.path.join(wurzel, n)
            rel = os.path.relpath(p, erg)
            if os.path.islink(p) or n.endswith(".ppm"):
                continue
            g = os.path.getsize(p)
            if g > DATEI_MAX or summe + g > ERGEBNIS_MAX:
                ausgelassen.append(f"{rel} ({g // 1024} KB)")
                continue
            summe += g
            dateien.append((rel, p))
    return dateien, ausgelassen


def ergebnis_hochladen(erg, pfad, tok):
    """Dateien nach <AUFTRAG_REPO>:vm-laeufer-ergebnisse/<pfad>/ – Rückgabe (Anzahl, ausgelassen)"""
    dateien, ausgelassen = ergebnis_dateien(erg)
    if not dateien:
        return 0, ausgelassen
    eintraege = []
    for rel, p in dateien:
        with open(p, "rb") as f:
            blob = anfrage(f"/repos/{AUFTRAG_REPO}/git/blobs", tok, "POST",
                           {"content": base64.b64encode(f.read()).decode(), "encoding": "base64"})
        eintraege.append({"path": f"{pfad}/{rel}", "mode": "100644", "type": "blob", "sha": blob["sha"]})
    for versuch in range(3):
        try:
            ref = anfrage(f"/repos/{AUFTRAG_REPO}/git/ref/heads/{ERGEBNIS_ZWEIG}", tok)
            eltern = [ref["object"]["sha"]]
            basis = anfrage(f"/repos/{AUFTRAG_REPO}/git/commits/{eltern[0]}", tok)["tree"]["sha"]
        except GhFehler as fehler:
            if fehler.status != 404:
                raise
            eltern, basis = [], None
        baum = {"tree": eintraege}
        if basis:
            baum["base_tree"] = basis
        tree = anfrage(f"/repos/{AUFTRAG_REPO}/git/trees", tok, "POST", baum)
        commit = anfrage(f"/repos/{AUFTRAG_REPO}/git/commits", tok, "POST",
                         {"message": f"VM-Läufer: {pfad}", "tree": tree["sha"], "parents": eltern})
        try:
            if eltern:
                anfrage(f"/repos/{AUFTRAG_REPO}/git/refs/heads/{ERGEBNIS_ZWEIG}", tok, "PATCH", {"sha": commit["sha"]})
            else:
                anfrage(f"/repos/{AUFTRAG_REPO}/git/refs", tok, "POST",
                        {"ref": f"refs/heads/{ERGEBNIS_ZWEIG}", "sha": commit["sha"]})
            return len(dateien), ausgelassen
        except GhFehler as fehler:
            if fehler.status not in (409, 422) or versuch == 2:
                raise
            time.sleep(2)  # jemand anderes hat gleichzeitig geschrieben
    return len(dateien), ausgelassen


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

def kommentar(nr, text, tok):
    anfrage(f"/repos/{AUFTRAG_REPO}/issues/{nr}/comments", tok, "POST", {"body": text})


def schliessen(nr, tok):
    try:
        anfrage(f"/repos/{AUFTRAG_REPO}/issues/{nr}", tok, "PATCH", {"state": "closed"})
    except GhFehler as fehler:
        sag(f"Issue #{nr} nicht geschlossen: {fehler}")


def fertig_melden(nr, a, rc, text, tok):
    kennung = a.get("kennung", "-") if a else "-"
    kommentar(nr, f"{MARKE_FERTIG} kennung={kennung} rc={rc} -->\n{text}", tok)
    schliessen(nr, tok)
    tagebuch_setzen(f"{nr}", {"kennung": kennung, "status": "fertig", "rc": rc})


def zusammenfassung(erg):
    try:
        return open(os.path.join(erg, "zusammenfassung.txt")).read().strip()
    except OSError:
        return "(keine Zusammenfassung)"


def kein_test(nr, a, rc_t, text, pfad, tok):
    """Ohne Test fertig melden – mit einer kleinen Datei im Ergebnis-Zweig (legt ihn beim ersten
    Mal an), damit jeder Auftrag dort einen Ordner hat"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "zusammenfassung.txt"), "w") as f:
            f.write(text + "\n")
        try:
            ergebnis_hochladen(d, pfad, tok)
            text += f"\nErgebnisse: Zweig `{ERGEBNIS_ZWEIG}`, Ordner `{pfad}/` (1 Datei)"
        except GhFehler as fehler:
            text += f"\nErgebnisse nicht hochgeladen: {fehler}"
    fertig_melden(nr, a, rc_t, text, tok)


def auftrag_bearbeiten(issue, owner, tok_lesen, tok_auftraege):
    nr = issue["number"]
    try:
        a = auftrag_lesen(issue.get("body") or "")
    except AuftragFehler as fehler:
        fertig_melden(nr, None, "auftrag", f"Auftrag nicht lesbar: {fehler}", tok_auftraege)
        return
    z = zustand()
    pfad = f"{nr}-{a['kennung']}"
    kvm, grund = kvm_pruefen()
    kvm_text = "ja" if kvm else ("NEIN (TCG, langsam – nur Test)" if ohne_kvm_erlaubt() else f"NEIN: {grund}")
    kommentar(nr, f"{MARKE_AN}\nangenommen: {a['ref']} ({a['commit'][:10]}), KVM {kvm_text}, "
                  f"bis zu {z.get('vms', '?')} VM(s) mit je {z.get('kerne', '?')} Kern(en) und {int(z.get('ram_mb', '0')) // 1024} GB", tok_auftraege)
    tagebuch_setzen(f"{nr}", {"kennung": a["kennung"], "status": "laeuft"})
    if not kvm and not ohne_kvm_erlaubt():
        # Nicht still in TCG rechnen: ohne KVM wären die Tests viel zu langsam
        kein_test(nr, a, "kvm", f"Kein Test: KVM nicht nutzbar – {grund}", pfad, tok_auftraege)
        return
    ordner = os.path.join(ARBEIT, "auftrag")
    try:
        rc, erg = lauf_ausfuehren(a, z, tok_lesen, ordner)
    except (AuftragFehler, GhFehler, OSError, tarfile.TarError, zipfile.BadZipFile) as fehler:
        shutil.rmtree(ordner, ignore_errors=True)
        kein_test(nr, a, "fehler", f"Kein Test: {fehler}", pfad, tok_auftraege)
        return
    if rc == 130 or zustand().get("freigabe") != "ja":
        text = "abgebrochen: Freigabe beendet\n```\n" + zusammenfassung(erg) + "\n```"
        rc_t = "aus"
    elif rc == 125:
        text = "Kein Test: Landlock nicht verfügbar (einsperren.py)"
        rc_t = "fehler"
    else:
        text = "```\n" + zusammenfassung(erg) + "\n```"
        rc_t = str(rc)
    try:
        n, ausgelassen = ergebnis_hochladen(erg, pfad, tok_auftraege)
        text += f"\nErgebnisse: Zweig `{ERGEBNIS_ZWEIG}`, Ordner `{pfad}/` ({n} Dateien)"
        if ausgelassen:
            text += "\nZu groß, nicht hochgeladen: " + ", ".join(ausgelassen[:10])
    except GhFehler as fehler:
        text += f"\nErgebnisse nicht hochgeladen: {fehler}"
    fertig_melden(nr, a, rc_t, text, tok_auftraege)
    shutil.rmtree(ordner, ignore_errors=True)


def offene_auftraege(owner, tok):
    """Offene Issues mit Label vm-laeufer vom Besitzer, ohne „fertig“-Kommentar"""
    issues = anfrage(f"/repos/{AUFTRAG_REPO}/issues?labels={LABEL}&state=open&sort=created&direction=asc&per_page=20", tok)
    for issue in issues:
        if "pull_request" in issue or (issue.get("user") or {}).get("login") != owner:
            continue
        kommentare = anfrage(f"/repos/{AUFTRAG_REPO}/issues/{issue['number']}/comments?per_page=100", tok)
        eigene = [k for k in kommentare if (k.get("user") or {}).get("login") == owner]
        if any(MARKE_FERTIG in (k.get("body") or "") for k in eigene):
            continue
        if any(MARKE_AN in (k.get("body") or "") for k in eigene):
            # schon angenommen, aber nicht fertig: lief, als der Läufer endete
            fertig_melden(issue["number"], None, "aus", "abgebrochen: Läufer wurde beendet (Freigabe zu Ende oder Neustart)", tok)
            continue
        yield issue


beenden = False
NEUSTART_MARKE = os.path.join(HOME, "neustart-kvm")


def neustart_erlaubt():
    """Höchstens ein Neustart wegen des Rechts je 10 Minuten (keine Schleife, falls es trotz
    Neustart nicht greift)"""
    try:
        if time.time() - os.path.getmtime(NEUSTART_MARKE) < 600:
            return False
    except OSError:
        pass
    try:
        open(NEUSTART_MARKE, "w").close()
    except OSError:
        return False
    return True


def signal_term(*_):
    global beenden
    beenden = True
    lauf_beenden()


def main():
    signal.signal(signal.SIGTERM, signal_term)
    signal.signal(signal.SIGINT, signal_term)
    os.makedirs(ARBEIT, exist_ok=True)
    kvm, grund = kvm_pruefen()
    sag(f"VM-Läufer startet (Aufträge: {AUFTRAG_REPO}, Code: {CODE_REPO}, KVM {'ja' if kvm else 'nein: ' + grund})")
    owner = None
    naechste = 0.0
    while not beenden:
        z = zustand()
        if z.get("freigabe") != "ja":
            sag("Freigabe beendet")
            break
        if z.get("pause") == "ja":
            status("Pause: jemand arbeitet am Rechner – keine neuen Aufträge")
            time.sleep(3)
            continue
        kvm, grund = kvm_pruefen()
        if not kvm and z.get("kvm") == "ja" and "Recht" in grund and neustart_erlaubt():
            # Recht „Virtuelle Maschinen“ nach dem Start eingeschaltet: Gruppe und Landlock-Regel
            # bekommt die App nur beim Start – beenden, Saalburg startet sie (nach 30 s) neu
            sag("Recht „Virtuelle Maschinen“ ist jetzt an – Neustart, damit es gilt")
            status("Recht „Virtuelle Maschinen“ eingeschaltet – der Läufer startet neu …")
            return 0
        tok_lesen, tok_auftraege = token("lesen"), token("auftraege")
        if not tok_lesen or not tok_auftraege:
            status("Token fehlt: " + ", ".join(n for n, t in (("Code lesen", tok_lesen), ("Aufträge", tok_auftraege)) if not t),
                   "Einstellungen → Apps & Rechte → VM-Läufer")
            time.sleep(5)
            continue
        if time.time() < naechste:
            time.sleep(1)
            continue
        naechste = time.time() + ABFRAGE_S
        try:
            if owner is None:
                owner = anfrage("/user", tok_auftraege)["login"]
            gefunden = False
            for issue in offene_auftraege(owner, tok_auftraege):
                gefunden = True
                sag(f"Auftrag #{issue['number']}: {issue.get('title', '')[:80]}")
                auftrag_bearbeiten(issue, owner, tok_lesen, tok_auftraege)
                naechste = 0.0
                break
            if not gefunden:
                if kvm:
                    status(f"Bereit – KVM, zuletzt nach Aufträgen gesehen {time.strftime('%H:%M')}"
                           + (" · niedrige Priorität" if z.get("prioritaet") == "niedrig" else ""))
                else:
                    status(f"OHNE KVM – nimmt keine Tests an: {grund}",
                           f"zuletzt nach Aufträgen gesehen {time.strftime('%H:%M')}")
        except GhFehler as fehler:
            sag(f"GitHub: {fehler}")
            status(f"GitHub nicht erreichbar oder Token ohne Recht: {str(fehler)[:120]}")
            if fehler.status == 401:
                owner = None
    status("beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
