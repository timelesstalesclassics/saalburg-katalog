"""Tests des VM-Läufers ohne Saalburg und ohne GitHub: Aufträge lesen, Abbild prüfen,
Archive entpacken, Landlock (einsperren.py) und ein ganzer Auftrag gegen eine
nachgebildete GitHub-API (Token nie an Umleitungsziele).

  python3 -m unittest discover -s apps/vm-laeufer/tests
"""
import base64
import hashlib
import http.server
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HIER)
sys.path.insert(0, APP)
import einsperren  # noqa: E402
import vm_laeufer as vl  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def block(**w):
    werte = {"kennung": "abc123def0", "ref": "vm-laeufer", "commit": COMMIT, "abbild_lauf": "77",
             "abbild_artefakt": "4242", "abbild_manifest": "0" * 64, "tests": "werkzeug/test_a.py; werkzeug/test_b.py --x",
             "parallel": "2"}
    werte.update(w)
    werte = {k: v for k, v in werte.items() if v is not None}
    return "Auftrag\n\n```vm-laeufer\n" + "".join(f"{k} = {v}\n" for k, v in werte.items()) + "```\n"


class AuftragLesen(unittest.TestCase):
    def test_gueltig(self):
        a = vl.auftrag_lesen(block())
        self.assertEqual(a["commit"], COMMIT)
        self.assertEqual(a["parallel"], "2")

    def test_ungueltig(self):
        for falsch in ({"commit": "abc"}, {"tests": "werkzeug/x.py && rm -rf /"}, {"parallel": "9"},
                       {"ref": "../x"}, {"abbild_manifest": "zz"}, {"ram": "viel"}, {"kennung": None}):
            with self.subTest(falsch=falsch):
                with self.assertRaises(vl.AuftragFehler):
                    vl.auftrag_lesen(block(**falsch))
        with self.assertRaises(vl.AuftragFehler):
            vl.auftrag_lesen(block() .replace("parallel = 2", "geheim = 1"))
        with self.assertRaises(vl.AuftragFehler):
            vl.auftrag_lesen("kein Block")


def github_tarball(commit, dateien, oben="lang", pax=True, links=()):
    """tar.gz wie von GitHub (api.github.com/repos/<o>/<r>/tarball/<sha>, geprüft an echten
    Archiven): globaler pax-Kopf „comment“ mit der vollen Commit-ID (git archive), oberster Ordner
    <owner>-<repo>-<sha> mit voller (heute üblich) oder kurzer SHA, zuerst der Ordner selbst."""
    ordner = "o-code-" + (commit if oben == "lang" else commit[:7] if oben == "kurz" else oben)
    puffer = io.BytesIO()
    kopf = {"comment": commit} if pax is True else ({"comment": pax} if pax else {})
    with tarfile.open(fileobj=puffer, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers=kopf) as t:
        info = tarfile.TarInfo(ordner)
        info.type = tarfile.DIRTYPE
        info.mode = 0o775
        t.addfile(info)
        gesehen = set()
        for name, inhalt in dateien:
            teile = name.split("/")
            for i in range(1, len(teile)):
                d = "/".join(teile[:i])
                if d not in gesehen:
                    gesehen.add(d)
                    di = tarfile.TarInfo(f"{ordner}/{d}")
                    di.type = tarfile.DIRTYPE
                    di.mode = 0o775
                    t.addfile(di)
            fi = tarfile.TarInfo(f"{ordner}/{name}")
            fi.size = len(inhalt)
            fi.mode = 0o664
            t.addfile(fi, io.BytesIO(inhalt))
        for name, ziel in links:
            li = tarfile.TarInfo(f"{ordner}/{name}")
            li.type = tarfile.SYMTYPE
            li.linkname = ziel
            t.addfile(li)
    return puffer.getvalue()


def abbild_anlegen(ordner, extra=None):
    dateien = {"bzImage": b"kernel", "stick/osproto/system.sqfs": b"system" * 100, "stick/EFI/BOOT/BOOTX64.EFI": b"kernel",
               "programme/app": b"app", "commit.txt": (COMMIT + "\n").encode()}
    for name, inhalt in dateien.items():
        p = os.path.join(ordner, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(inhalt)
    zeilen = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(dateien.items()))
    with open(os.path.join(ordner, "abbild.sha256"), "w") as f:
        f.write(zeilen)
    if extra:
        with open(os.path.join(ordner, extra), "wb") as f:
            f.write(b"fremd")
    return hashlib.sha256(zeilen.encode()).hexdigest()


class Abbild(unittest.TestCase):
    def test_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            m = abbild_anlegen(d)
            vl.manifest_pruefen(d, m)
            with self.assertRaises(vl.AuftragFehler):
                vl.manifest_pruefen(d, "1" * 64)
            with open(os.path.join(d, "bzImage"), "ab") as f:
                f.write(b"x")
            with self.assertRaises(vl.AuftragFehler):
                vl.manifest_pruefen(d, m)
        with tempfile.TemporaryDirectory() as d:
            m = abbild_anlegen(d, extra="boese.sh")
            with self.assertRaises(vl.AuftragFehler):
                vl.manifest_pruefen(d, m)

    def test_archiv_ohne_links(self):
        with tempfile.TemporaryDirectory() as d:
            arch = os.path.join(d, "a.tar.gz")
            with open(arch, "wb") as f:
                f.write(github_tarball(COMMIT, [("werkzeug/x.py", b"print(1)")],
                                       links=[("geheim", "/daten/system/laeufer/vm-laeufer/token-lesen")]))
            ziel = os.path.join(d, "r")
            vl.archiv_entpacken(arch, ziel, COMMIT)
            self.assertTrue(os.path.isfile(os.path.join(ziel, "werkzeug", "x.py")))
            self.assertFalse(os.path.lexists(os.path.join(ziel, "geheim")))
            with self.assertRaises(vl.AuftragFehler):
                vl.archiv_entpacken(arch, os.path.join(d, "r2"), "f" * 40)

    def test_archiv_commit(self):
        """Wie echte GitHub-Archive: Ordner mit voller oder kurzer SHA, Commit im pax-Kopf"""
        anderer = "f" * 40
        faelle = [
            ("volle SHA, pax", dict(oben="lang"), True),
            ("kurze SHA, pax", dict(oben="kurz"), True),
            ("volle SHA, ohne pax", dict(oben="lang", pax=False), True),
            ("kurze SHA, ohne pax", dict(oben="kurz", pax=False), True),
            ("12 Zeichen, ohne pax", dict(oben=COMMIT[:12], pax=False), True),
            ("pax mit anderem Commit", dict(oben="lang", pax=anderer), False),
            ("fremder Ordner, ohne pax", dict(oben="fffffff", pax=False), False),
            ("zu kurz, ohne pax", dict(oben="0123", pax=False), False),
        ]
        for name, art, ok in faelle:
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                arch = os.path.join(d, "a.tar.gz")
                with open(arch, "wb") as f:
                    f.write(github_tarball(COMMIT, [("werkzeug/laeufer/lauf.py", b"# --raum")], **art))
                if ok:
                    vl.archiv_entpacken(arch, os.path.join(d, "r"), COMMIT)
                    self.assertTrue(os.path.isfile(os.path.join(d, "r", "werkzeug", "laeufer", "lauf.py")))
                else:
                    with self.assertRaises(vl.AuftragFehler) as f:
                        vl.archiv_entpacken(arch, os.path.join(d, "r"), COMMIT)
                    self.assertIn("passt nicht zum Commit", str(f.exception))


class Kvm(unittest.TestCase):
    def test_fehlt_bios(self):
        alt = vl.cpu_flags
        try:
            vl.cpu_flags = lambda: {"fpu", "sse2", "aes"}
            ok, grund = vl.kvm_pruefen("/gibt/es/nicht/kvm")
            self.assertFalse(ok)
            self.assertIn("BIOS", grund)
            self.assertIn("VT-x", grund)
            vl.cpu_flags = lambda: {"fpu", "vmx"}
            ok, grund = vl.kvm_pruefen("/gibt/es/nicht/kvm")
            self.assertFalse(ok)
            self.assertIn("/dev/kvm fehlt", grund)
        finally:
            vl.cpu_flags = alt

    def test_kein_kvm_geraet(self):
        with tempfile.NamedTemporaryFile() as f:
            ok, grund = vl.kvm_pruefen(f.name)
            self.assertFalse(ok)
            self.assertIn("antwortet nicht", grund)

    def test_recht_fehlt(self):
        alt = os.getgroups
        try:
            os.getgroups = lambda: [999999]
            with tempfile.TemporaryDirectory() as d:
                ok, grund = vl.kvm_pruefen(d)  # Ordner: open(O_RDWR) scheitert wie ohne Recht
            self.assertFalse(ok)
            self.assertIn("Virtuelle Maschinen", grund)
        finally:
            os.getgroups = alt


@unittest.skipUnless(einsperren.abi() >= 1, "Landlock fehlt im Kernel")
class Einsperren(unittest.TestCase):
    def test_kein_zugriff_auf_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            geheim = os.path.join(d, "tokens")
            arbeit = os.path.join(d, "arbeit")
            os.makedirs(geheim)
            os.makedirs(arbeit)
            with open(os.path.join(geheim, "token-lesen"), "w") as f:
                f.write("github_pat_geheim")
            probe = ("import os,sys\n"
                     f"try:\n open({os.path.join(geheim, 'token-lesen')!r}).read(); print('TOKEN_GELESEN')\n"
                     "except OSError: print('TOKEN_ZU')\n"
                     f"open({os.path.join(arbeit, 'x')!r},'w').write('1'); print('ARBEIT_OK')\n"
                     "try:\n os.kill(int(sys.argv[1]), 0); print('SIGNAL_RAUS')\n"
                     "except PermissionError: print('SIGNAL_ZU')\n"
                     "try:\n open('/proc/%s/environ' % sys.argv[1],'rb').read(); print('ENVIRON_GELESEN')\n"
                     "except OSError: print('ENVIRON_ZU')\n")
            befehl = [sys.executable, os.path.join(APP, "einsperren.py")]
            for p in ("/usr", "/lib", "/lib64", "/bin", "/etc", "/proc", os.path.dirname(sys.executable)):
                befehl += ["--lesen", p]
            befehl += ["--schreiben", arbeit, "--geraet", "/dev/null", "--", sys.executable, "-I", "-c", probe, str(os.getpid())]
            r = subprocess.run(befehl, capture_output=True, text=True, timeout=60)
            aus = r.stdout + r.stderr
            self.assertIn("TOKEN_ZU", aus)
            self.assertIn("ARBEIT_OK", aus)
            if os.getuid() != 0:
                # root (CAP_SYS_PTRACE) darf trotz Landlock environ lesen; die App ist nie root
                self.assertIn("ENVIRON_ZU", aus)
            if einsperren.abi() >= 6:
                self.assertIn("SIGNAL_ZU", aus)


# ---------------------------------------------------------------------------
# Ganzer Auftrag gegen eine nachgebildete GitHub-API
# ---------------------------------------------------------------------------

LAUF_PY = r'''
import argparse, json, os, sys
a = argparse.ArgumentParser()
for x in ("--raum", "--wurzel", "--ergebnis", "--ref", "--commit", "--tests", "--parallel", "--kerne", "--ram", "--zeitlimit", "--kvm"):
    a.add_argument(x)
a.add_argument("--ohne-ssd", action="store_true")
g = a.parse_args()
erg = g.ergebnis
# eingesperrt: Tokens nicht lesbar, Abbild über bau/ lesbar
try:
    open("TOKENS_PFAD/token-lesen").read(); tok = "TOKEN_GELESEN"
except OSError:
    tok = "TOKEN_ZU"
kernel = open(os.path.join(g.wurzel, "bau", "minipc", "bzImage"), "rb").read().decode()
open(os.path.join(erg, "zusammenfassung.txt"), "w").write(f"ok    {g.tests} raum={g.raum} {tok} kernel={kernel} parallel={g.parallel}\n")
json.dump({"tests": [{"status": "ok"}]}, open(os.path.join(erg, "ergebnis.json"), "w"))
os.makedirs(os.path.join(erg, "01-test_a"))
open(os.path.join(erg, "01-test_a", "bild.png"), "wb").write(b"\x89PNG-test")
'''


class Github(http.server.BaseHTTPRequestHandler):
    zustand = None

    def log_message(self, *_):
        pass

    def antwort(self, code, daten=None, roh=None, kopf=None):
        body = roh if roh is not None else json.dumps(daten if daten is not None else {}).encode()
        self.send_response(code)
        for k, v in (kopf or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def lesen(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        z = self.zustand
        auth = self.headers.get("Authorization")
        z["anfragen"].append(("GET", self.path, auth))
        p = self.path
        if p.startswith("/speicher/"):
            # Umleitungsziel: darf nie einen Token sehen
            if auth:
                z["token_am_speicher"] = True
            return self.antwort(200, roh=z["dateien"][p])
        if p == "/user":
            return self.antwort(200, {"login": "besitzer"})
        if p.startswith("/repos/o/test/issues?"):
            return self.antwort(200, [i for i in z["issues"] if i["state"] == "open"])
        if p.startswith("/repos/o/test/issues/") and "/comments" in p:
            nr = int(p.split("/")[5])
            return self.antwort(200, z["kommentare"].get(nr, []))
        if p.startswith("/repos/o/code/tarball/"):
            if auth != "Bearer " + "L" * 30:
                return self.antwort(401, {})
            return self.antwort(302, roh=b"", kopf={"Location": f"http://127.0.0.1:{z['port']}/speicher/code.tar.gz"})
        if p.startswith("/repos/o/code/actions/artifacts/4242/zip"):
            if auth != "Bearer " + "L" * 30:
                return self.antwort(401, {})
            return self.antwort(302, roh=b"", kopf={"Location": f"http://127.0.0.1:{z['port']}/speicher/abbild.zip"})
        if p.startswith("/repos/o/test/git/ref/heads/"):
            return self.antwort(404, {"message": "Not Found"})
        return self.antwort(404, {"message": "?"})

    def do_POST(self):
        z = self.zustand
        d = self.lesen()
        z["anfragen"].append(("POST", self.path, self.headers.get("Authorization")))
        p = self.path
        if p.startswith("/repos/o/test/issues/") and p.endswith("/comments"):
            nr = int(p.split("/")[5])
            z["kommentare"].setdefault(nr, []).append({"user": {"login": "besitzer"}, "body": d["body"]})
            return self.antwort(201, {})
        if p == "/repos/o/test/git/blobs":
            z["blobs"].append(base64.b64decode(d["content"]))
            return self.antwort(201, {"sha": f"blob{len(z['blobs'])}"})
        if p == "/repos/o/test/git/trees":
            z["baum"] = d
            return self.antwort(201, {"sha": "baum1"})
        if p == "/repos/o/test/git/commits":
            return self.antwort(201, {"sha": "commit1"})
        if p == "/repos/o/test/git/refs":
            z["ref"] = d
            return self.antwort(201, {})
        return self.antwort(404, {})

    def do_PATCH(self):
        z = self.zustand
        d = self.lesen()
        p = self.path
        if p.startswith("/repos/o/test/issues/"):
            nr = int(p.split("/")[5])
            for i in z["issues"]:
                if i["number"] == nr:
                    i["state"] = d.get("state", i["state"])
            return self.antwort(200, {})
        return self.antwort(404, {})


class GanzerAuftrag(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.tokens = os.path.join(self.d, "tokens")
        lauf_py = LAUF_PY.replace("TOKENS_PFAD", self.tokens)
        # Archiv des Codes (Aufbau wie bei GitHub: volle SHA im Ordner, Commit im pax-Kopf)
        # mit Attrappe von lauf.py
        code = github_tarball(COMMIT, [("werkzeug/laeufer/lauf.py", lauf_py.encode()), ("werkzeug/test_a.py", b"")])
        abbild = os.path.join(self.d, "abbild-quelle")
        os.makedirs(abbild)
        self.manifest = abbild_anlegen(abbild)
        zpuffer = io.BytesIO()
        with zipfile.ZipFile(zpuffer, "w") as zf:
            for wurzel, _, namen in os.walk(abbild):
                for n in namen:
                    p = os.path.join(wurzel, n)
                    zf.write(p, os.path.relpath(p, abbild))
        self.zip = zpuffer.getvalue()
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Github)
        port = self.srv.server_address[1]
        Github.zustand = {"port": port, "anfragen": [], "kommentare": {}, "blobs": [], "token_am_speicher": False,
                          "dateien": {"/speicher/code.tar.gz": code, "/speicher/abbild.zip": self.zip},
                          "issues": []}
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.home = os.path.join(self.d, "home")
        os.makedirs(self.home)
        os.makedirs(self.tokens)
        for n, w in (("lesen", "L" * 30), ("auftraege", "A" * 30)):
            with open(os.path.join(self.tokens, f"token-{n}"), "w") as f:
                f.write(w)
        # wie auf Saalburg: Zustand in einem eigenen Ordner (/run/laeufer/<k>), getrennt von den Tokens
        os.makedirs(os.path.join(self.d, "run"))
        self.zustand_datei = os.path.join(self.d, "run", "zustand")
        with open(self.zustand_datei, "w") as f:
            f.write("freigabe=ja\npause=nein\nvms=2\nkerne=2\nram_mb=3072\n")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        subprocess.run(["chmod", "-R", "u+w", self.d])
        subprocess.run(["rm", "-rf", self.d])

    def laeufer(self, sekunden=60, kvm="tcg"):
        # kvm="tcg": ohne KVM in TCG erlaubt (Testrechner haben oft kein /dev/kvm);
        # kvm="fehlt": /dev/kvm gibt es nicht, TCG nicht erlaubt (wie ein Rechner mit VT-x aus)
        extra = {"VM_LAEUFER_TCG": "ja"} if kvm == "tcg" else {"VM_LAEUFER_KVM_GERAET": "/gibt/es/nicht/kvm"}
        env = dict(os.environ, HOME=self.home, XDG_RUNTIME_DIR=self.home, USER="vm-laeufer", **extra,
                   VM_LAEUFER_ZUSTAND=self.zustand_datei, VM_LAEUFER_TOKENS=self.tokens, VL_TOKENS=self.tokens,
                   VM_LAEUFER_API=f"http://127.0.0.1:{Github.zustand['port']}",
                   VM_LAEUFER_CODE_REPO="o/code", VM_LAEUFER_AUFTRAG_REPO="o/test")
        p = subprocess.Popen([sys.executable, "-I", os.path.join(APP, "vm_laeufer.py")], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return p

    def warte(self, bedingung, sekunden=60):
        import time
        ende = time.time() + sekunden
        while time.time() < ende:
            if bedingung():
                return True
            time.sleep(0.5)
        return False

    @unittest.skipUnless(einsperren.abi() >= 1, "Landlock fehlt im Kernel")
    def test_auftrag(self):
        z = Github.zustand
        body = block(abbild_manifest=self.manifest, abbild_zip_sha256=hashlib.sha256(self.zip).hexdigest(), katalog="nein")
        z["issues"] = [
            {"number": 5, "title": "fremd", "state": "open", "user": {"login": "jemand"}, "body": body},
            {"number": 7, "title": "VM-Läufer", "state": "open", "user": {"login": "besitzer"}, "body": body},
        ]
        p = self.laeufer()
        try:
            ok = self.warte(lambda: any(i["number"] == 7 and i["state"] == "closed" for i in z["issues"]), 90)
        finally:
            with open(self.zustand_datei, "w") as f:
                f.write("freigabe=nein\n")
            try:
                aus = p.communicate(timeout=30)[0]
            except subprocess.TimeoutExpired:
                p.kill()
                aus = p.communicate()[0]
        self.assertTrue(ok, aus)
        texte = [k["body"] for k in z["kommentare"].get(7, [])]
        self.assertTrue(any(vl.MARKE_AN in t for t in texte), texte)
        fertig = [t for t in texte if vl.MARKE_FERTIG in t]
        self.assertTrue(fertig and "rc=0" in fertig[0], (texte, [b[:3000] for b in z["blobs"]]))
        self.assertIn("raum=sandbox", fertig[0])
        self.assertIn("TOKEN_ZU", fertig[0])
        self.assertIn("kernel=kernel", fertig[0])
        self.assertIn("parallel=2", fertig[0])
        self.assertNotIn(5, z["kommentare"], "fremdes Issue darf nicht bearbeitet werden")
        self.assertFalse(z["token_am_speicher"], "Token ging an das Umleitungsziel")
        pfade = [e["path"] for e in z["baum"]["tree"]]
        self.assertIn("7-abc123def0/01-test_a/bild.png", pfade)
        self.assertEqual(z["ref"]["ref"], "refs/heads/vm-laeufer-ergebnisse")
        self.assertTrue(os.path.exists(os.path.join(self.home, "abbilder", self.manifest, ".geprueft")))
        for methode, pfad, auth in z["anfragen"]:
            if "/issues" in pfad or "/git/" in pfad or pfad == "/user":
                self.assertEqual(auth, "Bearer " + "A" * 30, pfad)

    def test_falsches_abbild_kein_test(self):
        z = Github.zustand
        z["issues"] = [{"number": 9, "title": "x", "state": "open", "user": {"login": "besitzer"},
                        "body": block(abbild_manifest="1" * 64, katalog="nein")}]
        p = self.laeufer()
        try:
            ok = self.warte(lambda: z["issues"][0]["state"] == "closed", 90)
        finally:
            with open(self.zustand_datei, "w") as f:
                f.write("freigabe=nein\n")
            aus = p.communicate(timeout=30)[0]
        self.assertTrue(ok, aus)
        texte = [k["body"] for k in z["kommentare"].get(9, [])]
        self.assertTrue(any("rc=fehler" in t and "Prüfsumme" in t for t in texte), texte)

    def auftrag_bis_fertig(self, nr, body, kvm="tcg"):
        z = Github.zustand
        z["issues"] = [{"number": nr, "title": "x", "state": "open", "user": {"login": "besitzer"}, "body": body}]
        p = self.laeufer(kvm=kvm)
        try:
            ok = self.warte(lambda: z["issues"][0]["state"] == "closed", 90)
        finally:
            with open(self.zustand_datei, "w") as f:
                f.write("freigabe=nein\n")
            aus = p.communicate(timeout=30)[0]
        self.assertTrue(ok, aus)
        return [k["body"] for k in z["kommentare"].get(nr, [])]

    def test_ohne_kvm_kein_test(self):
        """VT-x aus (kein /dev/kvm): nicht still TCG, sondern rc=kvm mit Grund; Ergebnis-Zweig wird
        angelegt (gab es auf GitHub noch nicht: GET ref → 404)"""
        z = Github.zustand
        texte = self.auftrag_bis_fertig(11, block(abbild_manifest=self.manifest, katalog="nein"), kvm="fehlt")
        self.assertTrue(any("KVM NEIN" in t for t in texte), texte)
        fertig = [t for t in texte if vl.MARKE_FERTIG in t]
        self.assertTrue(fertig and "rc=kvm" in fertig[0] and "KVM nicht nutzbar" in fertig[0], texte)
        self.assertEqual(z["ref"]["ref"], "refs/heads/vm-laeufer-ergebnisse")
        self.assertEqual([e["path"] for e in z["baum"]["tree"]], ["11-abc123def0/zusammenfassung.txt"])
        self.assertNotIn("base_tree", z["baum"])
        self.assertFalse(any("/tarball/" in pfad for _, pfad, _ in z["anfragen"]), "ohne KVM nichts laden")

    def test_archiv_anderer_commit(self):
        z = Github.zustand
        z["dateien"]["/speicher/code.tar.gz"] = github_tarball(COMMIT, [("werkzeug/laeufer/lauf.py", b"--raum")], pax="f" * 40)
        texte = self.auftrag_bis_fertig(12, block(abbild_manifest=self.manifest, katalog="nein"))
        fertig = [t for t in texte if vl.MARKE_FERTIG in t]
        self.assertTrue(fertig and "rc=fehler" in fertig[0] and "passt nicht zum Commit" in fertig[0], texte)
        self.assertIn("Ergebnisse: Zweig", fertig[0])

    def test_ohne_freigabe_nichts(self):
        with open(self.zustand_datei, "w") as f:
            f.write("freigabe=nein\n")
        p = self.laeufer()
        aus = p.communicate(timeout=30)[0]
        self.assertEqual(p.returncode, 0, aus)
        self.assertEqual(Github.zustand["anfragen"], [], "ohne Freigabe keine Anfrage an GitHub")

    def test_pause_keine_auftraege(self):
        import time
        with open(self.zustand_datei, "w") as f:
            f.write("freigabe=ja\npause=ja\n")
        p = self.laeufer()
        time.sleep(5)
        with open(self.zustand_datei, "w") as f:
            f.write("freigabe=nein\n")
        p.communicate(timeout=30)
        self.assertEqual(Github.zustand["anfragen"], [], "in der Pause keine Abfrage")
        with open(os.path.join(self.home, "laeufer.status")) as f:
            self.assertIn("beendet", f.read())


if __name__ == "__main__":
    unittest.main()
