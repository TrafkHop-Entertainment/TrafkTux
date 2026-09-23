#!/usr/bin/env python3
"""
WidgetsDaemon.py — TrafkTux Waybar Widget System (Daemon)
Invocation: python3 WidgetsDaemon.py
Controlled via client: WidgetsClient.py <widget>
Widgets: volume | network | bluetooth | brightness | akku | clock | settings | security
"""

import gi, sys, os, re, signal, subprocess, json, threading, time, calendar, shutil, traceback
import random, math, glob, stat
from datetime import datetime, date
from pathlib import Path

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf, Gio

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
    HAS_LS = True
except Exception:
    HAS_LS = False

try:
    import cairo
    HAS_CAIRO = True
except ImportError:
    HAS_CAIRO = False

# ════════════════════════════════════════════════════════════
#  Paths & Colors
# ════════════════════════════════════════════════════════════
HOME   = os.path.expanduser("~")
# TrafkBubble2.png ersetzt das alte bubble-normal.png als Hintergrund-
# Blase; TrafkBubble1.png ist NEU eine Overlay-Ebene, die über ALLEM
# liegt (Hintergrund + Pünktchen + eigentlicher Widget-Inhalt), siehe
# _paint_bubble_overlay() weiter unten - macht den Eindruck, als wäre
# der ganze Widget-Inhalt wirklich INNERHALB der Blase (Glanzlichter/
# Rand-Reflexion o.ä. je nachdem, was das Bild selbst zeigt).
BUBBLE_PATH  = "/tmp/TrafkBubble2.png"
OVERLAY_PATH = "/tmp/TrafkBubble1.png"
B_NORM = f"file://{BUBBLE_PATH}"
B_SEL  = "file:///tmp/bubble-selected.png"
WALLPAPER_SCRIPT = f"{HOME}/.config/hypr/random_wallpaper.sh"
# Kandidaten-Dateinamen für das Wallpaper-Shuffle-Script - der oben
# hartkodierte Name (random_wallpaper.sh) passte nie zum tatsächlich
# auf der Platte liegenden Skript (dort z.B. Wallpapers.sh), daher fand
# os.path.isfile() das Script nie und der Reroll-Button im Brightness-
# Tab blieb permanent deaktiviert. Statt wieder nur einen einzelnen
# fixen Namen zu raten, werden hier alle gängigen Varianten (Groß-/
# Kleinschreibung, mit/ohne Unterstrich) im selben Ordner geprüft und
# der erste tatsächlich existierende genommen.
_WALLPAPER_SCRIPT_CANDIDATES = [
    "random_wallpaper.sh", "Random_Wallpaper.sh",
    "Wallpapers.sh", "wallpapers.sh",
    "wallpaper.sh", "Wallpaper.sh",
]

def _resolve_wallpaper_script() -> str:
    hypr_dir = f"{HOME}/.config/hypr"
    for name in _WALLPAPER_SCRIPT_CANDIDATES:
        candidate = f"{hypr_dir}/{name}"
        if os.path.isfile(candidate):
            return candidate
    return WALLPAPER_SCRIPT  # Fallback nur für die Tooltip-Fehlermeldung

WEATHER_CONF     = Path(HOME) / ".config" / "wb-daemon" / "weather.json"
_DEFAULT_WEATHER_LOC = {"lat": 47.8121, "lon": 16.2506, "name": "Wiener Neustadt"}
GOLD   = "#fff495"   # "ausgewählter" Text, Pünktchen, Slider
GOLD_H = "#c8b800"
GOLD_DIM = "rgba(255,244,149,0.45)"
CRIMSON = "#dc143c"   # Kalender-Termin-Punkt - eigene Farbe, damit er sich
                      # klar von "ausgewählt/heute" (GOLD) unterscheidet
TEXT_NORMAL = "#f6f3d5"   # normaler/nicht ausgewählter Text

def _hex_to_rgb01(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

_GOLD_RGB = _hex_to_rgb01(GOLD)  # für die frei fliegenden Cairo-Pünktchen

# ════════════════════════════════════════════════════════════
#  CSS
# ════════════════════════════════════════════════════════════
def _css() -> bytes:
    return f"""
/* JEDES Fenster (volume, network, bluetooth, brightness, akku, clock,
   settings - wirklich alle) bekommt GENAU EINE große Blase als
   Hintergrund. WICHTIG: window ist "app-paintable", damit unser
   eigener Cairo-"draw"-Handler (_draw_window) die transparente Fläche
   + die Blase + die Wachs-Animation + die Pünktchen zeichnen darf -
   GTK unterdrückt dabei automatisch das normale CSS-Hintergrundbild
   für Fenster, darum wird die Blase NICHT hier über CSS geladen,
   sondern in _draw_window() direkt per GdkPixbuf/Cairo gemalt (siehe
   BUBBLE_PATH). Diese Regel hier ist nur der Fallback/die Doku. */
window {{
    background-color: transparent;
    border: none;
}}

/* GTK-Themes setzen auf "button" oft eine eigene Mindesthöhe für
   Touch-Bedienbarkeit (z.B. 34px) - die hat bisher JEDEN button.bubble
   im Programm unsichtbar aufgebläht, unabhängig vom eigenen
   padding/margin. War der eigentliche Grund für den riesigen Abstand
   zwischen Sektions-Buttons (z.B. "SCREEN: 100%") und dem Slider
   direkt darunter - kein Layout-/Spacing-Problem, sondern schlicht ein
   viel zu hoher, unsichtbarer Button selbst. Global zurückgesetzt,
   damit jeder Button im Programm wirklich auf seinen Text schrumpft.*/
button {{
    min-height: 0;
}}

/* Basis für JEDEN reinen, NICHT klickbaren Text/Icon (Titel,
   Section-Header, normale Listenzeilen, Slider-Icon-Label, Captions):
   KEIN eigener Hintergrund, KEIN Rand - der Text sitzt direkt auf der
   großen Fenster-Blase, standardmäßig in GOLD (#fff495). */
.bubble {{
    background: none;
    color: {GOLD};
    border: none;
    box-shadow: none;
    font-family: "JetBrainsMono Nerd Font", "Noto Sans";
    font-size: 13px;
}}

.bubble.title {{
    padding: 8px 22px;
    margin: 4px 0px;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 1px;
}}

/* Nur fürs Settings-Hauptmenü (Hub-Liste): der große Abstand zwischen
   Titel und der ersten Zeile fiel im Vergleich zu den nur 1px
   Abständen zwischen den Kategorie-Zeilen stark auf. Höhere
   Spezifität (3 statt 2 Klassen) überschreibt gezielt NUR hier
   Padding/Margin, ohne .bubble.title anderswo (jedes andere Fenster
   nutzt btitle() genauso) zu verändern. */
.bubble.title.compact-title {{
    padding: 2px 22px;
    margin: 0px 0px;
}}

/* NUR für reine Ziffern-/Uhrzeit-Anzeigen (z.B. die Uhr im
   Wetter-Widget) - manche gepatchten Builds von "JetBrainsMono Nerd
   Font" rendern einzelne ASCII-Zeichen wie ':' fehlerhaft (sichtbar
   z.B. als 'r' statt ':' bei "14:32"), vermutlich ein Patcher-Bug in
   der cmap-Tabelle der Font-Datei selbst - kein Zeichenkette-Bug im
   Python-Code (n.strftime("%H:%M") liefert garantiert einen echten
   Doppelpunkt). Da für reine Ziffern/Doppelpunkt ohnehin keine
   Nerd-Font-Icon-Glyphen gebraucht werden, hier einfach die Nerd-Font
   ganz umgehen und direkt eine normale Systemschrift nehmen -
   umgeht den Font-Bug zuverlässig, unabhängig von der genauen Ursache.
   KEIN font-variant-numeric mehr hier drin - das ist zwar echtes CSS,
   aber GTKs CSS-Provider (kennt nur eine Teilmenge von CSS) akzeptiert
   die Property nicht und wirft dafür einen GError. Genau DAS war der
   eigentliche Absturz: load_css() ist an dieser einen ungültigen
   Property gescheitert, main() kam nie durch, der Daemon hat nie sein
   Socket unter /tmp/wb-daemon.sock angelegt - deshalb "Datei nicht
   gefunden" bei jedem Waybar-Klick, ganz unabhängig vom Rest. */
.bubble.clock-digits {{
    font-family: "Noto Sans", sans-serif;
}}

.bubble.section {{
    padding: 3px 16px;
    margin: 6px 0px 1px 0px;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
    min-height: 0;
}}

.bubble.item {{
    padding: 5px 16px;
    margin: 1px 0px;
    font-size: 13px;
}}

/* Kalender-Tages-/Wochentags-Zellen: eigene, knappe Klasse statt
   .bubble.item - dessen 16px seitliches Padding war für Settings-
   Zeilen gedacht und hat hier JEDE Zelle weit über die eigentlich
   gewünschte CELL-Breite hinaus aufgeblasen (unnötig viel Weißraum,
   schlechter lesbar). */
.bubble.cal-cell {{
    padding: 2px 0px;
    margin: 0px;
    font-size: 13px;
}}

.icon-lg  {{ font-size: 22px; }}
.icon-xl  {{ font-size: 34px; }}
.value-md {{ font-size: 15px; font-weight: bold; }}
.value-lg {{ font-size: 26px; font-weight: bold; }}
.temp-xl  {{ font-size: 26px; font-weight: bold; }}
.caption  {{ font-size: 11px; }}

/* Der kleine Punkt "•" an Kalendertagen mit Termin - eigene Klasse,
   damit er sich (unabhängig vom sonstigen Text) farblich als
   "ausgewählt/markiert" abhebt, ganz ohne Rand/Ring drumherum. */
/* Kalendertage MIT Termin: die Tageszahl selbst glowt (gleicher Stil
   wie .active für "heute"), nur in Karminrot statt Gold - KEIN
   separater Punkt mehr, siehe Chat. */
.has-event-glow {{
    color: {CRIMSON};
    text-shadow: 0 0 4px {CRIMSON}, 0 0 10px {CRIMSON};
}}

/* Slider-Wrapper - reiner Text/Icon-Layoutcontainer, kein eigener
   Hintergrund, kein Rand. Die "gelben Balken mit Knopf" selbst kommen
   weiter unten über die GTK "scale"-Nodes (trough/highlight/slider) -
   das sind schlanke, bewusst sichtbare Bedienelemente, keine
   halbtransparenten Rechteck-Container. */
.bubble.slider {{
    background: none;
    padding: 0px 14px;
    margin: 1px 0px;
}}

/* Echte Klick-Ziele (Buttons, Toggles, Kalendertage, Dropdowns, ...):
   GAR KEIN Rand, GAR KEIN Hintergrund - reiner Text auf der großen
   Blase. Klickbares startet gedimmt (TEXT_NORMAL) und wird GOLD
   sobald ausgewählt/aktiv/hover - so lässt sich Klickbares von reinem
   Info-Text unterscheiden, ganz ohne Box drumherum. */
button.bubble, .bubble.dropdown {{
    background: none;
    color: {TEXT_NORMAL};
    border: none;
    box-shadow: none;
    padding: 5px 16px;
    margin: 1px 0px;
    min-height: 0;
}}
button.bubble:hover, button.bubble:active, button.bubble:checked,
.bubble.dropdown:hover, .bubble.dropdown:focus {{
    color: {GOLD};
    text-shadow: 0 0 3px {GOLD};
}}
button.bubble:focus, .bubble.dropdown:focus {{
    box-shadow: none;
    outline: none;
}}
button.bubble.active {{
    color: {GOLD};
    font-weight: bold;
    text-shadow: 0 0 4px {GOLD}, 0 0 10px {GOLD};
}}
button.bubble.title {{
    padding: 8px 22px;
    font-size: 17px;
    font-weight: bold;
}}

scale {{
    min-height: 15px;
}}
scale trough {{
    background-color: rgba(255,244,149,0.15);
    border-radius: 4px;
    min-height: 5px;
    min-width: 5px;
    border: none;
}}
scale highlight {{
    background-color: {GOLD};
    border-radius: 4px;
}}
scale slider {{
    background-color: {GOLD_H};
    min-width: 13px; min-height: 13px;
    border-radius: 7px;
    margin: -4px 0;
    border: none;
    box-shadow: none;
}}
scale slider:hover {{ background-color: {GOLD}; }}

separator {{
    background-color: rgba(255,244,149,0.2);
    min-height: 1px;
    margin: 5px 8px;
}}

/* Trennstrich direkt unter einer Tab-Leiste (Media/Devices/Apps,
   Networks/Speed Test, Battery/System, Weather/Calendar, Settings-
   Hub) - bewusst kräftiger als der normale separator{{}} oben, damit
   der Wechsel von Tabs zu Inhalt klar sichtbar ist. */
separator.tab-divider {{
    background-color: rgba(255,244,149,0.75);
    min-height: 2px;
    margin: 4px 10px 8px 10px;
}}

scrollbar {{ background-color: transparent; min-width: 3px; }}
scrollbar slider {{
    background-color: rgba(255,244,149,0.3);
    border-radius: 2px;
    min-width: 3px;
    min-height: 20px;
}}
""".encode()

# ════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════
def run(cmd: list, timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout).stdout.strip()
    except Exception:
        return ""

def run_ec(cmd: list, timeout: int = 5) -> tuple[str, str, int]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip(), p.stderr.strip(), p.returncode
    except Exception as e:
        return "", str(e), 1

def run_bg(cmd: list) -> None:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass

# ════════════════════════════════════════════════════════════
#  Systemsounds (SoundCenter.sh)
# ════════════════════════════════════════════════════════════
# Alle Sound-Events laufen über das zentrale SoundCenter.sh (siehe
# ~/.config/hypr/SoundCenter.sh), das selbst prüft, ob Sounds gerade
# aktiviert sind - hier also einfach immer fire-and-forget aufrufen.
# (SoundCenter.sh ist nur noch ein Trampolin ins kompilierte
# SoundControl-Binary, siehe dessen eigenes Repo - Aufrufkonvention hier
# unverändert: "bash <pfad> <event>" bzw. "--status"/"--enable"/"--disable".)
SOUNDCTL = os.path.join(HOME, ".config", "hypr", "SoundCenter.sh")

# Muss mit EVENT_NAMES[] in SoundDaemon.c übereinstimmen (siehe dessen
# eigener Kommentar dort für die Herleitung jedes einzelnen Namens) -
# einzige Stelle hier, die bei einer Event-Änderung mit angepasst werden
# muss, damit die Settings-Liste unten (SOUND EVENTS) synchron bleibt.
SOUND_EVENTS = [
    "Click", "RightClick", "MiddleClick",
    "Open", "Close", "FocusChange",
    "Pip", "Minimize", "LayoutSwitch", "Dunst",
    "Error",
]

def _play_sound(event: str) -> None:
    run_bg(["bash", SOUNDCTL, event])

def _sounds_enabled() -> bool:
    return run(["bash", SOUNDCTL, "--status"]) == "on"

def _set_sounds_enabled(enabled: bool) -> None:
    run_bg(["bash", SOUNDCTL, "--enable" if enabled else "--disable"])

def _event_sound_enabled(event: str) -> bool:
    return run(["bash", SOUNDCTL, "--status", event]) == "on"

def _set_event_sound_enabled(event: str, enabled: bool) -> None:
    run_bg(["bash", SOUNDCTL, "--enable" if enabled else "--disable", event])

def jrun(cmd: list) -> object:
    raw = run(cmd)
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None

import concurrent.futures as _cf
_THREAD_POOL = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="wb-worker")

def in_thread(fn, *args):
    # Wiederverwendeter, kleiner Thread-Pool statt für JEDEN einzelnen
    # Timer-Tick (System-Monitor alle 2s, Akku alle 10s, Medien alle
    # 1.5s, Uhr jede Sekunde, ...) einen KOMPLETT NEUEN OS-Thread zu
    # erzeugen. Laut strace-Diagnose (997k clock_gettime-Aufrufe,
    # futex als größter Zeitfresser = Thread-/GIL-Synchronisations-
    # Konkurrenz) war genau diese Thread-Erzeugungs-Churn unter
    # CPython (hier 3.14) bei mehreren gleichzeitig offenen Widgets
    # teuer genug, um einen Kern dauerhaft auszulasten. max_workers=4
    # reicht für dieses Projekt bei weitem (die Arbeit pro Tick ist
    # kurz: ein paar Subprozess-Aufrufe/sysfs-Reads), verhindert aber
    # die Erzeugungs-/Abbau-Kosten von hunderten kurzlebigen Threads.
    _THREAD_POOL.submit(fn, *args)

def load_css():
    p = Gtk.CssProvider()
    p.load_from_data(_css())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), p,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

# ════════════════════════════════════════════════════════════
#  Window Management
# ════════════════════════════════════════════════════════════
WIDGET = None
_open: dict[str, Gtk.Window] = {}
_timers_by_win: dict[Gtk.Window, list] = {}
_cleanup_by_win: dict[Gtk.Window, object] = {}
_current_win: list = [None]

# ────────────────────────────────────────────────────────────
#  Animation state (Pünktchen + Popup-Grow + Crossfade)
# ────────────────────────────────────────────────────────────
# Pro Fenster: Startzeit (für die frei fliegenden Gold-Pünktchen),
# eine Liste der Pünktchen selbst, sowie der aktuelle Popup-Fortschritt
# (0..1, 1 = fertig reingewachsen). Alles rein additiv zum bestehenden
# Cairo-"draw"-Handler des Fensters - blockiert dadurch NIE Mausklicks,
# weil es nur Zeichnen ist, kein eigenes interaktives Widget.
_anim: dict = {}

_POPUP_MS   = 350   # Dauer der Scale/Bounce-Animation - GLEICHE Dauer
                     # für Öffnen UND Schließen, da Schließen exakt die
                     # umgekehrte Animation ist (siehe _draw_window()).
_PARTICLE_N = 15     # Anzahl der frei fliegenden Pünktchen pro Blase
_TICK_MS    = 33     # ~30fps für die Pünktchen-Ambient-Animation

# ────────────────────────────────────────────────────────────
#  Die große Blase selbst (BUBBLE_PATH) - wird EINMAL geladen und dann
#  als Cairo-Surface gecacht. Gemalt wird sie manuell in _draw_window(),
#  NICHT über CSS "background-image", weil GtkWindow mit
#  app-paintable=True die normale CSS-Hintergrundzeichnung für sich
#  selbst unterdrückt (das war der Grund, warum das Bild zuvor gar
#  nicht angezeigt wurde).
# ────────────────────────────────────────────────────────────
_bubble_surface = None
_bubble_load_failed = False

def _get_bubble_surface():
    global _bubble_surface, _bubble_load_failed
    if _bubble_surface is not None or _bubble_load_failed:
        return _bubble_surface
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(BUBBLE_PATH)
        surf = Gdk.cairo_surface_create_from_pixbuf(pixbuf, 1, None)
        _bubble_surface = surf
    except Exception as e:
        _bubble_load_failed = True
        print(f"⚠ Blasenbild konnte nicht geladen werden ({BUBBLE_PATH}): {e}", file=sys.stderr)
    return _bubble_surface

_overlay_surface = None
_overlay_load_failed = False

def _get_overlay_surface():
    """Wie _get_bubble_surface(), nur für TrafkBubble1.png - die Ebene,
    die ganz am Ende über ALLES drüber gemalt wird (siehe
    _paint_bubble_overlay() + deren Aufruf in _draw_window())."""
    global _overlay_surface, _overlay_load_failed
    if _overlay_surface is not None or _overlay_load_failed:
        return _overlay_surface
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(OVERLAY_PATH)
        surf = Gdk.cairo_surface_create_from_pixbuf(pixbuf, 1, None)
        _overlay_surface = surf
    except Exception as e:
        _overlay_load_failed = True
        print(f"⚠ Overlay-Bild konnte nicht geladen werden ({OVERLAY_PATH}): {e}", file=sys.stderr)
    return _overlay_surface

def _paint_bubble_bg(ctx, w: int, h: int) -> None:
    """Malt die große Blase so, dass sie exakt die Fenstergröße w×h
    ausfüllt - läuft im bereits (per Popup-Animation) transformierten
    Koordinatensystem von _draw_window(), wächst also automatisch mit."""
    surf = _get_bubble_surface()
    if surf is None:
        return
    sw, sh = surf.get_width(), surf.get_height()
    if sw <= 0 or sh <= 0:
        return
    ctx.save()
    ctx.scale(w / sw, h / sh)
    ctx.set_source_surface(surf, 0, 0)
    ctx.paint()
    ctx.restore()

def _paint_bubble_overlay(ctx, w: int, h: int) -> None:
    """Malt TrafkBubble1.png GENAUSO wie _paint_bubble_bg() (identisches
    Format/Größe, siehe dort), aber als eigener Aufruf GANZ AM ENDE von
    _draw_window() - also über dem Hintergrund, den Pünktchen UND dem
    eigentlichen Widget-Inhalt (Buttons/Text). Dadurch wirkt alles
    andere wie INNERHALB der Blase liegend statt nur davor."""
    surf = _get_overlay_surface()
    if surf is None:
        return
    sw, sh = surf.get_width(), surf.get_height()
    if sw <= 0 or sh <= 0:
        return
    ctx.save()
    ctx.scale(w / sw, h / sh)
    ctx.set_source_surface(surf, 0, 0)
    ctx.paint()
    ctx.restore()

def _monitor_geometry_for_win(win: Gtk.Window):
    """Ermittelt die Geometrie (in logischen Pixeln) des Monitors, auf
    dem dieses Fenster erscheint - Grundlage für _clamp_window_to_screen()
    weiter unten. Läuft bewusst über Gdk.Display/Monitor statt
    win.get_window(): beim ERSTEN Öffnen (aus toggle_widget(), noch vor
    win.show_all()) ist das Fenster noch nicht realisiert, hat also noch
    kein Gdk.Window - display.get_monitor_at_window() würde dann
    scheitern. Fallback-Kette: Monitor des (falls vorhandenen) Gdk.Window
    -> "primärer" Monitor -> erster bekannter Monitor."""
    display = win.get_display()
    if display is None:
        return None
    monitor = None
    gdk_win = win.get_window()
    if gdk_win is not None:
        try:
            monitor = display.get_monitor_at_window(gdk_win)
        except Exception:
            monitor = None
    if monitor is None:
        try:
            monitor = display.get_primary_monitor()
        except Exception:
            monitor = None
    if monitor is None:
        try:
            if display.get_n_monitors() > 0:
                monitor = display.get_monitor(0)
        except Exception:
            monitor = None
    if monitor is None:
        return None
    try:
        return monitor.get_geometry()
    except Exception:
        return None

# Müssen zu den GtkLayerShell-Margins in make_win() passen (dort:
# BOTTOM=85, RIGHT=85) - sonst würde hier ein Fenster als "passt noch"
# durchgehen, das durch den Anchor-Offset trotzdem über den Bildschirm
# hinausragt.
# Müssen zu den GtkLayerShell-Margins in make_win() passen (dort:
# BOTTOM=65, RIGHT=35) - sonst würde hier ein Fenster als "passt noch"
# durchgehen, das durch den Anchor-Offset trotzdem über den Bildschirm
# hinausragt.
_SCREEN_MARGIN_BOTTOM = 65
_SCREEN_MARGIN_RIGHT  = 35
_SCREEN_EDGE_BUFFER   = 24   # Sicherheitsabstand zum oberen/linken Rand,
                              # damit auch ein voll ausgewickeltes
                              # Fenster nicht bis an Kante 0 heranreicht

def _clamp_window_to_screen(win: Gtk.Window) -> None:
    """Bugfix für "widgets can go over the screen if scale is too high"
    (siehe README, Known Bugs): bisher wurde ein Widget-Fenster NIE
    gegen die tatsächlich verfügbare Monitorfläche geprüft - bei hoher
    Scale (= kleine logische Auflösung) konnte ein Fenster mit viel
    Inhalt (z.B. Sound-Widget mit vielen offenen Audio-Apps, oder
    Settings->Display mit mehreren Monitor-Zeilen) locker über den
    sichtbaren Bereich hinauswachsen, mit dem unteren Teil dann
    schlicht unerreichbar außerhalb des Screens.

    Wickelt den Fensterinhalt bei Bedarf in ein Gtk.ScrolledWindow mit
    fester Maximalgröße. Wird sowohl beim ersten Öffnen (toggle_widget())
    als auch bei jedem Tab-/Kategoriewechsel (_shrink_to_fit(), da ein
    anfangs passender Tab beim Wechsel auf einen größeren nachträglich
    zu groß werden kann) aufgerufen - deshalb idempotent: ein bereits
    gewickeltes Fenster wird beim zweiten Aufruf nur in seinen
    Maximalwerten aktualisiert, nicht nochmal neu gewickelt."""
    geo = _monitor_geometry_for_win(win)
    if geo is None or geo.width <= 0 or geo.height <= 0:
        return
    max_h = max(120, geo.height - _SCREEN_MARGIN_BOTTOM - _SCREEN_EDGE_BUFFER)
    max_w = max(200, geo.width - _SCREEN_MARGIN_RIGHT - _SCREEN_EDGE_BUFFER)

    child = win.get_child()
    if child is None:
        return

    if isinstance(child, Gtk.ScrolledWindow) and child.get_name() == "wb-daemon-clamp":
        try:
            child.set_max_content_height(max_h)
            child.set_max_content_width(max_w)
        except Exception:
            child.set_size_request(-1, max_h)
        return

    natural_h = child.get_preferred_height()[1]
    natural_w = child.get_preferred_width()[1]
    if natural_h <= max_h and natural_w <= max_w:
        return  # passt so wie es ist, kein Scroll-Wrapper nötig

    win.remove(child)
    sw = Gtk.ScrolledWindow()
    sw.set_name("wb-daemon-clamp")
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    try:
        sw.set_propagate_natural_height(True)
        sw.set_propagate_natural_width(True)
        sw.set_max_content_height(max_h)
        sw.set_max_content_width(max_w)
    except AttributeError:
        # Ältere GTK-Versionen (<3.22) kennen propagate_natural_*/
        # max_content_* noch nicht - fester size_request als Fallback,
        # tut im Kern dasselbe (Fenster wird nicht größer als der
        # Screen), nur ohne das "wächst mit bis zum Max" Verhalten.
        sw.set_size_request(min(max_w, natural_w), max_h)
    sw.add(child)
    win.add(sw)
    sw.show_all()

def _shrink_to_fit(win: Gtk.Window) -> bool:
    """GTK-Fenster merken sich ihre zuletzt zugewiesene Größe und werden
    NIE von selbst wieder kleiner, auch wenn der aktuell sichtbare
    Inhalt (z.B. nach einem Stack-Tab-Wechsel oder einem Settings-
    Kategoriewechsel) viel weniger Platz braucht - genau das war der
    Grund für den riesigen leeren Bereich unterhalb der Blase, der mit
    jeder besuchten (größeren) Unterseite noch schlimmer wurde.
    win.resize(1, 1) zwingt GTK, die Fenstergröße komplett neu anhand
    des aktuell sichtbaren Inhalts zu berechnen, statt an der alten,
    zu groß gewordenen Größe festzuhalten."""
    try:
        win.resize(1, 1)
    except Exception:
        pass
    _clamp_window_to_screen(win)
    return False

def _switch_stack(stack: Gtk.Stack, win: Gtk.Window, name: str) -> None:
    """Zentrale Stelle zum Tab-/Seiten-Wechsel innerhalb eines Fensters:
    Sichtbaren Stack-Kind wechseln + danach das Fenster auf die dafür
    tatsächlich nötige (meist kleinere) Größe zurückschrumpfen lassen."""
    stack.set_visible_child_name(name)
    GLib.idle_add(_shrink_to_fit, win)

def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3

def _ease_out_elastic(t: float) -> float:
    """Sanftes 'easeOutBack': wächst gleichmäßig über die GANZE Dauer
    und schießt erst kurz vorm Ziel EIN einziges Mal leicht drüber
    hinaus, statt wie klassisches Elastic mehrfach hin- und
    herzuschwingen - letzteres wirkte zu hektisch/heftig und hatte
    quasi seine gesamte sichtbare Bewegung schon in den ersten 30-40%
    der Zeit verbraucht (fühlte sich dadurch auch "zu schnell" an,
    obwohl die Gesamtdauer stimmte). AMPLITUDE klein halten (c1 statt
    Standard-1.70158 nur 1.05) für ein spürbares, aber kein hartes
    Überschwingen."""
    t = max(0.0, min(1.0, t))
    c1 = 1.05
    c3 = c1 + 1
    u = t - 1
    return 1 + c3 * u ** 3 + c1 * u ** 2


def _make_particles(n: int = _PARTICLE_N) -> list:
    parts = []
    for _ in range(n):
        angle = random.uniform(0, math.tau)
        speed = random.uniform(0.012, 0.035)   # Anteil der Sicherheitsfläche/Sekunde
        parts.append({
            "x": random.random(),
            "y": random.random(),
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "r": random.uniform(1.0, 2.4),
            # Sanfte, konstante Drehrate pro Pünktchen (mal links-,
            # mal rechtsherum) - lässt die Flugbahn geschwungen statt
            # stur geradlinig wirken, ohne die Geschwindigkeit selbst
            # zu verändern (reine Rotation des Vektors).
            "turn": random.uniform(-0.5, 0.5),
        })
    return parts

def _draw_window(win: Gtk.Window, ctx) -> bool:
    """Ein einziger Draw-Handler pro Fenster: die große Blase (manuell
    per Cairo/GdkPixbuf gemalt, siehe _paint_bubble_bg) + die Scale/
    Bounce-Animation beim Öffnen/Schließen + die frei fliegenden
    Gold-Pünktchen.

    ANIMATION: reines Skalieren + Verschieben, verankert an der
    Fensterecke, an der das Fenster auch per GtkLayerShell hängt
    (unten rechts) - der Inhalt wächst von winzig auf Endgröße, MIT
    Überschwingen/Bounce (siehe _ease_out_elastic: schießt kurz über
    100% hinaus und pendelt sich dann ein), statt einer separaten
    Opacity-Überblendung ("kein einfaches Einblenden") - Sichtbarkeit
    kommt allein aus der Größe, nicht aus Alpha. Schließen ist exakt
    dieselbe Animation, nur mit rückwärts laufendem Fortschritt
    (state["closing_since"] gesetzt -> p_pop zählt von 1.0 auf 0.0
    statt von 0.0 auf 1.0) - identische Dauer (_POPUP_MS), identische
    Easing-Funktion, wirklich nur zeitlich umgekehrt abgespielt.

    WICHTIG zum Rendern: läuft NICHT über win.set_opacity() (das hat
    sich als unzuverlässig auf GtkLayerShell-Overlay-Surfaces
    herausgestellt - manche Wayland-Compositor ziehen Live-Änderungen
    der Fenster-Opacity nicht sauber nach, das Fenster blieb dann
    komplett unsichtbar). Stattdessen wird ALLES (Hintergrund-Blase +
    Pünktchen + die eigentlichen Kind-Widgets) manuell in eine
    transformierte Cairo-Gruppe gemalt (push_group/translate/scale/
    propagate_draw/pop_group_to_source) - reines Cairo-Compositing,
    hängt an gar nichts Wayland/Compositor-Spezifischem und
    funktioniert daher überall gleich zuverlässig."""
    state = _anim.get(win)
    now = time.time()
    alloc = win.get_allocation()
    w, h = max(alloc.width, 1), max(alloc.height, 1)

    if state is None:
        # Kein Cairo-Zustand (z.B. HAS_CAIRO=False) - einfach normal
        # zeichnen lassen, ohne jeden Effekt. Overlay (TrafkBubble1.png)
        # bewusst NICHT hier mit gemalt: dieser Zweig gibt False zurück
        # und lässt GTKs eigenen Default-Handler die Kinder NACH diesem
        # Aufruf zeichnen - ein hier gemaltes Overlay würde also unter
        # den Kindern landen statt darüber. Reiner Degraded-Fallback für
        # den seltenen Fall ohne Cairo, daher nicht weiter optimiert.
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        _paint_bubble_bg(ctx, w, h)
        return False

    closing_since = state.get("closing_since")
    if closing_since is not None:
        t_close = (now - closing_since) / (_POPUP_MS / 1000.0)
        p_pop = 1.0 - _ease_out_elastic(min(1.0, t_close))
    else:
        t_pop = (now - state["popup_start"]) / (_POPUP_MS / 1000.0)
        p_pop = _ease_out_elastic(t_pop)

    scale = max(0.0, p_pop)
    # Statt einer künstlichen Mindestgröße (die den Rest der
    # Schließen-Animation als ein stehenbleibendes kleines Pünktchen
    # hätte "einfrieren" lassen, bis der Cleanup-Timer das Fenster
    # irgendwann zerstört) hier bewusst GAR NICHTS mehr zeichnen, sobald
    # die Blase praktisch unsichtbar ist - sowohl ganz am Anfang des
    # Öffnens als auch ganz am Ende des Schließens. ctx.scale() mit
    # einem Wert nahe 0 würde außerdem eine (fast) singuläre Matrix
    # ergeben, was bei manchen Cairo-Operationen (z.B. Radial-Gradienten
    # der Pünktchen weiter unten) zu Fehlern führen kann - dieses
    # frühzeitige Return umgeht das gleich mit.
    if scale < 0.02:
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        return True
    tx = w * (1 - scale)
    ty = h * (1 - scale)

    ctx.push_group()
    ctx.translate(tx, ty)
    ctx.scale(scale, scale)

    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    _paint_bubble_bg(ctx, w, h)

    r_gold, g_gold, b_gold = _GOLD_RGB
    # Pünktchen bleiben innerhalb desselben Sicherheitsbereichs wie der
    # Content (nicht im vollen Fensterrechteck) - sonst fliegen sie
    # über den transparenten PNG-Rand hinweg, wo keine sichtbare Blase
    # mehr ist. Position wird jetzt pro Frame direkt fortgeschrieben
    # (statt aus verstrichener Zeit neu berechnet) und prallt an den
    # Rändern ab (Geschwindigkeit wird gespiegelt) - kein Sprung mehr
    # von einer Seite zur anderen. Der Geschwindigkeitsvektor wird
    # zusätzlich jeden Frame ein winziges Stück gedreht ("turn"), das
    # macht die Flugbahn geschwungen statt schnurgerade.
    dt = now - state.get("_last_tick", now)
    dt = min(dt, 0.25)   # Ausreißer (z.B. nach Fenster-Minimierung) kappen
    state["_last_tick"] = now

    px0 = w * PARTICLE_X_FRAC
    px1 = w * (1 - PARTICLE_X_FRAC)
    py0 = h * PARTICLE_Y_FRAC
    py1 = h * (1 - PARTICLE_Y_FRAC)
    pw, ph = max(1.0, px1 - px0), max(1.0, py1 - py0)
    for pt in state["particles"]:
        ang = pt["turn"] * dt
        if ang:
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            vx, vy = pt["vx"], pt["vy"]
            pt["vx"] = vx * cos_a - vy * sin_a
            pt["vy"] = vx * sin_a + vy * cos_a

        pt["x"] += pt["vx"] * dt
        pt["y"] += pt["vy"] * dt
        if pt["x"] < 0.0:
            pt["x"] = 0.0; pt["vx"] = abs(pt["vx"])
        elif pt["x"] > 1.0:
            pt["x"] = 1.0; pt["vx"] = -abs(pt["vx"])
        if pt["y"] < 0.0:
            pt["y"] = 0.0; pt["vy"] = abs(pt["vy"])
        elif pt["y"] > 1.0:
            pt["y"] = 1.0; pt["vy"] = -abs(pt["vy"])

        cx, cy = px0 + pt["x"] * pw, py0 + pt["y"] * ph
        ctx.save()
        # Glow: echter Radial-Gradient, der bei der Kern-Deckkraft
        # (65%) startet und nach außen sanft auf 0 ausfadet - statt
        # einer flachen Halo-Scheibe mit hartem Rand.
        core_alpha = 0.35
        glow_r = pt["r"] * 3.4
        grad = cairo.RadialGradient(cx, cy, 0, cx, cy, glow_r)
        grad.add_color_stop_rgba(0.0, r_gold, g_gold, b_gold, core_alpha)
        grad.add_color_stop_rgba(1.0, r_gold, g_gold, b_gold, 0.0)
        ctx.set_source(grad)
        ctx.arc(cx, cy, glow_r, 0, math.tau)
        ctx.fill()
        ctx.arc(cx, cy, pt["r"], 0, math.tau)
        ctx.set_source_rgba(r_gold, g_gold, b_gold, core_alpha)
        ctx.fill()
        ctx.restore()

    # Die eigentlichen Kind-Widgets (Buttons, Labels, ...) manuell mit
    # in dieselbe transformierte Gruppe zeichnen, damit sie exakt
    # genauso mitwachsen/-schrumpfen und mitbouncen wie der
    # Hintergrund, statt starr an fester Größe zu kleben.
    child = win.get_child()
    if child is not None:
        win.propagate_draw(child, ctx)

    # TrafkBubble1.png GANZ ZULETZT, nach Hintergrund/Pünktchen/Inhalt -
    # liegt dadurch optisch über allem anderen (siehe
    # _paint_bubble_overlay()-Docstring).
    _paint_bubble_overlay(ctx, w, h)

    ctx.pop_group_to_source()
    ctx.paint()
    # True = Signal-Emission hier stoppen, DAMIT GTKs eigener
    # Default-Handler die Kinder nicht noch ein zweites Mal (diesmal
    # untransformiert) obendrauf zeichnet - wir haben das oben schon
    # über propagate_draw() selbst erledigt.
    return True

def _start_popup_in(win: Gtk.Window) -> None:
    """Öffnen-Animation anstoßen. WICHTIG: setzt popup_start hier NEU
    (nicht mehr nur beim Erzeugen in make_win() belassen) - zwischen
    make_win() und dem tatsächlichen win.show_all() liegt noch der
    komplette Content-Aufbau (BUILDERS[name](win), bei größeren
    Widgets durchaus spürbar), der sonst schon einen Teil der
    Animationsdauer aufgefressen hätte, BEVOR überhaupt ein Frame
    sichtbar war - die Animation wäre dadurch beim ersten sichtbaren
    Frame schon halb "verbraucht" gewesen. Jetzt startet die Uhr erst
    hier, exakt am Anfang der tatsächlich sichtbaren Zeit."""
    state = _anim.get(win)
    if state is not None:
        state["popup_start"] = time.time()
    win.queue_draw()

def _fade_out_and_close(name: str, win: Gtk.Window) -> None:
    """Schließt ein Fenster mit der GENAU UMGEKEHRTEN Reveal-Animation,
    mit der es geöffnet wurde (siehe _draw_window(),
    state["closing_since"]) und räumt es danach über dieselbe
    _cleanup()-Funktion auf, die auch make_win() registriert hat. KEIN
    win.set_opacity() (siehe Kommentar in _draw_window() dazu, warum
    das auf Layer-Shell-Surfaces unzuverlässig war)."""
    def _finish():
        cleanup_fn = _cleanup_by_win.get(win)
        if cleanup_fn is not None:
            try:
                cleanup_fn()
            except Exception as e:
                print(f"⚠ _cleanup für Widget '{name}' fehlgeschlagen: {e}", file=sys.stderr)
        else:
            try: win.destroy()
            except Exception: pass

    state = _anim.get(win)
    if state is None:
        # Kein Cairo-Zustand vorhanden -> es gibt nichts zum Ausblenden,
        # einfach sofort schließen statt auf eine Animation zu warten,
        # die nie stattfindet.
        _finish()
        return

    state["closing_since"] = time.time()
    win.queue_draw()
    # Gleiche Dauer wie das Öffnen (_POPUP_MS) - sonst wäre es keine
    # wirklich "umgekehrte" Animation, sondern nur optisch ähnlich,
    # aber unterschiedlich schnell.
    GLib.timeout_add(_POPUP_MS + _TICK_MS, lambda: (_finish(), False)[1])

def _destroy_widget(name: str) -> None:
    win = _open.pop(name, None)
    if win is None:
        return
    # WICHTIG: _cleanup() (Timer-Entfernung, _timers_by_win/_open
    # aufräumen, win.destroy()) wird HIER DIREKT aufgerufen, statt sich
    # ausschließlich darauf zu verlassen, dass ein separater
    # win.destroy()-Aufruf zuverlässig das "destroy"-Signal auslöst,
    # das wiederum _cleanup() triggert. Genau diese indirekte Kette war
    # der eigentliche Leak: wenn win.destroy() intern aus irgendeinem
    # Grund scheiterte (GTK-Lifecycle-Timing, Fehler in einem Signal-
    # Handler während des Teardowns, o.ä.), wurde die Exception vom
    # bloßen "except: pass" verschluckt - das Fenster (und ALLE seine
    # periodischen Timer, z.B. der 2s-System-Monitor-Refresh) blieb
    # dann für immer im Hintergrund aktiv, obwohl _open das Widget
    # schon als geschlossen führte und ein erneutes Öffnen anstandslos
    # einen komplett NEUEN Timer-Satz obendrauf gestapelt hätte - über
    # einen Tag verteiltes wiederholtes Öffnen/Schließen summiert sich
    # so zu genau der Art von Hintergrund-Last, die hier beobachtet
    # wurde. _cleanup() selbst entfernt die Timer ZUERST, bevor es
    # überhaupt win.destroy() versucht - dieser Aufruf hier ist also
    # auch dann sicher, wenn win.destroy() intern nochmal scheitert.
    cleanup_fn = _cleanup_by_win.get(win)
    if cleanup_fn is not None:
        try: cleanup_fn()
        except Exception as e:
            print(f"⚠ _cleanup für Widget '{name}' fehlgeschlagen: {e}", file=sys.stderr)
    else:
        # Sollte nie vorkommen (make_win registriert IMMER einen
        # Eintrag, bevor ein Fenster in _open landen kann) - Fallback
        # nur zur Sicherheit, damit das Fenster wenigstens verschwindet.
        try: win.destroy()
        except Exception as e:
            print(f"⚠ win.destroy() für Widget '{name}' fehlgeschlagen: {e}", file=sys.stderr)

def _close_all(except_name: str = None) -> None:
    for name in list(_open):
        if name != except_name:
            _destroy_widget(name)

def toggle_widget(name: str) -> str:
    global WIDGET
    if name not in BUILDERS:
        return f"error: unknown widget '{name}'"

    if name in _open:
        # Gleiche Blase nochmal angeklickt -> sanft ausblenden statt
        # abrupt verschwinden zu lassen.
        win = _open.pop(name)
        _fade_out_and_close(name, win)
        _play_sound("Close")
        return "closed"

    # Alle evtl. noch offenen Blasen sanft ausblenden, WÄHREND die neue
    # gleichzeitig reinwächst/reinblendet -> ergibt zusammen den
    # Crossfade beim Wechseln zwischen Widgets.
    for old_name in list(_open):
        old_win = _open.pop(old_name)
        _fade_out_and_close(old_name, old_win)

    WIDGET = name
    win = make_win(name)
    _current_win[0] = win
    BUILDERS[name](win)
    _current_win[0] = None
    _clamp_window_to_screen(win)
    win.show_all()
    _open[name] = win
    _start_popup_in(win)
    _play_sound("Open")
    return "opened"

def add_timer(ms: int, fn) -> int:
    tid = GLib.timeout_add(ms, fn)
    win = _current_win[0]
    if win is not None and win in _timers_by_win:
        _timers_by_win[win].append(tid)
    return tid

def make_win(name: str) -> Gtk.Window:
    win = Gtk.Window()
    win.set_title(f"wb-{name}")
    win.set_decorated(False)
    win.set_resizable(False)
    win.set_app_paintable(True)
    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual: win.set_visual(visual)
    if HAS_LS:
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "wb-daemon")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT,  True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, 65)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT,  35)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    else:
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
    cleaned = [False]
    my_timers: list[int] = []
    _timers_by_win[win] = my_timers

    if HAS_CAIRO:
        now = time.time()
        _anim[win] = {
            "start": now,             # für die frei fliegenden Pünktchen
            "popup_start": now,       # für das Reinwachsen beim Öffnen
            "particles": _make_particles(),
        }
        win.connect("draw", _draw_window)
        # Ambient-Redraw, damit die Pünktchen sich die ganze Zeit,
        # in der die Blase offen ist, ganz leicht weiterbewegen.
        _amb_tid = GLib.timeout_add(_TICK_MS, lambda: (win.queue_draw(), True)[1])
        my_timers.append(_amb_tid)

    def _cleanup(*_):
        if cleaned[0]:
            return False
        cleaned[0] = True
        for tid in my_timers:
            try: GLib.source_remove(tid)
            except: pass
        my_timers.clear()
        _timers_by_win.pop(win, None)
        _cleanup_by_win.pop(win, None)
        _anim.pop(win, None)
        # WICHTIG (Bugfix "Duplikat-Fenster bei schnellem Öffnen/
        # Schließen/Öffnen", siehe Known Bugs in der README): NUR
        # entfernen, wenn _open[name] GENAU DIESES Fenster ist - nicht
        # blind nach Namen poppen. Ablauf des Bugs ohne diese Prüfung:
        # 1) Fenster A wird geöffnet -> _open["volume"] = A
        # 2) sofort wieder zugeklickt -> toggle_widget() poppt A schon
        #    SELBST aus _open (siehe dort) und startet nur noch
        #    _fade_out_and_close(A) - A ist ab jetzt nirgends mehr in
        #    _open drin, blendet aber noch ein paar hundert ms lang aus.
        # 3) sofort ein drittes Mal geklickt, WÄHREND A noch ausblendet
        #    -> "volume" ist nicht mehr in _open -> toggle_widget() legt
        #    ein KOMPLETT NEUES Fenster B an -> _open["volume"] = B.
        # 4) A's Fade-Timer läuft ab, _cleanup() für A feuert. Ohne
        #    Identitätsprüfung würde hier "_open.pop('volume', None)"
        #    B einfach mit rausreißen, obwohl B nichts mit A's Teardown
        #    zu tun hat und quicklebendig sichtbar bleibt. B ist danach
        #    nirgends mehr in _open registriert - ein erneuter Klick
        #    findet "volume" nicht in _open, versteht es also nicht als
        #    "schließen", sondern legt gleich ein VIERTES Fenster C an.
        #    B bleibt als nie mehr erreichbare, nie mehr schließbare
        #    Geister-Blase permanent auf dem Screen stehen - exakt der
        #    gemeldete Bug ("macht eine Duplikat, die immer auf dem
        #    Screen bleibt und nichts tut").
        if _open.get(name) is win:
            _open.pop(name, None)
        try: win.destroy()
        except: pass
        return False

    _cleanup_by_win[win] = _cleanup
    win.connect("destroy", _cleanup)
    win.connect("focus-out-event", lambda w, e: _cleanup())
    return win

# ════════════════════════════════════════════════════════════
#  UI Helpers
# ════════════════════════════════════════════════════════════
def vbox(sp: int = 4) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sp)

def hbox(sp: int = 6) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=sp)

def sep() -> Gtk.Separator:
    s = Gtk.Separator()
    return s

def tab_sep() -> Gtk.Separator:
    """Kräftigerer Trennstrich, der direkt unter einer Tab-Leiste
    (tab_row) sitzt - siehe separator.tab-divider in der CSS."""
    s = Gtk.Separator()
    s.get_style_context().add_class("tab-divider")
    return s

def pad(w: Gtk.Widget, h: int = 10, v: int = 10) -> Gtk.Widget:
    w.set_margin_start(h); w.set_margin_end(h)
    w.set_margin_top(v);   w.set_margin_bottom(v)
    return w

# Die Blasen-PNGs haben selbst ringsum transparenten Rand, der NICHT
# zur sichtbaren Kreisfläche gehört - ein fixer Pixel-Puffer war daher
# bei unterschiedlich breiten Fenstern (340px Battery bis 460px
# Kalender) mal zu knapp, mal unnötig groß. safe_pad() berechnet den
# Rand stattdessen als Anteil der (für jedes Fenster fest bekannten)
# Fensterbreite - grobe Schätzung der Kreis-Geometrie, aber
# proportional über alle Fenstergrößen hinweg konsistent.
SAFE_X_FRAC = 0.13
SAFE_Y_FRAC = 0.16

# Etwas großzügiger als der Content-Rand, weil einzelne Pünktchen (im
# Gegensatz zu Textzeilen) auch näher an der eigentlichen Kreiskante
# noch unauffällig aussehen.
PARTICLE_X_FRAC = 0.17
PARTICLE_Y_FRAC = 0.22

def safe_pad(w: Gtk.Widget, win_width: int,
             x_frac: float = SAFE_X_FRAC, y_frac: float = SAFE_Y_FRAC) -> Gtk.Widget:
    return pad(w, h=max(4, round(win_width * x_frac)),
                  v=max(4, round(win_width * y_frac)))

def safe_pad_edge(w: Gtk.Widget, win_width: int, top: bool, bottom: bool,
                   x_frac: float = SAFE_X_FRAC, y_frac: float = SAFE_Y_FRAC) -> Gtk.Widget:
    """Wie safe_pad(), aber oben/unten einzeln schaltbar. Für Fenster
    mit MEHREREN vertikal gestapelten Containern im selben Fenster
    (z.B. Settings: Stack-Seite + separate Apply/Discard-Leiste)
    braucht nur der jeweils äußere Rand (oben bei der ersten Sektion,
    unten bei der letzten) den vollen 'safe'-Randabstand zur
    gebogenen Blasenkante - am inneren Übergang zwischen den Sektionen
    sonst DOPPELT so groß wie nötig, siehe Chat ("riesiger Abstand um
    den Trennstrich zwischen Menüliste und Apply-Leiste")."""
    x = max(4, round(win_width * x_frac))
    y = max(4, round(win_width * y_frac))
    w.set_margin_start(x); w.set_margin_end(x)
    w.set_margin_top(y if top else 4)
    w.set_margin_bottom(y if bottom else 4)
    return w

def btitle(text: str) -> Gtk.Box:
    box = hbox(0)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("title")
    box.set_halign(Gtk.Align.CENTER)
    l = Gtk.Label(label=text)
    box.pack_start(l, False, False, 0)
    return box

def bsec(text: str) -> Gtk.Box:
    box = hbox(0)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("section")
    box.set_halign(Gtk.Align.CENTER)
    l = Gtk.Label(label=text.upper())
    box.pack_start(l, False, False, 0)
    return box

def bsec_btn(text: str, active: bool = False) -> Gtk.Button:
    """Wie bsec(), aber als klickbarer Button statt reinem Label - für
    Sektionsüberschriften, die selbst ein Schalter sind (z.B. "Volume:
    45%" = Mute-Schalter, kein separates Icon/Symbol mehr daneben
    nötig). Groß schreiben passiert hier genau wie bei bsec()."""
    b = Gtk.Button(label=text.upper())
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class("bubble")
    b.get_style_context().add_class("section")
    b.set_halign(Gtk.Align.CENTER)
    if active:
        b.get_style_context().add_class("active")
    return b

def bitem(text: str, dim: bool = False) -> Gtk.Box:
    box = hbox(0)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("item")
    box.set_halign(Gtk.Align.CENTER)
    l = Gtk.Label(label=text)
    if dim:
        l.set_opacity(0.6)
    l.set_ellipsize(Pango.EllipsizeMode.END)
    box.pack_start(l, False, False, 0)
    return box

def bitem_ref(text: str, dim: bool = False) -> tuple[Gtk.Box, Gtk.Label]:
    box = hbox(0)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("item")
    box.set_halign(Gtk.Align.CENTER)
    l = Gtk.Label(label=text)
    if dim: l.set_opacity(0.6)
    l.set_ellipsize(Pango.EllipsizeMode.END)
    box.pack_start(l, False, False, 0)
    return box, l

def btn(text: str, cb=None, tip: str = "",
        active: bool = False) -> Gtk.Button:
    b = Gtk.Button(label=text)
    b.get_style_context().add_class("bubble")
    b.set_halign(Gtk.Align.CENTER)
    b.set_can_focus(False)
    if active:
        b.get_style_context().add_class("active")
    if tip: b.set_tooltip_text(tip)
    if cb:
        # KEIN Klick-Sound hier (mehr) - bewusst nicht verdrahtet: ein
        # "Click"-Sound soll, wenn er kommt, wirklich systemweit sein
        # (jeder Mausklick, nicht nur die eigenen Widgets) - das ist auf
        # Wayland ohne rohen Input-Geräte-Zugriff nicht sauber lösbar
        # (siehe SoundCenter-Notizen), deshalb hier erstmal NICHTS statt
        # eines Widget-lokalen Behelfs. btn() bleibt trotzdem die
        # zentrale Stelle - sobald es einen echten systemweiten Weg gibt,
        # reicht ein Einzeiler genau hier für ALLE Widget-Buttons.
        b.connect("clicked", cb)
    return b

class _SegmentedControl:
    """Ersatz für Gtk.ComboBoxText bei Dropdowns mit klar BEGRENZTER
    Optionsanzahl (siehe README, Abschnitt "To Be Done": "some widgets
    have dropdown menus with limits. those should be turned into
    sliders. like the scale and rotation boxes/buttons"). Statt eines
    aufklappbaren Menüs eine Reihe direkt sichtbarer, antippbarer
    Knöpfe. Vorteil ggü. echtem Dropdown: alle Optionen sofort
    sichtbar, kein Extra-Klick zum Aufklappen, besser für Touch.
    (Rotation selbst ist inzwischen KEIN Anwendungsfall mehr dafür -
    die ist ein echter Zieh-Regler geworden, siehe rot_slider in
    _build_monitor_row(); diese Klasse wird aktuell für Refresh-Rate
    (hz_combo) genutzt.)

    Bildet bewusst NUR die Teilmenge der Gtk.ComboBoxText-API ab, die
    die aufrufenden Stellen tatsächlich nutzen (get_active_text,
    set_active, remove_all, append_text, connect("changed", ...) inkl.
    handler_block/unblock für programmatisches Umschalten ohne
    Rückkopplung, plus n_items() statt des ComboBoxText-eigenen
    get_model().iter_n_children(None)) - damit der Rest des
    aufrufenden Codes so gut wie unverändert bleiben kann.
    """
    def __init__(self):
        self.widget = hrow(sp=6)
        self._labels: list[str] = []
        self._buttons: list[Gtk.Button] = []
        self._active = -1
        self._handlers: dict[int, "callable"] = {}
        self._next_handler_id = 1
        self._blocked: set = set()

    def append_text(self, text: str):
        idx = len(self._labels)
        self._labels.append(text)
        b = btn(text, lambda _w, i=idx: self._on_click(i))
        self._buttons.append(b)
        self.widget.pack_start(b, False, False, 0)
        b.show()

    def remove_all(self):
        for b in self._buttons:
            self.widget.remove(b)
        self._labels.clear()
        self._buttons.clear()
        self._active = -1

    def _refresh(self):
        for i, b in enumerate(self._buttons):
            ctx = b.get_style_context()
            if i == self._active:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")

    def _on_click(self, idx: int):
        if idx == self._active:
            return
        self._active = idx
        self._refresh()
        # Wie bei Gtk.ComboBoxText: "changed" feuert bei jedem
        # Nutzerklick, aber (via handler_block/unblock, siehe oben)
        # unterdrückbar bei rein programmatischen set_active()-Aufrufen.
        for hid, cb in list(self._handlers.items()):
            if hid not in self._blocked:
                cb(self)

    def set_active(self, idx: int):
        self._active = idx if 0 <= idx < len(self._labels) else -1
        self._refresh()

    def get_active_text(self):
        return self._labels[self._active] if 0 <= self._active < len(self._labels) else None

    def n_items(self) -> int:
        return len(self._labels)

    def connect(self, signal: str, cb):
        assert signal == "changed", f"_SegmentedControl unterstützt nur 'changed', nicht {signal!r}"
        hid = self._next_handler_id
        self._next_handler_id += 1
        self._handlers[hid] = cb
        return hid

    def handler_block(self, hid):
        self._blocked.add(hid)

    def handler_unblock(self, hid):
        self._blocked.discard(hid)

    def set_can_focus(self, _v):
        pass  # Knöpfe kommen schon fokus-los aus btn()

    def set_sensitive(self, sensitive: bool):
        self.widget.set_sensitive(sensitive)

    def set_tooltip_text(self, text: str):
        self.widget.set_tooltip_text(text)

    def get_style_context(self):
        return self.widget.get_style_context()


def bslider(icon: str, lo: float, hi: float, step: float, val: float,
            cb=None, show_val: bool = True,
            suffix_lbl: Gtk.Label = None) -> tuple[Gtk.Box, Gtk.Scale]:
    box = hbox(8)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("slider")
    icon_l = Gtk.Label(label=icon)
    icon_l.set_opacity(0.7)
    box.pack_start(icon_l, False, False, 0)
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    s.set_value(val)
    s.set_hexpand(True)
    s.set_draw_value(show_val)
    s.set_can_focus(False)
    # ALLGEMEIN (Formatierungs-Feedback): Slider sollen NICHT per
    # Mausrad verstellbar sein - GtkRange (Basisklasse von GtkScale)
    # reagiert sonst standardmäßig auf "scroll-event" und ändert dabei
    # den Wert, oft ungewollt beim einfachen Durchscrollen des Fensters.
    # Da bslider() die EINZIGE Stelle im ganzen Programm ist, die
    # Gtk.Scale erzeugt, reicht dieser eine Handler für jeden Slider
    # überall (Lautstärke, Helligkeit, Scale, Rotation, Night Light, ...).
    s.connect("scroll-event", lambda *_: True)
    if show_val:
        s.set_value_pos(Gtk.PositionType.RIGHT)
    if cb: s.connect("value-changed", cb)
    box.pack_start(s, True, True, 0)
    if suffix_lbl is not None:
        box.pack_start(suffix_lbl, False, False, 0)
    return box, s

def hrow(*widgets, sp: int = 6) -> Gtk.Box:
    row = hbox(sp)
    row.set_halign(Gtk.Align.CENTER)
    for w in widgets:
        row.pack_start(w, False, False, 0)
    return row

def scroll_box(max_h: int = 220) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    # WICHTIG: set_min_content_height() (die alte Version davor) hat
    # IMMER diese Höhe reserviert, egal ob 2 oder 20 Einträge drin
    # standen - bei kurzen Listen (z.B. 2 bekannte Bluetooth-Geräte)
    # blieb dadurch ein riesiger leerer Bereich stehen. Jetzt:
    # set_max_content_height() als reine Obergrenze (erst AB der wird
    # gescrollt) + set_propagate_natural_height(True), damit sich das
    # ScrolledWindow bis dahin auf die TATSÄCHLICHE Höhe seines Inhalts
    # schrumpft.
    sw.set_max_content_height(max_h)
    sw.set_propagate_natural_height(True)
    b = vbox(2)
    b.set_margin_top(4); b.set_margin_bottom(4)
    b.set_margin_start(2); b.set_margin_end(2)
    sw.add(b)
    return sw, b


# ════════════════════════════════════════════════════════════
#  VOLUME
# ════════════════════════════════════════════════════════════
def _vol_pct() -> int:
    out = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    try: return int(float(out.split()[1]) * 100)
    except: return 50

def _is_muted() -> bool:
    return "[MUTED]" in run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])

def _media_all() -> dict:
    out = run(["playerctl", "metadata", "--format",
               "{{status}}|||{{title}}|||{{artist}}"])
    p = out.split("|||")
    if len(p) < 3: return {}
    return {"status": p[0], "title": p[1][:38], "artist": p[2][:32]}

def _default_sink_name() -> str:
    return run(["pactl", "get-default-sink"]).strip()

def _default_source_name() -> str:
    return run(["pactl", "get-default-source"]).strip()

def _get_sinks() -> list:
    data = jrun(["pactl", "--format=json", "list", "sinks"]) or []
    res = []
    for s in data:
        vols = s.get("volume", {})
        pct  = int(list(vols.values())[0].get(
                    "value_percent", "0%").rstrip("%")) if vols else 0
        res.append({"name": s.get("name",""), "desc": s.get("description","?")[:44],
                     "vol": pct, "muted": bool(s.get("mute", False))})
    return res

def _get_sources() -> list:
    data = jrun(["pactl", "--format=json", "list", "sources"]) or []
    res = []
    for s in data:
        if "monitor" in s.get("name","").lower():
            continue
        vols = s.get("volume", {})
        pct  = int(list(vols.values())[0].get(
                    "value_percent", "0%").rstrip("%")) if vols else 0
        res.append({"name": s.get("name",""), "desc": s.get("description","?")[:44],
                     "vol": pct, "muted": bool(s.get("mute", False))})
    return res

def _get_inputs() -> list:
    data = jrun(["pactl", "--format=json", "list", "sink-inputs"]) or []
    res = []
    for i in data:
        props = i.get("properties", {})
        name  = props.get("application.name",
                          props.get("media.name", f"App {i.get('index',0)}"))
        vols  = i.get("volume", {})
        pct   = int(list(vols.values())[0].get(
                    "value_percent","0%").rstrip("%")) if vols else 0
        res.append({"index": i.get("index",0), "name": name[:24], "vol": pct})
    return res

def _build_device_row(dev: dict, kind: str, is_default: bool, refresh_fn) -> Gtk.Box:
    """Eine Zeile pro Audio-Gerät im Devices-Tab: Name-Button (setzt
    dieses Gerät als Default, zeigt jetzt auch gleich die Lautstärke im
    Label mit an: "Name: 45%") + eigener Lautstärkeregler. KEIN Mute
    mehr hier - das geht schon über den Regler selbst (auf 0% ziehen),
    ein separater Mute-Schalter wäre nur Redundanz. Der Name-Button
    leuchtet jetzt stattdessen, wenn dieses Gerät das aktuelle Default
    ist. kind ist "sink" (Output) oder "source" (Input), steuert nur,
    welche pactl-Unterbefehle (set-default-sink/-source, set-sink-/
    -source-volume) benutzt werden."""
    set_default_cmd = "set-default-sink" if kind == "sink" else "set-default-source"
    set_volume_cmd  = "set-sink-volume"   if kind == "sink" else "set-source-volume"

    row = vbox(1)
    row.get_style_context().add_class("bubble")
    pad(row, h=8, v=4)

    vol_state = [dev["vol"]]

    # Name + Lautstärke in EINEM zentrierten Label - leuchtet, wenn
    # dieses Gerät das aktuelle Default ist.
    def _label_text():
        return f'{dev["desc"]}: {vol_state[0]}%'

    name_btn = btn(_label_text(), active=is_default)
    name_btn.set_halign(Gtk.Align.CENTER)

    def _on_select(_w, n=dev["name"]):
        in_thread(run, ["pactl", set_default_cmd, n])
        GLib.timeout_add(300, refresh_fn)
    name_btn.connect("clicked", _on_select)
    row.pack_start(name_btn, False, False, 0)

    def _on_vol(s, n=dev["name"]):
        vol_state[0] = int(s.get_value())
        name_btn.set_label(_label_text())
        in_thread(run, ["pactl", set_volume_cmd, n, f"{vol_state[0]}%"])
    # Kein Icon-Label mehr am Slider - Hitbox kommt global aus der CSS,
    # bewusst NICHT visuell größer (siehe bslider()/CSS-Kommentar).
    vol_box, _ = bslider("", 0, 150, 1, dev["vol"], cb=_on_vol, show_val=False)
    for ch in vol_box.get_children():
        if isinstance(ch, Gtk.Label):
            vol_box.remove(ch)
            break
    vol_box.set_halign(Gtk.Align.CENTER)
    vol_box.set_size_request(220, -1)
    row.pack_start(vol_box, False, False, 0)

    return row

def _volume_content(win: Gtk.Window) -> Gtk.Box:
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── TAB 1: Media ────────────────────────────────────────
    t1 = vbox(3); pad(t1, h=4, v=10)
    t1.set_margin_top(t1.get_margin_top() + 6)   # insgesamt etwas nach unten gerückt

    # Titel+Artist enger zusammen als der Rest (eigene, engere vbox
    # statt sich auf den generellen t1-Zeilenabstand zu verlassen).
    ta_box = vbox(1)
    title_box, title_lbl   = bitem_ref("  No Media")
    for c in title_box.get_children():
        if isinstance(c, Gtk.Label):
            c.get_style_context().add_class("value-md")
    artist_box, artist_lbl = bitem_ref("", dim=True)
    ta_box.pack_start(title_box,  False, False, 0)
    ta_box.pack_start(artist_box, False, False, 0)
    t1.pack_start(ta_box, False, False, 0)

    prev_b = btn("󰒮", tip="Previous")
    play_b = btn("󰐊", tip="Play/Pause")
    next_b = btn("󰒭", tip="Next")
    prev_b.connect("clicked", lambda _: run_bg(["playerctl", "previous"]))
    play_b.connect("clicked", lambda _: run_bg(["playerctl", "play-pause"]))
    next_b.connect("clicked", lambda _: run_bg(["playerctl", "next"]))
    # Kein extra Padding mehr - der t1-Basisabstand (3) reicht jetzt
    # als Lücke zum Artist darüber.
    t1.pack_start(hrow(prev_b, play_b, next_b), False, False, 0)

    # KEIN Trennstrich mehr vor VOLUME.

    # "Volume: 45%" ist jetzt EIN klickbarer Button = Mute-Schalter,
    # kein separates Lautstärke-Icon/Mute-Knopf mehr am Slider selbst.
    vol_sec_btn = bsec_btn(f"Volume: {_vol_pct()}%", active=_is_muted())
    t1.pack_start(vol_sec_btn, False, False, 0)

    def _on_mute(_w):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        ctx = vol_sec_btn.get_style_context()
        if _is_muted(): ctx.add_class("active")
        else:           ctx.remove_class("active")
    vol_sec_btn.connect("clicked", _on_mute)

    def _on_vol(s):
        val = int(s.get_value())
        vol_sec_btn.set_label(f"VOLUME: {val}%")
        in_thread(run, ["wpctl", "set-volume",
                        "@DEFAULT_AUDIO_SINK@", f"{val}%"])

    # Kein Icon-Label mehr am Slider (bslider() baut eins mit rein,
    # wird hier gleich wieder rausgenommen) - größere Hitbox kommt
    # global aus der CSS (siehe bslider()), hier zusätzlich zentriert
    # und auf eine feste, nicht mehr volle Fensterbreite begrenzt.
    vol_box, vol_s = bslider("", 0, 150, 1, _vol_pct(), cb=_on_vol, show_val=False)
    for ch in vol_box.get_children():
        if isinstance(ch, Gtk.Label):
            vol_box.remove(ch)
            break
    vol_box.set_halign(Gtk.Align.CENTER)
    vol_box.set_size_request(230, -1)
    t1.pack_start(vol_box, False, False, 0)

    def _update_media():
        def _fetch():
            info = _media_all()
            def _apply():
                title_lbl.set_label(info.get("title","") or "  No Media")
                artist_lbl.set_label(info.get("artist","") if info else "")
                play_b.set_label("󰏦" if info.get("status") == "Playing" else "󰐊")
            GLib.idle_add(_apply)
        in_thread(_fetch)
        return True

    add_timer(1500, _update_media)
    _update_media()

    # ── TAB 2: Devices ──────────────────────────────────────
    t2_sw, t2 = scroll_box(240)

    def _refresh_devices():
        for c in t2.get_children(): t2.remove(c)
        default_sink = _default_sink_name()
        t2.pack_start(bsec("OUTPUT"), False, False, 0)
        for s in _get_sinks():
            t2.pack_start(
                _build_device_row(s, "sink", s["name"] == default_sink,
                                   _refresh_devices),
                False, False, 0)
        t2.pack_start(sep(), False, False, 4)
        default_source = _default_source_name()
        t2.pack_start(bsec("INPUT"), False, False, 0)
        for s in _get_sources():
            t2.pack_start(
                _build_device_row(s, "source", s["name"] == default_source,
                                   _refresh_devices),
                False, False, 0)
        t2.show_all()

    _refresh_devices()

    # ── TAB 3: Apps ──────────────────────────────────────────
    t3_sw, t3 = scroll_box(240)

    def _refresh_apps():
        for c in t3.get_children(): t3.remove(c)
        inputs = _get_inputs()
        if not inputs:
            t3.pack_start(bitem("No active audio apps", dim=True),
                          False, False, 0)
        for inp in inputs:
            app_sec = bsec(f'{inp["name"]}: {inp["vol"]}%')
            sec_lbl = app_sec.get_children()[0]
            t3.pack_start(app_sec, False, False, 0)
            def _mk(idx, lbl=sec_lbl, name=inp["name"]):
                def _cb(sc):
                    val = int(sc.get_value())
                    lbl.set_label(f"{name.upper()}: {val}%")
                    in_thread(run, ["pactl", "set-sink-input-volume",
                                    str(idx), f"{val}%"])
                return _cb
            # Kein Icon-Label mehr am Slider - Abstand zum Label darüber
            # ist jetzt nur noch der normale, bereits enge t3-Zeilenabstand
            # (2), da Label+Slider nichts mehr extra auseinanderhält.
            app_box, _ = bslider("", 0, 150, 1, inp["vol"], cb=_mk(inp["index"]),
                                  show_val=False)
            for ch in app_box.get_children():
                if isinstance(ch, Gtk.Label):
                    app_box.remove(ch)
                    break
            app_box.set_halign(Gtk.Align.CENTER)
            app_box.set_size_request(220, -1)
            t3.pack_start(app_box, False, False, 0)
        t3.pack_start(sep(), False, False, 4)
        t3.pack_start(btn("󰑐  Refresh",
            lambda _: GLib.idle_add(_refresh_apps)), False, False, 0)
        t3.show_all()

    _refresh_apps()

    stack.add_named(t1,    "media")
    stack.add_named(t2_sw, "geraete")
    stack.add_named(t3_sw, "apps")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, label in (("media", "󰝚  Media"),
                         ("geraete", "󰓃  Devices"),
                         ("apps", "󰎄  Apps")):
        b = btn(label, active=(name == "media"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)

    outer = vbox(4); safe_pad(outer, 400)
    outer.pack_start(tab_row, True, False, 2)
    outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack,   False, False, 0)
    return outer

def build_volume(win: Gtk.Window):
    win.set_default_size(400, 1)
    win.add(_volume_content(win))

# ════════════════════════════════════════════════════════════
#  NETWORK
# ════════════════════════════════════════════════════════════
def _wifi_dev_name() -> str | None:
    out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"])
    wifi_devs = []
    for line in out.splitlines():
        p = line.split(":")
        if len(p) >= 3 and p[1] == "wifi":
            wifi_devs.append((p[0], p[2]))
    for dev, state in wifi_devs:
        if state == "connected":
            return dev
    return wifi_devs[0][0] if wifi_devs else None

def _wifi_list() -> list:
    out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
               "dev", "wifi", "list"])
    nets, seen = [], set()
    for line in out.splitlines():
        p = line.split(":", 3)
        if len(p) < 4 or not p[1] or p[1] in seen: continue
        seen.add(p[1])
        try: sig = int(p[2])
        except: sig = 0
        nets.append({"active": p[0].strip()=="*", "ssid": p[1],
                     "signal": sig, "secure": bool(p[3].strip())})
    nets.sort(key=lambda n: n["signal"], reverse=True)
    return nets[:20]

def _sig_icon(p: int) -> str:
    return "󰤨" if p>=80 else "󰤥" if p>=60 else "󰤢" if p>=40 else "󰤟" if p>=20 else "󰤯"

def _pw_dialog(parent: Gtk.Window, ssid: str) -> str | None:
    dlg = Gtk.Dialog(title=f"Password: {ssid}", transient_for=parent)
    # NOTE: set_wmclass() targeted the hl.window_rule(class=wb-daemon-popup)
    # in hyprland.lua, which has since been removed (it never matched the
    # main make_win() bubbles anyway, since those are GtkLayerShell layer
    # surfaces, not toplevels). Kept here since it's harmless and this
    # dialog is a real toplevel; set_modal/set_keep_above below already do
    # the actual floating/on-top work for it independent of that rule.
    dlg.set_name("wb-daemon-popup")
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                    "Connect", Gtk.ResponseType.OK)
    e = Gtk.Entry()
    e.set_visibility(False)
    e.set_placeholder_text("Wi-Fi Password")
    e.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
    dlg.get_content_area().pack_start(e, True, True, 12)
    dlg.show_all()
    resp = dlg.run()
    pw = e.get_text() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    return pw

def _ethernet_devices() -> list:
    """Alle LAN/Ethernet-Geräte - fehlten bisher komplett im Networks-
    Tab, der nur 'nmcli dev wifi list' abgefragt hat (siehe README/
    Chat: "check if lan connections show up in network")."""
    out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"])
    devs = []
    for line in out.splitlines():
        p = line.split(":", 3)
        if len(p) < 4 or p[1] != "ethernet":
            continue
        devs.append({"device": p[0], "state": p[2], "connection": p[3]})
    return devs

def _active_connection_name() -> str | None:
    """Name des aktuell aktiven Verbindungsprofils (WLAN ODER LAN) -
    für DNS-Änderungen gebraucht, die pro Profil gelten."""
    out = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"])
    for line in out.splitlines():
        p = line.split(":", 1)
        if len(p) == 2 and p[1]:
            return p[0]
    return None

def _current_dns(conn_name: str) -> str:
    return run(["nmcli", "-g", "ipv4.dns", "connection", "show", conn_name]).strip()

def _set_dns(conn_name: str, servers: str) -> tuple[bool, str]:
    """servers = '' -> zurück auf Auto/DHCP (löscht custom DNS),
    sonst komma-/leerzeichengetrennte IPs. Wendet danach sofort per
    'connection up' an, statt nur die Config zu ändern."""
    if servers.strip():
        dns_val = " ".join(servers.replace(",", " ").split())
        out, err, ec = run_ec(["nmcli", "connection", "modify", conn_name,
                                "ipv4.dns", dns_val,
                                "ipv4.ignore-auto-dns", "yes"], timeout=10)
    else:
        out, err, ec = run_ec(["nmcli", "connection", "modify", conn_name,
                                "ipv4.dns", "",
                                "ipv4.ignore-auto-dns", "no"], timeout=10)
    if ec != 0:
        return False, err or out
    out2, err2, ec2 = run_ec(["nmcli", "connection", "up", conn_name], timeout=15)
    if ec2 != 0:
        return False, err2 or out2
    return True, ""

def _dns_over_tls_status() -> str:
    """Liest DNSOverTLS= aus /etc/systemd/resolved.conf (unter
    [Resolve]). Rückgabe: 'yes' | 'opportunistic' | 'no' | '' (Zeile
    fehlt/Datei nicht lesbar - resolved's eigener Default ist dann
    'no', aber README/System-Setup gehen von 'yes' als Ausgangszustand
    aus, siehe _refresh_dot() im Aufrufer)."""
    try:
        text = Path("/etc/systemd/resolved.conf").read_text()
    except Exception:
        return ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        if key.strip().lower() == "dnsovertls":
            return val.strip().lower()
    return ""

def _set_dns_over_tls(enforce: bool) -> tuple[bool, str]:
    """enforce=True -> 'yes' (JEDE Anfrage MUSS über TLS, kein
    Klartext-Fallback), enforce=False -> 'opportunistic' (versucht
    TLS, fällt aber still auf Klartext zurück, falls der jeweilige
    DNS-Server kein DoT kann - z.B. viele Router-eigene DNS-Server im
    Hotel/Guest-WiFi-Modus weiter unten). Schreibt die Config-Zeile UND
    lädt systemd-resolved in EINEM einzigen pkexec-Aufruf neu (bash -c
    mit beidem drin), damit nur EIN Passwort-Prompt nötig ist statt
    zwei separaten."""
    value = "yes" if enforce else "opportunistic"
    script = (
        "set -e; f=/etc/systemd/resolved.conf; "
        "if grep -qi '^DNSOverTLS=' \"$f\" 2>/dev/null; then "
        f"sed -i 's/^DNSOverTLS=.*/DNSOverTLS={value}/I' \"$f\"; "
        "elif grep -qi '^\\[Resolve\\]' \"$f\" 2>/dev/null; then "
        f"sed -i '/^\\[Resolve\\]/a DNSOverTLS={value}' \"$f\"; "
        "else "
        f"printf '\\n[Resolve]\\nDNSOverTLS={value}\\n' >> \"$f\"; "
        "fi; systemctl restart systemd-resolved"
    )
    out, err, ec = run_ec(["pkexec", "bash", "-c", script], timeout=20)
    if ec != 0:
        return False, err or out or f"exit code {ec}"
    return True, ""

def _guest_wifi_active(conn_name: str) -> bool:
    """True = Hotel/Guest-WiFi-Modus für DIESES Verbindungsprofil aktiv
    (ipv4/ipv6.ignore-auto-dns steht auf 'no', der vom Router per DHCP
    gemeldete DNS darf also durch - nötig für Captive-Portal-
    Login-Seiten). False = normal/enforced (ignore-auto-dns='yes',
    Router-DNS wird ignoriert, es gilt weiter die global erzwungene
    Quad9/Cloudflare-DoT-Konfiguration)."""
    val = run(["nmcli", "-g", "ipv4.ignore-auto-dns",
               "connection", "show", conn_name]).strip().lower()
    return val in ("no", "0", "false")

def _set_guest_wifi(conn_name: str, enable: bool) -> tuple[bool, str]:
    """Setzt ipv4/ipv6.ignore-auto-dns NUR für DIESES eine
    Verbindungsprofil (kein globaler Default, siehe README: "new
    networks joined later still get encrypted DNS by default") und
    verbindet neu, damit die Änderung sofort greift. Braucht KEIN
    pkexec - NetworkManager erlaubt einem angemeldeten User per Polkit
    standardmäßig, seine EIGENEN Verbindungsprofile zu ändern (exakt
    dieselbe Berechtigungslage wie beim bestehenden _set_dns() oben)."""
    val = "no" if enable else "yes"
    out, err, ec = run_ec(["nmcli", "connection", "modify", conn_name,
                            "ipv4.ignore-auto-dns", val,
                            "ipv6.ignore-auto-dns", val], timeout=10)
    if ec != 0:
        return False, err or out
    out2, err2, ec2 = run_ec(["nmcli", "connection", "up", conn_name], timeout=15)
    if ec2 != 0:
        return False, err2 or out2
    return True, ""

def _dns_content(win: Gtk.Window) -> Gtk.Box:
    """DNS-Tab im Security-Widget (README, "DNS extensions"): der
    Server-Auswahl-Dialog, der vorher im Internet-Widget als Popup
    hing, ist HIERHER umgezogen - aber als richtig eingebetteter Tab
    statt Dialog, passend zum Rest des Security-Widgets (Privacy/
    Firewall zeigen auch alles inline). Dazu 2 neue Schalter: "Enforce
    DNS over TLS" (global, systemweit über systemd-resolved) und
    "Hotel/Guest WiFi mode" (nur fürs gerade aktive Verbindungsprofil).
    Kein Lazy-Loading nötig wie beim Firewall-Tab - nichts hier drin
    braucht beim ersten Anzeigen schon root/pkexec, nur der DoT-Toggle
    beim tatsächlichen Umschalten."""
    root = vbox(4); pad(root, h=4, v=6)
    root.pack_start(btitle("󰙲  DNS"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 3500):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    conn = _active_connection_name()

    # DoT + Guest-WiFi jetzt in EINER Zeile/Sektion statt zwei getrennten
    # mit je eigenem Header+Trennstrich (README-Feedback: "auch im
    # Security Tab kann man viel Platz sparen") - DoT ist system-/
    # global-weit und braucht KEINE aktive Verbindung, Guest-WiFi
    # dagegen schon (wirkt pro Verbindung); die Zeile wird deshalb erst
    # gebaut, wenn feststeht, ob `conn` überhaupt existiert.
    root.pack_start(bsec("ENCRYPTION"), False, False, 0)
    dot_row = hbox(10)
    dot_toggle = btn("Enforce DoT")

    def _refresh_dot(value: str):
        enforced = value == "yes"
        ctx = dot_toggle.get_style_context()
        if enforced: ctx.add_class("active")
        else:        ctx.remove_class("active")

    _refresh_dot(_dns_over_tls_status() or "yes")

    def _on_dot_toggle(_w):
        cur = _dns_over_tls_status()
        new_enforce = cur != "yes"
        def _apply():
            ok, err = _set_dns_over_tls(new_enforce)
            if not ok:
                raise RuntimeError(err)
        def _reset():
            _refresh_dot(_dns_over_tls_status() or "yes")
        _refresh_dot("yes" if new_enforce else "opportunistic")
        apply_change(
            f"DNS over TLS: {'Enforced' if new_enforce else 'Opportunistic'}",
            _apply, on_status=_flash, reset_fn=_reset)

    dot_toggle.connect("clicked", _on_dot_toggle)
    dot_toggle.set_tooltip_text(
        "Enforced: every DNS query must use TLS, no fallback. "
        "Opportunistic: tries TLS, silently falls back to plaintext "
        "if the server doesn't support it.")
    dot_row.pack_start(dot_toggle, False, False, 0)

    if conn:
        guest_toggle = btn("Guest WiFi", active=_guest_wifi_active(conn))

        def _refresh_guest(enabled: bool):
            ctx = guest_toggle.get_style_context()
            if enabled: ctx.add_class("active")
            else:       ctx.remove_class("active")

        _refresh_guest(_guest_wifi_active(conn))

        def _on_guest_toggle(_w):
            new_val = not _guest_wifi_active(conn)
            def _apply():
                ok, err = _set_guest_wifi(conn, new_val)
                if not ok:
                    raise RuntimeError(err)
            def _reset():
                _refresh_guest(_guest_wifi_active(conn))
            _refresh_guest(new_val)
            apply_change(f"Guest WiFi mode: {'On' if new_val else 'Off'}",
                         _apply, on_status=_flash, reset_fn=_reset)

        guest_toggle.connect("clicked", _on_guest_toggle)
        guest_toggle.set_tooltip_text(
            "Temporarily allows this network's own DNS (needed for hotel/"
            "airport/office captive portal login pages). Only affects this "
            "connection - other networks keep enforced encrypted DNS, and "
            "this one reverts as soon as you turn it back off.")
        dot_row.pack_start(guest_toggle, False, False, 0)

    dot_row.set_halign(Gtk.Align.CENTER)
    root.pack_start(dot_row, False, False, 0)

    if not conn:
        root.pack_start(sep(), False, False, 4)
        root.pack_start(bitem(
            "No active network connection - server picker and Guest "
            "WiFi mode need one.", dim=True), False, False, 0)
        root.pack_start(status_lbl, False, False, 4)
        return root

    root.pack_start(sep(), False, False, 4)

    # ── DNS Server (umgezogen aus dem Internet-Widget) ───────────────
    root.pack_start(bsec("DNS SERVER"), False, False, 0)
    dns_entry = Gtk.Entry()
    dns_entry.set_text(_current_dns(conn))
    dns_entry.set_placeholder_text("e.g. 1.1.1.1, 1.0.0.1 (empty = Auto/DHCP)")
    # "Connection: X" stand vorher als eigene Zeile drüber - jetzt nur
    # noch als Tooltip, spart eine ganze Zeile.
    dns_entry.set_tooltip_text(f"Connection: {conn}  ·  Press Enter to apply")
    root.pack_start(dns_entry, False, False, 0)

    def _apply_dns_value(value: str):
        def _apply():
            ok, err = _set_dns(conn, value)
            if not ok:
                raise RuntimeError(err)
        apply_change("DNS servers", _apply, on_status=_flash)

    # Kein eigener "Apply DNS"-Knopf mehr - Presets wenden sofort an,
    # und Enter im Textfeld tut's auch (README-Feedback: "kein extra
    # Button").
    dns_entry.connect("activate", lambda _e: _apply_dns_value(dns_entry.get_text()))

    preset_row = hbox(6)
    preset_row.set_halign(Gtk.Align.CENTER)
    for plabel, pval in (("Auto (DHCP)", ""), ("Cloudflare", "1.1.1.1, 1.0.0.1"),
                         ("Google", "8.8.8.8, 8.8.4.4"),
                         ("Quad9", "9.9.9.9, 149.112.112.112")):
        pb = btn(plabel)
        def _on_preset(_b, v=pval):
            dns_entry.set_text(v)
            _apply_dns_value(v)
        pb.connect("clicked", _on_preset)
        preset_row.pack_start(pb, False, False, 0)
    root.pack_start(preset_row, False, False, 0)

    root.pack_start(status_lbl, False, False, 4)
    return root

def _network_content(win: Gtk.Window) -> Gtk.Box:
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── TAB 1: Networks ──────────────────────────────────────
    t1 = vbox(2); pad(t1, h=4, v=6)

    scan_b = Gtk.Button(label="󰑐")
    scan_b.set_relief(Gtk.ReliefStyle.NONE)
    scan_b.get_style_context().add_class("flat")
    scan_b.set_halign(Gtk.Align.CENTER)
    scan_b.set_tooltip_text("Scan for networks")

    note_lbl = Gtk.Label(label="")
    note_lbl.get_style_context().add_class("caption")
    note_lbl.set_opacity(0.7)
    t1.pack_start(note_lbl, False, False, 0)

    sw, net_box = scroll_box(240)
    t1.pack_start(sw, True, True, 0)

    # Reines Symbol statt Text-Button, unten mittig unter der
    # Netzwerkliste statt oben (README-Feedback: "Scanning entfernen -
    # nur das Symbol unten in der Mitte unter den Netzwerken").
    t1.pack_start(scan_b, False, False, 0)

    def _flash_note(text: str, ms: int = 3500):
        note_lbl.set_label(text)
        GLib.timeout_add(ms, lambda: (note_lbl.set_label(""), False)[1])

    def _show_connect_error(msg: str):
        d = Gtk.MessageDialog(transient_for=win, modal=True,
                               message_type=Gtk.MessageType.ERROR,
                               buttons=Gtk.ButtonsType.OK,
                               text="Connection Failed")
        d.set_name("wb-daemon-popup")
        d.set_keep_above(True)
        d.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        d.format_secondary_text((msg or "Unknown error")[:200])
        d.run(); d.destroy()

    def _populate(nets, eth_devs):
        for c in net_box.get_children(): net_box.remove(c)

        if eth_devs:
            net_box.pack_start(bsec("LAN"), False, False, 0)
            for d in eth_devs:
                connected = d["state"] == "connected"
                check = "  " if connected else ""
                label = f"{check}󰈀  {d['device']}"
                if d["connection"]:
                    label += f"  ({d['connection']})"
                b = btn(label, tip=f"Status: {d['state']}", active=connected)
                def _mk_eth(device, is_connected):
                    def _cb(_):
                        def _toggle():
                            if is_connected:
                                run(["nmcli", "dev", "disconnect", device])
                            else:
                                out, err, rc = run_ec(["nmcli", "dev", "connect", device], timeout=15)
                                if rc != 0:
                                    GLib.idle_add(_show_connect_error, err or out)
                            GLib.idle_add(_do_load)
                        in_thread(_toggle)
                    return _cb
                b.connect("clicked", _mk_eth(d["device"], connected))
                net_box.pack_start(b, False, False, 0)
            net_box.pack_start(sep(), False, False, 2)
            net_box.pack_start(bsec("WI-FI"), False, False, 0)

        if not nets:
            net_box.pack_start(bitem("No networks", dim=True), False, False, 0)
            net_box.show_all(); return
        for n in nets:
            check = "  " if n["active"] else ""
            lock  = " 󰌾" if n["secure"] else ""
            label = f"{check}{_sig_icon(n['signal'])}  {n['ssid'][:26]}{lock}"
            b = btn(label, tip=f"Signal: {n['signal']}%",
                    active=n["active"])
            def _mk(ssid, secure, active):
                def _cb(_):
                    if active:
                        def _disconnect():
                            dev = _wifi_dev_name()
                            if dev:
                                run(["nmcli", "dev", "disconnect", dev])
                            GLib.idle_add(_do_load)
                        in_thread(_disconnect)
                    else:
                        pw = _pw_dialog(win, ssid) if secure else ""
                        if pw is None: return
                        def _connect():
                            dev = _wifi_dev_name()
                            cmd = ["nmcli", "dev", "wifi", "connect", ssid]
                            if pw:
                                cmd += ["password", pw]
                            if dev:
                                cmd += ["ifname", dev]
                            out, err, rc = run_ec(cmd, timeout=15)
                            if rc != 0:
                                GLib.idle_add(_show_connect_error, err or out)
                            GLib.idle_add(_do_load)
                        in_thread(_connect)
                return _cb
            b.connect("clicked", _mk(n["ssid"], n["secure"], n["active"]))
            net_box.pack_start(b, False, False, 0)
        net_box.show_all()

    def _do_load():
        for c in net_box.get_children(): net_box.remove(c)
        net_box.pack_start(bitem("  Loading…", dim=True), False, False, 0)
        net_box.show_all()
        def _fetch():
            nets = _wifi_list()
            eth = _ethernet_devices()
            GLib.idle_add(_populate, nets, eth)
        in_thread(_fetch)

    def _do_scan(_):
        scan_b.set_label("󰑎"); scan_b.set_sensitive(False)
        def _scan():
            dev = _wifi_dev_name()
            cmd = ["nmcli", "dev", "wifi", "rescan"]
            if dev:
                cmd += ["ifname", dev]
            out, err, rc = run_ec(cmd, timeout=10)
            if rc != 0 and "not allowed" in (err or "").lower():
                GLib.idle_add(_flash_note, "Scan cooldown active — showing current list")
            time.sleep(3)
            GLib.idle_add(_populate, _wifi_list(), _ethernet_devices())
            GLib.idle_add(lambda: (scan_b.set_label("󰑐"),
                                   scan_b.set_sensitive(True), False)[2])
        in_thread(_scan)

    scan_b.connect("clicked", _do_scan)

    # Beim Öffnen NICHT nur den (oft leeren/veralteten) NetworkManager-
    # Cache zeigen und auf einen manuellen Scan-Klick warten - sofort
    # zeigen was schon bekannt ist, UND direkt automatisch im
    # Hintergrund nachscannen. Siehe Chat: "steht immer erst nach dem
    # Scan-Druck was da".
    _do_load()
    _do_scan(None)

    # ── TAB 2: Speed Test ─────────────────────────────────────
    # Läuft komplett automatisch und ohne sichtbaren Text: kein
    # Start-Knopf, kein "Running…"/"Ready" mehr. Start/Stop hängt
    # direkt am Tab-Wechsel (siehe _switch_tab weiter unten) und an
    # win "destroy", damit im Hintergrund nichts weiterläuft, sobald
    # der Speed-Test-Tab nicht mehr sichtbar ist.
    t2 = vbox(4); pad(t2, h=4, v=16)

    def _stat_row(icon: str) -> tuple[Gtk.Box, Gtk.Label]:
        row = vbox(2)
        row.set_halign(Gtk.Align.CENTER)
        icon_l = Gtk.Label(label=icon)
        icon_l.get_style_context().add_class("icon-lg")
        icon_l.set_opacity(0.75)
        icon_l.set_halign(Gtk.Align.CENTER)
        val_l = Gtk.Label(label="–")
        val_l.get_style_context().add_class("value-md")
        val_l.set_halign(Gtk.Align.CENTER)
        row.pack_start(icon_l, False, False, 0)
        row.pack_start(val_l, False, False, 0)
        return row, val_l

    # 󰐰 (Pulse) statt des alten Signal-Icons - eindeutiger als "Ping"
    # erkennbar und nicht mehr mit dem Wifi/Netzwerk-Icon verwechselbar.
    ping_row, ping_val = _stat_row("󰐰")
    down_row, down_val = _stat_row("󰇚")
    up_row,   up_val   = _stat_row("󰕒")

    # Alle drei nebeneinander statt untereinander.
    st_row = hbox(28)
    st_row.set_halign(Gtk.Align.CENTER)
    st_row.set_valign(Gtk.Align.CENTER)
    st_row.pack_start(ping_row, False, False, 0)
    st_row.pack_start(down_row, False, False, 0)
    st_row.pack_start(up_row, False, False, 0)
    # Oben/unten je ein dehnbarer Platzhalter statt fixer Ränder -
    # zentriert die 3 Werte im FREIEN Bereich des Tabs (also unterhalb
    # des Tab-Umschalters, der außerhalb von t2 liegt), egal wie viel
    # Höhe der Stack diesem Tab gerade zugesteht.
    t2.pack_start(Gtk.Box(), True, True, 0)
    t2.pack_start(st_row, False, False, 0)
    t2.pack_start(Gtk.Box(), True, True, 0)

    # KEINE "..." Punkte-Animation mehr - stattdessen bekommen die 3
    # Messwerte selbst eine langsame, sanfte Wellenbewegung (leicht
    # phasenversetzt rauf/runter) als Lebenszeichen, solange die
    # Dauerschleife läuft (README-Feedback: "die 2 Messungen übernehmen
    # das", "wie eine Welle leicht nach oben und unten animiert -
    # langsam").
    _st_wave_tid = [None]
    _st_wave_t = [0.0]
    _ST_WAVE_ROWS = (ping_row, down_row, up_row)

    def _st_wave_tick():
        _st_wave_t[0] += 0.12   # bewusst langsam
        for i, row in enumerate(_ST_WAVE_ROWS):
            phase = i * (2 * math.pi / 3)
            offset = math.sin(_st_wave_t[0] + phase) * 3.0   # ±3px, dezent
            row.set_margin_top(max(0, int(round(4 + offset))))
            row.set_margin_bottom(max(0, int(round(4 - offset))))
        return True

    def _st_dot_start():
        if _st_wave_tid[0] is not None:
            return
        _st_wave_tid[0] = GLib.timeout_add(60, _st_wave_tick)

    def _st_dot_stop():
        if _st_wave_tid[0] is not None:
            try: GLib.source_remove(_st_wave_tid[0])
            except Exception: pass
            _st_wave_tid[0] = None
        for row in _ST_WAVE_ROWS:
            row.set_margin_top(4)
            row.set_margin_bottom(4)

    # Fehler/Hinweise (z.B. "speedtest-cli fehlt") landen NUR noch als
    # Tooltip auf der Zeile - kein sichtbarer Text mehr im Tab.
    #
    # BUGFIX/Umbau (README-Feedback): lief vorher über EINEN
    # blockierenden 'speedtest-cli --json'-Aufruf, der alle 3 Werte
    # erst nach Abschluss des KOMPLETTEN Tests (Ping+Download+Upload,
    # oft 20-40s) auf einmal zurückgab, und dazwischen 45s Pause. Zwei
    # Probleme damit: 1) man sah 45+ Sekunden lang gar nichts, 2)
    # gelegentlich kam ein offensichtlich kaputter Wert raus (z.B. ein
    # 150000ms-Ping), der unkommentiert einfach so angezeigt wurde.
    # Jetzt: 'speedtest-cli' OHNE --json, Ausgabe zeilenweise MITLAUFEND
    # gelesen (wie bei _clamav_scan()/_tailscale_login_flow()) - Ping/
    # Download/Upload erscheinen dadurch JEWEILS SOFORT, sobald ihre
    # jeweilige Phase fertig ist, statt erst ganz am Ende alle
    # zusammen. Kein Warten mehr zwischen zwei Läufen - läuft in einer
    # Endlosschleife, solange der Tab offen ist (wie Ookla, nur ohne
    # festgelegtes Ende, siehe README-Feedback). Offensichtlicher
    # Messmüll (Ping über 2 Sekunden) wird verworfen statt angezeigt.
    _ST_PING_RE = re.compile(r"\]:\s*([\d.]+)\s*ms")
    _ST_DOWN_RE = re.compile(r"^Download:\s*([\d.]+)\s*Mbit/s", re.IGNORECASE)
    _ST_UP_RE   = re.compile(r"^Upload:\s*([\d.]+)\s*Mbit/s", re.IGNORECASE)
    _ST_MAX_SANE_PING_MS = 2000.0

    _st_active   = [False]
    _st_running  = [False]
    _st_gen      = [0]   # verhindert, dass ein überholter Lauf (z.B. nach schnellem Tab-Wechsel raus/rein) noch die UI eines neuen Laufs überschreibt
    # Server-ID nach dem ERSTEN Lauf cachen (README-Feedback: "dauert
    # immer noch sau lang bis er Zahlen zeigt") - der mit Abstand
    # größte Zeitfresser, BEVOR überhaupt die erste Zahl (Ping)
    # erscheint, ist NICHT die eigentliche Messung, sondern dass
    # speedtest-cli bei JEDEM Aufruf erst die komplette Serverliste holt
    # und mehrere Kandidaten anpingt, um den "besten" auszuwählen - das
    # allein kann schon 5-15s dauern, ohne dass währenddessen IRGENDWAS
    # angezeigt wird. Ab dem zweiten Lauf denselben Server per
    # '--server <id>' direkt wiederverwenden statt die Auswahl jedes
    # Mal neu zu wiederholen - in einer Dauerschleife (siehe unten,
    # "kein festgelegtes Ende") macht das ab dem zweiten Durchlauf einen
    # spürbaren Unterschied. Die Server-ID steht NUR im --json-Format
    # drin (die normale Textausgabe zeigt sie nirgends an) - deshalb
    # einmalig ein schneller --json-Probe-Aufruf MIT --no-download
    # --no-upload (überspringt die eigentliche Bandbreitenmessung, tut
    # nur Config+Serverauswahl+Ping), NICHT bei jeder Runde.
    _st_server_id = [None]

    def _st_discover_server_id():
        if _st_server_id[0]:
            return
        out, _err, ec = run_ec(
            ["speedtest-cli", "--secure", "--no-download", "--no-upload", "--json"],
            timeout=20)
        if ec == 0:
            try:
                _st_server_id[0] = str(json.loads(out)["server"]["id"])
            except Exception:
                pass

    def _st_run_once():
        if not _st_active[0] or _st_running[0]:
            return
        if not shutil.which("speedtest-cli"):
            st_row.set_tooltip_text("speedtest-cli not installed (pacman -S speedtest-cli)")
            return
        _st_running[0] = True
        _st_dot_start()
        _st_gen[0] += 1
        my_gen = _st_gen[0]

        def _worker():
            _st_discover_server_id()
            cmd = ["speedtest-cli", "--secure"]
            if _st_server_id[0]:
                cmd += ["--server", _st_server_id[0]]
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            except Exception as e:
                GLib.idle_add(lambda msg=str(e): (_st_on_done(my_gen, msg), False)[1])
                return
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                m = _ST_PING_RE.search(line)
                if m:
                    val = float(m.group(1))
                    if val <= _ST_MAX_SANE_PING_MS:
                        GLib.idle_add(lambda v=val: (_st_on_ping(my_gen, v), False)[1])
                    continue
                m = _ST_DOWN_RE.match(line)
                if m:
                    GLib.idle_add(lambda v=float(m.group(1)): (_st_on_download(my_gen, v), False)[1])
                    continue
                m = _ST_UP_RE.match(line)
                if m:
                    GLib.idle_add(lambda v=float(m.group(1)): (_st_on_upload(my_gen, v), False)[1])
            ec = proc.wait()
            err_txt = None if ec == 0 else f"exit code {ec}"
            GLib.idle_add(lambda: (_st_on_done(my_gen, err_txt), False)[1])

        in_thread(_worker)

    def _st_on_ping(gen: int, val: float):
        if gen != _st_gen[0] or not _st_active[0]:
            return
        ping_val.set_label(f"{val:.0f} ms")

    def _st_on_download(gen: int, val: float):
        if gen != _st_gen[0] or not _st_active[0]:
            return
        down_val.set_label(f"{val:.1f} Mbit/s")

    def _st_on_upload(gen: int, val: float):
        if gen != _st_gen[0] or not _st_active[0]:
            return
        up_val.set_label(f"{val:.1f} Mbit/s")

    def _st_on_done(gen: int, error):
        if gen != _st_gen[0]:
            return
        _st_running[0] = False
        _st_dot_stop()
        st_row.set_tooltip_text(f"Speed test failed: {error}" if error else None)
        if not _st_active[0]:
            return
        # Kein Timer-Delay mehr - direkt weiter zum nächsten Lauf.
        # Trotzdem via idle_add statt eines direkten Aufrufs, damit
        # ein pausenloser Fehlschlag-Loop (z.B. kein Internet) nicht
        # den Python-Call-Stack immer tiefer verschachtelt.
        GLib.idle_add(_st_run_once)

    def _start_speedtest_loop():
        if _st_active[0]:
            return
        _st_active[0] = True
        _st_run_once()

    def _stop_speedtest_loop():
        _st_active[0] = False
        _st_dot_stop()
        _st_gen[0] += 1   # verwaist jeden noch laufenden Worker sofort - dessen idle_add-Callbacks erkennen die veraltete Generation und tun nichts mehr

    win.connect("destroy", lambda *_: _stop_speedtest_loop())

    # ── Tabs zusammensetzen (gleiches Muster wie Media/Devices/Apps) ─
    stack.add_named(t1, "networks")
    stack.add_named(t2, "speedtest")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch_tab(name):
        _switch_stack(stack, win, name)
        if name == "speedtest":
            _start_speedtest_loop()
        else:
            _stop_speedtest_loop()
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, label in (("networks", "󰤨  Networks"),
                         ("speedtest", "󰓅  Speed Test")):
        b = btn(label, active=(name == "networks"))
        b.connect("clicked", lambda _b, n=name: _switch_tab(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)

    outer = vbox(4); safe_pad(outer, 380)
    outer.pack_start(tab_row, True, False, 2)
    outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack,   False, False, 0)
    return outer

def build_network(win: Gtk.Window):
    win.set_default_size(380, 1)
    win.add(_network_content(win))

# ════════════════════════════════════════════════════════════
#  BLUETOOTH
# ════════════════════════════════════════════════════════════
def _bt(cmd: str) -> str:
    return run(["bluetoothctl"] + cmd.split(), timeout=8)

def _bt_powered() -> bool:
    return "Powered: yes" in _bt("show")

def _bt_connected(mac: str) -> bool:
    return "Connected: yes" in _bt(f"info {mac}")

def _bt_devices(filter_arg: str = "") -> list:
    out = _bt(f"devices {filter_arg}".strip())
    res = []
    for line in out.splitlines():
        p = line.split(" ", 2)
        if len(p) >= 3 and p[0] == "Device":
            res.append({"mac": p[1], "name": p[2]})
    return res

def _bluetooth_content() -> Gtk.Box:
    root = vbox(4); safe_pad(root, 380)
    powered = [_bt_powered()]

    root.pack_start(btitle("󰂯  Bluetooth"), False, False, 0)
    root.pack_start(tab_sep(), False, False, 0)

    # Icon-only, oben links (Ein/Aus) / oben rechts (Scan) direkt unter
    # dem fetten Trennstrich - kein Text mehr, nur noch das Symbol.
    pwr_b  = btn("󰂯" if powered[0] else "󰂲", active=powered[0])
    pwr_b.set_tooltip_text("Bluetooth on/off")
    scan_b = btn("󰑐")
    scan_b.set_sensitive(powered[0])
    scan_b.set_tooltip_text("Scan for devices")

    hdr = hbox(6)
    hdr.pack_start(pwr_b, False, False, 0)
    hdr.pack_end(scan_b, False, False, 0)
    root.pack_start(hdr, False, False, 0)

    sw, dev_box = scroll_box(280)
    root.pack_start(sw, True, True, 0)

    def _refresh():
        for c in dev_box.get_children(): dev_box.remove(c)
        if not powered[0]:
            dev_box.pack_start(bitem("Bluetooth disabled", dim=True),
                               False, False, 0)
            dev_box.show_all(); return

        paired_macs = {d["mac"] for d in _bt_devices("Paired")}
        all_devs    = _bt_devices()
        paired      = [d for d in all_devs if d["mac"] in paired_macs]
        found       = [d for d in all_devs if d["mac"] not in paired_macs]

        # KEIN "KNOWN DEVICES"-Header mehr - bekannte/gekoppelte Geräte
        # stehen direkt oben in der Liste, ohne eigene Überschrift.
        for d in paired:
            conn = _bt_connected(d["mac"])
            row = hrow(sp=6)
            row.set_halign(Gtk.Align.CENTER)
            # Voller Name, KEIN Bluetooth-Icon mehr links - der Name
            # SELBST ist jetzt der Connect/Disconnect-Schalter (leuchtet
            # bei aktiver Verbindung), kein separater Button mehr dafür.
            name_b = btn(d["name"], active=conn)
            rm_b   = btn("󰆴", tip="Remove")

            def _mk_con(mac, c):
                def _cb(_):
                    in_thread(lambda: (
                        _bt(f"disconnect {mac}") if c else _bt(f"connect {mac}"),
                        GLib.idle_add(_refresh)))
                return _cb
            def _mk_rm(mac):
                return lambda _: in_thread(lambda: (
                    _bt(f"remove {mac}"), GLib.idle_add(_refresh)))
            name_b.connect("clicked", _mk_con(d["mac"], conn))
            rm_b.connect("clicked",  _mk_rm(d["mac"]))
            row.pack_start(name_b, False, False, 0)
            row.pack_start(rm_b, False, False, 0)
            dev_box.pack_start(row, False, False, 0)

        if found:
            # Unbekannte/nicht gekoppelte Geräte UNTER den bekannten,
            # MIT eigener Überschrift (im selben Stil, den vorher
            # "KNOWN DEVICES" hatte).
            dev_box.pack_start(bsec("UNKNOWN DEVICES"), False, False, 0)
            for d in found:
                pair_row = hrow(sp=6)
                pair_row.set_halign(Gtk.Align.CENTER)
                pair_b = btn("Pair")
                def _mk_pair(mac):
                    return lambda _: in_thread(lambda: (
                        _bt(f"pair {mac}"), _bt(f"connect {mac}"),
                        GLib.idle_add(_refresh)))
                pair_b.connect("clicked", _mk_pair(d["mac"]))
                pair_row.pack_start(bitem(d["name"]), False, False, 0)
                pair_row.pack_start(pair_b, False, False, 0)
                dev_box.pack_start(pair_row, False, False, 0)
        dev_box.show_all()

    def _on_power(_):
        def _do():
            _bt("power " + ("off" if powered[0] else "on"))
            powered[0] = not powered[0]
            # WICHTIG: derselbe Bug-Typ wie bei apply_all()/
            # _apply_bar_refresh - ein unindiziertes Tupel-Literal ist
            # in Python IMMER wahr, unabhängig vom Inhalt (auch ein
            # Tupel aus lauter None-Werten ist wahr, da Tupel-
            # Wahrheitswert an der LÄNGE hängt, nicht am Inhalt). GLib
            # hätte diesen Callback dadurch für immer erneut
            # aufgerufen - bei JEDEM Klick auf den Bluetooth-Ein/Aus-
            # Schalter ein ungedrosselter Busy-Loop, der zusätzlich
            # jedes Mal _refresh() (inkl. bluetoothctl-Subprozess-
            # Aufrufen) erneut angestoßen hätte. Explizit False
            # zurückgeben, damit die Idle-Source sich selbst entfernt.
            def _apply_ui():
                pwr_b.set_label("󰂯" if powered[0] else "󰂲")
                if powered[0]:
                    pwr_b.get_style_context().add_class("active")
                else:
                    pwr_b.get_style_context().remove_class("active")
                scan_b.set_sensitive(powered[0])
                _refresh()
                return False
            GLib.idle_add(_apply_ui)
        in_thread(_do)

    def _on_scan(_):
        scan_b.set_label("󰑎"); scan_b.set_sensitive(False)
        def _do():
            proc = subprocess.Popen(
                ["bluetoothctl", "scan", "on"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(2):
                time.sleep(7)
                GLib.idle_add(_refresh)
            proc.terminate()
            subprocess.Popen(["bluetoothctl", "scan", "off"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            GLib.idle_add(_refresh)
            GLib.idle_add(lambda: (scan_b.set_label("󰑐"),
                                   scan_b.set_sensitive(True), False)[2])
        in_thread(_do)

    pwr_b.connect("clicked",  _on_power)
    scan_b.connect("clicked", _on_scan)
    _refresh()
    return root

def build_bluetooth(win: Gtk.Window):
    win.set_default_size(380, 1)
    win.add(_bluetooth_content())

# ════════════════════════════════════════════════════════════
#  BRIGHTNESS
# ════════════════════════════════════════════════════════════
_nl_proc   = None
_nl_temp   = [3500]
_nl_active = [False]
_nl_lock       = threading.Lock()
_nl_generation = [0]

def _bright_pct() -> int:
    try:
        cur = int(run(["brightnessctl", "get"]))
        mx  = int(run(["brightnessctl", "max"]))
        return max(5, int(cur / mx * 100))
    except: return 50

def _nl_available() -> str | None:
    for cmd in ["gammastep", "hyprsunset", "wlsunset"]:
        if run(["which", cmd]): return cmd
    return None

def _nl_stop_locked():
    global _nl_proc
    if _nl_proc:
        try: _nl_proc.terminate()
        except: pass
        _nl_proc = None
    for c in [["pkill","gammastep"],["pkill","hyprsunset"],["pkill","wlsunset"]]:
        try: subprocess.run(c, capture_output=True, timeout=2)
        except: pass

def _nl_start(temp: int, gen: int = None):
    global _nl_proc
    if gen is None:
        gen = _nl_generation[0]
    with _nl_lock:
        if gen != _nl_generation[0]:
            return
        _nl_stop_locked()
        for cmd in [["gammastep",  "-O", str(temp)],
                    ["hyprsunset", "-t", str(temp)],
                    ["wlsunset",   "-t", str(temp),
                     "-T", "6500", "-l", "47.8", "-L", "16.2"]]:
            try:
                _nl_proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.3)
                if gen != _nl_generation[0]:
                    _nl_stop_locked()
                    return
                if _nl_proc.poll() is None: return
                _nl_proc = None
            except FileNotFoundError:
                continue

def _nl_stop():
    with _nl_lock:
        _nl_stop_locked()

def _kbd_backlight_device() -> str | None:
    import re
    out = run(["brightnessctl", "-l"])
    for line in out.splitlines():
        if "kbd_backlight" in line.lower():
            m = re.search(r"Device '([^']+)'", line)
            if m: return m.group(1)
    return None

def _kbd_bright_pct(device: str) -> int:
    cur = run(["brightnessctl", "-d", device, "g"])
    mx  = run(["brightnessctl", "-d", device, "m"])
    try:
        return int(int(cur) / max(int(mx), 1) * 100)
    except Exception:
        return 50

def _openrgb_available() -> bool:
    return bool(run(["which", "openrgb"]))

# ════════════════════════════════════════════════════════════
#  OpenRGB (pro-Gerät Helligkeit + Farbe für alle erkannten
#  RGB-Geräte - Tastatur, Maus, Mainboard, GPU, RAM, ...)
# ════════════════════════════════════════════════════════════
# Ersetzt den alten, einzelnen globalen Hue-Regler: openrgb-python
# verbindet sich mit dem OpenRGB-SDK-Server und liefert strukturierte
# Geräteobjekte (Name, Typ, Modi) statt CLI-Text parsen zu müssen.
# API-Verhalten wurde gegen die tatsächlich installierte openrgb-
# python-Bibliothek verifiziert (Quellcode gelesen): device.active_mode
# ist ein INDEX in device.modes, kein Objekt; Helligkeit wird nicht über
# eine eigene Methode gesetzt, sondern indem man das ModeData-Objekt
# des aktiven Modus mit geändertem .brightness erneut über
# device.set_mode() schickt.
_ORGB_PORT = 6742

def _openrgb_server_running() -> bool:
    """Prüft, ob der SDK-Server bereits lauscht, per einfachem TCP-
    Connect-Versuch (kein extra Tool/Paket nötig dafür)."""
    import socket as _socket
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", _ORGB_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()

def _openrgb_ensure_server() -> bool:
    """Startet den OpenRGB-SDK-Server bei Bedarf selbst im Hintergrund
    ('openrgb --server') - bewusst NICHT als dauerhafter systemd-
    Service, damit nichts unnötig im Hintergrund läuft, wenn man das
    Brightness-Widget gar nicht öffnet. Wartet kurz auf den
    Verbindungsaufbau, da der Serverstart selbst nicht synchron ist."""
    if _openrgb_server_running():
        return True
    if not _openrgb_available():
        return False
    run_bg(["openrgb", "--server", "--server-port", str(_ORGB_PORT)])
    for _ in range(20):  # bis zu ~4s warten
        time.sleep(0.2)
        if _openrgb_server_running():
            return True
    return False

def _openrgb_client():
    """Liefert einen verbundenen OpenRGBClient, oder None bei Fehler.
    Cached NICHT über mehrere Widget-Öffnungen hinweg - eine tote/
    abgelaufene Verbindung vom letzten Mal würde sonst bei jedem
    weiteren Öffnen sofort wieder fehlschlagen, ohne dass ein
    Neuverbindungsversuch stattfindet."""
    try:
        from openrgb import OpenRGBClient
    except ImportError:
        return None
    if not _openrgb_ensure_server():
        return None
    try:
        client = OpenRGBClient(address="127.0.0.1", port=_ORGB_PORT,
                                name="wb-daemon")
        return client
    except Exception:
        return None

def _openrgb_device_info(dev) -> dict:
    """Extrahiert die für die UI relevanten Infos aus einem
    openrgb-python Device-Objekt: aktueller Modus, ob der aktuell
    aktive Modus Helligkeit unterstützt (ModeFlags.HAS_BRIGHTNESS -
    NICHT jeder Modus tut das), und die aktuelle Farbe fürs
    Vorbelegen des Farbreglers."""
    from openrgb.utils import ModeFlags
    mode = dev.modes[dev.active_mode] if dev.modes else None
    has_brightness = bool(mode and mode.flags & ModeFlags.HAS_BRIGHTNESS)
    cur_color = dev.colors[0] if dev.colors else None
    return {
        "name": dev.name,
        "type": dev.type.name if hasattr(dev.type, "name") else str(dev.type),
        "has_brightness": has_brightness,
        "brightness": mode.brightness if has_brightness else None,
        "brightness_min": mode.brightness_min if has_brightness else 0,
        "brightness_max": mode.brightness_max if has_brightness else 100,
        "color_hex": (f"{cur_color.red:02x}{cur_color.green:02x}{cur_color.blue:02x}"
                      if cur_color else "ffffff"),
    }

def _openrgb_find_device(client, name: str):
    """Sucht ein Gerät über seinen NAMEN statt über einen rohen Index -
    laut openrgb-python-Doku ist der Listenindex nicht stabil über
    Verbindungen hinweg (kann sich ändern, wenn Geräte hinzukommen oder
    die Detektor-Reihenfolge wechselt). Name ist innerhalb einer
    laufenden Widget-Sitzung stabil genug."""
    for d in client.devices:
        if d.name == name:
            return d
    return None

def _openrgb_set_brightness(dev_name: str, value: int) -> None:
    """Läuft in einem Hintergrund-Thread - öffnet dafür eine EIGENE,
    kurzlebige Verbindung statt die UI-Ladeverbindung wiederzuverwenden,
    da diese in einem anderen Thread lief und openrgb-python-
    Verbindungen nicht als thread-safe dokumentiert sind."""
    client = _openrgb_client()
    if client is None:
        return
    dev = _openrgb_find_device(client, dev_name)
    if dev is None or not dev.modes:
        return
    mode = dev.modes[dev.active_mode]
    mode.brightness = value
    try:
        dev.set_mode(mode)
    except Exception:
        pass

def _openrgb_set_color(dev_name: str, hex_color: str) -> None:
    """Wie _openrgb_set_brightness, für Farbe. Setzt die Farbe des
    gesamten Geräts (alle LEDs gleich)."""
    from openrgb.utils import RGBColor
    client = _openrgb_client()
    if client is None:
        return
    dev = _openrgb_find_device(client, dev_name)
    if dev is None:
        return
    try:
        dev.set_color(RGBColor.fromHEX(hex_color))
    except Exception:
        pass

def _brightness_content(win: Gtk.Window) -> Gtk.Box:
    # Roadmap-Punkt "Brightness Rework": vorher eine einzige lange Liste
    # (Screen/Keyboard/RGB/Night Light untereinander) - jetzt 2 Tabs:
    # "Monitor" (Bildschirmhelligkeit + Night Light - beides betrifft
    # den/die Monitor(e) selbst) und "Devices" (Keyboard-Backlight + ALLE
    # RGB-Geräte inkl. evtl. RGB-Beleuchtung AN Monitoren - bewusst KEINE
    # dritte, eigene RGB-Tab, siehe README: "no extra tab for that").
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── TAB 1: Monitor (Bildschirmhelligkeit + Night Light) ──────────
    t1 = vbox(3); pad(t1, h=4, v=6)
    # KEIN Titel/Icon mehr - der Tab-Button "Monitor" sagt schon alles,
    # eine zusätzliche Überschrift wäre redundant.

    wallpaper_script = _resolve_wallpaper_script()

    def _on_wallpaper(_w):
        run_bg(["bash", wallpaper_script])

    # "Screen: 80%" ist jetzt EIN klickbares Label - Klick löst aus,
    # was vorher der separate Reroll-Icon-Button daneben gemacht hat
    # (Wallpaper neu würfeln). Kein Icon mehr am Slider darunter.
    screen_btn = bsec_btn(f"Screen: {_bright_pct()}%")
    screen_btn.set_tooltip_text("Click to reroll wallpaper")
    if not os.path.isfile(wallpaper_script):
        screen_btn.set_sensitive(False)
        screen_btn.set_tooltip_text(
            f"Wallpaper script not found in ~/.config/hypr "
            f"(looked for: {', '.join(_WALLPAPER_SCRIPT_CANDIDATES)})")
    screen_btn.connect("clicked", _on_wallpaper)
    t1.pack_start(screen_btn, False, False, 0)

    def _on_bright(s):
        val = int(s.get_value())
        screen_btn.set_label(f"SCREEN: {val}%")
        in_thread(run, ["brightnessctl", "set", f"{val}%"])
    bright_box, _ = bslider("", 5, 100, 1, _bright_pct(), cb=_on_bright, show_val=False)
    for ch in bright_box.get_children():
        if isinstance(ch, Gtk.Label):
            bright_box.remove(ch)
            break
    bright_box.set_halign(Gtk.Align.CENTER)
    bright_box.set_size_request(230, -1)
    t1.pack_start(bright_box, False, False, 0)

    # NIGHT LIGHT: das Label SELBST ist jetzt der An/Aus-Schalter -
    # kein "On"/"Off"-Text mehr daneben, leuchtet stattdessen einfach,
    # wenn aktiv. Zeigt die aktuelle Farbtemperatur gleich mit an.
    nl_tool = _nl_available()
    nl_btn = bsec_btn(f"Night Light: {_nl_temp[0]}K", active=_nl_active[0])
    if not nl_tool:
        nl_btn.set_sensitive(False)
        nl_btn.set_tooltip_text(
            "No night light tool found (gammastep/hyprsunset/wlsunset)")
    t1.pack_start(nl_btn, False, False, 0)

    _nl_debounce_id = [0]

    def _on_temp(s):
        _nl_temp[0] = int(s.get_value())
        nl_btn.set_label(f"NIGHT LIGHT: {_nl_temp[0]}K")
        if not _nl_active[0]:
            return
        _nl_generation[0] += 1
        gen = _nl_generation[0]
        if _nl_debounce_id[0]:
            GLib.source_remove(_nl_debounce_id[0])
        def _fire():
            _nl_debounce_id[0] = 0
            in_thread(_nl_start, _nl_temp[0], gen)
            return False
        _nl_debounce_id[0] = GLib.timeout_add(150, _fire)

    temp_box, temp_s = bslider(
        "", 1000, 6500, 100, _nl_temp[0], cb=_on_temp, show_val=False)
    for ch in temp_box.get_children():
        if isinstance(ch, Gtk.Label):
            temp_box.remove(ch)
            break
    temp_s.set_inverted(True)
    temp_box.set_halign(Gtk.Align.CENTER)
    temp_box.set_size_request(230, -1)
    t1.pack_start(temp_box, False, False, 0)

    def _on_nl(_w):
        if not nl_tool: return
        _nl_active[0] = not _nl_active[0]
        ctx = nl_btn.get_style_context()
        _nl_generation[0] += 1
        gen = _nl_generation[0]
        if _nl_active[0]:
            ctx.add_class("active"); in_thread(_nl_start, _nl_temp[0], gen)
        else:
            ctx.remove_class("active"); in_thread(_nl_stop)

    nl_btn.connect("clicked", _on_nl)

    # ── TAB 2: Devices (Keyboard-Backlight + alle RGB-Geräte) ────────
    t2 = vbox(3); pad(t2, h=4, v=6)
    # KEIN Titel mehr - gleiche Begründung wie im Monitor-Tab.

    kbd_dev = _kbd_backlight_device()
    kbd_section_shown = [False]
    if kbd_dev:
        kbd_hdr = bsec(f"Keyboard Backlight: {_kbd_bright_pct(kbd_dev)}%")
        kbd_lbl = kbd_hdr.get_children()[0]
        t2.pack_start(kbd_hdr, False, False, 0)
        def _on_kbd(s):
            val = int(s.get_value())
            kbd_lbl.set_label(f"KEYBOARD BACKLIGHT: {val}%")
            in_thread(run, ["brightnessctl", "-d", kbd_dev, "set", f"{val}%"])
        kbd_box, _ = bslider("", 0, 100, 1, _kbd_bright_pct(kbd_dev),
                              cb=_on_kbd, show_val=False)
        for ch in kbd_box.get_children():
            if isinstance(ch, Gtk.Label):
                kbd_box.remove(ch)
                break
        kbd_box.set_halign(Gtk.Align.CENTER)
        kbd_box.set_size_request(220, -1)
        t2.pack_start(kbd_box, False, False, 0)
        kbd_section_shown[0] = True

    # ── OpenRGB: ein Regler-Set PRO ERKANNTEM GERÄT (Keyboards, RGB-
    # Streifen, aber auch RGB-Beleuchtung AN Monitoren, falls über
    # OpenRGB erkannt - alles landet hier im Devices-Tab, keine eigene
    # RGB-Tab, siehe Docstring oben) ─────────────────────────────────
    # Jedes Gerät bekommt nur die Regler, die es laut seinem aktuell
    # aktiven Modus tatsächlich unterstützt - Farbe ist praktisch immer
    # verfügbar, Helligkeit nur wenn ModeFlags.HAS_BRIGHTNESS gesetzt
    # ist. Erkennung + SDK-Serverstart laufen komplett asynchron -
    # openrgb-python macht synchrone Netzwerk-Aufrufe, ein direkter
    # Aufruf im GTK-Main-Thread würde das Fenster einfrieren.
    rgb_section = vbox(3)
    t2.pack_start(rgb_section, False, False, 0)

    no_devices_lbl = bitem("No keyboard backlight or RGB devices found", dim=True)
    if not kbd_dev:
        t2.pack_start(no_devices_lbl, False, False, 0)

    def _build_rgb_device_row(info: dict) -> Gtk.Box:
        dev_name = info["name"]
        box = vbox(2)
        box.get_style_context().add_class("bubble")
        pad(box, h=8, v=6)
        name_text = f'{info["name"]} ({info["type"].title()})'
        if info["has_brightness"]:
            name_text += f': {info["brightness"] or 0}%'
        name_lbl = Gtk.Label(label=name_text)
        name_lbl.set_halign(Gtk.Align.CENTER)
        name_lbl.get_style_context().add_class("caption")
        box.pack_start(name_lbl, False, False, 0)

        debounce_id = [0]

        def _debounced(fn, *args, delay=200):
            if debounce_id[0]:
                GLib.source_remove(debounce_id[0])
            def _fire():
                debounce_id[0] = 0
                in_thread(fn, *args)
                return False
            debounce_id[0] = GLib.timeout_add(delay, _fire)

        if info["has_brightness"]:
            def _on_bri(s, n=dev_name):
                val = int(s.get_value())
                name_lbl.set_label(
                    f'{info["name"]} ({info["type"].title()}): {val}%')
                _debounced(_openrgb_set_brightness, n, val)
            bri_box, _ = bslider(
                "", info["brightness_min"], info["brightness_max"], 1,
                info["brightness"] or 0, cb=_on_bri, show_val=False)
            for ch in bri_box.get_children():
                if isinstance(ch, Gtk.Label):
                    bri_box.remove(ch)
                    break
            bri_box.set_halign(Gtk.Align.CENTER)
            bri_box.set_size_request(200, -1)
            box.pack_start(bri_box, False, False, 0)

        swatch_css = Gtk.CssProvider()

        def _apply_swatch_color(hexcol: str):
            swatch_css.load_from_data(
                f"#swatch{id(swatch_css)} {{ background-color: #{hexcol}; "
                f"min-width: 22px; min-height: 14px; border-radius: 4px; }}"
                .encode())

        def _on_color(_w, n=dev_name):
            dlg = Gtk.ColorChooserDialog(title="Choose color", transient_for=win)
            dlg.set_use_alpha(False)
            resp = dlg.run()
            if resp == Gtk.ResponseType.OK:
                rgba = dlg.get_rgba()
                hexcol = "{:02x}{:02x}{:02x}".format(
                    int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
                _apply_swatch_color(hexcol)
                _debounced(_openrgb_set_color, n, hexcol, delay=0)
            dlg.destroy()

        color_row = hbox(6)
        color_row.set_halign(Gtk.Align.CENTER)
        color_lbl = Gtk.Label(label="Color:")
        color_lbl.get_style_context().add_class("caption")
        color_btn = Gtk.Button()
        color_btn.get_style_context().add_class("bubble")
        color_btn.set_can_focus(False)
        swatch = Gtk.Label(label="")
        swatch.set_name(f"swatch{id(swatch_css)}")
        swatch.get_style_context().add_provider(
            swatch_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _apply_swatch_color(info["color_hex"])
        color_btn.add(swatch)
        color_btn.connect("clicked", _on_color)
        color_row.pack_start(color_lbl, False, False, 0)
        color_row.pack_start(color_btn, False, False, 0)
        box.pack_start(color_row, False, False, 0)

        return box

    def _load_rgb_devices():
        client = _openrgb_client()
        if client is None:
            return
        try:
            devices = [_openrgb_device_info(d) for d in client.devices]
        except Exception:
            devices = []

        def _apply():
            if not devices:
                return
            # Der "keine Geräte"-Platzhalter war nur für den Fall
            # "weder Keyboard-Backlight noch (bisher unbekannt) RGB"
            # gedacht - sobald hier tatsächlich RGB-Geräte eintrudeln,
            # muss er weg, sonst steht er sinnlos über der jetzt doch
            # nicht leeren Geräteliste.
            if no_devices_lbl.get_parent() is not None:
                t2.remove(no_devices_lbl)
            rgb_section.pack_start(sep(), False, False, 2)
            rgb_section.pack_start(bsec("RGB DEVICES"), False, False, 0)
            for info in devices:
                row = _build_rgb_device_row(info)
                rgb_section.pack_start(row, False, False, 0)
            rgb_section.show_all()
        GLib.idle_add(_apply)

    if _openrgb_available():
        in_thread(_load_rgb_devices)

    stack.add_named(t1, "monitor")
    stack.add_named(t2, "devices")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, label in (("monitor", "󰍹  Monitor"),
                         ("devices", "⌨  Devices")):
        b = btn(label, active=(name == "monitor"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("monitor")

    outer = vbox(4); safe_pad(outer, 360)
    outer.pack_start(tab_row, True, False, 2)
    outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack,   False, False, 0)
    return outer

def build_brightness(win: Gtk.Window):
    win.set_default_size(360, 1)
    win.add(_brightness_content(win))

# ════════════════════════════════════════════════════════════
#  BATTERY
# ════════════════════════════════════════════════════════════
def _bat() -> dict | None:
    bats = list(Path("/sys/class/power_supply").glob("BAT*"))
    if not bats: return None
    b = bats[0]
    try:
        cap    = int((b/"capacity").read_text().strip())
        status = (b/"status").read_text().strip()
        return {"cap": cap, "status": status}
    except: return None

def _battery_present() -> bool:
    """Reine Existenzprüfung (kein Wert-Parsing nötig) - Grundlage für
    den Akku-Tab-vs-System-Monitor-Umschalter im Settings-Widget.
    Bewusst dieselbe Quelle wie _bat() (BAT*-Glob unter sysfs), nicht
    z.B. 'upower -e', damit beide Funktionen bei "hat/hat keinen Akku"
    niemals auseinanderlaufen können."""
    return bool(list(Path("/sys/class/power_supply").glob("BAT*")))

def _bat_power_info() -> dict:
    """Aktueller Verbrauch (Watt) + Restlaufzeit über 'upower -i',
    NICHT über rohes sysfs-Parsen (power_now/current_now) - upower
    normalisiert bereits bekannte Treiber-Eigenheiten (manche Treiber
    liefern gar kein power_now, manche liefern negative Werte je nach
    Kernel-Version), das selbst nachzubauen wäre fehleranfälliger als
    ein bereits etabliertes Tool zu nutzen. Rückgabe: {"watts": float
    | None, "time_str": str | None} - beide None, falls upower fehlt
    oder das Gerät gerade keine Rate ausweist (z.B. "fully-charged")."""
    path = run(["bash", "-c", "upower -e 2>/dev/null | grep -i battery | head -1"])
    if not path:
        return {"watts": None, "time_str": None}
    out = run(["upower", "-i", path])
    watts = None
    time_str = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("energy-rate:"):
            m = re.search(r'([\d.,]+)\s*W', line)
            if m:
                try: watts = float(m.group(1).replace(",", "."))
                except ValueError: pass
        elif line.startswith("time to empty:") or line.startswith("time to full:"):
            time_str = line.split(":", 1)[1].strip()
            time_str += " bis leer" if "empty" in line else " bis voll"
    return {"watts": watts, "time_str": time_str}

def _bat_icon(cap: int, status: str) -> str:
    if "Charging" in status: return "󰂄"
    if cap >= 95: return "󰁹"
    if cap >= 80: return "󰂂"
    if cap >= 60: return "󰂀"
    if cap >= 40: return "󰁾"
    if cap >= 20: return "󰁼"
    return "󰁺"

_ppd_icons  = {"performance": "󱐋", "balanced": "󰗑", "power-saver": "󰌪"}
_ppd_labels = {"performance": "Performance",
               "balanced":    "Balanced",
               "power-saver": "Power Saver"}

_PPD_BUS_NAME = "net.hadess.PowerProfiles"
_PPD_OBJ_PATH = "/net/hadess/PowerProfiles"
_PPD_IFACE    = "net.hadess.PowerProfiles"

def _ppd_proxy() -> Gio.DBusProxy | None:
    """DBus-Proxy auf net.hadess.PowerProfiles - das ist die stabile,
    freedesktop-weite API, die sowohl power-profiles-daemon als auch
    tuned-ppd (und TLPs tlp-pd) implementieren. Bewusst NICHT über den
    'powerprofilesctl' Befehl, weil dieser Teil des power-profiles-
    daemon Pakets selbst ist - sobald das (z.B. durch den Conflict mit
    tuned-ppd) entfernt wird, verschwindet der Befehl mit, auch wenn
    ein kompatibler DBus-Dienst weiterhin läuft. Wird gecacht wäre
    riskant, falls der Dienst zwischenzeitlich neu startet - deshalb
    bewusst pro Aufruf neu geholt (billig, reiner DBus-Verbindungsauf-
    bau, kein Netzwerk)."""
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
            _PPD_BUS_NAME, _PPD_OBJ_PATH, _PPD_IFACE, None)
    except Exception:
        return None

def _ppd_available() -> list:
    """Liste der unterstützten Profile in fester Anzeige-Reihenfolge.
    Gibt [] zurück, wenn kein net.hadess.PowerProfiles-Dienst auf dem
    System-Bus läuft (weder ppd noch tuned-ppd noch tlp-pd aktiv)."""
    proxy = _ppd_proxy()
    if proxy is None:
        return []
    try:
        variant = proxy.get_cached_property("Profiles")
        if variant is None:
            return []
        entries = variant.unpack()  # list[dict] mit u.a. "Profile": str
        names = {e.get("Profile") for e in entries if "Profile" in e}
    except Exception:
        return []
    return [p for p in ["power-saver", "balanced", "performance"] if p in names]

def _ppd_current() -> str:
    """Aktuell aktives Profil, oder '' falls kein Dienst erreichbar."""
    proxy = _ppd_proxy()
    if proxy is None:
        return ""
    try:
        variant = proxy.get_cached_property("ActiveProfile")
        return variant.unpack() if variant is not None else ""
    except Exception:
        return ""

def _ppd_set(profile: str) -> None:
    """Setzt das aktive Profil per DBus-Property-Set - Äquivalent zu
    'powerprofilesctl set <profile>', nur ohne die Abhängigkeit vom
    powerprofilesctl-Binary. IMMER aus einem Hintergrund-Thread
    aufrufen (call_sync blockiert kurz)."""
    proxy = _ppd_proxy()
    if proxy is None:
        return
    try:
        proxy.call_sync(
            "org.freedesktop.DBus.Properties.Set",
            GLib.Variant("(ssv)", (_PPD_IFACE, "ActiveProfile", GLib.Variant("s", profile))),
            Gio.DBusCallFlags.NONE, -1, None)
    except Exception:
        pass

# ════════════════════════════════════════════════════════════
#  System-Monitor (Ersatz für den Akku-Tab auf Geräten ohne Akku,
#  z.B. Desktop-PCs - siehe _battery_present())
# ════════════════════════════════════════════════════════════
_POWER_HELPER_CACHE = {"path": None, "checked": False}

def _power_helper_path() -> str | None:
    """Pfad zum SUID-root-Helper (wb-power-helper), der NUR die RAPL-
    Datei liest - CPU-Package-Watt ist seit Kernel 5.10 root-only
    (PLATYPUS-CVE), der AMD-eigene amd_energy-Treiber dafür wurde vom
    Kernel-Maintainer entfernt, udev-Regeln helfen wegen der Symlink-
    Struktur nicht. Sucht an mehreren Kandidatenorten, darunter
    explizit dem waybar/scripts-Verzeichnis (dort liegen bei diesem
    Projekt auch die anderen Helper wie waybar_autohide, WidgetsDaemon.py
    selbst) - eine reine PATH-Suche allein reichte nicht, weil der
    systemd-User-Service nicht zwingend denselben PATH wie ein
    interaktives Terminal hat. Ergebnis wird gecacht - ändert sich
    nicht zur Laufzeit."""
    if not _POWER_HELPER_CACHE["checked"]:
        _POWER_HELPER_CACHE["checked"] = True
        candidates = [
            "/usr/local/bin/wb-power-helper",
            "/usr/bin/wb-power-helper",
            str(Path(HOME) / ".config" / "waybar" / "scripts" / "wb-power-helper"),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                _POWER_HELPER_CACHE["path"] = c
                break
        else:
            which = run(["which", "wb-power-helper"])
            if which:
                _POWER_HELPER_CACHE["path"] = which
    return _POWER_HELPER_CACHE["path"]

def _cpu_watts() -> float | None:
    """Liefert CPU-Package-Watt über den SUID-Helper, oder None falls
    der Helper fehlt/nicht ausführbar ist/RAPL nicht lesbar war -
    NIEMALS eine geschätzte Zahl (keine verlässliche Formel von CPU%
    auf Watt). Der Helper braucht ca. 200ms - deshalb IMMER aus einem
    Hintergrund-Thread aufrufen, nie direkt im GTK-Main-Thread."""
    helper = _power_helper_path()
    if not helper:
        return None
    out, _err, ec = run_ec([helper], timeout=2)
    if ec != 0 or not out:
        return None
    try:
        return float(out.strip())
    except ValueError:
        return None

# ────────────────────────────────────────────────────────────
#  Gaming Mode: CPU Core-Performance-Boost aus/an (siehe Chat-
#  Historie - schaltet einen Teil des CPU-Power-Budgets Richtung
#  APU-GPU um). Bewusst über Polkit/pkexec statt SUID (Schreib-
#  zugriff, nicht nur Lesen wie bei _cpu_watts()) - siehe
#  com.trafktux.wbdaemon.cpuboost.policy + wb-cpuboost-helper.
# ────────────────────────────────────────────────────────────
_CPU_BOOST_SYSFS = Path("/sys/devices/system/cpu/cpufreq/boost")
_CPUBOOST_HELPER_CACHE = {"path": None, "checked": False}

def _cpuboost_helper_path() -> str | None:
    """Analog zu _power_helper_path(), nur für wb-cpuboost-helper -
    dieser braucht KEIN SUID-Bit (wird über pkexec aufgerufen), muss
    aber trotzdem ausführbar sein und an einem der Kandidatenpfade
    liegen (der Polkit-Policy-Annotation-Pfad ist fest auf
    /usr/local/bin/wb-cpuboost-helper eingestellt - die anderen
    Kandidaten hier sind nur Fallbacks für die reine Existenzprüfung/
    Anzeige im Widget, pkexec selbst nutzt immer den festen Pfad aus
    der .policy-Datei)."""
    if not _CPUBOOST_HELPER_CACHE["checked"]:
        _CPUBOOST_HELPER_CACHE["checked"] = True
        candidates = [
            "/usr/local/bin/wb-cpuboost-helper",
            "/usr/bin/wb-cpuboost-helper",
            str(Path(HOME) / ".config" / "waybar" / "scripts" / "wb-cpuboost-helper"),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                _CPUBOOST_HELPER_CACHE["path"] = c
                break
        else:
            which = run(["which", "wb-cpuboost-helper"])
            if which:
                _CPUBOOST_HELPER_CACHE["path"] = which
    return _CPUBOOST_HELPER_CACHE["path"]

def _cpu_boost_supported() -> bool:
    return _CPU_BOOST_SYSFS.is_file()

def _cpu_boost_enabled() -> bool | None:
    """Liest den Boost-Zustand - reiner Read, IMMER ohne Root möglich
    (der sysfs-Knoten selbst ist world-readable, nur das SCHREIBEN
    braucht Root - anders als die RAPL-Watt-Datei, die komplett
    root-only ist). None = Kernel/CPU unterstützt keinen Boost-Toggle
    (z.B. manche Intel-Systeme mit anderem Mechanismus)."""
    try:
        return _CPU_BOOST_SYSFS.read_text().strip() == "1"
    except Exception:
        return None

def _set_cpu_boost(enabled: bool) -> tuple[bool, str]:
    """Setzt den Boost-Zustand über pkexec + wb-cpuboost-helper. Zeigt
    bei fehlendem Helper eine klare Fehlermeldung statt eines stillen
    No-Ops - IMMER aus einem Hintergrund-Thread aufrufen (pkexec kann
    auf den Polkit-Auth-Dialog warten, blockiert also potenziell
    länger als ein kurzer Systemaufruf)."""
    if not _cpu_boost_supported():
        return False, "CPU/Kernel unterstützt keinen Boost-Toggle auf diesem System."
    helper = _cpuboost_helper_path()
    if not helper:
        return False, "wb-cpuboost-helper nicht gefunden (siehe com.trafktux.wbdaemon.cpuboost.policy)."
    _out, err, ec = run_ec(["pkexec", helper, "1" if enabled else "0"], timeout=30)
    if ec != 0:
        # ec=126/127 typischerweise: Nutzer hat den Polkit-Dialog
        # abgebrochen bzw. nicht autorisiert - das ist kein Bug,
        # einfach als normale Fehlermeldung durchreichen.
        return False, err or "pkexec/wb-cpuboost-helper fehlgeschlagen (abgebrochen oder nicht autorisiert)."
    return True, ""

# ────────────────────────────────────────────────────────────
#  Akku sparen: sämtliche Compositor-Effekte (Animationen, Schatten,
#  Blur, hyprglass, dynamic_cursors) live aus-/wieder einschalten.
#
#  WICHTIG (siehe Chat-Verlauf): 'hyprctl keyword ...' und 'hyprctl -j
#  getoption ...' sind seit Hyprland 0.55 (Lua-Config) nur noch ein
#  Legacy-Kompat-Shim für hyprlang/.conf-Setups - bei uns (echte
#  hyprland.lua) nimmt 'keyword' den Aufruf zwar mit exit 0 an, der
#  Wert ändert sich aber nachweislich NICHT (siehe Debug-Log: direkt
#  danach nochmal gelesen -> unverändert). Die offiziell dokumentierte
#  Methode für Live-Änderungen bei Lua-Configs ist stattdessen
#  'hyprctl eval "<lua>"', das denselben hl.*-Code ausführt wie
#  hyprland.lua selbst (siehe wiki.hypr.land/Configuring/Advanced-and-
#  Cool/Using-hyprctl). Deshalb hier komplett auf eval umgestellt.
#
#  Für den Restore-Zustand brauchen wir den *ursprünglich konfigurier-
#  ten* Wert - da getoption unzuverlässig ist, wird der stattdessen
#  direkt aus hyprland.lua herausgelesen (exakt dasselbe Prinzip wie
#  bei _cursor_plugin_enabled() oben), NICHT blind auf 1/true
#  angenommen (blur ist z.B. by default AUS, nicht an - siehe unten).
# ────────────────────────────────────────────────────────────
_EFFECTS_BATTERY_STATE = Path(HOME) / ".cache" / "hypr" / "wb_effects_saved.json"
_EFFECTS_BATTERY_LOG   = Path(HOME) / ".cache" / "hypr" / "wb_effects_debug.log"

def _effects_log(line: str) -> None:
    """Reines Debug-Logging - bei Problemen einfach
    ~/.cache/hypr/wb_effects_debug.log anschauen."""
    try:
        _EFFECTS_BATTERY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_EFFECTS_BATTERY_LOG, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
    except Exception:
        pass

def effects_battery_active() -> bool:
    return _EFFECTS_BATTERY_STATE.is_file()

def _hypr_eval(lua_code: str) -> tuple[str, str, int]:
    """Führt Lua gegen die echte hl.*-API aus - siehe Kommentar oben.
    Gibt bei Erfolg 'ok' zurück, bei Lua-Fehlern eine echte
    Fehlermeldung (anders als 'keyword', das Fehler oft verschluckt)."""
    return run_ec(["hyprctl", "eval", lua_code], timeout=3)

# (Anker-Regex im hyprland.lua-Text, jeweils GENAU 1x im File vorhanden
#  - siehe Chat, gegen die echte Datei verifiziert) -> (Default-Fallback,
#  falls das Muster mal nicht gefunden wird)
# WICHTIG: 'shadow' bewusst NICHT hier drin - das ist der goldene
# Fenster-Glow (color = rgba(fff495ff) in hyprland.lua), der soll beim
# Akku sparen erhalten bleiben, siehe Chat. Stattdessen wird die
# Fenster-Transparenz ausgeschaltet (auf 1.0 = voll opak) - das kostet
# beim Compositing tatsächlich mehr als ein reiner Schatten.
_EFFECTS_LUA_ANCHORS = {
    "blur":             (r'blur\s*=\s*\{\s*enabled\s*=\s*(true|false)', False),
    "hyprglass":        (r'hg\.config\(\{\s*enabled\s*=\s*(true|false)', True),
    "dynamic_cursors":  (r'dynamic_cursors\s*=\s*\{\s*enabled\s*=\s*(true|false)', True),
}
_EFFECTS_OPACITY_ANCHORS = {
    "active_opacity":   (r'active_opacity\s*=\s*([\d.]+)', 1.0),
    "inactive_opacity": (r'inactive_opacity\s*=\s*([\d.]+)', 1.0),
}

def _lua_bool_default(name: str) -> bool:
    pattern, fallback = _EFFECTS_LUA_ANCHORS[name]
    try:
        txt = _hypr_lua_path().read_text()
        m = re.search(pattern, txt)
        if m:
            return m.group(1) == "true"
    except Exception:
        pass
    return fallback

def _lua_float_default(name: str) -> float:
    pattern, fallback = _EFFECTS_OPACITY_ANCHORS[name]
    try:
        txt = _hypr_lua_path().read_text()
        m = re.search(pattern, txt)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return fallback

def _lua_bool(v: bool) -> str:
    return "true" if v else "false"

def _effects_battery_enable_impl() -> None:
    _effects_log("=== effects_battery_enable() (eval-basiert) ===")
    saved = {
        "animations":      True,  # kein statischer Default-Block in hyprland.lua -
                                   # Hyprland-interner Default ist an.
        "blur":            _lua_bool_default("blur"),
        "hyprglass":       _lua_bool_default("hyprglass"),
        "dynamic_cursors": _lua_bool_default("dynamic_cursors"),
        "active_opacity":   _lua_float_default("active_opacity"),
        "inactive_opacity": _lua_float_default("inactive_opacity"),
    }
    for k, v in saved.items():
        _effects_log(f"Default aus hyprland.lua gelesen: {k} = {v}")

    try:
        _EFFECTS_BATTERY_STATE.parent.mkdir(parents=True, exist_ok=True)
        _EFFECTS_BATTERY_STATE.write_text(json.dumps(saved))
    except Exception as e:
        _effects_log(f"Snapshot schreiben fehlgeschlagen: {e}")

    calls = [
        ("animations",      'hl.config({ animations = { enabled = false } })'),
        ("blur",            'hl.config({ decoration = { blur = { enabled = false } } })'),
        ("hyprglass",       'if hl.plugin.hyprglass then hl.plugin.hyprglass.config({ enabled = false }) end'),
        ("dynamic_cursors", 'if hl.plugin.dynamic_cursors then hl.config({ plugin = { dynamic_cursors = { enabled = false } } }) end'),
        ("opacity",         'hl.config({ decoration = { active_opacity = 1.0, inactive_opacity = 1.0 } })'),
    ]
    for name, lua in calls:
        out, err, ec = _hypr_eval(lua)
        _effects_log(f"eval[{name}] '{lua}' -> exit {ec}, out={out.strip()!r}{'  STDERR: ' + err if err else ''}")

def effects_battery_enable() -> None:
    """Wrapper mit Top-Level try/except - JEDE Exception hier landet
    mit vollem Traceback im Debug-Log, statt den Hintergrund-Thread
    lautlos sterben zu lassen."""
    try:
        _effects_battery_enable_impl()
    except Exception:
        _effects_log("!!! AUSNAHME in effects_battery_enable():\n" + traceback.format_exc())

def _effects_battery_disable_impl() -> None:
    _effects_log("=== effects_battery_disable() (eval-basiert) ===")
    saved: dict = {}
    try:
        saved = json.loads(_EFFECTS_BATTERY_STATE.read_text())
    except Exception as e:
        _effects_log(f"Snapshot lesen fehlgeschlagen: {e}")

    calls = [
        ("animations",      f'hl.config({{ animations = {{ enabled = {_lua_bool(saved.get("animations", True))} }} }})'),
        ("blur",            f'hl.config({{ decoration = {{ blur = {{ enabled = {_lua_bool(saved.get("blur", False))} }} }} }})'),
        ("hyprglass",       f'if hl.plugin.hyprglass then hl.plugin.hyprglass.config({{ enabled = {_lua_bool(saved.get("hyprglass", True))} }}) end'),
        ("dynamic_cursors", f'if hl.plugin.dynamic_cursors then hl.config({{ plugin = {{ dynamic_cursors = {{ enabled = {_lua_bool(saved.get("dynamic_cursors", True))} }} }} }}) end'),
        ("opacity",         f'hl.config({{ decoration = {{ active_opacity = {saved.get("active_opacity", 0.9865)}, inactive_opacity = {saved.get("inactive_opacity", 0.85)} }} }})'),
    ]
    for name, lua in calls:
        out, err, ec = _hypr_eval(lua)
        _effects_log(f"eval[{name}] '{lua}' -> exit {ec}, out={out.strip()!r}{'  STDERR: ' + err if err else ''}")

    try:
        _EFFECTS_BATTERY_STATE.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass

def effects_battery_disable() -> None:
    """Wrapper mit Top-Level try/except, siehe effects_battery_enable()."""
    try:
        _effects_battery_disable_impl()
    except Exception:
        _effects_log("!!! AUSNAHME in effects_battery_disable():\n" + traceback.format_exc())

def _amdgpu_paths() -> dict:
    """Findet den ersten amdgpu-Kartenordner + dessen hwmon-Unterordner
    (Nummer wie 'hwmon3' ist nicht vorhersagbar, wird pro Boot vom
    Kernel vergeben - deshalb hier per glob statt fest kodiert
    gesucht). Bewusst NICHT gecacht, trotz kleinem wiederkehrendem
    glob-Aufwand - riskant, falls sich das zwischen Boots ändert und
    der Daemon lange läuft."""
    for card in sorted(Path("/sys/class/drm").glob("card*")):
        vendor_f = card / "device" / "vendor"
        if not vendor_f.is_file():
            continue
        try:
            if vendor_f.read_text().strip() != "0x1002":  # AMD PCI Vendor-ID
                continue
        except Exception:
            continue
        hwmon_dirs = list((card / "device" / "hwmon").glob("hwmon*")) \
            if (card / "device" / "hwmon").is_dir() else []
        return {"card": card, "hwmon": hwmon_dirs[0] if hwmon_dirs else None}
    return {}

def _gpu_stats() -> dict:
    """AMD-GPU Auslastung/Temperatur/Watt rein über sysfs, kein extra
    Tool (radeontop/rocm-smi) nötig. gpu_busy_percent und die hwmon-
    Werte sind normalerweise world-readable (im Gegensatz zu RAPL),
    daher hier explizit NICHT über den SUID-Helper, sondern direkt
    gelesen."""
    paths = _amdgpu_paths()
    if not paths:
        return {}
    result = {}
    try:
        busy_f = paths["card"] / "device" / "gpu_busy_percent"
        if busy_f.is_file():
            result["busy_pct"] = int(busy_f.read_text().strip())
    except Exception:
        pass
    hwmon = paths.get("hwmon")
    if hwmon:
        try:
            temp_f = hwmon / "temp1_input"
            if temp_f.is_file():
                result["temp_c"] = int(temp_f.read_text().strip()) / 1000.0
        except Exception:
            pass
        for power_file in ("power1_average", "power1_input"):
            try:
                p_f = hwmon / power_file
                if p_f.is_file():
                    result["watts"] = int(p_f.read_text().strip()) / 1e6
                    break
            except Exception:
                pass
    return result

def _cpu_temp() -> float | None:
    """CPU-Temperatur über psutil (kapselt bereits das Suchen im
    richtigen hwmon/coretemp-Sensor-Eintrag plattformübergreifend)."""
    try:
        import psutil
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    for key in ("k10temp", "coretemp", "zenpower"):
        if key in temps and temps[key]:
            return temps[key][0].current
    for entries in temps.values():
        if entries:
            return entries[0].current
    return None

def _extra_disks() -> list:
    """Alle gemounteten Dateisysteme AUSSER der Haupt-/-Partition (die
    hat schon ihre eigene STORAGE-Zeile in _sysmon_content()) - externe
    SSDs/USB-Sticks, eingehängte ISOs (Loop-Devices), Disketten,
    zweite interne Laufwerke usw. (Roadmap: "System Monitor add
    dynamic storage like external ssds, eingehängte ISOs, Floppy
    Disks, etc")."""
    import psutil
    out = []
    seen_mounts = set()
    try:
        partitions = psutil.disk_partitions(all=True)
    except Exception:
        return out
    for p in partitions:
        mnt = p.mountpoint
        if not mnt or mnt == "/" or mnt in seen_mounts:
            continue
        # Pseudo-/virtuelle Dateisysteme rausfiltern (proc, sysfs,
        # tmpfs für /run & co, cgroup, devtmpfs, ...) - technisch auch
        # "gemountet", aber kein Storage im Sinne dieses Roadmap-
        # Punkts, würden die Liste nur zumüllen.
        if p.fstype in ("proc", "sysfs", "devtmpfs", "cgroup", "cgroup2",
                        "tmpfs", "devpts", "securityfs", "pstore",
                        "bpf", "tracefs", "mqueue", "hugetlbfs",
                        "debugfs", "configfs", "fusectl", "autofs",
                        "binfmt_misc", "efivarfs", "overlay", "squashfs"):
            continue
        # Mounts, die zur Hauptinstallation selbst gehören (/boot,
        # /var, /home als eigene Partition, ...) sind kein
        # "zusätzlicher/dynamischer" Storage im Sinne des Roadmap-
        # Punkts - der interessiert sich für Dinge, die NACH dem Boot
        # dazukommen/verschwinden (typischerweise unter /run/media,
        # /media, /mnt).
        if mnt.startswith(("/boot", "/var", "/home", "/usr", "/etc",
                           "/opt", "/srv", "/snap", "/nix")):
            continue
        try:
            usage = psutil.disk_usage(mnt)
        except (PermissionError, OSError):
            # Laufwerk ohne eingelegtes Medium (z.B. leeres Floppy-/
            # CD-Laufwerk) wirft hier meist genau das - lieber
            # überspringen als mit falschen Werten auflisten.
            continue
        seen_mounts.add(mnt)
        out.append({
            "mount": mnt,
            "device": p.device,
            "fstype": p.fstype,
            "is_iso": p.fstype in ("iso9660", "udf"),
            "removable": mnt.startswith(("/run/media", "/media", "/mnt")),
            "total": usage.total, "used": usage.used, "percent": usage.percent,
        })
    return out

def _sysmon_snapshot() -> dict:
    """Ein Aufruf, der ALLE System-Monitor-Metriken auf einmal liefert
    - wird IMMER aus einem Hintergrund-Thread aufgerufen. psutil.
    cpu_percent(interval=0.3) blockiert selbst schon absichtlich kurz
    (misst über ein Zeitfenster)."""
    import psutil
    return {
        "cpu_pct":  psutil.cpu_percent(interval=0.3),
        "ram":      psutil.virtual_memory(),
        "swap":     psutil.swap_memory(),
        "disk":     psutil.disk_usage("/"),
        "disks_extra": _extra_disks(),
        "cpu_temp": _cpu_temp(),
        "cpu_watts": _cpu_watts(),
        "gpu":      _gpu_stats(),
    }

def _akku_content(win: Gtk.Window) -> Gtk.Box:
    root = vbox(3); pad(root, h=4, v=6)
    # KEIN Titel mehr - die 2 Sub-Tabs "Battery"/"Profile" sagen schon,
    # was hier ist.

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    t_bat  = vbox(1); pad(t_bat, h=4, v=4)
    t_prof = vbox(4); pad(t_prof, h=4, v=4)

    # ── Sub-Tab: Battery ─────────────────────────────────────────
    # Icon+Prozent übereinander statt in einer 3-Spalten-Zeile, beides
    # vergrößert - kein separater "Charging/Discharging"-Text mehr,
    # das übernimmt jetzt das Icon selbst (_bat_icon() wählt je nach
    # Status ohnehin schon ein anderes Symbol). Watt-Verbrauch steht
    # direkt darunter statt seitlich daneben.
    center_box = vbox(0)
    center_box.set_halign(Gtk.Align.CENTER)

    icon_pct_row = hbox(6)
    icon_pct_row.set_halign(Gtk.Align.CENTER)
    bat_icon_lbl = Gtk.Label(label="")
    bat_icon_lbl.get_style_context().add_class("icon-xl")
    bat_pct_lbl  = Gtk.Label(label="–")
    bat_pct_lbl.get_style_context().add_class("value-lg")
    icon_pct_row.pack_start(bat_icon_lbl, False, False, 0)
    icon_pct_row.pack_start(bat_pct_lbl,  False, False, 0)
    center_box.pack_start(icon_pct_row, False, False, 0)

    power_lbl = Gtk.Label(label="")
    power_lbl.get_style_context().add_class("caption")
    power_lbl.set_halign(Gtk.Align.CENTER)
    power_lbl.set_no_show_all(True)
    center_box.pack_start(power_lbl, False, False, 0)

    t_bat.pack_start(center_box, False, False, 0)

    _power_fetch_in_flight = [False]

    def _refresh_bat():
        info = _bat()
        if info:
            bat_icon_lbl.set_label(_bat_icon(info["cap"], info["status"]))
            bat_pct_lbl.set_label(f'{info["cap"]} %')
            bat_icon_lbl.set_tooltip_text(info["status"])
            if not _power_fetch_in_flight[0]:
                _power_fetch_in_flight[0] = True
                def _fetch_power():
                    try:
                        p = _bat_power_info()
                        def _apply():
                            # Nur die Watt-Zahl steht sichtbar da, das
                            # "X days bis leer" wandert in den Tooltip -
                            # spart Platz, ohne die Info zu verlieren.
                            if p["watts"] is not None:
                                power_lbl.set_label(f'{p["watts"]:.1f} W')
                                power_lbl.set_tooltip_text(p["time_str"] or None)
                                power_lbl.show()
                            else:
                                power_lbl.hide()
                        GLib.idle_add(_apply)
                    finally:
                        _power_fetch_in_flight[0] = False
                in_thread(_fetch_power)
        else:
            bat_icon_lbl.set_label("󰂑")
            bat_pct_lbl.set_label("No Battery")
            bat_icon_lbl.set_tooltip_text(None)
            power_lbl.hide()
        return True

    add_timer(10000, _refresh_bat)
    _refresh_bat()

    # ── Sub-Tab: Profile ──────────────────────────────────────────
    # Einfach die 5 Profil-Buttons rein, ohne eigene Überschrift - der
    # Sub-Tab-Reiter "Profile" sagt schon, was das ist.
    pp_section = vbox(4)
    t_prof.pack_start(pp_section, False, False, 0)
    pp_section.pack_start(bitem("Loading…", dim=True), False, False, 0)
    pp_section.show_all()

    def _build_pp_row(profiles: list, current: str):
        for c in pp_section.get_children():
            pp_section.remove(c)
        pp_btns: dict = {}
        if profiles:
            pp_row = hbox(6)
            pp_row.set_halign(Gtk.Align.CENTER)
            for pr in profiles:
                b = btn(_ppd_icons.get(pr, "󰗑"),
                        active=(pr == current),
                        tip=_ppd_labels.get(pr, pr))
                b.get_style_context().add_class("icon-lg")
                def _mk(profile):
                    def _cb(_):
                        in_thread(_ppd_set, profile)
                        for p2, b2 in pp_btns.items():
                            ctx = b2.get_style_context()
                            if p2 == profile: ctx.add_class("active")
                            else:             ctx.remove_class("active")
                    return _cb
                pp_btns[pr] = b
                b.connect("clicked", _mk(pr))
                pp_row.pack_start(b, False, False, 0)
            pp_section.pack_start(pp_row, False, False, 0)
        else:
            pp_section.pack_start(
                bitem("No power profile service found", dim=True),
                False, False, 0)
        pp_section.show_all()

    gm_fx_row = hbox(6)
    gm_fx_row.set_halign(Gtk.Align.CENTER)

    gm_btn = btn("🎮", tip="Gaming Mode: performance profile + CPU boost off")
    fx_btn = btn("🔋", active=effects_battery_active(),
                 tip="Save power: turn off animations, blur, shadow, hyprglass & cursor effects")
    gm_fx_row.pack_start(gm_btn, False, False, 0)
    gm_fx_row.pack_start(fx_btn, False, False, 0)
    t_prof.pack_start(gm_fx_row, False, False, 0)

    if not _cpu_boost_supported():
        gm_btn.set_sensitive(False)
        gm_btn.set_tooltip_text("CPU boost toggle not supported on this system.")
    else:
        gm_state = {"on": _cpu_boost_enabled() is False}

        def _refresh_gm():
            ctx = gm_btn.get_style_context()
            if gm_state["on"]: ctx.add_class("active")
            else:              ctx.remove_class("active")
        _refresh_gm()

        def _on_gm_toggle(_w):
            turning_on = not gm_state["on"]
            gm_state["on"] = turning_on
            _refresh_gm()  # sofortiges visuelles Feedback, siehe _on_dark_toggle-Muster

            def _worker():
                if turning_on:
                    _ppd_set("performance")
                    ok, err = _set_cpu_boost(False)
                else:
                    ok, err = _set_cpu_boost(True)
                if not ok:
                    def _revert():
                        gm_state["on"] = not turning_on
                        _refresh_gm()
                        gm_btn.set_tooltip_text(f"Error: {err}")
                    GLib.idle_add(_revert)
            in_thread(_worker)

        gm_btn.connect("clicked", _on_gm_toggle)

    def _refresh_fx(active: bool):
        ctx = fx_btn.get_style_context()
        if active: ctx.add_class("active")
        else:      ctx.remove_class("active")
    _refresh_fx(effects_battery_active())

    def _on_fx_toggle(_w):
        turning_on = not effects_battery_active()
        _refresh_fx(turning_on)  # sofortiges Feedback, echte hyprctl-Aufrufe laufen im Hintergrund
        def _worker():
            if turning_on:
                effects_battery_enable()
            else:
                effects_battery_disable()
        in_thread(_worker)

    fx_btn.connect("clicked", _on_fx_toggle)

    def _load_pp():
        profiles = _ppd_available()
        current  = _ppd_current() if profiles else ""
        GLib.idle_add(_build_pp_row, profiles, current)

    in_thread(_load_pp)

    # ── 2 Sub-Tabs zusammensetzen: "Battery" (das Grad) / "Profile" ──
    stack.add_named(t_bat, "battery")
    stack.add_named(t_prof, "profile")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch_akku_tab(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for tname, tlabel in (("battery", "Battery"), ("profile", "Profile")):
        tb = btn(tlabel, active=(tname == "battery"))
        tb.connect("clicked", lambda _b, n=tname: _switch_akku_tab(n))
        tab_btns[tname] = tb
        tab_row.pack_start(tb, False, False, 0)
    stack.set_visible_child_name("battery")

    root.pack_start(tab_row, True, False, 2)
    root.pack_start(tab_sep(), False, False, 0)
    root.pack_start(stack, False, False, 0)
    return root

def _sysmon_content(win: Gtk.Window) -> Gtk.Box:
    """System-Monitor-Tab für Geräte OHNE Akku (Desktop-PCs) - zeigt
    CPU (Auslastung, Temperatur, Watt via SUID-Helper), RAM, Swap,
    Disk, und AMD-GPU-Stats (falls erkannt), als 4 Sub-Tabs (CPU/
    Memory/Storage/GPU) statt einer langen, mit Trennstrichen
    unterteilten Liste. Ist aber KEIN exklusiver Ersatz für den
    Akku-Tab - läuft als zweiter, immer vorhandener Tab neben Battery,
    siehe _akku_and_sysmon_content()."""
    root = vbox(3); pad(root, h=4, v=6)
    # KEIN Titel mehr - der Tab-Button "System" sagt schon, was das ist.

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # KEINE Sub-Tab-Überschriften mehr (kein "CPU"/"MEMORY"/"STORAGE"/
    # "GPU" bsec()) - der Sub-Tab-Reiter selbst sagt schon, was drin
    # ist. KEINE Trennstriche mehr außer dem einen unter der Sub-Tab-
    # Reihe selbst (tab_sep(), ganz normaler Bestandteil jeder
    # Tab-Leiste im Programm).
    t_cpu = vbox(3); pad(t_cpu, h=4, v=4)
    t_mem = vbox(3); pad(t_mem, h=4, v=4)
    t_sto = vbox(3); pad(t_sto, h=4, v=4)
    t_gpu = vbox(3); pad(t_gpu, h=4, v=4)

    _stat_prefixes: dict = {}  # Label -> "icon  Name:  " Präfix, siehe _set_stat()

    def _stat_row(icon: str, label_text: str) -> tuple[Gtk.Box, Gtk.Label]:
        """Wie bitem_ref() (zentrierte Bubble-Box, EIN Label) statt
        einer hexpand-gestreckten Zeile - letzteres verzerrt das
        Bubble-Hintergrundbild, weil background-size:100% 100% eine
        sehr breite, dünne Box anders füllt als die kompakten,
        zentrierten Boxen, für die dieses Bubble-Design gebaut ist."""
        prefix = f"{icon}  {label_text}:  "
        row, lbl = bitem_ref(f"{prefix}–")
        _stat_prefixes[lbl] = prefix
        return row, lbl

    def _set_stat(lbl: Gtk.Label, value: str):
        lbl.set_label(f"{_stat_prefixes[lbl]}{value}")

    cpu_row, cpu_val = _stat_row("󰻠", "Usage")
    t_cpu.pack_start(cpu_row, False, False, 0)
    temp_row, temp_val = _stat_row("󰔏", "Temperature")
    t_cpu.pack_start(temp_row, False, False, 0)
    watt_row, watt_val = _stat_row("󱐋", "Power")
    t_cpu.pack_start(watt_row, False, False, 0)

    ram_row, ram_val = _stat_row("󰘚", "RAM")
    t_mem.pack_start(ram_row, False, False, 0)
    swap_row, swap_val = _stat_row("󰋊", "Swap")
    t_mem.pack_start(swap_row, False, False, 0)

    disk_row, disk_val = _stat_row("󰆼", "Disk (/)")
    t_sto.pack_start(disk_row, False, False, 0)

    # Zusätzliche/dynamische Laufwerke (externe SSDs, eingehängte ISOs,
    # Disketten, ...) - siehe _extra_disks(). Wird bei JEDEM Poll-Tick
    # komplett neu aufgebaut statt wie die GPU-Sektion nur einmal, weil
    # sich diese Liste im Gegensatz zur GPU jederzeit ändern kann
    # (USB-Stick rein-/rausgezogen usw.).
    extra_storage_section = vbox(3)
    t_sto.pack_start(extra_storage_section, False, False, 0)

    gpu_section = t_gpu
    gpu_widgets = {}  # wird bei erster erfolgreicher GPU-Erkennung befüllt
    gpu_placeholder = bitem("No GPU stats available", dim=True)
    gpu_section.pack_start(gpu_placeholder, False, False, 0)

    def _fmt_bytes(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    def _apply_snapshot(snap: dict):
        _set_stat(cpu_val, f'{snap["cpu_pct"]:.0f} %')
        if snap["cpu_temp"] is not None:
            _set_stat(temp_val, f'{snap["cpu_temp"]:.0f} °C')
        else:
            _set_stat(temp_val, "n/v")
        if snap["cpu_watts"] is not None:
            _set_stat(watt_val, f'{snap["cpu_watts"]:.1f} W')
        else:
            # kein SUID-Helper installiert oder RAPL nicht lesbar -
            # Zeile bleibt sichtbar mit Platzhalter statt zu
            # verschwinden, konsistent mit der Temperature-Zeile.
            _set_stat(watt_val, "n/v")

        ram = snap["ram"]
        _set_stat(ram_val, f'{ram.percent:.0f} %  ·  {_fmt_bytes(ram.used)} / {_fmt_bytes(ram.total)}')
        sw = snap["swap"]
        if sw.total > 0:
            _set_stat(swap_val, f'{sw.percent:.0f} %  ·  {_fmt_bytes(sw.used)} / {_fmt_bytes(sw.total)}')
            swap_row.set_visible(True)
        else:
            swap_row.set_visible(False)
        d = snap["disk"]
        _set_stat(disk_val, f'{d.percent:.0f} %  ·  {_fmt_bytes(d.used)} / {_fmt_bytes(d.total)}')

        for c in extra_storage_section.get_children():
            extra_storage_section.remove(c)
        for ed in snap.get("disks_extra", []):
            icon = "󰗮" if ed["is_iso"] else ("󰐖" if ed["removable"] else "󰋊")
            row = bitem(f'{icon}  {ed["mount"]}:  {ed["percent"]:.0f} %  ·  '
                        f'{_fmt_bytes(ed["used"])} / {_fmt_bytes(ed["total"])}')
            extra_storage_section.pack_start(row, False, False, 0)
        extra_storage_section.show_all()

        gpu = snap["gpu"]
        if gpu and not gpu_widgets:
            if gpu_placeholder.get_parent() is not None:
                gpu_section.remove(gpu_placeholder)
            if "busy_pct" in gpu:
                r, v = _stat_row("󰢮", "Usage")
                gpu_section.pack_start(r, False, False, 0)
                gpu_widgets["busy"] = v
            if "temp_c" in gpu:
                r, v = _stat_row("󰔏", "Temperature")
                gpu_section.pack_start(r, False, False, 0)
                gpu_widgets["temp"] = v
            if "watts" in gpu:
                r, v = _stat_row("󱐋", "Power")
                gpu_section.pack_start(r, False, False, 0)
                gpu_widgets["watts"] = v
            gpu_section.show_all()
        if gpu_widgets:
            if "busy" in gpu_widgets and "busy_pct" in gpu:
                _set_stat(gpu_widgets["busy"], f'{gpu["busy_pct"]} %')
            if "temp" in gpu_widgets and "temp_c" in gpu:
                _set_stat(gpu_widgets["temp"], f'{gpu["temp_c"]:.0f} °C')
            if "watts" in gpu_widgets and "watts" in gpu:
                _set_stat(gpu_widgets["watts"], f'{gpu["watts"]:.1f} W')

    _fetch_in_flight = [False]

    def _refresh():
        # Überlappungs-Schutz: falls ein einzelner _fetch()-Durchlauf
        # (psutil + SUID-Helper-Subprozess + GPU-sysfs-Reads) mal länger
        # als die 2s-Poll-Rate braucht (z.B. bei hoher Systemlast),
        # NICHT einen weiteren Thread obendrauf starten - das würde bei
        # anhaltender Überlastung immer mehr Threads stapeln lassen.
        # Zusätzliche Absicherung unabhängig vom Fenster-Cleanup-Fix.
        if _fetch_in_flight[0]:
            return True
        _fetch_in_flight[0] = True
        def _fetch():
            try:
                snap = _sysmon_snapshot()
                GLib.idle_add(_apply_snapshot, snap)
            finally:
                _fetch_in_flight[0] = False
        in_thread(_fetch)
        return True

    add_timer(2000, _refresh)
    _refresh()

    stack.add_named(t_cpu, "cpu")
    stack.add_named(t_mem, "memory")
    stack.add_named(t_sto, "storage")
    stack.add_named(t_gpu, "gpu")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch_sysmon_tab(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for tname, tlabel in (("cpu", "CPU"), ("memory", "Memory"),
                          ("storage", "Storage"), ("gpu", "GPU")):
        tb = btn(tlabel, active=(tname == "cpu"))
        tb.connect("clicked", lambda _b, n=tname: _switch_sysmon_tab(n))
        tab_btns[tname] = tb
        tab_row.pack_start(tb, False, False, 0)
    stack.set_visible_child_name("cpu")

    root.pack_start(tab_row, True, False, 2)
    root.pack_start(tab_sep(), False, False, 0)
    root.pack_start(stack, False, False, 0)
    return root

def _confirm_kill_dialog(parent: Gtk.Window, proc_name: str, pid: int) -> bool:
    """Bestätigungs-Dialog vorm Beenden eines Prozesses - Kill ist
    destruktiv (ungespeicherte Arbeit in dem Programm ist weg), sowas
    darf nicht an einem einzigen Fehlklick in einer Liste hängen."""
    d = Gtk.MessageDialog(transient_for=parent, modal=True,
                           message_type=Gtk.MessageType.WARNING,
                           buttons=Gtk.ButtonsType.NONE,
                           text=f"End “{proc_name}” (PID {pid})?")
    d.set_name("wb-daemon-popup")
    d.set_keep_above(True)
    d.format_secondary_text("Unsaved work in this program will be lost.")
    d.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                  "End Process", Gtk.ResponseType.OK)
    resp = d.run()
    d.destroy()
    return resp == Gtk.ResponseType.OK

def _processes_content(win: Gtk.Window) -> Gtk.Box:
    """3. Tab neben Battery/System: htop-artige Prozessliste mit Kill-
    Möglichkeit (Roadmap: "add a 3rd tab wich shows all programs and
    to kill them").

    WICHTIG zur Sortierung/Stabilität (README-Feedback): Prozesse
    dürfen ihre Listenposition NICHT bei jedem 2s-Poll-Tick ändern, nur
    weil sich ihr CPU-Wert minimal verschoben hat - das machte die
    Liste vorher ständig hin- und herspringend und schwer lesbar. Jetzt:
    bestehende Zeilen werden nur noch in-place aktualisiert (Text
    ändern, NICHT neu bauen/neu einsortieren), neue Prozesse werden
    unten ANGEHÄNGT statt nach ihrem Rang eingefügt, und eine
    tatsächliche Neusortierung passiert NUR noch, wenn man aktiv auf
    einen der Spalten-Header (Name/CPU/Mem) klickt. Default-Sortierung
    ist nach Name.

    WICHTIG zur CPU%-Spalte: psutil braucht für sinnvolle Werte zwei
    Messpunkte pro Prozess (Process.cpu_percent(interval=None) misst
    die Zeit SEIT DEM LETZTEN Aufruf für genau dieses Process-Objekt) -
    deshalb wird hier bewusst EINE persistente Process-Objekt-Map über
    alle Poll-Ticks hinweg gepflegt, statt bei jedem Tick neue
    psutil.Process()-Instanzen zu bauen (die würden immer 0.0% liefern,
    weil sie beim ersten Aufruf noch keinen Referenzpunkt haben)."""
    root = vbox(3); pad(root, h=4, v=6)
    # KEIN Titel mehr - Konsistenz mit den anderen Sub-Tabs (CPU/Memory/
    # Storage/GPU haben auch keinen mehr).

    # Klickbare Spalten-Köpfe bestimmen NUR den Sortier-SCHLÜSSEL für
    # die NÄCHSTE Neusortierung - sie lösen die Liste NICHT bei jedem
    # Poll-Tick automatisch neu aus (siehe Docstring oben).
    MAX_ROWS = 40
    hdr_row = hbox(10)
    hdr_row.set_halign(Gtk.Align.CENTER)
    name_hdr = btn("Name", active=True)
    cpu_hdr  = btn("CPU")
    mem_hdr  = btn("Mem")
    hdr_row.pack_start(name_hdr, False, False, 0)
    hdr_row.pack_start(cpu_hdr, False, False, 0)
    hdr_row.pack_start(mem_hdr, False, False, 0)
    root.pack_start(hdr_row, False, False, 0)

    sw, box = scroll_box(300)
    root.pack_start(sw, True, True, 0)

    _proc_cache: dict = {}    # pid -> psutil.Process, siehe Docstring oben
    _row_widgets: dict = {}   # pid -> (row_box, name_lbl, stat_lbl)
    _order: list = []         # aktuelle, STABILE Anzeige-Reihenfolge (PIDs)
    _last_data: dict = {}     # pid -> (name, cpu, mem), letzter bekannter Stand
    _sort_state = {"key": "name"}

    def _build_row(pid: int, name: str, cpu: float, mem: float):
        row = hbox(6)
        row.get_style_context().add_class("bubble")
        row.get_style_context().add_class("item")
        pad(row, h=8, v=4)

        lbl = Gtk.Label(label=f"{name}  ·  PID {pid}")
        lbl.set_halign(Gtk.Align.START)
        # BEWUSST kein set_ellipsize()/set_max_width_chars() mehr -
        # das hat lange Namen fest abgeschnitten, obwohl eigentlich
        # noch Platz da gewesen wäre. Die Zeile darf jetzt ihre volle
        # natürliche Breite anfordern; _refresh() unten lässt das
        # Fenster danach per _shrink_to_fit() neu auf die dafür nötige
        # Breite wachsen. _clamp_window_to_screen() (siehe Known-Bugs-
        # Fix weiter oben in der Datei) fängt den Extremfall eines
        # winzig-absurd langen Namens trotzdem sicher ab, indem es dann
        # in ein scrollbares Fenster wechselt statt über den Bildschirm
        # hinauszuwachsen.
        lbl.set_hexpand(True)
        row.pack_start(lbl, True, True, 0)

        # Kein "·" mehr zwischen CPU und MEM - nur noch ein Leerraum.
        stat_lbl = Gtk.Label(label=f"{cpu:4.1f}% CPU   {mem:4.1f}% MEM")
        stat_lbl.get_style_context().add_class("caption")
        stat_lbl.set_opacity(0.7)
        row.pack_start(stat_lbl, False, False, 0)

        kill_b = Gtk.Button(label="󰅖")
        kill_b.set_relief(Gtk.ReliefStyle.NONE)
        kill_b.get_style_context().add_class("flat")
        kill_b.set_opacity(0.7)
        kill_b.set_tooltip_text("End process")
        def _on_kill(_w, p=pid, n=name):
            if not _confirm_kill_dialog(win, n, p):
                return
            def _worker():
                try:
                    proc = _proc_cache.get(p)
                    import psutil
                    if proc is None:
                        proc = psutil.Process(p)
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()  # nicht kooperativ -> hart nachlegen
                except Exception:
                    pass  # Prozess war evtl. schon weg - kein Grund für Fehlerdialog
                GLib.idle_add(_refresh)
            in_thread(_worker)
        kill_b.connect("clicked", _on_kill)
        row.pack_start(kill_b, False, False, 0)
        return row, lbl, stat_lbl

    def _fetch() -> dict:
        import psutil
        seen_pids = set()
        data = {}
        for p in psutil.process_iter(["pid", "name"]):
            pid = p.info["pid"]
            if pid == 0:
                continue  # kernel/sched-Pseudoprozess, nicht killbar
            seen_pids.add(pid)
            proc = _proc_cache.get(pid)
            if proc is None:
                proc = p
                _proc_cache[pid] = proc
            try:
                cpu = proc.cpu_percent(interval=None)
                mem = proc.memory_percent()
                name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            data[pid] = (name, cpu, mem)
        # Verwaiste Cache-Einträge (Prozess seitdem beendet) raus, sonst
        # wächst _proc_cache über die Laufzeit des offenen Fensters
        # unbegrenzt weiter.
        for pid in list(_proc_cache):
            if pid not in seen_pids:
                _proc_cache.pop(pid, None)
        return data

    def _apply_order():
        """Sortiert NUR die Reihenfolge der PIDs (per box.reorder_child)
        neu - baut dabei KEINE einzige Zeile neu, nur ihre Position
        ändert sich. Wird ausschließlich beim Klick auf einen der 3
        Spalten-Header (und einmalig beim allerersten Befüllen)
        aufgerufen, NIE automatisch bei jedem Poll-Tick."""
        key = _sort_state["key"]
        if key == "name":
            _order.sort(key=lambda p: (_last_data.get(p, ("", 0, 0))[0] or "").lower())
        elif key == "cpu":
            _order.sort(key=lambda p: _last_data.get(p, ("", 0, 0))[1], reverse=True)
        else:
            _order.sort(key=lambda p: _last_data.get(p, ("", 0, 0))[2], reverse=True)
        for idx, pid in enumerate(_order):
            box.reorder_child(_row_widgets[pid][0], idx)

    def _resort(key: str):
        _sort_state["key"] = key
        for hdr, k in ((name_hdr, "name"), (cpu_hdr, "cpu"), (mem_hdr, "mem")):
            ctx = hdr.get_style_context()
            if k == key: ctx.add_class("active")
            else:        ctx.remove_class("active")
        _apply_order()

    name_hdr.connect("clicked", lambda _w: _resort("name"))
    cpu_hdr.connect("clicked",  lambda _w: _resort("cpu"))
    mem_hdr.connect("clicked",  lambda _w: _resort("mem"))

    _fetch_in_flight = [False]
    _sorted_once = [False]

    def _apply(data: dict):
        _last_data.clear()
        _last_data.update(data)

        # Verschwundene Prozesse raus - einzige Fälle, in denen sich
        # die Liste "von selbst" verkürzt.
        for pid in [p for p in _order if p not in data]:
            widgets = _row_widgets.pop(pid, None)
            if widgets:
                box.remove(widgets[0])
            _order.remove(pid)

        # Neue Prozesse werden UNTEN angehängt (README-Feedback), NICHT
        # nach ihrem Sortier-Rang einsortiert - erst der nächste Klick
        # auf einen Spalten-Header bringt sie an ihre "richtige"
        # Position. Ein Cap verhindert, dass die Liste bei sehr vielen
        # laufenden Prozessen unbegrenzt wächst; bereits verfolgte
        # Prozesse bleiben davon unberührt (Positions-Stabilität geht
        # vor striktem Cap).
        new_pids = [p for p in data if p not in _row_widgets]
        for pid in new_pids:
            if len(_order) >= MAX_ROWS:
                break
            name, cpu, mem = data[pid]
            row, lbl, stat_lbl = _build_row(pid, name, cpu, mem)
            _row_widgets[pid] = (row, lbl, stat_lbl)
            _order.append(pid)
            box.pack_start(row, False, False, 0)

        # Bestehende Zeilen NUR in-place aktualisieren (Text ändern),
        # NIE neu bauen oder neu einfügen - das ist der Kern der
        # geforderten Positions-Stabilität.
        for pid in _order:
            if pid in new_pids:
                continue
            name, cpu, mem = data[pid]
            _, lbl, stat_lbl = _row_widgets[pid]
            lbl.set_label(f"{name}  ·  PID {pid}")
            stat_lbl.set_label(f"{cpu:4.1f}% CPU   {mem:4.1f}% MEM")

        if not _sorted_once[0] and _order:
            _sorted_once[0] = True
            _apply_order()

        box.show_all()
        # Neu seit Entfernen des harten Zeichen-Limits oben: Namen
        # können sich JEDEN Poll-Tick ändern (neue Prozesse) - ohne
        # diesen Aufruf hätte das Fenster nur beim ERSTEN Öffnen die
        # passende Breite bekommen und wäre danach nie wieder
        # mitgewachsen/-geschrumpft.
        GLib.idle_add(_shrink_to_fit, win)

    def _refresh():
        if _fetch_in_flight[0]:
            return True
        _fetch_in_flight[0] = True
        def _work():
            try:
                data = _fetch()
                GLib.idle_add(_apply, data)
            finally:
                _fetch_in_flight[0] = False
        in_thread(_work)
        return True

    add_timer(2000, _refresh)
    _refresh()
    return root

def _akku_and_sysmon_content(win: Gtk.Window) -> Gtk.Box:
    """Zwei-Tab-Fenster: Battery (nur falls _battery_present(), also
    nur auf Laptops) + System Monitor (IMMER, unabhängig vom Akku -
    CPU/RAM/GPU/Disk-Stats sind für jeden interessant, nicht nur für
    Desktop-Nutzer ohne Akku). Folgt demselben Gtk.Stack + Umschalt-
    Button-Muster wie _volume_content() (Media/Devices/Apps-Tabs)."""
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    has_bat = _battery_present()
    default_tab = "battery" if has_bat else "system"
    if has_bat:
        stack.add_named(_akku_content(win), "battery")

    # System-Tab wird LAZY gebaut - erst wenn tatsächlich draufgeklickt
    # wird, nicht sofort beim Öffnen des Fensters. Der System-Monitor
    # pollt alle 2s (CPU/RAM/GPU/Disk) - ohne Lazy-Loading würde dieser
    # Timer die GANZE Zeit mitlaufen, auch wenn nur der Battery-Tab
    # angeschaut wird. Falls kein Akku vorhanden ist, ist "system" der
    # einzige/Default-Tab und wird direkt gebaut (kein Grund zu warten,
    # er wird ja sofort angezeigt).
    system_built = [False]
    if not has_bat:
        stack.add_named(_sysmon_content(win), "system")
        system_built[0] = True

    def _ensure_system_tab():
        if system_built[0]:
            return
        system_built[0] = True
        # WICHTIG: _current_win muss hier gesetzt sein, exakt wie beim
        # Lazy-Aufbau der Settings-Kategorien - add_timer() registriert
        # neue Timer nur gegen _current_win[0]. Ohne das würde der
        # System-Monitor-Timer NIE in _timers_by_win landen und beim
        # Schließen des Fensters nie abgeräumt - derselbe Bug-Musterfall
        # wie zuvor bei den lazy geladenen Settings-Unterseiten.
        _current_win[0] = win
        try:
            stack.add_named(_sysmon_content(win), "system")
        finally:
            _current_win[0] = None
        stack.show_all()

    # Processes-Tab (Roadmap: 3. Tab mit Prozessliste + Kill) - genau
    # wie der System-Tab bewusst LAZY gebaut, aus demselben Grund
    # (eigener 2s-Poll-Timer, soll nicht mitlaufen, wenn der Tab gar
    # nicht offen ist) und aus demselben _current_win[0]-Grund.
    processes_built = [False]

    def _ensure_processes_tab():
        if processes_built[0]:
            return
        processes_built[0] = True
        _current_win[0] = win
        try:
            stack.add_named(_processes_content(win), "processes")
        finally:
            _current_win[0] = None
        stack.show_all()

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        if name == "system":
            _ensure_system_tab()
        elif name == "processes":
            _ensure_processes_tab()
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")

    tabs = ([("battery", "󰁹  Battery")] if has_bat else []) + \
           [("system", "󰍹  System"), ("processes", "󰆧  Processes")]
    for name, label in tabs:
        b = btn(label, active=(name == default_tab))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name(default_tab)

    outer = vbox(4); safe_pad(outer, 460)
    if len(tabs) > 1:
        outer.pack_start(tab_row, True, False, 2)
        outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack, False, False, 0)
    return outer

def build_akku(win: Gtk.Window):
    win.set_default_size(460, 1)
    win.add(_akku_and_sysmon_content(win))

# ════════════════════════════════════════════════════════════
#  CLOCK + CALENDAR
# ════════════════════════════════════════════════════════════
_WCODE_ICON = {
    "113": "☀️", "116": "⛅", "119": "☁️", "122": "☁️",
    "143": "🌫️", "248": "🌫️", "260": "🌫️", "176": "🌦️",
    "263": "🌦️", "266": "🌦️", "293": "🌦️", "296": "🌦️",
    "353": "🌦️", "281": "🌧️", "284": "🌧️", "299": "🌧️",
    "302": "🌧️", "305": "🌧️", "308": "🌧️", "311": "🌧️",
    "314": "🌧️", "356": "🌧️", "359": "🌧️", "179": "🌨️",
    "182": "🌨️", "185": "🌨️", "227": "🌨️", "317": "🌨️",
    "320": "🌨️", "362": "🌨️", "365": "🌨️", "368": "🌨️",
    "230": "❄️", "323": "🌨️", "326": "❄️", "329": "❄️",
    "332": "❄️", "335": "❄️", "338": "❄️", "371": "❄️",
    "350": "🧊", "374": "🧊", "377": "🧊", "200": "⛈️",
    "386": "⛈️", "389": "⛈️", "392": "⛈️", "395": "⛈️",
}
def _wicon(code) -> str:
    return _WCODE_ICON.get(str(code), "🌡️")

_WMO_ICON = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌦️", 55: "🌦️",
    56: "🌧️", 57: "🌧️", 61: "🌧️", 63: "🌧️", 65: "🌧️",
    66: "🌧️", 67: "🌧️", 71: "🌨️", 73: "🌨️", 75: "❄️", 77: "🌨️",
    80: "🌦️", 81: "🌧️", 82: "🌧️", 85: "🌨️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}
# Nur Codes mit einem reinen Sonnen-Symbol brauchen eine Nacht-Variante
# (Regen/Schnee/Sturm/Nebel-Icons haben ohnehin keine Sonne drin, die
# bei Nacht falsch aussehen würde) - siehe Chat: nachts wurde bisher
# trotzdem die Sonne angezeigt, weil is_day gar nicht abgefragt wurde.
_WMO_ICON_NIGHT = {0: "🌙", 1: "🌙", 2: "☁️"}
_WMO_DESC_EN = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy",
    3: "Overcast", 45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}
def _wicon_wmo(code, is_day: bool = True) -> str:
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "🌡️"
    if not is_day and code in _WMO_ICON_NIGHT:
        return _WMO_ICON_NIGHT[code]
    return _WMO_ICON.get(code, "🌡️")

def _load_weather_location() -> dict:
    try:
        data = json.loads(WEATHER_CONF.read_text())
        if "lat" in data and "lon" in data:
            return data
    except Exception:
        pass
    return _DEFAULT_WEATHER_LOC

def _save_weather_location(lat: float, lon: float, name: str) -> None:
    WEATHER_CONF.parent.mkdir(parents=True, exist_ok=True)
    WEATHER_CONF.write_text(json.dumps(
        {"lat": lat, "lon": lon, "name": name}, ensure_ascii=False, indent=2))

def _geocode(query: str) -> list:
    import urllib.request, urllib.parse, json as _json
    url = ("https://geocoding-api.open-meteo.com/v1/search?" +
           urllib.parse.urlencode({"name": query, "count": 5, "language": "en"}))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wb-daemon/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = _json.loads(resp.read().decode())
        return data.get("results") or []
    except Exception:
        return []

def _fetch_weather() -> dict:
    r = {"icon": "🌡️", "desc": "–", "temp": "–",
         "humidity": "–", "precip": "–",
         "day1_icon": "–", "day2_icon": "–", "location": "–"}
    loc = _load_weather_location()
    r["location"] = loc.get("name", "–")
    try:
        import urllib.request, urllib.parse, json as _json
        params = {
            "latitude": loc["lat"], "longitude": loc["lon"],
            "current": "temperature_2m,relative_humidity_2m,"
                       "precipitation,weather_code,is_day",
            "daily": "weather_code",
            "timezone": "auto",
            "forecast_days": 3,
            "models": "best_match",
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "wb-daemon/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = _json.loads(resp.read().decode())

        cur = data.get("current", {})
        code = cur.get("weather_code")
        is_day = cur.get("is_day", 1) == 1
        r["icon"] = _wicon_wmo(code, is_day)
        r["desc"] = _WMO_DESC_EN.get(int(code), "–") if code is not None else "–"
        temp = cur.get("temperature_2m")
        r["temp"] = f"{round(temp)}°C" if temp is not None else "–"
        hum = cur.get("relative_humidity_2m")
        r["humidity"] = f"{round(hum)}%" if hum is not None else "–"
        precip = cur.get("precipitation")
        r["precip"] = f"{precip} mm" if precip is not None else "–"

        daily_codes = data.get("daily", {}).get("weather_code", [])
        if len(daily_codes) > 1: r["day1_icon"] = _wicon_wmo(daily_codes[1])
        if len(daily_codes) > 2: r["day2_icon"] = _wicon_wmo(daily_codes[2])
    except Exception:
        try:
            import urllib.request, json as _json
            req = urllib.request.Request(
                f"https://wttr.in/{loc['lat']},{loc['lon']}?format=j1&lang=en",
                headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = _json.loads(resp.read().decode())
            cur = data["current_condition"][0]
            r["icon"] = _wicon(cur.get("weatherCode", ""))
            desc = cur.get("lang_en") or cur.get("weatherDesc") or []
            r["desc"] = desc[0]["value"] if desc else "–"
            r["temp"] = f'{cur.get("temp_C", "–")}°C'
            r["humidity"] = f'{cur.get("humidity", "–")}%'
            r["precip"] = f'{cur.get("precipMM", "0.0")} mm'

            def _midday_code(day: dict) -> str:
                hrs = day.get("hourly", [])
                if len(hrs) > 4: return hrs[4].get("weatherCode", "")
                if hrs: return hrs[len(hrs)//2].get("weatherCode", "")
                return ""

            days = data.get("weather", [])
            if len(days) > 1: r["day1_icon"] = _wicon(_midday_code(days[1]))
            if len(days) > 2: r["day2_icon"] = _wicon(_midday_code(days[2]))
        except Exception:
            pass
    return r

MONTHS_EN = ["January","February","March","April","May","June",
             "July","August","September","October","November","December"]
# Montag-first, exakt wie calendar.monthcalendar() (Python-Default
# firstweekday=0=Montag) die Wochen aufbaut - vorher stand hier
# Sonntag zuerst, wodurch sich JEDES Datum im Grid um eine Spalte nach
# links verschoben hat (z.B. der 12.08.2026, ein Mittwoch, landete
# unter dem "Tue"/Dienstag-Label). Siehe Chat.
DAYS_EN   = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

# ════════════════════════════════════════════════════════════
#  khal-Integration (schnelle Termine im Kalender-Widget)
# ════════════════════════════════════════════════════════════
# khal ist bewusst gewaehlt statt einer schwergewichtigen Desktop-App
# oder einer direkten Cloud-Anbindung: standardbasiert (iCalendar/
# vdir), leichtgewichtig, rein CLI-steuerbar.
_KHAL_CACHE = {"available": None, "configured": None}

def _khal_available() -> bool:
    if _KHAL_CACHE["available"] is None:
        import shutil
        _KHAL_CACHE["available"] = shutil.which("khal") is not None
    return _KHAL_CACHE["available"]

def _khal_configured() -> bool:
    """khal braucht mindestens einen konfigurierten Kalender, sonst
    schlagen 'khal new'/'khal list' mit einem Konfigurationsfehler
    fehl. 'khal printcalendars' listet alle konfigurierten Kalender -
    leere Ausgabe bzw. Fehler heisst: noch nichts eingerichtet."""
    if _KHAL_CACHE["configured"] is None:
        out, _err, ec = run_ec(["khal", "printcalendars"])
        _KHAL_CACHE["configured"] = (ec == 0 and bool(out.strip()))
    return _KHAL_CACHE["configured"]

def _khal_setup_default_calendar() -> tuple[bool, str]:
    """Legt automatisch einen minimalen lokalen Kalender an, falls noch
    keiner konfiguriert ist."""
    try:
        cal_dir = Path(HOME) / ".local" / "share" / "khal" / "calendars" / "private"
        cal_dir.mkdir(parents=True, exist_ok=True)
        conf_dir = Path(HOME) / ".config" / "khal"
        conf_dir.mkdir(parents=True, exist_ok=True)
        conf_path = conf_dir / "config"
        if not conf_path.is_file():
            tz = run(["timedatectl", "show", "-p", "Timezone", "--value"]) or "UTC"
            conf_path.write_text(
                "[calendars]\n"
                "[[private]]\n"
                f"path = {cal_dir}\n"
                "color = dark green\n\n"
                "[locale]\n"
                f"local_timezone = {tz}\n"
                f"default_timezone = {tz}\n"
                "timeformat = %H:%M\n"
                "dateformat = %Y-%m-%d\n"
                "longdateformat = %Y-%m-%d\n"
                "datetimeformat = %Y-%m-%d %H:%M\n"
                "longdatetimeformat = %Y-%m-%d %H:%M\n"
                "\n[default]\n"
                "default_calendar = private\n")
        _KHAL_CACHE["configured"] = None
        ok = _khal_configured()
        return ok, "" if ok else "khal-Konfiguration konnte nicht verifiziert werden."
    except Exception as e:
        return False, str(e)

def _khal_events_for_month(year: int, month: int) -> dict:
    """EIN einziger khal-Aufruf für den kompletten sichtbaren Monat
    statt bis zu 42 Einzelaufrufen (einer pro Kalendertag) - würde bei
    jedem Monatswechsel das UI einfrieren lassen. Rückgabe:
    {date_str: [event, ...]}.
    WICHTIG: 'khal list --json' gibt bei einem mehrtägigen Zeitraum
    NICHT ein einziges großes JSON-Array zurück, sondern EIN Array PRO
    TAG, zeilenweise aneinandergereiht (z.B. "[]\\n[]\\n[{...}]\\n").
    Ein einzelnes json.loads() auf den kompletten Output wirft daher
    "Extra data" - verifiziert gegen ein echtes khal 0.14.0 mit
    mehreren Terminen an unterschiedlichen Tagen. Fix: zeilenweise
    parsen, jede Zeile für sich als eigenes JSON-Array behandeln, dann
    zusammenführen."""
    if not (_khal_available() and _khal_configured()):
        return {}
    first = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    out, _err, ec = run_ec([
        "khal", "list", first.strftime("%Y-%m-%d"), f"{days_in_month}d",
        "--json", "title", "--json", "start-time", "--json", "start-date",
        "--json", "uid", "--json", "calendar",
    ])
    if ec != 0 or not out.strip():
        return {}
    all_events: list = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            arr = json.loads(line)
        except Exception:
            continue
        if isinstance(arr, list):
            all_events.extend(arr)
    by_day: dict = {}
    for ev in all_events:
        key = ev.get("start-date", "")
        by_day.setdefault(key, []).append(ev)
    return by_day

def _khal_new_event(d, time_str: str, title: str) -> tuple[bool, str]:
    """Legt einen neuen Termin an: Datum d (datetime.date) + Uhrzeit
    (HH:MM) + Titel."""
    if not title.strip():
        return False, "Titel darf nicht leer sein."
    if not re.match(r'^([01]?\d|2[0-3]):[0-5]\d$', time_str.strip()):
        return False, "Ungültige Uhrzeit (erwartet HH:MM)."
    date_str = d.strftime("%Y-%m-%d")
    _out, err, ec = run_ec(["khal", "new", date_str, time_str.strip(), title.strip()])
    if ec != 0:
        return False, err or "khal new ist fehlgeschlagen."
    return True, ""

def _khal_calendar_paths() -> dict:
    """Liest Kalendername -> vdir-Pfad direkt aus khals Config-Datei.
    WICHTIG: khal hat KEIN scriptbares 'khal delete' (nur die
    interaktiven 'ikhal'/'khal edit SUCHSTRING', beide ungeeignet für
    einen Button - offiziell verifiziert, siehe Chat/khal-Doku).
    Termine werden deshalb als das gelöscht, was sie technisch sind:
    einzelne .ics-Dateien in einem vdir-Ordner. Die Config nutzt
    verschachtelte [[name]]-Sektionen (kein Standard-INI, deshalb
    Handparsing statt configparser)."""
    conf_path = Path(HOME) / ".config" / "khal" / "config"
    paths: dict = {}
    try:
        txt = conf_path.read_text()
    except Exception:
        return paths
    current_cal = None
    in_calendars_section = False
    for line in txt.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r'^\[[a-zA-Z]', stripped):  # z.B. "[calendars]", "[locale]"
            in_calendars_section = (stripped == "[calendars]")
            current_cal = None
            continue
        if not in_calendars_section:
            continue
        m = re.match(r'^\[\[(.+?)\]\]$', stripped)
        if m:
            current_cal = m.group(1)
            continue
        m = re.match(r'^path\s*=\s*(.+)$', stripped)
        if m and current_cal:
            paths[current_cal] = Path(m.group(1).strip()).expanduser()
    return paths

def _khal_delete_event(calendar_name: str, uid: str) -> tuple[bool, str]:
    """Löscht das .ics einer Kalenderdatei anhand der UID (NICHT
    anhand des Dateinamens, der ist vdir-Implementierungsdetail und
    nicht garantiert die UID zu sein) - sucht die Datei, die eine
    Zeile 'UID:<uid>' enthält, und löscht genau die."""
    if not uid:
        return False, "No UID known for this event."
    paths = _khal_calendar_paths()
    cal_path = paths.get(calendar_name)
    if not cal_path or not cal_path.is_dir():
        return False, f"Calendar path for '{calendar_name}' not found."
    needle = f"UID:{uid}"
    try:
        for f in cal_path.glob("*.ics"):
            try:
                if needle in f.read_text(errors="ignore"):
                    f.unlink()
                    return True, ""
            except Exception:
                continue
    except Exception as e:
        return False, str(e)
    return False, "Event file not found (maybe already deleted)."

def _khal_default_calendar_name() -> str | None:
    """Liest 'default_calendar' aus der [default]-Sektion - dieselbe
    Handparser-Logik wie _khal_calendar_paths(), auf die einzelne
    Zeile beschränkt."""
    conf_path = Path(HOME) / ".config" / "khal" / "config"
    try:
        txt = conf_path.read_text()
    except Exception:
        return None
    in_default_section = False
    for line in txt.splitlines():
        stripped = line.strip()
        if re.match(r'^\[[a-zA-Z]', stripped):
            in_default_section = (stripped == "[default]")
            continue
        if in_default_section:
            m = re.match(r'^default_calendar\s*=\s*(.+)$', stripped)
            if m:
                return m.group(1).strip()
    return None

def _khal_change_storage_path(calendar_name: str, new_dir: Path, copy_old: bool) -> tuple[bool, str]:
    """Ändert den vdir-Speicherort eines Kalenders.

    copy_old steuert, ob die bestehenden .ics-Dateien in den neuen
    Ordner KOPIERT werden (Original bleibt unangetastet an der alten
    Stelle liegen, kein Verschieben mehr) - wird jetzt VORHER explizit
    per Dialog abgefragt (siehe _on_storage_btn()), statt automatisch
    anhand von "ist der Zielordner gerade leer?" zu entscheiden.

    Sicherheitsnetz bleibt unabhängig von copy_old bestehen: ist der
    Zielordner NICHT leer (z.B. schon ein über Syncthing/Nextcloud
    synchronisierter Ordner von einem anderen Gerät), wird dort NICHTS
    kopiert/überschrieben - dann wird nur der Config-Pfad umgebogen,
    jedes Anfassen des Zielordners in dem Fall wäre ein unnötiges
    Risiko (z.B. Konflikte mit dem Sync-Tool)."""
    conf_path = Path(HOME) / ".config" / "khal" / "config"
    try:
        txt = conf_path.read_text()
    except Exception as e:
        return False, f"Could not read khal config: {e}"

    paths = _khal_calendar_paths()
    old_dir = paths.get(calendar_name)

    try:
        new_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"Could not create new folder: {e}"

    target_already_has_data = any(new_dir.glob("*.ics"))
    copied = False
    if (copy_old and not target_already_has_data and old_dir and old_dir.is_dir()
            and old_dir.resolve() != new_dir.resolve()):
        for f in old_dir.glob("*.ics"):
            try:
                shutil.copy2(str(f), str(new_dir / f.name))
            except Exception as e:
                return False, f"Failed to copy {f.name}: {e}"
        copied = True

    # Pfad-Zeile NUR innerhalb der passenden [[calendar_name]]-Sektion
    # ersetzen (Handparsing analog zu _khal_calendar_paths(), diesmal
    # schreibend statt lesend).
    lines = txt.splitlines()
    out_lines = []
    in_calendars = False
    in_target_cal = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if re.match(r'^\[[a-zA-Z]', stripped):
            in_calendars = (stripped == "[calendars]")
            in_target_cal = False
            out_lines.append(line)
            continue
        if in_calendars:
            m = re.match(r'^\[\[(.+?)\]\]$', stripped)
            if m:
                in_target_cal = (m.group(1) == calendar_name)
                out_lines.append(line)
                continue
            if in_target_cal and re.match(r'^path\s*=\s*', stripped):
                out_lines.append(f"path = {new_dir}")
                replaced = True
                continue
        out_lines.append(line)

    if not replaced:
        return False, f"'path' line for calendar '{calendar_name}' not found in config."

    try:
        backup_file(conf_path)
        conf_path.write_text("\n".join(out_lines) + "\n")
    except Exception as e:
        return False, f"Could not write khal config: {e}"

    # Cache-DB verwerfen, damit khal den neuen Ordner sauber neu indiziert
    for db in (Path(HOME) / ".local" / "share" / "khal" / "khal.db",):
        try:
            db.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

    if target_already_has_data:
        return True, (f"Target folder already had events - nothing copied, "
                       f"just switched over. Old data is still at {old_dir}.")
    if copied:
        return True, f"Storage location changed, events copied (originals still at {old_dir})."
    return True, "Storage location changed."

def _clock_content(win: Gtk.Window) -> Gtk.Box:
    # Layout-Redesign: Wetter und Kalender waren vorher EIN langer,
    # durchgehender Stapel (Wetter-Karte + Vorschau + Datum/Zeit +
    # Monatsnavigation + Wochentage + Grid) - dadurch wurde das
    # Fenster so hoch, dass Kopf- und Fußzeile der Blase (die oben/
    # unten schmaler wird) über den sichtbaren Rand hinausragten.
    # Jetzt: zwei Tabs nach demselben Gtk.Stack-Muster wie bei
    # _volume_content() (Media/Devices/Apps) - jeder Tab für sich ist
    # deutlich kompakter und passt dadurch innerhalb des Blasenrands.
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    # NICHT homogen: das Fenster soll sich auf die Höhe des jeweils
    # SICHTBAREN Tabs einpendeln (Wetter ist viel kürzer als Kalender)
    # statt immer auf die Höhe des größten Tabs aufgebläht zu bleiben.
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── TAB 1: Weather ──────────────────────────────────────
    t1 = vbox(4); pad(t1, h=4, v=6)

    today_card = hbox(12)
    today_card.get_style_context().add_class("bubble")
    today_card.get_style_context().add_class("item")

    icon_lbl = Gtk.Label(label="🌡️")
    icon_lbl.get_style_context().add_class("icon-xl")
    today_card.pack_start(icon_lbl, False, False, 0)

    mid_box = vbox(2)
    mid_box.set_valign(Gtk.Align.CENTER)
    temp_lbl = Gtk.Label(label="–")
    temp_lbl.get_style_context().add_class("temp-xl")
    temp_lbl.set_halign(Gtk.Align.START)
    desc_lbl = Gtk.Label(label="Loading weather…")
    desc_lbl.get_style_context().add_class("value-md")
    desc_lbl.set_halign(Gtk.Align.START)
    mid_box.pack_start(temp_lbl, False, False, 0)
    mid_box.pack_start(desc_lbl, False, False, 0)
    mid_box.set_hexpand(True)
    today_card.pack_start(mid_box, True, True, 0)

    stats_box = vbox(3)
    stats_box.set_valign(Gtk.Align.CENTER)
    hum_lbl = Gtk.Label(label="💧 –")
    hum_lbl.get_style_context().add_class("caption")
    hum_lbl.set_halign(Gtk.Align.END)
    hum_lbl.set_tooltip_text("Humidity")
    rain_lbl = Gtk.Label(label="☔ –")
    rain_lbl.get_style_context().add_class("caption")
    rain_lbl.set_halign(Gtk.Align.END)
    rain_lbl.set_tooltip_text("Precipitation (mm)")
    loc_btn = Gtk.Button(label="📍")
    loc_btn.set_relief(Gtk.ReliefStyle.NONE)
    loc_btn.get_style_context().add_class("flat")
    loc_btn.set_can_focus(False)
    loc_btn.set_halign(Gtk.Align.END)
    loc_btn.set_tooltip_text("Change location")
    stats_box.pack_start(hum_lbl,  False, False, 0)
    stats_box.pack_start(rain_lbl, False, False, 0)
    stats_box.pack_start(loc_btn,  False, False, 0)
    today_card.pack_start(stats_box, False, False, 0)

    t1.pack_start(today_card, False, False, 0)

    def _prompt_change_location(_w=None):
        """Standort-Such-Dialog - nutzt denselben _geocode()-Helper
        wie die CLI (--set-weather), damit beide Wege konsistent
        bleiben."""
        dlg = Gtk.Dialog(title="Change location", transient_for=win)
        dlg.add_buttons("Close", Gtk.ResponseType.CANCEL)
        content = dlg.get_content_area()
        content.set_spacing(6)
        pad(content, h=14, v=10)
        dlg.set_default_size(340, 320)

        search_row = hbox(6)
        search_e = Gtk.Entry()
        search_e.set_placeholder_text("Search city…")
        search_e.set_hexpand(True)
        search_b = btn("Search")
        search_row.pack_start(search_e, True, True, 0)
        search_row.pack_start(search_b, False, False, 0)
        content.pack_start(search_row, False, False, 0)

        status_lbl = Gtk.Label(label="")
        status_lbl.get_style_context().add_class("caption")
        content.pack_start(status_lbl, False, False, 0)

        results_box = vbox(4)
        content.pack_start(results_box, True, True, 0)

        def _clear_results():
            for c in results_box.get_children():
                results_box.remove(c)

        def _select(res):
            _save_weather_location(res["latitude"], res["longitude"], res["name"])
            dlg.destroy()
            in_thread(_load_weather)

        def _do_search(_w=None):
            query = search_e.get_text().strip()
            if not query:
                return
            status_lbl.set_label("Searching…")
            _clear_results()

            def _fetch():
                results = _geocode(query)
                def _apply():
                    status_lbl.set_label(
                        "" if results else f"No results for “{query}”")
                    _clear_results()
                    for res in results[:8]:
                        admin = res.get("admin1", "")
                        country = res.get("country", "")
                        parts = ", ".join(p for p in (admin, country) if p)
                        label = f'{res["name"]}' + (f" ({parts})" if parts else "")
                        row_b = btn(label)
                        row_b.set_halign(Gtk.Align.FILL)
                        row_b.get_child().set_halign(Gtk.Align.START)
                        row_b.connect("clicked", lambda _b, r=res: _select(r))
                        results_box.pack_start(row_b, False, False, 0)
                    results_box.show_all()
                GLib.idle_add(_apply)
            in_thread(_fetch)

        search_b.connect("clicked", _do_search)
        search_e.connect("activate", _do_search)
        dlg_destroyed = [False]
        dlg.connect("destroy", lambda _d: dlg_destroyed.__setitem__(0, True))
        dlg.show_all()
        status_lbl.hide()
        search_e.grab_focus()
        dlg.run()
        if not dlg_destroyed[0]:
            dlg.destroy()

    loc_btn.connect("clicked", _prompt_change_location)

    fc_row = hbox(6)
    fc_row.set_halign(Gtk.Align.CENTER)

    d1_box = hbox(0)
    d1_box.get_style_context().add_class("bubble")
    d1_box.get_style_context().add_class("item")
    d1_box.set_size_request(70, -1)
    d1_box.set_halign(Gtk.Align.CENTER)
    d1_lbl = Gtk.Label(label="–")
    d1_lbl.get_style_context().add_class("icon-lg")
    d1_box.pack_start(d1_lbl, True, True, 0)

    d2_box = hbox(0)
    d2_box.get_style_context().add_class("bubble")
    d2_box.get_style_context().add_class("item")
    d2_box.set_size_request(70, -1)
    d2_box.set_halign(Gtk.Align.CENTER)
    d2_lbl = Gtk.Label(label="–")
    d2_lbl.get_style_context().add_class("icon-lg")
    d2_box.pack_start(d2_lbl, True, True, 0)

    fc_row.pack_start(d1_box, False, False, 0)
    fc_row.pack_start(d2_box, False, False, 0)
    t1.pack_start(fc_row, False, False, 0)

    t1.pack_start(sep(), False, False, 2)

    dt_row = hrow()
    dt_row.set_halign(Gtk.Align.CENTER)

    date_box = hbox(0)
    date_box.get_style_context().add_class("bubble")
    date_box.get_style_context().add_class("item")
    date_lbl = Gtk.Label(label="")
    date_box.pack_start(date_lbl, False, False, 0)

    time_box = hbox(0)
    time_box.get_style_context().add_class("bubble")
    time_box.get_style_context().add_class("title")
    time_lbl = Gtk.Label(label="--:--")
    time_lbl.get_style_context().add_class("clock-digits")
    time_box.pack_start(time_lbl, False, False, 0)

    dt_row.pack_start(date_box, False, False, 0)
    dt_row.pack_start(time_box, False, False, 0)
    t1.pack_start(dt_row, False, False, 0)

    # ── TAB 2: Calendar ─────────────────────────────────────
    t2 = vbox(2); pad(t2, h=6, v=4)

    now = datetime.now()
    cur = [now.year, now.month]

    prev_b      = btn("󰅁", tip="Previous month")
    next_b      = btn("󰅂", tip="Next month")
    mth_box, mth_lbl = bitem_ref("")
    storage_btn = btn("📁", tip="Change where calendar data is stored (e.g. for multi-device sync)")
    nav_row = hrow(prev_b, mth_box, next_b, storage_btn, sp=4)
    t2.pack_start(nav_row, False, False, 0)

    def _on_storage_btn(_w):
        cal_name = _khal_default_calendar_name()
        if not cal_name:
            storage_btn.set_tooltip_text("No default calendar found in khal's config.")
            return
        current = _khal_calendar_paths().get(cal_name)
        dlg = Gtk.FileChooserDialog(
            title="Choose calendar storage location",
            transient_for=win, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         "Apply", Gtk.ResponseType.OK)
        if current and current.is_dir():
            dlg.set_current_folder(str(current))
        resp = dlg.run()
        new_dir = Path(dlg.get_filename()) if dlg.get_filename() else None
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not new_dir:
            return

        # Explizit fragen statt (wie bisher) stillschweigend anhand von
        # "ist der Zielordner gerade leer?" zu entscheiden, ob die
        # bestehenden .ics-Dateien mitkopiert werden sollen.
        has_old_files = bool(current and current.is_dir()
                              and current.resolve() != new_dir.resolve()
                              and any(current.glob("*.ics")))
        copy_old = False
        if has_old_files:
            qdlg = Gtk.MessageDialog(
                transient_for=win, modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="Copy existing calendar files to the new folder?")
            qdlg.set_name("wb-daemon-popup")
            qdlg.set_keep_above(True)
            qdlg.format_secondary_text(
                f"Found existing events in {current}. The originals will "
                f"stay there either way - this only controls whether copies "
                f"go into the new folder too.")
            qdlg.add_buttons("Don't copy", Gtk.ResponseType.NO,
                             "Copy", Gtk.ResponseType.YES)
            qresp = qdlg.run()
            qdlg.destroy()
            copy_old = (qresp == Gtk.ResponseType.YES)

        def _worker():
            ok, msg = _khal_change_storage_path(cal_name, new_dir, copy_old)
            def _after():
                storage_btn.set_tooltip_text(
                    msg if msg else "Storage location changed."
                    if ok else f"Failed: {msg}")
                if ok:
                    _build_grid(cur[0], cur[1])
            GLib.idle_add(_after)
        in_thread(_worker)

    storage_btn.connect("clicked", _on_storage_btn)

    CELL = 34   # kompakter (vorher 40) - jetzt, wo die Zellen die
                # schlanke .cal-cell-Klasse statt .bubble.item nutzen,
                # reicht das für gute Lesbarkeit und macht das ganze
                # Grid spürbar kleiner.
    wd_row = hbox(1)
    wd_row.set_halign(Gtk.Align.CENTER)
    for wd in DAYS_EN:
        b = hbox(0)
        b.get_style_context().add_class("bubble")
        b.get_style_context().add_class("cal-cell")
        b.set_size_request(CELL, -1)
        l = Gtk.Label(label=wd)
        l.set_halign(Gtk.Align.CENTER)
        l.set_size_request(CELL, -1)
        b.pack_start(l, False, False, 0)
        wd_row.pack_start(b, False, False, 0)
    t2.pack_start(wd_row, False, False, 0)

    khal_ok = _khal_available() and _khal_configured()
    if not khal_ok and _khal_available():
        setup_row = hbox(6)
        setup_row.set_halign(Gtk.Align.CENTER)
        setup_lbl = Gtk.Label(label="Events not set up yet")
        setup_lbl.get_style_context().add_class("caption")
        setup_btn = btn("Set up", tip="Creates a local default calendar")
        setup_row.pack_start(setup_lbl, False, False, 0)
        setup_row.pack_start(setup_btn, False, False, 0)
        t2.pack_start(setup_row, False, False, 2)

        def _on_setup_clicked(_w):
            ok, err = _khal_setup_default_calendar()
            if ok:
                setup_row.set_visible(False)
                _build_grid(cur[0], cur[1])
            else:
                setup_lbl.set_label(f"Einrichtung fehlgeschlagen: {err}"[:60])
        setup_btn.connect("clicked", _on_setup_clicked)

    cal_grid = vbox(1)
    cal_grid.set_halign(Gtk.Align.CENTER)
    t2.pack_start(cal_grid, False, False, 0)

    def _prompt_new_event(d) -> None:
        """Kleiner Termin-Dialog - eigenständiges Gtk.Dialog-Fenster."""
        dlg = Gtk.Dialog(title=f"New Event – {d.strftime('%d.%m.%Y')}",
                          transient_for=win)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Create", Gtk.ResponseType.OK)
        content = dlg.get_content_area()
        content.set_spacing(6)
        pad(content, h=14, v=10)

        title_e = Gtk.Entry()
        title_e.set_placeholder_text("Title")
        title_e.set_activates_default(True)
        time_e = Gtk.Entry()
        time_e.set_placeholder_text("Time, e.g. 14:30")
        time_e.set_text("12:00")
        time_e.set_activates_default(True)
        err_lbl = Gtk.Label(label="")
        err_lbl.get_style_context().add_class("caption")
        err_lbl.set_no_show_all(True)
        err_lbl.hide()

        content.pack_start(Gtk.Label(label="Title:"), False, False, 0)
        content.pack_start(title_e, False, False, 0)
        content.pack_start(Gtk.Label(label="Time:"), False, False, 0)
        content.pack_start(time_e, False, False, 0)
        content.pack_start(err_lbl, False, False, 0)

        ok_btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        if ok_btn:
            dlg.set_default(ok_btn)
        dlg.show_all()
        title_e.grab_focus()

        while True:
            resp = dlg.run()
            if resp != Gtk.ResponseType.OK:
                break
            ok, err = _khal_new_event(d, time_e.get_text(), title_e.get_text())
            if ok:
                break
            err_lbl.set_label(err[:80])
            err_lbl.show()
        dlg.destroy()
        _build_grid(cur[0], cur[1])

    def _show_day_detail(day_date, events: list) -> None:
        """Zeigt die Termine eines Tages INLINE im selben Fenster (statt
        in einem Gtk.Popover) - Popover-Positionierung ist unter
        Wayland/Hyprland kaputt, sobald das Elternfenster ein
        GtkLayerShell-Surface ist (genau das, was ALLE Bubble-Fenster
        hier sind, siehe make_win()): es kam nur eine abgeschnittene
        Fenster-Ecke ohne Text, weil GtkPopover dafür schlicht nicht
        vorgesehen ist. Stattdessen wird cal_grid (derselbe Container,
        derselbe bereits funktionierende Hintergrund/Rahmen) kurzzeitig
        gegen eine Detail-Ansicht getauscht, siehe Chat."""
        nav_row.set_visible(False)
        wd_row.set_visible(False)
        for c in cal_grid.get_children(): cal_grid.remove(c)

        detail = vbox(4)

        back_btn = btn("←", tip="Back to month",
                        cb=lambda _w: _close_day_detail())
        title = Gtk.Label()
        title.set_markup(f"<b>{day_date.strftime('%d.%m.%Y')}</b>")
        header = hrow(back_btn, title, sp=6)
        detail.pack_start(header, False, False, 0)
        detail.pack_start(sep(), False, False, 2)

        def _on_delete_event(ev: dict) -> None:
            """Löscht per _khal_delete_event() im Hintergrund, entfernt
            den Termin danach aus 'events' (derselben Liste, die auch
            in day_widgets[...] hängt - so bleibt der Karminrot-Glow
            der Tageszahl beim nächsten Neuaufbau automatisch korrekt)
            und baut die Detail-Ansicht mit dem aktuellen Stand neu
            auf. Bei Fehler bleibt der Termin einfach stehen, Fehler-
            text kommt ins Tooltip des Löschen-Buttons."""
            def _worker():
                ok, err = _khal_delete_event(ev.get("calendar", ""), ev.get("uid", ""))
                def _after():
                    if ok:
                        if ev in events:
                            events.remove(ev)
                        _show_day_detail(day_date, events)
                    else:
                        err_lbl = Gtk.Label(label=f"Delete failed: {err}"[:60])
                        err_lbl.get_style_context().add_class("caption")
                        detail.pack_start(err_lbl, False, False, 0)
                        detail.show_all()
                GLib.idle_add(_after)
            in_thread(_worker)

        if not events:
            empty = Gtk.Label(label="No events")
            empty.get_style_context().add_class("caption")
            detail.pack_start(empty, False, False, 0)
        else:
            for e in sorted(events, key=lambda e: e.get("start-time", "")):
                row = hbox(6)
                t = e.get("start-time", "")
                time_lbl = Gtk.Label(label=t if t else "–")
                time_lbl.get_style_context().add_class("caption")
                time_lbl.set_width_chars(5)
                title_lbl = Gtk.Label(label=e.get("title", "(untitled)"))
                title_lbl.set_halign(Gtk.Align.START)
                title_lbl.set_line_wrap(True)
                title_lbl.set_max_width_chars(28)
                del_btn = btn("🗑", tip="Delete event",
                               cb=lambda _w, ev=e: _on_delete_event(ev))
                row.pack_start(time_lbl, False, False, 0)
                row.pack_start(title_lbl, True, True, 0)
                row.pack_start(del_btn, False, False, 0)
                detail.pack_start(row, False, False, 0)

        add_row = hbox(6)
        add_row.set_halign(Gtk.Align.END)
        add_btn = btn("+ Event", cb=lambda _w: (_close_day_detail(),
                      _prompt_new_event(day_date)))
        add_row.pack_start(add_btn, False, False, 0)
        detail.pack_start(sep(), False, False, 2)
        detail.pack_start(add_row, False, False, 0)

        cal_grid.pack_start(detail, False, False, 0)
        cal_grid.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    def _close_day_detail() -> None:
        nav_row.set_visible(True)
        wd_row.set_visible(True)
        _build_grid(cur[0], cur[1])
        GLib.idle_add(_shrink_to_fit, win)

    def _on_day_click(anchor_widget, day_date, ev, day_events_ref: list):
        """Linksklick (Button 1) -> Termine dieses Tages zeigen. Der
        Rechtsklick zum direkten Anlegen wurde bewusst entfernt (siehe
        README/Chat) - Termine anlegen geht weiterhin ganz normal über
        den "+ Termin"-Button in der Tagesansicht."""
        if ev.button == 1:
            _show_day_detail(day_date, day_events_ref)
            return True
        return False

    def _build_grid(year, month):
        for c in cal_grid.get_children(): cal_grid.remove(c)
        today = datetime.now()
        day_widgets = {}  # date_str -> (button, inner_box, events_ref) für async Nachtragen der Punkte/Termine

        for week in calendar.monthcalendar(year, month):
            week_row = hbox(1)
            week_row.set_halign(Gtk.Align.CENTER)
            for day in week:
                if day == 0:
                    b = hbox(0)
                    b.get_style_context().add_class("bubble")
                    b.get_style_context().add_class("cal-cell")
                    b.set_size_request(CELL, -1)
                    l = Gtk.Label(label="")
                    l.set_opacity(0)
                    l.set_size_request(CELL, -1)
                    b.pack_start(l, False, False, 0)
                    week_row.pack_start(b, False, False, 0)
                    continue

                is_today = (day == today.day and month == today.month
                            and year == today.year)
                day_date = date(year, month, day)
                cell_lbl = f"<b>{day}</b>" if is_today else str(day)

                b = Gtk.Button()
                b.get_style_context().add_class("bubble")
                b.get_style_context().add_class("cal-cell")
                b.set_size_request(CELL, -1)
                b.set_can_focus(False)
                b.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
                if is_today:
                    b.get_style_context().add_class("active")

                inner = vbox(0)
                l = Gtk.Label()
                l.set_markup(cell_lbl)
                l.set_size_request(CELL, -1)
                l.set_halign(Gtk.Align.CENTER)
                l.get_style_context().add_class("caption")
                inner.pack_start(l, False, False, 0)

                b.add(inner)
                if khal_ok:
                    day_events_ref = []
                    b.connect("button-press-event",
                              lambda _w, ev, dd=day_date, evs=day_events_ref:
                                  _on_day_click(_w, dd, ev, evs))
                    day_widgets[day_date.strftime("%Y-%m-%d")] = (b, l, day_events_ref)
                week_row.pack_start(b, False, False, 0)
            cal_grid.pack_start(week_row, False, False, 0)
        cal_grid.show_all()

        if not khal_ok:
            return

        # Termine NICHT synchron im GTK-Main-Thread abfragen. Grid
        # steht sofort (klickbar, ohne Glow), Termin-Glow/Tooltips
        # werden nachgetragen, sobald der Hintergrund-Thread fertig ist.
        def _fetch():
            month_events = _khal_events_for_month(year, month)
            def _apply():
                # Falls der Nutzer inzwischen weitergeblättert hat, ist
                # cal_grid schon neu aufgebaut - dann NICHT mehr in die
                # (jetzt falsche) alte Widget-Zuordnung schreiben.
                if cur[0] != year or cur[1] != month:
                    return
                for date_str, events in month_events.items():
                    widgets = day_widgets.get(date_str)
                    if not widgets or not events:
                        continue
                    btn_w, day_lbl, events_ref = widgets
                    events_ref.extend(events)
                    day_lbl.get_style_context().add_class("has-event-glow")
                    tip = "\n".join(
                        f"{e.get('start-time', '')}  {e.get('title', '')}".strip()
                        for e in events[:6])
                    btn_w.set_tooltip_text(tip)
            GLib.idle_add(_apply)
        in_thread(_fetch)

    def _update_mth():
        mth_lbl.set_label(f"{MONTHS_EN[cur[1]-1]}  {cur[0]}")

    def _nav_prev(_):
        cur[1] -= 1
        if cur[1] < 1: cur[1] = 12; cur[0] -= 1
        _update_mth(); _build_grid(cur[0], cur[1])

    def _nav_next(_):
        cur[1] += 1
        if cur[1] > 12: cur[1] = 1; cur[0] += 1
        _update_mth(); _build_grid(cur[0], cur[1])

    prev_b.connect("clicked", _nav_prev)
    next_b.connect("clicked", _nav_next)
    _update_mth()
    _build_grid(cur[0], cur[1])

    def _update_time():
        n = datetime.now()
        time_lbl.set_label(n.strftime("%H:%M"))
        date_lbl.set_label(n.strftime("  %A, %B %d, %Y  "))
        return True

    add_timer(1000, _update_time)
    _update_time()

    def _load_weather():
        w = _fetch_weather()
        def _apply():
            icon_lbl.set_label(w["icon"])
            temp_lbl.set_label(w["temp"])
            desc_lbl.set_label(w["desc"])
            hum_lbl.set_label(f'💧 {w["humidity"]}')
            rain_lbl.set_label(f'☔ {w["precip"]}')
            d1_lbl.set_label(w["day1_icon"])
            d2_lbl.set_label(w["day2_icon"])
            loc_tip = f'Location: {w["location"]}\nClick 📍 to change'
            today_card.set_tooltip_text(loc_tip)
        GLib.idle_add(_apply)

    in_thread(_load_weather)
    add_timer(600_000, lambda: in_thread(_load_weather) or True)

    # ── Tabs zusammensetzen (gleiches Muster wie Media/Devices/Apps) ─
    stack.add_named(t1, "weather")
    stack.add_named(t2, "calendar")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch_tab(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, label in (("weather", "󰖐  Weather"),
                         ("calendar", "󰃭  Calendar")):
        b = btn(label, active=(name == "weather"))
        b.connect("clicked", lambda _b, n=name: _switch_tab(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)

    outer = vbox(4); safe_pad(outer, 460)
    outer.pack_start(tab_row, True, False, 2)
    outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack,   False, False, 0)
    return outer

def build_clock(win: Gtk.Window):
    win.set_default_size(460, 1)
    win.add(_clock_content(win))

# ════════════════════════════════════════════════════════════
#  SETTINGS
# ════════════════════════════════════════════════════════════
BACKUP_DIR = Path(HOME) / ".config" / "wb-daemon" / "backups"

# ── Race-Schutz für hyprland.lua ────────────────────────────────────
# Seit Einstellungen sofort statt über Apply/Discard übernommen werden
# (siehe apply_change()), kann JEDE Feldänderung (Res, Hz, Scale, HDR,
# Position - auch über MEHRERE Monitore hinweg) einen eigenen
# Hintergrund-Thread anstoßen, der read-modify-write auf derselben
# hyprland.lua macht. Ohne Synchronisierung können zwei solcher Threads
# gleichzeitig lesen/schreiben - der spätere Schreibvorgang überschreibt
# dann blind, was der frühere gerade erst geschrieben hat (verlorene
# Änderungen), und Path.write_text() ist zusätzlich NICHT atomar (es
# LEERT die Datei sofort beim Öffnen und schreibt den Inhalt erst
# danach) - ein read_text() eines anderen Threads GENAU in diesem
# schmalen Fenster sieht dann eine leere/abgeschnittene Datei. Bestätigt
# als Ursache für kaputte hyprland.lua (verdoppelte hl.monitor-Blöcke,
# verlorene "local"-Keywords, fehlende Kommentare) nach schnell
# hintereinander geänderter Auflösung, siehe Chat. Behoben durch: (1)
# ein globales Lock, das alle hyprland.lua-Schreibzugriffe serialisiert,
# und (2) atomares Schreiben per os.replace() statt write_text().
_HYPR_LUA_LOCK = threading.Lock()

def atomic_write_text(path: Path, text: str) -> None:
    """Wie path.write_text(text), aber atomar: schreibt zuerst in eine
    temporäre Datei im selben Verzeichnis und ersetzt die Zieldatei dann
    per os.replace() - auf Linux ein einziger atomarer rename()-Syscall.
    Ein gleichzeitiger Lesevorgang (von diesem Daemon oder extern, z.B.
    Hyprland selbst beim Reload) sieht dadurch IMMER entweder die
    komplette alte ODER die komplette neue Datei, nie einen
    abgeschnittenen Zwischenzustand."""
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)

def apply_change(desc: str, apply_fn, on_status=None, reset_fn=None) -> None:
    """Ersetzt das frühere Stage/Apply/Discard-System (PendingChange +
    Apply-Leiste): JEDE Einstellung wird jetzt sofort übernommen, sobald
    sie ausgewählt wird - kein "pending"-Zustand mehr, kein Cancel/
    Apply-Klick nötig. apply_fn läuft in einem Hintergrund-Thread (die
    Änderungen dahinter sind i.d.R. blockierende subprocess-/D-Bus-
    Aufrufe, sonst würde die UI beim Klick kurz einfrieren).

    on_status(text) - falls angegeben - bekommt optional "Applying…"
    und danach "Applied ✓" bzw. eine Fehlermeldung, als Ersatz für die
    frühere gemeinsame Statuszeile in der Apply-Leiste.

    reset_fn wird NUR bei einem Fehler aufgerufen, um das betroffene
    Widget wieder auf den tatsächlichen (unveränderten) Zustand
    zurückzusetzen - die aufrufende Stelle gibt beim Klick i.d.R. schon
    sofortiges optisches Feedback (z.B. Toggle-Label umschalten), bevor
    apply_fn überhaupt fertig ist; reset_fn korrigiert das wieder, falls
    apply_fn dann doch fehlschlägt."""
    if on_status:
        on_status("Applying…")

    def _worker():
        err = None
        try:
            apply_fn()
        except Exception as e:
            err = str(e)
        def _finish():
            if err and reset_fn:
                try: reset_fn()
                except Exception: pass
            if on_status:
                on_status(f"Error: {err}" if err else "Applied ✓")
            return False
        GLib.idle_add(_finish)

    in_thread(_worker)

def _prompt_text_generic(win: Gtk.Window, title: str, placeholder: str,
                          initial: str = "") -> str | None:
    """Kleiner Text-Eingabe-Dialog - eigenständiges Gtk.Dialog-Fenster
    (floating/pinned via set_keep_above) statt Inline-Entry im Layer-
    Shell-Popup, da letztere keinen Tastaturfokus bekommen können
    (KeyboardMode.NONE). Global wiederverwendbare Version des zuerst
    im Display-Widget lokal gebauten _prompt_text() - wird jetzt auch
    von der Appearance&Language-Seite für Custom-Locale/Custom-Layout
    genutzt. Gibt den eingegebenen Text zurück, oder None bei
    Abbruch/leerer Eingabe."""
    dlg = Gtk.Dialog(title=title, transient_for=win)
    dlg.set_name("wb-daemon-popup")
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                    "Apply", Gtk.ResponseType.OK)
    e = Gtk.Entry()
    e.set_placeholder_text(placeholder)
    if initial:
        e.set_text(initial)
    e.set_activates_default(True)
    e.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
    dlg.get_content_area().pack_start(e, True, True, 12)
    dlg.show_all()
    resp = dlg.run()
    val = e.get_text().strip() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    return val or None

def backup_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (BACKUP_DIR / f"{path.name}.{stamp}.bak").write_bytes(path.read_bytes())
    except Exception:
        pass

def _settings_category_row(icon: str, label: str, desc: str, cb) -> Gtk.Button:
    b = Gtk.Button()
    b.get_style_context().add_class("bubble")
    b.get_style_context().add_class("item")
    b.set_can_focus(False)
    b.set_halign(Gtk.Align.CENTER)
    row = hbox(10)
    icon_l = Gtk.Label(label=icon)
    icon_l.get_style_context().add_class("icon-lg")
    txt = vbox(0)
    title_l = Gtk.Label(label=label)
    title_l.get_style_context().add_class("value-md")
    title_l.set_halign(Gtk.Align.CENTER)
    title_l.set_justify(Gtk.Justification.CENTER)
    desc_l = Gtk.Label(label=desc)
    desc_l.get_style_context().add_class("caption")
    desc_l.set_halign(Gtk.Align.CENTER)
    desc_l.set_justify(Gtk.Justification.CENTER)
    desc_l.set_opacity(0.6)
    txt.pack_start(title_l, False, False, 0)
    txt.pack_start(desc_l, False, False, 0)
    row.pack_start(icon_l, False, False, 0)
    row.pack_start(txt, False, False, 0)
    b.add(row)
    b.connect("clicked", cb)
    return b

def _build_settings_placeholder(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(
        bitem(f"{label}: not implemented yet — coming in a future update.", dim=True),
        False, False, 0)

def _build_settings_network(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_network_content(win), True, True, 0)

def _build_settings_appearance(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    # 3 Unterreiter statt einer einzigen langen Liste (Sachen aus dem
    # README, die sich alle auf "Appearance & Language" bezogen):
    # SOUND (System Sounds + Sound Events), LOOK (Theme + Cursor),
    # LANGUAGE (Systemsprache + Tastaturlayout). Titel "Appearance &
    # Language" + Trennstrich packt der Aufrufer (_open_category() in
    # build_settings()) schon VOR diesem Funktionsaufruf auf `page` -
    # hier kommt nur noch der Tab-Umschalter + Gtk.Stack rein.
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    t_sound = vbox(4)
    t_look  = vbox(4)
    t_lang  = vbox(4)

    # Gemeinsame Statuszeile für alle Einstellungen dieser Seite (über
    # alle 3 Tabs hinweg EINE einzige, unterhalb des Stacks, damit sie
    # beim Tab-Wechsel nicht mit verschwindet) - jede Änderung wird
    # sofort übernommen (siehe apply_change()), es gibt keine
    # Apply/Discard-Leiste mehr. Zeigt kurz "Applying…" bzw. das
    # Ergebnis, ähnlich der Statuszeile pro Monitor auf der Display-Seite.
    appearance_status_lbl = Gtk.Label(label="")
    appearance_status_lbl.get_style_context().add_class("caption")
    appearance_status_lbl.set_opacity(0.75)
    appearance_status_lbl.set_line_wrap(True)
    appearance_status_lbl.set_no_show_all(True)
    appearance_status_lbl.hide()

    def _flash_appearance_status(text: str, ms: int = 3000):
        appearance_status_lbl.set_label(text)
        appearance_status_lbl.show()
        GLib.timeout_add(ms, lambda: (appearance_status_lbl.hide(), False)[1])

    # ══════════════════════════ TAB: LOOK ════════════════════════════
    # Theme + Cursor effects in EINER Zeile statt zwei getrennten
    # Sektionen mit eigenem Header+Trennstrich dazwischen (README-
    # Feedback: "Appearance, da kann man viel Platz sparen, Sachen
    # nebeneinander machen") - Shake-to-find bleibt eine eigene Zeile
    # darunter, weil sie von "Cursor effects" abhängt (nur aktiv, wenn
    # das an ist) und optisch als Unterpunkt lesbar bleiben soll.
    t_look.pack_start(bsec("APPEARANCE & CURSOR"), False, False, 0)
    dark_row = hbox(10)
    dark_lbl = Gtk.Label(label="Theme:")
    dark_lbl.get_style_context().add_class("caption")
    dark_toggle = btn("", active=_is_dark_mode())
    def _refresh_dark_label():
        is_dark = _is_dark_mode()
        dark_toggle.set_label("Dark" if is_dark else "Light")
        ctx = dark_toggle.get_style_context()
        if is_dark: ctx.add_class("active")
        else:       ctx.remove_class("active")
    _refresh_dark_label()

    def _on_dark_toggle(_w):
        new_dark = not _is_dark_mode()
        def _apply():
            ok, err = _set_dark_mode(new_dark)
            if not ok:
                raise RuntimeError(err)
        def _reset():
            _refresh_dark_label()
        # Sofortiges visuelles Feedback am Button selbst, bevor
        # apply_fn im Hintergrund fertig ist - _is_dark_mode() liest ja
        # erst NACH dem Apply den neuen Zustand, bis dahin zeigt der
        # Button sonst noch den alten Zustand. Schlägt der Apply doch
        # fehl, macht _reset() das wieder rückgängig.
        dark_toggle.set_label("Dark" if new_dark else "Light")
        ctx = dark_toggle.get_style_context()
        if new_dark: ctx.add_class("active")
        else:        ctx.remove_class("active")
        apply_change(f"Theme: {'Dark' if new_dark else 'Light'}", _apply,
                     on_status=_flash_appearance_status, reset_fn=_reset)

    dark_toggle.connect("clicked", _on_dark_toggle)
    # Ehrlicher Hinweis statt eines leeren Versprechens: GTK/Firefox
    # ziehen i.d.R. live nach (gsettings + Portal-Neustart, siehe
    # _broadcast_theme_change), Qt/Kvantum-Apps können das laut
    # Kvantum-Upstream technisch NICHT ohne Neustart - kein Bug hier,
    # sondern eine Qt-Plattform-Grenze. Steht jetzt nur noch als
    # Tooltip da statt als eigener, klein gedruckter Textblock.
    dark_toggle.set_tooltip_text(
        "GTK & Firefox switch live. Qt/Kvantum apps need a restart to fully redraw.")

    # ── Cursor: dynamic_cursors Plugin (Tilt/Stretch-Effekte + Shake-to-Find) ──
    cursor_lbl = Gtk.Label(label="Cursor effects:")
    cursor_lbl.get_style_context().add_class("caption")
    cursor_toggle = btn("", active=_cursor_plugin_enabled())

    shake_row = hbox(8)
    shake_lbl = Gtk.Label(label="Shake-to-find:")
    shake_lbl.get_style_context().add_class("caption")
    shake_toggle = btn("", active=_cursor_shake_enabled())

    def _refresh_cursor_toggle(enabled: bool):
        cursor_toggle.set_label("On" if enabled else "Off")
        ctx = cursor_toggle.get_style_context()
        if enabled: ctx.add_class("active")
        else:       ctx.remove_class("active")
        # Shake ergibt nur Sinn, wenn das Plugin selbst überhaupt an ist
        shake_row.set_sensitive(enabled)

    def _refresh_shake_toggle(enabled: bool):
        shake_toggle.set_label("On" if enabled else "Off")
        ctx = shake_toggle.get_style_context()
        if enabled: ctx.add_class("active")
        else:       ctx.remove_class("active")

    _refresh_cursor_toggle(_cursor_plugin_enabled())
    _refresh_shake_toggle(_cursor_shake_enabled())

    def _on_cursor_toggle(_w):
        new_val = not _cursor_plugin_enabled()
        def _apply():
            ok, err = _set_cursor_plugin_enabled(new_val)
            if not ok:
                raise RuntimeError(err)
        def _reset():
            _refresh_cursor_toggle(_cursor_plugin_enabled())
        _refresh_cursor_toggle(new_val)  # sofortiges visuelles Feedback, siehe Dark-Mode-Toggle oben
        apply_change(f"Cursor effects: {'On' if new_val else 'Off'}", _apply,
                     on_status=_flash_appearance_status, reset_fn=_reset)

    def _on_shake_toggle(_w):
        new_val = not _cursor_shake_enabled()
        def _apply():
            ok, err = _set_cursor_shake_enabled(new_val)
            if not ok:
                raise RuntimeError(err)
        def _reset():
            _refresh_shake_toggle(_cursor_shake_enabled())
        _refresh_shake_toggle(new_val)
        apply_change(f"Shake-to-find: {'On' if new_val else 'Off'}", _apply,
                     on_status=_flash_appearance_status, reset_fn=_reset)

    cursor_toggle.connect("clicked", _on_cursor_toggle)
    shake_toggle.connect("clicked", _on_shake_toggle)

    _cursor_reload_tip = "Applies after 'hyprctl reload' or next Hyprland start."
    cursor_toggle.set_tooltip_text(_cursor_reload_tip)
    shake_toggle.set_tooltip_text(_cursor_reload_tip)

    dark_row.pack_start(dark_lbl, False, False, 0)
    dark_row.pack_start(dark_toggle, False, False, 0)
    dark_row.pack_start(cursor_lbl, False, False, 0)
    dark_row.pack_start(cursor_toggle, False, False, 0)
    t_look.pack_start(dark_row, False, False, 0)

    shake_row.pack_start(shake_lbl, False, False, 0)
    shake_row.pack_start(shake_toggle, False, False, 0)
    t_look.pack_start(shake_row, False, False, 0)

    # ══════════════════════════ TAB: SOUND ═══════════════════════════
    # ── Systemsounds: globaler An/Aus-Schalter (SoundCenter.sh) ──────
    # Steuert dieselbe State-Datei, die SoundCenter.sh selbst prüft - dieser
    # Switch hier ist also nur EIN möglicher Ort, an dem man umschalten
    # kann, kein eigener Zustand. Genau wie beim Dark-Toggle: sofortiges
    # visuelles Feedback am Button, bevor die Datei tatsächlich geschrieben
    # ist, mit _reset() als Fallback bei Fehlern.
    t_sound.pack_start(bsec("SYSTEM SOUNDS"), False, False, 0)
    sound_row = hbox(8)
    sound_lbl = Gtk.Label(label="Click/UI sounds:")
    sound_lbl.get_style_context().add_class("caption")
    sound_toggle = btn("", active=_sounds_enabled())

    def _refresh_sound_toggle(enabled: bool):
        sound_toggle.set_label("On" if enabled else "Off")
        ctx = sound_toggle.get_style_context()
        if enabled: ctx.add_class("active")
        else:       ctx.remove_class("active")

    _refresh_sound_toggle(_sounds_enabled())

    def _on_sound_toggle(_w):
        new_val = not _sounds_enabled()
        def _apply():
            _set_sounds_enabled(new_val)
        def _reset():
            _refresh_sound_toggle(_sounds_enabled())
        _refresh_sound_toggle(new_val)  # sofortiges visuelles Feedback, siehe Dark-Mode-Toggle oben
        apply_change(f"System sounds: {'On' if new_val else 'Off'}", _apply,
                     on_status=_flash_appearance_status, reset_fn=_reset)

    sound_toggle.connect("clicked", _on_sound_toggle)
    sound_row.pack_start(sound_lbl, False, False, 0)
    sound_row.pack_start(sound_toggle, False, False, 0)
    t_sound.pack_start(sound_row, False, False, 0)

    # ── Systemsounds: pro Event einzeln (SOUND_EVENTS) ───────────────
    # Gleiches Muster wie der globale Schalter direkt darüber, nur pro
    # Event statt global - nutzt SoundControls --status/--enable/
    # --disable MIT Event-Namen (siehe _event_sound_enabled/
    # _set_event_sound_enabled oben), läuft also über dieselben
    # Statusdateien, die SoundDaemon beim Abspielen sowieso schon prüft.
    # Wirkt nur, wenn der globale Schalter oben an ist (Master UND Event
    # müssen beide an sein, damit ein Sound tatsächlich spielt - exakt
    # wie im SoundDaemon-Code selbst).
    t_sound.pack_start(sep(), False, False, 3)
    t_sound.pack_start(bsec("SOUND EVENTS"), False, False, 0)

    def _make_sound_event_row(event: str) -> Gtk.Box:
        row = hbox(6)
        row.set_hexpand(True)
        lbl = Gtk.Label(label=event)
        lbl.get_style_context().add_class("caption")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        toggle = btn("", active=_event_sound_enabled(event))

        def _refresh(enabled: bool, _toggle=toggle):
            _toggle.set_label("On" if enabled else "Off")
            ctx = _toggle.get_style_context()
            if enabled: ctx.add_class("active")
            else:       ctx.remove_class("active")

        _refresh(_event_sound_enabled(event))

        def _on_event_toggle(_w, _event=event, _refresh=_refresh):
            new_val = not _event_sound_enabled(_event)
            def _apply():
                _set_event_sound_enabled(_event, new_val)
            def _reset():
                _refresh(_event_sound_enabled(_event))
            _refresh(new_val)  # sofortiges visuelles Feedback, siehe Dark-Mode-Toggle oben
            apply_change(f"{_event} sound: {'On' if new_val else 'Off'}", _apply,
                         on_status=_flash_appearance_status, reset_fn=_reset)

        toggle.connect("clicked", _on_event_toggle)
        row.pack_start(lbl, True, True, 0)
        row.pack_start(toggle, False, False, 0)
        return row

    # 2 Spalten statt 1 - bei 11 Events sind das 6 Zeilen statt 11,
    # spart ordentlich Höhe (README-Feedback: "Appearance, da kann man
    # viel Platz sparen, Sachen nebeneinander machen").
    _events_grid = Gtk.Grid()
    _events_grid.set_column_homogeneous(True)
    _events_grid.set_column_spacing(14)
    _events_grid.set_row_spacing(2)
    for idx, _event in enumerate(SOUND_EVENTS):
        _events_grid.attach(_make_sound_event_row(_event), idx % 2, idx // 2, 1, 1)
    t_sound.pack_start(_events_grid, False, False, 0)

    # ═════════════════════════ TAB: LANGUAGE ═════════════════════════
    # ── Language: Systemsprache (locale) ─────────────────────────────
    t_lang.pack_start(bsec("LANGUAGE"), False, False, 0)
    CUSTOM_LABEL = "Custom…"
    cur_locale = _current_locale()
    lang_combo = Gtk.ComboBoxText()
    lang_combo.get_style_context().add_class("bubble")
    lang_combo.get_style_context().add_class("dropdown")
    lang_combo.set_can_focus(False)
    for name, loc, _kb in LANGUAGE_PRESETS:
        lang_combo.append_text(f"{name}  ({loc})")
    lang_combo.append_text(CUSTOM_LABEL)
    preset_locales = [loc for _n, loc, _kb in LANGUAGE_PRESETS]
    if cur_locale in preset_locales:
        lang_combo.set_active(preset_locales.index(cur_locale))
    else:
        lang_combo.set_active(len(LANGUAGE_PRESETS))  # Custom, falls z.B. schon eine seltenere Locale aktiv ist

    lang_custom_state = {"locale": cur_locale if cur_locale not in preset_locales else ""}
    lang_custom_btn = Gtk.Button()
    lang_custom_btn.get_style_context().add_class("bubble")
    lang_custom_btn.set_can_focus(False)
    lang_custom_btn.set_no_show_all(True)

    def _prompt_locale():
        val = _prompt_text_generic(win, "Custom language",
                                    "e.g. pt_BR.UTF-8",
                                    initial=lang_custom_state["locale"])
        if val:
            lang_custom_state["locale"] = val.strip()
            lang_custom_btn.set_label(lang_custom_state["locale"])
        _stage_lang()

    def _update_lang_custom_visibility():
        is_custom = lang_combo.get_active_text() == CUSTOM_LABEL
        lang_custom_btn.set_visible(is_custom)
        if is_custom:
            lang_custom_btn.set_label(
                lang_custom_state["locale"] or "(tap to enter)")

    def _stage_lang():
        if lang_combo.get_active_text() == CUSTOM_LABEL:
            locale = lang_custom_state["locale"]
        else:
            idx = lang_combo.get_active()
            locale = LANGUAGE_PRESETS[idx][1] if 0 <= idx < len(LANGUAGE_PRESETS) else ""
        if not locale:
            return
        def _apply():
            ok, err = _set_system_locale(locale)
            if not ok:
                raise RuntimeError(err)
        apply_change(f"Language: {locale}", _apply, on_status=_flash_appearance_status)

    def _on_lang_change(_w):
        _update_lang_custom_visibility()
        if lang_combo.get_active_text() == CUSTOM_LABEL:
            _prompt_locale()
        else:
            _stage_lang()

    lang_combo.connect("changed", _on_lang_change)
    lang_custom_btn.connect("clicked", lambda _w: _prompt_locale())
    _update_lang_custom_visibility()
    lang_combo.set_tooltip_text("Usually applies after logging out and back in.")
    lang_row = hrow(lang_combo, lang_custom_btn, sp=8)
    t_lang.pack_start(lang_row, False, False, 0)

    t_lang.pack_start(sep(), False, False, 3)

    # ── Keyboard Layout ───────────────────────────────────────────────
    t_lang.pack_start(bsec("KEYBOARD LAYOUT"), False, False, 0)
    cur_kb = _current_kb_layout()
    kb_combo = Gtk.ComboBoxText()
    kb_combo.get_style_context().add_class("bubble")
    kb_combo.get_style_context().add_class("dropdown")
    kb_combo.set_can_focus(False)
    for name, _loc, kb in LANGUAGE_PRESETS:
        kb_combo.append_text(f"{name}  ({kb})")
    kb_combo.append_text(CUSTOM_LABEL)
    preset_kbs = [kb for _n, _l, kb in LANGUAGE_PRESETS]
    if cur_kb in preset_kbs:
        kb_combo.set_active(preset_kbs.index(cur_kb))
    else:
        kb_combo.set_active(len(LANGUAGE_PRESETS))

    kb_custom_state = {"layout": cur_kb if cur_kb not in preset_kbs else ""}
    kb_custom_btn = Gtk.Button()
    kb_custom_btn.get_style_context().add_class("bubble")
    kb_custom_btn.set_can_focus(False)
    kb_custom_btn.set_no_show_all(True)

    def _prompt_kb():
        val = _prompt_text_generic(win, "Benutzerdefiniertes Layout",
                                    "z.B. pt (xkb-Layout-Code)",
                                    initial=kb_custom_state["layout"])
        if val:
            kb_custom_state["layout"] = val.strip()
            kb_custom_btn.set_label(kb_custom_state["layout"])
        _stage_kb()

    def _update_kb_custom_visibility():
        is_custom = kb_combo.get_active_text() == CUSTOM_LABEL
        kb_custom_btn.set_visible(is_custom)
        if is_custom:
            kb_custom_btn.set_label(
                kb_custom_state["layout"] or "(antippen zum Eingeben)")

    def _stage_kb():
        if kb_combo.get_active_text() == CUSTOM_LABEL:
            layout = kb_custom_state["layout"]
        else:
            idx = kb_combo.get_active()
            layout = LANGUAGE_PRESETS[idx][2] if 0 <= idx < len(LANGUAGE_PRESETS) else ""
        if not layout:
            return
        def _apply():
            ok, err = _set_kb_layout(layout)
            if not ok:
                raise RuntimeError(err)
        apply_change(f"Tastatur: {layout}", _apply, on_status=_flash_appearance_status)

    def _on_kb_change(_w):
        _update_kb_custom_visibility()
        if kb_combo.get_active_text() == CUSTOM_LABEL:
            _prompt_kb()
        else:
            _stage_kb()

    kb_combo.connect("changed", _on_kb_change)
    kb_custom_btn.connect("clicked", lambda _w: _prompt_kb())
    _update_kb_custom_visibility()
    kb_combo.set_tooltip_text("Applies after 'hyprctl reload' or next Hyprland start.")
    kb_row = hrow(kb_combo, kb_custom_btn, sp=8)
    t_lang.pack_start(kb_row, False, False, 0)

    # ══════════════════════ Tabs zusammensetzen ══════════════════════
    stack.add_named(t_sound, "sound")
    stack.add_named(t_look,  "look")
    stack.add_named(t_lang,  "language")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, tlabel in (("sound", "🔊  Sound"), ("look", "🎨  Look"),
                          ("language", "🌐  Language")):
        b = btn(tlabel, active=(name == "sound"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("sound")

    page.pack_start(tab_row, True, False, 2)
    page.pack_start(tab_sep(), False, False, 0)
    page.pack_start(stack, False, False, 0)
    page.pack_start(appearance_status_lbl, False, False, 6)

def _build_settings_battery(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_akku_and_sysmon_content(win), True, True, 0)

def _hypr_lua_path() -> Path:
    return Path(HOME) / ".config" / "hypr" / "hyprland.lua"

# ════════════════════════════════════════════════════════════
#  Appearance & Language
# ════════════════════════════════════════════════════════════
KVANTUM_CONF   = Path(HOME) / ".config" / "Kvantum" / "kvantum.kvconfig"
KVANTUM_LIGHT  = "TrafkTux-Kvantum-Theme"
KVANTUM_DARK   = "TrafkTux-Kvantum-ThemeDark"
GTK_THEME_NAME = "TrafkTux-GTK-Theme"

# GTK liest 'gtk-application-prefer-dark-theme' NICHT nur aus
# gsettings/dconf, sondern (v.a. außerhalb einer vollen GNOME-Session,
# wie hier unter Hyprland) beim Start JEDER App direkt aus dieser
# Datei. Wurde nur gsettings gesetzt, stand hier weiterhin der fest
# einprogrammierte Ausgangswert (siehe settings.ini) - jede neu
# gestartete App zeigte also wieder den ALTEN/Default-Zustand statt
# dem, was gerade am System aktiv war. Siehe _set_gtk_settings_ini_key
# und deren Aufruf in _set_dark_mode().
GTK3_SETTINGS_INI = Path(HOME) / ".config" / "gtk-3.0" / "settings.ini"
GTK4_SETTINGS_INI = Path(HOME) / ".config" / "gtk-4.0" / "settings.ini"

def _kvantum_current_theme() -> str:
    """Liest den aktuell gewählten Kvantum-Theme-Namen direkt aus
    ~/.config/Kvantum/kvantum.kvconfig ([General] theme=...) - dieser
    Aufbau wurde am echten System verifiziert (nicht nur aus
    Kvantum-Doku extrapoliert), um Format-Rätselraten zu vermeiden."""
    try:
        txt = KVANTUM_CONF.read_text()
        m = re.search(r'^\s*theme\s*=\s*(.+)$', txt, re.M)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return KVANTUM_LIGHT  # Default-Annahme, falls Datei fehlt/leer

def _is_dark_mode() -> bool:
    """Was das Widget als 'ist gerade Dark Mode aktiv' anzeigt - LIVE
    aus der 'gtk-application-prefer-dark-theme'-Property des eigenen
    Gtk.Settings-Objekts gelesen, NICHT (mehr) nur aus der Kvantum-
    Config. Grund für den Wechsel: 'gtk-application-prefer-dark-theme'
    wird laut GTK/Wayland-Doku NIE live aus gsettings/dconf gelesen,
    sondern IMMER aus settings.ini beim Start jedes Prozesses (siehe
    GTK3_SETTINGS_INI oben) - das ist also exakt der Wert, den auch
    jede andere GTK-App gerade sieht/anzeigt. Verließ sich dieser Check
    nur auf die Kvantum-Config, konnte er beim allerersten Öffnen
    (bevor je über dieses Widget umgeschaltet wurde) danebenliegen:
    Kvantum-Config fehlte/stand auf ihrem Light-Fallback-Default,
    während settings.ini längst auf 'gtk-application-prefer-dark-
    theme=1' stand - der Button zeigte dann fälschlich 'Light', obwohl
    das System sichtbar im Dark-Modus lief. Gtk.Settings.get_default()
    liefert genau das, was DIESER Prozess (der Daemon) beim eigenen
    Start aus settings.ini gelesen hat, und wird von _set_dark_mode()
    unten sofort live nachgezogen - kann also nie mehr vom tatsächlich
    sichtbaren Zustand abweichen, auch nicht direkt nach dem Umschalten
    und ohne Neustart des Daemons."""
    settings = Gtk.Settings.get_default()
    if settings is not None:
        try:
            return bool(settings.get_property("gtk-application-prefer-dark-theme"))
        except Exception:
            pass
    # Fallback, falls aus irgendeinem Grund kein Gtk.Settings verfügbar
    # ist (sollte in einer laufenden GTK-App eigentlich nie passieren)
    # - dann wenigstens auf die Kvantum-Config zurückfallen statt zu
    # crashen.
    return _kvantum_current_theme() == KVANTUM_DARK

def _set_gtk_settings_ini_key(path: Path, key: str, value: str,
                               create_if_missing: bool) -> tuple[bool, str]:
    """Setzt/aktualisiert 'key=value' im [Settings]-Abschnitt einer GTK
    settings.ini (gtk-3.0 UND gtk-4.0 haben exakt dasselbe simple
    Format: eine [Settings]-Section, key=value-Zeilen - am echten,
    hochgeladenen settings.ini verifiziert). Das ist die Datei, aus der
    viele GTK-Apps 'gtk-application-prefer-dark-theme' beim Start lesen
    - unabhängig davon, was gsettings/dconf sagt. Bleibt sie hier auf
    dem alten Wert stehen, zeigt jede frisch gestartete App wieder den
    falschen Zustand.

    create_if_missing=False: eine (noch) nicht vorhandene Datei wird
    bewusst NICHT angelegt (z.B. gtk-4.0/settings.ini, falls der Nutzer
    nie eine hatte) - kein ungefragtes Erzeugen neuer Config-Dateien.
    Fehlt die Datei in diesem Fall, ist das kein Fehler (True, "")."""
    try:
        if not path.is_file():
            if not create_if_missing:
                return True, ""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"[Settings]\n{key}={value}\n")
            return True, ""

        backup_file(path)
        txt = path.read_text()
        key_re = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*).*$', re.M)
        if key_re.search(txt):
            txt = key_re.sub(rf'\g<1>{value}', txt, count=1)
        elif re.search(r'^\[Settings\]\s*$', txt, re.M):
            txt = re.sub(r'(^\[Settings\]\s*$)', rf'\1\n{key}={value}',
                          txt, count=1, flags=re.M)
        else:
            txt = f"[Settings]\n{key}={value}\n" + txt
        path.write_text(txt)
        return True, ""
    except Exception as e:
        return False, f"{path.name}: {e}"

def _broadcast_theme_change() -> None:
    """Best-effort 'sag allen laufenden Apps JETZT Bescheid' - bewusst
    ohne irgendetwas zu schließen/neu zu starten, das der Nutzer selbst
    offen hat. Rein fire-and-forget: jeder Schritt läuft unabhängig,
    ein fehlender/inaktiver Dienst darf die anderen nicht verhindern
    und darf NIE den eigentlichen Theme-Wechsel (siehe _set_dark_mode)
    zum Scheitern bringen - darum wird hier nichts zurückgegeben und
    kein Fehler propagiert.

    Kanal 1 - xdg-desktop-portal(-gtk): Genau DAS ist der Weg, über den
    Firefox (und jede andere Portal-fähige App im 'System/Auto'-Theme-
    Modus) live von einem Farbschema-Wechsel erfährt - der Portal-
    Daemon abonniert denselben gsettings-Key
    (org.gnome.desktop.interface color-scheme), den _set_dark_mode()
    weiter oben setzt, und sendet dann selbst ein 'SettingChanged'-
    Signal über org.freedesktop.portal.Settings. Hat der schon länger
    laufende Daemon die dconf-Änderung aus irgendeinem Grund verpasst
    oder verzögert verarbeitet (in der Praxis der häufigste Grund,
    warum Firefox nicht mitzieht), hilft ein Neustart zuverlässig, weil
    der Daemon beim Hochfahren seinen Zustand frisch einliest.
    'try-restart' statt 'restart': startet den Dienst NUR, wenn er
    schon aktiv lief - läuft hier gar kein Portal (z.B. weil keiner
    installiert/konfiguriert ist), passiert nichts, statt ungefragt
    einen neuen Hintergrunddienst hochzuziehen.

    Kanal 2 - Kvantum/Qt: Kvantum ist laut Upstream (tsujan/Kvantum,
    'Live theme reloading' Diskussion) technisch NICHT in der Lage,
    laufende Qt-Apps ohne Neustart umzustyle - das ist eine
    Qt-Plattform-Einschränkung (nur ein 'platform theme'-Plugin dürfte
    das, Kvantum ist nur ein Style-Plugin), keine Lücke, die sich per
    Skript schließen lässt. Darum wird hier bewusst NICHTS für Qt/
    Kvantum vorgetäuscht - offene Qt-Apps brauchen für ein volles
    Redraw weiterhin einen Neustart, siehe Hinweistext im UI."""
    for cmd in (
        ["systemctl", "--user", "try-restart", "xdg-desktop-portal-gtk.service"],
        ["systemctl", "--user", "try-restart", "xdg-desktop-portal.service"],
    ):
        try:
            run_ec(cmd, timeout=5)
        except Exception:
            pass

def _set_dark_mode(dark: bool) -> tuple[bool, str]:
    """Setzt Kvantum-Theme UND GTK-Dark-Preference in einem Rutsch -
    bewusst EIN gemeinsamer Umschalter (nicht zwei getrennte), damit
    Kvantum (Qt-Apps) und GTK-Apps nie auseinanderlaufen können. GTK-
    Theme-NAME bleibt bei TrafkTux-GTK-Theme (es gibt kein separates
    Dark-Pendant davon) - nur color-scheme schaltet um; das GTK-Theme
    selbst muss diese Einstellung respektieren (die meisten modernen
    Themes tun das). WICHTIG: 'gtk-application-prefer-dark-theme' (der
    ältere Key, boolean true/false) ist mittlerweile aus
    gsettings-desktop-schemas entfernt/deprecated (siehe GNOME-
    Diskussionen/Migrationsartikel dazu) - 'gsettings set' schlägt
    damit mit 'No such key' fehl, was den Change dauerhaft als
    "pending" hängen ließ, da apply_all() einen fehlgeschlagenen
    Change absichtlich NICHT aus der Pending-Liste entfernt. Der
    aktuelle, korrekte Ersatz ist 'color-scheme' mit den Werten
    "prefer-dark"/"prefer-light" (kein Boolean mehr)."""
    try:
        KVANTUM_CONF.parent.mkdir(parents=True, exist_ok=True)
        theme_name = KVANTUM_DARK if dark else KVANTUM_LIGHT
        if KVANTUM_CONF.is_file():
            backup_file(KVANTUM_CONF)
            txt = KVANTUM_CONF.read_text()
            if re.search(r'^\s*theme\s*=', txt, re.M):
                txt = re.sub(r'^(\s*theme\s*=\s*).+$', rf'\g<1>{theme_name}',
                              txt, count=1, flags=re.M)
            elif re.search(r'^\[General\]', txt, re.M):
                txt = re.sub(r'(^\[General\]\s*$)', rf'\1\ntheme={theme_name}',
                              txt, count=1, flags=re.M)
            else:
                txt = f"[General]\ntheme={theme_name}\n" + txt
        else:
            txt = f"[General]\ntheme={theme_name}\n"
        KVANTUM_CONF.write_text(txt)
    except Exception as e:
        return False, f"Kvantum-Config: {e}"

    _out, err, ec = run_ec([
        "gsettings", "set", "org.gnome.desktop.interface",
        "color-scheme", "prefer-dark" if dark else "prefer-light",
    ])
    if ec != 0:
        return False, f"gsettings: {err}"

    # GTK-Theme-Name selbst ebenfalls setzen (falls er noch nie gesetzt
    # wurde) - idempotent, ändert bei bereits korrektem Wert nichts.
    run_ec(["gsettings", "set", "org.gnome.desktop.interface",
            "gtk-theme", GTK_THEME_NAME])

    # settings.ini DIREKT patchen - der eigentliche Grund, warum bisher
    # jede frisch gestartete GTK-App wieder im (falschen) Default-
    # Zustand aufging: gsettings allein reicht hier nicht, siehe
    # Kommentar bei GTK3_SETTINGS_INI oben. gtk-3.0 wird IMMER
    # angelegt/gepflegt (die hochgeladene settings.ini beweist, dass
    # sie im Einsatz ist), gtk-4.0 nur, falls schon vorhanden.
    pref = "1" if dark else "0"
    ok, err = _set_gtk_settings_ini_key(
        GTK3_SETTINGS_INI, "gtk-application-prefer-dark-theme", pref,
        create_if_missing=True)
    if not ok:
        return False, err
    ok, err = _set_gtk_settings_ini_key(
        GTK4_SETTINGS_INI, "gtk-application-prefer-dark-theme", pref,
        create_if_missing=False)
    if not ok:
        return False, err

    # Live-Property DIESES Prozesses (des Daemons) sofort nachziehen -
    # damit _is_dark_mode() oben ab JETZT korrekt ist, ohne dass der
    # Daemon selbst neu gestartet werden müsste. Ohne das würde das
    # Widget nach dem Umschalten weiter den alten Zustand zeigen, bis
    # der Daemon irgendwann neu startet und settings.ini frisch liest.
    _gtk_settings = Gtk.Settings.get_default()
    if _gtk_settings is not None:
        try:
            _gtk_settings.set_property("gtk-application-prefer-dark-theme", dark)
        except Exception:
            pass

    # Best-effort: laufende Apps ohne Neustart benachrichtigen (siehe
    # _broadcast_theme_change - Qt/Kvantum kann das grundsätzlich
    # nicht, GTK/Firefox über gsettings + Portal-Neustart schon eher).
    _broadcast_theme_change()

    return True, ""

# Sprachen: bewusst kuratierte, feste Liste statt aller ~800 via
# 'localectl list-locales' - eine Rohliste wäre für die meisten Nutzer
# unbrauchbar unübersichtlich. Wer etwas Selteneres braucht, nutzt das
# Freitext-Eingabefeld (siehe UI unten). Französisch ist auf
# ausdrücklichen Wunsch NICHT dabei. "Chinesisch" deckt Mandarin ab
# (zh_CN ist die Standard-Locale dafür, keine separate "Mandarin"-
# Locale existiert).
LANGUAGE_PRESETS = [
    ("Deutsch",      "de_DE.UTF-8", "de"),
    ("English",      "en_US.UTF-8", "us"),
    ("Italiano",     "it_IT.UTF-8", "it"),
    ("Español",      "es_ES.UTF-8", "es"),
    ("日本語",        "ja_JP.UTF-8", "jp"),
    ("中文",          "zh_CN.UTF-8", "cn"),
]

def _current_locale() -> str:
    out = run(["localectl", "status"])
    m = re.search(r'LANG=(\S+)', out)
    return m.group(1) if m else ""

def _current_kb_layout() -> str:
    """Liest kb_layout direkt aus hyprland.lua (nicht 'localectl
    status' - das X11-Layout dort kann vom tatsächlich in Hyprland
    aktiven Layout abweichen, hyprland.lua ist die Quelle, die dieses
    Widget auch SCHREIBT, also auch die richtige Quelle zum LESEN)."""
    try:
        txt = _hypr_lua_path().read_text()
        m = re.search(r'kb_layout\s*=\s*"([^"]+)"', txt)
        if m: return m.group(1)
    except Exception:
        pass
    return "us"

def _set_system_locale(locale: str) -> tuple[bool, str]:
    """Setzt die System-Locale über localectl - läuft über D-Bus zu
    systemd-localed und braucht PolicyKit-Autorisierung (kann einen
    Passwort-Dialog auslösen, das ist normal, kein Fehler dieses
    Widgets)."""
    _out, err, ec = run_ec(["localectl", "set-locale", f"LANG={locale}"], timeout=15)
    if ec != 0:
        return False, err or "localectl set-locale fehlgeschlagen."
    return True, ""

def _set_kb_layout(layout: str) -> tuple[bool, str]:
    """Schreibt kb_layout direkt in hyprland.lua (Regex-Ersetzung im
    bestehenden hl.config({ input = { kb_layout = "..." } })-Block) -
    exakt dasselbe Muster wie das Display-Widget es für mode/scale
    schon nutzt. Wirkt erst nach 'hyprctl reload' bzw. dem nächsten
    Hyprland-Start - dieses Widget stößt reload NICHT automatisch an,
    um keine laufenden Fenster/Layouts zu stören; siehe UI-Hinweis."""
    path = _hypr_lua_path()
    if not path.is_file():
        return False, f"hyprland.lua not found ({path})"
    try:
        backup_file(path)
        txt = path.read_text()
        new_txt, n = re.subn(r'(kb_layout\s*=\s*)"[^"]*"',
                              rf'\1"{layout}"', txt, count=1)
        if n == 0:
            return False, "kb_layout line not found in hyprland.lua."
        path.write_text(new_txt)
        return True, ""
    except Exception as e:
        return False, str(e)

# ────────────────────────────────────────────────────────────
#  Cursor-Plugin (dynamic_cursors): ob es überhaupt aktiv ist, und ob
#  Shake-to-Find aktiv ist. Exakt dasselbe Muster wie kb_layout oben -
#  Regex-Ersetzung direkt in hyprland.lua, kein separates State-File.
#  Beide "enabled"-Vorkommen sind im File EINDEUTIG anhand ihres
#  jeweiligen umschließenden Blocks anzusteuern ("dynamic_cursors = {"
#  bzw. "shake = {" kommen je genau einmal in der Datei vor - siehe
#  hyprland.lua, Plugin-Sektion) - deshalb NICHT einfach global das
#  erste "enabled = true/false" ersetzen, das würde z.B. genauso gut
#  decoration.shadow.enabled oder ein anderes Plugin treffen.
# ────────────────────────────────────────────────────────────
def _cursor_plugin_enabled() -> bool:
    try:
        txt = _hypr_lua_path().read_text()
        m = re.search(r'dynamic_cursors\s*=\s*\{\s*enabled\s*=\s*(true|false)', txt)
        if m:
            return m.group(1) == "true"
    except Exception:
        pass
    return True  # Default im Grundzustand der Config

def _cursor_shake_enabled() -> bool:
    try:
        txt = _hypr_lua_path().read_text()
        m = re.search(r'shake\s*=\s*\{\s*enabled\s*=\s*(true|false)', txt)
        if m:
            return m.group(1) == "true"
    except Exception:
        pass
    return False  # Default im Grundzustand der Config

def _set_cursor_plugin_enabled(enabled: bool) -> tuple[bool, str]:
    """Schreibt dynamic_cursors.enabled direkt in hyprland.lua. Wirkt
    erst nach 'hyprctl reload' bzw. dem nächsten Hyprland-Start,
    genau wie _set_kb_layout - kein Auto-Reload aus demselben Grund
    (siehe dortiger Kommentar)."""
    path = _hypr_lua_path()
    if not path.is_file():
        return False, f"hyprland.lua not found ({path})"
    try:
        backup_file(path)
        txt = path.read_text()
        new_txt, n = re.subn(
            r'(dynamic_cursors\s*=\s*\{\s*enabled\s*=\s*)(true|false)',
            rf'\g<1>{"true" if enabled else "false"}', txt, count=1)
        if n == 0:
            return False, "dynamic_cursors plugin block not found in hyprland.lua."
        path.write_text(new_txt)
        return True, ""
    except Exception as e:
        return False, str(e)

def _set_cursor_shake_enabled(enabled: bool) -> tuple[bool, str]:
    """Wie _set_cursor_plugin_enabled, nur für shake.enabled."""
    path = _hypr_lua_path()
    if not path.is_file():
        return False, f"hyprland.lua not found ({path})"
    try:
        backup_file(path)
        txt = path.read_text()
        new_txt, n = re.subn(
            r'(shake\s*=\s*\{\s*enabled\s*=\s*)(true|false)',
            rf'\g<1>{"true" if enabled else "false"}', txt, count=1)
        if n == 0:
            return False, "shake block not found in hyprland.lua."
        path.write_text(new_txt)
        return True, ""
    except Exception as e:
        return False, str(e)

def _hypr_monitors_live() -> list:
    return jrun(["hyprctl", "monitors", "-j"]) or []

def _parse_modes(modes: list) -> dict:
    out: dict = {}
    for m in modes:
        try:
            res, hz = m.split("@")
            out.setdefault(res, []).append(hz.rstrip("Hz"))
        except ValueError:
            continue
    return out

def _edid_path_for_monitor(name: str) -> Path | None:
    """Findet die rohe EDID-Sysfs-Datei für einen Hyprland-Monitornamen
    (z.B. "HDMI-A-1") - der DRM-Kartenordnername hat ein "cardN-"-
    Präfix, dessen Nummer nicht vorhersagbar ist (vom Kernel pro Boot
    vergeben), daher per glob gesucht statt fest kodiert."""
    matches = list(Path("/sys/class/drm").glob(f"card*-{name}"))
    if not matches:
        return None
    edid_f = matches[0] / "edid"
    return edid_f if edid_f.is_file() else None

def _edid_extra_modes(name: str) -> dict:
    """Liest zusätzliche Auflösung/Hz-Kombinationen direkt aus der
    rohen EDID (via edid-decode), um Lücken in hyprctls eigener
    availableModes-Liste zu schließen - verifiziert an einem echten
    Fall: ein BenQ EX2710S meldet laut eigenem EDID (CTA-Extension-
    Block, "Detailed Timing Descriptors") eine 165Hz- und eine 144Hz-
    Detailed-Timing-Descriptor-Zeile, die hyprctl selbst NICHT in
    seiner availableModes-Liste ausgibt (bestätigter Hyprland/DRM-
    Parsing-Gap für bestimmte CTA-Extension-DTDs, kein Fehler in
    unserem eigenen hyprctl-Aufruf).

    Liest die EDID-Sysfs-Datei ZUERST ohne Root-Rechte (auf den
    meisten Systemen ist sie world-readable, da reine Monitor-
    Fähigkeitsdaten, keine sensiblen Infos) - schlägt das fehl, wird
    einfach ein leeres Ergebnis zurückgegeben (kein Absturz, die
    hyprctl-eigene Liste bleibt dann die einzige Quelle, wie bisher).
    Erwartet 'edid-decode' installiert (Paket v4l-utils, offizielles
    Arch-Repo, kein AUR)."""
    edid_f = _edid_path_for_monitor(name)
    if not edid_f or not shutil.which("edid-decode"):
        return {}
    out, _err, ec = run_ec(["edid-decode", str(edid_f)], timeout=5)
    if ec != 0 or not out:
        return {}
    # Ein generelles Muster deckt ALLE Timing-Listen-Abschnitte ab
    # (Established Timings, Standard Timings, CTA Video Data Block
    # VICs, Detailed Timing Descriptors in Base-EDID UND CTA-
    # Extension) - alle folgen demselben Textformat
    # "WIDTHxHEIGHT   FLOAT Hz", nur mit unterschiedlichen Zeilen-
    # Präfixen (IBM/DMT/GTF/Apple/VIC/DTD). Verifiziert gegen echten
    # edid-decode-Output eines realen Monitors (siehe Kommentar oben).
    extra: dict = {}
    for m in re.finditer(r'(\d+)x(\d+)\s+([\d.]+)\s*Hz', out):
        w, h, hz = m.group(1), m.group(2), m.group(3)
        res = f"{w}x{h}"
        hz_str = f"{float(hz):.2f}"
        extra.setdefault(res, set()).add(hz_str)
    return extra

def _write_hdr_fields(block_text: str, hdr_on: bool) -> str:
    """Fügt bitdepth/cm-Felder in einen bestehenden hl.monitor({...})-
    Blocktext ein bzw. aktualisiert sie, oder setzt sie explizit auf
    die Nicht-HDR-Standardwerte zurück (statt die Felder einfach zu
    entfernen - explizit "bitdepth=8, cm=srgb" ist klarer beim
    Nachlesen der Datei als ein stillschweigend fehlendes Feld)."""
    if hdr_on:
        if re.search(r'bitdepth\s*=', block_text):
            block_text = re.sub(r'bitdepth\s*=\s*[^,\n]+', 'bitdepth = 10', block_text)
        else:
            block_text = re.sub(r'(\}\)\s*$)', '    bitdepth = 10,\n\\1', block_text)
        if re.search(r'\bcm\s*=', block_text):
            block_text = re.sub(r'\bcm\s*=\s*"[^"]*"', 'cm       = "hdr"', block_text)
        else:
            block_text = re.sub(r'(\}\)\s*$)', '    cm       = "hdr",\n\\1', block_text)
    else:
        if re.search(r'bitdepth\s*=', block_text):
            block_text = re.sub(r'bitdepth\s*=\s*[^,\n]+', 'bitdepth = 8', block_text)
        if re.search(r'\bcm\s*=', block_text):
            block_text = re.sub(r'\bcm\s*=\s*"[^"]*"', 'cm       = "srgb"', block_text)
    return block_text

# ════════════════════════════════════════════════════════════
#  Screen Rotation (ScreenRotationDaemon Control-Socket)
# ════════════════════════════════════════════════════════════
# WICHTIG: hier absichtlich NICHT nochmal selbst "hyprctl keyword
# monitor" oder "hyprctl eval hl.monitor(...)" nachbauen. Der Daemon
# (ScreenRotationDaemon.c) kennt pro Monitor bereits den korrekt
# gecachten mode/position/scale und spricht die einzig bestätigt
# funktionierende hl.monitor()-Eval-Syntax - eine zweite, unabhängige
# Implementierung hier hätte wieder genau das Risiko, denselben "sieht
# aus als würde nix passieren"-Bug erneut einzubauen (siehe Chat: das
# alte "NAME,transform,N"-Kommando wurde von Hyprland stillschweigend
# verworfen). Dieses Widget ist bewusst nur ein dünner Client für das
# Control-Socket-Protokoll, das der Daemon exportiert:
#   list                    -> "NAME TRANSFORM\n" pro bekanntem Monitor
#   set NAME TRANSFORM      -> rotiert NAME live, echte Hyprland-Antwort
#   status/lock/unlock/toggle -> globaler Auto-Rotate-Freeze
_ROTATION_SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "screen-rotation.sock"

# transform-Werte wie vom Daemon/Hyprland erwartet: 0=normal, 1=90° CW,
# 2=180°, 3=270° CW. 4-7 wären zusätzlich gespiegelte Varianten - für
# ein Laptop-/Tablet-Panel praktisch nie gebraucht, deshalb hier nicht
# angeboten (der Daemon selbst blockt sie nicht, falls doch mal nötig -
# dann per socat/"set NAME 4..7").
_ROTATIONS: list[tuple[int, str]] = [(0, "0°"), (1, "90°"), (2, "180°"), (3, "270°")]

def _rotation_socket_cmd(cmd: str, timeout: float = 1.5) -> str | None:
    """Schickt EIN Kommando an den ScreenRotationDaemon (ein Kommando pro
    Verbindung, siehe Protokoll-Kommentar in ScreenRotationDaemon.c) und
    gibt die volle Antwort zurück. None bei JEDEM Fehler (Daemon läuft
    nicht, Socket fehlt, Timeout, ...) - wird aus UI-Handlern heraus
    aufgerufen, darf also nie eine Exception nach draußen werfen."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(str(_ROTATION_SOCK))
        s.sendall(cmd.encode())
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        s.close()
        return b"".join(chunks).decode(errors="replace")
    except Exception:
        return None

def _rotation_daemon_available() -> bool:
    return _ROTATION_SOCK.exists() and _rotation_socket_cmd("status") is not None

def _rotation_list() -> dict:
    """{monitor_name: transform} für ALLE Monitore, die der Daemon über
    "j/monitors" sieht (nicht nur den internen mit Sensor, siehe
    write_monitor_list() im Daemon - "fuer JEDEN Monitor, auch externe
    Pivot-Displays"). Leeres Dict bei jedem Fehler, nie eine Exception."""
    raw = _rotation_socket_cmd("list")
    out: dict = {}
    if not raw:
        return out
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return out

def _rotation_set(name: str, transform: int) -> tuple:
    """Setzt den transform EINES Monitors live über den Daemon. Gibt
    (erfolgreich, Antworttext) zurück. Der Daemon leitet mittlerweile
    Hyprlands ECHTE Antwort durch (früher hartkodiert "ok", egal was
    Hyprland zurückgab - siehe Chat) - hier also tatsächlich auf die
    Antwort schauen statt sie zu ignorieren."""
    resp = _rotation_socket_cmd(f"set {name} {transform}")
    if resp is None:
        return False, "Rotation daemon not reachable"
    resp = resp.strip()
    if resp.startswith("error"):
        return False, resp
    return True, resp

def _rotation_lock_status() -> str | None:
    """'locked' | 'unlocked' | None (Daemon nicht erreichbar)."""
    resp = _rotation_socket_cmd("status")
    return resp.strip() if resp else None

def _rotation_toggle_lock() -> str | None:
    resp = _rotation_socket_cmd("toggle")
    return resp.strip() if resp else None

def _build_autorotate_row() -> Gtk.Box:
    """Globaler Auto-Rotate Ein/Aus-Schalter - spiegelt g_state.locked im
    Daemon (EIN einziges Flag, nicht pro Monitor, daher hier separat
    von den Pro-Monitor-Rotationsknöpfen unten). "An" = Daemon folgt dem
    Beschleunigungssensor automatisch (unlocked). "Aus" = aktuelle
    Ausrichtung eingefroren (locked) - z.B. wenn man den Laptop trägt
    und dabei keine ungewollte Drehung will (siehe Chat: Convertible
    vs. reines Klapp-Laptop, Tablet-Mode-Erkennung als möglicher
    Folgeschritt)."""
    status = _rotation_lock_status()
    check = Gtk.CheckButton(label="Follow sensor")
    check.set_active(status != "locked")
    check.set_can_focus(False)
    check.set_tooltip_text(
        "On: screen rotates automatically with the accelerometer. "
        "Off: rotation is frozen at the current orientation (e.g. while "
        "carrying the laptop).")

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 2500):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    def _on_toggle(_w):
        wanted_unlocked = check.get_active()

        def _apply():
            new_status = _rotation_toggle_lock()
            if new_status is None:
                raise RuntimeError("Rotation daemon not reachable")
            if (new_status != "locked") != wanted_unlocked:
                # toggle() traf nicht den gewuenschten Zielzustand (z.B.
                # Race mit einem anderen gleichzeitigen Client) - noch
                # einmal umschalten statt den Nutzer mit einem UI-
                # Zustand sitzen zu lassen, der nicht dem echten
                # Daemon-Zustand entspricht.
                _rotation_toggle_lock()

        def _reset():
            check.set_active(not wanted_unlocked)

        apply_change("Auto-rotate " + ("on" if wanted_unlocked else "off"),
                     _apply, on_status=_flash, reset_fn=_reset)

    check.connect("toggled", _on_toggle)

    row = vbox(2)
    row.pack_start(hrow(check, sp=8), False, False, 0)
    row.pack_start(status_lbl, False, False, 0)
    return row

def _build_settings_display(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    monitors = _hypr_monitors_live()
    if not monitors:
        page.pack_start(
            bitem("No monitors found via hyprctl (is Hyprland running?)",
                  dim=True), False, False, 0)
        return

    lua_path = _hypr_lua_path()
    if not lua_path.is_file():
        page.pack_start(
            bitem(f"hyprland.lua not found ({lua_path}) — resolution "
                  f"will only be set live via hyprctl, not saved permanently.", dim=True), False, False, 0)

    # ── Auto-Rotate (ScreenRotationDaemon) ───────────────────────────
    # Feature-Detection statt Annahme: rotiert wird nur angeboten, wenn
    # der Daemon tatsächlich läuft und über seinen Control-Socket
    # antwortet. Läuft er nicht (z.B. Hardware ohne Accelerometer,
    # Service nicht aktiviert), zeigen wir hier still gar nichts an,
    # statt Knöpfe, die dann sowieso nur "Rotation daemon not
    # reachable" melden würden.
    rotation_up = _rotation_daemon_available()
    rotation_map = _rotation_list() if rotation_up else {}
    if rotation_up:
        page.pack_start(bsec("Auto-Rotate"), False, False, 0)
        page.pack_start(_build_autorotate_row(), False, False, 0)
        page.pack_start(sep(), False, False, 4)

    # Gemeinsamer Debounce-Status für den Waybar/Autohide-Reload - siehe
    # Kommentar bei waybar_restart_id in _build_monitor_row(). Ohne das
    # würde bei kurz hintereinander geänderten Monitor-Einstellungen
    # (jede wird sofort einzeln übernommen) der Reload einmal PRO
    # Änderung feuern, was zu einem Race zwischen zwei fast
    # gleichzeitigen "killall -SIGUSR2 waybar" +
    # "systemctl restart wb-autohide.service" führen kann.
    waybar_restart_id = [0]

    for mon in monitors:
        mon_name = mon.get("name", "?")
        page.pack_start(bsec(mon_name.upper()), False, False, 0)
        row = _build_monitor_row(mon, monitors, lua_path, win, waybar_restart_id,
                                  rotation_map.get(mon_name) if rotation_up else None)
        page.pack_start(row, False, False, 0)
        page.pack_start(sep(), False, False, 4)

_HEIGHT_SCALE_TABLE = [
    (480,  0.5),
    (600,  0.65),
    (720,  0.80),
    (900,  0.95),
    (1200, 1.2),
]
_DEFAULT_SCALE = 1.0

# ── Scale-Failsafe ──────────────────────────────────────────────────
# Änderungen werden jetzt sofort übernommen (kein Cancel/Apply-Schritt
# mehr) - dadurch braucht es eine harte Untergrenze, BEVOR überhaupt an
# hyprctl geschickt wird: die "logische" Auflösung (physische Höhe /
# scale) bestimmt, wie viel von der UI (inkl. diesem Settings-Fenster
# selbst) noch sichtbar/klickbar ist. Bei einer kleinen physischen
# Auflösung wie 360p kippt das schnell in beide Richtungen:
#   - scale zu GROSS  -> logische Fläche wird so winzig, dass Fenster
#     mit fester Mindestgröße (z.B. dieses 420px breite Settings-
#     Fenster) nicht mehr vollständig reinpassen/anklickbar sind.
#   - scale zu KLEIN  -> logische Fläche wird riesig relativ zu den
#     paar hundert physischen Pixeln, Text/Icons/die Waybar-Leiste
#     werden dadurch auf dem Bildschirm praktisch unsichtbar bzw. zu
#     klein zum Treffen.
# In beiden Fällen findet man ohne ein externes Tool (SSH + manuelles
# `hyprctl keyword monitor`) nicht mehr zurück in dieses Settings-
# Fenster, um es zu korrigieren - genau das soll dieser Failsafe
# verhindern, indem er den erlaubten Scale-Bereich auf das begrenzt,
# was eine noch benutzbare logische Auflösung ergibt.
_MIN_LOGICAL_H = 400    # darunter passt selbst dieses Settings-Fenster nicht mehr rein
_MAX_LOGICAL_H = 2400   # darüber wird jede UI auf einem kleinen Panel de facto unsichtbar

# Zusätzlicher, harter Deckel: ab dieser physischen Monitorhöhe bringt
# ein Scale über 2.0x keinen echten Mehrwert mehr - die GTK-UI (dieses
# Settings-Fenster inklusive) passt sich eh an, und mehr Platz durch
# noch mehr Scale gibt's ab da schlicht nicht mehr zu holen. Für
# KLEINERE Displays (< 1200px) gilt der Deckel bewusst NICHT - da kann
# ein Scale deutlich über 2.0x nötig sein, um überhaupt lesbar zu sein.
_MAX_SCALE_CAP = 2.0
_MAX_SCALE_CAP_MIN_HEIGHT = 1200

def _scale_bounds(height: int) -> tuple[float, float]:
    """Gibt (min_scale, max_scale) für eine gegebene physische
    Monitorhöhe zurück - innerhalb dieses Bereichs bleibt die daraus
    resultierende logische Höhe zwischen _MIN_LOGICAL_H und
    _MAX_LOGICAL_H, siehe Kommentar oben. Ab _MAX_SCALE_CAP_MIN_HEIGHT
    physischer Höhe wird der obere Wert zusätzlich hart auf
    _MAX_SCALE_CAP gedeckelt (siehe Kommentar dort)."""
    if height <= 0:
        return 0.1, 3.0
    lo = height / _MAX_LOGICAL_H
    hi = height / _MIN_LOGICAL_H
    if height >= _MAX_SCALE_CAP_MIN_HEIGHT:
        hi = min(hi, _MAX_SCALE_CAP)
    return round(lo, 3), round(hi, 3)

def _auto_scale_for_height(h: int) -> float:
    for max_h, sc in _HEIGHT_SCALE_TABLE:
        if h <= max_h:
            scale = sc
            break
    else:
        scale = _DEFAULT_SCALE
    # Auch der Auto-Wert wird gegen den Failsafe-Bereich geklemmt -
    # betrifft in der Praxis vor allem sehr kleine/unübliche Höhen, für
    # die die obige Tabelle keinen passgenauen Eintrag hat.
    lo, hi = _scale_bounds(h)
    return max(lo, min(hi, scale))

def _build_monitor_row(mon: dict, all_monitors: list, lua_path: Path, win: Gtk.Window,
                        waybar_restart_id: list, rotation_transform: int | None = None) -> Gtk.Box:
    name    = mon.get("name", "?")
    cur_res = f'{mon.get("width")}x{mon.get("height")}'
    cur_hz  = f'{mon.get("refreshRate", 0):.2f}'
    cur_scale = float(mon.get("scale", 1.0) or 1.0)
    modes   = _parse_modes(mon.get("availableModes", []))

    # EDID-Zusatzmodi einmischen (nicht ersetzen) - hyprctls eigene
    # availableModes-Liste hat nachgewiesenermaßen Lücken bei manchen
    # CTA-Extension-DTDs (siehe _edid_extra_modes-Docstring). Ein
    # direkter Datei-Read + edid-decode-Aufruf ist schnell genug
    # (keine Netzwerk-/Hardware-Pollingzeit), um synchron beim Aufbau
    # der Zeile zu laufen, ohne spürbares UI-Ruckeln.
    for res, hzs in _edid_extra_modes(name).items():
        existing = set(modes.get(res, []))
        modes.setdefault(res, [])
        for hz in hzs:
            if hz not in existing:
                modes[res].append(hz)

    res_list = sorted(modes.keys(), key=lambda r: -int(r.split("x")[0]))

    CUSTOM_LABEL = "Custom…"

    res_combo = Gtk.ComboBoxText()
    res_combo.get_style_context().add_class("bubble")
    res_combo.get_style_context().add_class("dropdown")
    res_combo.set_can_focus(False)
    for r in res_list:
        res_combo.append_text(r)
    res_combo.append_text(CUSTOM_LABEL)

    # Refresh-Rate hat pro Auflösung nur eine HANDVOLL fester Werte
    # (siehe modes-Dict oben) -> genau der "Dropdown mit Limits"-Fall
    # aus dem README, deshalb hier die Knopfreihe statt ComboBoxText.
    hz_combo = _SegmentedControl()
    hz_combo.get_style_context().add_class("bubble")
    hz_combo.get_style_context().add_class("segmented")
    hz_combo.set_can_focus(False)

    custom_state = {"res": cur_res, "hz": cur_hz}

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash_status(text: str, ms: int = 3000):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    res_val_lbl = Gtk.Button()
    res_val_lbl.get_style_context().add_class("bubble")
    res_val_lbl.set_can_focus(False)
    res_val_lbl.set_no_show_all(True)
    res_val_lbl.hide()

    hz_val_lbl = Gtk.Button()
    hz_val_lbl.get_style_context().add_class("bubble")
    hz_val_lbl.set_can_focus(False)
    hz_val_lbl.set_no_show_all(True)
    hz_val_lbl.hide()

    def _prompt_text(title: str, placeholder: str, initial: str = "") -> str | None:
        dlg = Gtk.Dialog(title=title, transient_for=win)
        dlg.set_name("wb-daemon-popup")   # <-- NEU
        dlg.set_modal(True)
        dlg.set_keep_above(True)
        dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Apply", Gtk.ResponseType.OK)
        e = Gtk.Entry()
        e.set_placeholder_text(placeholder)
        if initial:
            e.set_text(initial)
        e.set_activates_default(True)
        e.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
        dlg.get_content_area().pack_start(e, True, True, 12)
        dlg.show_all()
        resp = dlg.run()
        val = e.get_text().strip() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        return val or None

    scale_auto_check = Gtk.CheckButton(label="Auto")
    scale_auto_check.set_active(True)
    scale_auto_check.set_can_focus(False)
    scale_auto_check.set_tooltip_text(
        "Automatically derive scale from height. Uncheck to set manually.")

    # Scale ist im Gegensatz zu Resolution/Hz ein WIRKLICH stufenloser
    # Wert (siehe README: "some widgets have dropdown menus with
    # limits ... like the scale and rotation boxes/buttons") - deshalb
    # hier bewusst ein echter Zieh-Regler (bslider(), dasselbe Muster
    # wie Helligkeit/Lautstärke) statt Dropdown ODER Knopfreihe. Vorher
    # musste man den Wert über einen Text-Dialog eintippen - unpraktisch
    # gerade auf Touch.
    scale_state = {"value": cur_scale}
    _scale_lo0, _scale_hi0 = _scale_bounds(int(cur_res.split("x")[1]))
    scale_box, scale_slider = bslider(
        "⛶", _scale_lo0, _scale_hi0, 0.05, cur_scale, cb=None)
    scale_slider.set_digits(2)
    scale_slider.set_sensitive(False)   # "Auto" ist per Default an

    _scale_debounce_id = [0]

    def _on_scale_slider(s):
        scale_state["value"] = round(s.get_value(), 3)
        # Debounced statt bei jedem einzelnen Drag-Event: _apply_now()
        # schreibt die Lua-Config UND ruft hyprctl auf - das bei jedem
        # Pixel Mausbewegung zu tun, würde beim Ziehen spürbar
        # ruckeln/spammen.
        if _scale_debounce_id[0]:
            GLib.source_remove(_scale_debounce_id[0])
        def _fire():
            _scale_debounce_id[0] = 0
            _apply_now()
            return False
        _scale_debounce_id[0] = GLib.timeout_add(200, _fire)

    scale_handler_id = scale_slider.connect("value-changed", _on_scale_slider)

    def _sync_scale_slider_range():
        """Bounds des Reglers an die AKTUELL gewählte Auflösung
        anpassen (siehe _scale_bounds()) - ändert sich die Auflösung,
        ändert sich auch der sichere Scale-Bereich. Klemmt den
        aktuellen Wert mit rein, falls er durch den Auflösungswechsel
        jetzt außerhalb der neuen Grenzen liegen würde."""
        target_res, _target_hz = _resolve_res_hz()
        target_h_str = (target_res or cur_res).split("x")[1]
        lo, hi = _scale_bounds(int(target_h_str))
        scale_slider.set_range(lo, hi)
        clamped = round(max(lo, min(hi, scale_state["value"])), 3)
        if clamped != scale_state["value"]:
            scale_state["value"] = clamped
            # handler_block: set_value() würde sonst selbst wieder
            # "value-changed" auslösen -> _on_scale_slider() ->
            # debounced _apply_now() -> Endlosschleife mit dem
            # eigentlichen Auflösungswechsel-Apply.
            scale_slider.handler_block(scale_handler_id)
            scale_slider.set_value(clamped)
            scale_slider.handler_unblock(scale_handler_id)

    def _on_scale_auto_toggle(_w):
        scale_slider.set_sensitive(not scale_auto_check.get_active())
        _apply_now()

    scale_auto_check.connect("toggled", _on_scale_auto_toggle)

    # ── HDR ──────────────────────────────────────────────────────────
    # Hyprlands eigene hl.monitor({...})-Lua-DSL unterstützt HDR über
    # zwei Felder: bitdepth=10 + cm="hdr" (laut offizieller Hyprland-
    # Wiki-Doku zu Color Management). Startzustand wird aus
    # colorManagementPreset gelesen (liefert hyprctl bereits fertig -
    # "hdr"/"hdredid" heißt an, alles andere (z.B. "srgb") heißt aus).
    hdr_check = Gtk.CheckButton(label="HDR")
    hdr_check.set_active(mon.get("colorManagementPreset") in ("hdr", "hdredid"))
    hdr_check.set_can_focus(False)
    hdr_check.set_tooltip_text(
        "10-bit color + HDR color management (bitdepth=10, cm=hdr). "
        "Needs display/cable support, otherwise no effect or worse image.")
    hdr_check.connect("toggled", lambda _w: _apply_now())

    # ── Position / Anordnung relativ zu anderen Monitoren ────────────
    # Hyprland nutzt ein invertiertes Y-Koordinatensystem (negativeres
    # Y = weiter oben) - siehe offizielle Doku. "Manual / aktuelle
    # Position beibehalten" ist der Default, damit ein einzelner
    # Monitor (kein zweiter angeschlossen) sich hier gar nicht ändert
    # und die bisherige "Position einfach übernehmen"-Logik weiter
    # funktioniert, ohne dass man jedes Mal explizit "Manual" wählen
    # muss.
    other_monitors = [m for m in all_monitors if m.get("name") != name]
    POS_OPTIONS: list[tuple[str, str | None, str | None]] = [
        ("Manual / keep current position", None, None)]
    for om in other_monitors:
        om_name = om.get("name", "?")
        for direction, dir_label in (("right", "Right of"), ("left", "Left of"),
                                       ("above", "Above"), ("below", "Below")):
            POS_OPTIONS.append((f"{dir_label} {om_name}", om_name, direction))

    pos_combo = Gtk.ComboBoxText()
    pos_combo.get_style_context().add_class("bubble")
    pos_combo.get_style_context().add_class("dropdown")
    pos_combo.set_can_focus(False)
    for label_txt, _ref, _dir in POS_OPTIONS:
        pos_combo.append_text(label_txt)
    pos_combo.set_active(0)
    if len(other_monitors) == 0:
        pos_combo.set_sensitive(False)
        pos_combo.set_tooltip_text("Only one display connected - "
                                    "no relative arrangement possible.")
    pos_combo.connect("changed", lambda _w: _apply_now())

    def _resolve_position(own_res: str, own_scale: float) -> tuple[int, int]:
        """Berechnet x/y basierend auf der gewählten relativen
        Anordnung. Referenzmonitor-Maße kommen aus dem all_monitors-
        Snapshot vom Öffnen des Settings-Fensters (nicht live neu
        abgefragt) - falls kurz danach auch am Referenzmonitor etwas
        geändert wird, ist das die beste verfügbare Näherung ohne einen
        vollen Mehrmonitor-Layout-Solver zu bauen."""
        idx = pos_combo.get_active()
        if idx <= 0:
            return mon.get("x", 0), mon.get("y", 0)
        _label, ref_name, direction = POS_OPTIONS[idx]
        ref_mon = next((m for m in all_monitors if m.get("name") == ref_name), None)
        if not ref_mon:
            return mon.get("x", 0), mon.get("y", 0)
        ref_scale = float(ref_mon.get("scale", 1.0) or 1.0)
        ref_x = ref_mon.get("x", 0)
        ref_y = ref_mon.get("y", 0)
        ref_w = int(ref_mon.get("width", 0) / ref_scale)
        ref_h = int(ref_mon.get("height", 0) / ref_scale)
        own_w = int(int(own_res.split("x")[0]) / own_scale)
        own_h = int(int(own_res.split("x")[1]) / own_scale)
        if direction == "right":
            return ref_x + ref_w, ref_y
        elif direction == "left":
            return ref_x - own_w, ref_y
        elif direction == "above":
            return ref_x, ref_y - own_h
        elif direction == "below":
            return ref_x, ref_y + ref_h
        return mon.get("x", 0), mon.get("y", 0)

    # Handler-ID für hz_combo wird unten (nach dem eigentlichen connect())
    # gesetzt - siehe _fill_hz(): das Signal wird dort kurz geblockt,
    # damit ein programmatisches set_active() nicht selbst NOCHMAL einen
    # Apply auslöst (siehe Kommentar dort für den genauen Bug).
    hz_handler_id = [None]

    def _fill_hz(res: str, preselect: str = None):
        # WICHTIG: hz_combo.set_active() unten feuert (sobald das
        # "changed"-Signal weiter unten verbunden ist) selbst wieder
        # _on_hz_change() -> _apply_now(). Ohne den Block hier löste
        # eine EINZIGE Auflösungsänderung des Nutzers ZWEI parallele,
        # komplett unsynchronisierte Hintergrund-Threads aus (einen aus
        # _on_res_change()'s eigenem _apply_now()-Aufruf, einen aus
        # diesem indirekten hz-"changed"), die beide gleichzeitig
        # hyprland.lua lesen/verändern/schreiben - das war der
        # bestätigte Grund für kaputte/doppelte hl.monitor-Blöcke bzw.
        # verlorene "local"-Keywords nach mehrfachem schnellen Ändern
        # der Auflösung (siehe Chat).
        if hz_handler_id[0] is not None:
            hz_combo.handler_block(hz_handler_id[0])
        try:
            hz_combo.remove_all()
            hzs = sorted(set(modes.get(res, [])), key=lambda h: -float(h))
            for h in hzs:
                hz_combo.append_text(f"{h} Hz")
            hz_combo.append_text(CUSTOM_LABEL)
            if preselect in hzs:
                hz_combo.set_active(hzs.index(preselect))
            elif hzs:
                hz_combo.set_active(0)
        finally:
            if hz_handler_id[0] is not None:
                hz_combo.handler_unblock(hz_handler_id[0])

    def _update_custom_visibility():
        res_custom = res_combo.get_active_text() == CUSTOM_LABEL
        hz_custom  = hz_combo.get_active_text() == CUSTOM_LABEL
        res_val_lbl.set_visible(res_custom)
        hz_val_lbl.set_visible(hz_custom)
        if res_custom:
            res_val_lbl.set_label(custom_state["res"] or "(tap to enter)")
        if hz_custom:
            hz_val_lbl.set_label(
                f"{custom_state['hz']} Hz" if custom_state["hz"]
                else "(tap to enter)")

    def _on_res_custom_selected():
        val = _prompt_text("Custom Resolution", "e.g. 2560x1440",
                            initial=custom_state["res"])
        if val and re.match(r'^\d+\s*[xX]\s*\d+$', val):
            custom_state["res"] = val.lower().replace(" ", "")
        elif val is not None:
            _flash_status(f"Invalid format: '{val}' (expected WIDTHxHEIGHT)")
        _update_custom_visibility()
        _apply_now()

    def _on_hz_custom_selected():
        val = _prompt_text("Custom Refresh Rate", "e.g. 75",
                            initial=custom_state["hz"])
        if val:
            try:
                float(val.replace(",", "."))
                custom_state["hz"] = val.replace(",", ".")
            except ValueError:
                _flash_status(f"Invalid refresh rate: '{val}'")
        _update_custom_visibility()
        _apply_now()

    res_val_lbl.connect("clicked", lambda _w: _on_res_custom_selected())
    hz_val_lbl.connect("clicked", lambda _w: _on_hz_custom_selected())

    if cur_res in res_list:
        res_combo.set_active(res_list.index(cur_res))
    _fill_hz(cur_res if cur_res in res_list
             else (res_list[0] if res_list else ""), preselect=cur_hz)
    _update_custom_visibility()

    orig = [cur_res, cur_hz, cur_scale, True, hdr_check.get_active(), 0]

    def _resolve_res_hz() -> tuple[str, str] | tuple[None, None]:
        if res_combo.get_active_text() == CUSTOM_LABEL:
            res = custom_state["res"]
            if not res or not re.match(r'^\d+x\d+$', res):
                return None, None
        else:
            res = res_combo.get_active_text()

        if hz_combo.get_active_text() == CUSTOM_LABEL:
            hz = custom_state["hz"]
            if not hz:
                return None, None
            try:
                float(hz)
            except ValueError:
                return None, None
        else:
            hzt = hz_combo.get_active_text()
            hz = hzt.replace(" Hz", "") if hzt else None

        return res, hz

    def _resolve_scale(height_for_auto: int) -> float | None:
        if scale_auto_check.get_active():
            return _auto_scale_for_height(height_for_auto)
        return scale_state["value"] if scale_state["value"] > 0 else None

    def _apply():
        res, hz = _resolve_res_hz()
        if not res or not hz:
            return
        mode = f'{res}@{hz}'
        target_h = int(res.split("x")[1])
        scale = _resolve_scale(target_h)
        if scale is None:
            raise RuntimeError(
                "Invalid scale entered (must be a number > 0).")
        # Letzte Sicherheitsprüfung direkt vor dem hyprctl-Aufruf -
        # fängt auch den Fall ab, dass die Auflösung NACH dem Setzen
        # eines manuellen Scale-Werts gewechselt wurde (der Wert war für
        # die vorherige Auflösung ok, ist es für die neue aber nicht
        # mehr). Siehe _scale_bounds()-Kommentar weiter oben.
        lo, hi = _scale_bounds(target_h)
        if not (lo <= scale <= hi):
            raise RuntimeError(
                f"Scale {scale:g} unsafe for {res} (allowed {lo:g}–{hi:g}) — "
                f"would risk locking you out of this Settings window. Not applied.")
        pos_x, pos_y = _resolve_position(res, scale)
        hdr_on = hdr_check.get_active()

        # Ab hier: alles, was hyprctl aufruft und/oder hyprland.lua
        # liest+verändert+schreibt, läuft SERIALISIERT unter
        # _HYPR_LUA_LOCK - siehe Kommentar dort. Ohne das können zwei
        # gleichzeitige Feldänderungen (auch an verschiedenen Monitoren,
        # da alle dieselbe Datei teilen) sich gegenseitig überschreiben
        # oder die Datei kurzzeitig in einem kaputten Zwischenzustand
        # lesen.
        with _HYPR_LUA_LOCK:
            # HDR-Zusatzparameter im "hyprctl keyword monitor"-Format -
            # dieselbe kommagetrennte Syntax wie die statische Config-Zeile
            # akzeptiert auch optionale zusätzliche Schlüssel-Wert-Paare
            # nach den ersten 4 (name,mode,position,scale).
            #
            # BUGFIX ("Bildschirm wird beim Scale-Ändern manchmal dunkler,
            # Farben leicht anders"): bitdepth/cm wurden bisher NUR gesetzt,
            # wenn HDR an war - war HDR aus, wurden sie einfach GAR NICHT
            # mit übergeben, in der Annahme, Hyprland würde sie dann schon
            # von selbst auf Standard zurücksetzen. Tut es aber nicht
            # zuverlässig: ein "hyprctl keyword monitor"-Aufruf ist ein
            # TEIL-Reconfigure, nicht angegebene Eigenschaften bleiben auf
            # ihrem vorherigen Wert stehen. Wurde HDR also IRGENDWANN mal an
            # war (bitdepth=10, cm=hdr gesetzt) und man ändert danach nur
            # noch Scale/Auflösung mit ausgeschaltetem HDR-Haken, blieb der
            # Monitor intern im 10-Bit-HDR-Farbmodus hängen, während SDR-
            # Inhalte weiter normal (SDR-Kurve) gerendert werden - exakt das
            # beobachtete "dunkler, Farben leicht komisch", und warum es sich
            # so unberechenbar anfühlte (kam drauf an, ob und wann zuletzt
            # überhaupt einmal explizit ETWAS an bitdepth/cm gesetzt wurde).
            # Fix: bitdepth/cm werden jetzt bei JEDEM Apply explizit gesetzt,
            # nie mehr weggelassen - "aus" heißt jetzt aktiv "bitdepth,8,
            # cm,auto" statt einer Auslassung, auf deren Nebenwirkungen man
            # sich nicht verlassen kann.
            if hdr_on:
                monitor_arg = f"{name},{mode},{pos_x}x{pos_y},{scale},bitdepth,10,cm,hdr"
            else:
                monitor_arg = f"{name},{mode},{pos_x}x{pos_y},{scale},bitdepth,8,cm,srgb"
            out, err, rc = run_ec(["hyprctl", "keyword", "monitor", monitor_arg])
            if rc != 0 or "err" in (out or "").lower() or err:
                raise RuntimeError(
                    f"hyprctl rejected monitor command: {(err or out or 'unknown error')[:120]}")

            time.sleep(0.2)
            run(["hyprctl", "keyword", "monitor", monitor_arg])

            actual = jrun(["hyprctl", "monitors", "-j"]) or []
            for m2 in actual:
                if m2.get("name") == name:
                    msg = (f"After apply: {name} reports "
                           f"scale={m2.get('scale')} (requested: {scale})")
                    print(msg, file=sys.stderr)
                    break

            # Waybar per SIGUSR2 neu laden lassen (offizieller, eingebauter
            # Reload-Mechanismus laut "man waybar"). GEDEBOUNCED über den
            # gemeinsamen waybar_restart_id-Zähler statt direkt aufgerufen:
            # jede Feldänderung ruft jetzt sofort für sich _apply() auf, bei
            # schnell hintereinander geänderten Feldern (z.B. Res dann Hz)
            # also mehrfach kurz hintereinander - ein direkter run_bg() hier
            # hätte den Reload + Autohide-Neustart dann mehrfach fast
            # gleichzeitig angestoßen (Race-Risiko zwischen zwei
            # überlappenden Neustarts). Debounce sammelt mehrere kurz
            # aufeinanderfolgende Apply-Aufrufe zu EINEM tatsächlichen Reload.
            if waybar_restart_id[0]:
                GLib.source_remove(waybar_restart_id[0])
            def _do_waybar_restart():
                waybar_restart_id[0] = 0
                run_bg(["bash", "-c",
                        "killall -SIGUSR2 waybar; "
                        "systemctl --user restart wb-autohide.service"])
                return False
            waybar_restart_id[0] = GLib.timeout_add(300, _do_waybar_restart)

            if lua_path.is_file():
                backup_file(lua_path)
                txt = lua_path.read_text()
                block_re = re.compile(
                    r'hl\.monitor\(\{[^}]*output\s*=\s*"' +
                    re.escape(name) + r'"[^}]*\}\)', re.S)
                m = block_re.search(txt)
                if m:
                    new_block = re.sub(r'mode\s*=\s*"[^"]*"',
                                        f'mode     = "{mode}"', m.group(0))
                    new_block = re.sub(r'scale\s*=\s*[^,\n]+',
                                        f'scale    = {scale}', new_block)
                    new_block = re.sub(r'position\s*=\s*"[^"]*"',
                                        f'position = "{pos_x}x{pos_y}"', new_block)
                    new_block = _write_hdr_fields(new_block, hdr_on)
                    txt = txt[:m.start()] + new_block + txt[m.end():]
                else:
                    # WICHTIG: kein Block für diesen Monitor gefunden - das
                    # war der bestätigte Grund, warum Änderungen an einem
                    # zweiten/weiteren Monitor NIE dauerhaft gespeichert
                    # wurden. Der alte Code tat hier schlicht NICHTS (kein
                    # else-Zweig), wenn die Regex keinen bestehenden Block
                    # fand - die Live-Änderung via hyprctl lief zwar
                    # trotzdem durch, ging aber beim nächsten Hyprland-
                    # Start/Config-Reload wieder verloren, da hyprland.lua
                    # nie einen Eintrag für diesen Monitor bekam. Jetzt wird
                    # in diesem Fall ein KOMPLETT NEUER hl.monitor({...})-
                    # Block direkt nach dem letzten bestehenden angehängt
                    # (bzw. nach einem sinnvollen Alternativanker, falls gar
                    # keiner existiert).
                    new_block_lines = [
                        "hl.monitor({",
                        f'    output   = "{name}",',
                        f'    mode     = "{mode}",',
                        f'    position = "{pos_x}x{pos_y}",',
                        f'    scale    = {scale},',
                    ]
                    if hdr_on:
                        new_block_lines.append('    bitdepth = 10,')
                        new_block_lines.append('    cm       = "hdr",')
                    new_block_lines.append("})")
                    new_block = "\n".join(new_block_lines)

                    last_block_re = re.compile(r'hl\.monitor\(\{[^}]*\}\)', re.S)
                    all_blocks = list(last_block_re.finditer(txt))
                    if all_blocks:
                        insert_at = all_blocks[-1].end()
                        txt = txt[:insert_at] + "\n\n" + new_block + txt[insert_at:]
                    else:
                        # Kein einziger hl.monitor(...)-Block existiert
                        # irgendwo in der Datei (sehr unüblicher Fall) -
                        # nach der Layout-Zeile einfügen, falls vorhanden,
                        # sonst ganz am Dateiende anhängen. Beides sind
                        # bewusst simple, konservative Fallbacks - Hauptfall
                        # ist "mindestens ein Block existiert bereits"
                        # (z.B. der Laptop-eigene eDP-1-Block aus der
                        # Standardinstallation).
                        anchor = re.search(r'local\s+savedLayout\s*=.*$', txt, re.M)
                        if anchor:
                            insert_at = anchor.end()
                            txt = txt[:insert_at] + "\n\n" + new_block + txt[insert_at:]
                        else:
                            txt = txt.rstrip() + "\n\n" + new_block + "\n"
                atomic_write_text(lua_path, txt)

            orig[0], orig[1] = res, hz
            orig[2], orig[3] = scale, scale_auto_check.get_active()
            orig[4], orig[5] = hdr_on, pos_combo.get_active()

    def _reset():
        if orig[0] in res_list:
            res_combo.set_active(res_list.index(orig[0]))
        else:
            res_combo.set_active(len(res_list))
            custom_state["res"] = orig[0]
        _fill_hz(orig[0] if orig[0] in res_list else "", preselect=orig[1])
        if orig[0] not in res_list or orig[1] not in modes.get(orig[0], []):
            hz_combo.set_active(hz_combo.n_items() - 1)
            custom_state["hz"] = orig[1]
        scale_auto_check.set_active(orig[3])
        if not orig[3]:
            scale_state["value"] = orig[2]
            scale_slider.handler_block(scale_handler_id)
            scale_slider.set_value(orig[2])
            scale_slider.handler_unblock(scale_handler_id)
        _sync_scale_slider_range()
        hdr_check.set_active(orig[4])
        pos_combo.set_active(orig[5])
        _update_custom_visibility()

    def _apply_now():
        _update_custom_visibility()
        res, hz = _resolve_res_hz()
        scale_txt = "auto" if scale_auto_check.get_active() else f"{scale_state['value']:g}"
        extras = []
        if hdr_check.get_active():
            extras.append("HDR")
        if pos_combo.get_active() > 0:
            extras.append(pos_combo.get_active_text())
        extra_txt = f", {', '.join(extras)}" if extras else ""
        desc = f"{name}: {res or '?'}@{hz or '?'}Hz, scale={scale_txt}{extra_txt}"
        apply_change(desc, _apply, on_status=_flash_status, reset_fn=_reset)

    def _on_res_change(_w):
        if res_combo.get_active_text() != CUSTOM_LABEL:
            _fill_hz(res_combo.get_active_text())
            _update_custom_visibility()
            _sync_scale_slider_range()
            _apply_now()
        else:
            _on_res_custom_selected()

    def _on_hz_change(_w):
        if hz_combo.get_active_text() != CUSTOM_LABEL:
            _update_custom_visibility()
            _apply_now()
        else:
            _on_hz_custom_selected()

    res_combo.connect("changed", _on_res_change)
    hz_handler_id[0] = hz_combo.connect("changed", _on_hz_change)

    scale_slider.set_tooltip_text("Drag to set the monitor scale manually.")
    scale_box.pack_start(scale_auto_check, False, False, 0)

    combos_row = hrow(res_combo, hz_combo.widget, sp=8)
    custom_row = hrow(res_val_lbl, hz_val_lbl, sp=8)
    hdr_row    = hrow(hdr_check, sp=8)
    pos_row    = hrow(Gtk.Label(label="Position:"), pos_combo, sp=8)
    wrap = vbox(6)
    wrap.pack_start(combos_row, False, False, 0)
    wrap.pack_start(custom_row, False, False, 0)
    wrap.pack_start(scale_box, False, False, 0)
    wrap.pack_start(hdr_row, False, False, 0)
    wrap.pack_start(pos_row, False, False, 0)
    wrap.pack_start(status_lbl, False, False, 0)

    # ── Rotation (ScreenRotationDaemon, nur wenn Daemon diesen Monitor
    #    kennt - siehe rotation_transform-Übergabe in
    #    _build_settings_display()) ─────────────────────────────────
    # Bewusst getrennt von _apply()/_apply_now() oben: Rotation läuft
    # NICHT über "hyprctl keyword monitor" + hyprland.lua-Textersetzung
    # wie Auflösung/Scale/HDR/Position, sondern über den eigenen
    # ScreenRotationDaemon-Socket (siehe Kommentar bei
    # _rotation_socket_cmd()). Wird hier also absichtlich nicht in
    # _apply() mit reingezogen, sondern eigenständig behandelt - auch
    # damit ein Rotations-Fehler nie eine Resolution/Scale-Änderung
    # blockiert oder umgekehrt.
    if rotation_transform is not None:
        rot_status_lbl = Gtk.Label(label="")
        rot_status_lbl.get_style_context().add_class("caption")
        rot_status_lbl.set_opacity(0.75)
        rot_status_lbl.set_no_show_all(True)
        rot_status_lbl.hide()

        def _flash_rot(text: str, ms: int = 2500):
            rot_status_lbl.set_label(text)
            rot_status_lbl.show()
            GLib.timeout_add(ms, lambda: (rot_status_lbl.hide(), False)[1])

        rot_state = {"current": rotation_transform}
        _rot_label_by_val = dict(_ROTATIONS)   # {0: "0°", 1: "90°", ...}

        rot_deg_lbl = Gtk.Label(label=_rot_label_by_val[rotation_transform])
        rot_deg_lbl.get_style_context().add_class("caption")
        rot_deg_lbl.set_opacity(0.65)
        rot_deg_lbl.set_size_request(40, -1)
        rot_deg_lbl.set_halign(Gtk.Align.END)

        # Rotation ist zwar inhaltlich diskret (nur 4 mögliche Werte),
        # wird aber jetzt trotzdem als echter Zieh-Regler dargestellt
        # statt als 4 einzelne Knöpfe - gleiche Behandlung wie beim
        # Scale-Regler weiter oben. step=1 sorgt dafür, dass Pfeiltasten/
        # Scroll direkt auf ganze Werte springen; beim Ziehen mit der
        # Maus wird trotzdem in _on_rot_slider() hart auf den
        # nächstliegenden ganzzahligen Wert (0-3) gerundet UND der
        # Regler nach dem Loslassen sichtbar dahin einrasten gelassen -
        # ein "Rotation von 47°" soll es nicht geben können.
        rot_box, rot_slider = bslider(
            "󰑖", 0, len(_ROTATIONS) - 1, 1, rotation_transform,
            cb=None, show_val=False, suffix_lbl=rot_deg_lbl)
        for mark_val, _lbl in _ROTATIONS:
            rot_slider.add_mark(mark_val, Gtk.PositionType.BOTTOM, None)

        _rot_debounce_id = [0]

        def _apply_rotation(value: int, prev: int):
            def _apply():
                ok, msg = _rotation_set(name, value)
                if not ok:
                    raise RuntimeError(msg)

            def _reset():
                rot_state["current"] = prev
                rot_deg_lbl.set_label(_rot_label_by_val[prev])
                rot_slider.handler_block(rot_handler_id)
                rot_slider.set_value(prev)
                rot_slider.handler_unblock(rot_handler_id)

            apply_change(f"{name}: rotate {value * 90}°",
                         _apply, on_status=_flash_rot, reset_fn=_reset)

        def _on_rot_slider(s):
            raw = s.get_value()
            snapped = int(round(raw))
            snapped = max(0, min(len(_ROTATIONS) - 1, snapped))
            rot_deg_lbl.set_label(_rot_label_by_val[snapped])
            # Debounced statt bei jedem Drag-Event: verhindert Spam auf
            # den ScreenRotationDaemon-Socket, während man noch zieht.
            if _rot_debounce_id[0]:
                GLib.source_remove(_rot_debounce_id[0])
            def _fire():
                _rot_debounce_id[0] = 0
                # Beim Loslassen sichtbar auf den ganzzahligen Wert
                # einrasten, statt ihn optisch irgendwo dazwischen
                # stehen zu lassen - kurz blockiert, damit das
                # set_value() hier nicht nochmal _on_rot_slider() (und
                # damit eine neue, unnötige Debounce-Runde) auslöst.
                s.handler_block(rot_handler_id)
                s.set_value(snapped)
                s.handler_unblock(rot_handler_id)
                if snapped != rot_state["current"]:
                    prev = rot_state["current"]
                    rot_state["current"] = snapped
                    _apply_rotation(snapped, prev)
                return False
            _rot_debounce_id[0] = GLib.timeout_add(180, _fire)

        rot_handler_id = rot_slider.connect("value-changed", _on_rot_slider)
        rot_slider.set_tooltip_text("Drag to rotate this monitor in 90° steps.")

        wrap.pack_start(rot_box, False, False, 0)
        wrap.pack_start(rot_status_lbl, False, False, 0)

    return wrap

def _waybar_config_paths() -> list:
    """Findet die Waybar-Config-Datei(en). Normalerweise genau eine
    (~/.config/waybar/config.jsonc), aber Waybar erlaubt auch mehrere
    Bar-Configs (z.B. für Multi-Monitor-Setups) - deshalb zur Not
    zusätzlich nach config*.jsonc/.json gesucht."""
    base = Path(HOME) / ".config" / "waybar"
    candidates = []
    for name in ("config.jsonc", "config.json", "config"):
        p = base / name
        if p.is_file():
            candidates.append(p)
    if not candidates and base.is_dir():
        candidates.extend(sorted(base.glob("config*.jsonc")))
        candidates.extend(sorted(base.glob("config*.json")))
    return candidates

def _strip_jsonc_comments(text: str) -> str:
    """Entfernt // und /* */ Kommentare aus einer JSONC-Datei - ohne
    '//' oder '/*' INNERHALB von String-Literalen fälschlich als
    Kommentaranfang zu behandeln (in dieser Waybar-Config stecken
    z.B. lange on-click-Shell-Kommandos in Strings)."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c); i += 1
    return "".join(out)

def _waybar_active_widget_names() -> set | None:
    """Liest alle gefundenen Waybar-Configs und gibt die Menge der
    aktiven Modul-Namen zurück - OHNE 'custom/'-Präfix, also z.B.
    {'volume','network','akku','clock',...}, genau die Namen, die
    auch per 'socat ... <<< <name>' an diesen Daemon geschickt werden
    (siehe on-click in der Waybar-Config). None, wenn keine lesbare
    Config gefunden wurde - der Aufrufer soll das NICHT als "nichts
    ist in der Waybar" werten, sondern als "unbekannt" behandeln."""
    paths = _waybar_config_paths()
    if not paths:
        return None
    names: set = set()
    found_any = False
    for p in paths:
        try:
            data = json.loads(_strip_jsonc_comments(p.read_text()))
        except Exception:
            continue
        found_any = True
        bars = data if isinstance(data, list) else [data]
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            for key in ("modules-left", "modules-center", "modules-right"):
                for m in bar.get(key, []) or []:
                    if isinstance(m, str):
                        names.add(m.split("/", 1)[-1].lower())
    return names if found_any else None

# Welchem eigenständigen Waybar-Modul entspricht eine Settings-
# Kategorie? Display/Appearance/Apps haben KEIN eigenes Waybar-Modul
# (nur Unterseiten hier in den Settings) und landen daher immer unter
# "Nicht in der Waybar".
_CATEGORY_WAYBAR_WIDGET = {
    "audio":      "volume",
    "network":    "network",
    "bluetooth":  "bluetooth",
    "brightness": "brightness",
    "battery":    "akku",
    "calendar":   "clock",
    "security":   "security",
}

def _category_in_waybar(cat_key: str, active_names) -> bool:
    widget_name = _CATEGORY_WAYBAR_WIDGET.get(cat_key)
    if widget_name is None:
        return False
    if active_names is None:
        # Config nicht lesbar: bestmögliche Vermutung statt eines
        # sinnlos leeren "In Waybar"-Tabs - eine Kategorie mit
        # eigenem Waybar-Pendant gilt dann als vermutlich aktiv.
        return True
    return widget_name in active_names

SETTINGS_CATEGORIES = [
    ("display",    "󰍹", "Display",       "Resolution, Framerate"),
    ("brightness", "󰃟", "Brightness",    "Screen, Keyboard RGB, Night Light"),
    ("appearance", "󰉼", "Appearance & Language", "Light/Dark, System language, Keyboard"),
    ("audio",      "󰕾", "Audio",         "Volume, Devices, Apps"),
    ("network",    "󰤨", "Network",       "LAN, Wi-Fi, Mesh Connect"),
    ("bluetooth",  "󰂯", "Bluetooth",     "Pair & connect devices"),
    ("battery",    "󰁹", "Battery",       "Advanced power options"),
    ("calendar",   "󰃭", "Calendar",      "Weather, Time, Events"),
    ("security",   "󰦝", "Security",      "Privacy, Kill-Switches"),
    ("apps",       "󱁤", "Apps & Editor", "Launcher editor, Config files"),
]

def _build_settings_brightness(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_brightness_content(win), True, True, 0)

def _build_settings_audio(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_volume_content(win), True, True, 0)

def _build_settings_bluetooth(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_bluetooth_content(), True, True, 0)

def _build_settings_calendar(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_clock_content(win), True, True, 0)

# ════════════════════════════════════════════════════════════
#  Security-Widget: Privileged-Run-Helper
# ════════════════════════════════════════════════════════════
# Absprache mit dem Nutzer: KEINE eigene Polkit-.policy-Datei - pkexec
# fragt für die generische Standard-Aktion
# "org.freedesktop.policykit.exec" ohnehin bei JEDEM Aufruf nach dem
# Passwort, exakt das gewünschte Verhalten ("Nutzer soll jedes Mal das
# Passwort eingeben"), und ist damit auch sicherer als ein dauerhaft
# als root laufender Helfer-Daemon.
def _run_maybe_priv(cmd: list, timeout: int = 10) -> tuple[bool, str]:
    """Führt cmd zuerst ganz normal (unprivilegiert) aus - viele
    rfkill-Aktionen erlauben das auf den meisten Distros sowieso schon
    per udev-/Gruppenregel. NUR wenn das mit einem typischen
    Permission-Fehler scheitert, wird automatisch mit pkexec eskaliert
    (grafischer Polkit-Passwort-Dialog, timeout hier bewusst höher, da
    der Nutzer ja erst noch das Passwort eintippen muss)."""
    out, err, ec = run_ec(cmd, timeout=timeout)
    if ec == 0:
        return True, out
    # War bisher zu eng gefasst: ufw meldet bei fehlenden Rechten
    # WEDER "Permission denied" NOCH "must be root" NOCH EACCES,
    # sondern wörtlich "ERROR: You need to be root to run this
    # script." - passte auf keins der bisherigen Muster, needs_root
    # blieb also False, es wurde NIE auf pkexec eskaliert und der
    # Passwort-Dialog kam dementsprechend nie (genau der gemeldete Bug:
    # "es kommt kein Passwortfeld"). Jetzt eine deutlich breitere,
    # klein geschriebene Prüfung gegen mehrere gängige Formulierungen
    # verschiedener Tools statt nur exakter Wortlaute EINES Tools.
    err_l = err.lower()
    needs_root = any(s in err_l for s in (
        "permission denied", "operation not permitted", "eacces",
        "must be root", "need to be root", "needs to be root",
        "requires root", "requires superuser", "must be superuser",
        "run as root", "run this as root", "root privileges",
        "root to run", "not permitted", "not authorized",
        "authentication is required", "access denied"))
    if needs_root:
        out, err, ec = run_ec(["pkexec"] + cmd, timeout=max(timeout, 60))
        if ec == 0:
            return True, out
    return False, (err or f"exit code {ec}")

# ── Wifi/Bluetooth: rfkill (echter Kernel-Funk-Killswitch) ───────────
def _rfkill_devices() -> list:
    data = jrun(["rfkill", "--json"]) or {}
    if isinstance(data, dict):
        return data.get("rfkilldevices", [])
    return []

def _rfkill_state(rf_type: str) -> str:
    """"missing" (kein passendes Gerät), "hard-blocked" (physischer
    Schalter/Flugmodus-Taste - lässt sich NICHT per Software wieder
    freigeben, siehe rfkill(8)), "soft-blocked" oder "unblocked"."""
    devs = [d for d in _rfkill_devices() if d.get("type") == rf_type]
    if not devs:
        return "missing"
    if any(d.get("hard") == "blocked" for d in devs):
        return "hard-blocked"
    if any(d.get("soft") == "blocked" for d in devs):
        return "soft-blocked"
    return "unblocked"

def _rfkill_set(rf_type: str, blocked: bool) -> tuple[bool, str]:
    # rfkill akzeptiert Typnamen direkt (z.B. "wlan"/"bluetooth") statt
    # nur einzelner IDs - blockiert/entblockt damit in EINEM Aufruf
    # gleich alle Adapter dieses Typs (z.B. beide Wifi-Karten bei einem
    # Dual-Radio-Laptop).
    return _run_maybe_priv(["rfkill", "block" if blocked else "unblock", rf_type])

# ── Kamera: Device-Node-Zugriff komplett sperren ─────────────────────
# Bewusst KEIN Kernel-Modul-Unbind (uvcvideo etc.) - das ist je nach
# Treiber unterschiedlich robust/reversibel und kann bei manchen
# Laptops (Kamera + andere Funktion am selben USB-Controller) mehr als
# nur die Kamera lahmlegen. chmod auf die Device-Nodes selbst ist
# treiberunabhängig, sofort wirksam für JEDEN Prozess (auch schon
# laufende Videochat-Apps verlieren den Zugriff beim nächsten Frame)
# und genauso sofort wieder rückgängig zu machen.
def _camera_devices() -> list:
    return sorted(glob.glob("/dev/video*"))

def _camera_blocked() -> bool | None:
    devs = _camera_devices()
    if not devs:
        return None
    try:
        for d in devs:
            mode = os.stat(d).st_mode
            if mode & (stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO):
                return False   # mindestens ein Node noch zugreifbar -> nicht blockiert
        return True
    except OSError:
        return None

def _camera_set_blocked(blocked: bool) -> tuple[bool, str]:
    devs = _camera_devices()
    if not devs:
        return False, "No camera device found"
    mode = "000" if blocked else "660"
    # IMMER direkt mit pkexec statt erst unprivilegiert zu versuchen:
    # /dev/video*-Nodes gehören root:video, chmod braucht den
    # Eigentümer oder root - reines Gruppen-Schreibrecht (auch wenn der
    # Nutzer selbst in "video" ist) reicht dafür nicht, der erste
    # Versuch würde also ohnehin garantiert scheitern.
    return _run_maybe_priv(["chmod", mode, *devs], timeout=15)

# ── Mikrofon: Standard-Eingabegerät stumm schalten ───────────────────
# Kein echter Hardware-Killswitch (Software-Mute über wpctl/Pipewire,
# genau wie im Sound-Widget), aber hier trotzdem mit drin - gehört zum
# "alles auf einen Blick sperren"-Zweck dieses Privacy-Panels dazu,
# auch wenn es technisch reversibler ist als Wifi/Bluetooth/Kamera.
def _mic_muted() -> bool:
    return "[MUTED]" in run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])

def _mic_set_muted(muted: bool) -> tuple[bool, str]:
    out, err, ec = run_ec(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@",
                            "1" if muted else "0"])
    return ec == 0, err

# ── Touchpad & Touchscreen: über Hyprlands eigene Geräteverwaltung ──
# 'hyprctl keyword device:<name>:enabled 0/1' schaltet ein einzelnes
# Input-Gerät zur Laufzeit komplett ab/an - funktioniert für Touchpads
# UND Touchscreens gleichermaßen, beide tauchen in 'hyprctl devices -j'
# als eigene Geräte auf. Das genaue Geräte-Objekt muss aber jedes Mal
# frisch gesucht werden (Name kann sich zwischen Boots leicht ändern,
# z.B. USB-Touchscreens), nicht einmalig gecacht werden.
def _hypr_devices() -> list:
    data = jrun(["hyprctl", "devices", "-j"]) or {}
    devices = []
    for items in data.values():
        if isinstance(items, list):
            devices.extend(items)
    return devices

def _find_hypr_device(keywords: tuple) -> dict | None:
    for d in _hypr_devices():
        name = (d.get("name") or "").lower()
        if any(k in name for k in keywords):
            return d
    return None

# Fallback-Merker: nicht jede Hyprland-Version liefert ein "enabled"-
# Feld im devices-JSON zuverlässig mit zurück - fehlt es, auf den
# zuletzt SELBST gesetzten Zustand zurückfallen statt fälschlich immer
# "an" anzuzeigen, nachdem man's gerade erst blockiert hat.
_touchpad_last_set = {"enabled": True}
_touchscreen_last_set = {"enabled": True}

def _touchpad_blocked() -> bool | None:
    dev = _find_hypr_device(("touchpad",))
    if dev is None:
        return None
    return not dev.get("enabled", _touchpad_last_set["enabled"])

def _touchpad_set_blocked(blocked: bool) -> tuple[bool, str]:
    dev = _find_hypr_device(("touchpad",))
    if dev is None:
        return False, "No touchpad found"
    out, err, ec = run_ec(
        ["hyprctl", "keyword", f"device:{dev.get('name','')}:enabled",
         "0" if blocked else "1"], timeout=10)
    if ec != 0:
        return False, err or out
    _touchpad_last_set["enabled"] = not blocked
    return True, ""

def _touchscreen_blocked() -> bool | None:
    dev = _find_hypr_device(("touchscreen", "touch screen", "finger"))
    if dev is None:
        return None
    return not dev.get("enabled", _touchscreen_last_set["enabled"])

def _touchscreen_set_blocked(blocked: bool) -> tuple[bool, str]:
    dev = _find_hypr_device(("touchscreen", "touch screen", "finger"))
    if dev is None:
        return False, "No touchscreen found"
    out, err, ec = run_ec(
        ["hyprctl", "keyword", f"device:{dev.get('name','')}:enabled",
         "0" if blocked else "1"], timeout=10)
    if ec != 0:
        return False, err or out
    _touchscreen_last_set["enabled"] = not blocked
    return True, ""

def _privacy_content(win: Gtk.Window) -> Gtk.Box:
    """Privacy/Hardware-Kill-Switches-Tab: Wifi, Bluetooth, Kamera,
    Mikrofon jeweils mit einem Tap komplett sperren. Kleinster/
    einfachster der 5 Security-Unterbereiche aus der README (UFW, DNS,
    Tailscale, Privacy/Kill-Switches, ClamAV) - deshalb hier zuerst
    umgesetzt, die anderen 4 folgen als weitere Tabs in
    _security_content() unten."""
    root = vbox(4); pad(root, h=4, v=6)
    root.pack_start(btitle("󰦝  Privacy"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 3000):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    # Sammelt aus JEDER einzelnen Zeile unten eine "block jetzt,
    # synchron, ohne eigenes apply_change()"-Funktion + eine "UI neu
    # einlesen"-Funktion - der Panic-Button weiter unten ruft dann
    # EINMAL alle Block-Funktionen in einem gemeinsamen apply_change()
    # auf (ein Hintergrund-Thread, EIN Status-Text, kein Spam aus 4-5
    # einzelnen Flash-Meldungen hintereinander) und danach alle
    # Refresh-Funktionen, damit jede Zeile ihren tatsächlichen
    # Endzustand zeigt.
    _force_block_fns: list = []
    _refresh_fns: list = []

    panic_btn = btn("🚨  Lock everything")
    panic_btn.set_halign(Gtk.Align.CENTER)
    panic_btn.set_tooltip_text(
        "Immediately blocks Wi-Fi, Bluetooth, WWAN/GPS, Camera and "
        "Microphone all at once (meeting-mode style).")
    root.pack_start(panic_btn, False, False, 0)
    root.pack_start(sep(), False, False, 4)

    # Jede Zeile ist jetzt EIN EINZIGER Button (Text = Schalter, kein
    # separates Toggle-Element daneben mehr) - klick auf den Text selbst
    # schaltet um, "leuchtet" (aktive Klasse) wenn blockiert, sonst
    # nicht. Zwei pro Zeile nebeneinander über ein normales hbox-Paar
    # (bewusst KEIN Gtk.Grid mehr - das war zuvor im Verdacht, an der
    # Nicht-Reaktion der Buttons beteiligt gewesen zu sein).
    def _make_rfkill_row(rf_type: str, icon: str, label_text: str) -> Gtk.Button:
        b = btn(f"{icon}  {label_text}")
        b.set_hexpand(True)

        def _refresh():
            state = _rfkill_state(rf_type)
            ctx = b.get_style_context()
            if state == "missing":
                b.set_sensitive(False)
                ctx.remove_class("active")
                b.set_tooltip_text("No adapter found")
            elif state == "hard-blocked":
                b.set_sensitive(False)
                ctx.add_class("active")
                b.set_tooltip_text(
                    "Blocked by a physical switch/airplane-mode key - "
                    "can't be re-enabled from software.")
            else:
                b.set_sensitive(True)
                blocked = state == "soft-blocked"
                if blocked: ctx.add_class("active")
                else:       ctx.remove_class("active")
                b.set_tooltip_text("Tap to " + ("allow" if blocked else "block"))

        def _on_click(_w):
            state = _rfkill_state(rf_type)
            if state in ("missing", "hard-blocked"):
                return
            new_blocked = state != "soft-blocked"
            ctx = b.get_style_context()
            if new_blocked: ctx.add_class("active")
            else:           ctx.remove_class("active")
            def _apply():
                ok, err = _rfkill_set(rf_type, new_blocked)
                if not ok:
                    raise RuntimeError(err)
            apply_change(f"{label_text}: {'Blocked' if new_blocked else 'Allowed'}",
                         _apply, on_status=_flash, reset_fn=_refresh)

        b.connect("clicked", _on_click)
        _refresh()
        _force_block_fns.append(lambda t=rf_type: _rfkill_set(t, True))
        _refresh_fns.append(_refresh)
        return b

    _privacy_rows = [
        _make_rfkill_row("wlan", "󰤨", "Wi-Fi"),
        _make_rfkill_row("bluetooth", "󰂯", "Bluetooth"),
        # WWAN/GPS: nur auf Laptops mit eingebautem Mobilfunk-Modem
        # vorhanden - _rfkill_state() gibt für alle anderen Systeme
        # "missing" zurück, der Button zeigt sich dann selbst als
        # deaktiviert (siehe _make_rfkill_row()), kein Sonderfall hier nötig.
        _make_rfkill_row("wwan", "󰤩", "WWAN / GPS"),
    ]

    # ── Kamera & Mikrofon: einfaches Bool-Muster (kein Hard/Soft-
    #    Unterschied wie bei rfkill) ──────────────────────────────────
    def _make_bool_row(icon: str, label_text: str, get_blocked, set_blocked,
                        missing_tip: str = "Not found") -> Gtk.Button:
        b = btn(f"{icon}  {label_text}")
        b.set_hexpand(True)

        def _refresh():
            blocked = get_blocked()
            ctx = b.get_style_context()
            if blocked is None:
                b.set_sensitive(False)
                ctx.remove_class("active")
                b.set_tooltip_text(missing_tip)
                return
            b.set_sensitive(True)
            if blocked: ctx.add_class("active")
            else:       ctx.remove_class("active")
            b.set_tooltip_text("Tap to " + ("allow" if blocked else "block"))

        def _on_click(_w):
            cur = get_blocked()
            if cur is None:
                return
            new_val = not cur
            ctx = b.get_style_context()
            if new_val: ctx.add_class("active")
            else:       ctx.remove_class("active")
            def _apply():
                ok, err = set_blocked(new_val)
                if not ok:
                    raise RuntimeError(err)
            apply_change(f"{label_text}: {'Blocked' if new_val else 'Allowed'}",
                         _apply, on_status=_flash, reset_fn=_refresh)

        b.connect("clicked", _on_click)
        _refresh()
        _force_block_fns.append(lambda sb=set_blocked: sb(True))
        _refresh_fns.append(_refresh)
        return b

    _privacy_rows.append(_make_bool_row(
        "󰄀", "Camera", _camera_blocked, _camera_set_blocked,
        missing_tip="No /dev/video* device found"))
    _privacy_rows.append(_make_bool_row(
        "󰍬", "Microphone", _mic_muted, _mic_set_muted,
        missing_tip="No default input device"))
    _privacy_rows.append(_make_bool_row(
        "🖱️", "Touchpad", _touchpad_blocked, _touchpad_set_blocked,
        missing_tip="No touchpad found"))
    _privacy_rows.append(_make_bool_row(
        "👆", "Touchscreen", _touchscreen_blocked, _touchscreen_set_blocked,
        missing_tip="No touchscreen found"))

    # 2 pro Zeile via normalem hbox-Paar (kein Gtk.Grid).
    for i in range(0, len(_privacy_rows), 2):
        prow = hbox(6)
        prow.pack_start(_privacy_rows[i], True, True, 0)
        if i + 1 < len(_privacy_rows):
            prow.pack_start(_privacy_rows[i + 1], True, True, 0)
        root.pack_start(prow, False, False, 0)

    def _on_panic(_w):
        def _apply():
            errors = []
            for fn in _force_block_fns:
                ok, err = fn()
                if not ok and err:
                    errors.append(err)
            if errors:
                raise RuntimeError("; ".join(errors[:3]))
        def _refresh_all():
            for r in _refresh_fns:
                r()
        apply_change("Lock everything", _apply, on_status=_flash,
                     reset_fn=_refresh_all)
        GLib.timeout_add(600, lambda: (_refresh_all(), False)[1])
    panic_btn.connect("clicked", _on_panic)

    root.pack_start(status_lbl, False, False, 6)
    return root

# ════════════════════════════════════════════════════════════
#  Security-Widget: UFW (Uncomplicated Firewall)
# ════════════════════════════════════════════════════════════
# WICHTIG: praktisch JEDER ufw-Aufruf braucht Root - auch nur der
# Status! ("ERROR: You need to be root to run this script" bei einem
# normalen User). Deshalb wird hier NICHT wie beim System-Monitor alle
# paar Sekunden automatisch neu abgefragt (das würde bei JEDEM
# Auto-Refresh einen neuen Polkit-Passwort-Dialog aufreißen) - Status
# wird nur EINMAL beim Öffnen des Tabs UND nach jeder eigenen Aktion
# (enable/disable/Regel hinzufügen/löschen) neu geholt, plus ein
# manueller Refresh-Button für alle Fälle, in denen sich ufw von
# außerhalb dieses Panels geändert hat (z.B. per Terminal).
def _ufw_available() -> bool:
    return shutil.which("ufw") is not None

def _ufw_status() -> dict:
    """{"active": bool, "rules": [{"num":int,"to":str,"action":str,"from":str}]}
    Geparst aus 'ufw status numbered', z.B.:
        Status: active
        [ 1] 22/tcp                     ALLOW IN    Anywhere
    ok=False falls der Aufruf selbst fehlschlägt (z.B. root-Prompt vom
    Nutzer abgebrochen) - dann bleiben active/rules auf Default-Werten,
    der Aufrufer erkennt das am zusätzlichen "error"-Feld."""
    ok, out = _run_maybe_priv(["ufw", "status", "numbered"], timeout=15)
    if not ok:
        return {"active": False, "rules": [], "error": out}
    active = "Status: active" in out
    rules = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        m = re.match(r"^\[\s*(\d+)\]\s+(.*)$", line)
        if not m:
            continue
        num = int(m.group(1))
        # ufw richtet die 3 Spalten (To/Action/From) mit variabel
        # vielen Leerzeichen aus - mind. 2 Leerzeichen am Stück trennen
        # sie zuverlässig genug, ohne eine feste Spaltenbreite
        # anzunehmen (die je nach längstem Eintrag variiert).
        parts = re.split(r"\s{2,}", m.group(2).strip())
        rules.append({
            "num": num,
            "to":     parts[0] if len(parts) > 0 else "?",
            "action": parts[1] if len(parts) > 1 else "?",
            "from":   parts[2] if len(parts) > 2 else "?",
        })
    return {"active": active, "rules": rules}

def _ufw_set_enabled(enabled: bool) -> tuple[bool, str]:
    # --force: ufw fragt bei "enable" sonst interaktiv auf stdin nach
    # ("Command may disrupt existing ssh connections. Proceed?"), was
    # hier (kein TTY) sonst einfach nur hängen würde.
    cmd = ["ufw", "--force", "enable"] if enabled else ["ufw", "--force", "disable"]
    return _run_maybe_priv(cmd, timeout=20)

def _ufw_delete_rule(num: int) -> tuple[bool, str]:
    return _run_maybe_priv(["ufw", "--force", "delete", str(num)], timeout=15)

def _ufw_add_rule(action: str, port_spec: str) -> tuple[bool, str]:
    return _run_maybe_priv(["ufw", action, port_spec], timeout=15)

_PORT_SPEC_RE = re.compile(
    r"^\d{1,5}(:\d{1,5})?(/(tcp|udp))?$", re.IGNORECASE)

_UFW_PRESETS = [
    ("Steam LAN",   [("allow", "27031:27036/udp")]),
    ("KDE Connect", [("allow", "1714:1764/tcp"), ("allow", "1714:1764/udp")]),
    ("Samba",       [("allow", "samba")]),
]

def _ufw_preset_active(specs: list, rules: list) -> bool:
    """Ein Preset gilt als 'an', wenn für JEDEN seiner Teil-Specs (KDE
    Connect braucht z.B. TCP UND UDP zugleich) eine passende ALLOW-
    Regel existiert. Vergleich ist bewusst simpel/case-insensitive und
    auf Teilstring-Ebene - ufw normalisiert Anzeige-Strings leicht
    anders als die Eingabe (z.B. bei App-Profilen wie "samba" ->
    "Samba"), ein exakter Vergleich wäre hier zu zerbrechlich."""
    for _action, spec in specs:
        spec_l = spec.lower()
        spec_base = spec_l.split("/")[0]
        found = any(
            r["action"].upper().startswith("ALLOW") and
            (spec_l in r["to"].lower() or spec_base in r["to"].lower())
            for r in rules)
        if not found:
            return False
    return True

def _ufw_apply_preset(specs: list, enable: bool) -> tuple[bool, str]:
    """Fügt (enable=True) oder entfernt (enable=False) ALLE Teil-Regeln
    eines Presets. 'ufw delete allow <spec>' funktioniert bei ufw auch
    ohne die Regelnummer zu kennen, solange die Regel exakt so
    spezifiziert wird, wie sie angelegt wurde."""
    for action, spec in specs:
        cmd = (["ufw", action, spec] if enable else
               ["ufw", "--force", "delete", action, spec])
        ok, err = _run_maybe_priv(cmd, timeout=15)
        if not ok:
            return False, err
    return True, ""

_UFW_LOG_FIELD_RE = re.compile(r"\b(SRC|DST|SPT|DPT|PROTO)=(\S+)")
_UFW_LOG_TIME_RE  = re.compile(r"^(\w{3}\s+\d+\s[\d:]+)")

def _ufw_log_lines(n: int = 300) -> list:
    """Letzte N Zeilen aus /var/log/ufw.log, gefiltert auf
    '[UFW BLOCK]' - die Datei gehört üblicherweise root:adm mit Modus
    640, ein normaler User kann sie meist nicht lesen, deshalb über
    _run_maybe_priv() (pkexec bei Bedarf)."""
    ok, out = _run_maybe_priv(["tail", "-n", str(n), "/var/log/ufw.log"], timeout=10)
    if not ok:
        return []
    lines = [l for l in out.splitlines() if "[UFW BLOCK]" in l]
    lines.reverse()  # neueste zuerst
    return lines

def _parse_ufw_log_line(line: str) -> dict:
    fields = dict(_UFW_LOG_FIELD_RE.findall(line))
    m = _UFW_LOG_TIME_RE.match(line)
    return {
        "when":  m.group(1) if m else "",
        "src":   fields.get("SRC", "?"),
        "dst":   fields.get("DST", "?"),
        "spt":   fields.get("SPT", ""),
        "dpt":   fields.get("DPT", ""),
        "proto": fields.get("PROTO", "?"),
    }

def _ufw_content(win: Gtk.Window) -> Gtk.Box:
    root = vbox(4); pad(root, h=4, v=6)
    root.pack_start(btitle("󰈸  Firewall"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    if not _ufw_available():
        root.pack_start(bitem("ufw is not installed", dim=True), False, False, 0)
        return root

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 3500):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    # ── Ein/Aus-Schalter: "Firewall:" oben, Status+Refresh darunter,
    # beides zentriert (README-Feedback) ─────────────────────────────
    onoff_col = vbox(2)
    onoff_col.set_halign(Gtk.Align.CENTER)
    onoff_lbl = Gtk.Label(label="Firewall:")
    onoff_lbl.get_style_context().add_class("caption")
    onoff_lbl.set_halign(Gtk.Align.CENTER)
    onoff_col.pack_start(onoff_lbl, False, False, 0)

    onoff_state_row = hbox(8)
    onoff_state_row.set_halign(Gtk.Align.CENTER)
    onoff_toggle = btn("")
    refresh_b = Gtk.Button(label="󰑐")
    refresh_b.set_relief(Gtk.ReliefStyle.NONE)
    refresh_b.get_style_context().add_class("flat")
    refresh_b.set_opacity(0.7)
    refresh_b.set_tooltip_text("Refresh status")
    onoff_state_row.pack_start(onoff_toggle, False, False, 0)
    onoff_state_row.pack_start(refresh_b, False, False, 0)
    onoff_col.pack_start(onoff_state_row, False, False, 0)
    root.pack_start(onoff_col, False, False, 0)

    # ── Presets: ein Klick für ein paar gängige, oft gebrauchte
    # Portfreigaben, statt jedes Mal den Add-Rule-Dialog per Hand
    # auszufüllen. Zeigt seinen eigenen An/Aus-Zustand, erkannt aus der
    # aktuellen Regelliste (siehe _ufw_preset_active()).
    root.pack_start(sep(), False, False, 4)
    root.pack_start(bsec("PRESETS"), False, False, 0)
    preset_row = hbox(6)
    preset_row.set_halign(Gtk.Align.CENTER)
    preset_btns: dict = {}
    for pname, pspecs in _UFW_PRESETS:
        pb = btn(pname)
        preset_btns[pname] = pb
        def _on_preset(_w, n=pname, sp=pspecs):
            new_val = not _ufw_preset_active(sp, _state["rules"])
            def _apply():
                ok, err = _ufw_apply_preset(sp, new_val)
                if not ok:
                    raise RuntimeError(err)
            apply_change(f"{n}: {'On' if new_val else 'Off'}", _apply, on_status=_flash)
            GLib.timeout_add(600, lambda: (_load_status(), False)[1])
        pb.connect("clicked", _on_preset)
        preset_row.pack_start(pb, False, False, 0)
    root.pack_start(preset_row, False, False, 0)
    root.pack_start(sep(), False, False, 4)

    # ── 2 Sub-Tabs: Rules (wie bisher) + neu Log ──────────────────────
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    t_rules = vbox(3)
    t_rules.pack_start(bsec("RULES"), False, False, 0)
    rules_sw, rules_box = scroll_box(200)
    t_rules.pack_start(rules_sw, False, False, 0)
    add_row_btn = btn("➕  Add rule")
    t_rules.pack_start(add_row_btn, False, False, 0)

    t_log = vbox(3)
    log_sw, log_box = scroll_box(240)
    t_log.pack_start(log_sw, False, False, 0)
    refresh_log_btn = btn("󰑐  Refresh log")
    t_log.pack_start(refresh_log_btn, False, False, 0)

    stack.add_named(t_rules, "rules")
    stack.add_named(t_log, "log")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    _log_loaded = [False]

    def _switch_ufw_tab(name):
        if name == "log" and not _log_loaded[0]:
            _log_loaded[0] = True
            _load_log()
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")

    for tname, tlabel in (("rules", "Rules"), ("log", "Log")):
        tb = btn(tlabel, active=(tname == "rules"))
        tb.connect("clicked", lambda _b, n=tname: _switch_ufw_tab(n))
        tab_btns[tname] = tb
        tab_row.pack_start(tb, False, False, 0)
    stack.set_visible_child_name("rules")

    root.pack_start(tab_row, True, False, 2)
    root.pack_start(tab_sep(), False, False, 0)
    root.pack_start(stack, False, False, 0)
    root.pack_start(status_lbl, False, False, 4)

    _state = {"active": False, "rules": []}

    def _rebuild_log_ui(lines: list):
        for c in log_box.get_children():
            log_box.remove(c)
        if not lines:
            log_box.pack_start(
                bitem("No blocked connections logged (yet)", dim=True), False, False, 0)
        for line in lines[:150]:
            info = _parse_ufw_log_line(line)
            txt = (f'{info["when"]}  ·  {info["src"]}:{info["spt"]} → '
                   f'{info["dst"]}:{info["dpt"]}  ({info["proto"]})')
            log_box.pack_start(bitem(txt), False, False, 0)
        log_box.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    def _load_log():
        refresh_log_btn.set_sensitive(False)
        def _work():
            lines = _ufw_log_lines()
            def _apply():
                refresh_log_btn.set_sensitive(True)
                _rebuild_log_ui(lines)
            GLib.idle_add(_apply)
        in_thread(_work)

    refresh_log_btn.connect("clicked", lambda _w: _load_log())

    def _rebuild_rules_ui():
        for c in rules_box.get_children():
            rules_box.remove(c)
        if not _state["rules"]:
            rules_box.pack_start(
                bitem("No rules" if _state["active"] else
                      "Firewall is off - existing rules stay saved but inactive",
                      dim=True), False, False, 0)
        for r in _state["rules"]:
            row = hbox(8)
            row.get_style_context().add_class("bubble")
            row.get_style_context().add_class("item")
            pad(row, h=8, v=4)
            action_icon = "🟢" if r["action"].upper().startswith("ALLOW") else \
                          ("🟡" if r["action"].upper().startswith("LIMIT") else "🔴")
            lbl = Gtk.Label(
                label=f'{action_icon} {r["to"]}  ·  {r["action"]}  ·  from {r["from"]}')
            lbl.set_halign(Gtk.Align.START)
            # KEIN set_ellipsize() mehr - gleicher Fix wie beim Task-
            # Manager: Regel sollte NIE abgeschnitten werden, egal wie
            # lang Ports/Adressen sind. _shrink_to_fit() weiter unten
            # lässt die Blase auf die dafür nötige Breite wachsen,
            # _clamp_window_to_screen() greift trotzdem als
            # Sicherheitsnetz gegen den Bildschirmrand.
            lbl.set_hexpand(True)
            row.pack_start(lbl, True, True, 0)
            del_b = Gtk.Button(label="󰅖")
            del_b.set_relief(Gtk.ReliefStyle.NONE)
            del_b.get_style_context().add_class("flat")
            del_b.set_opacity(0.7)
            del_b.set_tooltip_text("Delete rule")
            def _on_del(_w, num=r["num"], desc=r["to"]):
                def _apply():
                    ok, err = _ufw_delete_rule(num)
                    if not ok:
                        raise RuntimeError(err)
                def _after():
                    _load_status()
                apply_change(f"Delete rule: {desc}", _apply,
                             on_status=_flash, reset_fn=_after)
                GLib.timeout_add(400, lambda: (_load_status(), False)[1])
            del_b.connect("clicked", _on_del)
            row.pack_start(del_b, False, False, 0)
            rules_box.pack_start(row, False, False, 0)
        rules_box.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    def _refresh_onoff_ui():
        onoff_toggle.set_label("🟢 Active" if _state["active"] else "🔴 Inactive")
        ctx = onoff_toggle.get_style_context()
        if _state["active"]: ctx.add_class("active")
        else:                ctx.remove_class("active")

    def _refresh_presets_ui():
        for pname, pspecs in _UFW_PRESETS:
            ctx = preset_btns[pname].get_style_context()
            if _ufw_preset_active(pspecs, _state["rules"]):
                ctx.add_class("active")
            else:
                ctx.remove_class("active")

    def _load_status():
        def _work():
            data = _ufw_status()
            def _apply():
                if data.get("error"):
                    _flash(f"Could not read firewall status: {data['error']}", ms=5000)
                    return
                _state["active"] = data["active"]
                _state["rules"] = data["rules"]
                _refresh_onoff_ui()
                _refresh_presets_ui()
                _rebuild_rules_ui()
            GLib.idle_add(_apply)
        in_thread(_work)

    def _on_onoff_toggle(_w):
        new_val = not _state["active"]
        _state["active"] = new_val
        _refresh_onoff_ui()
        def _apply():
            ok, err = _ufw_set_enabled(new_val)
            if not ok:
                raise RuntimeError(err)
        def _reset():
            _load_status()
        apply_change(f"Firewall: {'On' if new_val else 'Off'}", _apply,
                     on_status=_flash, reset_fn=_reset)
        GLib.timeout_add(600, lambda: (_load_status(), False)[1])

    onoff_toggle.connect("clicked", _on_onoff_toggle)
    refresh_b.connect("clicked", lambda _w: _load_status())

    def _on_add_rule(_w):
        dlg = Gtk.Dialog(title="Add firewall rule", transient_for=win)
        dlg.set_name("wb-daemon-popup")
        dlg.set_modal(True)
        dlg.set_keep_above(True)
        dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Add", Gtk.ResponseType.OK)
        content = dlg.get_content_area()
        content.set_spacing(8)
        pad(content, h=14, v=10)
        dlg.set_default_size(320, 1)

        port_e = Gtk.Entry()
        port_e.set_placeholder_text("Port, e.g. 22, 8080/tcp, 60000:61000/udp")
        port_e.set_activates_default(True)
        content.pack_start(port_e, False, False, 0)

        action_row = hbox(8)
        allow_toggle = btn("✅  Allow", active=True)
        deny_toggle  = btn("⛔  Deny")
        action_state = {"action": "allow"}
        def _pick_allow(_w=None):
            action_state["action"] = "allow"
            allow_toggle.get_style_context().add_class("active")
            deny_toggle.get_style_context().remove_class("active")
        def _pick_deny(_w=None):
            action_state["action"] = "deny"
            deny_toggle.get_style_context().add_class("active")
            allow_toggle.get_style_context().remove_class("active")
        allow_toggle.connect("clicked", _pick_allow)
        deny_toggle.connect("clicked", _pick_deny)
        action_row.pack_start(allow_toggle, False, False, 0)
        action_row.pack_start(deny_toggle, False, False, 0)
        content.pack_start(action_row, False, False, 0)

        err_lbl = Gtk.Label(label="")
        err_lbl.get_style_context().add_class("caption")
        err_lbl.set_no_show_all(True)
        err_lbl.hide()
        content.pack_start(err_lbl, False, False, 0)

        ok_btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        if ok_btn: ok_btn.set_can_default(True); ok_btn.grab_default()

        dlg.show_all()
        err_lbl.hide()
        port_e.grab_focus()
        dlg_destroyed = [False]
        dlg.connect("destroy", lambda _d: dlg_destroyed.__setitem__(0, True))

        while True:
            resp = dlg.run()
            if resp != Gtk.ResponseType.OK:
                break
            spec = port_e.get_text().strip()
            if not _PORT_SPEC_RE.match(spec):
                err_lbl.set_label(
                    "Invalid format - use a port, port range, or port/protocol "
                    "(e.g. 22, 6000:6010, 8080/tcp)")
                err_lbl.show()
                continue
            action = action_state["action"]
            def _apply(spec=spec, action=action):
                ok, err = _ufw_add_rule(action, spec)
                if not ok:
                    raise RuntimeError(err)
            apply_change(f"{action.title()} {spec}", _apply, on_status=_flash)
            GLib.timeout_add(600, lambda: (_load_status(), False)[1])
            break
        if not dlg_destroyed[0]:
            dlg.destroy()

    add_row_btn.connect("clicked", _on_add_rule)

    _load_status()
    return root


def _tailscale_available() -> bool:
    return shutil.which("tailscale") is not None

def _local_username() -> str:
    """Lokaler System-Username für die 'user@hostname'-Anzeige beim
    Tailscale-Tab (siehe README-Feedback: bei mehreren gleichnamigen
    trafktux-Systemen reicht der Tailscale-Hostname allein nicht zur
    Unterscheidung - genau wie im Terminal-Prompt soll auch hier
    User@Host stehen). os.getlogin() kann in manchen Kontexten ohne
    Controlling-TTY (z.B. als systemd-Service) fehlschlagen - deshalb
    mit Fallback auf $USER/$LOGNAME und zuletzt pwd.getpwuid()."""
    try:
        return os.getlogin()
    except Exception:
        pass
    for var in ("USER", "LOGNAME"):
        val = os.environ.get(var)
        if val:
            return val
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        return "?"

def _tailscale_status() -> dict:
    """Robuster Status-Parser über 'tailscale status --json'. Liefert
    bei Erfolg {"logged_in": bool, "hostname": str, "self_ip": str,
    "peers": [{"name","online","ip"}, ...]}, bei jedem Fehler
    (tailscaled nicht erreichbar, kaputtes JSON, Tool fehlt) stattdessen
    {"error": "..."} - der Aufrufer unterscheidet nur "error vorhanden"
    vs. nicht, muss also nicht zwischen den einzelnen Fehlerursachen
    unterscheiden."""
    out, err, ec = run_ec(["tailscale", "status", "--json"], timeout=5)
    if ec != 0:
        return {"error": err or out or "tailscale status failed"}
    try:
        data = json.loads(out)
    except Exception as e:
        return {"error": f"Could not parse tailscale status: {e}"}
    self_info = data.get("Self", {}) or {}
    peers_raw = data.get("Peer", {}) or {}
    peers = []
    for p in peers_raw.values():
        peers.append({
            "name": p.get("HostName", "?"),
            "online": bool(p.get("Online", False)),
            "ip": (p.get("TailscaleIPs") or [""])[0],
        })
    # Online zuerst, dann alphabetisch - genau wie bei den
    # Bluetooth-/WLAN-Listen anderswo im Daemon.
    peers.sort(key=lambda p: (not p["online"], p["name"].lower()))
    return {
        "logged_in": data.get("BackendState", "") == "Running",
        "hostname": self_info.get("HostName", ""),
        "self_ip": (self_info.get("TailscaleIPs") or [""])[0],
        "peers": peers,
    }

def _tailscale_login_flow(on_url, on_finished, _via_pkexec: bool = False) -> None:
    """Startet 'tailscale up' im Hintergrund. Der Befehl selbst
    BLOCKIERT, bis der Login im Browser abgeschlossen ist (oder er
    timeoutet/abbricht) - läuft deshalb komplett in einem eigenen
    Thread, damit die GTK-Mainloop responsive bleibt. Liest stdout+
    stderr zeilenweise MITLAUFEND (kein run_ec(), das würde erst nach
    Prozessende überhaupt etwas zurückgeben) und reagiert SOFORT, wenn
    die Login-URL erscheint: öffnet sie per xdg-open UND gibt sie über
    on_url() an die UI weiter (falls kein Standardbrowser konfiguriert
    ist, kann man sie wenigstens ablesen/kopieren). on_finished(error)
    wird aufgerufen, sobald der Prozess durch ist - error ist None bei
    Erfolg (schon eingeloggt ODER frisch authentifiziert).

    WICHTIG (Bugfix): meldete bei einem Fehlschlag bisher nur "exit
    code 1" ohne jeden Hinweis, WAS eigentlich schiefging - auf vielen
    Distros ist der tailscaled-Lokal-Socket nämlich nur für root lesbar/
    beschreibbar, 'tailscale up' scheitert dann SOFORT (es wird nie
    überhaupt eine Login-URL angezeigt) mit einer Permission-Meldung.
    Jetzt wird a) die tatsächliche Ausgabe als Fehlertext durchgereicht
    statt nur des Exit-Codes, und b) bei einer klar permission-artigen
    Meldung EINMALIG automatisch per pkexec erneut versucht -
    _via_pkexec verhindert dabei eine Endlosschleife (kein zweiter
    Auto-Retry mehr, falls auch DAS fehlschlägt)."""
    url_re = re.compile(r"https://login\.tailscale\.com/\S+")

    def _worker():
        cmd = (["pkexec"] if _via_pkexec else []) + ["tailscale", "up"]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as e:
            msg = str(e)
            GLib.idle_add(lambda: (on_finished(msg), False)[1])
            return
        url_found = False
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line.rstrip("\n"))
            m = url_re.search(line)
            if m and not url_found:
                url_found = True
                url = m.group(0)
                GLib.idle_add(lambda u=url: (on_url(u), False)[1])
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        ec = proc.wait()
        if ec == 0:
            GLib.idle_add(lambda: (on_finished(None), False)[1])
            return

        full_output = "\n".join(l for l in output_lines if l.strip()).strip()
        err_l = full_output.lower()
        needs_root = (not _via_pkexec) and any(s in err_l for s in (
            "permission denied", "operation not permitted", "eacces",
            "access denied", "must be root", "need to be root"))
        if needs_root:
            GLib.idle_add(lambda: (_tailscale_login_flow(on_url, on_finished, True), False)[1])
            return
        GLib.idle_add(lambda: (on_finished(full_output or f"exit code {ec}"), False)[1])

    in_thread(_worker)

def _tailscale_logout() -> tuple[bool, str]:
    """Kompletter Logout (im Gegensatz zu 'tailscale down' weiter oben,
    das nur trennt): entfernt die Anmeldedaten dieses Geräts, ein
    erneutes 'Enable Tailscale' braucht danach wieder den kompletten
    Browser-Login-Flow (siehe _tailscale_login_flow())."""
    out, err, ec = run_ec(["tailscale", "logout"], timeout=15)
    if ec != 0:
        return False, err or out
    return True, ""

def _tailscale_prefs() -> dict:
    """Aktuelle Verbindungs-Präferenzen (accept-routes/accept-dns/ssh/
    shields-up) - stehen NICHT in 'tailscale status --json' drin (das
    zeigt nur Verbindungs-/Peer-Status), sondern in 'tailscale debug
    prefs'. Die Feldnamen darin sind interne Tailscale-Struct-Namen und
    könnten sich zwischen Versionen ändern - deshalb überall mit
    .get()-Fallback statt hartem Zugriff, und ein leeres Dict bei jedem
    Fehler (Aufrufer behandelt ein leeres Dict wie "alles unbekannt/
    aus", die eigentlichen Set-Aufrufe unten funktionieren davon
    unabhängig trotzdem, da sie idempotent sind)."""
    out, _err, ec = run_ec(["tailscale", "debug", "prefs"], timeout=5)
    if ec != 0:
        return {}
    try:
        data = json.loads(out)
    except Exception:
        return {}
    return {
        "accept_routes": bool(data.get("RouteAll", False)),
        "accept_dns":    bool(data.get("CorpDNS", True)),
        "ssh":           bool(data.get("RunSSH", False)),
        "shields_up":    bool(data.get("ShieldsUp", False)),
    }

def _tailscale_set_pref(flag: str, value: bool) -> tuple[bool, str]:
    """Setzt GENAU EIN Preference-Flag über 'tailscale set --flag=...'
    - anders als 'tailscale up' braucht das keinen erneuten Login/keine
    Browser-URL, wirkt sofort auf die laufende Verbindung."""
    out, err, ec = run_ec(
        ["tailscale", "set", f"--{flag}={'true' if value else 'false'}"], timeout=15)
    if ec != 0:
        return False, err or out
    return True, ""

def _tailscaled_autostart_enabled() -> bool:
    out, _err, _ec = run_ec(["systemctl", "is-enabled", "tailscaled"], timeout=5)
    return out.strip() == "enabled"

def _set_tailscaled_autostart(enable: bool) -> tuple[bool, str]:
    """Schaltet NUR den Boot-Autostart um (enable/disable), fasst NICHT
    den aktuellen Lauf-/Login-Zustand an (siehe README: "separate from
    the login state") - wer's aus dem Bootvorgang raushaben will, aber
    gerade eingeloggt ist, bleibt eingeloggt, bis er Tailscale manuell
    trennt."""
    return _run_maybe_priv(
        ["systemctl", "enable" if enable else "disable", "tailscaled"], timeout=15)

def _tailscale_content(win: Gtk.Window) -> Gtk.Box:
    """Tailscale-Tab im Security-Widget. Exit-Node-Auswahl ABSICHTLICH
    NICHT enthalten (README: "later, needs explicit opt-in per the
    Tailscale docs" - das ist ein Sicherheits-relevantes Feature, das
    erst noch sein eigenes bewusstes Opt-in-UI braucht, kein einfacher
    Toggle nebenbei)."""
    root = vbox(4); pad(root, h=4, v=6)
    root.pack_start(btitle("󰖂  Tailscale"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    if not _tailscale_available():
        root.pack_start(bitem("tailscale is not installed", dim=True), False, False, 0)
        return root

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 3500):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    conn_lbl = Gtk.Label(label="Checking…")
    conn_lbl.get_style_context().add_class("caption")
    conn_lbl.set_halign(Gtk.Align.CENTER)
    root.pack_start(conn_lbl, False, False, 0)

    ip_row = hbox(6)
    ip_row.set_halign(Gtk.Align.CENTER)
    ip_lbl = Gtk.Label(label="")
    ip_lbl.get_style_context().add_class("caption")
    ip_lbl.set_opacity(0.7)
    ip_row.pack_start(ip_lbl, False, False, 0)
    copy_ip_btn = Gtk.Button(label="󰆏")
    copy_ip_btn.set_relief(Gtk.ReliefStyle.NONE)
    copy_ip_btn.get_style_context().add_class("flat")
    copy_ip_btn.set_opacity(0.7)
    copy_ip_btn.set_tooltip_text("Copy IP to clipboard")
    ip_row.pack_start(copy_ip_btn, False, False, 0)
    ip_row.set_no_show_all(True)
    ip_row.hide()
    root.pack_start(ip_row, False, False, 0)

    login_link_lbl = Gtk.Label(label="")
    login_link_lbl.get_style_context().add_class("caption")
    login_link_lbl.set_selectable(True)
    login_link_lbl.set_line_wrap(True)
    login_link_lbl.set_halign(Gtk.Align.CENTER)
    login_link_lbl.set_justify(Gtk.Justification.CENTER)
    login_link_lbl.set_no_show_all(True)
    login_link_lbl.hide()
    root.pack_start(login_link_lbl, False, False, 0)

    main_btn = btn("Enable Tailscale")
    main_btn.set_halign(Gtk.Align.CENTER)
    root.pack_start(main_btn, False, False, 0)

    disconnect_row = hbox(6)
    disconnect_row.set_halign(Gtk.Align.CENTER)
    disconnect_btn = btn("Disconnect")
    logout_btn = btn("Log out")
    disconnect_row.pack_start(disconnect_btn, False, False, 0)
    disconnect_row.pack_start(logout_btn, False, False, 0)
    disconnect_row.set_no_show_all(True)
    disconnect_row.hide()
    root.pack_start(disconnect_row, False, False, 0)

    # KEIN Trennstrich mehr zwischen Überschrift und "Start on boot" -
    # der einzige, der bleibt, ist der direkt über DEVICES weiter unten
    # (README-Feedback: "die Trennstriche zwischen der Überschrift und
    # Start on boot alle weg, nur den einen über Devices kann da
    # bleiben"). Ein einziger Button (Text = Schalter), zentriert -
    # gleiches Muster wie Privacy/DNS, kein separates Label mehr daneben.
    autostart_row = hbox(8)
    autostart_row.set_halign(Gtk.Align.CENTER)
    autostart_toggle = btn("Start on boot")
    autostart_row.pack_start(autostart_toggle, False, False, 0)
    root.pack_start(autostart_row, False, False, 0)

    # ── Optionen (nur sinnvoll/schaltbar, solange eingeloggt) ────────
    options_section = vbox(3)
    options_section.set_no_show_all(True)
    options_section.hide()
    root.pack_start(options_section, False, False, 0)

    options_section.pack_start(bsec("OPTIONS"), False, False, 0)
    opt_toggles: dict = {}
    _opt_rows = []
    for flag, opt_label, tip in (
        ("accept-routes", "Accept routes",
         "Use routes/subnets that other tailnet devices advertise (e.g. a home NAS or router)."),
        ("accept-dns", "Accept MagicDNS",
         "Use the tailnet's own DNS settings (MagicDNS) instead of this device's normal DNS."),
        ("ssh", "Tailscale SSH",
         "Let other tailnet devices (with permission) SSH into this device over Tailscale."),
        ("shields-up", "Shields up",
         "Block ALL incoming connections from tailnet peers - useful on untrusted networks."),
    ):
        row = hbox(6)
        lbl = Gtk.Label(label=opt_label + ":")
        lbl.get_style_context().add_class("caption")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        toggle = btn("…")
        toggle.set_tooltip_text(tip)
        row.pack_start(lbl, True, True, 0)
        row.pack_start(toggle, False, False, 0)
        opt_toggles[flag] = toggle
        _opt_rows.append(row)

    # 2x2 statt 4 Zeilen untereinander (README-Feedback: "auch im
    # Security Tab kann man viel Platz sparen").
    _opt_grid = Gtk.Grid()
    _opt_grid.set_column_homogeneous(True)
    _opt_grid.set_column_spacing(14)
    _opt_grid.set_row_spacing(2)
    for idx, orow in enumerate(_opt_rows):
        _opt_grid.attach(orow, idx % 2, idx // 2, 1, 1)
    options_section.pack_start(_opt_grid, False, False, 0)

    root.pack_start(sep(), False, False, 4)
    root.pack_start(bsec("DEVICES"), False, False, 0)
    devices_box = vbox(3)
    root.pack_start(devices_box, False, False, 0)

    root.pack_start(status_lbl, False, False, 4)

    _state = {"connecting": False, "self_ip": ""}

    def _refresh_autostart():
        def _work():
            enabled = _tailscaled_autostart_enabled()
            def _apply():
                ctx = autostart_toggle.get_style_context()
                if enabled: ctx.add_class("active")
                else:       ctx.remove_class("active")
            GLib.idle_add(_apply)
        in_thread(_work)

    def _rebuild_devices(peers: list):
        for c in devices_box.get_children():
            devices_box.remove(c)
        if not peers:
            devices_box.pack_start(
                bitem("No other devices in this tailnet", dim=True), False, False, 0)
        for p in peers:
            row = hbox(8)
            row.get_style_context().add_class("bubble")
            row.get_style_context().add_class("item")
            pad(row, h=8, v=4)
            dot = "🟢" if p["online"] else "⚪"
            txt = f'{dot} {p["name"]}' + (f'  ·  {p["ip"]}' if p["ip"] else "")
            lbl = Gtk.Label(label=txt)
            lbl.set_halign(Gtk.Align.START)
            # Kein Ellipsize/Namenslimit - gleicher Fix wie Task-Manager
            # und Firewall-Regeln, aus demselben Grund.
            lbl.set_hexpand(True)
            row.pack_start(lbl, True, True, 0)
            devices_box.pack_start(row, False, False, 0)
        devices_box.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    def _refresh_status():
        def _work():
            data = _tailscale_status()
            def _apply():
                if data.get("error"):
                    conn_lbl.set_label("Not connected")
                    ip_row.hide()
                    login_link_lbl.hide()
                    main_btn.show()
                    main_btn.set_sensitive(not _state["connecting"])
                    disconnect_row.hide()
                    options_section.hide()
                    _rebuild_devices([])
                    return
                if data["logged_in"]:
                    who = f'{_local_username()}@{data["hostname"]}' if data["hostname"] else "?"
                    conn_lbl.set_label(f'Connected as {who}')
                    if data["self_ip"]:
                        _state["self_ip"] = data["self_ip"]
                        ip_lbl.set_label(f'Your IP: {data["self_ip"]}')
                        ip_row.show()
                    else:
                        ip_row.hide()
                    login_link_lbl.hide()
                    main_btn.hide()
                    disconnect_row.show()
                    options_section.show()
                    _refresh_prefs()
                else:
                    conn_lbl.set_label("Not connected")
                    ip_row.hide()
                    main_btn.show()
                    main_btn.set_sensitive(not _state["connecting"])
                    disconnect_row.hide()
                    options_section.hide()
                _rebuild_devices(data.get("peers", []))
                GLib.idle_add(_shrink_to_fit, win)
            GLib.idle_add(_apply)
        in_thread(_work)

    def _on_url(url: str):
        login_link_lbl.set_label(f"Opening browser to sign in:\n{url}")
        login_link_lbl.show()
        GLib.idle_add(_shrink_to_fit, win)

    def _on_login_finished(error):
        _state["connecting"] = False
        main_btn.set_label("Enable Tailscale")
        login_link_lbl.hide()
        if error:
            short = error if len(error) <= 300 else error[:300] + "…"
            _flash(f"Tailscale login failed: {short}", ms=8000)
        _refresh_status()

    def _on_enable(_w):
        if _state["connecting"]:
            return
        _state["connecting"] = True
        main_btn.set_label("Connecting…")
        main_btn.set_sensitive(False)
        _tailscale_login_flow(_on_url, _on_login_finished)

    def _refresh_prefs():
        def _work():
            prefs = _tailscale_prefs()
            def _apply():
                for flag, toggle in opt_toggles.items():
                    key = flag.replace("-", "_")
                    on = bool(prefs.get(key))
                    toggle.set_label("🟢  On" if on else "⚪  Off")
                    ctx = toggle.get_style_context()
                    if on: ctx.add_class("active")
                    else:  ctx.remove_class("active")
            GLib.idle_add(_apply)
        in_thread(_work)

    def _on_copy_ip(_w):
        if not _state["self_ip"]:
            return
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(_state["self_ip"], -1)
        clip.store()
        _flash("IP copied to clipboard", ms=1500)

    def _on_logout(_w):
        def _apply():
            ok, err = _tailscale_logout()
            if not ok:
                raise RuntimeError(err)
        apply_change("Tailscale: log out", _apply, on_status=_flash)
        GLib.timeout_add(700, lambda: (_refresh_status(), False)[1])

    def _make_option_handler(flag: str, toggle: Gtk.Button):
        def _handler(_w):
            key = flag.replace("-", "_")
            cur = _tailscale_prefs().get(key, False)
            new_val = not cur
            def _apply():
                ok, err = _tailscale_set_pref(flag, new_val)
                if not ok:
                    raise RuntimeError(err)
            def _reset():
                _refresh_prefs()
            toggle.set_label("🟢  On" if new_val else "⚪  Off")
            ctx = toggle.get_style_context()
            if new_val: ctx.add_class("active")
            else:       ctx.remove_class("active")
            apply_change(f"Tailscale: {flag} {'on' if new_val else 'off'}",
                         _apply, on_status=_flash, reset_fn=_reset)
        return _handler

    def _on_disconnect(_w):
        def _apply():
            out, err, ec = run_ec(["tailscale", "down"], timeout=15)
            if ec != 0:
                raise RuntimeError(err or out)
        apply_change("Tailscale: disconnect", _apply, on_status=_flash)
        GLib.timeout_add(700, lambda: (_refresh_status(), False)[1])

    def _on_autostart_toggle(_w):
        def _apply():
            ok, err = _set_tailscaled_autostart(not _tailscaled_autostart_enabled())
            if not ok:
                raise RuntimeError(err)
        apply_change("Tailscale autostart", _apply, on_status=_flash,
                     reset_fn=_refresh_autostart)
        GLib.timeout_add(500, lambda: (_refresh_autostart(), False)[1])

    main_btn.connect("clicked", _on_enable)
    disconnect_btn.connect("clicked", _on_disconnect)
    logout_btn.connect("clicked", _on_logout)
    copy_ip_btn.connect("clicked", _on_copy_ip)
    autostart_toggle.connect("clicked", _on_autostart_toggle)
    for flag, toggle in opt_toggles.items():
        toggle.connect("clicked", _make_option_handler(flag, toggle))

    _refresh_status()
    _refresh_autostart()
    # Peers/Online-Status können sich jederzeit von außen ändern (ein
    # anderes Gerät geht on-/offline) - deshalb ein eigener Poll-Timer,
    # nicht nur einmalig beim Öffnen.
    add_timer(4000, lambda: (_refresh_status(), True)[1])

    return root

def _clamav_available() -> bool:
    return shutil.which("clamscan") is not None

_CLAMAV_DB_DIR = Path("/var/lib/clamav")
# Alle Endungen, die ClamAV als Signatur-Datenbank lädt - NICHT nur
# main.cvd/daily.cvd. clamav-unofficial-sigs legt zusätzlich dutzende
# .hdb/.ndb/.yara-Dateien (SecuriteInfo, Sanesecurity, ...) im selben
# Ordner ab, die genauso mitgeladen und mitgezählt werden.
_CLAMAV_DB_EXTENSIONS = (
    ".cvd", ".cld", ".hdb", ".hsb", ".hdu", ".ndb", ".ndu",
    ".ldb", ".ldu", ".yar", ".yara", ".fp", ".pdb", ".gdb",
    ".cbc", ".cdb", ".idb", ".wdb", ".crb",
)

def _clamav_db_status() -> dict:
    """BUGFIX: hat vorher NUR main.cvd/main.cld/daily.cvd/daily.cld
    betrachtet und davon auch nur die EINE zuletzt geänderte Datei -
    'sigtool --info' gibt aber die Signaturzahl NUR für genau die eine
    übergebene Datei zurück, nicht die Gesamtsumme über alle geladenen
    Datenbanken. Je nachdem, welche der 4 Dateien beim letzten
    Freshclam-Lauf zufällig zuletzt angefasst wurde, kam so mal die
    Zahl von daily.cvd (Millionen) und mal die von main.cvd (nur ein
    Bruchteil davon) raus - exakt das beobachtete wilde Schwanken
    zwischen 3,3 Mio. und ~500.000. Zusätzliche Signaturen aus
    clamav-unofficial-sigs (eigene .hdb/.ndb/.yara-Dateien im selben
    Ordner) wurden dabei komplett ignoriert.

    Jetzt: JEDE Datenbankdatei im Ordner einzeln über sigtool abfragen
    und die Signaturzahlen AUFSUMMIEREN - das entspricht dem, was
    clamscan/clamd beim Start tatsächlich alles zusammen lädt.
    "Last updated" ist die neueste mtime über ALLE gefundenen
    Dateien, nicht mehr nur der ursprünglichen 4."""
    if not _CLAMAV_DB_DIR.is_dir():
        return {"last_update": None, "sig_count": None}
    have_sigtool = bool(shutil.which("sigtool"))
    newest_mtime = None
    total_sigs = 0
    got_any_count = False
    try:
        entries = list(_CLAMAV_DB_DIR.iterdir())
    except OSError:
        return {"last_update": None, "sig_count": None}
    for p in entries:
        if p.suffix.lower() not in _CLAMAV_DB_EXTENSIONS:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if newest_mtime is None or mtime > newest_mtime:
            newest_mtime = mtime
        if not have_sigtool:
            continue
        out, _err, ec = run_ec(["sigtool", "--info", str(p)], timeout=10)
        if ec == 0:
            m = re.search(r"Signatures:\s*(\d+)", out)
            if m:
                total_sigs += int(m.group(1))
                got_any_count = True
    return {
        "last_update": datetime.fromtimestamp(newest_mtime) if newest_mtime else None,
        "sig_count": total_sigs if got_any_count else None,
    }

def _freshclam_update() -> tuple[bool, str]:
    """'freshclam' braucht so gut wie immer Root (schreibt nach
    /var/lib/clamav und /var/log/clamav) - Timeout bewusst hoch, ein
    volles Signatur-Update UND ein voller clamav-unofficial-sigs-Lauf
    (siehe unten) können bei langsamer Verbindung zusammen mehrere
    Minuten dauern.

    BUGFIX: lief bisher über _run_maybe_priv(), das erst UNPRIVILEGIERT
    versucht und nur anhand der Fehlermeldung entscheidet, ob auf
    pkexec eskaliert wird ("Permission denied", "must be root", ...).
    freshclams eigene Fehlermeldung bei fehlenden Rechten ("Problem
    with internal logger ... libfreshclam init failed") erwähnt aber
    nirgends root/Rechte - die Heuristik hat das NIE als "braucht root"
    erkannt und NIE eskaliert. Das mkdir -p von vorhin lief die ganze
    Zeit nur als normaler User, der in /var/log/ grundsätzlich nichts
    anlegen darf - der Ordner wurde also nie tatsächlich erstellt, der
    Button hat immer nur unprivilegiert probiert und ist immer mit
    exakt derselben Meldung gescheitert. Deshalb hier jetzt bewusst
    DIREKT über pkexec, ganz ohne den unprivilegierten Versuch davor -
    mkdir läuft dann tatsächlich als root und kann den Ordner wirklich
    anlegen.

    NEU: läuft danach zusätzlich 'clamav-unofficial-sigs.sh' (falls
    installiert - siehe README: "extended with community signatures
    (clamav-unofficial-sigs) for even better detection") IM SELBEN
    pkexec-Aufruf, damit nur EIN Passwort-Prompt für beides nötig ist.
    Mit ';' statt '&&' verkettet, damit ein für ClamAV harmloser,
    nicht-null Exit-Code von freshclam (manche Versionen geben sowas
    zurück, wenn eh schon alles aktuell ist) den unofficial-sigs-Lauf
    nicht verhindert."""
    unofficial_bin = (shutil.which("clamav-unofficial-sigs.sh") or
                       shutil.which("clamav-unofficial-sigs"))
    script = "mkdir -p /var/log/clamav; freshclam"
    if unofficial_bin:
        script += f"; {unofficial_bin}"
    out, err, ec = run_ec(["pkexec", "bash", "-c", script], timeout=600)
    if ec != 0:
        return False, err or out or f"exit code {ec}"
    return True, ""

def _clamav_scan(path: str, on_line, on_done) -> None:
    """Startet 'clamscan -r --bell -i <path>' (GENAU der Befehl aus der
    README) im Hintergrund-Thread, reicht jede Ausgabezeile live über
    on_line() durch und ruft am Ende on_done(threats, error) auf.
    threats ist eine Liste von (dateipfad, signaturname)-Tupeln,
    geparst aus Zeilen der Form '<pfad>: <Signaturname> FOUND'.
    WICHTIG: clamscans Exit-Code 1 bedeutet "Bedrohung(en) gefunden",
    NICHT "Fehler" - nur Exit-Code 2 ist ein echter Scan-Fehler
    (z.B. Pfad nicht lesbar, keine/kaputte Signatur-Datenbank).

    Bugfix: meldete bei Exit-Code 2 bisher nur den nichtssagenden
    Exit-Code selbst ("clamscan exited with code 2"), OBWOHL die
    tatsächliche Fehlerursache die ganze Zeit live über on_line()
    durchlief - die wurde nur nirgends für den Fehlerfall aufgehoben.
    Jetzt werden alle Zeilen mitgeschnitten und die letzten davon (die
    eigentliche Fehlermeldung steht bei clamscan i.d.R. ganz am Ende)
    im Fehlerfall mit durchgereicht, exakt derselbe Fix wie vorhin
    beim Tailscale-Login."""
    found_re = re.compile(r"^(.*): (.+) FOUND$")

    def _worker():
        cmd = ["clamscan", "-r", "--bell", "-i"]
        if os.path.abspath(path) == "/":
            # Voller System-Scan: Pseudo-Dateisysteme raus - die haben
            # keine echten Dateien zum Scannen und würden clamscan nur
            # unnötig lange hängen lassen bzw. mit Permission-Fehlern
            # volllaufen lassen. --exclude-dir nimmt eine PCRE-Regex
            # gegen den vollen Pfad. BEWUSST NICHT /run mit ausschließen
            # (war vorher ein Fehler von mir) - /run/media ist genau da,
            # wo eingehängte externe Laufwerke/USB-Sticks landen, die
            # will man bei einem "vollen System-Scan" ja gerade MIT
            # erfasst haben.
            cmd.append("--exclude-dir=^/(proc|sys|dev)(/|$)")
        cmd.append(path)
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except Exception as e:
            msg = str(e)
            GLib.idle_add(lambda: (on_done([], msg), False)[1])
            return
        threats = []
        output_lines = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            output_lines.append(line)
            if line:
                GLib.idle_add(lambda l=line: (on_line(l), False)[1])
            m = found_re.match(line)
            if m:
                threats.append((m.group(1).strip(), m.group(2).strip()))
        ec = proc.wait()
        if ec in (0, 1):
            error = None
        else:
            tail = "\n".join(l for l in output_lines if l.strip())[-400:]
            error = f"exit code {ec}" + (f": {tail}" if tail else "")
        GLib.idle_add(lambda: (on_done(threats, error), False)[1])

    in_thread(_worker)

# Modul-weiter State (NICHT innerhalb von _clamav_content(), das würde
# bei jedem Fenster-Neubau verloren gehen) - überlebt bewusst das
# Schließen/Neu-Öffnen des Security-Widgets: ein einmal gestarteter
# Scan soll im Hintergrund weiterlaufen, auch wenn niemand gerade
# hinschaut (README-Feedback: "sollte man das Widget schließen können
# und es sollte im Hintergrund weiterlaufen"). "listeners" ist ein
# dict {id(win): (on_line, on_done)} - jedes gerade offene ClamAV-Tab-
# Fenster trägt sich hier ein/aus (siehe _clamav_content()), damit
# Live-Updates NUR an tatsächlich noch existierende Fenster gehen,
# nie an ein inzwischen zerstörtes.
_clamav_scan_state = {
    "running": False, "path": None, "last_line": "",
    "threats": [], "error": None, "listeners": {},
    # Dauerhafter Klartext-Status (im Gegensatz zu status_lbl/_flash(),
    # der nach ein paar Sekunden wieder verschwindet) - README-Feedback:
    # "würd ne permanente Schrift hinpacken, was immer sagt was der
    # letzte Scan ergeben hat ... damit mans nachlesen kann, wenn man
    # nicht aufpasst". Bleibt stehen, bis der NÄCHSTE Scan beginnt oder
    # endet - kein Timer, kein automatisches Verschwinden.
    "summary": "No scan has been run yet.",
}

def _clamav_start_scan(path: str) -> bool:
    """Startet einen neuen Scan, FALLS nicht schon einer läuft (liefert
    in dem Fall False - der Aufrufer soll dann einfach an den bereits
    laufenden andocken statt einen zweiten parallel zu starten,
    _clamav_content() macht das beim Öffnen automatisch über die
    aktuellen _clamav_scan_state-Werte)."""
    if _clamav_scan_state["running"]:
        return False
    _clamav_scan_state.update(
        running=True, path=path, last_line="", threats=[], error=None,
        summary=f"Scan active: {path}")

    def _on_line(line: str):
        _clamav_scan_state["last_line"] = line
        for on_line, _on_done in list(_clamav_scan_state["listeners"].values()):
            try: on_line(line)
            except Exception: pass

    def _on_done(threats: list, error):
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        if error:
            summary = f"[{when}] Scan of {path} FAILED: {error[:250]}"
        elif threats:
            names = "; ".join(f"{fp} ({sig})" for fp, sig in threats[:5])
            more = f"  (+{len(threats) - 5} more)" if len(threats) > 5 else ""
            summary = (f"[{when}] Scan of {path}: {len(threats)} threat(s) "
                       f"found - {names}{more}")
        else:
            summary = f"[{when}] Scan of {path}: no threats found."
        _clamav_scan_state.update(
            running=False, threats=threats, error=error, summary=summary)
        for _on_line, on_done in list(_clamav_scan_state["listeners"].values()):
            try: on_done(threats, error)
            except Exception: pass

    _clamav_scan(path, _on_line, _on_done)
    return True

def _clamav_register_listener(win: Gtk.Window, on_line, on_done) -> None:
    """Trägt DIESES Fensters Callbacks als Zuhörer für den aktuellen
    (ggf. schon laufenden) Scan ein und meldet sie automatisch wieder
    ab, sobald das Fenster zerstört wird - verhindert, dass ein
    Callback später versucht, ein längst nicht mehr existierendes
    GTK-Widget zu aktualisieren."""
    key = id(win)
    _clamav_scan_state["listeners"][key] = (on_line, on_done)
    win.connect("destroy", lambda *_a: _clamav_scan_state["listeners"].pop(key, None))

# Gleiches Muster wie _clamav_scan_state, nur fürs Signatur-Update
# (README-Feedback: "wenn man updated ... und das Widget schließt,
# bricht's ab - das wäre besser, wenn das auch im Hintergrund rennen
# würde") - freshclam + clamav-unofficial-sigs laufen zusammen locker
# mehrere Minuten, das darf nicht an ein offenes Fenster gekoppelt sein.
_clamav_update_state = {
    "running": False, "listeners": {},
    "summary": "No update has been run yet.",
}

def _clamav_start_update() -> bool:
    """Startet 'Update now' modul-weit statt an ein Fenster gebunden -
    läuft weiter, auch wenn das Security-Widget inzwischen zu ist.
    Liefert False, wenn schon eins läuft (Aufrufer dockt dann einfach
    an, siehe _sync_update_ui() in _clamav_content())."""
    if _clamav_update_state["running"]:
        return False
    _clamav_update_state.update(running=True, summary="Update active…")

    def _worker():
        ok, err = _freshclam_update()
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        summary = (f"[{when}] Update failed: {err[:250]}" if not ok else
                   f"[{when}] Update finished.")
        def _finish():
            _clamav_update_state.update(running=False, summary=summary)
            for on_done in list(_clamav_update_state["listeners"].values()):
                try: on_done(ok, None if ok else err)
                except Exception: pass
        GLib.idle_add(_finish)

    in_thread(_worker)
    return True

def _clamav_register_update_listener(win: Gtk.Window, on_done) -> None:
    key = id(win)
    _clamav_update_state["listeners"][key] = on_done
    win.connect("destroy", lambda *_a: _clamav_update_state["listeners"].pop(key, None))

_CLAMAV_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
_CLAMAV_PATH_UNIT = "wb-clamav-downloads.path"
_CLAMAV_SERVICE_UNIT = "wb-clamav-downloads.service"

def _clamav_autoscan_enabled() -> bool:
    out, _err, _ec = run_ec(
        ["systemctl", "--user", "is-enabled", _CLAMAV_PATH_UNIT], timeout=5)
    return out.strip() == "enabled"

def _set_clamav_autoscan(enable: bool, watch_dir: str) -> tuple[bool, str]:
    """Legt bei Aktivierung 2 systemd --user Unit-Dateien an (Path- +
    Service-Unit unter ~/.config/systemd/user/) und (de)aktiviert sie -
    KEIN root nötig, --user-Units leben im eigenen Home-Verzeichnis,
    genau wie jeder andere --user-Dienst.

    VEREINFACHUNG ggü. "echter" Datei-für-Datei-Erkennung (die README
    nennt genau das selbst als 'more work'): die Path-Unit feuert bei
    JEDER Änderung im Ordner (neue Datei, gelöschte Datei, Umbenennung,
    ...) und scannt dann den KOMPLETTEN Ordner neu, nicht nur die eine
    neue Datei - für einen normal gefüllten Downloads-Ordner in der
    Praxis unproblematisch, bei einem SEHR vollen Ordner aber spürbar
    ineffizienter, als ein echter inotify-Watcher pro einzelner neuer
    Datei es wäre (der bräuchte einen eigenen kleinen Python-Daemon
    statt nur zweier Unit-Dateien - deutlich mehr Aufwand für einen
    Nice-to-have)."""
    if not enable:
        run_ec(["systemctl", "--user", "disable", "--now", _CLAMAV_PATH_UNIT], timeout=10)
        return True, ""
    clamscan_bin = shutil.which("clamscan") or "/usr/bin/clamscan"
    try:
        _CLAMAV_UNIT_DIR.mkdir(parents=True, exist_ok=True)
        (_CLAMAV_UNIT_DIR / _CLAMAV_SERVICE_UNIT).write_text(
            "[Unit]\n"
            "Description=ClamAV scan of newly modified files in Downloads\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f'ExecStart={clamscan_bin} -r --bell -i "{watch_dir}"\n')
        (_CLAMAV_UNIT_DIR / _CLAMAV_PATH_UNIT).write_text(
            "[Unit]\n"
            "Description=Watch Downloads for new files (auto ClamAV scan)\n\n"
            "[Path]\n"
            f"PathModified={watch_dir}\n"
            f"Unit={_CLAMAV_SERVICE_UNIT}\n\n"
            "[Install]\n"
            "WantedBy=default.target\n")
    except Exception as e:
        return False, str(e)
    out, err, ec = run_ec(["systemctl", "--user", "daemon-reload"], timeout=10)
    if ec != 0:
        return False, err or out
    out, err, ec = run_ec(
        ["systemctl", "--user", "enable", "--now", _CLAMAV_PATH_UNIT], timeout=10)
    if ec != 0:
        return False, err or out
    return True, ""

_CLAMAV_QUARANTINE_DIR = Path.home() / ".local" / "share" / "wb-daemon" / "clamav-quarantine"
# Trennzeichen zwischen Original-Pfad und laufender Nummer im
# Quarantäne-Dateinamen - ein Zeichen, das in echten Dateipfaden so gut
# wie nie vorkommt, damit sich der Original-Pfad beim Restore wieder
# zuverlässig zurückgewinnen lässt (siehe _clamav_quarantine_list()).
_CLAMAV_Q_SEP = "␟"

def _clamav_quarantine_file(filepath: str) -> tuple[bool, str]:
    """Verschiebt eine als infiziert gemeldete Datei in einen lokalen
    Quarantäne-Ordner statt sie sofort zu löschen - der Name kodiert
    den kompletten Original-Pfad (URL-encoded, damit Slashes nicht mit
    denen im Quarantäne-Ordner selbst kollidieren), damit "Restore"
    später weiß, wohin die Datei zurück soll. shutil.move() statt
    os.rename(), da Original und Quarantäne-Ordner auf unterschiedlichen
    Dateisystemen/Partitionen liegen könnten (os.rename() scheitert
    dann mit "Invalid cross-device link", shutil.move() fängt das ab
    und kopiert+löscht stattdessen)."""
    import urllib.parse
    try:
        _CLAMAV_QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        encoded = urllib.parse.quote(filepath, safe="")
        dest = _CLAMAV_QUARANTINE_DIR / f"{encoded}{_CLAMAV_Q_SEP}{os.path.basename(filepath)}"
        shutil.move(filepath, dest)
    except Exception as e:
        return False, str(e)
    return True, ""

def _clamav_quarantine_list() -> list:
    """Liste aller aktuell in Quarantäne liegenden Dateien:
    [{"quarantine_path": str, "original_path": str}, ...]."""
    import urllib.parse
    out = []
    if not _CLAMAV_QUARANTINE_DIR.is_dir():
        return out
    for p in _CLAMAV_QUARANTINE_DIR.iterdir():
        if _CLAMAV_Q_SEP not in p.name:
            continue
        encoded = p.name.split(_CLAMAV_Q_SEP, 1)[0]
        try:
            original = urllib.parse.unquote(encoded)
        except Exception:
            original = "?"
        out.append({"quarantine_path": str(p), "original_path": original})
    out.sort(key=lambda d: d["original_path"].lower())
    return out

def _clamav_quarantine_restore(quarantine_path: str, original_path: str) -> tuple[bool, str]:
    """Verschiebt eine quarantänisierte Datei zurück an ihren
    ursprünglichen Ort - schlägt bewusst fehl (statt zu überschreiben),
    falls dort inzwischen schon wieder eine Datei mit demselben Namen
    liegt, um niemals stillschweigend etwas zu überschreiben."""
    try:
        if os.path.exists(original_path):
            return False, f"A file already exists at {original_path} - move or rename it first."
        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        shutil.move(quarantine_path, original_path)
    except Exception as e:
        return False, str(e)
    return True, ""

def _clamav_quarantine_delete(quarantine_path: str) -> tuple[bool, str]:
    try:
        os.remove(quarantine_path)
    except Exception as e:
        return False, str(e)
    return True, ""

def _confirm_delete_dialog(parent: Gtk.Window, filepath: str) -> bool:
    """Bestätigungs-Dialog vorm endgültigen Löschen einer als infiziert
    gemeldeten Datei - gleiche Begründung wie bei _confirm_kill_dialog:
    destruktiv, darf nicht an einem einzigen Fehlklick hängen."""
    d = Gtk.MessageDialog(transient_for=parent, modal=True,
                           message_type=Gtk.MessageType.WARNING,
                           buttons=Gtk.ButtonsType.NONE,
                           text="Delete this file?")
    d.set_name("wb-daemon-popup")
    d.set_keep_above(True)
    d.format_secondary_text(filepath)
    d.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                  "Delete", Gtk.ResponseType.OK)
    resp = d.run()
    d.destroy()
    return resp == Gtk.ResponseType.OK

def _clamav_content(win: Gtk.Window) -> Gtk.Box:
    """ClamAV-Tab im Security-Widget - letztes von der README
    geforderte Sub-Panel. Kein Lazy-Loading nötig: der Status-Abruf
    (Datei-mtime + sigtool) und der Auto-Scan-Toggle (systemctl --user)
    brauchen beide KEIN root - nur "Update now" (freshclam) und
    tatsächliches Scannen lösen ggf. einen pkexec-Dialog bzw. echte
    Scan-Arbeit aus, und das jeweils erst auf Knopfdruck, nie beim
    bloßen Öffnen des Tabs."""
    root = vbox(4); pad(root, h=4, v=6)
    root.pack_start(btitle("🛡️  ClamAV"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    if not _clamav_available():
        root.pack_start(bitem("clamscan is not installed", dim=True), False, False, 0)
        return root

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 3500):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    # 4 Sub-Tabs statt 4 mit Trennstrichen getrennter Abschnitte
    # (README-Feedback: "unter ClamAV 4 Tabs ... dann brauchts auch
    # keine Trennstriche mehr") - Database/Scan/Auto-scan/Quarantine.
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    t_db   = vbox(4)
    t_scan = vbox(4)
    t_auto = vbox(4)
    t_quar = vbox(4)

    # ── TAB: Database ─────────────────────────────────────────────
    db_lbl = Gtk.Label(label="Checking…")
    db_lbl.get_style_context().add_class("caption")
    db_lbl.set_halign(Gtk.Align.CENTER)
    db_lbl.set_justify(Gtk.Justification.CENTER)
    db_lbl.set_line_wrap(True)
    t_db.pack_start(db_lbl, False, False, 0)

    update_btn = btn("Update now")
    update_btn.set_halign(Gtk.Align.CENTER)
    update_btn.set_tooltip_text(
        "Runs freshclam, plus clamav-unofficial-sigs if installed "
        "(community signature sources).")
    t_db.pack_start(update_btn, False, False, 0)

    # Dauerhafte Zusammenfassung, übersteht Schließen/Wiederöffnen -
    # gleiches Prinzip wie scan_summary_lbl weiter unten.
    update_summary_lbl = Gtk.Label(label=_clamav_update_state["summary"])
    update_summary_lbl.get_style_context().add_class("caption")
    update_summary_lbl.set_opacity(0.8)
    update_summary_lbl.set_line_wrap(True)
    update_summary_lbl.set_halign(Gtk.Align.CENTER)
    update_summary_lbl.set_justify(Gtk.Justification.CENTER)
    t_db.pack_start(update_summary_lbl, False, False, 0)

    def _refresh_db_status():
        def _work():
            info = _clamav_db_status()
            def _apply():
                when = (info["last_update"].strftime("%Y-%m-%d %H:%M")
                        if info["last_update"] else "unknown")
                sigs = f'{info["sig_count"]:,}' if info["sig_count"] else "unknown"
                db_lbl.set_label(f"Last updated: {when}  ·  Signatures: {sigs}")
            GLib.idle_add(_apply)
        in_thread(_work)

    def _on_update_done(ok: bool, err):
        update_btn.set_sensitive(True)
        update_btn.set_label("Update now")
        update_summary_lbl.set_label(_clamav_update_state["summary"])
        if ok:
            _flash("Update finished.", ms=3500)
            _refresh_db_status()
        else:
            _flash(f"Error: {err}", ms=8000)

    # BUGFIX (README-Feedback: "wenn man updated ... und das Widget
    # schließt, bricht's ab"): lief bisher über apply_change() direkt
    # in DIESEM Fenster - freshclam+unofficial-sigs zusammen können
    # locker mehrere Minuten brauchen, ein geschlossenes Fenster hätte
    # den Hintergrund-Thread zwar technisch weiterlaufen lassen, aber
    # dessen Callback hätte versucht, längst zerstörte Widgets (diesen
    # Button, dieses Label) zu aktualisieren. Läuft jetzt über den
    # MODUL-WEITEN _clamav_update_state (identisches Muster wie beim
    # Scan) - übersteht ein Schließen des Widgets tatsächlich.
    _clamav_register_update_listener(win, _on_update_done)

    def _on_update(_w):
        if _clamav_update_state["running"]:
            return
        update_btn.set_sensitive(False)
        update_btn.set_label("Updating…")
        update_summary_lbl.set_label(_clamav_update_state["summary"])
        _clamav_start_update()
    update_btn.connect("clicked", _on_update)

    def _sync_update_ui():
        update_summary_lbl.set_label(_clamav_update_state["summary"])
        if _clamav_update_state["running"]:
            update_btn.set_sensitive(False)
            update_btn.set_label("Updating…")
    _sync_update_ui()



    # ── TAB: Scan ─────────────────────────────────────────────────
    default_dir = str(Path.home() / "Downloads")
    scan_state = {"path": default_dir}

    path_row = hbox(6)
    path_row.set_halign(Gtk.Align.CENTER)
    path_lbl = Gtk.Label(label=default_dir)
    path_lbl.get_style_context().add_class("caption")
    path_lbl.set_ellipsize(Pango.EllipsizeMode.START)
    browse_btn = Gtk.Button(label="󰉖")
    browse_btn.set_relief(Gtk.ReliefStyle.NONE)
    browse_btn.get_style_context().add_class("flat")
    browse_btn.set_tooltip_text("Choose folder")
    browse_file_btn = Gtk.Button(label="󰈔")
    browse_file_btn.set_relief(Gtk.ReliefStyle.NONE)
    browse_file_btn.get_style_context().add_class("flat")
    browse_file_btn.set_tooltip_text("Choose a single file")
    path_row.pack_start(path_lbl, False, False, 0)
    path_row.pack_start(browse_file_btn, False, False, 0)
    path_row.pack_start(browse_btn, False, False, 0)
    t_scan.pack_start(path_row, False, False, 0)

    def _on_browse(_w):
        dlg = Gtk.FileChooserDialog(
            title="Choose folder to scan", transient_for=win,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        "Select", Gtk.ResponseType.OK)
        if os.path.isdir(scan_state["path"]):
            dlg.set_current_folder(scan_state["path"])
        resp = dlg.run()
        new_path = dlg.get_filename()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and new_path:
            scan_state["path"] = new_path
            path_lbl.set_label(new_path)
    browse_btn.connect("clicked", _on_browse)

    def _on_browse_file(_w):
        # Einzelne Datei scannen (wie ein einzelner VirusTotal-Upload) -
        # clamscan nimmt genauso gut eine einzelne Datei als Argument
        # wie einen Ordner, "-r" ist für eine einzelne Datei einfach
        # ein wirkungsloses No-Op-Flag, kein Sonderfall in
        # _clamav_scan() nötig.
        dlg = Gtk.FileChooserDialog(
            title="Choose a file to scan", transient_for=win,
            action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        "Select", Gtk.ResponseType.OK)
        start_dir = (scan_state["path"] if os.path.isdir(scan_state["path"])
                     else str(Path.home() / "Downloads"))
        dlg.set_current_folder(start_dir)
        resp = dlg.run()
        new_path = dlg.get_filename()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and new_path:
            scan_state["path"] = new_path
            path_lbl.set_label(new_path)
    browse_file_btn.connect("clicked", _on_browse_file)

    # Presets - beantwortet u.a. "kann man das auch wie einen kompletten
    # System-Scanner nutzen": ja, jeder beliebige Ordner geht über
    # "Choose folder", "/" (voller System-Scan) ist hier als Kurzwahl
    # mit dabei (automatischer Ausschluss von /proc,/sys,/dev,/run,
    # siehe _clamav_scan()) - ein voller Scan dauert je nach
    # Datenmenge aber ordentlich, ist also bewusst NICHT der Default.
    preset_row = hbox(6)
    preset_row.set_halign(Gtk.Align.CENTER)
    for plabel, ppath in (("Downloads", str(Path.home() / "Downloads")),
                         ("Home", str(Path.home())),
                         ("Full System (/)", "/")):
        pb = btn(plabel)
        def _on_preset(_w, p=ppath):
            scan_state["path"] = p
            path_lbl.set_label(p)
        pb.connect("clicked", _on_preset)
        preset_row.pack_start(pb, False, False, 0)
    t_scan.pack_start(preset_row, False, False, 0)

    scan_btn = btn("Start scan")
    scan_btn.set_halign(Gtk.Align.CENTER)
    t_scan.pack_start(scan_btn, False, False, 0)

    progress = Gtk.ProgressBar()
    progress.set_halign(Gtk.Align.CENTER)
    progress.set_size_request(220, -1)
    progress.set_no_show_all(True)
    progress.hide()
    t_scan.pack_start(progress, False, False, 0)

    scan_log_lbl = Gtk.Label(label="")
    scan_log_lbl.get_style_context().add_class("caption")
    scan_log_lbl.set_opacity(0.55)
    scan_log_lbl.set_ellipsize(Pango.EllipsizeMode.START)
    scan_log_lbl.set_halign(Gtk.Align.CENTER)
    scan_log_lbl.set_no_show_all(True)
    scan_log_lbl.hide()
    t_scan.pack_start(scan_log_lbl, False, False, 0)

    # Dauerhafte Klartext-Zusammenfassung - bleibt IMMER sichtbar (kein
    # _flash()-Timer), zeigt "Scan active: <pfad>" während des Scans und
    # danach das Ergebnis inkl. eventueller Fehler, bis der nächste Scan
    # das überschreibt. Genau dafür da, dass man z.B. nach einem vollen
    # System-Scan später nachlesen kann, was passiert ist, ohne
    # daneben gesessen zu haben.
    scan_summary_lbl = Gtk.Label(label=_clamav_scan_state["summary"])
    scan_summary_lbl.get_style_context().add_class("caption")
    scan_summary_lbl.set_opacity(0.8)
    scan_summary_lbl.set_line_wrap(True)
    scan_summary_lbl.set_halign(Gtk.Align.CENTER)
    scan_summary_lbl.set_justify(Gtk.Justification.CENTER)
    t_scan.pack_start(scan_summary_lbl, False, False, 0)

    results_box = vbox(3)
    t_scan.pack_start(results_box, False, False, 0)

    _scan_state = {"running": False}

    def _pulse():
        if not _scan_state["running"]:
            return False
        progress.pulse()
        return True

    def _rebuild_results(threats: list):
        for c in results_box.get_children():
            results_box.remove(c)
        if not threats:
            GLib.idle_add(_shrink_to_fit, win)
            return
        results_box.pack_start(bsec("THREATS FOUND"), False, False, 0)
        for filepath, sig in threats:
            row = vbox(4)
            row.get_style_context().add_class("bubble")
            pad(row, h=8, v=6)
            lbl = Gtk.Label(label=f"{filepath}\n{sig}")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_line_wrap(True)
            row.pack_start(lbl, False, False, 0)
            btn_row = hbox(6)
            # "Quarantine" statt "Delete": verschiebt die Datei nur in
            # einen lokalen Ordner (siehe QUARANTINE-Sektion weiter
            # unten), NICHT sofort weg - ein falsch-positiver Fund oder
            # ein Fehlklick ist damit über "Restore" wieder rückgängig
            # zu machen, ein direktes os.remove() wäre das nicht.
            quarantine_btn = btn("Quarantine")
            ignore_btn = btn("Ignore")
            btn_row.pack_start(quarantine_btn, False, False, 0)
            btn_row.pack_start(ignore_btn, False, False, 0)
            row.pack_start(btn_row, False, False, 0)
            results_box.pack_start(row, False, False, 0)

            def _forget_threat(fp=filepath, sig=sig):
                # Muss den GLOBALEN State mitpflegen, nicht nur die
                # lokale UI - sonst würde ein schon ignorierter/
                # quarantänisierter Fund beim nächsten Öffnen des
                # Widgets über _sync_scan_ui() wieder auftauchen, weil
                # _clamav_scan_state["threats"] noch den alten,
                # vollständigen Stand hätte.
                _clamav_scan_state["threats"] = [
                    t for t in _clamav_scan_state["threats"] if t != (fp, sig)]

            def _on_ignore(_w, r=row):
                _forget_threat()
                results_box.remove(r)
                GLib.idle_add(_shrink_to_fit, win)
            def _on_quarantine(_w, r=row, fp=filepath):
                def _apply():
                    ok, err = _clamav_quarantine_file(fp)
                    if not ok:
                        raise RuntimeError(err)
                apply_change(f"Quarantine {fp}", _apply, on_status=_flash)
                def _finish():
                    _forget_threat()
                    if r.get_parent() is not None:
                        results_box.remove(r)
                    _refresh_quarantine()
                    GLib.idle_add(_shrink_to_fit, win)
                GLib.timeout_add(400, lambda: (_finish(), False)[1])
            ignore_btn.connect("clicked", _on_ignore)
            quarantine_btn.connect("clicked", _on_quarantine)
        results_box.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    def _on_scan_line(line: str):
        scan_log_lbl.set_label(line[-90:])
        scan_log_lbl.show()

    def _on_scan_done(threats: list, error):
        _scan_state["running"] = False
        progress.hide()
        scan_log_lbl.hide()
        scan_btn.set_sensitive(True)
        scan_btn.set_label("Start scan")
        scan_summary_lbl.set_label(_clamav_scan_state["summary"])
        if error:
            _flash(f"Scan error: {error}", ms=9000)
        elif not threats:
            _flash("Scan complete - no threats found.")
        else:
            _flash(f"Scan complete - {len(threats)} threat(s) found.", ms=6000)
        _rebuild_results(threats)

    # Bei DIESEM Fenster als Zuhörer eintragen, BEVOR irgendwas
    # gestartet wird - falls schon ein Scan aus einer früheren, seitdem
    # geschlossenen Öffnung des Widgets läuft, bekommt dieses Fenster
    # dessen Live-Updates dann automatisch mit.
    _clamav_register_listener(win, _on_scan_line, _on_scan_done)

    def _sync_scan_ui():
        """Direkt beim Bauen des Tabs mit dem AKTUELLEN globalen Scan-
        Status abgleichen (siehe README-Feedback: Scan soll weiterlaufen
        UND sichtbar bleiben, auch wenn das Widget zwischendurch zu
        war) - deckt 3 Fälle ab: 1) läuft gerade (auch wenn VOR diesem
        Fenster gestartet) -> sofort "Scanning…" zeigen; 2) ist fertig,
        während das Fenster zu war -> Ergebnisse sofort zeigen, keine
        Wartezeit; 3) nichts los -> normaler Ausgangszustand, nichts zu
        tun. scan_summary_lbl wird IMMER auf den aktuellen globalen
        Text gesetzt, unabhängig vom Fall."""
        scan_summary_lbl.set_label(_clamav_scan_state["summary"])
        if _clamav_scan_state["running"]:
            _scan_state["running"] = True
            scan_btn.set_sensitive(False)
            scan_btn.set_label("Scanning…")
            progress.set_fraction(0)
            progress.show()
            GLib.timeout_add(120, _pulse)
            if _clamav_scan_state["path"]:
                scan_state["path"] = _clamav_scan_state["path"]
                path_lbl.set_label(_clamav_scan_state["path"])
            if _clamav_scan_state["last_line"]:
                _on_scan_line(_clamav_scan_state["last_line"])
        elif _clamav_scan_state["threats"] or _clamav_scan_state["error"]:
            _rebuild_results(_clamav_scan_state["threats"])

    def _on_scan(_w):
        if _scan_state["running"] or _clamav_scan_state["running"]:
            return
        path = scan_state["path"]
        if not (os.path.isdir(path) or os.path.isfile(path)):
            _flash(f"'{path}' does not exist.", ms=4000)
            return
        _scan_state["running"] = True
        scan_btn.set_sensitive(False)
        scan_btn.set_label("Scanning…")
        progress.set_fraction(0)
        progress.show()
        # Unbestimmter Fortschritt: clamscan gibt (mit -i) vor dem
        # Abschluss keine verlässliche "X von Y Dateien"-Info her, ohne
        # vorher selbst den ganzen Baum durchzuzählen - ein pulsierender
        # Balken ist hier ehrlicher als eine erfundene Prozentzahl.
        GLib.timeout_add(120, _pulse)
        # _clamav_start_scan() statt direkt _clamav_scan(): läuft über
        # den MODUL-WEITEN State, überlebt also ein Schließen dieses
        # Fensters (siehe _clamav_scan_state weiter oben) - die
        # eigentliche Warnung "läuft schon" wird oben schon per return
        # abgefangen, das False hier kann höchstens durch eine Race
        # Condition zwischen zwei Fenstern gleichzeitig auftreten.
        _clamav_start_scan(path)
        scan_summary_lbl.set_label(_clamav_scan_state["summary"])
    scan_btn.connect("clicked", _on_scan)

    _sync_scan_ui()

    # ── TAB: Auto-scan ────────────────────────────────────────────
    autoscan_row = hbox(8)
    autoscan_row.set_halign(Gtk.Align.CENTER)
    autoscan_lbl = Gtk.Label(label="Auto-scan Downloads:")
    autoscan_lbl.get_style_context().add_class("caption")
    autoscan_toggle = btn("…")
    autoscan_row.pack_start(autoscan_lbl, False, False, 0)
    autoscan_row.pack_start(autoscan_toggle, False, False, 0)
    t_auto.pack_start(autoscan_row, False, False, 0)

    autoscan_note = Gtk.Label(
        label="Re-scans the whole ~/Downloads folder whenever it changes "
              "(new/removed/renamed file) - not a true per-file watcher.")
    autoscan_note.get_style_context().add_class("caption")
    autoscan_note.set_opacity(0.5)
    autoscan_note.set_line_wrap(True)
    autoscan_note.set_halign(Gtk.Align.CENTER)
    autoscan_note.set_justify(Gtk.Justification.CENTER)
    t_auto.pack_start(autoscan_note, False, False, 0)

    def _refresh_autoscan():
        def _work():
            enabled = _clamav_autoscan_enabled()
            def _apply():
                autoscan_toggle.set_label("🟢  On" if enabled else "⚪  Off")
                ctx = autoscan_toggle.get_style_context()
                if enabled: ctx.add_class("active")
                else:       ctx.remove_class("active")
            GLib.idle_add(_apply)
        in_thread(_work)

    def _on_autoscan_toggle(_w):
        new_val = not _clamav_autoscan_enabled()
        def _apply():
            ok, err = _set_clamav_autoscan(new_val, str(Path.home() / "Downloads"))
            if not ok:
                raise RuntimeError(err)
        apply_change(f"Auto-scan Downloads: {'On' if new_val else 'Off'}",
                     _apply, on_status=_flash, reset_fn=_refresh_autoscan)
        GLib.timeout_add(500, lambda: (_refresh_autoscan(), False)[1])
    autoscan_toggle.connect("clicked", _on_autoscan_toggle)

    # ── TAB: Quarantine ───────────────────────────────────────────
    quarantine_box = vbox(3)
    t_quar.pack_start(quarantine_box, False, False, 0)

    def _refresh_quarantine():
        def _work():
            items = _clamav_quarantine_list()
            def _apply():
                for c in quarantine_box.get_children():
                    quarantine_box.remove(c)
                if not items:
                    quarantine_box.pack_start(
                        bitem("Nothing in quarantine", dim=True), False, False, 0)
                for item in items:
                    row = vbox(2)
                    row.get_style_context().add_class("bubble")
                    pad(row, h=8, v=6)
                    lbl = Gtk.Label(label=item["original_path"])
                    lbl.set_halign(Gtk.Align.CENTER)
                    lbl.set_justify(Gtk.Justification.CENTER)
                    lbl.set_line_wrap(True)
                    row.pack_start(lbl, False, False, 0)
                    btn_row = hbox(6)
                    btn_row.set_halign(Gtk.Align.CENTER)
                    restore_btn = btn("Restore")
                    delete_btn = btn("Delete permanently")
                    btn_row.pack_start(restore_btn, False, False, 0)
                    btn_row.pack_start(delete_btn, False, False, 0)
                    row.pack_start(btn_row, False, False, 0)
                    quarantine_box.pack_start(row, False, False, 0)

                    def _on_restore(_w, qp=item["quarantine_path"],
                                     op=item["original_path"]):
                        def _apply2():
                            ok, err = _clamav_quarantine_restore(qp, op)
                            if not ok:
                                raise RuntimeError(err)
                        apply_change(f"Restore {op}", _apply2, on_status=_flash)
                        GLib.timeout_add(400, lambda: (_refresh_quarantine(), False)[1])
                    def _on_delete_perm(_w, qp=item["quarantine_path"],
                                         op=item["original_path"]):
                        if not _confirm_delete_dialog(win, op):
                            return
                        def _apply2():
                            ok, err = _clamav_quarantine_delete(qp)
                            if not ok:
                                raise RuntimeError(err)
                        apply_change(f"Delete {op}", _apply2, on_status=_flash)
                        GLib.timeout_add(400, lambda: (_refresh_quarantine(), False)[1])
                    restore_btn.connect("clicked", _on_restore)
                    delete_btn.connect("clicked", _on_delete_perm)
                quarantine_box.show_all()
                GLib.idle_add(_shrink_to_fit, win)
            GLib.idle_add(_apply)
        in_thread(_work)

    # ── 4 Tabs zusammensetzen ─────────────────────────────────────
    stack.add_named(t_db, "database")
    stack.add_named(t_scan, "scan")
    stack.add_named(t_auto, "autoscan")
    stack.add_named(t_quar, "quarantine")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch_clamav_tab(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for tname, tlabel in (("database", "Database"), ("scan", "Scan"),
                          ("autoscan", "Auto-scan"), ("quarantine", "Quarantine")):
        tb = btn(tlabel, active=(tname == "database"))
        tb.connect("clicked", lambda _b, n=tname: _switch_clamav_tab(n))
        tab_btns[tname] = tb
        tab_row.pack_start(tb, False, False, 0)
    stack.set_visible_child_name("database")

    root.pack_start(tab_row, True, False, 2)
    root.pack_start(tab_sep(), False, False, 0)
    root.pack_start(stack, False, False, 0)
    root.pack_start(status_lbl, False, False, 4)

    _refresh_db_status()
    _refresh_autoscan()
    _refresh_quarantine()

    return root

def _security_content(win: Gtk.Window) -> Gtk.Box:
    """Tab-Hülle fürs Security-Widget - alle 5 README-Sub-Panels: 
    "Privacy" (Kill-Switches) + "DNS" (Server-Auswahl + Enforce-DoT +
    Guest-WiFi) + "Tailscale" + "Firewall" (UFW) + "ClamAV" (Signatur-
    Update, On-Demand-Scan, Auto-Scan-Toggle), als Gtk.Stack wie bei
    Volume/Battery/Appearance.

    UFW-Tab ist LAZY (wie der Processes-Tab beim Battery-Widget) -
    NICHT weil er einen eigenen Poll-Timer bräuchte (hat er nicht,
    siehe _ufw_content()-Docstring), sondern weil sein allererster
    Status-Abruf selbst schon einen Polkit-Passwort-Dialog auslösen
    kann (ufw braucht für praktisch alles Root) - der soll nicht
    einfach beim Öffnen des Widgets ungefragt aufpoppen, nur weil der
    Privacy-Tab (der KEINE Root-Rechte braucht) initial sichtbar ist.
    ClamAV braucht dasselbe NICHT (Status-Lesen + Auto-Scan-Toggle sind
    root-frei, siehe _clamav_content()-Docstring), ist also wie DNS/
    Tailscale eager gebaut."""
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)
    stack.add_named(_privacy_content(win), "privacy")
    stack.add_named(_dns_content(win), "dns")
    stack.add_named(_tailscale_content(win), "tailscale")
    stack.add_named(_clamav_content(win), "clamav")

    ufw_built = [False]

    def _ensure_ufw_tab():
        if ufw_built[0]:
            return
        ufw_built[0] = True
        # Gleicher Grund wie beim Processes-Tab: add_timer() (falls ein
        # künftiger UFW-Refresh mal einen Timer braucht) registriert
        # nur gegen _current_win[0].
        _current_win[0] = win
        try:
            stack.add_named(_ufw_content(win), "ufw")
        finally:
            _current_win[0] = None
        stack.show_all()

    # 2 Zeilen statt 1 lange (README-Feedback: "die ersten 2 Tabs über
    # den anderen 3, damit Platz gespart wird") - eine durchgehend lange
    # Tab-Reihe mit 5 Einträgen hätte entweder das Fenster unnötig
    # breit gemacht oder wäre auf schmaleren Bildschirmen umgebrochen.
    tab_row_top = hbox(6)
    tab_row_top.set_halign(Gtk.Align.CENTER)
    tab_row_bottom = hbox(6)
    tab_row_bottom.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        if name == "ufw":
            _ensure_ufw_tab()
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, tlabel, target_row in (
            ("privacy", "󰦝  Privacy", tab_row_top),
            ("dns", "󰙲  DNS", tab_row_top),
            ("tailscale", "󰖂  Tailscale", tab_row_bottom),
            ("ufw", "󰈸  Firewall", tab_row_bottom),
            ("clamav", "🛡️  ClamAV", tab_row_bottom)):
        b = btn(tlabel, active=(name == "privacy"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        target_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("privacy")

    outer = vbox(4); safe_pad(outer, 380)
    outer.pack_start(tab_row_top, True, False, 2)
    outer.pack_start(tab_row_bottom, True, False, 0)
    outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack, False, False, 0)
    return outer

def build_security(win: Gtk.Window):
    win.set_default_size(380, 1)
    win.add(_security_content(win))

def _build_settings_security(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_security_content(win), True, True, 0)

SETTINGS_BUILDERS = {
    "display":    _build_settings_display,
    "brightness": _build_settings_brightness,
    "audio":      _build_settings_audio,
    "network":    _build_settings_network,
    "bluetooth":  _build_settings_bluetooth,
    "battery":    _build_settings_battery,
    "calendar":   _build_settings_calendar,
    "appearance": _build_settings_appearance,
    "security":   _build_settings_security,
}

def build_settings(win: Gtk.Window):
    # Etwas breiter als vorher (380->420): das macht die Blase runder
    # statt einem sehr hohen, schmalen Oval, das oben/unten stark
    # zuläuft - dadurch bleiben Titel und Apply-Leiste innerhalb des
    # sichtbaren Blasenrands.
    win.set_default_size(420, 1)
    outer = vbox(0)

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    # NICHT homogen: sonst bleibt das Fenster für IMMER auf der Höhe
    # der größten je besuchten Kategorie (z.B. Bluetooth mit vielen
    # Geräten) aufgebläht - auch danach wieder im Hub oder einer viel
    # kleineren Kategorie wie Display. Genau das war der Grund, warum
    # es "noch viel schlimmer" wurde, sobald man Unterseiten geöffnet
    # hatte.
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    _reused_widget_categories = {"network", "battery", "audio", "bluetooth",
                                  "calendar", "brightness"}
    _cat_info = {ck: (icon, lbl, desc) for ck, icon, lbl, desc in SETTINGS_CATEGORIES}
    _built_pages: set = set()

    def _open_category(cat_key: str):
        if cat_key not in _built_pages:
            _built_pages.add(cat_key)
            icon, cat_label, cat_desc = _cat_info[cat_key]
            page = vbox(4); safe_pad_edge(page, 420, top=True, bottom=False)
            if cat_key not in _reused_widget_categories:
                page.pack_start(btitle(f"{icon}  {cat_label}"), False, False, 0)
                page.pack_start(sep(), False, False, 2)
            # WICHTIG: _current_win muss HIER, unmittelbar um den
            # Builder-Aufruf, gesetzt sein - nicht nur beim initialen
            # build_settings(win) in toggle_widget(). Diese Seiten
            # werden erst lazy gebaut, wenn der Nutzer die Kategorie
            # anklickt - zu dem Zeitpunkt ist toggle_widget() längst
            # durchgelaufen und hat _current_win[0] schon auf None
            # zurückgesetzt. Jeder add_timer()-Aufruf innerhalb eines
            # SETTINGS_BUILDERS-Eintrags (z.B. _akku_content() ->
            # add_timer(10000, _refresh_bat) fürs Battery-Tab) landete
            # dadurch NIE in _timers_by_win[win] - beim Schließen des
            # Fensters räumte _cleanup() diese Timer folglich nie ab.
            # Das war der "unsterbliche Hintergrund-Schleifen"-Leak:
            # jeder Klick auf eine wiederverwendete Kategorie
            # (Battery/Audio/Netzwerk/Bluetooth/Kalender/Brightness)
            # hat einen neuen, nie mehr abräumbaren Timer erzeugt.
            _current_win[0] = win
            try:
                SETTINGS_BUILDERS.get(cat_key, _build_settings_placeholder)(
                    page, cat_key, cat_label, win)
            finally:
                _current_win[0] = None
            page.show_all()
            stack.add_named(page, cat_key)
        _switch_stack(stack, win, cat_key)

    hub = vbox(2); safe_pad_edge(hub, 420, top=True, bottom=False)
    hub.set_valign(Gtk.Align.START)
    hub_title = btitle("󰒓  Settings")
    hub_title.get_style_context().add_class("compact-title")
    hub.pack_start(hub_title, False, False, 0)
    hub.pack_start(sep(), False, False, 0)

    # Dynamische Sortierung: Kategorien mit einem Widget, das gerade
    # in der Waybar (modules-left/-center/-right) auftaucht, landen im
    # "In Waybar"-Tab, alle anderen (z.B. Display, Appearance & Apps,
    # die kein eigenes Waybar-Modul haben) im "Other"-Tab.
    _active_wb_names = _waybar_active_widget_names()
    _in_waybar_cats: list = []
    _other_cats: list = []
    for cat_key, icon, cat_label, cat_desc in SETTINGS_CATEGORIES:
        (_in_waybar_cats if _category_in_waybar(cat_key, _active_wb_names)
         else _other_cats).append((cat_key, icon, cat_label, cat_desc))

    def _build_cat_list(cats: list) -> Gtk.Box:
        box = vbox(2)
        box.set_valign(Gtk.Align.START)
        for cat_key, icon, cat_label, cat_desc in cats:
            box.pack_start(
                _settings_category_row(
                    icon, cat_label, cat_desc,
                    lambda _b, k=cat_key: _open_category(k)),
                False, False, 0)
        if not cats:
            box.pack_start(bitem("Nothing here", dim=True), False, False, 0)
        return box

    hub_stack = Gtk.Stack()
    hub_stack.set_valign(Gtk.Align.START)
    hub_stack.set_transition_type(Gtk.StackTransitionType.NONE)
    hub_stack.set_hhomogeneous(False)
    hub_stack.set_vhomogeneous(False)
    hub_stack.add_named(_build_cat_list(_other_cats),     "other")
    hub_stack.add_named(_build_cat_list(_in_waybar_cats), "in_waybar")
    hub_stack.set_visible_child_name("other")

    hub_tab_row = hbox(6)
    hub_tab_row.set_halign(Gtk.Align.CENTER)
    hub_tab_btns: dict = {}
    def _switch_hub_tab(name):
        hub_stack.set_visible_child_name(name)
        # War hier bisher NICHT dabei (anders als bei jedem anderen
        # Tab-Wechsel im ganzen Daemon, siehe _switch_stack()) - genau
        # das war der gemeldete Bug: von "Other" auf "In Waybar"
        # wechseln (oder umgekehrt) hat das Fenster nie wieder auf die
        # für den jetzt sichtbaren Tab tatsächlich nötige Höhe
        # zurückschrumpfen lassen, es blieb auf der Höhe des zuletzt
        # besuchten (evtl. größeren) Tabs stehen.
        GLib.idle_add(_shrink_to_fit, win)
        for n, b in hub_tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    # "Other" zuerst: das sind genau die Kategorien OHNE eigenes
    # Waybar-Icon (Display, Appearance & Language, Apps & Editor) -
    # die erreicht man sonst nirgendwo direkt, im Gegensatz zu den
    # "In Waybar"-Kategorien, die man normalerweise eh per Klick auf
    # ihr eigenes Waybar-Icon öffnet.
    for name, label in (("other", "󰇘  Other"), ("in_waybar", "󱂩  In Waybar")):
        b = btn(label, active=(name == "other"))
        b.connect("clicked", lambda _b, n=name: _switch_hub_tab(n))
        hub_tab_btns[name] = b
        hub_tab_row.pack_start(b, False, False, 0)

    hub.pack_start(hub_tab_row, False, False, 2)
    hub.pack_start(tab_sep(), False, False, 0)
    hub.pack_start(hub_stack, False, False, 0)
    stack.add_named(hub, "hub")

    # Kein Apply/Discard mehr: jede Einstellung wird sofort beim
    # Auswählen übernommen (siehe apply_change()) - das Settings-Fenster
    # besteht daher nur noch aus dem Stack selbst, mit dem üblichen
    # unteren "safe"-Randabstand statt einer eigenen Leiste darunter.
    safe_pad_edge(stack, 420, top=False, bottom=True)
    outer.pack_start(stack, True, True, 0)

    win.add(outer)

# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════
BUILDERS = {
    "volume":     build_volume,
    "network":    build_network,
    "bluetooth":  build_bluetooth,
    "brightness": build_brightness,
    "akku":       build_akku,
    "clock":      build_clock,
    "settings":   build_settings,
    "security":   build_security,
}

# ════════════════════════════════════════════════════════════
#  Unix Socket Server
# ════════════════════════════════════════════════════════════
import socket

SOCK_PATH = os.environ.get("WB_DAEMON_SOCK", "/tmp/wb-daemon.sock")

def _diag_report() -> str:
    """Eingebaute Selbstdiagnose: soll beim nächsten Auftreten des
    100%-CPU-Problems SOFORT zeigen, ob heimlich noch Fenster/Timer im
    Hintergrund laufen, ohne dass wir nochmal manuell strace/py-spy
    durchgehen müssen. Aufrufbar z.B. per
    `echo diag | socat - UNIX-CONNECT:/tmp/wb-daemon.sock`.

    Kernidee: _open und _timers_by_win SOLLTEN exakt übereinstimmen mit
    dem, was GTK selbst als offene Top-Level-Fenster kennt
    (Gtk.Window.list_toplevels()). Klaffen diese auseinander, ist genau
    das der "unsichtbares Fenster hängt noch im Hintergrund"-Leck, den
    wir zuvor nur indirekt per py-spy vermuten konnten.
    """
    lines = []
    lines.append(f"open widgets (_open):        {sorted(_open.keys()) or '(keine)'}")

    total_timers = sum(len(v) for v in _timers_by_win.values())
    lines.append(f"tracked timers total:         {total_timers}")
    for win, tids in _timers_by_win.items():
        wname = next((n for n, w in _open.items() if w is win), "???")
        lines.append(f"  '{wname}': {len(tids)} timer(s), ids={tids}")

    try:
        toplevels = Gtk.Window.list_toplevels()
        visible = [w for w in toplevels if w.get_visible()]
        tracked = set(_open.values())
        untracked = [w for w in toplevels if w not in tracked]
        lines.append(f"GTK toplevels total:          {len(toplevels)} (visible: {len(visible)})")
        if untracked:
            lines.append(f"⚠ UNTRACKED toplevels (nicht in _open!): {len(untracked)}")
            for w in untracked:
                try:
                    title = w.get_title()
                except Exception:
                    title = "?"
                lines.append(f"    - title={title!r} visible={w.get_visible()}")
        else:
            lines.append("no untracked toplevels — kein Fenster-Leck erkennbar")
    except Exception as e:
        lines.append(f"(konnte GTK-Toplevels nicht auflisten: {e})")

    try:
        qsize = _THREAD_POOL._work_queue.qsize()
        nthreads = len(_THREAD_POOL._threads)
        lines.append(f"thread pool: {nthreads} worker thread(s), {qsize} queued task(s)")
    except Exception as e:
        lines.append(f"(konnte Thread-Pool-Status nicht lesen: {e})")

    try:
        import psutil
        p = psutil.Process()
        lines.append(f"process: {p.num_threads()} OS thread(s), "
                      f"{p.cpu_percent(interval=0.2):.1f}% CPU")
    except Exception as e:
        lines.append(f"(konnte Prozess-Info nicht lesen: {e})")

    return "\n".join(lines)

def _on_client_readable(conn, _cond):
    try:
        data = conn.recv(256)
        if data:
            name = data.decode("utf-8", "ignore").strip()
            if name in ("diag", "--diag"):
                result = _diag_report()
                try: conn.sendall((result + "\n").encode())
                except Exception: pass
            elif name:
                result = toggle_widget(name)
                try: conn.sendall((result + "\n").encode())
                except Exception: pass
    except Exception:
        pass
    finally:
        try: conn.close()
        except Exception: pass
    return False

def _on_socket_readable(server_sock, _cond):
    try:
        conn, _ = server_sock.accept()
        conn.setblocking(False)
        GLib.io_add_watch(conn, GLib.IO_IN | GLib.IO_HUP,
                           lambda c, cond: _on_client_readable(c, cond))
    except Exception:
        pass
    return True

def _start_socket_server() -> socket.socket:
    if os.path.exists(SOCK_PATH):
        os.unlink(SOCK_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    srv.listen(8)
    srv.setblocking(False)
    GLib.io_add_watch(srv, GLib.IO_IN,
                       lambda s, cond: _on_socket_readable(s, cond))
    return srv

def _shutdown(*_):
    _close_all()
    try: os.unlink(SOCK_PATH)
    except Exception: pass
    Gtk.main_quit()
    return False

def _prewarm_tools() -> None:
    for cmd in (
        ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
        ["playerctl", "metadata", "--format", "{{status}}"],
        ["pactl", "--format=json", "list", "sinks"],
        ["nmcli", "-t", "-f", "IN-USE,SSID", "dev", "wifi", "list"],
        ["bluetoothctl", "show"],
        ["brightnessctl", "get"],
    ):
        try:
            run(cmd, timeout=5)
        except Exception:
            pass
    try:
        _ppd_proxy()  # baut die System-Bus-Verbindung schon beim Start auf
    except Exception:
        pass

def _reconcile_theme_state() -> None:
    """Einmalig beim Daemon-Start: gleicht die Kvantum-Config (und
    damit Qt/Kvantum-Apps) auf das an, was laut Gtk.Settings/
    settings.ini GERADE TATSÄCHLICH aktiv ist (siehe _is_dark_mode).
    Grund: settings.ini kann schon länger auf 'dark=1' stehen, obwohl
    NIE über dieses Widget umgeschaltet wurde (z.B. weil das der
    Ausgangs-Default war) - Kvantum-Config stünde dann weiter auf
    ihrem Light-Fallback-Default, und Qt-Apps liefen sichtbar
    inkonsistent zu GTK-Apps, direkt ab dem ersten Systemstart. Rein
    best-effort: ein Fehlschlag hier darf den Daemon-Start nicht
    verhindern, darum wird nur geloggt statt geraised."""
    try:
        want_dark = _is_dark_mode()
        if _kvantum_current_theme() != (KVANTUM_DARK if want_dark else KVANTUM_LIGHT):
            ok, err = _set_dark_mode(want_dark)
            if not ok:
                print(f"⚠ Theme-Reconcile beim Start fehlgeschlagen: {err}",
                      file=sys.stderr)
    except Exception as e:
        print(f"⚠ Theme-Reconcile beim Start fehlgeschlagen: {e}", file=sys.stderr)

def main():
    load_css()
    _reconcile_theme_state()
    _start_socket_server()
    in_thread(_prewarm_tools)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT,  _shutdown)
    print(f"widgets_daemon: ready, listening on {SOCK_PATH}", file=sys.stderr)
    Gtk.main()

# ════════════════════════════════════════════════════════════
#  CLI Weather Options
# ════════════════════════════════════════════════════════════
def _cli_set_weather(query: str) -> int:
    results = _geocode(query)
    if not results:
        print(f"No results found for '{query}'.", file=sys.stderr)
        return 1
    if len(results) > 1:
        print(f"Multiple results for '{query}', please specify or choose a number:", file=sys.stderr)
        for i, res in enumerate(results, 1):
            admin   = res.get("admin1", "")
            country = res.get("country", "")
            print(f"  {i}. {res['name']} ({admin}, {country}) "
                  f"— lat={res['latitude']}, lon={res['longitude']}",
                  file=sys.stderr)
        print("\nEither specify more precisely, e.g. "
              '"--set-weather \\"City, Region\\"" ,'
              " or set coordinates directly with:\n"
              "  WidgetsDaemon.py --set-weather-coords <lat> <lon> \"<Name>\"",
              file=sys.stderr)
        return 1
    res = results[0]
    _save_weather_location(res["latitude"], res["longitude"], res["name"])
    print(f"Weather location set: {res['name']} "
          f"(lat={res['latitude']}, lon={res['longitude']})")
    print(f"Saved in {WEATHER_CONF}")
    return 0

def _cli_show_weather_location() -> int:
    loc = _load_weather_location()
    print(f"Current weather location: {loc.get('name', '?')} "
          f"(lat={loc['lat']}, lon={loc['lon']})")
    print(f"Config file: {WEATHER_CONF}")
    return 0

def _cli_diag() -> int:
    """Verbindet sich mit dem laufenden Daemon über dessen Unix-Socket
    und fragt den Selbstdiagnose-Report ab (siehe _diag_report()). So
    lässt sich beim nächsten "100% CPU"-Verdacht sofort prüfen, ob
    heimlich noch Fenster/Timer offen sind, ohne socat/py-spy/strace:

        python3 WidgetsDaemon.py --diag
    """
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(SOCK_PATH)
        s.sendall(b"diag")
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        s.close()
    except Exception as e:
        print(f"Konnte keine Verbindung zum Daemon herstellen ({SOCK_PATH}): {e}",
              file=sys.stderr)
        print("Läuft der Daemon? (systemctl --user status wb-daemon.service)",
              file=sys.stderr)
        return 1
    print(b"".join(chunks).decode("utf-8", "ignore"))
    return 0

def _print_cli_usage() -> None:
    print(
        "WidgetsDaemon.py [--set-weather \"<Location>\" | "
        "--set-weather-coords <lat> <lon> \"<Name>\" | "
        "--show-weather | --diag]\n"
        "Without arguments: starts the daemon (typically via systemd --user wb-daemon.service).",
        file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--diag":
        sys.exit(_cli_diag())
    elif len(sys.argv) > 1 and sys.argv[1] == "--set-weather":
        if len(sys.argv) < 3:
            _print_cli_usage()
            sys.exit(1)
        sys.exit(_cli_set_weather(" ".join(sys.argv[2:])))
    elif len(sys.argv) > 1 and sys.argv[1] == "--set-weather-coords":
        if len(sys.argv) < 5:
            _print_cli_usage()
            sys.exit(1)
        try:
            _lat, _lon = float(sys.argv[2]), float(sys.argv[3])
        except ValueError:
            print("lat/lon must be numbers, e.g. 47.0707 15.4395",
                  file=sys.stderr)
            sys.exit(1)
        _name = " ".join(sys.argv[4:])
        _save_weather_location(_lat, _lon, _name)
        print(f"Weather location set: {_name} (lat={_lat}, lon={_lon})")
        print(f"Saved in {WEATHER_CONF}")
        sys.exit(0)
    elif len(sys.argv) > 1 and sys.argv[1] in ("--show-weather", "--weather-status"):
        sys.exit(_cli_show_weather_location())
    elif len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        _print_cli_usage()
        sys.exit(0)
    main()
