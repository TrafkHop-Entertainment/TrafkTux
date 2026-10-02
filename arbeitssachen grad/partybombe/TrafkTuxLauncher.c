/*
 * TrafkTuxLauncher.c - eigenständiger GTK3-Bubble-Launcher (ersetzt rofi)
 *
 * Basiert auf RofiTrafkBubbleMenus.c (Menübaum-Logik, Desktop-App-Scan,
 * Icon-Sync, exec_detached 1:1 übernommen) - der komplette rofi-Teil
 * (dmenu-Skriptprotokoll, ROFI_RETV/INFO/DATA, .rasi-Theme) ist ersetzt
 * durch ein eigenes GTK3-Fenster mit direktem Cairo-Rendering.
 *
 * WARUM DAS DEN "FRONT-BUBBLE-VOR-ALLEM"-WUNSCH JETZT WIRKLICH ERFÜLLT:
 * rofi packt Icon/Text nur sequenziell (kein z-index zwischen Geschwister-
 * Widgets, siehe vorherige rasi-Versuche). Hier zeichnen WIR selbst
 * (draw-Callback, Cairo) - Zeichenreihenfolge = Aufrufreihenfolge, exakt
 * wie im Kommentar gewünscht:
 *   1) Back-Bubble   (TrafkBubble2 / Glow2)
 *   2) Icon
 *   3) Text
 *   4) Front-Bubble  (TrafkBubble1 / Glow1)   <- liegt jetzt WIRKLICH vor
 *                                                Icon UND Text.
 *
 * Kompilierung: make (siehe Makefile)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <math.h>
#include <glib.h>
#include <gio/gio.h>
#include <json-glib/json-glib.h>
#include <gtk/gtk.h>

#include <gio/gunixsocketaddress.h>
#include <glib-unix.h>
#include <glib/gstdio.h>

#ifdef HAVE_LAYER_SHELL
#include <gtk-layer-shell/gtk-layer-shell.h>
#endif

/* =========================================================================
 * Konstanten (RAW_*, VMODE_*, Pfade etc. 1:1 aus RofiTrafkBubbleMenus.c)
 * ========================================================================= */
#define BLANK_ICON_PATH     "/tmp/.trafk-launcher-blank.png"
#define PREV_WINDOW_FILE    "/tmp/rofi-prev-window"
#define SOUNDCTL_PATH       "~/.config/hypr/SoundCenter.sh"

#define RAW_BACK            "BACK"
#define RAW_EXIT            "EXIT"
#define RAW_NOOP            "NOOP"

#define CONTENT_COLUMNS     4
#define CONTENT_ROWS        3
#define PAGE_SIZE           (CONTENT_COLUMNS * CONTENT_ROWS)

#define VMODE_DRUN          "drun"
#define VMODE_DRUN_FILTERED "drun-filtered"
#define VMODE_RUN           "run"

#define SCAN_CACHE_TTL      180

/* Powermenü: flache Liste ohne Pagination, 6x3-Grid (siehe menu.json) */
#define PM_COLUMNS          6
#define PM_ROWS             3
#define PM_SLOTS            (PM_COLUMNS * PM_ROWS)

/* ── Effektive Pixelwerte ─────────────────────────────────────────────
 * Aus den alten .rasi-Dateien zurückgerechnet: "cell-size: 285.75mm"
 * (1080px) wurde von rofis fixed-columns-Listview ohnehin auf die
 * tatsächlich verfügbare Breite runterskaliert. Rechnung, die exakt mit
 * "Original: 1265px @96dpi" für die 6-spaltige PowerMenu-Fensterbreite
 * aufgeht: cell=170, gap=35, padding=35 ->
 *   6*170 + 5*35 + 2*35 = 1020+175+70 = 1265px  ✓
 * Diese realen Werte werden hier direkt in Pixeln benutzt (kein mm/DPI-
 * Umweg mehr nötig - GTK/Wayland skaliert HiDPI über den Output-
 * Scale-Faktor der Compositor-Seite automatisch mit).
 */
#define CELL_PX             170
#define GAP_PX              35
#define PAD_PX              35
#define ICON_PX             65
#define ARROW_PX            (2 * CELL_PX)  /* 2x so groß wie eine Bubble */
#define ARROW_GAP_PX         8        /* Abstand Pfeil<->Grid - bewusst sehr klein, da die
                                          Pfeil-Bilder selbst oft schon viel Leerraum um die
                                          sichtbare Spitze haben (bei ARROW_PX=340 wird das
                                          sonst gefühlt riesig) */
#define ICON_MARGIN_PX      5
#define ELEMENT_PAD_PX      35   /* Innenabstand pro Zelle (wie altes element{padding}) */

static const char *WRAPPER_PREFIXES[] = { "kitty", "sudo", NULL };

/* =========================================================================
 * exec_detached / play_sound / cleanup - 1:1 aus dem Original übernommen
 * ========================================================================= */
static void exec_detached(const char *command) {
    if (!command || !*command) return;
    pid_t pid = fork();
    if (pid < 0) {
        g_warning("exec_detached: fork fehlgeschlagen: %s", g_strerror(errno));
        return;
    }
    if (pid == 0) {
        setsid();
        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > 2) close(devnull);
        }
        execl("/bin/sh", "sh", "-c", command, (char *)NULL);
        _exit(127);
    }
}

static void play_sound(const char *event) {
    gchar *cmd = g_strdup_printf("bash %s %s", SOUNDCTL_PATH, event);
    exec_detached(cmd);
    g_free(cmd);
}

static void cleanup_files(void) {
    unlink(PREV_WINDOW_FILE);
}

static void save_active_window(void) {
    gchar *out = NULL;
    GError *err = NULL;
    if (g_spawn_command_line_sync("hyprctl activewindow -j", &out, NULL, NULL, &err)) {
        JsonParser *parser = json_parser_new();
        if (json_parser_load_from_data(parser, out, -1, &err)) {
            JsonObject *root = json_node_get_object(json_parser_get_root(parser));
            const char *addr = json_object_get_string_member(root, "address");
            if (addr && *addr) {
                FILE *f = fopen(PREV_WINDOW_FILE, "w");
                if (f) { fprintf(f, "%s", addr); fclose(f); }
            }
        } else if (err) {
            g_error_free(err);
            err = NULL;
        }
        g_object_unref(parser);
        g_free(out);
    }
    if (err) g_error_free(err);
}

static char* read_prev_window_addr(void) {
    if (!g_file_test(PREV_WINDOW_FILE, G_FILE_TEST_EXISTS)) return NULL;
    GError *err = NULL;
    gchar *content = NULL;
    if (!g_file_get_contents(PREV_WINDOW_FILE, &content, NULL, &err)) {
        if (err) g_error_free(err);
        return NULL;
    }
    g_strstrip(content);
    return content;
}

static gboolean is_number(const char *s) {
    if (!s || !*s) return FALSE;
    for (; *s; s++) if (!g_ascii_isdigit(*s)) return FALSE;
    return TRUE;
}

static gchar* focused_monitor_name(void) {
    gchar *out = NULL;
    GError *err = NULL;
    if (!g_spawn_command_line_sync("hyprctl monitors -j", &out, NULL, NULL, &err)) {
        if (err) g_error_free(err);
        return NULL;
    }
    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, out, -1, &err)) {
        if (err) g_error_free(err);
        g_object_unref(parser);
        g_free(out);
        return NULL;
    }
    JsonArray *arr = json_node_get_array(json_parser_get_root(parser));
    const char *name = NULL;
    for (guint i = 0; i < json_array_get_length(arr); i++) {
        JsonObject *m = json_node_get_object(json_array_get_element(arr, i));
        if (json_object_has_member(m, "focused") && json_object_get_boolean_member(m, "focused")) {
            name = json_object_get_string_member(m, "name");
            break;
        }
    }
    gchar *result = name ? g_strdup(name) : NULL;
    g_object_unref(parser);
    g_free(out);
    return result;
}

/* =========================================================================
 * Menü-State (jetzt im Prozessspeicher statt über ROFI_DATA serialisiert -
 * TrafkTuxLauncher läuft als ein einziger langlebiger Prozess, kein
 * Re-Exec pro Schritt mehr nötig)
 * ========================================================================= */
typedef struct {
    char *path;   /* "/"-getrennte Kindindizes, "" = Wurzel */
    int   page;
    char *vmode;  /* NULL oder VMODE_* */
} MenuState;

static MenuState default_state(void) {
    MenuState s = { g_strdup(""), 0, NULL };
    return s;
}

/* =========================================================================
 * Menü-JSON laden & Pfadauflösung - 1:1 übernommen
 * ========================================================================= */
static JsonObject* load_menu_json(const char *menu_name) {
    gchar *path = g_build_filename(g_get_home_dir(), ".config", "rofi", menu_name, "menu.json", NULL);
    JsonParser *parser = json_parser_new();
    GError *err = NULL;
    if (!json_parser_load_from_file(parser, path, &err)) {
        g_warning("Fehler beim Laden von %s: %s", path, err->message);
        g_error_free(err);
        g_free(path);
        g_object_unref(parser);
        return NULL;
    }
    g_free(path);
    JsonObject *root = json_node_get_object(json_parser_get_root(parser));
    JsonObject *clone = json_object_ref(root);
    g_object_unref(parser);
    return clone;
}

static JsonObject* resolve_path(JsonObject *root, const char *path_str) {
    if (!path_str || !*path_str) return root;
    JsonObject *node = root;
    char **parts = g_strsplit(path_str, "/", -1);
    for (int i = 0; parts[i]; i++) {
        if (!*parts[i]) continue;
        int idx = atoi(parts[i]);
        if (json_object_has_member(node, "children")) {
            JsonArray *arr = json_object_get_array_member(node, "children");
            if (idx < 0 || (guint)idx >= json_array_get_length(arr)) break;
            node = json_node_get_object(json_array_get_element(arr, idx));
        } else break;
    }
    g_strfreev(parts);
    return node;
}

/* =========================================================================
 * Desktop-Apps & PATH-Binaries (mit Cache) - 1:1 übernommen
 * ========================================================================= */
typedef struct {
    char *name;
    char *icon;
    char *exec;
    char *sort_key;
} AppEntry;

static GPtrArray *cached_desktop_apps = NULL;
static time_t cached_desktop_ts = 0;
static GPtrArray *cached_path_bins = NULL;
static time_t cached_path_ts = 0;

static void app_entry_free(gpointer data) {
    AppEntry *e = (AppEntry*)data;
    g_free(e->name); g_free(e->icon); g_free(e->exec); g_free(e->sort_key);
    g_free(e);
}

static gint app_entry_cmp(gconstpointer a, gconstpointer b) {
    AppEntry *A = *(AppEntry**)a;
    AppEntry *B = *(AppEntry**)b;
    return g_utf8_collate(A->sort_key ? A->sort_key : A->name,
                          B->sort_key ? B->sort_key : B->name);
}

static char* extract_binary(const char *exec_str) {
    if (!exec_str || !*exec_str) return NULL;
    char *copy = g_strdup(exec_str);
    char *p = copy;
    while (*p && g_ascii_isspace(*p)) p++;
    if (!*p) { g_free(copy); return NULL; }

    int again = 1;
    while (again) {
        again = 0;
        for (int i = 0; WRAPPER_PREFIXES[i]; i++) {
            int len = strlen(WRAPPER_PREFIXES[i]);
            if (g_ascii_strncasecmp(p, WRAPPER_PREFIXES[i], len) == 0 &&
                (p[len] == ' ' || p[len] == '\t' || p[len] == '\0')) {
                p += len;
                while (*p && g_ascii_isspace(*p)) p++;
                again = 1;
                break;
            }
        }
        if (g_ascii_strncasecmp(p, "bash", 4) == 0 && (p[4] == ' ' || p[4] == '\t')) {
            char *q = p + 4;
            while (*q && g_ascii_isspace(*q)) q++;
            if (g_ascii_strncasecmp(q, "-c", 2) == 0 && (q[2] == ' ' || q[2] == '\t')) {
                q += 2;
                while (*q && g_ascii_isspace(*q)) q++;
                if (*q == '"' || *q == '\'') {
                    char quote = *q;
                    q++;
                    char *end = strchr(q, quote);
                    if (end) {
                        *end = '\0';
                        g_free(copy);
                        copy = g_strdup(q);
                        p = copy;
                        while (*p && g_ascii_isspace(*p)) p++;
                        again = 1;
                        continue;
                    }
                }
            }
        }
    }

    char *space = strpbrk(p, " \t\n\r");
    if (space) *space = '\0';
    char *bin = g_path_get_basename(p);
    g_free(copy);
    return bin;
}

static char* strip_exec_field_codes(const char *exec_str) {
    if (!exec_str) return g_strdup("");
    GString *out = g_string_new(NULL);
    size_t len = strlen(exec_str);
    size_t i = 0;
    while (i < len) {
        char ch = exec_str[i];
        if (ch == '%' && i + 1 < len) {
            char nxt = exec_str[i + 1];
            if (nxt == '%') { g_string_append_c(out, '%'); i += 2; continue; }
            if (strchr("fFuUickdDnNvm", nxt)) { i += 2; continue; }
        }
        g_string_append_c(out, ch);
        i++;
    }
    char **parts = g_strsplit_set(out->str, " \t\n\r", -1);
    g_string_free(out, TRUE);
    GString *collapsed = g_string_new(NULL);
    gboolean first = TRUE;
    for (int k = 0; parts[k]; k++) {
        if (!*parts[k]) continue;
        if (!first) g_string_append_c(collapsed, ' ');
        g_string_append(collapsed, parts[k]);
        first = FALSE;
    }
    g_strfreev(parts);
    char *result = g_strdup(collapsed->str);
    g_string_free(collapsed, TRUE);
    return result;
}

static GPtrArray* get_xdg_data_dirs(void) {
    GPtrArray *raw = g_ptr_array_new_with_free_func(g_free);
    g_ptr_array_add(raw, g_build_filename(g_get_home_dir(), ".local", "share", NULL));

    const char *xdg_data_home = g_getenv("XDG_DATA_HOME");
    if (xdg_data_home && *xdg_data_home)
        g_ptr_array_insert(raw, 0, g_strdup(xdg_data_home));

    const char *xdg_data_dirs_env = g_getenv("XDG_DATA_DIRS");
    if (!xdg_data_dirs_env || !*xdg_data_dirs_env) xdg_data_dirs_env = "/usr/local/share:/usr/share";
    char **parts = g_strsplit(xdg_data_dirs_env, ":", -1);
    for (int i = 0; parts[i]; i++) {
        if (*parts[i]) g_ptr_array_add(raw, g_strdup(parts[i]));
    }
    g_strfreev(parts);

    GPtrArray *out = g_ptr_array_new_with_free_func(g_free);
    GHashTable *seen = g_hash_table_new(g_str_hash, g_str_equal);
    for (guint i = 0; i < raw->len; i++) {
        const char *d = g_ptr_array_index(raw, i);
        if (!g_hash_table_contains(seen, d)) {
            g_hash_table_add(seen, (gpointer)d);
            g_ptr_array_add(out, g_strdup(d));
        }
    }
    g_hash_table_unref(seen);
    g_ptr_array_unref(raw);
    return out;
}

static GHashTable* current_desktop_names(void) {
    GHashTable *set = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    const char *raw = g_getenv("XDG_CURRENT_DESKTOP");
    if (raw && *raw) {
        char **parts = g_strsplit(raw, ":", -1);
        for (int i = 0; parts[i]; i++) {
            g_strstrip(parts[i]);
            if (*parts[i]) g_hash_table_add(set, g_strdup(parts[i]));
        }
        g_strfreev(parts);
    }
    return set;
}

static void walk_desktop_files(const char *app_dir, const char *subdir,
                                GPtrArray *out_files, GPtrArray *out_ids) {
    gchar *full_dir = (subdir && *subdir) ? g_build_filename(app_dir, subdir, NULL) : g_strdup(app_dir);
    GDir *dir = g_dir_open(full_dir, 0, NULL);
    if (dir) {
        const char *fname;
        while ((fname = g_dir_read_name(dir)) != NULL) {
            gchar *full_path = g_build_filename(full_dir, fname, NULL);
            gchar *rel_sub = (subdir && *subdir) ? g_build_filename(subdir, fname, NULL) : g_strdup(fname);
            if (g_file_test(full_path, G_FILE_TEST_IS_DIR)) {
                walk_desktop_files(app_dir, rel_sub, out_files, out_ids);
            } else if (g_str_has_suffix(fname, ".desktop")) {
                gchar *id = g_strdup(rel_sub);
                for (char *p = id; *p; p++) if (*p == G_DIR_SEPARATOR) *p = '-';
                g_ptr_array_add(out_files, g_strdup(full_path));
                g_ptr_array_add(out_ids, id);
            }
            g_free(rel_sub);
            g_free(full_path);
        }
        g_dir_close(dir);
    }
    g_free(full_dir);
}

static gboolean field_intersects(const char *field, GHashTable *current_desktop) {
    gboolean hit = FALSE;
    char **parts = g_strsplit(field, ";", -1);
    for (int k = 0; parts[k]; k++) {
        g_strstrip(parts[k]);
        if (*parts[k] && g_hash_table_contains(current_desktop, parts[k])) { hit = TRUE; break; }
    }
    g_strfreev(parts);
    return hit;
}

static void collect_desktop_apps_impl(GPtrArray **out, time_t *ts) {
    time_t now = time(NULL);
    if (cached_desktop_apps && (now - cached_desktop_ts) < SCAN_CACHE_TTL) {
        *out = cached_desktop_apps;
        *ts = cached_desktop_ts;
        return;
    }

    GHashTable *current_desktop = current_desktop_names();
    GHashTable *seen_ids = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    GPtrArray *apps = g_ptr_array_new_with_free_func(app_entry_free);
    GPtrArray *data_dirs = get_xdg_data_dirs();

    for (guint d = 0; d < data_dirs->len; d++) {
        const char *data_dir = g_ptr_array_index(data_dirs, d);
        gchar *app_dir = g_build_filename(data_dir, "applications", NULL);
        if (!g_file_test(app_dir, G_FILE_TEST_IS_DIR)) { g_free(app_dir); continue; }

        GPtrArray *files = g_ptr_array_new_with_free_func(g_free);
        GPtrArray *ids = g_ptr_array_new_with_free_func(g_free);
        walk_desktop_files(app_dir, "", files, ids);

        for (guint i = 0; i < files->len; i++) {
            const char *full_path = g_ptr_array_index(files, i);
            const char *desktop_id = g_ptr_array_index(ids, i);
            if (g_hash_table_contains(seen_ids, desktop_id)) continue;

            GKeyFile *kf = g_key_file_new();
            if (!g_key_file_load_from_file(kf, full_path, G_KEY_FILE_NONE, NULL)) {
                g_key_file_free(kf);
                continue;
            }
            if (!g_key_file_has_group(kf, "Desktop Entry")) { g_key_file_free(kf); continue; }

            g_hash_table_add(seen_ids, g_strdup(desktop_id));

            gchar *type = g_key_file_get_string(kf, "Desktop Entry", "Type", NULL);
            gboolean skip = (type && *type && g_strcmp0(type, "Application") != 0);
            g_free(type);
            if (skip) { g_key_file_free(kf); continue; }

            GError *gerr = NULL;
            gboolean hidden = g_key_file_get_boolean(kf, "Desktop Entry", "Hidden", &gerr);
            if (gerr) { g_clear_error(&gerr); hidden = FALSE; }
            if (hidden) { g_key_file_free(kf); continue; }

            gboolean nodisplay = g_key_file_get_boolean(kf, "Desktop Entry", "NoDisplay", &gerr);
            if (gerr) { g_clear_error(&gerr); nodisplay = FALSE; }
            if (nodisplay) { g_key_file_free(kf); continue; }

            gchar *only_show_in = g_key_file_get_string(kf, "Desktop Entry", "OnlyShowIn", NULL);
            if (only_show_in && *only_show_in && g_hash_table_size(current_desktop) > 0) {
                gboolean allowed = field_intersects(only_show_in, current_desktop);
                g_free(only_show_in);
                if (!allowed) { g_key_file_free(kf); continue; }
            } else {
                g_free(only_show_in);
            }

            gchar *not_show_in = g_key_file_get_string(kf, "Desktop Entry", "NotShowIn", NULL);
            if (not_show_in && *not_show_in && g_hash_table_size(current_desktop) > 0) {
                gboolean denied = field_intersects(not_show_in, current_desktop);
                g_free(not_show_in);
                if (denied) { g_key_file_free(kf); continue; }
            } else {
                g_free(not_show_in);
            }

            gchar *exec_raw = g_key_file_get_string(kf, "Desktop Entry", "Exec", NULL);
            if (!exec_raw || !*exec_raw) { g_free(exec_raw); g_key_file_free(kf); continue; }

            gchar *name = g_key_file_get_string(kf, "Desktop Entry", "Name", NULL);
            if (!name || !*name) { g_free(name); name = g_strdup(desktop_id); }
            gchar *icon = g_key_file_get_string(kf, "Desktop Entry", "Icon", NULL);
            if (!icon || !*icon) { g_free(icon); icon = g_strdup("application-x-executable"); }

            char *stripped = strip_exec_field_codes(exec_raw);
            g_free(exec_raw);

            gboolean terminal = g_key_file_get_boolean(kf, "Desktop Entry", "Terminal", &gerr);
            if (gerr) { g_clear_error(&gerr); terminal = FALSE; }

            char *final_exec;
            if (terminal) {
                final_exec = g_strdup_printf("kitty %s", stripped);
                g_free(stripped);
            } else {
                final_exec = stripped;
            }

            AppEntry *e = g_new0(AppEntry, 1);
            e->name = name;
            e->icon = icon;
            e->exec = final_exec;
            e->sort_key = g_utf8_casefold(e->name, -1);
            g_ptr_array_add(apps, e);

            g_key_file_free(kf);
        }
        g_ptr_array_unref(files);
        g_ptr_array_unref(ids);
        g_free(app_dir);
    }
    g_ptr_array_unref(data_dirs);
    g_hash_table_unref(seen_ids);
    g_hash_table_unref(current_desktop);

    g_ptr_array_sort(apps, app_entry_cmp);
    if (cached_desktop_apps) g_ptr_array_unref(cached_desktop_apps);
    cached_desktop_apps = apps;
    cached_desktop_ts = now;
    *out = apps;
    *ts = now;
}

static GPtrArray* get_desktop_apps(void) {
    GPtrArray *apps; time_t ts;
    collect_desktop_apps_impl(&apps, &ts);
    return apps;
}

static GPtrArray* get_filtered_desktop_apps(JsonObject *root) {
    GPtrArray *all = get_desktop_apps();
    GHashTable *used_names = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    GHashTable *used_execs = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);

    GQueue *stack = g_queue_new();
    g_queue_push_tail(stack, root);
    while (!g_queue_is_empty(stack)) {
        JsonObject *node = g_queue_pop_head(stack);
        if (!json_object_has_member(node, "children")) continue;
        JsonArray *arr = json_object_get_array_member(node, "children");
        for (guint i = 0; i < json_array_get_length(arr); i++) {
            JsonObject *child = json_node_get_object(json_array_get_element(arr, i));
            const char *type = json_object_get_string_member(child, "type");
            if (g_strcmp0(type, "folder") == 0) {
                g_queue_push_tail(stack, child);
            } else if (g_strcmp0(type, "app") == 0) {
                const char *name = json_object_get_string_member(child, "name");
                if (name && *name) {
                    gchar *lower = g_utf8_casefold(name, -1);
                    g_hash_table_add(used_names, lower);
                }
                const char *exec_str = json_object_get_string_member(child, "exec");
                if (exec_str && *exec_str) {
                    char *bin = extract_binary(exec_str);
                    if (bin) {
                        gchar *lower = g_utf8_casefold(bin, -1);
                        g_hash_table_add(used_execs, lower);
                        g_free(bin);
                    }
                }
            }
        }
    }
    g_queue_free(stack);

    GPtrArray *filtered = g_ptr_array_new_with_free_func(app_entry_free);
    for (guint i = 0; i < all->len; i++) {
        AppEntry *e = g_ptr_array_index(all, i);
        gchar *name_lower = g_utf8_casefold(e->name, -1);
        char *bin = extract_binary(e->exec);
        gboolean found = (g_hash_table_lookup(used_names, name_lower) != NULL);
        if (!found && bin) {
            gchar *bin_lower = g_utf8_casefold(bin, -1);
            found = (g_hash_table_lookup(used_execs, bin_lower) != NULL);
            g_free(bin_lower);
        }
        g_free(name_lower);
        g_free(bin);
        if (!found) {
            AppEntry *copy = g_new0(AppEntry, 1);
            copy->name = g_strdup(e->name);
            copy->icon = g_strdup(e->icon);
            copy->exec = g_strdup(e->exec);
            copy->sort_key = g_utf8_casefold(e->name, -1);
            g_ptr_array_add(filtered, copy);
        }
    }
    g_ptr_array_sort(filtered, app_entry_cmp);
    g_hash_table_unref(used_names);
    g_hash_table_unref(used_execs);
    return filtered;
}

static GPtrArray* get_path_binaries(void) {
    time_t now = time(NULL);
    if (cached_path_bins && (now - cached_path_ts) < SCAN_CACHE_TTL) {
        return cached_path_bins;
    }

    GPtrArray *bins = g_ptr_array_new_with_free_func(app_entry_free);
    const char *path_env = g_getenv("PATH");
    if (!path_env) path_env = "/usr/local/bin:/usr/bin:/bin";
    char **dirs = g_strsplit(path_env, ":", -1);
    GHashTable *seen = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);

    for (int i = 0; dirs[i]; i++) {
        if (!dirs[i] || !*dirs[i]) continue;
        GDir *dir = g_dir_open(dirs[i], 0, NULL);
        if (!dir) continue;
        const char *fname;
        while ((fname = g_dir_read_name(dir)) != NULL) {
            if (g_hash_table_contains(seen, fname)) continue;
            gchar *full = g_build_filename(dirs[i], fname, NULL);
            if (g_file_test(full, G_FILE_TEST_IS_REGULAR) &&
                g_file_test(full, G_FILE_TEST_IS_EXECUTABLE)) {
                g_hash_table_add(seen, g_strdup(fname));
                AppEntry *e = g_new0(AppEntry, 1);
                e->name = g_strdup(fname);
                e->icon = g_strdup("application-x-executable");
                e->exec = g_strdup_printf("'%s'", full);
                e->sort_key = g_utf8_casefold(fname, -1);
                g_ptr_array_add(bins, e);
            }
            g_free(full);
        }
        g_dir_close(dir);
    }
    g_strfreev(dirs);
    g_ptr_array_sort(bins, app_entry_cmp);
    g_hash_table_unref(seen);

    if (cached_path_bins) g_ptr_array_unref(cached_path_bins);
    cached_path_bins = bins;
    cached_path_ts = now;
    return bins;
}

/* =========================================================================
 * Icon-Sync (Steam & JetBrains) - 1:1 übernommen
 * ========================================================================= */
static const char* steam_library_cache(void) {
    static gchar *path = NULL;
    if (!path) path = g_build_filename(g_get_home_dir(), ".local/share/Steam/appcache/librarycache", NULL);
    return path;
}
static const char* steam_icon_target(void) {
    static gchar *path = NULL;
    if (!path) path = g_build_filename(g_get_home_dir(), ".local/share/icons/hicolor/128x128/apps", NULL);
    return path;
}
static const char* jetbrains_dot_icons(void) {
    static gchar *path = NULL;
    if (!path) path = g_build_filename(g_get_home_dir(), ".local/share/JetBrains/Toolbox/dotDesktopIcons", NULL);
    return path;
}
static const char* jetbrains_icon_target(void) {
    static gchar *path = NULL;
    if (!path) path = g_build_filename(g_get_home_dir(), ".local/share/icons/hicolor/scalable/apps", NULL);
    return path;
}

static GHashTable *icon_stem_cache = NULL;

static void build_icon_stem_cache(void) {
    if (icon_stem_cache) {
        g_hash_table_unref(icon_stem_cache);
        icon_stem_cache = NULL;
    }
    icon_stem_cache = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    gchar *home_icons = g_build_filename(g_get_home_dir(), ".local/share/icons", NULL);
    const char *search_dirs[2] = { home_icons, "/usr/share/icons" };

    for (int d = 0; d < 2; d++) {
        GDir *dir = g_dir_open(search_dirs[d], 0, NULL);
        if (!dir) continue;
        const char *name;
        while ((name = g_dir_read_name(dir)) != NULL) {
            gchar *full = g_build_filename(search_dirs[d], name, NULL);
            if (g_file_test(full, G_FILE_TEST_IS_DIR)) {
                GDir *sub = g_dir_open(full, 0, NULL);
                if (sub) {
                    const char *subname;
                    while ((subname = g_dir_read_name(sub)) != NULL) {
                        gchar *subfull = g_build_filename(full, subname, NULL);
                        if (g_file_test(subfull, G_FILE_TEST_IS_REGULAR)) {
                            char *stem = g_strdup(subname);
                            char *dot = strrchr(stem, '.');
                            if (dot) *dot = '\0';
                            g_hash_table_add(icon_stem_cache, stem);
                        }
                        g_free(subfull);
                    }
                    g_dir_close(sub);
                }
            }
            g_free(full);
        }
        g_dir_close(dir);
    }
    g_free(home_icons);
}

static gboolean icon_already_resolvable(const char *icon_name) {
    if (!icon_name || !*icon_name) return FALSE;
    if (!icon_stem_cache) build_icon_stem_cache();
    return g_hash_table_contains(icon_stem_cache, icon_name);
}

static GHashTable* find_steam_desktop_appids(void) {
    GHashTable *appids = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    GPtrArray *data_dirs = get_xdg_data_dirs();

    for (guint d = 0; d < data_dirs->len; d++) {
        gchar *app_dir = g_build_filename(g_ptr_array_index(data_dirs, d), "applications", NULL);
        GDir *dir = g_dir_open(app_dir, 0, NULL);
        if (!dir) { g_free(app_dir); continue; }
        const char *fname;
        while ((fname = g_dir_read_name(dir)) != NULL) {
            if (!g_str_has_suffix(fname, ".desktop")) continue;
            gchar *full = g_build_filename(app_dir, fname, NULL);
            GKeyFile *kf = g_key_file_new();
            if (g_key_file_load_from_file(kf, full, G_KEY_FILE_NONE, NULL)) {
                gchar *icon = g_key_file_get_string(kf, "Desktop Entry", "Icon", NULL);
                if (icon && g_str_has_prefix(icon, "steam_icon_")) {
                    const char *appid = icon + strlen("steam_icon_");
                    if (appid && g_ascii_isdigit(*appid) && strspn(appid, "0123456789") == strlen(appid))
                        g_hash_table_add(appids, g_strdup(appid));
                }
                g_free(icon);
            }
            g_key_file_free(kf);
            g_free(full);
        }
        g_dir_close(dir);
        g_free(app_dir);
    }
    g_ptr_array_unref(data_dirs);
    return appids;
}

static char* find_steam_icon_source(const char *appid) {
    gchar *cache_dir = g_build_filename(steam_library_cache(), appid, NULL);
    if (!g_file_test(cache_dir, G_FILE_TEST_IS_DIR)) {
        g_free(cache_dir);
        return NULL;
    }
    GDir *dir = g_dir_open(cache_dir, 0, NULL);
    if (!dir) { g_free(cache_dir); return NULL; }

    const char *artwork_names[] = {
        "header.jpg", "logo.png", "library_600x900.jpg",
        "library_hero.jpg", "library_hero_blur.jpg",
        "capsule_231x87.jpg", "capsule_616x353.jpg",
        "page_bg_raw.jpg", "page.bg.jpg", NULL
    };

    char *best_path = NULL;
    int best_size = -1;
    const char *fname;
    while ((fname = g_dir_read_name(dir)) != NULL) {
        gboolean is_artwork = FALSE;
        for (int a = 0; artwork_names[a]; a++) {
            if (g_strcmp0(fname, artwork_names[a]) == 0) { is_artwork = TRUE; break; }
        }
        if (is_artwork) continue;
        gchar *full = g_build_filename(cache_dir, fname, NULL);
        if (!g_file_test(full, G_FILE_TEST_IS_REGULAR)) { g_free(full); continue; }

        gchar *quoted = g_shell_quote(full);
        gchar *cmd = g_strdup_printf("identify -format '%%w %%h' %s 2>/dev/null", quoted);
        gchar *out = NULL;
        GError *err = NULL;
        if (g_spawn_command_line_sync(cmd, &out, NULL, NULL, &err)) {
            if (out && *out) {
                int w, h;
                if (sscanf(out, "%d %d", &w, &h) == 2 && w == h && w > best_size) {
                    best_size = w;
                    g_free(best_path);
                    best_path = g_strdup(full);
                }
            }
            g_free(out);
        } else if (err) {
            g_error_free(err);
        }
        g_free(cmd);
        g_free(quoted);
        g_free(full);
    }
    g_dir_close(dir);
    g_free(cache_dir);
    return best_path;
}

static int sync_steam_icons(void) {
    if (!g_file_test(steam_library_cache(), G_FILE_TEST_IS_DIR)) return 0;

    GHashTable *appids = find_steam_desktop_appids();
    int installed = 0;
    GHashTableIter iter;
    gpointer key;
    g_hash_table_iter_init(&iter, appids);
    while (g_hash_table_iter_next(&iter, &key, NULL)) {
        const char *appid = key;
        gchar *icon_name = g_strdup_printf("steam_icon_%s", appid);
        if (icon_already_resolvable(icon_name)) {
            g_free(icon_name);
            continue;
        }
        char *source = find_steam_icon_source(appid);
        if (!source) { g_free(icon_name); continue; }
        const char *target_dir = steam_icon_target();
        g_mkdir_with_parents(target_dir, 0755);
        gchar *target = g_build_filename(target_dir, icon_name, NULL);
        gchar *target_png = g_strdup_printf("%s.png", target);
        gchar *src_q = g_shell_quote(source);
        gchar *dst_q = g_shell_quote(target_png);
        gchar *cmd = g_strdup_printf("magick %s %s 2>/dev/null", src_q, dst_q);
        GError *err = NULL;
        if (g_spawn_command_line_sync(cmd, NULL, NULL, NULL, &err)) {
            installed++;
            if (icon_stem_cache) {
                g_hash_table_unref(icon_stem_cache);
                icon_stem_cache = NULL;
            }
        } else if (err) {
            g_error_free(err);
        }
        g_free(cmd);
        g_free(src_q);
        g_free(dst_q);
        g_free(target);
        g_free(target_png);
        g_free(source);
        g_free(icon_name);
    }
    g_hash_table_unref(appids);
    if (installed > 0) {
        gchar *hicolor = g_build_filename(g_get_home_dir(), ".local/share/icons/hicolor", NULL);
        gchar *hq = g_shell_quote(hicolor);
        gchar *cmd = g_strdup_printf("gtk-update-icon-cache -f -t %s 2>/dev/null", hq);
        exec_detached(cmd);
        g_free(cmd);
        g_free(hq);
        g_free(hicolor);
    }
    return installed;
}

static int sync_jetbrains_icons(void) {
    const char *jet_dot = jetbrains_dot_icons();
    if (!g_file_test(jet_dot, G_FILE_TEST_IS_DIR))
        return 0;
    int installed = 0;
    GPtrArray *data_dirs = get_xdg_data_dirs();

    for (guint d = 0; d < data_dirs->len; d++) {
        gchar *app_dir = g_build_filename(g_ptr_array_index(data_dirs, d), "applications", NULL);
        GDir *dir = g_dir_open(app_dir, 0, NULL);
        if (!dir) { g_free(app_dir); continue; }
        const char *fname;
        while ((fname = g_dir_read_name(dir)) != NULL) {
            if (!g_str_has_prefix(fname, "jetbrains-") || !g_str_has_suffix(fname, ".desktop"))
                continue;
            gchar *full = g_build_filename(app_dir, fname, NULL);
            GKeyFile *kf = g_key_file_new();
            if (g_key_file_load_from_file(kf, full, G_KEY_FILE_NONE, NULL)) {
                gchar *icon = g_key_file_get_string(kf, "Desktop Entry", "Icon", NULL);
                if (icon && *icon && !icon_already_resolvable(icon)) {
                    gchar *source = g_strdup_printf("%s/%s.icon.svg", jet_dot, fname);
                    if (g_file_test(source, G_FILE_TEST_IS_REGULAR)) {
                        const char *target_dir = jetbrains_icon_target();
                        g_mkdir_with_parents(target_dir, 0755);
                        gchar *target = g_strdup_printf("%s/%s.svg", target_dir, icon);
                        GFile *src_file = g_file_new_for_path(source);
                        GFile *dst_file = g_file_new_for_path(target);
                        GError *err = NULL;
                        if (g_file_copy(src_file, dst_file, G_FILE_COPY_OVERWRITE, NULL, NULL, NULL, &err)) {
                            installed++;
                            if (icon_stem_cache) {
                                g_hash_table_unref(icon_stem_cache);
                                icon_stem_cache = NULL;
                            }
                        } else if (err) {
                            g_error_free(err);
                        }
                        g_object_unref(src_file);
                        g_object_unref(dst_file);
                        g_free(target);
                        g_free(source);
                    } else {
                        g_free(source);
                    }
                }
                g_free(icon);
            }
            g_key_file_free(kf);
            g_free(full);
        }
        g_dir_close(dir);
        g_free(app_dir);
    }
    g_ptr_array_unref(data_dirs);
    if (installed > 0) {
        gchar *hicolor = g_build_filename(g_get_home_dir(), ".local/share/icons/hicolor", NULL);
        gchar *hq = g_shell_quote(hicolor);
        gchar *cmd = g_strdup_printf("gtk-update-icon-cache -f -t %s 2>/dev/null", hq);
        exec_detached(cmd);
        g_free(cmd);
        g_free(hq);
        g_free(hicolor);
    }
    return installed;
}

/* =========================================================================
 * Icon-Auflösung -> GdkPixbuf (neu, ersetzt rofis "icon"-DMenu-Feld)
 * ========================================================================= */
static GdkPixbuf* load_icon_pixbuf(GHashTable *cache, const char *icon_name, int size) {
    if (!icon_name || !*icon_name) return NULL;
    gchar *key = g_strdup_printf("%s@%d", icon_name, size);
    GdkPixbuf *cached = g_hash_table_lookup(cache, key);
    if (cached) { g_free(key); return cached; }

    GdkPixbuf *pixbuf = NULL;
    GError *err = NULL;

    if (g_path_is_absolute(icon_name) && g_file_test(icon_name, G_FILE_TEST_EXISTS)) {
        pixbuf = gdk_pixbuf_new_from_file_at_scale(icon_name, size, size, TRUE, &err);
        if (err) { g_clear_error(&err); }
    }
    if (!pixbuf) {
        GtkIconTheme *theme = gtk_icon_theme_get_default();
        pixbuf = gtk_icon_theme_load_icon(theme, icon_name, size, GTK_ICON_LOOKUP_FORCE_SIZE, &err);
        if (err) { g_clear_error(&err); }
    }
    if (!pixbuf) {
        GtkIconTheme *theme = gtk_icon_theme_get_default();
        pixbuf = gtk_icon_theme_load_icon(theme, "application-x-executable", size, GTK_ICON_LOOKUP_FORCE_SIZE, NULL);
    }

    if (pixbuf) {
        g_hash_table_insert(cache, key, pixbuf); /* Ownership -> Cache */
    } else {
        g_free(key);
    }
    return pixbuf;
}

/* =========================================================================
 * Bubble-Assets (Back/Front x Normal/Selected), pro Menü einmal geladen
 * und auf CELL_PX vorskaliert.
 * ========================================================================= */
typedef struct {
    GdkPixbuf *back_normal;
    GdkPixbuf *back_selected;
    GdkPixbuf *front_normal;
    GdkPixbuf *front_selected;
} BubbleAssets;

static GdkPixbuf* try_load_scaled(const char *path, int size) {
    if (!path || !g_file_test(path, G_FILE_TEST_EXISTS)) return NULL;
    GError *err = NULL;
    GdkPixbuf *p = gdk_pixbuf_new_from_file_at_scale(path, size, size, FALSE, &err);
    if (err) { g_clear_error(&err); return NULL; }
    return p;
}

/* Priorität wie abgesprochen: /tmp/Trafk*.png hat IMMER Vorrang, Fallback
 * ~/.config/TrafkTuxLauncher/<menu>/assets/ (eigener Config-Pfad, nicht
 * mehr rofi). Trafk-Set (2-Lagen) hat Vorrang. Falls kein Trafk-Set
 * gefunden wird, Fallback auf altes Ein-Lagen-Set (bubble-normal.png /
 * bubble-selected.png), dann sind Front und Back identisch.
 *
 * Gibt bei jedem Start auf stderr aus, welche Datei für back/front x
 * normal/selected TATSÄCHLICH geladen wurde (oder "NICHT GEFUNDEN") -
 * damit sich "die Glow-Bilder werden nicht benutzt" selbst nachprüfen
 * lässt, statt geraten werden zu müssen. */
static const char* load_one(const char *label, const char * const *candidates, int n,
                             int size, GdkPixbuf **out_pixbuf) {
    for (int i = 0; i < n; i++) {
        GdkPixbuf *p = try_load_scaled(candidates[i], size);
        if (p) {
            *out_pixbuf = p;
            g_printerr("TrafkTuxLauncher: %-14s -> %s\n", label, candidates[i]);
            return candidates[i];
        }
    }
    g_printerr("TrafkTuxLauncher: %-14s -> NICHT GEFUNDEN (geprüft: ", label);
    for (int i = 0; i < n; i++) g_printerr("%s%s", i ? ", " : "", candidates[i]);
    g_printerr(")\n");
    return NULL;
}

static void load_bubble_assets(const char *menu_name, BubbleAssets *out) {
    gchar *cfg_dir = g_build_filename(g_get_home_dir(), ".config", "TrafkTuxLauncher", menu_name, "assets", NULL);

    gchar *p_back_n  = g_build_filename(cfg_dir, "TrafkBubble2.png", NULL);
    gchar *p_back_s  = g_build_filename(cfg_dir, "TrafkBubbleGlow2.png", NULL);
    gchar *p_front_n = g_build_filename(cfg_dir, "TrafkBubble1.png", NULL);
    gchar *p_front_s = g_build_filename(cfg_dir, "TrafkBubbleGlow1.png", NULL);

    const char *candidates_back_n[]  = { "/tmp/TrafkBubble2.png",     p_back_n  };
    const char *candidates_back_s[]  = { "/tmp/TrafkBubbleGlow2.png", p_back_s  };
    const char *candidates_front_n[] = { "/tmp/TrafkBubble1.png",     p_front_n };
    const char *candidates_front_s[] = { "/tmp/TrafkBubbleGlow1.png", p_front_s };

    load_one("back-normal",   candidates_back_n,  2, CELL_PX, &out->back_normal);
    load_one("back-selected", candidates_back_s,  2, CELL_PX, &out->back_selected);
    load_one("front-normal",  candidates_front_n, 2, CELL_PX, &out->front_normal);
    load_one("front-selected",candidates_front_s, 2, CELL_PX, &out->front_selected);

    /* Fallback: altes Ein-Lagen-Set, falls Trafk-Set (teilweise) fehlt */
    if (!out->back_normal || !out->front_normal) {
        GdkPixbuf *old_n = try_load_scaled("/tmp/bubble-normal.png", CELL_PX);
        if (!out->back_normal)  out->back_normal  = old_n ? g_object_ref(old_n) : NULL;
        if (!out->front_normal) out->front_normal = old_n; /* übernimmt Ref oder bleibt NULL */
    }
    if (!out->back_selected || !out->front_selected) {
        GdkPixbuf *old_s = try_load_scaled("/tmp/bubble-selected.png", CELL_PX);
        if (!out->back_selected)  out->back_selected  = old_s ? g_object_ref(old_s) : NULL;
        if (!out->front_selected) out->front_selected = old_s;
    }

    if (!out->back_normal) {
        g_warning("TrafkTuxLauncher: keine Bubble-Assets für Menü '%s' gefunden "
                  "(weder /tmp/Trafk*.png noch %s noch /tmp/bubble-*.png) - "
                  "Zellen werden ohne Bubble-Hintergrund gezeichnet.", menu_name, cfg_dir);
    }

    g_free(p_back_n); g_free(p_back_s); g_free(p_front_n); g_free(p_front_s);
    g_free(cfg_dir);
}

/* ── Nav-Assets: Pfeile links/rechts ─────────────────────────────────────
 * Werden OHNE Bubble gezeichnet (roh, mit Alpha), Icon-Größe wie die
 * App/Ordner-Icons (ICON_PX). Kein Back/Exit-Button mehr (siehe Punkt 3/4
 * - Leerbereich-Klick übernimmt das jetzt). Echte Dateinamen: Left.png/
 * Right.png (nicht Last/Next - war meine Fehlannahme). Gleiche
 * /tmp-zuerst-dann-Config-Fallback-Logik wie bei den Trafk-Bubbles,
 * gleiche Debug-Ausgabe. */
typedef struct {
    GdkPixbuf *arrow_left_normal;   /* Left.png */
    GdkPixbuf *arrow_left_glow;     /* LeftGlow.png */
    GdkPixbuf *arrow_right_normal;  /* Right.png */
    GdkPixbuf *arrow_right_glow;    /* RightGlow.png */
} NavAssets;

static void load_nav_assets(const char *menu_name, NavAssets *out) {
    gchar *cfg_dir = g_build_filename(g_get_home_dir(), ".config", "TrafkTuxLauncher", menu_name, "assets", NULL);

    gchar *p_left_n  = g_build_filename(cfg_dir, "Left.png", NULL);
    gchar *p_left_g  = g_build_filename(cfg_dir, "LeftGlow.png", NULL);
    gchar *p_right_n = g_build_filename(cfg_dir, "Right.png", NULL);
    gchar *p_right_g = g_build_filename(cfg_dir, "RightGlow.png", NULL);

    const char *c_left_n[]  = { "/tmp/Left.png",       p_left_n  };
    const char *c_left_g[]  = { "/tmp/LeftGlow.png",   p_left_g  };
    const char *c_right_n[] = { "/tmp/Right.png",      p_right_n };
    const char *c_right_g[] = { "/tmp/RightGlow.png",  p_right_g };

    load_one("arrow-left",       c_left_n,  2, ARROW_PX, &out->arrow_left_normal);
    load_one("arrow-left-glow",  c_left_g,  2, ARROW_PX, &out->arrow_left_glow);
    load_one("arrow-right",      c_right_n, 2, ARROW_PX, &out->arrow_right_normal);
    load_one("arrow-right-glow", c_right_g, 2, ARROW_PX, &out->arrow_right_glow);

    /* Fallback: wenn die Glow-Variante fehlt, lieber das normale Bild
     * beim Hover weiter anzeigen als GAR NICHTS - sonst verschwindet der
     * Pfeil beim Drüberfahren komplett (echter Bug, war so). */
    if (!out->arrow_left_glow && out->arrow_left_normal) out->arrow_left_glow = g_object_ref(out->arrow_left_normal);
    if (!out->arrow_right_glow && out->arrow_right_normal) out->arrow_right_glow = g_object_ref(out->arrow_right_normal);

    g_free(p_left_n); g_free(p_left_g); g_free(p_right_n); g_free(p_right_g);
    g_free(cfg_dir);
}

static void free_nav_assets(NavAssets *a) {
    if (a->arrow_left_normal) g_object_unref(a->arrow_left_normal);
    if (a->arrow_left_glow) g_object_unref(a->arrow_left_glow);
    if (a->arrow_right_normal) g_object_unref(a->arrow_right_normal);
    if (a->arrow_right_glow) g_object_unref(a->arrow_right_glow);
}

/* =========================================================================
 * Grid-Slots (entspricht GridEntry / build_grid_entries aus dem Original,
 * nur dass hier ein GPtrArray für die eigene Zeichnung befüllt wird statt
 * das dmenu-Protokoll auf stdout zu schreiben)
 * ========================================================================= */
typedef struct {
    char *name;
    char *icon;
    char *raw;            /* RAW_* Konstante ODER dezimaler Index (als String) */
    gboolean nonselectable;
} Slot;

static void slot_free(gpointer data) {
    Slot *e = (Slot*)data;
    g_free(e->name); g_free(e->icon); g_free(e->raw);
    g_free(e);
}

static Slot* make_slot(const char *name, const char *icon, const char *raw, gboolean nonselectable) {
    Slot *e = g_new0(Slot, 1);
    e->name = g_strdup(name ? name : " ");
    e->icon = g_strdup(icon ? icon : "");
    e->raw = g_strdup(raw ? raw : RAW_NOOP);
    e->nonselectable = nonselectable;
    return e;
}

/* Baumbasiertes Grid (AppLauncher-Stil): 4 Inhaltsspalten + 1 Nav-Spalte,
 * 3 Zeilen = 15 Slots. 1:1 Logik aus build_grid_entries() im Original. */
/* Reines 4x3 Content-Grid, IMMER (auch in der Wurzel) - keine Nav-Spalte
 * mehr eingemischt. Next/Prev sind jetzt freistehende Pfeile links/rechts
 * vom Grid, Back/Exit ein eigener Button unten mittig (siehe on_draw) -
 * beide werden NICHT mehr als Slots geführt, sondern direkt gezeichnet
 * und per eigenem Hit-Test angeklickt/mit q/e/x bedient. Macht diese
 * Funktion trivial: einfach die content_entries auf PAGE_SIZE auffüllen. */
/* Reines 4x3 Content-Grid. Next/Prev sind freistehende Pfeile, kein
 * Back/Exit-Button mehr im Bild (Leerbereich-Klick übernimmt das) -
 * beides KEINE Slots mehr. In der Wurzel gilt weiterhin die alte
 * 3+1-Verteilung (so war's schon vor dem GTK-Umbau): Spalten 0-2 werden
 * zeilenweise mit den ersten 9 Einträgen gefüllt, Spalte 3 bekommt
 * Eintrag 9/10/11 - einen pro Zeile - statt einfach sequenziell
 * aufzufüllen. Überall sonst (Unterordner, vmode-Listen) ganz normal
 * sequenziell 4 Spalten x 3 Zeilen. */
static GPtrArray* build_grid_slots(GPtrArray *content_entries, gboolean is_root) {
    GPtrArray *result = g_ptr_array_new_with_free_func(slot_free);

    Slot *content[PAGE_SIZE];
    for (int i = 0; i < PAGE_SIZE; i++)
        content[i] = make_slot(" ", "", RAW_NOOP, FALSE);
    guint copy_count = MIN(content_entries->len, (guint)PAGE_SIZE);
    for (guint i = 0; i < copy_count; i++) {
        Slot *src = g_ptr_array_index(content_entries, i);
        Slot *dst = content[i];
        g_free(dst->name); g_free(dst->icon); g_free(dst->raw);
        dst->name = g_strdup(src->name);
        dst->icon = g_strdup(src->icon);
        dst->raw = g_strdup(src->raw);
        dst->nonselectable = src->nonselectable;
    }

    if (is_root) {
        for (int row = 0; row < CONTENT_ROWS; row++) {
            for (int col = 0; col < 3; col++) {
                Slot *e = content[row * 3 + col];
                g_ptr_array_add(result, make_slot(e->name, e->icon, e->raw, e->nonselectable));
            }
            Slot *e4 = content[9 + row];
            g_ptr_array_add(result, make_slot(e4->name, e4->icon, e4->raw, e4->nonselectable));
        }
    } else {
        for (int i = 0; i < PAGE_SIZE; i++)
            g_ptr_array_add(result, make_slot(content[i]->name, content[i]->icon, content[i]->raw, content[i]->nonselectable));
    }

    for (int i = 0; i < PAGE_SIZE; i++) slot_free(content[i]);
    return result;
}

/* Flaches Grid (PowerMenu-Stil): Kinder des aktuellen Knotens in Original-
 * Reihenfolge + angehängtes "Exit", KEINE Pagination. 1:1 Logik aus dem
 * is_powermenu-Zweig von render_menu() im Original. */
static GPtrArray* build_flat_slots(JsonObject *node) {
    GPtrArray *result = g_ptr_array_new_with_free_func(slot_free);
    if (json_object_has_member(node, "children")) {
        JsonArray *arr = json_object_get_array_member(node, "children");
        for (guint i = 0; i < json_array_get_length(arr); i++) {
            JsonObject *child = json_node_get_object(json_array_get_element(arr, i));
            const char *type = json_object_has_member(child, "type") ?
                json_object_get_string_member(child, "type") : NULL;
            if (g_strcmp0(type, "placeholder") == 0) {
                g_ptr_array_add(result, make_slot(" ", "", RAW_NOOP, FALSE));
            } else {
                const char *name = json_object_has_member(child, "name") ?
                    json_object_get_string_member(child, "name") : NULL;
                const char *icon = json_object_has_member(child, "icon") ?
                    json_object_get_string_member(child, "icon") : NULL;
                gchar *idx_str = g_strdup_printf("%u", i);
                g_ptr_array_add(result, make_slot(name ? name : "Unbekannt", icon ? icon : "", idx_str, FALSE));
                g_free(idx_str);
            }
        }
    }
    g_ptr_array_add(result, make_slot("Exit", "application-exit", RAW_EXIT, FALSE));
    return result;
}

/* =========================================================================
 * App-State + Rendering + Eingabe
 * ========================================================================= */
typedef struct {
    char *path;
    char *vmode;
    int page;
    int selected;
} HistoryEntry;

static void history_entry_free(gpointer data) {
    HistoryEntry *h = data;
    g_free(h->path);
    g_free(h->vmode);
    g_free(h);
}

typedef enum { ANIM_NONE = 0, ANIM_OPEN, ANIM_CLOSE, ANIM_SWITCH } AnimType;

typedef struct {
    GtkWidget *window;
    GtkWidget *area;
    JsonObject *root;
    char *menu_name;
    gboolean x11;
    gboolean is_powermenu;
    MenuState state;
    GPtrArray *slots;      /* aktuell sichtbare Slot* */
    int columns, rows;
    int total_pages;        /* 1 = keine Pagination (PowerMenu) */
    int selected;           /* Index in slots, -1 = nichts */
    BubbleAssets assets;
    NavAssets nav;          /* Pfeile (nur Baum-/vmode-Grids) */
    GPtrArray *history;      /* Stack von HistoryEntry* - für "Zurück" mit Gedächtnis */
    int hover_special;       /* 0=nichts, 1=linker Pfeil, 2=rechter Pfeil */
    /* Vorberechnete Klick-/Hover-Flächen für die Pfeile (nur Baum-/vmode-
     * Grids, bei PowerMenu ungenutzt/leer). Kein Back-Button mehr - Klick
     * außerhalb von Grid+Pfeilen = Zurück/Exit, siehe on_button_press. */
    int grid_x, grid_y;                 /* Ursprung des reinen 4x3-Contentgrids */
    int arrow_left_x, arrow_right_x, arrow_y;
    GHashTable *icon_cache; /* "name@size" -> GdkPixbuf* (owned) */
    int win_w, win_h;
    /* Animation: Öffnen/Schließen UND Seiten-/Ordnerwechsel benutzen jetzt
     * denselben Bounce-Mechanismus (ease_out_back) - beim Wechsel schrumpfen
     * die alten Bubbles raus (rückwärts) während die neuen reinpoppen
     * (vorwärts), an denselben Positionen. Kein Crossfade/Snapshot-Bild
     * mehr nötig, siehe draw_content()/switch_content(). */
    AnimType anim_type;
    gint64 anim_start_us;
    guint tick_id;
    GPtrArray *prev_slots; /* Kopie der ALTEN Slots, nur während ANIM_SWITCH gültig */
    /* Kleiner "Press"-Puls für die Pfeile bei Klick/q/e, UND das Ein-/
     * Ausblenden zwischen aktiv/inaktiv - beides über denselben
     * unabhängigen Tick-Loop, läuft auch wenn gerade keine Seite/kein
     * Inhalt wechselt (z.B. Pfeil ohne verfügbare Seite gedrückt). */
    int arrow_press_which;       /* 0=keiner, 1=links, 2=rechts */
    gint64 arrow_press_start_us;
    guint arrow_tick_id;
    gboolean arrow_had_prev, arrow_had_next; /* letzter gezeichneter aktiv/inaktiv-Stand */
    gint64 arrow_left_fade_us, arrow_right_fade_us; /* Start des letzten Zustandswechsels */
    gboolean anim_reversed; /* TRUE bei "rückwärts" (q/links/Zurück) - Stagger-Reihenfolge umgedreht */
    /* Kleiner Pop, wenn die Auswahl (WASD/Hover) auf eine andere Bubble
     * springt - NICHT beim Seiten-/Ordnerwechsel (das hat schon seine
     * eigene Animation), nur beim reinen Cursor-Bewegen auf derselben
     * Seite. -1 = gerade kein Bounce aktiv. */
    int sel_bounce_slot;
    gint64 sel_bounce_start_us;
} App;

static void rebuild_slots(App *app) {
    if (app->slots) g_ptr_array_unref(app->slots);
    app->slots = NULL;

    if (app->is_powermenu) {
        JsonObject *node = resolve_path(app->root, app->state.path);
        app->slots = build_flat_slots(node);
        app->columns = PM_COLUMNS;
        app->rows = PM_ROWS;
        app->total_pages = 1;
    } else if (app->state.vmode) {
        GPtrArray *apps = NULL;
        if (g_strcmp0(app->state.vmode, VMODE_DRUN) == 0) apps = get_desktop_apps();
        else if (g_strcmp0(app->state.vmode, VMODE_DRUN_FILTERED) == 0) apps = get_filtered_desktop_apps(app->root);
        else if (g_strcmp0(app->state.vmode, VMODE_RUN) == 0) apps = get_path_binaries();
        gboolean is_temp = FALSE;
        if (!apps) { apps = g_ptr_array_new(); is_temp = TRUE; }

        int total_pages = (apps->len + PAGE_SIZE - 1) / PAGE_SIZE;
        if (total_pages == 0) total_pages = 1;
        app->state.page = CLAMP(app->state.page, 0, total_pages - 1);

        GPtrArray *content = g_ptr_array_new_with_free_func(slot_free);
        guint start = app->state.page * PAGE_SIZE;
        for (guint i = start; i < start + PAGE_SIZE && i < apps->len; i++) {
            AppEntry *a = g_ptr_array_index(apps, i);
            gchar *idx_str = g_strdup_printf("%u", i);
            g_ptr_array_add(content, make_slot(a->name, a->icon, idx_str, FALSE));
            g_free(idx_str);
        }
        app->slots = build_grid_slots(content, FALSE); /* vmode-Listen sind nie "Wurzel" */
        g_ptr_array_unref(content);
        if (is_temp) g_ptr_array_unref(apps);
        app->columns = CONTENT_COLUMNS;
        app->rows = CONTENT_ROWS;
        app->total_pages = total_pages;
    } else {
        JsonObject *node = resolve_path(app->root, app->state.path);
        gboolean is_root = (!app->state.path || !*app->state.path);
        if (!json_object_has_member(node, "children")) {
            GPtrArray *empty = g_ptr_array_new_with_free_func(slot_free);
            app->slots = build_grid_slots(empty, is_root); /* leeres Content-Array -> alles Platzhalter */
            g_ptr_array_unref(empty);
            app->total_pages = 1;
        } else {
            JsonArray *arr = json_object_get_array_member(node, "children");
            guint total = json_array_get_length(arr);
            int total_pages = (total + PAGE_SIZE - 1) / PAGE_SIZE;
            if (total_pages == 0) total_pages = 1;
            app->state.page = CLAMP(app->state.page, 0, total_pages - 1);

            GPtrArray *content = g_ptr_array_new_with_free_func(slot_free);
            guint start = app->state.page * PAGE_SIZE;
            for (guint i = start; i < start + PAGE_SIZE && i < total; i++) {
                JsonObject *child = json_node_get_object(json_array_get_element(arr, i));
                const char *type = json_object_get_string_member(child, "type");
                if (g_strcmp0(type, "placeholder") == 0) {
                    g_ptr_array_add(content, make_slot(" ", "", RAW_NOOP, FALSE));
                } else {
                    const char *name = json_object_get_string_member(child, "name");
                    const char *icon = json_object_get_string_member(child, "icon");
                    gchar *idx_str = g_strdup_printf("%u", i);
                    g_ptr_array_add(content, make_slot(name ? name : "Unbekannt", icon ? icon : "", idx_str, FALSE));
                    g_free(idx_str);
                }
            }
            /* 3+1-Verteilung nur auf der ERSTEN Seite der Wurzel (dort war
             * sie ursprünglich auch nur gemeint) - ab Seite 2 ganz normal
             * sequenziell, falls die Wurzel jemals >12 Einträge hat. */
            app->slots = build_grid_slots(content, is_root && app->state.page == 0);
            g_ptr_array_unref(content);
            app->total_pages = total_pages;
        }
        app->columns = CONTENT_COLUMNS;
        app->rows = CONTENT_ROWS;
    }

    /* Auswahl auf erstes selektierbares Slot setzen/klemmen */
    if (app->slots->len == 0) { app->selected = -1; return; }
    if (app->selected < 0 || (guint)app->selected >= app->slots->len) app->selected = 0;
    Slot *cur = g_ptr_array_index(app->slots, app->selected);
    if (cur->nonselectable) {
        for (guint i = 0; i < app->slots->len; i++) {
            Slot *s = g_ptr_array_index(app->slots, i);
            if (!s->nonselectable) { app->selected = i; break; }
        }
    }
}

/* Layout einmalig beim Fenster-Bau berechnen (ändert sich über die
 * Laufzeit nicht mehr, columns/rows sind bei Baum-/vmode-Grids jetzt
 * IMMER 4x3 - PowerMenu behält sein altes flaches Grid ohne Pfeile/Back). */
static void compute_layout(App *app) {
    if (app->is_powermenu) {
        app->grid_x = PAD_PX;
        app->grid_y = PAD_PX;
        app->win_w = 2 * PAD_PX + app->columns * CELL_PX + (app->columns - 1) * GAP_PX;
        app->win_h = 2 * PAD_PX + app->rows * CELL_PX + (app->rows - 1) * GAP_PX;
        return;
    }
    int grid_w = CONTENT_COLUMNS * CELL_PX + (CONTENT_COLUMNS - 1) * GAP_PX;
    int grid_h = CONTENT_ROWS * CELL_PX + (CONTENT_ROWS - 1) * GAP_PX;
    app->grid_x = PAD_PX + ARROW_PX + ARROW_GAP_PX;
    app->grid_y = PAD_PX;
    app->arrow_left_x = PAD_PX;
    app->arrow_right_x = app->grid_x + grid_w + ARROW_GAP_PX;
    app->arrow_y = app->grid_y + grid_h / 2 - ARROW_PX / 2;
    app->win_w = app->grid_x + grid_w + ARROW_GAP_PX + ARROW_PX + PAD_PX;
    app->win_h = app->grid_y + grid_h + PAD_PX; /* kein Back-Button mehr - kein extra Zeilenplatz nötig */
}

/* ── Zeichnen ─────────────────────────────────────────────────────────── */
static void draw_pixbuf_cover(cairo_t *cr, GdkPixbuf *pb, double x, double y, double w, double h) {
    if (!pb) return;
    double pw = gdk_pixbuf_get_width(pb), ph = gdk_pixbuf_get_height(pb);
    cairo_save(cr);
    cairo_translate(cr, x, y);
    cairo_scale(cr, w / pw, h / ph);
    gdk_cairo_set_source_pixbuf(cr, pb, 0, 0);
    cairo_paint(cr);
    cairo_restore(cr);
}

/* Schriftgröße dynamisch runterregeln, bis der komplette Name in die
 * Zelle passt - nie abgeschnitten, nie größer als die Basisgröße (8pt).
 * Setzt width auf -1 (kein Zeilenumbruch) und lässt Pango die natürliche
 * Breite bei jeder Größe messen, bis sie passt oder die Mindestgröße
 * erreicht ist. */
#define TEXT_MAX_PX  15   /* Basis-/Maximalgröße, wie gewünscht */
#define TEXT_MIN_PX  5    /* Untergrenze, danach wird nicht weiter geschrumpft */
#define TEXT_MAX_LINES 3  /* mehr als 3 Zeilen sprengt den Kreis unten */

/* Schriftgröße + Zeilenumbruch gemeinsam so wählen, dass der Name
 * VOLLSTÄNDIG hineinpasst: erst Wortumbruch bei fester Breite (Pango
 * macht das automatisch), danach Schriftgröße von TEXT_MAX_PX bis
 * TEXT_MIN_PX runterregeln, bis sowohl Zeilenanzahl (<=3) als auch Höhe
 * in den verfügbaren Platz passen. Absolute Pixelgrößen (nicht pt), wie
 * gewünscht. */
static void fit_text_font(PangoLayout *layout, const char *text, int max_w_px, int max_h_px) {
    pango_layout_set_width(layout, max_w_px * PANGO_SCALE);
    pango_layout_set_wrap(layout, PANGO_WRAP_WORD_CHAR);
    pango_layout_set_alignment(layout, PANGO_ALIGN_CENTER);
    pango_layout_set_text(layout, text, -1);
    double size = TEXT_MAX_PX;
    for (;;) {
        PangoFontDescription *desc = pango_font_description_new();
        pango_font_description_set_family(desc, "Sans");
        pango_font_description_set_weight(desc, PANGO_WEIGHT_BOLD);
        pango_font_description_set_absolute_size(desc, size * PANGO_SCALE);
        pango_layout_set_font_description(layout, desc);
        pango_font_description_free(desc);
        int line_count = pango_layout_get_line_count(layout);
        int w, h;
        pango_layout_get_pixel_size(layout, &w, &h);
        (void)w;
        if ((line_count <= TEXT_MAX_LINES && h <= max_h_px) || size <= TEXT_MIN_PX) break;
        size -= 0.5;
    }
}

static void draw_bubble_cell(App *app, cairo_t *cr, PangoLayout *layout, double x, double y,
                              GdkPixbuf *icon_pb, const char *name, gboolean selected) {
    /* 1) Back-Bubble */
    draw_pixbuf_cover(cr, selected ? app->assets.back_selected : app->assets.back_normal,
                      x, y, CELL_PX, CELL_PX);

    /* 2) Icon */
    if (icon_pb) {
        double icon_x = x + (CELL_PX - ICON_PX) / 2.0;
        double icon_y = y + ELEMENT_PAD_PX + ICON_MARGIN_PX;
        gdk_cairo_set_source_pixbuf(cr, icon_pb, icon_x, icon_y);
        cairo_paint(cr);
    }

    /* 3) Text - mehrzeilig (max 3 Zeilen), Schrift wird pro Zelle passend
     * zu Länge UND verfügbarer Höhe skaliert (siehe fit_text_font).
     * Feste Layout-Breite + ALIGN_CENTER übernimmt jetzt die Zentrierung
     * selbst, kein manuelles Ausmessen mehr nötig. */
    if (name && *name) {
        int max_w = CELL_PX - 2 * ELEMENT_PAD_PX;
        int max_h = CELL_PX - (ELEMENT_PAD_PX + ICON_PX + 2 * ICON_MARGIN_PX) - 8;
        fit_text_font(layout, name, max_w, max_h);
        double text_x = x + ELEMENT_PAD_PX;
        double text_y = y + ELEMENT_PAD_PX + ICON_PX + 2 * ICON_MARGIN_PX;
        cairo_set_source_rgba(cr, selected ? 1.0 : 0.86, selected ? 1.0 : 0.82,
                               selected ? 1.0 : 1.0, 1.0);
        cairo_move_to(cr, text_x, text_y);
        pango_cairo_show_layout(cr, layout);
    }

    /* 4) Front-Bubble - liegt jetzt WIRKLICH vor Icon und Text */
    draw_pixbuf_cover(cr, selected ? app->assets.front_selected : app->assets.front_normal,
                      x, y, CELL_PX, CELL_PX);
}

static void clear_transparent(cairo_t *cr) {
    cairo_save(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    cairo_restore(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
}

/* Zeichnet Grid + Pfeile OHNE vorheriges Clear (Aufrufer entscheidet, ob/
 * wann geklärt wird - beim Crossfade z.B. erst NACH dem alten Snapshot).
 * bubble_scale skaliert jede Bubble/Pfeil um ihren EIGENEN Mittelpunkt -
 * für den Öffnen/Schließen-Bounce (siehe ease_out_back). 1.0 = normal. */
#define ANIM_POP_US       65000.0   /* Pop-Dauer EINER Bubble, wie gewünscht */
#define ANIM_STAGGER_US   23000.0   /* Startzeit-Versatz pro Bubble in Lesereihenfolge */
#define ARROW_PRESS_US    150000.0  /* Dauer des kleinen Press-Pulses auf einem Pfeil */
#define ARROW_STATE_FADE_US 150000.0 /* Dauer des Ein-/Ausblendens aktiv<->inaktiv */
#define ARROW_ALPHA_INACTIVE 0.4    /* etwas sichtbarer als vorher (war 0.25) */
#define ARROW_ALPHA_ACTIVE   0.65   /* von Haus aus dezenter (war 1.0) */
#define ARROW_ALPHA_HOVER    1.0    /* beim Draufzeigen voll sichtbar */
#define SEL_BOUNCE_US        150000.0 /* kleiner Pop beim Auswahlwechsel (WASD/Hover) */
#define SEL_BOUNCE_AMOUNT    0.12     /* wie stark - bewusst klein/dezent */

/* Gesamtdauer der Öffnen/Schließen-Animation für n_slots Bubbles: die
 * letzte Bubble startet erst nach (n-1)*STAGGER und braucht dann noch
 * einmal die volle POP-Dauer. */
/* Klassische "Ease-Out-Back"-Kurve: startet bei 0, überschwingt kurz vor
 * dem Ziel leicht über 1.0, federt auf genau 1.0 zurück - exakt die
 * gewünschte kleine "Pop"-Bounce beim Öffnen. Für's Schließen wird sie
 * einfach rückwärts durchlaufen (ease_out_back(1-t)). */
static double ease_out_back(double t) {
    if (t < 0.0) t = 0.0;
    if (t > 1.0) t = 1.0;
    const double c1 = 1.70158;
    const double c3 = c1 + 1.0;
    double tm1 = t - 1.0;
    return 1.0 + c3 * tm1 * tm1 * tm1 + c1 * tm1 * tm1;
}

static double anim_total_duration_us(guint n_slots) {
    if (n_slots == 0) return ANIM_POP_US;
    return (n_slots - 1) * ANIM_STAGGER_US + ANIM_POP_US;
}

static GPtrArray* copy_slots(GPtrArray *src) {
    GPtrArray *copy = g_ptr_array_new_with_free_func(slot_free);
    for (guint i = 0; i < src->len; i++) {
        Slot *s = g_ptr_array_index(src, i);
        g_ptr_array_add(copy, make_slot(s->name, s->icon, s->raw, s->nonselectable));
    }
    return copy;
}

/* Zeichnet EIN Slots-Array (entweder die aktuellen ODER die alten, vor
 * einem Wechsel kopierten). animate=FALSE -> immer volle Größe (normales
 * Zeichnen). animate=TRUE -> jede Bubble bekommt ihre eigene, um
 * i*STAGGER verzögerte Pop-Animation (Lesereihenfolge 1 2 3/4 5 6/...);
 * growing=TRUE lässt sie reinwachsen (Öffnen/neuer Inhalt beim Wechsel),
 * growing=FALSE rausschrumpfen (Schließen/alter Inhalt beim Wechsel). */
static void draw_bubbles(App *app, cairo_t *cr, PangoLayout *layout, GPtrArray *slots,
                          gboolean animate, gboolean growing, gint64 elapsed_us, int selected_idx) {
    if (!slots) return;

    for (guint i = 0; i < slots->len; i++) {
        Slot *s = g_ptr_array_index(slots, i);
        int col = i % app->columns;
        int row = i / app->columns;
        double x = app->grid_x + col * (CELL_PX + GAP_PX);
        double y = app->grid_y + row * (CELL_PX + GAP_PX);
        gboolean selected = ((int)i == selected_idx);
        gboolean is_empty_placeholder =
            (!s->name || g_strcmp0(s->name, " ") == 0) && !(s->icon && *s->icon);

        GdkPixbuf *icon_pb = NULL;
        if (!is_empty_placeholder && s->icon && *s->icon)
            icon_pb = load_icon_pixbuf(app->icon_cache, s->icon, ICON_PX);

        double scale = 1.0;
        if (animate) {
            /* Bei "rückwärts" (q/links/Zurück) läuft die Stagger-Reihenfolge
             * umgedreht (letzte Bubble zuerst) statt in Lesereihenfolge. */
            guint stagger_idx = app->anim_reversed ? (slots->len - 1 - i) : i;
            double bubble_elapsed = elapsed_us - (double)stagger_idx * ANIM_STAGGER_US;
            double bt = (bubble_elapsed <= 0.0) ? 0.0
                       : (bubble_elapsed >= ANIM_POP_US) ? 1.0
                       : bubble_elapsed / ANIM_POP_US;
            scale = growing ? ease_out_back(bt) : ease_out_back(1.0 - bt);
            /* cairo_scale(cr, 0, 0) erzeugt eine singuläre Matrix (nicht
             * invertierbar) - das lässt Cairo/X11 mit "out of memory"
             * abstürzen, sobald mehrere Bubbles gleichzeitig exakt bei
             * Skalierung 0 stehen (z.B. Frame 1: alle noch nicht
             * gestarteten Bubbles). Deshalb hartes Minimum statt echter 0. */
            if (scale < 0.001) scale = 0.001;
        }

        /* Kleiner Auswahl-Pop (WASD/Hover) - unabhängig vom Öffnen/
         * Schließen/Wechsel-System, nur auf der GERADE frisch
         * ausgewählten Bubble, kurz und dezent. */
        if ((int)i == app->sel_bounce_slot) {
            gint64 be = g_get_monotonic_time() - app->sel_bounce_start_us;
            double bt = be / SEL_BOUNCE_US;
            if (bt < 0.0) bt = 0.0;
            if (bt > 1.0) bt = 1.0;
            scale *= 1.0 + SEL_BOUNCE_AMOUNT * sin(bt * G_PI);
        }

        gboolean scaling = (scale != 1.0);
        if (scaling) {
            cairo_save(cr);
            double cx = x + CELL_PX / 2.0, cy = y + CELL_PX / 2.0;
            cairo_translate(cr, cx, cy);
            cairo_scale(cr, scale, scale);
            cairo_translate(cr, -cx, -cy);
        }
        draw_bubble_cell(app, cr, layout, x, y, icon_pb,
                          is_empty_placeholder ? NULL : s->name, selected);
        if (scaling) cairo_restore(cr);
    }
}

/* anim_type steuert nur noch Öffnen/Schließen/Wechsel insgesamt - die
 * eigentliche Pop-Logik pro Bubble steckt jetzt in draw_bubbles(). Beim
 * Wechsel (ANIM_SWITCH) werden die alten Bubbles (prev_slots) zuerst
 * rausschrumpfend gezeichnet, danach die neuen (app->slots) reinwachsend
 * darüber - an denselben Positionen, kein Crossfade/Snapshot-Bild mehr. */
static void ensure_arrow_tick(App *app); /* Vorwärtsdeklaration - Definition weiter unten */

static void draw_content(App *app, cairo_t *cr, AnimType anim_type, gint64 elapsed_us) {
    if (!app->slots) return;

    PangoLayout *layout = pango_cairo_create_layout(cr);
    pango_layout_set_alignment(layout, PANGO_ALIGN_LEFT);

    if (anim_type == ANIM_SWITCH && app->prev_slots)
        draw_bubbles(app, cr, layout, app->prev_slots, TRUE, FALSE, elapsed_us, -1);

    gboolean animate = (anim_type == ANIM_OPEN || anim_type == ANIM_CLOSE || anim_type == ANIM_SWITCH);
    gboolean growing = (anim_type == ANIM_OPEN || anim_type == ANIM_SWITCH);
    /* Beim Wechsel soll die neue Bubble erst REINPOPPEN, wenn die alte an
     * DERSELBEN Stelle komplett rausgeschrumpft ist - nicht gleichzeitig
     * (siehe Feedback: "2 Blasen übereinander, sollten hintereinander
     * sein"). Deshalb hier um eine volle POP-Dauer nach hinten verschoben. */
    gint64 new_elapsed = (anim_type == ANIM_SWITCH) ? elapsed_us - (gint64)ANIM_POP_US : elapsed_us;
    draw_bubbles(app, cr, layout, app->slots, animate, growing, new_elapsed, app->selected);

    if (!app->is_powermenu) {
        gboolean has_prev = app->state.page > 0;
        gboolean has_next = app->state.page < app->total_pages - 1;
        gboolean hover_left = (app->hover_special == 1);
        gboolean hover_right = (app->hover_special == 2);

        /* Aktiv/inaktiv-Wechsel erkennen -> kurzes Ein-/Ausblenden starten
         * (Punkt: "Pfeil-Animation machen" - Zustandswechsel soll nicht
         * hart umschalten). */
        gint64 now = g_get_monotonic_time();
        if (has_prev != app->arrow_had_prev) { app->arrow_had_prev = has_prev; app->arrow_left_fade_us = now; ensure_arrow_tick(app); }
        if (has_next != app->arrow_had_next) { app->arrow_had_next = has_next; app->arrow_right_fade_us = now; ensure_arrow_tick(app); }

        double lft = (now - app->arrow_left_fade_us) / ARROW_STATE_FADE_US;
        if (lft < 0.0) lft = 0.0;
        if (lft > 1.0) lft = 1.0;
        double left_from  = has_prev ? ARROW_ALPHA_INACTIVE : ARROW_ALPHA_ACTIVE;
        double left_to    = has_prev ? ARROW_ALPHA_ACTIVE   : ARROW_ALPHA_INACTIVE;
        double left_base_alpha = left_from + (left_to - left_from) * lft;

        double rft = (now - app->arrow_right_fade_us) / ARROW_STATE_FADE_US;
        if (rft < 0.0) rft = 0.0;
        if (rft > 1.0) rft = 1.0;
        double right_from = has_next ? ARROW_ALPHA_INACTIVE : ARROW_ALPHA_ACTIVE;
        double right_to   = has_next ? ARROW_ALPHA_ACTIVE   : ARROW_ALPHA_INACTIVE;
        double right_base_alpha = right_from + (right_to - right_from) * rft;

        double left_alpha  = hover_left  ? ARROW_ALPHA_HOVER : left_base_alpha;
        double right_alpha = hover_right ? ARROW_ALPHA_HOVER : right_base_alpha;

        /* Pfeile sind keine "Blasen" - eigene, ungestaffelte Pop-Animation,
         * bewusst LANGSAMER/SPÄTER als die Bubbles (erst nach allen
         * Bubble-Startzeiten) - sie sind nicht so wichtig (in der Wurzel
         * z.B. oft unsichtbar) und müssen nicht zuerst da sein. Nehmen an
         * ANIM_SWITCH nicht teil - Wechsel ist nur für die Bubblen. */
        double arrow_scale = 1.0;
        if (anim_type == ANIM_OPEN || anim_type == ANIM_CLOSE) {
            guint n = app->slots->len;
            double arrow_delay = n > 0 ? (double)(n - 1) * ANIM_STAGGER_US : 0.0;
            double ae = elapsed_us - arrow_delay;
            double at = (ae <= 0.0) ? 0.0 : (ae >= ANIM_POP_US) ? 1.0 : ae / ANIM_POP_US;
            arrow_scale = (anim_type == ANIM_OPEN) ? ease_out_back(at) : ease_out_back(1.0 - at);
            if (arrow_scale < 0.001) arrow_scale = 0.001; /* siehe Kommentar oben - keine echte 0 */
        }

        /* Kleiner Press-Puls bei Klick/q/e (unabhängig vom Öffnen/Schließen/
         * Wechsel-System, siehe trigger_arrow_press) - kurz zusammenziehen,
         * dann zurückfedern. */
        double press_left = 1.0, press_right = 1.0;
        if (app->arrow_press_which != 0) {
            gint64 pe = g_get_monotonic_time() - app->arrow_press_start_us;
            double pt = pe / ARROW_PRESS_US;
            if (pt < 0.0) pt = 0.0;
            if (pt > 1.0) pt = 1.0;
            double bump = sin(pt * G_PI) * 0.18;
            if (app->arrow_press_which == 1) press_left = 1.0 - bump;
            else if (app->arrow_press_which == 2) press_right = 1.0 - bump;
        }
        double left_scale = arrow_scale * press_left;
        double right_scale = arrow_scale * press_right;

        /* Glow-Bild nur beim tatsächlichen Hover, sonst normales Bild -
         * Glow fällt (siehe load_nav_assets) auf das normale Bild zurück
         * falls die *Glow.png fehlt, damit der Pfeil beim Hover nie
         * komplett verschwindet. */
        GdkPixbuf *left_pb = hover_left ? app->nav.arrow_left_glow : app->nav.arrow_left_normal;
        if (left_pb) {
            gboolean scaling = (left_scale != 1.0);
            if (scaling) {
                cairo_save(cr);
                double cx = app->arrow_left_x + ARROW_PX / 2.0, cy = app->arrow_y + ARROW_PX / 2.0;
                cairo_translate(cr, cx, cy);
                cairo_scale(cr, left_scale, left_scale);
                cairo_translate(cr, -cx, -cy);
            }
            gdk_cairo_set_source_pixbuf(cr, left_pb, app->arrow_left_x, app->arrow_y);
            cairo_paint_with_alpha(cr, left_alpha);
            if (scaling) cairo_restore(cr);
        }
        GdkPixbuf *right_pb = hover_right ? app->nav.arrow_right_glow : app->nav.arrow_right_normal;
        if (right_pb) {
            gboolean scaling = (right_scale != 1.0);
            if (scaling) {
                cairo_save(cr);
                double cx = app->arrow_right_x + ARROW_PX / 2.0, cy = app->arrow_y + ARROW_PX / 2.0;
                cairo_translate(cr, cx, cy);
                cairo_scale(cr, right_scale, right_scale);
                cairo_translate(cr, -cx, -cy);
            }
            gdk_cairo_set_source_pixbuf(cr, right_pb, app->arrow_right_x, app->arrow_y);
            cairo_paint_with_alpha(cr, right_alpha);
            if (scaling) cairo_restore(cr);
        }
    }

    g_object_unref(layout);
}

static gboolean on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data) {
    App *app = (App*)user_data;
    (void)widget;

    clear_transparent(cr);
    if (!app->slots) return FALSE;

    if (app->anim_type == ANIM_NONE) {
        draw_content(app, cr, ANIM_NONE, 0);
        return FALSE;
    }

    gint64 elapsed = g_get_monotonic_time() - app->anim_start_us;
    draw_content(app, cr, app->anim_type, elapsed);
    return FALSE;
}

/* ── Zellindex aus Pixelkoordinaten ─────────────────────────────────────── */
static int slot_at_xy(App *app, double px, double py) {
    if (px < app->grid_x || py < app->grid_y) return -1;
    int col = (int)((px - app->grid_x) / (CELL_PX + GAP_PX));
    int row = (int)((py - app->grid_y) / (CELL_PX + GAP_PX));
    if (col < 0 || col >= app->columns || row < 0 || row >= app->rows) return -1;
    double local_x = px - app->grid_x - col * (CELL_PX + GAP_PX);
    double local_y = py - app->grid_y - row * (CELL_PX + GAP_PX);
    if (local_x > CELL_PX || local_y > CELL_PX) return -1; /* im Gap */
    int idx = row * app->columns + col;
    if (!app->slots || (guint)idx >= app->slots->len) return -1;
    return idx;
}

/* 0=nichts, 1=linker Pfeil, 2=rechter Pfeil - Pfeile sind IMMER als
 * Fläche da (auch wenn gerade keine vorherige/nächste Seite existiert),
 * damit der Bereich nie zum "Leerbereich" wird - sonst würde Pfeil-Spam
 * ohne verfügbare Seite versehentlich als Zurück/Exit-Klick zählen.
 * Ob der Klick tatsächlich was tut, entscheidet on_button_press anhand
 * von has_prev/has_next. */
static int special_at_xy(App *app, double px, double py) {
    if (app->is_powermenu) return 0;
    if (px >= app->arrow_left_x && px < app->arrow_left_x + ARROW_PX &&
        py >= app->arrow_y && py < app->arrow_y + ARROW_PX)
        return 1;
    if (px >= app->arrow_right_x && px < app->arrow_right_x + ARROW_PX &&
        py >= app->arrow_y && py < app->arrow_y + ARROW_PX)
        return 2;
    return 0;
}

/* Grid-Grenzen (ohne Pfeile) - für den "Leerbereich = Zurück/Exit"-Klick,
 * siehe on_button_press. Nur sinnvoll für Baum-/vmode-Grids. */
static gboolean point_in_grid_bounds(App *app, double px, double py) {
    int grid_w = CONTENT_COLUMNS * CELL_PX + (CONTENT_COLUMNS - 1) * GAP_PX;
    int grid_h = CONTENT_ROWS * CELL_PX + (CONTENT_ROWS - 1) * GAP_PX;
    return px >= app->grid_x && px < app->grid_x + grid_w &&
           py >= app->grid_y && py < app->grid_y + grid_h;
}

/* ── Aktionen ────────────────────────────────────────────────────────── */
static gboolean g_daemon_mode = FALSE; /* --daemon: Fenster verstecken statt Prozess beenden */

static void reset_app_state(App *app) {
    g_free(app->state.path);
    g_free(app->state.vmode);
    app->state.path = g_strdup("");
    app->state.vmode = NULL;
    app->state.page = 0;
    app->selected = 0; /* Menü öffnen -> immer oben links (Punkt 4) */
    app->hover_special = 0;
    if (app->history) { g_ptr_array_unref(app->history); app->history = NULL; }
    app->history = g_ptr_array_new_with_free_func(history_entry_free); /* Historie weg - frischer Start */
}

static void hide_app(App *app) {
    gtk_widget_hide(app->window);
    reset_app_state(app); /* nächstes Zeigen startet immer sauber in der Wurzel */
}

/* Treibt die Öffnen/Schließen/Crossfade-Animation per Frame-Clock-Tick an
 * (vsync-synchron, glatter als ein fester g_timeout_add-Takt). Läuft bis
 * die Gesamtdauer erreicht ist, danach räumt sie sich selbst ab. */
static gboolean on_anim_tick(GtkWidget *widget, GdkFrameClock *frame_clock, gpointer user_data) {
    App *app = user_data;
    (void)widget; (void)frame_clock;

    gint64 elapsed = g_get_monotonic_time() - app->anim_start_us;
    guint n_new = app->slots ? app->slots->len : 0;
    guint n_old = app->prev_slots ? app->prev_slots->len : 0;
    double duration;
    if (app->anim_type == ANIM_SWITCH) {
        /* Alte Bubbles schrumpfen erst komplett raus, NEUE starten danach
         * erst (siehe draw_content: new_elapsed = elapsed - ANIM_POP_US) -
         * Gesamtdauer ist daher alt-fertig + neue-eigene-Gesamtdauer. */
        double old_done = anim_total_duration_us(n_old);
        double new_done = ANIM_POP_US + anim_total_duration_us(n_new);
        duration = (old_done > new_done) ? old_done : new_done;
    } else {
        duration = anim_total_duration_us(n_new);
    }

    gtk_widget_queue_draw(app->area);

    if (elapsed >= duration) {
        AnimType finishing = app->anim_type;
        app->anim_type = ANIM_NONE;
        app->tick_id = 0;
        if (app->prev_slots) { g_ptr_array_unref(app->prev_slots); app->prev_slots = NULL; }
        if (finishing == ANIM_CLOSE) {
            if (g_daemon_mode) hide_app(app); else gtk_main_quit();
        }
        gtk_widget_queue_draw(app->area);
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void ensure_anim_tick(App *app) {
    if (app->tick_id) { gtk_widget_remove_tick_callback(app->area, app->tick_id); app->tick_id = 0; }
    app->tick_id = gtk_widget_add_tick_callback(app->area, on_anim_tick, app, NULL);
}

/* Treibt sowohl den Press-Puls als auch das Ein-/Ausblenden aktiv<->
 * inaktiv an - läuft weiter, solange IRGENDEINS von beiden noch aktiv
 * ist, unabhängig vom Öffnen/Schließen/Wechsel-System. */
static gboolean on_arrow_tick(GtkWidget *widget, GdkFrameClock *frame_clock, gpointer user_data) {
    App *app = user_data;
    (void)widget; (void)frame_clock;
    gint64 now = g_get_monotonic_time();
    gtk_widget_queue_draw(app->area);

    gboolean press_active = (app->arrow_press_which != 0) &&
        ((now - app->arrow_press_start_us) < (gint64)ARROW_PRESS_US);
    if (app->arrow_press_which != 0 && !press_active) app->arrow_press_which = 0;

    gboolean left_fade_active  = (now - app->arrow_left_fade_us)  < (gint64)ARROW_STATE_FADE_US;
    gboolean right_fade_active = (now - app->arrow_right_fade_us) < (gint64)ARROW_STATE_FADE_US;

    gboolean bounce_active = (app->sel_bounce_slot >= 0) &&
        ((now - app->sel_bounce_start_us) < (gint64)SEL_BOUNCE_US);
    if (app->sel_bounce_slot >= 0 && !bounce_active) app->sel_bounce_slot = -1;

    if (press_active || left_fade_active || right_fade_active || bounce_active) return G_SOURCE_CONTINUE;

    app->arrow_tick_id = 0;
    gtk_widget_queue_draw(app->area);
    return G_SOURCE_REMOVE;
}

static void ensure_arrow_tick(App *app) {
    if (!app->arrow_tick_id)
        app->arrow_tick_id = gtk_widget_add_tick_callback(app->area, on_arrow_tick, app, NULL);
}

/* Kleiner Press-Puls auf dem Pfeil - immer ausgelöst (Klick, q/e), auch
 * wenn die Seite dadurch gar nicht wechselt (kein Vorher/Nachher
 * verfügbar) - eigener Tick, unabhängig vom Öffnen/Schließen/Wechsel-
 * System, damit's IMMER ein bisschen Feedback gibt. */
static void trigger_arrow_press(App *app, int which) {
    app->arrow_press_which = which;
    app->arrow_press_start_us = g_get_monotonic_time();
    ensure_arrow_tick(app);
}

/* Kleiner Pop auf der Bubble, die gerade per WASD/Hover neu ausgewählt
 * wurde - reiner Cursor-Wechsel auf derselben Seite, kein Seiten-/
 * Ordnerwechsel (der hat schon seine eigene Animation). */
static void mark_selection_bounce(App *app, int idx) {
    app->sel_bounce_slot = idx;
    app->sel_bounce_start_us = g_get_monotonic_time();
    ensure_arrow_tick(app);
}

/* Zeigt app, versteckt other (falls gerade offen) - immer nur ein Fenster
 * gleichzeitig sichtbar. Alles (Fenster, Assets, Icon-Cache) existiert im
 * Daemon-Modus schon fertig gebaut - hier passiert nur noch show/hide,
 * kein GTK-Init, kein PNG-Decode, kein Icon-Theme-Lookup mehr -> instant. */
static void show_app(App *app, App *other) {
    if (other && other != app && gtk_widget_get_visible(other->window)) hide_app(other);
    reset_app_state(app);
    save_active_window(); /* für close-prev-window/Action-Fokus-Poll - muss bei JEDEM Öffnen frisch sein */
    rebuild_slots(app);
    gtk_widget_show_all(app->window);
    gtk_window_present(GTK_WINDOW(app->window));
    app->anim_type = ANIM_OPEN;
    app->anim_reversed = FALSE;
    app->anim_start_us = g_get_monotonic_time();
    ensure_anim_tick(app);
}

static void quit_app(App *app) {
    cleanup_files();
    if (app->anim_type == ANIM_CLOSE) return; /* schließt schon */
    app->anim_type = ANIM_CLOSE;
    app->anim_reversed = FALSE;
    app->anim_start_us = g_get_monotonic_time();
    ensure_anim_tick(app);
}

static void rerender(App *app) {
    rebuild_slots(app);
    gtk_widget_queue_draw(app->area);
}

/* Für Seiten-/Ordner-/vmode-Wechsel statt rerender(): sichert den
 * aktuellen Stand (app->slots wie er JETZT noch ist, VOR dem Wechsel) als
 * Crossfade-"Vorher"-Bild, baut dann die neuen Slots und startet den
 * Crossfade. Kein Bounce hier - nur beim eigentlichen Öffnen/Schließen
 * des ganzen Menüs (siehe show_app/quit_app). */
static void switch_content(App *app, gboolean reversed) {
    if (app->prev_slots) { g_ptr_array_unref(app->prev_slots); app->prev_slots = NULL; }
    app->prev_slots = copy_slots(app->slots);
    rebuild_slots(app);
    app->anim_type = ANIM_SWITCH;
    app->anim_reversed = reversed;
    app->anim_start_us = g_get_monotonic_time();
    ensure_anim_tick(app);
}

/* Setzt die Auswahl auf idx, falls dort ein selektierbarer Slot sitzt;
 * sonst bleibt, was vorher da war (z.B. der sichere Default aus
 * rebuild_slots()). Rückgabe: ob idx tatsächlich übernommen wurde. */
static gboolean try_select(App *app, int idx) {
    if (idx < 0 || !app->slots || (guint)idx >= app->slots->len) return FALSE;
    Slot *s = g_ptr_array_index(app->slots, idx);
    if (s->nonselectable) return FALSE;
    app->selected = idx;
    return TRUE;
}

/* Navigations-Historie: beim Reingehen (Ordner/vmode) wird der aktuelle
 * Zustand VOR dem Wechsel gepusht (inkl. genauer Auswahlposition). "Zurück"
 * poppt das exakt wieder - man landet also wieder auf der Kachel, aus der
 * man reingegangen ist, nicht irgendwo neu. Rein-Gehen selbst setzt die
 * Auswahl der neuen Seite auf oben-links (siehe activate_slot). */
static void push_history(App *app) {
    HistoryEntry *h = g_new0(HistoryEntry, 1);
    h->path = g_strdup(app->state.path);
    h->vmode = g_strdup(app->state.vmode);
    h->page = app->state.page;
    h->selected = app->selected;
    g_ptr_array_add(app->history, h);
}

static void go_back_or_exit(App *app) {
    if (app->history->len > 0) {
        HistoryEntry *h = g_ptr_array_steal_index(app->history, app->history->len - 1);
        if (app->prev_slots) { g_ptr_array_unref(app->prev_slots); app->prev_slots = NULL; }
        app->prev_slots = copy_slots(app->slots); /* aktueller (alter) Stand, vor der Umschaltung */
        g_free(app->state.path);
        g_free(app->state.vmode);
        app->state.path = h->path;
        app->state.vmode = h->vmode;
        app->state.page = h->page;
        int restore_sel = h->selected;
        g_free(h);
        play_sound("FocusChange");
        rebuild_slots(app);
        try_select(app, restore_sel);
        app->anim_type = ANIM_SWITCH;
        app->anim_reversed = TRUE; /* Zurück = rückwärts */
        app->anim_start_us = g_get_monotonic_time();
        ensure_anim_tick(app);
    } else {
        quit_app(app);
    }
}

static void activate_slot(App *app, Slot *s) {
    if (!s || s->nonselectable) return;

    if (g_strcmp0(s->raw, RAW_EXIT) == 0) { quit_app(app); return; }
    if (g_strcmp0(s->raw, RAW_BACK) == 0) { go_back_or_exit(app); return; }

    if (!is_number(s->raw)) return;
    int idx = atoi(s->raw);

    if (app->state.vmode) {
        GPtrArray *apps = NULL;
        if (g_strcmp0(app->state.vmode, VMODE_DRUN) == 0) apps = get_desktop_apps();
        else if (g_strcmp0(app->state.vmode, VMODE_DRUN_FILTERED) == 0) apps = get_filtered_desktop_apps(app->root);
        else if (g_strcmp0(app->state.vmode, VMODE_RUN) == 0) apps = get_path_binaries();
        if (apps && idx >= 0 && (guint)idx < apps->len) {
            AppEntry *a = g_ptr_array_index(apps, idx);
            if (a && a->exec) { exec_detached(a->exec); quit_app(app); return; }
        }
        rerender(app);
        return;
    }

    JsonObject *node = resolve_path(app->root, app->state.path);
    if (!json_object_has_member(node, "children")) { rerender(app); return; }
    JsonArray *arr = json_object_get_array_member(node, "children");
    if (idx < 0 || (guint)idx >= json_array_get_length(arr)) { rerender(app); return; }
    JsonObject *child = json_node_get_object(json_array_get_element(arr, idx));
    const char *type = json_object_get_string_member(child, "type");
    if (!type) type = "app";

    if (g_strcmp0(type, "folder") == 0) {
        char *new_path;
        if (app->state.path && *app->state.path)
            new_path = g_strdup_printf("%s/%d", app->state.path, idx);
        else
            new_path = g_strdup_printf("%d", idx);
        push_history(app);
        g_free(app->state.path);
        app->state.path = new_path;
        app->state.page = 0;
        app->selected = 0; /* Reingehen -> immer oben links starten (rebuild_slots weicht
                               automatisch aus, falls Platz 0 ein Platzhalter ist) */
        play_sound("FocusChange");
        switch_content(app, FALSE); /* Reingehen = vorwärts */
        return;
    }
    if (g_strcmp0(type, "close-prev-window") == 0) {
        char *addr = read_prev_window_addr();
        if (addr && *addr) {
            gchar *lua = g_strdup_printf("hl.dsp.window.close({ window = \"address:%s\" })", addr);
            gchar *lua_q = g_shell_quote(lua);
            gchar *cmd = g_strdup_printf("hyprctl dispatch %s", lua_q);
            exec_detached(cmd);
            g_free(cmd); g_free(lua_q); g_free(lua);
        }
        g_free(addr);
        quit_app(app);
        return;
    }
    if (g_strcmp0(type, "special-drun") == 0 || g_strcmp0(type, "special-drun-filtered") == 0 ||
        g_strcmp0(type, "special-run") == 0) {
        push_history(app);
        g_free(app->state.vmode);
        if (g_strcmp0(type, "special-drun") == 0) app->state.vmode = g_strdup(VMODE_DRUN);
        else if (g_strcmp0(type, "special-drun-filtered") == 0) app->state.vmode = g_strdup(VMODE_DRUN_FILTERED);
        else app->state.vmode = g_strdup(VMODE_RUN);
        app->state.page = 0;
        app->selected = 0; /* Reingehen -> immer oben links starten */
        play_sound("FocusChange");
        switch_content(app, FALSE); /* Reingehen = vorwärts */
        return;
    }
    if (g_strcmp0(type, "special-window") == 0) {
        /* NICHT konvertiert - offener Fenster-Switcher ist ein eigenes,
         * grundlegend anderes Feature (Live-Fensterliste) und war nicht
         * Teil des "Bubble-Grid ohne rofi"-Auftrags. Nutzt weiterhin rofi
         * als Subprozess für DIESEN einen Punkt, exakt wie im Original. */
        char *mon = focused_monitor_name();
        gchar *theme_path = g_build_filename(g_get_home_dir(), ".config", "rofi", app->menu_name, "theme.rasi", NULL);
        GString *cmd = g_string_new("rofi -show window ");
        if (app->x11) g_string_append(cmd, "-x11 ");
        if (mon) {
            gchar *mon_q = g_shell_quote(mon);
            g_string_append_printf(cmd, "-monitor %s ", mon_q);
            g_free(mon_q);
        }
        gchar *theme_q = g_shell_quote(theme_path);
        g_string_append_printf(cmd, "-theme %s", theme_q);
        g_free(theme_q);
        static const char *WASD_KB_ARGS[] = {
            "-kb-row-up", "Up,Control+p,w", "-kb-row-down", "Down,Control+n,s",
            "-kb-row-left", "Control+Page_Up,a", "-kb-row-right", "Control+Page_Down,d",
            "-kb-accept-entry", "Control+j,Control+m,Return,KP_Enter,space,less",
            "-kb-custom-1", "q", "-kb-custom-2", "e", "-kb-custom-3", "x", NULL
        };
        for (int k = 0; WASD_KB_ARGS[k]; k++) {
            gchar *aq = g_shell_quote(WASD_KB_ARGS[k]);
            g_string_append_printf(cmd, " %s", aq);
            g_free(aq);
        }
        exec_detached(cmd->str);
        g_string_free(cmd, TRUE);
        g_free(theme_path);
        g_free(mon);
        quit_app(app);
        return;
    }

    /* "action" / "app": exec-Feld ausführen */
    const char *exec_cmd = json_object_get_string_member(child, "exec");
    if (exec_cmd && *exec_cmd) {
        if (g_strcmp0(type, "action") == 0) {
            char *addr = read_prev_window_addr();
            if (addr && *addr) {
                gchar *poll_cmd = g_strdup_printf(
                    "for i in $(seq 1 20); do "
                    "cur=$(hyprctl activewindow -j 2>>/tmp/bubble-menu-action.log | "
                    "jq -r .address 2>>/tmp/bubble-menu-action.log); "
                    "[ \"$cur\" = \"%s\" ] && break; "
                    "hyprctl dispatch focuswindow address:%s >>/tmp/bubble-menu-action.log 2>&1; "
                    "sleep 0.02; "
                    "done; %s 2>>/tmp/bubble-menu-action.log",
                    addr, addr, exec_cmd);
                exec_detached(poll_cmd);
                g_free(poll_cmd);
            } else {
                exec_detached(exec_cmd);
            }
            g_free(addr);
        } else {
            exec_detached(exec_cmd);
        }
        quit_app(app);
        return;
    }
    rerender(app);
}

static void activate_selected(App *app) {
    if (app->selected < 0 || !app->slots || (guint)app->selected >= app->slots->len) return;
    activate_slot(app, g_ptr_array_index(app->slots, app->selected));
}

static void move_selection(App *app, int dcol, int drow) {
    if (!app->slots || app->slots->len == 0) return;
    int col = app->selected % app->columns;
    int row = app->selected / app->columns;
    int total_rows = (app->slots->len + app->columns - 1) / app->columns;

    /* Horizontale Navigation über den Seitenrand hinaus -> Seite wechseln.
     * War mit rofis Kb-System nie möglich (rofi kennt nur "Fokus auf
     * nächste/vorige Zeile/Spalte", kein Grid-Rand-Ereignis) - hier
     * bauen wir die Tastatur selbst, also geht's jetzt. Nur in
     * paginierten Grids (Baum-Menü & vmode-Listen); das flache PowerMenu
     * hat keine Seiten, dort bleibt es beim normalen Wrap-Around. */
    if (!app->is_powermenu && dcol != 0 && drow == 0) {
        int new_col = col + dcol;
        if (new_col >= app->columns && app->total_pages > 1) {
            int old_page = app->state.page;
            app->state.page = MIN(app->state.page + 1, app->total_pages - 1);
            if (app->state.page != old_page) {
                play_sound("FocusChange");
                if (app->prev_slots) { g_ptr_array_unref(app->prev_slots); app->prev_slots = NULL; }
                app->prev_slots = copy_slots(app->slots);
                rebuild_slots(app);
                if (!try_select(app, row * app->columns))
                    for (int c = 0; c < app->columns && !try_select(app, row * app->columns + c); c++);
                app->anim_type = ANIM_SWITCH;
                app->anim_reversed = FALSE; /* nach rechts über den Rand = vorwärts */
                app->anim_start_us = g_get_monotonic_time();
                ensure_anim_tick(app);
                return;
            }
        } else if (new_col < 0 && app->state.page > 0) {
            app->state.page--;
            play_sound("FocusChange");
            if (app->prev_slots) { g_ptr_array_unref(app->prev_slots); app->prev_slots = NULL; }
            app->prev_slots = copy_slots(app->slots);
            rebuild_slots(app);
            if (!try_select(app, row * app->columns + (app->columns - 1)))
                for (int c = app->columns - 1; c >= 0 && !try_select(app, row * app->columns + c); c--);
            app->anim_type = ANIM_SWITCH;
            app->anim_reversed = TRUE; /* nach links über den Rand = rückwärts */
            app->anim_start_us = g_get_monotonic_time();
            ensure_anim_tick(app);
            return;
        }
    }

    for (int tries = 0; tries < app->columns * total_rows; tries++) {
        col += dcol; row += drow;
        if (col < 0) col = app->columns - 1;
        if (col >= app->columns) col = 0;
        if (row < 0) row = total_rows - 1;
        if (row >= total_rows) row = 0;
        int idx = row * app->columns + col;
        if ((guint)idx < app->slots->len) {
            Slot *s = g_ptr_array_index(app->slots, idx);
            if (!s->nonselectable) {
                app->selected = idx;
                mark_selection_bounce(app, idx);
                gtk_widget_queue_draw(app->area);
                return;
            }
        }
    }
}

/* ── GTK-Signal-Handler ──────────────────────────────────────────────── */
static gboolean on_motion(GtkWidget *widget, GdkEventMotion *event, gpointer user_data) {
    App *app = (App*)user_data;
    (void)widget;
    int special = special_at_xy(app, event->x, event->y);
    if (special != app->hover_special) {
        app->hover_special = special;
        gtk_widget_queue_draw(app->area);
    }
    if (special != 0) return TRUE; /* über Pfeil/Back - Grid-Hover ignorieren */

    int idx = slot_at_xy(app, event->x, event->y);
    if (idx >= 0) {
        Slot *s = g_ptr_array_index(app->slots, idx);
        if (!s->nonselectable && idx != app->selected) {
            app->selected = idx;
            mark_selection_bounce(app, idx);
            gtk_widget_queue_draw(app->area);
        }
    }
    return TRUE;
}

static gboolean on_button_press(GtkWidget *widget, GdkEventButton *event, gpointer user_data) {
    App *app = (App*)user_data;
    (void)widget;
    if (event->button != 1) return TRUE;

    int special = special_at_xy(app, event->x, event->y);
    if (special == 1) { /* linker Pfeil = vorherige Seite (nur falls vorhanden) */
        trigger_arrow_press(app, 1);
        if (app->state.page > 0) {
            app->state.page--;
            play_sound("FocusChange");
            switch_content(app, TRUE);
        }
        return TRUE;
    }
    if (special == 2) { /* rechter Pfeil = nächste Seite (nur falls vorhanden) */
        trigger_arrow_press(app, 2);
        if (app->state.page < app->total_pages - 1) {
            app->state.page++;
            play_sound("FocusChange");
            switch_content(app, FALSE);
        }
        return TRUE;
    }

    /* Kein Back/Exit-Button mehr im Bild - Klick auf den Leerbereich
     * (außerhalb Grid UND außerhalb der Pfeile) dient jetzt als Zurück/
     * Exit. Geht, weil im Vollbild-Layer nichts anderes dahinterliegt,
     * das man sonst anklicken könnte. Nur für Baum-/vmode-Grids - bei
     * PowerMenu bleibt Exit ganz normal eine Kachel im Grid. */
    if (!app->is_powermenu && !point_in_grid_bounds(app, event->x, event->y)) {
        go_back_or_exit(app);
        return TRUE;
    }

    int idx = slot_at_xy(app, event->x, event->y);
    if (idx >= 0) {
        app->selected = idx;
        activate_selected(app);
    }
    return TRUE;
}

static gboolean on_key_press(GtkWidget *widget, GdkEventKey *event, gpointer user_data) {
    App *app = (App*)user_data;
    (void)widget;
    switch (event->keyval) {
        case GDK_KEY_Escape:
            quit_app(app);
            return TRUE;
        case GDK_KEY_Up: case GDK_KEY_w: case GDK_KEY_W:
            move_selection(app, 0, -1);
            return TRUE;
        case GDK_KEY_Down: case GDK_KEY_s: case GDK_KEY_S:
            move_selection(app, 0, 1);
            return TRUE;
        case GDK_KEY_Left: case GDK_KEY_a: case GDK_KEY_A:
            move_selection(app, -1, 0);
            return TRUE;
        case GDK_KEY_Right: case GDK_KEY_d: case GDK_KEY_D:
            move_selection(app, 1, 0);
            return TRUE;
        case GDK_KEY_Return: case GDK_KEY_KP_Enter: case GDK_KEY_space:
            activate_selected(app);
            return TRUE;
        case GDK_KEY_q: case GDK_KEY_Q: /* custom-1: vorherige Seite */
            trigger_arrow_press(app, 1);
            app->state.page = MAX(0, app->state.page - 1);
            play_sound("FocusChange");
            switch_content(app, TRUE);
            return TRUE;
        case GDK_KEY_e: case GDK_KEY_E: /* custom-2: nächste Seite */
            trigger_arrow_press(app, 2);
            app->state.page++;
            play_sound("FocusChange");
            switch_content(app, FALSE);
            return TRUE;
        case GDK_KEY_x: case GDK_KEY_X: /* custom-3: zurück/exit */
            go_back_or_exit(app);
            return TRUE;
        default:
            return FALSE;
    }
}

/* =========================================================================
 * App-Fenster bauen (extrahiert aus main() - wird für Standalone- UND
 * Daemon-Modus gebraucht, im Daemon-Modus einmal pro Menü beim Start)
 * ========================================================================= */
static App* build_app(const char *menu_name, gboolean x11) {
    JsonObject *root = load_menu_json(menu_name);
    if (!root) {
        g_printerr("Fehler: Konnte %s/menu.json nicht laden.\n", menu_name);
        return NULL;
    }

    App *app = g_new0(App, 1);
    app->root = root;
    app->menu_name = g_strdup(menu_name);
    app->x11 = x11;
    app->is_powermenu = (g_strcmp0(menu_name, "PowerMenu") == 0);
    app->state = default_state();
    app->selected = 0;
    app->hover_special = 0;
    app->sel_bounce_slot = -1;
    app->history = g_ptr_array_new_with_free_func(history_entry_free);
    app->icon_cache = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_object_unref);
    load_bubble_assets(menu_name, &app->assets);
    if (!app->is_powermenu) load_nav_assets(menu_name, &app->nav);

    rebuild_slots(app);
    compute_layout(app);

    /* Anfangszustand der Pfeile korrekt vorbelegen, damit beim allerersten
     * Zeichnen kein unnötiger Fade ausgelöst wird, und "lange her" für
     * den Sentinel-Wert setzen (unabhängig von der Systemlaufzeit sicher). */
    if (!app->is_powermenu) {
        app->arrow_had_prev = app->state.page > 0;
        app->arrow_had_next = app->state.page < app->total_pages - 1;
        gint64 long_ago = g_get_monotonic_time() - (gint64)(ARROW_STATE_FADE_US * 10);
        app->arrow_left_fade_us = long_ago;
        app->arrow_right_fade_us = long_ago;
    }

    app->window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_decorated(GTK_WINDOW(app->window), FALSE);
    gtk_window_set_default_size(GTK_WINDOW(app->window), app->win_w, app->win_h);
    gtk_widget_set_size_request(app->window, app->win_w, app->win_h);
    gtk_window_set_resizable(GTK_WINDOW(app->window), FALSE);
    gtk_widget_set_app_paintable(app->window, TRUE);

    GdkScreen *screen = gtk_widget_get_screen(app->window);
    GdkVisual *visual = gdk_screen_get_rgba_visual(screen);
    if (visual) gtk_widget_set_visual(app->window, visual);

#ifdef HAVE_LAYER_SHELL
    gtk_layer_init_for_window(GTK_WINDOW(app->window));
    gtk_layer_set_layer(GTK_WINDOW(app->window), GTK_LAYER_SHELL_LAYER_OVERLAY);
    gtk_layer_set_keyboard_mode(GTK_WINDOW(app->window), GTK_LAYER_SHELL_KEYBOARD_MODE_EXCLUSIVE);
    /* Ohne das hier ist der Layer-Namespace der gtk-layer-shell-Default
     * ("gtk-layer-shell"), NICHT "TrafkTuxLauncher" - deshalb griff
     * hg.layer("TrafkTuxLauncher", {exclude=true}) in hyprland.lua bisher
     * nie. Namespace muss exakt zu dem String passen, den hyprglass dort
     * erwartet. */
    gtk_layer_set_namespace(GTK_WINDOW(app->window), "TrafkTuxLauncher");
    /* Keine Anchors gesetzt -> Compositor zentriert die Surface. */
#else
    gtk_window_set_type_hint(GTK_WINDOW(app->window), GDK_WINDOW_TYPE_HINT_DIALOG);
    gtk_window_set_keep_above(GTK_WINDOW(app->window), TRUE);
    gtk_window_set_position(GTK_WINDOW(app->window), GTK_WIN_POS_CENTER);
    gtk_window_set_skip_taskbar_hint(GTK_WINDOW(app->window), TRUE);
    gtk_window_set_skip_pager_hint(GTK_WINDOW(app->window), TRUE);
#endif

    app->area = gtk_drawing_area_new();
    gtk_widget_set_size_request(app->area, app->win_w, app->win_h);
    gtk_widget_add_events(app->area, GDK_POINTER_MOTION_MASK | GDK_BUTTON_PRESS_MASK);
    gtk_container_add(GTK_CONTAINER(app->window), app->area);

    g_signal_connect(app->area, "draw", G_CALLBACK(on_draw), app);
    g_signal_connect(app->area, "motion-notify-event", G_CALLBACK(on_motion), app);
    g_signal_connect(app->area, "button-press-event", G_CALLBACK(on_button_press), app);
    g_signal_connect(app->window, "key-press-event", G_CALLBACK(on_key_press), app);
    if (!g_daemon_mode) {
        g_signal_connect(app->window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    } else {
        /* Im Daemon-Modus NIE zerstören, nur verstecken (z.B. wenn der
         * Compositor mal versucht das Fenster zu schließen) - sonst wäre
         * das nächste --show tot. */
        g_signal_connect(app->window, "delete-event", G_CALLBACK(gtk_widget_hide_on_delete), NULL);
    }

    return app;
}

static void free_app(App *app) {
    if (!app) return;
    if (app->slots) g_ptr_array_unref(app->slots);
    if (app->prev_slots) g_ptr_array_unref(app->prev_slots);
    if (app->history) g_ptr_array_unref(app->history);
    g_hash_table_unref(app->icon_cache);
    if (app->assets.back_normal) g_object_unref(app->assets.back_normal);
    if (app->assets.back_selected) g_object_unref(app->assets.back_selected);
    if (app->assets.front_normal) g_object_unref(app->assets.front_normal);
    if (app->assets.front_selected) g_object_unref(app->assets.front_selected);
    if (!app->is_powermenu) free_nav_assets(&app->nav);
    g_free(app->state.path);
    g_free(app->state.vmode);
    json_object_unref(app->root);
    g_free(app->menu_name);
    g_free(app);
}

/* =========================================================================
 * Daemon-Modus: ein Prozess hält beide Fenster fertig gebaut & versteckt,
 * lauscht auf einem Unix-Socket auf "AppLauncher"/"PowerMenu" und zeigt
 * nur noch das passende Fenster - kein GTK/Icon-Theme/PNG-Decode-Aufwand
 * mehr pro Aufruf, daher instant.
 * ========================================================================= */
typedef struct {
    App *app_launcher;
    App *app_powermenu;
    guint reload_timeout_id;
} Daemon;

/* ── Live-Neuladen der Assets ─────────────────────────────────────────
 * Bisher wurden Bubble-/Nav-Assets nur EINMAL beim Daemon-Start geladen -
 * Dateien, die man später (z.B. nachträglich) nach /tmp kopiert, wurden
 * ignoriert, bis der Daemon neu gestartet wurde. Jetzt wird /tmp (und
 * jeder vorhandene ~/.config/TrafkTuxLauncher/<Menü>/assets/-Ordner) per
 * GFileMonitor beobachtet; bei einer relevanten Änderung werden die
 * Assets neu geladen und sofort neu gezeichnet - kein Neustart nötig. */
static const char *ASSET_BASENAMES[] = {
    "TrafkBubble1.png", "TrafkBubble2.png", "TrafkBubbleGlow1.png", "TrafkBubbleGlow2.png",
    "bubble-normal.png", "bubble-selected.png",
    "Left.png", "Right.png", "LeftGlow.png", "RightGlow.png",
    NULL
};

static gboolean is_relevant_asset_name(const char *basename) {
    if (!basename) return FALSE;
    for (int i = 0; ASSET_BASENAMES[i]; i++)
        if (g_strcmp0(basename, ASSET_BASENAMES[i]) == 0) return TRUE;
    return FALSE;
}

static void reload_assets(App *app) {
    if (!app) return;
    if (app->assets.back_normal) g_object_unref(app->assets.back_normal);
    if (app->assets.back_selected) g_object_unref(app->assets.back_selected);
    if (app->assets.front_normal) g_object_unref(app->assets.front_normal);
    if (app->assets.front_selected) g_object_unref(app->assets.front_selected);
    memset(&app->assets, 0, sizeof(app->assets));
    load_bubble_assets(app->menu_name, &app->assets);

    if (!app->is_powermenu) {
        free_nav_assets(&app->nav);
        memset(&app->nav, 0, sizeof(app->nav));
        load_nav_assets(app->menu_name, &app->nav);
    }
    gtk_widget_queue_draw(app->area);
}

static gboolean do_asset_reload(gpointer user_data) {
    Daemon *d = user_data;
    reload_assets(d->app_launcher);
    reload_assets(d->app_powermenu);
    d->reload_timeout_id = 0;
    g_printerr("TrafkTuxLauncher-Daemon: Assets neu geladen (Dateiänderung erkannt).\n");
    return G_SOURCE_REMOVE;
}

/* Entprellt: Dateikopien lösen oft mehrere Events kurz hintereinander
 * aus (CREATED, dann CHANGED, dann CHANGES_DONE_HINT) - ohne Entprellen
 * würde mehrfach kurz hintereinander neu geladen. */
static void schedule_asset_reload(Daemon *d) {
    if (d->reload_timeout_id) g_source_remove(d->reload_timeout_id);
    d->reload_timeout_id = g_timeout_add(300, do_asset_reload, d);
}

static void on_tmp_changed(GFileMonitor *monitor, GFile *file, GFile *other_file,
                            GFileMonitorEvent event_type, gpointer user_data) {
    (void)monitor; (void)other_file;
    if (event_type != G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT &&
        event_type != G_FILE_MONITOR_EVENT_CREATED &&
        event_type != G_FILE_MONITOR_EVENT_CHANGED)
        return;
    gchar *basename = g_file_get_basename(file);
    gboolean relevant = is_relevant_asset_name(basename);
    g_free(basename);
    if (relevant) schedule_asset_reload((Daemon*)user_data);
}

static void on_config_assets_changed(GFileMonitor *monitor, GFile *file, GFile *other_file,
                                      GFileMonitorEvent event_type, gpointer user_data) {
    (void)monitor; (void)file; (void)other_file; (void)event_type;
    schedule_asset_reload((Daemon*)user_data);
}

static void setup_asset_watchers(Daemon *d) {
    GError *err = NULL;
    GFile *tmp_dir = g_file_new_for_path("/tmp");
    GFileMonitor *tmp_mon = g_file_monitor_directory(tmp_dir, G_FILE_MONITOR_NONE, NULL, &err);
    if (tmp_mon) {
        g_signal_connect(tmp_mon, "changed", G_CALLBACK(on_tmp_changed), d);
        /* Monitor absichtlich nicht unref't - soll leben, solange der Daemon läuft */
    } else {
        g_printerr("TrafkTuxLauncher-Daemon: konnte /tmp nicht überwachen: %s\n", err->message);
        g_clear_error(&err);
    }
    g_object_unref(tmp_dir);

    const char *menu_names[2] = { "AppLauncher", "PowerMenu" };
    for (int i = 0; i < 2; i++) {
        gchar *cfg_dir = g_build_filename(g_get_home_dir(), ".config", "TrafkTuxLauncher",
                                           menu_names[i], "assets", NULL);
        if (g_file_test(cfg_dir, G_FILE_TEST_IS_DIR)) {
            GFile *cfg_file = g_file_new_for_path(cfg_dir);
            GFileMonitor *cfg_mon = g_file_monitor_directory(cfg_file, G_FILE_MONITOR_NONE, NULL, &err);
            if (cfg_mon) {
                g_signal_connect(cfg_mon, "changed", G_CALLBACK(on_config_assets_changed), d);
            } else {
                g_clear_error(&err);
            }
            g_object_unref(cfg_file);
        }
        g_free(cfg_dir);
    }
}

static gchar* get_socket_path(void) {
    return g_build_filename(g_get_user_runtime_dir(), "trafktuxlauncher.sock", NULL);
}

static gboolean on_socket_incoming(GSocketService *service, GSocketConnection *connection,
                                    GObject *source_object, gpointer user_data) {
    (void)service; (void)source_object;
    Daemon *d = user_data;
    GInputStream *in = g_io_stream_get_input_stream(G_IO_STREAM(connection));
    char buf[64];
    gssize n = g_input_stream_read(in, buf, sizeof(buf) - 1, NULL, NULL);
    if (n > 0) {
        buf[n] = '\0';
        g_strstrip(buf);
        if (g_strcmp0(buf, "AppLauncher") == 0 && d->app_launcher) {
            show_app(d->app_launcher, d->app_powermenu);
        } else if (g_strcmp0(buf, "PowerMenu") == 0 && d->app_powermenu) {
            show_app(d->app_powermenu, d->app_launcher);
        } else {
            g_printerr("TrafkTuxLauncher-Daemon: unbekanntes Kommando '%s'\n", buf);
        }
    }
    g_io_stream_close(G_IO_STREAM(connection), NULL, NULL);
    return TRUE;
}

static gboolean on_sigterm(gpointer user_data) {
    (void)user_data;
    gtk_main_quit();
    return G_SOURCE_REMOVE;
}

/* Icon-Sync läuft jetzt NICHT mehr menügetriggert (kein UI-Element mehr
 * dafür, siehe Redesign), sondern einmal automatisch beim Start des
 * Daemons - im Hintergrund-Thread wie schon vorher, damit auch der
 * Daemon-Start selbst nicht blockiert. */
typedef struct {
    App *app_launcher;
    App *app_powermenu;
    int n_steam, n_jet;
} StartupIconSync;

static gboolean startup_icon_sync_done_idle(gpointer data) {
    StartupIconSync *r = data;
    int total = r->n_steam + r->n_jet;
    if (total > 0) {
        gchar *msg = g_strdup_printf("%d Steam-Icon(s), %d JetBrains-Icon(s) installiert.", r->n_steam, r->n_jet);
        gchar *msg_q = g_shell_quote(msg);
        gchar *cmd = g_strdup_printf("notify-send -a 'TrafkTuxLauncher' 'Icons synchronisiert' %s", msg_q);
        exec_detached(cmd);
        g_free(cmd); g_free(msg_q); g_free(msg);
        if (cached_desktop_apps) { g_ptr_array_unref(cached_desktop_apps); cached_desktop_apps = NULL; }
        if (r->app_launcher) g_hash_table_remove_all(r->app_launcher->icon_cache);
        if (r->app_powermenu) g_hash_table_remove_all(r->app_powermenu->icon_cache);
    } else {
        g_printerr("TrafkTuxLauncher-Daemon: Icon-Sync fertig, nichts zu tun.\n");
    }
    g_free(r);
    return G_SOURCE_REMOVE;
}

static gpointer startup_icon_sync_thread(gpointer data) {
    StartupIconSync *r = data;
    r->n_steam = sync_steam_icons();
    r->n_jet = sync_jetbrains_icons();
    g_idle_add(startup_icon_sync_done_idle, r);
    return NULL;
}

static int run_daemon(gboolean x11) {
    g_daemon_mode = TRUE;

    Daemon d = {0};
    d.app_launcher = build_app("AppLauncher", x11);
    d.app_powermenu = build_app("PowerMenu", x11);
    if (!d.app_launcher && !d.app_powermenu) {
        g_printerr("TrafkTuxLauncher-Daemon: weder AppLauncher- noch PowerMenu-menu.json gefunden, breche ab.\n");
        return 1;
    }
    /* Beide Fenster existieren jetzt fertig gebaut (Assets geladen, Icons
     * aufgelöst, Layer-Surface erzeugt) - aber unsichtbar. Genau dieser
     * einmalige Aufwand beim Daemon-Start ist es, der bisher bei JEDEM
     * Öffnen erneut anfiel. */

    StartupIconSync *isr = g_new0(StartupIconSync, 1);
    isr->app_launcher = d.app_launcher;
    isr->app_powermenu = d.app_powermenu;
    GThread *isync_thread = g_thread_new("icon-sync", startup_icon_sync_thread, isr);
    g_thread_unref(isync_thread);

    setup_asset_watchers(&d);

    gchar *sock_path = get_socket_path();
    g_unlink(sock_path); /* verwaisten Socket von einem abgestürzten alten Daemon entfernen */

    GSocketService *service = g_socket_service_new();
    GSocketAddress *addr = g_unix_socket_address_new(sock_path);
    GError *err = NULL;
    if (!g_socket_listener_add_address(G_SOCKET_LISTENER(service), addr,
                                        G_SOCKET_TYPE_STREAM, G_SOCKET_PROTOCOL_DEFAULT,
                                        NULL, NULL, &err)) {
        g_printerr("TrafkTuxLauncher-Daemon: konnte Socket %s nicht öffnen: %s\n",
                   sock_path, err->message);
        g_error_free(err);
        g_object_unref(addr);
        g_free(sock_path);
        return 1;
    }
    g_object_unref(addr);
    g_signal_connect(service, "incoming", G_CALLBACK(on_socket_incoming), &d);
    g_socket_service_start(G_SOCKET_SERVICE(service));

    g_unix_signal_add(SIGTERM, on_sigterm, NULL);
    g_unix_signal_add(SIGINT, on_sigterm, NULL);

    g_printerr("TrafkTuxLauncher-Daemon: bereit, lauscht auf %s\n", sock_path);
    g_free(sock_path);

    gtk_main();

    free_app(d.app_launcher);
    free_app(d.app_powermenu);
    return 0;
}

/* Client-Seite von --show: verbindet sich zum laufenden Daemon, schickt
 * den Menünamen, fertig - KEIN gtk_init() in diesem Pfad, daher schnell
 * genug um bei jedem Tastendruck neu gestartet zu werden. Falls kein
 * Daemon erreichbar ist (noch nicht gestartet, abgestürzt, o.ä.),
 * Rückgabewert FALSE -> main() fällt dann auf den alten eigenständigen
 * Weg zurück, damit's auch ohne Daemon nicht einfach nichts tut. */
static gboolean try_show_via_daemon(const char *menu_name) {
    gchar *sock_path = get_socket_path();
    GSocketClient *client = g_socket_client_new();
    GSocketConnectable *addr = G_SOCKET_CONNECTABLE(g_unix_socket_address_new(sock_path));
    GError *err = NULL;
    GSocketConnection *conn = g_socket_client_connect(client, addr, NULL, &err);
    g_object_unref(addr);
    g_free(sock_path);
    g_object_unref(client);
    if (!conn) {
        if (err) g_error_free(err);
        return FALSE;
    }
    GOutputStream *out = g_io_stream_get_output_stream(G_IO_STREAM(conn));
    g_output_stream_write(out, menu_name, strlen(menu_name), NULL, NULL);
    g_io_stream_close(G_IO_STREAM(conn), NULL, NULL);
    g_object_unref(conn);
    return TRUE;
}

/* =========================================================================
 * main
 * ========================================================================= */
int main(int argc, char *argv[]) {
    char *menu_name = g_strdup("AppLauncher");
    char *show_target = NULL;
    gboolean x11 = FALSE;
    gboolean daemon_flag = FALSE;
    for (int i = 1; i < argc; i++) {
        if (g_strcmp0(argv[i], "--menu") == 0 && i + 1 < argc) {
            g_free(menu_name);
            menu_name = g_strdup(argv[i + 1]);
            i++;
        } else if (g_strcmp0(argv[i], "--show") == 0 && i + 1 < argc) {
            g_free(show_target);
            show_target = g_strdup(argv[i + 1]);
            i++;
        } else if (g_strcmp0(argv[i], "--daemon") == 0) {
            daemon_flag = TRUE;
        } else if (g_strcmp0(argv[i], "--x11") == 0) {
            x11 = TRUE;
        }
    }

    /* --show: erst OHNE gtk_init versuchen, den laufenden Daemon zu
     * erreichen (schnellster Pfad). Klappt das nicht, fällt menu_name auf
     * show_target und es geht unten in den normalen eigenständigen Start
     * über - kein separater Codepfad nötig, kein "tut einfach nichts". */
    if (show_target) {
        if (try_show_via_daemon(show_target)) {
            g_free(menu_name);
            g_free(show_target);
            return 0;
        }
        g_printerr("TrafkTuxLauncher: kein Daemon erreichbar, starte eigenständig "
                   "(langsamer - 'TrafkTuxLauncher --daemon &' im Autostart prüfen).\n");
        g_free(menu_name);
        menu_name = show_target;
        show_target = NULL;
    }

    gtk_init(&argc, &argv);

    if (daemon_flag) {
        int ret = run_daemon(x11);
        g_free(menu_name);
        return ret;
    }

    save_active_window();

    App *app = build_app(menu_name, x11);
    g_free(menu_name);
    if (!app) return 1;

    gtk_widget_show_all(app->window);
    gtk_window_present(GTK_WINDOW(app->window));
    app->anim_type = ANIM_OPEN;
    app->anim_reversed = FALSE;
    app->anim_start_us = g_get_monotonic_time();
    ensure_anim_tick(app);
    gtk_main();

    free_app(app);
    return 0;
}
