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

typedef struct { uint8_t kind; uint16_t code; uint16_t mod; } Action; /* kind: 0 none, 1 key, 2 maus-btn */
#define NOACT      ((Action){0, 0, 0})
#define K(c)       ((Action){1, (c), 0})
#define KM(m, c)   ((Action){1, (c), (m)})
#define MB(c)      ((Action){2, (c), 0})
#define MBM(m, c)  ((Action){2, (c), (m)})

typedef struct {
    bool enabled, start_active, left_wasd, swap_ab, rumble, notify, sounds, scroll_invert;
    float stick_thr, mouse_dz, mouse_speed, mouse_curve, scroll_speed;
    unsigned combo_mask;
    int combo_hold_ms, combo_grace_ms;
    /* Achsen-/Tasten-Zuordnung: -2 = automatisch, -1 = keine, sonst evdev-Code */
    int ov_rx, ov_ry, ov_l2, ov_r2, home_btn;
    bool debug, home_tap;
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
    bool combo_armed, combo_latch;
    int64_t combo_since;
    int ff_id;
    bool ff_ok, grabbed;
    bool home_armed, home_used;     /* Tipp auf Home = naechste Taste kommt aus der Home-Ebene */
    int64_t home_armed_until, home_down_at;
    bool ax_set;
    int ax[4];                     /* rechter Stick X/Y, L2-/R2-Achse (-1 = keine) */
} Pad;

/* welche evdev-Achse dient als ... (0 RX, 1 RY, 2 L2, 3 R2) */
static int ax_of(const Pad *p, int which) {
    static const int def[4] = { ABS_RX, ABS_RY, ABS_Z, ABS_RZ };
    return p->ax_set ? p->ax[which] : def[which];
}

static Cfg cfg;
static Action map_base[I_COUNT], map_home[I_COUNT];
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
#else
static struct libevdev_uinput *ui_kbd, *ui_mouse;
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
static void apply_action(const Action *a, int d) {
    if (!a->kind) return;
    if (d > 0) {
        if (a->mod) key_ref(a->mod, 1);
        a->kind == 1 ? key_ref(a->code, 1) : btn_ref(a->code, 1);
    } else {
        a->kind == 1 ? key_ref(a->code, -1) : btn_ref(a->code, -1);
        if (a->mod) key_ref(a->mod, -1);
    }
}
static void release_all_outputs(void) {
    for (int c = 1; c < KEYS_USED; c++) if (kref[c] > 0) { kref[c] = 0; out_key(c, 0); }
    for (int i = 0; i < 3; i++) if (bref[i] > 0) { bref[i] = 0; out_btn(BTN_LEFT + i, 0); }
}

/* ─────────────────────────────── Belegung ─────────────────────────────── */
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
        .ov_rx = -2, .ov_ry = -2, .ov_l2 = -2, .ov_r2 = -2, .home_btn = BTN_MODE, .debug = false, .home_tap = true,
    };
    cfg.combo_mask = (1u << I_L1) | (1u << I_R1) | (1u << I_SELECT) | (1u << I_START);
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
    else if (!strcmp(k, "home_tap")) cfg.home_tap = parse_bool(v, cfg.home_tap);
    else if (!strcmp(k, "debug")) cfg.debug = parse_bool(v, cfg.debug);
    else if (!strcmp(k, "rstick_x")) cfg.ov_rx = parse_code(v, EV_ABS, cfg.ov_rx);
    else if (!strcmp(k, "rstick_y")) cfg.ov_ry = parse_code(v, EV_ABS, cfg.ov_ry);
    else if (!strcmp(k, "l2_axis")) cfg.ov_l2 = parse_code(v, EV_ABS, cfg.ov_l2);
    else if (!strcmp(k, "r2_axis")) cfg.ov_r2 = parse_code(v, EV_ABS, cfg.ov_r2);
    else if (!strcmp(k, "home_button")) { int c = parse_code(v, EV_KEY, cfg.home_btn); cfg.home_btn = c < 0 ? BTN_MODE : c; }
    else if (!strcmp(k, "toggle_combo")) { unsigned m = parse_combo(v); if (m) cfg.combo_mask = m; }
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
    p->home = false; p->home_armed = false;
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
static bool combo_member(int i) { return i <= I_DR && (cfg.combo_mask & (1u << i)); }
static bool combo_down(const Pad *p) {
    for (int i = 0; i <= I_DR; i++) if ((cfg.combo_mask & (1u << i)) && !p->down[i]) return false;
    return cfg.combo_mask != 0;
}

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
    Action a = lay ? map_home[i] : map_base[i];
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

static void combo_check(Pad *p) {
    bool d = combo_down(p);
    if (d && !p->combo_armed && !p->combo_latch) {
        p->combo_armed = true;
        p->combo_since = clock_ms();
    } else if (!d) {
        p->combo_armed = false;
        p->combo_latch = false;
    }
}

static void on_input_change(Pad *p, int i, bool down) {
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
        if (combo_member(i) && cfg.combo_grace_ms > 0) {
            bool other = false;
            for (int j = 0; j <= I_DR; j++)
                if (j != i && combo_member(j) && p->down[j]) other = true;
            if (other) {                      /* sieht nach Toggle-Kombi aus: verschlucken */
                p->swallowed[i] = true;
                for (int j = 0; j <= I_DR; j++)
                    if (p->pending[j]) { p->pending[j] = false; p->swallowed[j] = true; }
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
        bool now = d[k].cur ? (m > r) : (m > t);
        set_src(p, d[k].in, true, now);
    }
}

static void pad_event(Pad *p, int type, int code, int value) {
    if (type == EV_KEY) {
        int in = -1;
        switch (code) {
        case BTN_SOUTH: in = cfg.swap_ab ? I_B : I_A; break;
        case BTN_EAST:  in = cfg.swap_ab ? I_A : I_B; break;
        case BTN_NORTH: in = I_X; break;
        case BTN_WEST:  in = I_Y; break;
        case BTN_TL: in = I_L1; break;      case BTN_TR: in = I_R1; break;
        case BTN_TL2: in = I_L2; break;     case BTN_TR2: in = I_R2; break;
        case BTN_SELECT: in = I_SELECT; break; case BTN_START: in = I_START; break;
        case BTN_THUMBL: in = I_L3; break;  case BTN_THUMBR: in = I_R3; break;
        case BTN_DPAD_UP: in = I_DU; break; case BTN_DPAD_DOWN: in = I_DD; break;
        case BTN_DPAD_LEFT: in = I_DL; break; case BTN_DPAD_RIGHT: in = I_DR; break;
        }
        if (code == cfg.home_btn) in = I_HOME;
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

/* ─────────────────────────── Tick: Maus, Scrollen, Timer ─────────────────────────── */
static float acc_x, acc_y, acc_sx, acc_sy;
static int notch_x, notch_y;
static int64_t last_tick;

static bool rstick_live(const Pad *p) { return hypotf(p->rx, p->ry) > cfg.mouse_dz; }

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
        for (int i = 0; i < I_COUNT; i++)
            if (p->pending[i]) {
                if (now >= p->pending_at[i]) { p->pending[i] = false; press_action(p, i); }
                else need = true;
            }
        if (p->combo_armed) {
            if (!combo_down(p)) p->combo_armed = false;
            else if (now - p->combo_since >= cfg.combo_hold_ms) {
                p->combo_armed = false;
                p->combo_latch = true;
                set_active(!g.active, true);
                return true;                  /* Zustand hat sich geaendert, neu bewerten */
            } else need = true;
        }
        if (!g.active || !rstick_live(p)) continue;
        need = true;
        float mag = hypotf(p->rx, p->ry);
        float s = clampf((mag - cfg.mouse_dz) / (1.f - cfg.mouse_dz), 0.f, 1.f);
        s = powf(s, cfg.mouse_curve);
        float ux = p->rx / mag, uy = p->ry / mag;
        if (layer_on(p)) {                     /* Scroll-Ebene */
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
    return need;
}

#ifndef TRAFKPAD_TEST
/* ─────────────────────────────── Geraete ─────────────────────────────── */
static int epfd = -1, tickfd = -1, infd = -1, sockfd = -1;
static bool tick_armed;
static int64_t rescan_at;

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
        if (p->combo_armed || (g.active && rstick_live(p))) return true;
        for (int i = 0; i < I_COUNT; i++) if (p->pending[i]) return true;
    }
    return false;
}
static void update_tick(void) { tick_set(need_tick()); }

static void pad_close(Pad *p) {
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
    bool is_pad = libevdev_has_event_code(dev, EV_KEY, BTN_SOUTH) && libevdev_has_event_code(dev, EV_ABS, ABS_X)
                  && !libevdev_has_event_type(dev, EV_REL) && strncmp(nm ? nm : "", "TrafkPad", 8) != 0;
    if (!is_pad) { libevdev_free(dev); close(fd); return; }
    int slot = -1;
    for (int i = 0; i < MAX_PADS; i++) if (!pads[i]) { slot = i; break; }
    if (slot < 0) { libevdev_free(dev); close(fd); return; }
    Pad *p = calloc(1, sizeof *p);
    p->fd = fd; p->dev = dev; p->ff_id = -1;
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
    for (size_t k = 0; k < sizeof btns / sizeof *btns; k++)
        if (libevdev_has_event_code(dev, EV_KEY, btns[k]))
            pad_event(p, EV_KEY, btns[k], libevdev_get_event_value(dev, EV_KEY, btns[k]));
    for (size_t k = 0; k < sizeof axes / sizeof *axes; k++)
        if (libevdev_has_event_code(dev, EV_ABS, axes[k]))
            pad_event(p, EV_ABS, axes[k], libevdev_get_event_value(dev, EV_ABS, axes[k]));
    struct epoll_event ee = { .events = EPOLLIN, .data.ptr = p };
    epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ee);
    logf_("Pad gefunden: %s (%s)%s", p->name, path, p->ff_ok ? " [rumble]" : "");
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
            if (ev.type == EV_KEY || ev.type == EV_ABS) {
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
    return 0;
}

/* ─────────────────────────────── Steuer-Socket ─────────────────────────────── */
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
        if (!cfg.enabled) apply_enabled(false);
        else if (!was_enabled) { apply_enabled(false); set_active(cfg.start_active, false); }
        snprintf(reply, sizeof reply, "ok reloaded enabled=%d", cfg.enabled);
    } else if (!strcmp(buf, "status")) {
        int np = 0;
        for (int i = 0; i < MAX_PADS; i++) if (pads[i]) np++;
        snprintf(reply, sizeof reply, "%s pads=%d enabled=%d", g.active ? "on" : "off", np, cfg.enabled);
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
    snprintf(flag_path, sizeof flag_path, "%s/.cache/hypr/controller_mode_active", home);
    if (xrd && strlen(xrd) < 90) snprintf(sock_path, sizeof sock_path, "%s/TrafkPad.sock", xrd);
    else snprintf(sock_path, sizeof sock_path, "/tmp/TrafkPad-%u.sock", (unsigned)getuid());

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
        int timeout = rescan_at ? 300 : -1;
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

    printf(fails ? "\n%d FEHLER\n" : "\nalle Tests ok\n", fails);
    return fails != 0;
}
#endif
