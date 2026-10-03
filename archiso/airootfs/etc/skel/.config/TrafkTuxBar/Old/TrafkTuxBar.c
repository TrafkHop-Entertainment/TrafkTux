/* ═══════════════════════════════════════════════════════════════════
 *  TrafkTuxBar.c - custom GTK/Layer-Shell Statusbar fuer Hyprland
 *
 *  Einzeldatei-Build (bewusst so gehalten): dieses eine File ersetzt
 *  komplett waybar + style.css + WaybarAutohideDaemon.c/.service.
 *
 *  Visuelles Konzept:
 *   - Bar-Hintergrund: Bar.png per 3-/9-Slice gezeichnet (Ecken bleiben
 *     unverzerrt, nur die Mitte wird gestreckt) statt CSS-background.
 *   - Jedes Modul ist eine "Bubble" aus zwei Bildern (Hintergrund +
 *     Vordergrund), Icon/Text liegt dazwischen -> wirkt wirklich "in"
 *     der Blase. Hover blendet weich zwischen normal/hover ueber.
 *   - Icons kommen aus einem echten Icon-Theme (z.B. "Clay") statt aus
 *     einer Nerd Font.
 *   - Autohide + Show/Hide-Transition sind Teil dieses einen Prozesses
 *     (kein externer Daemon + Signale mehr noetig).
 *
 *  Konfiguration: ~/.config/TrafkTuxBar/TrafkTuxBar.jsonc
 *  Blasen-Bilder erwartet unter /tmp/ (bubble-normal.png etc., analog
 *  zum bisherigen rofi/waybar-Setup, das sie beim Hyprland-Start dorthin
 *  kopiert) - siehe README.md.
 * ═══════════════════════════════════════════════════════════════════ */

#include <cairo.h>
#include <errno.h>
#include <glib-unix.h>
#include <glib.h>
#include <glob.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <gdk-pixbuf/gdk-pixbuf.h>
#include <gdk/gdk.h>
#include <gio/gio.h>
#include <gio/gdesktopappinfo.h>
#include <gtk-layer-shell/gtk-layer-shell.h>
#include <gtk/gtk.h>
#include <json-glib/json-glib.h>
#include <sys/signalfd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/prctl.h>

/* ───────────────────────── config : Typen/Deklarationen ───────────────────────── */
/* ── Modul-Typen ─────────────────────────────────────────────── */
typedef enum {
    MOD_BUTTON = 0,     /* einfacher Klick-Button (appmenu, shortcuts, ...) */
    MOD_CLOCK,          /* Uhrzeit, per Timer aktualisiert */
    MOD_HYPR_WORKSPACES,/* dynamische Workspace-Pillen + Taskbar-Icons */
    MOD_TRAY,           /* StatusNotifierItem Systemtray */
    MOD_SPACER,         /* fester Leerraum zum optischen Gruppieren */
    MOD_BUTTON_ROW,     /* horizontale Reihe von Buttons, max_width + Scrollbalken (z.B. gepinnte Apps) */
    MOD_WIDGET_GRID      /* Buttons, die bei max_width umbrechen; Balken blaettert zwischen den Zeilen */
} ModuleType;

typedef struct {
    ModuleType type;

    char *id;              /* frei waehlbarer Bezeichner, fuer Logs */
    char *icon_name;        /* Icon-Theme-Name (z.B. "system-shutdown") */
    char *icon_active_name;  /* optionales Icon im "active"-Zustand */
    char *text;              /* statischer Text statt/zusaetzlich zum Icon */
    char *tooltip;

    char *on_click;          /* Shell-Kommando, Taste links */
    char *on_click_right;    /* Shell-Kommando, Taste rechts */
    char *on_click_middle;   /* Shell-Kommando, mittlere Taste */

    /* optionales Polling wie waybar custom/-Module:
     * exec_cmd wird alle exec_interval_sec ausgefuehrt; liefert entweder
     * reinen Text (-> tooltip) oder JSON {"text":..,"tooltip":..,"class":".."}
     * (return_type_json = TRUE). "class":"active" schaltet die Blase
     * dauerhaft auf die Hover-Optik (wie .active in der alten style.css). */
    char *exec_cmd;
    int   exec_interval_sec;
    gboolean exec_return_json;

    char *clock_format;      /* nur MOD_CLOCK */
    char *clock_format_alt;  /* nur MOD_CLOCK, Rechtsklick toggelt */

    int   spacer_width;      /* nur MOD_SPACER, in px */

    GPtrArray *items;         /* ModuleConfig*, nur MOD_BUTTON_ROW/MOD_WIDGET_GRID */
    int   max_width;          /* nur MOD_HYPR_WORKSPACES (Apps-Reihe): Fallback, falls monitor-Erkennung fehlschlaegt */
    int   visible_count;      /* nur MOD_BUTTON_ROW/MOD_WIDGET_GRID: wie viele Items IMMER angezeigt werden,
                                * bevor der Rest auf eine neue Zeile/Seite umbricht - anders als max_width
                                * ist das aufloesungs-/skalierungs-unabhaengig ("immer genau 3"), was der
                                * eigentliche Sinn dieses Feldes ist. Default 3. */
} ModuleConfig;

static void module_free(gpointer p); /* Vorwaertsdeklaration: parse_module() unten braucht sie schon
                                       * als Free-Func fuer verschachtelte "items"-Module. */

typedef struct {
    int left_slice, right_slice;
    char *image_path;
} NineSliceConfig;

typedef struct {
    char *bg_normal_path;
    char *bg_hover_path;
    char *fg_normal_path;   /* darf leer sein -> kein Vordergrund-Layer */
    char *fg_hover_path;    /* faellt auf fg_normal_path zurueck wenn leer */
    int   transition_ms;    /* Dauer der Hover-Ueberblendung in ms */
    int   min_size;         /* min-width/min-height, wie frueher CSS min-width */
    int   padding;          /* Innenabstand um Icon/Text, wie frueher CSS padding */
    int   margin;           /* Aussenabstand zwischen Blasen, wie frueher CSS margin */
} BubbleConfig;

typedef struct {
    /* Fenster / Layer */
    char *position;         /* "top" | "bottom" */
    int   height;            /* logische Hoehe des Inhaltsbereichs */
    gboolean exclusive_zone;

    /* Hintergrundbild der ganzen Bar (3-/9-Slice) */
    NineSliceConfig bar_bg;

    /* Blasen-Optik fuer alle Module */
    BubbleConfig bubble;

    /* Icons */
    char *icon_theme;
    int   icon_size;

    /* Farben */
    GdkRGBA text_color;
    GdkRGBA text_color_hover;

    /* Autohide */
    gboolean autohide_enabled;
    int   trigger_px;
    int   hide_px;
    int   touch_timeout_sec;
    int   slide_ms;
    int   edge_overhang_px;  /* Wie viele Pixel der Kantensensor ueber den Bildschirmrand
                               * hinaus reicht (negativer Rand an der Bildschirmkante).
                               * Erleichtert das Aufrufen der Bar bei Monitoren, die ueber
                               * anderen Monitoren positioniert sind. Standard 10px. */

    int   edge_margin;   /* Abstand der Module-Boxen zum Bar-Rand (siehe Kommentar bei config_load) */

    /* Mehrere Monitore: Name des Ausgangs, auf dem die Bar erscheinen soll
     * (z.B. "eDP-1" oder "HDMI-A-1" - mit "hyprctl monitors" herausfinden).
     * Gesetzt = Bar bleibt fest an diesem Monitor. Leer/NULL = die EINE
     * Bar folgt dem Cursor: sie zieht auf den Monitor um, an dessen Rand
     * der Cursor die Bar ausloest. */
    char *monitor;

    /* Center-Modul (offene Fenster): wie viel vom LOGISCHEN (skalierten)
     * Breite des Ziel-Monitors maximal fuer die Reihe offener Fenster
     * verwendet wird, bevor der Rest auf eine neue Zeile/Seite umbricht -
     * das macht die Breite automatisch aufloesungs-/skalierungs-
     * unabhaengig statt eines festen Pixelwerts. */
    double center_width_fraction;

    /* Module */
    GPtrArray *modules_left;    /* ModuleConfig* */
    GPtrArray *modules_center;
    GPtrArray *modules_right;

    char *config_dir;    /* Verzeichnis, in dem config.jsonc lag -> fuer relative Pfade */
} BarConfig;

BarConfig *config_load(const char *path);
char      *config_resolve_asset(BarConfig *cfg, const char *maybe_relative);
void       config_free(BarConfig *cfg);


/* ═══════════════════════════ config : Implementierung ═══════════════════════════ */
/* ── Hilfsfunktionen fuer nachsichtiges JSON-Lesen ──────────────────
 * json-glib kann von Haus aus keine "//"-Kommentare (JSONC). Wir
 * filtern sie vor dem Parsen simpel raus: "//" ausserhalb von
 * Strings entfernt den Rest der Zeile. Das reicht fuer unsere
 * Config-Dateien vollkommen aus und erlaubt weiterhin ein Format,
 * das sich liest wie das alte waybar config.jsonc. */
static char *strip_jsonc_comments(const char *src) {
    GString *out = g_string_sized_new(strlen(src));
    gboolean in_string = FALSE;
    gboolean escaped = FALSE;
    for (const char *p = src; *p; p++) {
        if (in_string) {
            g_string_append_c(out, *p);
            if (escaped) escaped = FALSE;
            else if (*p == '\\') escaped = TRUE;
            else if (*p == '"') in_string = FALSE;
            continue;
        }
        if (*p == '"') { in_string = TRUE; g_string_append_c(out, *p); continue; }
        if (*p == '/' && *(p + 1) == '/') {
            while (*p && *p != '\n') p++;
            if (!*p) break;
            g_string_append_c(out, '\n');
            continue;
        }
        g_string_append_c(out, *p);
    }
    return g_string_free(out, FALSE);
}

static const char *jstr(JsonObject *o, const char *key, const char *def) {
    if (o && json_object_has_member(o, key)) {
        JsonNode *n = json_object_get_member(o, key);
        if (JSON_NODE_HOLDS_VALUE(n)) return json_object_get_string_member(o, key);
    }
    return def;
}
static int jint(JsonObject *o, const char *key, int def) {
    if (o && json_object_has_member(o, key))
        return (int)json_object_get_int_member(o, key);
    return def;
}
static gboolean jbool(JsonObject *o, const char *key, gboolean def) {
    if (o && json_object_has_member(o, key))
        return json_object_get_boolean_member(o, key);
    return def;
}
static JsonObject *jobj(JsonObject *o, const char *key) {
    if (o && json_object_has_member(o, key)) {
        JsonNode *n = json_object_get_member(o, key);
        if (JSON_NODE_HOLDS_OBJECT(n)) return json_object_get_object_member(o, key);
    }
    return NULL;
}

static void parse_color(const char *hex, GdkRGBA *out, const char *fallback) {
    if (!hex || !gdk_rgba_parse(out, hex)) {
        gdk_rgba_parse(out, fallback);
    }
}

static ModuleType parse_module_type(const char *s) {
    if (!s) return MOD_BUTTON;
    if (g_strcmp0(s, "clock") == 0) return MOD_CLOCK;
    if (g_strcmp0(s, "hyprland_workspaces") == 0) return MOD_HYPR_WORKSPACES;
    if (g_strcmp0(s, "tray") == 0) return MOD_TRAY;
    if (g_strcmp0(s, "spacer") == 0) return MOD_SPACER;
    if (g_strcmp0(s, "button_row") == 0) return MOD_BUTTON_ROW;
    if (g_strcmp0(s, "widget_grid") == 0) return MOD_WIDGET_GRID;
    return MOD_BUTTON;
}

static void parse_module_array(JsonObject *root, const char *key, GPtrArray *out); /* s.u. */

static ModuleConfig *parse_module(JsonObject *mo) {
    ModuleConfig *m = g_new0(ModuleConfig, 1);
    m->type = parse_module_type(jstr(mo, "type", "button"));
    m->id = g_strdup(jstr(mo, "id", "module"));
    m->icon_name = g_strdup(jstr(mo, "icon", NULL));
    m->icon_active_name = g_strdup(jstr(mo, "icon_active", NULL));
    m->text = g_strdup(jstr(mo, "text", NULL));
    m->tooltip = g_strdup(jstr(mo, "tooltip", NULL));
    m->on_click = g_strdup(jstr(mo, "on_click", NULL));
    m->on_click_right = g_strdup(jstr(mo, "on_click_right", NULL));
    m->on_click_middle = g_strdup(jstr(mo, "on_click_middle", NULL));
    m->exec_cmd = g_strdup(jstr(mo, "exec_cmd", NULL));
    m->exec_interval_sec = jint(mo, "exec_interval_sec", 0);
    m->exec_return_json = jbool(mo, "exec_return_json", FALSE);
    m->spacer_width = jint(mo, "width", 20);
    m->clock_format = g_strdup(jstr(mo, "format", "%H:%M"));
    m->clock_format_alt = g_strdup(jstr(mo, "format_alt", "%d.%m.%Y"));
    m->max_width = jint(mo, "max_width", 220);
    m->visible_count = jint(mo, "visible_count", 3);
    /* items: verschachtelte Buttons fuer button_row/widget_grid. Der
     * Free-Func wird direkt hier gesetzt, damit ein "items"-Array nie
     * unbeaufsichtigt herumliegt. */
    m->items = g_ptr_array_new_with_free_func(module_free);
    if (m->type == MOD_BUTTON_ROW || m->type == MOD_WIDGET_GRID)
        parse_module_array(mo, "items", m->items);
    return m;
}

static void parse_module_array(JsonObject *root, const char *key, GPtrArray *out) {
    if (!root || !json_object_has_member(root, key)) return;
    JsonArray *arr = json_object_get_array_member(root, key);
    guint n = json_array_get_length(arr);
    for (guint i = 0; i < n; i++) {
        JsonObject *mo = json_array_get_object_element(arr, i);
        if (mo) g_ptr_array_add(out, parse_module(mo));
    }
}

BarConfig *config_load(const char *path) {
    GError *err = NULL;
    char *raw = NULL;
    gsize len = 0;
    if (!g_file_get_contents(path, &raw, &len, &err)) {
        g_printerr("[config] Kann %s nicht lesen: %s\n", path, err ? err->message : "?");
        if (err) g_error_free(err);
        return NULL;
    }

    char *clean = strip_jsonc_comments(raw);
    g_free(raw);

    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, clean, -1, &err)) {
        g_printerr("[config] JSON-Fehler in %s: %s\n", path, err ? err->message : "?");
        if (err) g_error_free(err);
        g_free(clean);
        g_object_unref(parser);
        return NULL;
    }
    g_free(clean);

    JsonNode *root_node = json_parser_get_root(parser);
    JsonObject *root = json_node_get_object(root_node);

    BarConfig *cfg = g_new0(BarConfig, 1);
    cfg->config_dir = g_path_get_dirname(path);

    cfg->position = g_strdup(jstr(root, "position", "bottom"));
    cfg->height = jint(root, "height", 45);
    cfg->exclusive_zone = jbool(root, "exclusive_zone", FALSE);
    /* Abstand links/rechts, bevor die erste/letzte Modul-Blase beginnt -
     * soll erst NACH der Rundung der Bar-Ecke anfangen, siehe Redesign-
     * Skizze. Default grosszuegiger als die alten fest verdrahteten 15px. */
    cfg->edge_margin = jint(root, "edge_margin", 34);
    cfg->monitor = g_strdup(jstr(root, "monitor", ""));
    cfg->center_width_fraction = json_object_has_member(root, "center_width_fraction")
        ? json_object_get_double_member(root, "center_width_fraction") : 0.30;

    JsonObject *bg = jobj(root, "bar_background");
    cfg->bar_bg.image_path = g_strdup(jstr(bg, "image", "Bar.png"));
    cfg->bar_bg.left_slice = jint(bg, "left_slice", 140);
    cfg->bar_bg.right_slice = jint(bg, "right_slice", 140);

    JsonObject *bub = jobj(root, "bubble");
    cfg->bubble.bg_normal_path = g_strdup(jstr(bub, "bg_normal", "bubble-normal.png"));
    cfg->bubble.bg_hover_path = g_strdup(jstr(bub, "bg_hover", "bubble-selected.png"));
    cfg->bubble.fg_normal_path = g_strdup(jstr(bub, "fg_normal", NULL));
    cfg->bubble.fg_hover_path = g_strdup(jstr(bub, "fg_hover", NULL));
    cfg->bubble.transition_ms = jint(bub, "transition_ms", 140);
    cfg->bubble.min_size = jint(bub, "min_size", 28);
    cfg->bubble.padding = jint(bub, "padding", 8);
    cfg->bubble.margin = jint(bub, "margin", 5);

    cfg->icon_theme = g_strdup(jstr(root, "icon_theme", "Clay"));
    cfg->icon_size = jint(root, "icon_size", 20);

    parse_color(jstr(root, "text_color", NULL), &cfg->text_color, "#fff495");
    parse_color(jstr(root, "text_color_hover", NULL), &cfg->text_color_hover, "#c8b800");

    JsonObject *ah = jobj(root, "autohide");
    cfg->autohide_enabled = jbool(ah, "enabled", TRUE);
    cfg->trigger_px = jint(ah, "trigger_px", 5);
    cfg->hide_px = jint(ah, "hide_px", 65);
    cfg->edge_overhang_px = jint(ah, "edge_overhang_px", 10);
    cfg->touch_timeout_sec = jint(ah, "touch_timeout_sec", 5);
    cfg->slide_ms = jint(ah, "slide_ms", 220);

    cfg->modules_left = g_ptr_array_new();
    cfg->modules_center = g_ptr_array_new();
    cfg->modules_right = g_ptr_array_new();
    parse_module_array(root, "modules_left", cfg->modules_left);
    parse_module_array(root, "modules_center", cfg->modules_center);
    parse_module_array(root, "modules_right", cfg->modules_right);

    g_object_unref(parser);
    return cfg;
}

char *config_resolve_asset(BarConfig *cfg, const char *maybe_relative) {
    if (!maybe_relative) return NULL;
    if (g_path_is_absolute(maybe_relative)) return g_strdup(maybe_relative);
    return g_build_filename(cfg->config_dir, "assets", maybe_relative, NULL);
}

static void module_free(gpointer p) {
    ModuleConfig *m = p;
    g_free(m->id); g_free(m->icon_name); g_free(m->icon_active_name);
    g_free(m->text); g_free(m->tooltip);
    g_free(m->on_click); g_free(m->on_click_right); g_free(m->on_click_middle);
    g_free(m->exec_cmd); g_free(m->clock_format); g_free(m->clock_format_alt);
    if (m->items) g_ptr_array_free(m->items, TRUE); /* free_func = module_free, siehe parse_module() */
    g_free(m);
}

void config_free(BarConfig *cfg) {
    if (!cfg) return;
    g_free(cfg->position);
    g_free(cfg->monitor);
    g_free(cfg->bar_bg.image_path);
    g_free(cfg->bubble.bg_normal_path); g_free(cfg->bubble.bg_hover_path);
    g_free(cfg->bubble.fg_normal_path); g_free(cfg->bubble.fg_hover_path);
    g_free(cfg->icon_theme);
    g_free(cfg->config_dir);
    if (cfg->modules_left) { g_ptr_array_set_free_func(cfg->modules_left, module_free); g_ptr_array_free(cfg->modules_left, TRUE); }
    if (cfg->modules_center) { g_ptr_array_set_free_func(cfg->modules_center, module_free); g_ptr_array_free(cfg->modules_center, TRUE); }
    if (cfg->modules_right) { g_ptr_array_set_free_func(cfg->modules_right, module_free); g_ptr_array_free(cfg->modules_right, TRUE); }
    g_free(cfg);
}


/* ───────────────────────── nine_slice : Typen/Deklarationen ───────────────────────── */
/* WICHTIG - NEUES Modell (ersetzt die vorherige top_slice/bottom_slice-
 * Variante komplett): unser Bar.png hat eine UNGEWOEHNLICH grosse
 * Rundung (bis zu 172px tief), waehrend die Bar in der Praxis viel
 * kuerzer sein soll (z.B. 60-80px). Klassisches 9-Slice ("Ecken NIE
 * skalieren") zwingt die Bar-Hoehe dann auf mindestens 172px - das war
 * der Grund fuer die "viel zu grosse Bar".
 *
 * Stattdessen wird die Ecke jetzt UNIFORM (gleicher Faktor in Breite
 * UND Hoehe) auf die Ziel-Hoehe skaliert - die Rundung wird bei einer
 * kuerzeren Bar einfach proportional kleiner, genau wie beim
 * Verkleinern eines ganzen Bildes, statt sie zu verzerren. Nur die
 * MITTE wird noch (rein horizontal) gestreckt, um beliebige Breiten zu
 * fuellen - unbedenklich, weil dieser Bereich im Quellbild ohnehin
 * einfarbig ist. */
typedef struct NineSlice NineSlice;

NineSlice *nine_slice_load(const char *path, int left, int right, GError **error);
void       nine_slice_draw(NineSlice *ns, cairo_t *cr, double w, double h);
void       nine_slice_free(NineSlice *ns);


/* ═══════════════════════════ nine_slice : Implementierung ═══════════════════════════ */
struct NineSlice {
    GdkPixbuf *src;
    int left, right; /* Breite der Ecken-Bereiche IM QUELLBILD (Pixel) */
    int sw, sh;       /* Quellgroesse */
    /* Fertig gerenderte Bar (Groesse+Skalierung des Ziels). Vorher wurde
     * bei JEDEM Redraw das komplette Full-HD-Bild neu konvertiert und
     * skaliert (gdk_cairo_set_source_pixbuf erzeugt jedes Mal eine neue
     * Cairo-Surface) - das waren die 100-300ms in process_updates. */
    cairo_surface_t *cache;
    int cache_w, cache_h;
};

NineSlice *nine_slice_load(const char *path, int left, int right, GError **error) {
    GdkPixbuf *pb = gdk_pixbuf_new_from_file(path, error);
    if (!pb) return NULL;

    NineSlice *ns = g_new0(NineSlice, 1);
    ns->src = pb;
    ns->sw = gdk_pixbuf_get_width(pb);
    ns->sh = gdk_pixbuf_get_height(pb);
    ns->left = CLAMP(left, 0, ns->sw / 2);
    ns->right = CLAMP(right, 0, ns->sw / 2);
    return ns;
}

/* Kopiert ein Rechteck aus dem Quellbild (sx,sy,sw,sh) skaliert auf
 * das Zielrechteck (dx,dy,dw,dh). Bei dw/sw==dh/sh ist das eine
 * UNIFORME Skalierung (keine Verzerrung). */
static void blit(cairo_t *cr, GdkPixbuf *src,
                  int sx, int sy, int sw, int sh,
                  double dx, double dy, double dw, double dh) {
    if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) return;

    cairo_save(cr);
    cairo_rectangle(cr, dx, dy, dw, dh);
    cairo_clip(cr);

    cairo_translate(cr, dx, dy);
    cairo_scale(cr, dw / (double)sw, dh / (double)sh);

    GdkPixbuf *region = gdk_pixbuf_new_subpixbuf(src, sx, sy, sw, sh);
    gdk_cairo_set_source_pixbuf(cr, region, 0, 0);
    cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_BEST);
    cairo_pattern_set_extend(cairo_get_source(cr), CAIRO_EXTEND_PAD);
    cairo_paint(cr);
    g_object_unref(region);

    cairo_restore(cr);
}

static void nine_slice_render(NineSlice *ns, cairo_t *cr, double w, double h) {
    if (!ns || !ns->src || ns->sh <= 0) return;

    /* Uniformer Skalierungsfaktor: die Ecke wird in Breite UND Hoehe
     * um GENAU denselben Faktor skaliert -> keine Verzerrung, egal wie
     * kurz/lang die Ziel-Hoehe ist. */
    double scale = h / (double)ns->sh;
    double corner_l_w = ns->left * scale;
    double corner_r_w = ns->right * scale;

    /* Falls die Bar so schmal ist, dass beide Ecken zusammen breiter
     * waeren als die ganze Bar (kommt in der Praxis kaum vor, aber
     * defensiv abfangen statt mit negativer Mitte zu rechnen). */
    if (corner_l_w + corner_r_w > w && (corner_l_w + corner_r_w) > 0) {
        double f = w / (corner_l_w + corner_r_w);
        corner_l_w *= f;
        corner_r_w *= f;
    }

    /* linke Ecke - uniform skaliert, NIE verzerrt */
    blit(cr, ns->src, 0, 0, ns->left, ns->sh, 0, 0, corner_l_w, h);
    /* rechte Ecke - uniform skaliert, NIE verzerrt */
    blit(cr, ns->src, ns->sw - ns->right, 0, ns->right, ns->sh,
         w - corner_r_w, 0, corner_r_w, h);

    /* Mitte - horizontal gestreckt (Quellbereich ist dort einfarbig,
     * daher unbedenklich), Hoehe folgt dem gleichen uniformen Faktor
     * wie die Ecken (kein separates Vertical-Stretching mehr). */
    int mid_sw = ns->sw - ns->left - ns->right;
    double mid_dw = w - corner_l_w - corner_r_w;
    if (mid_sw > 0 && mid_dw > 0) {
        blit(cr, ns->src, ns->left, 0, mid_sw, ns->sh, corner_l_w, 0, mid_dw, h);
    }
}

/* Zeichnet die Bar aus dem Cache; gerendert wird nur bei Groessenaenderung. */
void nine_slice_draw(NineSlice *ns, cairo_t *cr, double w, double h) {
    if (!ns || !ns->src || ns->sh <= 0 || w <= 0 || h <= 0) return;
    double sx = 1.0, sy = 1.0;
    cairo_surface_get_device_scale(cairo_get_target(cr), &sx, &sy);
    if (sx < 1.0) sx = 1.0;
    int pw = (int)ceil(w * sx), ph = (int)ceil(h * sx);
    if (!ns->cache || ns->cache_w != pw || ns->cache_h != ph) {
        if (ns->cache) cairo_surface_destroy(ns->cache);
        ns->cache = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, pw, ph);
        cairo_surface_set_device_scale(ns->cache, sx, sx);
        cairo_t *cc = cairo_create(ns->cache);
        nine_slice_render(ns, cc, w, h);
        cairo_destroy(cc);
        ns->cache_w = pw;
        ns->cache_h = ph;
    }
    cairo_set_source_surface(cr, ns->cache, 0, 0);
    cairo_paint(cr);
}

/* Wie nine_slice_draw(), verlaengert die Bar aber zusaetzlich um `extra`
 * Pixel NACH UNTEN, indem eine Bildzeile weit unten im Bar-Bild
 * (deckend, nicht der evtl. halbtransparente Rand ganz unten) vertikal
 * auf `extra` Pixel gedehnt wird. Keine Verzerrung der Bar selbst und
 * keine Abhaengigkeit vom Frame-Timing: die Verlaengerung ist IMMER da.
 * Im Ruhezustand liegt sie unter dem Bildschirmrand (unsichtbar), beim
 * Aufklapp-Overshoot deckt sie genau den Bereich ab, in dem sonst ein
 * Spalt zum Desktop zu sehen waere. (Vorher: Bild dehnen per
 * cairo_scale - der Streckfaktor kam durch das Zeichnen im NAECHSTEN
 * Frame aber immer einen Schritt zu spaet, dieser Rueckstand WAR der
 * Spalt.) */
void nine_slice_draw_extended(NineSlice *ns, cairo_t *cr, double w, double h, double extra) {
    nine_slice_draw(ns, cr, w, h);
    if (!ns || !ns->cache || extra <= 0.5) return;
    double src_row = MAX(0.0, h - 4.0); /* logische Zeile knapp ueber dem Rand */
    cairo_save(cr);
    cairo_rectangle(cr, 0, h, w, extra);
    cairo_clip(cr);
    cairo_translate(cr, 0, h);
    cairo_scale(cr, 1.0, extra);
    cairo_set_source_surface(cr, ns->cache, 0, -src_row);
    cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_NEAREST);
    cairo_rectangle(cr, 0, 0, w, 1.0);
    cairo_fill(cr);
    cairo_restore(cr);
}

void nine_slice_free(NineSlice *ns) {
    if (!ns) return;
    if (ns->cache) cairo_surface_destroy(ns->cache);
    if (ns->src) g_object_unref(ns->src);
    g_free(ns);
}


/* ───────────────────────── bubble : Typen/Deklarationen ───────────────────────── */
/* Geteilte, einmal geladene Blasen-Bilder (Hintergrund + Vordergrund,
 * je normal/hover). Werden von ALLEN Bubbles der Bar gemeinsam benutzt -
 * jede Bubble skaliert sie beim Zeichnen nur auf ihre eigene, per Inhalt
 * bestimmte Groesse (genau wie vorher "background-size: 100% 100%"). */
typedef struct {
    GdkPixbuf *bg_normal;
    GdkPixbuf *bg_hover;
    GdkPixbuf *fg_normal;  /* darf NULL sein */
    GdkPixbuf *fg_hover;   /* darf NULL sein (faellt dann auf fg_normal zurueck) */
    GHashTable *scaled;    /* Cache: Groesse -> BubbleScaled (fertig skalierte Surfaces) */
} BubbleAssets;

BubbleAssets *bubble_assets_load(BarConfig *cfg, GError **error);
void          bubble_assets_free(BubbleAssets *a);

typedef void (*TbBubbleClickFn)(gpointer user_data);

typedef struct TbBubble TbBubble;

/* icon_name ODER text angeben (das jeweils andere NULL lassen). */
TbBubble *tb_bubble_new(BubbleAssets *assets, BarConfig *cfg,
                         const char *icon_name, const char *text);

GtkWidget *tb_bubble_widget(TbBubble *b);   /* zum Einhaengen in eine Box */

void tb_bubble_set_click_handlers(TbBubble *b,
                                   TbBubbleClickFn left,
                                   TbBubbleClickFn right,
                                   TbBubbleClickFn middle,
                                   gpointer user_data);
void tb_bubble_set_tooltip(TbBubble *b, const char *tooltip);
void tb_bubble_set_icon(TbBubble *b, const char *icon_name);
void tb_bubble_set_icon_pixbuf(TbBubble *b, GdkPixbuf *pixbuf); /* nimmt eine eigene Referenz */
void tb_bubble_set_text(TbBubble *b, const char *text);
void tb_bubble_set_extra_padding(TbBubble *b, int px); /* Text-Blasen: extra Padding links/rechts */

/* Pinnt die Blase dauerhaft auf die Hover-Optik (z.B. fuer .active
 * Zustaende wie OSK-an oder Hide-Windows-aktiv). Overrides Hover-Handling
 * nicht - beides zusammen ergibt einfach "Ziel=Hover" so oder so. */
void tb_bubble_set_forced_active(TbBubble *b, gboolean active);

/* ── Multi-Icon-Modus (fuer den Tray: EINE gestreckte Blase mit mehreren
 * Icons drin statt einer eigenen Blase pro Icon) ───────────────────────
 * tb_bubble_new_multi() erzeugt eine anfangs LEERE Blase (0 Icons, nicht
 * sichtbar). tb_bubble_add_sub_icon() haengt ein Icon an (Blase wird
 * dabei automatisch breiter + sichtbar), gibt ein opakes Handle zurueck,
 * mit dem man das Icon spaeter aktualisieren oder wieder entfernen kann.
 * Jedes Sub-Icon hat seine EIGENEN Klick-Handler (fuer den Tray: pro
 * Icon ein eigener D-Bus-Client dahinter). Normale tb_bubble_set_icon()/
 * _set_text()/_set_click_handlers()-Aufrufe sind mit einer Multi-Icon-
 * Blase nicht gemeint und werden ignoriert, solange sub_icons nicht leer
 * ist - beide Modi gleichzeitig zu nutzen ist nicht vorgesehen. */
typedef struct TbSubIcon TbSubIcon; /* opakes Handle */
TbBubble *tb_bubble_new_multi(BubbleAssets *assets, BarConfig *cfg);
TbSubIcon *tb_bubble_add_sub_icon(TbBubble *b, GdkPixbuf *icon,
                                   TbBubbleClickFn left, TbBubbleClickFn right,
                                   TbBubbleClickFn middle, gpointer user_data);
void tb_bubble_update_sub_icon(TbBubble *b, TbSubIcon *handle, GdkPixbuf *new_icon);
void tb_bubble_set_sub_icon_tooltip(TbBubble *b, TbSubIcon *handle, const char *tooltip);
void tb_bubble_remove_sub_icon(TbBubble *b, TbSubIcon *handle);

/* Ueberschreibt Schriftgroesse (in px, absolute Groesse, DPI-unabhaengig)
 * und/oder Textfarbe fuer GENAU diese Blase - andere Text-Blasen (z.B.
 * die Workspace-Nummer) bleiben unberuehrt. font_px<=0 = Standardgroesse
 * (vom GTK-Theme geerbt) beibehalten. has_color=FALSE = normale
 * Hover-Blendfarbe (text_color/text_color_hover) beibehalten. */
void tb_bubble_set_text_style(TbBubble *b, double font_px, gboolean has_color, GdkRGBA color);

void tb_bubble_free(TbBubble *b); /* Widget wird NICHT zerstoert (macht GTK selbst) */


/* ═══════════════════════════ bubble : Implementierung ═══════════════════════════ */
struct TbSubIcon {
    GdkPixbuf *icon; /* besessen, darf NULL sein (Fallback: nichts zeichnen) */
    char *tooltip;   /* besessen, darf NULL sein */
    TbBubbleClickFn on_left, on_right, on_middle;
    gpointer user_data;
};

/* Hover-"Pop": Icon/Text wachsen beim Hover federnd (mit Ueberschwingen)
 * auf 1+POP_SCALE. Groesser = staerkerer Effekt. */
#define TB_HOVER_POP_SCALE 0.14
#define TB_HOVER_BOUNCE_C1 3.0

struct TbBubble {
    GtkWidget *event_box;
    GtkWidget *area;

    BubbleAssets *assets;      /* nicht besessen */
    BarConfig    *cfg;         /* nicht besessen */

    GdkPixbuf *icon;           /* besessen, darf NULL sein */
    char      *text;           /* besessen, darf NULL sein */
    double     font_px_override;    /* <=0 = Standardgroesse vom Theme */
    gboolean   has_color_override;
    GdkRGBA    color_override;

    /* Multi-Icon-Modus (Tray) - siehe tb_bubble_new_multi(). Ist dieses
     * Array nicht leer, werden icon/text oben ignoriert und stattdessen
     * jedes TbSubIcon nebeneinander in EINER gestreckten Blase gezeichnet. */
    GPtrArray *sub_icons; /* TbSubIcon*, besessen */

    /* Hover-/Active-Animation */
    gboolean hover_now;        /* Maus gerade drueber? */
    gboolean forced_active;    /* von aussen gepinnt (z.B. .active) */
    double   t;                /* aktueller Blend 0..1 (0=normal, 1=hover) */
    double   t_from;
    double   pop, pop_from;    /* Hover-Pop (darf kurz ueber 1.0 schwingen) */
    gint64   anim_start_us;
    guint    tick_id;          /* Frame-Clock-Tick-Callback (vsync) */

    int      extra_pad_x;      /* zusaetzliches Padding links/rechts (Text) */
    int      text_w_max;       /* breiteste bisher gemessene Textbreite */

    TbBubbleClickFn on_left, on_right, on_middle;
    gpointer cb_user_data;
};

/* ── Assets ──────────────────────────────────────────────────────── */

static GdkPixbuf *load_or_null(const char *path, GError **error) {
    if (!path || !*path) return NULL;
    if (!g_file_test(path, G_FILE_TEST_EXISTS)) return NULL;
    return gdk_pixbuf_new_from_file(path, error);
}

BubbleAssets *bubble_assets_load(BarConfig *cfg, GError **error) {
    BubbleAssets *a = g_new0(BubbleAssets, 1);

    char *bgn = config_resolve_asset(cfg, cfg->bubble.bg_normal_path);
    char *bgh = config_resolve_asset(cfg, cfg->bubble.bg_hover_path);
    char *fgn = config_resolve_asset(cfg, cfg->bubble.fg_normal_path);
    char *fgh = config_resolve_asset(cfg, cfg->bubble.fg_hover_path);

    a->bg_normal = load_or_null(bgn, error);
    if (!a->bg_normal) { g_free(bgn); g_free(bgh); g_free(fgn); g_free(fgh); g_free(a); return NULL; }

    a->bg_hover = load_or_null(bgh, NULL);
    if (!a->bg_hover) a->bg_hover = g_object_ref(a->bg_normal);

    a->fg_normal = load_or_null(fgn, NULL);
    a->fg_hover  = load_or_null(fgh, NULL);
    if (a->fg_hover == NULL && a->fg_normal != NULL) a->fg_hover = g_object_ref(a->fg_normal);

    g_free(bgn); g_free(bgh); g_free(fgn); g_free(fgh);
    return a;
}

void bubble_assets_free(BubbleAssets *a) {
    if (!a) return;
    g_clear_object(&a->bg_normal);
    g_clear_object(&a->bg_hover);
    g_clear_object(&a->fg_normal);
    g_clear_object(&a->fg_hover);
    if (a->scaled) g_hash_table_destroy(a->scaled);
    g_free(a);
}

/* ── Zeichnen ────────────────────────────────────────────────────── */

/* kubisches Ease-in-out fuer die Ueberblendung - fuehlt sich "smooth"
 * an statt linear zu blenden. */
static double ease_in_out_cubic(double x) {
    return x < 0.5 ? 4 * x * x * x : 1 - pow(-2 * x + 2, 3) / 2;
}

/* Fertig auf Bubble-Groesse skalierte Surfaces (bg/fg, normal/hover).
 * Wird pro Groesse EINMAL erzeugt; on_draw blittet dann nur noch. */
typedef struct { cairo_surface_t *s[4]; } BubbleScaled;

static void bubble_scaled_free(gpointer p) {
    BubbleScaled *bs = p;
    for (int i = 0; i < 4; i++)
        if (bs->s[i]) cairo_surface_destroy(bs->s[i]);
    g_free(bs);
}

static cairo_surface_t *scaled_surface_from_pixbuf(GdkPixbuf *pb, int w, int h, int sf) {
    if (!pb || w <= 0 || h <= 0) return NULL;
    int sw = gdk_pixbuf_get_width(pb), sh = gdk_pixbuf_get_height(pb);
    if (sw <= 0 || sh <= 0) return NULL;
    cairo_surface_t *surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w * sf, h * sf);
    cairo_surface_set_device_scale(surf, sf, sf);
    cairo_t *c = cairo_create(surf);
    cairo_scale(c, w / (double)sw, h / (double)sh);
    gdk_cairo_set_source_pixbuf(c, pb, 0, 0);
    cairo_pattern_set_filter(cairo_get_source(c), CAIRO_FILTER_GOOD);
    cairo_pattern_set_extend(cairo_get_source(c), CAIRO_EXTEND_PAD);
    cairo_paint(c);
    cairo_destroy(c);
    return surf;
}

static BubbleScaled *bubble_scaled_get(BubbleAssets *a, int w, int h, int sf) {
    if (sf < 1) sf = 1;
    if (!a->scaled)
        a->scaled = g_hash_table_new_full(g_direct_hash, g_direct_equal, NULL, bubble_scaled_free);
    gpointer key = GSIZE_TO_POINTER(((gsize)sf << 48) | ((gsize)(w & 0xFFFFFF) << 24) | (gsize)(h & 0xFFFFFF));
    BubbleScaled *bs = g_hash_table_lookup(a->scaled, key);
    if (bs) return bs;
    bs = g_new0(BubbleScaled, 1);
    bs->s[0] = scaled_surface_from_pixbuf(a->bg_normal, w, h, sf);
    bs->s[1] = scaled_surface_from_pixbuf(a->bg_hover, w, h, sf);
    bs->s[2] = scaled_surface_from_pixbuf(a->fg_normal, w, h, sf);
    bs->s[3] = scaled_surface_from_pixbuf(a->fg_hover, w, h, sf);
    g_hash_table_insert(a->scaled, key, bs);
    return bs;
}

static void paint_surface(cairo_t *cr, cairo_surface_t *surf, double alpha) {
    if (!surf || alpha <= 0.001) return;
    cairo_set_source_surface(cr, surf, 0, 0);
    if (alpha >= 0.999) cairo_paint(cr);
    else cairo_paint_with_alpha(cr, alpha);
}

static gboolean on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data) {
    TbBubble *b = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(widget, &alloc);
    double w = alloc.width, h = alloc.height;
    if (w <= 0 || h <= 0) return FALSE;

    double t = ease_in_out_cubic(CLAMP(b->t, 0.0, 1.0));
    BubbleScaled *bs = bubble_scaled_get(b->assets, alloc.width, alloc.height,
                                         gtk_widget_get_scale_factor(widget));

    /* 1) Hintergrund - Normal- und Hover-Bild werden ueberblendet
     *    (nicht hart geswitcht), das ergibt die "smoothe Blende". */
    paint_surface(cr, bs->s[0], 1.0 - t);
    paint_surface(cr, bs->s[1], t);

    /* 2) Icon/Text - liegt ZWISCHEN Hintergrund und Vordergrund, damit
     *    er wirklich "in" der Blase sitzt statt nur obendrauf. */
    GdkRGBA col;
    col.red   = b->cfg->text_color.red   + (b->cfg->text_color_hover.red   - b->cfg->text_color.red)   * t;
    col.green = b->cfg->text_color.green + (b->cfg->text_color_hover.green - b->cfg->text_color.green) * t;
    col.blue  = b->cfg->text_color.blue  + (b->cfg->text_color_hover.blue  - b->cfg->text_color.blue)  * t;
    col.alpha = 1.0;

    double pop_s = 1.0 + TB_HOVER_POP_SCALE * b->pop;
    gboolean is_multi = (b->sub_icons && b->sub_icons->len > 0);
    if (!is_multi) {
        cairo_save(cr);
        cairo_translate(cr, w / 2.0, h / 2.0);
        cairo_scale(cr, pop_s, pop_s);
        cairo_translate(cr, -w / 2.0, -h / 2.0);
    }

    if (b->sub_icons && b->sub_icons->len > 0) {
        /* Multi-Icon-Modus: alle Icons nebeneinander in gleich breiten
         * Slots innerhalb DERSELBEN (bereits oben gestreckt gezeichneten)
         * Blase - genau das "eine schoen gestreckte Blase statt einer pro
         * Icon"-Layout, das der Tray benutzt. */
        guint n = b->sub_icons->len;
        double slot_w = w / (double)n;
        for (guint i = 0; i < n; i++) {
            TbSubIcon *si = g_ptr_array_index(b->sub_icons, i);
            if (!si->icon) continue;
            int iw = gdk_pixbuf_get_width(si->icon);
            int ih = gdk_pixbuf_get_height(si->icon);
            double slot_cx = slot_w * i + slot_w / 2.0;
            double x = slot_cx - iw / 2.0, y = (h - ih) / 2.0;
            cairo_save(cr);
            cairo_translate(cr, slot_cx, h / 2.0);
            cairo_scale(cr, pop_s, pop_s);
            cairo_translate(cr, -slot_cx, -h / 2.0);
            gdk_cairo_set_source_pixbuf(cr, si->icon, x, y);
            cairo_paint(cr);
            cairo_restore(cr);
        }
    } else if (b->icon) {
        int iw = gdk_pixbuf_get_width(b->icon);
        int ih = gdk_pixbuf_get_height(b->icon);
        double x = (w - iw) / 2.0, y = (h - ih) / 2.0;

        /* Icon in der Blendfarbe einfaerben (die meisten Icon-Packs sind
         * Symbolic/mono; fuer volltonige Icons einfach mit alpha 1.0
         * unveraendert zeichnen - siehe icons_recolor unten). */
        gdk_cairo_set_source_pixbuf(cr, b->icon, x, y);
        cairo_paint(cr);
        (void)col;
    } else if (b->text && *b->text) {
        PangoLayout *layout = gtk_widget_create_pango_layout(widget, b->text);
        if (b->font_px_override > 0) {
            /* Kopie der vom Theme geerbten Schrift, NUR die Groesse
             * geaendert - Familie/Gewicht etc. bleiben wie vom Theme
             * vorgegeben, nur eben in einer anderen, absoluten (Px-,
             * nicht Pt-, also DPI-unabhaengigen) Groesse. */
            PangoContext *pctx = gtk_widget_get_pango_context(widget);
            PangoFontDescription *fd =
                pango_font_description_copy(pango_context_get_font_description(pctx));
            pango_font_description_set_absolute_size(fd, b->font_px_override * PANGO_SCALE);
            pango_layout_set_font_description(layout, fd);
            pango_font_description_free(fd);
        }
        GdkRGBA text_col = b->has_color_override ? b->color_override : col;
        int tw, th;
        pango_layout_get_pixel_size(layout, &tw, &th);
        cairo_save(cr);
        cairo_set_source_rgba(cr, text_col.red, text_col.green, text_col.blue, text_col.alpha);
        cairo_move_to(cr, (w - tw) / 2.0, (h - th) / 2.0);
        pango_cairo_show_layout(cr, layout);
        cairo_restore(cr);
        g_object_unref(layout);
    }

    if (!is_multi) cairo_restore(cr);

    /* 3) Vordergrund (Glanzlicht/Kante) - liegt ueber allem und macht
     *    aus Hintergrund+Icon eine "echte" Blase mit Tiefe. */
    paint_surface(cr, bs->s[2], 1.0 - t);
    paint_surface(cr, bs->s[3], t);

    return FALSE;
}

/* ── Animation ───────────────────────────────────────────────────── */

/* Hover-Animation laeuft ueber den GDK-Frame-Clock (vsync-synchron, also
 * auch bei 120 Hz und mehr glatt). Der frueher vermutete "Frame-Clock
 * haengt die Event-Loop auf"-Effekt war in Wahrheit der blockierende
 * read() im Hyprland-Event-Kanal (laengst per NONBLOCK behoben); ein
 * Frame-Clock-Stillstand kann nur das Zeichnen, nie die Loop blockieren.
 * Gezeichnet wird pro Frame nur ueber gecachte Surfaces - praktisch gratis. */
static double ease_out_cubic(double x) {
    double inv = 1.0 - x;
    return 1.0 - inv * inv * inv;
}

/* ease-out-back mit einstellbarer Staerke c1 (1.7 = ~10% Ueberschwingen,
 * 3.0 = ~25%). */
static double ease_out_back_c(double x, double c1) {
    double c3 = c1 + 1.0;
    double u = x - 1.0;
    return 1.0 + c3 * u * u * u + c1 * u * u;
}

static gboolean bubble_tick_cb(GtkWidget *widget, GdkFrameClock *clock, gpointer user_data) {
    (void)widget;
    TbBubble *b = user_data;
    gint64 now = gdk_frame_clock_get_frame_time(clock);
    double duration_us = MAX(1, b->cfg->bubble.transition_ms) * 1000.0;
    double target = (b->hover_now || b->forced_active) ? 1.0 : 0.0;
    double raw = CLAMP((now - b->anim_start_us) / duration_us, 0.0, 1.0);
    double e = ease_out_cubic(raw);
    b->t = b->t_from + (target - b->t_from) * e;
    /* Beim Hovern federt der Pop ueber sein Ziel hinaus und faengt sich,
     * beim Verlassen faehrt er glatt zurueck. */
    double pe = target > 0.5 ? ease_out_back_c(raw, TB_HOVER_BOUNCE_C1) : e;
    b->pop = b->pop_from + (target - b->pop_from) * pe;

    if (raw >= 1.0) {
        b->t = target;
        b->pop = target;
        gtk_widget_queue_draw(b->area);
        b->tick_id = 0;
        return G_SOURCE_REMOVE;
    }
    gtk_widget_queue_draw(b->area);
    return G_SOURCE_CONTINUE;
}

static void restart_animation_toward_target(TbBubble *b) {
    double target = (b->hover_now || b->forced_active) ? 1.0 : 0.0;
    if (fabs(b->t - target) < 0.001 && fabs(b->pop - target) < 0.001) return; /* schon da */

    b->t_from = b->t;
    b->pop_from = b->pop;
    b->anim_start_us = g_get_monotonic_time();
    if (b->tick_id == 0)
        b->tick_id = gtk_widget_add_tick_callback(b->area, bubble_tick_cb, b, NULL);
}

/*  Events  */

static gboolean on_enter(GtkWidget *w, GdkEventCrossing *ev, gpointer user_data) {
    (void)w; (void)ev;
    TbBubble *b = user_data;
    b->hover_now = TRUE;
    restart_animation_toward_target(b);
    return FALSE;
}

static gboolean on_leave(GtkWidget *w, GdkEventCrossing *ev, gpointer user_data) {
    (void)w; (void)ev;
    TbBubble *b = user_data;
    b->hover_now = FALSE;
    restart_animation_toward_target(b);
    return FALSE;
}

static gboolean on_button_press(GtkWidget *w, GdkEventButton *ev, gpointer user_data) {
    TbBubble *b = user_data;

    if (b->sub_icons && b->sub_icons->len > 0) {
        /* Multi-Icon-Modus: erst rausfinden, welcher Slot geklickt wurde
         * (x-Position innerhalb der Blase geteilt durch Slot-Breite),
         * dann an DESSEN eigene Handler weiterreichen statt an b->on_*. */
        guint n = b->sub_icons->len;
        GtkAllocation alloc;
        gtk_widget_get_allocation(w, &alloc);
        double slot_w = alloc.width / (double)n;
        int idx = slot_w > 0 ? (int)(ev->x / slot_w) : 0;
        idx = CLAMP(idx, 0, (int)n - 1);
        TbSubIcon *si = g_ptr_array_index(b->sub_icons, idx);
        g_message("[click] Multi-Icon-Blase: Slot %d/%u getroffen (button=%u)", idx, n, ev->button);
        if (ev->type != GDK_BUTTON_PRESS) return FALSE;
        switch (ev->button) {
            case GDK_BUTTON_PRIMARY:   if (si->on_left)   si->on_left(si->user_data);   break;
            case GDK_BUTTON_SECONDARY: if (si->on_right)  si->on_right(si->user_data);  break;
            case GDK_BUTTON_MIDDLE:    if (si->on_middle) si->on_middle(si->user_data); break;
            default: break;
        }
        return TRUE;
    }

    g_message("[click] button-press-event empfangen: button=%u type=%d has_left=%d has_right=%d has_middle=%d",
              ev->button, ev->type, b->on_left != NULL, b->on_right != NULL, b->on_middle != NULL);
    if (ev->type != GDK_BUTTON_PRESS) return FALSE;
    switch (ev->button) {
        case GDK_BUTTON_PRIMARY:
            if (b->on_left) { g_message("[click] -> on_left() wird aufgerufen"); b->on_left(b->cb_user_data); }
            else g_message("[click] -> KEIN on_left-Handler gesetzt, nichts passiert");
            break;
        case GDK_BUTTON_SECONDARY:
            if (b->on_right) b->on_right(b->cb_user_data);
            break;
        case GDK_BUTTON_MIDDLE:
            if (b->on_middle) b->on_middle(b->cb_user_data);
            break;
        default:
            break;
    }
    return TRUE;
}

/* ── API ─────────────────────────────────────────────────────────── */

static GdkPixbuf *lookup_icon(BarConfig *cfg, const char *icon_name) {
    if (!icon_name || !*icon_name) return NULL;
    GtkIconTheme *theme = gtk_icon_theme_get_default();
    /* Konfiguriertes Icon-Theme (z.B. "Clay") zusaetzlich zum System-
     * Default durchsuchen, falls es nicht global gesetzt ist. */
    if (cfg->icon_theme && *cfg->icon_theme) {
        GtkSettings *settings = gtk_settings_get_default();
        gchar *current = NULL;
        g_object_get(settings, "gtk-icon-theme-name", &current, NULL);
        if (g_strcmp0(current, cfg->icon_theme) != 0) {
            g_object_set(settings, "gtk-icon-theme-name", cfg->icon_theme, NULL);
        }
        g_free(current);
    }
    GError *err = NULL;
    GdkPixbuf *pb = gtk_icon_theme_load_icon(theme, icon_name, cfg->icon_size,
                                              GTK_ICON_LOOKUP_FORCE_SIZE, &err);
    if (!pb) {
        g_warning("[bubble] Icon '%s' nicht gefunden: %s", icon_name, err ? err->message : "?");
        if (err) g_error_free(err);
    }
    return pb;
}

TbBubble *tb_bubble_new(BubbleAssets *assets, BarConfig *cfg,
                         const char *icon_name, const char *text) {
    TbBubble *b = g_new0(TbBubble, 1);
    b->assets = assets;
    b->cfg = cfg;
    b->t = 0.0;
    b->t_from = 0.0;

    if (icon_name) b->icon = lookup_icon(cfg, icon_name);
    if (text) b->text = g_strdup(text);

    b->area = g_object_ref_sink(gtk_drawing_area_new());
    gtk_widget_set_name(b->area, "tb-bubble-area");

    int min_w = cfg->bubble.min_size + 2 * cfg->bubble.padding;
    int min_h = cfg->bubble.min_size + 2 * cfg->bubble.padding;
    if (b->text && *b->text) {
        /* Text darf die Blase in der Breite aufziehen (wie vorher
         * durch CSS padding/auto-width), Hoehe bleibt fix. */
        PangoLayout *layout = gtk_widget_create_pango_layout(b->area, b->text);
        int tw, th;
        pango_layout_get_pixel_size(layout, &tw, &th);
        min_w = MAX(min_w, tw + 2 * cfg->bubble.padding);
        min_h = MAX(min_h, th + 2 * cfg->bubble.padding);
        g_object_unref(layout);
    }
    gtk_widget_set_size_request(b->area, min_w, min_h);

    g_signal_connect(b->area, "draw", G_CALLBACK(on_draw), b);

    b->event_box = gtk_event_box_new();
    gtk_widget_set_can_focus(b->event_box, FALSE);
    /* WICHTIG: ohne das hier wird die Bubble von GtkBox auf die volle
     * Hoehe der Bar gedehnt (GtkBox gibt Kindern in der Querachse
     * standardmaessig die volle Boxhoehe, unabhaengig von
     * pack_start(expand=FALSE,fill=FALSE), das gilt nur fuer die
     * Hauptachse!) - dadurch wurden aus runden Blasen laenglich
     * gestreckte Ovale, sobald die Bar hoeher als die Blase selbst
     * ist. GTK_ALIGN_CENTER haelt die Blase bei ihrer natuerlichen
     * (quadratischen) Groesse und zentriert sie vertikal in der Bar. */
    gtk_widget_set_halign(b->event_box, GTK_ALIGN_CENTER);
    gtk_widget_set_valign(b->event_box, GTK_ALIGN_CENTER);
    gtk_widget_set_margin_start(b->event_box, cfg->bubble.margin);
    gtk_widget_set_margin_end(b->event_box, cfg->bubble.margin);
    gtk_widget_set_margin_top(b->event_box, cfg->bubble.margin);
    gtk_widget_set_margin_bottom(b->event_box, cfg->bubble.margin);
    gtk_container_add(GTK_CONTAINER(b->event_box), b->area);

    gtk_widget_add_events(b->event_box, GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK |
                                         GDK_BUTTON_PRESS_MASK);
    g_signal_connect(b->event_box, "enter-notify-event", G_CALLBACK(on_enter), b);
    g_signal_connect(b->event_box, "leave-notify-event", G_CALLBACK(on_leave), b);
    g_signal_connect(b->event_box, "button-press-event", G_CALLBACK(on_button_press), b);

    return b;
}

GtkWidget *tb_bubble_widget(TbBubble *b) { return b->event_box; }

void tb_bubble_set_click_handlers(TbBubble *b, TbBubbleClickFn left, TbBubbleClickFn right,
                                   TbBubbleClickFn middle, gpointer user_data) {
    b->on_left = left;
    b->on_right = right;
    b->on_middle = middle;
    b->cb_user_data = user_data;
}

void tb_bubble_set_tooltip(TbBubble *b, const char *tooltip) {
    gtk_widget_set_tooltip_text(b->event_box, tooltip);
}

void tb_bubble_set_icon(TbBubble *b, const char *icon_name) {
    g_clear_object(&b->icon);
    b->icon = lookup_icon(b->cfg, icon_name);
    gtk_widget_queue_draw(b->area);
}

void tb_bubble_set_icon_pixbuf(TbBubble *b, GdkPixbuf *pixbuf) {
    g_clear_object(&b->icon);
    b->icon = pixbuf ? g_object_ref(pixbuf) : NULL;
    gtk_widget_queue_draw(b->area);
}

/* Berechnet die Mindestgroesse fuer Text-Blasen mit der TATSAECHLICH
 * verwendeten Schrift (inkl. font_px_override) plus extra_pad_x. Die
 * Breite waechst nur (text_w_max), damit die Blase nicht bei jeder
 * Ziffernaenderung der Uhr um ein paar Pixel hin- und herspringt. */
static void bubble_update_text_size(TbBubble *b) {
    if (!b->text || !*b->text || b->icon) return;
    if (b->sub_icons && b->sub_icons->len > 0) return;
    PangoLayout *layout = gtk_widget_create_pango_layout(b->area, b->text);
    if (b->font_px_override > 0) {
        PangoContext *pctx = gtk_widget_get_pango_context(b->area);
        PangoFontDescription *fd =
            pango_font_description_copy(pango_context_get_font_description(pctx));
        pango_font_description_set_absolute_size(fd, b->font_px_override * PANGO_SCALE);
        pango_layout_set_font_description(layout, fd);
        pango_font_description_free(fd);
    }
    int tw = 0, th = 0;
    pango_layout_get_pixel_size(layout, &tw, &th);
    g_object_unref(layout);
    b->text_w_max = MAX(b->text_w_max, tw);
    int pad = b->cfg->bubble.padding;
    int min_w = MAX(b->cfg->bubble.min_size + 2 * pad, b->text_w_max + 2 * (pad + b->extra_pad_x));
    int min_h = MAX(b->cfg->bubble.min_size + 2 * pad, th + 2 * pad);
    gtk_widget_set_size_request(b->area, min_w, min_h);
}

void tb_bubble_set_extra_padding(TbBubble *b, int px) {
    b->extra_pad_x = MAX(0, px);
    bubble_update_text_size(b);
    gtk_widget_queue_draw(b->area);
}

void tb_bubble_set_text(TbBubble *b, const char *text) {
    g_free(b->text);
    b->text = g_strdup(text);
    bubble_update_text_size(b);
    gtk_widget_queue_draw(b->area);
}

void tb_bubble_set_text_style(TbBubble *b, double font_px, gboolean has_color, GdkRGBA color) {
    b->font_px_override = font_px;
    bubble_update_text_size(b);
    b->has_color_override = has_color;
    if (has_color) b->color_override = color;
    gtk_widget_queue_draw(b->area);
}

void tb_bubble_set_forced_active(TbBubble *b, gboolean active) {
    if (b->forced_active == active) return;
    b->forced_active = active;
    restart_animation_toward_target(b);
}

void tb_bubble_free(TbBubble *b) {
    if (!b) return;
    /* tick_id ist ein Frame-Clock-Tick-Callback auf b->area. Wir halten
     * selbst eine Referenz auf b->area (siehe tb_bubble_new), damit das
     * Objekt auch nach gtk_widget_destroy() gueltig bleibt und das
     * Entfernen hier immer sicher ist (Reihenfolge egal). */
    if (b->tick_id && b->area)
        gtk_widget_remove_tick_callback(b->area, b->tick_id);
    b->tick_id = 0;
    g_clear_object(&b->icon);
    g_free(b->text);
    if (b->sub_icons) {
        for (guint i = 0; i < b->sub_icons->len; i++) {
            TbSubIcon *si = g_ptr_array_index(b->sub_icons, i);
            g_clear_object(&si->icon);
            g_free(si->tooltip);
            g_free(si);
        }
        g_ptr_array_free(b->sub_icons, TRUE);
    }
    g_clear_object(&b->area);
    g_free(b);
}

/* ── Multi-Icon-Modus (Tray) ─────────────────────────────────────── */

/* Breite = N Icon-Slots (je min_size breit, wie die Icon-Flaeche einer
 * normalen Blase) + Rand-Padding, Hoehe wie eine normale Blase. Bei 0
 * Icons wird die Blase komplett versteckt statt auf 0 Breite geschrumpft
 * - eine 0px breite, aber trotzdem "sichtbare" leere Blase wuerde als
 * hauchduenner Strich aufblitzen, sobald das allererste Icon dazukommt. */
static void bubble_resize_for_sub_icons(TbBubble *b) {
    guint n = b->sub_icons ? b->sub_icons->len : 0;
    if (n == 0) {
        gtk_widget_hide(b->event_box);
        return;
    }
    int slot = b->cfg->bubble.min_size;
    int w = (int)n * slot + 2 * b->cfg->bubble.padding;
    int h = b->cfg->bubble.min_size + 2 * b->cfg->bubble.padding;
    gtk_widget_set_size_request(b->area, w, h);
    gtk_widget_show_all(b->event_box);
}

/* Ermittelt aus x/y (Widget-Koordinaten des event_box) den getroffenen
 * Sub-Icon-Slot - dieselbe Rechnung wie in on_button_press(), nur fuer
 * Tooltips statt Klicks. GTK ruft das auf, sobald die Maus kurz ueber
 * einem Widget mit has-tooltip=TRUE ruht. */
static gboolean on_query_tooltip(GtkWidget *w, gint x, gint y, gboolean keyboard_mode,
                                  GtkTooltip *tooltip, gpointer user_data) {
    (void)keyboard_mode;
    TbBubble *b = user_data;
    if (!b->sub_icons || b->sub_icons->len == 0) return FALSE;
    guint n = b->sub_icons->len;
    GtkAllocation alloc;
    gtk_widget_get_allocation(w, &alloc);
    (void)y;
    double slot_w = alloc.width / (double)n;
    int idx = slot_w > 0 ? (int)(x / slot_w) : 0;
    idx = CLAMP(idx, 0, (int)n - 1);
    TbSubIcon *si = g_ptr_array_index(b->sub_icons, idx);
    if (!si->tooltip || !*si->tooltip) return FALSE;
    gtk_tooltip_set_text(tooltip, si->tooltip);
    return TRUE;
}

TbBubble *tb_bubble_new_multi(BubbleAssets *assets, BarConfig *cfg) {
    TbBubble *b = g_new0(TbBubble, 1);
    b->assets = assets;
    b->cfg = cfg;
    b->t = 0.0;
    b->t_from = 0.0;
    b->sub_icons = g_ptr_array_new();

    b->area = g_object_ref_sink(gtk_drawing_area_new());
    gtk_widget_set_name(b->area, "tb-bubble-area");
    g_signal_connect(b->area, "draw", G_CALLBACK(on_draw), b);

    b->event_box = gtk_event_box_new();
    gtk_widget_set_can_focus(b->event_box, FALSE);
    gtk_widget_set_halign(b->event_box, GTK_ALIGN_CENTER);
    gtk_widget_set_valign(b->event_box, GTK_ALIGN_CENTER);
    gtk_widget_set_margin_start(b->event_box, cfg->bubble.margin);
    gtk_widget_set_margin_end(b->event_box, cfg->bubble.margin);
    gtk_widget_set_margin_top(b->event_box, cfg->bubble.margin);
    gtk_widget_set_margin_bottom(b->event_box, cfg->bubble.margin);
    gtk_container_add(GTK_CONTAINER(b->event_box), b->area);

    gtk_widget_add_events(b->event_box, GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK |
                                         GDK_BUTTON_PRESS_MASK);
    g_signal_connect(b->event_box, "enter-notify-event", G_CALLBACK(on_enter), b);
    g_signal_connect(b->event_box, "leave-notify-event", G_CALLBACK(on_leave), b);
    g_signal_connect(b->event_box, "button-press-event", G_CALLBACK(on_button_press), b);

    /* Pro-Icon-Tooltips statt einem einzigen fuer die ganze Blase - siehe
     * on_query_tooltip(). */
    gtk_widget_set_has_tooltip(b->event_box, TRUE);
    g_signal_connect(b->event_box, "query-tooltip", G_CALLBACK(on_query_tooltip), b);

    bubble_resize_for_sub_icons(b); /* startet mit 0 Icons -> versteckt */
    return b;
}

TbSubIcon *tb_bubble_add_sub_icon(TbBubble *b, GdkPixbuf *icon,
                                   TbBubbleClickFn left, TbBubbleClickFn right,
                                   TbBubbleClickFn middle, gpointer user_data) {
    TbSubIcon *si = g_new0(TbSubIcon, 1);
    si->icon = icon ? g_object_ref(icon) : NULL;
    si->on_left = left;
    si->on_right = right;
    si->on_middle = middle;
    si->user_data = user_data;
    g_ptr_array_add(b->sub_icons, si);
    bubble_resize_for_sub_icons(b);
    gtk_widget_queue_draw(b->area);
    return si;
}

void tb_bubble_update_sub_icon(TbBubble *b, TbSubIcon *handle, GdkPixbuf *new_icon) {
    if (!handle) return;
    g_clear_object(&handle->icon);
    handle->icon = new_icon ? g_object_ref(new_icon) : NULL;
    gtk_widget_queue_draw(b->area);
}

void tb_bubble_set_sub_icon_tooltip(TbBubble *b, TbSubIcon *handle, const char *tooltip) {
    (void)b;
    if (!handle) return;
    g_free(handle->tooltip);
    handle->tooltip = g_strdup(tooltip);
}

void tb_bubble_remove_sub_icon(TbBubble *b, TbSubIcon *handle) {
    if (!handle || !b->sub_icons) return;
    if (g_ptr_array_remove(b->sub_icons, handle)) {
        g_clear_object(&handle->icon);
        g_free(handle);
        bubble_resize_for_sub_icons(b);
        gtk_widget_queue_draw(b->area);
    }
}


/* ───────────────────────── hypr_ipc : Typen/Deklarationen ───────────────────────── */
typedef struct {
    float x, y, w, h;
    float reserved_top, reserved_bottom, reserved_left, reserved_right;
    int id;
    char name[64];   /* Ausgangsname wie "eDP-1"/"HDMI-A-1" - fest statt Pointer,
                       * damit die bestehenden g_free(mons)-Aufrufe ueberall
                       * unveraendert bleiben koennen (kein extra Feld zum
                       * Freigeben, kein Leck-Risiko). */
} HyprMonitor;

typedef struct {
    int id;
    char *name;
} HyprWorkspace;

typedef struct {
    char *address;      /* "0x...", eindeutige Fenster-Adresse */
    char *class_name;    /* fuer Icon-Lookup */
    char *title;
    int   workspace_id;
    gboolean minimized;  /* liegt in special:minimized */
} HyprClient;

/* Verbindet sich mit dem Hyprland-IPC-Socket (.socket.sock fuer Befehle,
 * .socket2.sock fuer Events). Gibt FALSE zurueck, wenn kein laufendes
 * Hyprland gefunden wurde (z.B. Bar wird zum Testen unter X11 gestartet). */
gboolean hypr_ipc_init(void);
gboolean hypr_ipc_available(void);

gboolean hypr_ipc_get_cursor_pos(int *x, int *y);

/* monitors: von hypr_ipc_get_monitors() (Aufrufer besitzt); *out_count
 * gesetzt. Muss mit g_free() freigegeben werden. */
HyprMonitor *hypr_ipc_get_monitors(int *out_count);

/* Workspaces sortiert nach id. Freigeben mit hypr_ipc_free_workspaces(). */
GPtrArray *hypr_ipc_get_workspaces(void);
void hypr_ipc_free_workspaces(GPtrArray *ws);

/* Alle Clients (Fenster), inkl. minimierter. Freigeben mit
 * hypr_ipc_free_clients(). */
GPtrArray *hypr_ipc_get_clients(void);
void hypr_ipc_free_clients(GPtrArray *clients);

int hypr_ipc_get_active_workspace_id(void);

void hypr_ipc_dispatch(const char *dispatcher_and_args); /* "hyprctl dispatch ..." Kurzform */

/* Vorwaerts-Deklarationen fuer die Autohide-Anbindung des OSK-Moduls
 * (btn_exec_poll() weiter unten braucht das, TbAutohide selbst wird aber
 * erst viel spaeter im "Autohide: Implementierung"-Abschnitt vollstaendig
 * definiert - siehe dort fuer die eigentliche Struct/Funktions-Definition). */
typedef struct TbAutohide TbAutohide;
static TbAutohide *g_autohide_singleton;
static void tb_autohide_set_force_visible(TbAutohide *ah, gboolean active);
static void tb_autohide_menu_hold(TbAutohide *ah, gboolean hold); /* Bar sichtbar halten solange ein Menue offen ist */

/* Event-Abo: callback wird bei JEDER Zeile vom .socket2.sock aufgerufen,
 * z.B. "workspace>>2", "activewindow>>class,title", "openwindow>>...".
 * Laeuft ueber einen GIOChannel im Main-Loop-Thread - kein eigener Thread
 * noetig, blockiert also nichts. */
typedef void (*HyprEventFn)(const char *event_line, gpointer user_data);
void hypr_ipc_subscribe_events(HyprEventFn fn, gpointer user_data);


/* ═══════════════════════════ hypr_ipc : Implementierung ═══════════════════════════ */
static char g_cmd_sock_path[512] = {0};
static char g_evt_sock_path[512] = {0};
static gboolean g_available = FALSE;

static int workspace_compare(gconstpointer a, gconstpointer b) {
    HyprWorkspace * const *wa = a;
    HyprWorkspace * const *wb = b;
    return (*wa)->id - (*wb)->id;
}

/* Findet beide Hyprland-Sockets analog zur alten WaybarAutohideDaemon.c:
 * bevorzugt HYPRLAND_INSTANCE_SIGNATURE, sonst erster Treffer per glob. */
static gboolean find_sockets(void) {
    const char *sig = g_getenv("HYPRLAND_INSTANCE_SIGNATURE");
    const char *runtime = g_getenv("XDG_RUNTIME_DIR");
    char default_runtime[64];
    if (!runtime) {
        g_snprintf(default_runtime, sizeof(default_runtime), "/run/user/%d", getuid());
        runtime = default_runtime;
    }

    if (sig) {
        g_snprintf(g_cmd_sock_path, sizeof(g_cmd_sock_path), "%s/hypr/%s/.socket.sock", runtime, sig);
        g_snprintf(g_evt_sock_path, sizeof(g_evt_sock_path), "%s/hypr/%s/.socket2.sock", runtime, sig);
        if (g_file_test(g_cmd_sock_path, G_FILE_TEST_EXISTS)) return TRUE;
    }

    char pattern[512];
    g_snprintf(pattern, sizeof(pattern), "%s/hypr/*/.socket.sock", runtime);
    glob_t glob_result;
    memset(&glob_result, 0, sizeof(glob_result));
    if (glob(pattern, 0, NULL, &glob_result) == 0 && glob_result.gl_pathc > 0) {
        g_strlcpy(g_cmd_sock_path, glob_result.gl_pathv[0], sizeof(g_cmd_sock_path));
        char *evt = g_strdup(g_cmd_sock_path);
        char *pos = strstr(evt, ".socket.sock");
        if (pos) {
            *pos = '\0';
            g_snprintf(g_evt_sock_path, sizeof(g_evt_sock_path), "%s.socket2.sock", evt);
        }
        g_free(evt);
        globfree(&glob_result);
        return TRUE;
    }
    globfree(&glob_result);
    return FALSE;
}

gboolean hypr_ipc_init(void) {
    g_available = find_sockets();
    if (!g_available) {
        g_warning("[hypr_ipc] Kein Hyprland-Socket gefunden - Workspace-Modul bleibt leer.");
    }
    return g_available;
}

gboolean hypr_ipc_available(void) { return g_available; }

static char *hypr_cmd(const char *cmd) {
    if (!g_available) return NULL;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return NULL;
    struct timeval tv = { .tv_sec = 1, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    g_strlcpy(addr.sun_path, g_cmd_sock_path, sizeof(addr.sun_path));
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) { close(fd); return NULL; }
    if (write(fd, cmd, strlen(cmd)) < 0) { close(fd); return NULL; }
    shutdown(fd, SHUT_WR);

    size_t buf_size = 4096, len = 0;
    char *buf = g_malloc(buf_size);
    while (1) {
        if (len + 1024 > buf_size) { buf_size *= 2; buf = g_realloc(buf, buf_size); }
        ssize_t n = read(fd, buf + len, 1024);
        if (n <= 0) break;
        len += (size_t)n;
    }
    buf[len] = '\0';
    close(fd);
    return buf;
}

gboolean hypr_ipc_get_cursor_pos(int *x, int *y) {
    char *out = hypr_cmd("cursorpos");
    if (!out) return FALSE;
    char *comma = strchr(out, ',');
    gboolean ok = FALSE;
    if (comma) {
        *x = atoi(out);
        *y = atoi(comma + 1);
        ok = TRUE;
    }
    g_free(out);
    return ok;
}

HyprMonitor *hypr_ipc_get_monitors(int *out_count) {
    *out_count = 0;
    char *out = hypr_cmd("j/monitors");
    if (!out) return NULL;

    GError *err = NULL;
    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, out, -1, &err)) {
        g_warning("[hypr_ipc] monitors JSON: %s", err ? err->message : "?");
        if (err) g_error_free(err);
        g_object_unref(parser);
        g_free(out);
        return NULL;
    }
    g_free(out);

    JsonArray *arr = json_node_get_array(json_parser_get_root(parser));
    guint n = json_array_get_length(arr);
    HyprMonitor *mons = g_new0(HyprMonitor, n);
    int count = 0;
    for (guint i = 0; i < n && count < 64; i++) {
        JsonObject *o = json_array_get_object_element(arr, i);
        if (!o) continue;
        if (json_object_has_member(o, "disabled") && json_object_get_boolean_member(o, "disabled"))
            continue;
        mons[count].id = json_object_has_member(o, "id") ? (int)json_object_get_int_member(o, "id") : count;
        if (json_object_has_member(o, "name")) {
            const char *nm = json_object_get_string_member(o, "name");
            if (nm) g_strlcpy(mons[count].name, nm, sizeof(mons[count].name));
        }
        mons[count].x = json_object_has_member(o, "x") ? (float)json_object_get_double_member(o, "x") : 0;
        mons[count].y = json_object_has_member(o, "y") ? (float)json_object_get_double_member(o, "y") : 0;

        /* WICHTIG: "width"/"height" in hyprctl monitors -j sind die
         * PHYSISCHEN Pixel, waehrend "cursorpos" & "x"/"y" in LOGISCHEN
         * (Layout-)Koordinaten sind - bei scale != 1.0 muessen wir
         * durch den Skalierungsfaktor teilen, sonst "haengt" der
         * berechnete Rand weit ausserhalb dessen, was der Cursor
         * ueberhaupt erreichen kann. */
        double scale = json_object_has_member(o, "scale") ? json_object_get_double_member(o, "scale") : 1.0;
        if (scale <= 0.0) scale = 1.0;
        double raw_w = json_object_has_member(o, "width") ? json_object_get_int_member(o, "width") : 0;
        double raw_h = json_object_has_member(o, "height") ? json_object_get_int_member(o, "height") : 0;
        mons[count].w = (float)(raw_w / scale);
        mons[count].h = (float)(raw_h / scale);

        /* "reserved": [left, top, right, bottom] - Platz, den eine
         * andere Exclusive-Zone-Surface (z.B. ein zweites Panel) am
         * jeweiligen Rand bereits belegt. Ohne das hier abzuziehen,
         * erreicht der Cursor den von uns angenommenen Bildschirmrand
         * nie, weil das andere Panel ihn vorher blockiert. */
        if (json_object_has_member(o, "reserved")) {
            JsonArray *rsv = json_object_get_array_member(o, "reserved");
            if (rsv && json_array_get_length(rsv) >= 4) {
                mons[count].reserved_left   = (float)json_array_get_double_element(rsv, 0);
                mons[count].reserved_top    = (float)json_array_get_double_element(rsv, 1);
                mons[count].reserved_right  = (float)json_array_get_double_element(rsv, 2);
                mons[count].reserved_bottom = (float)json_array_get_double_element(rsv, 3);
            }
        }
        if (mons[count].w <= 0 || mons[count].h <= 0) continue;
        count++;
    }
    *out_count = count;
    g_object_unref(parser);
    return mons;
}

/* Sucht in einer hypr_ipc_get_monitors()-Liste den per cfg->monitor
 * benannten Ausgang; leer/NULL/nicht gefunden -> erster Monitor (best
 * effort, wie an anderen Stellen in dieser Datei schon so gehandhabt,
 * z.B. ah_update_base_offset()). Gibt NULL zurueck nur wenn die Liste
 * leer ist. */
static HyprMonitor *find_target_hypr_monitor(BarConfig *cfg, HyprMonitor *mons, int count) {
    if (!mons || count <= 0) return NULL;
    if (cfg->monitor && *cfg->monitor) {
        for (int i = 0; i < count; i++) {
            if (g_strcmp0(mons[i].name, cfg->monitor) == 0) return &mons[i];
        }
        g_warning("[monitor] '%s' nicht unter den aktuell erkannten Monitoren gefunden "
                  "(pruefe den Namen mit 'hyprctl monitors') - falle auf den ersten Monitor zurueck.",
                  cfg->monitor);
    }
    return &mons[0];
}

/* Hyprland-Monitor, in dem der Cursor (logische Koordinaten) gerade liegt;
 * NULL, wenn er in keinem liegt. Obere Grenzen exklusiv, damit zwei
 * nebeneinanderliegende Monitore am gemeinsamen Rand eindeutig bleiben. */
static HyprMonitor *tb_hypr_monitor_at(HyprMonitor *mons, int count, int cx, int cy) {
    for (int i = 0; i < count; i++) {
        HyprMonitor *m = &mons[i];
        if (cx >= m->x && cx < m->x + m->w && cy >= m->y && cy < m->y + m->h)
            return m;
    }
    return NULL;
}

/* Passenden GdkMonitor zu einem Hyprland-Monitor finden. gtk-layer-shell
 * braucht ein echtes GdkMonitor*, Hyprland liefert nur Namen/Position.
 * GDKs Monitor-Geometrie liegt unter Wayland in denselben logischen
 * Koordinaten wie Hyprlands x/y -> Match ueber die Position, als
 * Rueckfall ueber eine eindeutige Groesse. NULL, wenn nichts passt. */
static GdkMonitor *tb_gdk_monitor_for_hypr(const HyprMonitor *m) {
    if (!m) return NULL;
    GdkDisplay *disp = gdk_display_get_default();
    if (!disp) return NULL;
    int n = gdk_display_get_n_monitors(disp);
    GdkMonitor *best = NULL, *by_size = NULL;
    double best_d = 1e9;
    int size_hits = 0;
    for (int i = 0; i < n; i++) {
        GdkMonitor *gm = gdk_display_get_monitor(disp, i);
        GdkRectangle g;
        gdk_monitor_get_geometry(gm, &g);
        double d = fabs(g.x - m->x) + fabs(g.y - m->y);
        if (d < best_d) { best_d = d; best = gm; }
        if (fabs(g.width - m->w) < 2 && fabs(g.height - m->h) < 2) { by_size = gm; size_hits++; }
    }
    if (best && best_d < 4) return best;
    if (size_hits == 1) return by_size;
    return NULL;
}

/* Monitor, auf dem die Bar gerade sitzt (wird in apply_layer_shell()
 * gesetzt, danach vom Autohide bei jedem Umzug nachgefuehrt). */
static char        g_bar_monitor_name[64];
static GdkMonitor *g_bar_gdk_monitor;

GPtrArray *hypr_ipc_get_workspaces(void) {
    char *out = hypr_cmd("j/workspaces");
    GPtrArray *result = g_ptr_array_new();
    if (!out) return result;

    GError *err = NULL;
    JsonParser *parser = json_parser_new();
    if (json_parser_load_from_data(parser, out, -1, &err)) {
        JsonArray *arr = json_node_get_array(json_parser_get_root(parser));
        guint n = json_array_get_length(arr);
        for (guint i = 0; i < n; i++) {
            JsonObject *o = json_array_get_object_element(arr, i);
            if (!o) continue;
            const char *name = json_object_has_member(o, "name") ? json_object_get_string_member(o, "name") : "";
            if (name && g_str_has_prefix(name, "special")) continue; /* wie show-special:false */
            HyprWorkspace *w = g_new0(HyprWorkspace, 1);
            w->id = json_object_has_member(o, "id") ? (int)json_object_get_int_member(o, "id") : 0;
            w->name = g_strdup(name);
            g_ptr_array_add(result, w);
        }
    } else if (err) {
        g_error_free(err);
    }
    g_object_unref(parser);
    g_free(out);

    /* nach id sortieren */
    g_ptr_array_sort(result, workspace_compare);
    return result;
}

void hypr_ipc_free_workspaces(GPtrArray *ws) {
    if (!ws) return;
    for (guint i = 0; i < ws->len; i++) {
        HyprWorkspace *w = g_ptr_array_index(ws, i);
        g_free(w->name);
        g_free(w);
    }
    g_ptr_array_free(ws, TRUE);
}

GPtrArray *hypr_ipc_get_clients(void) {
    char *out = hypr_cmd("j/clients");
    GPtrArray *result = g_ptr_array_new();
    if (!out) return result;

    GError *err = NULL;
    JsonParser *parser = json_parser_new();
    if (json_parser_load_from_data(parser, out, -1, &err)) {
        JsonArray *arr = json_node_get_array(json_parser_get_root(parser));
        guint n = json_array_get_length(arr);
        for (guint i = 0; i < n; i++) {
            JsonObject *o = json_array_get_object_element(arr, i);
            if (!o) continue;
            HyprClient *c = g_new0(HyprClient, 1);
            c->address = g_strdup(json_object_has_member(o, "address") ? json_object_get_string_member(o, "address") : "");
            c->class_name = g_strdup(json_object_has_member(o, "class") ? json_object_get_string_member(o, "class") : "");
            c->title = g_strdup(json_object_has_member(o, "title") ? json_object_get_string_member(o, "title") : "");
            if (json_object_has_member(o, "workspace")) {
                JsonObject *wso = json_object_get_object_member(o, "workspace");
                c->workspace_id = wso && json_object_has_member(wso, "id") ? (int)json_object_get_int_member(wso, "id") : 0;
            }
            c->minimized = c->workspace_id < 0; /* special:minimized hat neg. id */
            g_ptr_array_add(result, c);
        }
    } else if (err) {
        g_error_free(err);
    }
    g_object_unref(parser);
    g_free(out);
    return result;
}

void hypr_ipc_free_clients(GPtrArray *clients) {
    if (!clients) return;
    for (guint i = 0; i < clients->len; i++) {
        HyprClient *c = g_ptr_array_index(clients, i);
        g_free(c->address); g_free(c->class_name); g_free(c->title);
        g_free(c);
    }
    g_ptr_array_free(clients, TRUE);
}

int hypr_ipc_get_active_workspace_id(void) {
    char *out = hypr_cmd("j/activeworkspace");
    if (!out) return -1;
    int id = -1;
    GError *err = NULL;
    JsonParser *parser = json_parser_new();
    if (json_parser_load_from_data(parser, out, -1, &err)) {
        JsonObject *o = json_node_get_object(json_parser_get_root(parser));
        if (o && json_object_has_member(o, "id")) id = (int)json_object_get_int_member(o, "id");
    } else if (err) g_error_free(err);
    g_object_unref(parser);
    g_free(out);
    return id;
}

void hypr_ipc_dispatch(const char *dispatcher_and_args) {
    char *cmd = g_strdup_printf("dispatch %s", dispatcher_and_args);
    char *out = hypr_cmd(cmd);
    g_free(cmd);
    g_free(out);
}

/* ── Event-Subscription ─────────────────────────────────────────── */

typedef struct {
    HyprEventFn fn;
    gpointer user_data;
} EventSub;

static gboolean on_evt_readable(GIOChannel *chan, GIOCondition cond, gpointer user_data) {
    EventSub *sub = user_data;
    if (cond & (G_IO_HUP | G_IO_ERR)) {
        g_warning("[hypr_ipc] Event-Socket getrennt.");
        return G_SOURCE_REMOVE;
    }
    gchar *line = NULL;
    gsize len = 0;
    GError *err = NULL;
    GIOStatus st;
    while ((st = g_io_channel_read_line(chan, &line, &len, NULL, &err)) == G_IO_STATUS_NORMAL) {
        if (line) {
            g_strchomp(line);
            if (*line) sub->fn(line, sub->user_data);
            g_free(line);
            line = NULL;
        }
    }
    /* G_IO_STATUS_AGAIN ist der NORMALE, erwartete Weg aus dieser
     * Schleife: "gerade keine weitere komplette Zeile im Puffer" - kein
     * Fehler. Der Kanal MUSS dafuer non-blocking sein (siehe
     * hypr_ipc_subscribe_events()) - sonst blockiert
     * g_io_channel_read_line() hier synchron im read()-Syscall, bis
     * Hyprland die naechste Zeile schickt. Das passiert im HAUPTTHREAD
     * (gtk_main()) - waehrenddessen steht die GESAMTE Event-Loop still:
     * keine Timer, keine Klicks, nichts. Genau DAS war der Grund fuer
     * das komplette Einfrieren der Bar (per gdb-Backtrace bestaetigt:
     * Thread 1 hing exakt hier in read()). */
    if (st == G_IO_STATUS_ERROR || st == G_IO_STATUS_EOF) {
        g_warning("[hypr_ipc] Event-Socket-Lesefehler oder EOF (status=%d)%s%s.",
                  st, err ? ": " : "", err ? err->message : "");
        if (err) g_error_free(err);
        return G_SOURCE_REMOVE;
    }
    if (err) g_error_free(err);
    return G_SOURCE_CONTINUE;
}

void hypr_ipc_subscribe_events(HyprEventFn fn, gpointer user_data) {
    if (!g_available) return;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    g_strlcpy(addr.sun_path, g_evt_sock_path, sizeof(addr.sun_path));
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        g_warning("[hypr_ipc] Konnte Event-Socket nicht verbinden: %s", g_evt_sock_path);
        close(fd);
        return;
    }

    GIOChannel *chan = g_io_channel_unix_new(fd);
    g_io_channel_set_close_on_unref(chan, TRUE);
    g_io_channel_set_encoding(chan, NULL, NULL); /* Rohdaten, kein UTF-8-Zwang */

    /* KRITISCH: ohne das hier blockiert on_evt_readable() irgendwann im
     * Hauptthread und reisst die komplette Event-Loop mit (Klicks,
     * Timer, alles - siehe ausfuehrlicher Kommentar dort). Non-blocking
     * heisst: g_io_channel_read_line() gibt sofort G_IO_STATUS_AGAIN
     * zurueck statt zu warten, sobald der Puffer leer ist. */
    GError *flags_err = NULL;
    if (g_io_channel_set_flags(chan, G_IO_FLAG_NONBLOCK, &flags_err) != G_IO_STATUS_NORMAL) {
        g_warning("[hypr_ipc] Konnte Event-Socket nicht auf non-blocking setzen: %s",
                  flags_err ? flags_err->message : "?");
        g_clear_error(&flags_err);
    }

    EventSub *sub = g_new0(EventSub, 1);
    sub->fn = fn;
    sub->user_data = user_data;

    g_io_add_watch(chan, G_IO_IN | G_IO_HUP | G_IO_ERR, on_evt_readable, sub);
    g_io_channel_unref(chan); /* watch haelt eigene Referenz */
}


/* ───────────────────────── tray : Typen/Deklarationen ───────────────────────── */
/* Minimaler StatusNotifierItem-Host (KDE/freedesktop-SNI-Protokoll, das
 * z.B. nm-applet, blueman-applet und xwaylandvideobridge nutzen).
 *
 * Funktionsumfang bewusst reduziert gegenueber Waybars Tray:
 *  - Icon per IconName (Icon-Theme) ODER IconPixmap (roh, ARGB32) aus
 *    org.freedesktop.StatusNotifierItem
 *  - Linksklick -> Activate(x,y), Rechtsklick -> ContextMenu(x,y)
 *    (kein eigenes Menu-Rendering - das macht der Tray-Client selbst
 *    per D-Bus-Popup, genau wie er es fuer jeden SNI-Host taete)
 *  - Tooltip aus der Tooltip-Property, sonst Title
 *
 * Falls kein StatusNotifierWatcher auf der Session-Bus laeuft (z.B. auf
 * einem schlanken Hyprland-Setup ohne KDE/GNOME-Komponenten), tritt
 * dieses Modul selbst als Watcher auf - exakt das Verhalten, das Waybar
 * in derselben Situation zeigt. */
typedef struct TbTray TbTray;

/* container: GtkBox, in die pro Icon eine Bubble eingehaengt wird. */
TbTray *tb_tray_new(GtkWidget *container, BubbleAssets *assets, BarConfig *cfg);
void    tb_tray_free(TbTray *tray);


/* ═══════════════════════════ tray : Implementierung ═══════════════════════════ */
#define SNW_BUS_NAME "org.kde.StatusNotifierWatcher"
/* Tray.txt: "org.kde.StatusNotifierWatcher" ist die kanonische, von echten
 * Clients (u.a. hyprland-minimizer) tatsaechlich abgefragte Adresse - der
 * freedesktop.org-Name ist historisch nur ein optionaler Alias, den manche
 * (nicht alle!) Clients zusaetzlich pruefen. Vorher stand hier NUR der
 * freedesktop-Name - dadurch war "org.kde.StatusNotifierWatcher" komplett
 * unbesetzt, RegisterStatusNotifierItem-Aufrufe dorthin liefen ins Leere.
 * Wir beanspruchen jetzt BEIDE (siehe tb_tray_new()), damit auch Clients
 * erreicht werden, die (unueblicherweise) nur den freedesktop-Namen pruefen. */
#define SNW_BUS_NAME_FALLBACK "org.freedesktop.StatusNotifierWatcher"
#define SNW_OBJ_PATH "/StatusNotifierWatcher"
#define SNW_IFACE    "org.kde.StatusNotifierWatcher"
#define SNI_IFACE    "org.kde.StatusNotifierItem"

typedef struct {
    TbTray  *owner;
    char    *service;       /* Bus-Name des Tray-Clients */
    char    *object_path;   /* meist "/StatusNotifierItem" */
    GDBusProxy *proxy;      /* org.kde.StatusNotifierItem am Client */
    TbSubIcon *sub_icon;    /* Slot in tray->shared_bubble - siehe tb_bubble_new_multi() */
    guint    signal_id;
} TbTrayItem;

struct TbTray {
    GtkWidget    *container;
    TbBubble     *shared_bubble; /* EINE gestreckte Blase fuer ALLE Tray-Icons
                                   * (statt einer Blase pro Icon) - siehe
                                   * tb_bubble_new_multi(). */
    BubbleAssets *assets;
    BarConfig    *cfg;

    GDBusConnection *conn;
    char *unique_name;

    gboolean we_are_watcher;
    guint    own_name_id;
    guint    own_name_id_fallback; /* org.freedesktop.StatusNotifierWatcher, siehe SNW_BUS_NAME_FALLBACK */
    guint    watcher_reg_id;   /* Object-Registrierung, falls wir Watcher sind */
    GDBusNodeInfo *watcher_introspection;

    GDBusProxy *watcher_proxy; /* falls jemand anders Watcher ist */
    guint watcher_signal_sub;
    guint name_owner_sub; /* NameOwnerChanged-Abo, siehe Tray.txt "Aufraeumen nicht vergessen" */

    GPtrArray *items; /* TbTrayItem* */
};

/* ── Introspection-XML fuer den Fallback-Watcher ────────────────────
 * Minimal, aber vollstaendig genug fuer alle gaengigen Tray-Clients
 * (nm-applet, blueman-applet, xwaylandvideobridge, ...). */
static const char *watcher_xml =
"<node>"
"  <interface name='org.kde.StatusNotifierWatcher'>"
"    <method name='RegisterStatusNotifierItem'>"
"      <arg type='s' name='service' direction='in'/>"
"    </method>"
"    <method name='RegisterStatusNotifierHost'>"
"      <arg type='s' name='service' direction='in'/>"
"    </method>"
"    <property name='RegisteredStatusNotifierItems' type='as' access='read'/>"
"    <property name='IsStatusNotifierHostRegistered' type='b' access='read'/>"
"    <property name='ProtocolVersion' type='i' access='read'/>"
"    <signal name='StatusNotifierItemRegistered'><arg type='s'/></signal>"
"    <signal name='StatusNotifierItemUnregistered'><arg type='s'/></signal>"
"    <signal name='StatusNotifierHostRegistered'/>"
"  </interface>"
"</node>";

static void tray_add_item(TbTray *tray, const char *service_arg, const char *sender);
static void tray_remove_item_by_service(TbTray *tray, const char *service);

/* ── Icon eines Tray-Items laden ─────────────────────────────────── */

static void free_pixbuf_data(guchar *pixels, gpointer data) {
    (void)data;
    g_free(pixels);
}

static GdkPixbuf *pixbuf_from_iconpixmap_variant(GVariant *v) {
    /* Typ: a(iiay) - Liste von (width, height, ARGB32-Bytes,
     * Netzwerk-Byteorder). Wir nehmen das groesste Icon. */
    if (!v) return NULL;
    GVariantIter iter;
    g_variant_iter_init(&iter, v);
    gint best_w = 0, best_h = 0;
    GVariant *best_bytes = NULL;

    gint w, h;
    GVariant *bytes;
    while (g_variant_iter_next(&iter, "(ii@ay)", &w, &h, &bytes)) {
        if (w * h > best_w * best_h) {
            if (best_bytes) g_variant_unref(best_bytes);
            best_bytes = bytes;
            best_w = w; best_h = h;
        } else {
            g_variant_unref(bytes);
        }
    }
    if (!best_bytes || best_w <= 0 || best_h <= 0) {
        if (best_bytes) g_variant_unref(best_bytes);
        return NULL;
    }

    gsize n = 0;
    const guint8 *data = g_variant_get_fixed_array(best_bytes, &n, sizeof(guint8));
    gsize expected = (gsize)best_w * (gsize)best_h * 4;
    if (n < expected) { g_variant_unref(best_bytes); return NULL; }

    /* ARGB (network order) -> RGBA fuer GdkPixbuf umkopieren. */
    guint8 *rgba = g_malloc(expected);
    for (gsize i = 0; i < (gsize)best_w * (gsize)best_h; i++) {
        guint8 a = data[i * 4 + 0];
        guint8 r = data[i * 4 + 1];
        guint8 g = data[i * 4 + 2];
        guint8 b = data[i * 4 + 3];
        rgba[i * 4 + 0] = r;
        rgba[i * 4 + 1] = g;
        rgba[i * 4 + 2] = b;
        rgba[i * 4 + 3] = a;
    }
    g_variant_unref(best_bytes);

    GdkPixbuf *pb = gdk_pixbuf_new_from_data(rgba, GDK_COLORSPACE_RGB, TRUE, 8,
                                              best_w, best_h, best_w * 4,
                                              free_pixbuf_data, NULL);
    return pb;
}

static GVariant *proxy_get_prop(GDBusProxy *proxy, const char *name) {
    return g_dbus_proxy_get_cached_property(proxy, name);
}

static void tray_item_refresh_icon(TbTrayItem *it) {
    if (!it->proxy) return;

    GdkPixbuf *pb = NULL;
    const char *source = "keins";

    GVariant *icon_name_v = proxy_get_prop(it->proxy, "IconName");
    const char *icon_name = icon_name_v ? g_variant_get_string(icon_name_v, NULL) : NULL;

    if (icon_name && *icon_name) {
        GError *err = NULL;
        pb = gtk_icon_theme_load_icon(gtk_icon_theme_get_default(), icon_name,
                                       it->owner->cfg->icon_size,
                                       GTK_ICON_LOOKUP_FORCE_SIZE, &err);
        if (err) {
            g_message("[tray] '%s': IconName='%s' im Theme nicht gefunden (%s), versuche IconPixmap.",
                      it->service, icon_name, err->message);
            g_error_free(err);
        } else {
            source = "IconName";
        }
    }
    if (!pb) {
        GVariant *pixmap_v = proxy_get_prop(it->proxy, "IconPixmap");
        pb = pixbuf_from_iconpixmap_variant(pixmap_v);
        if (pb) {
            source = "IconPixmap";
            /* auf konfigurierte Icon-Groesse bringen */
            int size = it->owner->cfg->icon_size;
            GdkPixbuf *scaled = gdk_pixbuf_scale_simple(pb, size, size, GDK_INTERP_BILINEAR);
            g_object_unref(pb);
            pb = scaled;
        }
        if (pixmap_v) g_variant_unref(pixmap_v);
    }
    if (icon_name_v) g_variant_unref(icon_name_v);

    g_message("[tray] '%s': Icon-Quelle=%s (%s)", it->service, source, pb ? "geladen" : "FEHLGESCHLAGEN - Fallback-Icon bleibt");

    if (pb) {
        tb_bubble_update_sub_icon(it->owner->shared_bubble, it->sub_icon, pb);
        g_object_unref(pb);
    }

    GVariant *tooltip_v = proxy_get_prop(it->proxy, "ToolTip");
    GVariant *title_v = proxy_get_prop(it->proxy, "Title");
    const char *tip = NULL;
    char *tip_owned = NULL;
    if (tooltip_v && g_variant_n_children(tooltip_v) >= 4) {
        /* (sa(iiay)ss): icon-name, icon-pixmap, title, text */
        const char *tip_title = NULL, *tip_text = NULL;
        g_variant_get_child(tooltip_v, 2, "&s", &tip_title);
        g_variant_get_child(tooltip_v, 3, "&s", &tip_text);
        if (tip_text && *tip_text) tip = tip_text;
        else if (tip_title && *tip_title) tip = tip_title;
    }
    if (!tip && title_v) tip_owned = g_variant_dup_string(title_v, NULL);
    tb_bubble_set_sub_icon_tooltip(it->owner->shared_bubble, it->sub_icon,
                                    tip ? tip : (tip_owned ? tip_owned : it->service));
    g_free(tip_owned);
    if (tooltip_v) g_variant_unref(tooltip_v);
    if (title_v) g_variant_unref(title_v);
}

/*  dbusmenu-Client (com.canonical.dbusmenu)
 * Steam, Discord & Co. (libappindicator/Ayatana) implementieren
 * ContextMenu() NICHT - der Host muss das Menue selbst aus dem
 * dbusmenu-Objekt (SNI-Property "Menu") aufbauen, genau wie Waybar. */
#define DBUSMENU_IFACE "com.canonical.dbusmenu"

typedef struct {
    GDBusConnection *conn; /* nicht besessen */
    char *service;
    char *path;
} TbDbusMenuCtx;

static void dbusmenu_ctx_free(gpointer p) {
    TbDbusMenuCtx *c = p;
    if (!c) return;
    g_free(c->service);
    g_free(c->path);
    g_free(c);
}

static void dbusmenu_send_event(TbDbusMenuCtx *ctx, gint32 id, const char *event) {
    g_dbus_connection_call(ctx->conn, ctx->service, ctx->path, DBUSMENU_IFACE, "Event",
                           g_variant_new("(isvu)", id, event, g_variant_new_int32(0),
                                         (guint32)(g_get_monotonic_time() / 1000)),
                           NULL, G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}

static void dbusmenu_item_activated(GtkMenuItem *item, gpointer user_data) {
    TbDbusMenuCtx *ctx = user_data;
    gint32 id = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(item), "tb-dbusmenu-id"));
    dbusmenu_send_event(ctx, id, "clicked");
}

/* children: GVariant vom Typ av (Liste von (ia{sv}av)) */
static GtkWidget *dbusmenu_build(TbDbusMenuCtx *ctx, GVariant *children) {
    GtkWidget *menu = gtk_menu_new();
    GVariantIter iter;
    GVariant *cv;
    g_variant_iter_init(&iter, children);
    while ((cv = g_variant_iter_next_value(&iter))) {
        GVariant *node = g_variant_get_variant(cv);
        gint32 id = 0;
        GVariant *props = NULL, *kids = NULL;
        g_variant_get(node, "(i@a{sv}@av)", &id, &props, &kids);

        gchar *type = NULL, *label = NULL, *toggle = NULL;
        gboolean enabled = TRUE, visible = TRUE;
        gint32 tstate = -1;
        g_variant_lookup(props, "type", "s", &type);
        g_variant_lookup(props, "label", "s", &label);
        g_variant_lookup(props, "enabled", "b", &enabled);
        g_variant_lookup(props, "visible", "b", &visible);
        g_variant_lookup(props, "toggle-type", "s", &toggle);
        g_variant_lookup(props, "toggle-state", "i", &tstate);

        if (visible) {
            GtkWidget *mi;
            if (g_strcmp0(type, "separator") == 0) {
                mi = gtk_separator_menu_item_new();
            } else {
                const char *lab = label ? label : "";
                if (g_strcmp0(toggle, "checkmark") == 0 || g_strcmp0(toggle, "radio") == 0) {
                    mi = gtk_check_menu_item_new_with_mnemonic(lab);
                    if (g_strcmp0(toggle, "radio") == 0)
                        gtk_check_menu_item_set_draw_as_radio(GTK_CHECK_MENU_ITEM(mi), TRUE);
                    gtk_check_menu_item_set_active(GTK_CHECK_MENU_ITEM(mi), tstate == 1);
                } else {
                    mi = gtk_menu_item_new_with_mnemonic(lab);
                }
                gtk_widget_set_sensitive(mi, enabled);
                if (kids && g_variant_n_children(kids) > 0) {
                    gtk_menu_item_set_submenu(GTK_MENU_ITEM(mi), dbusmenu_build(ctx, kids));
                } else {
                    g_object_set_data(G_OBJECT(mi), "tb-dbusmenu-id", GINT_TO_POINTER(id));
                    g_signal_connect(mi, "activate", G_CALLBACK(dbusmenu_item_activated), ctx);
                }
            }
            gtk_menu_shell_append(GTK_MENU_SHELL(menu), mi);
            gtk_widget_show(mi);
        }

        g_free(type); g_free(label); g_free(toggle);
        if (props) g_variant_unref(props);
        if (kids) g_variant_unref(kids);
        g_variant_unref(node);
        g_variant_unref(cv);
    }
    return menu;
}

typedef struct {
    TbDbusMenuCtx *ctx;   /* geht beim Anzeigen an das Menue ueber */
    GtkWidget *anchor;    /* referenziert */
    gboolean   top;
    double     x;
    GdkEvent  *ev;        /* Kopie des Klick-Events (fuer den Popup-Grab) */
} TbMenuReq;

static void menu_req_free(TbMenuReq *rq) {
    dbusmenu_ctx_free(rq->ctx);
    if (rq->anchor) g_object_unref(rq->anchor);
    if (rq->ev) gdk_event_free(rq->ev);
    g_free(rq);
}

static gboolean dbusmenu_destroy_idle(gpointer m) {
    gtk_widget_destroy(GTK_WIDGET(m));
    g_object_unref(m);
    return G_SOURCE_REMOVE;
}

static void dbusmenu_deactivated(GtkMenuShell *shell, gpointer user_data) {
    (void)user_data;
    tb_autohide_menu_hold(g_autohide_singleton, FALSE);
    g_idle_add(dbusmenu_destroy_idle, shell); /* unsere Referenz geht an den Idle */
}

static void dbusmenu_layout_cb(GObject *src, GAsyncResult *res, gpointer user_data) {
    TbMenuReq *rq = user_data;
    GError *err = NULL;
    GVariant *ret = g_dbus_connection_call_finish(G_DBUS_CONNECTION(src), res, &err);
    if (!ret) {
        g_warning("[tray] dbusmenu GetLayout fehlgeschlagen: %s", err ? err->message : "?");
        if (err) g_error_free(err);
        menu_req_free(rq);
        return;
    }
    guint32 rev = 0;
    GVariant *layout = NULL;
    g_variant_get(ret, "(u@(ia{sv}av))", &rev, &layout);
    gint32 rid = 0;
    GVariant *rprops = NULL, *rkids = NULL;
    g_variant_get(layout, "(i@a{sv}@av)", &rid, &rprops, &rkids);

    if (!rkids || g_variant_n_children(rkids) == 0) {
        g_message("[tray] dbusmenu: leeres Menue.");
    } else {
        GtkWidget *menu = dbusmenu_build(rq->ctx, rkids);
        g_object_set_data_full(G_OBJECT(menu), "tb-ctx", rq->ctx, dbusmenu_ctx_free);
        rq->ctx = NULL; /* gehoert jetzt dem Menue */
        g_object_ref_sink(menu);
        g_signal_connect(menu, "deactivate", G_CALLBACK(dbusmenu_deactivated), NULL);
        tb_autohide_menu_hold(g_autohide_singleton, TRUE);

        GtkAllocation alloc;
        gtk_widget_get_allocation(rq->anchor, &alloc);
        GdkRectangle rect = { (int)rq->x, 0, 1, MAX(1, alloc.height) };
        gtk_menu_popup_at_rect(GTK_MENU(menu), gtk_widget_get_window(rq->anchor), &rect,
                               rq->top ? GDK_GRAVITY_SOUTH_WEST : GDK_GRAVITY_NORTH_WEST,
                               rq->top ? GDK_GRAVITY_NORTH_WEST : GDK_GRAVITY_SOUTH_WEST,
                               rq->ev);
        if (!gtk_widget_get_visible(menu)) { /* Popup fehlgeschlagen -> nichts festhalten */
            tb_autohide_menu_hold(g_autohide_singleton, FALSE);
            g_idle_add(dbusmenu_destroy_idle, menu);
        }
    }
    if (rprops) g_variant_unref(rprops);
    if (rkids) g_variant_unref(rkids);
    g_variant_unref(layout);
    g_variant_unref(ret);
    menu_req_free(rq);
}

/* Liefert den dbusmenu-Objektpfad des Items (NULL wenn keins). */
static char *tray_item_menu_path(TbTrayItem *it) {
    if (!it->proxy) return NULL;
    GVariant *v = g_dbus_proxy_get_cached_property(it->proxy, "Menu");
    char *p = NULL;
    if (v) {
        const char *sp = g_variant_get_string(v, NULL);
        if (sp && *sp && g_strcmp0(sp, "/") != 0) p = g_strdup(sp);
        g_variant_unref(v);
    }
    return p;
}

static void tray_item_show_menu(TbTrayItem *it, const char *menu_path) {
    TbTray *tray = it->owner;
    GtkWidget *anchor = tb_bubble_widget(tray->shared_bubble);
    TbMenuReq *rq = g_new0(TbMenuReq, 1);
    rq->ctx = g_new0(TbDbusMenuCtx, 1);
    rq->ctx->conn = tray->conn;
    rq->ctx->service = g_strdup(it->service);
    rq->ctx->path = g_strdup(menu_path);
    rq->anchor = g_object_ref(anchor);
    rq->top = g_strcmp0(tray->cfg->position, "top") == 0;
    rq->ev = gtk_get_current_event(); /* Kopie, im Klick-Handler gueltig */
    double ex = 0;
    if (rq->ev) gdk_event_get_coords(rq->ev, &ex, NULL);
    rq->x = ex;

    /* AboutToShow + GetLayout gehen in Reihenfolge auf dieselbe Verbindung. */
    g_dbus_connection_call(tray->conn, it->service, menu_path, DBUSMENU_IFACE, "AboutToShow",
                           g_variant_new("(i)", 0), NULL, G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
    const char *no_props[] = { NULL };
    g_dbus_connection_call(tray->conn, it->service, menu_path, DBUSMENU_IFACE, "GetLayout",
                           g_variant_new("(ii^as)", 0, -1, no_props), G_VARIANT_TYPE("(u(ia{sv}av))"),
                           G_DBUS_CALL_FLAGS_NONE, 2000, NULL, dbusmenu_layout_cb, rq);
}

static void on_item_click_left(gpointer user_data) {
    TbTrayItem *it = user_data;
    g_message("[tray] Klick (links/Activate) auf '%s'.", it->service);
    if (!it->proxy) { g_warning("[tray] '%s': kein Proxy, Klick ignoriert.", it->service); return; }
    /* ItemIsMenu: der Client hat keine Activate()-Aktion, Linksklick = Menue. */
    GVariant *iim = g_dbus_proxy_get_cached_property(it->proxy, "ItemIsMenu");
    gboolean is_menu = iim && g_variant_is_of_type(iim, G_VARIANT_TYPE_BOOLEAN) && g_variant_get_boolean(iim);
    if (iim) g_variant_unref(iim);
    char *mp = is_menu ? tray_item_menu_path(it) : NULL;
    if (mp) {
        tray_item_show_menu(it, mp);
        g_free(mp);
        return;
    }
    g_dbus_proxy_call(it->proxy, "Activate", g_variant_new("(ii)", 0, 0),
                       G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}
static void on_item_click_right(gpointer user_data) {
    TbTrayItem *it = user_data;
    g_message("[tray] Klick (rechts/Menue) auf '%s'.", it->service);
    if (!it->proxy) { g_warning("[tray] '%s': kein Proxy, Klick ignoriert.", it->service); return; }
    char *mp = tray_item_menu_path(it);
    if (mp) { /* dbusmenu vorhanden -> selbst rendern (Steam u.a.) */
        tray_item_show_menu(it, mp);
        g_free(mp);
        return;
    }
    g_dbus_proxy_call(it->proxy, "ContextMenu", g_variant_new("(ii)", 0, 0),
                       G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}
static void on_item_click_middle(gpointer user_data) {
    TbTrayItem *it = user_data;
    g_message("[tray] Klick (mitte/SecondaryActivate) auf '%s'.", it->service);
    if (!it->proxy) { g_warning("[tray] '%s': kein Proxy, Klick ignoriert.", it->service); return; }
    g_dbus_proxy_call(it->proxy, "SecondaryActivate", g_variant_new("(ii)", 0, 0),
                       G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}

static void on_item_signal(GDBusProxy *proxy, const char *sender, const char *signal,
                            GVariant *params, gpointer user_data) {
    (void)proxy; (void)sender; (void)params;
    TbTrayItem *it = user_data;
    /* NewIcon / NewStatus / NewToolTip / NewTitle -> einfach neu laden. */
    if (g_str_has_prefix(signal, "New")) tray_item_refresh_icon(it);
}

static void on_item_proxy_ready(GObject *src, GAsyncResult *res, gpointer user_data) {
    (void)src;
    TbTrayItem *it = user_data;
    GError *err = NULL;
    it->proxy = g_dbus_proxy_new_for_bus_finish(res, &err);
    if (!it->proxy) {
        g_warning("[tray] Proxy fuer %s fehlgeschlagen: %s", it->service, err ? err->message : "?");
        if (err) g_error_free(err);
        return;
    }
    g_message("[tray] Proxy fuer '%s' (%s) bereit - lade Icon/Tooltip.", it->service, it->object_path);
    it->signal_id = g_signal_connect(it->proxy, "g-signal", G_CALLBACK(on_item_signal), it);
    tray_item_refresh_icon(it);
}

static void tray_add_item(TbTray *tray, const char *service_arg, const char *sender) {
    char *service = NULL;
    char *object_path = NULL;

    if (service_arg && service_arg[0] == '/') {
        /* Nur ein Objektpfad angegeben -> gehoert zum Sender selbst. */
        service = g_strdup(sender);
        object_path = g_strdup(service_arg);
    } else if (service_arg && strchr(service_arg, '/')) {
        const char *slash = strchr(service_arg, '/');
        service = g_strndup(service_arg, slash - service_arg);
        object_path = g_strdup(slash);
    } else {
        service = g_strdup(service_arg ? service_arg : sender);
        object_path = g_strdup("/StatusNotifierItem");
    }

    /* Duplikate vermeiden (manche Clients registrieren mehrfach). */
    for (guint i = 0; i < tray->items->len; i++) {
        TbTrayItem *ex = g_ptr_array_index(tray->items, i);
        if (g_strcmp0(ex->service, service) == 0 && g_strcmp0(ex->object_path, object_path) == 0) {
            g_free(service); g_free(object_path);
            return;
        }
    }

    TbTrayItem *it = g_new0(TbTrayItem, 1);
    it->owner = tray;
    it->service = service;
    it->object_path = object_path;
    g_message("[tray] neues Item: service='%s' object_path='%s'", service, object_path);

    /* Fallback-Icon, bis der Proxy-Callback das echte IconName/IconPixmap
     * nachlaedt (tray_item_refresh_icon()) - direkt als eigener Slot in
     * DERSELBEN gestreckten Tray-Blase statt einer eigenen Blase pro
     * Item. */
    GdkPixbuf *fallback = lookup_icon(tray->cfg, "application-x-executable");
    it->sub_icon = tb_bubble_add_sub_icon(tray->shared_bubble, fallback,
                                           on_item_click_left, on_item_click_right,
                                           on_item_click_middle, it);
    g_clear_object(&fallback); /* tb_bubble_add_sub_icon() nimmt seine eigene Referenz */

    g_ptr_array_add(tray->items, it);

    g_dbus_proxy_new_for_bus(G_BUS_TYPE_SESSION, G_DBUS_PROXY_FLAGS_NONE, NULL,
                              it->service, it->object_path, SNI_IFACE, NULL,
                              on_item_proxy_ready, it);
}

static void tray_item_free(TbTrayItem *it) {
    if (it->proxy) {
        if (it->signal_id) g_signal_handler_disconnect(it->proxy, it->signal_id);
        g_object_unref(it->proxy);
    }
    if (it->sub_icon)
        tb_bubble_remove_sub_icon(it->owner->shared_bubble, it->sub_icon);
    g_free(it->service);
    g_free(it->object_path);
    g_free(it);
}

static void tray_remove_item_by_service(TbTray *tray, const char *service_arg) {
    char *service = NULL;
    if (service_arg && service_arg[0] != '/' && strchr(service_arg, '/')) {
        const char *slash = strchr(service_arg, '/');
        service = g_strndup(service_arg, slash - service_arg);
    } else {
        service = g_strdup(service_arg);
    }
    for (guint i = 0; i < tray->items->len; i++) {
        TbTrayItem *it = g_ptr_array_index(tray->items, i);
        if (g_strcmp0(it->service, service) == 0) {
            tray_item_free(it);
            g_ptr_array_remove_index(tray->items, i);
            break;
        }
    }
    g_free(service);
}

/* ── Wir sind der Watcher (Fallback, falls keiner laeuft) ──────────── */

static GVariant *registered_items_variant(TbTray *tray) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("as"));
    for (guint i = 0; i < tray->items->len; i++) {
        TbTrayItem *it = g_ptr_array_index(tray->items, i);
        g_variant_builder_add(&b, "s", it->service);
    }
    return g_variant_builder_end(&b);
}

static void watcher_method_call(GDBusConnection *conn, const char *sender,
                                 const char *object_path, const char *interface_name,
                                 const char *method_name, GVariant *params,
                                 GDBusMethodInvocation *invocation, gpointer user_data) {
    (void)conn; (void)object_path; (void)interface_name;
    TbTray *tray = user_data;

    if (g_strcmp0(method_name, "RegisterStatusNotifierItem") == 0) {
        const char *service_arg = NULL;
        g_variant_get(params, "(&s)", &service_arg);
        g_message("[tray] RegisterStatusNotifierItem: sender='%s' arg='%s'", sender, service_arg);
        tray_add_item(tray, service_arg, sender);
        g_dbus_connection_emit_signal(tray->conn, NULL, SNW_OBJ_PATH, SNW_IFACE,
                                       "StatusNotifierItemRegistered",
                                       g_variant_new("(s)", service_arg), NULL);
        g_dbus_method_invocation_return_value(invocation, NULL);
    } else if (g_strcmp0(method_name, "RegisterStatusNotifierHost") == 0) {
        /* Wir zaehlen Hosts nicht einzeln mit - es reicht, dass wir
         * IsStatusNotifierHostRegistered ab jetzt TRUE liefern. */
        g_dbus_connection_emit_signal(tray->conn, NULL, SNW_OBJ_PATH, SNW_IFACE,
                                       "StatusNotifierHostRegistered", NULL, NULL);
        g_dbus_method_invocation_return_value(invocation, NULL);
    } else {
        g_dbus_method_invocation_return_error(invocation, G_DBUS_ERROR, G_DBUS_ERROR_UNKNOWN_METHOD,
                                               "Unbekannte Methode %s", method_name);
    }
}

static GVariant *watcher_get_property(GDBusConnection *conn, const char *sender,
                                       const char *object_path, const char *interface_name,
                                       const char *property_name, GError **error, gpointer user_data) {
    (void)conn; (void)sender; (void)object_path; (void)interface_name; (void)error;
    TbTray *tray = user_data;
    if (g_strcmp0(property_name, "RegisteredStatusNotifierItems") == 0)
        return registered_items_variant(tray);
    if (g_strcmp0(property_name, "IsStatusNotifierHostRegistered") == 0)
        return g_variant_new_boolean(TRUE);
    if (g_strcmp0(property_name, "ProtocolVersion") == 0)
        return g_variant_new_int32(0);
    return NULL;
}

static const GDBusInterfaceVTable watcher_vtable = {
    .method_call = watcher_method_call,
    .get_property = watcher_get_property,
    .set_property = NULL,
};

/* Tray.txt, "Aufraeumen nicht vergessen": wird aufgerufen, sobald
 * IRGENDEIN Bus-Name auf dem Session-Bus seinen Besitzer verliert.
 * Interessiert uns nur, wenn der verschwundene Name zu einem UNSERER
 * registrierten Items gehoert (Prozess beendet/gecrasht) - dann raus
 * aus der Liste + StatusNotifierItemUnregistered emittieren, damit sich
 * keine Leichen ansammeln. */
static void on_name_owner_changed(GDBusConnection *conn, const char *sender,
                                   const char *object_path, const char *interface_name,
                                   const char *signal_name, GVariant *params, gpointer user_data) {
    (void)conn; (void)sender; (void)object_path; (void)interface_name; (void)signal_name;
    TbTray *tray = user_data;
    const char *name = NULL, *old_owner = NULL, *new_owner = NULL;
    g_variant_get(params, "(&s&s&s)", &name, &old_owner, &new_owner);
    if (new_owner && *new_owner) return; /* Name hat einfach nur den Besitzer gewechselt */

    gboolean was_ours = FALSE;
    for (guint i = 0; i < tray->items->len; i++) {
        TbTrayItem *it = g_ptr_array_index(tray->items, i);
        if (g_strcmp0(it->service, name) == 0) { was_ours = TRUE; break; }
    }
    if (!was_ours) return;

    g_message("[tray] Item-Prozess '%s' ist vom Bus verschwunden (NameOwnerChanged) - raeume auf.", name);
    tray_remove_item_by_service(tray, name);
    g_dbus_connection_emit_signal(tray->conn, NULL, SNW_OBJ_PATH, SNW_IFACE,
                                   "StatusNotifierItemUnregistered",
                                   g_variant_new("(s)", name), NULL);
}

/* Reiner Zusatz-Namensbeanspruch fuer org.freedesktop.StatusNotifierWatcher
 * (siehe SNW_BUS_NAME_FALLBACK) - das eigentliche Objekt wird bereits ueber
 * den primaeren org.kde.*-Namen exportiert, hier gibt's nichts weiter zu
 * tun ausser zu loggen. */
static void on_fallback_name_acquired(GDBusConnection *conn, const char *name, gpointer user_data) {
    (void)conn; (void)user_data;
    g_message("[tray] Fallback-Name '%s' zusaetzlich uebernommen.", name);
}
static void on_fallback_name_lost(GDBusConnection *conn, const char *name, gpointer user_data) {
    (void)conn; (void)user_data;
    g_message("[tray] Fallback-Name '%s' nicht bekommen (evtl. von jemand anderem besetzt) - "
              "kein Problem, org.kde.StatusNotifierWatcher ist der wichtige.", name);
}

static void on_watcher_name_acquired(GDBusConnection *conn, const char *name, gpointer user_data) {
    (void)name;
    TbTray *tray = user_data;
    tray->conn = conn;
    tray->we_are_watcher = TRUE;

    GDBusInterfaceInfo *iface = tray->watcher_introspection->interfaces[0];
    GError *err = NULL;
    tray->watcher_reg_id = g_dbus_connection_register_object(
        conn, SNW_OBJ_PATH, iface, &watcher_vtable, tray, NULL, &err);
    if (err) {
        g_warning("[tray] Konnte Watcher-Objekt nicht exportieren: %s", err->message);
        g_error_free(err);
    } else {
        g_message("[tray] Kein StatusNotifierWatcher gefunden - TrafkTuxBar uebernimmt die Rolle.");
    }

    /* Tray.txt, "Aufraeumen nicht vergessen": auf NameOwnerChanged fuer
     * org.freedesktop.DBus lauschen - stirbt ein registriertes Item
     * (Prozess beendet sich, z.B. hyprland-minimizer nachdem er fertig
     * ist), verschwindet dessen Bus-Name komplett vom Bus (new_owner
     * wird leer). Ohne diesen Handler sammeln sich dafuer "Leichen" in
     * tray->items an - nur relevant, wenn WIR der Watcher sind (ist ein
     * externer Watcher aktiv, ist DAS dessen Job, nicht unserer - unsere
     * Host-Seite bekommt dessen StatusNotifierItemUnregistered-Signal
     * bereits ueber on_ext_watcher_signal()). */
    tray->name_owner_sub = g_dbus_connection_signal_subscribe(
        conn, "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
        "/org/freedesktop/DBus", NULL, G_DBUS_SIGNAL_FLAGS_NONE,
        on_name_owner_changed, tray, NULL);
}

static void on_watcher_name_lost(GDBusConnection *conn, const char *name, gpointer user_data) {
    (void)name;
    TbTray *tray = user_data;
    if (tray->we_are_watcher) return; /* wir hatten ihn nie - normal beim Start */
    tray->conn = conn ? conn : tray->conn;
}

/* ── Wir sind nur Host (ein externer Watcher laeuft schon) ─────────── */

static void on_ext_watcher_signal(GDBusProxy *proxy, const char *sender_name,
                                   const char *signal_name, GVariant *params, gpointer user_data) {
    (void)proxy; (void)sender_name;
    TbTray *tray = user_data;
    if (g_strcmp0(signal_name, "StatusNotifierItemRegistered") == 0) {
        const char *service_arg = NULL;
        g_variant_get(params, "(&s)", &service_arg);
        tray_add_item(tray, service_arg, service_arg);
    } else if (g_strcmp0(signal_name, "StatusNotifierItemUnregistered") == 0) {
        const char *service_arg = NULL;
        g_variant_get(params, "(&s)", &service_arg);
        tray_remove_item_by_service(tray, service_arg);
    }
}

static void connect_to_external_watcher(TbTray *tray) {
    GError *err = NULL;
    tray->watcher_proxy = g_dbus_proxy_new_for_bus_sync(
        G_BUS_TYPE_SESSION, G_DBUS_PROXY_FLAGS_NONE, NULL,
        SNW_BUS_NAME, SNW_OBJ_PATH, SNW_IFACE, NULL, &err);
    if (!tray->watcher_proxy) {
        g_warning("[tray] Kein Zugriff auf existierenden Watcher: %s", err ? err->message : "?");
        if (err) g_error_free(err);
        return;
    }

    g_signal_connect(tray->watcher_proxy, "g-signal", G_CALLBACK(on_ext_watcher_signal), tray);

    /* uns selbst als Host anmelden und bereits registrierte Items holen */
    g_dbus_proxy_call(tray->watcher_proxy, "RegisterStatusNotifierHost",
                       g_variant_new("(s)", tray->unique_name),
                       G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);

    GVariant *items_v = g_dbus_proxy_get_cached_property(tray->watcher_proxy,
                                                           "RegisteredStatusNotifierItems");
    if (items_v) {
        GVariantIter it;
        const char *s;
        g_variant_iter_init(&it, items_v);
        while (g_variant_iter_next(&it, "&s", &s)) tray_add_item(tray, s, s);
        g_variant_unref(items_v);
    }
}

/* ── Oeffentliche API ───────────────────────────────────────────────
 * Strategie: wir versuchen IMMER, org.freedesktop.StatusNotifierWatcher
 * fuer uns zu beanspruchen (mit allow_replacement=FALSE, damit ein
 * zufaellig etwas spaeter startender zweiter Host uns nicht killt).
 * Existiert der Name schon, bekommen wir ihn nicht (GBus meldet das
 * synchron nicht - wir pruefen daher zuerst per Sync-Call, ob schon
 * jemand antwortet, und werden nur bei Fehlschlag Watcher). */

static gboolean external_watcher_exists(void) {
    GDBusConnection *conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);
    if (!conn) return FALSE;
    GVariant *res = g_dbus_connection_call_sync(
        conn, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
        "NameHasOwner", g_variant_new("(s)", SNW_BUS_NAME), G_VARIANT_TYPE("(b)"),
        G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL);
    gboolean exists = FALSE;
    if (res) {
        g_variant_get(res, "(b)", &exists);
        g_variant_unref(res);
    }
    return exists;
}

TbTray *tb_tray_new(GtkWidget *container, BubbleAssets *assets, BarConfig *cfg) {
    TbTray *tray = g_new0(TbTray, 1);
    tray->container = container;
    tray->assets = assets;
    tray->cfg = cfg;
    tray->items = g_ptr_array_new();
    tray->watcher_introspection = g_dbus_node_info_new_for_xml(watcher_xml, NULL);

    /* EINE gestreckte Blase fuer den ganzen Tray statt einer pro Icon -
     * startet leer/versteckt, waechst automatisch mit jedem
     * tb_bubble_add_sub_icon()-Aufruf aus tray_add_item(). */
    tray->shared_bubble = tb_bubble_new_multi(assets, cfg);
    gtk_box_pack_start(GTK_BOX(container), tb_bubble_widget(tray->shared_bubble), FALSE, FALSE, 0);

    tray->conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);
    if (!tray->conn) {
        g_warning("[tray] Keine Session-D-Bus-Verbindung - Tray bleibt leer.");
        return tray;
    }
    tray->unique_name = g_strdup(g_dbus_connection_get_unique_name(tray->conn));
    g_message("[tray] D-Bus verbunden als '%s'.", tray->unique_name);

    gboolean ext_exists = external_watcher_exists();
    g_message("[tray] externer StatusNotifierWatcher gefunden: %s", ext_exists ? "ja" : "nein");
    if (ext_exists) {
        connect_to_external_watcher(tray);
    } else {
        tray->own_name_id = g_bus_own_name(G_BUS_TYPE_SESSION, SNW_BUS_NAME,
                                            G_BUS_NAME_OWNER_FLAGS_NONE,
                                            NULL, on_watcher_name_acquired, on_watcher_name_lost,
                                            tray, NULL);
        /* Zusaetzlich den freedesktop-Alias beanspruchen (siehe Kommentar
         * bei SNW_BUS_NAME_FALLBACK) - das Objekt selbst ist schon exportiert
         * (passiert in on_watcher_name_acquired() fuer den primaeren Namen),
         * D-Bus-Objektexporte gelten pro VERBINDUNG, nicht pro Bus-Name -
         * hier muss also nichts nochmal registriert werden, nur der
         * zusaetzliche Name beansprucht werden. */
        tray->own_name_id_fallback = g_bus_own_name(G_BUS_TYPE_SESSION, SNW_BUS_NAME_FALLBACK,
                                                      G_BUS_NAME_OWNER_FLAGS_NONE,
                                                      NULL, on_fallback_name_acquired, on_fallback_name_lost,
                                                      NULL, NULL);
    }

    return tray;
}

void tb_tray_free(TbTray *tray) {
    if (!tray) return;
    for (guint i = 0; i < tray->items->len; i++)
        tray_item_free(g_ptr_array_index(tray->items, i));
    g_ptr_array_free(tray->items, TRUE);

    if (tray->shared_bubble) {
        /* wie beim alten Pro-Item-Bubble-Cleanup: erst Widget-Zeiger
         * sichern, dann tb_bubble_free() (gibt den TbBubble selbst frei),
         * dann erst das GTK-Widget zerstoeren. */
        GtkWidget *w = tb_bubble_widget(tray->shared_bubble);
        tb_bubble_free(tray->shared_bubble);
        gtk_widget_destroy(w);
    }

    if (tray->watcher_reg_id && tray->conn)
        g_dbus_connection_unregister_object(tray->conn, tray->watcher_reg_id);
    if (tray->name_owner_sub && tray->conn)
        g_dbus_connection_signal_unsubscribe(tray->conn, tray->name_owner_sub);
    if (tray->own_name_id) g_bus_unown_name(tray->own_name_id);
    if (tray->own_name_id_fallback) g_bus_unown_name(tray->own_name_id_fallback);
    if (tray->watcher_proxy) g_object_unref(tray->watcher_proxy);
    if (tray->watcher_introspection) g_dbus_node_info_unref(tray->watcher_introspection);
    g_free(tray->unique_name);
    g_free(tray);
}


/* ───────────────────────── modules : Typen/Deklarationen ───────────────────────── */
/* Baut aus einem GPtrArray<ModuleConfig*> Bubbles und haengt sie in
 * `box` ein. Verwaltet intern alles Notwendige (Timer fuer exec_cmd/
 * Uhr, Hyprland-Event-Abo fuer das Workspace-Modul, ...) - Aufrufer
 * muss sich um nichts weiter kuemmern. */
typedef struct TbModules TbModules;

TbModules *tb_modules_build(GtkWidget *box, GPtrArray *module_configs,
                             BubbleAssets *assets, BarConfig *cfg);
void       tb_modules_free(TbModules *m);


/* ═══════════════════════════ scrollbar : schmaler, gelber Blaetterbalken ═══════════════════════════ */
/* Rein Cairo-gezeichnet (kein GTK-Scrollbar-Theming). Arbeitet IMMER
 * ueber ein GtkAdjustment:
 *  - echte Reihen-Scrollbars (gepinnte Apps, Taskbar-Icons) haengen am
 *    hadjustment des GtkScrolledWindow der jeweiligen Reihe (Pixel-Basis)
 *  - "Stepper" (Workspace-Wechsel, Widget-Seiten) bekommen ein eigenes,
 *    klein angelegtes Index-Adjustment (0..N-1, page_size meist 1)
 * Zeichnen/Klick/Wheel ist fuer beide Faelle identisch - nur was beim
 * Wert-Wechsel passiert (Scroll-Offset vs. echte Aktion) unterscheidet
 * sich, und das entscheidet allein, WER das Adjustment "value-changed"
 * abonniert (der Anlegende), nicht der Balken selbst. */
typedef struct {
    GtkWidget *area;
    GtkOrientation orient;
    GtkAdjustment *adj;   /* nicht besessen */
    gboolean hover;
    int hover_btn;         /* -1 = keins, 0 = erster Pfeil, 1 = zweiter Pfeil */
} TbScrollBar;

static void sb_redraw_cb(GtkAdjustment *adj, gpointer ud) {
    (void)adj;
    gtk_widget_queue_draw(GTK_WIDGET(ud));
}

/* KEIN Hintergrund-Rechteck mehr - nur noch die reinen Pfeil-Glyphen in
 * der dunklen "Thumb"-Farbe (genau das, was am Anfang gewuenscht war:
 * "sollten die Farbe des Scrollbalken-Mitteldings haben"), direkt auf dem
 * Bar-Hintergrund sitzend. Kein Rechteck heisst auch: nichts, womit die
 * Pfeile ueberlappen/verschmelzen koennten. */
static gboolean sb_on_draw(GtkWidget *w, cairo_t *cr, gpointer user_data) {
    TbScrollBar *sb = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(w, &alloc);
    double W = alloc.width, H = alloc.height;
    if (W < 3 || H < 3) return FALSE;
    gboolean horiz = (sb->orient == GTK_ORIENTATION_HORIZONTAL);

    GdkRGBA col;
    gdk_rgba_parse(&col, "#fff495");
    GdkRGBA dark = col;
    dark.red *= 0.55; dark.green *= 0.55; dark.blue *= 0.40;

    double gap = 2.0;
    double main_total = horiz ? W : H;
    double cross = horiz ? H : W;
    double half = (main_total - gap) / 2.0;

    for (int btn = 0; btn < 2; btn++) {
        double bx, by, bw, bh;
        if (horiz) { bx = btn == 0 ? 0 : half + gap; by = 0; bw = half; bh = cross; }
        else       { bx = 0; by = btn == 0 ? 0 : half + gap; bw = cross; bh = half; }

        double cx = bx + bw / 2.0, cy = by + bh / 2.0;
        double s = MIN(bw, bh) * 0.40;
        double a = sb->hover_btn == btn ? 1.0 : 0.9;
        cairo_set_source_rgba(cr, dark.red, dark.green, dark.blue, a);
        if (horiz) {
            if (btn == 0) { /* Pfeil nach links */
                cairo_move_to(cr, cx + s * 0.6, cy - s);
                cairo_line_to(cr, cx - s * 0.7, cy);
                cairo_line_to(cr, cx + s * 0.6, cy + s);
            } else { /* Pfeil nach rechts */
                cairo_move_to(cr, cx - s * 0.6, cy - s);
                cairo_line_to(cr, cx + s * 0.7, cy);
                cairo_line_to(cr, cx - s * 0.6, cy + s);
            }
        } else {
            if (btn == 0) { /* Pfeil nach oben */
                cairo_move_to(cr, cx - s, cy + s * 0.6);
                cairo_line_to(cr, cx, cy - s * 0.7);
                cairo_line_to(cr, cx + s, cy + s * 0.6);
            } else { /* Pfeil nach unten */
                cairo_move_to(cr, cx - s, cy - s * 0.6);
                cairo_line_to(cr, cx, cy + s * 0.7);
                cairo_line_to(cr, cx + s, cy - s * 0.6);
            }
        }
        cairo_close_path(cr);
        cairo_fill(cr);
    }
    return FALSE;
}

static void sb_step(TbScrollBar *sb, double dir) {
    if (!sb->adj) return;
    double step = gtk_adjustment_get_step_increment(sb->adj);
    if (step <= 0) step = 1.0;
    double lo = gtk_adjustment_get_lower(sb->adj);
    double hi = gtk_adjustment_get_upper(sb->adj) - gtk_adjustment_get_page_size(sb->adj);
    gtk_adjustment_set_value(sb->adj, CLAMP(gtk_adjustment_get_value(sb->adj) + dir * step, lo, MAX(lo, hi)));
}

/* Nur noch 2 Haelften, keine Lauffläche/Thumb-Logik mehr - Klick in die
 * erste Haelfte = ein Schritt zurueck, zweite Haelfte = ein Schritt vor. */
static gboolean sb_on_press(GtkWidget *w, GdkEventButton *ev, gpointer user_data) {
    TbScrollBar *sb = user_data;
    if (ev->button != 1 || !sb->adj) return FALSE;
    GtkAllocation alloc;
    gtk_widget_get_allocation(w, &alloc);
    gboolean horiz = sb->orient == GTK_ORIENTATION_HORIZONTAL;
    double pos = horiz ? ev->x : ev->y;
    double main_len = horiz ? alloc.width : alloc.height;
    sb_step(sb, pos < main_len / 2.0 ? -1 : 1);
    return TRUE;
}

static gboolean sb_on_scroll(GtkWidget *w, GdkEventScroll *ev, gpointer user_data) {
    (void)w;
    TbScrollBar *sb = user_data;
    double dir = 0;
    if (ev->direction == GDK_SCROLL_UP || ev->direction == GDK_SCROLL_LEFT) dir = -1;
    else if (ev->direction == GDK_SCROLL_DOWN || ev->direction == GDK_SCROLL_RIGHT) dir = 1;
    else if (ev->direction == GDK_SCROLL_SMOOTH) dir = (ev->delta_y + ev->delta_x) > 0 ? 1 : -1;
    if (dir != 0) sb_step(sb, dir);
    return TRUE;
}

static gboolean sb_on_motion(GtkWidget *w, GdkEventMotion *ev, gpointer ud) {
    TbScrollBar *sb = ud;
    GtkAllocation alloc;
    gtk_widget_get_allocation(w, &alloc);
    gboolean horiz = sb->orient == GTK_ORIENTATION_HORIZONTAL;
    double pos = horiz ? ev->x : ev->y;
    double main_len = horiz ? alloc.width : alloc.height;
    int btn = pos < main_len / 2.0 ? 0 : 1;
    if (btn != sb->hover_btn) { sb->hover_btn = btn; gtk_widget_queue_draw(w); }
    return FALSE;
}
static gboolean sb_on_enter(GtkWidget *w, GdkEventCrossing *ev, gpointer ud) {
    (void)ev; TbScrollBar *sb = ud; sb->hover = TRUE; gtk_widget_queue_draw(w); return FALSE;
}
static gboolean sb_on_leave(GtkWidget *w, GdkEventCrossing *ev, gpointer ud) {
    (void)ev; TbScrollBar *sb = ud; sb->hover = FALSE; sb->hover_btn = -1; gtk_widget_queue_draw(w); return FALSE;
}

/* adj darf NULL sein und spaeter per tb_scrollbar_set_adjustment() gesetzt
 * werden (z.B. wenn das GtkScrolledWindow sein hadjustment erst nach dem
 * Anlegen des Balkens preisgibt). */
/* thick ist die Dicke QUER zur Scrollrichtung (Touch-Ziel-Groesse); die
 * LAENGE in Scrollrichtung ist jetzt fix 2*thick+2px (zwei quadratische
 * Pfeil-Buttons + kleiner Zwischenraum) statt vorher ueber vexpand/FILL
 * auf die volle Zeilenhoehe gestreckt - kein Track mehr, der gestreckt
 * werden muesste. */
static TbScrollBar *tb_scrollbar_new(GtkOrientation orient, GtkAdjustment *adj, int thick) {
    TbScrollBar *sb = g_new0(TbScrollBar, 1);
    sb->orient = orient;
    sb->hover_btn = -1;
    sb->area = g_object_ref_sink(gtk_drawing_area_new());
    int main_total = thick * 2 + 2;
    if (orient == GTK_ORIENTATION_HORIZONTAL) gtk_widget_set_size_request(sb->area, main_total, thick);
    else gtk_widget_set_size_request(sb->area, thick, main_total);
    gtk_widget_set_app_paintable(sb->area, TRUE);
    gtk_widget_add_events(sb->area, GDK_BUTTON_PRESS_MASK | GDK_SCROLL_MASK |
                          GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK | GDK_POINTER_MOTION_MASK);
    g_signal_connect(sb->area, "draw", G_CALLBACK(sb_on_draw), sb);
    g_signal_connect(sb->area, "button-press-event", G_CALLBACK(sb_on_press), sb);
    g_signal_connect(sb->area, "scroll-event", G_CALLBACK(sb_on_scroll), sb);
    g_signal_connect(sb->area, "motion-notify-event", G_CALLBACK(sb_on_motion), sb);
    g_signal_connect(sb->area, "enter-notify-event", G_CALLBACK(sb_on_enter), sb);
    g_signal_connect(sb->area, "leave-notify-event", G_CALLBACK(sb_on_leave), sb);
    if (adj) {
        sb->adj = adj;
        g_signal_connect(adj, "value-changed", G_CALLBACK(sb_redraw_cb), sb->area);
        g_signal_connect(adj, "changed", G_CALLBACK(sb_redraw_cb), sb->area);
    }
    return sb;
}

static GtkWidget *tb_scrollbar_widget(TbScrollBar *sb) { return sb->area; }

/* Leitet Mausrad-Events von einem BELIEBIGEN anderen Widget (z.B. dem
 * Blasenbereich, den der Balken steuert) an dieselbe sb_on_scroll()-Logik
 * weiter wie ein Wheel-Event direkt auf dem Balken. So funktioniert
 * Scrollen auch, wenn man mit der Maus/dem Finger genau ueber den
 * Icons/Blasen steht statt exakt ueber dem schmalen Balken. */
static void tb_scrollbar_forward_wheel_from(TbScrollBar *sb, GtkWidget *source_widget) {
    gtk_widget_add_events(source_widget, GDK_SCROLL_MASK);
    g_signal_connect(source_widget, "scroll-event", G_CALLBACK(sb_on_scroll), sb);
}

static void tb_scrollbar_free(TbScrollBar *sb) {
    if (!sb) return;
    g_clear_object(&sb->area);
    g_free(sb);
}

/* Blendet den Balken aus, wenn sein Adjustment gar nichts zu scrollen hat
 * (upper-lower <= page_size) - sonst haengt ein toter Pfeil-Balken herum,
 * wo eh alles passt. */
static void sb_autohide_cb(GtkAdjustment *adj, gpointer user_data) {
    GtkWidget *bar_widget = user_data;
    gboolean need = (gtk_adjustment_get_upper(adj) - gtk_adjustment_get_lower(adj)) >
                    gtk_adjustment_get_page_size(adj) + 0.5;
    gtk_widget_set_visible(bar_widget, need);
}
static void tb_scrollbar_enable_autohide(TbScrollBar *sb) {
    if (!sb->adj) return;
    g_signal_connect(sb->adj, "changed", G_CALLBACK(sb_autohide_cb), sb->area);
    sb_autohide_cb(sb->adj, sb->area);
}

/* ═══════════════════════════ modules : Implementierung ═══════════════════════════ */
typedef struct {
    ModuleConfig *mc;
    TbBubble *bubble;
    guint exec_timeout_id;
    guint clock_timeout_id;
    gboolean exec_busy;      /* async Exec laeuft gerade */
    gboolean clock_alt_shown;
    BarConfig *cfg;
} ButtonRuntime;

typedef struct {
    ModuleConfig *mc;
    GtkWidget *container;   /* einfache HBox: [Workspace-Blase][vBalken][Fenster-Reihe] */
    BubbleAssets *assets;
    BarConfig *cfg;
    GPtrArray *bubbles;     /* TbBubble* der Fenster-Icons, wird bei jedem Rebuild neu befuellt */
    guint pending_rebuild_id; /* Debounce - siehe on_hypr_event() */

    /* Redesign: nur noch EINE Blase zeigt die aktive Workspace-Nummer,
     * ein senkrechter Balken daneben wechselt zwischen Workspaces (statt
     * vorher einer Pille pro Workspace nebeneinander). Die Fenster-Icons
     * zeigen nur noch die des AKTIVEN Workspace, in einer eigenen
     * Scroll-Reihe OHNE eigenen Balken (keine horizontalen Balken mehr
     * im Design - Mausrad ueber den Icons scrollt trotzdem, das kann
     * GtkScrolledWindow von Haus aus). */
    TbBubble *ws_bubble;
    GtkAdjustment *ws_adj;   /* Index-Adjustment 0..workspaces-1 */
    TbScrollBar *vbar;
    GArray *ws_ids;          /* int, sortierte Workspace-IDs - Index<->ID-Mapping fuer ws_adj */
    gboolean syncing;        /* TRUE waehrend rebuild() ws_adj nur nach einem echten Hyprland-
                               * Event NACHZIEHT - verhindert, dass das dabei ausgeloeste
                               * "value-changed" faelschlich nochmal einen Workspace-Wechsel dispatcht */

    /* Fenster-Reihe: wie bei MOD_WIDGET_GRID brechen zu viele offene
     * Fenster jetzt in eine neue Zeile/Seite um (statt gecropt/versteckt
     * zu werden) - ein eigener senkrechter Balken blaettert dazwischen.
     * apps_per_row wird EINMAL beim Bauen aus der Monitor-Breite
     * berechnet (siehe compute_dynamic_apps_per_row()), damit es auf
     * jeder Aufloesung/jedem Skalierungsfaktor sinnvoll viele Fenster
     * pro Zeile zeigt statt eines fest verdrahteten Pixelwerts. */
    int apps_per_row;
    GtkWidget *apps_rows_box;      /* vbox, ein Kind (hbox) pro Zeile/Seite */
    GPtrArray *apps_page_boxes;    /* GtkWidget* je Zeile, wird bei jedem Rebuild neu aufgebaut */
    GtkAdjustment *apps_page_adj;
    TbScrollBar *apps_vbar;

    /* Preview-Modus: Scroll/Pfeil auf dem Workspace-Balken wechselt NICHT
     * den aktiven Workspace (das passiert nur bei Klick auf die Zahlen-Blase),
     * sondern zeigt nur die Apps des gewaehlten Workspace als Vorschau.
     * viewing_override=TRUE solange der Nutzer manuell gescrollt hat;
     * viewed_ws_id ist die angezeigte Workspace-ID.
     * Reset passiert, wenn die Bar sich wieder versteckt (do_hide). */
    gboolean viewing_override;
    int      viewed_ws_id;
} WorkspacesRuntime;

typedef struct {
    ModuleConfig *mc;
    GtkWidget *container;
    TbTray *tray;
} TrayRuntime;

typedef struct {
    GtkWidget *widget; /* leerer Platzhalter-Widget fester Breite */
} SpacerRuntime;

/* MOD_BUTTON_ROW (gepinnte Apps) und MOD_WIDGET_GRID (die anderen
 * Widgets) sind jetzt IDENTISCH umgesetzt: Items brechen bei max_width in
 * eine neue Zeile um statt horizontal zu scrollen (keine horizontalen
 * Balken mehr im Design), es ist immer nur eine Zeile ("Seite") sichtbar,
 * ein senkrechter Balken blaettert zwischen den Zeilen. Beide Modul-Typen
 * benutzen denselben Runtime-Typ und Builder (build_widget_grid) - der
 * Modul-Typ in der jsonc ist nur noch eine kosmetische Unterscheidung. */
typedef struct {
    ModuleConfig *mc;
    GtkWidget *container;      /* hbox: [rows_box][vBalken] */
    GtkWidget *rows_box;       /* vbox, ein Kind (hbox) pro Zeile/Seite */
    GPtrArray *page_boxes;     /* GtkWidget* je Zeile */
    GPtrArray *item_runtimes;  /* ModuleRuntime* (RT_BUTTON), alle Items ueber alle Zeilen */
    GtkAdjustment *page_adj;
    TbScrollBar *vbar;
} WidgetGridRuntime;

typedef enum { RT_BUTTON, RT_WORKSPACES, RT_TRAY, RT_SPACER, RT_WIDGET_GRID } RuntimeKind;

typedef struct {
    RuntimeKind kind;
    union {
        ButtonRuntime button;
        WorkspacesRuntime workspaces;
        TrayRuntime tray;
        SpacerRuntime spacer;
        WidgetGridRuntime widget_grid;
    } u;
} ModuleRuntime;

struct TbModules {
    GPtrArray *runtimes; /* ModuleRuntime* */
};

static void widget_grid_page_changed_cb(GtkAdjustment *adj, gpointer user_data); /* s.u. */
static void apps_page_changed_cb(GtkAdjustment *adj, gpointer user_data); /* s.o. bei workspaces */
static void workspaces_rebuild(WorkspacesRuntime *wr); /* Forward-Decl: benoetigt von do_hide() */

/* Muss NACH gtk_widget_show_all(window) aufgerufen werden (siehe main()):
 * show_all() macht JEDES Kind-Widget sichtbar, auch die Seiten 1..n
 * eines Widget-Grids ODER der Workspace-Fenster-Zeilen, die wir beim
 * Aufbau bewusst versteckt hatten. Ohne diesen Re-Sync stehen alle
 * Seiten gleichzeitig da und blaehen die Bar-Hoehe massiv auf (war der
 * Grund fuer die viel zu grosse Bar). */
static void tb_modules_resync_pages(TbModules *m) {
    if (!m) return;
    for (guint i = 0; i < m->runtimes->len; i++) {
        ModuleRuntime *rt = g_ptr_array_index(m->runtimes, i);
        if (rt->kind == RT_WIDGET_GRID) {
            WidgetGridRuntime *wg = &rt->u.widget_grid;
            widget_grid_page_changed_cb(wg->page_adj, wg);
            /* gtk_widget_show_all() macht ALLE Widgets sichtbar, auch den
             * Navigations-Balken der nur 1 Zeile hat. Hier nachholen. */
            sb_autohide_cb(wg->page_adj, tb_scrollbar_widget(wg->vbar));
        } else if (rt->kind == RT_WORKSPACES) {
            WorkspacesRuntime *wr = &rt->u.workspaces;
            apps_page_changed_cb(wr->apps_page_adj, wr);
            sb_autohide_cb(wr->ws_adj,       tb_scrollbar_widget(wr->vbar));
            sb_autohide_cb(wr->apps_page_adj, tb_scrollbar_widget(wr->apps_vbar));
        }
    }
}


/* ── Shell-Kommandos ausfuehren (wie waybar on-click) ──────────────── */

static void run_shell(const char *cmd) {
    if (!cmd || !*cmd) return;
    GError *err = NULL;
    char *argv[] = { "/bin/sh", "-c", (char *)cmd, NULL };
    if (!g_spawn_async(NULL, argv, NULL, G_SPAWN_SEARCH_PATH | G_SPAWN_STDOUT_TO_DEV_NULL |
                        G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL, NULL, &err)) {
        g_warning("[modules] on-click fehlgeschlagen: %s", err ? err->message : "?");
        if (err) g_error_free(err);
    }
}

/* ── MOD_BUTTON ─────────────────────────────────────────────────── */

static gboolean btn_exec_poll(gpointer user_data);

static gboolean btn_recheck_cb(gpointer ud) {
    btn_exec_poll(ud);
    return G_SOURCE_REMOVE;
}

/* Nach einem Klick den Zustand des Moduls schnell neu abfragen (statt bis zu
 * exec_interval_sec zu warten) - z.B. damit die Bar sofort ueber die gerade
 * gestartete Bildschirmtastatur springt. */
static void btn_schedule_recheck(ButtonRuntime *r) {
    if (r->mc->exec_cmd && r->mc->exec_interval_sec > 0) {
        g_timeout_add(350, btn_recheck_cb, r);
        g_timeout_add(1200, btn_recheck_cb, r);
    }
}

static void btn_click_left(gpointer ud) { ButtonRuntime *r = ud; run_shell(r->mc->on_click); btn_schedule_recheck(r); }
static void btn_click_right(gpointer ud) { ButtonRuntime *r = ud; run_shell(r->mc->on_click_right); }
static void btn_click_middle(gpointer ud) { ButtonRuntime *r = ud; run_shell(r->mc->on_click_middle); }

static void btn_exec_apply(ButtonRuntime *r, const char *out) {
    if (r->mc->exec_return_json && *out) {
        JsonParser *parser = json_parser_new();
        if (json_parser_load_from_data(parser, out, -1, NULL)) {
            JsonObject *o = json_node_get_object(json_parser_get_root(parser));
            if (o) {
                if (json_object_has_member(o, "class")) {
                    const char *cls = json_object_get_string_member(o, "class");
                    gboolean is_active = g_strcmp0(cls, "active") == 0;
                    tb_bubble_set_forced_active(r->bubble, is_active);
                    /* Sonderfall Bildschirmtastatur - siehe
                     * tb_autohide_set_force_visible(). */
                    if (g_strcmp0(r->mc->id, "osk") == 0)
                        tb_autohide_set_force_visible(g_autohide_singleton, is_active);
                }
                if (json_object_has_member(o, "tooltip"))
                    tb_bubble_set_tooltip(r->bubble, json_object_get_string_member(o, "tooltip"));
                else if (r->mc->tooltip)
                    tb_bubble_set_tooltip(r->bubble, r->mc->tooltip);
                if (json_object_has_member(o, "text"))
                    tb_bubble_set_text(r->bubble, json_object_get_string_member(o, "text"));
            }
        }
        g_object_unref(parser);
    } else if (*out) {
        tb_bubble_set_tooltip(r->bubble, out);
    }
}

static void btn_exec_done(GObject *src, GAsyncResult *res, gpointer user_data) {
    ButtonRuntime *r = user_data;
    GSubprocess *proc = G_SUBPROCESS(src);
    char *out = NULL;
    GError *err = NULL;
    r->exec_busy = FALSE;
    if (g_subprocess_communicate_utf8_finish(proc, res, &out, NULL, &err) && out) {
        g_strchomp(out);
        btn_exec_apply(r, out);
    }
    if (err) g_error_free(err);
    g_free(out);
    g_object_unref(proc);
}

/* ASYNCHRON (GSubprocess): der Main-Loop wartet nie auf ein Shell-Skript.
 * Vorher blockierte g_spawn_sync() z.B. bei HideAll.sh status jede Sekunde
 * die komplette Bar (Animationen, Klicks, Zeichnen). */
static gboolean btn_exec_poll(gpointer user_data) {
    ButtonRuntime *r = user_data;
    if (r->exec_busy) return G_SOURCE_CONTINUE;
    GError *err = NULL;
    GSubprocess *proc = g_subprocess_new(G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_SILENCE,
                                         &err, "/bin/sh", "-c", r->mc->exec_cmd, NULL);
    if (!proc) {
        g_warning("[modules] exec fehlgeschlagen: %s", err ? err->message : "?");
        if (err) g_error_free(err);
        return G_SOURCE_CONTINUE;
    }
    r->exec_busy = TRUE;
    g_subprocess_communicate_utf8_async(proc, NULL, NULL, btn_exec_done, r);
    return G_SOURCE_CONTINUE;
}

static void clock_click_right(gpointer ud) {
    ButtonRuntime *r = ud;
    r->clock_alt_shown = !r->clock_alt_shown;
}

static gboolean clock_tick(gpointer user_data) {
    ButtonRuntime *r = user_data;
    time_t now = time(NULL);
    struct tm tmv;
    localtime_r(&now, &tmv);
    char buf[128];
    const char *fmt = r->clock_alt_shown ? r->mc->clock_format_alt : r->mc->clock_format;
    strftime(buf, sizeof(buf), fmt ? fmt : "%H:%M", &tmv);
    tb_bubble_set_text(r->bubble, buf);
    return G_SOURCE_CONTINUE;
}

static ModuleRuntime *build_button(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg) {
    ModuleRuntime *rt = g_new0(ModuleRuntime, 1);
    rt->kind = RT_BUTTON;
    ButtonRuntime *r = &rt->u.button;
    r->mc = mc;
    r->cfg = cfg;

    r->bubble = tb_bubble_new(assets, cfg, mc->icon_name, mc->text);
    if (mc->tooltip) tb_bubble_set_tooltip(r->bubble, mc->tooltip);
    tb_bubble_set_click_handlers(r->bubble, btn_click_left, btn_click_right, btn_click_middle, r);
    gtk_box_pack_start(GTK_BOX(box), tb_bubble_widget(r->bubble), FALSE, FALSE, 0);

    if (mc->exec_cmd && mc->exec_interval_sec > 0) {
        btn_exec_poll(r); /* sofort einmal ausfuehren, nicht erst nach dem 1. Intervall */
        r->exec_timeout_id = g_timeout_add_seconds((guint)mc->exec_interval_sec, btn_exec_poll, r);
    }
    return rt;
}

static ModuleRuntime *build_clock(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg) {
    ModuleRuntime *rt = g_new0(ModuleRuntime, 1);
    rt->kind = RT_BUTTON;
    ButtonRuntime *r = &rt->u.button;
    r->mc = mc;
    r->cfg = cfg;

    r->bubble = tb_bubble_new(assets, cfg, NULL, "--:--");
    /* Etwas kleiner und weisser als der Rest - NUR fuer die Uhr, andere
     * Text-Blasen (z.B. die Workspace-Nummer) bleiben unveraendert.
     * "Weisser" = Richtung Weiss gemischt, nicht 100% Weiss (Wunsch war
     * explizit "nicht komplett aber weisser"). */
    {
        GdkRGBA clock_col;
        const double white_mix = 0.55;
        clock_col.red   = cfg->text_color.red   + (1.0 - cfg->text_color.red)   * white_mix;
        clock_col.green = cfg->text_color.green + (1.0 - cfg->text_color.green) * white_mix;
        clock_col.blue  = cfg->text_color.blue  + (1.0 - cfg->text_color.blue)  * white_mix;
        clock_col.alpha = cfg->text_color.alpha;
        /* Wieder groesser (war 10px) + extra Padding links/rechts. */
        tb_bubble_set_text_style(r->bubble, 14.0, TRUE, clock_col);
        tb_bubble_set_extra_padding(r->bubble, 9);
    }
    tb_bubble_set_click_handlers(r->bubble, btn_click_left, clock_click_right, btn_click_middle, r);
    gtk_box_pack_start(GTK_BOX(box), tb_bubble_widget(r->bubble), FALSE, FALSE, 0);

    clock_tick(r);
    r->clock_timeout_id = g_timeout_add_seconds(1, clock_tick, r);
    return rt;
}

/* ── MOD_HYPR_WORKSPACES ────────────────────────────────────────── */

static void ws_click(gpointer ud) {
    int id = GPOINTER_TO_INT(ud);
    /* WICHTIG: NICHT der Standard-Hyprland-Dispatcher "workspace" -
     * dieses System laeuft auf dem hl.dsp.*-Wrapper (siehe hyprland.lua),
     * der eigene Dispatcher-Namen mit Lua-Tabellen-Syntax als Argument
     * erwartet. "workspace %d" wuerde hier vermutlich schlicht nichts
     * tun (falscher/unbekannter Dispatcher-Name fuer diesen Hyprland-
     * Fork). */
    char cmd[64];
    g_snprintf(cmd, sizeof(cmd), "hl.dsp.focus({workspace=%d})", id);
    hypr_ipc_dispatch(cmd);
}

/* Linksklick auf die Zahlen-Blase: in den gerade ANGEZEIGTEN (preview)
 * Workspace wechseln und Preview-Override zuruecksetzen. */
static void ws_bubble_click(gpointer ud) {
    WorkspacesRuntime *wr = ud;
    int id;
    if (wr->viewing_override && wr->viewed_ws_id > 0) {
        id = wr->viewed_ws_id;
    } else {
        int idx = (int)lround(gtk_adjustment_get_value(wr->ws_adj));
        if (!wr->ws_ids || idx < 0 || (guint)idx >= wr->ws_ids->len) return;
        id = g_array_index(wr->ws_ids, int, idx);
    }
    wr->viewing_override = FALSE;
    ws_click(GINT_TO_POINTER(id));
}

/* Reagiert auf Scroll/Pfeil-Klicks auf dem senkrechten Workspace-Balken.
 * KEIN Workspace-Wechsel mehr - das passiert nur beim Klick auf die
 * Zahlen-Blase (ws_bubble). Stattdessen: Preview-Modus aktivieren und
 * die App-Reihe fuer den gewaehlten Workspace zeigen. */
static void ws_adj_changed_cb(GtkAdjustment *adj, gpointer user_data) {
    WorkspacesRuntime *wr = user_data;
    if (wr->syncing) return;
    int idx = (int)lround(gtk_adjustment_get_value(adj));
    if (!wr->ws_ids || idx < 0 || (guint)idx >= wr->ws_ids->len) return;
    int id = g_array_index(wr->ws_ids, int, idx);
    wr->viewing_override = TRUE;
    wr->viewed_ws_id = id;
    workspaces_rebuild(wr); /* zeigt Apps des angepeilten Workspace, kein Dispatcher */
}

/* Blaettert zwischen den Zeilen/Seiten der offenen Fenster - exakt
 * dasselbe Prinzip wie widget_grid_page_changed_cb(), nur auf
 * WorkspacesRuntime statt WidgetGridRuntime, weil die Fenster-Liste
 * dynamisch (aus Hyprland) statt aus statischen Config-Items kommt. */
static void apps_page_changed_cb(GtkAdjustment *adj, gpointer user_data) {
    WorkspacesRuntime *wr = user_data;
    int idx = (int)lround(gtk_adjustment_get_value(adj));
    for (guint i = 0; i < wr->apps_page_boxes->len; i++)
        gtk_widget_set_visible(g_ptr_array_index(wr->apps_page_boxes, i), (int)i == idx);
}

/* Linksklick auf ein Taskbar-Fenster-Icon: fokussieren (wechselt bei
 * Bedarf automatisch den Workspace). 1:1 dieselbe Dispatcher-Syntax wie
 * im alten, nachweislich funktionierenden WaybarClicks.sh. */
static void win_click_left(gpointer ud) {
    char *addr = ud; /* "0x..." - static Anzeigezeit, siehe rebuild() */
    char cmd[160];
    g_snprintf(cmd, sizeof(cmd), "hl.dsp.focus({window='address:%s'})", addr);
    hypr_ipc_dispatch(cmd);
}

/* Mittelklick / 3-Finger-Tipp: Fenster schliessen. */
static void win_click_middle(gpointer ud) {
    char *addr = ud;
    char cmd[160];
    g_snprintf(cmd, sizeof(cmd), "hl.dsp.window.close({window='address:%s'})", addr);
    hypr_ipc_dispatch(cmd);
}

/* Rechtsklick: minimieren. hyprland-minimizer wirkt auf das gerade
 * FOKUSSIERTE Fenster, deshalb - genau wie im alten Skript - erst
 * fokussieren, dann den Minimizer feuern. Klappt nur zuverlaessig, wenn
 * ein StatusNotifierWatcher laeuft (siehe Tray.txt) - das uebernimmt
 * TrafkTuxBar inzwischen selbst (siehe "[tray] ... uebernimmt die Rolle"
 * im Log), auch ohne dass die eigentliche Tray-Anzeige schon fertig ist. */
static void win_click_right(gpointer ud) {
    char *addr = ud;
    char cmd[160];
    g_snprintf(cmd, sizeof(cmd), "hl.dsp.focus({window='address:%s'})", addr);
    hypr_ipc_dispatch(cmd);
    hypr_ipc_dispatch("hl.dsp.exec_cmd(\"hyprland-minimizer\")");
}

/* Manuelle Alias-Tabelle fuer Faelle, in denen WM_CLASS und der
 * Icon-Name im Theme bekanntermassen auseinanderlaufen (z.B. Klasse
 * "xfce4-terminal", aber die meisten Icon-Packs - inkl. "Clay" -
 * kennen dafuer nur "utilities-terminal"). Wird NACH dem exakten
 * Treffer, aber VOR dem generischen .desktop-Lookup probiert, weil
 * sie fuer unsere bekannten Standard-Apps schneller und zuverlaessiger
 * ist als die automatische Suche. Bei Bedarf einfach erweitern. */
static const struct { const char *class_name; const char *icon; } ICON_ALIASES[] = {
    { "xfce4-terminal", "utilities-terminal" },
    { "Thunar",         "system-file-manager" },
    { "code",           "visual-studio-code" },
    { "code-oss",       "visual-studio-code" },
    { "discord",        "discord" },
    { "vesktop",        "discord" },
    { NULL, NULL }
};

/* Sucht ueber ALLE installierten .desktop-Dateien nach einer, deren
 * StartupWMClass zur uebergebenen Fenster-Klasse passt (case-
 * insensitiv - Hyprland liefert oft "Thunar", waehrend .desktop-
 * Dateien meist "thunar" o.ae. setzen), und liefert deren Icon-Namen.
 * Das ist der "korrekte" Weg, den auch echte Taskbars/Docks gehen -
 * WM_CLASS und Icon-Theme-Name sind bei vielen Apps schlicht NICHT
 * identisch, ein reiner Klein/Gross-Vergleich (bisheriges Verhalten)
 * findet daher systematisch nicht alle Icons.
 *
 * g_app_info_get_all() ist relativ teuer (liest alle .desktop-Dateien
 * im System) - wird deshalb genau EINMAL pro Programmlaufzeit gecacht,
 * nicht pro Aufruf. */
static char *icon_via_desktop_file(const char *class_name) {
    static GList *apps = NULL;
    static gboolean loaded = FALSE;
    if (!loaded) {
        apps = g_app_info_get_all();
        loaded = TRUE;
    }
    for (GList *l = apps; l; l = l->next) {
        if (!G_IS_DESKTOP_APP_INFO(l->data)) continue;
        GDesktopAppInfo *info = G_DESKTOP_APP_INFO(l->data);
        const char *wmclass = g_desktop_app_info_get_startup_wm_class(info);
        if (!wmclass || g_ascii_strcasecmp(wmclass, class_name) != 0) continue;

        GIcon *icon = g_app_info_get_icon(G_APP_INFO(info));
        if (!icon) continue;
        if (G_IS_THEMED_ICON(icon)) {
            const char * const *names = g_themed_icon_get_names(G_THEMED_ICON(icon));
            if (names && names[0]) return g_strdup(names[0]);
        } else {
            char *s = g_icon_to_string(icon);
            if (s) return s;
        }
    }
    return NULL;
}

/* class_name -> zuletzt gefundener Icon-Name. Verhindert, dass z.B.
 * 5 offene Terminal-Fenster bei JEDEM Rebuild erneut die komplette
 * .desktop-Suche + Log-Zeile ausloesen - genau das war vorher der
 * Grund, warum dieselbe [icons]-Meldung mehrfach im Log auftauchte. */
static GHashTable *g_icon_cache = NULL; /* owned char* -> owned char* */

static char *guess_icon_for_class(const char *class_name) {
    if (!class_name || !*class_name) {
        g_message("[icons] leere window class -> Fallback-Icon");
        return g_strdup("application-x-executable");
    }

    if (!g_icon_cache)
        g_icon_cache = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);

    const char *cached = g_hash_table_lookup(g_icon_cache, class_name);
    if (cached) return g_strdup(cached);

    GtkIconTheme *theme = gtk_icon_theme_get_default();
    char *found = NULL;
    const char *source = NULL;

    /* 1) Klasse 1:1 wie geliefert - manche Icon-Packs benennen ihre
     *    Icons exakt wie die WM_CLASS (Gross-/Kleinschreibung inkl.). */
    if (gtk_icon_theme_has_icon(theme, class_name)) {
        found = g_strdup(class_name);
        source = "exakt";
    }

    /* 2) Alias-Tabelle fuer bekannte Sonderfaelle. */
    if (!found) {
        for (int i = 0; ICON_ALIASES[i].class_name; i++) {
            if (g_ascii_strcasecmp(ICON_ALIASES[i].class_name, class_name) == 0 &&
                gtk_icon_theme_has_icon(theme, ICON_ALIASES[i].icon)) {
                found = g_strdup(ICON_ALIASES[i].icon);
                source = "Alias-Tabelle";
                break;
            }
        }
    }

    /* 3) kleingeschrieben (das bisherige, alleinige Verhalten). */
    if (!found) {
        char *lower = g_ascii_strdown(class_name, -1);
        if (gtk_icon_theme_has_icon(theme, lower)) {
            found = lower;
            source = "kleingeschrieben";
        } else {
            g_free(lower);
        }
    }

    /* 4) .desktop-Datei ueber StartupWMClass - deckt den Rest ab. */
    if (!found) {
        char *via_desktop = icon_via_desktop_file(class_name);
        if (via_desktop) {
            if (gtk_icon_theme_has_icon(theme, via_desktop)) {
                found = via_desktop;
                source = ".desktop StartupWMClass";
            } else {
                g_free(via_desktop);
            }
        }
    }

    if (found) {
        g_message("[icons] class='%s' -> Icon '%s' gefunden (%s)", class_name, found, source);
    } else {
        found = g_strdup("application-x-executable");
        g_message("[icons] class='%s' -> KEIN passendes Icon gefunden ueber exakt/Alias/"
                  "kleingeschrieben/.desktop -> Fallback", class_name);
    }

    g_hash_table_insert(g_icon_cache, g_strdup(class_name), g_strdup(found));
    return found;
}

static void workspaces_rebuild(WorkspacesRuntime *wr) {
    /* alte Fenster-Icon-Bubbles UND die alten Zeilen-Boxen der Apps-Reihe
     * entfernen - erst tb_bubble_free(), DANACH das Widget zerstoeren
     * (Reihenfolge s. Kommentar an gleicher Stelle in aelteren Versionen
     * dieser Datei). Die Zeilen-Boxen selbst werden bei JEDEM Rebuild neu
     * aufgebaut, weil sich die Fensteranzahl (und damit die Seitenzahl)
     * jederzeit aendern kann. */
    for (guint i = 0; i < wr->bubbles->len; i++) {
        TbBubble *b = g_ptr_array_index(wr->bubbles, i);
        GtkWidget *w = tb_bubble_widget(b);
        tb_bubble_free(b);
        gtk_widget_destroy(w);
    }
    g_ptr_array_set_size(wr->bubbles, 0);
    for (guint i = 0; i < wr->apps_page_boxes->len; i++)
        gtk_widget_destroy(g_ptr_array_index(wr->apps_page_boxes, i));
    g_ptr_array_set_size(wr->apps_page_boxes, 0);

    if (!hypr_ipc_available()) {
        g_warning("[workspaces] hypr_ipc_available()==FALSE - Workspace-Modul bleibt leer.");
        tb_bubble_set_text(wr->ws_bubble, "-");
        return;
    }

    GPtrArray *ws = hypr_ipc_get_workspaces();
    GPtrArray *clients = hypr_ipc_get_clients();
    int active_id = hypr_ipc_get_active_workspace_id();
    g_message("[workspaces] rebuild: %u workspaces, %u clients, active_id=%d",
              ws->len, clients->len, active_id);

    g_array_set_size(wr->ws_ids, 0);
    int active_idx = 0;
    for (guint i = 0; i < ws->len; i++) {
        HyprWorkspace *w = g_ptr_array_index(ws, i);
        g_array_append_val(wr->ws_ids, w->id);
        if (w->id == active_id) active_idx = (int)i;
    }

    /* Preview-Modus: viewing_override=TRUE bedeutet, der Nutzer hat per
     * Scroll/Pfeil einen anderen Workspace gewaehlt, ohne dorthin zu wechseln.
     * Pruefe ob der gemerkte Workspace noch existiert - falls nicht,
     * Override aufheben und zum aktiven zurueckfallen. */
    int viewed_idx = active_idx;
    if (wr->viewing_override && wr->viewed_ws_id > 0) {
        gboolean still_exists = FALSE;
        for (guint i = 0; i < wr->ws_ids->len; i++) {
            if (g_array_index(wr->ws_ids, int, i) == wr->viewed_ws_id) {
                viewed_idx = (int)i;
                still_exists = TRUE;
                break;
            }
        }
        if (!still_exists) {
            wr->viewing_override = FALSE;
            wr->viewed_ws_id = 0;
        }
    }
    int display_id = wr->viewing_override ? wr->viewed_ws_id : active_id;

    /* Zahlen-Blase: zeigt den gerade angezeigten WS (Preview oder aktiv). */
    char num[16];
    g_snprintf(num, sizeof(num), "%d", display_id);
    tb_bubble_set_text(wr->ws_bubble, num);

    /* syncing=TRUE: die folgenden gtk_adjustment_set_*()-Aufrufe loesen
     * "value-changed" aus - der Handler soll das aber NICHT als
     * Benutzerwunsch missverstehen. Im Preview-Modus behalten wir den
     * vom Nutzer gewaehlten Index (viewed_idx); sonst folgen wir dem
     * aktiven Workspace (active_idx). */
    wr->syncing = TRUE;
    gtk_adjustment_set_lower(wr->ws_adj, 0);
    gtk_adjustment_set_upper(wr->ws_adj, MAX(1, (double)ws->len));
    gtk_adjustment_set_page_size(wr->ws_adj, 1);
    gtk_adjustment_set_step_increment(wr->ws_adj, 1);
    gtk_adjustment_set_value(wr->ws_adj, viewed_idx);
    wr->syncing = FALSE;

    /* Fenster des angezeigten (preview oder aktiven) Workspace einsammeln. */
    GtkWidget *cur_row = NULL;
    guint shown = 0;
    for (guint c = 0; c < clients->len; c++) {
        HyprClient *cl = g_ptr_array_index(clients, c);
        if (cl->minimized || cl->workspace_id != display_id) continue;

        if (shown % (guint)wr->apps_per_row == 0) {
            cur_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
            gtk_box_pack_start(GTK_BOX(wr->apps_rows_box), cur_row, FALSE, FALSE, 0);
            g_ptr_array_add(wr->apps_page_boxes, cur_row);
        }
        shown++;

        char *icon = guess_icon_for_class(cl->class_name);
        TbBubble *wb = tb_bubble_new(wr->assets, wr->cfg, icon, NULL);
        g_free(icon);
        tb_bubble_set_tooltip(wb, cl->title);
        char *addr_copy = g_strdup(cl->address);
        g_object_set_data_full(G_OBJECT(tb_bubble_widget(wb)), "tb-win-addr", addr_copy, g_free);
        tb_bubble_set_click_handlers(wb, win_click_left, win_click_right, win_click_middle, addr_copy);
        gtk_box_pack_start(GTK_BOX(cur_row), tb_bubble_widget(wb), FALSE, FALSE, 0);
        gtk_widget_show_all(tb_bubble_widget(wb));
        g_ptr_array_add(wr->bubbles, wb);
    }
    if (wr->apps_page_boxes->len == 0) { /* keine Fenster offen - trotzdem eine leere Seite, sonst NULL-Zugriffe unten */
        cur_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
        gtk_box_pack_start(GTK_BOX(wr->apps_rows_box), cur_row, FALSE, FALSE, 0);
        g_ptr_array_add(wr->apps_page_boxes, cur_row);
    }

    /* Seiten-Adjustment nachziehen - aktuelle Seite beibehalten, wenn sie
     * nach dem Rebuild noch existiert, sonst auf die letzte gueltige. */
    double old_page = gtk_adjustment_get_value(wr->apps_page_adj);
    double new_upper = MAX(1, (double)wr->apps_page_boxes->len);
    gtk_adjustment_set_upper(wr->apps_page_adj, new_upper);
    gtk_adjustment_set_value(wr->apps_page_adj, CLAMP(old_page, 0, new_upper - 1));
    apps_page_changed_cb(wr->apps_page_adj, wr);

    hypr_ipc_free_workspaces(ws);
    hypr_ipc_free_clients(clients);
}

/* Ein einzelner globaler Event-Handler reicht: Hyprland-Events kommen
 * fuer alle Monitore/Workspaces auf demselben Socket rein, jede
 * WorkspacesRuntime-Instanz wird bei relevanten Events neu gebaut. */
static GPtrArray *g_ws_runtimes = NULL; /* WorkspacesRuntime* */

static gboolean debounced_rebuild_cb(gpointer user_data) {
    WorkspacesRuntime *wr = user_data;
    wr->pending_rebuild_id = 0;
    workspaces_rebuild(wr);
    return G_SOURCE_REMOVE;
}

static void on_hypr_event(const char *line, gpointer user_data) {
    (void)user_data;
    /* "activewindow>>" ABSICHTLICH NICHT hier drin: das Event feuert
     * bei JEDEM Fokuswechsel, auch innerhalb derselben Workspace (z.B.
     * einfaches Klicken zwischen zwei offenen Fenstern) - im normalen
     * Gebrauch mehrmals pro Sekunde. Jeder Treffer loeste bisher einen
     * KOMPLETTEN, synchron blockierenden Rebuild aus (3 Hyprland-IPC-
     * Round-Trips + kompletter Widget-Neubau), was bei haeufigem
     * Fensterwechsel die ganze Bar (Klicks, Autohide, alles) spuerbar
     * einfrieren liess. Fuer unsere Zwecke (welche Workspaces/Fenster
     * es gibt, welche Workspace aktiv ist) reichen die strukturellen
     * Events unten voellig aus. */
    static const char *relevant[] = {
        "workspace>>", "createworkspace>>", "destroyworkspace>>",
        "focusedmon>>", "openwindow>>", "closewindow>>", "movewindow>>",
        NULL
    };
    gboolean hit = FALSE;
    for (int i = 0; relevant[i]; i++) {
        if (g_str_has_prefix(line, relevant[i])) { hit = TRUE; break; }
    }
    if (!hit || !g_ws_runtimes) return;

    /* Debounce: mehrere Events in schneller Folge (z.B. beim Schliessen
     * mehrerer Fenster auf einmal) sollen nur EINEN Rebuild ausloesen,
     * nicht einen pro Event. */
    for (guint i = 0; i < g_ws_runtimes->len; i++) {
        WorkspacesRuntime *wr = g_ptr_array_index(g_ws_runtimes, i);
        if (wr->pending_rebuild_id) g_source_remove(wr->pending_rebuild_id);
        wr->pending_rebuild_id = g_timeout_add(80, debounced_rebuild_cb, wr);
    }
}

static ModuleRuntime *build_workspaces(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg) {
    ModuleRuntime *rt = g_new0(ModuleRuntime, 1);
    rt->kind = RT_WORKSPACES;
    WorkspacesRuntime *wr = &rt->u.workspaces;
    wr->mc = mc;
    wr->assets = assets;
    wr->cfg = cfg;
    wr->bubbles = g_ptr_array_new();
    wr->ws_ids = g_array_new(FALSE, FALSE, sizeof(int));
    wr->apps_page_boxes = g_ptr_array_new();

    /* Blase mit der aktuellen Workspace-Nummer - bleibt dauerhaft
     * bestehen (nicht wie frueher pro Rebuild neu erzeugt), nur Text
     * und Adjustment werden nachgezogen. Optisch immer im "aktiv"-Look,
     * es ist ja per Definition immer DER aktuelle Workspace. */
    wr->ws_bubble = tb_bubble_new(assets, cfg, NULL, "-");
    tb_bubble_set_forced_active(wr->ws_bubble, TRUE);
    /* Linksklick auf die Zahlen-Blase: in den angezeigten Workspace wechseln
     * (Preview oder aktiv) und Preview-Override zuruecksetzen. */
    tb_bubble_set_click_handlers(wr->ws_bubble, ws_bubble_click, NULL, NULL, wr);

    wr->ws_adj = gtk_adjustment_new(0, 0, 1, 1, 1, 1);
    g_signal_connect(wr->ws_adj, "value-changed", G_CALLBACK(ws_adj_changed_cb), wr);
    /* Feste Groesse, angelehnt an die Blasen-Groesse statt an der
     * Ziffernbreite (das war vorher fast unsichtbar duenn) UND ohne die
     * spaetere Uebertreibung nach oben - orientiert sich jetzt an der
     * halben Blasen-Hoehe, damit die 2 Pfeil-Buttons zusammen etwa eine
     * Blase hoch sind, nicht mehr. */
    int nav_thick = MAX(16, cfg->bubble.min_size - 6);
    wr->vbar = tb_scrollbar_new(GTK_ORIENTATION_VERTICAL, wr->ws_adj, nav_thick);
    tb_scrollbar_enable_autohide(wr->vbar); /* bei nur 1 Workspace: Balken weg */
    /* Mausrad soll auch ueber der Workspace-Zahlen-Blase selbst wechseln,
     * nicht nur exakt ueber dem schmalen Balken. */
    tb_scrollbar_forward_wheel_from(wr->vbar, tb_bubble_widget(wr->ws_bubble));

    /* Dynamisch statt fester Pixelwert: wie viele offene Fenster passen
     * pro Zeile, bevor der Rest umbricht? Berechnet aus der LOGISCHEN
     * (schon durch den Skalierungsfaktor geteilten) Breite des Ziel-
     * Monitors - genau das hat vorher bei 1080p+2x gefehlt (ein fest
     * verdrahteter max_width-Pixelwert kennt weder Aufloesung noch
     * Skalierung des Geraets, auf dem TrafkTuxBar gerade laeuft). */
    int item_w = cfg->bubble.min_size + 2 * cfg->bubble.padding + 2 * cfg->bubble.margin;
    int mon_count = 0;
    HyprMonitor *mons = hypr_ipc_get_monitors(&mon_count);
    HyprMonitor *target = find_target_hypr_monitor(cfg, mons, mon_count);
    /* Bar folgt dem Cursor (cfg->monitor leer) -> sie kann auf jedem Monitor
     * landen, also nach dem SCHMALSTEN Monitor rechnen, damit die Fenster-
     * Reihe ueberall passt. Fester Monitor -> nach dem. */
    double ref_w = target ? target->w : 0.0;
    if (!(cfg->monitor && *cfg->monitor)) {
        for (int i = 0; i < mon_count; i++)
            if (ref_w <= 0.0 || mons[i].w < ref_w) ref_w = mons[i].w;
    }
    double avail_w = ref_w > 0.0 ? ref_w * cfg->center_width_fraction : 400.0;
    wr->apps_per_row = MAX(1, (int)(avail_w / MAX(1, item_w)));
    g_message("[workspaces] dynamische Breite: Monitor '%s' %.0fx%.0f -> "
              "%.0fpx verfuegbar (Faktor %.2f) -> %d Fenster/Zeile",
              (cfg->monitor && *cfg->monitor && target) ? target->name : "(kleinster)", ref_w, target ? target->h : 0.0,
              avail_w, cfg->center_width_fraction, wr->apps_per_row);
    g_free(mons);

    int bubble_h = cfg->bubble.min_size + 2 * cfg->bubble.padding + 2 * cfg->bubble.margin;
    wr->apps_rows_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_size_request(wr->apps_rows_box, -1, bubble_h); /* nur 1 Zeile hoch, wie bei MOD_WIDGET_GRID */

    wr->apps_page_adj = gtk_adjustment_new(0, 0, 1, 1, 1, 1);
    g_signal_connect(wr->apps_page_adj, "value-changed", G_CALLBACK(apps_page_changed_cb), wr);
    wr->apps_vbar = tb_scrollbar_new(GTK_ORIENTATION_VERTICAL, wr->apps_page_adj, nav_thick);
    tb_scrollbar_enable_autohide(wr->apps_vbar); /* nur 1 Zeile Fenster: Balken weg */

    /* wr->apps_rows_box ist eine reine GtkBox OHNE eigenes GdkWindow -
     * Mausrad ueber der leeren Flaeche zwischen/neben den Fenster-Icons
     * kam da nie zuverlaessig an (derselbe Bug wie bei MOD_WIDGET_GRID,
     * siehe dort). GtkEventBox erzwingt ein echtes Fenster dafuer. */
    GtkWidget *wheel_catcher = gtk_event_box_new();
    gtk_container_add(GTK_CONTAINER(wheel_catcher), wr->apps_rows_box);
    tb_scrollbar_forward_wheel_from(wr->apps_vbar, wheel_catcher);

    /* Einfache Box statt Grid: [Zahlen-Blase][vBalken][Fenster-Zeilen][vBalken]
     * in einer einzigen Zeile - robuster als eine Grid-Konstruktion (die
     * u.a. mitverantwortlich fuer die viel zu grosse Bar-Hoehe war, siehe
     * Kommentar bei gtk_widget_show_all(window) in main()). */
    wr->container = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 3);
    gtk_box_pack_start(GTK_BOX(wr->container), tb_bubble_widget(wr->ws_bubble), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(wr->container), tb_scrollbar_widget(wr->vbar), FALSE, FALSE, 0);
    gtk_widget_set_valign(tb_scrollbar_widget(wr->vbar), GTK_ALIGN_CENTER); /* feste kompakte Groesse, nicht strecken */
    gtk_box_pack_start(GTK_BOX(wr->container), wheel_catcher, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(wr->container), tb_scrollbar_widget(wr->apps_vbar), FALSE, FALSE, 0);
    gtk_widget_set_valign(tb_scrollbar_widget(wr->apps_vbar), GTK_ALIGN_CENTER);

    gtk_box_pack_start(GTK_BOX(box), wr->container, FALSE, FALSE, 0);
    gtk_widget_show_all(wr->container);

    if (!g_ws_runtimes) g_ws_runtimes = g_ptr_array_new();
    g_ptr_array_add(g_ws_runtimes, wr);

    workspaces_rebuild(wr);
    sb_autohide_cb(wr->ws_adj, tb_scrollbar_widget(wr->vbar)); /* Anfangszustand nachziehen, s. Kommentar bei tb_scrollbar_enable_autohide() */
    sb_autohide_cb(wr->apps_page_adj, tb_scrollbar_widget(wr->apps_vbar));

    static gboolean subscribed = FALSE;
    if (!subscribed && hypr_ipc_available()) {
        hypr_ipc_subscribe_events(on_hypr_event, NULL);
        subscribed = TRUE;
    }
    return rt;
}
/* ── MOD_TRAY ───────────────────────────────────────────────────── */

static ModuleRuntime *build_tray(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg) {
    ModuleRuntime *rt = g_new0(ModuleRuntime, 1);
    rt->kind = RT_TRAY;
    TrayRuntime *tr = &rt->u.tray;
    tr->mc = mc;
    tr->container = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_box_pack_start(GTK_BOX(box), tr->container, FALSE, FALSE, 0);
    gtk_widget_show(tr->container);
    tr->tray = tb_tray_new(tr->container, assets, cfg);
    return rt;
}

/* ── MOD_BUTTON_ROW / MOD_WIDGET_GRID (gemeinsam) ──────────────────── */
/* Beide Modul-Typen sind jetzt derselbe Mechanismus: Items brechen bei
 * max_width in eine neue Zeile um, nur eine Zeile ("Seite") ist
 * sichtbar, ein senkrechter Balken blaettert zwischen den Zeilen. Kein
 * horizontales Scrollen/keine horizontalen Balken mehr. */

static ModuleRuntime *build_button(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg); /* s.o. */

static void widget_grid_page_changed_cb(GtkAdjustment *adj, gpointer user_data) {
    WidgetGridRuntime *wg = user_data;
    int idx = (int)lround(gtk_adjustment_get_value(adj));
    for (guint i = 0; i < wg->page_boxes->len; i++)
        gtk_widget_set_visible(g_ptr_array_index(wg->page_boxes, i), (int)i == idx);
}

static ModuleRuntime *build_widget_grid(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg) {
    ModuleRuntime *rt = g_new0(ModuleRuntime, 1);
    rt->kind = RT_WIDGET_GRID;
    WidgetGridRuntime *wg = &rt->u.widget_grid;
    wg->mc = mc;
    wg->item_runtimes = g_ptr_array_new();
    wg->page_boxes = g_ptr_array_new();

    /* Anzahl statt Pixelbreite: aufloesungs-/skalierungsunabhaengig -
     * "immer genau N Stueck", egal auf welchem Bildschirm/Scale-Faktor
     * das laeuft. Das war der eigentliche Bug bei 1080p+2x: ein fester
     * max_width-Pixelwert passt eben nicht auf jede Aufloesung. */
    int per_row = mc->visible_count > 0 ? mc->visible_count : 3;

    wg->rows_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkWidget *cur_row = NULL;
    for (guint i = 0; i < mc->items->len; i++) {
        if (i % (guint)per_row == 0) {
            cur_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
            gtk_box_pack_start(GTK_BOX(wg->rows_box), cur_row, FALSE, FALSE, 0);
            g_ptr_array_add(wg->page_boxes, cur_row);
        }
        ModuleConfig *item_mc = g_ptr_array_index(mc->items, i);
        ModuleRuntime *item_rt = build_button(item_mc, cur_row, assets, cfg);
        g_ptr_array_add(wg->item_runtimes, item_rt);
    }
    if (wg->page_boxes->len == 0) { /* keine Items konfiguriert - trotzdem eine leere Seite, sonst NULL-Zugriffe unten */
        cur_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
        gtk_box_pack_start(GTK_BOX(wg->rows_box), cur_row, FALSE, FALSE, 0);
        g_ptr_array_add(wg->page_boxes, cur_row);
    }

    wg->page_adj = gtk_adjustment_new(0, 0, MAX(1, (double)wg->page_boxes->len), 1, 1, 1);
    g_signal_connect(wg->page_adj, "value-changed", G_CALLBACK(widget_grid_page_changed_cb), wg);
    int nav_thick = MAX(16, cfg->bubble.min_size - 6); /* s. Kommentar bei build_workspaces() */
    wg->vbar = tb_scrollbar_new(GTK_ORIENTATION_VERTICAL, wg->page_adj, nav_thick);
    tb_scrollbar_enable_autohide(wg->vbar);
    /* wg->rows_box ist eine reine GtkBox OHNE eigenes GdkWindow - Events
     * (Mausrad!) ueber der leeren Flaeche zwischen/neben den Icons kamen
     * da nie zuverlaessig an. GtkEventBox erzwingt ein echtes Fenster
     * fuer genau diesen Bereich, damit Mausrad ueber der ganzen Reihe
     * (nicht nur exakt ueber dem schmalen Balken) sicher greift. */
    GtkWidget *wheel_catcher = gtk_event_box_new();
    gtk_container_add(GTK_CONTAINER(wheel_catcher), wg->rows_box);
    tb_scrollbar_forward_wheel_from(wg->vbar, wheel_catcher);

    wg->container = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 3);
    gtk_box_pack_start(GTK_BOX(wg->container), wheel_catcher, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(wg->container), tb_scrollbar_widget(wg->vbar), FALSE, FALSE, 0);
    /* Balken ist jetzt eine feste, kompakte Groesse (2 Pfeil-Buttons,
     * kein Track mehr, der auf volle Zeilenhoehe gestreckt werden muss)
     * - einfach vertikal mittig neben die Reihe setzen. */
    gtk_widget_set_valign(tb_scrollbar_widget(wg->vbar), GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(box), wg->container, FALSE, FALSE, 0);
    gtk_widget_show_all(wg->container);

    widget_grid_page_changed_cb(wg->page_adj, wg); /* nur Seite 0 sichtbar */
    sb_autohide_cb(wg->page_adj, tb_scrollbar_widget(wg->vbar));
    /* WICHTIG: gtk_widget_show_all(window) in main() laeuft NACH dem
     * Bau aller Module und macht ALLE Kinder wieder sichtbar - auch die
     * hier bewusst versteckten Seiten 1..n! Das war der Grund fuer die
     * viel zu grosse Bar (main_box wollte ploetzlich Platz fuer ALLE
     * Seiten gleichzeitig). main() ruft darum tb_modules_resync_pages()
     * NACH gtk_widget_show_all(window) nochmal auf - siehe dort. */
    return rt;
}

/* MOD_BUTTON_ROW ist inzwischen exakt derselbe Mechanismus wie
 * MOD_WIDGET_GRID (Zeilenumbruch + Seiten-Balken statt Scrollen) - beide
 * jsonc-Typnamen bleiben erhalten (unterschiedliche Bedeutung fuer den
 * Menschen, der die Config liest), teilen sich aber denselben Builder. */
static ModuleRuntime *build_button_row(ModuleConfig *mc, GtkWidget *box, BubbleAssets *assets, BarConfig *cfg) {
    return build_widget_grid(mc, box, assets, cfg);
}

/* ── MOD_SPACER ─────────────────────────────────────────────────── */

static ModuleRuntime *build_spacer(ModuleConfig *mc, GtkWidget *box) {
    ModuleRuntime *rt = g_new0(ModuleRuntime, 1);
    rt->kind = RT_SPACER;
    SpacerRuntime *sr = &rt->u.spacer;
    sr->widget = gtk_drawing_area_new(); /* rein visuell leer, nur fuer die Breite */
    gtk_widget_set_size_request(sr->widget, MAX(0, mc->spacer_width), -1);
    gtk_box_pack_start(GTK_BOX(box), sr->widget, FALSE, FALSE, 0);
    gtk_widget_show(sr->widget);
    return rt;
}

/* ── Oeffentliche API ───────────────────────────────────────────── */

TbModules *tb_modules_build(GtkWidget *box, GPtrArray *module_configs,
                             BubbleAssets *assets, BarConfig *cfg) {
    TbModules *m = g_new0(TbModules, 1);
    m->runtimes = g_ptr_array_new();

    for (guint i = 0; i < module_configs->len; i++) {
        ModuleConfig *mc = g_ptr_array_index(module_configs, i);
        ModuleRuntime *rt = NULL;
        switch (mc->type) {
            case MOD_CLOCK: rt = build_clock(mc, box, assets, cfg); break;
            case MOD_HYPR_WORKSPACES: rt = build_workspaces(mc, box, assets, cfg); break;
            case MOD_TRAY: rt = build_tray(mc, box, assets, cfg); break;
            case MOD_SPACER: rt = build_spacer(mc, box); break;
            case MOD_BUTTON_ROW: rt = build_button_row(mc, box, assets, cfg); break;
            case MOD_WIDGET_GRID: rt = build_widget_grid(mc, box, assets, cfg); break;
            case MOD_BUTTON:
            default: rt = build_button(mc, box, assets, cfg); break;
        }
        if (rt) g_ptr_array_add(m->runtimes, rt);
    }
    return m;
}

static void runtime_free(ModuleRuntime *rt); /* rekursiv, siehe RT_WIDGET_GRID unten */

static void runtime_free(ModuleRuntime *rt) {
    switch (rt->kind) {
        case RT_BUTTON: {
            ButtonRuntime *r = &rt->u.button;
            if (r->exec_timeout_id) g_source_remove(r->exec_timeout_id);
            if (r->clock_timeout_id) g_source_remove(r->clock_timeout_id);
            tb_bubble_free(r->bubble);
            break;
        }
        case RT_WORKSPACES: {
            WorkspacesRuntime *wr = &rt->u.workspaces;
            if (wr->pending_rebuild_id) g_source_remove(wr->pending_rebuild_id);
            for (guint i = 0; i < wr->bubbles->len; i++)
                tb_bubble_free(g_ptr_array_index(wr->bubbles, i));
            g_ptr_array_free(wr->bubbles, TRUE);
            tb_bubble_free(wr->ws_bubble);
            tb_scrollbar_free(wr->vbar);
            tb_scrollbar_free(wr->apps_vbar);
            g_ptr_array_free(wr->apps_page_boxes, TRUE); /* Widgets selbst sterben mit dem Fenster */
            g_array_free(wr->ws_ids, TRUE);
            break;
        }
        case RT_TRAY: {
            TrayRuntime *tr = &rt->u.tray;
            tb_tray_free(tr->tray);
            break;
        }
        case RT_SPACER:
            /* Widget wird von GTK selbst zerstoert (Kind der Box) */
            break;
        case RT_WIDGET_GRID: {
            WidgetGridRuntime *wg = &rt->u.widget_grid;
            for (guint i = 0; i < wg->item_runtimes->len; i++)
                runtime_free(g_ptr_array_index(wg->item_runtimes, i));
            g_ptr_array_free(wg->item_runtimes, TRUE);
            g_ptr_array_free(wg->page_boxes, TRUE);
            tb_scrollbar_free(wg->vbar);
            break;
        }
    }
    g_free(rt);
}

void tb_modules_free(TbModules *m) {
    if (!m) return;
    for (guint i = 0; i < m->runtimes->len; i++)
        runtime_free(g_ptr_array_index(m->runtimes, i));
    g_ptr_array_free(m->runtimes, TRUE);
    g_free(m);
}


/* ───────────────────────── autohide : Typen/Deklarationen ───────────────────────── */
/* Ersetzt den alten WaybarAutohideDaemon.c + das SIGUSR1/2-Sende an
 * waybar: die Bar ist jetzt ihr eigener Prozess, kann also direkt
 * ihre gtk-layer-shell-Margin animieren statt einem fremden Prozess
 * ein Signal zu schicken. Cursor-Polling-Logik (3 Tiers) ist 1:1 vom
 * alten Daemon uebernommen.
 *
 * Kompatibel bleiben zusaetzlich:
 *  - PID-Datei /tmp/TrafkTuxBar.pid (frueher waybar-autohide.pid)
 *  - SIGRTMIN  -> Touch-Geste zeigt die Bar kurz (wie Touch-Wisch in hyprland.lua)
 *  - SIGRTMIN+1-> Autohide dauerhaft sperren/entsperren (wie mainMod-Bind)
 */
typedef struct TbAutohide TbAutohide;

TbAutohide *tb_autohide_start(GtkWindow *window, BarConfig *cfg);
void        tb_autohide_stop(TbAutohide *ah);

/* Manuelles Ein-/Ausblenden von aussen (z.B. Rechtsklick-Menu-Punkt
 * "Bar sperren" o.ae. - optional nutzbar). */
void tb_autohide_force_show(TbAutohide *ah);
void tb_autohide_force_hide(TbAutohide *ah);


/* ═══════════════════════════ autohide : Implementierung ═══════════════════════════ */
#define PID_FILE "/tmp/TrafkTuxBar.pid"
/* trigger_px kommt jetzt aus cfg->trigger_px (config-jsonc "autohide.
 * trigger_px") statt eines festen Werts - siehe poll_once(). */
#define TOUCH_SHOW_SIGNAL SIGRTMIN
#define TOUCH_TIMEOUT_SEC 5
#define LOCK_TOGGLE_SIGNAL (SIGRTMIN + 1)

#define FAST_POLL_MS 15
#define MID_POLL_MS  35
#define SLOW_POLL_MS 65

/* Slide-Animation */
#define AH_BOUNCE_C1        2.6     /* Ueberschwingen beim Zeigen (2.6 = ~20%, 1.7 = ~10%) */
#define AH_HIDE_FACTOR      0.6     /* Verstecken dauert slide_ms * Faktor */
#define AH_WATCHDOG_MS      10      /* Sicherheitsnetz, falls der Frame-Clock stillsteht */
#define AH_WATCHDOG_GAP_US  24000
#define AH_EDGE_SENSOR_PX   2       /* Hoehe des unsichtbaren Rand-Sensors */
#define AH_FILLER_FRAC      0.30    /* Reserve unter der Bar (Anteil der Bar-Hoehe) fuer den Overshoot */

/* Beim Overshoot faehrt die Bar ueber ihre Ruheposition hinaus. Damit dabei
 * unten keine Luecke entsteht, ist das Fenster um g_bar_filler_px hoeher als
 * die Bar (Reserve liegt in Ruhe unter dem Bildschirmrand) und der Bereich
 * darin wird von nine_slice_draw_extended() mit einer Bar-Bildzeile
 * aufgefuellt, so dass die Bar immer bis zum Rand reicht. Nur fuer Bars am
 * unteren Rand (Top-Bar: 0 = kein Overshoot). */
static int    g_bar_filler_px = 0;

struct TbAutohide {
    GtkWindow *window;
    BarConfig *cfg;

    gboolean visible;
    gboolean locked;
    gboolean touch_override_active;
    gint64   touch_override_until_us;
    gboolean force_visible;    /* z.B. waehrend die Bildschirmtastatur an ist */

    /* Slide-Animation */
    double   progress;      /* 0 = versteckt, 1 = sichtbar */
    double   progress_from;
    gint64   anim_start_us;
    guint    tick_id;           /* Frame-Clock-Tick-Callback am Fenster (vsync) */
    guint    watchdog_id;       /* Timer-Sicherheitsnetz */
    gint64   last_step_us;      /* Zeit des letzten Animationsschritts */
    int      wd_steps;          /* Schritte, die der Watchdog statt des Frame-Clocks machen musste */
    int      slide_margin;      /* aktueller Slide-Anteil des Margins */
    int      base_offset;       /* zusaetzlicher Margin (z.B. ueber der Bildschirmtastatur) */
    int      applied_margin;    /* zuletzt an die Layer-Shell gesendet */
    gint64   menu_hold_until_us; /* >jetzt: Tray-Menue offen, Bar sichtbar halten */
    GtkWidget *sensor;          /* unsichtbarer Rand-Sensor (Enter -> sofort zeigen) */
    gboolean first_tick_pending; /* fuer [timing]-Log: wie lange bis der allererste Animations-Frame */
    int      tick_seq;          /* fuer [timing]-Log: laufende Tick-Nummer waehrend EINER Animation */
    gint64   prev_tick_us;      /* fuer [timing]-Log: Abstand zum letzten Tick */

    guint    poll_source_id;

    HyprMonitor *monitors;
    int monitors_count;
    int refresh_counter;

    char        bar_monitor[64];  /* Hyprland-Name des Monitors, auf dem die Bar gerade sitzt */
    GdkMonitor *bar_gdk;          /* dazugehoeriger GdkMonitor (fuer Rand-Sensor) */

    int  signal_fd;         /* signalfd() fuer SIGRTMIN/SIGRTMIN+1 */
    guint signal_watch_id;  /* GIOChannel-Watch auf signal_fd */

    gint64 last_debug_log_us; /* Drosselung fuer die Diagnose-Ausgabe unten */
    gint64 last_poll_start_us; /* fuer [timing]-Log: tatsaechlicher Abstand zw. Polls */
};

static void write_pid_file(void) {
    FILE *f = fopen(PID_FILE, "w");
    if (!f) return;
    fprintf(f, "%d\n", getpid());
    fclose(f);
}

/* Bouncy "Pop"-Einfahren fuer's ZEIGEN - ueberschiesst kurz leicht ueber
 * das Ziel hinaus und faengt sich dann wieder (klassische "ease-out-back"
 * Kurve). Fuehlt sich lebendig/elastisch an, UND wirkt schneller als eine
 * symmetrische ease-in-out-Kurve, weil die Bewegung vorne rausballert
 * statt erst langsam anzufahren. */
static double ah_ease_out_back(double x) {
    const double c1 = AH_BOUNCE_C1;
    const double c3 = c1 + 1.0;
    double xm1 = x - 1.0;
    return 1.0 + c3 * xm1 * xm1 * xm1 + c1 * xm1 * xm1;
}

/* Zuegiges, GLATTES Verschwinden fuer's VERSTECKEN - bewusst OHNE
 * Overshoot (sonst wuerde die Bar beim Wegfahren kurz nochmal "reinpoppen",
 * was wie ein Grafikfehler aussieht statt wie ein Bounce). */
static double ah_ease_in_quad(double x) {
    return x * x;
}

/* ── Slide-Animation ─────────────────────────────────────────────── */

/* Sendet den Margin (Slide-Anteil + Offset) an die Layer-Shell - nur bei Aenderung. */
static void ah_apply_margin(TbAutohide *ah) {
    int m = ah->base_offset + ah->slide_margin;
    if (m == ah->applied_margin) return;
    ah->applied_margin = m;
    gtk_layer_set_margin(ah->window,
        g_strcmp0(ah->cfg->position, "top") == 0 ? GTK_LAYER_SHELL_EDGE_TOP : GTK_LAYER_SHELL_EDGE_BOTTOM, m);
}

/* Bildschirmtastatur: solange sie aktiv ist, sitzt die Bar ueber ihr (wie
 * bei Waybar) statt dahinter. Hoehe = von Hyprland gemeldete reservierte Zone. */
static void ah_update_base_offset(TbAutohide *ah) {
    int off = 0;
    if (ah->force_visible && ah->monitors_count > 0) {
        /* Der Monitor, auf dem die Bar gerade sitzt (nicht mehr blind der erste). */
        HyprMonitor *m = &ah->monitors[0];
        for (int i = 0; i < ah->monitors_count; i++) {
            if (g_strcmp0(ah->monitors[i].name, ah->bar_monitor) == 0) { m = &ah->monitors[i]; break; }
        }
        gboolean top = g_strcmp0(ah->cfg->position, "top") == 0;
        off = (int)(top ? m->reserved_top : m->reserved_bottom);
        if (off < 0) off = 0;
    }
    if (off != ah->base_offset) {
        g_message("[autohide] Tastatur-Offset: %d px -> %d px", ah->base_offset, off);
        ah->base_offset = off;
        ah_apply_margin(ah);
    }
}

/* Nach einem Monitor-Wechsel: die Eingabe-Region (nur die Bar, nicht die
 * Reserve darunter) neu setzen - die Surface wurde neu erzeugt. */
static void on_window_input_shape(GtkWidget *w, GdkRectangle *a, gpointer user_data);
static gboolean ah_reapply_shape_cb(gpointer user_data) {
    TbAutohide *ah = user_data;
    if (ah != g_autohide_singleton) return G_SOURCE_REMOVE;
    GtkWidget *w = GTK_WIDGET(ah->window);
    GtkAllocation a;
    gtk_widget_get_allocation(w, &a);
    if (a.width > 1 && a.height > 1) on_window_input_shape(w, &a, NULL);
    return G_SOURCE_REMOVE;
}

/* Bar (und Rand-Sensor) auf einen anderen Monitor umziehen. Margin,
 * Anker und Groesse bleiben erhalten, gtk-layer-shell mappt die Surface
 * dafuer neu. Tastatur-Offset wird fuer den neuen Monitor neu berechnet. */
static void ah_move_bar_to(TbAutohide *ah, HyprMonitor *m) {
    if (!m || g_strcmp0(ah->bar_monitor, m->name) == 0) return;
    GdkMonitor *gm = tb_gdk_monitor_for_hypr(m);
    if (!gm) {
        static gboolean warned = FALSE;
        if (!warned) {
            warned = TRUE;
            g_warning("[monitor] Kein GDK-Monitor fuer '%s' (%.0f,%.0f) gefunden - Bar kann nicht umziehen.",
                      m->name, m->x, m->y);
        }
        return;
    }
    g_message("[monitor] Bar zieht um: '%s' -> '%s'.", ah->bar_monitor[0] ? ah->bar_monitor : "?", m->name);
    g_strlcpy(ah->bar_monitor, m->name, sizeof(ah->bar_monitor));
    ah->bar_gdk = gm;
    gtk_layer_set_monitor(ah->window, gm);
    if (ah->sensor) gtk_layer_set_monitor(GTK_WINDOW(ah->sensor), gm);
    ah_update_base_offset(ah);
    g_idle_add(ah_reapply_shape_cb, ah);
    g_timeout_add(150, ah_reapply_shape_cb, ah);
}

/* Bar folgt dem Cursor: sitzt sie nicht auf dem Monitor unter dem Cursor,
 * zieht sie dorthin. Nicht bei fest eingestelltem "monitor" in der jsonc. */
static void ah_follow_cursor(TbAutohide *ah, int cx, int cy) {
    if (ah->cfg->monitor && *ah->cfg->monitor) return;
    HyprMonitor *m = tb_hypr_monitor_at(ah->monitors, ah->monitors_count, cx, cy);
    if (m) ah_move_bar_to(ah, m);
}

/* Ein Animationsschritt, rein zeitbasiert (Wanduhr) - egal ob vom Frame-Clock
 * oder vom Watchdog aufgerufen. KEIN Flush, KEIN process_updates: gtk_layer_set_margin()
 * ist nur ein kleiner Protokoll-Request, das Fenster selbst wird nicht neu gerendert.
 * Gibt TRUE zurueck, wenn die Animation fertig ist. */
static gboolean ah_step(TbAutohide *ah, gint64 now) {
    ah->last_step_us = now;
    ah->tick_seq++;
    if (ah->first_tick_pending) {
        ah->first_tick_pending = FALSE;
        g_message("[timing] erster Animations-Schritt %.1fms nach ah_start_slide().",
                  (now - ah->anim_start_us) / 1000.0);
    }

    GtkWidget *widget = GTK_WIDGET(ah->window);
    int win_h = gtk_widget_get_allocated_height(widget);
    int height = win_h - g_bar_filler_px;         /* Hoehe der Bar selbst */
    if (height <= 1) { height = ah->cfg->height; win_h = height + g_bar_filler_px; }

    double show_us = MAX(1, ah->cfg->slide_ms) * 1000.0;
    double duration_us = ah->visible ? show_us : MAX(40000.0, show_us * AH_HIDE_FACTOR);
    double target = ah->visible ? 1.0 : 0.0;
    double raw = CLAMP((now - ah->anim_start_us) / duration_us, 0.0, 1.0);
    ah->progress = ah->progress_from + (target - ah->progress_from) * raw;

    /* Zeigen: ease-out-back (federt ueber das Ziel und faengt sich = Bounce).
     * Verstecken: glatt, ohne Overshoot. */
    double eased = ah->visible ? ah_ease_out_back(ah->progress) : ah_ease_in_quad(ah->progress);
    /* v = sichtbare Hoehe ueber dem Rand (kann beim Overshoot > height sein). */
    double v = eased * height;
    if (v > win_h) v = win_h;
    ah->slide_margin = (int)lround(-win_h + v);
    ah_apply_margin(ah);

    /* Nur minimaler Damage: haelt den GDK-Frame-Clock ueber die
     * Frame-Callbacks des Compositors auf dessen echter Bildwiederholrate
     * (60/120/144 Hz). Ein Neuzeichnen der ganzen Bar ist nicht mehr
     * noetig - die Verlaengerung nach unten (nine_slice_draw_extended)
     * steht immer schon da. */
    gtk_widget_queue_draw_area(widget, 0, 0, 1, 1);

    if (raw >= 1.0) {
        g_message("[timing] Slide %s fertig: %d Schritte in %.0fms (davon %d durch Watchdog).",
                  ah->visible ? "SHOW" : "HIDE", ah->tick_seq,
                  (now - ah->anim_start_us) / 1000.0, ah->wd_steps);
        return TRUE;
    }
    return FALSE;
}

static gboolean ah_tick_cb(GtkWidget *w, GdkFrameClock *clock, gpointer user_data) {
    (void)w; (void)clock;
    TbAutohide *ah = user_data;
    if (ah_step(ah, g_get_monotonic_time())) {
        ah->tick_id = 0; /* GTK entfernt den Callback selbst (Rueckgabe FALSE) */
        if (ah->watchdog_id) { g_source_remove(ah->watchdog_id); ah->watchdog_id = 0; }
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

/* Sicherheitsnetz: bleibt der Frame-Clock aus (z.B. weil der Compositor fuer
 * eine ausserhalb liegende Layer-Surface keine Frame-Callbacks schickt),
 * treibt der Watchdog die Animation weiter - sie kann so nie haengen. */
static gboolean ah_watchdog_cb(gpointer user_data) {
    TbAutohide *ah = user_data;
    gint64 now = g_get_monotonic_time();
    if (now - ah->last_step_us < AH_WATCHDOG_GAP_US) return G_SOURCE_CONTINUE;
    ah->wd_steps++;
    if (ah_step(ah, now)) {
        ah->watchdog_id = 0;
        if (ah->tick_id) {
            gtk_widget_remove_tick_callback(GTK_WIDGET(ah->window), ah->tick_id);
            ah->tick_id = 0;
        }
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void ah_start_slide(TbAutohide *ah) {
    ah->progress_from = ah->progress;
    ah->anim_start_us = g_get_monotonic_time();
    ah->last_step_us = ah->anim_start_us;
    ah->tick_seq = 0;
    ah->wd_steps = 0;
    ah->prev_tick_us = 0;
    g_message("[timing] ah_start_slide() bei t=%.1fms.", ah->anim_start_us / 1000.0);
    ah->first_tick_pending = TRUE;
    if (ah->tick_id == 0)
        ah->tick_id = gtk_widget_add_tick_callback(GTK_WIDGET(ah->window), ah_tick_cb, ah, NULL);
    if (ah->watchdog_id == 0)
        ah->watchdog_id = g_timeout_add(AH_WATCHDOG_MS, ah_watchdog_cb, ah);
}

static void do_show(TbAutohide *ah) {
    if (ah->visible) return;
    ah->visible = TRUE;
    g_message("[autohide] -> SHOW (progress war %.2f)", ah->progress);
    ah_start_slide(ah);
}
static void do_hide(TbAutohide *ah) {
    if (!ah->visible) return;
    ah->visible = FALSE;
    g_message("[autohide] -> HIDE (progress war %.2f)", ah->progress);
    ah_start_slide(ah);
    /* Preview-Override aller Workspace-Module zuruecksetzen: beim naechsten
     * Oeffnen der Bar zeigt sie wieder den aktiven Workspace. */
    if (g_ws_runtimes) {
        for (guint _i = 0; _i < g_ws_runtimes->len; _i++) {
            WorkspacesRuntime *_wr = g_ptr_array_index(g_ws_runtimes, _i);
            if (_wr->viewing_override) {
                _wr->viewing_override = FALSE;
                _wr->viewed_ws_id = 0;
                workspaces_rebuild(_wr);
            }
        }
    }
}

/* Unsichtbarer, 2px hoher Layer-Shell-Streifen am Bildschirmrand. Die Maus
 * kann ihn beim Erreichen des Rands nicht verfehlen (der Cursor bleibt am
 * Rand haengen) -> enter-notify kommt sofort vom Compositor, ganz ohne
 * Polling-Wartezeit. Das Polling bleibt als Fallback und fuer's Verstecken. */
static gboolean ah_sensor_enter(GtkWidget *w, GdkEventCrossing *ev, gpointer user_data) {
    (void)w; (void)ev;
    TbAutohide *ah = user_data;
    if (!ah->locked && !ah->visible) {
        g_message("[timing] Kantensensor: Maus am Rand -> do_show() (ohne Poll-Wartezeit).");
        do_show(ah);
    }
    return FALSE;
}

static gboolean ah_sensor_draw(GtkWidget *w, cairo_t *cr, gpointer user_data) {
    (void)w; (void)user_data;
    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    return TRUE;
}

static void ah_create_edge_sensor(TbAutohide *ah) {
    GtkWidget *s = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    GtkWindow *win = GTK_WINDOW(s);
    gtk_widget_set_app_paintable(s, TRUE);
    GdkVisual *visual = gdk_screen_get_rgba_visual(gtk_widget_get_screen(s));
    if (visual) gtk_widget_set_visual(s, visual);
    gtk_window_set_accept_focus(win, FALSE);
    gtk_window_set_default_size(win, 1, AH_EDGE_SENSOR_PX);
    gtk_widget_set_size_request(s, -1, AH_EDGE_SENSOR_PX);

    gtk_layer_init_for_window(win);
    gtk_layer_set_layer(win, GTK_LAYER_SHELL_LAYER_OVERLAY);
    gtk_layer_set_namespace(win, "trafktuxbar-edge");
    gboolean top = g_strcmp0(ah->cfg->position, "top") == 0;
    gtk_layer_set_anchor(win, GTK_LAYER_SHELL_EDGE_LEFT, TRUE);
    gtk_layer_set_anchor(win, GTK_LAYER_SHELL_EDGE_RIGHT, TRUE);
    gtk_layer_set_anchor(win, top ? GTK_LAYER_SHELL_EDGE_TOP : GTK_LAYER_SHELL_EDGE_BOTTOM, TRUE);
    gtk_layer_set_exclusive_zone(win, -1);
    gtk_layer_set_keyboard_mode(win, GTK_LAYER_SHELL_KEYBOARD_MODE_NONE);

    /* Ueberhang: negativer Rand an der Bildschirmkante schiebt den Sensor
     * um edge_overhang_px HINTER den Bildschirmrand. Damit reicht seine
     * Hitbox auch in den Bereich des darunterliegenden Monitors hinein -
     * das Aufrufen der Bar ist dadurch viel einfacher, wenn dieser Monitor
     * ueber einem anderen positioniert ist (Maus am oberen Rand des
     * unteren Monitors trifft den Sensor sofort). Bei gesperrter Bar
     * (bar-lock) hat das keine Nebenwirkungen. */
    int overhang = ah->cfg->edge_overhang_px;
    if (overhang > 0) {
        GtkLayerShellEdge opp = top ? GTK_LAYER_SHELL_EDGE_BOTTOM : GTK_LAYER_SHELL_EDGE_TOP;
        gtk_layer_set_margin(win, top ? GTK_LAYER_SHELL_EDGE_TOP : GTK_LAYER_SHELL_EDGE_BOTTOM, -overhang);
        (void)opp; /* nur fuer eventuelle kuenftige Nutzung, kein Warning */
    }

    /* Gleicher Monitor wie die Bar; beim Umzug der Bar zieht er mit
     * (ah_move_bar_to()). */
    if (ah->bar_gdk) gtk_layer_set_monitor(win, ah->bar_gdk);

    gtk_widget_add_events(s, GDK_ENTER_NOTIFY_MASK);
    g_signal_connect(s, "enter-notify-event", G_CALLBACK(ah_sensor_enter), ah);
    g_signal_connect(s, "draw", G_CALLBACK(ah_sensor_draw), NULL);
    gtk_widget_show_all(s);
    ah->sensor = s;
    g_message("[autohide] Kantensensor aktiv (%d px, overhang=%dpx).", AH_EDGE_SENSOR_PX, overhang);
}

void tb_autohide_force_show(TbAutohide *ah) { do_show(ah); }
void tb_autohide_force_hide(TbAutohide *ah) { do_hide(ah); }

/* ── Rand-Distanz-Berechnung (1:1 Logik aus WaybarAutohideDaemon.c,
 * jetzt zusaetzlich um die "reserved"-Zone eines anderen Panels
 * korrigiert - siehe hypr_ipc_get_monitors()) ──────────────────── */

static float get_dist_to_edge(TbAutohide *ah, int cx, int cy, gboolean bottom_edge) {
    if (ah->monitors_count == 0)
        return bottom_edge ? (1080.0f - cy) : (float)cy;

    for (int i = 0; i < ah->monitors_count; i++) {
        HyprMonitor *m = &ah->monitors[i];
        float effective_bottom = m->y + m->h - m->reserved_bottom;
        float effective_top = m->y + m->reserved_top;
        if (cx >= m->x && cx <= (m->x + m->w) && cy >= m->y && cy <= (m->y + m->h)) {
            return bottom_edge ? effective_bottom - cy : cy - effective_top;
        }
    }
    for (int i = 0; i < ah->monitors_count; i++) {
        HyprMonitor *m = &ah->monitors[i];
        float effective_bottom = m->y + m->h - m->reserved_bottom;
        float effective_top = m->y + m->reserved_top;
        if (cx >= m->x && cx <= (m->x + m->w)) {
            if (bottom_edge) {
                if (cy > m->y + m->h) return (float)(ah->cfg->hide_px + 1);
                return effective_bottom - m->y;
            } else {
                if (cy < m->y) return (float)(ah->cfg->hide_px + 1);
                return effective_top - m->y;
            }
        }
    }
    if (ah->monitors_count > 0) {
        HyprMonitor *m = &ah->monitors[0];
        float effective_bottom = m->y + m->h - m->reserved_bottom;
        float effective_top = m->y + m->reserved_top;
        return bottom_edge ? effective_bottom - cy : cy - effective_top;
    }
    return 9999.0f;
}

/* ── Polling (3 Stufen: fast/mid/slow, wie im alten Daemon) ────────── */

static gboolean poll_once(gpointer user_data);

static void schedule_next_poll(TbAutohide *ah, int delay_ms) {
    ah->poll_source_id = g_timeout_add(delay_ms, poll_once, ah);
}

static gboolean poll_once(gpointer user_data) {
    TbAutohide *ah = user_data;
    ah->poll_source_id = 0;
    gint64 poll_start_now = g_get_monotonic_time();
    gint64 prev_poll_start_us = ah->last_poll_start_us; /* fuer den [timing]-Log unten */
    ah->last_poll_start_us = poll_start_now;

    /* Heartbeat: beweist, dass die Polling-Schleife ueberhaupt laeuft -
     * unabhaengig davon, ob Hyprland-IPC verfuegbar ist. Erste 5 Aufrufe
     * immer, danach hoechstens 1x/Sekunde (wie der Cursor-Log unten). */
    static int poll_call_count = 0;
    static gint64 last_heartbeat_us = 0;
    gint64 hb_now = g_get_monotonic_time();
    if (poll_call_count++ < 5 || hb_now - last_heartbeat_us >= 30000000) {
        last_heartbeat_us = hb_now;
        g_message("[autohide] poll_once() Aufruf #%d - Loop laeuft. visible=%d locked=%d "
                  "hypr_ipc_available=%d", poll_call_count, ah->visible, ah->locked,
                  hypr_ipc_available());
    }

    ah->refresh_counter++;
    if (ah->refresh_counter >= 50) {
        ah->refresh_counter = 0;
        g_free(ah->monitors);
        ah->monitors = hypr_ipc_get_monitors(&ah->monitors_count);
        ah_update_base_offset(ah);
    }

    if (ah->force_visible || ah->menu_hold_until_us > poll_start_now) {
        if (!ah->visible) do_show(ah);
        schedule_next_poll(ah, MID_POLL_MS);
        return G_SOURCE_REMOVE;
    }

    if (ah->locked) {
        schedule_next_poll(ah, SLOW_POLL_MS);
        return G_SOURCE_REMOVE;
    }

    gboolean bottom_edge = g_strcmp0(ah->cfg->position, "top") != 0;
    int poll_tier = (ah->visible || ah->touch_override_active) ? 2 : 0;

    if (ah->touch_override_active) {
        if (g_get_monotonic_time() >= ah->touch_override_until_us) {
            if (ah->visible) do_hide(ah);
            ah->touch_override_active = FALSE;
        }
    } else if (hypr_ipc_available()) {
        int cx, cy;
        gint64 t_before_cmd = g_get_monotonic_time();
        gboolean ok = hypr_ipc_get_cursor_pos(&cx, &cy);
        gint64 t_after_cmd = g_get_monotonic_time();
        if (ok) {
            float dist = get_dist_to_edge(ah, cx, cy, bottom_edge);
            int fast_zone = ah->cfg->hide_px * 2;

            gint64 now = g_get_monotonic_time();
            /* Diagnose nur noch alle 5 s statt bei jedem Poll (jedes g_message
             * ist ein write() auf stderr). */
            if (now - ah->last_debug_log_us >= 5000000) {
                ah->last_debug_log_us = now;
                double since_last_poll_start_ms = prev_poll_start_us > 0
                    ? (poll_start_now - prev_poll_start_us) / 1000.0 : -1.0;
                HyprMonitor *m0 = ah->monitors_count > 0 ? &ah->monitors[0] : NULL;
                g_message("[timing] cursor=(%d,%d) dist=%.1f visible=%d ipc_roundtrip=%.1fms "
                          "seit_start_letzter_poll=%.1fms mon0[y=%.0f h=%.0f reservedB=%.0f]",
                           cx, cy, dist, ah->visible, (t_after_cmd - t_before_cmd) / 1000.0,
                           since_last_poll_start_ms, m0 ? m0->y : -1, m0 ? m0->h : -1,
                           m0 ? m0->reserved_bottom : -1);
            }

            if (dist <= ah->cfg->trigger_px) {
                /* Zuerst auf den Monitor unter dem Cursor umziehen (falls
                 * noetig), erst dann zeigen. Gilt auch, wenn die Bar auf
                 * einem anderen Monitor schon sichtbar ist. */
                ah_follow_cursor(ah, cx, cy);
                if (!ah->visible) {
                    g_message("[timing] TRIGGER erkannt bei t=%.1fms (seit Programmstart), rufe do_show() auf.",
                              now / 1000.0);
                    do_show(ah);
                }
            } else if (dist > ah->cfg->hide_px && ah->visible) {
                do_hide(ah);
            }

            if (dist <= fast_zone) poll_tier = 2;
            else if (dist <= 200) poll_tier = 1;
        } else {
            g_warning("[autohide] hypr_ipc_get_cursor_pos() fehlgeschlagen (Socket tot?)");
        }
    } else {
        static gboolean warned_once = FALSE;
        if (!warned_once) {
            warned_once = TRUE;
            g_warning("[autohide] hypr_ipc nicht verfuegbar - Autohide reagiert NICHT auf die Maus.");
        }
    }

    int delay = poll_tier >= 2 ? FAST_POLL_MS : (poll_tier == 1 ? MID_POLL_MS : SLOW_POLL_MS);
    schedule_next_poll(ah, delay);
    return G_SOURCE_REMOVE;
}

/* ── Echtzeit-Signale (Touch-Geste / Lock-Toggle), kompatibel mit den
 * bestehenden hyprland.lua-Binds (kill -RTMIN / -RTMIN+1 <pid>) ────
 *
 * WICHTIG: g_unix_signal_add() unterstuetzt NUR SIGHUP/SIGINT/SIGTERM/
 * SIGUSR1/SIGUSR2/SIGWINCH (siehe GLib-Doku) - SIGRTMIN & SIGRTMIN+1
 * loesen dort einen g_return-Assert aus und werden NIE zugestellt. Wir
 * blocken die Signale stattdessen per sigprocmask() ganz normal und
 * lesen sie ueber signalfd() im Main-Loop - das funktioniert fuer
 * beliebige Signalnummern, auch Realtime-Signale. */

/* Zeigt eine Desktop-Benachrichtigung, aber NUR wenn notify-send
 * ueberhaupt installiert ist - g_spawn_command_line_async() wuerde bei
 * einem fehlenden Binary zwar auch nur (sauber, ohne Crash) fehlschlagen,
 * aber ein Vorab-Check macht das Verhalten explizit statt implizit und
 * spart den unnoetigen Shell-Parse-Versuch. */
static void notify(const char *message) {
    static gboolean checked = FALSE;
    static gboolean available = FALSE;
    if (!checked) {
        char *path = g_find_program_in_path("notify-send");
        available = (path != NULL);
        g_free(path);
        checked = TRUE;
        if (!available)
            g_message("[autohide] notify-send nicht gefunden - Benachrichtigungen werden uebersprungen.");
    }
    if (!available) return;

    char *cmd = g_strdup_printf("notify-send -t 1200 'TrafkTuxBar' '%s'", message);
    run_shell(cmd);
    g_free(cmd);
}

static void handle_touch_signal(TbAutohide *ah) {
    if (hypr_ipc_available() && !(ah->cfg->monitor && *ah->cfg->monitor)) {
        int cx, cy;
        if (hypr_ipc_get_cursor_pos(&cx, &cy)) {
            g_free(ah->monitors);
            ah->monitors = hypr_ipc_get_monitors(&ah->monitors_count);
            ah_follow_cursor(ah, cx, cy);
        }
    }
    if (!ah->visible) do_show(ah);
    ah->touch_override_active = TRUE;
    ah->touch_override_until_us = g_get_monotonic_time() + (gint64)TOUCH_TIMEOUT_SEC * 1000000;
    g_message("[autohide] SIGRTMIN empfangen - Bar wird kurz gezeigt.");
}

static void handle_lock_signal(TbAutohide *ah) {
    ah->locked = !ah->locked;
    g_message("[autohide] SIGRTMIN+1 empfangen - locked=%d.", ah->locked);
    if (ah->locked) {
        g_message("[autohide] handle_lock_signal: rufe do_hide() auf...");
        do_hide(ah);
        g_message("[autohide] handle_lock_signal: do_hide() zurueck.");
        ah->touch_override_active = FALSE;
        notify("Autohide gesperrt");
    } else {
        notify("Autohide entsperrt");
    }
    g_message("[autohide] handle_lock_signal: fertig.");
}

static gboolean on_signalfd_readable(GIOChannel *source, GIOCondition cond, gpointer user_data) {
    (void)source;
    TbAutohide *ah = user_data;
    if (cond & (G_IO_HUP | G_IO_ERR)) return G_SOURCE_REMOVE;

    struct signalfd_siginfo si;
    ssize_t n;
    /* signalfd ist non-blocking - alle wartenden Signale in einem
     * Rutsch abholen, Echtzeit-Signale werden sonst aufgestaut. */
    while ((n = read(ah->signal_fd, &si, sizeof(si))) == sizeof(si)) {
        if ((int)si.ssi_signo == TOUCH_SHOW_SIGNAL) handle_touch_signal(ah);
        else if ((int)si.ssi_signo == LOCK_TOGGLE_SIGNAL) handle_lock_signal(ah);
    }
    return G_SOURCE_CONTINUE;
}

/* WICHTIG: muss als praktisch ERSTES im ganzen Programm laufen, VOR
 * gtk_init() und jeglicher D-Bus/Tray-Initialisierung. sigprocmask()
 * setzt die Signalmaske nur fuer den AUFRUFENDEN Thread - GLib/GTK/GIO
 * erzeugen intern eigene Worker-Threads (z.B. der GDBusConnection-
 * I/O-Thread, den tb_tray_new() ueber g_bus_get_sync() anstoesst).
 * Jeder Thread, der VOR diesem Aufruf hier entsteht, hat SIGRTMIN/
 * SIGRTMIN+1 weiterhin UNBLOCKIERT - trifft der Kernel zufaellig genau
 * diesen Thread mit dem Signal (Linux liefert Prozess-Signale an einen
 * beliebigen Thread, der es nicht blockiert), greift dort mangels
 * Handler die Standardaktion fuer Echtzeitsignale: Prozess-Terminierung!
 * Das war exakt der Grund fuer die zufaelligen "Real-Time Signal 1"-
 * Abstuerze beim Touch-Gesten-/Lock-Signal. Wird die Maske dagegen VOR
 * jeder Thread-Erzeugung gesetzt, erben alle spaeter erzeugten Threads
 * sie automatisch, und der Kernel liefert das Signal zuverlaessig an
 * einen Thread, der es blockiert (hier: den Haupt-Thread mit dem
 * signalfd()).
 *
 * NACHTRAG: genau dieser Fix (Aufruf ganz an den Anfang von main()
 * verschieben) war schon drin - und der Crash trat TROTZDEM noch auf.
 * Mit reinem Nachdenken/Code-Lesen laesst sich nicht zweifelsfrei
 * herausfinden, WELCHER Thread das Signal am Ende doch unblockiert
 * bekommen hat (z.B. weil irgendeine Bibliothek - GDBus, GTK/Fontconfig,
 * ein Icon-Loader o.ae. - fuer einen eigenen Worker-Thread aktiv
 * pthread_sigmask() aufruft, statt die geerbte Maske stehen zu lassen).
 * Deshalb zusaetzlich ein zweites, unabhaengiges Sicherheitsnetz:
 * sigaction() registriert einen (bewusst leeren) Handler fuer beide
 * Signale. Ohne einen registrierten Handler fuehrt JEDE Zustellung an
 * einen Thread, der das Signal nicht blockiert, zur Standardaktion
 * (Prozess-Terminierung) - MIT Handler passiert in genau diesem
 * (eigentlich unerwarteten) Fall stattdessen: nichts, der Handler
 * kehrt sofort zurueck. Der normale, erwartete Zustellweg bleibt
 * weiterhin signalfd() im Haupt-Thread (siehe setup_realtime_signals())
 * - das hier ist nur die Absicherung fuer den Fall, dass die Maske aus
 * irgendeinem Grund doch nicht ueberall greift. */
static void rt_signal_noop_handler(int signo) {
    (void)signo;
    /* Absichtlich leer - siehe Kommentar oben. Nur async-signal-sichere
     * Operationen waeren hier ueberhaupt erlaubt (kein g_message(), kein
     * malloc() etc.), daher bewusst NICHTS weiter als sofort zurueckkehren. */
}

static gboolean block_realtime_signals_early(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = rt_signal_noop_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_RESTART;
    sigaction(TOUCH_SHOW_SIGNAL, &sa, NULL);
    sigaction(LOCK_TOGGLE_SIGNAL, &sa, NULL);

    sigset_t mask;
    sigemptyset(&mask);
    sigaddset(&mask, TOUCH_SHOW_SIGNAL);
    sigaddset(&mask, LOCK_TOGGLE_SIGNAL);
    if (sigprocmask(SIG_BLOCK, &mask, NULL) != 0) {
        g_warning("[autohide] sigprocmask fehlgeschlagen: %s", g_strerror(errno));
        return FALSE;
    }
    return TRUE;
}

static gboolean setup_realtime_signals(TbAutohide *ah) {
    /* Maske wurde schon ganz am Anfang von main() gesetzt (siehe
     * block_realtime_signals_early()) - hier nur noch signalfd() +
     * GIOChannel-Watch einrichten. */
    sigset_t mask;
    sigemptyset(&mask);
    sigaddset(&mask, TOUCH_SHOW_SIGNAL);
    sigaddset(&mask, LOCK_TOGGLE_SIGNAL);

    ah->signal_fd = signalfd(-1, &mask, SFD_NONBLOCK | SFD_CLOEXEC);
    if (ah->signal_fd < 0) {
        g_warning("[autohide] signalfd() fehlgeschlagen: %s", g_strerror(errno));
        return FALSE;
    }

    GIOChannel *chan = g_io_channel_unix_new(ah->signal_fd);
    g_io_channel_set_encoding(chan, NULL, NULL);
    g_io_channel_set_close_on_unref(chan, TRUE);
    ah->signal_watch_id = g_io_add_watch(chan, G_IO_IN | G_IO_HUP | G_IO_ERR,
                                          on_signalfd_readable, ah);
    g_io_channel_unref(chan); /* watch haelt eigene Referenz */
    return TRUE;
}

/* ── API ─────────────────────────────────────────────────────────── */

/* Erzwingt "sichtbar", unabhaengig von der Cursor-Position - z.B. waehrend
 * die Bildschirmtastatur (wvkbd) an ist: die sitzt am unteren Bildschirm-
 * rand, genau da, wo Autohide sonst "Maus ist weit weg -> verstecken"
 * entscheiden wuerde, sobald man mitten im Tippen ist und die Maus/der
 * letzte Finger dadurch nicht mehr "nah am Rand" im ueblichen Sinne ist.
 * Einfacher, robuster Ansatz statt die Tastatur-Geometrie tracken zu
 * muessen: waehrend sie an ist, bleibt die Bar schlicht immer da.
 * (Deklaration weiter oben, direkt nach hypr_ipc_dispatch() - siehe
 * Kommentar dort.) */
static gboolean ah_kbd_recheck_cb(gpointer user_data) {
    TbAutohide *ah = user_data;
    if (ah != g_autohide_singleton || !ah->force_visible) return G_SOURCE_REMOVE;
    g_free(ah->monitors);
    ah->monitors = hypr_ipc_get_monitors(&ah->monitors_count);
    ah_update_base_offset(ah);
    return G_SOURCE_REMOVE;
}

/* Haelt die Bar sichtbar, solange ein Tray-Menue offen ist (das Menue haengt
 * an der Bar-Surface; wuerde sie wegfahren, verschwaende das Menue mit). */
static void tb_autohide_menu_hold(TbAutohide *ah, gboolean hold) {
    if (!ah) return;
    ah->menu_hold_until_us = hold ? g_get_monotonic_time() + 120 * G_USEC_PER_SEC : 0;
    if (hold && !ah->visible) do_show(ah);
}

static void tb_autohide_set_force_visible(TbAutohide *ah, gboolean active) {
    if (!ah || ah->force_visible == active) return; /* keine Aenderung */
    ah->force_visible = active;
    if (active) {
        /* Reservierte Zone (Tastaturhoehe) sofort abfragen und in den
         * naechsten Momenten noch ein paar Mal nachpruefen - die Tastatur
         * meldet ihre Zone erst kurz nach dem Start. */
        g_free(ah->monitors);
        ah->monitors = hypr_ipc_get_monitors(&ah->monitors_count);
        g_timeout_add(250, ah_kbd_recheck_cb, ah);
        g_timeout_add(700, ah_kbd_recheck_cb, ah);
        g_timeout_add(1500, ah_kbd_recheck_cb, ah);
    }
    ah_update_base_offset(ah);
    if (active) {
        g_message("[autohide] force_visible AN (z.B. Bildschirmtastatur aktiv) - Bar bleibt sichtbar.");
        if (!ah->visible) do_show(ah);
    } else {
        g_message("[autohide] force_visible AUS - normales cursorbasiertes Autohide wieder aktiv.");
    }
}

TbAutohide *tb_autohide_start(GtkWindow *window, BarConfig *cfg) {
    TbAutohide *ah = g_new0(TbAutohide, 1);
    ah->window = window;
    ah->cfg = cfg;
    ah->visible = TRUE;   /* Start sichtbar, dann uebernimmt das Polling */
    ah->progress = 1.0;
    ah->signal_fd = -1;
    g_autohide_singleton = ah;
    g_strlcpy(ah->bar_monitor, g_bar_monitor_name, sizeof(ah->bar_monitor));
    ah->bar_gdk = g_bar_gdk_monitor;
    /* Ruhelage: die Reserve unter der Bar liegt unter dem Bildschirmrand. */
    ah->slide_margin = -g_bar_filler_px;
    ah_apply_margin(ah);

    write_pid_file();

    /* hypr_ipc_init() wird jetzt ganz am Anfang von main() aufgerufen,
     * BEVOR die Module (insbesondere hyprland_workspaces) gebaut
     * werden - vorher lief das hier zu spaet und das Workspace-Modul
     * hat seinen allerersten (und einzigen initialen) Rebuild noch mit
     * hypr_ipc_available()==FALSE gemacht, blieb also fuer immer leer. */
    ah->monitors = hypr_ipc_get_monitors(&ah->monitors_count);

    if (cfg->autohide_enabled) {
        schedule_next_poll(ah, SLOW_POLL_MS);
        g_message("[autohide] Polling gestartet (autohide_enabled=true, erster Poll in %dms).", SLOW_POLL_MS);
    } else {
        g_message("[autohide] autohide_enabled=false in der Config - Polling wird NICHT gestartet, "
                  "Bar bleibt dauerhaft sichtbar.");
    }

    setup_realtime_signals(ah);

    if (cfg->autohide_enabled) ah_create_edge_sensor(ah);

    return ah;
}

void tb_autohide_stop(TbAutohide *ah) {
    if (!ah) return;
    if (ah->poll_source_id) g_source_remove(ah->poll_source_id);
    /* Der Frame-Clock-Callback stirbt mit dem (beim Beenden schon
     * zerstoerten) Fenster - hier nur den Timer entfernen. */
    if (ah->watchdog_id) g_source_remove(ah->watchdog_id);
    if (ah->sensor) gtk_widget_destroy(ah->sensor);
    if (ah->signal_watch_id) g_source_remove(ah->signal_watch_id);
    g_free(ah->monitors);
    unlink(PID_FILE);
    if (g_autohide_singleton == ah) g_autohide_singleton = NULL;
    g_free(ah);
}


/* ═══════════════════════════ main : Implementierung ═══════════════════════════ */
/* TrafkTuxBar - custom GTK/Layer-Shell Statusbar
 *
 * Ersetzt waybar + WaybarAutohideDaemon.c komplett durch einen einzigen
 * Prozess. Visuelles Konzept (siehe README.md fuer Details):
 *   - Bar-Hintergrund: Bar.png per 3-/9-Slice gezeichnet (Ecken bleiben
 *     unverzerrt, nur die Mitte wird gestreckt) statt CSS-background.
 *   - Jedes Modul ist eine "Bubble" aus zwei Bildern (Hintergrund +
 *     Vordergrund), Icon/Text liegt dazwischen -> wirkt wirklich "in"
 *     der Blase. Hover blendet weich zwischen normal/hover ueber.
 *   - Icons kommen aus einem echten Icon-Theme (z.B. "Clay") statt aus
 *     einer Nerd Font.
 *   - Autohide + Show/Hide-Transition sind jetzt Teil dieses einen
 *     Prozesses (kein externer Daemon + Signale mehr noetig).
 */


typedef struct {
    BarConfig    *cfg;
    NineSlice    *bar_bg;
    BubbleAssets *assets;
    TbAutohide   *autohide;
    TbModules    *mod_left, *mod_center, *mod_right;
} AppState;

/* Zeichnet den Bar-Hintergrund (Bar.png, 3-/9-Slice) hinter allen
 * Modulen. Haengt normal (nicht _after) am "draw"-Signal von main_box:
 * das "draw"-Signal ist RUN_LAST, unser Handler laeuft also VOR
 * GtkBox' eigenem Default-Handler, der die Kinder (Module) zeichnet -
 * genau die richtige Reihenfolge fuer "Hintergrund hinter Inhalt". */
static gboolean on_bar_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data) {
    AppState *app = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(widget, &alloc);
    /* Die unteren g_bar_filler_px sind Reserve fuer den Aufklapp-Overshoot:
     * dort wird die Bar nach unten VERLAENGERT (nicht gestreckt), siehe
     * nine_slice_draw_extended(). Immer gezeichnet, unabhaengig vom
     * aktuellen Animationsstand - kein Frame-Rueckstand mehr moeglich. */
    double bh = alloc.height - g_bar_filler_px;
    if (bh < 1) bh = alloc.height;
    nine_slice_draw_extended(app->bar_bg, cr, alloc.width, bh, g_bar_filler_px);
    return FALSE; /* Kinder (die Module) werden von GTK danach normal gezeichnet */
}

/* Die Reserve unter der Bar soll keine Klicks schlucken (z.B. auf die
 * Bildschirmtastatur, wenn die Bar darueber sitzt): Eingabebereich = nur die Bar. */
static void on_window_input_shape(GtkWidget *w, GdkRectangle *a, gpointer user_data) {
    (void)user_data;
    if (g_bar_filler_px <= 0) return;
    GdkWindow *gw = gtk_widget_get_window(w);
    if (!gw) return;
    cairo_rectangle_int_t r = { 0, 0, a->width, MAX(1, a->height - g_bar_filler_px) };
    cairo_region_t *reg = cairo_region_create_rectangle(&r);
    gdk_window_input_shape_combine_region(gw, reg, 0, 0);
    cairo_region_destroy(reg);
}

static void apply_layer_shell(GtkWindow *window, BarConfig *cfg) {
    gtk_layer_init_for_window(window);
    gtk_layer_set_layer(window, GTK_LAYER_SHELL_LAYER_OVERLAY);
    gtk_layer_set_namespace(window, "trafktuxbar");

    /* Mehrere Monitore: OHNE das hier faellt die Wahl gtk-layer-shell /
     * dem Compositor selbst zu, was NICHT zwingend der Monitor ist, auf
     * dem der Mensch die Bar tatsaechlich haben will (der urspruengliche
     * Bug-Report: "Bar taucht am falschen Monitor auf"). gtk-layer-shell
     * will dafuer ein echtes GdkMonitor* - das gibt es nur ueber GDK,
     * nicht ueber Hyprlands IPC. Deshalb: Hyprland nennt uns per Name
     * (cfg->monitor) den Ziel-Monitor samt Position (x,y in LOGISCHEN
     * Koordinaten, schon durch den Skalierungsfaktor geteilt), und wir
     * suchen unter ALLEN GdkMonitoren denjenigen mit genau dieser
     * Position - das ist portabel und funktioniert ohne wayland-
     * spezifische APIs, weil GDKs eigene Monitor-Geometrie in
     * derselben logischen Koordinatenwelt wie Hyprlands x/y liegt. */
    {
        /* "monitor" gesetzt -> Bar bleibt fest dort. Leer -> Startmonitor ist
         * der unter dem Cursor; danach zieht der Autohide die Bar bei jedem
         * Ausloesen auf den Monitor, an dessen Rand der Cursor ist. */
        int mon_count = 0;
        HyprMonitor *mons = hypr_ipc_get_monitors(&mon_count);
        HyprMonitor *target = NULL;
        if (cfg->monitor && *cfg->monitor) {
            target = find_target_hypr_monitor(cfg, mons, mon_count);
        } else {
            int cx, cy;
            if (hypr_ipc_get_cursor_pos(&cx, &cy))
                target = tb_hypr_monitor_at(mons, mon_count, cx, cy);
            if (!target && mon_count > 0) target = &mons[0];
        }
        if (target) {
            GdkMonitor *found = tb_gdk_monitor_for_hypr(target);
            if (found) {
                gtk_layer_set_monitor(window, found);
                g_bar_gdk_monitor = found;
                g_strlcpy(g_bar_monitor_name, target->name, sizeof(g_bar_monitor_name));
                g_message("[monitor] Bar startet an Monitor '%s' (%.0f,%.0f).",
                          target->name, target->x, target->y);
            } else {
                g_warning("[monitor] Kein GDK-Monitor an Position (%.0f,%.0f) gefunden fuer '%s' - "
                          "Compositor/gtk-layer-shell entscheiden selbst.",
                          target->x, target->y, target->name);
            }
        }
        g_free(mons);
    }

    gboolean top = g_strcmp0(cfg->position, "top") == 0;
    gtk_layer_set_anchor(window, GTK_LAYER_SHELL_EDGE_LEFT, TRUE);
    gtk_layer_set_anchor(window, GTK_LAYER_SHELL_EDGE_RIGHT, TRUE);
    gtk_layer_set_anchor(window, top ? GTK_LAYER_SHELL_EDGE_TOP : GTK_LAYER_SHELL_EDGE_BOTTOM, TRUE);

    /* exclusive_zone: reserviert echten Platz auf dem Bildschirm.
     * Fuer eine Autohide-Bar i.d.R. FALSE (overlay), genau wie in der
     * alten waybar-Config ("exclusive": false, "mode": "hide"). */
    gtk_layer_set_exclusive_zone(window, cfg->exclusive_zone ? cfg->height : -1);

    /* Explizit statt dem (identischen) Default: eine Bar soll NIE
     * Tastaturfokus einsammeln (sonst klaut sie z.B. Tastatureingaben
     * von der gerade aktiven App, sobald der Compositor ihr aus
     * irgendeinem Grund doch Fokus gibt). Fuer die Maus/Klicks macht
     * das keinen Unterschied - Pointer- und Keyboard-Interaktivitaet
     * sind im Layer-Shell-Protokoll zwei getrennte Dinge - aber explizit
     * ist besser als implizit, falls sich der Default je zwischen
     * gtk-layer-shell-Versionen unterscheidet. */
    gtk_layer_set_keyboard_mode(window, GTK_LAYER_SHELL_KEYBOARD_MODE_NONE);

    /* Bar beginnt sichtbar (margin=0) - tb_autohide_start() setzt
     * ah->visible passend dazu auf TRUE, damit beide Seiten (Layer-
     * Shell-Margin und Autohide-Zustand) beim Start synchron sind.
     * Sobald der erste Poll feststellt, dass die Maus weit vom Rand
     * entfernt ist, faehrt do_hide() sie sauber animiert weg. */
    gtk_layer_set_margin(window, top ? GTK_LAYER_SHELL_EDGE_TOP : GTK_LAYER_SHELL_EDGE_BOTTOM, 0);
}

static void load_css(void) {
    /* Minimales CSS - nur fuer Dinge, die Cairo nicht uebernimmt
     * (z.B. Fensterhintergrund transparent, Tooltip-Styling). Der
     * komplette visuelle Look der Bar selbst kommt aus Bar.png +
     * den Bubble-Bildern, nicht mehr aus CSS. */
    GtkCssProvider *provider = gtk_css_provider_new();
    const char *css =
        "window { background-color: transparent; }\n"
        "tooltip { padding: 4px 8px; }\n";
    gtk_css_provider_load_from_data(provider, css, -1, NULL);
    gtk_style_context_add_provider_for_screen(
        gdk_screen_get_default(), GTK_STYLE_PROVIDER(provider),
        GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    g_object_unref(provider);
}

static gboolean enable_screen_alpha(GtkWidget *widget) {
    GdkScreen *screen = gtk_widget_get_screen(widget);
    GdkVisual *visual = gdk_screen_get_rgba_visual(screen);
    if (visual) {
        gtk_widget_set_visual(widget, visual);
        return TRUE;
    }
    return FALSE;
}

/* ── Debug-/Diagnose-Hilfsmittel ─────────────────────────────────────
 * BUILD-TAG: wird bei JEDEM Start als allererste Log-Zeile ausgegeben
 * (siehe main()). Damit ist zweifelsfrei nachpruefbar, welcher Build
 * tatsaechlich laeuft, statt es zu raten - bitte bei jedem Testlauf
 * die BUILD-Zeile mit posten. */
#define TB_BUILD_TAG "2026-09-redesign-fix6-follow-cursor-monitor"

static gboolean on_window_click_probe(GtkWidget *widget, GdkEventButton *ev, gpointer user_data) {
    (void)widget; (void)user_data;
    g_message("[click-probe] FENSTER hat button-press-event bekommen: x=%.0f y=%.0f button=%u",
              ev->x, ev->y, ev->button);
    return FALSE; /* nicht schlucken - normal weiterreichen an die Kinder */
}

static void on_window_size_allocate_probe(GtkWidget *widget, GdkRectangle *alloc, gpointer user_data) {
    (void)widget; (void)user_data;
    /* nur die ersten paar Male loggen, sonst spammt es bei jedem Resize */
    static int count = 0;
    if (count++ < 5) {
        g_message("[debug] Fenster-size-allocate #%d: %dx%d @ (%d,%d)",
                  count, alloc->width, alloc->height, alloc->x, alloc->y);
    }
}

/* DIAGNOSE-Kanarienvogel: voellig unabhaengig von Autohide/Tray/Klicks -
 * ein simpler g_timeout_add(), der alle 500ms tickt. Zweck: naechstes Mal,
 * wenn "Klicks kommen nicht an" + "Autohide feuert nicht" gleichzeitig
 * auftreten, sehen wir hier SOFORT, ob das GANZE GLib-Hauptloop nach dem
 * Start ueberhaupt noch iteriert, oder ob es irgendwo (vermutlich in der
 * Wayland/Layer-Shell-Anbindung) komplett haengen bleibt. Bleibt DIESE
 * Meldung nach dem Start ebenfalls aus, ist es kein Klick- oder
 * Autohide-spezifisches Problem, sondern die Hauptschleife selbst steht -
 * dann brauchen wir als naechstes ein `gdb -p $(pidof TrafkTuxBar)` + `bt`
 * waehrend die Bar haengt, um zu sehen, WO genau. Tickt sie dagegen brav
 * weiter, ist es enger auf Autohide/Klicks eingegrenzt. */
static gboolean canary_heartbeat(gpointer user_data) {
    (void)user_data;
    static int n = 0;
    g_message("[canary] Hauptloop lebt noch, Tick #%d.", ++n);
    return G_SOURCE_CONTINUE;
}

int main(int argc, char **argv) {
    g_message("[debug] TrafkTuxBar BUILD=" TB_BUILD_TAG " startet (PID %d)", getpid());
    gint64 t_start_us = g_get_monotonic_time();

    /* WICHTIG fuer Autohide-Latenz: der Linux-Kernel darf Timer- und
     * poll()/epoll_wait()-Aufwachzeiten (GENAU das, worauf g_timeout_add()
     * intern basiert) um den "Timer Slack" des Prozesses nach hinten
     * verschieben, um mehrere Aufwach-Ereignisse zu buendeln und Strom zu
     * sparen. Default sind hier gemessen 50000ns (50 Mikrosekunden) - das
     * allein erklaert KEINE hunderte Millisekunden Verzoegerung. Trotzdem
     * gesetzt, weil es garantiert nicht schadet (ein bisschen mehr, dafuer
     * praeziser getimte Aufwach-Events kostet praktisch nichts bei der
     * Handvoll winziger IPC-Calls/Sekunde, die diese Bar macht) und weil
     * es zusammen mit dem cpufreq/cpuidle-Governor (powersave vs.
     * performance - genau der Unterschied, den du beobachtet hast) in
     * dieselbe Kerbe schlaegt: je aggressiver der Kernel/die Hardware
     * Aufwach-Events buendelt bzw. den Prozessor in tiefe C-States/
     * niedrige Taktraten parkt, desto spaeter kommt JEDER Timer bei uns
     * an - nicht nur der Poll-Timer, sondern auch der 16ms-Animations-
     * Timer selbst. Der GROESSTE Hebel dafuer liegt aber ausserhalb
     * dieses Programms, naemlich im cpufreq-Governor/Power-Profil des
     * Systems (z.B. via powerprofilesctl/TLP/tuned) - das kann Code hier
     * nicht erzwingen. */
    if (prctl(PR_SET_TIMERSLACK, 1000UL, 0, 0, 0) != 0) {
        g_warning("[timing] PR_SET_TIMERSLACK fehlgeschlagen: %s", g_strerror(errno));
    } else {
        g_message("[timing] Timer-Slack auf 1us gesetzt (weniger Timer-Buendelung durch den Kernel).");
    }

    /* MUSS vor gtk_init() passieren - siehe Kommentar an
     * block_realtime_signals_early() selbst. */
    block_realtime_signals_early();
    gtk_init(&argc, &argv);

    char *config_path = NULL;
    if (argc > 1) {
        config_path = g_strdup(argv[1]);
    } else {
        config_path = g_build_filename(g_get_user_config_dir(), "TrafkTuxBar", "TrafkTuxBar.jsonc", NULL);
    }

    BarConfig *cfg = config_load(config_path);
    g_free(config_path);
    if (!cfg) {
        g_printerr("Konnte Konfiguration nicht laden - Abbruch.\n");
        return EXIT_FAILURE;
    }

    AppState app = {0};
    app.cfg = cfg;

    GError *err = NULL;
    char *bar_bg_path = config_resolve_asset(cfg, cfg->bar_bg.image_path);
    app.bar_bg = nine_slice_load(bar_bg_path, cfg->bar_bg.left_slice, cfg->bar_bg.right_slice, &err);
    g_free(bar_bg_path);
    if (!app.bar_bg) {
        g_printerr("Konnte Bar-Hintergrund nicht laden: %s\n", err ? err->message : "?");
        return EXIT_FAILURE;
    }

    app.assets = bubble_assets_load(cfg, &err);
    if (!app.assets) {
        g_printerr("Konnte Blasen-Bilder nicht laden: %s\n", err ? err->message : "?");
        return EXIT_FAILURE;
    }

    /* WICHTIG: muss VOR tb_modules_build() laufen - das
     * hyprland_workspaces-Modul macht seinen ersten Rebuild synchron
     * beim Bauen und braucht dafuer eine bereits initialisierte
     * Hyprland-IPC-Verbindung, sonst bleibt es leer. */
    hypr_ipc_init();

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_widget_set_app_paintable(window, TRUE);
    enable_screen_alpha(window);
    load_css();
    apply_layer_shell(GTK_WINDOW(window), cfg);

    /* WICHTIG: kein GtkOverlay mehr! Vorher lag der gezeichnete
     * Hintergrund (bg_area) und die Module (main_box) als getrennte
     * Overlay-Kinder nebeneinander - beide bekommen dabei ihr eigenes
     * natives GdkWindow (GtkDrawingArea UND GtkEventBox tun das
     * defaultmaessig). GtkOverlay garantiert KEINE zuverlaessige
     * Stapelreihenfolge fuer solche nativen Fenster bei Eingaben -
     * das native Fenster von bg_area konnte Klicks abfangen, obwohl es
     * optisch "hinter" den Bubbles lag. Genau das war vermutlich der
     * Grund, warum die Bar komplett unklickbar war.
     *
     * Stattdessen jetzt der Standard-GTK-Trick: der Hintergrund wird
     * DIREKT im "draw"-Handler von main_box selbst gezeichnet (VOR dem
     * Default-Handler von GtkBox, der die Kinder zeichnet - das
     * "draw"-Signal ist RUN_LAST, ein normal verbundener Handler laeuft
     * also vor der Default-Klassenimplementierung). main_box ist damit
     * das EINZIGE Widget im Fenster - keine zwei parallelen nativen
     * Fenster mehr, keine Stapel-Mehrdeutigkeit, Klicks funktionieren
     * garantiert normal. */
    GtkWidget *main_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(window), main_box);
    g_signal_connect(main_box, "draw", G_CALLBACK(on_bar_draw), &app);

    GtkWidget *left_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    GtkWidget *center_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    GtkWidget *right_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);

    /* Bar.png hat oben einen sehr hohen weichen Schlagschatten (bis zu
     * top_slice px) - der voll deckende Bereich ist nur ein schmaler
     * Streifen unten. valign=END verankert die Module dort, statt sie
     * mittig ueber die ganze (grosse) Bar-Hoehe zu verteilen. */
    gtk_widget_set_valign(left_box, GTK_ALIGN_END);
    gtk_widget_set_valign(center_box, GTK_ALIGN_END);
    gtk_widget_set_valign(right_box, GTK_ALIGN_END);

    /* Abstand zum Bar-Rand: soll erst nach der Eckenrundung anfangen,
     * siehe Kommentar bei cfg->edge_margin in config_load(). */
    gtk_box_pack_start(GTK_BOX(main_box), left_box, FALSE, FALSE, cfg->edge_margin);
    gtk_box_set_center_widget(GTK_BOX(main_box), center_box);
    gtk_box_pack_end(GTK_BOX(main_box), right_box, FALSE, FALSE, cfg->edge_margin);

    app.mod_left = tb_modules_build(left_box, cfg->modules_left, app.assets, cfg);
    app.mod_center = tb_modules_build(center_box, cfg->modules_center, app.assets, cfg);
    app.mod_right = tb_modules_build(right_box, cfg->modules_right, app.assets, cfg);

    /* WICHTIG: gtk_widget_show_all() muss VOR der Preferred-Size-Abfrage
     * laufen! GtkBox schliesst standardmaessig UNSICHTBARE Kinder von
     * der eigenen Groessenberechnung aus - und vor show_all() ist noch
     * nichts sichtbar (nur die einzelnen Workspace-/Tray-Bubbles hatten
     * ihr eigenes show_all(), die normalen Button-Module nicht). Das war
     * der Grund fuer das geloggte "natural_nat=0": main_box wusste zu
     * dem Zeitpunkt schlicht noch nicht, dass es ueberhaupt sichtbare
     * Kinder hat. Reihenfolge jetzt: erst zeigen, dann fragen, dann bei
     * Bedarf nachtraeglich groesser anfordern (GTK relayoutet das
     * automatisch). */
    gtk_widget_add_events(window, GDK_BUTTON_PRESS_MASK);
    g_signal_connect(window, "button-press-event", G_CALLBACK(on_window_click_probe), NULL);
    g_signal_connect(window, "size-allocate", G_CALLBACK(on_window_size_allocate_probe), NULL);
    g_signal_connect(window, "size-allocate", G_CALLBACK(on_window_input_shape), NULL);

    gtk_widget_show_all(window);

    /* show_all() hat gerade ALLE Kinder sichtbar gemacht, auch die
     * bewusst versteckten Widget-Grid-Seiten (siehe Kommentar bei
     * tb_modules_resync_pages()) - sofort korrigieren, bevor irgendeine
     * Groessen-Anfrage/Zeichnung damit rechnet. */
    tb_modules_resync_pages(app.mod_left);
    tb_modules_resync_pages(app.mod_center);
    tb_modules_resync_pages(app.mod_right);

    /* Kanarienvogel so frueh wie moeglich einplanen - noch vor Tray/
     * Autohide-Setup, damit wir im naechsten Log unabhaengig von beiden
     * sehen, ob die Hauptschleife ueberhaupt am Laufen bleibt. */
    g_timeout_add_seconds(10, canary_heartbeat, NULL);

    gint natural_min = 0, natural_nat = 0;
    gtk_widget_get_preferred_height(main_box, &natural_min, &natural_nat);
    int bar_height = MAX(natural_nat, cfg->height);
    g_bar_filler_px = (g_strcmp0(cfg->position, "top") == 0) ? 0 : (int)ceil(bar_height * AH_FILLER_FRAC);
    gtk_widget_set_size_request(main_box, -1, bar_height + g_bar_filler_px);
    gtk_widget_set_margin_bottom(left_box, g_bar_filler_px);   /* Module bleiben an ihrer Position */
    gtk_widget_set_margin_bottom(center_box, g_bar_filler_px);
    gtk_widget_set_margin_bottom(right_box, g_bar_filler_px);

    g_message("[debug] BUILD=" TB_BUILD_TAG " cfg->height=%d bar_bg.left/right_slice=%d/%d "
              "bubble.min_size=%d bubble.padding=%d "
              "main_box: natural_min=%d natural_nat=%d -> bar_height(gesetzt)=%d",
              cfg->height, cfg->bar_bg.left_slice, cfg->bar_bg.right_slice,
              cfg->bubble.min_size, cfg->bubble.padding, natural_min, natural_nat, bar_height);

    g_message("[startup] Fenster sichtbar nach %.1f ms seit Programmstart.",
              (g_get_monotonic_time() - t_start_us) / 1000.0);

    app.autohide = tb_autohide_start(GTK_WINDOW(window), cfg);

    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    gtk_main();

    tb_autohide_stop(app.autohide);
    tb_modules_free(app.mod_left);
    tb_modules_free(app.mod_center);
    tb_modules_free(app.mod_right);
    bubble_assets_free(app.assets);
    nine_slice_free(app.bar_bg);
    config_free(cfg);
    return EXIT_SUCCESS;
}
