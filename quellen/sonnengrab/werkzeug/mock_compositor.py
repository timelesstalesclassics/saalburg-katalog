#!/usr/bin/env python3
"""Strenger Test-Compositor: spielt die Rolle der Saalburg-Oberfläche (wl_shm, xdg-shell,
wl_seat mit Tastatur) nach dem Wayland-Protokoll, startet Sonnengrab als Klient,
schickt Größenänderungen, Tasten, Fokuswechsel und am Ende close (Super+Q) und
speichert die gelieferten Bilder als PNG.

  tools/mock_compositor.py <programm> <ausgabeordner>
"""
import array, mmap, os, socket, struct, subprocess, sys, time
from PIL import Image

PROG, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
rt = os.path.join(OUT, "rt"); os.makedirs(rt, exist_ok=True)
path = os.path.join(rt, "wayland-0")
if os.path.exists(path): os.unlink(path)
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(path); srv.listen(1)

# Sandbox von Saalburg: absoluter WAYLAND_DISPLAY
env = {"WAYLAND_DISPLAY": path, "XDG_RUNTIME_DIR": rt, "HOME": OUT, "PATH": "/usr/bin:/bin"}
if "ALSA_CONFIG_PATH" in os.environ: env["ALSA_CONFIG_PATH"] = os.environ["ALSA_CONFIG_PATH"]
proc = subprocess.Popen([PROG], env=env, stderr=subprocess.PIPE)
srv.settimeout(5)
c, _ = srv.accept(); c.setblocking(False)

GLOBALS = [(1, "wl_compositor", 6), (2, "wl_subcompositor", 1), (3, "wl_shm", 1), (4, "wl_seat", 7),
           (5, "wl_output", 4), (6, "xdg_wm_base", 5), (7, "zxdg_decoration_manager_v1", 1),
           (8, "wl_data_device_manager", 3), (9, "zwp_linux_dmabuf_v1", 3)]
# Anfragesignaturen (aus wl_protokoll.zig von Saalburg)
REQ = {
    "wl_display": ["n:wl_callback", "n:wl_registry"],
    "wl_registry": ["uN"],
    "wl_compositor": ["n:wl_surface", "n:wl_region", ""],
    "wl_shm": ["nhi:wl_shm_pool", ""],
    "wl_shm_pool": ["niiiiu:wl_buffer", "", "i"],
    "wl_buffer": [""],
    "wl_surface": ["", "oii", "iiii", "n:wl_callback", "o", "o", "", "i", "i", "iiii", "ii", "n:wl_callback"],
    "wl_seat": ["n:wl_pointer", "n:wl_keyboard", "n:wl_touch", ""],
    "wl_keyboard": [""],
    "xdg_wm_base": ["", "n:xdg_positioner", "no:xdg_surface", "u"],
    "xdg_surface": ["", "n:xdg_toplevel", "noo:xdg_popup", "iiii", "u"],
    "xdg_toplevel": ["", "o", "s", "s", "ouii", "ou", "ouu", "ii", "ii", "", "", "o", "", ""],
}
DESTRUCTOR = {("wl_buffer", 0), ("wl_shm_pool", 1), ("wl_surface", 0), ("xdg_surface", 0), ("xdg_toplevel", 0), ("wl_keyboard", 0)}

objs = {1: "wl_display"}
fds_in = []
inbuf = b""
pools, buffers = {}, {}
surface_state = {"pending": None, "frames": [], "committed": 0}
log = []
fehler = []
frames_saved = []
serial = [100]
closing = False
ids = {}

def nser():
    serial[0] += 1; return serial[0]

def send(obj, op, payload=b"", fds=()):
    msg = struct.pack("<II", obj, ((8 + len(payload)) << 16) | op) + payload
    anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
    while True:
        try: c.sendmsg([msg], anc); return
        except BlockingIOError: time.sleep(0.001)
        except BrokenPipeError:
            if closing: return
            print("Klient weg; stderr:", proc.stderr.read().decode(), "rc", proc.wait()); print("bisher:", log[-15:], fehler); sys.exit(1)

def s_str(s):
    b = s.encode() + b"\0"; return struct.pack("<I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)

def s_arr(b):
    return struct.pack("<I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)

def destroy(oid):
    objs.pop(oid, None); send(1, 1, struct.pack("<I", oid))

def new_obj(oid, typ):
    if oid in objs: fehler.append(f"ID {oid} wiederverwendet, obwohl noch belegt ({objs[oid]})")
    objs[oid] = typ

def configure(w, h, aktiv=True):
    st = [1, 5, 6, 7, 8] + ([4] if aktiv else [])
    send(ids["toplevel"], 0, struct.pack("<ii", w, h) + s_arr(struct.pack(f"<{len(st)}I", *st)))
    send(ids["xdg_surface"], 0, struct.pack("<I", nser()))

def handle(oid, op, p):
    typ = objs.get(oid)
    if typ is None: fehler.append(f"Anfrage an unbekanntes Objekt {oid} op {op}"); return
    sigs = REQ.get(typ)
    if sigs is None or op >= len(sigs): fehler.append(f"unbekannte Anfrage {typ}.{op}"); return
    sig, _, newtyp = sigs[op].partition(":")
    args, pos = [], 0
    for ch in sig:
        if ch in "uon": args.append(struct.unpack_from("<I", p, pos)[0]); pos += 4
        elif ch == "i": args.append(struct.unpack_from("<i", p, pos)[0]); pos += 4
        elif ch == "s":
            n = struct.unpack_from("<I", p, pos)[0]; s = p[pos + 4:pos + 4 + n - 1].decode(); pos += 4 + ((n + 3) & ~3); args.append(s)
        elif ch == "N":
            n = struct.unpack_from("<I", p, pos)[0]; s = p[pos + 4:pos + 4 + n - 1].decode(); pos += 4 + ((n + 3) & ~3)
            ver, nid = struct.unpack_from("<II", p, pos); pos += 8; args += [s, ver, nid]
        elif ch == "h":
            if not fds_in: fehler.append(f"{typ}.{op}: Deskriptor fehlt"); return
            args.append(fds_in.pop(0))
    if pos != len(p): fehler.append(f"{typ}.{op}: Länge {len(p)} statt {pos}")
    if (typ, op) in DESTRUCTOR: destroy(oid)
    log.append((typ, op))
    if typ == "wl_display":
        new_obj(args[0], newtyp)
        if op == 0: send(args[0], 0, struct.pack("<I", 1)); destroy(args[0])
        else:
            for name, iface, ver in GLOBALS: send(args[0], 0, struct.pack("<I", name) + s_str(iface) + struct.pack("<I", ver))
    elif typ == "wl_registry":
        name, iface, ver, nid = args
        g = [x for x in GLOBALS if x[0] == name]
        if not g or g[0][1] != iface or ver > g[0][2] or ver < 1: fehler.append(f"bind falsch: {args}")
        new_obj(nid, iface); ids[iface] = nid
        if iface == "wl_seat":
            send(nid, 0, struct.pack("<I", 3))  # Zeiger + Tastatur
            if ver >= 2: send(nid, 1, s_str("seat0"))
        if iface == "wl_shm":
            send(nid, 0, struct.pack("<I", 0)); send(nid, 0, struct.pack("<I", 1))
    elif typ == "wl_compositor":
        new_obj(args[0], newtyp); ids[newtyp.split("_")[-1]] = args[0]
    elif typ == "wl_shm":
        nid, fd, size = args
        new_obj(nid, "wl_shm_pool"); pools[nid] = (mmap.mmap(fd, size), size); os.close(fd)
    elif typ == "wl_shm_pool" and op == 0:
        nid, off, w, h, stride, fmt = args
        if fmt not in (0, 1): fehler.append(f"Format {fmt}")
        if off + stride * h > pools[oid][1]: fehler.append("Puffer ragt über den Pool hinaus")
        new_obj(nid, "wl_buffer"); buffers[nid] = (oid, off, w, h, stride)
    elif typ == "wl_seat" and op == 1:
        new_obj(args[0], "wl_keyboard"); ids["keyboard"] = args[0]
        km = os.memfd_create("km"); os.write(km, b"xkb_keymap {};\0")
        send(args[0], 0, struct.pack("<II", 1, 15), fds=[km]); os.close(km)
        send(args[0], 5, struct.pack("<ii", 30, 500))
    elif typ == "xdg_wm_base":
        if op == 2: new_obj(args[0], "xdg_surface"); ids["xdg_surface"] = args[0]
        if op == 3: log.append(("pong", args[0]))
    elif typ == "xdg_surface":
        if op == 1: new_obj(args[0], "xdg_toplevel"); ids["toplevel"] = args[0]
        if op == 4: surface_state["acked"] = args[0]
    elif typ == "xdg_toplevel":
        if op == 2: ids["title"] = args[0]
    elif typ == "wl_surface":
        if op == 1: surface_state["pending"] = args[0]
        if op == 3: new_obj(args[0], "wl_callback"); surface_state["frames"].append(args[0])
        if op == 6:
            surface_state["committed"] += 1
            if surface_state["committed"] == 1:
                configure(960, 552)  # erster Platz: Vollbild 1:1-ähnlich
            b = surface_state["pending"]
            if b:
                if b not in buffers: fehler.append("attach mit unbekanntem Puffer"); return
                if surface_state.get("acked") is None: fehler.append("Puffer vor ack_configure")
                pid, off, w, h, stride = buffers[b]
                mm = pools[pid][0]
                img = Image.frombuffer("RGBX", (w, h), mm[off:off + stride * h], "raw", "BGRX", stride, 1).convert("RGB")
                surface_state["last"] = img
                surface_state["shown"] = surface_state.get("shown", 0) + 1
                send(b, 0)  # release
                surface_state["pending"] = None

def pump(dauer):
    global inbuf
    ende = time.time() + dauer
    while time.time() < ende:
        try:
            data, anc, _, _ = c.recvmsg(65536, socket.CMSG_SPACE(16 * 4))
            if not data: return False

            for lvl, t, d in anc:
                a = array.array("i"); a.frombytes(d[:len(d) - len(d) % 4]); fds_in.extend(a)
            inbuf += data
            while len(inbuf) >= 8:
                oid, h2 = struct.unpack_from("<II", inbuf)
                size = h2 >> 16
                if size < 8 or size % 4: fehler.append("Nachrichtengröße"); return False
                if len(inbuf) < size: break
                handle(oid, h2 & 0xffff, inbuf[8:size]); inbuf = inbuf[size:]
        except BlockingIOError:
            time.sleep(0.002)
        # Bild fertig: Rückrufe auslösen (~60 Hz)
        if surface_state["frames"] and time.time() - surface_state.get("t", 0) > 1 / 60:
            surface_state["t"] = time.time()
            for cb in surface_state["frames"]:
                send(cb, 0, struct.pack("<I", int(time.time() * 1000) & 0xffffffff)); destroy(cb)
            surface_state["frames"] = []
        if proc.poll() is not None: return False
    return True

def save(name):
    if "last" in surface_state:
        surface_state["last"].save(os.path.join(OUT, name)); frames_saved.append((name, surface_state["last"].size))

def key(code, down):
    send(ids["keyboard"], 3, struct.pack("<IIII", nser(), int(time.time() * 1000) & 0xffffffff, code, 1 if down else 0))

def tap(code, t=0.12):
    key(code, True); pump(t); key(code, False); pump(t)

pump(2.0)
save("1-titel-960x552.png")
n_titel = surface_state.get("shown", 0)
# Fokus geben, Ping
send(ids["keyboard"], 1, struct.pack("<II", nser(), ids["surface"]) + s_arr(b""))
send(ids["xdg_wm_base"], 0, struct.pack("<I", 4242))
tap(28)                       # Enter: Spiel starten
pump(1.5)
key(42, True); key(106, True)  # Shift + rechts: rennen
pump(1.2)
key(106, False); key(42, False)
tap(57)                       # Sprung
pump(0.6)
save("2-spiel-960x552.png")
configure(1920, 1080)          # Vollbild (Super+1)
pump(1.0)
save("3-vollbild-1920x1080.png")
configure(700, 400)            # kleiner Platz
pump(0.8)
save("4-klein-700x400.png")
configure(960, 1050)           # 1:1 hochkant
pump(0.6)
send(ids["keyboard"], 2, struct.pack("<II", nser(), ids["surface"]))  # Fokus weg -> Pause
pump(0.8)
save("5-fokus-weg-pause.png")
closing = True
send(ids["toplevel"], 1)       # close (Super+Q)
pump(2.0)
rc = proc.wait(timeout=5)
err = proc.stderr.read().decode()
print("Rückgabewert:", rc, "| Fehlerausgabe:", err.strip() or "-")
print("Bilder gezeigt:", surface_state.get("shown", 0), "(Titel in 2 s:", n_titel, ")")
print("Titel gesetzt:", ids.get("title"), "| pong:", [x for x in log if x[0] == "pong"])
print("gespeichert:", frames_saved)
print("PROTOKOLLFEHLER:" if fehler else "Protokoll ok", fehler[:10])
