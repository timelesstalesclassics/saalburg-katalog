"""Tests der App „zig“ (unittest, nur Standardbibliothek).

Auf Saalburg in der Sandbox der App:
  python3 -I -B -m unittest discover -v -s /daten/apps/zig/aktuell/tests
Arbeitet in $HOME der App (Dokumente/unittest-*), richtet Zig dort ein, falls nötig.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HIER = os.path.dirname(os.path.abspath(__file__))
WERKZEUG = os.path.join(os.path.dirname(HIER), "werkzeug")
sys.path.insert(0, WERKZEUG)

import werkzeug_mcp as wm  # noqa: E402
import zig_dist  # noqa: E402


class Mcp:
    """MCP-Server als Kindprozess, eine JSON-Zeile hin, eine zurück."""

    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-I", "-B", os.path.join(WERKZEUG, "zig_mcp.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True)
        self.nr = 0

    def anfrage(self, methode, params=None):
        self.nr += 1
        n = {"jsonrpc": "2.0", "id": self.nr, "method": methode}
        if params is not None:
            n["params"] = params
        self.p.stdin.write(json.dumps(n) + "\n")
        self.p.stdin.flush()
        while True:
            antwort = json.loads(self.p.stdout.readline())
            if antwort.get("id") == self.nr:
                return antwort

    def werkzeug(self, name, **argumente):
        erg = self.anfrage("tools/call", {"name": name, "arguments": argumente})["result"]
        return erg["content"][0]["text"], erg.get("isError", False)

    def ende(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


class TestPfade(unittest.TestCase):
    def setUp(self):
        self.alt = os.environ.get("HOME")
        self.tmp = tempfile.mkdtemp()
        os.environ["HOME"] = self.tmp
        os.makedirs(os.path.join(self.tmp, "Dokumente", "a"))

    def tearDown(self):
        os.environ["HOME"] = self.alt
        shutil.rmtree(self.tmp)

    def test_innerhalb(self):
        self.assertTrue(wm.in_dokumente("a").endswith("/Dokumente/a"))
        self.assertTrue(wm.in_dokumente("app.zig:/a").endswith("/Dokumente/a"))

    def test_ausserhalb(self):
        for rel in ("../", "a/../../x", "/../etc"):
            with self.assertRaises(wm.WerkzeugFehler):
                wm.in_dokumente(rel, muss_existieren=False)

    def test_link_nach_aussen(self):
        os.symlink("/etc", os.path.join(self.tmp, "Dokumente", "raus"))
        with self.assertRaises(wm.WerkzeugFehler):
            wm.in_dokumente("raus/passwd")

    def test_papierkorb(self):
        os.makedirs(os.path.join(self.tmp, "Dokumente", ".Papierkorb", "x"))
        with self.assertRaises(wm.WerkzeugFehler):
            wm.in_dokumente(".Papierkorb/x")


class TestAusfuehren(unittest.TestCase):
    def test_zeitlimit(self):
        erg = wm.ausfuehren(["sh", "-c", "echo los; sleep 30"], "/", 1)
        self.assertTrue(erg.zeitueberschreitung)
        self.assertIn("los", erg.ausgabe)
        self.assertLess(erg.dauer, 10)

    def test_eingabe_und_rc(self):
        erg = wm.ausfuehren(["sh", "-c", "read x; echo \"[$x]\"; exit 3"], "/", 10, eingabe="hallo\n")
        self.assertEqual(erg.rc, 3)
        self.assertIn("[hallo]", erg.ausgabe)

    def test_kuerzen(self):
        t = wm.kuerzen("x" * 100_000)
        self.assertLess(len(t), wm.AUSGABE_MAX + 100)
        self.assertIn("ausgelassen", t)


class TestZig(unittest.TestCase):
    """Zig selbst und der MCP-Server."""

    @classmethod
    def setUpClass(cls):
        cls.projekt = f"unittest-{os.getpid()}"
        cls.doku = os.path.join(os.environ["HOME"], "Dokumente")
        cls.mcp = Mcp()

    @classmethod
    def tearDownClass(cls):
        cls.mcp.ende()
        shutil.rmtree(os.path.join(cls.doku, cls.projekt), ignore_errors=True)
        shutil.rmtree(os.path.join(cls.doku, cls.projekt + "-datei"), ignore_errors=True)

    def test_0_paket(self):
        # Zig liegt entpackt im Paket (nur lesbar), das Archiv nicht mehr
        self.assertTrue(zig_dist.bereit(), zig_dist.zig_datei())
        self.assertFalse(os.path.exists(os.path.join(zig_dist.PAKET, zig_dist.ARCHIV)))
        self.assertFalse(os.access(zig_dist.ZIG_ORDNER, os.W_OK))
        self.assertTrue(os.path.isfile(os.path.join(zig_dist.ZIG_ORDNER, "lib", "std", "std.zig")))

    def test_1_protokoll(self):
        init = self.mcp.anfrage("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "zig")
        self.assertIn("app datei kopieren", init["result"]["instructions"])
        namen = {w["name"] for w in self.mcp.anfrage("tools/list")["result"]["tools"]}
        self.assertTrue({"zig_version", "zig_bauen", "zig_test", "programm_ausfuehren", "zig"} <= namen)
        self.assertIn("error", self.mcp.anfrage("tools/call", {"name": "gibt_es_nicht", "arguments": {}}))
        text, fehler = self.mcp.werkzeug("zig_bauen", projekt="../../etc")
        self.assertTrue(fehler)
        text, fehler = self.mcp.werkzeug("zig_bauen", projekt="x", unbekannt=1)
        self.assertTrue(fehler)

    def test_2_version(self):
        text, fehler = self.mcp.werkzeug("zig_version")
        self.assertFalse(fehler, text)
        self.assertIn("zig 0.16.0", text)

    def test_3_init_bauen_ausfuehren_testen(self):
        text, fehler = self.mcp.werkzeug("zig", argumente=["init"], ordner=self.projekt)
        self.assertFalse(fehler, text)
        main = os.path.join(self.doku, self.projekt, "src", "main.zig")
        if not os.path.exists(main):
            self.skipTest("zig init hat kein src/main.zig angelegt")
        text, fehler = self.mcp.werkzeug("zig_bauen", projekt=self.projekt, ziel="saalburg",
                                         optimierung="ReleaseSafe", zeitlimit_s=1800)
        self.assertFalse(fehler, text)
        self.assertIn("zig-out/bin/", text)
        text, fehler = self.mcp.werkzeug("programm_ausfuehren", projekt=self.projekt, zeitlimit_s=60)
        self.assertFalse(fehler, text)
        text, fehler = self.mcp.werkzeug("zig_test", projekt=self.projekt, zeitlimit_s=1800)
        self.assertFalse(fehler, text)

    def test_4_datei(self):
        ordner = os.path.join(self.doku, self.projekt + "-datei")
        os.makedirs(ordner, exist_ok=True)
        with open(os.path.join(ordner, "hallo.zig"), "w") as f:
            f.write('const std = @import("std");\n\n'
                    'pub fn main() void {\n    std.debug.print("Hallo, Saalburg!\\n", .{});\n}\n\n'
                    'test "addieren" {\n    try std.testing.expectEqual(@as(u32, 4), 2 + 2);\n}\n')
        rel = self.projekt + "-datei/hallo.zig"
        text, fehler = self.mcp.werkzeug("zig_fmt", projekt=rel)
        self.assertFalse(fehler, text)
        text, fehler = self.mcp.werkzeug("zig_bauen", projekt=rel, zeitlimit_s=1800)
        self.assertFalse(fehler, text)
        text, fehler = self.mcp.werkzeug("programm_ausfuehren", projekt=self.projekt + "-datei",
                                         programm="zig-out/bin/hallo")
        self.assertFalse(fehler, text)
        self.assertIn("Hallo, Saalburg!", text)
        text, fehler = self.mcp.werkzeug("zig_test", projekt=rel, filter="addieren", zeitlimit_s=1800)
        self.assertFalse(fehler, text)
        # Kompilierfehler kommt als Fehler mit Meldung zurück
        with open(os.path.join(ordner, "kaputt.zig"), "w") as f:
            f.write("pub fn main() void { undefinierter_name(); }\n")
        text, fehler = self.mcp.werkzeug("zig_bauen", projekt=self.projekt + "-datei/kaputt.zig")
        self.assertTrue(fehler)
        self.assertIn("undefinierter_name", text)
        # keine Caches in den Dokumenten
        self.assertFalse(os.path.exists(os.path.join(ordner, ".zig-cache")))


if __name__ == "__main__":
    unittest.main()
