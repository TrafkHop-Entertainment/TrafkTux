/*
 * ScreenRotationDaemon.c — TrafkTux Auto-Rotate Daemon
 *
 * Hört auf net.hadess.SensorProxy (iio-sensor-proxy) via DBus SystemBus
 * PropertiesChanged und dreht den internen Laptop-Monitor + alle
 * zugehörigen Touch-/Pen-Input-Devices passend mit.
 *
 * Generisch: kein Monitor- oder Device-Name ist hardcoded. Der interne
 * Monitor wird über "hyprctl monitors -j" anhand des Feldes "focused"/
 * Beschreibung ermittelt — konkret: der Monitor, dessen Name mit einem
 * bekannten internen Panel-Präfix beginnt (eDP-, LVDS-, DSI-), analog
 * zu dem, was iio-sensor-proxy selbst als "ist das ein Laptop-Panel"
 * behandelt. Touch-/Pen-Devices werden über "hyprctl devices -j"
 * vollständig ausgelesen (touch[] und tablets[]) — ALLE davon werden
 * gedreht, nicht nur das erste, da manche Geräte mehrere Touch-Digitizer
 * haben (Screen + separates Touchpad-als-Touch-Device o.ä.).
 *
 * Performance-Designentscheidung (siehe Chat-Verlauf):
 *   - Device-Discovery (welcher Monitor ist intern, welche Touch-Devices
 *     existieren) läuft NUR EINMAL beim Start und wird gecacht.
 *   - Re-Discovery nur beim Empfang eines Hyprland "monitoraddedv2" /
 *     "monitorremoved" Events über den socket2 Event-Stream (Hotplug).
 *   - Bei jedem tatsächlichen Orientierungswechsel (selten, DBus-Signal,
 *     kein Polling) wird NUR noch der gecachte transform-Wert über den
 *     Hyprland IPC-Socket geschrieben — kein erneutes fork()/exec(),
 *     kein erneutes Parsen der vollen Geräteliste.
 *
 * Control-Socket (Lock-Feature):
 *   $XDG_RUNTIME_DIR/screen-rotation.sock — Unix-Socket, text-basiert,
 *   ein Kommando pro Verbindung. Für Widgets/Scripts gedacht.
 *   Kommandos: "lock" | "unlock" | "toggle" | "status"
 *              "list"                        -> alle Monitore + transform
 *              "set <monitor> <transform>"    -> manuelles Rotate (0-7),
 *                                                 fuer JEDEN Monitor, auch
 *                                                 externe Pivot-Displays
 *                                                 ohne eigenen Sensor
 *   Antwort:   "locked" | "unlocked" | Monitorliste | "ok" | "error: ..."
 *   Bei "lock" wird der zuletzt gesetzte transform eingefroren, DBus-
 *   Events kommen weiter rein und werden gecacht (pending_transform),
 *   aber NICHT angewendet, bis "unlock"/"toggle" kommt — dann wird der
 *   zuletzt bekannte Sensor-Wert sofort nachgeholt.
 *
 * Build (Arch: dbus-Paket bringt bereits Header + .so mit, kein
 * separates "-dev"-Paket wie bei Debian/Ubuntu nötig):
 *   sudo pacman -S --needed base-devel dbus
 *   gcc -O2 -o ScreenRotationDaemon ScreenRotationDaemon.c \
 *       $(pkg-config --cflags --libs dbus-1) -lpthread
 *
 * Laufzeit-Abhängigkeiten: iio-sensor-proxy (DBus SystemBus Service),
 * Hyprland (liest $HYPRLAND_INSTANCE_SIGNATURE / $XDG_RUNTIME_DIR),
 * libdbus-1.
 */

#define _GNU_SOURCE
#include <dbus/dbus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <errno.h>
#include <ctype.h>
#include <signal.h>
#include <pthread.h>
#include <sys/stat.h>

#define MAX_DEVICES   32
#define NAME_LEN      128
#define BUF_LEN       65536
#define LOG(...)      do { fprintf(stderr, "[ScreenRotationDaemon] " __VA_ARGS__); fprintf(stderr, "\n"); } while (0)

/* ------------------------------------------------------------------ */
/* Zustand: gecachte Geräte-Discovery                                  */
/* ------------------------------------------------------------------ */

typedef struct {
    char monitor_name[NAME_LEN];          /* z.B. "eDP-1" */
    int  monitor_found;

    /* Gecacht aus "j/monitors" beim letzten discover_devices() - noetig,
     * weil hl.monitor() (siehe hypr_eval_monitor()) alle Felder explizit
     * braucht, nicht nur transform. Wird wie monitor_name nur bei Start/
     * Hotplug neu ermittelt, nicht bei jedem Orientierungswechsel. */
    char   monitor_mode[NAME_LEN];        /* z.B. "1920x1200@60.00" */
    char   monitor_position[NAME_LEN];    /* z.B. "0x0" */
    double monitor_scale;                 /* z.B. 1.07 */

    char touch_names[MAX_DEVICES][NAME_LEN];
    int  touch_count;

    int  last_transform;                  /* -1 = noch nie gesetzt */

    int  locked;                          /* 1 = Rotation gesperrt */
    int  pending_transform;               /* letzter Sensor-Wert, auch waehrend locked */
} rotation_state_t;

static rotation_state_t g_state;
static pthread_mutex_t  g_state_mutex = PTHREAD_MUTEX_INITIALIZER;

/* Bekannte Präfixe interner Laptop-Panel-Outputs. eDP = klassisches
 * internes eDP-Panel, LVDS = ältere Laptops, DVI-I/DSI = seltener,
 * manche embedded/Convertible-Panels. Alles NICHT hier drin (HDMI-,
 * DP-, USB-C-Ausgänge) gilt als externer Monitor und wird ignoriert. */
static const char *INTERNAL_PANEL_PREFIXES[] = { "eDP-", "LVDS-", "DSI-", NULL };

/* Forward-Declarations: die vollen Definitionen kommen weiter unten
 * (JSON-Objekt-Helfer), werden aber schon in discover_devices() und
 * handle_set_command() gebraucht. */
static int split_json_objects(const char *json, char *out[], int max);
static int extract_int_field(const char *json_obj, const char *field);
static int extract_float_field(const char *json_obj, const char *field, double *out);
static int extract_name_field(const char *json_obj, char *out, size_t out_len);

/* ------------------------------------------------------------------ */
/* Hyprland IPC (Unix Socket, .socket.sock) — Requests                 */
/* ------------------------------------------------------------------ */

static int hypr_socket_path(char *out, size_t out_len, const char *suffix) {
    const char *xdg = getenv("XDG_RUNTIME_DIR");
    const char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    if (!xdg || !sig) {
        LOG("XDG_RUNTIME_DIR oder HYPRLAND_INSTANCE_SIGNATURE nicht gesetzt "
            "- läuft der Daemon in der richtigen Session?");
        return -1;
    }
    snprintf(out, out_len, "%s/hypr/%s/%s", xdg, sig, suffix);
    return 0;
}

/* Führt einen einzelnen Hyprland-IPC-Request aus (z.B. "j/monitors") und
 * gibt die Antwort in out zurück. Nutzt einen frischen Connect pro Call -
 * das ist bei Hyprlands .socket.sock so vorgesehen (kurzlebige Requests,
 * kein persistenter Request-Kanal). Für socket2 (Events) siehe unten,
 * der bleibt dauerhaft offen. */
static ssize_t hypr_request(const char *request, char *out, size_t out_cap) {
    char path[512];
    if (hypr_socket_path(path, sizeof(path), ".socket.sock") != 0) return -1;

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { LOG("socket() fehlgeschlagen: %s", strerror(errno)); return -1; }

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        LOG("connect() an %s fehlgeschlagen: %s", path, strerror(errno));
        close(fd);
        return -1;
    }

    if (write(fd, request, strlen(request)) < 0) {
        LOG("write() an Hyprland-Socket fehlgeschlagen: %s", strerror(errno));
        close(fd);
        return -1;
    }

    /* WICHTIG: Schreibseite explizit herunterfahren, bevor wir lesen.
     * "hyprctl" (und socat mit stdin-EOF, siehe Chat-Test) tun das
     * implizit - unser eigener Client bisher nicht. Ohne dieses Signal
     * scheint Hyprlands "eval"-Handler die Anfrage nie als vollstaendig
     * abgeschlossen zu betrachten: er antwortet zwar irgendwann brav
     * mit "ok" (kein harter Fehler, daher bisher unbemerkt), fuehrt den
     * Lua-Ausdruck dabei aber nie wirklich aus - exakt das beobachtete
     * "loggt Erfolg, dreht aber nix"-Symptom. Kurze Requests wie
     * "j/monitors" oder "keyword ..." haben das ueberlebt, "eval" nicht.
     * shutdown() statt close(), weil wir die Leseseite noch offen
     * brauchen, um die Antwort abzuholen. */
    shutdown(fd, SHUT_WR);

    size_t total = 0;
    ssize_t n;
    while (total < out_cap - 1 && (n = read(fd, out + total, out_cap - 1 - total)) > 0) {
        total += (size_t)n;
    }
    out[total] = '\0';
    close(fd);
    return (ssize_t)total;
}

/* Schickt einen "dispatch"-artigen keyword-Befehl fire-and-forget.
 * Beispiel: hypr_keyword("monitor", "eDP-1,transform,1")
 *
 * WICHTIG (nur noch fuer Nicht-Monitor-Keywords wie device[...]:transform
 * relevant): das "monitor"-Keyword selbst wird NICHT MEHR ueber diese
 * Funktion gesetzt, siehe hypr_eval_monitor() unten - Grund steht dort. */
static void hypr_keyword(const char *key, const char *value) {
    char req[512];
    char resp[256];
    /* WICHTIG: KEIN führendes "/" hier - das ist nur Teil des "j/"-
     * JSON-Flags (siehe hypr_request("j/monitors", ...) weiter oben),
     * nicht ein generelles Präfix für Kommandos. "/keyword ..." wird
     * von Hyprland als unbekanntes Kommando ignoriert (kein Fehler,
     * aber auch kein Effekt) - genau das hat Auto-Rotation und
     * manuelles "set" bisher wirkungslos gemacht. */
    snprintf(req, sizeof(req), "keyword %s %s", key, value);
    ssize_t n = hypr_request(req, resp, sizeof(resp));
    /* Antwort mitloggen statt wegzuwerfen - reine Diagnose, kein
     * Verhaltenswechsel. Falls Touch-/Tablet-Rotation je nicht sichtbar
     * greift, steht die Ursache dann wenigstens im Journal statt im
     * Dunkeln (das war beim monitor-Keyword-Bug genau das Problem). */
    if (n > 0) LOG("keyword %s -> Antwort: %s", key, resp);
}

/* Schickt einen "eval"-Befehl (Lua-Runtime-API dieses Hyprland-Forks) und
 * gibt die ECHTE Antwort zurueck, statt sie wie hypr_keyword() wegzuwerfen.
 * Wird fuer alles benutzt, wo wir wissen wollen/muessen, ob Hyprland das
 * Kommando tatsaechlich angenommen hat. */
static ssize_t hypr_eval(const char *lua_expr, char *out, size_t out_cap) {
    char req[640];
    snprintf(req, sizeof(req), "eval %s", lua_expr);
    return hypr_request(req, out, out_cap);
}

/* Setzt den Transform eines Monitors ueber hl.monitor().
 *
 * Der naheliegende Weg waere "keyword monitor NAME,transform,N" gewesen
 * (siehe hypr_keyword() oben) - genau der wurde zuerst als kaputt
 * identifiziert (fuehrendes "/", laengst gefixt), ist aber TROTZDEM falsch:
 * Hyprlands "monitor"-Keyword erwartet die Felder als VOLLSTAENDIGE,
 * positionelle Liste (Aufloesung, Position, Scale, ..., dann transform).
 * "NAME,transform,N" allein liefert an Stelle 2 (wo "Aufloesung" erwartet
 * wird) das Wort "transform" - Hyprland verwirft das Kommando dann
 * stillschweigend (kein Fehler, aber auch kein Effekt). Live gegen
 * Hardware verifiziert: sowohl Auto-Rotate als auch manuelles "set" hatten
 * dadurch NIE einen sichtbaren Effekt, trotz "ok"-Antwort vom Daemon.
 *
 * Stattdessen die Lua-Runtime-API dieses Forks (hl.monitor({...}), siehe
 * hyprland.lua Zeile ~17) mit allen Feldern EXPLIZIT benannt - das
 * funktioniert nachweislich (per hyprctl eval manuell getestet und
 * bestaetigt: Bildschirm dreht sich sichtbar). */
static ssize_t hypr_eval_monitor(const char *name, const char *mode,
                                  const char *position, double scale,
                                  int transform, char *out, size_t out_cap) {
    char expr[512];
    snprintf(expr, sizeof(expr),
        "hl.monitor({ output = \"%s\", mode = \"%s\", position = \"%s\", "
        "scale = %.3f, transform = %d })",
        name, mode, position, scale, transform);
    return hypr_eval(expr, out, out_cap);
}

/* ------------------------------------------------------------------ */
/* Sehr kleiner, zweckgebundener JSON-Scanner                          */
/* (kein vollwertiger Parser nötig - wir suchen nur "name": "..." und   */
/*  "description" Felder innerhalb bekannter Arrays)                   */
/* ------------------------------------------------------------------ */

/* Extrahiert alle Werte von "name":"..." Vorkommen aus json in out[]. */
static int extract_all_names(const char *json, char out[][NAME_LEN], int max_out) {
    int count = 0;
    const char *p = json;
    const char *key = "\"name\"";

    while ((p = strstr(p, key)) != NULL && count < max_out) {
        p += strlen(key);
        p = strchr(p, ':');
        if (!p) break;
        p++;
        while (*p == ' ') p++;
        if (*p != '"') { continue; }
        p++;
        const char *end = strchr(p, '"');
        if (!end) break;

        size_t len = (size_t)(end - p);
        if (len >= NAME_LEN) len = NAME_LEN - 1;
        strncpy(out[count], p, len);
        out[count][len] = '\0';
        count++;
        p = end + 1;
    }
    return count;
}

static int starts_with_any(const char *s, const char **prefixes) {
    for (int i = 0; prefixes[i] != NULL; i++) {
        if (strncmp(s, prefixes[i], strlen(prefixes[i])) == 0) return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Discovery: einmalig (bzw. nach Hotplug) den internen Monitor und    */
/* alle Touch-/Tablet-Devices ermitteln und in g_state cachen.         */
/* ------------------------------------------------------------------ */

static void discover_devices(void) {
    char resp[BUF_LEN];

    pthread_mutex_lock(&g_state_mutex);

    g_state.monitor_found = 0;
    g_state.touch_count = 0;

    /* --- Monitore ---
     * Wir brauchen hier PRO Monitor-Objekt width/height/refreshRate/x/y/
     * scale (nicht nur den Namen wie frueher), weil hl.monitor() beim
     * Rotieren alle Felder explizit braucht (siehe hypr_eval_monitor()).
     * Deshalb jetzt ueber die einzelnen JSON-Objekte statt ueber eine
     * globale Namensliste. */
    if (hypr_request("j/monitors", resp, sizeof(resp)) > 0) {
        char *objects[MAX_DEVICES];
        int n = split_json_objects(resp, objects, MAX_DEVICES);

        for (int i = 0; i < n; i++) {
            char name[NAME_LEN];
            if (!g_state.monitor_found &&
                extract_name_field(objects[i], name, sizeof(name)) == 0 &&
                starts_with_any(name, INTERNAL_PANEL_PREFIXES)) {

                strncpy(g_state.monitor_name, name, NAME_LEN - 1);
                g_state.monitor_found = 1;

                int width  = extract_int_field(objects[i], "width");
                int height = extract_int_field(objects[i], "height");
                double refresh = 60.0;
                extract_float_field(objects[i], "refreshRate", &refresh);
                int x = extract_int_field(objects[i], "x");
                int y = extract_int_field(objects[i], "y");
                double scale = 1.0;
                extract_float_field(objects[i], "scale", &scale);

                if (width > 0 && height > 0) {
                    snprintf(g_state.monitor_mode, NAME_LEN, "%dx%d@%.2f", width, height, refresh);
                } else {
                    g_state.monitor_mode[0] = '\0';
                    LOG("WARNUNG: konnte width/height fuer %s nicht aus j/monitors lesen", name);
                }
                snprintf(g_state.monitor_position, NAME_LEN, "%dx%d", x, y);
                g_state.monitor_scale = scale;
            }
            free(objects[i]);
        }
    }

    if (!g_state.monitor_found) {
        LOG("WARNUNG: kein internes Panel (eDP-/LVDS-/DSI-*) gefunden - "
            "Monitor-Rotation wird übersprungen, bis eines erscheint.");
    } else {
        LOG("interner Monitor erkannt: %s", g_state.monitor_name);
    }

    /* --- Touch- und Tablet-Devices ---
     * hyprctl devices -j hat getrennte Arrays "touch" und "tablets".
     * Wir extrahieren name-Felder aus der GESAMTEN Antwort und filtern
     * grob per Heuristik nichts weiter raus, weil "touch" bereits nur
     * Touch-Digitizer enthält (keine Maus/Tastatur-Namen) - anders als
     * bei "mice"/"keyboards" gibt es hier kein Namens-Rauschen, das wir
     * ausschließen müssten. Tablets (Stift-Digitizer, oft dasselbe
     * Panel wie der Touchscreen bei Convertibles) werden bewusst
     * mitgenommen. */
    if (hypr_request("j/devices", resp, sizeof(resp)) > 0) {
        char *touch_section = strstr(resp, "\"touch\"");
        char *tablets_section = strstr(resp, "\"tablets\"");
        char *keyboards_section = strstr(resp, "\"keyboards\"");

        /* Grenzen: touch-Array endet dort wo tablets (oder das nächste
         * bekannte Feld) beginnt - reicht für unseren Zweck, da wir nur
         * "name" Vorkommen INNERHALB dieses Bereichs zählen wollen. */
        if (touch_section) {
            char *section_end = tablets_section ? tablets_section
                               : keyboards_section ? keyboards_section
                               : touch_section + strlen(touch_section);
            size_t section_len = (size_t)(section_end - touch_section);
            char *section_copy = malloc(section_len + 1);
            if (section_copy) {
                memcpy(section_copy, touch_section, section_len);
                section_copy[section_len] = '\0';

                char names[MAX_DEVICES][NAME_LEN];
                int n = extract_all_names(section_copy, names,
                                           MAX_DEVICES - g_state.touch_count);
                for (int i = 0; i < n && g_state.touch_count < MAX_DEVICES; i++) {
                    strncpy(g_state.touch_names[g_state.touch_count], names[i], NAME_LEN - 1);
                    g_state.touch_count++;
                }
                free(section_copy);
            }
        }

        if (tablets_section) {
            char names[MAX_DEVICES][NAME_LEN];
            int n = extract_all_names(tablets_section, names,
                                       MAX_DEVICES - g_state.touch_count);
            for (int i = 0; i < n && g_state.touch_count < MAX_DEVICES; i++) {
                strncpy(g_state.touch_names[g_state.touch_count], names[i], NAME_LEN - 1);
                g_state.touch_count++;
            }
        }
    }

    LOG("%d Touch-/Tablet-Device(s) gefunden:", g_state.touch_count);
    for (int i = 0; i < g_state.touch_count; i++) {
        LOG("  - %s", g_state.touch_names[i]);
    }

    g_state.last_transform = -1; /* nach Rediscovery immer neu anwenden */

    pthread_mutex_unlock(&g_state_mutex);
}

/* ------------------------------------------------------------------ */
/* Transform anwenden — nur noch billige IPC-Writes, keine Discovery   */
/* ------------------------------------------------------------------ */

/* Schreibt transform tatsaechlich via hyprctl-Socket. Erwartet
 * g_state_mutex bereits gehalten. */
static void apply_transform_locked(int transform) {
    if (transform == g_state.last_transform) return;

    LOG("wechsle transform -> %d", transform);

    if (g_state.monitor_found) {
        if (g_state.monitor_mode[0] != '\0') {
            char resp[256];
            ssize_t n = hypr_eval_monitor(g_state.monitor_name, g_state.monitor_mode,
                                           g_state.monitor_position, g_state.monitor_scale,
                                           transform, resp, sizeof(resp));
            LOG("hl.monitor(%s, transform=%d) -> %s", g_state.monitor_name, transform,
                n > 0 ? resp : "(keine Antwort)");
        } else {
            LOG("WARNUNG: kein gecachter Mode/Position/Scale fuer %s - "
                "transform wird uebersprungen (Discovery-Problem, siehe oben)",
                g_state.monitor_name);
        }
    }

    for (int i = 0; i < g_state.touch_count; i++) {
        char key[NAME_LEN + 32];
        char value[16];
        snprintf(key, sizeof(key), "device[%s]:transform", g_state.touch_names[i]);
        snprintf(value, sizeof(value), "%d", transform);
        hypr_keyword(key, value);
    }

    g_state.last_transform = transform;
}

/* Einstiegspunkt fuer neue Sensor-Orientierung. Merkt sich den Wert
 * immer (pending_transform), wendet ihn aber nur an, wenn nicht
 * gesperrt. */
static void set_orientation(int transform) {
    pthread_mutex_lock(&g_state_mutex);
    g_state.pending_transform = transform;
    if (!g_state.locked) {
        apply_transform_locked(transform);
    } else {
        LOG("Rotation gesperrt, Sensor-Wert %d gemerkt, nicht angewendet", transform);
    }
    pthread_mutex_unlock(&g_state_mutex);
}

/* Mapping iio-sensor-proxy AccelerometerOrientation -> Hyprland transform.
 * transform: 0=normal, 1=90° CW, 2=180°, 3=270° CW.
 *
 * WICHTIG: "right-up"/"left-up" beschreiben, welche KANTE des Geräts
 * jetzt oben ist - nicht die Drehrichtung selbst. "left-up" (linke
 * Kante zeigt nach oben) entsteht durch eine 90°-Drehung IM Uhrzeiger-
 * sinn -> transform 1. "right-up" entsteht durch eine 90°-Drehung
 * GEGEN den Uhrzeigersinn -> transform 3. Vorher war das genau
 * vertauscht (right-up->1, left-up->3) - deshalb ist die Rotation in
 * die falsche Richtung gelaufen ("links und rechts vertauscht").
 * Konvention wie bei GNOME/mutter (orientation_to_transform()). */
static int orientation_to_transform(const char *orientation) {
    if (strcmp(orientation, "normal")    == 0) return 0;
    if (strcmp(orientation, "left-up")   == 0) return 1;
    if (strcmp(orientation, "bottom-up") == 0) return 2;
    if (strcmp(orientation, "right-up")  == 0) return 3;
    return -1; /* unbekannt, z.B. "undefined" beim Start */
}

/* ------------------------------------------------------------------ */
/* DBus: net.hadess.SensorProxy PropertiesChanged                      */
/* ------------------------------------------------------------------ */

static DBusHandlerResult on_dbus_signal(DBusConnection *conn, DBusMessage *msg, void *user_data) {
    (void)conn; (void)user_data;

    if (!dbus_message_is_signal(msg, "org.freedesktop.DBus.Properties", "PropertiesChanged"))
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;

    DBusMessageIter args, dict;
    if (!dbus_message_iter_init(msg, &args)) return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;

    const char *iface_name;
    dbus_message_iter_get_basic(&args, &iface_name);
    if (strcmp(iface_name, "net.hadess.SensorProxy") != 0)
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;

    if (!dbus_message_iter_next(&args)) return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    dbus_message_iter_recurse(&args, &dict);

    while (dbus_message_iter_get_arg_type(&dict) == DBUS_TYPE_DICT_ENTRY) {
        DBusMessageIter entry, variant;
        dbus_message_iter_recurse(&dict, &entry);

        const char *prop_name;
        dbus_message_iter_get_basic(&entry, &prop_name);

        if (strcmp(prop_name, "AccelerometerOrientation") == 0) {
            dbus_message_iter_next(&entry);
            dbus_message_iter_recurse(&entry, &variant);
            const char *orientation;
            dbus_message_iter_get_basic(&variant, &orientation);

            int transform = orientation_to_transform(orientation);
            if (transform >= 0) {
                set_orientation(transform);
            } else {
                LOG("unbekannte Orientierung ignoriert: %s", orientation);
            }
        }

        dbus_message_iter_next(&dict);
    }

    return DBUS_HANDLER_RESULT_HANDLED;
}

static DBusConnection *g_dbus = NULL;

static void claim_accelerometer(DBusConnection *conn) {
    DBusMessage *msg = dbus_message_new_method_call(
        "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
        "net.hadess.SensorProxy", "ClaimAccelerometer");
    DBusError err; dbus_error_init(&err);
    DBusMessage *reply = dbus_connection_send_with_reply_and_block(conn, msg, 2000, &err);
    if (dbus_error_is_set(&err)) {
        LOG("ClaimAccelerometer fehlgeschlagen: %s", err.message);
        dbus_error_free(&err);
    }
    if (reply) dbus_message_unref(reply);
    dbus_message_unref(msg);
}

static void release_accelerometer(DBusConnection *conn) {
    DBusMessage *msg = dbus_message_new_method_call(
        "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
        "net.hadess.SensorProxy", "ReleaseAccelerometer");
    DBusMessage *reply = dbus_connection_send_with_reply_and_block(conn, msg, 2000, NULL);
    if (reply) dbus_message_unref(reply);
    dbus_message_unref(msg);
}

/* Initialen Orientierungswert direkt beim Start abfragen, statt auf die
 * erste Drehung zu warten. */
static void apply_initial_orientation(DBusConnection *conn) {
    DBusMessage *msg = dbus_message_new_method_call(
        "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
        "org.freedesktop.DBus.Properties", "Get");
    const char *iface = "net.hadess.SensorProxy";
    const char *prop  = "AccelerometerOrientation";
    dbus_message_append_args(msg, DBUS_TYPE_STRING, &iface,
                                   DBUS_TYPE_STRING, &prop, DBUS_TYPE_INVALID);

    DBusError err; dbus_error_init(&err);
    DBusMessage *reply = dbus_connection_send_with_reply_and_block(conn, msg, 2000, &err);
    dbus_message_unref(msg);

    if (!reply) {
        if (dbus_error_is_set(&err)) { LOG("initiale Orientierung: %s", err.message); dbus_error_free(&err); }
        return;
    }

    DBusMessageIter iter, variant;
    dbus_message_iter_init(reply, &iter);
    dbus_message_iter_recurse(&iter, &variant);
    const char *orientation;
    dbus_message_iter_get_basic(&variant, &orientation);

    int transform = orientation_to_transform(orientation);
    if (transform >= 0) set_orientation(transform);

    dbus_message_unref(reply);
}

/* ------------------------------------------------------------------ */
/* Control-Socket: lock/unlock/toggle/status fuer Widgets/Scripts      */
/* ------------------------------------------------------------------ */

static char g_control_sock_path[512];
static int  g_control_fd = -1;

static int control_socket_path(char *out, size_t out_len) {
    const char *xdg = getenv("XDG_RUNTIME_DIR");
    if (!xdg) { LOG("XDG_RUNTIME_DIR nicht gesetzt, kein Control-Socket"); return -1; }
    snprintf(out, out_len, "%s/screen-rotation.sock", xdg);
    return 0;
}

/* Zerlegt ein flaches JSON-Array von Objekten (wie "hyprctl monitors -j"
 * liefert) in die einzelnen Objekt-Strings. Depth-basiert, funktioniert
 * unabhängig davon wie viele Monitore/Felder enthalten sind. */
static int split_json_objects(const char *json, char *out[], int max) {
    int count = 0;
    int depth = 0;
    const char *obj_start = NULL;

    for (const char *p = json; *p && count < max; p++) {
        if (*p == '{') {
            if (depth == 0) obj_start = p;
            depth++;
        } else if (*p == '}') {
            depth--;
            if (depth == 0 && obj_start) {
                size_t len = (size_t)(p - obj_start + 1);
                out[count] = malloc(len + 1);
                if (out[count]) {
                    memcpy(out[count], obj_start, len);
                    out[count][len] = '\0';
                    count++;
                }
                obj_start = NULL;
            }
        }
    }
    return count;
}

/* Extrahiert "field":<int> aus einem einzelnen JSON-Objekt-String.
 * Gibt -1 zurueck wenn nicht gefunden. */
static int extract_int_field(const char *json_obj, const char *field) {
    char key[64];
    snprintf(key, sizeof(key), "\"%s\"", field);
    const char *p = strstr(json_obj, key);
    if (!p) return -1;
    p = strchr(p + strlen(key), ':');
    if (!p) return -1;
    p++;
    while (*p == ' ') p++;
    return atoi(p);
}

/* Extrahiert "field":<float> aus einem einzelnen JSON-Objekt-String, z.B.
 * "scale":1.070000 oder "refreshRate":60.000004. Gibt -1 zurueck wenn
 * nicht gefunden, *out bleibt dann unveraendert (Caller setzt vorher
 * einen sinnvollen Default). */
static int extract_float_field(const char *json_obj, const char *field, double *out) {
    char key[64];
    snprintf(key, sizeof(key), "\"%s\"", field);
    const char *p = strstr(json_obj, key);
    if (!p) return -1;
    p = strchr(p + strlen(key), ':');
    if (!p) return -1;
    p++;
    while (*p == ' ') p++;
    *out = atof(p);
    return 0;
}

/* Extrahiert "name":"..." aus einem einzelnen JSON-Objekt-String. */
static int extract_name_field(const char *json_obj, char *out, size_t out_len) {
    const char *p = strstr(json_obj, "\"name\"");
    if (!p) return -1;
    p = strchr(p, ':');
    if (!p) return -1;
    p++;
    while (*p == ' ') p++;
    if (*p != '"') return -1;
    p++;
    const char *end = strchr(p, '"');
    if (!end) return -1;
    size_t len = (size_t)(end - p);
    if (len >= out_len) len = out_len - 1;
    strncpy(out, p, len);
    out[len] = '\0';
    return 0;
}

/* "list" Kommando: alle aktuell verbundenen Monitore + deren transform,
 * unabhaengig davon ob intern/extern - fuer manuelles Multi-Monitor-Rotate. */
static void write_monitor_list(int client_fd) {
    char resp[BUF_LEN];
    if (hypr_request("j/monitors", resp, sizeof(resp)) <= 0) {
        const char *err = "error: hyprctl nicht erreichbar\n";
        if (write(client_fd, err, strlen(err)) < 0) { /* nichts zu tun */ }
        return;
    }

    char *objects[MAX_DEVICES];
    int n = split_json_objects(resp, objects, MAX_DEVICES);

    for (int i = 0; i < n; i++) {
        char name[NAME_LEN];
        if (extract_name_field(objects[i], name, sizeof(name)) == 0) {
            int transform = extract_int_field(objects[i], "transform");
            char line[NAME_LEN + 16];
            int len = snprintf(line, sizeof(line), "%s %d\n", name, transform);
            if (write(client_fd, line, (size_t)len) < 0) { /* Client weg, egal */ }
        }
        free(objects[i]);
    }
}

/* Fragt Mode/Position/Scale eines BELIEBIGEN Monitors frisch ab (nicht
 * gecacht) - fuer "set" ueber den Control-Socket, das auch externe Pivot-
 * Monitore treffen kann, die discover_devices() nie gecacht hat (die
 * cacht nur den internen Panel-Monitor). Ein hyprctl-Roundtrip pro
 * manuellem Aufruf ist hier voellig unkritisch, das ist kein Hot-Path. */
static int query_monitor_geometry(const char *name, char *mode_out, size_t mode_len,
                                   char *pos_out, size_t pos_len, double *scale_out) {
    char resp[BUF_LEN];
    if (hypr_request("j/monitors", resp, sizeof(resp)) <= 0) return -1;

    char *objects[MAX_DEVICES];
    int n = split_json_objects(resp, objects, MAX_DEVICES);
    int found = -1;

    for (int i = 0; i < n; i++) {
        char obj_name[NAME_LEN];
        if (found != 0 &&
            extract_name_field(objects[i], obj_name, sizeof(obj_name)) == 0 &&
            strcmp(obj_name, name) == 0) {

            int width  = extract_int_field(objects[i], "width");
            int height = extract_int_field(objects[i], "height");
            double refresh = 60.0;
            extract_float_field(objects[i], "refreshRate", &refresh);
            int x = extract_int_field(objects[i], "x");
            int y = extract_int_field(objects[i], "y");
            double scale = 1.0;
            extract_float_field(objects[i], "scale", &scale);

            if (width > 0 && height > 0) {
                snprintf(mode_out, mode_len, "%dx%d@%.2f", width, height, refresh);
                snprintf(pos_out, pos_len, "%dx%d", x, y);
                *scale_out = scale;
                found = 0;
            }
        }
        free(objects[i]);
    }
    return found;
}

/* "set NAME TRANSFORM" Kommando: rotiert EINEN beliebigen Monitor direkt,
 * unabhaengig vom Auto-Rotate-Cache. Kein Touch-Mapping (externe Pivot-
 * Monitore haben ueblicherweise keinen zugehoerigen Touchscreen). Falls
 * NAME zufaellig der intern automatisch rotierte Monitor ist, ueberschreibt
 * der naechste Sensor-Event diesen manuellen Wert wieder - das ist
 * beabsichtigtes Verhalten, kein Bug. */
static void handle_set_command(const char *name, const char *transform_str, int client_fd) {
    char *endptr;
    long transform = strtol(transform_str, &endptr, 10);
    const char *reply;

    if (*transform_str == '\0' || *endptr != '\0' || transform < 0 || transform > 7) {
        reply = "error: transform muss 0-7 sein\n";
        if (write(client_fd, reply, strlen(reply)) < 0) { /* egal */ }
        return;
    }

    char mode[NAME_LEN], position[NAME_LEN];
    double scale = 1.0;
    if (query_monitor_geometry(name, mode, sizeof(mode), position, sizeof(position), &scale) != 0) {
        char err[NAME_LEN + 64];
        int len = snprintf(err, sizeof(err), "error: Monitor '%s' nicht gefunden\n", name);
        if (write(client_fd, err, (size_t)len) < 0) { /* egal */ }
        return;
    }

    char hypr_resp[256];
    ssize_t rn = hypr_eval_monitor(name, mode, position, scale, (int)transform,
                                    hypr_resp, sizeof(hypr_resp));
    LOG("manuelles Rotate via Control-Socket: %s -> %ld (Hyprland-Antwort: %s)",
        name, transform, rn > 0 ? hypr_resp : "(keine Antwort)");

    /* WICHTIG: hier vorher IMMER "ok\n" geantwortet, egal was Hyprland
     * wirklich zurueckgegeben hat (auch wenn's ein Fehler war) - das war
     * die "der Daemon luegt dich an"-Luecke. Jetzt geht die echte
     * Hyprland-Antwort an den Client raus. */
    if (rn > 0 && hypr_resp[0] != '\0') {
        char out[300];
        int len = snprintf(out, sizeof(out), "%s\n", hypr_resp);
        if (write(client_fd, out, (size_t)len) < 0) { /* egal */ }
    } else {
        reply = "error: keine Antwort von Hyprland erhalten\n";
        if (write(client_fd, reply, strlen(reply)) < 0) { /* egal */ }
    }
}

static void handle_control_command(int client_fd) {
    char buf[128];
    ssize_t n = read(client_fd, buf, sizeof(buf) - 1);
    if (n <= 0) return;
    buf[n] = '\0';

    for (ssize_t i = n - 1; i >= 0 && (buf[i] == '\n' || buf[i] == '\r' || buf[i] == ' '); i--) buf[i] = '\0';

    /* Tokenisieren: cmd [arg1 [arg2]] */
    char *cmd  = strtok(buf, " ");
    char *arg1 = strtok(NULL, " ");
    char *arg2 = strtok(NULL, " ");

    if (!cmd) return;

    if (strcmp(cmd, "list") == 0) {
        write_monitor_list(client_fd);
        return;
    }

    if (strcmp(cmd, "set") == 0) {
        if (!arg1 || !arg2) {
            const char *err = "error: usage: set <monitor> <transform 0-7>\n";
            if (write(client_fd, err, strlen(err)) < 0) { /* egal */ }
            return;
        }
        handle_set_command(arg1, arg2, client_fd);
        return;
    }

    pthread_mutex_lock(&g_state_mutex);

    if (strcmp(cmd, "lock") == 0) {
        g_state.locked = 1;
        LOG("gesperrt via Control-Socket");
    } else if (strcmp(cmd, "unlock") == 0) {
        g_state.locked = 0;
        LOG("entsperrt via Control-Socket, hole letzten Sensor-Wert nach");
        apply_transform_locked(g_state.pending_transform);
    } else if (strcmp(cmd, "toggle") == 0) {
        g_state.locked = !g_state.locked;
        LOG("umgeschaltet via Control-Socket -> %s", g_state.locked ? "gesperrt" : "entsperrt");
        if (!g_state.locked) apply_transform_locked(g_state.pending_transform);
    } else if (strcmp(cmd, "status") != 0) {
        LOG("unbekanntes Control-Kommando: '%s'", cmd);
    }

    const char *reply = g_state.locked ? "locked\n" : "unlocked\n";
    if (write(client_fd, reply, strlen(reply)) < 0) {
        LOG("Control-Socket: write() an Client fehlgeschlagen: %s", strerror(errno));
    }

    pthread_mutex_unlock(&g_state_mutex);
}

static void *control_socket_thread(void *arg) {
    (void)arg;

    if (control_socket_path(g_control_sock_path, sizeof(g_control_sock_path)) != 0)
        return NULL;

    unlink(g_control_sock_path); /* Rest von vorherigem Lauf entfernen */

    g_control_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_control_fd < 0) { LOG("Control-Socket: socket() fehlgeschlagen: %s", strerror(errno)); return NULL; }

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, g_control_sock_path, sizeof(addr.sun_path) - 1);

    if (bind(g_control_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        LOG("Control-Socket: bind() fehlgeschlagen: %s", strerror(errno));
        close(g_control_fd);
        g_control_fd = -1;
        return NULL;
    }
    chmod(g_control_sock_path, 0666); /* jedes lokale Widget darf schreiben */

    if (listen(g_control_fd, 8) != 0) {
        LOG("Control-Socket: listen() fehlgeschlagen: %s", strerror(errno));
        close(g_control_fd);
        g_control_fd = -1;
        return NULL;
    }

    LOG("Control-Socket bereit: %s (Kommandos: lock|unlock|toggle|status)", g_control_sock_path);

    while (1) {
        int client_fd = accept(g_control_fd, NULL, NULL);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            break; /* Socket wurde beim Shutdown geschlossen */
        }
        handle_control_command(client_fd);
        close(client_fd);
    }
    return NULL;
}

static volatile sig_atomic_t g_running = 1;
static void on_sigterm(int sig) { (void)sig; g_running = 0; }

int main(void) {
    signal(SIGTERM, on_sigterm);
    signal(SIGINT,  on_sigterm);

    memset(&g_state, 0, sizeof(g_state));
    g_state.last_transform = -1;

    LOG("starte, führe initiale Geräte-Discovery aus...");
    discover_devices();

    DBusError err;
    dbus_error_init(&err);
    g_dbus = dbus_bus_get(DBUS_BUS_SYSTEM, &err);
    if (!g_dbus) {
        LOG("Konnte System-DBus nicht verbinden: %s", err.message);
        dbus_error_free(&err);
        return 1;
    }

    dbus_bus_add_match(g_dbus,
        "type='signal',interface='org.freedesktop.DBus.Properties',"
        "member='PropertiesChanged',path='/net/hadess/SensorProxy'", &err);
    if (dbus_error_is_set(&err)) {
        LOG("add_match fehlgeschlagen: %s", err.message);
        dbus_error_free(&err);
        return 1;
    }
    dbus_connection_add_filter(g_dbus, on_dbus_signal, NULL, NULL);

    claim_accelerometer(g_dbus);
    apply_initial_orientation(g_dbus);

    pthread_t ctrl_thread;
    pthread_create(&ctrl_thread, NULL, control_socket_thread, NULL);
    pthread_detach(ctrl_thread);

    LOG("bereit, warte auf Orientierungswechsel (Discovery gecacht, "
        "keine wiederholten hyprctl-Prozessaufrufe pro Event).");

    while (g_running && dbus_connection_read_write_dispatch(g_dbus, 200)) {
        /* 200ms Timeout im Dispatch-Loop: reicht für schnelle Reaktion
         * auf Signale, ohne aktiv zu pollen (dispatch blockiert bis zu
         * 200ms auf dem Socket, verbraucht in der Zwischenzeit keine
         * CPU-Zyklen - kein Busy-Wait). */
    }

    if (g_control_fd >= 0) {
        close(g_control_fd);
        unlink(g_control_sock_path);
    }

    release_accelerometer(g_dbus);
    dbus_connection_unref(g_dbus);
    return 0;
}