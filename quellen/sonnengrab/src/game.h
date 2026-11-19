#ifndef SONNENGRAB_GAME_H
#define SONNENGRAB_GAME_H

#define SCR_W 480
#define SCR_H 276
#define HUD_H 20

typedef struct {
    unsigned char left, right, up, down;
    unsigned char jump;      /* Leertaste: hoher Sprung */
    unsigned char ljump;     /* X / Strg: flacher Weitsprung */
    unsigned char run;       /* Shift: rennen */
    unsigned char pause;     /* Esc */
    unsigned char confirm;   /* Enter */
    unsigned char music;     /* M */
    unsigned char sfx;       /* N */
} Input;

void game_init(void);
void game_update(const Input *in);          /* 60 Hz */
void game_render(unsigned int *fb);          /* SCR_W*SCR_H, 0x00RRGGBB */
int  game_quit_requested(void);
void game_focus_lost(void);              /* Fenster verliert den Fokus */
int  game_fullscreen_toggle_requested(void); /* liefert 1 einmalig nach Menüwahl */

void audio_init(int samplerate);
void audio_mix(short *out, int frames);      /* Stereo interleaved */
void audio_set_lock(void (*lock)(void), void (*unlock)(void));

#endif
