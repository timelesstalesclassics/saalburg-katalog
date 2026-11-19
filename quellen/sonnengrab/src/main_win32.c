/* Windows-Plattformschicht für Sonnengrab: Fenster, Tastatur, Gamepad, Ton */
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <mmsystem.h>
#include <string.h>
#include "game.h"

void game_icon(unsigned int *argb, int size);

static unsigned int fb[SCR_W * SCR_H];
static BITMAPINFO bmi;
static HWND hwnd;
static HDC hdc;
static volatile int keys[256];
static int running = 1;
static WINDOWPLACEMENT wp_prev = { sizeof(WINDOWPLACEMENT) };

/* ---------------- Gamepad (XInput, dynamisch geladen) ---------------- */
typedef struct { WORD wButtons; BYTE bLeftTrigger, bRightTrigger; SHORT sThumbLX, sThumbLY, sThumbRX, sThumbRY; } XGamepad;
typedef struct { DWORD dwPacketNumber; XGamepad Gamepad; } XState;
typedef DWORD(WINAPI *XInputGetState_t)(DWORD, XState *);
static XInputGetState_t pXInputGetState = 0;
static void load_xinput(void) {
    const wchar_t *names[] = { L"xinput1_4.dll", L"xinput1_3.dll", L"xinput9_1_0.dll" };
    for (int i = 0; i < 3 && !pXInputGetState; i++) {
        HMODULE m = LoadLibraryW(names[i]);
        if (m) pXInputGetState = (XInputGetState_t)(void *)GetProcAddress(m, "XInputGetState");
    }
}

/* ---------------- Ton ---------------- */
#define ABUFS 4
#define AFRAMES 512
static HWAVEOUT hwo;
static WAVEHDR hdrs[ABUFS];
static short abuf[ABUFS][AFRAMES * 2];
static CRITICAL_SECTION acs;
static HANDLE aevent, athread;
static volatile int arunning = 1;
static void alock_w(void) { EnterCriticalSection(&acs); }
static void aunlock_w(void) { LeaveCriticalSection(&acs); }
static DWORD WINAPI audio_thread(LPVOID p) {
    (void)p;
    while (arunning) {
        WaitForSingleObject(aevent, 30);
        for (int i = 0; i < ABUFS; i++) {
            if (hdrs[i].dwFlags & WHDR_DONE) {
                audio_mix(abuf[i], AFRAMES);
                waveOutWrite(hwo, &hdrs[i], sizeof(WAVEHDR));
            }
        }
    }
    return 0;
}
static void audio_start(void) {
    InitializeCriticalSection(&acs);
    audio_set_lock(alock_w, aunlock_w);
    audio_init(44100);
    aevent = CreateEventW(0, FALSE, FALSE, 0);
    WAVEFORMATEX wf;
    memset(&wf, 0, sizeof wf);
    wf.wFormatTag = WAVE_FORMAT_PCM; wf.nChannels = 2; wf.nSamplesPerSec = 44100;
    wf.wBitsPerSample = 16; wf.nBlockAlign = 4; wf.nAvgBytesPerSec = 44100 * 4;
    if (waveOutOpen(&hwo, WAVE_MAPPER, &wf, (DWORD_PTR)aevent, 0, CALLBACK_EVENT) != MMSYSERR_NOERROR) { hwo = 0; return; }
    for (int i = 0; i < ABUFS; i++) {
        memset(&hdrs[i], 0, sizeof(WAVEHDR));
        hdrs[i].lpData = (LPSTR)abuf[i];
        hdrs[i].dwBufferLength = AFRAMES * 4;
        waveOutPrepareHeader(hwo, &hdrs[i], sizeof(WAVEHDR));
        audio_mix(abuf[i], AFRAMES);
        waveOutWrite(hwo, &hdrs[i], sizeof(WAVEHDR));
    }
    athread = CreateThread(0, 0, audio_thread, 0, 0, 0);
    SetThreadPriority(athread, THREAD_PRIORITY_ABOVE_NORMAL);
}
static void audio_stop(void) {
    if (!hwo) return;
    arunning = 0;
    SetEvent(aevent);
    WaitForSingleObject(athread, 500);
    waveOutReset(hwo);
    for (int i = 0; i < ABUFS; i++) waveOutUnprepareHeader(hwo, &hdrs[i], sizeof(WAVEHDR));
    waveOutClose(hwo);
}

/* ---------------- Fenster ---------------- */
static void toggle_fullscreen(void) {
    DWORD style = (DWORD)GetWindowLongW(hwnd, GWL_STYLE);
    if (style & WS_OVERLAPPEDWINDOW) {
        MONITORINFO mi = { sizeof(mi) };
        if (GetWindowPlacement(hwnd, &wp_prev) && GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY), &mi)) {
            SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_OVERLAPPEDWINDOW);
            SetWindowPos(hwnd, HWND_TOP, mi.rcMonitor.left, mi.rcMonitor.top,
                         mi.rcMonitor.right - mi.rcMonitor.left, mi.rcMonitor.bottom - mi.rcMonitor.top,
                         SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
            ShowCursor(FALSE);
        }
    } else {
        SetWindowLongW(hwnd, GWL_STYLE, style | WS_OVERLAPPEDWINDOW);
        SetWindowPlacement(hwnd, &wp_prev);
        SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
        ShowCursor(TRUE);
    }
}

static void blit(void) {
    RECT rc; GetClientRect(hwnd, &rc);
    int cw = rc.right - rc.left, ch = rc.bottom - rc.top;
    if (cw <= 0 || ch <= 0) return;
    float sx = (float)cw / SCR_W, sy = (float)ch / SCR_H;
    float s = sx < sy ? sx : sy;
    if (s >= 1.0f) { float fl = (float)(int)s; if (fl >= 1 && s - fl < 0.5f) s = fl; } /* möglichst ganzzahlig, scharfe Pixel */
    int w = (int)(SCR_W * s), h = (int)(SCR_H * s);
    int x = (cw - w) / 2, y = (ch - h) / 2;
    if (y > 0) { PatBlt(hdc, 0, 0, cw, y, BLACKNESS); PatBlt(hdc, 0, y + h, cw, ch - y - h, BLACKNESS); }
    if (x > 0) { PatBlt(hdc, 0, 0, x, ch, BLACKNESS); PatBlt(hdc, x + w, 0, cw - x - w, ch, BLACKNESS); }
    SetStretchBltMode(hdc, COLORONCOLOR);
    StretchDIBits(hdc, x, y, w, h, 0, 0, SCR_W, SCR_H, fb, &bmi, DIB_RGB_COLORS, SRCCOPY);
}

static LRESULT CALLBACK wndproc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CLOSE: running = 0; return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    case WM_KILLFOCUS: memset((void *)keys, 0, sizeof(keys)); return 0;
    case WM_KEYDOWN: case WM_SYSKEYDOWN:
        if (wp == VK_F11 && !(lp & (1 << 30))) { toggle_fullscreen(); return 0; }
        if (wp == VK_RETURN && (GetKeyState(VK_MENU) & 0x8000) && !(lp & (1 << 30))) { toggle_fullscreen(); return 0; }
        if (wp == VK_F4 && (GetKeyState(VK_MENU) & 0x8000)) { running = 0; return 0; }
        if (wp < 256) keys[wp] = 1;
        return 0;
    case WM_KEYUP: case WM_SYSKEYUP:
        if (wp < 256) keys[wp] = 0;
        return 0;
    case WM_SYSCHAR: return 0; /* kein Piepen bei Alt+Enter */
    case WM_SETCURSOR:
        if (LOWORD(lp) == HTCLIENT) { SetCursor(LoadCursor(0, IDC_ARROW)); return TRUE; }
        break;
    case WM_ERASEBKGND: return 1;
    case WM_PAINT: { PAINTSTRUCT ps; BeginPaint(h, &ps); blit(); EndPaint(h, &ps); return 0; }
    }
    return DefWindowProcW(h, msg, wp, lp);
}

static Input gather_input(void) {
    Input in; memset(&in, 0, sizeof in);
    in.left = keys[VK_LEFT] || keys['A'];
    in.right = keys[VK_RIGHT] || keys['D'];
    in.up = keys[VK_UP] || keys['W'];
    in.down = keys[VK_DOWN] || keys['S'];
    in.jump = keys[VK_SPACE];
    in.ljump = keys['X'] || keys[VK_CONTROL];
    in.run = keys[VK_SHIFT];
    in.pause = keys[VK_ESCAPE] || keys['P'];
    in.confirm = keys[VK_RETURN];
    in.music = keys['M'];
    in.sfx = keys['N'];
    if (pXInputGetState) {
        XState st;
        if (pXInputGetState(0, &st) == 0) {
            XGamepad *g = &st.Gamepad;
            if ((g->wButtons & 0x0004) || g->sThumbLX < -12000) in.left = 1;
            if ((g->wButtons & 0x0008) || g->sThumbLX > 12000) in.right = 1;
            if ((g->wButtons & 0x0001) || g->sThumbLY > 16000) in.up = 1;
            if ((g->wButtons & 0x0002) || g->sThumbLY < -16000) in.down = 1;
            if (g->wButtons & 0x1000) in.jump = 1;              /* A */
            if (g->wButtons & 0x4000) in.ljump = 1;             /* X */
            if ((g->wButtons & 0x2000) || g->bRightTrigger > 60) in.run = 1; /* B / RT */
            if (g->wButtons & 0x0010) in.pause = 1;             /* Start */
            if (g->wButtons & 0x0020) in.music = 1;             /* Back */
        }
    }
    return in;
}

static HICON make_icon(int size) {
    unsigned int px[48 * 48];
    game_icon(px, size);
    BITMAPV5HEADER bi; memset(&bi, 0, sizeof bi);
    bi.bV5Size = sizeof bi; bi.bV5Width = size; bi.bV5Height = -size; bi.bV5Planes = 1; bi.bV5BitCount = 32;
    bi.bV5Compression = BI_BITFIELDS; bi.bV5RedMask = 0x00FF0000; bi.bV5GreenMask = 0x0000FF00; bi.bV5BlueMask = 0x000000FF; bi.bV5AlphaMask = 0xFF000000;
    void *bits = 0;
    HDC dc = GetDC(0);
    HBITMAP col = CreateDIBSection(dc, (BITMAPINFO *)&bi, DIB_RGB_COLORS, &bits, 0, 0);
    ReleaseDC(0, dc);
    if (!col) return 0;
    memcpy(bits, px, size * size * 4);
    HBITMAP mask = CreateBitmap(size, size, 1, 1, 0);
    ICONINFO ii; ii.fIcon = TRUE; ii.xHotspot = ii.yHotspot = 0; ii.hbmMask = mask; ii.hbmColor = col;
    HICON ic = CreateIconIndirect(&ii);
    DeleteObject(col); DeleteObject(mask);
    return ic;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    (void)prev; (void)cmd;
    HMODULE user32 = LoadLibraryW(L"user32.dll");
    if (user32) {
        typedef BOOL(WINAPI * SPDA)(void);
        SPDA f = (SPDA)(void *)GetProcAddress(user32, "SetProcessDPIAware");
        if (f) f();
    }
    game_init();
    HICON big = make_icon(48), small = make_icon(16);
    WNDCLASSEXW wc; memset(&wc, 0, sizeof wc);
    wc.cbSize = sizeof wc; wc.style = CS_OWNDC | CS_HREDRAW | CS_VREDRAW; wc.lpfnWndProc = wndproc; wc.hInstance = inst;
    wc.hCursor = LoadCursor(0, IDC_ARROW); wc.lpszClassName = L"SonnengrabWnd"; wc.hIcon = big; wc.hIconSm = small;
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    RegisterClassExW(&wc);

    RECT wa; SystemParametersInfoW(SPI_GETWORKAREA, 0, &wa, 0);
    int aw = wa.right - wa.left, ah = wa.bottom - wa.top;
    int scale = 1;
    while (SCR_W * (scale + 1) <= aw * 0.92 && SCR_H * (scale + 1) + 40 <= ah * 0.92) scale++;
    RECT r = { 0, 0, SCR_W * scale, SCR_H * scale };
    AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW, FALSE);
    int ww = r.right - r.left, wh = r.bottom - r.top;
    hwnd = CreateWindowExW(0, wc.lpszClassName, L"Sonnengrab – Das Grab des Sonnenkönigs", WS_OVERLAPPEDWINDOW,
                           wa.left + (aw - ww) / 2, wa.top + (ah - wh) / 2, ww, wh, 0, 0, inst, 0);
    if (!hwnd) return 1;
    hdc = GetDC(hwnd);
    memset(&bmi, 0, sizeof bmi);
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = SCR_W; bmi.bmiHeader.biHeight = -SCR_H;
    bmi.bmiHeader.biPlanes = 1; bmi.bmiHeader.biBitCount = 32; bmi.bmiHeader.biCompression = BI_RGB;
    ShowWindow(hwnd, show);
    UpdateWindow(hwnd);
    load_xinput();
    audio_start();
    timeBeginPeriod(1);

    LARGE_INTEGER freq, last, now;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&last);
    double acc = 0, dt = 1.0 / 60.0;
    MSG msg;
    while (running) {
        while (PeekMessageW(&msg, 0, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) running = 0;
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        QueryPerformanceCounter(&now);
        acc += (double)(now.QuadPart - last.QuadPart) / freq.QuadPart;
        last = now;
        if (acc > 0.25) acc = 0.25;
        int stepped = 0;
        while (acc >= dt) {
            Input in = gather_input();
            game_update(&in);
            acc -= dt; stepped = 1;
            if (game_quit_requested()) running = 0;
            if (game_fullscreen_toggle_requested()) toggle_fullscreen();
        }
        if (stepped) { game_render(fb); blit(); }
        else Sleep(1);
    }
    audio_stop();
    timeEndPeriod(1);
    DestroyWindow(hwnd);
    return 0;
}
