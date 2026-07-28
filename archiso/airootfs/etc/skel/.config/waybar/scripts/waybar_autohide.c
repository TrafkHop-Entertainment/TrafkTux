#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <dirent.h>
#include <signal.h>
#include <time.h>
#include <glob.h>
#include <ctype.h>

#define LOG_FILE "/tmp/waybar-autohide.log"
#define PID_FILE "/tmp/waybar-autohide.pid"
#define TRIG_PX 15
#define HIDE_PX 65
/* Monitore werden alle 50 Durchläufe aktualisiert */
#define SCREEN_H_REFRESH_ITERS 50

/* Drei Polling-Stufen:
 *   FAST (35ms)  – Maus nah am Rand oder Waybar gerade sichtbar
 *   MID  (80ms)  – Maus in der Mittelzone, könnte bald am Rand landen
 *   SLOW (200ms) – Maus weit weg vom Rand
 *
 * FAST_ZONE_PX:  ab hier → FAST-Polling  (= HIDE_PX * 2 = 130px)
 * MID_ZONE_PX:   ab hier → MID-Polling   (200px vom Rand)
 *
 * Latenz im Worst-Case:
 *   Alt: Maus springt von Mitte zu Rand → bis zu 350ms Verzögerung
 *   Neu: SLOW-Zone → max 200ms, MID-Zone → max 80ms, FAST-Zone → max 35ms
 *
 * CPU-Impact: +2 Socket-Calls/sec im SLOW-Modus (von 2.9 auf 5.0/sec) → negligible.
 */
#define FAST_POLL_MS  35
#define MID_POLL_MS   80
#define SLOW_POLL_MS  200
#define FAST_ZONE_PX  (HIDE_PX * 2)
#define MID_ZONE_PX   200

#define TOUCH_SHOW_SIGNAL SIGRTMIN
#define TOUCH_TIMEOUT_SEC 5
#define LOCK_TOGGLE_SIGNAL (SIGRTMIN + 1)

volatile sig_atomic_t running = 1;
volatile sig_atomic_t touch_trigger = 0;
volatile sig_atomic_t lock_trigger = 0;
volatile sig_atomic_t autohide_locked = 0;

/* ── Cache für das Monitor-Layout ─────────────────────────────────── */
typedef struct {
    float x, y, w, h;
} MonitorDef;

MonitorDef monitors[8];
int mon_count = 0;

void do_log(const char *msg) {
    FILE *f = fopen(LOG_FILE, "a");
    if (!f) return;
    time_t now = time(NULL);
    char tstr[64];
    strftime(tstr, sizeof(tstr), "%Y-%m-%d %H:%M:%S", localtime(&now));
    fprintf(f, "%s: %s\n", tstr, msg);
    fclose(f);
}

char* find_hypr_socket() {
    static char path[512];
    char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    char *runtime = getenv("XDG_RUNTIME_DIR");
    char default_runtime[64];
    if (!runtime) {
        snprintf(default_runtime, sizeof(default_runtime), "/run/user/%d", getuid());
        runtime = default_runtime;
    }
    if (sig) {
        snprintf(path, sizeof(path), "%s/hypr/%s/.socket.sock", runtime, sig);
        if (access(path, F_OK) == 0) return path;
    }
    char pattern[512];
    snprintf(pattern, sizeof(pattern), "%s/hypr/*/.socket.sock", runtime);
    glob_t glob_result;
    if (glob(pattern, 0, NULL, &glob_result) == 0) {
        if (glob_result.gl_pathc > 0) {
            strncpy(path, glob_result.gl_pathv[0], sizeof(path) - 1);
            globfree(&glob_result);
            return path;
        }
        globfree(&glob_result);
    }
    return NULL;
}

char* hypr_cmd(const char *sock_path, const char *cmd) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return NULL;
    struct timeval tv = { .tv_sec = 1, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);
    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(fd); return NULL;
    }
    if (write(fd, cmd, strlen(cmd)) < 0) {
        close(fd); return NULL;
    }
    shutdown(fd, SHUT_WR);
    size_t buf_size = 4096;
    size_t len = 0;
    char *buf = malloc(buf_size);
    if (!buf) { close(fd); return NULL; }
    while (1) {
        if (len + 1024 > buf_size) {
            buf_size *= 2;
            char *new_buf = realloc(buf, buf_size);
            if (!new_buf) { free(buf); close(fd); return NULL; }
            buf = new_buf;
        }
        ssize_t n = read(fd, buf + len, 1024);
        if (n <= 0) break;
        len += n;
    }
    buf[len] = '\0';
    close(fd);
    return buf;
}

int get_cursor_pos(const char *sock_path, int *x, int *y) {
    char *out = hypr_cmd(sock_path, "cursorpos");
    if (!out) return 0;
    char *comma = strchr(out, ',');
    if (comma) {
        *x = atoi(out);
        *y = atoi(comma + 1);
        free(out);
        return 1;
    }
    free(out);
    return 0;
}

/*
 * update_monitors() – liest "j/monitors" und baut das monitors[]-Array neu auf.
 *
 * ZWEI frühere Bugs in dieser Funktion:
 *
 * Bug A (Parsing): Der alte Code suchte nach dem nächsten "id":-Vorkommen und
 * ging dann rückwärts nach '{'. Das fand fälschlich auch verschachtelte Objekte
 * wie "activeWorkspace":{"id":1,...} und "specialWorkspace":{"id":0,...}.
 * Diese wurden mit Defaultwerten (w=1920, h=1080, x=0, y=0) als echte Monitore
 * ins Array geschrieben → 6 Geist-Einträge statt 2 echter Monitore.
 *
 * Fix A: Wir iterieren jetzt über die direkten Array-Kinder des JSON-Arrays.
 * Das äußere '[' bringt depth=1. Jedes '{' auf depth=1 ist ein Monitor-Objekt.
 * Wir extrahieren dieses vollständige Objekt per Klammerzählung und parsen
 * dann nur innerhalb dieses klar abgegrenzten Bereichs.
 *
 * Bug B (disabled-Check): Selbst mit sauberem Parsing wurden deaktivierte
 * Monitore manchmal mitgezählt, wenn "disabled" nicht gefunden wurde. Das
 * tritt auf, wenn hyprctl deaktivierte Outputs ohne das Feld listet. Wir
 * prüfen jetzt aktiv auf "disabled":true UND filtern Einträge ohne sinnvolle
 * Dimension (w oder h == 0 nach Division durch scale).
 */
void update_monitors(const char *sock_path) {
    char *out = hypr_cmd(sock_path, "j/monitors");
    if (!out) return;
    mon_count = 0;

    /*
     * Iteriere über die direkten Array-Kinder: suche '[', dann finde jedes '{'
     * auf der ersten Ebene (depth=1 nach dem '[').
     */
    char *arr_start = strchr(out, '[');
    if (!arr_start) {
        free(out);
        return;
    }

    char *p = arr_start + 1;  /* zeigt auf den Inhalt nach '[' */

    while (*p && mon_count < 8) {
        /* Leerzeichen / Newlines / Kommas überspringen */
        while (*p && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t' || *p == ','))
            p++;

        if (*p == ']' || *p == '\0')
            break;

        if (*p != '{') {
            p++;
            continue;
        }

        /* Objekt-Grenzen per Klammerzählung bestimmen */
        char *obj_start = p;
        char *obj_end = p;
        int depth = 0;
        for (char *q = obj_start; *q; q++) {
            if (*q == '{') depth++;
            else if (*q == '}') {
                depth--;
                if (depth == 0) { obj_end = q; break; }
            }
        }

        /* Weiter-Pointer setzen, bevor wir evtl. mit continue springen */
        p = obj_end + 1;

        /* ── Felder aus dem Objekt lesen ── */
        float mx = 0, my = 0, mw = 0, mh = 0, mscale = 1.0f;

        char *x_ptr = strstr(obj_start, "\"x\":");
        if (x_ptr && x_ptr < obj_end) mx = atof(x_ptr + 4);

        char *y_ptr = strstr(obj_start, "\"y\":");
        if (y_ptr && y_ptr < obj_end) my = atof(y_ptr + 4);

        char *w_ptr = strstr(obj_start, "\"width\":");
        if (w_ptr && w_ptr < obj_end) mw = atof(w_ptr + 8);

        char *h_ptr = strstr(obj_start, "\"height\":");
        if (h_ptr && h_ptr < obj_end) mh = atof(h_ptr + 9);

        char *s_ptr = strstr(obj_start, "\"scale\":");
        if (s_ptr && s_ptr < obj_end) mscale = atof(s_ptr + 8);

        /* Deaktivierte Monitore überspringen */
        char *dis_ptr = strstr(obj_start, "\"disabled\":");
        if (dis_ptr && dis_ptr < obj_end) {
            /* Whitespace nach ':' überspringen */
            char *dval = dis_ptr + 11;
            while (*dval == ' ' || *dval == '\t') dval++;
            if (strncmp(dval, "true", 4) == 0) {
                char dbg[128];
                snprintf(dbg, sizeof(dbg),
                         "[DEBUG] Monitor uebersprungen (disabled): x=%.1f y=%.1f w=%.1f h=%.1f",
                         mx, my, mw, mh);
                do_log(dbg);
                continue;
            }
        }

        /* Einträge ohne sinnvolle Auflösung ignorieren */
        if (mw <= 0 || mh <= 0 || mscale <= 0) {
            do_log("[DEBUG] Monitor uebersprungen (keine sinnvolle Aufloesung)");
            continue;
        }

        monitors[mon_count].x = mx;
        monitors[mon_count].y = my;
        monitors[mon_count].w = mw / mscale;
        monitors[mon_count].h = mh / mscale;

        char dbg[200];
        snprintf(dbg, sizeof(dbg),
                 "[DEBUG] Monitor %d: x=%.1f y=%.1f w=%.1f h=%.1f "
                 "(raw w=%.1f h=%.1f scale=%.2f) -> bottom=%.1f",
                 mon_count, mx, my,
                 monitors[mon_count].w, monitors[mon_count].h,
                 mw, mh, mscale,
                 my + monitors[mon_count].h);
        do_log(dbg);

        mon_count++;
    }

    free(out);
}

typedef enum { MATCH_EXACT, MATCH_CLAMPED_X, MATCH_FALLBACK, MATCH_NONE } MatchType;

/*
 * get_dist_to_bottom() – Abstand der Maus zum unteren Rand IHRES Monitors.
 *
 * Früherer Bug (Bug C): Der MATCH_CLAMPED_X-Pfad hat cy auf m->bottom
 * geclampet, wenn cy > m->bottom. Resultat: dist=0, Waybar erscheint sofort,
 * wenn die Maus vom höheren Laptop-Screen an der Unterkante auf den kürzeren
 * externen Monitor wechselt – obwohl sie visuell in der Mitte des ext. Monitors
 * war (die Monitorunterkante ist schlicht bei y=1080, der Cursor war bei y>1080).
 *
 * Fix C: Liegt cy ÜBER m->bottom (also im "Überhang"-Bereich des höheren
 * Nachbar-Monitors), ist die Maus definitiv NICHT am unteren Rand des aktuellen
 * Monitors. Wir geben einen Wert > HIDE_PX zurück, damit kein Trigger feuert.
 * Liegt cy unter m->y (oberhalb des Monitors), geben wir die volle Monitorhöhe
 * zurück – auch kein Trigger.
 */
float get_dist_to_bottom(int cx, int cy, int *out_idx, MatchType *out_type) {
    if (mon_count == 0) {
        if (out_idx)  *out_idx  = -1;
        if (out_type) *out_type = MATCH_NONE;
        return 1080.0f - cy;
    }

    /* 1. Exakter Treffer: Cursor liegt vollständig im Monitor */
    for (int i = 0; i < mon_count; i++) {
        MonitorDef *m = &monitors[i];
        if (cx >= m->x && cx <= (m->x + m->w) &&
            cy >= m->y && cy <= (m->y + m->h)) {
            if (out_idx)  *out_idx  = i;
            if (out_type) *out_type = MATCH_EXACT;
            return (m->y + m->h) - cy;
        }
    }

    /*
     * 2. X-Bereich stimmt, aber cy liegt außerhalb des Y-Bereichs.
     *
     * Das tritt auf, wenn unterschiedlich hohe Monitore nebeneinander stehen
     * (z.B. Laptop 1920×1200 neben externem 1920×1080, beide oben bündig).
     * Beim Übergang an der Unterkante des Laptops kann cy kurzzeitig > 1080
     * sein, obwohl der Cursor schon auf dem externen x-Bereich liegt.
     *
     * WICHTIG: In diesem Fall ist die Maus NICHT am unteren Rand des ext.
     * Monitors – sie ist schlicht im Höhenüberhang des Laptop-Screens.
     * Kein Trigger! Wir geben HIDE_PX+1 zurück.
     *
     * Liegt cy < m->y (Cursor oberhalb des Monitors, sehr selten), geben
     * wir m->h zurück – ebenfalls kein Trigger.
     */
    for (int i = 0; i < mon_count; i++) {
        MonitorDef *m = &monitors[i];
        if (cx >= m->x && cx <= (m->x + m->w)) {
            if (out_idx)  *out_idx  = i;
            if (cy > m->y + m->h) {
                /* Cursor im Überhang des höheren Nachbar-Monitors */
                if (out_type) *out_type = MATCH_CLAMPED_X;
                return (float)(HIDE_PX + 1);
            }
            /* cy < m->y: Cursor oberhalb des Monitors */
            if (out_type) *out_type = MATCH_CLAMPED_X;
            return m->h;
        }
    }

    /* Letzter Fallback – praktisch nie erreicht */
    if (out_idx)  *out_idx  = 0;
    if (out_type) *out_type = MATCH_FALLBACK;
    return (monitors[0].y + monitors[0].h) - cy;
}

pid_t get_waybar_pid() {
    DIR *dir = opendir("/proc");
    if (!dir) return -1;
    struct dirent *ent;
    pid_t target = -1;
    while ((ent = readdir(dir)) != NULL) {
        if (!isdigit(ent->d_name[0])) continue;
        char path[256];
        snprintf(path, sizeof(path), "/proc/%s/comm", ent->d_name);
        FILE *f = fopen(path, "r");
        if (f) {
            char comm[256];
            if (fgets(comm, sizeof(comm), f)) {
                comm[strcspn(comm, "\n")] = 0;
                if (strcmp(comm, "waybar") == 0) {
                    target = atoi(ent->d_name);
                    fclose(f); break;
                }
            }
            fclose(f);
        }
    }
    closedir(dir);
    return target;
}

void send_signal(int sig) {
    pid_t pid = get_waybar_pid();
    if (pid <= 0) return;
    if (kill(pid, sig) == 0) {
        char msg[64];
        snprintf(msg, sizeof(msg), "Signal %d -> PID %d", (sig == SIGUSR1 ? 10 : 12), pid);
        do_log(msg);
    }
}

void on_term(int sig) { (void)sig; running = 0; do_log("Autohide beendet"); }
void on_touch_trigger(int sig) { (void)sig; touch_trigger = 1; }
void on_lock_toggle(int sig) { (void)sig; lock_trigger = 1; }

void write_pid_file() {
    FILE *f = fopen(PID_FILE, "w");
    if (!f) return;
    fprintf(f, "%d\n", getpid());
    fclose(f);
}

int main() {
    char logmsg[128];
    snprintf(logmsg, sizeof(logmsg), "Autohide (Fix) gestartet (PID %d)", getpid());
    do_log(logmsg);

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_term;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);

    struct sigaction sa_touch;
    memset(&sa_touch, 0, sizeof(sa_touch));
    sa_touch.sa_handler = on_touch_trigger;
    sigaction(TOUCH_SHOW_SIGNAL, &sa_touch, NULL);

    struct sigaction sa_lock;
    memset(&sa_lock, 0, sizeof(sa_lock));
    sa_lock.sa_handler = on_lock_toggle;
    sigaction(LOCK_TOGGLE_SIGNAL, &sa_lock, NULL);

    write_pid_file();

    char *sock_path = find_hypr_socket();
    if (!sock_path) {
        do_log("✗ Hyprland-Socket nicht gefunden!");
        return 1;
    }

    update_monitors(sock_path);

    int visible = 0;
    int refresh_counter = 0;
    int touch_override_active = 0;
    time_t touch_override_until = 0;

    struct timespec ts_fast = { .tv_sec = 0, .tv_nsec = FAST_POLL_MS * 1000000L };
    struct timespec ts_mid  = { .tv_sec = 0, .tv_nsec = MID_POLL_MS  * 1000000L };
    struct timespec ts_slow = { .tv_sec = 0, .tv_nsec = SLOW_POLL_MS * 1000000L };

    while (running) {
        refresh_counter++;
        if (refresh_counter >= SCREEN_H_REFRESH_ITERS) {
            refresh_counter = 0;
            update_monitors(sock_path);
        }

        if (lock_trigger) {
            lock_trigger = 0;
            autohide_locked = !autohide_locked;
            if (autohide_locked) {
                send_signal(SIGUSR1);
                visible = 0;
                touch_override_active = 0;
                system("notify-send -t 1200 'Waybar' 'Autohide gesperrt' >/dev/null 2>&1 &");
            } else {
                system("notify-send -t 1200 'Waybar' 'Autohide entsperrt' >/dev/null 2>&1 &");
            }
        }

        if (autohide_locked) {
            touch_trigger = 0;
            nanosleep(&ts_slow, NULL);
            continue;
        }

        if (touch_trigger) {
            touch_trigger = 0;
            if (!visible) {
                send_signal(SIGUSR2);
                visible = 1;
            }
            touch_override_active = 1;
            touch_override_until = time(NULL) + TOUCH_TIMEOUT_SEC;
        }

        /* 0 = slow, 1 = mid, 2 = fast */
        int poll_tier = (visible || touch_override_active) ? 2 : 0;

        if (touch_override_active) {
            if (time(NULL) >= touch_override_until) {
                if (visible) { send_signal(SIGUSR1); visible = 0; }
                touch_override_active = 0;
            }
        } else {
            int cx, cy;
            if (get_cursor_pos(sock_path, &cx, &cy)) {
                int mon_idx;
                MatchType mtype;
                float dist = get_dist_to_bottom(cx, cy, &mon_idx, &mtype);

                if (dist <= TRIG_PX && !visible) {
                    char dbg[160];
                    snprintf(dbg, sizeof(dbg),
                             "[DEBUG] SHOW cx=%d cy=%d dist=%.1f monitor=%d match=%d",
                             cx, cy, dist, mon_idx, mtype);
                    do_log(dbg);
                    send_signal(SIGUSR2);
                    visible = 1;
                } else if (dist > HIDE_PX && visible) {
                    char dbg[160];
                    snprintf(dbg, sizeof(dbg),
                             "[DEBUG] HIDE cx=%d cy=%d dist=%.1f monitor=%d match=%d",
                             cx, cy, dist, mon_idx, mtype);
                    do_log(dbg);
                    send_signal(SIGUSR1);
                    visible = 0;
                }

                /* Polling-Stufe anhand der Distanz zum Rand bestimmen */
                if (dist <= FAST_ZONE_PX)
                    poll_tier = 2;       /* FAST: nah am Rand */
                else if (dist <= MID_ZONE_PX)
                    poll_tier = 1;       /* MID:  Mittelzone */
                /* sonst bleibt poll_tier = 0 (SLOW) */
            }
        }

        if (poll_tier >= 2)
            nanosleep(&ts_fast, NULL);
        else if (poll_tier == 1)
            nanosleep(&ts_mid, NULL);
        else
            nanosleep(&ts_slow, NULL);
    }

    remove(PID_FILE);
    return 0;
}
