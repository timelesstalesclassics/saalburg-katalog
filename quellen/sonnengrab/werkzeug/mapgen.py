# Baut den Pyramidenplan von "Sonnengrab" und schreibt src/level.h
# Legende:
#  ' ' leer (Innenwand)   ',' leer (Nachthimmel)   '#' Stein   'Z' Sarkophag (fest)
#  '-' Sims (von unten durchspringbar)   'H' Leiter   '^' Stacheln   'T' Zeitstacheln
#  '!' Stacheln ab 2. Durchgang   'K' Schlüssel   'D' Tür   '$' Schatz   'S' Sprungfeder
#  'L' Laser nach rechts  'J' Laser nach links  'V' Laser nach unten
#  'b' Fledermaus  'f' Skarabäus  'm' Mumie   '*' Fackel   'I' Säule (Deko)   'P' Start
import sys, os

RW, RH, GX, GY = 30, 16, 5, 4
W, H = RW * GX, RH * GY
g = [['#'] * W for _ in range(H)]

def S(rx, ry, x, y, c):
    assert 0 <= x < RW and 0 <= y < RH, (rx, ry, x, y)
    g[ry * RH + y][rx * RW + x] = c

def fill(rx, ry, x0, y0, x1, y1, c):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            S(rx, ry, x, y, c)

def carve(rx, ry, x0, y0, x1, y1): fill(rx, ry, x0, y0, x1, y1, ' ')
def plat(rx, ry, x0, x1, y): fill(rx, ry, x0, y, x1, y, '-')
def ladder(rx, ry, x, y0, y1): fill(rx, ry, x, y0, x, y1, 'H')
def hexit(rx, ry, y=12):
    carve(rx, ry, 29, y, 29, y + 1); carve(rx + 1, ry, 0, y, 0, y + 1)
def vexit(rx, ry, x, y0, y1):
    """Leiter von Raum (rx,ry) Zeile y0 bis Raum (rx,ry+1) Zeile y1."""
    carve(rx, ry, x, 14, x + 1, 15); carve(rx, ry + 1, x, 0, x + 1, 0)
    gx = rx * RW + x
    for gy in range(ry * RH + y0, (ry + 1) * RH + y1 + 1):
        g[gy][gx] = 'H'
def room(rx, ry):
    carve(rx, ry, 1, 1, 28, 13)

# ---------------- Reihe 2: Basis der Pyramide ----------------
# (0,2) Eingang – draußen Nacht, Wüste
for r in range(0, 12):
    start = 16 - r
    fill(0, 2, 0, r, start - 1, r, ',')
    if r >= 2:
        carve(0, 2, start + 4, r, 28, r)
fill(0, 2, 0, 12, 6, 13, ',')
carve(0, 2, 7, 12, 28, 13)
ladder(0, 2, 22, 4, 13)
plat(0, 2, 18, 21, 4); plat(0, 2, 23, 27, 4)
S(0, 2, 26, 3, 'K')
plat(0, 2, 14, 19, 8)
S(0, 2, 12, 13, '#')            # erster Block zum Drüberspringen
S(0, 2, 18, 13, 'f')
S(0, 2, 2, 13, 'P')
for x, y in [(20, 2), (26, 6), (16, 6), (11, 11), (26, 11)]: S(0, 2, x, y, '*')
hexit(0, 2)

# (1,2) Säulenhalle
room(1, 2)
plat(1, 2, 2, 11, 10)
S(1, 2, 3, 9, 'K')
fill(1, 2, 14, 13, 15, 13, '^')
fill(1, 2, 28, 12, 28, 13, 'D')
plat(1, 2, 17, 26, 7)
S(1, 2, 18, 5, 'b')
for x in (10, 19, 25): fill(1, 2, x, 1, x, 6, 'I')
for x, y in [(4, 6), (13, 9), (24, 4), (20, 11)]: S(1, 2, x, y, '*')
hexit(1, 2)

# (2,2) Große Galerie
room(2, 2)
plat(2, 2, 1, 12, 10); plat(2, 2, 16, 28, 10)
S(2, 2, 1, 8, 'L')
S(2, 2, 27, 13, 'S')
plat(2, 2, 21, 28, 6)
S(2, 2, 26, 5, 'K')
S(2, 2, 20, 13, 'm')
for x, y in [(6, 7), (24, 3), (9, 12), (22, 8)]: S(2, 2, x, y, '*')
for x in (4, 25): fill(2, 2, x, 1, x, 5, 'I')
hexit(2, 2)

# (3,2) Kammer der Lanzen
room(3, 2)
fill(3, 2, 6, 13, 9, 13, 'T')
fill(3, 2, 14, 13, 16, 13, 'T')
plat(3, 2, 2, 4, 12); plat(3, 2, 6, 8, 10); plat(3, 2, 10, 14, 8)
S(3, 2, 12, 7, '$')
plat(3, 2, 21, 27, 4)
S(3, 2, 26, 3, 'K')
S(3, 2, 24, 7, 'b')
fill(3, 2, 28, 12, 28, 13, 'D')
S(3, 2, 24, 13, '!')
for x, y in [(4, 7), (12, 4), (17, 10), (25, 1)]: S(3, 2, x, y, '*')
hexit(3, 2)

# (4,2) Ostflügel
room(4, 2)
fill(4, 2, 8, 13, 9, 13, '^'); fill(4, 2, 18, 13, 19, 13, '^')
plat(4, 2, 22, 24, 12); plat(4, 2, 25, 27, 10); plat(4, 2, 22, 24, 8)
plat(4, 2, 25, 27, 6); plat(4, 2, 19, 23, 4)
S(4, 2, 20, 3, '$')
S(4, 2, 28, 7, 'J')
plat(4, 2, 5, 6, 12); plat(4, 2, 1, 4, 10)
S(4, 2, 2, 9, 'K')
S(4, 2, 13, 13, 'f')
S(4, 2, 11, 13, '!')
for x, y in [(3, 6), (12, 8), (21, 9), (26, 2)]: S(4, 2, x, y, '*')

# ---------------- Reihe 1 ----------------
# (1,1) Schreiberstube
room(1, 1)
for r in range(1, 7):
    fill(1, 1, 1, r, max(1, (7 - r) * 2 - 1), r, '#')
ladder(1, 1, 18, 4, 13)
plat(1, 1, 2, 17, 4); plat(1, 1, 19, 22, 4)
fill(1, 1, 1, 1, 12, 3, '#')
carve(1, 1, 2, 2, 12, 3)
S(1, 1, 3, 3, '$')
S(1, 1, 10, 7, 'b')
S(1, 1, 11, 13, '!')
for x, y in [(8, 2), (16, 9), (24, 6), (4, 11)]: S(1, 1, x, y, '*')
hexit(1, 1)

# (2,1) Halle der Götter
room(2, 1)
ladder(2, 1, 8, 5, 13)
plat(2, 1, 1, 7, 5); plat(2, 1, 9, 18, 5); plat(2, 1, 19, 19, 5)
fill(2, 1, 19, 1, 19, 2, '#')
fill(2, 1, 19, 3, 19, 4, 'D')
plat(2, 1, 20, 23, 5)
S(2, 1, 11, 1, 'V')
plat(2, 1, 21, 22, 12); plat(2, 1, 23, 28, 10)
S(2, 1, 26, 9, 'K')
S(2, 1, 24, 13, 'm')
for x, y in [(4, 3), (16, 9), (26, 6), (12, 11)]: S(2, 1, x, y, '*')
for x in (3, 25): fill(2, 1, x, 6, x, 9, 'I')
hexit(2, 1)

# (3,1) Lasergang
room(3, 1)
for r in range(1, 5):
    fill(3, 1, 30 - (7 - r) * 2, r, 28, r, '#')
S(3, 1, 8, 1, 'V'); S(3, 1, 12, 1, 'V'); S(3, 1, 16, 1, 'V')
ladder(3, 1, 24, 7, 13)
plat(3, 1, 25, 28, 7)
S(3, 1, 27, 6, '$')
S(3, 1, 14, 13, '!')
for x, y in [(4, 4), (10, 9), (22, 10), (26, 11)]: S(3, 1, x, y, '*')

# ---------------- Reihe 0: Spitze ----------------
# (2,0) Grabkammer des Sonnenkönigs
for r in range(2, 14):
    half = r + 1
    carve(2, 0, max(1, 15 - half), r, min(28, 14 + half), r)
fill(2, 0, 12, 12, 17, 13, 'Z')
S(2, 0, 14, 11, '$')
S(2, 0, 8, 9, 'b'); S(2, 0, 21, 7, 'b')
for x, y in [(11, 8), (18, 8), (5, 11), (24, 11)]: S(2, 0, x, y, '*')
for x in (9, 20): fill(2, 0, x, 10, x, 13, 'I')

# ---------------- Reihe 3: Krypta ----------------
# (0,3) Brunnenschacht
room(0, 3)
ladder(0, 3, 7, 6, 13)
plat(0, 3, 1, 6, 6)
S(0, 3, 3, 5, '$')
fill(0, 3, 10, 13, 12, 13, '^')
plat(0, 3, 15, 22, 10)
S(0, 3, 18, 13, 'f'); S(0, 3, 19, 9, 'f')
S(0, 3, 4, 13, '!')
for x, y in [(4, 2), (13, 7), (24, 7), (9, 11)]: S(0, 3, x, y, '*')
hexit(0, 3)

# (1,3) Gewölbe
room(1, 3)
fill(1, 3, 1, 12, 1, 13, 'D')
fill(1, 3, 8, 13, 10, 13, 'T')
plat(1, 3, 3, 7, 10)
S(1, 3, 5, 9, 'K')
S(1, 3, 16, 13, 'm')
plat(1, 3, 12, 18, 8)
for x, y in [(6, 6), (15, 5), (26, 9), (12, 11)]: S(1, 3, x, y, '*')
hexit(1, 3)

# (2,3) Schlangengrube
room(2, 3)
fill(2, 3, 9, 13, 21, 13, '^')
plat(2, 3, 8, 10, 11); plat(2, 3, 13, 18, 10); plat(2, 3, 21, 23, 11)
S(2, 3, 16, 9, '$')
S(2, 3, 1, 6, 'L')
fill(2, 3, 28, 12, 28, 13, 'D')
S(2, 3, 15, 4, 'b')
for x, y in [(7, 6), (16, 6), (25, 7), (3, 11)]: S(2, 3, x, y, '*')
hexit(2, 3)

# (3,3) Säulengruft
room(3, 3)
for x in (6, 12, 18, 24): fill(3, 3, x, 1, x, 13, 'I')
plat(3, 3, 9, 15, 9)
S(3, 3, 13, 8, 'K')
S(3, 3, 9, 6, 'b'); S(3, 3, 20, 10, 'b')
fill(3, 3, 16, 13, 16, 13, 'T')
fill(3, 3, 10, 12, 10, 13, '#')
S(3, 3, 21, 13, '!')
for x, y in [(3, 7), (15, 4), (21, 7), (27, 9)]: S(3, 3, x, y, '*')
hexit(3, 3)

# (4,3) Schatzkammer
room(4, 3)
S(4, 3, 4, 13, 'S')
plat(4, 3, 1, 9, 5)
S(4, 3, 7, 4, '$')
fill(4, 3, 18, 13, 22, 13, 'T')
S(4, 3, 20, 7, 'b')
S(4, 3, 26, 13, 'f')
for x, y in [(3, 2), (12, 8), (22, 4), (26, 10)]: S(4, 3, x, y, '*')

# ---------------- Verbindungen nach oben/unten ----------------
vexit(1, 1, 7, 14, 13)    # Schreiberstube -> Säulenhalle
vexit(2, 1, 14, 14, 13)   # Halle der Götter -> Große Galerie
vexit(3, 1, 20, 14, 13)   # Lasergang -> Kammer der Lanzen
vexit(2, 0, 20, 14, 4)    # Grabkammer -> Halle der Götter (Leiter bis aufs Sims)
vexit(1, 2, 22, 14, 13)   # Säulenhalle -> Gewölbe
vexit(2, 2, 4, 14, 13)    # Große Galerie -> Schlangengrube
vexit(4, 2, 14, 14, 13)   # Ostflügel -> Schatzkammer

ROOMS = [(2,0),(1,1),(2,1),(3,1),(0,2),(1,2),(2,2),(3,2),(4,2),(0,3),(1,3),(2,3),(3,3),(4,3)]

out = sys.argv[1] if len(sys.argv) > 1 else 'src/level.h'
with open(out, 'w') as f:
    f.write('/* automatisch erzeugt von tools/mapgen.py */\n')
    f.write(f'#define WORLD_W {W}\n#define WORLD_H {H}\n')
    f.write('static const char *WORLD_SRC[WORLD_H] = {\n')
    for row in g:
        f.write('  "' + ''.join(row) + '",\n')
    f.write('};\n')
    f.write('static const unsigned char ROOM_EXISTS[%d][%d] = {\n' % (GY, GX))
    for ry in range(GY):
        f.write('  {' + ','.join('1' if (rx, ry) in ROOMS else '0' for rx in range(GX)) + '},\n')
    f.write('};\n')
if '-v' in sys.argv:
    for ry in range(GY):
        for y in range(RH):
            print('|'.join(''.join(g[ry*RH+y][rx*RW:(rx+1)*RW]) for rx in range(GX)))
        print('-' * (W + GX))
