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
#include <gtk-layer-shell/gtk-layer-shell.h>
#include <gtk/gtk.h>
#include <json-glib/json-glib.h>
#include <sys/signalfd.h>
#include <sys/socket.h>
#include <sys/un.h>

/* ───────────────────────── config : Typen/Deklarationen ───────────────────────── */
/* ── Modul-Typen ─────────────────────────────────────────────── */
typedef enum {
    MOD_BUTTON = 0,     /* einfacher Klick-Button (appmenu, shortcuts, ...) */
    MOD_CLOCK,          /* Uhrzeit, per Timer aktualisiert */
    MOD_HYPR_WORKSPACES,/* dynamische Workspace-Pillen + Taskbar-Icons */
    MOD_TRAY,           /* StatusNotifierItem Systemtray */
    MOD_SPACER          /* fester Leerraum zum optischen Gruppieren */
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
} ModuleConfig;

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
    return MOD_BUTTON;
}

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
    g_free(m);
}

void config_free(BarConfig *cfg) {
    if (!cfg) return;
    g_free(cfg->position);
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
    cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_BILINEAR);
    cairo_pattern_set_extend(cairo_get_source(cr), CAIRO_EXTEND_PAD);
    cairo_paint(cr);
    g_object_unref(region);

    cairo_restore(cr);
}

void nine_slice_draw(NineSlice *ns, cairo_t *cr, double w, double h) {
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

void nine_slice_free(NineSlice *ns) {
    if (!ns) return;
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

/* Pinnt die Blase dauerhaft auf die Hover-Optik (z.B. fuer .active
 * Zustaende wie OSK-an oder Hide-Windows-aktiv). Overrides Hover-Handling
 * nicht - beides zusammen ergibt einfach "Ziel=Hover" so oder so. */
void tb_bubble_set_forced_active(TbBubble *b, gboolean active);

void tb_bubble_free(TbBubble *b); /* Widget wird NICHT zerstoert (macht GTK selbst) */


/* ═══════════════════════════ bubble : Implementierung ═══════════════════════════ */
struct TbBubble {
    GtkWidget *event_box;
    GtkWidget *area;

    BubbleAssets *assets;      /* nicht besessen */
    BarConfig    *cfg;         /* nicht besessen */

    GdkPixbuf *icon;           /* besessen, darf NULL sein */
    char      *text;           /* besessen, darf NULL sein */

    /* Hover-/Active-Animation */
    gboolean hover_now;        /* Maus gerade drueber? */
    gboolean forced_active;    /* von aussen gepinnt (z.B. .active) */
    double   t;                /* aktueller Blend 0..1 (0=normal, 1=hover) */
    double   t_from;
    gint64   anim_start_us;
    guint    tick_id;

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
    g_free(a);
}

/* ── Zeichnen ────────────────────────────────────────────────────── */

/* kubisches Ease-in-out fuer die Ueberblendung - fuehlt sich "smooth"
 * an statt linear zu blenden. */
static double ease_in_out_cubic(double x) {
    return x < 0.5 ? 4 * x * x * x : 1 - pow(-2 * x + 2, 3) / 2;
}

static void paint_stretched(cairo_t *cr, GdkPixbuf *pb, double w, double h, double alpha) {
    if (!pb || alpha <= 0.001) return;
    int sw = gdk_pixbuf_get_width(pb);
    int sh = gdk_pixbuf_get_height(pb);
    if (sw <= 0 || sh <= 0) return;

    cairo_save(cr);
    cairo_scale(cr, w / (double)sw, h / (double)sh);
    gdk_cairo_set_source_pixbuf(cr, pb, 0, 0);
    cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_GOOD);
    cairo_paint_with_alpha(cr, alpha);
    cairo_restore(cr);
}

static gboolean on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data) {
    TbBubble *b = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(widget, &alloc);
    double w = alloc.width, h = alloc.height;
    if (w <= 0 || h <= 0) return FALSE;

    double t = ease_in_out_cubic(CLAMP(b->t, 0.0, 1.0));

    /* 1) Hintergrund - Normal- und Hover-Bild werden ueberblendet
     *    (nicht hart geswitcht), das ergibt die "smoothe Blende". */
    paint_stretched(cr, b->assets->bg_normal, w, h, 1.0 - t);
    paint_stretched(cr, b->assets->bg_hover, w, h, t);

    /* 2) Icon/Text - liegt ZWISCHEN Hintergrund und Vordergrund, damit
     *    er wirklich "in" der Blase sitzt statt nur obendrauf. */
    GdkRGBA col;
    col.red   = b->cfg->text_color.red   + (b->cfg->text_color_hover.red   - b->cfg->text_color.red)   * t;
    col.green = b->cfg->text_color.green + (b->cfg->text_color_hover.green - b->cfg->text_color.green) * t;
    col.blue  = b->cfg->text_color.blue  + (b->cfg->text_color_hover.blue  - b->cfg->text_color.blue)  * t;
    col.alpha = 1.0;

    if (b->icon) {
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
        int tw, th;
        pango_layout_get_pixel_size(layout, &tw, &th);
        cairo_save(cr);
        cairo_set_source_rgba(cr, col.red, col.green, col.blue, col.alpha);
        cairo_move_to(cr, (w - tw) / 2.0, (h - th) / 2.0);
        pango_cairo_show_layout(cr, layout);
        cairo_restore(cr);
        g_object_unref(layout);
    }

    /* 3) Vordergrund (Glanzlicht/Kante) - liegt ueber allem und macht
     *    aus Hintergrund+Icon eine "echte" Blase mit Tiefe. */
    paint_stretched(cr, b->assets->fg_normal, w, h, 1.0 - t);
    paint_stretched(cr, b->assets->fg_hover, w, h, t);

    return FALSE;
}

/* ── Animation ───────────────────────────────────────────────────── */

static gboolean anim_tick(GtkWidget *widget, GdkFrameClock *clock, gpointer user_data) {
    TbBubble *b = user_data;
    gint64 now = gdk_frame_clock_get_frame_time(clock);
    double duration_us = MAX(1, b->cfg->bubble.transition_ms) * 1000.0;
    double target = (b->hover_now || b->forced_active) ? 1.0 : 0.0;
    double progress = (now - b->anim_start_us) / duration_us;
    progress = CLAMP(progress, 0.0, 1.0);
    b->t = b->t_from + (target - b->t_from) * progress;

    gtk_widget_queue_draw(widget);

    if (progress >= 1.0) {
        b->tick_id = 0;
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void restart_animation_toward_target(TbBubble *b) {
    double target = (b->hover_now || b->forced_active) ? 1.0 : 0.0;
    if (fabs(b->t - target) < 0.001) return; /* schon da, nichts zu tun */

    b->t_from = b->t;
    GdkFrameClock *clock = gtk_widget_get_frame_clock(b->area);
    b->anim_start_us = clock ? gdk_frame_clock_get_frame_time(clock) : g_get_monotonic_time();
    if (b->tick_id == 0) {
        b->tick_id = gtk_widget_add_tick_callback(b->area, anim_tick, b, NULL);
    }
}

/* ── Events ──────────────────────────────────────────────────────── */

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
    (void)w;
    TbBubble *b = user_data;
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

    b->area = gtk_drawing_area_new();
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

void tb_bubble_set_text(TbBubble *b, const char *text) {
    g_free(b->text);
    b->text = g_strdup(text);
    gtk_widget_queue_draw(b->area);
}

void tb_bubble_set_forced_active(TbBubble *b, gboolean active) {
    if (b->forced_active == active) return;
    b->forced_active = active;
    restart_animation_toward_target(b);
}

void tb_bubble_free(TbBubble *b) {
    if (!b) return;
    /* Defensive Absicherung: falls der Aufrufer (versehentlich) das
     * Widget schon per gtk_widget_destroy() zerstoert hat, BEVOR er
     * tb_bubble_free() aufruft, ist b->area kein gueltiges GtkWidget
     * mehr - gtk_widget_remove_tick_callback() darauf wuerde einen
     * GTK-CRITICAL-Assert ausloesen. Aufrufer sollten IMMER erst
     * tb_bubble_free() und danach gtk_widget_destroy() aufrufen (die
     * Reihenfolge ist an allen Aufrufstellen entsprechend gefixt),
     * aber dieser Check faengt es zusaetzlich ab, falls doch mal
     * jemand die Reihenfolge vertauscht. */
    if (b->tick_id && GTK_IS_WIDGET(b->area))
        gtk_widget_remove_tick_callback(b->area, b->tick_id);
    g_clear_object(&b->icon);
    g_free(b->text);
    g_free(b);
}


/* ───────────────────────── hypr_ipc : Typen/Deklarationen ───────────────────────── */
typedef struct {
    float x, y, w, h;
    float reserved_top, reserved_bottom, reserved_left, reserved_right;
    int id;
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
#define SNW_BUS_NAME "org.freedesktop.StatusNotifierWatcher"
#define SNW_OBJ_PATH "/StatusNotifierWatcher"
#define SNW_IFACE    "org.freedesktop.StatusNotifierWatcher"
#define SNI_IFACE    "org.kde.StatusNotifierItem"

typedef struct {
    TbTray  *owner;
    char    *service;       /* Bus-Name des Tray-Clients */
    char    *object_path;   /* meist "/StatusNotifierItem" */
    GDBusProxy *proxy;      /* org.kde.StatusNotifierItem am Client */
    TbBubble *bubble;
    guint    signal_id;
} TbTrayItem;

struct TbTray {
    GtkWidget    *container;
    BubbleAssets *assets;
    BarConfig    *cfg;

    GDBusConnection *conn;
    char *unique_name;

    gboolean we_are_watcher;
    guint    own_name_id;
    guint    watcher_reg_id;   /* Object-Registrierung, falls wir Watcher sind */
    GDBusNodeInfo *watcher_introspection;

    GDBusProxy *watcher_proxy; /* falls jemand anders Watcher ist */
    guint watcher_signal_sub;

    GPtrArray *items; /* TbTrayItem* */
};

/* ── Introspection-XML fuer den Fallback-Watcher ────────────────────
 * Minimal, aber vollstaendig genug fuer alle gaengigen Tray-Clients
 * (nm-applet, blueman-applet, xwaylandvideobridge, ...). */
static const char *watcher_xml =
"<node>"
"  <interface name='org.freedesktop.StatusNotifierWatcher'>"
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

    GVariant *icon_name_v = proxy_get_prop(it->proxy, "IconName");
    const char *icon_name = icon_name_v ? g_variant_get_string(icon_name_v, NULL) : NULL;

    if (icon_name && *icon_name) {
        GError *err = NULL;
        pb = gtk_icon_theme_load_icon(gtk_icon_theme_get_default(), icon_name,
                                       it->owner->cfg->icon_size,
                                       GTK_ICON_LOOKUP_FORCE_SIZE, &err);
        if (err) g_error_free(err);
    }
    if (!pb) {
        GVariant *pixmap_v = proxy_get_prop(it->proxy, "IconPixmap");
        pb = pixbuf_from_iconpixmap_variant(pixmap_v);
        if (pb) {
            /* auf konfigurierte Icon-Groesse bringen */
            int size = it->owner->cfg->icon_size;
            GdkPixbuf *scaled = gdk_pixbuf_scale_simple(pb, size, size, GDK_INTERP_BILINEAR);
            g_object_unref(pb);
            pb = scaled;
        }
    }
    if (icon_name_v) g_variant_unref(icon_name_v);

    if (pb) {
        /* tb_bubble_set_icon erwartet einen Icon-Theme-Namen, kein
         * direktes Pixbuf - also setzen wir es hier direkt am Widget
         * vorbei ueber das Draw-Icon-Feld. Kleiner Kompromiss: wir
         * kapseln das ueber eine dedizierte Bubble-API. */
        tb_bubble_set_icon_pixbuf(it->bubble, pb); /* siehe bubble.c-Ergaenzung */
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
    tb_bubble_set_tooltip(it->bubble, tip ? tip : (tip_owned ? tip_owned : it->service));
    g_free(tip_owned);
    if (tooltip_v) g_variant_unref(tooltip_v);
    if (title_v) g_variant_unref(title_v);
}

static void on_item_click_left(gpointer user_data) {
    TbTrayItem *it = user_data;
    if (!it->proxy) return;
    g_dbus_proxy_call(it->proxy, "Activate", g_variant_new("(ii)", 0, 0),
                       G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}
static void on_item_click_right(gpointer user_data) {
    TbTrayItem *it = user_data;
    if (!it->proxy) return;
    g_dbus_proxy_call(it->proxy, "ContextMenu", g_variant_new("(ii)", 0, 0),
                       G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}
static void on_item_click_middle(gpointer user_data) {
    TbTrayItem *it = user_data;
    if (!it->proxy) return;
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
    it->bubble = tb_bubble_new(tray->assets, tray->cfg, "application-x-executable", NULL);
    tb_bubble_set_click_handlers(it->bubble, on_item_click_left, on_item_click_right,
                                  on_item_click_middle, it);
    gtk_box_pack_start(GTK_BOX(tray->container), tb_bubble_widget(it->bubble), FALSE, FALSE, 0);
    gtk_widget_show_all(tb_bubble_widget(it->bubble));

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
    if (it->bubble) {
        /* WICHTIG: erst Widget-Zeiger sichern (tb_bubble_free() gibt
         * den TbBubble selbst frei, danach ist it->bubble ungueltig -
         * tb_bubble_widget() darf also nur VORHER aufgerufen werden). */
        GtkWidget *w = tb_bubble_widget(it->bubble);
        tb_bubble_free(it->bubble);
        gtk_widget_destroy(w);
    }
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

    tray->conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);
    if (!tray->conn) {
        g_warning("[tray] Keine Session-D-Bus-Verbindung - Tray bleibt leer.");
        return tray;
    }
    tray->unique_name = g_strdup(g_dbus_connection_get_unique_name(tray->conn));

    if (external_watcher_exists()) {
        connect_to_external_watcher(tray);
    } else {
        tray->own_name_id = g_bus_own_name(G_BUS_TYPE_SESSION, SNW_BUS_NAME,
                                            G_BUS_NAME_OWNER_FLAGS_NONE,
                                            NULL, on_watcher_name_acquired, on_watcher_name_lost,
                                            tray, NULL);
    }

    return tray;
}

void tb_tray_free(TbTray *tray) {
    if (!tray) return;
    for (guint i = 0; i < tray->items->len; i++)
        tray_item_free(g_ptr_array_index(tray->items, i));
    g_ptr_array_free(tray->items, TRUE);

    if (tray->watcher_reg_id && tray->conn)
        g_dbus_connection_unregister_object(tray->conn, tray->watcher_reg_id);
    if (tray->own_name_id) g_bus_unown_name(tray->own_name_id);
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


/* ═══════════════════════════ modules : Implementierung ═══════════════════════════ */
typedef struct {
    ModuleConfig *mc;
    TbBubble *bubble;
    guint exec_timeout_id;
    guint clock_timeout_id;
    gboolean clock_alt_shown;
    BarConfig *cfg;
} ButtonRuntime;

typedef struct {
    ModuleConfig *mc;
    GtkWidget *container;   /* eigene HBox fuer Workspace-Pillen + Fenster-Icons */
    BubbleAssets *assets;
    BarConfig *cfg;
    GPtrArray *bubbles;     /* TbBubble*, wird bei jedem Rebuild neu befuellt */
    guint pending_rebuild_id; /* Debounce - siehe on_hypr_event() */
} WorkspacesRuntime;

typedef struct {
    ModuleConfig *mc;
    GtkWidget *container;
    TbTray *tray;
} TrayRuntime;

typedef struct {
    GtkWidget *widget; /* leerer Platzhalter-Widget fester Breite */
} SpacerRuntime;

typedef enum { RT_BUTTON, RT_WORKSPACES, RT_TRAY, RT_SPACER } RuntimeKind;

typedef struct {
    RuntimeKind kind;
    union {
        ButtonRuntime button;
        WorkspacesRuntime workspaces;
        TrayRuntime tray;
        SpacerRuntime spacer;
    } u;
} ModuleRuntime;

struct TbModules {
    GPtrArray *runtimes; /* ModuleRuntime* */
};

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

static void btn_click_left(gpointer ud) { ButtonRuntime *r = ud; run_shell(r->mc->on_click); }
static void btn_click_right(gpointer ud) { ButtonRuntime *r = ud; run_shell(r->mc->on_click_right); }
static void btn_click_middle(gpointer ud) { ButtonRuntime *r = ud; run_shell(r->mc->on_click_middle); }

static gboolean btn_exec_poll(gpointer user_data) {
    ButtonRuntime *r = user_data;
    gchar *out = NULL;
    gint status = 0;
    GError *err = NULL;
    /* WICHTIG: g_spawn_command_line_sync() geht NICHT ueber eine Shell -
     * es zerlegt die Zeile nur in Woerter und execve()'t argv[0] direkt.
     * exec_cmd darf in der Config aber &&/||/> etc. enthalten (siehe
     * z.B. das osk-Modul) - dafuer brauchen wir wirklich /bin/sh -c. */
    char *argv[] = { "/bin/sh", "-c", r->mc->exec_cmd, NULL };
    if (g_spawn_sync(NULL, argv, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL,
                      &out, NULL, &status, &err) && out) {
        g_strchomp(out);
        if (r->mc->exec_return_json && *out) {
            JsonParser *parser = json_parser_new();
            if (json_parser_load_from_data(parser, out, -1, NULL)) {
                JsonObject *o = json_node_get_object(json_parser_get_root(parser));
                if (o) {
                    if (json_object_has_member(o, "class")) {
                        const char *cls = json_object_get_string_member(o, "class");
                        tb_bubble_set_forced_active(r->bubble, g_strcmp0(cls, "active") == 0);
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
    if (err) g_error_free(err);
    g_free(out);
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
    tb_bubble_set_click_handlers(r->bubble, btn_click_left, clock_click_right, btn_click_middle, r);
    gtk_box_pack_start(GTK_BOX(box), tb_bubble_widget(r->bubble), FALSE, FALSE, 0);

    clock_tick(r);
    r->clock_timeout_id = g_timeout_add_seconds(1, clock_tick, r);
    return rt;
}

/* ── MOD_HYPR_WORKSPACES ────────────────────────────────────────── */

static void ws_click(gpointer ud) {
    int id = GPOINTER_TO_INT(ud);
    char cmd[64];
    g_snprintf(cmd, sizeof(cmd), "workspace %d", id);
    hypr_ipc_dispatch(cmd);
}

static void win_click(gpointer ud) {
    char *addr = ud; /* "0x..." - static Anzeigezeit, siehe rebuild() */
    char cmd[160];
    g_snprintf(cmd, sizeof(cmd), "focuswindow address:%s", addr);
    hypr_ipc_dispatch(cmd);
}

static char *guess_icon_for_class(const char *class_name) {
    if (!class_name || !*class_name) {
        g_message("[icons] leere window class -> Fallback-Icon");
        return g_strdup("application-x-executable");
    }
    char *lower = g_ascii_strdown(class_name, -1);
    GtkIconTheme *theme = gtk_icon_theme_get_default();
    if (gtk_icon_theme_has_icon(theme, lower)) {
        g_message("[icons] class='%s' -> Icon '%s' im Theme gefunden", class_name, lower);
        return lower;
    }
    g_message("[icons] class='%s' -> KEIN passendes Icon im Theme ('%s' nicht gefunden) -> Fallback",
              class_name, lower);
    g_free(lower);
    return g_strdup("application-x-executable");
}

static void workspaces_rebuild(WorkspacesRuntime *wr) {
    /* alte Bubbles entfernen - WICHTIG: erst tb_bubble_free() (entfernt
     * u.a. einen ggf. noch laufenden Hover-Tick-Callback vom Widget,
     * das dafuer noch gueltig sein muss), DANACH erst das Widget
     * zerstoeren. Umgekehrte Reihenfolge loeste bei jedem Rebuild ein
     * "gtk_widget_remove_tick_callback: assertion GTK_IS_WIDGET failed"
     * aus, sobald eine Bubble gerade eine Hover-Animation liefen hatte. */
    for (guint i = 0; i < wr->bubbles->len; i++) {
        TbBubble *b = g_ptr_array_index(wr->bubbles, i);
        GtkWidget *w = tb_bubble_widget(b);
        tb_bubble_free(b);
        gtk_widget_destroy(w);
    }
    g_ptr_array_set_size(wr->bubbles, 0);

    if (!hypr_ipc_available()) {
        g_warning("[workspaces] hypr_ipc_available()==FALSE - Workspace-Modul bleibt leer.");
        return;
    }

    GPtrArray *ws = hypr_ipc_get_workspaces();
    GPtrArray *clients = hypr_ipc_get_clients();
    int active_id = hypr_ipc_get_active_workspace_id();
    g_message("[workspaces] rebuild: %u workspaces, %u clients, active_id=%d",
              ws->len, clients->len, active_id);

    for (guint i = 0; i < ws->len; i++) {
        HyprWorkspace *w = g_ptr_array_index(ws, i);
        char num[16];
        g_snprintf(num, sizeof(num), "%d", w->id);

        TbBubble *b = tb_bubble_new(wr->assets, wr->cfg, NULL, num);
        tb_bubble_set_forced_active(b, w->id == active_id);
        tb_bubble_set_click_handlers(b, ws_click, NULL, NULL, GINT_TO_POINTER(w->id));
        gtk_box_pack_start(GTK_BOX(wr->container), tb_bubble_widget(b), FALSE, FALSE, 0);
        gtk_widget_show_all(tb_bubble_widget(b));
        g_ptr_array_add(wr->bubbles, b);

        for (guint c = 0; c < clients->len; c++) {
            HyprClient *cl = g_ptr_array_index(clients, c);
            if (cl->minimized || cl->workspace_id != w->id) continue;

            char *icon = guess_icon_for_class(cl->class_name);
            TbBubble *wb = tb_bubble_new(wr->assets, wr->cfg, icon, NULL);
            g_free(icon);
            tb_bubble_set_tooltip(wb, cl->title);
            /* address wird an das Bubble-"user_data" gehaengt und lebt
             * so lange wie die Bubble selbst - g_strdup + Free beim
             * naechsten Rebuild ueber ein Quark am Widget. */
            char *addr_copy = g_strdup(cl->address);
            g_object_set_data_full(G_OBJECT(tb_bubble_widget(wb)), "tb-win-addr",
                                    addr_copy, g_free);
            tb_bubble_set_click_handlers(wb, win_click, NULL, NULL, addr_copy);
            gtk_box_pack_start(GTK_BOX(wr->container), tb_bubble_widget(wb), FALSE, FALSE, 0);
            gtk_widget_show_all(tb_bubble_widget(wb));
            g_ptr_array_add(wr->bubbles, wb);
        }
    }

    hypr_ipc_free_workspaces(ws);
    hypr_ipc_free_clients(clients);
}

/* Ein einzelner globaler Event-Handler reicht (i.d.R. genau ein
 * Workspace-Modul pro Bar) - haelt die Liste der interessierten
 * WorkspacesRuntime-Instanzen und rebuilt bei relevanten Events. */
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

    wr->container = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_box_pack_start(GTK_BOX(box), wr->container, FALSE, FALSE, 0);
    gtk_widget_show(wr->container);

    if (!g_ws_runtimes) g_ws_runtimes = g_ptr_array_new();
    g_ptr_array_add(g_ws_runtimes, wr);

    workspaces_rebuild(wr);

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
            case MOD_BUTTON:
            default: rt = build_button(mc, box, assets, cfg); break;
        }
        if (rt) g_ptr_array_add(m->runtimes, rt);
    }
    return m;
}

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

#define FAST_POLL_MS 20
#define MID_POLL_MS  50
#define SLOW_POLL_MS 120

struct TbAutohide {
    GtkWindow *window;
    BarConfig *cfg;

    gboolean visible;
    gboolean locked;
    gboolean touch_override_active;
    gint64   touch_override_until_us;

    /* Slide-Animation */
    double   progress;      /* 0 = versteckt, 1 = sichtbar */
    double   progress_from;
    gint64   anim_start_us;
    guint    tick_id;

    guint    poll_source_id;

    HyprMonitor *monitors;
    int monitors_count;
    int refresh_counter;

    int  signal_fd;         /* signalfd() fuer SIGRTMIN/SIGRTMIN+1 */
    guint signal_watch_id;  /* GIOChannel-Watch auf signal_fd */

    gint64 last_debug_log_us; /* Drosselung fuer die Diagnose-Ausgabe unten */
};

static void write_pid_file(void) {
    FILE *f = fopen(PID_FILE, "w");
    if (!f) return;
    fprintf(f, "%d\n", getpid());
    fclose(f);
}

static double ah_ease_in_out_cubic(double x) {
    return x < 0.5 ? 4 * x * x * x : 1 - pow(-2 * x + 2, 3) / 2;
}

/* ── Slide-Animation ─────────────────────────────────────────────── */

static gboolean ah_anim_tick(GtkWidget *widget, GdkFrameClock *clock, gpointer user_data) {
    TbAutohide *ah = user_data;
    int height = gtk_widget_get_allocated_height(widget);
    if (height <= 1) height = ah->cfg->height;

    gint64 now = gdk_frame_clock_get_frame_time(clock);
    double duration_us = MAX(1, ah->cfg->slide_ms) * 1000.0;
    double target = ah->visible ? 1.0 : 0.0;
    double raw_progress = (now - ah->anim_start_us) / duration_us;
    raw_progress = CLAMP(raw_progress, 0.0, 1.0);
    ah->progress = ah->progress_from + (target - ah->progress_from) * raw_progress;

    double eased = ah_ease_in_out_cubic(ah->progress);
    int margin = (int)round(-height + eased * height); /* -height (weg) .. 0 (sichtbar) */

    if (g_strcmp0(ah->cfg->position, "top") == 0)
        gtk_layer_set_margin(GTK_WINDOW(widget), GTK_LAYER_SHELL_EDGE_TOP, margin);
    else
        gtk_layer_set_margin(GTK_WINDOW(widget), GTK_LAYER_SHELL_EDGE_BOTTOM, margin);

    if (raw_progress >= 1.0) {
        ah->tick_id = 0;
        if (ah->visible)
            g_message("[autohide] SHOW-Animation fertig (margin=0, sichtbar).");
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void ah_start_slide(TbAutohide *ah) {
    ah->progress_from = ah->progress;
    GdkFrameClock *clock = gtk_widget_get_frame_clock(GTK_WIDGET(ah->window));
    ah->anim_start_us = clock ? gdk_frame_clock_get_frame_time(clock) : g_get_monotonic_time();
    if (ah->tick_id == 0)
        ah->tick_id = gtk_widget_add_tick_callback(GTK_WIDGET(ah->window), ah_anim_tick, ah, NULL);
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

    /* Heartbeat: beweist, dass die Polling-Schleife ueberhaupt laeuft -
     * unabhaengig davon, ob Hyprland-IPC verfuegbar ist. Erste 5 Aufrufe
     * immer, danach hoechstens 1x/Sekunde (wie der Cursor-Log unten). */
    static int poll_call_count = 0;
    static gint64 last_heartbeat_us = 0;
    gint64 hb_now = g_get_monotonic_time();
    if (poll_call_count++ < 5 || hb_now - last_heartbeat_us >= 1000000) {
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
        if (hypr_ipc_get_cursor_pos(&cx, &cy)) {
            float dist = get_dist_to_edge(ah, cx, cy, bottom_edge);
            int fast_zone = ah->cfg->hide_px * 2;

            /* Diagnose, hoechstens 1x/Sekunde - hilft zu sehen, ob
             * Cursor-Position/Distanz ueberhaupt sinnvoll ankommen. */
            gint64 now = g_get_monotonic_time();
            if (now - ah->last_debug_log_us >= 1000000) {
                ah->last_debug_log_us = now;
                HyprMonitor *m0 = ah->monitors_count > 0 ? &ah->monitors[0] : NULL;
                g_message("[autohide] cursor=(%d,%d) dist=%.1f visible=%d trigger_px=%d hide_px=%d "
                          "mon0[y=%.0f h=%.0f reservedT=%.0f reservedB=%.0f]",
                           cx, cy, dist, ah->visible, ah->cfg->trigger_px, ah->cfg->hide_px,
                           m0 ? m0->y : -1, m0 ? m0->h : -1,
                           m0 ? m0->reserved_top : -1, m0 ? m0->reserved_bottom : -1);
            }

            if (dist <= ah->cfg->trigger_px && !ah->visible) {
                do_show(ah);
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

static void handle_touch_signal(TbAutohide *ah) {
    if (!ah->visible) do_show(ah);
    ah->touch_override_active = TRUE;
    ah->touch_override_until_us = g_get_monotonic_time() + (gint64)TOUCH_TIMEOUT_SEC * 1000000;
    g_message("[autohide] SIGRTMIN empfangen - Bar wird kurz gezeigt.");
}

static void handle_lock_signal(TbAutohide *ah) {
    ah->locked = !ah->locked;
    g_message("[autohide] SIGRTMIN+1 empfangen - locked=%d.", ah->locked);
    if (ah->locked) {
        do_hide(ah);
        ah->touch_override_active = FALSE;
        g_spawn_command_line_async(
            "notify-send -t 1200 'TrafkTuxBar' 'Autohide gesperrt'", NULL);
    } else {
        g_spawn_command_line_async(
            "notify-send -t 1200 'TrafkTuxBar' 'Autohide entsperrt'", NULL);
    }
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
 * signalfd()). */
static gboolean block_realtime_signals_early(void) {
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

TbAutohide *tb_autohide_start(GtkWindow *window, BarConfig *cfg) {
    TbAutohide *ah = g_new0(TbAutohide, 1);
    ah->window = window;
    ah->cfg = cfg;
    ah->visible = TRUE;   /* Start sichtbar, dann uebernimmt das Polling */
    ah->progress = 1.0;
    ah->signal_fd = -1;

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

    return ah;
}

void tb_autohide_stop(TbAutohide *ah) {
    if (!ah) return;
    if (ah->poll_source_id) g_source_remove(ah->poll_source_id);
    if (ah->tick_id) gtk_widget_remove_tick_callback(GTK_WIDGET(ah->window), ah->tick_id);
    if (ah->signal_watch_id) g_source_remove(ah->signal_watch_id);
    g_free(ah->monitors);
    unlink(PID_FILE);
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
    nine_slice_draw(app->bar_bg, cr, alloc.width, alloc.height);
    return FALSE; /* Kinder (die Module) werden von GTK danach normal gezeichnet */
}

static void apply_layer_shell(GtkWindow *window, BarConfig *cfg) {
    gtk_layer_init_for_window(window);
    gtk_layer_set_layer(window, GTK_LAYER_SHELL_LAYER_OVERLAY);
    gtk_layer_set_namespace(window, "trafktuxbar");

    gboolean top = g_strcmp0(cfg->position, "top") == 0;
    gtk_layer_set_anchor(window, GTK_LAYER_SHELL_EDGE_LEFT, TRUE);
    gtk_layer_set_anchor(window, GTK_LAYER_SHELL_EDGE_RIGHT, TRUE);
    gtk_layer_set_anchor(window, top ? GTK_LAYER_SHELL_EDGE_TOP : GTK_LAYER_SHELL_EDGE_BOTTOM, TRUE);

    /* exclusive_zone: reserviert echten Platz auf dem Bildschirm.
     * Fuer eine Autohide-Bar i.d.R. FALSE (overlay), genau wie in der
     * alten waybar-Config ("exclusive": false, "mode": "hide"). */
    gtk_layer_set_exclusive_zone(window, cfg->exclusive_zone ? cfg->height : -1);

    /* Start unsichtbar unterhalb/oberhalb des Bildschirmrands -
     * tb_autohide_start() faehrt sie beim ersten Poll sanft ein. */
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
#define TB_BUILD_TAG "2026-08-debug-2-uniform-corners"

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

int main(int argc, char **argv) {
    g_message("[debug] TrafkTuxBar BUILD=" TB_BUILD_TAG " startet (PID %d)", getpid());
    gint64 t_start_us = g_get_monotonic_time();
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

    gtk_box_pack_start(GTK_BOX(main_box), left_box, FALSE, FALSE, 15);
    gtk_box_set_center_widget(GTK_BOX(main_box), center_box);
    gtk_box_pack_end(GTK_BOX(main_box), right_box, FALSE, FALSE, 15);

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

    gtk_widget_show_all(window);

    gint natural_min = 0, natural_nat = 0;
    gtk_widget_get_preferred_height(main_box, &natural_min, &natural_nat);
    int bar_height = MAX(natural_nat, cfg->height);
    gtk_widget_set_size_request(main_box, -1, bar_height);

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
