/*
 * RofiTrafkBubbleMenus.c – Generische Rofi Bubble-Menü-Engine (C-Version)
 *
 * Kompilierung: make (siehe Makefile)
 * Abhängigkeiten: glib-2.0, json-glib-1.0, gio-2.0, ImageMagick (für Icon-Sync)
 *
 * Diese Version behebt zwei Kernfehler des vorherigen (deepseek-)Ports:
 *
 * 1) exec_detached() lief bisher über g_spawn_command_line_async(), was
 *    NIEMALS eine echte Shell benutzt (nur wortweises Zerlegen + direktes
 *    execve). Das Python-Original nutzte subprocess.Popen(cmd, shell=True,
 *    start_new_session=True, ...). Ohne echte Shell scheitern alle
 *    exec-Strings mit Shell-Syntax (Semikolons, for-Schleifen, $(...), &&) -
 *    genau das nutzt der Powermenü-"action"-Zweig für den Fokus-Poll vor
 *    z.B. "systemctl poweroff". Ergebnis: Bubble schließt sich, Aktion
 *    passiert aber nicht.
 *
 * 2) Ohne setsid() (Python: start_new_session=True) bleibt der gestartete
 *    Prozess in derselben Prozessgruppe/Session wie dieser sehr kurzlebige
 *    Helper-Prozess. Wird beim Schließen der Bubble ein Signal an die
 *    gesamte Prozessgruppe geschickt (üblich bei Layer-Surface-Teardown),
 *    kann das die frisch gestartete App genau in dem Moment treffen, in dem
 *    sie ihr Fenster mappen/den Fokus übernehmen will - Hyprland bleibt mit
 *    exklusivem Rofi-Fokus auf einer toten Surface hängen -> Softlock.
 *
 * Zusätzlich wurde die Desktop-App-Erkennung von GLibs GAppInfo (die die
 * Filter-/Field-Code-/Terminal-Logik des Originals nicht 1:1 abbildet) auf
 * eine manuelle .desktop-Datei-Auswertung analog zum Python-Original
 * umgestellt (Hidden/NoDisplay/Type/OnlyShowIn/NotShowIn, %f/%u-Field-Code-
 * Stripping, Terminal=true -> "kitty <cmd>").
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
#include <glib.h>
#include <gio/gio.h>
#include <json-glib/json-glib.h>

/* --------------------------- Konstanten --------------------------- */
#define BLANK_ICON_PATH     "/tmp/.bubble-menu-blank.png"
#define PREV_WINDOW_FILE    "/tmp/rofi-prev-window"
#define SOUNDCTL_PATH       "~/.config/hypr/soundctl.sh"

#define RAW_BACK            "BACK"
#define RAW_EXIT            "EXIT"
#define RAW_NEXT            "NEXT"
#define RAW_PREV            "PREV"
#define RAW_NOOP            "NOOP"
#define RAW_SYNC_ICONS      "SYNC_ICONS"

#define RETV_SELECT         "1"
#define RETV_CUSTOM_1       "10"   /* q → prev page */
#define RETV_CUSTOM_2       "11"   /* e → next page (oder Sync in root) */
#define RETV_CUSTOM_3       "12"   /* x → back/exit */

#define CONTENT_COLUMNS     4
#define CONTENT_ROWS        3
#define PAGE_SIZE           (CONTENT_COLUMNS * CONTENT_ROWS)

#define VMODE_DRUN          "drun"
#define VMODE_DRUN_FILTERED "drun-filtered"
#define VMODE_RUN           "run"

#define SCAN_CACHE_TTL      180        /* 3 Minuten für App-/Binary-Caches */

/* Custom-Keybindings, identisch zu Pythons WASD_KB_ARGS - wird für das
 * eigenständige "special-window"-Rofi (offene Fenster) mitgegeben. */
static const char *WASD_KB_ARGS[] = {
    "-kb-row-up", "Up,Control+p,w",
    "-kb-row-down", "Down,Control+n,s",
    "-kb-row-left", "Control+Page_Up,a",
    "-kb-row-right", "Control+Page_Down,d",
    "-kb-accept-entry", "Control+j,Control+m,Return,KP_Enter,space,less",
    "-kb-custom-1", "q",
    "-kb-custom-2", "e",
    "-kb-custom-3", "x",
    NULL
};

/* Dynamische Pfadfunktionen */
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

/* eingebettete 1x1 transparente PNG */
static const unsigned char BLANK_PNG[] = {
    0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,
    0x49,0x48,0x44,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,
    0x08,0x06,0x00,0x00,0x00,0x1F,0x15,0xC4,0x89,0x00,0x00,0x00,
    0x0D,0x49,0x44,0x41,0x54,0x78,0xDA,0x63,0x60,0x00,0x00,0x00,
    0x02,0x00,0x01,0xE2,0x26,0x05,0x9B,0x00,0x00,0x00,0x00,0x49,
    0x45,0x4E,0x44,0xAE,0x42,0x60,0x82
};
#define BLANK_PNG_LEN (sizeof(BLANK_PNG))

static const char *WRAPPER_PREFIXES[] = { "kitty", "sudo", NULL };

/* --------------------------- exec_detached (FIX) --------------------------- */
/*
 * Entspricht Pythons:
 *   subprocess.Popen(command, shell=True, start_new_session=True,
 *                     stdout=DEVNULL, stderr=DEVNULL)
 *
 * WICHTIG: bewusst über fork()+execl("/bin/sh","-c",command,...) statt
 * g_spawn_command_line_async() - letzteres benutzt KEINE Shell (nur
 * wortweises g_shell_parse_argv + direktes execve), versteht also weder
 * "for ... done", "$(...)", ";", "&&" noch ähnliche Konstrukte, die im
 * Menübaum (z.B. Fokus-Poll vor Power-Aktionen, Layout-Switcher) benutzt
 * werden. Zusätzlich setsid() im Kind, damit der gestartete Prozess NICHT
 * in der (sehr kurzlebigen) Prozessgruppe/Session dieses Helferprozesses
 * hängt - siehe Kommentar am Dateianfang.
 */
void exec_detached(const char *command) {
    if (!command || !*command) return;

    pid_t pid = fork();
    if (pid < 0) {
        g_warning("exec_detached: fork fehlgeschlagen: %s", g_strerror(errno));
        return;
    }
    if (pid == 0) {
        /* Kindprozess */
        setsid();

        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > 2) close(devnull);
        }

        execl("/bin/sh", "sh", "-c", command, (char *)NULL);
        _exit(127); /* nur erreicht, wenn execl fehlschlägt */
    }
    /* Elternprozess: NICHT warten (fire-and-forget). Da dieser Helper-
     * Prozess sich selbst gleich beendet, wird das Kind von init/systemd
     * geerbt und automatisch gereapt - kein Zombie-Risiko. */
}

void play_sound(const char *event) {
    gchar *cmd = g_strdup_printf("bash %s %s", SOUNDCTL_PATH, event);
    exec_detached(cmd);
    g_free(cmd);
}

const char* ensure_blank_icon(void) {
    if (!g_file_test(BLANK_ICON_PATH, G_FILE_TEST_EXISTS)) {
        FILE *f = fopen(BLANK_ICON_PATH, "wb");
        if (f) {
            fwrite(BLANK_PNG, 1, BLANK_PNG_LEN, f);
            fclose(f);
        }
    }
    return BLANK_ICON_PATH;
}

void cleanup_files(void) {
    unlink(PREV_WINDOW_FILE);
}

void save_active_window(void) {
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

char* read_prev_window_addr(void) {
    if (!g_file_test(PREV_WINDOW_FILE, G_FILE_TEST_EXISTS))
        return NULL;
    GError *err = NULL;
    gchar *content = NULL;
    if (!g_file_get_contents(PREV_WINDOW_FILE, &content, NULL, &err)) {
        if (err) g_error_free(err);
        return NULL;
    }
    g_strstrip(content);
    return content;
}

gboolean is_number(const char *s) {
    if (!s || !*s) return FALSE;
    for (; *s; s++) if (!g_ascii_isdigit(*s)) return FALSE;
    return TRUE;
}

gchar* focused_monitor_name(void) {
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

/* --------------------------- State --------------------------- */
typedef struct {
    char *path;
    int page;
    char *vmode;   /* NULL → normaler Baum, sonst VMODE_* */
} MenuState;

MenuState default_state(void) {
    MenuState s = { g_strdup(""), 0, NULL };
    return s;
}

MenuState parse_state(const char *rofi_data) {
    MenuState s = default_state();
    if (!rofi_data || !*rofi_data) return s;
    JsonParser *parser = json_parser_new();
    if (json_parser_load_from_data(parser, rofi_data, -1, NULL)) {
        JsonObject *root = json_node_get_object(json_parser_get_root(parser));
        if (json_object_has_member(root, "path")) {
            g_free(s.path);
            s.path = g_strdup(json_object_get_string_member(root, "path"));
        }
        if (json_object_has_member(root, "page"))
            s.page = json_object_get_int_member(root, "page");
        if (json_object_has_member(root, "vmode") &&
            !json_node_is_null(json_object_get_member(root, "vmode"))) {
            s.vmode = g_strdup(json_object_get_string_member(root, "vmode"));
        }
    }
    g_object_unref(parser);
    return s;
}

char* state_to_json(const MenuState *state) {
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "path");
    json_builder_add_string_value(builder, state->path ? state->path : "");
    json_builder_set_member_name(builder, "page");
    json_builder_add_int_value(builder, state->page);
    json_builder_set_member_name(builder, "vmode");
    if (state->vmode) json_builder_add_string_value(builder, state->vmode);
    else json_builder_add_null_value(builder);
    json_builder_end_object(builder);

    JsonGenerator *gen = json_generator_new();
    JsonNode *root = json_builder_get_root(builder);
    json_generator_set_root(gen, root);
    gsize len;
    char *data = json_generator_to_data(gen, &len);
    json_node_free(root);
    g_object_unref(gen);
    g_object_unref(builder);
    return data;
}

void free_state(MenuState *state) {
    g_free(state->path);
    g_free(state->vmode);
}

/* --------------------------- Menü-JSON laden & Pfadauflösung --------------------------- */
JsonObject* load_menu_json(const char *menu_name) {
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

JsonObject* resolve_path(JsonObject *root, const char *path_str) {
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

/* --------------------------- Desktop-Apps & PATH-Binaries (mit Cache) --------------------------- */
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

/* --------------------------- Exec-Field-Code-Stripping (FIX: fehlte im C-Port) ------------ */
/* Entspricht Pythons _strip_exec_field_codes(): entfernt %f/%F/%u/%U/%i/%c/
 * %k/%d/%D/%n/%N/%v/%m (mit %% -> %), und normalisiert Whitespace danach
 * auf einzelne Leerzeichen (" ".join(s.split())). */
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

/* --------------------------- XDG-Datenverzeichnisse (FIX: fehlte im C-Port) --------------- */
/* Entspricht Pythons _xdg_data_dirs(): ~/.local/share (+ optional
 * XDG_DATA_HOME vorne dran) + XDG_DATA_DIRS (Default /usr/local/share:/usr/share),
 * dedupliziert unter Beibehaltung der Reihenfolge. */
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

/* Rekursiver .desktop-Scan (analog zu Pythons os.walk(app_dir)). Sammelt
 * volle Pfade + "desktop_id" (Pfad relativ zu app_dir, '/' -> '-'), damit
 * Duplikate über mehrere XDG-Datenverzeichnisse korrekt anhand der ID
 * (nicht des Dateinamens) dedupliziert werden können. */
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

/* Prüft, ob ein ';'-getrenntes Feld (OnlyShowIn/NotShowIn) eine der aktuell
 * aktiven Desktop-Umgebungen enthält. */
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

/* --------------------------- Desktop-App-Sammlung (FIX: manuelle Auswertung -------------- */
/* Entspricht 1:1 Pythons collect_desktop_apps(): Type/Hidden/NoDisplay/
 * OnlyShowIn/NotShowIn-Filter, %-Field-Code-Stripping, Terminal=true ->
 * "kitty <cmd>". Vorher nutzte der C-Port GAppInfo, was diese Logik nicht
 * abbildet (u.a. fehlte Terminal-Wrapping und Field-Code-Stripping komplett -
 * Ursache für Apps, die scheinbar "nichts tun" bzw. mit kaputten Argumenten
 * starten). */
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

GPtrArray* get_desktop_apps(void) {
    GPtrArray *apps; time_t ts;
    collect_desktop_apps_impl(&apps, &ts);
    return apps;
}

GPtrArray* get_filtered_desktop_apps(JsonObject *root) {
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

GPtrArray* get_path_binaries(void) {
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

/* --------------------------- Icon-Sync (Steam & JetBrains) --------------------------- */
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

int sync_steam_icons(void) {
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

int sync_jetbrains_icons(void) {
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

void run_manual_icon_sync_and_notify(void) {
    int n_steam = sync_steam_icons();
    int n_jet = sync_jetbrains_icons();
    int total = n_steam + n_jet;
    gchar *msg;
    if (total > 0)
        msg = g_strdup_printf("%d Steam-Icon(s), %d JetBrains-Icon(s) installiert.", n_steam, n_jet);
    else
        msg = g_strdup("Keine fehlenden Icons gefunden - alles schon aktuell.");
    gchar *msg_q = g_shell_quote(msg);
    gchar *cmd = g_strdup_printf("notify-send -a 'Bubble-Menu' 'Icons synchronisiert' %s", msg_q);
    exec_detached(cmd);
    g_free(cmd);
    g_free(msg_q);
    g_free(msg);
    /* Caches invalidieren, damit neu installierte Icons sofort sichtbar sind. */
    if (cached_desktop_apps) { g_ptr_array_unref(cached_desktop_apps); cached_desktop_apps = NULL; }
}

/* --------------------------- Rendering (Grid) --------------------------- */
typedef struct {
    char *name;
    char *icon;
    char *raw;
    gboolean nonselectable;
} GridEntry;

static void grid_entry_free(gpointer data) {
    GridEntry *e = (GridEntry*)data;
    g_free(e->name);
    g_free(e->icon);
    g_free(e->raw);
    g_free(e);
}

static GridEntry* make_entry(const char *name, const char *icon, const char *raw, gboolean nonselectable) {
    GridEntry *e = g_new0(GridEntry, 1);
    e->name = g_strdup(name ? name : " ");
    e->icon = g_strdup(icon ? icon : "");
    e->raw = g_strdup(raw ? raw : RAW_NOOP);
    e->nonselectable = nonselectable;
    return e;
}

static void emit_entry(const GridEntry *e) {
    const char *display = (e->name && *e->name) ? e->name : " ";
    fwrite(display, 1, strlen(display), stdout);
    fwrite("\0info\x1f", 1, sizeof("\0info\x1f") - 1, stdout);
    fwrite(e->raw, 1, strlen(e->raw), stdout);
    if (e->icon && *e->icon) {
        fwrite("\x1ficon\x1f", 1, sizeof("\x1ficon\x1f") - 1, stdout);
        fwrite(e->icon, 1, strlen(e->icon), stdout);
    }
    if (e->nonselectable) {
        fwrite("\x1fnonselectable\x1ftrue", 1, sizeof("\x1fnonselectable\x1ftrue") - 1, stdout);
    }
    fwrite("\n", 1, 1, stdout);
}

static void emit_header(void) {
    fwrite("\0use-hot-keys\x1ftrue\n", 1, sizeof("\0use-hot-keys\x1ftrue\n") - 1, stdout);
    fwrite("\0no-custom\x1ftrue\n", 1, sizeof("\0no-custom\x1ftrue\n") - 1, stdout);
}

static GPtrArray* build_grid_entries(GPtrArray *content_entries, int page, int total_pages,
                                     gboolean is_root, gboolean has_parent) {
    GPtrArray *result = g_ptr_array_new_with_free_func(grid_entry_free);

    GridEntry *content[PAGE_SIZE];
    for (int i = 0; i < PAGE_SIZE; i++) {
        content[i] = make_entry(" ", ensure_blank_icon(), RAW_NOOP, TRUE);
    }
    guint copy_count = MIN(content_entries->len, (guint)PAGE_SIZE);
    for (guint i = 0; i < copy_count; i++) {
        GridEntry *src = g_ptr_array_index(content_entries, i);
        GridEntry *dst = content[i];
        g_free(dst->name); g_free(dst->icon); g_free(dst->raw);
        dst->name = g_strdup(src->name);
        dst->icon = g_strdup(src->icon);
        dst->raw = g_strdup(src->raw);
        dst->nonselectable = src->nonselectable;
    }

    GridEntry *nav_next, *nav_prev, *nav_back;
    gboolean has_next = (page < total_pages - 1);
    gboolean has_prev = (page > 0);

    if (is_root) {
        nav_next = make_entry("Icons synchronisieren", "view-refresh", RAW_SYNC_ICONS, FALSE);
    } else {
        nav_next = has_next ? make_entry("Next Page", "go-next", RAW_NEXT, FALSE)
                            : make_entry(" ", ensure_blank_icon(), RAW_NOOP, TRUE);
    }
    nav_prev = has_prev ? make_entry("Last Page", "go-previous", RAW_PREV, FALSE)
                        : make_entry(" ", ensure_blank_icon(), RAW_NOOP, TRUE);
    nav_back = has_parent ? make_entry("\u2190 Zurück", "go-previous", RAW_BACK, FALSE)
                          : make_entry("Exit", "application-exit", RAW_EXIT, FALSE);

    GridEntry *nav_col[3] = { nav_next, nav_prev, nav_back };

    if (is_root) {
        for (int row = 0; row < CONTENT_ROWS; row++) {
            for (int col = 0; col < 3; col++) {
                GridEntry *e = content[row * 3 + col];
                g_ptr_array_add(result, make_entry(e->name, e->icon, e->raw, e->nonselectable));
            }
            GridEntry *e2 = content[9 + row];
            g_ptr_array_add(result, make_entry(e2->name, e2->icon, e2->raw, e2->nonselectable));
            GridEntry *n = nav_col[row];
            g_ptr_array_add(result, make_entry(n->name, n->icon, n->raw, n->nonselectable));
        }
    } else {
        for (int row = 0; row < CONTENT_ROWS; row++) {
            for (int col = 0; col < CONTENT_COLUMNS; col++) {
                GridEntry *e = content[row * CONTENT_COLUMNS + col];
                g_ptr_array_add(result, make_entry(e->name, e->icon, e->raw, e->nonselectable));
            }
            GridEntry *n = nav_col[row];
            g_ptr_array_add(result, make_entry(n->name, n->icon, n->raw, n->nonselectable));
        }
    }

    for (int i = 0; i < PAGE_SIZE; i++) grid_entry_free(content[i]);
    grid_entry_free(nav_next);
    grid_entry_free(nav_prev);
    grid_entry_free(nav_back);

    return result;
}

/* --------------------------- Rendering-Funktion --------------------------- */
static void render_menu(const char *menu_name, JsonObject *root, MenuState *state) {
    emit_header();

    gboolean is_powermenu = (g_strcmp0(menu_name, "powermenu") == 0);

    if (is_powermenu) {
        /* Powermenü: flache Liste, KEINE Pagination/Grid-Logik (analog zu
         * Pythons build_powermenu_entries) - läuft unabhängig vom
         * generischen Grid-Pfad, um die vorher hier entstehende
         * (ungenutzte) Grid-Berechnung + den daraus resultierenden Leak zu
         * vermeiden. */
        JsonObject *node = resolve_path(root, state->path);
        if (json_object_has_member(node, "children")) {
            JsonArray *arr = json_object_get_array_member(node, "children");
            for (guint i = 0; i < json_array_get_length(arr); i++) {
                JsonObject *child = json_node_get_object(json_array_get_element(arr, i));
                const char *type = json_object_has_member(child, "type") ?
                    json_object_get_string_member(child, "type") : NULL;
                if (g_strcmp0(type, "placeholder") == 0) {
                    GridEntry *e = make_entry(" ", ensure_blank_icon(), RAW_NOOP, TRUE);
                    emit_entry(e);
                    grid_entry_free(e);
                } else {
                    const char *name = json_object_has_member(child, "name") ?
                        json_object_get_string_member(child, "name") : NULL;
                    const char *icon = json_object_has_member(child, "icon") ?
                        json_object_get_string_member(child, "icon") : NULL;
                    gchar *idx_str = g_strdup_printf("%u", i);
                    GridEntry *e = make_entry(name ? name : "Unbekannt", icon ? icon : "", idx_str, FALSE);
                    emit_entry(e);
                    grid_entry_free(e);
                    g_free(idx_str);
                }
            }
        }
        GridEntry *exit_e = make_entry("Exit", "application-exit", RAW_EXIT, FALSE);
        emit_entry(exit_e);
        grid_entry_free(exit_e);
    } else {
        GPtrArray *render_entries = NULL;
        int total_pages = 1;

        if (state->vmode) {
            GPtrArray *apps = NULL;
            if (g_strcmp0(state->vmode, VMODE_DRUN) == 0)
                apps = get_desktop_apps();
            else if (g_strcmp0(state->vmode, VMODE_DRUN_FILTERED) == 0)
                apps = get_filtered_desktop_apps(root);
            else if (g_strcmp0(state->vmode, VMODE_RUN) == 0)
                apps = get_path_binaries();
            gboolean apps_is_temp = FALSE;
            if (!apps) { apps = g_ptr_array_new(); apps_is_temp = TRUE; }
            total_pages = (apps->len + PAGE_SIZE - 1) / PAGE_SIZE;
            if (total_pages == 0) total_pages = 1;
            state->page = CLAMP(state->page, 0, total_pages - 1);

            GPtrArray *content = g_ptr_array_new_with_free_func(grid_entry_free);
            guint start = state->page * PAGE_SIZE;
            for (guint i = start; i < start + PAGE_SIZE && i < apps->len; i++) {
                AppEntry *a = g_ptr_array_index(apps, i);
                gchar *idx_str = g_strdup_printf("%u", i);
                GridEntry *e = make_entry(a->name, a->icon, idx_str, FALSE);
                g_free(idx_str);
                g_ptr_array_add(content, e);
            }
            render_entries = build_grid_entries(content, state->page, total_pages, FALSE, TRUE);
            g_ptr_array_unref(content);
            if (apps_is_temp) g_ptr_array_unref(apps);
        } else {
            JsonObject *node = resolve_path(root, state->path);
            if (!json_object_has_member(node, "children")) {
                render_entries = g_ptr_array_new_with_free_func(grid_entry_free);
            } else {
                JsonArray *arr = json_object_get_array_member(node, "children");
                guint total = json_array_get_length(arr);
                total_pages = (total + PAGE_SIZE - 1) / PAGE_SIZE;
                if (total_pages == 0) total_pages = 1;
                state->page = CLAMP(state->page, 0, total_pages - 1);

                GPtrArray *content = g_ptr_array_new_with_free_func(grid_entry_free);
                guint start = state->page * PAGE_SIZE;
                for (guint i = start; i < start + PAGE_SIZE && i < total; i++) {
                    JsonObject *child = json_node_get_object(json_array_get_element(arr, i));
                    const char *type = json_object_get_string_member(child, "type");
                    if (g_strcmp0(type, "placeholder") == 0) {
                        GridEntry *e = make_entry(" ", ensure_blank_icon(), RAW_NOOP, TRUE);
                        g_ptr_array_add(content, e);
                    } else {
                        const char *name = json_object_get_string_member(child, "name");
                        const char *icon = json_object_get_string_member(child, "icon");
                        gchar *idx_str = g_strdup_printf("%u", i);
                        GridEntry *e = make_entry(name ? name : "Unbekannt", icon ? icon : "", idx_str, FALSE);
                        g_free(idx_str);
                        g_ptr_array_add(content, e);
                    }
                }
                gboolean is_root = (!state->path || !*state->path);
                gboolean has_parent = (state->path && *state->path) || state->vmode != NULL;
                render_entries = build_grid_entries(content, state->page, total_pages, is_root, has_parent);
                g_ptr_array_unref(content);
            }
        }

        for (guint i = 0; i < render_entries->len; i++) {
            emit_entry(g_ptr_array_index(render_entries, i));
        }
        g_ptr_array_unref(render_entries);
    }

    char *data_json = state_to_json(state);
    fwrite("\0data\x1f", 1, sizeof("\0data\x1f") - 1, stdout);
    fwrite(data_json, 1, strlen(data_json), stdout);
    fwrite("\n", 1, 1, stdout);
    g_free(data_json);

    fflush(stdout);
}

/* --------------------------- Hauptverarbeitung --------------------------- */
void handle_step(const char *menu_name, gboolean x11, const char *retv, const char *info,
                  const char *rofi_data, JsonObject *root) {
    MenuState state = parse_state(rofi_data);

    /* --- Custom-Keys zuerst --- */
    if (g_strcmp0(retv, RETV_CUSTOM_1) == 0) {  /* q → prev page */
        state.page = MAX(0, state.page - 1);
        play_sound("nav");
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }
    else if (g_strcmp0(retv, RETV_CUSTOM_2) == 0) {  /* e → next page / Sync in Root */
        if (!state.vmode && (!state.path || !*state.path)) {
            play_sound("enter");
            run_manual_icon_sync_and_notify();
        } else {
            state.page++;
            play_sound("nav");
        }
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }
    else if (g_strcmp0(retv, RETV_CUSTOM_3) == 0) {  /* x → back/exit */
        if (state.vmode) {
            g_free(state.vmode); state.vmode = NULL;
            state.page = 0;
            play_sound("nav");
            render_menu(menu_name, root, &state);
            free_state(&state);
            return;
        } else if (state.path && *state.path) {
            char *last_slash = strrchr(state.path, '/');
            if (last_slash) *last_slash = '\0';
            else { g_free(state.path); state.path = g_strdup(""); }
            state.page = 0;
            play_sound("nav");
            render_menu(menu_name, root, &state);
            free_state(&state);
            return;
        } else {
            cleanup_files();
            free_state(&state);
            return;
        }
    }

    /* --- Erstaufruf (info == NULL) --- */
    if (!info) {
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }

    /* --- Normale Auswahl (Enter / Klick) --- */
    if (g_strcmp0(info, RAW_EXIT) == 0) {
        cleanup_files();
        free_state(&state);
        return;
    }
    if (g_strcmp0(info, RAW_NEXT) == 0) {
        state.page++;
        play_sound("nav");
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }
    if (g_strcmp0(info, RAW_PREV) == 0) {
        state.page = MAX(0, state.page - 1);
        play_sound("nav");
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }
    if (g_strcmp0(info, RAW_SYNC_ICONS) == 0) {
        play_sound("enter");
        run_manual_icon_sync_and_notify();
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }
    if (g_strcmp0(info, RAW_BACK) == 0) {
        if (state.vmode) {
            g_free(state.vmode); state.vmode = NULL;
            state.page = 0;
        } else if (state.path && *state.path) {
            char *last_slash = strrchr(state.path, '/');
            if (last_slash) *last_slash = '\0';
            else { g_free(state.path); state.path = g_strdup(""); }
            state.page = 0;
        }
        play_sound("nav");
        render_menu(menu_name, root, &state);
        free_state(&state);
        return;
    }

    /* --- Auswahl eines Eintrags (Index) --- */
    if (is_number(info)) {
        int idx = atoi(info);

        if (state.vmode) {
            GPtrArray *apps = NULL;
            if (g_strcmp0(state.vmode, VMODE_DRUN) == 0)
                apps = get_desktop_apps();
            else if (g_strcmp0(state.vmode, VMODE_DRUN_FILTERED) == 0)
                apps = get_filtered_desktop_apps(root);
            else if (g_strcmp0(state.vmode, VMODE_RUN) == 0)
                apps = get_path_binaries();
            if (apps && idx >= 0 && (guint)idx < apps->len) {
                AppEntry *app = g_ptr_array_index(apps, idx);
                if (app && app->exec) {
                    play_sound("enter");
                    exec_detached(app->exec);
                    cleanup_files();
                    free_state(&state);
                    exit(0);
                }
            }
            render_menu(menu_name, root, &state);
            free_state(&state);
            return;
        } else {
            JsonObject *node = resolve_path(root, state.path);
            if (!json_object_has_member(node, "children")) {
                render_menu(menu_name, root, &state);
                free_state(&state);
                return;
            }
            JsonArray *arr = json_object_get_array_member(node, "children");
            if (idx < 0 || (guint)idx >= json_array_get_length(arr)) {
                render_menu(menu_name, root, &state);
                free_state(&state);
                return;
            }
            JsonObject *child = json_node_get_object(json_array_get_element(arr, idx));
            const char *type = json_object_get_string_member(child, "type");
            if (!type) type = "app";

            /* --- Ordner behandeln --- */
            if (g_strcmp0(type, "folder") == 0) {
                char *new_path;
                if (state.path && *state.path)
                    new_path = g_strdup_printf("%s/%d", state.path, idx);
                else
                    new_path = g_strdup_printf("%d", idx);
                g_free(state.path);
                state.path = new_path;
                state.page = 0;
                play_sound("nav");
                render_menu(menu_name, root, &state);
                free_state(&state);
                return;
            }
            /* --- close-prev-window --- */
            else if (g_strcmp0(type, "close-prev-window") == 0) {
                char *addr = read_prev_window_addr();
                if (addr && *addr) {
                    gchar *lua = g_strdup_printf("hl.dsp.window.close({ window = \"address:%s\" })", addr);
                    gchar *lua_q = g_shell_quote(lua);
                    gchar *cmd = g_strdup_printf("hyprctl dispatch %s", lua_q);
                    exec_detached(cmd);
                    g_free(cmd); g_free(lua_q); g_free(lua);
                }
                g_free(addr);
                play_sound("enter");
                cleanup_files();
                free_state(&state);
                exit(0);
            }
            /* --- special-* Modi (führen zu neuem Rendering) --- */
            else if (g_strcmp0(type, "special-drun") == 0 ||
                     g_strcmp0(type, "special-drun-filtered") == 0 ||
                     g_strcmp0(type, "special-run") == 0) {
                g_free(state.vmode);
                if (g_strcmp0(type, "special-drun") == 0)
                    state.vmode = g_strdup(VMODE_DRUN);
                else if (g_strcmp0(type, "special-drun-filtered") == 0)
                    state.vmode = g_strdup(VMODE_DRUN_FILTERED);
                else
                    state.vmode = g_strdup(VMODE_RUN);
                state.page = 0;
                play_sound("nav");
                render_menu(menu_name, root, &state);
                free_state(&state);
                return;
            }
            else if (g_strcmp0(type, "special-window") == 0) {
                play_sound("enter");
                char *mon = focused_monitor_name();
                gchar *theme_path = g_build_filename(g_get_home_dir(), ".config", "rofi", menu_name, "theme.rasi", NULL);

                GString *cmd = g_string_new("rofi -show window ");
                if (x11) g_string_append(cmd, "-x11 ");
                if (mon) {
                    gchar *mon_q = g_shell_quote(mon);
                    g_string_append_printf(cmd, "-monitor %s ", mon_q);
                    g_free(mon_q);
                }
                gchar *theme_q = g_shell_quote(theme_path);
                g_string_append_printf(cmd, "-theme %s", theme_q);
                g_free(theme_q);
                for (int k = 0; WASD_KB_ARGS[k]; k++) {
                    gchar *aq = g_shell_quote(WASD_KB_ARGS[k]);
                    g_string_append_printf(cmd, " %s", aq);
                    g_free(aq);
                }

                exec_detached(cmd->str);
                g_string_free(cmd, TRUE);
                g_free(theme_path);
                g_free(mon);
                cleanup_files();
                free_state(&state);
                exit(0);
            }
            /* --- Jeder andere Typ ("action"/"app"): exec-Feld ausführen --- */
            else {
                const char *exec_cmd = json_object_get_string_member(child, "exec");
                if (exec_cmd && *exec_cmd) {
                    play_sound("enter");
                    if (g_strcmp0(type, "action") == 0) {
                        /* hyprctl-dispatch-Befehle (fullscreen, swapwithmaster,
                         * minimize, pin, ...) wirken implizit auf das "aktive
                         * Fenster". Solange Rofi als Layer-Surface mit
                         * exklusivem Fokus noch gemappt ist, zieht Hyprland
                         * den Fokus sofort wieder auf Rofi zurück - daher
                         * erst (aktiv pollend statt blind sleep) auf das
                         * vorherige Fenster fokussieren, DANN die eigentliche
                         * Aktion feuern, alles als eine Kette in einem
                         * einzigen detached Shell-Aufruf. */
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
                    cleanup_files();
                    free_state(&state);
                    exit(0);
                }
                /* Fallback: neu rendern */
                render_menu(menu_name, root, &state);
                free_state(&state);
                return;
            }
        }
    }

    /* Fallback */
    render_menu(menu_name, root, &state);
    free_state(&state);
}

/* --------------------------- Hauptprogramm --------------------------- */
int main(int argc, char *argv[]) {
    char *menu_name = g_strdup("launcher");
    gboolean x11 = FALSE;
    for (int i = 1; i < argc; i++) {
        if (g_strcmp0(argv[i], "--menu") == 0 && i + 1 < argc) {
            g_free(menu_name);
            menu_name = g_strdup(argv[i + 1]);
            i++;
        } else if (g_strcmp0(argv[i], "--x11") == 0) {
            x11 = TRUE;
        }
    }

    const char *retv = g_getenv("ROFI_RETV");
    const char *info = g_getenv("ROFI_INFO");
    const char *rofi_data = g_getenv("ROFI_DATA");
    if (!retv) retv = "";
    /* Beim allerersten Aufruf (info fehlt) ist ROFI_RETV laut rofi-script(5)
     * "0" (nicht leer!) - hier einmalig das zuvor aktive Fenster merken, für
     * "close-prev-window"- und "action"-Einträge. */
    if (!info && (g_strcmp0(retv, "0") == 0 || g_strcmp0(retv, "") == 0)) {
        save_active_window();
    }

    JsonObject *root = load_menu_json(menu_name);
    if (!root) {
        g_printerr("Fehler: Konnte %s/menu.json nicht laden.\n", menu_name);
        g_free(menu_name);
        return 1;
    }

    handle_step(menu_name, x11, retv, info, rofi_data, root);

    json_object_unref(root);
    g_free(menu_name);
    return 0;
}
