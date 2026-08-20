/*
 * FocusFixDaemon.c — Workaround für Hyprland-Bug #9326
 * (https://github.com/hyprwm/Hyprland/issues/9326, von den Maintainern
 * "closed as not planned").
 *
 * Problem: Sobald alle "echten" Fenster geschlossen sind, greift das
 * Desktop-Hintergrundfenster von xfdesktop den Fokus und gibt ihn nicht
 * mehr her. Eine danach neu geöffnete App bekommt dann KEINEN Fokus - man
 * muss erst mit der Maus klicken/bewegen, damit irgendwas wieder
 * fokussierbar ist. xfdesktop taucht dabei nie als regulärer Client in
 * "hyprctl clients" auf (Desktop-Fenstertyp), eine class-basierte
 * Windowrule kann es also gar nicht matchen.
 *
 * Fix: Wir hören auf Hyprlands Event-Socket (.socket2.sock) und feuern bei
 * jedem "openwindow"-Event den Lua-Dispatcher "hl.dsp.focus({ window =
 * "address:0x..." })" auf genau dieses neue Fenster (Hyprland >= 0.55,
 * Lua-Config-API). Im Normalfall (Fenster bekommt eh schon Fokus) ist das
 * ein No-Op. Nur im kaputten Fall (xfdesktop hält den Fokus fest) sorgt
 * es dafür, dass die neue App trotzdem fokussiert wird.
 *
 * WICHTIG: Der Befehl wird NICHT über das "hyprctl"-Kommandozeilentool
 * verschickt (per fork+exec), sondern direkt und roh über Hyprlands
 * Control-Socket (.socket.sock) - genau das, was hyprctl intern auch tut.
 * "dispatch <X>" wird vom Compositor 1:1 als "return hl.dispatch(<X>)"
 * ausgewertet; <X> muss also ein gültiger Lua-Ausdruck sein, der ein
 * HL.Dispatcher-Objekt liefert (siehe hl.dsp.* in hyprland.lua).
 *
 * Läuft dauerhaft im Hintergrund, verbindet sich bei Hyprland-Neustart
 * automatisch neu.
 *
 * Build:  gcc -O2 -o FocusFixDaemon FocusFixDaemon.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>

#define RECV_BUF   4096
#define LINE_BUF   8192
#define SOCK_PATH_MAX 512

/* Pfad zu Hyprlands Control-Socket (.socket.sock), einmal beim Start
 * ermittelt und danach für jeden "dispatch focuswindow"-Aufruf wieder-
 * verwendet. */
static char g_control_sock_path[SOCK_PATH_MAX];

/* Fensterklassen, die absichtlich OHNE Fokus aufgehen sollen (z.B.
 * Notification-Popups) - hier NICHT zwangsfokussieren. */
static const char *EXCLUDE_CLASSES[] = { "dunst", "xfdesktop", "vlc", "VLC", NULL };

static int class_excluded(const char *cls, size_t len) {
    for (int i = 0; EXCLUDE_CLASSES[i]; i++) {
        size_t elen = strlen(EXCLUDE_CLASSES[i]);
        if (elen == len && strncmp(cls, EXCLUDE_CLASSES[i], len) == 0)
            return 1;
    }
    return 0;
}

/* Baut den Pfad zu einem Hyprland-Socket (Event- oder Control-Socket) aus
 * XDG_RUNTIME_DIR und HYPRLAND_INSTANCE_SIGNATURE. sock_name ist z.B.
 * ".socket2.sock" (Events) oder ".socket.sock" (Control/Commands).
 * Gibt 0 bei Erfolg zurück. */
static int build_socket_path(char *out, size_t out_len, const char *sock_name) {
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    char runtime_buf[128];
    if (!runtime) {
        snprintf(runtime_buf, sizeof(runtime_buf), "/run/user/%d", getuid());
        runtime = runtime_buf;
    }
    const char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    if (!sig) {
        fprintf(stderr, "FocusFixDaemon: HYPRLAND_INSTANCE_SIGNATURE nicht "
                        "gesetzt - läuft das hier wirklich unter Hyprland?\n");
        return -1;
    }
    snprintf(out, out_len, "%s/hypr/%s/%s", runtime, sig, sock_name);
    return 0;
}

/* Schickt einen rohen Hyprland-IPC-Befehl über das Control-Socket
 * (.socket.sock) und loggt die Antwort. Das ist exakt das, was hyprctl
 * intern auch tut: verbinden, Befehlstext (ohne "hyprctl"-Präfix)
 * schreiben, Antwort lesen, Verbindung schließen. Kein fork/exec, keine
 * Abhängigkeit von irgendeinem "hyprctl"-Binary/-Wrapper in PATH. */
static void send_hypr_command(const char *cmd) {
    if (g_control_sock_path[0] == '\0') {
        fprintf(stderr, "FocusFixDaemon: kein Control-Socket-Pfad bekannt, "
                        "überspringe Befehl\n");
        return;
    }

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        fprintf(stderr, "FocusFixDaemon: socket() fehlgeschlagen: %s\n", strerror(errno));
        return;
    }

    struct sockaddr_un caddr;
    memset(&caddr, 0, sizeof(caddr));
    caddr.sun_family = AF_UNIX;
    if (strlen(g_control_sock_path) >= sizeof(caddr.sun_path)) {
        fprintf(stderr, "FocusFixDaemon: Control-Socket-Pfad zu lang: %s\n",
                g_control_sock_path);
        close(fd);
        return;
    }
    memcpy(caddr.sun_path, g_control_sock_path, strlen(g_control_sock_path) + 1);

    if (connect(fd, (struct sockaddr *)&caddr, sizeof(caddr)) != 0) {
        fprintf(stderr, "FocusFixDaemon: connect() auf Control-Socket "
                        "fehlgeschlagen: %s\n", strerror(errno));
        close(fd);
        return;
    }

    size_t cmd_len = strlen(cmd);
    ssize_t sent = send(fd, cmd, cmd_len, 0);
    if (sent < 0 || (size_t)sent != cmd_len) {
        fprintf(stderr, "FocusFixDaemon: send() auf Control-Socket "
                        "fehlgeschlagen: %s\n", strerror(errno));
        close(fd);
        return;
    }

    /* Antwort einsammeln (Hyprland schließt die Verbindung nach der
     * Antwort, daher reicht Lesen bis EOF). Bei "dispatch" ist die
     * Antwort normalerweise einfach "ok". */
    char reply[512];
    size_t total = 0;
    for (;;) {
        ssize_t n = recv(fd, reply + total, sizeof(reply) - 1 - total, 0);
        if (n <= 0) break;
        total += (size_t)n;
        if (total >= sizeof(reply) - 1) break;
    }
    reply[total] = '\0';
    close(fd);

    fprintf(stderr, "FocusFixDaemon: Befehl \"%s\" -> Antwort: \"%s\"\n", cmd, reply);
}

/* Baut den Dispatch-Befehl für "hl.dsp.focus({ window = "address:0x<addr>" })"
 * und schickt ihn über das Control-Socket. Seit Hyprland 0.55 läuft die
 * gesamte IPC-Kommandosprache über die Lua-API (hl.*), nicht mehr über
 * die klassische "hyprctl dispatch focuswindow address:..."-Syntax -
 * "dispatch <X>" wird vom Compositor 1:1 als "return hl.dispatch(<X>)"
 * ausgewertet, <X> muss also ein gültiger Lua-Ausdruck sein, der ein
 * HL.Dispatcher-Objekt liefert. Für Fensterauswahl per Adresse ist das
 * hl.dsp.focus({ window = "address:0x..." }) (address: ist einer der
 * "exakten Selektoren", siehe Dispatchers-Doku). */
static void focus_address(const char *addr, size_t addr_len) {
    char cmd[256];
    if (addr_len + 60 >= sizeof(cmd)) return; /* defensiv, sollte nie passieren */
    snprintf(cmd, sizeof(cmd),
             "dispatch hl.dsp.focus({ window = \"address:0x%.*s\" })",
             (int)addr_len, addr);

    fprintf(stderr, "FocusFixDaemon: fokussiere address:0x%.*s\n",
            (int)addr_len, addr);
    send_hypr_command(cmd);
}

/* Verarbeitet eine einzelne Event-Zeile. Format bei openwindow:
 *   openwindow>>ADDRESS,WORKSPACENAME,CLASS,TITLE
 * TITLE kann Kommas enthalten - uns interessieren nur die ersten drei
 * Felder, der Rest wird ignoriert. */
static void handle_line(const char *line, size_t len) {
    const char *prefix = "openwindow>>";
    size_t plen = strlen(prefix);
    if (len < plen || strncmp(line, prefix, plen) != 0) return;

    const char *payload = line + plen;
    size_t remaining = len - plen;

    const char *p1 = memchr(payload, ',', remaining);
    if (!p1) return;
    const char *addr = payload;
    size_t addr_len = (size_t)(p1 - payload);

    const char *after_ws = p1 + 1;
    size_t rem2 = remaining - (addr_len + 1);
    const char *p2 = memchr(after_ws, ',', rem2);
    if (!p2) return;
    /* Workspace-Feld liegt zwischen p1+1 und p2, wird nicht gebraucht */

    const char *cls = p2 + 1;
    size_t rem3 = rem2 - (size_t)(p2 - after_ws) - 1;
    const char *p3 = memchr(cls, ',', rem3);
    size_t cls_len = p3 ? (size_t)(p3 - cls) : rem3;

    if (addr_len == 0) return;

    if (class_excluded(cls, cls_len)) {
        fprintf(stderr, "FocusFixDaemon: openwindow class=%.*s -> excluded, skip\n",
                (int)cls_len, cls);
        return;
    }

    fprintf(stderr, "FocusFixDaemon: openwindow addr=%.*s class=%.*s -> fokussiere\n",
            (int)addr_len, addr, (int)cls_len, cls);
    focus_address(addr, addr_len);
}

static int run_once(void) {
    char sock_path[SOCK_PATH_MAX];
    if (build_socket_path(sock_path, sizeof(sock_path), ".socket2.sock") != 0)
        return -1; /* fataler Config-Fehler, kein Retry sinnvoll */

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return 1;

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    if (strlen(sock_path) >= sizeof(addr.sun_path)) {
        fprintf(stderr, "FocusFixDaemon: Socket-Pfad zu lang: %s\n", sock_path);
        close(fd);
        return -1;
    }
    memcpy(addr.sun_path, sock_path, strlen(sock_path) + 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return 1;
    }
    fprintf(stderr, "FocusFixDaemon: verbunden mit %s\n", sock_path);
    fflush(stderr);

    char recvbuf[RECV_BUF];
    char linebuf[LINE_BUF];
    size_t linelen = 0;

    for (;;) {
        ssize_t n = recv(fd, recvbuf, sizeof(recvbuf), 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (n == 0) break; /* Verbindung von Hyprland geschlossen */

        for (ssize_t i = 0; i < n; i++) {
            char c = recvbuf[i];
            if (c == '\n') {
                fprintf(stderr, "FocusFixDaemon: [raw] %.*s\n", (int)linelen, linebuf);
                fflush(stderr);
                handle_line(linebuf, linelen);
                linelen = 0;
            } else if (linelen + 1 < sizeof(linebuf)) {
                linebuf[linelen++] = c;
            } /* zu lange Zeilen (sollte nicht vorkommen) werden verworfen */
        }
    }

    close(fd);
    return 1; /* Verbindung verloren -> Retry */
}

int main(void) {
    setvbuf(stderr, NULL, _IONBF, 0);

    /* Control-Socket-Pfad einmalig ermitteln - ändert sich nicht zur
     * Laufzeit (HYPRLAND_INSTANCE_SIGNATURE bleibt für diesen Hyprland-
     * Prozess konstant, auch über Reconnects des Event-Sockets hinweg). */
    if (build_socket_path(g_control_sock_path, sizeof(g_control_sock_path),
                           ".socket.sock") != 0) {
        return 1; /* fataler Config-Fehler */
    }
    fprintf(stderr, "FocusFixDaemon: Control-Socket: %s\n", g_control_sock_path);

    for (;;) {
        int rc = run_once();
        if (rc < 0) return 1; /* fataler Fehler, kein Sinn in Retry */
        fprintf(stderr, "FocusFixDaemon: Verbindung verloren/fehlgeschlagen, "
                        "neuer Versuch in 2s...\n");
        fflush(stderr);
        sleep(2);
    }
}
