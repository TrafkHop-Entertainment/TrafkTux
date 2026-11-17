/*
 * TrafkPad.c - Controller-Steuerung fuers ganze System (TrafkTux)
 *
 * Verwandelt JEDES angeschlossene Gamepad in eine virtuelle Tastatur + Maus
 * (uinput). Keine App muss etwas davon wissen - fuer Hyprland, Launcher,
 * Widgets, Browser usw. ist es einfach eine normale Tastatur/Maus.
 *
 * Zustaende:
 *   AN  - Pads werden exklusiv abgegriffen (EVIOCGRAB) und in Tastatur/Maus
 *         uebersetzt. Flag-Datei ~/.cache/hypr/controller_mode_active
 *         existiert (Controls.lua liest sie, siehe Controller-Binds dort).
 *   AUS - Pads werden NICHT abgegriffen, nichts wird ausgegeben, Spiele/
 *         Steam sehen die Pads ganz normal. Es wird nur still auf die
 *         Toggle-Kombi gelauscht (Standard: L1+R1+Select+Start 1s halten).
 *
 * Belegung (Standard, siehe build_maps()):
 *   Linker Stick  = W A S D  (Config left_stick = arrows -> Pfeiltasten)
 *   D-Pad         = Pfeiltasten
 *   Rechter Stick = Mauszeiger
 *   A=Space  B=X  X=Backspace  Y=Tab  L1=Q  R1=E  Start=Enter  Select=Esc
 *   L2=Linksklick  R2=Rechtsklick  R3=Mittelklick  L3=Shift
 *   HOME gehalten = Ebene 2: Buttons senden F13-F24 (Controls.lua bindet
 *   diese NUR im Controller-Modus), Rechter Stick = Scrollen (4 Richtungen),
 *   Linker Stick = Fenster-Fokus, L2/R2 = Super+Maus (Fenster ziehen/skalieren)
 *
 * Kein systemd: wird aus Autostart.lua gestartet (Watchdog-Loop).
 * Steuerung von aussen:  TrafkPad --ctl toggle|on|off|status|reload|quit
 *
 * Build: gcc -O2 -Wall -Wextra -o TrafkPad TrafkPad.c $(pkg-config --cflags --libs libevdev) -lm
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <libevdev/libevdev-uinput.h>
#include <libevdev/libevdev.h>
#include <linux/input-event-codes.h>
#include <linux/input.h>
#include <math.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <sys/epoll.h>
#include <sys/inotify.h>
#include <sys/ioctl.h>
#include <sys/signalfd.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/timerfd.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define MAX_PADS 16
#define PAD_PROTO 4          /* Protokollstand der Socket-Befehle (Widget prueft das) */
#define TICK_MS 8
#define KEYS_USED 256

/* ───────────────────────── Eingaben (abstrakt) ───────────────────────── */
enum {
    I_A, I_B, I_X, I_Y, I_L1, I_R1, I_L2, I_R2, I_SELECT, I_START, I_HOME,
    I_L3, I_R3, I_DU, I_DD, I_DL, I_DR, I_SLU, I_SLD, I_SLL, I_SLR, I_COUNT
};
static const char *INPUT_NAMES[I_COUNT] = {
    "A", "B", "X", "Y", "L1", "R1", "L2", "R2", "SELECT", "START", "HOME",
    "L3", "R3", "DU", "DD", "DL", "DR", "SLU", "SLD", "SLL", "SLR"
};

typedef struct { uint8_t kind; uint16_t code; uint16_t mod; uint8_t mods; } Action; /* kind: 0 none, 1 key, 2 maus-btn, 3 scroll (code 0 hoch,1 runter,2 links,3 rechts); mods: Bit0 Shift, 1 Strg, 2 Alt, 3 Super */
#define NOACT      ((Action){0, 0, 0, 0})
#define K(c)       ((Action){1, (c), 0, 0})
#define KM(m, c)   ((Action){1, (c), (m), 0})
#define MB(c)      ((Action){2, (c), 0, 0})
#define MBM(m, c)  ((Action){2, (c), (m), 0})

typedef struct {
    bool enabled, start_active, left_wasd, swap_ab, swap_xy, swap_dpad, mouse_left, rumble, notify, sounds, scroll_invert;
    float stick_thr, mouse_dz, mouse_speed, mouse_curve, scroll_speed;
    unsigned combo_mask;
    int combo_hold_ms, combo_grace_ms;
    /* Achsen-/Tasten-Zuordnung: -2 = automatisch, -1 = keine, sonst evdev-Code */
    int ov_rx, ov_ry, ov_l2, ov_r2, home_btn, home_release_ms;
    bool debug, home_tap;
    char layout[48];                          /* aktives Layout: layouts/<name>.conf (Ueberschreibungen der Standardbelegung) */
    int stick_base, stick_home;               /* Maus-Stick: 0 aus, 1 Maus, 2 Scrollen (ohne / mit Home) */
    bool wii_pointer, wii_flip_x, wii_flip_y, wii_nun_flip_y;   /* Wiimote: IR-Zeiger, Achsen-Spiegelung */
    float wii_tau;                            /* Glaettung 1..4 -> Zeitkonstante in s (gross = traege) */
    int wii_mode, wii_alt_mode;               /* 0 absolut, 1 relativ (Delta), 2 Joystick (Abstand zur Mitte) */
    float wii_rel_scale;                      /* relativ: Pixel pro ganzer Bildschirmbreite */
    unsigned wii_combo_mask, wii_mode_mask;   /* Wiimote: Kombi AN/AUS, Kombi Zeigermodus (Bits = interne Eingaben) */
    int wii_mode_hold_ms;
    bool wii_area_active;                     /* Zeigerbereich folgt dem fokussierten Monitor (aktiver Workspace) */
    char wii_cur[64];                         /* beim Speichern fokussierter Monitor (Startwert fuer 'aktiv') */
    char wii_mons[512];                       /* "NAME x0 y0 x1 y1;NAME2 ..." (Anteile der Gesamtflaeche, vom Widget geschrieben) */
    float wii_x0, wii_y0, wii_x1, wii_y1;     /* Zeigerbereich als Anteil der gesamten Bildflaeche */
} Cfg;

typedef struct Pad {
    int fd;
    struct libevdev *dev;
    char path[300], name[96];
    struct input_absinfo ai[ABS_CNT > 64 ? 64 : ABS_CNT];
    bool src_btn[I_COUNT], src_abs[I_COUNT], down[I_COUNT];
    bool ignore[I_COUNT];          /* beim Aktivieren schon gehalten */
    bool pending[I_COUNT], swallowed[I_COUNT];
    int64_t pending_at[I_COUNT];
    Action held[I_COUNT];
    bool held_valid[I_COUNT];
    float lx, ly, rx, ry;
    bool home;
    bool combo_armed, combo_latch, mcombo_armed, mcombo_latch;
    int64_t combo_since, mcombo_since;
    int ff_id;
    bool ff_ok, grabbed;
    bool home_rel_pending; int64_t home_rel_at;   /* Home-Impulse zusammenfassen (Entprellen) */
    bool home_armed, home_used;     /* Tipp auf Home = naechste Taste kommt aus der Home-Ebene */
    int64_t home_armed_until, home_down_at;
    bool ax_set;
    int ax[4];                     /* rechter Stick X/Y, L2-/R2-Achse (-1 = keine) */
    int wii;                       /* 0 normales Pad, 1 Wiimote (Tasten), 2 Nunchuk, 3 IR-Kamera */
    char uniq[32];                 /* Bluetooth-Adresse: ordnet Nunchuk/IR dem richtigen Wiimote zu */
    int cx, cy;                    /* Nunchuk-Stick: Ruhelage */
} Pad;

/* welche evdev-Achse dient als ... (0 RX, 1 RY, 2 L2, 3 R2) */
static int ax_of(const Pad *p, int which) {
    static const int def[4] = { ABS_RX, ABS_RY, ABS_Z, ABS_RZ };
    return p->ax_set ? p->ax[which] : def[which];
}

static Cfg cfg;
static Action map_base[I_COUNT], map_home[I_COUNT];
static Action wmap_base[I_COUNT], wmap_home[I_COUNT];   /* Wiimote hat eigene Belegung (Layout-Schluessel wbase./whome.) */
static Pad *pads[MAX_PADS];
static struct { bool active; } g;

static int64_t (*clock_ms)(void);
static int64_t real_clock_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void logf_(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[TrafkPad] ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

/* ───────────────────────────── Ausgabe-Schicht ───────────────────────────── */
#ifdef TRAFKPAD_TEST
static char rec[16384];
static void rec_add(const char *fmt, ...) {
    va_list ap;
    size_t n = strlen(rec);
    va_start(ap, fmt);
    vsnprintf(rec + n, sizeof rec - n, fmt, ap);
    va_end(ap);
}
static void out_key(int code, int val)  { rec_add("K%d=%d ", code, val); }
static void out_btn(int code, int val)  { rec_add("B%d=%d ", code, val); }
static void out_rel(int code, int val)  { rec_add("R%d:%d ", code, val); }
static void out_abs(int code, int val)  { rec_add("A%d:%d ", code, val); }
#else
static struct libevdev_uinput *ui_kbd, *ui_mouse, *ui_ptr;
static void out_key(int code, int val) {
    if (!ui_kbd) return;
    libevdev_uinput_write_event(ui_kbd, EV_KEY, code, val);
    libevdev_uinput_write_event(ui_kbd, EV_SYN, SYN_REPORT, 0);
}
static void out_btn(int code, int val) {
    if (!ui_mouse) return;
    libevdev_uinput_write_event(ui_mouse, EV_KEY, code, val);
    libevdev_uinput_write_event(ui_mouse, EV_SYN, SYN_REPORT, 0);
}
static void out_rel(int code, int val) {
    if (!ui_mouse) return;
    libevdev_uinput_write_event(ui_mouse, EV_REL, code, val);
}
static void out_rel_sync(void) {
    if (ui_mouse) libevdev_uinput_write_event(ui_mouse, EV_SYN, SYN_REPORT, 0);
}
static void out_abs(int code, int val) {
    if (!ui_ptr) return;
    libevdev_uinput_write_event(ui_ptr, EV_ABS, code, val);
}
static void out_abs_sync(void) {
    if (ui_ptr) libevdev_uinput_write_event(ui_ptr, EV_SYN, SYN_REPORT, 0);
}
#endif

static int kref[KEYS_USED], bref[3];

static void key_ref(int code, int d) {
    if (code <= 0 || code >= KEYS_USED) return;
    if (d > 0) { if (kref[code]++ == 0) out_key(code, 1); }
    else if (kref[code] > 0 && --kref[code] == 0) out_key(code, 0);
}
static void btn_ref(int code, int d) {
    int i = code - BTN_LEFT;
    if (i < 0 || i > 2) return;
    if (d > 0) { if (bref[i]++ == 0) out_btn(code, 1); }
    else if (bref[i] > 0 && --bref[i] == 0) out_btn(code, 0);
}
static const int MOD_KEYS[4] = { KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_LEFTALT, KEY_LEFTMETA };
static void apply_action(const Action *a, int d) {
    if (!a->kind || a->kind == 3) return;         /* Scroll-Aktionen laufen im Tick, solange gehalten */
    if (d > 0) {
        if (a->mod) key_ref(a->mod, 1);
        for (int b = 0; b < 4; b++) if (a->mods & (1 << b)) key_ref(MOD_KEYS[b], 1);
        a->kind == 1 ? key_ref(a->code, 1) : btn_ref(a->code, 1);
    } else {
        a->kind == 1 ? key_ref(a->code, -1) : btn_ref(a->code, -1);
        for (int b = 3; b >= 0; b--) if (a->mods & (1 << b)) key_ref(MOD_KEYS[b], -1);
        if (a->mod) key_ref(a->mod, -1);
    }
}
static void release_all_outputs(void) {
    for (int c = 1; c < KEYS_USED; c++) if (kref[c] > 0) { kref[c] = 0; out_key(c, 0); }
    for (int i = 0; i < 3; i++) if (bref[i] > 0) { bref[i] = 0; out_btn(BTN_LEFT + i, 0); }
}

/* ─────────────────────────────── Belegung ─────────────────────────────── */
static void layout_apply(void);
static void build_maps(void) {
    memset(map_base, 0, sizeof map_base);
    memset(map_home, 0, sizeof map_home);
    map_base[I_A] = K(KEY_SPACE);      map_base[I_B] = K(KEY_X);
    map_base[I_X] = K(KEY_BACKSPACE);  map_base[I_Y] = K(KEY_TAB);
    map_base[I_L1] = K(KEY_Q);         map_base[I_R1] = K(KEY_E);
    map_base[I_L2] = MB(BTN_LEFT);     map_base[I_R2] = MB(BTN_RIGHT);
    map_base[I_SELECT] = K(KEY_ESC);   map_base[I_START] = K(KEY_ENTER);
    map_base[I_L3] = K(KEY_LEFTSHIFT); map_base[I_R3] = MB(BTN_MIDDLE);
    map_base[I_DU] = K(KEY_UP);   map_base[I_DD] = K(KEY_DOWN);
    map_base[I_DL] = K(KEY_LEFT); map_base[I_DR] = K(KEY_RIGHT);
    if (cfg.left_wasd) {
        map_base[I_SLU] = K(KEY_W); map_base[I_SLD] = K(KEY_S);
        map_base[I_SLL] = K(KEY_A); map_base[I_SLR] = K(KEY_D);
    } else {
        map_base[I_SLU] = K(KEY_UP);   map_base[I_SLD] = K(KEY_DOWN);
        map_base[I_SLL] = K(KEY_LEFT); map_base[I_SLR] = K(KEY_RIGHT);
    }
    /* Home-Ebene: F13..F24 (KEY_F13=183). Hyprland-Binds: "code:<evdev+8>"
       in Controls.lua. Linker Stick = Shift+F13..F16 (Fenster-Fokus). */
    map_home[I_A] = K(KEY_F13);  map_home[I_B] = K(KEY_F14);
    map_home[I_X] = K(KEY_F15);  map_home[I_Y] = K(KEY_F16);
    map_home[I_DU] = K(KEY_F17); map_home[I_DD] = K(KEY_F18);
    map_home[I_DL] = K(KEY_F19); map_home[I_DR] = K(KEY_F20);
    map_home[I_L1] = K(KEY_F21); map_home[I_R1] = K(KEY_F22);
    map_home[I_START] = K(KEY_F23); map_home[I_SELECT] = K(KEY_F24);
    map_home[I_L2] = MBM(KEY_LEFTMETA, BTN_LEFT);   /* Super+LMB = Fenster ziehen   */
    map_home[I_R2] = MBM(KEY_LEFTMETA, BTN_RIGHT);  /* Super+RMB = Fenster skalieren */
    map_home[I_SLU] = KM(KEY_LEFTSHIFT, KEY_F13);
    map_home[I_SLL] = KM(KEY_LEFTSHIFT, KEY_F14);
    map_home[I_SLD] = KM(KEY_LEFTSHIFT, KEY_F15);
    map_home[I_SLR] = KM(KEY_LEFTSHIFT, KEY_F16);
    if (cfg.swap_dpad) {                    /* D-Pad <-> linker Stick, in BEIDEN Ebenen */
        static const int dp[4] = { I_DU, I_DD, I_DL, I_DR }, sl[4] = { I_SLU, I_SLD, I_SLL, I_SLR };
        for (int k = 0; k < 4; k++) {
            Action t = map_base[dp[k]]; map_base[dp[k]] = map_base[sl[k]]; map_base[sl[k]] = t;
            t = map_home[dp[k]]; map_home[dp[k]] = map_home[sl[k]]; map_home[sl[k]] = t;
        }
        /* Linker Stick = Maus: die Stick-Richtungen (jetzt Launcher/Power/Settings/Expo)
           sind nicht erreichbar -> Launcher und Power-Menue auf Home + L3 / R3 legen. */
        if (cfg.mouse_left) { map_home[I_L3] = K(KEY_F17); map_home[I_R3] = K(KEY_F18); }
    }
    memcpy(wmap_base, map_base, sizeof wmap_base);
    memcpy(wmap_home, map_home, sizeof wmap_home);
    layout_apply();
}

/* ─────────────────────────────── Config ─────────────────────────────── */
static char cfg_path[512], flag_path[512], sock_path[108];
#ifdef TRAFKPAD_TEST
#define MAYBE_UNUSED __attribute__((unused))
#endif

static void cfg_defaults(void) {
    cfg = (Cfg){
        .enabled = true, .start_active = true, .left_wasd = true, .swap_ab = false,
        .rumble = true, .notify = true, .sounds = true, .scroll_invert = false,
        .stick_thr = 0.5f, .mouse_dz = 0.12f, .mouse_speed = 900.f, .mouse_curve = 1.8f,
        .scroll_speed = 1500.f, .combo_hold_ms = 1000, .combo_grace_ms = 80,
        .ov_rx = -2, .ov_ry = -2, .ov_l2 = -2, .ov_r2 = -2, .home_btn = BTN_MODE, .home_release_ms = 350, .debug = false, .home_tap = true,
        .wii_pointer = true, .wii_flip_x = true, .wii_flip_y = false, .wii_nun_flip_y = true,
        .layout = "default", .stick_base = 1, .stick_home = 2,
        .wii_tau = 0.2f, .wii_mode = 0, .wii_alt_mode = 1, .wii_rel_scale = 2500.f, .wii_x0 = 0.f, .wii_y0 = 0.f, .wii_x1 = 1.f, .wii_y1 = 1.f,
    };
    cfg.combo_mask = (1u << I_L1) | (1u << I_R1) | (1u << I_SELECT) | (1u << I_START);
    cfg.wii_combo_mask = (1u << I_START) | (1u << I_SELECT);      /* + und -  */
    cfg.wii_mode_mask = (1u << I_A) | (1u << I_B);                /* 1 und 2  */
    cfg.wii_mode_hold_ms = 600;
}
static bool parse_bool(const char *v, bool def) {
    if (!strcasecmp(v, "true") || !strcmp(v, "1") || !strcasecmp(v, "yes") || !strcasecmp(v, "on")) return true;
    if (!strcasecmp(v, "false") || !strcmp(v, "0") || !strcasecmp(v, "no") || !strcasecmp(v, "off")) return false;
    return def;
}
static unsigned parse_combo(const char *v) {
    unsigned m = 0;
    char buf[128];
    snprintf(buf, sizeof buf, "%s", v);
    for (char *t = strtok(buf, "+, "); t; t = strtok(NULL, "+, "))
        for (int i = 0; i <= I_DR; i++)
            if (!strcasecmp(t, INPUT_NAMES[i])) m |= 1u << i;
    return __builtin_popcount(m) >= 2 ? m : 0;
}
static float clampf(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }

/* "auto" | "none" | "ABS_Z" | "BTN_MODE" | Zahl  ->  Code (-2 auto, -1 keine) */
static int parse_code(const char *v, int type, int def) {
    if (!strcasecmp(v, "auto")) return -2;
    if (!strcasecmp(v, "none")) return -1;
    int c = libevdev_event_code_from_name(type, v);
    if (c >= 0) return c;
    if (*v >= '0' && *v <= '9') return atoi(v);
    return def;
}

static void cfg_apply_kv(const char *k, const char *v) {
    if (!strcmp(k, "enabled")) cfg.enabled = parse_bool(v, cfg.enabled);
    else if (!strcmp(k, "start_active")) cfg.start_active = parse_bool(v, cfg.start_active);
    else if (!strcmp(k, "left_stick")) cfg.left_wasd = strcasecmp(v, "arrows") != 0;
    else if (!strcmp(k, "swap_xy")) cfg.swap_xy = parse_bool(v, cfg.swap_xy);
    else if (!strcmp(k, "nintendo_layout")) cfg.swap_ab = cfg.swap_xy = parse_bool(v, cfg.swap_ab);
    else if (!strcmp(k, "swap_dpad")) cfg.swap_dpad = parse_bool(v, cfg.swap_dpad);
    else if (!strcmp(k, "mouse_stick")) cfg.mouse_left = strcasecmp(v, "left") == 0;
    else if (!strcmp(k, "swap_ab")) cfg.swap_ab = parse_bool(v, cfg.swap_ab);
    else if (!strcmp(k, "rumble")) cfg.rumble = parse_bool(v, cfg.rumble);
    else if (!strcmp(k, "notify")) cfg.notify = parse_bool(v, cfg.notify);
    else if (!strcmp(k, "sounds")) cfg.sounds = parse_bool(v, cfg.sounds);
    else if (!strcmp(k, "scroll_invert")) cfg.scroll_invert = parse_bool(v, cfg.scroll_invert);
    else if (!strcmp(k, "stick_threshold")) cfg.stick_thr = clampf(atof(v), 0.2f, 0.9f);
    else if (!strcmp(k, "mouse_deadzone")) cfg.mouse_dz = clampf(atof(v), 0.0f, 0.6f);
    else if (!strcmp(k, "mouse_speed")) cfg.mouse_speed = clampf(atof(v), 50.f, 6000.f);
    else if (!strcmp(k, "mouse_curve")) cfg.mouse_curve = clampf(atof(v), 1.0f, 4.0f);
    else if (!strcmp(k, "scroll_speed")) cfg.scroll_speed = clampf(atof(v), 100.f, 10000.f);
    else if (!strcmp(k, "toggle_hold_ms")) cfg.combo_hold_ms = (int)clampf(atoi(v), 300, 5000);
    else if (!strcmp(k, "combo_grace_ms")) cfg.combo_grace_ms = (int)clampf(atoi(v), 0, 300);
    else if (!strcmp(k, "home_release_ms")) cfg.home_release_ms = (int)clampf(atoi(v), 0, 1500);
    else if (!strcmp(k, "home_tap")) cfg.home_tap = parse_bool(v, cfg.home_tap);
    else if (!strcmp(k, "debug")) cfg.debug = parse_bool(v, cfg.debug);
    else if (!strcmp(k, "wii_pointer")) cfg.wii_pointer = parse_bool(v, cfg.wii_pointer);
    else if (!strcmp(k, "wii_flip_x")) cfg.wii_flip_x = parse_bool(v, cfg.wii_flip_x);
    else if (!strcmp(k, "wii_flip_y")) cfg.wii_flip_y = parse_bool(v, cfg.wii_flip_y);
    else if (!strcmp(k, "wii_smooth")) { static const float tau[6] = { 0.15f, 0.9f, 0.45f, 0.2f, 0.08f, 0.f }; int l = (int)clampf((float)atoi(v), 1.f, 5.f); cfg.wii_tau = tau[l];   /* 1 = extrem glatt ... 5 = roh */ }
    else if (!strcmp(k, "layout")) {
        size_t i = 0;
        for (const char *c = v; *c && i < sizeof cfg.layout - 1; c++)
            if (isalnum((unsigned char)*c) || *c == '_' || *c == '-') cfg.layout[i++] = (char)tolower((unsigned char)*c);
        cfg.layout[i] = 0;
        if (!i) snprintf(cfg.layout, sizeof cfg.layout, "default");
    }
    else if (!strcmp(k, "wii_mode") || !strcmp(k, "wii_alt_mode")) {
        int m = !strcmp(v, "rel") ? 1 : !strcmp(v, "joy") ? 2 : 0;
        if (!strcmp(k, "wii_mode")) cfg.wii_mode = m; else cfg.wii_alt_mode = m ? m : 1;
    }
    else if (!strcmp(k, "wii_rel_scale")) cfg.wii_rel_scale = clampf((float)atof(v), 300.f, 8000.f);
    else if (!strcmp(k, "wii_toggle_combo")) { unsigned m = parse_combo(v); if (m) cfg.wii_combo_mask = m; }
    else if (!strcmp(k, "wii_mode_combo")) { if (!strcasecmp(v, "none")) cfg.wii_mode_mask = 0; else { unsigned m = parse_combo(v); if (m) cfg.wii_mode_mask = m; } }
    else if (!strcmp(k, "wii_mode_hold_ms")) cfg.wii_mode_hold_ms = (int)clampf((float)atoi(v), 200, 3000);
    else if (!strcmp(k, "wii_area")) cfg.wii_area_active = !strcmp(v, "active");
    else if (!strcmp(k, "wii_mons")) snprintf(cfg.wii_mons, sizeof cfg.wii_mons, "%s", v);
    else if (!strcmp(k, "wii_cur")) snprintf(cfg.wii_cur, sizeof cfg.wii_cur, "%s", v);
    else if (!strcmp(k, "wii_rect")) {
        float a, b, c, d;
        if (sscanf(v, "%f %f %f %f", &a, &b, &c, &d) == 4 && c - a > 0.01f && d - b > 0.01f
            && a >= 0 && b >= 0 && c <= 1.001f && d <= 1.001f) { cfg.wii_x0 = a; cfg.wii_y0 = b; cfg.wii_x1 = c; cfg.wii_y1 = d; }
    }
    else if (!strcmp(k, "wii_nunchuk_flip_y")) cfg.wii_nun_flip_y = parse_bool(v, cfg.wii_nun_flip_y);
    else if (!strcmp(k, "rstick_x")) cfg.ov_rx = parse_code(v, EV_ABS, cfg.ov_rx);
    else if (!strcmp(k, "rstick_y")) cfg.ov_ry = parse_code(v, EV_ABS, cfg.ov_ry);
    else if (!strcmp(k, "l2_axis")) cfg.ov_l2 = parse_code(v, EV_ABS, cfg.ov_l2);
    else if (!strcmp(k, "r2_axis")) cfg.ov_r2 = parse_code(v, EV_ABS, cfg.ov_r2);
    else if (!strcmp(k, "home_button")) { int c = parse_code(v, EV_KEY, cfg.home_btn); cfg.home_btn = c < 0 ? BTN_MODE : c; }
    else if (!strcmp(k, "toggle_combo")) { unsigned m = parse_combo(v); if (m) cfg.combo_mask = m; }
}

/* ───────────────────── Layout-Dateien (Mapping-Editor) ─────────────────────
 * layouts/<name>.conf enthaelt NUR Ueberschreibungen der Standardbelegung:
 *   base.A = space          home.A = f13          base.L2 = mouse:left
 *   home.R1 = ctrl+shift+t  base.DU = scroll:up   base.L3 = none
 *   stick.base = mouse      stick.home = scroll   (mouse|scroll|none)
 * Eingaben: A B X Y L1 R1 L2 R2 SELECT START L3 R3 DU DD DL DR SLU SLD SLL SLR (HOME bleibt Ebenentaste) */
static char layout_dir[512];

static bool parse_action(const char *v, Action *out) {
    char buf[96]; snprintf(buf, sizeof buf, "%s", v);
    for (char *c = buf; *c; c++) *c = (char)tolower((unsigned char)*c);
    char *toks[6]; int nt = 0;
    for (char *t = strtok(buf, "+"); t && nt < 6; t = strtok(NULL, "+")) toks[nt++] = t;
    if (nt == 0) return false;
    Action a = {0};
    int last = nt - 1;
    for (int k = 0; k < last; k++) {
        if (!strcmp(toks[k], "shift")) a.mods |= 1; else if (!strcmp(toks[k], "ctrl")) a.mods |= 2;
        else if (!strcmp(toks[k], "alt")) a.mods |= 4; else if (!strcmp(toks[k], "super")) a.mods |= 8;
        else return false;
    }
    const char *t = toks[last];
    if (!strcmp(t, "none")) { *out = NOACT; return true; }
    if (!strncmp(t, "mouse:", 6)) {
        int c = !strcmp(t + 6, "left") ? BTN_LEFT : !strcmp(t + 6, "right") ? BTN_RIGHT : !strcmp(t + 6, "middle") ? BTN_MIDDLE : -1;
        if (c < 0) return false;
        a.kind = 2; a.code = (uint16_t)c;
    } else if (!strncmp(t, "scroll:", 7)) {
        int c = !strcmp(t + 7, "up") ? 0 : !strcmp(t + 7, "down") ? 1 : !strcmp(t + 7, "left") ? 2 : !strcmp(t + 7, "right") ? 3 : -1;
        if (c < 0) return false;
        a.kind = 3; a.code = (uint16_t)c;
    } else {
        char nm[64];
        if (nt == 1 && (!strcmp(t, "shift") || !strcmp(t, "ctrl") || !strcmp(t, "alt") || !strcmp(t, "super"))) {
            a.kind = 1; a.code = (uint16_t)(!strcmp(t, "shift") ? KEY_LEFTSHIFT : !strcmp(t, "ctrl") ? KEY_LEFTCTRL : !strcmp(t, "alt") ? KEY_LEFTALT : KEY_LEFTMETA);
            *out = a; return true;
        }
        snprintf(nm, sizeof nm, "KEY_%s", t);
        for (char *c = nm; *c; c++) *c = (char)toupper((unsigned char)*c);
        int c = libevdev_event_code_from_name(EV_KEY, nm);
        if (c < 0) return false;
        a.kind = 1; a.code = (uint16_t)c;
    }
    *out = a;
    return true;
}

static void action_str(const Action *a, char *out, size_t n) {
    out[0] = 0;
    if (!a->kind) { snprintf(out, n, "none"); return; }
    size_t l = 0;
    static const char *mn[4] = { "shift", "ctrl", "alt", "super" };
    for (int b = 0; b < 4; b++) if (a->mods & (1 << b)) l += (size_t)snprintf(out + l, n - l, "%s+", mn[b]);
    if (a->mod) {                              /* eingebaute Belegungen (Super+LMB, Shift+F13, ...) */
        const char *m = a->mod == KEY_LEFTSHIFT ? "shift" : a->mod == KEY_LEFTCTRL ? "ctrl" : a->mod == KEY_LEFTALT ? "alt" : a->mod == KEY_LEFTMETA ? "super" : NULL;
        if (m) l += (size_t)snprintf(out + l, n - l, "%s+", m);
    }
    if (a->kind == 2) snprintf(out + l, n - l, "mouse:%s", a->code == BTN_LEFT ? "left" : a->code == BTN_RIGHT ? "right" : "middle");
    else if (a->kind == 3) snprintf(out + l, n - l, "scroll:%s", a->code == 0 ? "up" : a->code == 1 ? "down" : a->code == 2 ? "left" : "right");
    else {
        const char *nm = libevdev_event_code_get_name(EV_KEY, a->code);
        if (!nm) { snprintf(out + l, n - l, "none"); return; }
        if (!strncmp(nm, "KEY_", 4)) nm += 4;
        size_t k = 0;
        for (; nm[k] && l + k < n - 1; k++) out[l + k] = (char)tolower((unsigned char)nm[k]);
        out[l + k] = 0;
    }
}

static int input_by_name(const char *nm) {
    for (int i = 0; i < I_COUNT; i++) if (!strcasecmp(nm, INPUT_NAMES[i])) return i;
    return -1;
}

static int stick_mode_by_name(const char *v) { return !strcmp(v, "mouse") ? 1 : !strcmp(v, "scroll") ? 2 : !strcmp(v, "none") ? 0 : -1; }

static void layout_apply(void) {
    if (!layout_dir[0] || !cfg.layout[0]) return;
    char path[640]; snprintf(path, sizeof path, "%s/%s.conf", layout_dir, cfg.layout);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char line[160];
    while (fgets(line, sizeof line, f)) {
        char *h = strchr(line, '#'); if (h) *h = 0;
        char *eq = strchr(line, '='); if (!eq) continue;
        *eq = 0;
        char *k = line, *v = eq + 1;
        while (*k == ' ' || *k == '\t') k++;
        for (char *e = k + strlen(k); e > k && (e[-1] == ' ' || e[-1] == '\t'); ) *--e = 0;
        while (*v == ' ' || *v == '\t') v++;
        for (char *e = v + strlen(v); e > v && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\n' || e[-1] == '\r'); ) *--e = 0;
        if (!strncmp(k, "stick.", 6)) {
            int m = stick_mode_by_name(v);
            if (m >= 0) { if (!strcmp(k + 6, "base")) cfg.stick_base = m; else if (!strcmp(k + 6, "home")) cfg.stick_home = m; }
            continue;
        }
        Action *map = !strncmp(k, "base.", 5) ? map_base : !strncmp(k, "home.", 5) ? map_home
                    : !strncmp(k, "wbase.", 6) ? wmap_base : !strncmp(k, "whome.", 6) ? wmap_home : NULL;
        if (!map) continue;
        int in = input_by_name(k + (map == wmap_base || map == wmap_home ? 6 : 5));
        Action a;
        if (in < 0 || in == I_HOME || !parse_action(v, &a)) continue;
        map[in] = a;
    }
    fclose(f);
}

static void cfg_load(void) {
    cfg_defaults();
    FILE *f = fopen(cfg_path, "r");
    if (!f) { build_maps(); return; }        /* Datei fehlt = Standardwerte (AN) */
    char line[256];
    while (fgets(line, sizeof line, f)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == ';' || *p == '\n' || !*p) continue;
        char *eq = strchr(p, '=');
        if (!eq) continue;
        *eq = 0;
        char *k = p, *v = eq + 1;
        for (char *e = k + strlen(k); e > k && (e[-1] == ' ' || e[-1] == '\t'); ) *--e = 0;
        while (*v == ' ' || *v == '\t') v++;
        char *h = strchr(v, '#');
        if (h) *h = 0;
        for (char *e = v + strlen(v); e > v && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\n' || e[-1] == '\r'); ) *--e = 0;
        cfg_apply_kv(k, v);
    }
    fclose(f);
    build_maps();
}

/* ──────────────────────── Nebenwirkungen (Sound, Notify, Flag) ───────────────────────── */
#ifndef TRAFKPAD_TEST
static void spawn_sh(const char *cmd) {
    pid_t pid = fork();
    if (pid == 0) {
        setsid();
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        _exit(127);
    }
}
static void set_flag_file(bool on) {
    if (on) {
        char dir[512];
        snprintf(dir, sizeof dir, "%s", flag_path);
        char *s = strrchr(dir, '/');
        if (s) { *s = 0; mkdir(dir, 0755); }
        int fd = open(flag_path, O_CREAT | O_WRONLY, 0644);
        if (fd >= 0) close(fd);
    } else unlink(flag_path);
}
static void rumble(Pad *p, int ms) {
    if (!cfg.rumble || !p->dev || p->fd < 0 || !p->ff_ok) return;
    struct ff_effect e;
    memset(&e, 0, sizeof e);
    e.type = FF_RUMBLE;
    e.id = p->ff_id;
    e.u.rumble.strong_magnitude = 0x5000;
    e.u.rumble.weak_magnitude = 0x3000;
    e.replay.length = ms;
    if (ioctl(p->fd, EVIOCSFF, &e) < 0) { p->ff_ok = false; return; }
    p->ff_id = e.id;
    struct input_event ev = { .type = EV_FF, .code = (uint16_t)p->ff_id, .value = 1 };
    if (write(p->fd, &ev, sizeof ev) < 0) p->ff_ok = false;
}
#else
static void spawn_sh(const char *cmd) { (void)cmd; }
static void wii_cal_save(void) {}
static void wii_cal_notify(const char *msg) { (void)msg; }
static void set_flag_file(bool on) { rec_add("FLAG=%d ", on); }
static void rumble(Pad *p, int ms) { (void)p; (void)ms; }
#endif

static void pad_grab(Pad *p, bool on) {
    if (p->grabbed == on) return;
#ifndef TRAFKPAD_TEST
    if (p->dev && libevdev_grab(p->dev, on ? LIBEVDEV_GRAB : LIBEVDEV_UNGRAB) < 0) {
        logf_("grab(%d) fehlgeschlagen fuer %s: %s", on, p->name, strerror(errno));
        return;
    }
#endif
    p->grabbed = on;
}

/* ─────────────────────────────── Modus-Wechsel ─────────────────────────────── */
static void pad_reset_state(Pad *p) {
    memset(p->pending, 0, sizeof p->pending);
    memset(p->swallowed, 0, sizeof p->swallowed);
    memset(p->held_valid, 0, sizeof p->held_valid);
    p->home = false; p->home_armed = false; p->home_rel_pending = false;
}

static void set_active(bool on, bool announce) {
    if (g.active == on) return;
    g.active = on;
    if (on) {
        for (int i = 0; i < MAX_PADS; i++) if (pads[i]) {
            Pad *p = pads[i];
            pad_reset_state(p);
            /* Was gerade schon gehalten wird (z.B. die Toggle-Kombi selbst),
               zaehlt erst nach dem Loslassen wieder. */
            for (int k = 0; k < I_COUNT; k++) p->ignore[k] = p->down[k];
            p->combo_armed = false;
            p->combo_latch = true;
            p->mcombo_armed = false;
            p->mcombo_latch = true;
            pad_grab(p, true);
        }
    } else {
        release_all_outputs();
        for (int i = 0; i < MAX_PADS; i++) if (pads[i]) {
            pad_reset_state(pads[i]);
            pad_grab(pads[i], false);
            pads[i]->combo_armed = false;
            pads[i]->combo_latch = true;
        }
    }
    set_flag_file(on);
    logf_("Controller-Modus: %s", on ? "AN" : "AUS");
    if (announce) {
        for (int i = 0; i < MAX_PADS; i++) if (pads[i]) { rumble(pads[i], on ? 140 : 350); }
        if (cfg.sounds)
            spawn_sh(on ? "bash \"$HOME/.config/hypr/SoundCenter.sh\" Open >/dev/null 2>&1"
                        : "bash \"$HOME/.config/hypr/SoundCenter.sh\" Close >/dev/null 2>&1");
        if (cfg.notify)
            spawn_sh(on ? "command -v notify-send >/dev/null && notify-send -a TrafkPad -t 2000 -i input-gaming 'Controller-Modus: AN' 'Gamepad steuert den Desktop'"
                        : "command -v notify-send >/dev/null && notify-send -a TrafkPad -t 2000 -i input-gaming 'Controller-Modus: AUS' 'Gamepad gehoert wieder den Spielen'");
    }
}

/* ─────────────────────────────── Eingabe-Logik ─────────────────────────────── */
static unsigned toggle_mask(const Pad *p) { return p->wii == 1 ? cfg.wii_combo_mask : cfg.combo_mask; }
static unsigned mode_mask(const Pad *p) { return p->wii == 1 ? cfg.wii_mode_mask : 0; }
static bool mask_down(const Pad *p, unsigned m) {
    if (!m) return false;
    for (int i = 0; i <= I_DR; i++) if ((m & (1u << i)) && !p->down[i]) return false;
    return true;
}
static bool combo_down(const Pad *p) { return mask_down(p, toggle_mask(p)); }
static bool mcombo_down(const Pad *p) { return mask_down(p, mode_mask(p)); }
static bool combo_member(const Pad *p, int i) { return i <= I_DR && ((toggle_mask(p) | mode_mask(p)) & (1u << i)); }
static bool combo_partner(const Pad *p, int i, int j) {       /* i und j gehoeren zur selben Kombi */
    unsigned ms[2] = { toggle_mask(p), mode_mask(p) };
    for (int k = 0; k < 2; k++) if ((ms[k] & (1u << i)) && (ms[k] & (1u << j))) return true;
    return false;
}

/* Mapping-Editor offen: Eingaben werden nur angezeigt, nichts wird ausgefuehrt. Der Editor meldet sich
 * alle ~100 ms per "padmon"; bleibt die Meldung aus (Widget zu/abgestuerzt), gilt wieder alles normal. */
static int64_t mon_until;
static unsigned mon_seq;
static char mon_last[16];
static bool mon_last_w;
static bool monitoring(void) { return mon_until > clock_ms(); }

/* Home-Ebene aktiv? Entweder Home wird gehalten, oder es wurde kurz getippt
 * (home_tap, fuer Pads die Home nur als kurzen Impuls senden): dann gilt die
 * Ebene fuer die NAECHSTE Taste bzw. 4 s lang (Scrollen). */
#define HOME_TAP_MS    250
#define HOME_ARMED_MS  4000
static bool layer_on(Pad *p) {
    if (p->home) return true;
    if (p->home_armed && clock_ms() > p->home_armed_until) p->home_armed = false;
    return p->home_armed;
}

static void press_action(Pad *p, int i) {
    bool lay = layer_on(p);
    Action a = p->wii ? (lay ? wmap_home[i] : wmap_base[i]) : (lay ? map_home[i] : map_base[i]);
    if (lay) { p->home_used = true; if (!p->home) p->home_armed = false; }
    p->held[i] = a;
    p->held_valid[i] = true;
    apply_action(&a, +1);
}
static void release_action(Pad *p, int i) {
    if (!p->held_valid[i]) return;
    p->held_valid[i] = false;
    apply_action(&p->held[i], -1);
}

/* Fuer den Mapping-Editor: wirksame Belegung + Live-Zustand als Text */
static size_t dump_maps(char *out, size_t n) {
    size_t l = (size_t)snprintf(out, n, "layout=%s\nstick.base=%s\nstick.home=%s\n", cfg.layout,
        cfg.stick_base == 0 ? "none" : cfg.stick_base == 2 ? "scroll" : "mouse", cfg.stick_home == 0 ? "none" : cfg.stick_home == 2 ? "scroll" : "mouse");
    for (int lay = 0; lay < 2; lay++)
        for (int i = 0; i < I_COUNT; i++) {
            if (i == I_HOME) continue;
            char a[96]; action_str(lay ? &map_home[i] : &map_base[i], a, sizeof a);
            if (l < n) l += (size_t)snprintf(out + l, n - l, "%s.%s=%s\n", lay ? "home" : "base", INPUT_NAMES[i], a);
            action_str(lay ? &wmap_home[i] : &wmap_base[i], a, sizeof a);
            if (l < n) l += (size_t)snprintf(out + l, n - l, "%s.%s=%s\n", lay ? "whome" : "wbase", INPUT_NAMES[i], a);
        }
    return l < n ? l : n - 1;
}
static void pressed_str(char *out, size_t n) {
    bool dn[I_COUNT] = {0}, wd[I_COUNT] = {0}; bool lay = false, wlay = false;
    float lx = 0, ly = 0, rx = 0, ry = 0, wlx = 0, wly = 0, best = -1;
    for (int k = 0; k < MAX_PADS; k++) {
        Pad *p = pads[k];
        if (!p || p->wii >= 2) continue;
        if (p->wii == 1) {
            for (int i = 0; i < I_COUNT; i++) if (p->down[i]) wd[i] = true;
            if (layer_on(p)) wlay = true;
            if (fabsf(p->lx) + fabsf(p->ly) > fabsf(wlx) + fabsf(wly)) { wlx = p->lx; wly = p->ly; }
            continue;
        }
        for (int i = 0; i < I_COUNT; i++) if (p->down[i]) dn[i] = true;
        if (layer_on(p)) lay = true;
        float m = fabsf(p->lx) + fabsf(p->ly) + fabsf(p->rx) + fabsf(p->ry);
        if (m > best) { best = m; lx = p->lx; ly = p->ly; rx = p->rx; ry = p->ry; }
    }
    size_t l = 0;
    for (int w = 0; w < 2; w++) {
        bool *d = w ? wd : dn;
        l += (size_t)snprintf(out + l, n - l, "%s=", w ? "wdown" : "down");
        bool first = true;
        for (int i = 0; i < I_COUNT && l < n; i++) if (d[i]) { l += (size_t)snprintf(out + l, n - l, "%s%s", first ? "" : ",", INPUT_NAMES[i]); first = false; }
        if (first && l < n) l += (size_t)snprintf(out + l, n - l, "-");
        if (l < n) l += (size_t)snprintf(out + l, n - l, " ");
    }
    if (l < n) snprintf(out + l, n - l, "lx=%.2f ly=%.2f rx=%.2f ry=%.2f wlx=%.2f wly=%.2f layer=%s wlayer=%s seq=%u last=%s lastw=%d",
                        lx, ly, rx, ry, wlx, wly, lay ? "home" : "base", wlay ? "home" : "base", mon_seq, mon_last[0] ? mon_last : "-", mon_last_w ? 1 : 0);
}

static void combo_check(Pad *p) {
    bool d = combo_down(p);
    if (d && !p->combo_armed && !p->combo_latch) {
        p->combo_armed = true;
        p->combo_since = clock_ms();
        if (cfg.debug) logf_("Kombi: komplett, Haltezeit laeuft (%d ms)", cfg.combo_hold_ms);
    } else if (!d) {
        p->combo_armed = false;
        p->combo_latch = false;
    }
    bool m = mcombo_down(p);
    if (m && g.active && !p->mcombo_armed && !p->mcombo_latch) {
        p->mcombo_armed = true;
        p->mcombo_since = clock_ms();
    } else if (!m) {
        p->mcombo_armed = false;
        p->mcombo_latch = false;
    }
}

static bool detect_on;
static char detect_name[16];

static void on_input_change(Pad *p, int i, bool down) {
    if (down && detect_on) {                   /* Mapping-Editor: naechste Eingabe nur melden, nicht ausfuehren */
        snprintf(detect_name, sizeof detect_name, "%s", INPUT_NAMES[i]);
        detect_on = false;
        if (g.active) p->ignore[i] = true;
        return;
    }
    if (monitoring() && down) {                /* Mapping-Editor offen: nur anzeigen, nichts ausfuehren */
        mon_seq++; snprintf(mon_last, sizeof mon_last, "%s", INPUT_NAMES[i]); mon_last_w = p->wii == 1;
        if (g.active) p->ignore[i] = true;
        return;
    }
    if (cfg.debug)
        logf_("INPUT %s %s%s%s%s", INPUT_NAMES[i], down ? "down" : "up", g.active ? "" : " [Modus AUS]",
              p->ignore[i] ? " [ignoriert: schon beim Einschalten gehalten]" : "", p->home ? " [Home gehalten]" : "");
    if (!g.active) { combo_check(p); return; }
    if (p->ignore[i]) { if (!down) p->ignore[i] = false; combo_check(p); return; }
    if (i == I_HOME) {
        int64_t now = clock_ms();
        if (down) {
            p->home_down_at = now; p->home_used = false;
            if (p->home_armed) { p->home_armed = false; p->home_used = true; }  /* 2. Tipp = abbrechen */
            p->home = true;
        } else {
            p->home = false;
            if (cfg.home_tap && !p->home_used && now - p->home_down_at < HOME_TAP_MS) {
                p->home_armed = true; p->home_armed_until = now + HOME_ARMED_MS;
            }
        }
        combo_check(p);
        return;
    }

    if (down) {
        if (combo_member(p, i) && cfg.combo_grace_ms > 0) {
            bool other = false;
            for (int j = 0; j <= I_DR; j++)
                if (j != i && p->down[j] && combo_partner(p, i, j)) other = true;
            if (other) {                      /* sieht nach Kombi aus: verschlucken */
                p->swallowed[i] = true;
                for (int j = 0; j <= I_DR; j++)
                    if (p->pending[j] && combo_partner(p, i, j)) { p->pending[j] = false; p->swallowed[j] = true; }
            } else {
                p->pending[i] = true;
                p->pending_at[i] = clock_ms() + cfg.combo_grace_ms;
            }
        } else press_action(p, i);
    } else {
        if (p->swallowed[i]) p->swallowed[i] = false;
        else if (p->pending[i]) { p->pending[i] = false; press_action(p, i); release_action(p, i); }
        else release_action(p, i);
    }
    combo_check(p);
}

static void set_src(Pad *p, int i, bool is_abs, bool v) {
    bool *src = is_abs ? p->src_abs : p->src_btn;
    if (src[i] == v) return;
    src[i] = v;
    bool nd = p->src_btn[i] || p->src_abs[i];
    if (nd != p->down[i]) { p->down[i] = nd; on_input_change(p, i, nd); }
}

static float norm_axis(const Pad *p, int code, int value) {
    if (code >= 64) return 0;
    const struct input_absinfo *a = &p->ai[code];
    float range = (float)(a->maximum - a->minimum);
    if (range <= 0) return 0;
    return clampf(((float)value - (a->minimum + a->maximum) / 2.0f) / (range / 2.0f), -1.f, 1.f);
}
static float norm_trigger(const Pad *p, int code, int value) {
    if (code >= 64) return 0;
    const struct input_absinfo *a = &p->ai[code];
    float range = (float)(a->maximum - a->minimum);
    return range > 0 ? clampf(((float)value - a->minimum) / range, 0.f, 1.f) : 0;
}

static void update_left_stick(Pad *p) {
    float t = cfg.stick_thr, r = t * 0.7f;
    struct { int in; bool cur; float v; bool neg; } d[4] = {
        { I_SLU, p->src_abs[I_SLU], p->ly, true  }, { I_SLD, p->src_abs[I_SLD], p->ly, false },
        { I_SLL, p->src_abs[I_SLL], p->lx, true  }, { I_SLR, p->src_abs[I_SLR], p->lx, false },
    };
    for (int k = 0; k < 4; k++) {
        float m = d[k].neg ? -d[k].v : d[k].v;
        bool now = !cfg.mouse_left && (d[k].cur ? (m > r) : (m > t));   /* links = Maus: keine Tasten */
        set_src(p, d[k].in, true, now);
    }
}

static void pad_event(Pad *p, int type, int code, int value) {
    if (type == EV_KEY) {
        int in = -1;
        switch (code) {
        case BTN_SOUTH: in = cfg.swap_ab ? I_B : I_A; break;
        case BTN_EAST:  in = cfg.swap_ab ? I_A : I_B; break;
        case BTN_NORTH: in = cfg.swap_xy ? I_Y : I_X; break;
        case BTN_WEST:  in = cfg.swap_xy ? I_X : I_Y; break;
        case BTN_TL: in = I_L1; break;      case BTN_TR: in = I_R1; break;
        case BTN_TL2: in = I_L2; break;     case BTN_TR2: in = I_R2; break;
        case BTN_SELECT: in = I_SELECT; break; case BTN_START: in = I_START; break;
        case BTN_THUMBL: in = I_L3; break;  case BTN_THUMBR: in = I_R3; break;
        case BTN_DPAD_UP: in = I_DU; break; case BTN_DPAD_DOWN: in = I_DD; break;
        case BTN_DPAD_LEFT: in = I_DL; break; case BTN_DPAD_RIGHT: in = I_DR; break;
        }
        if (code == cfg.home_btn) {
            in = I_HOME;
            /* Manche Pads (8BitDo) senden Home nur als ~100 ms-Impuls, beim Halten als
             * Impulsfolge. Release deshalb verzoegern: Impulse verschmelzen zu "gehalten". */
            if (cfg.home_release_ms > 0) {
                if (value) { p->home_rel_pending = false; set_src(p, I_HOME, false, true); }
                else if (p->src_btn[I_HOME]) { p->home_rel_pending = true; p->home_rel_at = clock_ms() + cfg.home_release_ms; }
                return;
            }
        }
        if (in >= 0) set_src(p, in, false, value != 0);
    } else if (type == EV_ABS) {
        switch (code) {
        case ABS_X:  p->lx = norm_axis(p, code, value); update_left_stick(p); break;
        case ABS_Y:  p->ly = norm_axis(p, code, value); update_left_stick(p); break;
        case ABS_HAT0X: set_src(p, I_DL, true, value < 0); set_src(p, I_DR, true, value > 0); break;
        case ABS_HAT0Y: set_src(p, I_DU, true, value < 0); set_src(p, I_DD, true, value > 0); break;
        }
        if (code == ax_of(p, 0)) p->rx = norm_axis(p, code, value);
        if (code == ax_of(p, 1)) p->ry = norm_axis(p, code, value);
        if (code == ax_of(p, 2)) { float t = norm_trigger(p, code, value); set_src(p, I_L2, true, p->src_abs[I_L2] ? t > 0.35f : t > 0.5f); }
        if (code == ax_of(p, 3)) { float t = norm_trigger(p, code, value); set_src(p, I_R2, true, p->src_abs[I_R2] ? t > 0.35f : t > 0.5f); }
    }
}

/* ─────────────────────────────── Wiimote ───────────────────────────────
 * hid-wiimote legt mehrere evdev-Knoten an: "Nintendo Wii Remote" (Tasten, Rumble),
 * "... Nunchuk" (Stick, C, Z) und "... IR" (bis zu 4 Kamerapunkte). Alle drei fliessen
 * in EIN logisches Pad (den Tasten-Knoten): Home-Ebene, Toggle usw. gelten gemeinsam.
 * Zeiger: absolutes uinput-Geraet "TrafkPad Pointer", Mitte der beiden Sensorleisten-Punkte. */
/* Bei mehreren Wiimotes gehoeren Nunchuk/IR zum Wiimote mit gleicher Adresse (uniq).
 * Der IR-Zeiger kommt nur vom ersten (Haupt-)Wiimote. */
static Pad *wii_core_for(const Pad *src) {
    for (int i = 0; i < MAX_PADS; i++)
        if (pads[i] && pads[i]->wii == 1 && (!src->uniq[0] || !pads[i]->uniq[0] || !strcmp(pads[i]->uniq, src->uniq))) return pads[i];
    return NULL;
}
static bool wii_ir_primary(const Pad *ir_pad) {
    for (int i = 0; i < MAX_PADS; i++)
        if (pads[i] && pads[i]->wii == 1) return !ir_pad->uniq[0] || !pads[i]->uniq[0] || !strcmp(pads[i]->uniq, ir_pad->uniq);
    return false;
}

/* Kalibrierung: 1 = oben links zeigen + A, 2 = unten rechts zeigen + A */
static int wii_cal_step;
static float cal_u0 = 0.20f, cal_v0 = 0.20f, cal_u1 = 0.80f, cal_v1 = 0.80f;   /* Kamerabereich = Bildschirm */
static void wii_cal_save(void);
static void wii_cal_notify(const char *msg);
static bool ir_vis_now(void);
static float ir_u_now(void), ir_v_now(void);

static void wii_button(Pad *p, int code, int value) {
    int in = -1;
    if (wii_cal_step && code == BTN_SOUTH) {
        if (value == 1 && ir_vis_now()) {
            if (wii_cal_step == 1) { cal_u0 = ir_u_now(); cal_v0 = ir_v_now(); wii_cal_step = 2; wii_cal_notify("Kalibrierung 2/2: auf die UNTERE RECHTE Bildschirmecke zeigen und A druecken"); }
            else if (ir_u_now() - cal_u0 > 0.05f && ir_v_now() - cal_v0 > 0.05f) { cal_u1 = ir_u_now(); cal_v1 = ir_v_now(); wii_cal_step = 0; wii_cal_save(); wii_cal_notify("Kalibrierung fertig"); }
            else wii_cal_notify("Unten rechts muss unter/rechts von oben links liegen - nochmal");
        } else if (value == 1) wii_cal_notify("Sensorleiste nicht sichtbar");
        return;                              /* A gehoert waehrend der Kalibrierung nur der Kalibrierung */
    }
    switch (code) {
    case BTN_SOUTH: in = I_L2; break;       /* A = Linksklick */
    case BTN_EAST:  in = I_R2; break;       /* B (Zielknopf) = Rechtsklick */
    case BTN_1: in = I_A; break;            /* 1 = Space   */
    case BTN_2: in = I_B; break;            /* 2 = X       */
    case KEY_NEXT: in = I_START; break;     /* +  */
    case KEY_PREVIOUS: in = I_SELECT; break;/* -  */
    case BTN_MODE: in = I_HOME; break;
    case KEY_UP: in = I_DU; break;   case KEY_DOWN: in = I_DD; break;
    case KEY_LEFT: in = I_DL; break; case KEY_RIGHT: in = I_DR; break;
    }
    if (in >= 0 && value != 2) set_src(p, in, false, value != 0);
}

#define NUN_RANGE 95.0f
static void wii_nunchuk(Pad *p, int type, int code, int value) {
    Pad *c = wii_core_for(p);
    if (!c) return;
    if (type == EV_KEY) {
        if (code == BTN_Z && value != 2) set_src(c, I_L1, false, value != 0);   /* Z = Q */
        if (code == BTN_C && value != 2) set_src(c, I_R1, false, value != 0);   /* C = E */
    } else if (type == EV_ABS) {
        float sg = cfg.wii_nun_flip_y ? -1.f : 1.f;
        if (code == ABS_HAT0X) { c->lx = clampf((value - p->cx) / NUN_RANGE, -1.f, 1.f); update_left_stick(c); }
        if (code == ABS_HAT0Y) { c->ly = sg * clampf((value - p->cy) / NUN_RANGE, -1.f, 1.f); update_left_stick(c); }
    }
}

/* Modus: absolut (Desktop), relativ/Joystick (Spiele mit Mausfang). Umschalten per Tastenkombi
 * (wii_mode_combo) oder Socket ("wii-mode toggle"); bleibt bis zum naechsten Config-Reload. */
static int wii_mode_rt = -1;
static int wii_mode_eff(void) { return wii_mode_rt >= 0 ? wii_mode_rt : cfg.wii_mode; }
static void wii_mode_toggle(void) {
    static const char *names[] = { "absolut", "relativ", "Joystick" };
    wii_mode_rt = wii_mode_eff() == 0 ? cfg.wii_alt_mode : 0;
    char m[96]; snprintf(m, sizeof m, "Zeiger-Modus: %s", names[wii_mode_rt]); wii_cal_notify(m);
}
static float act_rect[4]; static bool act_ok;
static void set_active_mon(const char *name) {
    char list[sizeof cfg.wii_mons]; snprintf(list, sizeof list, "%s", cfg.wii_mons);
    for (char *e = strtok(list, ";"); e; e = strtok(NULL, ";")) {
        char nm[64]; float a, b, c2, d;
        if (sscanf(e, "%63s %f %f %f %f", nm, &a, &b, &c2, &d) == 5 && !strcmp(nm, name) && c2 - a > 0.01f && d - b > 0.01f) {
            act_rect[0] = a; act_rect[1] = b; act_rect[2] = c2; act_rect[3] = d; act_ok = true;
        }
    }
}
static void hypr_line(const char *line) {
    int pre = !strncmp(line, "focusedmonv2>>", 14) ? 14 : !strncmp(line, "focusedmon>>", 12) ? 12 : 0;
    if (!pre) return;                                           /* aktiver Workspace/Monitor wechselt */
    char name[64]; size_t i = 0;
    for (const char *c = line + pre; *c && *c != ',' && i < sizeof name - 1; c++) name[i++] = *c;
    name[i] = 0;
    set_active_mon(name);
}

/* IR-Zeiger */
static struct {
    bool have2, vis, init;
    float pa[2], pb[2], mid[2];
    float u, v;              /* roh, normiert 0..1 (nach Spiegelung) */
    float sx, sy;            /* geglaettet, Bildschirm 0..1 */
    int last_x, last_y;
    float tx, ty;            /* Ziel (kalibriert, 0..1) */
    bool dirty, fresh;       /* neue Rohdaten da / Zeiger gerade neu aufgetaucht */
    Pad *pad;                /* IR-Knoten */
} ir;
static bool ir_vis_now(void) { return ir.vis; }
static float ir_u_now(void) { return ir.u; }
static float ir_v_now(void) { return ir.v; }


static void ir_process(const int pts[][2], int n) {
    if (n <= 0) { ir.vis = false; return; }
    float mx_, my_;
    if (n >= 2) {
        int bi = 0, bj = 1; float bd = -1;
        for (int i = 0; i < n; i++) for (int j = i + 1; j < n; j++) {
            float d = hypotf((float)(pts[i][0] - pts[j][0]), (float)(pts[i][1] - pts[j][1]));
            if (d > bd) { bd = d; bi = i; bj = j; }
        }
        ir.pa[0] = pts[bi][0]; ir.pa[1] = pts[bi][1]; ir.pb[0] = pts[bj][0]; ir.pb[1] = pts[bj][1];
        ir.have2 = true;
        mx_ = (ir.pa[0] + ir.pb[0]) / 2; my_ = (ir.pa[1] + ir.pb[1]) / 2;
    } else {
        float q[2] = { (float)pts[0][0], (float)pts[0][1] };
        if (ir.have2) {      /* ein Punkt sichtbar: Versatz zur letzten Mitte vom naeheren Punkt uebernehmen */
            float da = hypotf(q[0] - ir.pa[0], q[1] - ir.pa[1]), db = hypotf(q[0] - ir.pb[0], q[1] - ir.pb[1]);
            float *near_ = da <= db ? ir.pa : ir.pb;
            float ox = (ir.pa[0] + ir.pb[0]) / 2 - near_[0], oy = (ir.pa[1] + ir.pb[1]) / 2 - near_[1];
            near_[0] = q[0]; near_[1] = q[1];
            mx_ = q[0] + ox; my_ = q[1] + oy;
        } else { mx_ = q[0]; my_ = q[1]; }
    }
    if (!ir.vis) ir.fresh = true;
    ir.vis = true;
    float u = clampf(mx_ / 1023.f, 0.f, 1.f), v = clampf(my_ / 767.f, 0.f, 1.f);
    if (cfg.wii_flip_x) u = 1.f - u;
    if (cfg.wii_flip_y) v = 1.f - v;
    ir.u = u; ir.v = v;
    ir.tx = clampf((u - cal_u0) / (cal_u1 - cal_u0), 0.f, 1.f);
    ir.ty = clampf((v - cal_v0) / (cal_v1 - cal_v0), 0.f, 1.f);
}

/* Glaettung nach ZEIT (nicht pro Ereignis) und Ausgabe; wird vom Tick aufgerufen. */
static void ir_emit(float dt) {
    static bool prev_reset;
    if (!ir.vis) { prev_reset = true; return; }
    if (!ir.init || ir.fresh) { prev_reset = true; ir.sx = ir.tx; ir.sy = ir.ty; ir.init = true; ir.fresh = false; ir.last_x = ir.last_y = -1; }
    else {
        float d = hypotf(ir.tx - ir.sx, ir.ty - ir.sy);
        float a = cfg.wii_tau > 0.f ? 1.f - expf(-dt / cfg.wii_tau) : 1.f;
        if (d > 0.25f) a = clampf(a + (d - 0.25f) * 4.f, a, 1.f);   /* nur echte Spruenge (neuer Zielpunkt) ohne Verzoegerung */
        ir.sx += (ir.tx - ir.sx) * a; ir.sy += (ir.ty - ir.sy) * a;
    }
    if (!g.active || !cfg.wii_pointer || monitoring()) return;
    int mode = wii_mode_eff();
    static float racc_x, racc_y, prev_sx, prev_sy; static bool prev_ok; static int prev_mode;
    if (mode != prev_mode || prev_reset) { prev_ok = false; racc_x = racc_y = 0; prev_mode = mode; prev_reset = false; }
    if (mode != 0) {
        float fx = 0, fy = 0;
        if (mode == 1) {                                   /* Delta wie eine Maus */
            if (prev_ok) { fx = (ir.sx - prev_sx) * cfg.wii_rel_scale; fy = (ir.sy - prev_sy) * cfg.wii_rel_scale * 0.5625f; }
            prev_sx = ir.sx; prev_sy = ir.sy; prev_ok = true;
        } else {                                            /* Abstand zur Bildschirmmitte = Geschwindigkeit */
            float vx = (ir.sx - 0.5f) * 2.f, vy = (ir.sy - 0.5f) * 2.f, dz = 0.15f;
            float mag = hypotf(vx, vy);
            if (mag > dz) {
                float k = powf(clampf((mag - dz) / (1.f - dz), 0.f, 1.f), 1.5f) / mag;
                fx = vx * k * cfg.mouse_speed * dt; fy = vy * k * cfg.mouse_speed * dt;
            }
        }
        racc_x += fx; racc_y += fy;
        int ix = (int)racc_x, iy = (int)racc_y;
        racc_x -= ix; racc_y -= iy;
        if (ix) out_rel(REL_X, ix);
        if (iy) out_rel(REL_Y, iy);
#ifndef TRAFKPAD_TEST
        if (ix || iy) out_rel_sync();
#endif
        return;
    }
    prev_ok = false;
    float rc[4] = { cfg.wii_x0, cfg.wii_y0, cfg.wii_x1, cfg.wii_y1 };
    if (cfg.wii_area_active && !act_ok && cfg.wii_cur[0]) set_active_mon(cfg.wii_cur);
    if (cfg.wii_area_active && act_ok) memcpy(rc, act_rect, sizeof rc);
    int ox = (int)((rc[0] + ir.sx * (rc[2] - rc[0])) * 32767.f + 0.5f);
    int oy = (int)((rc[1] + ir.sy * (rc[3] - rc[1])) * 32767.f + 0.5f);
    if (ox == ir.last_x && oy == ir.last_y) return;
    ir.last_x = ox; ir.last_y = oy;
    out_abs(ABS_X, ox); out_abs(ABS_Y, oy);
#ifndef TRAFKPAD_TEST
    out_abs_sync();
#endif
}

/* Rohpunkte aus dem libevdev-Zustand des IR-Knotens lesen (erst im Tick: ein IR-Bericht kommt
 * in mehreren SYN-Paketen, halbe Zustaende duerfen nicht ausgewertet werden). */
static void ir_poll(void) {
    if (!ir.dirty || !ir.pad) return;
    ir.dirty = false;
    int pts[4][2], n = 0;
    for (int k = 0; k < 4; k++) {
        int x = libevdev_get_event_value(ir.pad->dev, EV_ABS, ABS_HAT0X + 2 * k);
        int y = libevdev_get_event_value(ir.pad->dev, EV_ABS, ABS_HAT0Y + 2 * k);
        if (x >= 1023 && y >= 1023) continue;
        pts[n][0] = x; pts[n][1] = y; n++;
    }
    ir_process(pts, n);
}

/* ─────────────────────────── Tick: Maus, Scrollen, Timer ─────────────────────────── */
static float acc_x, acc_y, acc_sx, acc_sy;
static int notch_x, notch_y;
static int64_t last_tick;

/* Welcher Stick steuert Maus/Scrollen? (Standard rechts; mouse_stick = left: linker Stick) */
static float mx(const Pad *p) { return cfg.mouse_left ? p->lx : p->rx; }
static float my(const Pad *p) { return cfg.mouse_left ? p->ly : p->ry; }
static bool rstick_live(const Pad *p) { return hypotf(mx(p), my(p)) > cfg.mouse_dz; }

static void emit_wheel(int hires_code, int legacy_code, float *acc, int *notch) {
    int h = (int)*acc;
    if (!h) return;
    *acc -= h;
    out_rel(hires_code, h);
    *notch += h;
    while (*notch >= 120)  { out_rel(legacy_code, 1);  *notch -= 120; }
    while (*notch <= -120) { out_rel(legacy_code, -1); *notch += 120; }
}

/* true = weitere Ticks noetig */
static bool tick(int64_t now) {
    bool need = false;
    float dt = last_tick ? (float)(now - last_tick) / 1000.f : 0.f;
    if (dt > 0.05f) dt = 0.05f;
    last_tick = now;

    for (int n = 0; n < MAX_PADS; n++) {
        Pad *p = pads[n];
        if (!p) continue;
        if (p->home_rel_pending) {
            if (now >= p->home_rel_at) { p->home_rel_pending = false; set_src(p, I_HOME, false, false); return true; }
            need = true;
        }
        for (int i = 0; i < I_COUNT; i++)
            if (p->pending[i]) {
                if (now >= p->pending_at[i]) { p->pending[i] = false; press_action(p, i); }
                else need = true;
            }
        if (p->combo_armed) {
            if (!combo_down(p)) { p->combo_armed = false; if (cfg.debug) logf_("Kombi: vor Ablauf losgelassen"); }
            else if (now - p->combo_since >= cfg.combo_hold_ms) {
                p->combo_armed = false;
                p->combo_latch = true;
                set_active(!g.active, true);
                return true;                  /* Zustand hat sich geaendert, neu bewerten */
            } else need = true;
        }
        if (p->mcombo_armed) {
            if (!g.active || !mcombo_down(p)) p->mcombo_armed = false;
            else if (now - p->mcombo_since >= cfg.wii_mode_hold_ms) {
                p->mcombo_armed = false; p->mcombo_latch = true;
                wii_mode_toggle(); rumble(p, 120);
            } else need = true;
        }
        if (g.active)                              /* Scroll-Aktionen (Mapping): laufen solange die Taste gehalten wird */
            for (int i = 0; i < I_COUNT; i++)
                if (p->held_valid[i] && p->held[i].kind == 3) {
                    float sp = cfg.scroll_speed * dt * (cfg.scroll_invert ? -1.f : 1.f);
                    switch (p->held[i].code) { case 0: acc_sy += sp; break; case 1: acc_sy -= sp; break; case 2: acc_sx -= sp; break; default: acc_sx += sp; }
                    need = true;
                }
        if (!g.active || !rstick_live(p) || monitoring()) continue;
        need = true;
        float mag = hypotf(mx(p), my(p));
        float s = clampf((mag - cfg.mouse_dz) / (1.f - cfg.mouse_dz), 0.f, 1.f);
        s = powf(s, cfg.mouse_curve);
        float ux = mx(p) / mag, uy = my(p) / mag;
        int smode = layer_on(p) ? cfg.stick_home : cfg.stick_base;
        if (smode == 0) continue;
        if (smode == 2) {                      /* Scrollen */
            float sp = cfg.scroll_speed * s * dt;
            acc_sx += ux * sp * (cfg.scroll_invert ? -1.f : 1.f);
            acc_sy += -uy * sp * (cfg.scroll_invert ? -1.f : 1.f);
        } else {
            acc_x += ux * cfg.mouse_speed * s * dt;
            acc_y += uy * cfg.mouse_speed * s * dt;
        }
    }
    bool any = false;
    int ix = (int)acc_x, iy = (int)acc_y;
    if (ix) { acc_x -= ix; out_rel(REL_X, ix); any = true; }
    if (iy) { acc_y -= iy; out_rel(REL_Y, iy); any = true; }
    int before = (int)(acc_sx != 0) + (int)(acc_sy != 0);
    (void)before;
    if ((int)acc_sy) { emit_wheel(REL_WHEEL_HI_RES, REL_WHEEL, &acc_sy, &notch_y); any = true; }
    if ((int)acc_sx) { emit_wheel(REL_HWHEEL_HI_RES, REL_HWHEEL, &acc_sx, &notch_x); any = true; }
#ifndef TRAFKPAD_TEST
    if (any) out_rel_sync();
#else
    (void)any;
#endif
    ir_poll();
    ir_emit(dt);
    if (ir.vis && g.active && cfg.wii_pointer) need = true;
    return need;
}

#ifndef TRAFKPAD_TEST
/* ─────────────────────────────── Geraete ─────────────────────────────── */
static int epfd = -1, tickfd = -1, infd = -1, sockfd = -1, hyprfd = -1;
static int64_t hypr_retry_at;
static char hbuf[1024];
static size_t hlen;
static bool tick_armed;
static int64_t rescan_at;

/* Hyprland-Eventsocket: focusedmon>> -> Zeigerbereich folgt dem aktiven Monitor */
static bool hypr_wanted(void) { return cfg.wii_area_active; }
static void hypr_close(void) {
    if (hyprfd >= 0) { epoll_ctl(epfd, EPOLL_CTL_DEL, hyprfd, NULL); close(hyprfd); hyprfd = -1; }
    hlen = 0;
}
static void hypr_connect(void) {
    hypr_retry_at = clock_ms() + 5000;
    const char *xrd = getenv("XDG_RUNTIME_DIR"), *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    if (!xrd || !sig || !hypr_wanted()) return;
    struct sockaddr_un a = { .sun_family = AF_UNIX };
    snprintf(a.sun_path, sizeof a.sun_path, "%s/hypr/%s/.socket2.sock", xrd, sig);
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return;
    if (connect(fd, (struct sockaddr *)&a, sizeof a) < 0) { close(fd); return; }
    struct epoll_event e = { .events = EPOLLIN, .data.ptr = &hyprfd };
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &e) < 0) { close(fd); return; }
    hyprfd = fd; hlen = 0;
}
static void hypr_read(void) {
    ssize_t n = read(hyprfd, hbuf + hlen, sizeof hbuf - 1 - hlen);
    if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) { hypr_close(); return; }
    if (n < 0) return;
    hlen += (size_t)n; hbuf[hlen] = 0;
    char *start = hbuf, *nl;
    while ((nl = strchr(start, '\n'))) { *nl = 0; hypr_line(start); start = nl + 1; }
    hlen = strlen(start); memmove(hbuf, start, hlen + 1);
    if (hlen >= sizeof hbuf - 1) hlen = 0;      /* Zeile zu lang: verwerfen */
}

static void tick_set(bool on) {
    if (on == tick_armed) return;
    struct itimerspec its = {0};
    if (on) {
        its.it_interval.tv_nsec = TICK_MS * 1000000L;
        its.it_value.tv_nsec = TICK_MS * 1000000L;
        last_tick = clock_ms();
    }
    timerfd_settime(tickfd, 0, &its, NULL);
    tick_armed = on;
}
static bool need_tick(void) {
    for (int n = 0; n < MAX_PADS; n++) {
        Pad *p = pads[n];
        if (!p) continue;
        if (p->combo_armed || p->mcombo_armed || p->home_rel_pending || (g.active && rstick_live(p))) return true;
        for (int i = 0; i < I_COUNT; i++) if (g.active && p->held_valid[i] && p->held[i].kind == 3) return true;
        if (p->wii == 3 && (ir.dirty || (ir.vis && g.active && cfg.wii_pointer))) return true;
        for (int i = 0; i < I_COUNT; i++) if (p->pending[i]) return true;
    }
    return false;
}
static void update_tick(void) { tick_set(need_tick()); }

static void pad_close(Pad *p) {
    if (ir.pad == p) { ir.pad = NULL; ir.vis = false; ir.dirty = false; }
    for (int k = 0; k < I_COUNT; k++) if (p->held_valid[k]) release_action(p, k);
    if (p->fd >= 0) epoll_ctl(epfd, EPOLL_CTL_DEL, p->fd, NULL);
    if (p->dev) libevdev_free(p->dev);
    if (p->fd >= 0) close(p->fd);
    for (int i = 0; i < MAX_PADS; i++) if (pads[i] == p) pads[i] = NULL;
    logf_("Pad entfernt: %s", p->name);
    free(p);
}

static bool pad_known(const char *path) {
    for (int i = 0; i < MAX_PADS; i++) if (pads[i] && !strcmp(pads[i]->path, path)) return true;
    return false;
}

static void pad_try_open(const char *path) {
    if (pad_known(path)) return;
    int fd = open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) { if (errno == EACCES) rescan_at = clock_ms() + 300; return; }
    struct libevdev *dev = NULL;
    if (libevdev_new_from_fd(fd, &dev) < 0) { close(fd); return; }
    const char *nm = libevdev_get_name(dev);
    int wk = 0;
    if (nm && !strcmp(nm, "Nintendo Wii Remote") && libevdev_has_event_code(dev, EV_KEY, BTN_1)) wk = 1;
    else if (nm && !strcmp(nm, "Nintendo Wii Remote Nunchuk")) wk = 2;
    else if (nm && !strcmp(nm, "Nintendo Wii Remote IR")) wk = 3;
    bool is_pad = wk || (libevdev_has_event_code(dev, EV_KEY, BTN_SOUTH) && libevdev_has_event_code(dev, EV_ABS, ABS_X)
                  && !libevdev_has_event_type(dev, EV_REL) && strncmp(nm ? nm : "", "TrafkPad", 8) != 0);
    if (!is_pad) { libevdev_free(dev); close(fd); return; }
    int slot = -1;
    for (int i = 0; i < MAX_PADS; i++) if (!pads[i]) { slot = i; break; }
    if (slot < 0) { libevdev_free(dev); close(fd); return; }
    Pad *p = calloc(1, sizeof *p);
    p->fd = fd; p->dev = dev; p->ff_id = -1; p->wii = wk;
    { const char *u = libevdev_get_uniq(dev); if (u) snprintf(p->uniq, sizeof p->uniq, "%s", u); }
    if (wk == 3) {      /* Kernel-Fuzz (2) wuerde den Zeiger in groben Stufen ruckeln lassen */
        for (int c = ABS_HAT0X; c <= ABS_HAT3Y; c++) {
            const struct input_absinfo *ai = libevdev_get_abs_info(dev, c);
            if (!ai) continue;
            struct input_absinfo n = *ai; n.fuzz = 0; n.flat = 0;
            libevdev_kernel_set_abs_info(dev, c, &n);
        }
    }
    if (wk == 2) { p->cx = libevdev_get_event_value(dev, EV_ABS, ABS_HAT0X); p->cy = libevdev_get_event_value(dev, EV_ABS, ABS_HAT0Y); }
    snprintf(p->path, sizeof p->path, "%s", path);
    snprintf(p->name, sizeof p->name, "%s", nm ? nm : "?");
    for (int c = 0; c < 64; c++) {
        const struct input_absinfo *a = libevdev_get_abs_info(dev, c);
        if (a) p->ai[c] = *a;
    }
    p->ff_ok = libevdev_has_event_code(dev, EV_FF, FF_RUMBLE) && fcntl(fd, F_GETFL) >= 0;
    /* Startzustand lesen (Trigger in Ruhe, schon gehaltene Tasten) */
    static const int btns[] = { BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST, BTN_TL, BTN_TR, BTN_TL2, BTN_TR2,
        BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR, BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT };
    static const int axes[] = { ABS_X, ABS_Y, ABS_RX, ABS_RY, ABS_Z, ABS_RZ, ABS_HAT0X, ABS_HAT0Y };
    /* Rechter Stick / Trigger-Achsen: Standard RX/RY + Z/RZ. Viele DInput-Pads (u.a.
     * 8BitDo) melden den rechten Stick aber als Z/RZ und die Trigger nur als Tasten. */
    {
        bool rxy = libevdev_has_event_code(dev, EV_ABS, ABS_RX) && libevdev_has_event_code(dev, EV_ABS, ABS_RY);
        bool zrz = libevdev_has_event_code(dev, EV_ABS, ABS_Z) && libevdev_has_event_code(dev, EV_ABS, ABS_RZ);
        bool trig_btn = libevdev_has_event_code(dev, EV_KEY, BTN_TL2) && libevdev_has_event_code(dev, EV_KEY, BTN_TR2);
        p->ax_set = true;
        p->ax[0] = ABS_RX; p->ax[1] = ABS_RY; p->ax[2] = ABS_Z; p->ax[3] = ABS_RZ;
        if (!rxy && zrz && trig_btn) { p->ax[0] = ABS_Z; p->ax[1] = ABS_RZ; p->ax[2] = p->ax[3] = -1; }
        if (cfg.ov_rx != -2) p->ax[0] = cfg.ov_rx;
        if (cfg.ov_ry != -2) p->ax[1] = cfg.ov_ry;
        if (cfg.ov_l2 != -2) p->ax[2] = cfg.ov_l2;
        if (cfg.ov_r2 != -2) p->ax[3] = cfg.ov_r2;
    }
    pads[slot] = p;
    for (size_t k = 0; !wk && k < sizeof btns / sizeof *btns; k++)
        if (libevdev_has_event_code(dev, EV_KEY, btns[k]))
            pad_event(p, EV_KEY, btns[k], libevdev_get_event_value(dev, EV_KEY, btns[k]));
    for (size_t k = 0; !wk && k < sizeof axes / sizeof *axes; k++)
        if (libevdev_has_event_code(dev, EV_ABS, axes[k]))
            pad_event(p, EV_ABS, axes[k], libevdev_get_event_value(dev, EV_ABS, axes[k]));
    struct epoll_event ee = { .events = EPOLLIN, .data.ptr = p };
    epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ee);
    logf_("Pad gefunden: %s (%s)%s%s%s%s", p->name, path, p->ff_ok ? " [rumble]" : "", wk && p->uniq[0] ? " " : "", wk ? p->uniq : "",
          wk == 1 ? " [Wiimote]" : wk == 2 ? " [Nunchuk]" : wk == 3 ? " [IR-Zeiger]" : "");
    logf_("  rechter Stick: X=%s Y=%s | L2-Achse=%s R2-Achse=%s | Home-Taste=%s",
          p->ax[0] < 0 ? "-" : libevdev_event_code_get_name(EV_ABS, p->ax[0]),
          p->ax[1] < 0 ? "-" : libevdev_event_code_get_name(EV_ABS, p->ax[1]),
          p->ax[2] < 0 ? "-" : libevdev_event_code_get_name(EV_ABS, p->ax[2]),
          p->ax[3] < 0 ? "-" : libevdev_event_code_get_name(EV_ABS, p->ax[3]),
          libevdev_event_code_get_name(EV_KEY, cfg.home_btn));
    if (cfg.debug) {
        for (int c = 0; c < 64; c++)
            if (libevdev_has_event_code(dev, EV_ABS, c))
                logf_("  hat Achse %s (%d..%d)", libevdev_event_code_get_name(EV_ABS, c), p->ai[c].minimum, p->ai[c].maximum);
        for (int c = 0; c < KEY_MAX; c++)
            if (libevdev_has_event_code(dev, EV_KEY, c)) logf_("  hat Taste %s (%d)", libevdev_event_code_get_name(EV_KEY, c), c);
    }
    if (g.active) {
        for (int k = 0; k < I_COUNT; k++) p->ignore[k] = p->down[k];
        p->combo_latch = true;
        pad_grab(p, true);
    }
}

static void scan_pads(void) {
    DIR *d = opendir("/dev/input");
    if (!d) return;
    struct dirent *de;
    while ((de = readdir(d))) {
        if (strncmp(de->d_name, "event", 5)) continue;
        char path[300];
        snprintf(path, sizeof path, "/dev/input/%s", de->d_name);
        pad_try_open(path);
    }
    closedir(d);
}
static void close_all_pads(void) {
    for (int i = 0; i < MAX_PADS; i++) if (pads[i]) pad_close(pads[i]);
}

static void pad_read(Pad *p) {
    struct input_event ev;
    unsigned flags = LIBEVDEV_READ_FLAG_NORMAL;
    int rc;
    do {
        rc = libevdev_next_event(p->dev, flags, &ev);
        if (rc == LIBEVDEV_READ_STATUS_SYNC) flags = LIBEVDEV_READ_FLAG_SYNC;
        else if (rc == LIBEVDEV_READ_STATUS_SUCCESS) {
            flags = LIBEVDEV_READ_FLAG_NORMAL;
            if (p->wii) {
                if (p->wii == 1 && ev.type == EV_KEY) wii_button(p, ev.code, ev.value);
                else if (p->wii == 2) wii_nunchuk(p, ev.type, ev.code, ev.value);
                else if (p->wii == 3 && ev.type == EV_SYN && ev.code == SYN_REPORT) { if (wii_ir_primary(p)) { ir.pad = p; ir.dirty = true; } }
                if (cfg.debug && p->wii != 3 && (ev.type == EV_KEY || ev.type == EV_ABS))
                    logf_("WII%d %s = %d", p->wii, libevdev_event_code_get_name(ev.type, ev.code) ? libevdev_event_code_get_name(ev.type, ev.code) : "?", ev.value);
            } else if (ev.type == EV_KEY || ev.type == EV_ABS) {
                if (cfg.debug) {
                    const char *cn = libevdev_event_code_get_name(ev.type, ev.code);
                    logf_("EV %s %s (%d) = %d", ev.type == EV_KEY ? "KEY" : "ABS", cn ? cn : "?", ev.code, ev.value);
                }
                pad_event(p, ev.type, ev.code, ev.value);
            }
        }
    } while (rc == LIBEVDEV_READ_STATUS_SUCCESS || rc == LIBEVDEV_READ_STATUS_SYNC);
    if (rc == -ENODEV || rc == -EIO) pad_close(p);
}

/* ─────────────────────────── Virtuelle Geraete ─────────────────────────── */
static int create_outputs(void) {
    struct libevdev *k = libevdev_new();
    libevdev_set_name(k, "TrafkPad Keyboard");
    libevdev_set_id_bustype(k, BUS_VIRTUAL);
    libevdev_enable_event_type(k, EV_KEY);
    for (int c = 1; c < KEYS_USED; c++) libevdev_enable_event_code(k, EV_KEY, c, NULL);
    int rc = libevdev_uinput_create_from_device(k, LIBEVDEV_UINPUT_OPEN_MANAGED, &ui_kbd);
    libevdev_free(k);
    if (rc < 0) { logf_("uinput (Tastatur) fehlgeschlagen: %s - /dev/uinput Rechte? modules-load uinput?", strerror(-rc)); return -1; }

    struct libevdev *m = libevdev_new();
    libevdev_set_name(m, "TrafkPad Mouse");
    libevdev_set_id_bustype(m, BUS_VIRTUAL);
    libevdev_enable_event_type(m, EV_KEY);
    libevdev_enable_event_code(m, EV_KEY, BTN_LEFT, NULL);
    libevdev_enable_event_code(m, EV_KEY, BTN_RIGHT, NULL);
    libevdev_enable_event_code(m, EV_KEY, BTN_MIDDLE, NULL);
    libevdev_enable_event_type(m, EV_REL);
    int rels[] = { REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES };
    for (size_t i = 0; i < sizeof rels / sizeof *rels; i++) libevdev_enable_event_code(m, EV_REL, rels[i], NULL);
    libevdev_enable_property(m, INPUT_PROP_POINTER);
    rc = libevdev_uinput_create_from_device(m, LIBEVDEV_UINPUT_OPEN_MANAGED, &ui_mouse);
    libevdev_free(m);
    if (rc < 0) { logf_("uinput (Maus) fehlgeschlagen: %s", strerror(-rc)); return -1; }

    /* Absoluter Zeiger (Wiimote-IR). BTN_LEFT nur damit udev/libinput es als Zeigegeraet einstuft. */
    struct libevdev *a = libevdev_new();
    libevdev_set_name(a, "TrafkPad Pointer");
    libevdev_set_id_bustype(a, BUS_VIRTUAL);
    libevdev_enable_event_type(a, EV_KEY);
    libevdev_enable_event_code(a, EV_KEY, BTN_LEFT, NULL);
    libevdev_enable_event_type(a, EV_ABS);
    struct input_absinfo ai = { .minimum = 0, .maximum = 32767, .resolution = 0 };
    libevdev_enable_event_code(a, EV_ABS, ABS_X, &ai);
    libevdev_enable_event_code(a, EV_ABS, ABS_Y, &ai);
    rc = libevdev_uinput_create_from_device(a, LIBEVDEV_UINPUT_OPEN_MANAGED, &ui_ptr);
    libevdev_free(a);
    if (rc < 0) logf_("uinput (Zeiger) fehlgeschlagen: %s - Wiimote-Zeiger aus", strerror(-rc));
    return 0;
}

/* ─────────────────────────────── Steuer-Socket ─────────────────────────────── */
static char cal_path[512];
static void wii_cal_notify(const char *msg) {
    char cmd[400];
    snprintf(cmd, sizeof cmd, "command -v notify-send >/dev/null && notify-send -a TrafkPad -t 4000 -i input-gaming 'Wiimote' '%s'", msg);
    spawn_sh(cmd);
    logf_("%s", msg);
}
static void wii_cal_load(void) {
    FILE *f = fopen(cal_path, "r");
    if (!f) return;
    float a, b, c, d;
    if (fscanf(f, "%f %f %f %f", &a, &b, &c, &d) == 4 && c - a > 0.05f && d - b > 0.05f) { cal_u0 = a; cal_v0 = b; cal_u1 = c; cal_v1 = d; }
    fclose(f);
}
static void wii_cal_save(void) {
    FILE *f = fopen(cal_path, "w");
    if (!f) return;
    fprintf(f, "%.4f %.4f %.4f %.4f\n", cal_u0, cal_v0, cal_u1, cal_v1);
    fclose(f);
}

static void apply_enabled(bool first) {
    if (!cfg.enabled) {
        set_active(false, false);
        close_all_pads();
        return;
    }
    scan_pads();
    if (first) set_active(cfg.start_active, false);
}

static void handle_cmd(int c) {
    char buf[64] = {0};
    ssize_t n = read(c, buf, sizeof buf - 1);
    if (n <= 0) return;
    while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' ')) buf[--n] = 0;
    char reply[160];
    bool was_enabled = cfg.enabled;
    if (!strcmp(buf, "toggle")) { if (cfg.enabled) set_active(!g.active, true); snprintf(reply, sizeof reply, "ok %s", g.active ? "on" : "off"); }
    else if (!strcmp(buf, "on"))  { if (cfg.enabled) set_active(true, true);  snprintf(reply, sizeof reply, "ok on"); }
    else if (!strcmp(buf, "off")) { set_active(false, true); snprintf(reply, sizeof reply, "ok off"); }
    else if (!strcmp(buf, "reload")) {
        cfg_load();
        wii_mode_rt = -1;                        /* geaenderte Einstellung gilt sofort */
        if (!cfg.enabled) apply_enabled(false);
        else if (!was_enabled) { apply_enabled(false); set_active(cfg.start_active, false); }
        snprintf(reply, sizeof reply, "ok reloaded enabled=%d", cfg.enabled);
    } else if (!strcmp(buf, "dump")) {
        char big[6144]; size_t l = dump_maps(big, sizeof big);
        (void)!write(c, big, l);
        return;
    } else if (!strcmp(buf, "padmon")) {
        mon_until = clock_ms() + 800;
        char pr[400]; pressed_str(pr, sizeof pr);
        (void)!write(c, pr, strlen(pr));
        return;
    } else if (!strcmp(buf, "version")) { snprintf(reply, sizeof reply, "TrafkPad proto=%d", PAD_PROTO);
    } else if (!strcmp(buf, "pressed")) {
        char pr[400]; pressed_str(pr, sizeof pr);
        (void)!write(c, pr, strlen(pr));
        return;
    } else if (!strcmp(buf, "detect start")) { detect_on = true; detect_name[0] = 0; snprintf(reply, sizeof reply, "ok");
    } else if (!strcmp(buf, "detect stop")) { detect_on = false; snprintf(reply, sizeof reply, "ok");
    } else if (!strcmp(buf, "detect")) { snprintf(reply, sizeof reply, "%s", detect_name[0] ? detect_name : (detect_on ? "waiting" : "-")); if (detect_name[0]) detect_name[0] = 0;
    } else if (!strcmp(buf, "status")) {
        int np = 0;
        for (int i = 0; i < MAX_PADS; i++) if (pads[i]) np++;
        static const char *wm[] = { "abs", "rel", "joy" };
        snprintf(reply, sizeof reply, "%s pads=%d enabled=%d proto=%d wii=%s", g.active ? "on" : "off", np, cfg.enabled, PAD_PROTO, wm[wii_mode_eff()]);
    } else if (!strncmp(buf, "wii-mode", 8)) {
        const char *w = buf + 8;
        while (*w == ' ') w++;
        static const char *names[] = { "abs", "rel", "joy" };
        if (!strcmp(w, "toggle")) wii_mode_toggle();
        else if (!strcmp(w, "auto")) wii_mode_rt = -1;
        else if (!strcmp(w, "abs")) wii_mode_rt = 0;
        else if (!strcmp(w, "rel")) wii_mode_rt = 1;
        else if (!strcmp(w, "joy")) wii_mode_rt = 2;
        else { snprintf(reply, sizeof reply, "error wii-mode abs|rel|joy|toggle|auto"); goto wii_mode_done; }
        if (strcmp(w, "toggle")) { char m[96]; snprintf(m, sizeof m, "Zeiger-Modus: %s", names[wii_mode_eff()]); wii_cal_notify(m); }
        snprintf(reply, sizeof reply, "ok %s", names[wii_mode_eff()]);
        wii_mode_done:;
    } else if (!strncmp(buf, "wii-cal", 7)) {
        const char *w = buf + 7;
        while (*w == ' ') w++;
        if (!strcmp(w, "start")) { wii_cal_step = 1; wii_cal_notify("Kalibrierung 1/2: auf die OBERE LINKE Bildschirmecke zeigen und A druecken"); snprintf(reply, sizeof reply, "ok Kalibrierung gestartet"); }
        else if (!strcmp(w, "reset")) { cal_u0 = cal_v0 = 0.20f; cal_u1 = cal_v1 = 0.80f; unlink(cal_path); snprintf(reply, sizeof reply, "ok reset"); }
        else if (!ir.vis) snprintf(reply, sizeof reply, "error Sensorleiste nicht sichtbar");
        else if (!strcmp(w, "tl")) { cal_u0 = ir.u; cal_v0 = ir.v; wii_cal_save(); snprintf(reply, sizeof reply, "ok oben-links gespeichert"); }
        else if (!strcmp(w, "br")) {
            if (ir.u - cal_u0 > 0.05f && ir.v - cal_v0 > 0.05f) { cal_u1 = ir.u; cal_v1 = ir.v; wii_cal_save(); snprintf(reply, sizeof reply, "ok unten-rechts gespeichert"); }
            else snprintf(reply, sizeof reply, "error erst 'wii-cal tl' (oben links) zeigen");
        } else snprintf(reply, sizeof reply, "error wii-cal start|tl|br|reset");
    } else if (!strcmp(buf, "quit")) { snprintf(reply, sizeof reply, "ok bye"); (void)!write(c, reply, strlen(reply)); raise(SIGTERM); return; }
    else snprintf(reply, sizeof reply, "error unknown command");
    (void)!write(c, reply, strlen(reply));
}

static int ctl_client(const char *cmd) {
    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a = { .sun_family = AF_UNIX };
    snprintf(a.sun_path, sizeof a.sun_path, "%s", sock_path);
    if (connect(s, (struct sockaddr *)&a, sizeof a) < 0) { fprintf(stderr, "TrafkPad laeuft nicht (%s)\n", sock_path); return 1; }
    (void)!write(s, cmd, strlen(cmd));
    shutdown(s, SHUT_WR);
    char b[256];
    ssize_t n = read(s, b, sizeof b - 1);
    if (n > 0) { b[n] = 0; printf("%s\n", b); }
    close(s);
    return 0;
}

static int listen_sock(void) {
    int s = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    struct sockaddr_un a = { .sun_family = AF_UNIX };
    snprintf(a.sun_path, sizeof a.sun_path, "%s", sock_path);
    unlink(sock_path);
    if (bind(s, (struct sockaddr *)&a, sizeof a) < 0 || listen(s, 4) < 0) { logf_("Socket %s: %s", sock_path, strerror(errno)); return -1; }
    chmod(sock_path, 0600);
    return s;
}

int main(int argc, char **argv) {
    clock_ms = real_clock_ms;
    const char *home = getenv("HOME");
    const char *xrd = getenv("XDG_RUNTIME_DIR");
    if (!home) home = "/tmp";
    snprintf(cfg_path, sizeof cfg_path, "%s/.config/TrafkTuxPad/TrafkPad.conf", home);
    snprintf(layout_dir, sizeof layout_dir, "%s/.config/TrafkTuxPad/layouts", home);
    snprintf(flag_path, sizeof flag_path, "%s/.cache/hypr/controller_mode_active", home);
    if (xrd && strlen(xrd) < 90) snprintf(sock_path, sizeof sock_path, "%s/TrafkPad.sock", xrd);
    else snprintf(sock_path, sizeof sock_path, "/tmp/TrafkPad-%u.sock", (unsigned)getuid());

    snprintf(cal_path, sizeof cal_path, "%s/.config/TrafkTuxPad/wii.cal", home);
    if (argc >= 3 && !strcmp(argv[1], "--ctl")) return ctl_client(argv[2]);

    signal(SIGCHLD, SIG_IGN);
    signal(SIGPIPE, SIG_IGN);
    {   /* laeuft schon? */
        int s = socket(AF_UNIX, SOCK_STREAM, 0);
        struct sockaddr_un a = { .sun_family = AF_UNIX };
        snprintf(a.sun_path, sizeof a.sun_path, "%s", sock_path);
        if (connect(s, (struct sockaddr *)&a, sizeof a) == 0) { fprintf(stderr, "TrafkPad laeuft bereits\n"); return 0; }
        close(s);
    }
    cfg_load();
    wii_cal_load();
    if (create_outputs() < 0) return 1;

    epfd = epoll_create1(EPOLL_CLOEXEC);
    tickfd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    infd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    inotify_add_watch(infd, "/dev/input", IN_CREATE | IN_ATTRIB);
    sockfd = listen_sock();
    sigset_t ss;
    sigemptyset(&ss);
    sigaddset(&ss, SIGTERM); sigaddset(&ss, SIGINT); sigaddset(&ss, SIGHUP);
    sigprocmask(SIG_BLOCK, &ss, NULL);
    int sigfd = signalfd(-1, &ss, SFD_NONBLOCK | SFD_CLOEXEC);

    struct epoll_event e;
    int *tags[] = { &tickfd, &infd, &sockfd, &sigfd };
    for (int i = 0; i < 4; i++) {
        e.events = EPOLLIN;
        e.data.ptr = tags[i];
        epoll_ctl(epfd, EPOLL_CTL_ADD, *tags[i], &e);
    }

    apply_enabled(true);
    logf_("gestartet (enabled=%d, aktiv=%d)", cfg.enabled, g.active);

    bool run = true;
    while (run) {
        if (hyprfd < 0 && hypr_wanted() && clock_ms() >= hypr_retry_at) hypr_connect();
        int timeout = rescan_at ? 300 : (hyprfd < 0 && hypr_wanted() ? 5000 : -1);
        struct epoll_event evs[16];
        int n = epoll_wait(epfd, evs, 16, timeout);
        if (n < 0 && errno != EINTR) break;
        for (int i = 0; i < n; i++) {
            void *ptr = evs[i].data.ptr;
            if (ptr == &tickfd) {
                uint64_t x;
                (void)!read(tickfd, &x, sizeof x);
                tick(clock_ms());
            } else if (ptr == &infd) {
                char buf[4096];
                while (read(infd, buf, sizeof buf) > 0) {}
                if (cfg.enabled) rescan_at = clock_ms() + 150;
            } else if (ptr == &sockfd) {
                int c = accept4(sockfd, NULL, NULL, SOCK_CLOEXEC);
                if (c >= 0) {
                    struct timeval tv = { .tv_sec = 1 };
                    setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
                    handle_cmd(c);
                    close(c);
                }
            } else if (ptr == &hyprfd) {
                hypr_read();
            } else if (ptr == &sigfd) {
                struct signalfd_siginfo si;
                while (read(sigfd, &si, sizeof si) == sizeof si) {
                    if (si.ssi_signo == SIGHUP) { cfg_load(); if (cfg.enabled) scan_pads(); }
                    else run = false;
                }
            } else {
                pad_read((Pad *)ptr);
            }
        }
        if (rescan_at && clock_ms() >= rescan_at) { rescan_at = 0; if (cfg.enabled) scan_pads(); }
        update_tick();
    }
    hypr_close();
    release_all_outputs();
    set_flag_file(false);
    unlink(sock_path);
    close_all_pads();
    return 0;
}

#else  /* ───────────────────────────── Selbsttest ───────────────────────────── */
static int64_t fake_now;
static int64_t fake_clock(void) { return fake_now; }
static int fails;
#define CHECK(cond, ...) do { if (!(cond)) { fails++; printf("FAIL line %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
static void clear(void) { rec[0] = 0; }
static bool has(const char *s) { return strstr(rec, s) != NULL; }
static void adv(int ms) { for (int t = 0; t < ms; t += TICK_MS) { fake_now += TICK_MS; tick(fake_now); } }
static Pad *mk(void) {
    Pad *p = calloc(1, sizeof *p);
    p->fd = -1;
    for (int c = 0; c < 64; c++) { p->ai[c].minimum = -32768; p->ai[c].maximum = 32767; }
    p->ai[ABS_Z].minimum = 0; p->ai[ABS_Z].maximum = 255;
    p->ai[ABS_RZ].minimum = 0; p->ai[ABS_RZ].maximum = 255;
    return p;
}
int main(void) {
    clock_ms = fake_clock;
    cfg_defaults();
    cfg.home_release_ms = 0;               /* alte Tests: Home sofort loslassen */
    build_maps();
    Pad *p = mk();
    pads[0] = p;

    /* AUS: nichts darf ausgegeben werden */
    g.active = false;
    pad_event(p, EV_KEY, BTN_SOUTH, 1); pad_event(p, EV_KEY, BTN_SOUTH, 0);
    CHECK(rec[0] == 0, "AUS gibt nichts aus: '%s'", rec);

    set_active(true, false); clear();
    /* Basis-Tasten */
    pad_event(p, EV_KEY, BTN_SOUTH, 1);  CHECK(has("K57=1"), "A=Space down '%s'", rec);
    pad_event(p, EV_KEY, BTN_SOUTH, 0);  CHECK(has("K57=0"), "A=Space up");
    clear();
    pad_event(p, EV_ABS, ABS_HAT0Y, -1); CHECK(has("K103=1"), "Dpad hoch = KEY_UP '%s'", rec);
    pad_event(p, EV_ABS, ABS_HAT0Y, 0);  CHECK(has("K103=0"), "Dpad los");
    clear();
    pad_event(p, EV_ABS, ABS_X, -30000); CHECK(has("K30=1"), "Linker Stick links = A '%s'", rec);
    pad_event(p, EV_ABS, ABS_X, 0);      CHECK(has("K30=0"), "Stick los -> A up");
    clear();
    pad_event(p, EV_ABS, ABS_Z, 255);    CHECK(has("B272=1"), "L2 = Linksklick '%s'", rec);
    pad_event(p, EV_ABS, ABS_Z, 0);      CHECK(has("B272=0"), "L2 los");
    clear();
    /* Start/Select einzeln: erst nach Karenzzeit, Tap sofort bei Release */
    pad_event(p, EV_KEY, BTN_START, 1);  CHECK(!has("K28"), "Start verzoegert (Karenz) '%s'", rec);
    adv(100);                            CHECK(has("K28=1"), "Start nach Karenz = Enter '%s'", rec);
    pad_event(p, EV_KEY, BTN_START, 0);  CHECK(has("K28=0"), "Start los");
    clear();
    pad_event(p, EV_KEY, BTN_SELECT, 1); pad_event(p, EV_KEY, BTN_SELECT, 0);
    CHECK(has("K1=1 K1=0"), "Select-Tap vor Karenz = Esc-Tap '%s'", rec);

    /* Home-Ebene */
    clear();
    pad_event(p, EV_KEY, BTN_MODE, 1);
    pad_event(p, EV_ABS, ABS_HAT0Y, -1); CHECK(has("K187=1"), "Home+Dpad hoch = F17(%d) '%s'", KEY_F17, rec);
    pad_event(p, EV_KEY, BTN_MODE, 0);   /* Home vor Dpad losgelassen */
    pad_event(p, EV_ABS, ABS_HAT0Y, 0);  CHECK(has("K187=0"), "F17 wird trotzdem losgelassen (kein haengender Key) '%s'", rec);
    clear();
    pad_event(p, EV_KEY, BTN_MODE, 1);
    pad_event(p, EV_ABS, ABS_Z, 255);    CHECK(has("K125=1 B272=1"), "Home+L2 = Super+LMB '%s'", rec);
    pad_event(p, EV_ABS, ABS_Z, 0);      CHECK(has("B272=0 K125=0"), "Super+LMB los '%s'", rec);
    pad_event(p, EV_KEY, BTN_MODE, 0);
    clear();
    pad_event(p, EV_KEY, BTN_MODE, 1);
    pad_event(p, EV_ABS, ABS_X, 30000);  CHECK(has("K42=1 K186=1"), "Home+Stick rechts = Shift+F16 '%s'", rec);
    pad_event(p, EV_ABS, ABS_X, 0);      pad_event(p, EV_KEY, BTN_MODE, 0);
    CHECK(kref[KEY_LEFTSHIFT] == 0 && kref[KEY_F16] == 0, "nichts haengt");

    /* Maus */
    clear();
    pad_event(p, EV_ABS, ABS_RX, 32767);
    adv(100);
    CHECK(has("R0:"), "Rechter Stick bewegt Maus X '%s'", rec);
    int moved = 0;
    for (char *s = rec; (s = strstr(s, "R0:")); s += 3) moved += atoi(s + 3);
    CHECK(moved > 60 && moved < 120, "Mausweg bei 100ms Vollausschlag ~90px, war %d", moved);
    pad_event(p, EV_ABS, ABS_RX, 0);
    /* Scrollen: Home + rechter Stick, 4 Richtungen */
    clear();
    pad_event(p, EV_KEY, BTN_MODE, 1);
    pad_event(p, EV_ABS, ABS_RY, -32767);
    adv(200);
    CHECK(has("R11:") && has("R8:1"), "Home+Stick hoch = Rad hoch (hires 11, legacy 8) '%s'", rec);
    pad_event(p, EV_ABS, ABS_RY, 0);
    clear();
    pad_event(p, EV_ABS, ABS_RX, 32767); adv(200);
    CHECK(has("R12:") && has("R6:1"), "Home+Stick rechts = horizontal (hires 12, legacy 6) '%s'", rec);
    pad_event(p, EV_ABS, ABS_RX, 0);
    pad_event(p, EV_KEY, BTN_MODE, 0);

    /* Toggle-Kombi: AN -> AUS, ohne Geister-Tasten (Enter/Esc/Q/E) */
    clear();
    pad_event(p, EV_KEY, BTN_TL, 1);  adv(10);
    pad_event(p, EV_KEY, BTN_TR, 1);  adv(10);
    pad_event(p, EV_KEY, BTN_SELECT, 1); adv(10);
    pad_event(p, EV_KEY, BTN_START, 1);
    adv(1100);
    CHECK(!g.active, "Kombi 1s gehalten -> AUS");
    CHECK(!has("K28=1") && !has("K1=1"), "Keine Geister-Tasten (Enter/Esc) bei der Kombi '%s'", rec);
    CHECK(has("FLAG=0"), "Flag-Datei weg");
    pad_event(p, EV_KEY, BTN_TL, 0); pad_event(p, EV_KEY, BTN_TR, 0);
    pad_event(p, EV_KEY, BTN_SELECT, 0); pad_event(p, EV_KEY, BTN_START, 0);
    adv(50);

    /* AUS: Kombi schaltet wieder AN, aber kein erneutes Umschalten durch Weiterhalten */
    clear();
    pad_event(p, EV_KEY, BTN_TL, 1); pad_event(p, EV_KEY, BTN_TR, 1);
    pad_event(p, EV_KEY, BTN_SELECT, 1); pad_event(p, EV_KEY, BTN_START, 1);
    adv(1100);
    CHECK(g.active, "AUS -> AN per Kombi");
    adv(3000);
    CHECK(g.active, "Weiterhalten schaltet nicht erneut um");
    clear();
    pad_event(p, EV_KEY, BTN_TL, 0); pad_event(p, EV_KEY, BTN_TR, 0);
    pad_event(p, EV_KEY, BTN_SELECT, 0); pad_event(p, EV_KEY, BTN_START, 0);
    CHECK(rec[0] == 0 || !has("K"), "Loslassen nach Aktivierung gibt keine Tasten aus '%s'", rec);

    /* Zu kurz gehaltene Kombi loest nichts aus */
    pad_event(p, EV_KEY, BTN_TL, 1); pad_event(p, EV_KEY, BTN_TR, 1);
    pad_event(p, EV_KEY, BTN_SELECT, 1); pad_event(p, EV_KEY, BTN_START, 1);
    adv(500);
    pad_event(p, EV_KEY, BTN_TL, 0); pad_event(p, EV_KEY, BTN_TR, 0);
    pad_event(p, EV_KEY, BTN_SELECT, 0); pad_event(p, EV_KEY, BTN_START, 0);
    adv(1200);
    CHECK(g.active, "0,5s halten toggelt nicht");

    /* Zwei Pads: gemeinsamer Key bleibt bis BEIDE los sind */
    Pad *p2 = mk(); pads[1] = p2;
    clear();
    pad_event(p, EV_KEY, BTN_SOUTH, 1); pad_event(p2, EV_KEY, BTN_SOUTH, 1);
    pad_event(p, EV_KEY, BTN_SOUTH, 0);
    CHECK(has("K57=1") && !has("K57=0"), "Space bleibt solange Pad 2 haelt '%s'", rec);
    pad_event(p2, EV_KEY, BTN_SOUTH, 0);
    CHECK(has("K57=0"), "Space los wenn beide los");

    /* Modus AUS gibt alles frei */
    pad_event(p, EV_ABS, ABS_X, 30000);
    set_active(false, false);
    CHECK(kref[KEY_D] == 0, "AUS laesst nichts haengen");

    /* Config-Parser */
    {
        snprintf(cfg_path, sizeof cfg_path, "/tmp/trafkpad_test.conf");
        FILE *f = fopen(cfg_path, "w");
        fputs("# Kommentar\nenabled = false   # aus\nleft_stick=arrows\ntoggle_combo = A+B+L1\nmouse_speed = 1234\nmouse_curve = 99\nswap_ab = yes\ntoggle_hold_ms=50\n", f);
        fclose(f);
        cfg_load();
        CHECK(!cfg.enabled, "enabled=false");
        CHECK(!cfg.left_wasd && map_base[I_SLU].code == KEY_UP, "left_stick=arrows -> Pfeile");
        CHECK(cfg.combo_mask == ((1u << I_A) | (1u << I_B) | (1u << I_L1)), "combo A+B+L1");
        CHECK(cfg.mouse_speed == 1234.f && cfg.mouse_curve == 4.0f, "Wert + Clamp (curve 99 -> 4)");
        CHECK(cfg.swap_ab && cfg.combo_hold_ms == 300, "swap_ab yes, hold clamp 300");
        snprintf(cfg_path, sizeof cfg_path, "/nonexistent/x.conf");
        cfg_load();
        CHECK(cfg.enabled && cfg.start_active && cfg.left_wasd, "fehlende Datei = Standard AN");
        unlink("/tmp/trafkpad_test.conf");
    }

    /* 8BitDo: Home als 100 ms-Impulsfolge = gehalten (Entprellung) */
    {
        cfg.home_release_ms = 350;
        Pad *q = mk(); pads[4] = q; g.active = true; clear();
        pad_event(q, EV_KEY, BTN_MODE, 1); adv(100); pad_event(q, EV_KEY, BTN_MODE, 0); adv(150);
        pad_event(q, EV_KEY, BTN_MODE, 1); adv(100); pad_event(q, EV_KEY, BTN_MODE, 0); adv(150);
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);
        CHECK(has("K187=1"), "Home als Impulsfolge + Dpad hoch = F17 '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0); adv(500);
        CHECK(!q->home && !q->home_armed, "Home nach Impulsfolge wieder losgelassen");
        pads[4] = NULL; free(q); g.active = true; cfg.home_release_ms = 0;
    }

    /* Pad sendet Home nur als kurzen Impuls: Tipp = naechste Taste aus der Home-Ebene */
    {
        Pad *q = mk(); pads[4] = q; g.active = true; clear();
        pad_event(q, EV_KEY, BTN_MODE, 1); adv(40); pad_event(q, EV_KEY, BTN_MODE, 0);
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);
        CHECK(has("K187=1"), "Home-Tipp + Dpad hoch = F17 '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0); clear();
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);
        CHECK(has("K103=1") && !has("K187"), "danach wieder normal (Pfeil hoch) '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0);
        clear();
        pad_event(q, EV_KEY, BTN_MODE, 1); adv(40); pad_event(q, EV_KEY, BTN_MODE, 0);
        adv(4500);
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);
        CHECK(has("K103=1"), "Tipp verfaellt nach 4 s '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0);
        clear();
        pad_event(q, EV_KEY, BTN_MODE, 1); adv(40); pad_event(q, EV_KEY, BTN_MODE, 0);
        pad_event(q, EV_KEY, BTN_MODE, 1); adv(40); pad_event(q, EV_KEY, BTN_MODE, 0);
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);
        CHECK(has("K103=1"), "zweiter Tipp bricht ab '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0);
        pads[4] = NULL; free(q);
    }

    /* D-Pad <-> Stick tauschen, linker Stick = Maus */
    {
        cfg.swap_dpad = true; cfg.mouse_left = true; cfg.left_wasd = true; build_maps();
        Pad *q = mk(); pads[6] = q; g.active = true; clear();
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);  CHECK(has("K17=1"), "Dpad hoch = W (getauscht) '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0);
        clear();
        pad_event(q, EV_KEY, BTN_MODE, 1);
        pad_event(q, EV_ABS, ABS_HAT0Y, -1);  CHECK(has("K42=1 K183=1"), "Home+Dpad hoch = Fokus (Shift+F13) '%s'", rec);
        pad_event(q, EV_ABS, ABS_HAT0Y, 0);
        clear();
        pad_event(q, EV_KEY, BTN_THUMBL, 1);  CHECK(has("K187=1"), "Home+L3 = Launcher (F17) '%s'", rec);
        pad_event(q, EV_KEY, BTN_THUMBL, 0);
        pad_event(q, EV_KEY, BTN_MODE, 0);
        clear();
        pad_event(q, EV_ABS, ABS_X, 30000);
        CHECK(!has("K32") && !has("K106"), "linker Stick = Maus: keine Tasten '%s'", rec);
        CHECK(rstick_live(q), "linker Stick bewegt die Maus");
        adv(100); CHECK(has("R0:"), "Maus X bewegt sich '%s'", rec);
        pad_event(q, EV_ABS, ABS_X, 0);
        clear();
        pad_event(q, EV_ABS, ABS_RX, 30000);  CHECK(!rstick_live(q), "rechter Stick deaktiviert");
        pad_event(q, EV_ABS, ABS_RX, 0);
        /* nur tauschen, Stick bleibt Tasten-Stick: Home+Stick hoch = Launcher */
        cfg.mouse_left = false; build_maps(); clear();
        pad_event(q, EV_ABS, ABS_RX, 0);
        pad_event(q, EV_KEY, BTN_MODE, 1);
        pad_event(q, EV_ABS, ABS_Y, -30000);  CHECK(has("K187=1"), "Tausch: Home+Stick hoch = F17 '%s'", rec);
        pad_event(q, EV_ABS, ABS_Y, 0);
        pad_event(q, EV_KEY, BTN_MODE, 0);
        pads[6] = NULL; free(q);
        cfg.swap_dpad = cfg.mouse_left = false; build_maps();
    }

    /* Nintendo-Layout: A<->B und X<->Y getauscht */
    {
        Pad *q = mk(); pads[5] = q; g.active = true; cfg.swap_ab = cfg.swap_xy = true; clear();
        pad_event(q, EV_KEY, BTN_EAST, 1);  CHECK(has("K57=1"), "Nintendo: rechte Taste (A) = Space '%s'", rec);
        pad_event(q, EV_KEY, BTN_EAST, 0);
        pad_event(q, EV_KEY, BTN_NORTH, 1); pad_event(q, EV_KEY, BTN_WEST, 1);
        pad_event(q, EV_KEY, BTN_NORTH, 0); pad_event(q, EV_KEY, BTN_WEST, 0);
        cfg.swap_ab = cfg.swap_xy = false; pads[5] = NULL; free(q);
    }

    /* DInput-Pad: rechter Stick = Z/RZ (0..255), Trigger nur als Tasten */
    {
        Pad *q = mk();
        q->ax_set = true; q->ax[0] = ABS_Z; q->ax[1] = ABS_RZ; q->ax[2] = q->ax[3] = -1;
        q->ai[ABS_Z].minimum = 0; q->ai[ABS_Z].maximum = 255;
        q->ai[ABS_RZ].minimum = 0; q->ai[ABS_RZ].maximum = 255;
        pads[3] = q;
        g.active = true; clear();
        pad_event(q, EV_ABS, ABS_Z, 255);
        CHECK(!has("B272"), "Z als Stick loest KEIN L2 aus '%s'", rec);
        CHECK(q->rx > 0.9f && fabsf(q->ry) < 0.05f, "Z = rechter Stick X (rx=%.2f ry=%.2f)", q->rx, q->ry);
        pad_event(q, EV_ABS, ABS_Z, 128);
        pad_event(q, EV_KEY, BTN_TL2, 1);
        CHECK(has("B272=1"), "BTN_TL2 = L2 '%s'", rec);
        pad_event(q, EV_KEY, BTN_TL2, 0);
        pads[3] = NULL; free(q);
    }


    /* Wiimote: Tasten, Nunchuk, IR-Zeiger */
    {
        Pad *w = mk(); w->wii = 1; pads[6] = w;
        Pad *nk = mk(); nk->wii = 2; nk->cx = -13; nk->cy = 10; pads[7] = nk;
        g.active = true; cfg.mouse_left = false; clear();
        wii_button(w, BTN_SOUTH, 1); wii_button(w, BTN_SOUTH, 0);
        CHECK(has("B272=1") && has("B272=0"), "Wii A = Linksklick '%s'", rec);
        clear(); wii_button(w, BTN_EAST, 1); wii_button(w, BTN_EAST, 0);
        CHECK(has("B273=1"), "Wii B = Rechtsklick '%s'", rec);
        clear(); wii_button(w, KEY_UP, 1); wii_button(w, KEY_UP, 0);
        CHECK(has("K103=1"), "Wii Steuerkreuz hoch = Pfeil hoch '%s'", rec);
        clear(); wii_button(w, BTN_1, 1); wii_button(w, BTN_1, 0);
        CHECK(has("K57=1"), "Wii 1 = Space '%s'", rec);
        clear(); wii_nunchuk(nk, EV_ABS, ABS_HAT0Y, 10 + 90);   /* Stick nach oben (positiv) */
        adv(10);
        CHECK(has("K17=1"), "Nunchuk hoch = W '%s'", rec);
        wii_nunchuk(nk, EV_ABS, ABS_HAT0Y, 10);
        CHECK(has("K17=0"), "Nunchuk Ruhe = W los '%s'", rec);
        clear(); wii_nunchuk(nk, EV_KEY, BTN_Z, 1); wii_nunchuk(nk, EV_KEY, BTN_Z, 0);
        adv(100);
        CHECK(has("K16=1"), "Nunchuk Z = Q '%s'", rec);
        /* Home auf der Wiimote = Ebene */
        clear(); wii_button(w, BTN_MODE, 1); wii_button(w, BTN_1, 1); wii_button(w, BTN_1, 0); wii_button(w, BTN_MODE, 0);
        CHECK(has("K191=1") || has("K183=1"), "Wii Home+1 = F13 '%s'", rec);
        /* IR: zwei Punkte -> Mitte, gespiegelt */
        ir.init = false; ir.have2 = false; ir.vis = false; ir.last_x = ir.last_y = 0;
        cal_u0 = cal_v0 = 0.f; cal_u1 = cal_v1 = 1.f; clear();
        int two[2][2] = { { 400, 300 }, { 600, 500 } };
        ir_process(two, 2); ir_emit(0.5f);
        CHECK(has("A0:") && has("A1:"), "IR gibt Zeiger aus '%s'", rec);
        CHECK(fabsf(ir.u - (1.f - 500.f / 1023.f)) < 0.002f, "IR X gespiegelt u=%.3f", ir.u);
        /* ein Punkt: Mitte bleibt (Versatz vom naeheren Punkt) */
        float u0 = ir.u, v0 = ir.v;
        int one[1][2] = { { 410, 310 } };
        ir_process(one, 1); ir_emit(0.5f);
        CHECK(fabsf(ir.u - (u0 - 10.f / 1023.f)) < 0.002f && fabsf(ir.v - (v0 + 10.f / 767.f)) < 0.002f, "IR 1 Punkt folgt (u=%.3f v=%.3f)", ir.u, ir.v);
        clear(); ir_process(NULL, 0);
        CHECK(!ir.vis && rec[0] == 0, "IR weg: Zeiger bleibt stehen '%s'", rec);
        /* Kalibrierung: A zeigt Ecken */
        ir.init = false; ir.vis = false; cal_u0 = cal_v0 = 0.f; cal_u1 = cal_v1 = 1.f;
        int c1[2][2] = { { 800, 150 }, { 800, 150 } }; ir_process(c1, 2);
        wii_cal_step = 1; clear(); wii_button(w, BTN_SOUTH, 1); wii_button(w, BTN_SOUTH, 0);
        CHECK(wii_cal_step == 2 && rec[0] == 0, "Kal. Schritt 1: A kein Klick '%s'", rec);
        int c2[2][2] = { { 200, 600 }, { 200, 600 } }; ir_process(c2, 2);
        wii_button(w, BTN_SOUTH, 1); wii_button(w, BTN_SOUTH, 0);
        CHECK(wii_cal_step == 0 && cal_u1 > cal_u0 && cal_v1 > cal_v0, "Kal. fertig u=%.2f..%.2f v=%.2f..%.2f", cal_u0, cal_u1, cal_v0, cal_v1);
        cal_u0 = cal_v0 = 0.f; cal_u1 = cal_v1 = 1.f;
        /* Bereich: rechte Haelfte */
        cfg_apply_kv("wii_rect", "0.5 0 1 1"); cfg_apply_kv("wii_smooth", "5");
        CHECK(cfg.wii_tau == 0.f, "wii_smooth 5 = roh");
        ir.init = false; ir.vis = false; clear();
        int mid[2][2] = { { 511, 383 }, { 511, 383 } };
        ir_process(mid, 2); ir_emit(0.5f);
        CHECK(has("A0:2457") || has("A0:245") , "Zeiger in rechter Haelfte '%s'", rec);
        cfg_apply_kv("wii_rect", "0 0 1 1");
        /* Glaettung nach Zeit: kleiner Schritt wird ueber mehrere Ticks genommen, nicht sofort */
        cfg_apply_kv("wii_smooth", "3"); cal_u0 = cal_v0 = 0.f; cal_u1 = cal_v1 = 1.f;
        ir.init = false; ir.vis = false;
        int s0[2][2] = { { 500, 380 }, { 500, 380 } }, s1[2][2] = { { 480, 380 }, { 480, 380 } };
        ir_process(s0, 2); ir_emit(0.008f);
        float sx0 = ir.sx; ir_process(s1, 2); ir_emit(0.008f);
        CHECK(ir.sx != sx0 && fabsf(ir.sx - ir.tx) > 0.003f, "Glaettung: nach 8 ms noch nicht am Ziel (sx=%.4f tx=%.4f)", ir.sx, ir.tx);
        for (int i = 0; i < 60; i++) ir_emit(0.008f);
        CHECK(fabsf(ir.sx - ir.tx) < 0.002f, "Glaettung: nach 0.5 s am Ziel");
        cfg_apply_kv("wii_rect", "0 0 1 1");
        /* Zwei Wiimotes: Nunchuk/IR gehoeren zum Wiimote mit gleicher Adresse, IR-Zeiger nur vom ersten */
        {
            Pad *w1 = mk(), *w2 = mk(), *n2 = mk(), *i1 = mk(), *i2 = mk();
            w1->wii = 1; w2->wii = 1; n2->wii = 2; i1->wii = 3; i2->wii = 3;
            snprintf(w1->uniq, sizeof w1->uniq, "AA:01"); snprintf(w2->uniq, sizeof w2->uniq, "BB:02");
            snprintf(n2->uniq, sizeof n2->uniq, "BB:02"); snprintf(i1->uniq, sizeof i1->uniq, "AA:01"); snprintf(i2->uniq, sizeof i2->uniq, "BB:02");
            Pad *save[MAX_PADS]; memcpy(save, pads, sizeof save); memset(pads, 0, sizeof pads);
            pads[0] = w1; pads[1] = w2;
            CHECK(wii_core_for(n2) == w2, "Nunchuk von Wiimote 2 gehoert zu Wiimote 2");
            CHECK(wii_ir_primary(i1) && !wii_ir_primary(i2), "IR-Zeiger nur vom ersten Wiimote");
            memcpy(pads, save, sizeof pads);
            free(w1); free(w2); free(n2); free(i1); free(i2);
        }
        /* Modi: relativ (Delta), Joystick (Mitte), Auto per Fenster */
        {
            cfg_apply_kv("wii_smooth", "5"); cfg_apply_kv("wii_rel_scale", "1000"); cal_u0 = cal_v0 = 0.f; cal_u1 = cal_v1 = 1.f;
            wii_mode_rt = 1; ir.init = false; ir.vis = false; clear();
            int m0[2][2] = { { 511, 383 }, { 511, 383 } }, m1[2][2] = { { 460, 383 }, { 460, 383 } };   /* nach links im Bild = Zeiger nach rechts (gespiegelt) */
            ir_process(m0, 2); ir_emit(0.5f);
            CHECK(rec[0] == 0, "rel: erstes Bild gibt nichts aus '%s'", rec);
            ir_process(m1, 2); ir_emit(0.5f);
            CHECK(has("R0:") , "rel: Bewegung -> REL_X '%s'", rec);
            wii_mode_rt = 2; ir.init = false; ir.vis = false; clear();
            int j[2][2] = { { 100, 383 }, { 100, 383 } };        /* weit links im Bild = Zeiger rechts */
            ir_process(j, 2); ir_emit(0.1f);
            CHECK(has("R0:") && !has("R0:-"), "joy: rechts von der Mitte -> positive REL_X '%s'", rec);
            ir.init = false; ir.vis = false; clear();
            int c0[2][2] = { { 511, 383 }, { 511, 383 } };
            ir_process(c0, 2); ir_emit(0.1f);
            CHECK(rec[0] == 0, "joy: Mitte = Ruhe '%s'", rec);
            wii_mode_rt = -1;
            CHECK(wii_mode_eff() == 0, "Standard absolut");
            hypr_line("activewindow>>Minecraft* 1.20.1,Minecraft* 1.20.1");
            CHECK(wii_mode_eff() == 0, "kein Auto-Modus mehr (activewindow wird ignoriert)");
            cfg_apply_kv("wii_mons", "DP-1 0 0 0.6 1;HDMI-A-1 0.6 0 1 0.75"); cfg_apply_kv("wii_area", "active");
            hypr_line("focusedmon>>HDMI-A-1,3");
            CHECK(cfg.wii_area_active && act_ok && fabsf(act_rect[0] - 0.6f) < 0.001f && fabsf(act_rect[3] - 0.75f) < 0.001f, "Aktiver Monitor -> Zeigerbereich");
            hypr_line("focusedmonv2>>DP-1,2");
            CHECK(act_ok && fabsf(act_rect[2] - 0.6f) < 0.001f, "focusedmonv2 wird auch verstanden");
            act_ok = false; cfg_apply_kv("wii_cur", "HDMI-A-1");
            { int c1[2][2] = { { 511, 383 }, { 511, 383 } }; ir.init = false; ir.vis = false; wii_mode_rt = 0; ir_process(c1, 2); ir_emit(0.1f); }
            CHECK(act_ok && fabsf(act_rect[0] - 0.6f) < 0.001f, "Startwert wii_cur -> Zeigerbereich ohne Event");
            cfg_apply_kv("wii_cur", ""); wii_mode_rt = -1;
            cfg_apply_kv("wii_area", "all"); act_ok = false;
            cfg_apply_kv("wii_rel_scale", "2500");
        }
        /* Smoothing: Stufe 1 deutlich traeger als Stufe 4 */
        {
            cal_u0 = cal_v0 = 0.f; cal_u1 = cal_v1 = 1.f;
            float res[2];
            int lv[2] = { 1, 4 };
            for (int k = 0; k < 2; k++) {
                char sv[4]; snprintf(sv, sizeof sv, "%d", lv[k]); cfg_apply_kv("wii_smooth", sv);
                ir.init = false; ir.vis = false; wii_mode_rt = 0;
                int a0[2][2] = { { 500, 380 }, { 500, 380 } }, a1[2][2] = { { 460, 380 }, { 460, 380 } };
                ir_process(a0, 2); ir_emit(0.008f); float x0 = ir.sx;
                ir_process(a1, 2);
                for (int i = 0; i < 10; i++) ir_emit(0.008f);    /* 80 ms */
                res[k] = fabsf(ir.sx - x0) / fabsf(ir.tx - x0);
            }
            CHECK(res[0] < 0.2f && res[1] > 0.45f && res[0] < res[1] * 0.5f, "Smoothing 1 viel traeger als 4 (%.2f vs %.2f nach 80ms)", res[0], res[1]);
            wii_mode_rt = -1; cfg_apply_kv("wii_smooth", "3");
        }
        /* Mapping-Editor: Aktionen parsen/ausgeben */
        {
            Action ac; char sb[96];
            CHECK(parse_action("ctrl+shift+t", &ac) && ac.kind == 1 && ac.code == KEY_T && ac.mods == 3, "parse ctrl+shift+t");
            action_str(&ac, sb, sizeof sb); CHECK(!strcmp(sb, "shift+ctrl+t"), "action_str '%s'", sb);
            CHECK(parse_action("super+mouse:left", &ac) && ac.kind == 2 && ac.code == BTN_LEFT && ac.mods == 8, "parse super+mouse:left");
            CHECK(parse_action("scroll:down", &ac) && ac.kind == 3 && ac.code == 1, "parse scroll:down");
            CHECK(parse_action("none", &ac) && ac.kind == 0, "parse none");
            CHECK(parse_action("shift", &ac) && ac.kind == 1 && ac.code == KEY_LEFTSHIFT, "parse shift allein");
            CHECK(!parse_action("ctrl+gibtsnicht", &ac) && !parse_action("mouse:x", &ac), "parse Fehler");
            /* Layout-Datei */
            snprintf(layout_dir, sizeof layout_dir, "/tmp/trafkpad_test_layouts"); mkdir(layout_dir, 0755);
            FILE *lf = fopen("/tmp/trafkpad_test_layouts/spiel.conf", "w");
            fputs("# test\nbase.A = enter\nhome.A = ctrl+c\nbase.DU = scroll:up\nbase.L2 = none\nstick.base = none\nstick.home = mouse\nbase.HOME = x\nbase.QQ = y\nbase.B = kaputt+\n", lf);
            fclose(lf);
            cfg_defaults(); snprintf(cfg.layout, sizeof cfg.layout, "spiel"); build_maps();
            CHECK(map_base[I_A].code == KEY_ENTER, "Layout: base.A = Enter");
            CHECK(map_home[I_A].code == KEY_C && map_home[I_A].mods == 2, "Layout: home.A = Ctrl+C");
            CHECK(map_base[I_DU].kind == 3 && map_base[I_L2].kind == 0, "Layout: Scroll + none");
            CHECK(map_base[I_B].code == KEY_X, "Layout: kaputte Zeile ignoriert");
            CHECK(cfg.stick_base == 0 && cfg.stick_home == 1, "Layout: Stick-Modi");
            char big[6144]; dump_maps(big, sizeof big);
            CHECK(strstr(big, "base.A=enter") && strstr(big, "home.A=ctrl+c") && strstr(big, "layout=spiel") && strstr(big, "stick.home=mouse"), "dump_maps");
            /* Scroll-Aktion laeuft im Tick, solange gehalten */
            Pad *sp = mk(); pads[5] = sp; g.active = true; clear();
            press_action(sp, I_DU);
            tick(clock_ms() + 16);
            tick(clock_ms() + 40);
            CHECK(has("R11:") || has("R8:"), "Scroll-Taste scrollt '%s'", rec);
            release_action(sp, I_DU); pads[5] = NULL; free(sp);
            cfg_defaults(); build_maps();
            CHECK(map_base[I_A].code == KEY_SPACE, "Standard nach Layout-Reset");
        }
        /* Erkennung */
        {
            Pad *dp = mk(); memset(dp->down, 0, sizeof dp->down); memset(dp->src_btn, 0, sizeof dp->src_btn); memset(dp->src_abs, 0, sizeof dp->src_abs); dp->lx = dp->ly = 0; Pad *keep[MAX_PADS]; memcpy(keep, pads, sizeof keep); memset(pads, 0, sizeof pads); pads[5] = dp; g.active = true; clear();
            detect_on = true; detect_name[0] = 0;
            set_src(dp, I_Y, false, true);
            CHECK(!strcmp(detect_name, "Y") && !detect_on && rec[0] == 0, "detect meldet Y, fuehrt nichts aus '%s'", rec);
            set_src(dp, I_Y, false, false);
            CHECK(rec[0] == 0, "detect: Loslassen ohne Folgen");
            set_src(dp, I_A, false, true);
            CHECK(has("K57=1"), "nach detect wieder normal '%s'", rec);
            set_src(dp, I_A, false, false);
            char pr[320]; set_src(dp, I_B, false, true); pressed_str(pr, sizeof pr);
            CHECK(strstr(pr, "down=B ") != NULL, "pressed '%s'", pr);
            set_src(dp, I_B, false, false); memcpy(pads, keep, sizeof pads); free(dp);
        }
        /* Eigene Wiimote-Belegung, Modus-Kombi, Monitor-Sperre */
        {
            cfg_defaults(); snprintf(layout_dir, sizeof layout_dir, "/tmp/trafkpad_test_layouts");
            FILE *lf = fopen("/tmp/trafkpad_test_layouts/wiitest.conf", "w");
            fputs("wbase.L2 = enter\nwhome.A = ctrl+c\nbase.L2 = none\n", lf); fclose(lf);
            snprintf(cfg.layout, sizeof cfg.layout, "wiitest"); build_maps();
            CHECK(wmap_base[I_L2].code == KEY_ENTER && map_base[I_L2].kind == 0, "wbase. nur fuer Wiimote, base. nur fuer Gamepad");
            CHECK(wmap_home[I_A].code == KEY_C && map_home[I_A].code == KEY_F13, "whome.");
            char big[6144]; dump_maps(big, sizeof big);
            CHECK(strstr(big, "wbase.L2=enter") && strstr(big, "whome.A=ctrl+c") && strstr(big, "base.L2=none"), "dump enthaelt Wiimote-Belegung");
            Pad *keep[MAX_PADS]; memcpy(keep, pads, sizeof keep); memset(pads, 0, sizeof pads);
            Pad *wp = mk(); wp->wii = 1; pads[3] = wp; Pad *gp = mk(); pads[4] = gp;
            memset(wp->down, 0, sizeof wp->down); memset(wp->src_btn, 0, sizeof wp->src_btn); memset(wp->src_abs, 0, sizeof wp->src_abs);
            memset(gp->down, 0, sizeof gp->down); memset(gp->src_btn, 0, sizeof gp->src_btn); memset(gp->src_abs, 0, sizeof gp->src_abs);
            g.active = true; clear();
            press_action(wp, I_L2); CHECK(has("K28=1"), "Wiimote-A -> Enter laut Wiimote-Belegung '%s'", rec); release_action(wp, I_L2);
            clear(); press_action(gp, I_L2); CHECK(rec[0] == 0, "Gamepad-L2 = none '%s'", rec);
            /* Modus-Kombi 1+2 */
            wii_mode_rt = -1; cfg_defaults(); build_maps();
            int64_t t0 = clock_ms();
            set_src(wp, I_A, false, true); set_src(wp, I_B, false, true);
            CHECK(rec[0] == 0 || !has("K57=1"), "1+2 innerhalb der Gnadenfrist werden verschluckt '%s'", rec);
            CHECK(wp->mcombo_armed, "Modus-Kombi scharf");
            tick(t0 + 300); CHECK(wii_mode_eff() == 0, "zu frueh: noch absolut");
            tick(t0 + 700); CHECK(wii_mode_eff() == 1, "nach 600 ms: relativ");
            set_src(wp, I_A, false, false); set_src(wp, I_B, false, false);
            set_src(wp, I_A, false, true); set_src(wp, I_B, false, true);
            tick(clock_ms() + 700); CHECK(wii_mode_eff() == 0, "nochmal: zurueck auf absolut");
            set_src(wp, I_A, false, false); set_src(wp, I_B, false, false);
            cfg_apply_kv("wii_mode_combo", "none"); CHECK(cfg.wii_mode_mask == 0, "Modus-Kombi aus");
            cfg_apply_kv("wii_mode_combo", "L2+R2"); CHECK(cfg.wii_mode_mask == ((1u << I_L2) | (1u << I_R2)), "Modus-Kombi A+B der Wiimote");
            cfg_apply_kv("wii_toggle_combo", "A+B"); CHECK(cfg.wii_combo_mask == ((1u << I_A) | (1u << I_B)), "Wiimote-Toggle-Kombi frei waehlbar");
            cfg_defaults(); build_maps();
            /* Monitor-Sperre */
            clear(); mon_until = clock_ms() + 5000;
            set_src(gp, I_A, false, true);
            CHECK(rec[0] == 0 && !strcmp(mon_last, "A") && !mon_last_w, "Sperre: A wird nur gemeldet '%s'", rec);
            char pr[400]; pressed_str(pr, sizeof pr);
            CHECK(strstr(pr, "down=A ") && strstr(pr, "last=A") && strstr(pr, "lastw=0"), "pressed meldet A '%s'", pr);
            set_src(gp, I_A, false, false);
            clear(); set_src(wp, I_L2, false, true); pressed_str(pr, sizeof pr);
            CHECK(rec[0] == 0 && mon_last_w && strstr(pr, "wdown=L2 ") && strstr(pr, "lastw=1"), "Sperre: Wiimote getrennt gemeldet '%s'", pr);
            set_src(wp, I_L2, false, false);
            mon_until = 0; clear();
            set_src(gp, I_A, false, true); CHECK(has("K57=1"), "Sperre abgelaufen: wieder normal '%s'", rec);
            set_src(gp, I_A, false, false);
            pads[3] = pads[4] = NULL; free(wp); free(gp); memcpy(pads, keep, sizeof pads);
        }
        /* Toggle-Kombi: + und - */
        CHECK(combo_down(w) == false, "Kombi nicht ohne Tasten");
        w->down[I_START] = w->down[I_SELECT] = true;
        CHECK(combo_down(w), "Wii-Kombi + und -");
        w->down[I_START] = w->down[I_SELECT] = false;
        pads[6] = pads[7] = NULL; free(w); free(nk);
    }

    printf(fails ? "\n%d FEHLER\n" : "\nalle Tests ok\n", fails);
    return fails != 0;
}
#endif
