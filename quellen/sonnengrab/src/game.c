/* SONNENGRAB – Das Grab des Sonnenkönigs
 * Ein Plattformspiel im Geiste der 8-Bit-Pyramidenklassiker.
 * Plattformunabhängiger Kern: Spiellogik, Software-Renderer mit dynamischem Licht, Audio.
 */
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include "game.h"
#include "level.h"
#include "sprites.h"
#include "audio.c"

#define TS 16
#define RW 30
#define RH 16
#define VW 480
#define VH 256
#define GX 5
#define GY 4
#define PW 10
#define PH 22

/* Physik */
#define WALK 1.35f
#define RUN 2.25f
#define GRAV 0.28f
#define MAXFALL 6.0f
#define JUMP_HIGH (-5.0f)
#define JUMP_LOW (-3.0f)
#define LOWVX 2.6f
#define SPRING_V (-9.0f)
#define CLIMB 1.25f
#define AIRACC 0.06f

static float clampf(float v, float a, float b) { return v < a ? a : (v > b ? b : v); }
static float lerpf(float a, float b, float t) { return a + (b - a) * t; }
static float smooth(float a, float b, float x) { float t = clampf((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }

static unsigned int hash2(int x, int y) {
    unsigned int h = (unsigned int)x * 374761393u + (unsigned int)y * 668265263u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return h ^ (h >> 16);
}
static float h01(int x, int y) { return (hash2(x, y) & 0xffffff) / 16777216.0f; }
static float vnoise(float x, float y) {
    int ix = (int)floorf(x), iy = (int)floorf(y);
    float fx = x - ix, fy = y - iy;
    fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
    float a = h01(ix, iy), b = h01(ix + 1, iy), c = h01(ix, iy + 1), d = h01(ix + 1, iy + 1);
    return lerpf(lerpf(a, b, fx), lerpf(c, d, fx), fy);
}
static float fbm(float x, float y) { return vnoise(x, y) * 0.55f + vnoise(x * 2.1f + 13, y * 2.1f + 7) * 0.3f + vnoise(x * 4.3f + 3, y * 4.3f + 31) * 0.15f; }
static unsigned int grng = 12345u;
static float frnd(void) { grng = grng * 1664525u + 1013904223u; return (grng >> 8) / 16777216.0f; }
static float frnds(void) { return frnd() * 2 - 1; }

/* ======================================================================= */
/*                                 Welt                                    */
/* ======================================================================= */
static char world[WORLD_H][WORLD_W + 1];
static int round_no = 1;

static const char *ROOM_NAME[GY][GX] = {
    { 0, 0, "GRABKAMMER DES SONNENKÖNIGS", 0, 0 },
    { 0, "SCHREIBERSTUBE", "HALLE DER GÖTTER", "GANG DER STRAHLEN", 0 },
    { "EINGANG", "SÄULENHALLE", "GROSSE GALERIE", "KAMMER DER LANZEN", "OSTFLÜGEL" },
    { "BRUNNENSCHACHT", "GEWÖLBE", "SCHLANGENGRUBE", "SÄULENGRUFT", "SCHATZKAMMER" },
};

enum { EN_BAT = 1, EN_SCARAB, EN_MUMMY };
typedef struct { int type; float x, y, vx, vy, hy; int w, h; float t, anim; int room; } Enemy;
typedef struct { int type; int tx, ty, taken, room; } Item; /* type 0 Schlüssel, 1 Schatz */
typedef struct { int tx, ty, room; float comp; } Spring;
typedef struct { int tx, ty, room, dir, len, off, was_on; } Laser;
typedef struct { int tx, ty, room; float seed; } Torch;
typedef struct { int tx, ty, h, room, open; float anim; } Door;

#define MAXEN 64
static Enemy enemies[MAXEN]; static int n_enemies;
static Item items[64]; static int n_items, n_treasures_total;
static Spring springs[32]; static int n_springs;
static Laser lasers[32]; static int n_lasers;
static Torch torches[128]; static int n_torches;
static Door doors[32]; static int n_doors;
static float start_x, start_y;

static char tile(int tx, int ty) {
    if (tx < 0 || ty < 0 || tx >= WORLD_W || ty >= WORLD_H) return '#';
    return world[ty][tx];
}
static int room_of_tile(int tx, int ty) { return (ty / RH) * GX + tx / RW; }
static int room_exists(int rx, int ry) { return rx >= 0 && ry >= 0 && rx < GX && ry < GY && ROOM_EXISTS[ry][rx]; }
static int is_solid_c(char c) { return c == '#' || c == 'Z' || c == 'D' || c == 'L' || c == 'J' || c == 'V'; }
static int is_solid(int tx, int ty) { return is_solid_c(tile(tx, ty)); }
static int is_ladder(int tx, int ty) { return tile(tx, ty) == 'H'; }
static int is_oneway(int tx, int ty) {
    char c = tile(tx, ty);
    if (c == '-') return 1;
    if (c == 'H' && tile(tx, ty - 1) != 'H' && !is_solid(tx, ty - 1)) return 1;
    return 0;
}
static int is_spike_static(int tx, int ty) {
    char c = tile(tx, ty);
    return c == '^' || (c == '!' && round_no >= 2);
}

static void world_load(void) {
    n_enemies = n_items = n_springs = n_lasers = n_torches = n_doors = 0;
    n_treasures_total = 0;
    for (int y = 0; y < WORLD_H; y++) {
        for (int x = 0; x < WORLD_W; x++) {
            char c = WORLD_SRC[y][x];
            int room = room_of_tile(x, y);
            if (c == 'b' || c == 'f' || c == 'm') {
                Enemy *e = &enemies[n_enemies++];
                memset(e, 0, sizeof(*e));
                e->room = room; e->t = x * 0.7f;
                if (c == 'b') { e->type = EN_BAT; e->w = 12; e->h = 7; e->x = x * TS + 2; e->y = y * TS + 4; e->hy = e->y; e->vx = 1.0f; }
                if (c == 'f') { e->type = EN_SCARAB; e->w = 10; e->h = 7; e->x = x * TS + 3; e->y = y * TS + 9; e->vx = 1.5f; }
                if (c == 'm') { e->type = EN_MUMMY; e->w = 10; e->h = 22; e->x = x * TS + 3; e->y = y * TS + 16 - 22; e->vx = -0.45f; }
                c = ' ';
            } else if (c == 'K' || c == '$') {
                Item *it = &items[n_items++];
                it->type = c == '$'; it->tx = x; it->ty = y; it->taken = 0; it->room = room;
                if (c == '$') n_treasures_total++;
                c = ' ';
            } else if (c == 'P') {
                start_x = x * TS + 3; start_y = (y + 1) * TS - PH;
                c = (x > 0 && WORLD_SRC[y][x - 1] == ',') ? ',' : ' ';
            } else if (c == 'S') {
                Spring *s = &springs[n_springs++]; s->tx = x; s->ty = y; s->room = room; s->comp = 0;
            } else if (c == 'L' || c == 'J' || c == 'V') {
                Laser *l = &lasers[n_lasers++];
                l->tx = x; l->ty = y; l->room = room; l->dir = c == 'L' ? 0 : c == 'J' ? 1 : 2;
                l->off = (x * 37 + y * 91) % 240; l->was_on = 0; l->len = 0;
            } else if (c == '*') {
                Torch *t = &torches[n_torches++]; t->tx = x; t->ty = y; t->room = room; t->seed = h01(x, y) * 100;
            } else if (c == 'D') {
                if (y == 0 || WORLD_SRC[y - 1][x] != 'D') {
                    Door *d = &doors[n_doors++];
                    d->tx = x; d->ty = y; d->room = room; d->open = 0; d->anim = 0; d->h = 0;
                    while (y + d->h < WORLD_H && WORLD_SRC[y + d->h][x] == 'D') d->h++;
                }
            }
            world[y][x] = c;
        }
        world[y][WORLD_W] = 0;
    }
}

static void laser_measure(Laser *l) {
    int dx = l->dir == 0 ? 1 : l->dir == 1 ? -1 : 0, dy = l->dir == 2 ? 1 : 0;
    int tx = l->tx + dx, ty = l->ty + dy, n = 0;
    int r = l->room, rx = r % GX, ry = r / GX;
    while (!is_solid(tx, ty) && tile(tx, ty) != '-' && tx >= rx * RW && tx < (rx + 1) * RW && ty >= ry * RH && ty < (ry + 1) * RH && n < 40) {
        tx += dx; ty += dy; n++;
    }
    l->len = n * TS;
}

/* ======================================================================= */
/*                          Spieler & Spielzustand                         */
/* ======================================================================= */
enum { PS_GROUND, PS_AIR, PS_CLIMB };
typedef struct {
    float x, y, vx, vy;
    int st, facing, coyote, jumpbuf, ljbuf;
    float anim, stepacc;
    int invuln, dead, deadt;
} Player;
typedef struct { int dir, up, down, run, jumpP, ljumpP, downP, upP; } PIn;
enum { EV_JUMP = 1, EV_LJUMP = 2, EV_LAND = 4, EV_SPRING = 8, EV_LOCKED = 16, EV_DOOR = 32 };

static Player pl;
static int sim_mode = 0, sim_door = -1;
static int keys_held = 0, lives = 5, treasures_got = 0, score = 0;
static unsigned int gframe = 0;
static int cur_room = -1;
static float cp_x, cp_y; static int cp_pending = 0;

static int door_at(int tx, int ty) {
    for (int i = 0; i < n_doors; i++)
        if (doors[i].tx == tx && ty >= doors[i].ty && ty < doors[i].ty + doors[i].h) return i;
    return -1;
}
static void lights_dirty(void);
static int door_touch(int tx, int ty, int *ev) {
    if (tile(tx, ty) != 'D') return 0;
    int d = door_at(tx, ty);
    if (d < 0) return 0;
    if (sim_mode) { sim_door = d; return 0; }
    if (keys_held <= 0) { *ev |= EV_LOCKED; return 0; }
    keys_held--;
    doors[d].open = 1; doors[d].anim = 0;
    for (int i = 0; i < doors[d].h; i++) world[doors[d].ty + i][doors[d].tx] = ' ';
    for (int i = 0; i < n_lasers; i++) laser_measure(&lasers[i]);
    lights_dirty();
    score += 50;
    *ev |= EV_DOOR;
    return 1;
}

static void move_x(Player *p, float dx, int *ev) {
    if (dx == 0) return;
    p->x += dx;
    int top = (int)floorf(p->y / TS), bot = (int)floorf((p->y + PH - 1) / TS);
    if (dx > 0) {
        int tx = (int)floorf((p->x + PW - 1) / TS);
        for (int ty = top; ty <= bot; ty++)
            if (is_solid(tx, ty) && !door_touch(tx, ty, ev)) { p->x = tx * TS - PW; p->vx = 0; break; }
    } else {
        int tx = (int)floorf(p->x / TS);
        for (int ty = top; ty <= bot; ty++)
            if (is_solid(tx, ty) && !door_touch(tx, ty, ev)) { p->x = (tx + 1) * TS; p->vx = 0; break; }
    }
}
static int move_y(Player *p, float dy, int oneway) {
    float oldbot = p->y + PH;
    p->y += dy;
    int l = (int)floorf(p->x / TS), r = (int)floorf((p->x + PW - 1) / TS);
    if (dy > 0) {
        int ty = (int)floorf((p->y + PH - 0.01f) / TS);
        for (int tx = l; tx <= r; tx++) {
            if (is_solid(tx, ty) || (oneway && is_oneway(tx, ty) && oldbot <= ty * TS + 0.01f)) {
                p->y = ty * TS - PH; p->vy = 0; return 1;
            }
        }
    } else if (dy < 0) {
        int ty = (int)floorf(p->y / TS);
        for (int tx = l; tx <= r; tx++)
            if (is_solid(tx, ty)) { p->y = (ty + 1) * TS; p->vy = 0; return 0; }
    }
    return 0;
}
static int spring_at(int tx, int ty) {
    for (int i = 0; i < n_springs; i++) if (springs[i].tx == tx && springs[i].ty == ty) return i;
    return -1;
}

static int player_step(Player *p, const PIn *in) {
    int ev = 0;
    float cx = p->x + PW * 0.5f;
    int ltx = (int)floorf(cx / TS);
    float spd = in->run ? RUN : WALK;
    if (in->jumpP) p->jumpbuf = 6; else if (p->jumpbuf > 0) p->jumpbuf--;
    if (in->ljumpP) p->ljbuf = 6; else if (p->ljbuf > 0) p->ljbuf--;

    if (p->st == PS_CLIMB) {
        if (in->dir && !in->up && !in->down) {
            p->st = PS_AIR; p->facing = in->dir; p->vx = in->dir * WALK; p->vy = 0;
            if (p->jumpbuf) { p->vy = JUMP_HIGH * 0.85f; p->jumpbuf = 0; ev |= EV_JUMP; }
            move_x(p, p->vx, &ev);
            return ev;
        }
        float dy = in->up ? -CLIMB : (in->down ? CLIMB : 0);
        if (dy < 0) {
            p->y += dy;
            int hty = (int)floorf(p->y / TS);
            if (is_solid(ltx, hty)) p->y = (hty + 1) * TS;
            int fty = (int)floorf((p->y + PH - 1) / TS);
            if (!is_ladder(ltx, fty)) { p->y = (fty + 1) * TS - PH; p->st = PS_GROUND; p->vy = 0; }
        } else if (dy > 0) {
            if (move_y(p, dy, 0)) p->st = PS_GROUND;
            else {
                int fty = (int)floorf((p->y + PH - 1) / TS), mty = (int)floorf((p->y + PH * 0.5f) / TS);
                if (!is_ladder(ltx, fty) && !is_ladder(ltx, mty)) { p->st = PS_AIR; p->vx = 0; }
            }
        }
        p->anim += fabsf(dy) * 0.12f;
        return ev;
    }

    int dir = in->dir;
    if (dir) p->facing = dir;
    /* Leiter greifen */
    float lad_dx = cx - (ltx * TS + 8);
    if (in->up && fabsf(lad_dx) < 6.5f &&
        (is_ladder(ltx, (int)floorf((p->y + PH - 2) / TS)) || is_ladder(ltx, (int)floorf((p->y + 4) / TS)))) {
        p->st = PS_CLIMB; p->x = ltx * TS + 8 - PW * 0.5f; p->vx = p->vy = 0; p->jumpbuf = 0;
        return ev;
    }
    if (in->down && p->st == PS_GROUND && fabsf(lad_dx) < 6.5f && is_ladder(ltx, (int)floorf((p->y + PH + 1) / TS)) && !dir) {
        p->st = PS_CLIMB; p->x = ltx * TS + 8 - PW * 0.5f; p->vx = p->vy = 0; p->y += 2;
        return ev;
    }
    int grounded = p->st == PS_GROUND || p->coyote > 0;
    if (p->st == PS_GROUND) {
        float target = dir * spd;
        p->vx += clampf(target - p->vx, -0.45f, 0.45f);
    } else if (dir) {
        p->vx += dir * AIRACC;
        if (p->vx > RUN) p->vx = RUN;
        if (p->vx < -RUN) p->vx = -RUN;
    }
    if (p->jumpbuf && grounded) {
        p->vy = JUMP_HIGH; p->st = PS_AIR; p->coyote = 0; p->jumpbuf = 0; p->ljbuf = 0;
        p->vx = dir * spd; ev |= EV_JUMP;
    } else if (p->ljbuf && grounded) {
        int d = dir ? dir : p->facing;
        p->vy = JUMP_LOW; p->st = PS_AIR; p->coyote = 0; p->ljbuf = 0; p->jumpbuf = 0;
        p->vx = d * LOWVX; ev |= EV_LJUMP;
    }
    p->vy += GRAV; if (p->vy > MAXFALL) p->vy = MAXFALL;
    move_x(p, p->vx, &ev);
    int was_air = p->st == PS_AIR;
    int landed = move_y(p, p->vy, 1);
    if (landed) {
        if (was_air) ev |= EV_LAND;
        p->st = PS_GROUND; p->coyote = 0;
        int ft = (int)floorf((p->y + PH - 1) / TS);
        int si = spring_at((int)floorf((p->x + PW * 0.5f) / TS), ft);
        if (si >= 0) {
            p->vy = SPRING_V; p->st = PS_AIR; ev |= EV_SPRING;
            if (!sim_mode) springs[si].comp = 1;
        }
    } else {
        if (p->st == PS_GROUND) { p->st = PS_AIR; p->coyote = 6; }
        else if (p->coyote > 0) p->coyote--;
    }
    if (p->st == PS_GROUND) p->anim += fabsf(p->vx) * 0.09f;
    return ev;
}

static int rect_hit(float ax, float ay, float aw, float ah, float bx, float by, float bw, float bh) {
    return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}
static int hazard_static(const Player *p) {
    float hx = p->x + 1.5f, hy = p->y + 3, hw = PW - 3, hh = PH - 4;
    int l = (int)floorf(hx / TS), r = (int)floorf((hx + hw) / TS);
    int t = (int)floorf(hy / TS), b = (int)floorf((hy + hh) / TS);
    for (int ty = t; ty <= b; ty++)
        for (int tx = l; tx <= r; tx++)
            if (is_spike_static(tx, ty) && rect_hit(hx, hy, hw, hh, tx * TS + 2, ty * TS + 7, 12, 9)) return 1;
    return 0;
}
static float tspike_ext(int tx, unsigned int frame) {
    int ph = (int)((frame + (unsigned)((tx / 4) * 47)) % 160);
    if (ph < 60) return 0;
    if (ph < 70) return (ph - 60) / 10.0f;
    if (ph < 120) return 1;
    if (ph < 136) return 1 - (ph - 120) / 16.0f;
    return 0;
}
static int laser_phase(const Laser *l, unsigned int frame) { return (int)((frame + l->off) % 240); }
static int laser_on(const Laser *l, unsigned int frame) { return laser_phase(l, frame) < 90; }
static int laser_warn(const Laser *l, unsigned int frame) { return laser_phase(l, frame) >= 200; }
static void laser_rect(const Laser *l, float *x, float *y, float *w, float *h) {
    if (l->dir == 0) { *x = (l->tx + 1) * TS; *y = l->ty * TS + 6; *w = l->len; *h = 4; }
    else if (l->dir == 1) { *x = l->tx * TS - l->len; *y = l->ty * TS + 6; *w = l->len; *h = 4; }
    else { *x = l->tx * TS + 6; *y = (l->ty + 1) * TS; *w = 4; *h = l->len; }
}
static int hazard_dynamic(const Player *p) {
    float hx = p->x + 1.5f, hy = p->y + 3, hw = PW - 3, hh = PH - 4;
    int l = (int)floorf(hx / TS), r = (int)floorf((hx + hw) / TS);
    int t = (int)floorf(hy / TS), b = (int)floorf((hy + hh) / TS);
    for (int ty = t; ty <= b; ty++)
        for (int tx = l; tx <= r; tx++)
            if (tile(tx, ty) == 'T') {
                float e = tspike_ext(tx, gframe);
                if (e > 0.45f && rect_hit(hx, hy, hw, hh, tx * TS + 2, ty * TS + 16 - 10 * e, 12, 10 * e)) return 1;
            }
    for (int i = 0; i < n_lasers; i++) {
        Laser *L = &lasers[i];
        if (L->room != cur_room || !laser_on(L, gframe)) continue;
        float x, y, w, h; laser_rect(L, &x, &y, &w, &h);
        if (rect_hit(hx, hy, hw, hh, x, y, w, h)) return 1;
    }
    for (int i = 0; i < n_enemies; i++) {
        Enemy *e = &enemies[i];
        if (e->room != cur_room) continue;
        if (rect_hit(hx, hy, hw, hh, e->x + 1, e->y + 1, e->w - 2, e->h - 2)) return 1;
    }
    return 0;
}

/* ======================================================================= */
/*                                Partikel                                 */
/* ======================================================================= */
enum { PT_DUST, PT_SPARK, PT_SAND, PT_PUFF, PT_GLINT, PT_BURST, PT_BIT };
typedef struct { float x, y, vx, vy, life, max, r, g, b, size; int kind; } Part;
#define MAXP 1400
static Part parts[MAXP]; static int n_parts;
static Part *part_new(int kind, float x, float y) {
    if (n_parts >= MAXP) return 0;
    Part *p = &parts[n_parts++];
    memset(p, 0, sizeof(*p));
    p->kind = kind; p->x = x; p->y = y; p->size = 1;
    return p;
}
static void puff(float x, float y, int n) {
    for (int i = 0; i < n; i++) {
        Part *p = part_new(PT_PUFF, x + frnds() * 4, y);
        if (!p) return;
        p->vx = frnds() * 0.6f; p->vy = -frnd() * 0.35f; p->max = p->life = 25 + frnd() * 20;
        p->r = 0.55f; p->g = 0.42f; p->b = 0.28f; p->size = 1 + frnd() * 1.5f;
    }
}
static void burst(float x, float y, float r, float g, float b, int n, float sp) {
    for (int i = 0; i < n; i++) {
        Part *p = part_new(PT_BURST, x, y);
        if (!p) return;
        float a = frnd() * 6.283f, s = sp * (0.3f + frnd());
        p->vx = cosf(a) * s; p->vy = sinf(a) * s - 0.5f; p->max = p->life = 30 + frnd() * 40;
        p->r = r; p->g = g; p->b = b;
    }
}

/* ======================================================================= */
/*                              Renderpuffer                               */
/* ======================================================================= */
#define NPIX (VW * VH)
static float s_alb[NPIX * 3], s_nrm[NPIX * 2], s_emi[NPIX * 3];
static float f_alb[NPIX * 3], f_nrm[NPIX * 2], f_emi[NPIX * 3], f_lit[NPIX * 3], f_col[NPIX * 3];
#define BW (VW / 4)
#define BH (VH / 4)
static float bl_a[BW * BH * 3], bl_b[BW * BH * 3];
static unsigned char lut_srgb[4097];
static int room_ox, room_oy;      /* Pixelursprung des aktuellen Raums */
static int room_exterior = 0;
static int static_round = -1;

/* ---- Lichter ---- */
enum { LK_TORCH, LK_MOON, LK_ITEM, LK_LASER, LK_EMIT, LK_PLAYER, LK_DOORSEAL };
typedef struct { int kind, ref; float x, y, r, g, b, rad, h; float vis[17][31]; } Light;
#define MAXL 48
static Light slights[MAXL]; static int n_slights;
static Light plight;
static int lights_need_rebuild = 0;
static void lights_dirty(void) { lights_need_rebuild = 1; }

static int occludes(int lx, int ly) {
    int tx = (int)floorf((float)lx / TS) + room_ox / TS, ty = (int)floorf((float)ly / TS) + room_oy / TS;
    char c = tile(tx, ty);
    return is_solid_c(c);
}
static void compute_vis(Light *L) {
    int stx = (int)floorf(L->x / TS), sty = (int)floorf(L->y / TS);
    for (int j = 0; j <= RH; j++)
        for (int i = 0; i <= RW; i++) {
            float px = i * TS, py = j * TS;
            float dx = px - L->x, dy = py - L->y, d = sqrtf(dx * dx + dy * dy);
            float v = 1;
            if (d > L->rad + 24) { L->vis[j][i] = 0; continue; }
            int steps = (int)(d / 3.0f);
            for (int s = 1; s < steps; s++) {
                float t = (float)s / steps;
                float sx = L->x + dx * t, sy = L->y + dy * t;
                if (d * (1 - t) < 4.0f) break;
                int tx = (int)floorf(sx / TS), ty = (int)floorf(sy / TS);
                if (tx == stx && ty == sty) continue;
                if (occludes((int)sx, (int)sy)) { v = 0; break; }
            }
            L->vis[j][i] = v;
        }
}
static Light *slight_add(int kind, int ref, float x, float y, float r, float g, float b, float rad, float h) {
    if (n_slights >= MAXL) return 0;
    Light *L = &slights[n_slights++];
    L->kind = kind; L->ref = ref; L->x = x; L->y = y; L->r = r; L->g = g; L->b = b; L->rad = rad; L->h = h;
    return L;
}
static void build_lights(void) {
    n_slights = 0;
    for (int i = 0; i < n_torches; i++) {
        Torch *t = &torches[i];
        if (t->room != cur_room) continue;
        slight_add(LK_TORCH, i, t->tx * TS - room_ox + 8, t->ty * TS - room_oy + 4, 1.0f, 0.55f, 0.22f, 135, 22);
    }
    if (room_exterior) slight_add(LK_MOON, 0, 56, 26, 0.30f, 0.40f, 0.75f, 900, 260);
    for (int i = 0; i < n_items; i++) {
        Item *it = &items[i];
        if (it->room != cur_room) continue;
        if (it->type) slight_add(LK_ITEM, i, it->tx * TS - room_ox + 8, it->ty * TS - room_oy + 8, 1.0f, 0.62f, 0.25f, 70, 14);
        else slight_add(LK_ITEM, i, it->tx * TS - room_ox + 8, it->ty * TS - room_oy + 8, 0.9f, 0.7f, 0.3f, 40, 12);
    }
    for (int i = 0; i < n_lasers; i++) {
        Laser *l = &lasers[i];
        if (l->room != cur_room) continue;
        float ex = l->tx * TS - room_ox + 8, ey = l->ty * TS - room_oy + 8;
        slight_add(LK_EMIT, i, ex, ey, 1.0f, 0.15f, 0.08f, 40, 12);
        int segs = l->len / 48 + 1;
        for (int s = 0; s < segs; s++) {
            float t = (s + 0.5f) / segs * l->len;
            float lx = ex + (l->dir == 0 ? 8 + t : l->dir == 1 ? -8 - t : 0);
            float ly = ey + (l->dir == 2 ? 8 + t : 0);
            slight_add(LK_LASER, i, lx, ly, 1.0f, 0.12f, 0.06f, 70, 10);
        }
    }
    for (int i = 0; i < n_doors; i++) {
        Door *d = &doors[i];
        if (d->room != cur_room || d->open) continue;
        slight_add(LK_DOORSEAL, i, d->tx * TS - room_ox + 8, d->ty * TS - room_oy + d->h * 8, 0.9f, 0.6f, 0.2f, 34, 10);
    }
    for (int i = 0; i < n_slights; i++) compute_vis(&slights[i]);
    lights_need_rebuild = 0;
}

/* ---- statische Raumgrafik ---- */
static int tile_depth(int tx, int ty) {
    if (!is_solid(tx, ty)) return -1;
    for (int r = 1; r <= 3; r++)
        for (int dy = -r; dy <= r; dy++)
            for (int dx = -r; dx <= r; dx++) {
                if (abs(dx) != r && abs(dy) != r) continue;
                if (!is_solid(tx + dx, ty + dy) && tile(tx + dx, ty + dy) != ',') return r - 1;
                if (tile(tx + dx, ty + dy) == ',') return r - 1;
            }
    return 3;
}
static int glyph_px(int g, int x, int y) {
    if (x < 0 || y < 0 || x >= 7 || y >= 9) return 0;
    return GLYPHS[g][y][x] == '#';
}

static void paint_wall(int gx, int gy, float *a, float *n) {
    int by = gy / 16, off = (by & 1) ? 16 : 0;
    int bx = (gx + off) / 32, lx = (gx + off) % 32, ly = gy % 16;
    float r = h01(bx * 3 + 7, by * 5 + 1);
    float nz = fbm(gx * 0.18f, gy * 0.18f);
    float k = (0.7f + 0.5f * r) * (0.78f + 0.44f * nz);
    a[0] = 0.088f * k; a[1] = 0.066f * k; a[2] = 0.050f * k;
    n[0] = n[1] = 0;
    if (lx == 0 || ly == 0) { a[0] *= 0.35f; a[1] *= 0.35f; a[2] *= 0.35f; return; }
    if (lx == 1) n[0] = -0.45f; else if (lx == 31) n[0] = 0.45f;
    if (ly == 1) n[1] = -0.45f; else if (ly == 15) n[1] = 0.45f;
    /* Reliefs */
    float hr = h01(bx * 11 + 5, by * 7 + 3);
    if (hr < 0.24f) {
        int g1 = hash2(bx, by) % 7, g2 = hash2(bx + 9, by) % 7, g3 = hash2(bx, by + 4) % 7;
        int gl = -1, gxl = 0;
        if (lx >= 3 && lx < 10) { gl = g1; gxl = lx - 3; }
        else if (lx >= 13 && lx < 20) { gl = g2; gxl = lx - 13; }
        else if (lx >= 23 && lx < 30) { gl = g3; gxl = lx - 23; }
        if (gl >= 0) {
            int gyl = ly - 4;
            if (glyph_px(gl, gxl, gyl)) {
                a[0] *= 0.42f; a[1] *= 0.42f; a[2] *= 0.42f;
                if (hr < 0.10f) { /* Farbreste */
                    int blue = hash2(bx, by * 3) & 1;
                    if (blue) { a[0] = 0.02f; a[1] = 0.05f; a[2] = 0.13f; }
                    else { a[0] = 0.16f; a[1] = 0.045f; a[2] = 0.02f; }
                }
                n[1] = 0.3f;
            } else if (glyph_px(gl, gxl, gyl + 1)) {
                n[1] = -0.55f; a[0] *= 1.15f; a[1] *= 1.15f; a[2] *= 1.15f;
            }
        }
    }
}
static void paint_stone(int gx, int gy, int depth, int topopen, float *a, float *n) {
    int by = gy / 8, off = (by & 1) ? 8 : 0;
    int bx = (gx + off) / 16, lx = (gx + off) % 16, ly = gy % 8;
    float r = h01(bx * 5 + 1, by * 3 + 2);
    float nz = fbm(gx * 0.25f, gy * 0.25f);
    float k = (0.78f + 0.36f * r) * (0.8f + 0.4f * nz);
    a[0] = 0.50f * k; a[1] = 0.32f * k; a[2] = 0.15f * k;
    n[0] = n[1] = 0;
    if (lx == 0 || ly == 0) { k = 0.32f; a[0] *= k; a[1] *= k; a[2] *= k; }
    else {
        if (lx == 1) n[0] = -0.55f; else if (lx == 15) n[0] = 0.55f;
        if (ly == 1) n[1] = -0.55f; else if (ly == 7) n[1] = 0.55f;
        if (r > 0.82f) { /* Risse */
            float cr = fabsf(sinf((lx + ly * 0.8f) * 0.9f + r * 40) * 3 - (ly - 4));
            if (cr < 0.6f) { a[0] *= 0.4f; a[1] *= 0.4f; a[2] *= 0.4f; }
        }
    }
    float dk = depth <= 0 ? 1.0f : depth == 1 ? 0.5f : depth == 2 ? 0.26f : 0.14f;
    a[0] *= dk; a[1] *= dk; a[2] *= dk;
    if (topopen && (gy % 16) < 2) {
        float sk = (gy % 16) == 0 ? 0.75f : 0.4f;
        a[0] = lerpf(a[0], 0.50f, sk); a[1] = lerpf(a[1], 0.36f, sk); a[2] = lerpf(a[2], 0.19f, sk);
        n[1] = -0.75f;
    }
}
static void paint_sand(int gx, int gy, float *a, float *n) {
    float rip = sinf(gx * 0.35f + fbm(gx * 0.05f, gy * 0.2f) * 6 + gy * 0.6f);
    float nz = fbm(gx * 0.3f, gy * 0.3f);
    float k = 0.85f + 0.2f * nz + 0.08f * rip;
    a[0] = 0.40f * k; a[1] = 0.28f * k; a[2] = 0.14f * k;
    n[0] = rip * 0.25f; n[1] = (gy % 16 == 0) ? -0.8f : -0.2f;
}

static float moon_x = 56, moon_y = 26;
static void paint_sky(int lx, int ly, int gx, int gy, float *a, float *n, float *e) {
    float t = clampf(ly / 224.0f, 0, 1);
    e[0] = lerpf(0.002f, 0.050f, t * t); e[1] = lerpf(0.004f, 0.030f, t * t); e[2] = lerpf(0.030f, 0.075f, t);
    a[0] = a[1] = a[2] = 0; n[0] = n[1] = 0;
    float sv = h01(gx * 3 + 1, gy * 7 + 5);
    if (sv > 0.9965f) { float b = (sv - 0.9965f) / 0.0035f; e[0] += 0.6f * b; e[1] += 0.65f * b; e[2] += 0.8f * b; }
    float dx = lx - moon_x, dy = ly - moon_y, d = sqrtf(dx * dx + dy * dy);
    if (d < 13) {
        float cr = fbm(lx * 0.35f, ly * 0.35f);
        float limb = sqrtf(1 - (d / 13) * (d / 13));
        float k = (0.75f + 0.25f * limb) * (0.82f + 0.3f * cr);
        e[0] = 1.25f * k; e[1] = 1.22f * k; e[2] = 1.08f * k;
    } else {
        float gl = expf(-(d - 13) / 28.0f);
        e[0] += 0.10f * gl; e[1] += 0.12f * gl; e[2] += 0.22f * gl;
    }
    /* Ferne Pyramide und Dünen */
    float pyr = 196 - (40 - fabsf(lx - 62.0f)) * 1.0f;
    float dune1 = 200 + 7 * sinf(lx * 0.021f + 1.3f) + 4 * sinf(lx * 0.06f);
    float dune2 = 212 + 6 * sinf(lx * 0.034f + 4.0f) + 2 * sinf(lx * 0.11f);
    if (ly > dune2) { paint_sand(gx, gy, a, n); a[0] *= 0.6f; a[1] *= 0.6f; a[2] *= 0.6f; e[0] = e[1] = e[2] = 0; n[0] = cosf(lx * 0.034f + 4) * 0.4f; }
    else if (ly > dune1) { a[0] = 0.16f; a[1] = 0.11f; a[2] = 0.06f; n[0] = cosf(lx * 0.021f + 1.3f) * 0.3f; n[1] = -0.4f; e[0] *= 0.1f; e[1] *= 0.1f; e[2] *= 0.1f; }
    else if (fabsf(lx - 62.0f) < 40 && ly > pyr) {
        float side = lx < 62 ? 0.5f : -0.5f;
        a[0] = 0.13f; a[1] = 0.09f; a[2] = 0.05f; n[0] = -side; n[1] = -0.3f;
        if (((int)(ly - pyr)) % 4 == 0) { a[0] *= 0.6f; a[1] *= 0.6f; a[2] *= 0.6f; }
        e[0] *= 0.05f; e[1] *= 0.05f; e[2] *= 0.08f;
    }
}

static void build_room(int room) {
    cur_room = room;
    int rx = room % GX, ry = room / GX;
    room_ox = rx * RW * TS; room_oy = ry * RH * TS;
    room_exterior = (rx == 0 && ry == 2);
    static_round = round_no;
    int depth[RH][RW], topopen[RH][RW];
    for (int ty = 0; ty < RH; ty++)
        for (int tx = 0; tx < RW; tx++) {
            int gtx = rx * RW + tx, gty = ry * RH + ty;
            depth[ty][tx] = tile_depth(gtx, gty);
            topopen[ty][tx] = is_solid(gtx, gty) && !is_solid(gtx, gty - 1) && tile(gtx, gty - 1) != '-';
        }
    int zx0 = 0, zy0 = 0;
    for (int ly = 0; ly < VH; ly++) {
        for (int lx = 0; lx < VW; lx++) {
            int i = ly * VW + lx;
            int gx = room_ox + lx, gy = room_oy + ly;
            int tx = lx / TS, ty = ly / TS, px = lx % TS, py = ly % TS;
            int gtx = rx * RW + tx, gty = ry * RH + ty;
            char c = tile(gtx, gty);
            float *a = &s_alb[i * 3], *n = &s_nrm[i * 2], *e = &s_emi[i * 3];
            e[0] = e[1] = e[2] = 0;
            if (is_solid_c(c) && c != 'D') {
                if (c == 'Z') {
                    if (!(tile(gtx - 1, gty) == 'Z')) zx0 = gtx;
                    if (!(tile(gtx, gty - 1) == 'Z')) zy0 = gty;
                    int zx = gx - zx0 * TS, zy = gy - zy0 * TS;
                    while (tile(gtx, zy0 - 1) == 'Z') { zy0--; zy = gy - zy0 * TS; }
                    a[0] = 0.025f; a[1] = 0.04f; a[2] = 0.035f; n[0] = n[1] = 0;
                    float nz = fbm(gx * 0.3f, gy * 0.3f);
                    a[0] *= 0.8f + 0.4f * nz; a[1] *= 0.8f + 0.4f * nz; a[2] *= 0.8f + 0.4f * nz;
                    int zw = 0; while (tile(zx0 + zw, gty) == 'Z') zw++;
                    int gold = zy < 3 || zy == 31 || zx < 2 || zx >= zw * TS - 2 || (zx % 24) == 12 || (zx % 24) == 13;
                    int lapis = (zy >= 8 && zy < 11) || (zy >= 20 && zy < 23);
                    if (lapis && !gold) { a[0] = 0.02f; a[1] = 0.06f; a[2] = 0.30f; }
                    if (gold) { a[0] = 0.75f; a[1] = 0.45f; a[2] = 0.09f; }
                    if (!gold && !lapis && glyph_px((zx / 12) % 7, (zx % 12) - 3, (zy - 12) / 2 * 1 % 9) && zy > 12 && zy < 20) { a[0] = 0.55f; a[1] = 0.32f; a[2] = 0.07f; }
                    if (zy == 0) n[1] = -0.8f; else if (zy == 1) n[1] = -0.4f;
                } else {
                    paint_stone(gx, gy, depth[ty][tx], topopen[ty][tx], a, n);
                    if (room_exterior && gty == ry * RH + 14 && tx < 7) paint_sand(gx, gy, a, n);
                    if (room_exterior && gty >= ry * RH + 14 && tx < 7 && gty > ry * RH + 14) { paint_sand(gx, gy, a, n); a[0] *= 0.5f; a[1] *= 0.5f; a[2] *= 0.5f; }
                    if (c == 'L' || c == 'J' || c == 'V') {
                        float dx = px - 7.5f, dy = py - 7.5f, d = sqrtf(dx * dx + dy * dy);
                        a[0] = 0.10f; a[1] = 0.075f; a[2] = 0.05f;
                        if (d < 6.5f) { a[0] = 0.03f; a[1] = 0.02f; a[2] = 0.015f; n[0] = dx / 8; n[1] = dy / 8; }
                        else if (d < 7.5f) { a[0] = 0.5f; a[1] = 0.3f; a[2] = 0.08f; }
                        if (px == 0 || py == 0) { a[0] *= 0.4f; a[1] *= 0.4f; a[2] *= 0.4f; }
                    }
                }
                continue;
            }
            /* nicht fest: Hintergrund */
            if (c == ',') { paint_sky(lx, ly, gx, gy, a, n, e); continue; }
            paint_wall(gx, gy, a, n);
            /* Umgebungsverdeckung an festen Nachbarn */
            {
                float dmin = 99;
                for (int oy = -1; oy <= 1; oy++)
                    for (int ox = -1; ox <= 1; ox++) {
                        if (!ox && !oy) continue;
                        if (!is_solid(gtx + ox, gty + oy)) continue;
                        float ddx = ox < 0 ? px : ox > 0 ? 15 - px : 0;
                        float ddy = oy < 0 ? py : oy > 0 ? 15 - py : 0;
                        float d = ox && oy ? sqrtf(ddx * ddx + ddy * ddy) : (ox ? ddx : ddy);
                        if (d < dmin) dmin = d;
                    }
                float ao = 0.22f + 0.78f * smooth(0, 12, dmin);
                if (dmin < 1) ao *= 0.5f;
                if (tile(gtx, gty - 1) == '-' && py < 7) ao *= 0.55f + 0.45f * py / 7.0f;
                a[0] *= ao; a[1] *= ao; a[2] *= ao;
            }
            if (c == 'I') {
                int top = tile(gtx, gty - 1) != 'I', bot = tile(gtx, gty + 1) != 'I';
                int w0 = 3, w1 = 12;
                if (top && py < 6) { int fl = 6 - py; w0 = 3 - fl / 2; w1 = 12 + fl / 2; }
                if (bot && py > 12) { w0 = 2; w1 = 13; }
                if (px >= w0 && px <= w1) {
                    float cxp = (px - (w0 + w1) * 0.5f) / ((w1 - w0) * 0.5f + 0.5f);
                    float nz = fbm(gx * 0.4f, gy * 0.1f);
                    float k = 0.85f + 0.25f * nz;
                    a[0] = 0.30f * k; a[1] = 0.21f * k; a[2] = 0.12f * k;
                    if (!top && !bot && (px % 3) == 0) { a[0] *= 0.7f; a[1] *= 0.7f; a[2] *= 0.7f; }
                    if (top && py < 6) {
                        int band = py % 3;
                        if (band == 0) { a[0] = 0.04f; a[1] = 0.18f; a[2] = 0.14f; }
                        else if (band == 1) { a[0] = 0.55f; a[1] = 0.35f; a[2] = 0.08f; }
                    }
                    n[0] = cxp * 0.85f; n[1] = 0;
                }
            }
            if (c == 'H') {
                int rail = (px >= 2 && px <= 3) || (px >= 12 && px <= 13);
                int rung = (py % 8 == 3 || py % 8 == 4) && px > 3 && px < 12;
                if (rail || rung) {
                    float g = 0.75f + 0.35f * vnoise(gx * 0.6f, gy * 0.12f);
                    a[0] = 0.34f * g; a[1] = 0.17f * g; a[2] = 0.06f * g;
                    n[0] = rail ? (px == 2 || px == 12 ? -0.5f : 0.5f) : 0;
                    n[1] = rung ? (py % 8 == 3 ? -0.6f : 0.5f) : 0;
                    if (rail && (py % 8 == 3 || py % 8 == 4)) { a[0] = 0.10f; a[1] = 0.08f; a[2] = 0.05f; }
                }
            }
            if (c == '-') {
                if (py <= 5) {
                    int bx2 = (gx + ((gy / 16) & 1) * 8) / 24;
                    float k = (0.8f + 0.3f * h01(bx2, gy / 16)) * (0.85f + 0.3f * fbm(gx * 0.3f, gy * 0.3f));
                    a[0] = 0.42f * k; a[1] = 0.29f * k; a[2] = 0.15f * k;
                    n[0] = 0; n[1] = py == 0 ? -0.8f : py == 5 ? 0.6f : 0;
                    if ((gx + ((gy / 16) & 1) * 8) % 24 == 0) { a[0] *= 0.4f; a[1] *= 0.4f; a[2] *= 0.4f; }
                    if (py == 0) { a[0] *= 1.2f; a[1] *= 1.2f; a[2] *= 1.2f; }
                }
            }
            if (c == '^' || (c == '!' && round_no >= 2) || c == 'T') {
                if (py >= 13) {
                    a[0] = 0.06f; a[1] = 0.045f; a[2] = 0.03f; n[1] = py == 13 ? -0.6f : 0;
                    if (c == 'T' && (px % 4 == 2)) { a[0] = 0.01f; a[1] = 0.01f; a[2] = 0.01f; }
                } else if (c != 'T') {
                    for (int k = 0; k < 4; k++) {
                        float sc = 2 + k * 4;
                        float half = (py - 5) * 0.24f + 0.3f;
                        if (py >= 5 && fabsf(px + 0.5f - sc) <= half) {
                            float side = (px + 0.5f - sc) / (half + 0.01f);
                            float g = 0.7f + 0.3f * (1 - (py - 5) / 8.0f);
                            a[0] = 0.85f * g; a[1] = 0.55f * g; a[2] = 0.22f * g;
                            n[0] = side * 0.7f; n[1] = -0.2f;
                        }
                    }
                }
            }
            if (c == '*') {
                int bowl = py >= 7 && py <= 9 && px >= 4 && px <= 11 && !(py == 9 && (px == 4 || px == 11));
                int stem = px >= 7 && px <= 8 && py >= 9 && py <= 13;
                int plate = px >= 6 && px <= 9 && py >= 13 && py <= 15;
                if (bowl || stem || plate) {
                    a[0] = 0.05f; a[1] = 0.045f; a[2] = 0.04f;
                    n[0] = (px - 7.5f) / 6; n[1] = bowl && py == 7 ? -0.7f : 0;
                    if (bowl && py == 7) { a[0] = 0.25f; a[1] = 0.16f; a[2] = 0.07f; }
                }
            }
        }
    }
    for (int i = 0; i < n_lasers; i++) if (lasers[i].room == room) laser_measure(&lasers[i]);
    build_lights();
}

/* ---- Sprites ---- */
typedef struct { float r, g, b, er, eg, eb; } PalE;
static int pal_lookup(char ch, PalE *p) {
    memset(p, 0, sizeof(*p));
#define C(a,b2,c2) do { p->r = a; p->g = b2; p->b = c2; } while (0)
    switch (ch) {
    case 'k': C(0.012f, 0.009f, 0.010f); break;
    case 'h': C(0.20f, 0.10f, 0.035f); break;
    case 'j': C(0.38f, 0.21f, 0.08f); break;
    case 'H': C(0.05f, 0.025f, 0.01f); break;
    case 's': C(0.70f, 0.36f, 0.18f); break;
    case 'S': C(0.40f, 0.17f, 0.08f); break;
    case 'e': C(0.0f, 0.0f, 0.0f); break;
    case 'r': C(0.55f, 0.04f, 0.025f); break;
    case 'R': C(0.24f, 0.012f, 0.01f); break;
    case 'w': C(0.60f, 0.48f, 0.25f); break;
    case 'W': C(0.30f, 0.23f, 0.10f); break;
    case 'b': C(0.09f, 0.04f, 0.015f); break;
    case 'y': C(0.90f, 0.55f, 0.10f); break;
    case 'Y': C(1.0f, 0.80f, 0.32f); break;
    case 'u': C(0.40f, 0.20f, 0.03f); break;
    case 'p': C(0.16f, 0.11f, 0.06f); break;
    case 'P': C(0.07f, 0.05f, 0.025f); break;
    case 'o': C(0.08f, 0.03f, 0.01f); break;
    case 'g': C(0.25f, 0.10f, 0.03f); break;
    case 'm': C(0.52f, 0.47f, 0.34f); break;
    case 'M': C(0.26f, 0.22f, 0.15f); break;
    case 'E': C(0.1f, 0.3f, 0.1f); p->er = 0.5f; p->eg = 2.2f; p->eb = 0.8f; break;
    case 'n': C(0.06f, 0.04f, 0.06f); break;
    case 'N': C(0.16f, 0.09f, 0.14f); break;
    case 'X': C(0.6f, 0.05f, 0.03f); p->er = 4.0f; p->eg = 0.4f; p->eb = 0.15f; break;
    case 'q': C(0.012f, 0.10f, 0.12f); break;
    case 'Q': C(0.25f, 0.70f, 0.60f); p->er = 0.12f; p->eg = 0.75f; p->eb = 0.65f; break;
    case 'G': C(0.6f, 0.04f, 0.03f); p->er = 1.6f; p->eg = 0.12f; p->eb = 0.06f; break;
    default: return 0;
    }
#undef C
    return 1;
}
static void put_alb(int x, int y, float r, float g, float b, float nx, float ny) {
    if (x < 0 || y < 0 || x >= VW || y >= VH) return;
    int i = y * VW + x;
    f_alb[i * 3] = r; f_alb[i * 3 + 1] = g; f_alb[i * 3 + 2] = b;
    f_nrm[i * 2] = nx; f_nrm[i * 2 + 1] = ny;
}
static void add_emi(int x, int y, float r, float g, float b) {
    if (x < 0 || y < 0 || x >= VW || y >= VH) return;
    int i = y * VW + x;
    f_emi[i * 3] += r; f_emi[i * 3 + 1] += g; f_emi[i * 3 + 2] += b;
}
static void blend_alb(int x, int y, float r, float g, float b, float a) {
    if (x < 0 || y < 0 || x >= VW || y >= VH) return;
    int i = y * VW + x;
    f_alb[i * 3] = lerpf(f_alb[i * 3], r, a); f_alb[i * 3 + 1] = lerpf(f_alb[i * 3 + 1], g, a); f_alb[i * 3 + 2] = lerpf(f_alb[i * 3 + 2], b, a);
}
static void spr_draw(const char *const *rows, int h, int x, int y, int flip, float tint, int cliptop) {
    int w = (int)strlen(rows[0]);
    for (int r = 0; r < h; r++) {
        if (y + r < cliptop) continue;
        for (int c = 0; c < w; c++) {
            char ch = rows[r][flip ? w - 1 - c : c];
            PalE p;
            if (!pal_lookup(ch, &p)) continue;
            /* weiche Kugelnormale für plastische Sprites */
            float nx = ((c + 0.5f) / w - 0.5f) * 0.9f, ny = ((r + 0.5f) / h - 0.5f) * 0.6f;
            put_alb(x + c, y + r, p.r * tint, p.g * tint, p.b * tint, nx, ny);
            if (p.er > 0 || p.eg > 0 || p.eb > 0) add_emi(x + c, y + r, p.er, p.eg, p.eb);
        }
    }
}

/* ======================================================================= */
/*                              Text                                       */
/* ======================================================================= */
static const Glyph5 *font_find(unsigned int cp) {
    if (cp >= 'a' && cp <= 'z') cp -= 32;
    if (cp == 0xE4) cp = 0xC4; if (cp == 0xF6) cp = 0xD6; if (cp == 0xFC) cp = 0xDC;
    for (int i = 0; i < FONT_COUNT; i++) if (FONT[i].code == cp) return &FONT[i];
    return &FONT[0];
}
static unsigned int utf8_next(const char **s) {
    const unsigned char *p = (const unsigned char *)*s;
    unsigned int c = *p;
    if (c < 0x80) { *s += 1; return c; }
    if ((c & 0xE0) == 0xC0) { *s += 2; return ((c & 0x1F) << 6) | (p[1] & 0x3F); }
    if ((c & 0xF0) == 0xE0) { *s += 3; return ((c & 0x0F) << 12) | ((p[1] & 0x3F) << 6) | (p[2] & 0x3F); }
    *s += 1; return '?';
}
static int text_width(const char *s, int scale, int spacing) {
    int n = 0;
    while (*s) { utf8_next(&s); n++; }
    return n ? n * (5 * scale + spacing) - spacing : 0;
}
static void text_srgb(unsigned int *fb, int x, int y, const char *s, int scale, unsigned int col, int shadow) {
    int spacing = scale;
    while (*s) {
        unsigned int cp = utf8_next(&s);
        const Glyph5 *g = font_find(cp);
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 5; c++) {
                if (!(g->rows[r] & (1 << (4 - c)))) continue;
                for (int sy = 0; sy < scale; sy++)
                    for (int sx = 0; sx < scale; sx++) {
                        int px = x + c * scale + sx, py = y + r * scale + sy;
                        if (shadow) {
                            int qx = px + (scale > 1 ? scale / 2 + 1 : 1), qy = py + (scale > 1 ? scale / 2 + 1 : 1);
                            if (qx >= 0 && qy >= 0 && qx < SCR_W && qy < SCR_H) {
                                unsigned int o = fb[qy * SCR_W + qx];
                                fb[qy * SCR_W + qx] = ((o >> 2) & 0x3F3F3F);
                            }
                        }
                        if (px >= 0 && py >= 0 && px < SCR_W && py < SCR_H) fb[py * SCR_W + px] = col;
                    }
            }
        x += 5 * scale + spacing;
    }
}
static void text_srgb_c(unsigned int *fb, int cx, int y, const char *s, int scale, unsigned int col, int shadow) {
    text_srgb(fb, cx - text_width(s, scale, scale) / 2, y, s, scale, col, shadow);
}
/* Text in den Emissionspuffer (glüht durch Bloom) */
static void text_emi(int x, int y, const char *s, int scale, float r, float g, float b, float grad) {
    while (*s) {
        unsigned int cp = utf8_next(&s);
        const Glyph5 *gl = font_find(cp);
        for (int rr = 0; rr < 7; rr++)
            for (int c = 0; c < 5; c++) {
                if (!(gl->rows[rr] & (1 << (4 - c)))) continue;
                for (int sy = 0; sy < scale; sy++)
                    for (int sx = 0; sx < scale; sx++) {
                        float k = 1 + grad * (0.5f - (rr * scale + sy) / (7.0f * scale));
                        int edge = (sy == 0 && (rr == 0 || !(gl->rows[rr - 1] & (1 << (4 - c)))));
                        float hl = edge ? 1.5f : 1.0f;
                        int px = x + c * scale + sx, py = y + rr * scale + sy;
                        if (px < 0 || py < 0 || px >= VW || py >= VH) continue;
                        int i = py * VW + px;
                        f_alb[i * 3] = f_alb[i * 3 + 1] = f_alb[i * 3 + 2] = 0;
                        f_emi[i * 3] = r * k * hl; f_emi[i * 3 + 1] = g * k * hl; f_emi[i * 3 + 2] = b * k * hl;
                    }
            }
        x += 5 * scale + scale;
    }
}
static void fill_rect_srgb(unsigned int *fb, int x, int y, int w, int h, unsigned int col, float alpha) {
    for (int yy = y; yy < y + h; yy++)
        for (int xx = x; xx < x + w; xx++) {
            if (xx < 0 || yy < 0 || xx >= SCR_W || yy >= SCR_H) continue;
            unsigned int o = fb[yy * SCR_W + xx];
            int r = (int)(((o >> 16) & 255) * (1 - alpha) + ((col >> 16) & 255) * alpha);
            int g = (int)(((o >> 8) & 255) * (1 - alpha) + ((col >> 8) & 255) * alpha);
            int b = (int)((o & 255) * (1 - alpha) + (col & 255) * alpha);
            fb[yy * SCR_W + xx] = (r << 16) | (g << 8) | b;
        }
}
static unsigned int lin2srgb_u(float r, float g, float b) {
    int R = lut_srgb[(int)(clampf(r, 0, 1) * 4096)], G = lut_srgb[(int)(clampf(g, 0, 1) * 4096)], B = lut_srgb[(int)(clampf(b, 0, 1) * 4096)];
    return (R << 16) | (G << 8) | B;
}
static void spr_srgb(unsigned int *fb, const char *const *rows, int h, int x, int y, float bright) {
    int w = (int)strlen(rows[0]);
    for (int r = 0; r < h; r++)
        for (int c = 0; c < w; c++) {
            PalE p;
            if (!pal_lookup(rows[r][c], &p)) continue;
            int px = x + c, py = y + r;
            if (px < 0 || py < 0 || px >= SCR_W || py >= SCR_H) continue;
            fb[py * SCR_W + px] = lin2srgb_u(p.r * bright + p.er * 0.3f, p.g * bright + p.eg * 0.3f, p.b * bright + p.eb * 0.3f);
        }
}

/* ======================================================================= */
/*                         Spielablauf & Menüs                             */
/* ======================================================================= */
enum { GS_TITLE, GS_PLAY, GS_PAUSE, GS_GAMEOVER, GS_ROUND };
static int gstate = GS_TITLE;
static Input prev_in;
static int menu_sel = 0;
static int quit_req = 0, fs_req = 0;
static int banner_t = 0; static const char *banner_text = 0;
static int msg_t = 0; static char msg_text[96];
static int fade_t = 0;
static float shake = 0;
static int state_t = 0;
static int locked_cool = 0;
static int music_enabled = 1, sfx_enabled = 1;
static int audio_ok = 1;
static void menus_build(void);

static void show_msg(const char *s, int frames) { snprintf(msg_text, sizeof(msg_text), "%s", s); msg_t = frames; }

static void enter_room(int room) {
    build_room(room);
    int rx = room % GX, ry = room / GX;
    banner_text = ROOM_NAME[ry][rx]; banner_t = 170;
    fade_t = 14;
    cp_pending = 1;
    n_parts = 0;
}

static void new_round(int fresh) {
    if (fresh) { lives = 5; score = 0; round_no = 1; }
    world_load();
    keys_held = 0; treasures_got = 0;
    memset(&pl, 0, sizeof(pl));
    pl.x = start_x; pl.y = start_y; pl.facing = 1; pl.st = PS_GROUND; pl.invuln = 60;
    cp_x = start_x; cp_y = start_y;
    int rx = (int)((pl.x + PW / 2) / (RW * TS)), ry = (int)((pl.y + PH / 2) / (RH * TS));
    enter_room(ry * GX + rx);
    char buf[96];
    if (round_no == 1) snprintf(buf, sizeof buf, "FINDE DIE %d SONNENAMULETTE", n_treasures_total);
    else snprintf(buf, sizeof buf, "DURCHGANG %d – DIE PYRAMIDE WIRD TÜCKISCHER", round_no);
    show_msg(buf, 260);
}

void game_init(void) {
    for (int i = 0; i <= 4096; i++) lut_srgb[i] = (unsigned char)(255.0f * powf(i / 4096.0f, 1 / 2.2f) + 0.5f);
    world_load();
    build_room(2 * GX + 0);
    gstate = GS_TITLE;
    memset(&prev_in, 0, sizeof(prev_in));
    menus_build();
    music_enabled = sfx_enabled = audio_ok;
    audio_set_music(audio_ok); audio_set_sfx(audio_ok);
}
/* Plattform meldet, ob Ton ausgegeben werden kann (vor game_init aufrufen) */
void game_set_audio_available(int ok) { audio_ok = ok ? 1 : 0; }
int game_quit_requested(void) { return quit_req; }
int game_fullscreen_toggle_requested(void) { int r = fs_req; fs_req = 0; return r; }

static int cp_ok(void) {
    if (hazard_static(&pl) || hazard_dynamic(&pl)) return 0;
    int l = (int)floorf(pl.x / TS), r = (int)floorf((pl.x + PW - 1) / TS), ty = (int)floorf((pl.y + PH - 1) / TS);
    for (int tx = l - 1; tx <= r + 1; tx++) if (tile(tx, ty) == 'T' || tile(tx, ty) == '^' || (tile(tx, ty) == '!' && round_no >= 2)) return 0;
    for (int i = 0; i < n_lasers; i++) {
        Laser *L = &lasers[i]; if (L->room != cur_room) continue;
        float x, y, w, h; laser_rect(L, &x, &y, &w, &h);
        if (rect_hit(pl.x - 4, pl.y, PW + 8, PH, x, y, w, h)) return 0;
    }
    for (int i = 0; i < n_enemies; i++) {
        Enemy *e = &enemies[i]; if (e->room != cur_room) continue;
        float dx = e->x - pl.x, dy = e->y - pl.y;
        if (dx * dx + dy * dy < 56 * 56) return 0;
    }
    return 1;
}
static void kill_player(void) {
    if (pl.dead) return;
    pl.dead = 1; pl.deadt = 0;
    float cx = pl.x + PW / 2 - room_ox, cy = pl.y + PH / 2 - room_oy;
    burst(cx, cy, 2.5f, 1.2f, 0.4f, 70, 2.2f);
    for (int i = 0; i < 26; i++) {
        Part *p = part_new(PT_BIT, cx + frnds() * 4, cy + frnds() * 8);
        if (!p) break;
        p->vx = frnds() * 2.2f; p->vy = -1.5f - frnd() * 2.5f; p->max = p->life = 80 + frnd() * 40;
        float k = frnd();
        if (k < 0.3f) { p->r = 0.55f; p->g = 0.04f; p->b = 0.02f; } else if (k < 0.6f) { p->r = 0.6f; p->g = 0.48f; p->b = 0.25f; } else { p->r = 0.2f; p->g = 0.1f; p->b = 0.03f; }
        p->size = 1 + (frnd() < 0.3f);
    }
    shake = 6;
    sfx(SFX_DEATH);
}

static void update_world(void) {
    float rx0 = room_ox, rx1 = room_ox + VW;
    float spdk = round_no >= 3 ? 1.5f : round_no >= 2 ? 1.25f : 1.0f;
    for (int i = 0; i < n_enemies; i++) {
        Enemy *e = &enemies[i];
        if (e->room != cur_room) continue;
        e->anim += 0.12f;
        if (e->type == EN_BAT) {
            e->t += 0.045f;
            e->x += e->vx * spdk;
            int tx = (int)floorf((e->vx > 0 ? e->x + e->w : e->x) / TS), ty = (int)floorf((e->y + e->h * 0.5f) / TS);
            if (is_solid(tx, ty) || e->x < rx0 + 2 || e->x + e->w > rx1 - 2) { e->vx = -e->vx; e->x += e->vx * 2; }
            float ny = e->hy + sinf(e->t) * 12;
            int ty2 = (int)floorf((ny + (ny > e->y ? e->h : 0)) / TS);
            int txc = (int)floorf((e->x + e->w * 0.5f) / TS);
            if (!is_solid(txc, ty2)) e->y = ny;
            else e->t += 3.14159f;
        } else {
            float sp = (e->type == EN_SCARAB ? 1.5f : 0.45f) * spdk;
            e->vx = (e->vx >= 0 ? 1 : -1) * sp;
            e->vy += GRAV; if (e->vy > MAXFALL) e->vy = MAXFALL;
            e->y += e->vy;
            int fty = (int)floorf((e->y + e->h) / TS);
            int l = (int)floorf(e->x / TS), r = (int)floorf((e->x + e->w - 1) / TS);
            int ground = 0;
            for (int tx = l; tx <= r; tx++)
                if (is_solid(tx, fty) || is_oneway(tx, fty)) { if (e->vy >= 0 && e->y + e->h - e->vy <= fty * TS + 0.5f) { e->y = fty * TS - e->h; e->vy = 0; ground = 1; } }
            if (ground) {
                float nx = e->x + e->vx;
                int front = (int)floorf((e->vx > 0 ? nx + e->w : nx) / TS);
                int body = (int)floorf((e->y + e->h - 1) / TS);
                int top = (int)floorf(e->y / TS);
                int blocked = 0;
                for (int ty = top; ty <= body; ty++) if (is_solid(front, ty)) blocked = 1;
                char fc = tile(front, body);
                if (fc == '^' || fc == 'T' || (fc == '!' && round_no >= 2)) blocked = 1;
                if (!is_solid(front, body + 1) && !is_oneway(front, body + 1)) blocked = 1;
                if (nx < rx0 || nx + e->w > rx1) blocked = 1;
                if (blocked) e->vx = -e->vx; else e->x = nx;
            }
        }
    }
    for (int i = 0; i < n_springs; i++) springs[i].comp *= 0.85f;
    for (int i = 0; i < n_doors; i++) if (doors[i].open && doors[i].anim < 1) doors[i].anim += 0.022f;
    /* Laser-Geräusch */
    for (int i = 0; i < n_lasers; i++) {
        Laser *L = &lasers[i];
        if (L->room != cur_room) continue;
        int on = laser_on(L, gframe);
        if (on && !L->was_on) {
            float dx = L->tx * TS + 8 - (pl.x + PW / 2), dy = L->ty * TS + 8 - (pl.y + PH / 2);
            if (dx * dx + dy * dy < 260 * 260) sfx(SFX_LASER);
        }
        L->was_on = on;
    }
    /* Zeitstacheln-Geräusch */
    if ((gframe % 4) == 0) {
        int ptx = (int)((pl.x + PW / 2) / TS);
        static unsigned int last_spike = 0;
        for (int ty = cur_room / GX * RH; ty < cur_room / GX * RH + RH; ty++)
            for (int tx = ptx - 6; tx <= ptx + 6; tx++)
                if (tile(tx, ty) == 'T') {
                    int ph = (int)((gframe + (unsigned)((tx / 4) * 47)) % 160);
                    if (ph >= 60 && ph < 64 && gframe - last_spike > 30) { sfx(SFX_SPIKE); last_spike = gframe; }
                }
    }
}

static void update_particles(void) {
    /* Umgebung: Staub, Funken, rieselnder Sand */
    int dust = 0;
    for (int i = 0; i < n_parts; i++) if (parts[i].kind == PT_DUST) dust++;
    while (dust < 70) {
        Part *p = part_new(PT_DUST, frnd() * VW, frnd() * VH);
        if (!p) break;
        p->vx = frnds() * 0.08f; p->vy = frnds() * 0.05f; p->max = p->life = 300 + frnd() * 400;
        p->r = p->g = p->b = 1; p->size = 1;
        dust++;
    }
    for (int i = 0; i < n_torches; i++) {
        Torch *t = &torches[i];
        if (t->room != cur_room) continue;
        if (frnd() < 0.18f) {
            Part *p = part_new(PT_SPARK, t->tx * TS - room_ox + 8 + frnds() * 2, t->ty * TS - room_oy + 3);
            if (!p) break;
            p->vx = frnds() * 0.3f; p->vy = -0.4f - frnd() * 0.7f; p->max = p->life = 30 + frnd() * 40;
            p->r = 2.2f; p->g = 0.9f; p->b = 0.25f;
        }
    }
    if (!room_exterior && frnd() < 0.02f) {
        int tx = (int)(frnd() * RW), gtx = cur_room % GX * RW + tx;
        for (int ty = 1; ty < RH - 2; ty++) {
            int gty = cur_room / GX * RH + ty;
            if (is_solid(gtx, gty) && !is_solid(gtx, gty + 1) && tile(gtx, gty + 1) != ',') {
                for (int k = 0; k < 18; k++) {
                    Part *p = part_new(PT_SAND, tx * TS + 4 + frnd() * 8, (ty + 1) * TS + 1);
                    if (!p) break;
                    p->vx = frnds() * 0.05f; p->vy = 0.2f + frnd() * 0.4f; p->max = p->life = 90; p->r = 0.55f; p->g = 0.42f; p->b = 0.25f;
                    p->y -= k * 3;
                }
                break;
            }
        }
    }
    for (int i = 0; i < n_items; i++) {
        Item *it = &items[i];
        if (it->room != cur_room || it->taken || !it->type) continue;
        if (frnd() < 0.08f) {
            Part *p = part_new(PT_GLINT, it->tx * TS - room_ox + 8 + frnds() * 9, it->ty * TS - room_oy + 8 + frnds() * 9);
            if (!p) break;
            p->vy = -0.15f; p->max = p->life = 30; p->r = 2.5f; p->g = 1.9f; p->b = 0.9f;
        }
    }
    for (int i = 0; i < n_parts; i++) {
        Part *p = &parts[i];
        p->life -= 1;
        if (p->life <= 0) { parts[i] = parts[--n_parts]; i--; continue; }
        switch (p->kind) {
        case PT_DUST: p->vx += frnds() * 0.004f; p->vy += frnds() * 0.004f; p->vx *= 0.995f; p->vy *= 0.995f; break;
        case PT_SPARK: p->vx += frnds() * 0.05f; p->vy *= 0.99f; break;
        case PT_SAND: p->vy += 0.05f; break;
        case PT_PUFF: p->vx *= 0.94f; p->vy *= 0.94f; p->size += 0.04f; break;
        case PT_BURST: p->vx *= 0.96f; p->vy = p->vy * 0.96f + 0.03f; break;
        case PT_BIT: p->vy += 0.15f; {
            int tx = (int)floorf((p->x + room_ox) / TS), ty = (int)floorf((p->y + p->vy + room_oy) / TS);
            if (is_solid(tx, ty) || tile(tx, ty) == '-') { p->vy *= -0.3f; p->vx *= 0.6f; }
        } break;
        }
        p->x += p->vx; p->y += p->vy;
    }
}

enum { MA_START, MA_MUSIC, MA_SFX, MA_FS, MA_QUIT, MA_RESUME, MA_TITLE };
/* Menüs je nach Plattform: Vollbild-Punkt nur unter Windows (Saalburg: Super+1),
 * Musik/Effekte nur, wenn Ton ausgegeben werden kann */
static int TITLE_MENU[6], PAUSE_MENU[6], N_TITLE = 0, N_PAUSE = 0;
static void menus_build(void) {
    N_TITLE = N_PAUSE = 0;
    TITLE_MENU[N_TITLE++] = MA_START; PAUSE_MENU[N_PAUSE++] = MA_RESUME;
    if (audio_ok) {
        TITLE_MENU[N_TITLE++] = MA_MUSIC; TITLE_MENU[N_TITLE++] = MA_SFX;
        PAUSE_MENU[N_PAUSE++] = MA_MUSIC; PAUSE_MENU[N_PAUSE++] = MA_SFX;
    }
#ifndef SAALBURG
    TITLE_MENU[N_TITLE++] = MA_FS; PAUSE_MENU[N_PAUSE++] = MA_FS;
#endif
    TITLE_MENU[N_TITLE++] = MA_QUIT; PAUSE_MENU[N_PAUSE++] = MA_TITLE;
}
static const char *menu_label(int a) {
    switch (a) {
    case MA_START: return "SPIEL STARTEN";
    case MA_MUSIC: return music_enabled ? "MUSIK: AN" : "MUSIK: AUS";
    case MA_SFX: return sfx_enabled ? "EFFEKTE: AN" : "EFFEKTE: AUS";
    case MA_FS: return "VOLLBILD / FENSTER";
    case MA_QUIT: return "BEENDEN";
    case MA_RESUME: return "WEITERSPIELEN";
    case MA_TITLE: return "ZUM TITELBILD";
    }
    return "";
}
/* Fenster verliert den Fokus: laufendes Spiel anhalten */
void game_focus_lost(void) {
    if (gstate == GS_PLAY) { gstate = GS_PAUSE; menu_sel = 0; }
}
static void menu_input(const Input *in, int n, int *sel) {
    if (in->up && !prev_in.up) { *sel = (*sel + n - 1) % n; sfx(SFX_MENU); }
    if (in->down && !prev_in.down) { *sel = (*sel + 1) % n; sfx(SFX_MENU); }
}
static int confirm_pressed(const Input *in) {
    return (in->confirm && !prev_in.confirm) || (in->jump && !prev_in.jump);
}

void game_update(const Input *in) {
    gframe++; state_t++;
    if (audio_ok && in->music && !prev_in.music) { music_enabled = !music_enabled; audio_set_music(music_enabled); }
    if (audio_ok && in->sfx && !prev_in.sfx) { sfx_enabled = !sfx_enabled; audio_set_sfx(sfx_enabled); }
    if (fade_t > 0) fade_t--;
    if (shake > 0) shake *= 0.9f; if (shake < 0.2f) shake = 0;
    if (banner_t > 0) banner_t--;
    if (msg_t > 0) msg_t--;
    if (locked_cool > 0) locked_cool--;

    if (gstate == GS_TITLE) {
        menu_input(in, N_TITLE, &menu_sel);
        int lr = (in->left && !prev_in.left) || (in->right && !prev_in.right);
        int act = TITLE_MENU[menu_sel % N_TITLE];
        if (confirm_pressed(in) || (lr && (act == MA_MUSIC || act == MA_SFX))) {
            sfx(SFX_SELECT);
            switch (act) {
            case MA_START: new_round(1); gstate = GS_PLAY; state_t = 0; break;
            case MA_MUSIC: music_enabled = !music_enabled; audio_set_music(music_enabled); break;
            case MA_SFX: sfx_enabled = !sfx_enabled; audio_set_sfx(sfx_enabled); break;
            case MA_FS: fs_req = 1; break;
            case MA_QUIT: quit_req = 1; break;
            }
        }
        if (cur_room != 2 * GX) build_room(2 * GX);
        update_particles();
        update_world();
        prev_in = *in;
        return;
    }
    if (gstate == GS_PAUSE) {
        menu_input(in, N_PAUSE, &menu_sel);
        int lr = (in->left && !prev_in.left) || (in->right && !prev_in.right);
        int act = PAUSE_MENU[menu_sel % N_PAUSE];
        if (in->pause && !prev_in.pause) { gstate = GS_PLAY; }
        else if (confirm_pressed(in) || (lr && (act == MA_MUSIC || act == MA_SFX))) {
            sfx(SFX_SELECT);
            switch (act) {
            case MA_RESUME: gstate = GS_PLAY; break;
            case MA_MUSIC: music_enabled = !music_enabled; audio_set_music(music_enabled); break;
            case MA_SFX: sfx_enabled = !sfx_enabled; audio_set_sfx(sfx_enabled); break;
            case MA_FS: fs_req = 1; break;
            case MA_TITLE: gstate = GS_TITLE; menu_sel = 0; world_load(); build_room(2 * GX); break;
            }
        }
        prev_in = *in;
        return;
    }
    if (gstate == GS_GAMEOVER) {
        update_particles();
        if (state_t > 90 && confirm_pressed(in)) { gstate = GS_TITLE; menu_sel = 0; world_load(); build_room(2 * GX); }
        prev_in = *in;
        return;
    }
    if (gstate == GS_ROUND) {
        update_particles();
        if (state_t > 330 || (state_t > 90 && confirm_pressed(in))) {
            round_no++;
            new_round(0);
            gstate = GS_PLAY; state_t = 0;
        }
        prev_in = *in;
        return;
    }

    /* ---------------- GS_PLAY ---------------- */
    if (in->pause && !prev_in.pause) { gstate = GS_PAUSE; menu_sel = 0; prev_in = *in; return; }
    if (lights_need_rebuild) build_lights();
    update_world();
    if (!pl.dead) {
        PIn pi;
        pi.dir = (in->right ? 1 : 0) - (in->left ? 1 : 0);
        pi.up = in->up; pi.down = in->down; pi.run = in->run;
        pi.ljumpP = (in->ljump && !prev_in.ljump);
        pi.upP = in->up && !prev_in.up;
        pi.downP = in->down && !prev_in.down;
        pi.jumpP = in->jump && !prev_in.jump;
        /* ↓ + Richtung: flacher Sprung (wie im Original) */
        if (pi.downP && pi.dir && pl.st == PS_GROUND) {
            int ltx = (int)floorf((pl.x + PW / 2) / TS);
            if (!is_ladder(ltx, (int)floorf((pl.y + PH + 1) / TS))) pi.ljumpP = 1;
        }
        /* ↑ ohne Leiter: hoher Sprung */
        if (pi.upP && pl.st == PS_GROUND) {
            int ltx = (int)floorf((pl.x + PW / 2) / TS);
            if (!is_ladder(ltx, (int)floorf((pl.y + PH - 2) / TS)) && !is_ladder(ltx, (int)floorf((pl.y + 4) / TS))) pi.jumpP = 1;
        }
        float oldx = pl.x, oldy = pl.y;
        int ev = player_step(&pl, &pi);
        float fx = pl.x + PW / 2 - room_ox, fy = pl.y + PH - room_oy;
        if (ev & EV_JUMP) { sfx(SFX_JUMP); puff(fx, fy, 5); }
        if (ev & EV_LJUMP) { sfx(SFX_LJUMP); puff(fx, fy, 6); }
        if (ev & EV_LAND) { sfx(SFX_LAND); puff(fx, fy, 8); }
        if (ev & EV_SPRING) { sfx(SFX_SPRING); puff(fx, fy, 10); }
        if (ev & EV_DOOR) { sfx(SFX_DOOR); shake = 3; show_msg("DIE STEINTÜR GLEITET AUF", 120); }
        if ((ev & EV_LOCKED) && !locked_cool) { sfx(SFX_LOCKED); show_msg("VERSCHLOSSEN – DU BRAUCHST EIN SCHLÜSSEL-ANCH", 140); locked_cool = 90; }
        if (pl.st == PS_GROUND) {
            pl.stepacc += fabsf(pl.x - oldx);
            if (pl.stepacc > (fabsf(pl.vx) > 1.8f ? 13 : 17)) { pl.stepacc = 0; sfx(SFX_STEP); if (fabsf(pl.vx) > 1.8f) puff(fx, fy, 1); }
        } else if (pl.st == PS_CLIMB) {
            pl.stepacc += fabsf(pl.y - oldy);
            if (pl.stepacc > 8) { pl.stepacc = 0; sfx(SFX_CLIMB); }
        }
        if (pl.invuln > 0) pl.invuln--;
        /* Gegenstände */
        for (int i = 0; i < n_items; i++) {
            Item *it = &items[i];
            if (it->taken || it->room != cur_room) continue;
            if (rect_hit(pl.x, pl.y, PW, PH, it->tx * TS + 2, it->ty * TS + 2, 12, 12)) {
                it->taken = 1;
                float ix = it->tx * TS - room_ox + 8, iy = it->ty * TS - room_oy + 8;
                if (it->type == 0) {
                    keys_held++; score += 150; sfx(SFX_KEY);
                    burst(ix, iy, 2.4f, 1.7f, 0.6f, 24, 1.2f);
                    show_msg("SCHLÜSSEL-ANCH GEFUNDEN", 110);
                } else {
                    treasures_got++; lives++; score += 1000; sfx(SFX_TREASURE);
                    burst(ix, iy, 2.8f, 2.0f, 0.7f, 60, 1.8f);
                    char buf[96]; snprintf(buf, sizeof buf, "SONNENAMULETT %d/%d – EIN LEBEN MEHR", treasures_got, n_treasures_total);
                    show_msg(buf, 150);
                    cp_pending = 1;
                }
                lights_dirty();
            }
        }
        /* Gefahren */
        if (hazard_static(&pl) || (pl.invuln <= 0 && hazard_dynamic(&pl))) kill_player();
        /* Raumwechsel */
        if (!pl.dead) {
            int rx = (int)floorf((pl.x + PW / 2) / (RW * TS)), ry = (int)floorf((pl.y + PH / 2) / (RH * TS));
            if (room_exists(rx, ry) && ry * GX + rx != cur_room) enter_room(ry * GX + rx);
            if (cp_pending && pl.st == PS_GROUND && cp_ok()) { cp_x = pl.x; cp_y = pl.y; cp_pending = 0; }
        }
        if (treasures_got >= n_treasures_total && n_treasures_total > 0 && !pl.dead) {
            score += 5000 * round_no;
            gstate = GS_ROUND; state_t = 0; sfx(SFX_ROUND);
        }
    } else {
        pl.deadt++;
        if (pl.deadt == 90) {
            lives--;
            if (lives < 0) { gstate = GS_GAMEOVER; state_t = 0; sfx(SFX_GAMEOVER); lives = 0; }
            else {
                pl.dead = 0; pl.x = cp_x; pl.y = cp_y; pl.vx = pl.vy = 0; pl.st = PS_AIR; pl.invuln = 120;
                int rx = (int)floorf((pl.x + PW / 2) / (RW * TS)), ry = (int)floorf((pl.y + PH / 2) / (RH * TS));
                if (ry * GX + rx != cur_room) enter_room(ry * GX + rx); else fade_t = 14;
            }
        }
    }
    update_particles();
    prev_in = *in;
}

/* ======================================================================= */
/*                              Rendern                                    */
/* ======================================================================= */
static float torch_flicker(int i) {
    float t = gframe * 0.11f + torches[i].seed;
    return 0.82f + 0.12f * sinf(t * 1.7f) * sinf(t * 0.63f) + 0.08f * vnoise(t * 2.3f, torches[i].seed);
}

static void apply_light(const Light *L, float inten) {
    if (inten <= 0.001f) return;
    int x0 = (int)(L->x - L->rad), x1 = (int)(L->x + L->rad), y0 = (int)(L->y - L->rad), y1 = (int)(L->y + L->rad);
    if (x0 < 0) x0 = 0; if (y0 < 0) y0 = 0; if (x1 > VW - 1) x1 = VW - 1; if (y1 > VH - 1) y1 = VH - 1;
    float r2 = L->rad * L->rad, ir = 1.0f / L->rad;
    float cr = L->r * inten, cg = L->g * inten, cb = L->b * inten;
    for (int y = y0; y <= y1; y++) {
        float dy = y + 0.5f - L->y;
        float fy = (y + 0.5f) / TS; int iy = (int)fy; float ty = fy - iy; if (iy >= RH) { iy = RH - 1; ty = 1; }
        for (int x = x0; x <= x1; x++) {
            float dx = x + 0.5f - L->x, d2 = dx * dx + dy * dy;
            if (d2 >= r2) continue;
            float d = sqrtf(d2);
            float att = 1 - d * ir; att *= att;
            float fx = (x + 0.5f) / TS; int ix = (int)fx; float tx = fx - ix; if (ix >= RW) { ix = RW - 1; tx = 1; }
            float v = lerpf(lerpf(L->vis[iy][ix], L->vis[iy][ix + 1], tx), lerpf(L->vis[iy + 1][ix], L->vis[iy + 1][ix + 1], tx), ty);
            if (v <= 0.001f) continue;
            int i = y * VW + x;
            float nx = f_nrm[i * 2], ny = f_nrm[i * 2 + 1];
            float nz = sqrtf(fmaxf(0.0f, 1 - nx * nx - ny * ny));
            float il = 1.0f / sqrtf(d2 + L->h * L->h);
            float ndl = (-dx * nx - dy * ny + L->h * nz) * il;
            ndl = ndl < 0 ? 0 : ndl;
            ndl = 0.2f + 0.8f * ndl;
            float k = att * v * ndl;
            f_lit[i * 3] += cr * k; f_lit[i * 3 + 1] += cg * k; f_lit[i * 3 + 2] += cb * k;
            /* Lichtschein in staubiger Luft */
            float glow = att * att * v * 0.05f;
            f_emi[i * 3] += cr * glow; f_emi[i * 3 + 1] += cg * glow; f_emi[i * 3 + 2] += cb * glow;
        }
    }
}

static void draw_flame(float x, float y, float seed, float scale) {
    float t = gframe * 0.18f + seed;
    for (int py = -10; py <= 1; py++)
        for (int px = -4; px <= 4; px++) {
            float h = -py / 10.0f;
            float wob = sinf(t * 1.3f + h * 4) * 1.2f * h;
            float w = (1 - h) * 3.6f * scale + 0.3f;
            float d = fabsf(px - wob) / w;
            if (d > 1 || h > 1.05f) continue;
            float n = vnoise(px * 0.7f + seed, py * 0.6f - t * 2.2f);
            float k = (1 - d) * (1 - h * 0.85f) * (0.6f + 0.6f * n);
            if (k < 0.12f) continue;
            float hot = clampf(k * 1.4f, 0, 1);
            add_emi((int)(x + px), (int)(y + py), (2.8f + 1.5f * hot) * k, (0.9f + 1.6f * hot * hot) * k, (0.15f + 0.9f * hot * hot * hot) * k);
        }
}

static void draw_hero(int x, int y) {
    int flip = pl.facing < 0;
    if (pl.st == PS_CLIMB) {
        int fr = ((int)pl.anim) & 1;
        spr_draw(HERO_CLIMB, 22, x - 1, y, fr, 1, -99);
        return;
    }
    const char *rows[22];
    for (int i = 0; i < 14; i++) rows[i] = HERO_UPPER[i];
    const char *const *legs = HERO_LEGS_STAND;
    if (pl.st == PS_AIR) legs = HERO_LEGS_JUMP;
    else if (fabsf(pl.vx) > 0.25f) { int f = ((int)pl.anim) & 3; legs = (f == 0 || f == 2) ? HERO_LEGS_WALK1 : HERO_LEGS_WALK2; }
    for (int i = 0; i < 8; i++) rows[14 + i] = legs[i];
    int bob = (pl.st == PS_GROUND && fabsf(pl.vx) < 0.25f && ((gframe / 40) & 1)) ? 1 : 0;
    spr_draw(rows, 22, x - 1, y + bob, flip, 1, -99);
    /* Laterne */
    int lx = flip ? x - 3 : x + 10, ly = y + 12;
    for (int py = 0; py < 5; py++)
        for (int px = 0; px < 3; px++) {
            int frame = py == 0 || py == 4 || px == 0 || px == 2;
            if (frame) put_alb(lx + px, ly + py, 0.05f, 0.04f, 0.03f, 0, 0);
            else { put_alb(lx + px, ly + py, 0.9f, 0.7f, 0.3f, 0, 0); add_emi(lx + px, ly + py, 3.0f, 1.9f, 0.7f); }
        }
}

static void render_scene(int with_player) {
    memcpy(f_alb, s_alb, sizeof(f_alb));
    memcpy(f_nrm, s_nrm, sizeof(f_nrm));
    memcpy(f_emi, s_emi, sizeof(f_emi));
    /* Sterne funkeln */
    if (room_exterior) {
        for (int k = 0; k < 40; k++) {
            int sx = (int)(h01(k, 3) * VW), sy = (int)(h01(k, 9) * 150);
            int i = sy * VW + sx;
            if (s_emi[i * 3 + 2] > 0.3f || f_alb[i * 3] > 0.01f) continue;
            float tw = 0.5f + 0.5f * sinf(gframe * 0.05f + k * 1.7f);
            float b = 0.5f * tw * h01(k, 17);
            add_emi(sx, sy, b, b * 1.05f, b * 1.25f);
        }
    }
    /* Fackelflammen */
    for (int i = 0; i < n_torches; i++) {
        Torch *t = &torches[i];
        if (t->room != cur_room) continue;
        draw_flame(t->tx * TS - room_ox + 8, t->ty * TS - room_oy + 6, t->seed, 1);
    }
    /* Zeitstacheln */
    for (int ty = 0; ty < RH; ty++)
        for (int tx = 0; tx < RW; tx++) {
            int gtx = cur_room % GX * RW + tx, gty = cur_room / GX * RH + ty;
            if (tile(gtx, gty) != 'T') continue;
            float e = tspike_ext(gtx, gframe);
            if (e <= 0.02f) continue;
            for (int k = 0; k < 4; k++) {
                float sc = 2 + k * 4;
                for (int py = 0; py < 13; py++) {
                    float yy = py - (13 - 9 * e);
                    if (yy < 0) continue;
                    float half = yy * 0.24f + 0.3f;
                    for (int px = 0; px < 16; px++) {
                        if (fabsf(px + 0.5f - sc) > half) continue;
                        float side = (px + 0.5f - sc) / (half + 0.01f);
                        put_alb(tx * TS + px, ty * TS + py, 0.85f, 0.55f, 0.22f, side * 0.7f, -0.2f);
                    }
                }
            }
        }
    /* Federn */
    for (int i = 0; i < n_springs; i++) {
        Spring *s = &springs[i];
        if (s->room != cur_room) continue;
        int bx = s->tx * TS - room_ox, by = s->ty * TS - room_oy;
        float c = s->comp;
        int top = (int)(9 + c * 3 - (1 - c) * 0);
        for (int px = 2; px < 14; px++) { put_alb(bx + px, by + 15, 0.08f, 0.06f, 0.05f, 0, -0.5f); put_alb(bx + px, by + top, 0.75f, 0.45f, 0.12f, 0, -0.7f); put_alb(bx + px, by + top + 1, 0.45f, 0.26f, 0.06f, 0, 0.4f); }
        for (int py = top + 2; py < 15; py++) {
            int ph = (py - top) % 3;
            int x0 = ph == 0 ? 4 : 5, x1 = ph == 0 ? 11 : 10;
            put_alb(bx + x0, by + py, 0.4f, 0.4f, 0.42f, -0.6f, 0);
            put_alb(bx + x1, by + py, 0.4f, 0.4f, 0.42f, 0.6f, 0);
            if (ph == 1) for (int px = x0; px <= x1; px++) put_alb(bx + px, by + py, 0.3f, 0.3f, 0.33f, 0, 0.3f);
        }
    }
    /* Türen */
    for (int i = 0; i < n_doors; i++) {
        Door *d = &doors[i];
        if (d->room != cur_room || (d->open && d->anim >= 1)) continue;
        int bx = d->tx * TS - room_ox, by = d->ty * TS - room_oy;
        int hh = d->h * TS;
        int off = (int)(d->anim * hh);
        for (int py = 0; py < hh; py++) {
            int sy = by + py - off;
            if (sy < by) continue;
            for (int px = 1; px < 15; px++) {
                float nz = fbm((bx + px) * 0.3f + i * 7, py * 0.3f);
                float k = 0.8f + 0.35f * nz;
                float r = 0.32f * k, g = 0.22f * k, b = 0.12f * k;
                float nx = 0, ny = 0;
                if (px == 1) nx = -0.6f; if (px == 14) nx = 0.6f;
                if (py == 0) ny = -0.6f; if (py == hh - 1) ny = 0.6f;
                if (px == 3 || px == 12) { r *= 0.5f; g *= 0.5f; b *= 0.5f; }
                float dx = px - 7.5f, dy = py - hh * 0.5f, dd = sqrtf(dx * dx + dy * dy);
                if (dd < 4.6f) {
                    r = 0.85f; g = 0.52f; b = 0.12f; nx = dx / 6; ny = dy / 6;
                    if (dd < 2.2f) { r = 0.5f; g = 0.05f; b = 0.03f; if (!d->open) add_emi(bx + px, sy, 0.9f, 0.08f, 0.04f); }
                } else if (dd < 7.0f && ((int)(atan2f(dy, dx) * 2.6f + 20) % 2) == 0 && dd > 5.2f) {
                    r = 0.7f; g = 0.42f; b = 0.1f;
                }
                put_alb(bx + px, sy, r, g, b, nx, ny);
            }
        }
    }
    /* Gegenstände */
    for (int i = 0; i < n_items; i++) {
        Item *it = &items[i];
        if (it->room != cur_room || it->taken) continue;
        float bob = sinf(gframe * 0.06f + i) * 1.5f;
        int x = it->tx * TS - room_ox, y = it->ty * TS - room_oy + (int)bob;
        if (it->type == 0) {
            spr_draw(KEY_SPR, 12, x + 3, y + 2, 0, 1, -99);
            add_emi(x + 7, y + 3, 0.6f, 0.45f, 0.15f);
        } else {
            spr_draw(TREASURE_SPR, 11, x + 2, y + 2, 0, 1, -99);
            /* Strahlenkranz */
            float cxp = x + 8, cyp = y + 7.5f;
            for (int k = 0; k < 12; k++) {
                float a = k * 0.5236f + gframe * 0.01f;
                for (int r = 8; r < 13; r++) {
                    float fade = (13 - r) / 5.0f * (0.6f + 0.4f * sinf(gframe * 0.08f + k));
                    add_emi((int)(cxp + cosf(a) * r), (int)(cyp + sinf(a) * r), 0.5f * fade, 0.32f * fade, 0.08f * fade);
                }
            }
        }
    }
    /* Laser */
    for (int i = 0; i < n_lasers; i++) {
        Laser *L = &lasers[i];
        if (L->room != cur_room) continue;
        int ex = L->tx * TS - room_ox, ey = L->ty * TS - room_oy;
        int on = laser_on(L, gframe), warn = laser_warn(L, gframe);
        float gem = on ? 3.0f : warn ? ((gframe / 4) & 1 ? 2.2f : 0.3f) : 0.35f;
        for (int py = 5; py < 11; py++) for (int px = 5; px < 11; px++) {
            float dd = (px - 7.5f) * (px - 7.5f) + (py - 7.5f) * (py - 7.5f);
            if (dd < 7.5f) add_emi(ex + px, ey + py, gem, gem * 0.08f, gem * 0.04f);
        }
        if (on) {
            float x, y, w, h; laser_rect(L, &x, &y, &w, &h);
            x -= room_ox; y -= room_oy;
            float wob = 0.8f + 0.2f * sinf(gframe * 0.9f);
            if (L->dir < 2) {
                for (int px = (int)x; px < (int)(x + w); px++)
                    for (int k = -3; k <= 3; k++) {
                        float core = expf(-k * k * 0.5f) * wob;
                        add_emi(px, (int)(y + 2) + k, 3.5f * core, (0.25f + (abs(k) < 1 ? 1.2f : 0)) * core, (0.12f + (abs(k) < 1 ? 0.9f : 0)) * core);
                    }
            } else {
                for (int py = (int)y; py < (int)(y + h); py++)
                    for (int k = -3; k <= 3; k++) {
                        float core = expf(-k * k * 0.5f) * wob;
                        add_emi((int)(x + 2) + k, py, 3.5f * core, (0.25f + (abs(k) < 1 ? 1.2f : 0)) * core, (0.12f + (abs(k) < 1 ? 0.9f : 0)) * core);
                    }
            }
        }
    }
    /* Gegner */
    for (int i = 0; i < n_enemies; i++) {
        Enemy *e = &enemies[i];
        if (e->room != cur_room) continue;
        int x = (int)(e->x - room_ox), y = (int)(e->y - room_oy);
        int fr = ((int)e->anim) & 1;
        if (e->type == EN_BAT) spr_draw(fr ? BAT_B : BAT_A, 8, x - 1, y - 1, e->vx < 0, 1, -99);
        else if (e->type == EN_SCARAB) spr_draw(fr ? SCARAB_B : SCARAB_A, 8, x - 1, y - 1, e->vx < 0, 1, -99);
        else {
            const char *rows[22];
            for (int k = 0; k < 16; k++) rows[k] = MUMMY_UP[k];
            for (int k = 0; k < 6; k++) rows[16 + k] = ((int)(e->anim * 0.5f) & 1) ? MUMMY_LEGS_B[k] : MUMMY_LEGS_A[k];
            spr_draw(rows, 22, x - 1, y, e->vx < 0, 1, -99);
        }
    }
    /* Spieler */
    if (with_player && !pl.dead && !(pl.invuln > 0 && (gframe / 4) % 2 == 0 && pl.invuln < 110)) draw_hero((int)(pl.x - room_ox), (int)(pl.y - room_oy));
    /* Partikel */
    for (int i = 0; i < n_parts; i++) {
        Part *p = &parts[i];
        float a = clampf(p->life / (p->max * 0.3f), 0, 1);
        int x = (int)p->x, y = (int)p->y;
        switch (p->kind) {
        case PT_DUST: {
            float tw = 0.35f * a * clampf((p->max - p->life) / 60.0f, 0, 1);
            if (x >= 0 && y >= 0 && x < VW && y < VH) {
                int i2 = y * VW + x;
                if (f_alb[i2 * 3] < 0.6f) blend_alb(x, y, 1.0f, 0.9f, 0.75f, tw);
            }
            break;
        }
        case PT_SAND: blend_alb(x, y, p->r, p->g, p->b, 0.8f * a); break;
        case PT_PUFF: {
            int s = (int)p->size;
            for (int yy = -s; yy <= s; yy++) for (int xx = -s; xx <= s; xx++)
                if (xx * xx + yy * yy <= s * s) blend_alb(x + xx, y + yy, p->r, p->g, p->b, 0.25f * a);
            break;
        }
        case PT_SPARK: case PT_BURST: case PT_GLINT: {
            float k = a * (p->kind == PT_GLINT ? sinf((1 - p->life / p->max) * 3.14159f) : 1);
            add_emi(x, y, p->r * k, p->g * k, p->b * k);
            if (p->kind == PT_GLINT) { add_emi(x + 1, y, p->r * k * 0.4f, p->g * k * 0.4f, p->b * k * 0.4f); add_emi(x - 1, y, p->r * k * 0.4f, p->g * k * 0.4f, p->b * k * 0.4f); add_emi(x, y + 1, p->r * k * 0.4f, p->g * k * 0.4f, p->b * k * 0.4f); add_emi(x, y - 1, p->r * k * 0.4f, p->g * k * 0.4f, p->b * k * 0.4f); }
            break;
        }
        case PT_BIT: put_alb(x, y, p->r, p->g, p->b, 0, -0.3f); if (p->size > 1) put_alb(x + 1, y, p->r, p->g, p->b, 0, 0); break;
        }
    }

    /* ---------- Licht ---------- */
    float amb_r = 0.026f, amb_g = 0.024f, amb_b = 0.040f;
    if (room_exterior) { amb_r = 0.03f; amb_g = 0.035f; amb_b = 0.06f; }
    for (int i = 0; i < NPIX; i++) { f_lit[i * 3] = amb_r; f_lit[i * 3 + 1] = amb_g; f_lit[i * 3 + 2] = amb_b; }
    for (int i = 0; i < n_slights; i++) {
        Light *L = &slights[i];
        float in = 1;
        switch (L->kind) {
        case LK_TORCH: in = 1.55f * torch_flicker(L->ref); break;
        case LK_MOON: in = 1.0f; break;
        case LK_ITEM: if (items[L->ref].taken) in = 0; else in = items[L->ref].type ? 0.9f + 0.25f * sinf(gframe * 0.08f) : 0.45f; break;
        case LK_LASER: in = laser_on(&lasers[L->ref], gframe) ? 1.1f : 0; break;
        case LK_EMIT: in = laser_on(&lasers[L->ref], gframe) ? 1.2f : laser_warn(&lasers[L->ref], gframe) ? ((gframe / 4) & 1) * 0.9f : 0.15f; break;
        case LK_DOORSEAL: in = doors[L->ref].open ? 0 : 0.35f; break;
        }
        apply_light(L, in);
    }
    if (with_player && !pl.dead) {
        Light *L = &plight;
        L->kind = LK_PLAYER;
        L->x = pl.x - room_ox + (pl.facing < 0 ? -2 : 11) + 0.5f; L->y = pl.y - room_oy + 14;
        L->r = 1.0f; L->g = 0.72f; L->b = 0.38f; L->rad = 105; L->h = 16;
        compute_vis(L);
        float fl = 0.92f + 0.06f * sinf(gframe * 0.21f) + 0.04f * sinf(gframe * 0.53f);
        apply_light(L, 1.15f * fl);
    }
    if (pl.dead && with_player) {
        Light L; memset(&L, 0, sizeof L);
        L.x = pl.x - room_ox + 5; L.y = pl.y - room_oy + 11; L.r = 1; L.g = 0.5f; L.b = 0.2f; L.rad = 120; L.h = 20;
        compute_vis(&L);
        apply_light(&L, 2.5f * expf(-pl.deadt * 0.06f));
    }
    /* Zusammensetzen */
    for (int i = 0; i < NPIX * 3; i++) f_col[i] = f_alb[i] * f_lit[i] + f_emi[i];
}

static void post_process(unsigned int *fb, float fade, int title_dim) {
    /* Bloom: Helligkeit herausziehen und verkleinern */
    for (int by = 0; by < BH; by++)
        for (int bx = 0; bx < BW; bx++) {
            float r = 0, g = 0, b = 0;
            for (int y = 0; y < 4; y++)
                for (int x = 0; x < 4; x++) {
                    int i = ((by * 4 + y) * VW + bx * 4 + x) * 3;
                    float lr = f_col[i], lg = f_col[i + 1], lb = f_col[i + 2];
                    float l = 0.3f * lr + 0.6f * lg + 0.1f * lb;
                    float k = l > 0.55f ? (l - 0.55f) / (l + 0.001f) : 0;
                    r += lr * k; g += lg * k; b += lb * k;
                }
            int o = (by * BW + bx) * 3;
            bl_a[o] = r / 16; bl_a[o + 1] = g / 16; bl_a[o + 2] = b / 16;
        }
    for (int pass = 0; pass < 3; pass++) {
        int R = 2 + pass;
        for (int y = 0; y < BH; y++)
            for (int x = 0; x < BW; x++) {
                float r = 0, g = 0, b = 0; int n = 0;
                for (int k = -R; k <= R; k++) { int xx = x + k; if (xx < 0 || xx >= BW) continue; int o = (y * BW + xx) * 3; r += bl_a[o]; g += bl_a[o + 1]; b += bl_a[o + 2]; n++; }
                int o = (y * BW + x) * 3; bl_b[o] = r / n; bl_b[o + 1] = g / n; bl_b[o + 2] = b / n;
            }
        for (int y = 0; y < BH; y++)
            for (int x = 0; x < BW; x++) {
                float r = 0, g = 0, b = 0; int n = 0;
                for (int k = -R; k <= R; k++) { int yy = y + k; if (yy < 0 || yy >= BH) continue; int o = (yy * BW + x) * 3; r += bl_b[o]; g += bl_b[o + 1]; b += bl_b[o + 2]; n++; }
                int o = (y * BW + x) * 3; bl_a[o] = r / n; bl_a[o + 1] = g / n; bl_a[o + 2] = b / n;
            }
    }
    int sx = shake > 0 ? (int)(frnds() * shake) : 0, sy = shake > 0 ? (int)(frnds() * shake) : 0;
    float exposure = 1.35f;
    for (int y = 0; y < VH; y++) {
        float fy = (y + 0.5f) / 4 - 0.5f; int y0 = (int)floorf(fy); float ty = fy - y0;
        int y0c = y0 < 0 ? 0 : y0, y1c = y0 + 1 >= BH ? BH - 1 : y0 + 1;
        if (y0c >= BH) y0c = BH - 1;
        for (int x = 0; x < VW; x++) {
            int sxp = x - sx, syp = y - sy;
            if (sxp < 0) sxp = 0; if (sxp >= VW) sxp = VW - 1; if (syp < 0) syp = 0; if (syp >= VH) syp = VH - 1;
            int i = (syp * VW + sxp) * 3;
            float fx = (x + 0.5f) / 4 - 0.5f; int x0 = (int)floorf(fx); float tx = fx - x0;
            int x0c = x0 < 0 ? 0 : x0, x1c = x0 + 1 >= BW ? BW - 1 : x0 + 1;
            if (x0c >= BW) x0c = BW - 1;
            float c[3];
            for (int k = 0; k < 3; k++) {
                float b = lerpf(lerpf(bl_a[(y0c * BW + x0c) * 3 + k], bl_a[(y0c * BW + x1c) * 3 + k], tx),
                                lerpf(bl_a[(y1c * BW + x0c) * 3 + k], bl_a[(y1c * BW + x1c) * 3 + k], tx), ty);
                float v = (f_col[i + k] + b * 0.9f) * exposure;
                v = (v * (2.51f * v + 0.03f)) / (v * (2.43f * v + 0.59f) + 0.14f);
                c[k] = v;
            }
            /* Farbstimmung: Schatten ins Kühle, Lichter warm */
            float l = 0.3f * c[0] + 0.6f * c[1] + 0.1f * c[2];
            float sh = clampf(1 - l * 3, 0, 1);
            c[0] = c[0] * (1 - 0.06f * sh); c[2] = c[2] + 0.012f * sh;
            /* Vignette */
            float vx = (x - VW * 0.5f) / (VW * 0.5f), vy = (y - VH * 0.5f) / (VH * 0.5f);
            float vig = 1 - 0.38f * (vx * vx * 0.8f + vy * vy) * 0.8f;
            float f = fade * vig * (title_dim ? 0.55f + 0.45f * clampf(1 - fabsf(vy + 0.2f), 0, 1) : 1);
            for (int k = 0; k < 3; k++) c[k] *= f;
            unsigned int px = lin2srgb_u(c[0], c[1], c[2]);
            int gn = (int)(hash2(x + gframe * 131, y * 7 + gframe * 17) % 5) - 2;
            int R = ((px >> 16) & 255) + gn, G = ((px >> 8) & 255) + gn, B = (px & 255) + gn;
            R = R < 0 ? 0 : R > 255 ? 255 : R; G = G < 0 ? 0 : G > 255 ? 255 : G; B = B < 0 ? 0 : B > 255 ? 255 : B;
            fb[(y + HUD_H) * SCR_W + x] = (R << 16) | (G << 8) | B;
        }
    }
}

static void draw_hud(unsigned int *fb) {
    for (int y = 0; y < HUD_H; y++) {
        float k = 1 - y / (float)HUD_H * 0.4f;
        unsigned int c = ((int)(22 * k) << 16) | ((int)(14 * k) << 8) | (int)(8 * k);
        for (int x = 0; x < SCR_W; x++) fb[y * SCR_W + x] = c;
    }
    for (int x = 0; x < SCR_W; x++) {
        float g = 0.6f + 0.4f * sinf(x * 0.05f);
        fb[(HUD_H - 1) * SCR_W + x] = ((int)(150 * g) << 16) | ((int)(100 * g) << 8) | (int)(30 * g);
    }
    char buf[64];
    spr_srgb(fb, HERO_UPPER, 8, 6, 5, 2.2f);
    snprintf(buf, sizeof buf, "×%d", lives); text_srgb(fb, 21, 7, buf, 1, 0xE8D8B0, 1);
    spr_srgb(fb, KEY_SPR, 12, 46, 4, 1.4f);
    snprintf(buf, sizeof buf, "×%d", keys_held); text_srgb(fb, 58, 7, buf, 1, 0xE8D8B0, 1);
    spr_srgb(fb, TREASURE_SPR, 11, 82, 5, 1.4f);
    snprintf(buf, sizeof buf, "%d/%d", treasures_got, n_treasures_total); text_srgb(fb, 97, 7, buf, 1, 0xF0C860, 1);
    if (cur_room >= 0) {
        const char *nm = ROOM_NAME[cur_room / GX][cur_room % GX];
        if (nm) text_srgb_c(fb, SCR_W / 2 + 8, 7, nm, 1, 0xC8A878, 1);
    }
    snprintf(buf, sizeof buf, "%07d", score); text_srgb(fb, SCR_W - 6 - text_width(buf, 1, 1), 7, buf, 1, 0xF0D890, 1);
    if (audio_ok) {
        text_srgb(fb, SCR_W - 92, 7, "♪", 1, music_enabled ? 0xE0B050 : 0x403020, 0);
        text_srgb(fb, SCR_W - 82, 7, "FX", 1, sfx_enabled ? 0xE0B050 : 0x403020, 0);
    }
    if (round_no > 1) { snprintf(buf, sizeof buf, "D%d", round_no); text_srgb(fb, 122, 7, buf, 1, 0xB07040, 1); }
}

static void draw_menu(unsigned int *fb, const char **items, int n, int sel, int cy) {
    int w = 200, h = n * 16 + 14;
    fill_rect_srgb(fb, SCR_W / 2 - w / 2, cy - 8, w, h, 0x0A0604, 0.72f);
    for (int x = SCR_W / 2 - w / 2; x < SCR_W / 2 + w / 2; x++) { fb[(cy - 8) * SCR_W + x] = 0x8A6020; fb[(cy - 8 + h) * SCR_W + x] = 0x8A6020; }
    for (int i = 0; i < n; i++) {
        int y = cy + i * 16;
        unsigned int col = i == sel ? 0xFFD870 : 0xA08868;
        text_srgb_c(fb, SCR_W / 2, y, items[i], 1, col, 1);
        if (i == sel) {
            int tw = text_width(items[i], 1, 1);
            float p = sinf(gframe * 0.15f) * 2;
            text_srgb(fb, SCR_W / 2 - tw / 2 - 16 - (int)p, y, "→", 1, 0xFFC040, 0);
            text_srgb(fb, SCR_W / 2 + tw / 2 + 10 + (int)p, y, "←", 1, 0xFFC040, 0);
        }
    }
}

void game_render(unsigned int *fb) {
    float fade = 1 - fade_t / 14.0f;
    if (gstate == GS_TITLE) {
        render_scene(0);
        /* Titel glüht im Emissionspuffer */
        const char *t = "SONNENGRAB";
        int sc = 5, tw = text_width(t, sc, sc);
        int tx = VW / 2 - tw / 2, ty = 30;
        float pulse = 0.85f + 0.15f * sinf(gframe * 0.04f);
        text_emi(tx + 3, ty + 3, t, sc, 0.02f, 0.01f, 0.0f, 0);
        text_emi(tx, ty, t, sc, 2.2f * pulse, 1.25f * pulse, 0.35f * pulse, 1.2f);
        for (int i = 0; i < NPIX * 3; i++) f_col[i] = f_alb[i] * f_lit[i] + f_emi[i];
        post_process(fb, 1, 0);
        for (int y = 0; y < HUD_H; y++) for (int x = 0; x < SCR_W; x++) fb[y * SCR_W + x] = 0;
        text_srgb_c(fb, SCR_W / 2, HUD_H + 72, "DAS GRAB DES SONNENKÖNIGS", 1, 0xD8B888, 1);
        const char *items[8];
        for (int i = 0; i < N_TITLE; i++) items[i] = menu_label(TITLE_MENU[i]);
        draw_menu(fb, items, N_TITLE, menu_sel % N_TITLE, HUD_H + 112);
        text_srgb_c(fb, SCR_W / 2, SCR_H - 34, "←→ LAUFEN   SHIFT RENNEN   ↑↓ KLETTERN", 1, 0x907860, 1);
        text_srgb_c(fb, SCR_W / 2, SCR_H - 23, "LEERTASTE HOCHSPRUNG   X ODER ↓+RICHTUNG WEITSPRUNG", 1, 0x907860, 1);
#ifdef SAALBURG
        text_srgb_c(fb, SCR_W / 2, SCR_H - 12, audio_ok ? "M MUSIK   N EFFEKTE   ESC MENÜ   SUPER+Q BEENDEN" : "ESC MENÜ   SUPER+1 VOLLBILD   SUPER+Q BEENDEN", 1, 0x705A48, 1);
#else
        text_srgb_c(fb, SCR_W / 2, SCR_H - 12, "M MUSIK   N EFFEKTE   F11 VOLLBILD   ESC MENÜ", 1, 0x705A48, 1);
#endif
        return;
    }
    render_scene(1);
    float dim = 1;
    if (gstate == GS_PAUSE) dim = 0.45f;
    if (gstate == GS_GAMEOVER) dim = 0.4f + 0.6f * expf(-state_t * 0.03f);
    post_process(fb, fade * dim, 0);
    draw_hud(fb);
    if (banner_t > 0 && banner_text && gstate == GS_PLAY) {
        float a = clampf(banner_t / 30.0f, 0, 1) * clampf((170 - banner_t) / 20.0f, 0, 1);
        int c = (int)(a * 255);
        unsigned int col = ((c * 232 / 255) << 16) | ((c * 200 / 255) << 8) | (c * 140 / 255);
        if (a > 0.05f) text_srgb_c(fb, SCR_W / 2, SCR_H - 26, banner_text, 2, col, 1);
    }
    if (msg_t > 0 && gstate == GS_PLAY) {
        float a = clampf(msg_t / 25.0f, 0, 1);
        int c = (int)(a * 255);
        unsigned int col = ((c * 255 / 255) << 16) | ((c * 210 / 255) << 8) | (c * 120 / 255);
        text_srgb_c(fb, SCR_W / 2, HUD_H + 10, msg_text, 1, col, 1);
    }
    if (gstate == GS_PAUSE) {
        text_srgb_c(fb, SCR_W / 2, HUD_H + 50, "PAUSE", 3, 0xF0C860, 1);
        const char *items[8];
        for (int i = 0; i < N_PAUSE; i++) items[i] = menu_label(PAUSE_MENU[i]);
        draw_menu(fb, items, N_PAUSE, menu_sel % N_PAUSE, HUD_H + 100);
    }
    if (gstate == GS_GAMEOVER) {
        text_srgb_c(fb, SCR_W / 2, HUD_H + 80, "SPIEL VORBEI", 4, 0xE07040, 1);
        char buf[64]; snprintf(buf, sizeof buf, "PUNKTE: %d   AMULETTE: %d/%d", score, treasures_got, n_treasures_total);
        text_srgb_c(fb, SCR_W / 2, HUD_H + 130, buf, 1, 0xE8D0A0, 1);
        if (state_t > 90 && (gframe / 30) % 2) text_srgb_c(fb, SCR_W / 2, HUD_H + 160, "ENTER – ZUM TITELBILD", 1, 0xC0A070, 1);
    }
    if (gstate == GS_ROUND) {
        text_srgb_c(fb, SCR_W / 2, HUD_H + 70, "ALLE AMULETTE GEBORGEN!", 2, 0xFFD870, 1);
        text_srgb_c(fb, SCR_W / 2, HUD_H + 100, "DER SONNENKÖNIG ERWACHT ...", 1, 0xE0C090, 1);
        char buf[64]; snprintf(buf, sizeof buf, "BONUS %d   –   DURCHGANG %d BEGINNT", 5000 * round_no, round_no + 1);
        text_srgb_c(fb, SCR_W / 2, HUD_H + 120, buf, 1, 0xC0A070, 1);
    }
}

/* Fenstersymbol: Sonnenamulett */
void game_icon(unsigned int *argb, int size) {
    for (int y = 0; y < size; y++)
        for (int x = 0; x < size; x++) {
            int sx = x * 12 / size, sy = y * 12 / size;
            argb[y * size + x] = 0;
            if (sy >= 11) continue;
            PalE p;
            if (!pal_lookup(TREASURE_SPR[sy][sx], &p)) continue;
            argb[y * size + x] = 0xFF000000u | lin2srgb_u(p.r * 1.3f + p.er * 0.3f, p.g * 1.3f + p.eg * 0.3f, p.b * 1.3f + p.eb * 0.3f);
        }
}
