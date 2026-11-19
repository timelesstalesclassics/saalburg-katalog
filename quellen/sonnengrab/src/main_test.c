/* Prüfprogramm (Linux): Lösbarkeit, Screenshots, Audio, Laufzeit */
#include "game.c"
#include <time.h>

static unsigned int fb[SCR_W * SCR_H];

static void write_ppm(const char *path) {
    FILE *f = fopen(path, "wb");
    fprintf(f, "P6\n%d %d\n255\n", SCR_W, SCR_H);
    for (int i = 0; i < SCR_W * SCR_H; i++) { unsigned char c[3] = { (fb[i] >> 16) & 255, (fb[i] >> 8) & 255, fb[i] & 255 }; fwrite(c, 1, 3, f); }
    fclose(f);
}

static int check_rows(const char *name, const char *const *rows, int n) {
    int w = (int)strlen(rows[0]), bad = 0;
    for (int i = 0; i < n; i++) if ((int)strlen(rows[i]) != w) { printf("SPRITE %s Zeile %d: Breite %d statt %d\n", name, i, (int)strlen(rows[i]), w); bad = 1; }
    return bad;
}

/* ------------------------- Lösbarkeitsprüfung ------------------------- */
#define MAXS 20000
typedef struct { short tx, ty; char climb; } SState;
static SState sq[MAXS]; static int nsq;
static unsigned char seen[WORLD_H][WORLD_W][2];
static unsigned char item_seen[64];
static unsigned char door_seen[32];
static int sim_frames_total = 0;

static void place(Player *p, int tx, int ty, int climb) {
    memset(p, 0, sizeof(*p));
    p->x = tx * TS + 8 - PW * 0.5f; p->y = (ty + 1) * TS - PH; p->facing = 1;
    p->st = climb ? PS_CLIMB : PS_GROUND;
}
static void mark_items(const Player *p) {
    for (int i = 0; i < n_items; i++)
        if (rect_hit(p->x, p->y, PW, PH, items[i].tx * TS + 2, items[i].ty * TS + 2, 12, 12)) item_seen[i] = 1;
}
static int cur_from = -1;
#define MAXEDGE 200000
static int edge_a[MAXEDGE], edge_b[MAXEDGE], nedge;
static short sidx[WORLD_H][WORLD_W][2];
static void push_state(const Player *p) {
    int tx = (int)floorf((p->x + PW * 0.5f) / TS), ty = (int)floorf((p->y + PH - 1) / TS);
    int c = p->st == PS_CLIMB;
    if (tx < 0 || ty < 0 || tx >= WORLD_W || ty >= WORLD_H) return;
    if (seen[ty][tx][c]) { if (cur_from >= 0 && nedge < MAXEDGE) { edge_a[nedge] = cur_from; edge_b[nedge++] = sidx[ty][tx][c]; } return; }
    seen[ty][tx][c] = 1;
    if (nsq < MAXS) { sidx[ty][tx][c] = nsq; if (cur_from >= 0 && nedge < MAXEDGE) { edge_a[nedge] = cur_from; edge_b[nedge++] = nsq; } sq[nsq].tx = tx; sq[nsq].ty = ty; sq[nsq].climb = c; nsq++; }
}
/* mode: 0 gehen,1 rennen,2 hoch(gehen),3 hoch(rennen),4 flach,5 klettern hoch,6 klettern runter,7 seitlich abspringen */
static void run_macro(int tx, int ty, int climb, int mode, int dir) {
    Player p; place(&p, tx, ty, climb);
    sim_mode = 1;
    int sx = tx;
    float sy = p.y;
    for (int f = 0; f < 240; f++) {
        PIn in; memset(&in, 0, sizeof in);
        in.dir = dir;
        if (mode == 1 || mode == 3) in.run = 1;
        if ((mode == 2 || mode == 3) && f == 0) in.jumpP = 1;
        if (mode == 4 && f == 0) in.ljumpP = 1;
        if (mode == 5) { in.up = 1; in.dir = 0; }
        if (mode == 6) { in.down = 1; in.dir = 0; }
        sim_door = -1;
        player_step(&p, &in);
        sim_frames_total++;
        if (sim_door >= 0) door_seen[sim_door] = 1;
        mark_items(&p);
        if (hazard_static(&p)) { sim_mode = 0; return; }
        int ctx = (int)floorf((p.x + PW * 0.5f) / TS);
        if (mode <= 1) {
            if (p.st == PS_GROUND && ctx != sx && fabsf(p.x + PW * 0.5f - (ctx * TS + 8)) < 2.5f) break;
            if (p.st == PS_GROUND && f > 30 && ctx == sx) { sim_mode = 0; return; } /* blockiert */
        } else if (mode >= 2 && mode <= 4) {
            if (f > 2 && p.st != PS_AIR) break;
        } else if (mode == 5 || mode == 6) {
            if (p.st != PS_CLIMB && f > 0) break;
            if (fabsf(p.y - sy) >= 16) break;
        } else if (mode == 7) {
            if (f > 2 && p.st != PS_AIR) break;
        }
        if (f == 239) { sim_mode = 0; return; }
    }
    /* ausruhen bis stabil */
    for (int f = 0; f < 120 && p.st == PS_AIR; f++) {
        PIn in; memset(&in, 0, sizeof in);
        player_step(&p, &in); mark_items(&p);
        if (hazard_static(&p)) { sim_mode = 0; return; }
    }
    sim_mode = 0;
    if (p.st == PS_AIR) return;
    push_state(&p);
}
static void reach(int stx, int sty) {
    memset(seen, 0, sizeof seen); nsq = 0; nedge = 0; cur_from = -1;
    Player p; place(&p, stx, sty, 0); push_state(&p); mark_items(&p);
    for (int qi = 0; qi < nsq; qi++) {
        SState s = sq[qi];
        cur_from = qi;
        if (!s.climb) {
            for (int d = -1; d <= 1; d += 2) { run_macro(s.tx, s.ty, 0, 0, d); run_macro(s.tx, s.ty, 0, 1, d); run_macro(s.tx, s.ty, 0, 4, d); }
            for (int d = -1; d <= 1; d++) { run_macro(s.tx, s.ty, 0, 2, d); run_macro(s.tx, s.ty, 0, 3, d); }
            run_macro(s.tx, s.ty, 0, 5, 0); run_macro(s.tx, s.ty, 0, 6, 0);
        } else {
            run_macro(s.tx, s.ty, 1, 5, 0); run_macro(s.tx, s.ty, 1, 6, 0);
            run_macro(s.tx, s.ty, 1, 7, -1); run_macro(s.tx, s.ty, 1, 7, 1);
        }
    }
}
static int validate(int rnd) {
    round_no = rnd;
    world_load();
    memset(item_seen, 0, sizeof item_seen);
    int opened[32] = { 0 }, nopen = 0;
    int stx = (int)((start_x + PW / 2) / TS), sty = (int)((start_y + PH - 1) / TS);
    for (;;) {
        memset(door_seen, 0, sizeof door_seen);
        reach(stx, sty);
        int keys = 0;
        for (int i = 0; i < n_items; i++) if (item_seen[i] && items[i].type == 0) keys++;
        int avail = keys - nopen, progressed = 0;
        for (int d = 0; d < n_doors && avail > 0; d++)
            if (door_seen[d] && !opened[d]) {
                opened[d] = 1; nopen++; avail--; progressed = 1;
                for (int k = 0; k < doors[d].h; k++) world[doors[d].ty + k][doors[d].tx] = ' ';
                printf("  öffne Tür %d (Raum %d,%d)\n", d, doors[d].room % GX, doors[d].room / GX);
            }
        if (!progressed) break;
    }
    /* Sackgassen: Zustände, von denen der Start nicht mehr erreichbar ist */
    {
        static unsigned char back[MAXS]; memset(back, 0, sizeof back); back[0] = 1;
        int ch = 1;
        while (ch) { ch = 0; for (int e = 0; e < nedge; e++) if (back[edge_b[e]] && !back[edge_a[e]]) { back[edge_a[e]] = 1; ch = 1; } }
        int nd = 0;
        for (int i = 0; i < nsq; i++) if (!back[i]) { if (nd < 40) printf("  SACKGASSE Raum (%d,%d) Kachel (%d,%d)%s\n", sq[i].tx / RW, sq[i].ty / RH, sq[i].tx % RW, sq[i].ty % RH, sq[i].climb ? " Leiter" : ""); nd++; }
        printf("  Sackgassen: %d\n", nd);
    }
    int tr = 0, ks = 0, bad = 0;
    for (int i = 0; i < n_items; i++) {
        if (item_seen[i]) { if (items[i].type) tr++; else ks++; }
        else { printf("  NICHT ERREICHBAR: %s in Raum (%d,%d) Kachel (%d,%d)\n", items[i].type ? "Schatz" : "Schlüssel", items[i].room % GX, items[i].room / GX, items[i].tx % RW, items[i].ty % RH); if (items[i].type) bad = 1; }
    }
    for (int d = 0; d < n_doors; d++) if (!opened[d]) printf("  Tür %d (Raum %d,%d) bleibt zu\n", d, doors[d].room % GX, doors[d].room / GX);
    printf("Durchgang %d: Schätze %d/%d, Schlüssel %d, Türen %d/%d, Zustände %d\n", rnd, tr, n_treasures_total, ks, nopen, n_doors, nsq);
    return bad;
}
static void print_reach_map(void) {
    for (int ry = 0; ry < GY; ry++) {
        for (int y = 0; y < RH; y++) {
            for (int rx = 0; rx < GX; rx++) {
                for (int x = 0; x < RW; x++) {
                    int gx = rx * RW + x, gy = ry * RH + y;
                    char c = world[gy][gx];
                    if (seen[gy][gx][0]) c = 'o';
                    else if (seen[gy][gx][1]) c = '+';
                    putchar(c);
                }
                putchar('|');
            }
            putchar('\n');
        }
        for (int i = 0; i < GX * (RW + 1); i++) putchar('-');
        putchar('\n');
    }
}

int main(int argc, char **argv) {
    int bad = 0;
    bad |= check_rows("HERO_UPPER", HERO_UPPER, 14); bad |= check_rows("STAND", HERO_LEGS_STAND, 8);
    bad |= check_rows("WALK1", HERO_LEGS_WALK1, 8); bad |= check_rows("WALK2", HERO_LEGS_WALK2, 8);
    bad |= check_rows("JUMP", HERO_LEGS_JUMP, 8); bad |= check_rows("CLIMB", HERO_CLIMB, 22);
    bad |= check_rows("MUMMY", MUMMY_UP, 16); bad |= check_rows("MLA", MUMMY_LEGS_A, 6); bad |= check_rows("MLB", MUMMY_LEGS_B, 6);
    bad |= check_rows("BATA", BAT_A, 8); bad |= check_rows("BATB", BAT_B, 8);
    bad |= check_rows("SCA", SCARAB_A, 8); bad |= check_rows("SCB", SCARAB_B, 8);
    bad |= check_rows("KEY", KEY_SPR, 12); bad |= check_rows("TRE", TREASURE_SPR, 11);
    for (int g = 0; g < 7; g++) bad |= check_rows("GLYPH", GLYPHS[g], 9);
    if (strlen(HERO_UPPER[0]) != 12 || strlen(MUMMY_LEGS_A[0]) != 12) { printf("Breite Held/Mumie falsch\n"); bad = 1; }
    printf("Sprites %s\n", bad ? "FEHLER" : "ok");

    const char *mode = argc > 1 ? argv[1] : "all";
    audio_init(44100);
    sfx_on = 0;
    if (!strcmp(mode, "all") || !strcmp(mode, "validate")) {
        int b1 = validate(1);
        if (argc > 2) print_reach_map();
        int b2 = validate(2);
        printf("Lösbarkeit: %s (Sim-Frames %d)\n", (b1 || b2) ? "FEHLER" : "ok", sim_frames_total);
        bad |= b1 | b2;
    }
    if (!strcmp(mode, "all") || !strcmp(mode, "shots")) {
        sfx_on = 1; sfx_gain = 1;
        game_init();
        Input in; memset(&in, 0, sizeof in);
        for (int f = 0; f < 120; f++) game_update(&in);
        game_render(fb); write_ppm("shots/title.ppm");
        /* Spielstart */
        in.confirm = 1; game_update(&in); in.confirm = 0; game_update(&in);
        for (int f = 0; f < 60; f++) game_update(&in);
        game_render(fb); write_ppm("shots/start.ppm");
        in.right = 1; in.run = 1;
        for (int f = 0; f < 70; f++) game_update(&in);
        game_render(fb); write_ppm("shots/run.ppm");
        /* jeden Raum zeigen */
        clock_t t0 = clock(); int frames = 0;
        for (int r = 0; r < GX * GY; r++) {
            if (!ROOM_EXISTS[r / GX][r % GX]) continue;
            enter_room(r);
            /* Spieler auf eine erreichte Position im Raum setzen */
            int found = 0;
            for (int ty = 13; ty >= 1 && !found; ty--)
                for (int tx = 3; tx < RW - 3 && !found; tx++) {
                    int gx = (r % GX) * RW + tx, gy = (r / GX) * RH + ty;
                    if (!is_solid(gx, gy) && !is_solid(gx, gy - 1) && (is_solid(gx, gy + 1) || is_oneway(gx, gy + 1)) && tile(gx, gy) == ' ' && tile(gx, gy - 1) == ' ') {
                        pl.x = gx * TS + 3; pl.y = (gy + 1) * TS - PH; pl.st = PS_GROUND; found = 1;
                    }
                }
            pl.dead = 0; pl.invuln = 0; fade_t = 0; banner_t = 120; msg_t = 0;
            for (int f = 0; f < 50; f++) { memset(&in, 0, sizeof in); update_world(); update_particles(); gframe++; }
            game_render(fb); frames++;
            char path[64]; snprintf(path, sizeof path, "shots/room_%d_%d.ppm", r % GX, r / GX);
            write_ppm(path);
        }
        double ms = (double)(clock() - t0) / CLOCKS_PER_SEC * 1000;
        /* reine Renderzeit messen */
        t0 = clock();
        for (int i = 0; i < 60; i++) game_render(fb);
        printf("Renderzeit: %.2f ms pro Bild\n", (double)(clock() - t0) / CLOCKS_PER_SEC * 1000 / 60);
        (void)ms; (void)frames;
        gstate = GS_PAUSE; menu_sel = 1; game_render(fb); write_ppm("shots/pause.ppm");
    }
    if (!strcmp(mode, "all") || !strcmp(mode, "audio")) {
        audio_init(44100);
        audio_set_music(1); audio_set_sfx(1);
        int secs = 48, n = 44100 * secs;
        short *buf = malloc(n * 4);
        int pos = 0, chunk = 735, k = 0;
        int sfxlist[] = { SFX_JUMP, SFX_LAND, SFX_KEY, SFX_DOOR, SFX_TREASURE, SFX_SPRING, SFX_LASER, SFX_DEATH, SFX_SPIKE, SFX_ROUND, SFX_GAMEOVER };
        clock_t t0 = clock();
        while (pos < n) {
            int c = n - pos < chunk ? n - pos : chunk;
            if (pos > 44100 * 30 && (pos / chunk) % 120 == 0 && k < (int)(sizeof sfxlist / sizeof sfxlist[0])) sfx(sfxlist[k++]);
            audio_mix(buf + pos * 2, c);
            pos += c;
        }
        double t = (double)(clock() - t0) / CLOCKS_PER_SEC;
        double sum = 0; int peak = 0;
        for (int i = 0; i < n * 2; i++) { int v = abs(buf[i]); if (v > peak) peak = v; sum += (double)buf[i] * buf[i]; }
        printf("Audio: %d s in %.2f s gemischt, Spitze %d, RMS %.0f\n", secs, t, peak, sqrt(sum / (n * 2)));
        FILE *f = fopen("shots/audio.wav", "wb");
        int datalen = n * 4;
        unsigned char hdr[44] = { 'R','I','F','F',0,0,0,0,'W','A','V','E','f','m','t',' ',16,0,0,0,1,0,2,0, 0x44,0xAC,0,0, 0x10,0xB1,2,0, 4,0,16,0,'d','a','t','a',0,0,0,0 };
        int rl = datalen + 36; memcpy(hdr + 4, &rl, 4); memcpy(hdr + 40, &datalen, 4);
        fwrite(hdr, 1, 44, f); fwrite(buf, 1, datalen, f); fclose(f);
        free(buf);
    }
    return bad;
}
