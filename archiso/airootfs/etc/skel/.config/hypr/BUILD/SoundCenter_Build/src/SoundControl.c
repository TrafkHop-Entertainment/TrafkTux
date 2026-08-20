/*
 * SoundControl.c — Ersatz für die alte soundctl.sh-Logik.
 *
 * Teil von SoundCenter. Gegenstück: SoundDaemon.c (der Daemon).
 *
 * Exakt dieselbe Kommandozeilen-Grammatik wie bisher:
 *
 *   SoundControl <event>                spielt <event> (nur wenn Master
 *                                        UND Event selbst an sind)
 *   SoundControl --enable  [event]      Master an, oder nur <event> an
 *   SoundControl --disable [event]      Master aus, oder nur <event> aus
 *   SoundControl --toggle  [event]      Master/Event umschalten, druckt on/off
 *   SoundControl --status  [event]      Master/Event-Status, druckt on/off
 *   (kein Argument)                     nichts tun, exit 0
 *
 * Nur "<event>" (Play) spricht den Daemon an - als reines fire-and-forget-
 * Datagramm ohne jede Antwort, das ist der einzige latenzkritische Pfad.
 * Enable/Disable/Toggle/Status schreiben/lesen direkt die Statusdateien
 * unter ~/.cache/hypr/ (genau wie die alte soundctl.sh) - braucht den
 * Daemon dafür gar nicht.
 *
 * KEIN fest einkompilierter Installationspfad: der Daemon wird beim
 * Selbstheilen (siehe unten) per execlp("SoundDaemon", ...) über $PATH
 * gesucht, nicht über einen hartkodierten ~/.config/hypr/bin/-Pfad. Damit
 * ist es egal, ob SoundDaemon/SoundControl in ~/.local/bin, /usr/bin,
 * /usr/local/bin oder sonst wo landen - Hauptsache beide sind über $PATH
 * auffindbar.
 *
 * Selbstheilung: falls der Daemon beim Abspielen nicht erreichbar ist
 * (Socket fehlt / ECONNREFUSED, z.B. nach einem Absturz oder vor dem
 * allerersten Start), wird er hier lautlos im Hintergrund nachgestartet -
 * der GERADE angeforderte Sound geht in diesem einen Fall verloren (kein
 * Warten, das würde wieder eine Verzögerung einführen), der NÄCHSTE
 * Aufruf funktioniert dann wieder normal. Funktioniert auch ganz ohne
 * SoundCenter.service/systemd.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/types.h>

static void get_home(char *buf, size_t n) {
    const char *h = getenv("HOME");
    snprintf(buf, n, "%s", (h && *h) ? h : "/tmp");
}

static void state_dir(char *buf, size_t n, const char *home) {
    snprintf(buf, n, "%s/.cache/hypr", home);
}

static void events_dir(char *buf, size_t n, const char *state) {
    snprintf(buf, n, "%s/sound_events", state);
}

static void socket_path(char *buf, size_t n) {
    const char *rt = getenv("XDG_RUNTIME_DIR");
    if (rt && *rt) snprintf(buf, n, "%s/SoundCenter.sock", rt);
    else            snprintf(buf, n, "/tmp/SoundCenter-%d.sock", getuid());
}

/* mkdir -p: legt jede Pfad-Komponente einzeln an (ein einzelner mkdir()
 * scheitert, wenn das Elternverzeichnis - z.B. ~/.cache - noch fehlt). */
static void ensure_dir(const char *path) {
    char tmp[PATH_MAX];
    snprintf(tmp, sizeof(tmp), "%s", path);
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
    mkdir(tmp, 0755);
}

static int flag_enabled(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return 1; /* fehlt -> Default an, wie bisher */
    char buf[16] = {0};
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r' || buf[n-1] == ' '))
        buf[--n] = '\0';
    return strcmp(buf, "1") == 0;
}

static void write_flag(const char *path, int val) {
    FILE *f = fopen(path, "w");
    if (!f) return;
    fprintf(f, "%d\n", val ? 1 : 0);
    fclose(f);
}

/* Startet SoundDaemon lautlos & losgelöst im Hintergrund, gefunden über
 * $PATH (siehe Datei-Kommentar oben) - Fire-and-forget, gleiches
 * setsid+dup2(/dev/null)-Muster wie überall sonst in der Config (siehe
 * RofiTrafkBubbleMenus.c exec_detached). */
static void spawn_daemon(void) {
    pid_t pid = fork();
    if (pid < 0) return;
    if (pid == 0) {
        setsid();
        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > 2) close(devnull);
        }
        execlp("SoundDaemon", "SoundDaemon", (char *)NULL);
        _exit(127); /* nur erreicht, wenn SoundDaemon nicht im $PATH liegt */
    }
    /* Elternprozess (wir) wartet NICHT - wir wollen sofort zurück. */
}

static void send_play(const char *event) {
    char sock_path[PATH_MAX];
    socket_path(sock_path, sizeof(sock_path));

    int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (fd < 0) return;

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);

    char msg[128];
    int len = snprintf(msg, sizeof(msg), "PLAY %s", event);

    ssize_t rc = sendto(fd, msg, (size_t)len, 0,
                         (struct sockaddr *)&addr, sizeof(addr));
    close(fd);

    if (rc < 0 && (errno == ECONNREFUSED || errno == ENOENT)) {
        spawn_daemon();
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) return 0; /* kein Argument -> nichts tun, kein Fehler */

    char home[PATH_MAX];
    get_home(home, sizeof(home));

    char state[PATH_MAX];
    state_dir(state, sizeof(state), home);
    ensure_dir(state);

    char evdir[PATH_MAX];
    events_dir(evdir, sizeof(evdir), state);
    ensure_dir(evdir);

    char master_path[PATH_MAX];
    snprintf(master_path, sizeof(master_path), "%s/sounds_enabled", state);

    const char *arg1 = argv[1];
    const char *event_arg = (argc > 2) ? argv[2] : NULL;

    if (strcmp(arg1, "--enable") == 0 || strcmp(arg1, "--disable") == 0) {
        int val = (strcmp(arg1, "--enable") == 0) ? 1 : 0;
        if (event_arg) {
            char p[PATH_MAX];
            snprintf(p, sizeof(p), "%s/%s", evdir, event_arg);
            write_flag(p, val);
        } else {
            write_flag(master_path, val);
        }
        puts(val ? "on" : "off");
    } else if (strcmp(arg1, "--toggle") == 0) {
        char p[PATH_MAX];
        const char *target = event_arg ? p : master_path;
        if (event_arg) snprintf(p, sizeof(p), "%s/%s", evdir, event_arg);
        int cur = flag_enabled(target);
        write_flag(target, !cur);
        puts(!cur ? "on" : "off");
    } else if (strcmp(arg1, "--status") == 0) {
        char p[PATH_MAX];
        const char *target = event_arg ? p : master_path;
        if (event_arg) snprintf(p, sizeof(p), "%s/%s", evdir, event_arg);
        puts(flag_enabled(target) ? "on" : "off");
    } else {
        send_play(arg1);
    }

    return 0;
}
