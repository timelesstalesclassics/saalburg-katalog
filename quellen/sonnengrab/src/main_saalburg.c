/* Saalburg-Plattformschicht für Sonnengrab: schlanker Wayland-Klient ohne libwayland.
 *
 * Spricht das Wayland-Protokoll direkt über den Socket (wl_shm + xdg-shell + wl_seat),
 * so wie es der Wayland-Server von Saalburg (apps/oberflaeche/wayland.zig) anbietet.
 * Statisch gegen musl gebaut: läuft in der Sandbox ohne weitere Bibliotheken.
 *
 *   Fenstergröße  bestimmt die Oberfläche (Vollbild, 1:1, Leiste) – das Spielbild wird
 *                 ganzzahlig vergrößert und mittig gesetzt
 *   Tasten        evdev-Codes aus wl_keyboard.key (physische Lage, unabhängig vom Layout)
 *   Takt          Spiellogik fest mit 60 Hz, gezeichnet wird auf frame-Rückruf
 *   Fokus weg     Spiel hält an (Pause-Menü)
 *   Ton           Saalburg hat noch keine Tonausgabe – das Spiel läuft stumm
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include "game.h"

/* ------------------------------------------------------------------ */
/*                       Wayland-Drahtprotokoll                        */
/* ------------------------------------------------------------------ */
enum {
    T_NONE = 0, T_DISPLAY, T_REGISTRY, T_CALLBACK_SYNC, T_CALLBACK_FRAME, T_COMPOSITOR, T_SHM, T_SHM_POOL,
    T_BUFFER, T_SURFACE, T_SEAT, T_KEYBOARD, T_WM_BASE, T_XDG_SURFACE, T_XDG_TOPLEVEL,
    T_ZOMBIE, /* zerstört, ID erst nach delete_id wieder frei */
};
#define MAXOBJ 1024
static unsigned char obj_type[MAXOBJ];
static int obj_aux[MAXOBJ];          /* Puffer: Index */
static uint32_t next_id = 2;

static int sock = -1;
static unsigned char outbuf[16384];
static int outlen = 0;
static int out_fds[4], n_out_fds = 0;
static unsigned char inbuf[65536];
static int inlen = 0;
static int in_fds[32], n_in_fds = 0;

static void die(const char *msg) {
    fprintf(stderr, "sonnengrab: %s\n", msg);
    exit(1);
}

static uint32_t new_id(int type) {
    /* frei gewordene IDs (delete_id) zuerst wiederverwenden */
    for (uint32_t i = 2; i < next_id; i++)
        if (obj_type[i] == T_NONE) { obj_type[i] = (unsigned char)type; return i; }
    if (next_id >= MAXOBJ) die("zu viele Wayland-Objekte");
    obj_type[next_id] = (unsigned char)type;
    return next_id++;
}

static void flush_out(void) {
    if (outlen == 0 && n_out_fds == 0) return;
    struct iovec iov = { outbuf, (size_t)outlen };
    struct msghdr msg;
    memset(&msg, 0, sizeof msg);
    msg.msg_iov = &iov; msg.msg_iovlen = 1;
    char cbuf[CMSG_SPACE(sizeof(int) * 4)];
    if (n_out_fds) {
        memset(cbuf, 0, sizeof cbuf);
        msg.msg_control = cbuf;
        msg.msg_controllen = CMSG_SPACE(sizeof(int) * n_out_fds);
        struct cmsghdr *c = CMSG_FIRSTHDR(&msg);
        c->cmsg_level = SOL_SOCKET; c->cmsg_type = SCM_RIGHTS;
        c->cmsg_len = CMSG_LEN(sizeof(int) * n_out_fds);
        memcpy(CMSG_DATA(c), out_fds, sizeof(int) * n_out_fds);
    }
    int off = 0;
    while (off < outlen) {
        iov.iov_base = outbuf + off; iov.iov_len = (size_t)(outlen - off);
        ssize_t r = sendmsg(sock, &msg, MSG_NOSIGNAL);
        if (r < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN) { struct pollfd p = { sock, POLLOUT, 0 }; poll(&p, 1, 100); continue; }
            die("Verbindung zur Oberfläche verloren");
        }
        off += (int)r;
        msg.msg_control = NULL; msg.msg_controllen = 0; /* Deskriptoren nur einmal */
    }
    outlen = 0; n_out_fds = 0;
}

/* Nachricht zusammensetzen */
static unsigned char msgbuf[4096];
static int msglen;
static void m_begin(void) { msglen = 8; }
static void m_u32(uint32_t v) { memcpy(msgbuf + msglen, &v, 4); msglen += 4; }
static void m_i32(int32_t v) { memcpy(msgbuf + msglen, &v, 4); msglen += 4; }
static void m_str(const char *s) {
    uint32_t n = (uint32_t)strlen(s) + 1;
    m_u32(n);
    memcpy(msgbuf + msglen, s, n);
    msglen += (int)n;
    while (msglen & 3) msgbuf[msglen++] = 0;
}
static void m_fd(int fd) { out_fds[n_out_fds++] = fd; }
static void m_send(uint32_t obj, uint16_t opcode) {
    uint32_t hdr2 = ((uint32_t)msglen << 16) | opcode;
    memcpy(msgbuf, &obj, 4); memcpy(msgbuf + 4, &hdr2, 4);
    if (outlen + msglen > (int)sizeof outbuf || n_out_fds > 3) flush_out();
    memcpy(outbuf + outlen, msgbuf, (size_t)msglen);
    outlen += msglen;
    if (n_out_fds) flush_out(); /* Deskriptor sofort mit seiner Nachricht senden */
}

/* ------------------------------------------------------------------ */
/*                               Zustand                               */
/* ------------------------------------------------------------------ */
static uint32_t id_registry, id_compositor, id_shm, id_seat, id_wm, id_keyboard;
static uint32_t id_surface, id_xdg_surface, id_toplevel, id_frame;
static uint32_t seat_name, sync_id;
static int sync_done = 0;
static int configured = 0, pending_serial_valid = 0;
static uint32_t pending_serial;
static int pend_w = 0, pend_h = 0;
static int win_w = SCR_W * 2, win_h = SCR_H * 2;
static int running = 1, focused = 1, frame_pending = 0;
static int keys[256];

typedef struct { uint32_t id; int busy; uint32_t *px; } Buf;
static Buf bufs[2];
static int buf_w = 0, buf_h = 0;
static uint32_t pool_id = 0;
static int pool_fd = -1;
static void *pool_mem = NULL;
static size_t pool_size = 0;

static void destroy_buffers(void) {
    for (int i = 0; i < 2; i++) {
        if (bufs[i].id) {
            m_begin(); m_send(bufs[i].id, 0); /* wl_buffer.destroy */
            obj_type[bufs[i].id] = T_ZOMBIE;
            bufs[i].id = 0;
        }
    }
    if (pool_id) { m_begin(); m_send(pool_id, 1); obj_type[pool_id] = T_ZOMBIE; pool_id = 0; } /* wl_shm_pool.destroy */
    if (pool_mem) { munmap(pool_mem, pool_size); pool_mem = NULL; }
    if (pool_fd >= 0) { close(pool_fd); pool_fd = -1; }
}

static void create_buffers(int w, int h) {
    destroy_buffers();
    buf_w = w; buf_h = h;
    size_t one = (size_t)w * h * 4;
    pool_size = one * 2;
    pool_fd = memfd_create("sonnengrab", MFD_CLOEXEC);
    if (pool_fd < 0) die("memfd_create fehlgeschlagen");
    if (ftruncate(pool_fd, (off_t)pool_size) < 0) die("ftruncate fehlgeschlagen");
    pool_mem = mmap(NULL, pool_size, PROT_READ | PROT_WRITE, MAP_SHARED, pool_fd, 0);
    if (pool_mem == MAP_FAILED) die("mmap fehlgeschlagen");
    pool_id = new_id(T_SHM_POOL);
    m_begin(); m_u32(pool_id); m_fd(pool_fd); m_i32((int32_t)pool_size); m_send(id_shm, 0); /* create_pool */
    for (int i = 0; i < 2; i++) {
        bufs[i].id = new_id(T_BUFFER);
        obj_aux[bufs[i].id] = i;
        bufs[i].busy = 0;
        bufs[i].px = (uint32_t *)((char *)pool_mem + one * i);
        memset(bufs[i].px, 0, one);
        m_begin(); m_u32(bufs[i].id); m_i32((int32_t)(one * i)); m_i32(w); m_i32(h); m_i32(w * 4); m_u32(1); /* XRGB8888 */
        m_send(pool_id, 0); /* create_buffer */
    }
}

/* ------------------------------------------------------------------ */
/*                           Ereignisse lesen                          */
/* ------------------------------------------------------------------ */
static int take_fd(void) {
    if (n_in_fds == 0) return -1;
    int fd = in_fds[0];
    memmove(in_fds, in_fds + 1, sizeof(int) * (size_t)(--n_in_fds));
    return fd;
}

static void handle_event(uint32_t obj, uint16_t op, const unsigned char *p, int len) {
    uint32_t a0 = 0, a1 = 0, a2 = 0, a3 = 0;
    if (len >= 4) memcpy(&a0, p, 4);
    if (len >= 8) memcpy(&a1, p + 4, 4);
    if (len >= 12) memcpy(&a2, p + 8, 4);
    if (len >= 16) memcpy(&a3, p + 12, 4);
    int type = obj < MAXOBJ ? obj_type[obj] : T_NONE;
#ifdef WLDEBUG
    fprintf(stderr, "ev obj=%u typ=%d op=%u len=%d\n", obj, type, op, len);
#endif
    switch (type) {
    case T_DISPLAY:
        if (op == 0) { /* error(object, code, message) */
            const char *m = len > 12 ? (const char *)(p + 12) : "";
            fprintf(stderr, "sonnengrab: Wayland-Fehler an Objekt %u, Code %u: %s\n", a0, a1, m);
            exit(1);
        } else if (op == 1) { /* delete_id */
            if (a0 < MAXOBJ) obj_type[a0] = T_NONE;
        }
        break;
    case T_REGISTRY:
        if (op == 0) { /* global(name, interface, version) */
            uint32_t name = a0;
            const char *iface = (const char *)(p + 8);
            uint32_t slen = a1;
            uint32_t ver; memcpy(&ver, p + 8 + ((slen + 3) & ~3u), 4);
#define BIND(var, typ, ifname, v) do { var = new_id(typ); m_begin(); m_u32(name); m_str(ifname); m_u32(v); m_u32(var); m_send(id_registry, 0); } while (0)
            if (!strcmp(iface, "wl_compositor") && !id_compositor) BIND(id_compositor, T_COMPOSITOR, "wl_compositor", ver < 4 ? ver : 4);
            else if (!strcmp(iface, "wl_shm") && !id_shm) BIND(id_shm, T_SHM, "wl_shm", 1);
            else if (!strcmp(iface, "xdg_wm_base") && !id_wm) BIND(id_wm, T_WM_BASE, "xdg_wm_base", ver < 2 ? ver : 2);
            else if (!strcmp(iface, "wl_seat") && !id_seat) { BIND(id_seat, T_SEAT, "wl_seat", ver < 5 ? ver : 5); seat_name = name; }
#undef BIND
        }
        break;
    case T_CALLBACK_SYNC:
        if (op == 0) { sync_done = 1; obj_type[obj] = T_ZOMBIE; }
        break;
    case T_CALLBACK_FRAME:
        if (op == 0) { frame_pending = 0; if (obj == id_frame) id_frame = 0; obj_type[obj] = T_ZOMBIE; }
        break;
    case T_BUFFER:
        if (op == 0) bufs[obj_aux[obj]].busy = 0; /* release */
        break;
    case T_SEAT:
        if (op == 0) { /* capabilities */
            if ((a0 & 2) && !id_keyboard) {
                id_keyboard = new_id(T_KEYBOARD);
                m_begin(); m_u32(id_keyboard); m_send(id_seat, 1); /* get_keyboard */
            }
        }
        break;
    case T_KEYBOARD:
        if (op == 0) { /* keymap(format, fd, size): wir brauchen sie nicht – evdev-Codes reichen */
            int fd = take_fd();
            if (fd >= 0) close(fd);
        } else if (op == 1) { /* enter */
            focused = 1;
        } else if (op == 2) { /* leave */
            focused = 0;
            memset(keys, 0, sizeof keys);
            game_focus_lost();
        } else if (op == 3) { /* key(serial, time, key, state) */
            if (a2 < 256) keys[a2] = (a3 == 1);
        }
        break;
    case T_WM_BASE:
        if (op == 0) { m_begin(); m_u32(a0); m_send(id_wm, 3); } /* ping -> pong */
        break;
    case T_XDG_SURFACE:
        if (op == 0) { pending_serial = a0; pending_serial_valid = 1; }
        break;
    case T_XDG_TOPLEVEL:
        if (op == 0) { pend_w = (int32_t)a0; pend_h = (int32_t)a1; }
        else if (op == 1) { running = 0; fprintf(stderr, "sonnengrab: Fenster geschlossen\n"); } /* close (Super+Q) */
        break;
    default:
        break;
    }
}

static void dispatch_buffer(void) {
    int off = 0;
    while (inlen - off >= 8) {
        uint32_t obj, h2;
        memcpy(&obj, inbuf + off, 4);
        memcpy(&h2, inbuf + off + 4, 4);
        int size = (int)(h2 >> 16);
        if (size < 8) die("kaputte Wayland-Nachricht");
        if (inlen - off < size) break;
        handle_event(obj, (uint16_t)(h2 & 0xffff), inbuf + off + 8, size - 8);
        off += size;
    }
    memmove(inbuf, inbuf + off, (size_t)(inlen - off));
    inlen -= off;
}

static int read_events(int timeout_ms) {
    flush_out();
    struct pollfd pfd = { sock, POLLIN, 0 };
    int r = poll(&pfd, 1, timeout_ms);
    if (r <= 0) return 0;
    if (pfd.revents & (POLLHUP | POLLERR)) die("Oberfläche hat die Verbindung beendet");
    struct iovec iov = { inbuf + inlen, sizeof inbuf - (size_t)inlen };
    char cbuf[CMSG_SPACE(sizeof(int) * 16)];
    struct msghdr msg;
    memset(&msg, 0, sizeof msg);
    msg.msg_iov = &iov; msg.msg_iovlen = 1;
    msg.msg_control = cbuf; msg.msg_controllen = sizeof cbuf;
    ssize_t n = recvmsg(sock, &msg, MSG_CMSG_CLOEXEC | MSG_DONTWAIT);
    if (n < 0) { if (errno == EAGAIN || errno == EINTR) return 0; die("Lesefehler"); }
    if (n == 0) die("Oberfläche hat die Verbindung beendet");
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&msg); c; c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS) {
            int cnt = (int)((c->cmsg_len - CMSG_LEN(0)) / sizeof(int));
            for (int i = 0; i < cnt; i++) {
                int fd; memcpy(&fd, CMSG_DATA(c) + i * sizeof(int), sizeof(int));
                if (n_in_fds < 32) in_fds[n_in_fds++] = fd; else close(fd);
            }
        }
    }
    inlen += (int)n;
    dispatch_buffer();
    return 1;
}

static void roundtrip(void) {
    sync_id = new_id(T_CALLBACK_SYNC);
    sync_done = 0;
    m_begin(); m_u32(sync_id); m_send(1, 0); /* wl_display.sync */
    for (int i = 0; i < 500 && !sync_done; i++) read_events(10);
    if (!sync_done) die("Oberfläche antwortet nicht");
}

/* ------------------------------------------------------------------ */
/*                    Bild vergrößern und ausgeben                     */
/* ------------------------------------------------------------------ */
static unsigned int fb[SCR_W * SCR_H];

/* Spielbild in den Platz einpassen: so groß wie möglich, Seitenverhältnis bleibt,
 * Pixel bleiben scharf (nächster Nachbar), Rand schwarz */
static int xmap[8192];
static void blit_scaled(uint32_t *dst, int w, int h) {
    int ow, oh;
    if ((long)w * SCR_H <= (long)h * SCR_W) { ow = w; oh = (int)((long)w * SCR_H / SCR_W); }
    else { oh = h; ow = (int)((long)h * SCR_W / SCR_H); }
    if (ow < 1) ow = 1;
    if (oh < 1) oh = 1;
    if (ow > 8192) ow = 8192;
    int ox = (w - ow) / 2, oy = (h - oh) / 2;
    for (int x = 0; x < ow; x++) xmap[x] = (int)((long)x * SCR_W / ow);
    for (int y = 0; y < oy; y++) memset(dst + (size_t)y * w, 0, (size_t)w * 4);
    for (int y = oy + oh; y < h; y++) memset(dst + (size_t)y * w, 0, (size_t)w * 4);
    int prev_src = -1;
    uint32_t *prev_row = NULL;
    for (int y = 0; y < oh; y++) {
        int sy = (int)((long)y * SCR_H / oh);
        uint32_t *row = dst + (size_t)(oy + y) * w;
        if (sy == prev_src && prev_row) { memcpy(row, prev_row, (size_t)w * 4); continue; }
        memset(row, 0, (size_t)ox * 4);
        const unsigned int *src = fb + sy * SCR_W;
        uint32_t *d = row + ox;
        for (int x = 0; x < ow; x++) d[x] = src[xmap[x]];
        memset(row + ox + ow, 0, (size_t)(w - ox - ow) * 4);
        prev_src = sy; prev_row = row;
    }
}

static void present(void) {
    if (!configured || frame_pending) return;
    if (buf_w != win_w || buf_h != win_h) create_buffers(win_w, win_h);
    Buf *b = NULL;
    for (int i = 0; i < 2; i++) if (!bufs[i].busy) { b = &bufs[i]; break; }
    if (!b) return; /* beide noch bei der Oberfläche */
    game_render(fb);
    blit_scaled(b->px, buf_w, buf_h);
    b->busy = 1;
    id_frame = new_id(T_CALLBACK_FRAME);
    frame_pending = 1;
    m_begin(); m_u32(id_frame); m_send(id_surface, 3);                       /* frame */
    m_begin(); m_u32(b->id); m_i32(0); m_i32(0); m_send(id_surface, 1);      /* attach */
    m_begin(); m_i32(0); m_i32(0); m_i32(buf_w); m_i32(buf_h); m_send(id_surface, 2); /* damage */
    m_begin(); m_send(id_surface, 6);                                         /* commit */
    flush_out();
}

/* ------------------------------------------------------------------ */
/*                               Eingabe                               */
/* ------------------------------------------------------------------ */
enum {
    K_ESC = 1, K_W = 17, K_P = 25, K_ENTER = 28, K_LCTRL = 29, K_A = 30, K_S = 31, K_D = 32,
    K_LSHIFT = 42, K_X = 45, K_RSHIFT = 54, K_SPACE = 57, K_KPENTER = 96, K_RCTRL = 97,
    K_UP = 103, K_LEFT = 105, K_RIGHT = 106, K_DOWN = 108,
};
static Input gather_input(void) {
    Input in;
    memset(&in, 0, sizeof in);
    in.left = keys[K_LEFT] || keys[K_A];
    in.right = keys[K_RIGHT] || keys[K_D];
    in.up = keys[K_UP] || keys[K_W];
    in.down = keys[K_DOWN] || keys[K_S];
    in.jump = keys[K_SPACE];
    in.ljump = keys[K_X] || keys[K_LCTRL] || keys[K_RCTRL];
    in.run = keys[K_LSHIFT] || keys[K_RSHIFT];
    in.pause = keys[K_ESC] || keys[K_P];
    in.confirm = keys[K_ENTER] || keys[K_KPENTER];
    return in;
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

/* ------------------------------------------------------------------ */
int main(void) {
    const char *disp = getenv("WAYLAND_DISPLAY");
    if (!disp || !*disp) disp = "wayland-0";
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof addr);
    addr.sun_family = AF_UNIX;
    if (disp[0] == '/') snprintf(addr.sun_path, sizeof addr.sun_path, "%s", disp);
    else {
        const char *rt = getenv("XDG_RUNTIME_DIR");
        if (!rt) die("XDG_RUNTIME_DIR fehlt");
        snprintf(addr.sun_path, sizeof addr.sun_path, "%s/%s", rt, disp);
    }
    sock = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (sock < 0 || connect(sock, (struct sockaddr *)&addr, sizeof addr) < 0) die("keine Verbindung zur Oberfläche (Wayland)");

    obj_type[1] = T_DISPLAY;
    id_registry = new_id(T_REGISTRY);
    m_begin(); m_u32(id_registry); m_send(1, 1); /* get_registry */
    roundtrip();
    if (!id_compositor || !id_shm || !id_wm) die("Oberfläche bietet wl_compositor, wl_shm oder xdg_wm_base nicht an");
    roundtrip(); /* Fähigkeiten des Sitzes, Tastatur */

    game_init();

    id_surface = new_id(T_SURFACE);
    m_begin(); m_u32(id_surface); m_send(id_compositor, 0);                  /* create_surface */
    id_xdg_surface = new_id(T_XDG_SURFACE);
    m_begin(); m_u32(id_xdg_surface); m_u32(id_surface); m_send(id_wm, 2);   /* get_xdg_surface */
    id_toplevel = new_id(T_XDG_TOPLEVEL);
    m_begin(); m_u32(id_toplevel); m_send(id_xdg_surface, 1);                /* get_toplevel */
    m_begin(); m_str("Sonnengrab"); m_send(id_toplevel, 2);                  /* set_title */
    m_begin(); m_str("sonnengrab"); m_send(id_toplevel, 3);                  /* set_app_id */
    m_begin(); m_send(id_surface, 6);                                         /* commit ohne Puffer */
    flush_out();

    double acc = 0, last = now_s();
    const double dt = 1.0 / 60.0;
    while (running) {
        /* Bis zum nächsten Logikschritt auf Ereignisse warten */
        double wait = dt - acc;
        int ms = wait > 0 ? (int)(wait * 1000) : 0;
        read_events(ms);
        while (read_events(0)) {}
        if (pending_serial_valid) {
            m_begin(); m_u32(pending_serial); m_send(id_xdg_surface, 4);         /* ack_configure */
            pending_serial_valid = 0;
            if (pend_w > 0 && pend_h > 0) { win_w = pend_w; win_h = pend_h; }
            configured = 1;
            /* nach Größenwechsel sofort neu zeichnen */
            if (buf_w != win_w || buf_h != win_h) frame_pending = 0;
        }
        double t = now_s();
        acc += t - last;
        last = t;
        if (acc > 0.25) acc = 0.25;
        int stepped = 0;
        while (acc >= dt) {
            Input in = gather_input();
            if (!focused) memset(&in, 0, sizeof in);
            game_update(&in);
            acc -= dt;
            stepped = 1;
            if (game_quit_requested()) { running = 0; fprintf(stderr, "sonnengrab: beendet über Menü\n"); }
            (void)game_fullscreen_toggle_requested();
        }
        if (stepped) present();
    }
    destroy_buffers();
    flush_out();
    close(sock);
    return 0;
}
