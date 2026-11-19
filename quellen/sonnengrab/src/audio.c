/* Synthesizer, Musik und Effekte für Sonnengrab (wird von game.c eingebunden) */

enum { V_OFF = 0, V_PLUCK, V_NEY, V_DUM, V_TEK, V_BELL, V_SWEEP, V_NOISE, V_RUMBLE };

typedef struct {
    int type, music;
    int delay;              /* Samples bis Start */
    double t;               /* Sekunden seit Start */
    float f0, f1, dur, amp, pan, vib, send;
    double ph, ph2;
    float lp, lp2, hp;
    float *ks; int kslen, kspos; float ksdecay;
} Voice;

#define MAXV 40
#define KSMAX 2400
static Voice voices[MAXV];
static float ksbuf[MAXV][KSMAX];
static int SR = 44100;
static void (*a_lock)(void) = 0;
static void (*a_unlock)(void) = 0;
static unsigned int arng = 0x9E3779B9u;
static float music_gain = 1.0f, music_target = 1.0f, sfx_gain = 1.0f;
static int music_on = 1, sfx_on = 1;

/* Hall */
#define NCOMB 4
static const int comb_len[NCOMB] = { 1557, 1617, 1491, 1422 };
static const int comb_lenR[NCOMB] = { 1580, 1640, 1514, 1445 };
static float combL[NCOMB][1700], combR[NCOMB][1700];
static int combpos[NCOMB], combposR[NCOMB];
static float comblpL[NCOMB], comblpR[NCOMB];
static float apL[2][600], apR[2][600];
static int appos[2], apposR[2];
static const int ap_len[2] = { 556, 441 };
static const int ap_lenR[2] = { 579, 464 };

/* Sequencer */
static double seq_samples = 0;
static int seq_step = -1;
static float drone_ph[4], drone_lp = 0, drone_lp2 = 0, drone_t = 0;

void audio_set_lock(void (*lock)(void), void (*unlock)(void)) { a_lock = lock; a_unlock = unlock; }
static void alock(void) { if (a_lock) a_lock(); }
static void aunlock(void) { if (a_unlock) a_unlock(); }

static float arnd(void) { arng ^= arng << 13; arng ^= arng >> 17; arng ^= arng << 5; return (arng & 0xffffff) / 8388608.0f - 1.0f; }
static float mtof(float m) { return 440.0f * powf(2.0f, (m - 69.0f) / 12.0f); }

static Voice *voice_alloc(int music) {
    int best = -1; double bt = -1;
    for (int i = 0; i < MAXV; i++) {
        if (voices[i].type == V_OFF) { best = i; break; }
        if (voices[i].music == music && voices[i].t > bt) { bt = voices[i].t; best = i; }
    }
    if (best < 0) best = 0;
    Voice *v = &voices[best];
    memset(v, 0, sizeof(*v));
    v->ks = ksbuf[best];
    v->music = music;
    v->pan = 0.5f;
    return v;
}

static void v_pluck(float midi, float amp, float pan, int delay, int music, float decay) {
    Voice *v = voice_alloc(music);
    v->type = V_PLUCK; v->amp = amp; v->pan = pan; v->delay = delay; v->send = 0.35f;
    float f = mtof(midi);
    v->kslen = (int)(SR / f); if (v->kslen > KSMAX - 1) v->kslen = KSMAX - 1; if (v->kslen < 2) v->kslen = 2;
    v->ksdecay = decay;
    float lp = 0;
    for (int i = 0; i < v->kslen; i++) { lp = lp * 0.55f + arnd() * 0.45f; v->ks[i] = lp; }
    v->dur = 3.0f;
}
static void v_ney(float midi, float dur, float amp, float pan, int delay, int music) {
    Voice *v = voice_alloc(music);
    v->type = V_NEY; v->f0 = mtof(midi); v->dur = dur; v->amp = amp; v->pan = pan; v->delay = delay; v->send = 0.6f;
}
static void v_dum(float amp, int delay, int music) {
    Voice *v = voice_alloc(music);
    v->type = V_DUM; v->f0 = 110; v->f1 = 52; v->dur = 0.45f; v->amp = amp; v->pan = 0.48f; v->delay = delay; v->send = 0.15f;
}
static void v_tek(float amp, float pan, int delay, int music) {
    Voice *v = voice_alloc(music);
    v->type = V_TEK; v->dur = 0.09f; v->amp = amp; v->pan = pan; v->delay = delay; v->send = 0.2f;
}
static void v_bell(float freq, float dur, float amp, float pan, int delay) {
    Voice *v = voice_alloc(0);
    v->type = V_BELL; v->f0 = freq; v->dur = dur; v->amp = amp; v->pan = pan; v->delay = delay; v->send = 0.5f;
}
static void v_sweep(float f0, float f1, float dur, float amp, float vib, int delay) {
    Voice *v = voice_alloc(0);
    v->type = V_SWEEP; v->f0 = f0; v->f1 = f1; v->dur = dur; v->amp = amp; v->vib = vib; v->delay = delay; v->send = 0.2f;
}
static void v_noise(float cutoff, float dur, float amp, int delay) {
    Voice *v = voice_alloc(0);
    v->type = V_NOISE; v->f0 = cutoff; v->dur = dur; v->amp = amp; v->delay = delay; v->send = 0.25f;
}
static void v_rumble(float dur, float amp) {
    Voice *v = voice_alloc(0);
    v->type = V_RUMBLE; v->f0 = 48; v->dur = dur; v->amp = amp; v->send = 0.3f;
}

static float voice_sample(Voice *v) {
    float dt = 1.0f / SR, t = (float)v->t, s = 0;
    switch (v->type) {
    case V_PLUCK: {
        int i = v->kspos, j = (i + 1) % v->kslen;
        float out = v->ks[i];
        v->ks[i] = (v->ks[i] + v->ks[j]) * 0.5f * v->ksdecay;
        v->kspos = j;
        /* Körper: leichter Tiefpass für warmen Oud-Klang */
        v->lp += (out - v->lp) * 0.55f;
        s = v->lp * v->amp * 1.6f;
        if (t > v->dur) v->type = V_OFF;
        break;
    }
    case V_NEY: {
        float att = 0.12f, rel = 0.25f;
        float env = t < att ? t / att : (t > v->dur ? 1.0f - (t - v->dur) / rel : 1.0f);
        if (t > v->dur + rel) { v->type = V_OFF; break; }
        float vib = t > 0.25f ? sinf(t * 2 * 3.14159f * 5.2f) * 0.012f * fminf(1, (t - 0.25f) * 2) : 0;
        v->ph += v->f0 * (1 + vib) * dt;
        float p = (float)(v->ph - floor(v->ph));
        float tone = sinf(p * 6.2831853f) + 0.18f * sinf(p * 12.566f) + 0.06f * sinf(p * 18.85f);
        float n = arnd();
        v->lp += (n - v->lp) * 0.08f; v->lp2 += (v->lp - v->lp2) * 0.2f;
        float breath = (v->lp - v->lp2) * 2.2f * (0.5f + 0.5f * (t < 0.15f ? 1.5f : 0.6f));
        s = (tone * 0.85f + breath * 0.5f) * env * v->amp;
        break;
    }
    case V_DUM: {
        float f = v->f1 + (v->f0 - v->f1) * expf(-t * 18);
        v->ph += f * dt;
        float env = expf(-t * 7.5f);
        s = sinf((float)v->ph * 6.2831853f) * env * v->amp;
        float n = arnd(); v->lp += (n - v->lp) * 0.05f;
        s += v->lp * expf(-t * 40) * v->amp * 1.5f;
        if (t > v->dur) v->type = V_OFF;
        break;
    }
    case V_TEK: {
        float n = arnd();
        v->hp = n - v->lp; v->lp += (n - v->lp) * 0.35f;
        float env = expf(-t * 55);
        v->ph += 410 * dt;
        s = (v->hp * 0.9f + sinf((float)v->ph * 6.2831853f) * 0.5f * expf(-t * 90)) * env * v->amp;
        if (t > v->dur) v->type = V_OFF;
        break;
    }
    case V_BELL: {
        float env = expf(-t * 4.0f / v->dur) * (t < 0.004f ? t / 0.004f : 1);
        v->ph += v->f0 * dt; v->ph2 += v->f0 * 2.76f * dt;
        s = (sinf((float)v->ph * 6.2831853f) + 0.35f * sinf((float)v->ph2 * 6.2831853f) * expf(-t * 9)) * env * v->amp;
        if (t > v->dur * 1.6f) v->type = V_OFF;
        break;
    }
    case V_SWEEP: {
        float k = t / v->dur; if (k > 1) { v->type = V_OFF; break; }
        float f = v->f0 * powf(v->f1 / v->f0, k);
        if (v->vib > 0) f *= 1 + 0.08f * sinf(t * 6.2831853f * v->vib);
        v->ph += f * dt;
        float p = (float)(v->ph - floor(v->ph));
        float w = sinf(p * 6.2831853f) + 0.3f * sinf(p * 12.566f);
        float env = (1 - k) * (k < 0.05f ? k / 0.05f : 1);
        s = w * env * v->amp;
        break;
    }
    case V_NOISE: {
        float k = t / v->dur; if (k > 1) { v->type = V_OFF; break; }
        float c = v->f0 / SR * 6.28f; if (c > 1) c = 1;
        v->lp += (arnd() - v->lp) * c; v->lp2 += (v->lp - v->lp2) * c;
        float env = (1 - k) * (1 - k) * (k < 0.02f ? k / 0.02f : 1);
        s = v->lp2 * env * v->amp * 3.0f;
        break;
    }
    case V_RUMBLE: {
        float k = t / v->dur; if (k > 1) { v->type = V_OFF; break; }
        v->lp += (arnd() - v->lp) * 0.02f;
        v->ph += (v->f0 + 6 * sinf(t * 17)) * dt;
        float wob = 0.6f + 0.4f * sinf(t * 31) * sinf(t * 7);
        float env = sinf(k * 3.14159f);
        s = (v->lp * 6 + 0.5f * sinf((float)v->ph * 6.2831853f)) * env * wob * v->amp;
        break;
    }
    }
    v->t += dt;
    return s;
}

/* ---------------- Musik: eigene Komposition in D-Doppelharmonisch ---------------- */
typedef struct { signed char note, len; } Note;
static const Note MEL_A[] = {
    {69,4},{70,2},{69,2},{67,4},{66,4},
    {67,2},{66,2},{63,4},{62,8},
    {62,2},{63,2},{66,2},{67,2},{69,4},{73,2},{74,2},
    {70,4},{69,4},{69,6},{0,2},
};
static const Note MEL_B[] = {
    {74,2},{73,2},{70,2},{69,2},{67,2},{69,2},{70,4},
    {69,2},{67,2},{66,2},{67,2},{69,8},
    {67,2},{66,2},{63,2},{66,2},{67,2},{66,2},{63,4},
    {62,4},{63,2},{62,2},{62,8},
};
static const signed char BASS[16] = { 50,50,51,50, 50,50,55,50, 50,50,51,50, 50,55,55,50 };
#define STEPS_PER_BAR 16
#define LOOP_BARS 16

static int mel_note_at(const Note *m, int n, int step, int *len) {
    int pos = 0;
    for (int i = 0; i < n; i++) {
        if (pos == step) { *len = m[i].len; return m[i].note; }
        if (step > pos && step < pos + m[i].len) { *len = -(step - pos); return m[i].note; }
        pos += m[i].len;
    }
    *len = 0; return 0;
}

static void seq_trigger(int step) {
    int bar = (step / STEPS_PER_BAR) % LOOP_BARS, s = step % STEPS_PER_BAR;
    float stepdur = 60.0f / 92.0f / 4.0f;
    /* Darbuka – Maqsum */
    if (s == 0 || s == 8) v_dum(0.55f, 0, 1);
    if (s == 2 || s == 6 || s == 12) v_tek(0.30f, 0.62f, 0, 1);
    if (bar >= 4 && (s == 10 || s == 14)) v_tek(0.12f, 0.38f, 0, 1);
    if (bar >= 12 && (s == 15 || s == 5)) v_tek(0.09f, 0.7f, 0, 1);
    /* Bass-Oud */
    int root = BASS[bar], fifth = root + (root == 51 ? 7 : 7);
    if (s == 0) v_pluck(root - 12, 0.55f, 0.4f, 0, 1, 0.996f);
    if (s == 6) v_pluck(fifth - 12, 0.32f, 0.42f, 0, 1, 0.995f);
    if (s == 8) v_pluck(root, 0.36f, 0.45f, 0, 1, 0.995f);
    if (s == 12) v_pluck(fifth - 12, 0.28f, 0.42f, 0, 1, 0.995f);
    if (s == 14) v_pluck(root - 12, 0.22f, 0.4f, 0, 1, 0.995f);
    /* Melodie */
    int len, note;
    int melstep = (bar % 4) * STEPS_PER_BAR + s;
    if (bar >= 4 && bar < 8) {
        note = mel_note_at(MEL_A, sizeof(MEL_A) / sizeof(MEL_A[0]), melstep, &len);
        if (note && len > 0) v_ney(note, len * stepdur * 0.92f, 0.24f, 0.62f, 0, 1);
    } else if (bar >= 8 && bar < 12) {
        note = mel_note_at(MEL_B, sizeof(MEL_B) / sizeof(MEL_B[0]), melstep, &len);
        if (note && len > 0) v_pluck(note, 0.42f, 0.6f, 0, 1, 0.9975f);
        else if (note && len < 0 && ((-len) % 2) == 0) v_pluck(note, 0.22f, 0.6f, 0, 1, 0.997f); /* Tremolo */
    } else if (bar >= 12) {
        note = mel_note_at(MEL_A, sizeof(MEL_A) / sizeof(MEL_A[0]), melstep, &len);
        if (note && len > 0) { v_ney(note + 12, len * stepdur * 0.9f, 0.16f, 0.66f, 0, 1); v_pluck(note, 0.30f, 0.34f, 0, 1, 0.997f); }
    }
}

void audio_init(int samplerate) {
    SR = samplerate;
    memset(voices, 0, sizeof(voices));
}

static float comb_proc(float *buf, int len, int *pos, float *lp, float in) {
    float out = buf[*pos];
    *lp = out * 0.6f + *lp * 0.4f;
    buf[*pos] = in + *lp * 0.80f;
    if (++*pos >= len) *pos = 0;
    return out;
}
static float ap_proc(float *buf, int len, int *pos, float in) {
    float b = buf[*pos];
    float out = -in + b;
    buf[*pos] = in + b * 0.5f;
    if (++*pos >= len) *pos = 0;
    return out;
}

void audio_mix(short *out, int frames) {
    alock();
    double stepsamples = SR * 60.0 / 92.0 / 4.0;
    for (int n = 0; n < frames; n++) {
        /* Sequencer */
        if (music_on || music_gain > 0.001f) {
            int st = (int)(seq_samples / stepsamples);
            if (st != seq_step) { seq_step = st; seq_trigger(st); }
            seq_samples += 1;
        }
        music_gain += (music_target - music_gain) * 0.00008f;
        float L = 0, R = 0, send = 0;
        /* Grundton-Bordun */
        {
            static const float df[4] = { 73.42f, 73.9f, 110.0f, 146.83f };
            float d = 0;
            for (int i = 0; i < 4; i++) {
                drone_ph[i] += df[i] / SR; if (drone_ph[i] >= 1) drone_ph[i] -= 1;
                d += (drone_ph[i] * 2 - 1) * (i == 3 ? 0.4f : 1.0f);
            }
            drone_t += 1.0f / SR;
            float cut = 0.012f + 0.008f * sinf(drone_t * 0.21f);
            drone_lp += (d - drone_lp) * cut;
            drone_lp2 += (drone_lp - drone_lp2) * cut * 1.4f;
            float dv = drone_lp2 * 0.11f * music_gain;
            L += dv; R += dv; send += dv * 0.5f;
        }
        for (int i = 0; i < MAXV; i++) {
            Voice *v = &voices[i];
            if (v->type == V_OFF) continue;
            if (v->delay > 0) { v->delay--; continue; }
            float s = voice_sample(v);
            float g = v->music ? music_gain : sfx_gain;
            s *= g;
            L += s * (1 - v->pan) * 1.2f; R += s * v->pan * 1.2f;
            send += s * v->send;
        }
        /* Hall */
        float rl = 0, rr = 0;
        for (int c = 0; c < NCOMB; c++) {
            rl += comb_proc(combL[c], comb_len[c], &combpos[c], &comblpL[c], send * 0.15f);
            rr += comb_proc(combR[c], comb_lenR[c], &combposR[c], &comblpR[c], send * 0.15f);
        }
        for (int a = 0; a < 2; a++) { rl = ap_proc(apL[a], ap_len[a], &appos[a], rl); rr = ap_proc(apR[a], ap_lenR[a], &apposR[a], rr); }
        L += rl * 0.55f; R += rr * 0.55f;
        L = tanhf(L * 0.9f); R = tanhf(R * 0.9f);
        out[n * 2] = (short)(L * 30000); out[n * 2 + 1] = (short)(R * 30000);
    }
    aunlock();
}

static void audio_set_music(int on) { alock(); music_on = on; music_target = on ? 1.0f : 0.0f; aunlock(); }
static void audio_set_sfx(int on) { alock(); sfx_on = on; sfx_gain = on ? 1.0f : 0.0f; aunlock(); }

/* ---------------- Soundeffekte ---------------- */
enum { SFX_JUMP, SFX_LJUMP, SFX_LAND, SFX_STEP, SFX_KEY, SFX_DOOR, SFX_TREASURE, SFX_DEATH, SFX_SPRING,
       SFX_LASER, SFX_SPIKE, SFX_MENU, SFX_SELECT, SFX_ROUND, SFX_GAMEOVER, SFX_LOCKED, SFX_CLIMB };

static void sfx(int id) {
    if (!sfx_on) return;
    alock();
    int ms = SR / 1000;
    switch (id) {
    case SFX_JUMP: v_sweep(260, 560, 0.14f, 0.20f, 0, 0); v_noise(2500, 0.06f, 0.05f, 0); break;
    case SFX_LJUMP: v_sweep(230, 380, 0.11f, 0.18f, 0, 0); v_noise(1800, 0.08f, 0.06f, 0); break;
    case SFX_LAND: { Voice *v = voice_alloc(0); v->type = V_DUM; v->f0 = 85; v->f1 = 45; v->dur = 0.15f; v->amp = 0.22f; v->pan = 0.5f; v->send = 0.05f; v_noise(900, 0.09f, 0.08f, 0); break; }
    case SFX_STEP: v_tek(0.045f, 0.5f + arnd() * 0.1f, 0, 0); break;
    case SFX_CLIMB: v_noise(1400, 0.05f, 0.05f, 0); break;
    case SFX_KEY: v_bell(1318.5f, 0.6f, 0.18f, 0.55f, 0); v_bell(1975.5f, 0.8f, 0.14f, 0.45f, 70 * ms); v_pluck(86, 0.2f, 0.5f, 0, 0, 0.998f); break;
    case SFX_DOOR: v_rumble(1.1f, 0.35f); v_noise(260, 1.0f, 0.22f, 0); v_dum(0.4f, 900 * ms, 0); break;
    case SFX_TREASURE: {
        static const float arp[] = { 74, 78, 81, 86, 85, 86 };
        for (int i = 0; i < 6; i++) v_bell(mtof(arp[i]), 0.9f, 0.15f, 0.3f + 0.08f * i, i * 80 * ms);
        v_ney(86, 0.9f, 0.12f, 0.5f, 480 * ms, 0);
        break;
    }
    case SFX_DEATH: v_sweep(700, 70, 0.8f, 0.28f, 7, 0); v_noise(1200, 0.5f, 0.18f, 0); v_dum(0.5f, 0, 0); break;
    case SFX_SPRING: v_sweep(170, 760, 0.3f, 0.22f, 26, 0); break;
    case SFX_LASER: v_sweep(1500, 1320, 0.3f, 0.06f, 55, 0); v_noise(5000, 0.12f, 0.03f, 0); break;
    case SFX_SPIKE: v_tek(0.10f, 0.5f, 0, 0); v_noise(4000, 0.06f, 0.04f, 0); break;
    case SFX_MENU: v_pluck(81, 0.22f, 0.5f, 0, 0, 0.995f); break;
    case SFX_SELECT: v_pluck(74, 0.3f, 0.45f, 0, 0, 0.997f); v_pluck(81, 0.28f, 0.55f, 60 * ms, 0, 0.997f); break;
    case SFX_LOCKED: v_tek(0.3f, 0.5f, 0, 0); v_sweep(140, 110, 0.15f, 0.15f, 0, 0); break;
    case SFX_ROUND: {
        static const float m[] = { 62, 66, 69, 74, 73, 74, 78, 81 };
        for (int i = 0; i < 8; i++) v_pluck(m[i], 0.4f, 0.4f + 0.03f * i, i * 140 * ms, 0, 0.998f);
        v_ney(86, 1.6f, 0.15f, 0.5f, 1120 * ms, 0);
        break;
    }
    case SFX_GAMEOVER: {
        static const float m[] = { 69, 67, 66, 63, 62 };
        for (int i = 0; i < 5; i++) v_ney(m[i], i == 4 ? 1.4f : 0.32f, 0.2f, 0.5f, i * 380 * ms, 0);
        break;
    }
    }
    aunlock();
}
