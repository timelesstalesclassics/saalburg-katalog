#!/usr/bin/env python3
"""Einen Befehl weiter einsperren (Landlock, ohne root), dann ausführen.

Der VM-Läufer startet die Tests eines Auftrags damit: Die Test-Skripte kommen aus dem
Repo, das getestet wird, und laufen mit derselben Kennung wie die App. Landlock sorgt dafür,
dass sie trotzdem nicht an die Tokens der App (/daten/system/laeufer/…), ihr Tagebuch
und ihre übrigen Dateien kommen und dem Läufer selbst weder Signale schicken noch seinen
Speicher lesen können (ein eingesperrter Prozess darf Prozesse außerhalb seines
Bereichs nicht „ptracen“, also auch /proc/<pid>/mem und environ nicht lesen).

  einsperren.py --lesen PFAD … --schreiben PFAD … --geraet PFAD … -- befehl …

--lesen:     lesen und ausführen (System, Abbilder)
--schreiben: alles außer Geräteknoten anlegen (Arbeitsordner, /tmp)
--geraet:    eine Gerätedatei öffnen, lesen, schreiben, ioctl (/dev/kvm, /dev/null …)
Fehlt Landlock (Kernel zu alt), bricht es ab (Rückgabe 125) – lieber kein Test als einer
mit Zugriff auf die Tokens.
"""
import ctypes
import os
import sys

SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446
PR_SET_NO_NEW_PRIVS = 38

EXECUTE = 1 << 0
WRITE_FILE = 1 << 1
READ_FILE = 1 << 2
READ_DIR = 1 << 3
REMOVE_DIR = 1 << 4
REMOVE_FILE = 1 << 5
MAKE_CHAR = 1 << 6
MAKE_DIR = 1 << 7
MAKE_REG = 1 << 8
MAKE_SOCK = 1 << 9
MAKE_FIFO = 1 << 10
MAKE_BLOCK = 1 << 11
MAKE_SYM = 1 << 12
REFER = 1 << 13
TRUNCATE = 1 << 14
IOCTL_DEV = 1 << 15
DATEI_RECHTE = EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE | IOCTL_DEV


def _libc():
    for name in (None, "libc.musl-x86_64.so.1", "libc.so.6"):
        try:
            lib = ctypes.CDLL(name, use_errno=True)
            lib.syscall  # noqa: B018
            return lib
        except (OSError, AttributeError):
            continue
    raise OSError("libc nicht gefunden")


def abi():
    """Landlock-ABI des Kernels (0: keins)"""
    lib = _libc()
    lib.syscall.restype = ctypes.c_long
    r = lib.syscall(SYS_CREATE, None, ctypes.c_size_t(0), ctypes.c_uint32(1))
    return max(0, r)


def einsperren(lesen=(), schreiben=(), geraete=()):
    """Den eigenen Prozess (und alles, was er startet) einsperren. OSError, wenn es nicht geht."""
    lib = _libc()
    lib.syscall.restype = ctypes.c_long
    v = abi()
    if v < 1:
        raise OSError("Landlock fehlt im Kernel")
    alles = (REFER << 1) - 1 - REFER  # ABI 1: bis MAKE_SYM
    if v >= 2:
        alles |= REFER
    if v >= 3:
        alles |= TRUNCATE
    if v >= 5:
        alles |= IOCTL_DEV
    attr = (ctypes.c_uint64 * 3)(alles, 0, 0)
    groesse = 8
    if v >= 4:
        groesse = 16
    if v >= 6:
        attr[2] = 1 | 2  # abstrakte Unix-Sockets und Signale nur innerhalb
        groesse = 24
    rs = lib.syscall(SYS_CREATE, ctypes.byref(attr), ctypes.c_size_t(groesse), ctypes.c_uint32(0))
    if rs < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")

    class Regel(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("erlaubt", ctypes.c_uint64), ("fd", ctypes.c_int32)]

    def regel(pfad, rechte):
        try:
            fd = os.open(pfad, os.O_PATH | os.O_CLOEXEC)
        except OSError:
            return  # gibt es nicht: nichts freizugeben
        try:
            r = rechte & alles
            if not os.path.isdir(pfad):
                r &= DATEI_RECHTE
            reg = Regel(r, fd)
            if lib.syscall(SYS_ADD, ctypes.c_int(rs), ctypes.c_int(1), ctypes.byref(reg), ctypes.c_uint32(0)) < 0:
                raise OSError(ctypes.get_errno(), f"landlock_add_rule {pfad}")
        finally:
            os.close(fd)

    try:
        for p in lesen:
            regel(p, EXECUTE | READ_FILE | READ_DIR)
        for p in schreiben:
            regel(p, alles & ~(MAKE_CHAR | MAKE_BLOCK | IOCTL_DEV))
        for p in geraete:
            regel(p, READ_FILE | WRITE_FILE | IOCTL_DEV)
        if lib.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "no_new_privs")
        if lib.syscall(SYS_RESTRICT, ctypes.c_int(rs), ctypes.c_uint32(0)) < 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    finally:
        os.close(rs)


def main(argv):
    lesen, schreiben, geraete = [], [], []
    ziel = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            ziel = argv[i + 1:]
            break
        if a in ("--lesen", "--schreiben", "--geraet") and i + 1 < len(argv):
            {"--lesen": lesen, "--schreiben": schreiben, "--geraet": geraete}[a].append(argv[i + 1])
            i += 2
            continue
        print(f"einsperren.py: unbekannt: {a}", file=sys.stderr)
        return 2
    if not ziel:
        print("einsperren.py: Befehl fehlt (nach --)", file=sys.stderr)
        return 2
    try:
        einsperren(lesen, schreiben, geraete)
    except OSError as fehler:
        print(f"einsperren.py: Landlock geht nicht ({fehler}) – kein Test", file=sys.stderr)
        return 125
    os.execvp(ziel[0], ziel)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
