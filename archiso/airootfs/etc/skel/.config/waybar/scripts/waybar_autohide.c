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

// ── Touch-Modus ─────────────────────────────────────────────────────
// Maus-Logik oben bleibt unverändert (kontinuierliche cursorpos-Abfrage).
// Für Touch gibt's keinen "Zeiger, der sich entfernt" - der Trigger ist
// ein einzelnes Signal von außen (z.B. eine hyprgrass-Edge-Swipe-Geste,
// siehe hyprland.lua), und statt "Cursor weit weg" entscheidet ein reiner
// Timeout, wann die Bar wieder verschwindet.
#define TOUCH_SHOW_SIGNAL SIGRTMIN
#define TOUCH_TIMEOUT_SEC 4

volatile sig_atomic_t running = 1;
volatile sig_atomic_t touch_trigger = 0;

// ── Logging ────────────────────────────────────────────────────────
void do_log(const char *msg) {
    FILE *f = fopen(LOG_FILE, "a");
    if (!f) return;

    time_t now = time(NULL);
    char tstr[64];
    strftime(tstr, sizeof(tstr), "%Y-%m-%d %H:%M:%S", localtime(&now));

    fprintf(f, "%s: %s\n", tstr, msg);
    fclose(f);
}

// ── Hyprland-IPC-Socket finden ─────────────────────────────────────
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

    // Fallback: Globbing
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

// ── IPC-Kommando senden & empfangen ────────────────────────────────
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
        close(fd);
        return NULL;
    }

    if (write(fd, cmd, strlen(cmd)) < 0) {
        close(fd);
        return NULL;
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

// ── Y-Position des Cursors extrahieren ─────────────────────────────
int get_cursor_y(const char *sock_path, int *y) {
    char *out = hypr_cmd(sock_path, "cursorpos");
    if (!out) return 0;

    // Output ist z.B. "1920, 1080"
    char *comma = strchr(out, ',');
    if (comma) {
        *y = atoi(comma + 1);
        free(out);
        return 1;
    }
    free(out);
    return 0;
}

// ── Bildschirmhöhe (skaliert) extrahieren ──────────────────────────
float get_screen_height(const char *sock_path) {
    char *out = hypr_cmd(sock_path, "j/monitors");
    if (!out) {
        do_log("⚠ Monitorabfrage fehlgeschlagen, nehme 1080 an");
        return 1080.0;
    }

    float height = 1080.0;
    float scale = 1.0;

    // Simples Pattern-Matching für den ersten Monitor im JSON
    char *h_ptr = strstr(out, "\"height\":");
    if (h_ptr) height = atof(h_ptr + 9);

    char *s_ptr = strstr(out, "\"scale\":");
    if (s_ptr) scale = atof(s_ptr + 8);

    free(out);
    return height / scale;
}

// ── Waybar PID finden ──────────────────────────────────────────────
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
                comm[strcspn(comm, "\n")] = 0; // Newline entfernen
                if (strcmp(comm, "waybar") == 0) {
                    target = atoi(ent->d_name);
                    fclose(f);
                    break;
                }
            }
            fclose(f);
        }
    }
    closedir(dir);
    return target;
}

// ── Signal an Waybar senden ────────────────────────────────────────
void send_signal(int sig) {
    pid_t pid = get_waybar_pid();
    if (pid <= 0) {
        do_log("⚠ waybar-PID nicht gefunden");
        return;
    }

    if (kill(pid, sig) == 0) {
        char msg[64];
        snprintf(msg, sizeof(msg), "Signal %d -> PID %d", (sig == SIGUSR1 ? 10 : 12), pid);
        do_log(msg);
    } else {
        char msg[64];
        snprintf(msg, sizeof(msg), "⚠ Signal an PID %d fehlgeschlagen", pid);
        do_log(msg);
    }
}

// ── Terminierung behandeln ─────────────────────────────────────────
void on_term(int sig) {
    (void)sig; // unused
    running = 0;
    do_log("Autohide beendet");
}

// ── Touch-Trigger empfangen ──────────────────────────────────────────
// Nur ein Flag setzen (async-signal-safe) - die eigentliche Arbeit
// (kill(), fopen() fürs Log) passiert in der Main-Loop, nicht hier.
void on_touch_trigger(int sig) {
    (void)sig;
    touch_trigger = 1;
}

// ── Eigene PID ablegen ────────────────────────────────────────────────
// Damit andere Skripte (z.B. eine hyprgrass-Geste) uns gezielt anpingen
// können: `kill -RTMIN $(cat /tmp/waybar-autohide.pid)`.
void write_pid_file() {
    FILE *f = fopen(PID_FILE, "w");
    if (!f) return;
    fprintf(f, "%d\n", getpid());
    fclose(f);
}

// ── MAIN ───────────────────────────────────────────────────────────
int main() {
    char logmsg[128];
    snprintf(logmsg, sizeof(logmsg), "Autohide (C-Variante) gestartet (PID %d)", getpid());
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

    write_pid_file();

    char *sock_path = find_hypr_socket();
    if (!sock_path) {
        do_log("✗ Hyprland-Socket nicht gefunden - beende mich. HYPRLAND_INSTANCE_SIGNATURE prüfen.");
        return 1;
    }

    snprintf(logmsg, sizeof(logmsg), "Nutze Hyprland-Socket: %s", sock_path);
    do_log(logmsg);

    float screen_h = get_screen_height(sock_path);
    int visible = 0;

    // Touch-Override: solange gesetzt, ignoriert die Loop die normale
    // Maus-Distanz-Logik (die würde sonst sofort wieder verstecken, weil
    // bei Touch ja kein Zeiger in der Nähe des Rands "bleibt").
    int touch_override_active = 0;
    time_t touch_override_until = 0;

    // 10ms Takt
    struct timespec ts;
    ts.tv_sec = 0;
    ts.tv_nsec = 10 * 1000000L; // 10 Millisekunden

    while (running) {
        if (touch_trigger) {
            touch_trigger = 0;
            if (!visible) {
                send_signal(SIGUSR2);
                visible = 1;
                do_log("Touch-Trigger -> zeige Bar");
            }
            touch_override_active = 1;
            touch_override_until = time(NULL) + TOUCH_TIMEOUT_SEC;
        }

        if (touch_override_active) {
            if (time(NULL) >= touch_override_until) {
                if (visible) {
                    send_signal(SIGUSR1);
                    visible = 0;
                    do_log("Touch-Timeout -> verstecke Bar");
                }
                touch_override_active = 0;
            }
        } else {
            int y;
            if (get_cursor_y(sock_path, &y)) {
                float dist = screen_h - y;
                if (dist <= TRIG_PX && !visible) {
                    send_signal(SIGUSR2);
                    visible = 1;
                } else if (dist > HIDE_PX && visible) {
                    send_signal(SIGUSR1);
                    visible = 0;
                }
            }
        }
        nanosleep(&ts, NULL);
    }

    remove(PID_FILE);
    return 0;
}
