#!/usr/bin/env python3
"""
WidgetsDaemon.py — TrafkTux Waybar Widget System (Daemon)
Invocation: python3 WidgetsDaemon.py
Controlled via client: WidgetsClient.py <widget>
Widgets: volume | network | bluetooth | brightness | akku | clock | settings | security
"""

import gi, sys, os, re, signal, subprocess, json, threading, time, calendar, shutil, traceback
import random, math, glob, stat, tempfile, configparser
from datetime import datetime, date
from pathlib import Path

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf, Gio, GObject

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

# Ordnerstruktur von Wallpapers.sh: ~/.config/hypr/Wallpapers/<ratio>/,
# Ratio-Keys 11/1610/169/219/329/43 (siehe Wallpapers.sh-Kommentar) -
# für den neuen Wallpapers-Tab (Appearance & Language) wird hier
# derselbe Ordner rekursiv gescannt, damit dort exakt dieselben Bilder
# auftauchen, die auch beim Zufalls-Wallpaper zur Auswahl stehen.
WALLPAPER_DIR = f"{HOME}/.config/hypr/Wallpapers"
_WALLPAPER_EXTS = (".jpg", ".jpeg", ".png", ".webp")

def _scan_wallpaper_images() -> list[str]:
    """Rein lesendes os.walk() über lokale Dateien - schnell genug für
    einen synchronen Aufruf. Das eigentliche Preview-Rendering (siehe
    _build_appearance_wallpapers_tab) läuft trotzdem in einem eigenen
    Thread, da GdkPixbuf.Pixbuf.new_from_file_at_scale() bei vielen
    bzw. großen Bildern durchaus spürbar dauern kann und den GTK-
    Main-Thread sonst blockieren würde."""
    if not os.path.isdir(WALLPAPER_DIR):
        return []
    out = []
    for root, _dirs, files in os.walk(WALLPAPER_DIR):
        for f in files:
            if f.lower().endswith(_WALLPAPER_EXTS):
                out.append(os.path.join(root, f))
    return sorted(out)

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

/* FIX ("vieler Text ist noch immer schwarz statt weiß-gelb, wenn das
   GTK-Theme auf Light steht"): jedes Label OHNE eigene color-Angabe
   (z.B. reine .caption-only-Labels, oder sonstige bare Gtk.Label-
   Instanzen ohne .bubble-Klasse) hatte bisher GAR KEINE eigene
   color-Property und übernahm damit stillschweigend GTKs Theme-
   Default-Textfarbe - unter einem hellen (Light) GTK-Theme ist das
   naturgemäß schwarz/dunkelgrau statt der hier gewollten TEXT_NORMAL-
   Farbe. Bewusst als simpler ELEMENT-Selektor (Spezifität 0,0,1) ganz
   am Anfang des Stylesheets platziert: ".bubble" (color: GOLD),
   "button.bubble"/".bubble.dropdown" (color: TEXT_NORMAL) und alle
   anderen spezifischeren Klassen-Regeln weiter unten haben höhere
   CSS-Spezifität (mind. 0,1,0) und überschreiben diese Basis-Regel
   wie gehabt - hier wird NUR der bisher komplett ungesetzte Fall
   (kein .bubble, keine andere color-Regel) auf TEXT_NORMAL gelegt. */
label {{
    color: {TEXT_NORMAL};
}}

/* GTK-Themes setzen auf "button" oft eine eigene Mindesthöhe für
   Touch-Bedienbarkeit (z.B. 34px) - die hat bisher JEDEN button.bubble
   im Programm unsichtbar aufgebläht, unabhängig vom eigenen
   padding/margin. War der eigentliche Grund für den riesigen Abstand
   zwischen Sektions-Buttons (z.B. "SCREEN: 100%") und dem Slider
   direkt darunter - kein Layout-/Spacing-Problem, sondern schlicht ein
   viel zu hoher, unsichtbarer Button selbst.

   min-height: 0 auf "button" ALLEIN reicht aber nicht: das Theme setzt
   ZUSÄTZLICH Padding auf den inneren Knoten (button-box/label/image
   zwischen dem <button>-Rand und dem eigentlichen Text) - genau DAS
   blieb bisher aktiv und blähte die Hitbox trotzdem weiter auf, auch
   nachdem der äußere Button selbst schon auf 0 stand (das war der
   eigentliche, bis zuletzt ungefundene Rest-Abstand zwischen Label und
   Slider). Beides jetzt explizit zurückgesetzt - außen UND am inneren
   Knoten -, alle spezifischeren Klassen weiter unten (.bubble.section,
   .bubble.slider, button.bubble usw.) haben höhere Spezifität und
   setzen ihr eigenes gewolltes Padding danach gezielt wieder. */
button, button.text-button, button.image-button, button.toggle,
button.flat {{
    min-height: 0;
    min-width: 0;
    padding: 0;
    margin: 0;
    border: none;
    outline: none;
    box-shadow: none;
    background: none;
    background-image: none;
}}
button > box, button > label, button > image {{
    min-height: 0;
    min-width: 0;
    padding: 0;
    margin: 0;
    border: none;
}}
button:hover, button:active, button:checked, button:focus,
button:focus-visible {{
    box-shadow: none;
    outline: none;
    border: none;
}}

/* Gleiches Prinzip für die Scale-Knoten (Slider) - trough/highlight/
   slider/value könnten vom Theme ebenfalls eigenes Padding/Margin
   bekommen, das den Regler unnötig aufbläht. scale{{}} unten (Zeile mit
   min-height: 15px) setzt danach gezielt die gewollte Reglerhöhe. */
scale, scale contents, scale trough, scale highlight, scale slider,
scale value {{
    padding: 0;
    margin: 0;
    border: none;
    outline: none;
    box-shadow: none;
    background-image: none;
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
    font-size: 19px;
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

/* NEU: eigener, großer Font-Grad NUR für die Uhr-Anzeige im neuen
   dedizierten "Clock"-Haupttab (Redesign-Liste: "Das groß mittig die
   Uhr und direkt darunter das Datum") - der alte .clock-digits-Fund
   oben bleibt unverändert (nutzt weiterhin die kleinere .bubble.title-
   Größe), nur der neue Tab bekommt diese deutlich größere Variante. */
.clock-digits-huge {{
    font-family: "Noto Sans", sans-serif;
    font-size: 52px;
    font-weight: bold;
    letter-spacing: 1px;
}}

.bubble.section {{
    padding: 3px 16px;
    margin: 6px 0px 0px 0px;
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

/* App-Editor Such-Eingabefeld (Launcher-Tab, "Unsorted"/"All Apps") -
   getippter Text in GOLD statt Standard-Textfarbe. */
entry.applauncher-search, entry.applauncher-search text {{
    color: {GOLD};
}}

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
    margin: 0px 0px;
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
/* NUR für den "Dark Theme"-Umschalter in Appearance & Language (Look-
   Tab): wenn Dark-Mode aktiv ist, ein eigener lila Glow statt des
   normalen goldenen - Redesign-Vorgabe "wenn dark auf die Farbe
   #9C81CF mit #7554B3 Glow, wenn light der normale Glow". 3 Klassen
   ((0,3,0)) schlagen die 2 Klassen von button.bubble.active
   ((0,2,0)) gezielt NUR hier, ohne jeden anderen aktiven Button in
   der App zu beeinflussen. */
button.bubble.active.theme-glow-dark {{
    color: #9C81CF;
    text-shadow: 0 0 4px #7554B3, 0 0 10px #7554B3;
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

/* NUR für den Settings-Hub-Titel ("Settings"-Überschrift im Haupt-
   Einstellungsmenü) - Redesign-Vorgabe: "kein dünner Strich mehr,
   sondern ein fetterer als bei den Tabs, Abstand verringern, Über-
   schrift soll fast auf dem Strich stehen". Bewusst NOCH kräftiger
   als .tab-divider oben (3px statt 2px, mehr Deckkraft) und mit
   deutlich knapperem Rand zur Überschrift hin. */
separator.hub-divider {{
    background-color: rgba(255,244,149,0.9);
    min-height: 3px;
    margin: 1px 10px 6px 10px;
}}

/* NUR für den "Connected as ..."-Link oben im Tailscale-Tab -
   Redesign-Vorgabe: "sollte viel größer sein und leuchten". */
.tailscale-conn-big {{
    font-size: 20px;
    font-weight: bold;
    color: {GOLD};
    text-shadow: 0 0 4px {GOLD}, 0 0 10px {GOLD};
}}
/* NUR für "Start on boot" im Tailscale-Tab - Redesign-Vorgabe "start
   on boot bissl kleiner machen". */
button.bubble.compact-btn {{
    font-size: 12px;
    padding: 4px 12px;
}}
scrollbar slider {{
    background-color: rgba(255,244,149,0.3);
    border-radius: 2px;
    min-width: 3px;
    min-height: 20px;
}}

/* ── Theme-unabhängige Overrides ────────────────────────────────────
   Das Fenster hat immer denselben dunklen Cairo-Blob als Hintergrund,
   egal ob GTK im Dark- oder Light-Mode ist. Alle Widgets, bei denen
   GTK-Light-Mode sonst eigene helle Hintergründe / dunkle Texte
   einschleust (GtkEntry, GtkComboBoxText-Popup, GtkNotebook-Tabs,
   GtkTreeView) werden hier explizit in unserer Farb-Welt gehalten.
   Das ist der Fix für „im Light-Mode sind viele Texte weiß/unleserlich"
   – die Texte SOLLEN immer gold/cremefarben bleiben. */

/* Entries (Custom-Res/Hz-Felder) */
entry, entry text {{
    background: rgba(255,244,149,0.07);
    color: {GOLD};
    caret-color: {GOLD};
    border: 1px solid rgba(255,244,149,0.25);
    border-radius: 6px;
    padding: 2px 8px;
    box-shadow: none;
}}
entry:focus, entry text:focus {{
    border-color: rgba(255,244,149,0.6);
    background: rgba(255,244,149,0.12);
}}

/* ComboBoxText – die ausklappbare Liste (GtkMenu/GtkTreeView drin) */
combobox button {{
    background: rgba(255,244,149,0.07);
    color: {GOLD};
    border: 1px solid rgba(255,244,149,0.25);
    border-radius: 6px;
    padding: 2px 8px;
    min-height: 0;
}}
combobox button:hover, combobox button:active {{
    background: rgba(255,244,149,0.15);
    color: {GOLD};
}}
combobox button arrow {{
    color: {GOLD};
    min-width: 12px;
    min-height: 12px;
}}
/* Popup-Menü des ComboBox */
menu, menu menuitem {{
    background-color: #1a1535;
    color: {GOLD};
    border: none;
    box-shadow: 0 4px 24px rgba(0,0,0,0.6);
}}
menu menuitem:hover, menu menuitem:selected {{
    background-color: rgba(255,244,149,0.15);
    color: {GOLD};
}}

/* Notebook-Tabs (Sub-Tabs innerhalb Settings) – damit Tab-Labels
   im Light-Mode nicht plötzlich schwarz auf hellem Grund stehen */
notebook > header {{
    background: none;
    border: none;
    box-shadow: none;
}}
notebook > header tab {{
    background: none;
    color: {TEXT_NORMAL};
    border: none;
    padding: 4px 12px;
    margin: 0;
    min-height: 0;
}}
notebook > header tab:checked, notebook > header tab:hover {{
    background: none;
    color: {GOLD};
    box-shadow: none;
}}
notebook > header tabs indicator {{
    background-color: {GOLD};
    min-height: 2px;
}}

/* TreeView / ListView (Prozessliste etc.) */
treeview, treeview.view {{
    background-color: transparent;
    color: {GOLD};
}}
treeview:selected, treeview.view:selected {{
    background-color: rgba(255,244,149,0.15);
    color: {GOLD};
}}
treeview header button {{
    background: none;
    color: {TEXT_NORMAL};
    border: none;
    border-bottom: 1px solid rgba(255,244,149,0.2);
    border-radius: 0;
    padding: 3px 8px;
    font-weight: bold;
    letter-spacing: 1px;
    font-size: 11px;
}}
treeview header button:hover {{
    color: {GOLD};
}}

/* Tooltip immer dunkel */
tooltip {{
    background-color: #1a1535;
    color: {GOLD};
    border: 1px solid rgba(255,244,149,0.25);
    border-radius: 6px;
}}
tooltip label {{
    color: {GOLD};
    padding: 2px 6px;
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
        print(f"WARNING: Blasenbild konnte nicht geladen werden ({BUBBLE_PATH}): {e}", file=sys.stderr)
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
        print(f"WARNING: Overlay-Bild konnte nicht geladen werden ({OVERLAY_PATH}): {e}", file=sys.stderr)
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

def _draw_particles(ctx, state: dict, w: int, h: int, now: float) -> None:
    """Physik-Update + Zeichnen der frei fliegenden Gold-Pünktchen.
    Ausgelagert aus _draw_window(), damit der Ruhezustand-Pfad (siehe
    dort, Analyse Punkt 6a) und der Animations-Pfad exakt denselben
    Code nutzen - identische Gradienten/Größe/Geschwindigkeit/
    Bewegungsmuster in beiden Fällen, keinerlei optische Änderung."""
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
        # BUGFIX (vom Nutzer gemeldet: "Fenster taucht beim Schließen
        # nochmal kurz auf"): hier IMMER True, auch sobald t_close >= 1.
        # Grund: der "Ruhezustand"-Schnellpfad weiter unten (if not
        # animating: ...) kennt KEIN scale/tx/ty - er zeichnet immer
        # die VOLLE, unskalierte Blase. Wenn man ihn hier (fälschlich,
        # mein Fehler) auch nach Ende der Schließen-Animation
        # anspringen lässt, blitzt für einen Frame nochmal die komplette
        # Blase in voller Größe auf, bevor der Cleanup-Timer das Fenster
        # zerstört. Richtig ist: der Schließen-Pfad bleibt IMMER im
        # skalierten (animating) Zweig - der behandelt das Ende über
        # "scale < 0.02 -> nichts zeichnen" bereits korrekt.
        animating = True
    else:
        t_pop = (now - state["popup_start"]) / (_POPUP_MS / 1000.0)
        p_pop = _ease_out_elastic(t_pop)
        # _ease_out_elastic() klemmt t intern auf [0,1] -> sobald
        # t_pop >= 1 ist p_pop dauerhaft exakt 1.0 (kein Nachschwingen
        # mehr danach). Für t_pop < 1 läuft noch die eigentliche
        # Bounce-Animation (inkl. kurzem Überschwingen über 1.0). Der
        # Ruhezustand-Schnellpfad (siehe oben) ist NUR hier zulässig,
        # weil scale in diesem Zweig nach Ende der Animation garantiert
        # 1.0 ist (nicht 0.0 wie beim Schließen) - voll ausgewachsene,
        # unskalierte Blase IST hier der korrekte Dauerzustand.
        animating = t_pop < 1.0

    scale = max(0.0, p_pop)

    # FIX (Analyse Punkt 6a - Performance ohne jede optische
    # Änderung): im eingeschwungenen Ruhezustand (nicht am Öffnen/
    # Schließen gerade beteiligt) ist scale hier IMMER exakt 1.0,
    # tx/ty wären also 0 - push_group()/translate(0,0)/scale(1,1)/
    # pop_group_to_source() ist in diesem Fall eine reine
    # Identitätstransformation, die visuell exakt dasselbe Ergebnis
    # liefert wie direktes Zeichnen in ctx, aber JEDEN der alle 33ms
    # laufenden Frames (siehe _amb_tid in make_win()) eine komplette
    # Offscreen-Surface anlegt und kompositiert, obendrein inklusive
    # eines manuellen zweiten propagate_draw() des kompletten
    # Kind-Baums. Hintergrund, Pünktchen (exakt dieselbe
    # _draw_particles()-Funktion, identische Gradienten/Größe/
    # Geschwindigkeit) und Overlay werden hier direkt in ctx gemalt,
    # die Kind-Widgets überlässt GTK seiner eigenen, ohnehin
    # effizienteren Draw-Pipeline (return False).
    if not animating:
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        _paint_bubble_bg(ctx, w, h)
        _draw_particles(ctx, state, w, h, now)
        # WICHTIG (Reihenfolge): TrafkBubble1.png muss weiterhin ÜBER
        # den Kind-Widgets liegen (siehe _paint_bubble_overlay()-
        # Docstring) - dafür hier wie im Animations-Pfad die Kinder
        # selbst per propagate_draw() VOR dem Overlay zeichnen, statt
        # einfach False zurückzugeben (das würde GTKs Default-Handler
        # die Kinder erst NACH diesem Aufruf malen lassen, also unter
        # dem Overlay - sichtbarer Unterschied zum bisherigen
        # Verhalten). push_group()/pop_group_to_source() ist dafür
        # nicht nötig: ohne Skalierung/Verschiebung (scale ist hier
        # ohnehin 1.0) reicht direktes Malen in ctx, um dasselbe
        # Schichtbild zu erzeugen, nur ohne die teure Offscreen-Surface.
        child = win.get_child()
        if child is not None:
            win.propagate_draw(child, ctx)
        _paint_bubble_overlay(ctx, w, h)
        return True

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

    # Nur während der ~_POPUP_MS Popup-/Close-Animation der bisherige,
    # teurere Pfad über eine transformierte Offscreen-Gruppe - hier
    # IST die Transformation sichtbar (scale != 1.0), push_group() also
    # tatsächlich nötig, um Hintergrund + Pünktchen + Kind-Widgets
    # gemeinsam zu skalieren/verschieben.
    ctx.push_group()
    ctx.translate(tx, ty)
    ctx.scale(scale, scale)

    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    _paint_bubble_bg(ctx, w, h)
    _draw_particles(ctx, state, w, h, now)

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
                print(f"WARNING: _cleanup für Widget '{name}' fehlgeschlagen: {e}", file=sys.stderr)
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
            print(f"WARNING: _cleanup für Widget '{name}' fehlgeschlagen: {e}", file=sys.stderr)
    else:
        # Sollte nie vorkommen (make_win registriert IMMER einen
        # Eintrag, bevor ein Fenster in _open landen kann) - Fallback
        # nur zur Sicherheit, damit das Fenster wenigstens verschwindet.
        try: win.destroy()
        except Exception as e:
            print(f"WARNING: win.destroy() für Widget '{name}' fehlgeschlagen: {e}", file=sys.stderr)

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

def hub_sep() -> Gtk.Separator:
    """NOCH kräftigerer Trennstrich NUR für den Settings-Hub-Titel
    (siehe separator.hub-divider in der CSS) - Redesign-Vorgabe "ein
    fetterer als bei den Tabs"."""
    s = Gtk.Separator()
    s.get_style_context().add_class("hub-divider")
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
    (Rotation und Hz nutzen das mittlerweile beide NICHT mehr - Rotation
    ist eine Gtk.ComboBoxText geworden (siehe rot_combo in
    _build_monitor_row()), Hz ebenso (siehe hz_combo dort) - diese
    Klasse wird aktuell für den Monitor-Ziel-Wähler im Wallpapers-Tab
    genutzt, siehe target_ctrl in _build_appearance_wallpapers_tab().)

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
    # ALLGEMEIN: Slider sollen NICHT per Mausrad verstellbar sein.
    # `lambda *_: True` reicht NICHT — GtkRange verarbeitet scroll-event
    # im C-Level-Default-Handler, der trotz `return True` vom User-Handler
    # weiter läuft. GLib.signal_stop_emission_by_name() bricht dagegen
    # die komplette Signal-Emission inkl. Default-Handler ab.
    def _block_scroll_on_slider(widget, _event):
        widget.stop_emission_by_name("scroll-event")
        return True
    s.connect("scroll-event", _block_scroll_on_slider)
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
        t2.pack_start(hub_sep(), False, False, 2)
        for s in _get_sinks():
            row = _build_device_row(s, "sink", s["name"] == default_sink,
                                    _refresh_devices)
            row.set_halign(Gtk.Align.CENTER)
            t2.pack_start(row, False, False, 0)
        default_source = _default_source_name()
        t2.pack_start(bsec("INPUT"), False, False, 4)
        t2.pack_start(hub_sep(), False, False, 2)
        for s in _get_sources():
            row = _build_device_row(s, "source", s["name"] == default_source,
                                    _refresh_devices)
            row.set_halign(Gtk.Align.CENTER)
            t2.pack_start(row, False, False, 0)
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
    """Eine Zeile pro SSID. Mehrere Access Points mit gleichem Namen
    werden zusammengeführt: aktiv gewinnt immer, sonst das stärkste
    Signal. rsplit() schneidet SECURITY und SIGNAL rechts ab, damit
    escapte Doppelpunkte (\\:) in SSIDs nicht stören."""
    out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
               "dev", "wifi", "list"])
    best = {}
    for line in out.splitlines():
        try:
            head, sig_s, sec = line.rsplit(":", 2)
            in_use, ssid = head.split(":", 1)
        except ValueError:
            continue
        ssid = ssid.replace("\\:", ":")
        if not ssid:
            continue
        try: sig = int(sig_s)
        except ValueError: sig = 0
        sec = sec.strip()
        active = in_use.strip() == "*"
        cur = best.get(ssid)
        if cur is None:
            best[ssid] = {"active": active, "ssid": ssid, "signal": sig,
                          "secure": bool(sec),
                          "enterprise": "802.1x" in sec.lower()}
        else:
            cur["active"] = cur["active"] or active
            cur["signal"] = max(cur["signal"], sig)
    nets = sorted(best.values(), key=lambda n: n["signal"], reverse=True)
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

def _eap_dialog(parent: Gtk.Window, ssid: str) -> dict | None:
    """Benutzername+Passwort+EAP-Methode für WPA2/WPA3-Enterprise-
    (802.1X-)Netzwerke - genau das Feld, das bisher komplett fehlte
    (siehe _pw_dialog() oben, die nur ein einzelnes Passwort-Feld
    kennt). PEAP/MSCHAPv2 ist voreingestellt, weil das mit großem
    Abstand die häufigste Kombination bei Schul-/Uni-/Firmen-RADIUS-
    Servern ist (dieselbe Standard-Kombi, die Windows/Android/iOS-
    Verbindungsassistenten defaultmäßig vorschlagen) - TTLS/TLS/FAST
    stehen als Alternative zur Auswahl, falls PEAP bei einem
    bestimmten Netzwerk nicht klappt."""
    dlg = Gtk.Dialog(title=f"Enterprise Wi-Fi: {ssid}", transient_for=parent)
    dlg.set_name("wb-daemon-popup")
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                    "Connect", Gtk.ResponseType.OK)
    area = dlg.get_content_area()
    area.pack_start(Gtk.Label(
        label="This network needs your personal login (802.1X), "
              "not just a shared Wi-Fi password."),
        False, False, 4)

    e_user = Gtk.Entry()
    e_user.set_placeholder_text("Username")
    area.pack_start(e_user, True, True, 4)

    e_pw = Gtk.Entry()
    e_pw.set_visibility(False)
    e_pw.set_placeholder_text("Password")
    e_pw.set_activates_default(True)
    e_pw.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
    area.pack_start(e_pw, True, True, 4)

    eap_row = hrow(sp=6)
    eap_row.pack_start(Gtk.Label(label="EAP method:"), False, False, 0)
    eap_combo = Gtk.ComboBoxText()
    eap_combo.get_style_context().add_class("bubble")
    eap_combo.get_style_context().add_class("dropdown")
    for m in ("PEAP", "TTLS", "TLS", "FAST"):
        eap_combo.append_text(m)
    eap_combo.set_active(0)
    eap_row.pack_start(eap_combo, False, False, 0)
    area.pack_start(eap_row, False, False, 4)

    dlg.show_all()
    resp = dlg.run()
    result = None
    if resp == Gtk.ResponseType.OK:
        result = {
            "username": e_user.get_text(),
            "password": e_pw.get_text(),
            "eap": (eap_combo.get_active_text() or "peap").lower(),
        }
    dlg.destroy()
    return result

def _check_and_open_captive_portal(on_done=None) -> None:
    """Fragt NetworkManager nach dem Verbindungsstatus (eigener Check,
    nicht über DNS/HTTP, daher kein Fehlalarm auf Netzen, die HTTP
    blockieren). Bei 'portal' oder 'limited' wird der Gast-Modus fürs
    Profil aktiviert (Router-DNS erlaubt, DoT pro Link aus) und der
    Browser auf eine reine HTTP-Seite geöffnet, damit das Portal greift."""
    state = run(["nmcli", "networking", "connectivity", "check"],
                timeout=15).strip().lower()
    portal = state in ("portal", "limited")
    if portal:
        conn = _active_connection_name()
        if conn and not _guest_wifi_active(conn):
            _set_guest_wifi(conn, True)
        for cmd in (["xdg-open", "http://neverssl.com"],
                    [os.environ.get("BROWSER", "xdg-open"), "http://neverssl.com"]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                break
            except Exception:
                continue
    if on_done:
        GLib.idle_add(on_done, portal)

def _wifi_connect_psk(ssid: str, password: str, dev: str | None) -> tuple[bool, str]:
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    if dev:
        cmd += ["ifname", dev]
    out, err, rc = run_ec(cmd, timeout=20)
    return rc == 0, (err or out)

def _wifi_connect_enterprise(ssid: str, creds: dict, dev: str | None) -> tuple[bool, str]:
    """802.1X-Verbindung. Das bestehende Profil bleibt erhalten, bis das
    neue erfolgreich aktiviert ist (vorher wurde es zuerst gelöscht, bei
    einem falschen Passwort war dann nichts mehr da). password-flags 0
    speichert das Passwort im Profil, sonst fragt NM über einen Agenten
    nach, den das Widget nicht hat."""
    tmp = f"{ssid}__tmp"
    run_ec(["nmcli", "connection", "delete", tmp], timeout=10)
    add_cmd = [
        "nmcli", "connection", "add", "type", "wifi", "con-name", tmp,
        "ssid", ssid,
        "wifi-sec.key-mgmt", "wpa-eap",
        "802-1x.eap", creds["eap"],
        "802-1x.identity", creds["username"],
        "802-1x.password", creds["password"],
        "802-1x.password-flags", "0",
        "connection.autoconnect", "yes",
    ]
    if creds["eap"] in ("peap", "ttls"):
        add_cmd += ["802-1x.phase2-auth", "mschapv2"]
    if dev:
        add_cmd += ["ifname", dev]
    out, err, rc = run_ec(add_cmd, timeout=15)
    if rc != 0:
        return False, err or out
    out2, err2, rc2 = run_ec(["nmcli", "connection", "up", tmp], timeout=25)
    if rc2 != 0:
        run_ec(["nmcli", "connection", "delete", tmp], timeout=10)
        return False, err2 or out2
    run_ec(["nmcli", "connection", "delete", ssid], timeout=10)
    run_ec(["nmcli", "connection", "modify", tmp, "connection.id", ssid], timeout=10)
    return True, ""

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
    pkexec für diesen Teil - NetworkManager erlaubt einem angemeldeten
    User per Polkit standardmäßig, seine EIGENEN Verbindungsprofile zu
    ändern (exakt dieselbe Berechtigungslage wie beim bestehenden
    _set_dns() oben).

    FIX (gemeldet: Captive-Portal-Login in Schul-/Gäste-WLANs zeigt
    GAR NICHTS an, weder Login-Seite noch sonst was lädt): ignore-
    auto-dns allein reicht NICHT. Ist "Enforce DNS over TLS" global
    aktiv (DNSOverTLS=yes in /etc/systemd/resolved.conf - und das ist
    hier der Default, siehe _refresh_dot()), gilt das für JEDEN Link,
    auch für diesen hier - selbst wenn jetzt brav der Router-eigene
    DNS-Server benutzt wird (ignore-auto-dns=no), verlangt
    systemd-resolved von GENAU DIESEM Server trotzdem zwingend DNS-
    over-TLS. Schul-/Hotel-/Flughafen-Router-DNS kann so gut wie nie
    DoT - die Namensauflösung über diesen Link schlägt dann KOMPLETT
    fehl, nicht nur die Captive-Portal-Erkennung. Genau das war der
    Bug: nicht "Login-Seite wird nicht erkannt", sondern "DNS geht für
    dieses Netzwerk überhaupt nicht mehr". Fix: zusätzlich ein
    PER-LINK-Override setzen (resolvectl dnsovertls <iface> no/...) -
    nur für dieses eine Interface, zur Laufzeit, OHNE die globale
    resolved.conf-Einstellung anzutasten (andere Links/Netzwerke
    bleiben weiter voll verschlüsselt). systemd-resolved erlaubt das
    per Polkit normalerweise auch ohne root für die aktive Sitzung -
    _run_maybe_priv() eskaliert automatisch auf pkexec, falls ein
    System das doch anders konfiguriert hat."""
    val = "no" if enable else "yes"
    out, err, ec = run_ec(["nmcli", "connection", "modify", conn_name,
                            "ipv4.ignore-auto-dns", val,
                            "ipv6.ignore-auto-dns", val], timeout=10)
    if ec != 0:
        return False, err or out
    out2, err2, ec2 = run_ec(["nmcli", "connection", "up", conn_name], timeout=15)
    if ec2 != 0:
        return False, err2 or out2

    iface = run(["nmcli", "-g", "GENERAL.DEVICES",
                 "connection", "show", conn_name]).strip()
    if iface and shutil.which("resolvectl"):
        # Beim Ausschalten zurück auf den gerade geltenden GLOBALEN
        # Modus (yes/opportunistic) - nicht hart auf "yes", falls der
        # Nutzer Enforce DoT inzwischen selbst auf opportunistic
        # gestellt hat.
        dot_val = "no" if enable else (_dns_over_tls_status() or "yes")
        ok, err3 = _run_maybe_priv(["resolvectl", "dnsovertls", iface, dot_val], timeout=15)
        if not ok:
            # DNS/Verbindung selbst stehen trotzdem schon - das hier
            # nur als Hinweis zurückgeben, kein harter Fehlschlag der
            # ganzen Aktion.
            return True, (f"Guest WiFi set, but per-link DoT override failed "
                           f"({err3}) - DNS over TLS may still block this network.")
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
    root = vbox(4); pad(root, h=4, v=2)
    # Redesign-Liste: "Keine Überschrift. Nur den Trennstrich unter
    # Encryption stehen lassen, den darüber nicht. Abstand oben
    # entfernen/verringern." - btitle()+sep() oben sind weg, top-
    # Padding von 6 auf 2 verringert; der sep() direkt unter der
    # Encryption-Zeile (siehe "root.pack_start(sep(), ...)" nach
    # dot_row weiter unten) bleibt unverändert stehen.

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
                if err:
                    # ok=True, aber mit Hinweistext (z.B. der Fallback-
                    # resolvectl-Aufruf in _set_guest_wifi() schlug
                    # fehl) - bewusst trotzdem als Fehler hochreichen,
                    # statt den Hinweis stillschweigend zu verschlucken:
                    # ein Nutzer, der denkt "Guest WiFi ist an" während
                    # DNS over TLS den Router-DNS insgeheim weiter
                    # blockiert, ist schlechter dran als einer, der
                    # einfach nochmal klicken muss.
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
            def _mk(ssid, secure, enterprise, active):
                def _cb(_):
                    if active:
                        def _disconnect():
                            dev = _wifi_dev_name()
                            if dev:
                                run(["nmcli", "dev", "disconnect", dev])
                            GLib.idle_add(_do_load)
                        in_thread(_disconnect)
                    elif enterprise:
                        # FIX: Schul-/Firmen-WLANs (z.B. "HTL ...")
                        # sind so gut wie immer WPA2/WPA3-Enterprise
                        # (802.1X) - brauchen Benutzername UND
                        # Passwort, nicht nur ein gemeinsames WLAN-
                        # Passwort. Siehe _eap_dialog()/
                        # _wifi_connect_enterprise() weiter oben.
                        creds = _eap_dialog(win, ssid)
                        if creds is None or not creds["username"]:
                            return
                        def _connect():
                            dev = _wifi_dev_name()
                            ok, err = _wifi_connect_enterprise(ssid, creds, dev)
                            if not ok:
                                GLib.idle_add(_show_connect_error, err)
                            else:
                                _check_and_open_captive_portal()
                            GLib.idle_add(_do_load)
                        in_thread(_connect)
                    else:
                        pw = _pw_dialog(win, ssid) if secure else ""
                        if pw is None: return
                        def _connect():
                            dev = _wifi_dev_name()
                            ok, err = _wifi_connect_psk(ssid, pw, dev)
                            if not ok:
                                GLib.idle_add(_show_connect_error, err)
                            else:
                                # FIX (gemeldet: "sollte eigentlich auf
                                # ne Login-Seite weiterleiten") - nach
                                # jeder erfolgreichen Verbindung kurz
                                # prüfen, ob ein Captive Portal (Gäste-/
                                # Hotel-/Flughafen-WLAN) im Weg hängt,
                                # und falls ja automatisch den Browser
                                # auf dessen Login-Seite öffnen.
                                _check_and_open_captive_portal()
                            GLib.idle_add(_do_load)
                        in_thread(_connect)
                return _cb
            b.connect("clicked", _mk(n["ssid"], n["secure"], n["enterprise"], n["active"]))
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

    root.pack_start(btitle("Bluetooth"), False, False, 0)
    root.pack_start(hub_sep(), False, False, 0)

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

def _internal_panel_available() -> bool:
    """brightnessctl ohne -d steuert das Default-Gerät der Klasse
    'backlight' - existiert keins (z.B. Desktop-PC ohne eingebautes
    Panel), liefert 'brightnessctl max' 0 oder einen Fehler."""
    try:
        return int(run(["brightnessctl", "max"]) or 0) > 0
    except Exception:
        return False

def _ddcutil_available() -> bool:
    return shutil.which("ddcutil") is not None

def _ddcutil_displays() -> list[dict]:
    """Externe Monitore mit DDC/CI-Unterstützung, via 'ddcutil detect'.
    NICHT jeder Monitor/jedes Kabel unterstützt DDC/CI (v.a. manche
    USB-C-Docks/KVMs blockieren das) - taucht ein Monitor hier nicht
    auf, findet ddcutil ihn schlicht nicht, kein Fehlerfall. ACHTUNG:
    dieser Aufruf tastet den I2C-Bus ab und kann pro Anzeige gut eine
    halbe bis mehrere Sekunden dauern - IMMER via in_thread() aufrufen,
    NIE direkt im GTK-Main-Thread (siehe _load_monitor_brightness())."""
    if not _ddcutil_available():
        return []
    out = run(["ddcutil", "detect", "--brief"], timeout=15)
    displays: list[dict] = []
    cur: dict | None = None
    for line in (out or "").splitlines():
        line = line.strip()
        m = re.match(r'Display\s+(\d+)', line)
        if m:
            if cur:
                displays.append(cur)
            cur = {"display": int(m.group(1)), "model": ""}
            continue
        if cur is not None:
            mm = re.match(r'Model:\s*(.+)', line)
            if mm:
                cur["model"] = mm.group(1).strip()
    if cur:
        displays.append(cur)
    return displays

def _ddcutil_get_brightness(display: int) -> int:
    """VCP-Code 0x10 = Helligkeit (Standard-DDC/CI-Feature-Code, siehe
    MCCS-Spezifikation) - '--brief' liefert eine einzeilige Ausgabe im
    Format 'VCP 10 C <aktuell> <max>', dritter Wert ist der aktuelle
    Rohwert (praktisch immer bereits 0-100 bei Helligkeit)."""
    out = run(["ddcutil", "--display", str(display), "getvcp", "10",
               "--brief"], timeout=8)
    parts = (out or "").split()
    try:
        idx = parts.index("10")
        return int(parts[idx + 2])
    except (ValueError, IndexError):
        return 50

def _ddcutil_set_brightness(display: int, value: int) -> None:
    run(["ddcutil", "--display", str(display), "setvcp", "10", str(value)],
        timeout=8)

def _brightness_devices() -> list[dict]:
    """Alle steuerbaren Bildschirm-Helligkeiten in EINER Liste: das
    interne Panel (immer über brightnessctl, DDC/CI gibt's dafür
    nicht) + jeder per ddcutil erkannte externe Monitor. Rein lesende
    Erkennung (ddcutil detect + brightnessctl max) - läuft im Aufrufer
    IMMER per in_thread(), da ddcutil-Bus-Polling spürbar dauern kann
    (siehe _ddcutil_displays()-Docstring). Analog zu _get_sinks() im
    Audio-Widget: liefert eine einfache Liste von Dicts, die
    _build_monitor_brightness_row() dann in Zeilen umsetzt (gleiches
    Muster wie _build_device_row() für Audiogeräte)."""
    devices: list[dict] = []
    if _internal_panel_available():
        devices.append({
            "kind": "internal", "id": None,
            "label": "Internal Display",
            "min": 5, "cur": _bright_pct(),
        })
    for d in _ddcutil_displays():
        disp = d["display"]
        devices.append({
            "kind": "ddcutil", "id": disp,
            "label": d["model"] or f"Display {disp}",
            "min": 0, "cur": _ddcutil_get_brightness(disp),
        })
    return devices

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

def _build_monitor_brightness_row(dev: dict) -> Gtk.Box:
    """Eine Zeile PRO ERKANNTER ANZEIGE im Monitor-Tab des Brightness-
    Widgets - exakt dasselbe Muster wie _build_device_row() im Audio-
    Widget (Redesign-Vorgabe: "Pro Monitor Überschrift wie bei audio
    devices"): Name+Wert in EINEM zentrierten Label, darunter ein
    Regler ohne Icon, reduzierter Abstand. dev kommt aus
    _brightness_devices() - "kind" entscheidet nur, welcher Backend-
    Aufruf beim Ziehen läuft (brightnessctl fürs interne Panel,
    ddcutil/DDC-CI für externe Monitore)."""
    row = vbox(1)
    row.get_style_context().add_class("bubble")
    pad(row, h=8, v=4)

    val_state = [dev["cur"]]

    def _label_text():
        return f'{dev["label"]}: {val_state[0]}%'

    name_lbl = bsec(_label_text())
    name_widget = name_lbl.get_children()[0]
    row.pack_start(name_lbl, False, False, 0)

    debounce_id = [0]

    def _apply_value(v: int):
        if dev["kind"] == "internal":
            run(["brightnessctl", "set", f"{v}%"])
        else:
            _ddcutil_set_brightness(dev["id"], v)

    def _on_change(s):
        val_state[0] = int(s.get_value())
        name_widget.set_label(_label_text())
        # ddcutil ist deutlich langsamer pro Aufruf als brightnessctl
        # (I2C-Bus statt sysfs) - Debounce verhindert, dass beim Ziehen
        # ein Rattenschwanz an Hintergrund-Threads sich gegenseitig
        # überholt und die Anzeige am Ende auf einem veralteten Wert
        # hängen bleibt.
        if debounce_id[0]:
            GLib.source_remove(debounce_id[0])
        def _fire():
            debounce_id[0] = 0
            in_thread(_apply_value, val_state[0])
            return False
        debounce_id[0] = GLib.timeout_add(150, _fire)

    box, _ = bslider("", dev["min"], 100, 1, dev["cur"], cb=_on_change, show_val=False)
    for ch in box.get_children():
        if isinstance(ch, Gtk.Label):
            box.remove(ch)
            break
    box.set_halign(Gtk.Align.CENTER)
    box.set_size_request(220, -1)
    row.pack_start(box, False, False, 0)

    return row

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

    # BUGFIX ("mehrere Monitore werden nicht angezeigt"): hier stand
    # bisher GENAU EIN globaler brightnessctl-Regler ("Screen: X%"),
    # unabhängig davon, wie viele Bildschirme tatsächlich angeschlossen
    # sind - brightnessctl kennt naturgemäß nur das interne Panel, nie
    # externe DP/HDMI-Monitore. Jetzt: eine Zeile PRO erkannter Anzeige
    # (internes Panel via brightnessctl + jeder per DDC/CI erkannte
    # externe Monitor via ddcutil, siehe _brightness_devices()), exakt
    # nach demselben "Pro Monitor Überschrift wie bei audio devices"-
    # Muster aus der Redesign-Liste. Erkennung läuft async (ddcutil ist
    # I2C-Bus-Polling, spürbar langsam), Platzhalter bis dahin.
    #
    # Der Klick-zum-Wallpaper-neu-würfeln auf dem alten "Screen"-Label
    # ist bewusst WEG (Redesign-Liste: "Screen Label triggert jetzt
    # beim klicken das was vorher das Symbol rechts davon gemacht hätte
    # - geben wir weg") - Wallpaper-Auswahl lebt jetzt vollständig im
    # neuen Wallpapers-Tab unter Appearance & Language (manuelle Auswahl
    # mit Preview statt nur Zufalls-Reroll).
    mon_section = vbox(4)
    t1.pack_start(mon_section, False, False, 0)
    _loading_lbl = bitem("Loading displays…", dim=True)
    mon_section.pack_start(_loading_lbl, False, False, 0)

    def _load_monitor_brightness():
        try:
            devices = _brightness_devices()
        except Exception:
            devices = []
        def _apply():
            if _loading_lbl.get_parent() is not None:
                mon_section.remove(_loading_lbl)
            if not devices:
                mon_section.pack_start(
                    bitem("No controllable displays found "
                          "(internal panel, or ddcutil for external "
                          "monitors)", dim=True),
                    False, False, 0)
            for i, dev in enumerate(devices):
                mon_section.pack_start(
                    _build_monitor_brightness_row(dev), False, False,
                    0 if i == 0 else 4)
            mon_section.show_all()
            return False
        GLib.idle_add(_apply)

    in_thread(_load_monitor_brightness)

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

    # 24px statt 6px zwischen den beiden Buttons: bei nur 2 Buttons
    # (statt 3 wie bei den Profilen oben) wirkte der enge pp_row-Abstand
    # hier, als würden GameMode und Battery-Saver aneinanderkleben -
    # für die gewünschte "umgekehrte Pyramide" (oben breiter, unten
    # schmaler, aber klar abgesetzt) brauchen die 2 Buttons mehr Luft.
    gm_fx_row = hbox(24)
    gm_fx_row.set_halign(Gtk.Align.CENTER)

    gm_btn = Gtk.Button.new_from_icon_name("input-gaming-symbolic", Gtk.IconSize.BUTTON)
    gm_btn.set_tooltip_text("Gaming Mode: performance profile + CPU boost off")
    fx_btn = Gtk.Button.new_from_icon_name("battery-good-symbolic", Gtk.IconSize.BUTTON)
    fx_btn.set_tooltip_text(
        "Save power: turn off animations, blur, shadow, hyprglass & cursor effects")
    gm_fx_row.pack_start(gm_btn, False, False, 0)
    gm_fx_row.pack_start(fx_btn, False, False, 0)
    # Extra Abstand zu den 3 Profil-Buttons oben (t_prof = vbox(4) gibt
    # sonst nur die knappen 4px Standard-Spacing zwischen ALLEN Kindern
    # - das ließ die 2 Buttons hier optisch an den 3 Profil-Buttons
    # kleben statt wie eine "umgekehrte Pyramide" abgesetzt zu wirken).
    t_prof.pack_start(gm_fx_row, False, False, 14)

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

    # FIX ("processes monitor geht auch nicht gescheit"): ein Kill, der
    # mit AccessDenied/NoSuchProcess fehlschlägt (z.B. Systemprozess,
    # nicht der eigene Nutzer), wurde bisher im "except Exception: pass"
    # unten KOMPLETT stillschweigend verschluckt - der Button tat dann
    # buchstäblich nichts sichtbares, ohne jede Rückmeldung, was sich
    # wie "geht nicht" anfühlt. Jetzt mit einer kleinen Statuszeile
    # (gleiches Flash-Muster wie in den anderen Tabs, z.B. Privacy),
    # die nach jedem Kill-Versuch Erfolg/Fehler meldet.
    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()
    root.pack_start(status_lbl, False, False, 0)

    def _flash(text: str, ms: int = 3000):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

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
                import psutil
                err_msg = None
                try:
                    proc = _proc_cache.get(p)
                    if proc is None:
                        proc = psutil.Process(p)
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()  # nicht kooperativ -> hart nachlegen
                except psutil.NoSuchProcess:
                    pass  # Prozess war schon weg - kein Fehler, kein Hinweis nötig
                except psutil.AccessDenied:
                    # Vorher hier stillschweigend verschluckt (siehe FIX-
                    # Kommentar oben) - das war vermutlich ein guter Teil
                    # des "geht nicht gescheit": Klick auf Kill bei einem
                    # fremden/Root-Prozess tat rein gar nichts sichtbares.
                    err_msg = f"No permission to end “{n}” (PID {p})."
                except Exception as e:
                    err_msg = f"Failed to end “{n}”: {e}"
                def _done():
                    if err_msg:
                        _flash(f"Error: {err_msg}")
                    _refresh()
                    return False
                GLib.idle_add(_done)
            in_thread(_worker)
        kill_b.connect("clicked", _on_kill)
        row.pack_start(kill_b, False, False, 0)
        return row, lbl, stat_lbl

    _warmed_up = [False]

    def _fetch() -> dict:
        import psutil
        seen_pids = set()
        data = {}

        # FIX (Analyse Punkt 5 - Processes-Tab zeigt beim Öffnen immer
        # 0.0%): psutil.Process.cpu_percent(interval=None) liefert beim
        # ALLERERSTEN Aufruf für ein Process-Objekt laut Dokumentation
        # IMMER 0.0 zurück, egal wie lange der Prozess davor schon
        # lief - es braucht zwingend einen ZWEITEN Aufruf mit etwas
        # Zeitabstand dazwischen. Ein früherer Versuch, das über einen
        # separaten Vorwärm-Hintergrund-Thread + GLib.timeout_add zu
        # lösen, hat nicht zuverlässig funktioniert - vermutlich weil
        # in_thread()/ThreadPoolExecutor Exceptions aus einem
        # submit()-ten Callable komplett lautlos verschluckt (niemand
        # ruft .result() auf das Future ab), ein Fehler darin also ganz
        # ohne jede sichtbare Fehlermeldung einfach nichts getan hätte.
        # Jetzt stattdessen denkbar einfach UND robust: genau EINMAL,
        # synchron, direkt hier im ohnehin schon per in_thread()
        # laufenden Hintergrund-Thread (siehe _refresh() unten) - erst
        # für ALLE Prozesse den Referenzpunkt setzen, kurz blockierend
        # warten (blockiert NUR diesen Hintergrund-Thread, nicht die
        # UI), DANACH erst die eigentliche Messung. Kein zweiter Thread,
        # kein Timer, keine Race Condition, keine Stelle, an der ein
        # Fehler die ganze Vorwärm-Logik unbemerkt stilllegen könnte.
        if not _warmed_up[0]:
            _warmed_up[0] = True
            for p in psutil.process_iter(["pid"]):
                pid = p.info["pid"]
                if pid == 0:
                    continue
                _proc_cache[pid] = p
                try:
                    p.cpu_percent(interval=None)  # nur Referenzpunkt setzen
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            # 350ms: genug Zeitfenster für eine brauchbare erste
            # CPU%-Messung, kurz genug, dass die Verzögerung beim allerersten
            # Öffnen des Tabs kaum auffällt (siehe Analyse, 300-500ms).
            time.sleep(0.35)

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

    # Wieder das ursprüngliche, simple Muster (Timer für die
    # Folge-Ticks + ein sofortiger erster Aufruf) - das eigentliche
    # Warm-up (siehe _fetch()-Docstring oben) passiert jetzt INNERHALB
    # dieses ersten Aufrufs selbst, transparent für den Rest des Codes
    # hier.
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
         "hourly": [], "daily": [], "location": "–"}
    loc = _load_weather_location()
    r["location"] = loc.get("name", "–")
    try:
        import urllib.request, urllib.parse, json as _json
        params = {
            "latitude": loc["lat"], "longitude": loc["lon"],
            "current": "temperature_2m,relative_humidity_2m,"
                       "precipitation,weather_code,is_day",
            "hourly": "temperature_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 7,
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

        # "Das Wetter in den nächsten paar Stunden" - die nächsten 6
        # vollen Stunden AB JETZT (nicht ab Mitternacht, wie Open-Meteo
        # die hourly-Liste sonst liefert) - daher hier per aktueller
        # Systemzeit in die Liste reingesucht statt einfach Index 0.
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        codes = hourly.get("weather_code", [])
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:00")
        start_idx = 0
        for i, t in enumerate(times):
            if t >= now_iso:
                start_idx = i
                break
        for i in range(start_idx, min(start_idx + 6, len(times))):
            try:
                hh = times[i].split("T")[1][:5]
                r["hourly"].append({
                    "label": hh,
                    "icon": _wicon_wmo(codes[i]) if i < len(codes) else "–",
                    "temp": f"{round(temps[i])}°" if i < len(temps) else "–",
                })
            except (IndexError, ValueError):
                continue

        # "Die 7 Tage Prognose" - Tagesname (Mo/Di/...) + Icon +
        # Min/Max-Temperatur, inklusive heute als erster Eintrag.
        daily = data.get("daily", {})
        d_times = daily.get("time", [])
        d_codes = daily.get("weather_code", [])
        d_max = daily.get("temperature_2m_max", [])
        d_min = daily.get("temperature_2m_min", [])
        for i, dstr in enumerate(d_times[:7]):
            try:
                wd = date.fromisoformat(dstr)
                label = "Today" if i == 0 else DAYS_EN[wd.weekday()]
                r["daily"].append({
                    "label": label,
                    "icon": _wicon_wmo(d_codes[i]) if i < len(d_codes) else "–",
                    "hi": f"{round(d_max[i])}°" if i < len(d_max) else "–",
                    "lo": f"{round(d_min[i])}°" if i < len(d_min) else "–",
                })
            except (IndexError, ValueError):
                continue
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

            days = data.get("weather", [])
            now_hour = datetime.now().hour
            if days:
                # wttr.in liefert pro Tag 8 Einträge im 3h-Raster
                # ("time": "0","300",...,"2100") - die ab JETZT
                # passenden aus heute + (falls nötig) morgen sammeln.
                pool = []
                for di, day in enumerate(days[:2]):
                    for h in day.get("hourly", []):
                        try:
                            slot_hour = int(h.get("time", "0")) // 100
                        except ValueError:
                            continue
                        abs_hour = slot_hour + di * 24
                        pool.append((abs_hour, h))
                for abs_hour, h in pool:
                    if abs_hour < now_hour:
                        continue
                    if len(r["hourly"]) >= 6:
                        break
                    r["hourly"].append({
                        "label": f"{abs_hour % 24:02d}:00",
                        "icon": _wicon(h.get("weatherCode", "")),
                        "temp": f'{h.get("tempC", "–")}°',
                    })

            for i, day in enumerate(days[:7]):
                try:
                    wd = date.fromisoformat(day.get("date", ""))
                    label = "Today" if i == 0 else DAYS_EN[wd.weekday()]
                except ValueError:
                    label = f"D{i}"
                hrs = day.get("hourly", [])
                mid_code = hrs[4].get("weatherCode", "") if len(hrs) > 4 else ""
                r["daily"].append({
                    "label": label,
                    "icon": _wicon(mid_code),
                    "hi": f'{day.get("maxtempC", "–")}°',
                    "lo": f'{day.get("mintempC", "–")}°',
                })
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

    # ── TAB 0: Clock (NEU - eigener Haupttab) ────────────────────────
    # Redesign-Liste: "Vorher neuer Haupttab: Clock: Das groß mittig
    # die Uhr und direkt darunter das Datum" - Uhrzeit/Datum standen
    # bisher klein mit im Weather-Tab (dt_row unten) - jetzt eigener,
    # eigenständiger Tab mit großer, zentrierter Anzeige.
    t0 = vbox(6); pad(t0, h=4, v=18)
    time_lbl = Gtk.Label(label="--:--")
    time_lbl.get_style_context().add_class("clock-digits-huge")
    time_lbl.set_halign(Gtk.Align.CENTER)
    date_lbl = Gtk.Label(label="")
    date_lbl.get_style_context().add_class("value-md")
    date_lbl.set_halign(Gtk.Align.CENTER)
    t0.pack_start(time_lbl, False, False, 0)
    t0.pack_start(date_lbl, False, False, 0)

    # ── TAB 1: Weather ──────────────────────────────────────
    # Redesign-Liste: "Oben Mittig Was grad ist. Oben links das
    # Location Pin Icon. Oben rechts die 2 anderen Stats" + "Unten
    # mitte: das Wetter in den nächsten paar Stunden" + "Unten unten
    # Mitte: die 7 Tage Prognose".
    t1 = vbox(4); pad(t1, h=4, v=6)

    top_row = hbox(8)
    top_row.set_halign(Gtk.Align.FILL)

    loc_btn = Gtk.Button(label="📍")
    loc_btn.set_relief(Gtk.ReliefStyle.NONE)
    loc_btn.get_style_context().add_class("flat")
    loc_btn.set_can_focus(False)
    loc_btn.set_halign(Gtk.Align.START)
    loc_btn.set_valign(Gtk.Align.START)
    loc_btn.set_tooltip_text("Change location")
    top_row.pack_start(loc_btn, False, False, 0)

    mid_box = vbox(2)
    mid_box.set_valign(Gtk.Align.CENTER)
    mid_box.set_halign(Gtk.Align.CENTER)
    mid_box.set_hexpand(True)
    icon_row = hbox(6)
    icon_row.set_halign(Gtk.Align.CENTER)
    icon_lbl = Gtk.Label(label="🌡️")
    icon_lbl.get_style_context().add_class("icon-xl")
    temp_lbl = Gtk.Label(label="–")
    temp_lbl.get_style_context().add_class("temp-xl")
    icon_row.pack_start(icon_lbl, False, False, 0)
    icon_row.pack_start(temp_lbl, False, False, 0)
    desc_lbl = Gtk.Label(label="Loading weather…")
    desc_lbl.get_style_context().add_class("value-md")
    desc_lbl.set_halign(Gtk.Align.CENTER)
    mid_box.pack_start(icon_row, False, False, 0)
    mid_box.pack_start(desc_lbl, False, False, 0)
    top_row.pack_start(mid_box, True, True, 0)

    stats_box = vbox(3)
    stats_box.set_valign(Gtk.Align.START)
    hum_lbl = Gtk.Label(label="💧 –")
    hum_lbl.get_style_context().add_class("caption")
    hum_lbl.set_halign(Gtk.Align.END)
    hum_lbl.set_tooltip_text("Humidity")
    rain_lbl = Gtk.Label(label="☔ –")
    rain_lbl.get_style_context().add_class("caption")
    rain_lbl.set_halign(Gtk.Align.END)
    rain_lbl.set_tooltip_text("Precipitation (mm)")
    stats_box.pack_start(hum_lbl,  False, False, 0)
    stats_box.pack_start(rain_lbl, False, False, 0)
    top_row.pack_start(stats_box, False, False, 0)

    t1.pack_start(top_row, False, False, 0)

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

    t1.pack_start(sep(), False, False, 2)

    # ── "Unten mitte": Wetter in den nächsten paar Stunden ──────────
    _N_HOURLY = 6
    hourly_row = hbox(4)
    hourly_row.set_halign(Gtk.Align.CENTER)
    hourly_slots = []
    for _ in range(_N_HOURLY):
        cell = vbox(1)
        cell.get_style_context().add_class("bubble")
        cell.get_style_context().add_class("item")
        cell.set_size_request(48, -1)
        cell.set_halign(Gtk.Align.CENTER)
        h_time = Gtk.Label(label="–")
        h_time.get_style_context().add_class("caption")
        h_icon = Gtk.Label(label="–")
        h_icon.get_style_context().add_class("icon-lg")
        h_temp = Gtk.Label(label="–")
        h_temp.get_style_context().add_class("caption")
        cell.pack_start(h_time, False, False, 0)
        cell.pack_start(h_icon, False, False, 0)
        cell.pack_start(h_temp, False, False, 0)
        hourly_row.pack_start(cell, False, False, 0)
        hourly_slots.append((cell, h_time, h_icon, h_temp))
    t1.pack_start(hourly_row, False, False, 0)

    t1.pack_start(sep(), False, False, 2)

    # ── "Unten unten Mitte": die 7-Tage-Prognose ─────────────────────
    daily_row = hbox(4)
    daily_row.set_halign(Gtk.Align.CENTER)
    daily_slots = []
    for _ in range(7):
        cell = vbox(1)
        cell.get_style_context().add_class("bubble")
        cell.get_style_context().add_class("item")
        cell.set_size_request(44, -1)
        cell.set_halign(Gtk.Align.CENTER)
        d_lbl = Gtk.Label(label="–")
        d_lbl.get_style_context().add_class("caption")
        d_icon = Gtk.Label(label="–")
        d_icon.get_style_context().add_class("icon-lg")
        d_temp = Gtk.Label(label="–")
        d_temp.get_style_context().add_class("caption")
        cell.pack_start(d_lbl, False, False, 0)
        cell.pack_start(d_icon, False, False, 0)
        cell.pack_start(d_temp, False, False, 0)
        daily_row.pack_start(cell, False, False, 0)
        daily_slots.append((cell, d_lbl, d_icon, d_temp))
    t1.pack_start(daily_row, False, False, 0)

    # ── TAB 2: Calendar ─────────────────────────────────────
    t2 = vbox(2); pad(t2, h=6, v=4)

    now = datetime.now()
    cur = [now.year, now.month]

    prev_b = btn("󰅁", tip="Previous month")
    next_b = btn("󰅂", tip="Next month")
    # Redesign: Monat/Jahr-Label als klickbarer Button (Hover-Glow zeigt
    # Klickbarkeit). Klick öffnet den Kalender-Speicherort-Dialog, der
    # früher am separaten storage_btn hing. Pfeilabstand reduziert (sp=2).
    mth_btn = Gtk.Button()
    mth_btn.set_relief(Gtk.ReliefStyle.NONE)
    mth_btn.get_style_context().add_class("flat")
    mth_btn.get_style_context().add_class("bubble")
    mth_btn.set_can_focus(False)
    mth_btn.set_tooltip_text("Click to change calendar storage location")
    mth_lbl = Gtk.Label(label="")
    mth_lbl.set_halign(Gtk.Align.CENTER)
    mth_btn.add(mth_lbl)
    nav_row = hbox(2)
    nav_row.set_halign(Gtk.Align.CENTER)
    nav_row.pack_start(prev_b,  False, False, 0)
    nav_row.pack_start(mth_btn, False, False, 2)
    nav_row.pack_start(next_b,  False, False, 0)
    t2.pack_start(nav_row, False, False, 0)

    def _on_storage_btn(_w):
        cal_name = _khal_default_calendar_name()
        if not cal_name:
            mth_btn.set_tooltip_text("No default calendar found in khal's config.")
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
                mth_btn.set_tooltip_text(
                    msg if msg else "Storage location changed."
                    if ok else f"Failed: {msg}")
                if ok:
                    _build_grid(cur[0], cur[1])
            GLib.idle_add(_after)
        in_thread(_worker)

    mth_btn.connect("clicked", _on_storage_btn)

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
                del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
                del_btn.set_tooltip_text("Delete event")
                del_btn.connect("clicked", lambda _w, ev=e: _on_delete_event(ev))
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

        # BUGFIX ("Blase viel zu groß für den Inhalt" beim
        # Kalender-Widget): calendar.monthcalendar() liefert je nach
        # Monat 4, 5 oder 6 Wochen-Zeilen zurück - das Grid wird hier
        # bei jeder Navigation (_nav_prev/_nav_next) komplett neu
        # gebaut und kann dadurch von einem Monat zum nächsten
        # SCHRUMPFEN (z.B. von einem 6-Wochen- auf einen 4-Wochen-
        # Monat). GTK-Fenster werden aber nie von selbst wieder
        # kleiner (siehe _shrink_to_fit()-Docstring) - ohne diesen
        # Aufruf hier blieb das Fenster/die Blase bei der Größe des
        # größten bisher gezeigten Monats hängen, während der Grid-
        # Inhalt selbst schon kleiner war. _switch_stack() (Tab-
        # Wechsel) hatte diesen Aufruf schon immer, _build_grid()
        # (Monats-Wechsel INNERHALB des Calendar-Tabs) bisher nicht -
        # derselbe Bug-Mechanismus kann grundsätzlich überall auftreten,
        # wo Inhalt nachträglich schrumpft, ohne dass ein Tab-Wechsel
        # (und damit _switch_stack()) im Spiel ist.
        GLib.idle_add(_shrink_to_fit, win)

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

            for i, (cell, h_time, h_icon, h_temp) in enumerate(hourly_slots):
                if i < len(w["hourly"]):
                    h = w["hourly"][i]
                    h_time.set_label(h["label"])
                    h_icon.set_label(h["icon"])
                    h_temp.set_label(h["temp"])
                    cell.set_no_show_all(False)
                    cell.show_all()
                else:
                    cell.hide()

            for i, (cell, d_lbl, d_icon, d_temp) in enumerate(daily_slots):
                if i < len(w["daily"]):
                    d = w["daily"][i]
                    d_lbl.set_label(d["label"])
                    d_icon.set_label(d["icon"])
                    d_temp.set_label(f'{d["hi"]}/{d["lo"]}')
                    cell.set_no_show_all(False)
                    cell.show_all()
                else:
                    cell.hide()

            loc_tip = f'Location: {w["location"]}\nClick 📍 to change'
            mid_box.set_tooltip_text(loc_tip)
        GLib.idle_add(_apply)

    in_thread(_load_weather)
    add_timer(600_000, lambda: in_thread(_load_weather) or True)

    # ── Tabs zusammensetzen (gleiches Muster wie Media/Devices/Apps) ─
    stack.add_named(t0, "clock")
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
    for name, label in (("clock", "  Clock"),
                         ("weather", "󰖐  Weather"),
                         ("calendar", "󰃭  Calendar")):
        b = btn(label, active=(name == "clock"))
        b.connect("clicked", lambda _b, n=name: _switch_tab(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("clock")

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

# ── TrafkTuxLauncher Settings.json (neuer "Launcher"-Tab, Appearance) ──
def _launcher_settings_path() -> Path:
    return Path(HOME) / ".config" / "TrafkTuxLauncher" / "Settings.json"

_LAUNCHER_SPEED_PRESETS = ("Normal", "Fast", "Turbo")

def _read_launcher_settings() -> dict:
    """Liest TrafkTuxLauncher/Settings.json, exakt nach der in
    Settings.md dokumentierten Logik: Datei fehlt -> Defaults, Schlüssel
    fehlt/Wert ungültig -> Default für GENAU diesen Wert (nicht die
    ganze Datei), kaputtes JSON -> Defaults + Warnung auf stderr (der
    Launcher selbst verhält sich laut Settings.md identisch - diese UI
    soll bei einer von Hand editierten, kaputten Datei also nicht
    einfach crashen, sondern genau wie der Launcher selbst reagieren).
    Gibt IMMER ein Dict mit "Style" (str) und "Speed" (str) zurück -
    bei Speed bleibt eine Zahl als String erhalten (z.B. "1.5"), damit
    die aufrufende UI selbst entscheiden kann, ob sie das als Preset
    oder als Custom-Zahl anzeigt."""
    p = _launcher_settings_path()
    style, speed, selection = "Classic", "Normal", "Flicker"
    if p.is_file():
        try:
            data = json.loads(p.read_text())
        except Exception as e:
            print(f"[Launcher-Settings] {p}: invalid JSON, using defaults ({e})",
                  file=sys.stderr)
            data = {}
        anim = data.get("Animation", {}) if isinstance(data, dict) else {}
        if isinstance(anim, dict):
            s = anim.get("Style")
            if isinstance(s, str) and s.strip().lower() in ("classic", "radial"):
                style = s.strip()
            sp = anim.get("Speed")
            _preset_match = None
            if isinstance(sp, str):
                _preset_match = next(
                    (preset for preset in _LAUNCHER_SPEED_PRESETS
                     if preset.lower() == sp.strip().lower()), None)
            if _preset_match is not None:
                speed = _preset_match  # auf kanonische Schreibweise normalisiert
            elif isinstance(sp, (int, float)):
                speed = f"{max(0.25, min(8.0, float(sp)))}"
            elif isinstance(sp, str):
                try:
                    speed = f"{max(0.25, min(8.0, float(sp)))}"
                except ValueError:
                    pass  # ungültiger Text -> Default "Normal" bleibt stehen
            # NEU: Animation.Selection (Flicker/Fade) - siehe TrafkTuxLauncher.c,
            # exakt dieselbe Default-/Fallback-Logik wie dort (case-insensitive,
            # fehlend/ungültig -> "Flicker" bleibt stehen).
            se = anim.get("Selection")
            if isinstance(se, str) and se.strip().lower() in ("flicker", "fade"):
                selection = "Flicker" if se.strip().lower() == "flicker" else "Fade"
    return {"Style": style, "Speed": speed, "Selection": selection}

def _write_launcher_settings(style: str = None, speed: str = None,
                              selection: str = None) -> None:
    """Schreibt Settings.json atomar (siehe atomic_write_text()). Nur
    der jeweils übergebene Wert wird geändert, die anderen bleiben
    unangetastet (vorher aus der bestehenden Datei gelesen) - ein Klick
    auf "Radial" soll weder die Speed- noch die Selection-Einstellung
    anfassen und umgekehrt. Das Verzeichnis wird bei Bedarf angelegt,
    da die Datei laut Settings.md optional ist und beim allerersten
    Ändern über diese UI noch gar nicht existieren muss."""
    cur = _read_launcher_settings()
    new_style = style if style is not None else cur["Style"]
    new_speed = speed if speed is not None else cur["Speed"]
    new_selection = selection if selection is not None else cur["Selection"]
    p = _launcher_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"Animation": {"Style": new_style, "Speed": new_speed,
                              "Selection": new_selection}}
    atomic_write_text(p, json.dumps(payload, indent=2) + "\n")

def apply_change(desc: str, apply_fn, on_status=None, reset_fn=None) -> None:
    """Ersetzt das frühere Stage/Apply/Discard-System (PendingChange +
    Apply-Leiste): JEDE Einstellung wird jetzt sofort übernommen, sobald
    sie ausgewählt wird - kein "pending"-Zustand mehr, kein Cancel/
    Apply-Klick nötig. apply_fn läuft in einem Hintergrund-Thread (die
    Änderungen dahinter sind i.d.R. blockierende subprocess-/D-Bus-
    Aufrufe, sonst würde die UI beim Klick kurz einfrieren).

    on_status(text) - falls angegeben - bekommt optional "Applying…"
    und danach "Applied" bzw. eine Fehlermeldung, als Ersatz für die
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
                on_status(f"Error: {err}" if err else "Applied")
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

def _build_appearance_wallpapers_tab(win: Gtk.Window) -> Gtk.Box:
    """Neuer Wallpapers-Tab (Appearance & Language) - scannt beim
    Öffnen automatisch den Wallpapers.sh-Ordner (~/.config/hypr/
    Wallpapers/<ratio>/, siehe _scan_wallpaper_images()) und zeigt
    JEDES gefundene Bild als Preview-Kachel. Klick auf eine Kachel
    setzt sie sofort als Wallpaper über 'Wallpapers.sh --set' (neuer
    Modus, siehe dortiger Kommentar) - entweder auf ALLE Monitore oder
    nur auf den oben per Segmented-Control gewählten einzelnen.
    Umsetzt den Wunsch aus dem Chat: "über das selbe skript wie bei den
    zufalls sachen... beim skript was hinzufügen... die wallpaper
    sollen automatisch geladen werden, einfach beim öffnen des widgets
    den ordner scannen und alle anzeigen (mit preview gleich dazu)".
    Behebt nebenbei den zweiten gemeldeten Bug ("wahrscheinlich kann
    man deswegen auch nicht das wallpaper ändern") - vorher gab es
    NUR den Zufalls-Reroll (siehe alter screen_btn in
    _brightness_content), keine Möglichkeit, ein bestimmtes Bild
    gezielt auszuwählen."""
    outer = vbox(4)
    wallpaper_script = _resolve_wallpaper_script()

    if not os.path.isfile(wallpaper_script):
        outer.pack_start(
            bitem(f"Wallpaper script not found in ~/.config/hypr "
                  f"(looked for: {', '.join(_WALLPAPER_SCRIPT_CANDIDATES)})",
                  dim=True), False, False, 0)
        return outer

    # ── Zielauswahl: alle Monitore (Default) oder ein bestimmter ────
    mon_names = [m.get("name") for m in _hypr_monitors_live() if m.get("name")]
    target_ctrl = _SegmentedControl()
    target_ctrl.get_style_context().add_class("bubble")
    target_ctrl.get_style_context().add_class("segmented")
    target_ctrl.set_can_focus(False)
    target_ctrl.append_text("All Displays")
    for n in mon_names:
        target_ctrl.append_text(n)
    target_ctrl.set_active(0)
    if len(mon_names) <= 1:
        target_ctrl.set_sensitive(False)
        target_ctrl.set_tooltip_text("Only one display connected.")
    target_row = hbox(6)
    target_row.set_halign(Gtk.Align.CENTER)
    target_row.pack_start(target_ctrl.widget, False, False, 0)
    outer.pack_start(target_row, False, False, 0)

    def _selected_monitor() -> str | None:
        idx = target_ctrl._active
        return mon_names[idx - 1] if idx > 0 else None

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    scroller, scroll_inner = scroll_box(max_h=260)
    flow = Gtk.FlowBox()
    flow.set_valign(Gtk.Align.START)
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    flow.set_homogeneous(True)
    flow.set_max_children_per_line(4)
    flow.set_min_children_per_line(2)
    flow.set_row_spacing(6)
    flow.set_column_spacing(6)
    scroll_inner.pack_start(flow, True, True, 0)
    outer.pack_start(scroller, False, False, 0)

    loading_lbl = bitem("Scanning wallpapers…", dim=True)
    outer.pack_start(loading_lbl, False, False, 0)
    outer.pack_start(status_lbl, False, False, 4)

    _THUMB = 96

    def _on_pick(path: str):
        mon = _selected_monitor()
        cmd = ["bash", wallpaper_script, "--set", path] + ([mon] if mon else [])
        in_thread(run, cmd)
        status_lbl.set_label(
            f"Applied: {os.path.basename(path)}"
            + (f" → {mon}" if mon else " → all displays"))
        status_lbl.show()
        GLib.timeout_add(2500, lambda: (status_lbl.hide(), False)[1])

    def _load_previews():
        # GdkPixbuf.new_from_file_at_scale() ist synchrones Datei-I/O +
        # Dekodierung - bei vielen/großen Bildern spürbar langsam, daher
        # komplett im Hintergrund-Thread, nur der fertige Kachel-Aufbau
        # läuft über GLib.idle_add() zurück im Main-Thread (gleiches
        # Muster wie _load_rgb_devices() im Brightness-Widget).
        tiles = []
        for p in _scan_wallpaper_images():
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    p, _THUMB, _THUMB, True)
            except Exception:
                continue
            tiles.append((p, pix))

        def _apply():
            if loading_lbl.get_parent() is not None:
                outer.remove(loading_lbl)
            if not tiles:
                outer.pack_start(
                    bitem(f"No wallpapers found in {WALLPAPER_DIR}",
                          dim=True), False, False, 0)
                outer.show_all()
                status_lbl.hide()
                return False
            for path, pix in tiles:
                tile_btn = Gtk.Button()
                tile_btn.get_style_context().add_class("bubble")
                tile_btn.set_can_focus(False)
                tile_btn.set_tooltip_text(os.path.basename(path))
                tile_btn.add(Gtk.Image.new_from_pixbuf(pix))
                tile_btn.connect("clicked", lambda _b, p=path: _on_pick(p))
                flow.add(tile_btn)
            flow.show_all()
            outer.show_all()
            status_lbl.hide()
            return False
        GLib.idle_add(_apply)

    in_thread(_load_previews)
    return outer

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

    t_sound    = vbox(4)
    t_look     = vbox(4)
    t_lang     = vbox(4)
    t_launcher = vbox(4)

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
    # Theme + Cursor effects + Shake-to-find jetzt EIN einziger,
    # zentrierter Row - "Wiedermal die on off Sachen auf die Label
    # verschieben": kein separates Label+Toggle-Paar mehr, der
    # Button-Text SELBST ist die Beschreibung, leuchtet per aktiver
    # Klasse (exakt dasselbe Muster wie bei Privacy/DNS/Tailscale,
    # siehe "Enforce DoT"/"Guest WiFi"/"Start on boot").
    t_look.pack_start(bsec("APPEARANCE & CURSOR"), False, False, 0)

    # "Theme: wenn dark auf die Farbe #9C81CF mit #7554B3 Glow, wenn
    # light der normale Glow - button entfernen und aufs Label geben":
    # der Button ist IMMER "aktiv" (irgendein Theme ist ja immer
    # gewählt) - nur die GLOW-FARBE zeigt an, welches: lila bei Dark
    # (theme-glow-dark-Klasse, siehe CSS oben), normales Gold bei
    # Light (Standard-.active-Look, keine Zusatzklasse nötig).
    theme_toggle = btn("", active=True)
    theme_toggle.set_always_show_image(True)
    def _set_theme_toggle_label(is_dark: bool):
        theme_toggle.set_label("Dark" if is_dark else "Light")
        theme_toggle.set_image(Gtk.Image.new_from_icon_name(
            "weather-clear-night-symbolic" if is_dark else "weather-clear-symbolic",
            Gtk.IconSize.BUTTON))
    def _refresh_theme_toggle():
        # Robuster: _is_dark_mode() liest aus Gtk.Settings (live im Prozess)
        # UND fällt auf gsettings zurück, falls die In-Prozess-Property
        # noch den alten Start-Zustand hat.
        is_dark = _is_dark_mode()
        try:
            _gs_out = run(["gsettings", "get",
                           "org.gnome.desktop.interface", "color-scheme"])
            if _gs_out.strip():
                is_dark = "dark" in _gs_out.lower()
        except Exception:
            pass
        # Label+Icon: "Dark"/moon wenn Dark-Mode aktiv, "Light"/sun wenn
        # Light aktiv. Eindeutiger als vorher (kein "Dark Theme" das im
        # Light-Modus verwirrt) - das aktive Icon + Glow zeigt, was
        # GERADE läuft.
        _set_theme_toggle_label(is_dark)
        ctx = theme_toggle.get_style_context()
        if is_dark:
            ctx.add_class("active")
            ctx.add_class("theme-glow-dark")
        else:
            ctx.add_class("active")
            ctx.remove_class("theme-glow-dark")
    _refresh_theme_toggle()

    def _on_dark_toggle(_w):
        new_dark = not _is_dark_mode()
        try:
            _gs_out = run(["gsettings", "get",
                           "org.gnome.desktop.interface", "color-scheme"])
            if _gs_out.strip():
                new_dark = not ("dark" in _gs_out.lower())
        except Exception:
            pass

        def _apply():
            ok, err = _set_dark_mode(new_dark)
            if not ok:
                raise RuntimeError(err)
        def _reset():
            _refresh_theme_toggle()
        # Sofortiges visuelles Feedback
        _set_theme_toggle_label(new_dark)
        ctx = theme_toggle.get_style_context()
        if new_dark:
            ctx.add_class("theme-glow-dark")
        else:
            ctx.remove_class("theme-glow-dark")
        apply_change(f"Theme: {'Dark' if new_dark else 'Light'}", _apply,
                     on_status=_flash_appearance_status, reset_fn=_reset)

    theme_toggle.connect("clicked", _on_dark_toggle)
    # Ehrlicher Hinweis statt eines leeren Versprechens: GTK/Firefox
    # ziehen i.d.R. live nach (gsettings + Portal-Neustart, siehe
    # _broadcast_theme_change), Qt/Kvantum-Apps können das laut
    # Kvantum-Upstream technisch NICHT ohne Neustart - kein Bug hier,
    # sondern eine Qt-Plattform-Grenze. Steht jetzt nur noch als
    # Tooltip da statt als eigener, klein gedruckter Textblock.
    theme_toggle.set_tooltip_text(
        "GTK & Firefox switch live. Qt/Kvantum apps need a restart to fully redraw.")

    # ── Cursor: dynamic_cursors Plugin (Tilt/Stretch-Effekte + Shake-to-Find) ──
    cursor_toggle = btn("Cursor effects", active=_cursor_plugin_enabled())
    shake_toggle = btn("Shake-to-find", active=_cursor_shake_enabled())

    def _refresh_cursor_toggle(enabled: bool):
        ctx = cursor_toggle.get_style_context()
        if enabled: ctx.add_class("active")
        else:       ctx.remove_class("active")
        # Shake ergibt nur Sinn, wenn das Plugin selbst überhaupt an ist
        shake_toggle.set_sensitive(enabled)

    def _refresh_shake_toggle(enabled: bool):
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

    look_row = hbox(10)
    look_row.set_halign(Gtk.Align.CENTER)
    look_row.pack_start(theme_toggle, False, False, 0)
    look_row.pack_start(cursor_toggle, False, False, 0)
    look_row.pack_start(shake_toggle, False, False, 0)
    t_look.pack_start(look_row, False, False, 0)

    # ══════════════════════════ TAB: SOUND ═══════════════════════════
    # Redesign-Liste: "eine Überschrift nur mehr: 'Sounds' kann man
    # klicken um alle sounds zu aktivieren/deaktivieren - click/ui
    # sounds Schalter entfernen". Die vorher separate "Click/UI
    # sounds"-Zeile UND die separate "SOUND EVENTS"-Zwischenüberschrift
    # sind beide weg - die einzige verbleibende Überschrift ("Sounds")
    # ist selbst der globale An/Aus-Schalter (gleiches bsec_btn()-
    # Muster wie "VOLUME: 45%" im Media-Tab), Events hängen direkt
    # darunter, kein Trennstrich mehr dazwischen ("keine Striche").
    sounds_hdr = bsec_btn("Sounds", active=_sounds_enabled())

    def _refresh_sounds_hdr(enabled: bool):
        ctx = sounds_hdr.get_style_context()
        if enabled: ctx.add_class("active")
        else:       ctx.remove_class("active")

    def _on_sounds_hdr_toggle(_w):
        new_val = not _sounds_enabled()
        def _apply():
            _set_sounds_enabled(new_val)
        def _reset():
            _refresh_sounds_hdr(_sounds_enabled())
        _refresh_sounds_hdr(new_val)  # sofortiges visuelles Feedback, siehe Dark-Mode-Toggle oben
        apply_change(f"System sounds: {'On' if new_val else 'Off'}", _apply,
                     on_status=_flash_appearance_status, reset_fn=_reset)

    sounds_hdr.connect("clicked", _on_sounds_hdr_toggle)
    sounds_hdr.set_tooltip_text("Click to toggle all system sounds on/off")
    t_sound.pack_start(sounds_hdr, False, False, 0)

    # ── Pro-Event-Schalter (SOUND_EVENTS) ─────────────────────────────
    # Nutzt SoundControls --status/--enable/--disable MIT Event-Namen
    # (siehe _event_sound_enabled/_set_event_sound_enabled oben), läuft
    # also über dieselben Statusdateien, die SoundDaemon beim
    # Abspielen sowieso schon prüft. Wirkt nur, wenn der globale
    # Schalter oben an ist (Master UND Event müssen beide an sein).
    # "die ganzen On/Off Dinger weg, das machen die Label" - der
    # Event-Name selbst ist jetzt der Schalter, kein separates
    # On/Off-Label mehr daneben.
    def _make_sound_event_row(event: str) -> Gtk.Box:
        row = hbox(0)
        row.set_halign(Gtk.Align.CENTER)
        toggle = btn(event, active=_event_sound_enabled(event))

        def _refresh(enabled: bool, _toggle=toggle):
            ctx = _toggle.get_style_context()
            if enabled: ctx.add_class("active")
            else:       ctx.remove_class("active")

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
        row.pack_start(toggle, True, True, 0)
        return row

    # "weniger Abstand zwischen den 2 Spalten" (vorher 14px) - und die
    # Events hängen jetzt ohne jeden Zusatzabstand/Trennstrich direkt
    # unterm Sounds-Header ("die buttons alle den Abstand zu oben
    # verringern").
    _events_grid = Gtk.Grid()
    _events_grid.set_column_homogeneous(True)
    _events_grid.set_column_spacing(4)
    _events_grid.set_row_spacing(0)
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

    # NEU: Wallpapers-Tab (siehe _build_appearance_wallpapers_tab()) -
    # eigene Funktion statt inline hier, da sie unabhängig vom Rest
    # dieser Funktion (kein Zugriff auf appearance_status_lbl o.ä.
    # nötig) und dadurch auch unabhängig testbar ist.
    t_wall = _build_appearance_wallpapers_tab(win)

    # ══════════════════════════ TAB: LAUNCHER ═════════════════════════
    # Neuer Tab für ~/.config/TrafkTuxLauncher/Settings.json (siehe
    # Settings.md/.json) - Animation.Style (Classic/Radial) +
    # Animation.Speed (Normal/Fast/Turbo oder eine eigene Zahl
    # 0.25-8). Die Datei wird bei JEDEM Öffnen des Launchers neu
    # gelesen (laut Settings.md), eine Änderung hier braucht also
    # keinen Neustart/Reload-Befehl - anders als z.B. die Cursor-
    # Effekte oben, die extra den Tooltip mit dem hyprctl-reload-
    # Hinweis brauchen.
    _launcher_cur = _read_launcher_settings()

    style_row = hbox(10)
    style_row.set_halign(Gtk.Align.CENTER)
    style_btns: dict = {}

    def _refresh_style_btns(active_style: str):
        for n, b in style_btns.items():
            ctx = b.get_style_context()
            if n.lower() == active_style.lower(): ctx.add_class("active")
            else:                                  ctx.remove_class("active")

    def _on_style_click(_w, _name):
        def _apply():
            _write_launcher_settings(style=_name)
        _refresh_style_btns(_name)  # sofortiges visuelles Feedback
        apply_change(f"Launcher animation style: {_name}", _apply,
                     on_status=_flash_appearance_status,
                     reset_fn=lambda: _refresh_style_btns(_read_launcher_settings()["Style"]))

    for name in ("Classic", "Radial"):
        b = btn(name)
        b.connect("clicked", lambda _b, n=name: _on_style_click(_b, n))
        style_btns[name] = b
        style_row.pack_start(b, False, False, 0)
    _refresh_style_btns(_launcher_cur["Style"])
    style_row.set_tooltip_text(
        "Classic: reading order (top-left → bottom-right). "
        "Radial: spreads out from the selected bubble.")
    t_launcher.pack_start(bsec("Animation Style"), False, False, 0)
    t_launcher.pack_start(style_row, False, False, 0)

    speed_row = hbox(10)
    speed_row.set_halign(Gtk.Align.CENTER)
    speed_btns: dict = {}

    def _cur_speed_is_preset(speed_str: str) -> bool:
        return speed_str in _LAUNCHER_SPEED_PRESETS

    def _refresh_speed_btns(speed_str: str):
        is_preset = _cur_speed_is_preset(speed_str)
        for n, b in speed_btns.items():
            ctx = b.get_style_context()
            active = (n == speed_str) if n != "Custom…" else not is_preset
            if active: ctx.add_class("active")
            else:      ctx.remove_class("active")
        speed_btns["Custom…"].set_label(
            "Custom…" if is_preset else f"Custom… ({speed_str}×)")

    def _on_speed_preset_click(_w, _name):
        def _apply():
            _write_launcher_settings(speed=_name)
        _refresh_speed_btns(_name)
        apply_change(f"Launcher animation speed: {_name}", _apply,
                     on_status=_flash_appearance_status,
                     reset_fn=lambda: _refresh_speed_btns(_read_launcher_settings()["Speed"]))

    def _on_speed_custom_click(_w):
        cur = _read_launcher_settings()["Speed"]
        initial = cur if not _cur_speed_is_preset(cur) else ""
        val = _prompt_text_generic(
            win, "Custom Animation Speed",
            "Factor, e.g. 1.5 (clamped to 0.25–8)", initial=initial)
        if val is None:
            return
        try:
            factor = float(val.replace(",", "."))
        except ValueError:
            _flash_appearance_status(f"'{val}' is not a number.")
            return
        factor = max(0.25, min(8.0, factor))
        speed_str = f"{factor}"
        def _apply():
            _write_launcher_settings(speed=speed_str)
        _refresh_speed_btns(speed_str)
        apply_change(f"Launcher animation speed: {speed_str}×", _apply,
                     on_status=_flash_appearance_status,
                     reset_fn=lambda: _refresh_speed_btns(_read_launcher_settings()["Speed"]))

    for name in _LAUNCHER_SPEED_PRESETS:
        b = btn(name)
        b.connect("clicked", lambda _b, n=name: _on_speed_preset_click(_b, n))
        speed_btns[name] = b
        speed_row.pack_start(b, False, False, 0)
    custom_b = btn("Custom…")
    custom_b.connect("clicked", _on_speed_custom_click)
    speed_btns["Custom…"] = custom_b
    speed_row.pack_start(custom_b, False, False, 0)
    _refresh_speed_btns(_launcher_cur["Speed"])
    speed_row.set_tooltip_text(
        "Scales the duration of all bubble animations. Normal=1×, "
        "Fast=2×, Turbo=3×, or pick your own factor (0.25–8).")
    t_launcher.pack_start(bsec("Animation Speed"), False, False, 0)
    t_launcher.pack_start(speed_row, False, False, 0)

    # NEU: Animation.Selection (Flicker/Fade) - siehe Settings.json/
    # TrafkTuxLauncher.c: steuert, wie der Launcher beim Auswahl-
    # wechsel zwischen den Bubbles überblendet - Flicker = Glühlampen-
    # Flackern (Default), Fade = ruhiges Überblenden. Gleiches
    # Button-Muster wie "Animation Style" oben.
    selection_row = hbox(10)
    selection_row.set_halign(Gtk.Align.CENTER)
    selection_btns: dict = {}

    def _refresh_selection_btns(active_selection: str):
        for n, b in selection_btns.items():
            ctx = b.get_style_context()
            if n.lower() == active_selection.lower(): ctx.add_class("active")
            else:                                      ctx.remove_class("active")

    def _on_selection_click(_w, _name):
        def _apply():
            _write_launcher_settings(selection=_name)
        _refresh_selection_btns(_name)  # sofortiges visuelles Feedback
        apply_change(f"Launcher selection effect: {_name}", _apply,
                     on_status=_flash_appearance_status,
                     reset_fn=lambda: _refresh_selection_btns(_read_launcher_settings()["Selection"]))

    for name in ("Flicker", "Fade"):
        b = btn(name)
        b.connect("clicked", lambda _b, n=name: _on_selection_click(_b, n))
        selection_btns[name] = b
        selection_row.pack_start(b, False, False, 0)
    _refresh_selection_btns(_launcher_cur["Selection"])
    selection_row.set_tooltip_text(
        "Flicker: lightbulb-style flicker when the selection changes (default). "
        "Fade: calm crossfade instead.")
    t_launcher.pack_start(bsec("Selection Effect"), False, False, 0)
    t_launcher.pack_start(selection_row, False, False, 0)

    if not _launcher_settings_path().parent.is_dir():
        hint = Gtk.Label(
            label="No TrafkTuxLauncher config found yet — it will be "
                  "created on your first change here.")
        hint.set_line_wrap(True)
        hint.set_opacity(0.65)
        hint.get_style_context().add_class("caption")
        t_launcher.pack_start(hint, False, False, 4)

    # ══════════════════════ Tabs zusammensetzen ══════════════════════
    stack.add_named(t_sound,    "sound")
    stack.add_named(t_look,     "look")
    stack.add_named(t_lang,     "language")
    stack.add_named(t_wall,     "wallpapers")
    stack.add_named(t_launcher, "launcher")

    # 2 Zeilen statt 1 lange, gleiches Muster wie beim Security-Widget
    # (siehe dort) - 5 Tabs in einer Reihe wären entweder zu breit oder
    # würden auf schmaleren Bildschirmen umbrechen.
    tab_row_top = hbox(6)
    tab_row_top.set_halign(Gtk.Align.CENTER)
    tab_row_bottom = hbox(6)
    tab_row_bottom.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, tlabel, ticon, target_row in (
            ("sound", "Sound", "audio-volume-high-symbolic", tab_row_top),
            ("look", "Look", "preferences-desktop-theme-symbolic", tab_row_top),
            ("language", "Language", "preferences-desktop-locale-symbolic", tab_row_top),
            ("wallpapers", "Wallpapers", "preferences-desktop-wallpaper-symbolic", tab_row_bottom),
            ("launcher", "Launcher", "system-run-symbolic", tab_row_bottom)):
        b = btn(tlabel, active=(name == "sound"))
        b.set_image(Gtk.Image.new_from_icon_name(ticon, Gtk.IconSize.BUTTON))
        b.set_always_show_image(True)
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        target_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("sound")

    page.pack_start(tab_row_top, True, False, 2)
    page.pack_start(tab_row_bottom, True, False, 0)
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
        # FIX: bisher wurde NUR die Datei geschrieben (wirkt erst nach
        # 'hyprctl reload'/Neustart) - kein Live-Apply. Jetzt zusätzlich
        # sofort per "hyprctl eval" gegen den laufenden Lua-State
        # anwenden, exakt dasselbe Muster wie effects_battery_enable/
        # disable() weiter oben (siehe _hypr_eval()-Kommentar). Fehler
        # hier werden bewusst NICHT den Rückgabewert kippen - die Datei
        # wurde korrekt geschrieben, das ist die "Quelle der Wahrheit";
        # schlägt nur das Live-Apply fehl, greift der neue Wert spätestens
        # beim nächsten Reload.
        _hypr_eval(
            "if hl.plugin.dynamic_cursors then hl.config({ plugin = "
            "{ dynamic_cursors = { enabled = " +
            ("true" if enabled else "false") + " } } }) end")
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
        # FIX ("Shake-to-find geht nicht mehr"): wie bei
        # _set_cursor_plugin_enabled() oben fehlte das Live-Apply
        # komplett - nur die Datei wurde geändert, Hyprland bekam davon
        # erst nach einem Reload etwas mit. Jetzt zusätzlich sofort per
        # "hyprctl eval" gesetzt.
        _hypr_eval(
            "if hl.plugin.dynamic_cursors then hl.config({ plugin = "
            "{ dynamic_cursors = { shake = { enabled = " +
            ("true" if enabled else "false") + " } } } }) end")
        return True, ""
    except Exception as e:
        return False, str(e)

def _hypr_monitors_live() -> list:
    return jrun(["hyprctl", "monitors", "-j"]) or []

def _parse_modes(modes: list) -> dict:
    """FIX (Zusatzblock, Punkt c): Hz-Werte jetzt immer als float
    normalisiert und einheitlich mit zwei Dezimalstellen zurückgegeben
    (z.B. sowohl "165Hz" als auch "165.00Hz" werden zu "165.00"). Vorher
    behielt hz.rstrip("Hz") den Rohtext bei - meldete Hyprland einen
    Modus ohne Dezimalstellen ("...@165Hz"), während cur_hz (siehe
    _fill_hz()-Aufrufstelle) als "165.00" gebildet wurde, stimmten die
    Strings nicht überein, die Vorauswahl schlug fehl und _fill_hz()
    fiel auf set_active(0) zurück - bei absteigend sortierter Liste
    also den HÖCHSTEN verfügbaren Wert statt des tatsächlich aktiven."""
    out: dict = {}
    for m in modes:
        try:
            res, hz = m.split("@")
            hz_clean = hz.rstrip("Hz").strip()
            hz_val = float(hz_clean)
            out.setdefault(res, []).append(f"{hz_val:.2f}")
        except (ValueError, IndexError):
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
    # FIX (vermutlich DER Hauptgrund, warum Hz>120 trotz der obigen
    # Regex-Fixes nie ankamen): edid-decodes Exit-Code spiegelt NICHT
    # "Parsen erfolgreich ja/nein" wider, sondern die Anzahl/Schwere
    # gefundener EDID-KONFORMITÄTS-Probleme (Warnings/Failures laut
    # eigener Doku) - und so gut wie jedes reale Monitor-EDID hat
    # IRGENDEINE kleine Nichtkonformität (Hersteller nehmen es mit dem
    # Standard oft nicht genau). "if ec != 0: return {}" hat also
    # praktisch IMMER den kompletten, vollständig und korrekt auf
    # stdout stehenden Output verworfen - die Regex-Fixes weiter unten
    # kamen dadurch nie zum Einsatz, selbst wenn das Monitor-EDID
    # bereits 144/165Hz-Timings sauber enthielt. Jetzt wird NUR NOCH
    # geprüft, ob überhaupt Output da ist - der Exit-Code selbst ist
    # für unseren reinen Lese-/Grep-Zweck irrelevant.
    if not out:
        return {}
    # Ein generelles Muster deckt ALLE Timing-Listen-Abschnitte ab
    # (Established Timings, Standard Timings, CTA Video Data Block
    # VICs, Detailed Timing Descriptors in Base-EDID UND CTA-
    # Extension) - alle folgen demselben Textformat
    # "WIDTHxHEIGHT   FLOAT Hz", nur mit unterschiedlichen Zeilen-
    # Präfixen (IBM/DMT/GTF/Apple/VIC/DTD). Verifiziert gegen echten
    # edid-decode-Output eines realen Monitors (siehe Kommentar oben).
    #
    # FIX (Zusatzblock, Punkt b): die Regex war zu eng gefasst - sie
    # verlangte zwingend Whitespace zwischen "WIDTHxHEIGHT" und dem
    # Hz-Wert sowie 1-9999 Pixel ohne Breiten-Begrenzung. edid-decode
    # gibt Timings aber auch als "1920x1080@165Hz" (ohne Leerzeichen,
    # mit "@") aus, und reine Ziffernfolgen ohne Breitenbegrenzung
    # können versehentlich auf Timing-fremden Text matchen. Jetzt:
    # Auflösungswerte auf plausible 3-5-stellige Pixelzahlen begrenzt
    # und ein optionales "@" (mit optionalem Whitespace drumherum)
    # zwischen Auflösung und Hz-Zahl zugelassen - deckt sowohl
    # "1920x1080  165.00 Hz" als auch "1920x1080@165Hz" ab.
    extra: dict = {}
    for m in re.finditer(r'(\d{3,5})x(\d{3,5})\s*(?:@\s*)?([\d.]+)\s*Hz', out):
        w, h, hz = m.group(1), m.group(2), m.group(3)
        res = f"{w}x{h}"
        try:
            hz_val = float(hz)
        except ValueError:
            continue
        hz_str = f"{hz_val:.2f}"
        extra.setdefault(res, set()).add(hz_str)
    return extra

def _write_hdr_fields(block_text: str, hdr_on: bool,
                       sdr_brightness: float = 1.0,
                       sdr_saturation: float = 1.0) -> str:
    """Fügt bitdepth/cm-Felder in einen bestehenden hl.monitor({...})-
    Blocktext ein bzw. aktualisiert sie, oder setzt sie explizit auf
    die Nicht-HDR-Standardwerte zurück (statt die Felder einfach zu
    entfernen - explizit "bitdepth=8, cm=srgb" ist klarer beim
    Nachlesen der Datei als ein stillschweigend fehlendes Feld).

    sdrbrightness/sdrsaturation (siehe Hyprland-Wiki "Colors and
    colorspaces") werden nach demselben Muster IMMER explizit gesetzt,
    nie weggelassen - dieselbe Begründung wie beim ursprünglichen
    bitdepth/cm-Bugfix oben: ein "hyprctl keyword monitor"-Aufruf ist
    ein Teil-Reconfigure, weggelassene Felder blieben sonst auf einem
    evtl. veralteten Wert von einem früheren Apply hängen. Bei
    ausgeschaltetem HDR werden sie auf 1.0 (= "unverändert", Hyprland-
    Default) zurückgesetzt statt entfernt."""
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

    sdr_bri_val = round(sdr_brightness if hdr_on else 1.0, 3)
    sdr_sat_val = round(sdr_saturation if hdr_on else 1.0, 3)
    if re.search(r'\bsdrbrightness\s*=', block_text):
        block_text = re.sub(r'sdrbrightness\s*=\s*[^,\n]+',
                             f'sdrbrightness = {sdr_bri_val}', block_text)
    else:
        block_text = re.sub(r'(\}\)\s*$)',
                             f'    sdrbrightness = {sdr_bri_val},\n\\1', block_text)
    if re.search(r'\bsdrsaturation\s*=', block_text):
        block_text = re.sub(r'sdrsaturation\s*=\s*[^,\n]+',
                             f'sdrsaturation = {sdr_sat_val}', block_text)
    else:
        block_text = re.sub(r'(\}\)\s*$)',
                             f'    sdrsaturation = {sdr_sat_val},\n\\1', block_text)
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
    # Redesign-Liste: "Unter Display eine fette Linie anstatt einer
    # dünnen. Andere Linien entfernen." + "Unter einem Display keine
    # Linie mehr - Bildschirm Label regelt das." - der einzige
    # verbleibende Strich auf dieser Seite ist der fette hub_sep()
    # direkt unter der Seiten-Überschrift (kommt vom generischen
    # Settings-Seiten-Rahmen); alle sep()-Trennstriche, die hier vorher
    # zwischen Auto-Rotate/den Monitor-Blöcken standen, sind weg - jeder
    # Monitor-Block grenzt sich jetzt über seine eigene, deutlich
    # sichtbare header_row (Icon+Name+HDR, siehe _build_monitor_row())
    # selbst genug vom nächsten ab.
    if rotation_up:
        page.pack_start(_build_autorotate_row(), False, False, 4)

    waybar_restart_id = [0]

    if len(monitors) == 1:
        # Einzelner Monitor: direkt ohne Tab-Bar anzeigen
        mon = monitors[0]
        header_row, row = _build_monitor_row(
            mon, monitors, lua_path, win, waybar_restart_id,
            rotation_map.get(mon.get("name", "?")) if rotation_up else None)
        page.pack_start(header_row, False, False, 6)
        page.pack_start(row, False, False, 0)
    else:
        # Mehrere Monitore: Standard-Tab-Pattern wie überall sonst im Programm
        # (btn()-Buttons + tab_sep() + Gtk.Stack) statt Gtk.Notebook.
        mon_stack = Gtk.Stack()
        mon_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        mon_stack.set_transition_duration(150)
        mon_stack.set_hhomogeneous(False)
        mon_stack.set_vhomogeneous(False)

        mon_tab_row = hbox(6)
        mon_tab_row.set_halign(Gtk.Align.CENTER)
        mon_tab_btns: dict = {}

        def _switch_mon(name):
            mon_stack.set_visible_child_name(name)
            for n, b in mon_tab_btns.items():
                ctx = b.get_style_context()
                if n == name: ctx.add_class("active")
                else:         ctx.remove_class("active")

        for i, mon in enumerate(monitors):
            mon_name = mon.get("name", "?")
            header_row, row = _build_monitor_row(
                mon, monitors, lua_path, win, waybar_restart_id,
                rotation_map.get(mon_name) if rotation_up else None)
            mon_page = vbox(4)
            mon_page.pack_start(header_row, False, False, 6)
            mon_page.pack_start(row, False, False, 0)
            mon_stack.add_named(mon_page, mon_name)

            tab_b = btn(mon_name, active=(i == 0))
            tab_b.connect("clicked", lambda _b, n=mon_name: _switch_mon(n))
            mon_tab_btns[mon_name] = tab_b
            mon_tab_row.pack_start(tab_b, False, False, 0)

        if monitors:
            mon_stack.set_visible_child_name(monitors[0].get("name", "?"))

        page.pack_start(mon_tab_row, False, False, 2)
        page.pack_start(tab_sep(), False, False, 0)
        page.pack_start(mon_stack, False, False, 0)

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

def _valid_scales_for_resolution(width: int, height: int) -> list[float]:
    """Gibt alle Scale-Werte zurück, bei denen sowohl width/scale als
    auch height/scale exakt ganzzahlig sind – nur diese Werte führen in
    Hyprland zu pixelgenauen, überlappungsfreien Monitor-Layouts.

    FIX (Analyse Punkt 1): die alte Brute-Force über beliebige
    rationale Zahlen p/q (q ≤ 20) ließ mathematisch gültige, aber für
    Hyprland UNGÜLTIGE Brüche wie 12/13 ≈ 0.9231 durch - Hyprland
    quantisiert Scales intern auf Vielfache von 1/120 und verlangt
    exakte Teilbarkeit beider Dimensionen durch genau diesen
    quantisierten Wert, nicht durch einen beliebigen anderen Bruch mit
    (zufällig) kleinem Nenner. Jetzt wird nur noch über n/120 iteriert
    (n von 60 bis 360, also exakt der von Hyprland tatsächlich
    verwendete Wertebereich 0.5–3.0 in 1/120-Schritten) - dieselbe
    Grundidee wie das externe PyPI-Paket `hyprland-monitors`
    (compute_valid_scales()), nur ohne zusätzliche Abhängigkeit und
    dafür selbst gepflegt."""
    seen: set[float] = set()
    valid: list[float] = []
    for n in range(60, 361):
        scale = n / 120
        key = round(scale, 4)
        if key in seen:
            continue
        lw = width / scale
        lh = height / scale
        if abs(lw - round(lw)) < 0.01 and abs(lh - round(lh)) < 0.01:
            seen.add(key)
            valid.append(key)
    # Auch die bounds prüfen
    lo, hi = _scale_bounds(height)
    valid = [s for s in valid if lo <= s <= hi]
    return sorted(valid) or [1.0]

def _repack_lua_positions(lua_txt: str,
                          live_mons: list[dict],
                          changed_name: str,
                          new_phys_w: int, new_phys_h: int,
                          new_scale: float) -> str:
    """Schreibt nach einer Scale-/Auflösungsänderung die Positionen
    ALLER Monitore im Lua-Text neu, damit keine Lücken oder Überlappungen
    entstehen.

    Hyprland-Positionskoordinaten sind logische Pixel (physical / scale).
    Wenn Monitor A seine Scale ändert, verändert sich seine logische Breite
    → alle Monitore die RECHTS/UNTER A sitzen, müssen verschoben werden.

    Unterstützt rein horizontale und rein vertikale Arrangements sowie
    Standard-Grid-Layouts. L-förmige Sonder-Setups werden nicht
    vollständig re-packed; es wird aber sichergestellt dass direkte
    Nachbarn des geänderten Monitors korrekt gesetzt werden.
    """
    import math as _math

    # Alle Monitore: starte mit live-Daten von hyprctl
    # (nach dem hyprctl-keyword-Apply schon aktuell).
    mon_data: dict[str, dict] = {}
    for m in live_mons:
        n = m.get("name", "")
        if not n:
            continue
        mon_data[n] = {
            "x":     int(m.get("x", 0)),
            "y":     int(m.get("y", 0)),
            "phys_w": int(m.get("width", 0)),
            "phys_h": int(m.get("height", 0)),
            "scale": float(m.get("scale", 1.0) or 1.0),
        }
    # Überschreibe den gerade geänderten Monitor mit den NEUEN Werten
    if changed_name in mon_data:
        mon_data[changed_name]["phys_w"] = new_phys_w
        mon_data[changed_name]["phys_h"] = new_phys_h
        mon_data[changed_name]["scale"]  = new_scale
    else:
        return lua_txt  # Monitor unbekannt → nichts tun

    def logical_size(n):
        d = mon_data.get(n, {})
        sc = d.get("scale", 1.0) or 1.0
        return (int(round(d.get("phys_w", 0) / sc)),
                int(round(d.get("phys_h", 0) / sc)))

    names = list(mon_data.keys())
    if len(names) <= 1:
        return lua_txt  # Nur ein Monitor → nichts zu re-packen

    # Bestimme ob Layout eher horizontal oder vertikal ist
    # (Tipp: größte x-Differenz vs größte y-Differenz)
    max_dx = max(mon_data[b]["x"] - mon_data[a]["x"]
                 for a in names for b in names)
    max_dy = max(mon_data[b]["y"] - mon_data[a]["y"]
                 for a in names for b in names)

    new_positions: dict[str, tuple[int, int]] = {}

    if max_dx >= max_dy:
        # ── Horizontales Layout (Monitors nebeneinander) ──────────────
        # Anchor ist der Monitor mit dem kleinsten x
        sorted_h = sorted(names, key=lambda n: mon_data[n]["x"])
        # Anchor bleibt an seiner y-Position; ab x=0 aufaddieren
        anchor_y = mon_data[sorted_h[0]]["y"]
        cursor_x = mon_data[sorted_h[0]]["x"]  # normalerweise 0
        for nm in sorted_h:
            lw, lh = logical_size(nm)
            new_positions[nm] = (cursor_x, mon_data[nm]["y"])
            cursor_x += lw
    else:
        # ── Vertikales Layout (Monitors übereinander) ─────────────────
        sorted_v = sorted(names, key=lambda n: mon_data[n]["y"])
        cursor_y = mon_data[sorted_v[0]]["y"]  # normalerweise 0
        for nm in sorted_v:
            lw, lh = logical_size(nm)
            new_positions[nm] = (mon_data[nm]["x"], cursor_y)
            cursor_y += lh

    # Lua-Text: für jeden Monitor dessen position-Zeile aktualisieren
    block_re = re.compile(r'(hl\.monitor\(\{[^}]*\}\))', re.S)
    def _patch_block(m):
        block = m.group(1)
        nm_m = re.search(r'output\s*=\s*"([^"]*)"', block)
        if not nm_m:
            return block
        nm = nm_m.group(1)
        if nm not in new_positions:
            return block
        px, py = new_positions[nm]
        old_pos = (mon_data[nm]["x"], mon_data[nm]["y"])
        if (px, py) == old_pos:
            return block  # keine Änderung nötig
        return re.sub(r'position\s*=\s*"[^"]*"',
                      f'position = "{px}x{py}"', block)
    return block_re.sub(_patch_block, lua_txt)

def _build_monitor_row(mon: dict, all_monitors: list, lua_path: Path, win: Gtk.Window,
                        waybar_restart_id: list,
                        rotation_transform: int | None = None) -> tuple[Gtk.Box, Gtk.Box]:
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

    # Hz ist jetzt ein ECHTES Dropdown, genau wie Res (Redesign-Wunsch:
    # "die Hz soll wie Res ein Dropdown sein") - vorher eine Reihe
    # einzelner Knöpfe (_SegmentedControl), die ursprünglich als
    # Touch-freundlicherer Ersatz für ein Dropdown mit wenigen Optionen
    # gedacht war (siehe _SegmentedControl-Docstring), das wird hier
    # jetzt aber ausdrücklich nicht mehr gewollt. Gtk.ComboBoxText hat
    # zufällig exakt dieselbe API, die _fill_hz() weiter unten schon
    # benutzt hat (remove_all/append_text/set_active/handler_block/
    # unblock/get_active_text) - _fill_hz() selbst bleibt dadurch
    # unverändert. "Custom... entfernen, das kommt jetzt, wenn man auf
    # die Hz drückt" ist damit auch automatisch erledigt: "Custom…" ist
    # jetzt einfach der letzte Dropdown-Eintrag, exakt wie bei Res.
    hz_combo = Gtk.ComboBoxText()
    hz_combo.get_style_context().add_class("bubble")
    hz_combo.get_style_context().add_class("dropdown")
    hz_combo.set_can_focus(False)
    # FIX (Zusatzblock, Punkt a): ein stiller Fallback auf eine
    # unvollständige Modusliste (weil edid-decode fehlt) ist keine
    # akzeptable Lösung - der Nutzer soll sehen, WARUM hohe
    # Bildwiederholraten evtl. fehlen, statt das für einen Bug zu
    # halten. Tooltip statt Statuszeile, damit das Dropdown selbst
    # nicht ständig eine zusätzliche Zeile Platz braucht.
    if not shutil.which("edid-decode"):
        hz_combo.set_tooltip_text(
            "'edid-decode' not found (package v4l-utils) — refresh "
            "rates reported only via Hyprland's own mode list are "
            "shown; some high refresh rates your monitor actually "
            "supports may be missing until v4l-utils is installed.")

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

    # Scale als Dropdown mit ausschließlich hyprland-sicheren Werten
    # (ganzzahlige logische Auflösung → kein Monitor-Überlappen).
    # Kein Slider + kein "Auto"-Haken mehr (Redesign + User-Feedback).
    _scale_valid_vals: list[float] = _valid_scales_for_resolution(
        int(cur_res.split("x")[0]), int(cur_res.split("x")[1]))
    _scale_auto_default = _auto_scale_for_height(int(cur_res.split("x")[1]))
    # Nächsten gültigen Wert zum aktuellen Scale vorauswählen
    def _nearest_valid_scale(target: float, vals: list[float]) -> int:
        if not vals:
            return 0
        return min(range(len(vals)), key=lambda i: abs(vals[i] - target))

    # REVERT: ein Gtk.Popover (ScrollablePopoverCombo, der vorherige
    # Versuch hier) rendert in diesem Setup KEINEN eigenen Hintergrund,
    # sondern zeigt einen Ausschnitt des manuell per Cairo gemalten
    # Bubble-Hintergrundbilds des Haupt-Fensters - vermutlich weil
    # Popover-GdkWindows hier (Layer-Shell + custom RGBA-Visual) nicht
    # denselben Compositing-Pfad wie ein normales Top-Level-Fenster
    # bekommen, und laut Nutzer-Hinweis trat exakt dieser Bug schon in
    # einer alten Version auf derselben Grundlage auf. Zurück zu
    # Gtk.ComboBoxText - die 1/120-Quantisierung in
    # _valid_scales_for_resolution() (siehe dort) hält die Liste
    # inzwischen ohnehin kurz genug, dass das alte "Popup wächst über
    # den Bildschirmrand"-Problem praktisch nicht mehr auftritt.
    scale_combo = Gtk.ComboBoxText()
    scale_combo.get_style_context().add_class("bubble")
    scale_combo.get_style_context().add_class("dropdown")
    scale_combo.set_can_focus(False)
    scale_combo.set_tooltip_text(
        "Only integer-logical-resolution scales are listed — "
        "these are guaranteed not to cause monitor overlap in Hyprland.")

    scale_handler_id = [None]

    def _fill_scale_combo(res_str: str, preselect: float = None):
        w_str, h_str = res_str.split("x")
        vals = _valid_scales_for_resolution(int(w_str), int(h_str))
        _scale_valid_vals[:] = vals
        if scale_handler_id[0] is not None:
            scale_combo.handler_block(scale_handler_id[0])
        try:
            scale_combo.remove_all()
            for v in vals:
                scale_combo.append_text(f"{v:g}×")
            target = preselect if preselect is not None else _auto_scale_for_height(int(h_str))
            idx = _nearest_valid_scale(target, vals)
            scale_combo.set_active(idx)
        finally:
            if scale_handler_id[0] is not None:
                scale_combo.handler_unblock(scale_handler_id[0])

    def _sync_scale_slider_range():
        """Beim Auflösungswechsel Scale-Dropdown neu befüllen."""
        target_res, _ = _resolve_res_hz()
        res = target_res or cur_res
        cur_txt = scale_combo.get_active_text() or ""
        try:
            cur_val = float(cur_txt.replace("×", "").strip())
        except ValueError:
            cur_val = cur_scale
        _fill_scale_combo(res, preselect=cur_val)

    _fill_scale_combo(cur_res, preselect=cur_scale)

    def _on_scale_combo(_w):
        _apply_now()

    scale_handler_id[0] = scale_combo.connect("changed", _on_scale_combo)

    # ── HDR ──────────────────────────────────────────────────────────
    # Hyprlands eigene hl.monitor({...})-Lua-DSL unterstützt HDR über
    # zwei Felder: bitdepth=10 + cm="hdr" (laut offizieller Hyprland-
    # Wiki-Doku zu Color Management). Startzustand wird aus
    # colorManagementPreset gelesen (liefert hyprctl bereits fertig -
    # "hdr"/"hdredid" heißt an, alles andere (z.B. "srgb") heißt aus).
    #
    # Redesign-Liste: "HDR ist nun einfach 'HDR' neben dem Label" - kein
    # Checkbox+Text-Paar mehr in einer eigenen Zeile, sondern ein
    # einzelnes klickbares Wort "HDR", das in der Kopfzeile direkt neben
    # dem (jetzt vergrößerten) Monitornamen sitzt - siehe header_row
    # ganz am Ende dieser Funktion, wo hdr_toggle tatsächlich platziert
    # wird. Zustand jetzt in hdr_state (statt Gtk.CheckButton.get_active()),
    # damit ein einfacher btn() genügt statt eines Checkbox-Widgets mit
    # eigenem Kästchen.
    hdr_state = {"on": mon.get("colorManagementPreset") in ("hdr", "hdredid")}
    hdr_toggle = btn("HDR", active=hdr_state["on"])
    hdr_toggle.set_tooltip_text(
        "10-bit color + HDR color management (bitdepth=10, cm=hdr). "
        "Needs display/cable support, otherwise no effect or worse image.")
    # BUGFIX ("keine richtigen HDR-Settings pro Monitor"): bisher war
    # HDR nur ein reiner An/Aus-Schalter (bitdepth+cm). Die Hyprland-
    # Wiki-Doku (Colors & Colorspaces) nennt sdrbrightness/
    # sdrsaturation als die eigentlichen PRO-MONITOR-Stellschrauben, um
    # SDR-Inhalte innerhalb eines aktiven HDR-Modus nutzbar hell/
    # gesättigt zu halten (Wiki-Beispiel: sdrbrightness=1.2,
    # sdrsaturation=0.98 - Default für beide ist 1.0 = unverändert).
    # Bewusst NUR diese beiden zusätzlich zu bitdepth/cm - andere HDR-
    # Felder wie sdr_max_luminance/sdr_min_luminance werden laut
    # bestätigtem Hyprland-Bug von "hyprctl keyword monitor" mit
    # "invalid syntax" abgelehnt und funktionieren nur über einen
    # kompletten Hyprland-Neustart mit der reinen Lua-Config - für ein
    # Live-Regler-UI hier also ungeeignet.
    #
    # Immer noch "nicht wirklich gut zum einstellen" (Feedback) - jetzt
    # mit eigenen, beschrifteten Zeilen statt zweier namenloser Slider
    # nebeneinander, damit klar ist, welcher Regler was tut, plus
    # Live-Prozentanzeige im Label selbst statt nur der reinen Zahl auf
    # dem Slider.
    sdr_bri_state = {"value": float(mon.get("sdrBrightness", 1.0) or 1.0)}
    sdr_sat_state = {"value": float(mon.get("sdrSaturation", 1.0) or 1.0)}

    sdr_bri_lbl = bsec(f'SDR brightness: {round(sdr_bri_state["value"] * 100)}%')
    sdr_bri_val_widget = sdr_bri_lbl.get_children()[0]
    sdr_bri_box, sdr_bri_slider = bslider(
        "", 0.5, 2.0, 0.05, sdr_bri_state["value"], cb=None, show_val=False)
    for ch in sdr_bri_box.get_children():
        if isinstance(ch, Gtk.Label):
            sdr_bri_box.remove(ch); break
    sdr_bri_box.set_halign(Gtk.Align.CENTER)
    sdr_bri_box.set_size_request(180, -1)

    sdr_sat_lbl = bsec(f'SDR saturation: {round(sdr_sat_state["value"] * 100)}%')
    sdr_sat_val_widget = sdr_sat_lbl.get_children()[0]
    sdr_sat_box, sdr_sat_slider = bslider(
        "", 0.5, 1.5, 0.05, sdr_sat_state["value"], cb=None, show_val=False)
    for ch in sdr_sat_box.get_children():
        if isinstance(ch, Gtk.Label):
            sdr_sat_box.remove(ch); break
    sdr_sat_box.set_halign(Gtk.Align.CENTER)
    sdr_sat_box.set_size_request(180, -1)

    sdr_col = vbox(1)
    sdr_col.pack_start(sdr_bri_lbl, False, False, 0)
    sdr_col.pack_start(sdr_bri_box, False, False, 0)
    sdr_col.pack_start(sdr_sat_lbl, False, False, 0)
    sdr_col.pack_start(sdr_sat_box, False, False, 0)

    _sdr_debounce_id = [0]

    def _on_sdr_change(_s=None):
        sdr_bri_state["value"] = round(sdr_bri_slider.get_value(), 3)
        sdr_sat_state["value"] = round(sdr_sat_slider.get_value(), 3)
        sdr_bri_val_widget.set_label(f'SDR BRIGHTNESS: {round(sdr_bri_state["value"] * 100)}%')
        sdr_sat_val_widget.set_label(f'SDR SATURATION: {round(sdr_sat_state["value"] * 100)}%')
        if _sdr_debounce_id[0]:
            GLib.source_remove(_sdr_debounce_id[0])
        def _fire():
            _sdr_debounce_id[0] = 0
            _apply_now()
            return False
        _sdr_debounce_id[0] = GLib.timeout_add(200, _fire)

    sdr_bri_slider.connect("value-changed", _on_sdr_change)
    sdr_sat_slider.connect("value-changed", _on_sdr_change)
    sdr_bri_slider.set_tooltip_text(
        "SDR brightness while HDR is active on this monitor (default 100%).")
    sdr_sat_slider.set_tooltip_text(
        "SDR saturation while HDR is active on this monitor (default 100%).")

    def _sync_sdr_sensitivity():
        sdr_col.set_sensitive(hdr_state["on"])

    def _set_hdr_ui(on: bool):
        hdr_state["on"] = on
        ctx = hdr_toggle.get_style_context()
        if on: ctx.add_class("active")
        else:  ctx.remove_class("active")
        _sync_sdr_sensitivity()

    def _on_hdr_toggle(_w):
        _set_hdr_ui(not hdr_state["on"])
        _apply_now()

    hdr_toggle.connect("clicked", _on_hdr_toggle)
    _sync_sdr_sensitivity()

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
        ("Manual", None, None)]
    for om in other_monitors:
        om_name = om.get("name", "?")
        for direction, dir_label in (("right", "→"), ("left", "←"),
                                       ("above", "↑"), ("below", "↓")):
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
                # FIX (Zusatzblock, Punkt c): vorher hier blind
                # set_active(0) bei fehlender EXAKTER Übereinstimmung -
                # da hzs absteigend sortiert ist, landete das faktisch
                # immer beim HÖCHSTEN verfügbaren Wert (z.B. 120 Hz
                # statt der tatsächlich aktiven 165 Hz), sobald sich
                # cur_hz/preselect und die geparsten Hz-Strings auch
                # nur in der Nachkommastellen-Formatierung
                # unterschieden. _parse_modes() normalisiert Hz-Werte
                # mittlerweile zwar schon einheitlich (siehe dort), als
                # zusätzliches Sicherheitsnetz hier trotzdem: bei
                # fehlender exakter Übereinstimmung den NÄCHSTGELEGENEN
                # Wert wählen statt stur den ersten/höchsten.
                try:
                    target = float(preselect)
                    idx = min(range(len(hzs)),
                              key=lambda i: abs(float(hzs[i]) - target))
                    hz_combo.set_active(idx)
                except (ValueError, TypeError):
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
        _apply_now(confirm_after=not _suppress_confirm[0])

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
        _apply_now(confirm_after=not _suppress_confirm[0])

    res_val_lbl.connect("clicked", lambda _w: _on_res_custom_selected())
    hz_val_lbl.connect("clicked", lambda _w: _on_hz_custom_selected())

    if cur_res in res_list:
        res_combo.set_active(res_list.index(cur_res))
    _fill_hz(cur_res if cur_res in res_list
             else (res_list[0] if res_list else ""), preselect=cur_hz)
    _update_custom_visibility()

    orig = [cur_res, cur_hz, cur_scale, None, hdr_state["on"], 0,
            sdr_bri_state["value"], sdr_sat_state["value"]]

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
        txt = (scale_combo.get_active_text() or "").replace("×", "").strip()
        try:
            val = float(txt)
            return val if val > 0 else None
        except ValueError:
            return None

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
        hdr_on = hdr_state["on"]

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
            # sdrbrightness/sdrsaturation sind laut bestätigtem Hyprland-
            # Verhalten (anders als sdr_max_luminance/sdr_min_luminance,
            # die "hyprctl keyword monitor" mit "invalid syntax"
            # ablehnt) auch über die kommagetrennte Keyword-Syntax
            # akzeptiert - werden also, genau wie bitdepth/cm, bei JEDEM
            # Apply explizit mitgeschickt (aus = 1.0/1.0, siehe
            # _write_hdr_fields()-Docstring für die Begründung).
            sdr_bri = round(sdr_bri_state["value"] if hdr_on else 1.0, 3)
            sdr_sat = round(sdr_sat_state["value"] if hdr_on else 1.0, 3)
            # FIX (Display-Tab "applied nix"): "hyprctl keyword monitor" ist
            # der ALTE hyprlang-Kompatibilitäts-Shim. Gegen eine Lua-Config
            # (hyprland.lua, hl.*-API) ist das laut Hyprland-Wiki
            # ("Configuring/Advanced-and-Cool/Using-hyprctl") kein
            # zuverlässiger Weg mehr, live etwas zu setzen - das Keyword
            # schreibt oft klaglos "ok" obwohl de facto nichts angewendet
            # wird, weil die Lua-Config beim nächsten internen Reload den
            # alten Lua-Zustand wiederherstellt. Der korrekte Weg unter
            # Hyprland 0.65.2+ mit Lua-Config ist "hyprctl eval <lua>", das
            # GEGEN DENSELBEN persistenten Lua-State läuft wie die Config
            # selbst (siehe _hypr_eval()-Docstring/Kommentar oben, bereits
            # so für effects_battery_enable/disable() verwendet) - hier also
            # dieselbe hl.monitor({...})-Tabellen-Syntax wie in hyprland.lua.
            if hdr_on:
                monitor_lua = (
                    "hl.monitor({ output = \"" + name + "\", "
                    "mode = \"" + mode + "\", "
                    f"position = \"{pos_x}x{pos_y}\", "
                    f"scale = {scale}, "
                    "bitdepth = 10, cm = \"hdr\", "
                    f"sdrbrightness = {sdr_bri}, sdrsaturation = {sdr_sat} }})"
                )
            else:
                monitor_lua = (
                    "hl.monitor({ output = \"" + name + "\", "
                    "mode = \"" + mode + "\", "
                    f"position = \"{pos_x}x{pos_y}\", "
                    f"scale = {scale}, "
                    "bitdepth = 8, cm = \"srgb\", "
                    f"sdrbrightness = {sdr_bri}, sdrsaturation = {sdr_sat} }})"
                )
            out, err, rc = _hypr_eval(monitor_lua)
            if rc != 0 or err or "error" in (out or "").lower():
                raise RuntimeError(
                    f"hyprctl eval rejected monitor command: {(err or out or 'unknown error')[:160]}")

            # Zweiter Eval-Aufruf wie zuvor beim "keyword"-Pfad: manche
            # Treiber/Monitore brauchen laut bestätigtem Hyprland-Verhalten
            # einen kurzen Moment + einen zweiten Reconfigure-Stoß, bis
            # Scale/Mode tatsächlich greifen (siehe time.sleep(0.2) unten -
            # unverändert aus dem alten Code übernommen).
            time.sleep(0.2)
            _hypr_eval(monitor_lua)

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
                    new_block = _write_hdr_fields(new_block, hdr_on,
                                                   sdr_bri_state["value"],
                                                   sdr_sat_state["value"])
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
                        new_block_lines.append(
                            f'    sdrbrightness = {round(sdr_bri_state["value"], 3)},')
                        new_block_lines.append(
                            f'    sdrsaturation = {round(sdr_sat_state["value"], 3)},')
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
                # ── Positions aller Monitore neu berechnen ─────────────
                # Jetzt wo der geänderte Monitor in Lua + live korrekt ist,
                # sicherstellen dass NACHBAR-Monitore nicht mehr überlappen.
                # _repack_lua_positions() liest die aktuellen hyprctl-Daten
                # (actual) und schreibt alle position-Zeilen im Lua-Text neu.
                new_w_str, new_h_str = res.split("x")
                txt = _repack_lua_positions(
                    txt, actual,
                    name, int(new_w_str), int(new_h_str), scale)
                atomic_write_text(lua_path, txt)

                # Nachbar-Positionen auch live per hyprctl setzen, damit
                # Hyprland sofort reagiert und nicht erst beim nächsten Reload.
                #
                # FIX (Analyse Punkt 2 - "Hyprland beschwert sich weiterhin"):
                # vorher wurde hier für JEDEN Nachbarn einzeln _hypr_eval()
                # aufgerufen - Hyprland führt nach JEDEM einzelnen
                # "hyprctl eval"-Aufruf seinen Layout-Check durch und sah
                # dabei zwischen zwei Nachbarn einen inkonsistenten
                # Zwischenzustand (ein Nachbar schon an neuer Position, der
                # nächste noch an der alten, jetzt dazu nicht mehr passenden
                # Position). Die eigentliche Positions-MATHEMATIK in
                # _repack_lua_positions() war bereits korrekt, nur die
                # Anwendungs-Reihenfolge nicht. Jetzt: alle hl.monitor(...)-
                # Aufrufe für die Nachbarn werden gesammelt und als EIN
                # einziger Lua-Chunk in EINEM "hyprctl eval"-Aufruf
                # geschickt - "hyprctl eval" nimmt einen ganzen Lua-
                # Codeblock entgegen, mehrere hl.monitor()-Aufrufe lassen
                # sich also zu einem String verketten. Dadurch validiert
                # Hyprland das Layout genau einmal, gegen den bereits
                # vollständig konsistenten Endzustand aller Nachbarn - nicht
                # mehrfach gegen Zwischenzustände.
                neighbor_block_re = re.compile(
                    r'hl\.monitor\(\{[^}]*\}\)', re.S)
                out_name_re = re.compile(r'output\s*=\s*"([^"]*)"')
                mode_re     = re.compile(r'mode\s*=\s*"([^"]*)"')
                pos_re      = re.compile(r'position\s*=\s*"([^"]*)"')
                sc_re       = re.compile(r'scale\s*=\s*([0-9.]+)')
                nb_lua_statements: list[str] = []
                for nb in neighbor_block_re.finditer(txt):
                    blk = nb.group(0)
                    nm_m = out_name_re.search(blk)
                    if not nm_m or nm_m.group(1) == name:
                        continue  # skip the monitor we just did
                    nb_name = nm_m.group(1)
                    _mm = mode_re.search(blk)
                    _pm = pos_re.search(blk)
                    _sm = sc_re.search(blk)
                    nb_mode = _mm.group(1) if _mm else ""
                    nb_pos  = _pm.group(1) if _pm else "0x0"
                    nb_sc   = _sm.group(1) if _sm else "1"
                    if not nb_mode:
                        continue
                    # Gleicher Fix wie oben: "keyword" durch "eval" +
                    # hl.monitor({...}) ersetzt, siehe Kommentar beim
                    # primären monitor_lua-Aufruf weiter oben.
                    nb_lua_statements.append(
                        "hl.monitor({ output = \"" + nb_name + "\", "
                        "mode = \"" + nb_mode + "\", "
                        f"position = \"{nb_pos}\", "
                        f"scale = {nb_sc} }})"
                    )
                if nb_lua_statements:
                    # EIN Aufruf, EIN Lua-Chunk mit allen Nachbarn drin -
                    # statt eines Aufrufs pro Monitor (siehe Kommentar oben).
                    _hypr_eval("\n".join(nb_lua_statements))

            orig[0], orig[1] = res, hz
            orig[2] = scale
            orig[4], orig[5] = hdr_on, pos_combo.get_active()
            orig[6], orig[7] = sdr_bri_state["value"], sdr_sat_state["value"]

    def _reset():
        if orig[0] in res_list:
            res_combo.set_active(res_list.index(orig[0]))
        else:
            res_combo.set_active(len(res_list))
            custom_state["res"] = orig[0]
        _fill_hz(orig[0] if orig[0] in res_list else "", preselect=orig[1])
        if orig[0] not in res_list or orig[1] not in modes.get(orig[0], []):
            hz_combo.set_active(hz_combo.get_model().iter_n_children(None) - 1)
            custom_state["hz"] = orig[1]
        _fill_scale_combo(orig[0], preselect=orig[2])
        _set_hdr_ui(orig[4])
        pos_combo.set_active(orig[5])
        sdr_bri_state["value"], sdr_sat_state["value"] = orig[6], orig[7]
        sdr_bri_slider.set_value(orig[6])
        sdr_sat_slider.set_value(orig[7])
        _sync_sdr_sensitivity()
        _update_custom_visibility()

    # ── Bestätigungs-Dialog nach Auflösungs-/Hz-Änderungen ───────────
    # Klassisches Verhalten wie bei Windows/macOS/GNOME-Monitor-
    # Einstellungen: nach einer Res/Hz-Änderung 35 Sekunden Zeit, die
    # neue Einstellung zu bestätigen ("Keep changes") - bestätigt der
    # Nutzer nicht aktiv, wird automatisch auf die zuletzt erfolgreich
    # angewendeten Werte zurückgesetzt. Schützt davor, sich mit einer
    # falschen Auflösung/Bildwiederholrate (schwarzes Bild, kein Signal
    # mehr, Maus/Tastatur aber auch kein Zugriff auf den Dialog selbst)
    # komplett auszusperren. Bewusst NUR für Res/Hz, nicht für Scale/
    # HDR/Position/SDR - die können zwar auch optisch danebengehen,
    # aber nicht "kein Bild mehr"-artig komplett aussperren.
    _suppress_confirm = [False]

    def _do_revert(snapshot: list):
        """snapshot ist eine Kopie von orig() VOR der jetzt zu
        verwerfenden Änderung. _suppress_confirm verhindert, dass die
        durch _reset() ausgelöste res_combo-"changed"-Kaskade (siehe
        _on_res_change() unten) selbst wieder einen neuen
        Bestätigungsdialog für den Revert öffnet. Der explizite
        _apply_now()-Aufruf am Ende ist nötig, weil _fill_hz() (von
        _reset() aufgerufen) hz_combos eigenen "changed"-Handler
        absichtlich blockt (siehe dort) - bei einer reinen Hz-Änderung
        (Auflösung unverändert) würde sonst NICHTS den Revert
        tatsächlich an hyprctl schicken, nur die UI würde sich
        zurücksetzen."""
        _suppress_confirm[0] = True
        try:
            orig[:] = snapshot
            _reset()
            _apply_now()
        finally:
            _suppress_confirm[0] = False

    def _start_confirm_flow(snapshot: list):
        res, hz = _resolve_res_hz()
        dlg = Gtk.MessageDialog(
            transient_for=win, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Keep this display setting?")
        dlg.set_keep_above(True)
        dlg.add_buttons("Revert", Gtk.ResponseType.CANCEL,
                        "Keep changes", Gtk.ResponseType.OK)
        seconds_left = [35]

        def _update_secondary():
            dlg.format_secondary_text(
                f"{name}: {res or '?'}@{hz or '?'}Hz\n\n"
                f"Reverting automatically in {seconds_left[0]}s "
                "if you don't confirm.")
        _update_secondary()

        def _tick():
            seconds_left[0] -= 1
            if seconds_left[0] <= 0:
                dlg.response(Gtk.ResponseType.CANCEL)
                return False
            _update_secondary()
            return True
        # GLib.timeout_add tickt auch INNERHALB der verschachtelten
        # Main-Loop von dlg.run() weiter (run() verarbeitet den
        # Default-Main-Context ganz normal mit) - kein separater Thread
        # nötig.
        tick_id = GLib.timeout_add(1000, _tick)

        resp = dlg.run()
        GLib.source_remove(tick_id)
        dlg.destroy()

        if resp != Gtk.ResponseType.OK:
            _do_revert(snapshot)

    def _apply_now(confirm_after: bool = False):
        _update_custom_visibility()
        res, hz = _resolve_res_hz()
        scale_txt = (scale_combo.get_active_text() or "?").replace("×", "").strip()
        extras = []
        if hdr_state["on"]:
            extras.append("HDR")
        if pos_combo.get_active() > 0:
            extras.append(pos_combo.get_active_text())
        extra_txt = f", {', '.join(extras)}" if extras else ""
        desc = f"{name}: {res or '?'}@{hz or '?'}Hz, scale={scale_txt}{extra_txt}"

        # Snapshot JETZT nehmen (bevor _apply() im Erfolgsfall orig auf
        # die NEUEN Werte überschreibt, siehe orig[0], orig[1] = res, hz
        # weiter oben) - sonst wäre der "vorherige" Stand beim Revert
        # schon mit dem gerade erst applizierten identisch.
        pending_snapshot = list(orig) if confirm_after else None

        def _on_status(text):
            _flash_status(text)
            if pending_snapshot is not None and not text.startswith("Error"):
                _start_confirm_flow(pending_snapshot)

        apply_change(desc, _apply,
                     on_status=_on_status if pending_snapshot is not None else _flash_status,
                     reset_fn=_reset)

    def _on_res_change(_w):
        if res_combo.get_active_text() != CUSTOM_LABEL:
            _fill_hz(res_combo.get_active_text())
            _update_custom_visibility()
            _sync_scale_slider_range()
            _apply_now(confirm_after=not _suppress_confirm[0])
        else:
            _on_res_custom_selected()

    def _on_hz_change(_w):
        if hz_combo.get_active_text() != CUSTOM_LABEL:
            _update_custom_visibility()
            _apply_now(confirm_after=not _suppress_confirm[0])
        else:
            _on_hz_custom_selected()

    res_combo.connect("changed", _on_res_change)
    hz_handler_id[0] = hz_combo.connect("changed", _on_hz_change)

    # Scale-Zeile: Icon + Dropdown nebeneinander, zentriert
    scale_row_lbl = Gtk.Image.new_from_icon_name("zoom-fit-best-symbolic", Gtk.IconSize.BUTTON)
    scale_row_lbl.get_style_context().add_class("bubble")
    scale_row_lbl.set_opacity(0.7)
    scale_row = hbox(8)
    scale_row.set_halign(Gtk.Align.CENTER)
    scale_row.pack_start(scale_row_lbl, False, False, 0)
    scale_row.pack_start(scale_combo, False, False, 0)

    combos_row = hrow(res_combo, hz_combo, sp=8)
    custom_row = hrow(res_val_lbl, hz_val_lbl, sp=8)
    # Redesign-Liste: "Position: kein Label mehr, nur die Box - die
    # etwas verkürzt wird" + "Rotation: nun wieder eine Box wie
    # Position - wird rechts neben Position hingepackt, 2 Boxen in der
    # selben Zeile" - pos_combo wird hier bewusst NOCH NICHT in eine
    # Zeile gepackt, das passiert erst weiter unten zusammen mit
    # rot_combo (falls der Rotation-Daemon für diesen Monitor
    # verfügbar ist), siehe pos_rot_row.
    pos_combo.set_size_request(150, -1)
    wrap = vbox(6)
    wrap.pack_start(combos_row, False, False, 0)
    wrap.pack_start(custom_row, False, False, 0)
    wrap.pack_start(scale_row, False, False, 0)
    wrap.pack_start(sdr_col, False, False, 0)
    wrap.pack_start(status_lbl, False, False, 0)

    # ── Position + Rotation ───────────────────────────────────────────
    # Redesign-Liste: "Rotation: nun wieder eine Box wie Position - wird
    # rechts neben Position hingepackt, 2 Boxen in der selben Zeile."
    # Rotation läuft NICHT über "hyprctl keyword monitor" + hyprland.
    # lua-Textersetzung wie Auflösung/Scale/HDR/Position, sondern über
    # den eigenen ScreenRotationDaemon-Socket (siehe Kommentar bei
    # _rotation_socket_cmd()) - bewusst NICHT in _apply() mit reinge-
    # zogen, sondern eigenständig behandelt, auch damit ein Rotations-
    # Fehler nie eine Resolution/Scale-Änderung blockiert oder
    # umgekehrt. Nur angeboten, wenn der Rotation-Daemon diesen Monitor
    # tatsächlich kennt - sonst bleibt Position allein in der Zeile,
    # keine leere zweite Box.
    pos_rot_row = hrow(pos_combo, sp=8)
    rot_status_lbl = Gtk.Label(label="")
    rot_status_lbl.get_style_context().add_class("caption")
    rot_status_lbl.set_opacity(0.75)
    rot_status_lbl.set_no_show_all(True)
    rot_status_lbl.hide()

    if rotation_transform is not None:
        def _flash_rot(text: str, ms: int = 2500):
            rot_status_lbl.set_label(text)
            rot_status_lbl.show()
            GLib.timeout_add(ms, lambda: (rot_status_lbl.hide(), False)[1])

        rot_state = {"current": rotation_transform}

        # "nun wieder eine Box wie Position" - echtes Dropdown statt des
        # vorherigen Zieh-Reglers (der Slider war selbst schon eine
        # frühere Abkehr von genau so einer Box, siehe README-Verweis
        # oben bei _SegmentedControl - jetzt per explizitem Wunsch
        # wieder zurück).
        rot_combo = Gtk.ComboBoxText()
        rot_combo.get_style_context().add_class("bubble")
        rot_combo.get_style_context().add_class("dropdown")
        rot_combo.set_can_focus(False)
        rot_combo.set_size_request(110, -1)
        for _val, _lbl in _ROTATIONS:
            rot_combo.append_text(_lbl)
        rot_combo.set_active(rotation_transform)
        rot_combo.set_tooltip_text("Rotate this monitor in 90° steps.")

        def _apply_rotation(value: int, prev: int):
            def _apply():
                ok, msg = _rotation_set(name, value)
                if not ok:
                    raise RuntimeError(msg)

            def _reset():
                rot_state["current"] = prev
                rot_combo.handler_block(rot_handler_id)
                rot_combo.set_active(prev)
                rot_combo.handler_unblock(rot_handler_id)

            apply_change(f"{name}: rotate {value * 90}°",
                         _apply, on_status=_flash_rot, reset_fn=_reset)

        def _on_rot_change(_w):
            new_val = rot_combo.get_active()
            if new_val < 0 or new_val == rot_state["current"]:
                return
            prev = rot_state["current"]
            rot_state["current"] = new_val
            _apply_rotation(new_val, prev)

        rot_handler_id = rot_combo.connect("changed", _on_rot_change)
        pos_rot_row.pack_start(rot_combo, False, False, 0)

    wrap.pack_start(pos_rot_row, False, False, 0)
    wrap.pack_start(rot_status_lbl, False, False, 0)

    # ── Kopfzeile: Icon + Monitorname (vergrößert) + HDR-Toggle ──────
    # Redesign-Liste: "Ein einzelnes Icon neben dem Label des Monitors.
    # Label des Monitors vergrößern." + "HDR ist nun einfach 'HDR'
    # neben dem Label." Ersetzt das simple bsec(mon_name.upper()) aus
    # _build_settings_display() komplett - "Bildschirm Label regelt
    # das" (Redesign-Liste, zum Wegfall der Trennstriche zwischen den
    # Monitor-Blöcken): diese Kopfzeile übernimmt jetzt selbst die
    # optische Abgrenzung zum nächsten Monitor-Block, kein sep() mehr
    # nötig.
    header_row = hbox(8)
    header_row.set_halign(Gtk.Align.CENTER)
    mon_icon_lbl = Gtk.Label(label="󰍹")
    mon_icon_lbl.get_style_context().add_class("icon-lg")
    mon_name_lbl = Gtk.Label(label=name)
    mon_name_lbl.get_style_context().add_class("value-lg")
    header_row.pack_start(mon_icon_lbl, False, False, 0)
    header_row.pack_start(mon_name_lbl, False, False, 0)
    header_row.pack_start(hdr_toggle, False, False, 0)

    return header_row, wrap

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
    ("apps",       "󱁤", "Apps & Shortcuts", "Launcher editor, Config files"),
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

def _run_maybe_priv_force(cmd: list, timeout: int = 10) -> tuple[bool, str]:
    """Wie _run_maybe_priv(), aber OHNE die stderr-Text-Heuristik: wird
    nur für Kommandos benutzt, bei denen bereits der unprivilegierte
    Versuch gelaufen und fehlgeschlagen ist (der Aufrufer prüft das
    selbst) - eskaliert dann bedingungslos mit pkexec, statt sich
    darauf zu verlassen, dass die Fehlermeldung zu einem der bekannten
    "Permission denied"-artigen Muster passt. Siehe _rfkill_set()-
    Kommentar für den konkreten Bug, den das behebt."""
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
    cmd = ["rfkill", "block" if blocked else "unblock", rf_type]
    out, err, ec = run_ec(cmd)
    if ec == 0:
        return True, out
    # FIX ("es kommt kein sudo-Popup, weswegen man so oder so nix
    # blockieren kann"): _run_maybe_priv() eskaliert nur auf pkexec,
    # wenn die stderr-Meldung gegen eine feste Liste bekannter
    # Permission-Formulierungen passt - rfkill meldet auf manchen
    # Systemen/Versionen aber gar KEINEN Text, der da reinpasst (z.B.
    # einfach einen stillen Fehlschlag ohne "permission"/"root"/etc. im
    # Wortlaut), wodurch needs_root nie True wurde und pkexec NIE
    # aufgerufen wurde - der Passwort-Dialog kam folglich nie,
    # unabhängig vom UI-Zustand. Genau wie bei der Kamera
    # (_camera_set_blocked(), siehe deren Kommentar) wird jetzt bei
    # JEDEM Fehlschlag bedingungslos mit pkexec eskaliert, statt sich
    # auf eine Text-Heuristik zu verlassen.
    return _run_maybe_priv_force(cmd)

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
    # Versuch würde also ohnehin garantiert scheitern. FIX: vorher wurde
    # hier trotz dieses Kommentars noch die heuristik-basierte
    # _run_maybe_priv() aufgerufen (Docstring/Code-Widerspruch) - jetzt
    # wie _rfkill_set()/_freshclam_update() konsequent auf
    # _run_maybe_priv_force() umgestellt, kein garantiert scheiternder
    # erster Versuch mehr pro Kamera-Toggle.
    return _run_maybe_priv_force(["chmod", mode, *devs], timeout=15)

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

    panic_btn = btn("Everything")
    panic_btn.set_image(Gtk.Image.new_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.BUTTON))
    panic_btn.set_always_show_image(True)
    panic_btn.set_hexpand(True)
    panic_btn.set_tooltip_text(
        "Immediately blocks Wi-Fi, Bluetooth, WWAN/GPS, Camera and "
        "Microphone all at once (meeting-mode style).")

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
            # FIX ("die sachen die nicht blockiert sind, sollten
            # leuchten, nicht die blockierten"): "active"-Klasse (Glow)
            # wird jetzt für NICHT-blockierte/erlaubte Zustände gesetzt,
            # nicht mehr für blockierte - vorher exakt umgekehrt.
            state = _rfkill_state(rf_type)
            ctx = b.get_style_context()
            if state == "missing":
                b.set_sensitive(False)
                ctx.remove_class("active")
                b.set_tooltip_text("No adapter found")
            elif state == "hard-blocked":
                b.set_sensitive(False)
                ctx.remove_class("active")
                b.set_tooltip_text(
                    "Blocked by a physical switch/airplane-mode key - "
                    "can't be re-enabled from software.")
            else:
                b.set_sensitive(True)
                blocked = state == "soft-blocked"
                if blocked: ctx.remove_class("active")
                else:       ctx.add_class("active")
                b.set_tooltip_text("Tap to " + ("allow" if blocked else "block"))

        def _on_click(_w):
            state = _rfkill_state(rf_type)
            if state in ("missing", "hard-blocked"):
                return
            new_blocked = state != "soft-blocked"
            ctx = b.get_style_context()
            # Optimistisches UI-Update spiegelt dieselbe Umkehr wie
            # _refresh() oben: glow = erlaubt, nicht blockiert.
            if new_blocked: ctx.remove_class("active")
            else:           ctx.add_class("active")
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
                        missing_tip: str = "Not found", icon_name: str = None) -> Gtk.Button:
        # icon_name: echtes Icon-Theme-Icon statt Nerd-Font-Glyph im
        # Label-Text (für Fälle ohne verlässliches Nerd-Font-Symbol zur
        # Hand, siehe Touchpad/Touchscreen weiter unten) - icon bleibt
        # das bisherige Verhalten für Camera/Mic.
        if icon_name:
            b = btn(label_text)
            b.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
            b.set_always_show_image(True)
        else:
            b = btn(f"{icon}  {label_text}")
        b.set_hexpand(True)

        def _refresh():
            # FIX: siehe _make_rfkill_row() oben - glow ("active") zeigt
            # jetzt "nicht blockiert/erlaubt" statt "blockiert" an.
            blocked = get_blocked()
            ctx = b.get_style_context()
            if blocked is None:
                b.set_sensitive(False)
                ctx.remove_class("active")
                b.set_tooltip_text(missing_tip)
                return
            b.set_sensitive(True)
            if blocked: ctx.remove_class("active")
            else:       ctx.add_class("active")
            b.set_tooltip_text("Tap to " + ("allow" if blocked else "block"))

        def _on_click(_w):
            cur = get_blocked()
            if cur is None:
                return
            new_val = not cur
            ctx = b.get_style_context()
            if new_val: ctx.remove_class("active")
            else:       ctx.add_class("active")
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
        "", "Touchpad", _touchpad_blocked, _touchpad_set_blocked,
        missing_tip="No touchpad found", icon_name="input-touchpad-symbolic"))
    _privacy_rows.append(_make_bool_row(
        "", "Touchscreen", _touchscreen_blocked, _touchscreen_set_blocked,
        missing_tip="No touchscreen found", icon_name="input-touchscreen-symbolic"))
    # "Der Lock everything Button ist noch 'Everything' mit Emoji und
    # kommt rechts von Touchscreen hin" - Touchscreen ist der 7. (also
    # ungerade) Eintrag in _privacy_rows, hätte in der 2er-Paarung
    # unten sonst keinen Partner in seiner Zeile; panic_btn füllt genau
    # diese Lücke, statt wie vorher als eigene Zeile ganz oben zu
    # stehen.
    _privacy_rows.append(panic_btn)

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
    # Redesign-Liste: "Keine Überschrift – keine Trennstriche" - die
    # vorherige btitle()+sep()-Kopfzeile UND der separate On/Off-Block
    # darüber sind beide weg. Status/Schalter lebt jetzt als eigener
    # Sub-Tab ("Firewall") neben Rules/Log (3 Sub-Tabs statt 2).
    root = vbox(4); pad(root, h=4, v=6)

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

    # ── 3 Sub-Tabs: Firewall (neu) / Rules / Log ──────────────────────
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── Sub-Tab: Firewall - "Label: 'Firewall' mit dem grünen/roten
    # Symbol dazu - label button zum ein-aus schalten". Ein einziger
    # klickbarer Button trägt Name+Status-Punkt zusammen, kein
    # separates Label+Toggle-Paar mehr (gleiches Muster wie überall
    # sonst in diesem Redesign-Durchgang).
    t_fw = vbox(4); pad(t_fw, h=4, v=10)
    fw_row = hbox(8)
    fw_row.set_halign(Gtk.Align.CENTER)
    onoff_toggle = btn("Firewall — Off")
    refresh_b = Gtk.Button(label="󰑐")
    refresh_b.set_relief(Gtk.ReliefStyle.NONE)
    refresh_b.get_style_context().add_class("flat")
    refresh_b.set_opacity(0.7)
    refresh_b.set_tooltip_text("Refresh status")
    fw_row.pack_start(onoff_toggle, False, False, 0)
    fw_row.pack_start(refresh_b, False, False, 0)
    t_fw.pack_start(fw_row, False, False, 0)

    t_rules = vbox(3)
    rules_sw, rules_box = scroll_box(200)
    t_rules.pack_start(rules_sw, False, False, 0)
    add_row_btn = btn("Add rule")
    add_row_btn.set_image(Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON))
    add_row_btn.set_always_show_image(True)
    t_rules.pack_start(add_row_btn, False, False, 0)

    t_log = vbox(3)
    log_sw, log_box = scroll_box(240)
    t_log.pack_start(log_sw, False, False, 0)
    refresh_log_btn = btn("󰑐  Refresh log")
    t_log.pack_start(refresh_log_btn, False, False, 0)

    stack.add_named(t_fw,    "firewall")
    stack.add_named(t_rules, "rules")
    stack.add_named(t_log,   "log")

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

    for tname, tlabel in (("firewall", "Firewall"), ("rules", "Rules"),
                           ("log", "Log")):
        tb = btn(tlabel, active=(tname == "firewall"))
        tb.connect("clicked", lambda _b, n=tname: _switch_ufw_tab(n))
        tab_btns[tname] = tb
        tab_row.pack_start(tb, False, False, 0)
    stack.set_visible_child_name("firewall")

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
            if r["action"].upper().startswith("ALLOW"):
                action_icon_name = "emblem-ok-symbolic"
            elif r["action"].upper().startswith("LIMIT"):
                action_icon_name = "dialog-warning-symbolic"
            else:
                action_icon_name = "process-stop-symbolic"
            action_icon = Gtk.Image.new_from_icon_name(action_icon_name, Gtk.IconSize.MENU)
            action_icon.set_tooltip_text(r["action"])
            row.pack_start(action_icon, False, False, 0)
            lbl = Gtk.Label(
                label=f'{r["to"]}  ·  {r["action"]}  ·  from {r["from"]}')
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
        onoff_toggle.set_label("Firewall — On" if _state["active"] else "Firewall — Off")
        ctx = onoff_toggle.get_style_context()
        if _state["active"]: ctx.add_class("active")
        else:                ctx.remove_class("active")

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
        allow_toggle = btn("Allow", active=True)
        allow_toggle.set_image(Gtk.Image.new_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.BUTTON))
        allow_toggle.set_always_show_image(True)
        deny_toggle  = btn("Deny")
        deny_toggle.set_image(Gtk.Image.new_from_icon_name("process-stop-symbolic", Gtk.IconSize.BUTTON))
        deny_toggle.set_always_show_image(True)
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
    # Redesign-Liste: "Keine Überschrift - kein Strich."

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

    # "Connected as ... sollte viel größer sein und leuchten - wenn man
    # da drauf klickt, dann soll man auf die Tailscale-Seite kommen, wo
    # man sich auch abmelden kann und alles konfigurieren kann" - jetzt
    # ein klickbarer Button statt eines reinen Labels, öffnet die
    # Tailscale-Admin-Konsole im Standardbrowser (login.tailscale.com/
    # admin/machines - von dort aus lassen sich Geräte abmelden,
    # umbenennen, Exit-Nodes/ACLs konfigurieren usw., alles was
    # Tailscale selbst an Verwaltung anbietet).
    conn_lbl = Gtk.Button(label="Checking…")
    conn_lbl.set_relief(Gtk.ReliefStyle.NONE)
    conn_lbl.get_style_context().add_class("flat")
    conn_lbl.get_style_context().add_class("tailscale-conn-big")
    conn_lbl.set_can_focus(False)
    conn_lbl.set_halign(Gtk.Align.CENTER)
    conn_lbl.set_tooltip_text("Open the Tailscale admin console")
    conn_lbl.connect("clicked", lambda _w: subprocess.Popen(
        ["xdg-open", "https://login.tailscale.com/admin/machines"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
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
    autostart_toggle.get_style_context().add_class("compact-btn")
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
            dot = Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic" if p["online"] else "process-stop-symbolic",
                Gtk.IconSize.MENU)
            dot.set_tooltip_text("Online" if p["online"] else "Offline")
            row.pack_start(dot, False, False, 0)
            txt = p["name"] + (f'  ·  {p["ip"]}' if p["ip"] else "")
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
                    toggle.set_label("On" if on else "Off")
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
            toggle.set_label("On" if new_val else "Off")
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
    # BUGFIX (gemeldet: "im ClamAV-Tab ist noch immer die Überschrift
    # im Tab und der Trennstrich darunter") - kein anderer Sub-Tab
    # dieses Security-Widgets (Privacy/DNS/Tailscale/Firewall/
    # Authentication) wiederholt seinen eigenen Tab-Namen nochmal als
    # Überschrift IM Inhalt - der Tab-Button selbst sagt bereits
    # "ClamAV". btitle()+sep() hier waren redundant.

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
        label="Re-scans ~/Downloads on any change (not per-file).")
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
                autoscan_toggle.set_label("On" if enabled else "Off")
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

# ════════════════════════════════════════════════════════════
#  AUTHENTICATION (Analyse Punkt 3) — Password / Fingerprint / FIDO
#  Neuer Security-Sub-Tab. Alles, was auf einem normalen Linux-System
#  (PAM, fprintd, pam-u2f) technisch machbar ist, ohne Abstriche bei
#  der Funktionalität - siehe Analyse-Dokument für die recherchierten
#  Befehle/Optionen.
# ════════════════════════════════════════════════════════════

def _current_username() -> str:
    return os.environ.get("USER") or os.path.basename(HOME) or "user"

def _pam_target_file() -> Path:
    """Arch Linux (dieses Projekt läuft laut README/Analyse auf Arch)
    nutzt 'system-auth' als zentrale, von allen anderen PAM-Diensten
    per 'include'/'auth include system-auth' eingebundene Datei -
    genau dort gehören pam_fprintd.so/pam_u2f.so rein, damit sie für
    ALLE Dienste (Login, sudo, Display-Manager, …) gelten, nicht nur
    für einen einzelnen. Fällt die Datei doch nicht vorhanden sein
    (z.B. minimales/anders aufgesetztes System), auf '/etc/pam.d/sudo'
    zurückfallen (siehe Analyse) - gilt dann wenigstens für sudo."""
    sysauth = Path("/etc/pam.d/system-auth")
    if sysauth.is_file():
        return sysauth
    return Path("/etc/pam.d/sudo")

def _pam_write_privileged(path: Path, new_text: str) -> tuple[bool, str]:
    """Schreibt eine neue Version einer PAM-Datei root-privilegiert.
    Baut den neuen Inhalt vorher lokal als normaler User zusammen und
    kopiert ihn per 'pkexec cp' an die Zielposition, statt Nutzerdaten
    in einen sed/printf-Shell-Befehl für pkexec einzubetten (vermeidet
    Quoting-/Injection-Risiken bei Sonderzeichen).

    WICHTIG (siehe Analyse, Arch-Wiki-Warnung zu PAM): ruft IMMER
    zuerst backup_file() auf DIESER Datei auf - eine fehlerhafte
    PAM-Änderung kann den Nutzer aussperren, und ein pkexec-Dialog
    ersetzt KEINE Root-Shell als Rettungsanker. Das Backup hier ist
    die einzige eingebaute Notbremse; die UI erinnert zusätzlich aktiv
    daran, vor dem Aktivieren von "2FA erzwingen" eine Root-Shell offen
    zu halten (siehe _authentication_content())."""
    backup_file(path)
    tmp = Path(tempfile.gettempdir()) / f"wb-pam-{os.getpid()}-{int(time.time()*1000)}.tmp"
    try:
        tmp.write_text(new_text)
        tmp.chmod(0o644)
        out, err, ec = run_ec(["pkexec", "cp", str(tmp), str(path)], timeout=15)
        if ec != 0:
            return False, err or out or f"exit code {ec}"
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

def _run_streaming(cmd: list, on_line, on_done, input_text: str | None = None) -> None:
    """Gemeinsames Streaming-Muster für interaktive Subprozesse
    (fprintd-enroll, pamu2fcfg, passwd, …) - exakt dasselbe Vorgehen
    wie das bereits etablierte _clamav_scan() (Popen, stdout/stderr
    zusammengeführt, zeilenweise über GLib.idle_add in den GTK-
    Hauptthread durchgereicht). input_text wird (falls angegeben)
    einmal komplett auf stdin geschrieben und der Stream dann
    geschlossen - deckt z.B. passwd (current/new/new je Zeile) und
    fido2-token -S -e (current-/new-PIN je Zeile) ab."""
    def _worker():
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE if input_text is not None else None,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except Exception as e:
            msg = str(e)
            GLib.idle_add(lambda: (on_done([], msg), False)[1])
            return
        if input_text is not None:
            try:
                proc.stdin.write(input_text)
                proc.stdin.close()
            except Exception:
                pass
        lines = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if line:
                GLib.idle_add(lambda l=line: (on_line(l), False)[1])
        ec = proc.wait()
        GLib.idle_add(lambda: (on_done(lines, None if ec == 0 else f"exit code {ec}"), False)[1])
    in_thread(_worker)

# ── Password ─────────────────────────────────────────────────────
def _change_password(current: str, new: str, on_line, on_done) -> None:
    """'passwd' für den eigenen Account - PAM fragt das aktuelle
    Passwort selbst ab, braucht also kein root (siehe Analyse).
    current/new werden zeilenweise auf stdin geschrieben, exakt der
    Reihenfolge, in der 'passwd' interaktiv danach fragt (aktuelles,
    neues, neues zur Bestätigung)."""
    _run_streaming(["passwd"], on_line, on_done,
                   input_text=f"{current}\n{new}\n{new}\n")

# ── Fingerprint (fprintd) ────────────────────────────────────────
def _fprintd_available() -> bool:
    return bool(shutil.which("fprintd-enroll"))

# Standard-Fingernamen, die fprintd(-enroll/-list/-delete) kennt (siehe
# `man fprintd-enroll`) - (interner Name, Anzeige-Name) je Eintrag.
FPRINTD_FINGERS = [
    ("right-index-finger",  "Right index finger"),
    ("right-thumb",         "Right thumb"),
    ("right-middle-finger", "Right middle finger"),
    ("right-ring-finger",   "Right ring finger"),
    ("right-little-finger", "Right little finger"),
    ("left-index-finger",   "Left index finger"),
    ("left-thumb",          "Left thumb"),
    ("left-middle-finger",  "Left middle finger"),
    ("left-ring-finger",    "Left ring finger"),
    ("left-little-finger",  "Left little finger"),
]
_FPRINTD_FRIENDLY = dict(FPRINTD_FINGERS)

def _finger_friendly(internal_name: str) -> str:
    return _FPRINTD_FRIENDLY.get(internal_name, internal_name.replace("-", " ").capitalize())

def _fprintd_list(user: str) -> list[str]:
    out, _err, ec = run_ec(["fprintd-list", user], timeout=5)
    if ec != 0 or not out:
        return []
    # fprintd-list gibt i.d.R. eine Zeile wie
    # "user has 2 enrolled fingers: right-index-finger, left-thumb" aus
    m = re.search(r":\s*(.+)$", out.strip())
    if not m:
        return []
    return [f.strip() for f in m.group(1).split(",") if f.strip()]

def _fprintd_delete(user: str) -> tuple[bool, str]:
    out, err, ec = run_ec(["fprintd-delete", user], timeout=10)
    return ec == 0, (err or out if ec != 0 else "")

# fprintd-enroll gibt bei jedem Sensor-Kontakt eine Zeile
# "Enroll result: <code>" aus. Terminal-Codes beenden den Vorgang
# (erfolgreich ODER endgültig fehlgeschlagen), alle anderen sind nur
# eine Zwischen-Rückmeldung zu EINER Auflage - fprintd fragt danach
# automatisch weiter ab, bis genug gute Auflagen zusammenkommen (wie
# viele das sind, hängt vom Sensor ab und wird von fprintd selbst
# entschieden, nicht hier). Liste nicht abschließend garantiert (neuere
# fprintd-Versionen können weitere Codes einführen), aber deckt alle
# dokumentierten/üblichen Fälle ab - ein unbekannter Code fällt unten
# auf eine generische "noch in Arbeit"-Meldung zurück statt zu crashen.
_FPRINTD_STAGE_MSG = {
    "enroll-stage-passed":        "Good — lift your finger and place it again…",
    "enroll-swipe-too-short":     "Swipe was too short — try again.",
    "enroll-finger-not-centered": "Finger wasn't centered on the sensor — try again.",
    "enroll-remove-and-retry":    "Lift your finger, then place it again.",
}
_FPRINTD_TERMINAL_OK = {"enroll-completed"}
_FPRINTD_TERMINAL_ERR = {
    "enroll-failed":       "Enrollment failed.",
    "enroll-disconnected": "Fingerprint reader was disconnected.",
    "enroll-unknown-error": "Unknown error from the fingerprint reader.",
    "enroll-data-full":    "This reader's storage is full — delete an old finger first.",
}

def _fprintd_parse_enroll_line(line: str) -> tuple[str, str | None]:
    """Übersetzt EINE Zeile aus dem fprintd-enroll-Live-Output in
    (anzuzeigender Text, Ergebnis) - Ergebnis ist "ok"/"error"/None
    (None = Zwischenstand, noch nicht fertig). Macht die rohen
    "Enroll result: enroll-stage-passed"-Codes erst für Menschen
    lesbar - genau das hat vorher komplett gefehlt (die Live-Zeilen
    wurden zwar eingesammelt, aber nie angezeigt)."""
    m = re.search(r"Enroll result:\s*(\S+)", line)
    if not m:
        if "Enrolling" in line or "Using device" in line:
            return "Place your finger on the sensor…", None
        return line, None
    code = m.group(1)
    if code in _FPRINTD_TERMINAL_OK:
        return "Done.", "ok"
    if code in _FPRINTD_TERMINAL_ERR:
        return _FPRINTD_TERMINAL_ERR[code], "error"
    return _FPRINTD_STAGE_MSG.get(code, f"Still scanning ({code})…"), None

def _fprintd_enroll(finger: str, on_line, on_done) -> None:
    """Fingerabdruck für EINEN bestimmten Finger einlesen - 'fprintd-
    enroll -f <finger>' statt ohne Argument (das würde immer denselben
    Default-Finger nehmen, der Nutzer konnte bisher gar nicht wählen,
    WELCHEN Finger er registriert). Läuft über dasselbe Live-Ausgabe-
    Streaming-Muster wie der bestehende ClamAV-Scan
    (_run_streaming/_clamav_scan)."""
    _run_streaming(["fprintd-enroll", "-f", finger], on_line, on_done)

def _fprintd_verify(finger: str, on_line, on_done) -> None:
    _run_streaming(["fprintd-verify", "-f", finger], on_line, on_done)

def _pam_fprintd_enabled() -> bool:
    try:
        txt = _pam_target_file().read_text()
    except Exception:
        return False
    return bool(re.search(r'^\s*auth\s+\S+\s+pam_fprintd\.so', txt, re.M))

def _pam_fprintd_set_enabled(enabled: bool) -> tuple[bool, str]:
    """Schreibt/entfernt die 'auth sufficient pam_fprintd.so'-Zeile in
    der PAM-Datei (siehe _pam_target_file()). Muss VOR der
    pam_unix.so-Zeile stehen, sonst wird pam_unix zuerst gefragt und
    der Fingerabdruck-Erfolg kommt nie zum Tragen (gleiches Prinzip
    wie bei pam_u2f, siehe Analyse)."""
    path = _pam_target_file()
    try:
        txt = path.read_text() if path.is_file() else ""
    except Exception as e:
        return False, str(e)
    line_re = re.compile(r'^\s*auth\s+\S+\s+pam_fprintd\.so.*$\n?', re.M)
    if enabled:
        if line_re.search(txt):
            return True, ""  # schon aktiv, nichts zu tun
        new_line = "auth      sufficient                                   pam_fprintd.so\n"
        unix_re = re.compile(r'^(\s*auth\s+\S+\s+pam_unix\.so.*)$', re.M)
        m = unix_re.search(txt)
        if m:
            new_txt = txt[:m.start()] + new_line + txt[m.start():]
        else:
            # Kein pam_unix.so-Anker gefunden (unüblich) - ganz oben einfügen,
            # das ist für ein "sufficient"-Modul (kann nur ERFOLGREICH früher
            # durchlassen, nie zusätzlich blockieren) der sicherste Ort.
            new_txt = new_line + txt
    else:
        if not line_re.search(txt):
            return True, ""  # schon inaktiv
        new_txt = line_re.sub("", txt)
    return _pam_write_privileged(path, new_txt)

# ── FIDO2/U2F (pam_u2f) ──────────────────────────────────────────
def _u2f_mapping_path() -> Path:
    return Path(HOME) / ".config" / "Yubico" / "u2f_keys"

def _u2f_available() -> bool:
    return bool(shutil.which("pamu2fcfg"))

def _u2f_registered_count() -> int:
    """pamu2fcfg schreibt pro Nutzer EINE Zeile
    'username:credential1:credential2:...' - die Anzahl der Keys ist
    also (Anzahl ':'-getrennter Felder in der Zeile) - 1 (das erste
    Feld ist der Username, kein Key)."""
    p = _u2f_mapping_path()
    if not p.is_file():
        return 0
    try:
        lines = [l for l in p.read_text().splitlines() if l.strip()]
    except Exception:
        return 0
    total = 0
    for line in lines:
        parts = line.split(":")
        total += max(0, len(parts) - 1)
    return total

def _u2f_enabled() -> bool:
    try:
        txt = _pam_target_file().read_text()
    except Exception:
        return False
    return bool(re.search(r'^\s*auth\s+\S+\s+pam_u2f\.so', txt, re.M))

def _u2f_set_enabled(enabled: bool, authfile: Path, require_password: bool) -> tuple[bool, str]:
    """Schreibt/entfernt die pam_u2f.so-Zeile. require_password=True
    schreibt 'required ... cue' (echtes 2FA: Passwort UND Key nötig),
    False schreibt 'sufficient' (passwordless: Key allein reicht) -
    siehe Analyse für beide Varianten. Muss ebenfalls VOR pam_unix.so
    stehen."""
    path = _pam_target_file()
    try:
        txt = path.read_text() if path.is_file() else ""
    except Exception as e:
        return False, str(e)
    line_re = re.compile(r'^\s*auth\s+\S+\s+pam_u2f\.so.*$\n?', re.M)
    if enabled:
        control = "required" if require_password else "sufficient"
        extra = " cue" if require_password else ""
        new_line = (f"auth      {control:<10} pam_u2f.so authfile={authfile}{extra}\n")
        txt_wo_old = line_re.sub("", txt)
        unix_re = re.compile(r'^(\s*auth\s+\S+\s+pam_unix\.so.*)$', re.M)
        m = unix_re.search(txt_wo_old)
        if m:
            new_txt = txt_wo_old[:m.start()] + new_line + txt_wo_old[m.start():]
        else:
            new_txt = new_line + txt_wo_old
    else:
        if not line_re.search(txt):
            return True, ""
        new_txt = line_re.sub("", txt)
    return _pam_write_privileged(path, new_txt)

def _pamu2fcfg_add_key(on_line, on_done, append: bool) -> None:
    """Startet 'pamu2fcfg' (bzw. 'pamu2fcfg -n' für einen weiteren Key
    zur bestehenden Datei dazu, siehe Analyse) mit Live-Ausgabe
    ("Touch your key…" erscheint während pamu2fcfg wartet). on_done
    bekommt zusätzlich die fertige Mapping-Zeile zum Anhängen - das
    Anhängen selbst übernimmt der Aufrufer (siehe
    _authentication_content()), damit diese Funktion keine
    Dateisystem-Annahmen treffen muss."""
    cmd = ["pamu2fcfg"] + (["-n"] if append else [])
    _run_streaming(cmd, on_line, on_done)

def _fido2_list_tokens() -> list[str]:
    out, _err, ec = run_ec(["fido2-token", "-L"], timeout=5)
    if ec != 0 or not out:
        return []
    # Jede Zeile beginnt mit dem Device-Pfad, z.B. "/dev/hidraw3: ..."
    return [l.split(":")[0].strip() for l in out.splitlines() if l.strip()]

def _fido2_set_pin(device: str, current_pin: str, new_pin: str, on_line, on_done) -> None:
    """'fido2-token -S -e <device>' fragt (bzw. erwartet über stdin,
    falls nicht an ein Terminal gebunden) zuerst die aktuelle PIN
    (leer lassen = Key hat noch keine PIN), dann zweimal die neue PIN."""
    _run_streaming(["fido2-token", "-S", "-e", device], on_line, on_done,
                   input_text=f"{current_pin}\n{new_pin}\n{new_pin}\n")


def _authentication_content(win: Gtk.Window) -> Gtk.Box:
    """Neuer Security-Sub-Tab "Authentication" (Analyse Punkt 3):
    Password / Fingerprint / FIDO Key, als eigener kleiner Gtk.Stack
    innerhalb des Tabs (gleiches Verschachtelungs-Muster wie der
    ClamAV-Tab mit seinen 4 Unter-Tabs)."""
    root = vbox(4)

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.8)
    status_lbl.set_line_wrap(True)
    status_lbl.set_max_width_chars(40)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 5000):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    def _backup_reminder_dialog() -> bool:
        """Warnung (siehe Analyse, Arch-Wiki-Hinweis) VOR jeder
        PAM-Aktivierung: ein pkexec-Dialog ist kein Rettungsanker."""
        d = Gtk.MessageDialog(
            transient_for=win, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Enabling this changes system login (PAM) rules.")
        d.format_secondary_text(
            "A backup of the PAM file is made automatically, but a "
            "bad PAM change can still lock you out of sudo/login. "
            "Keep a root shell open elsewhere until you've confirmed "
            "this works. Continue?")
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                      "I have a root shell open — Continue", Gtk.ResponseType.OK)
        d.set_keep_above(True)
        resp = d.run()
        d.destroy()
        return resp == Gtk.ResponseType.OK

    # ── Sub-Stack ────────────────────────────────────────────────
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(200)

    # ══ Password ══
    pw_box = vbox(6); pad(pw_box, h=4, v=4)
    pw_box.pack_start(Gtk.Label(label="Change your account password."), False, False, 0)
    pw_change_btn = btn("Change Password…")
    pw_box.pack_start(pw_change_btn, False, False, 0)

    def _on_change_password(_b):
        dlg = Gtk.Dialog(title="Change Password", transient_for=win)
        dlg.set_name("wb-daemon-popup")
        dlg.set_modal(True)
        dlg.set_keep_above(True)
        dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Change", Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        e_cur = Gtk.Entry(); e_cur.set_visibility(False)
        e_cur.set_placeholder_text("Current password")
        e_new = Gtk.Entry(); e_new.set_visibility(False)
        e_new.set_placeholder_text("New password")
        e_conf = Gtk.Entry(); e_conf.set_visibility(False)
        e_conf.set_placeholder_text("Confirm new password")
        e_conf.set_activates_default(True)
        e_conf.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
        for e in (e_cur, e_new, e_conf):
            area.pack_start(e, True, True, 4)
        dlg.show_all()
        resp = dlg.run()
        current, new, conf = e_cur.get_text(), e_new.get_text(), e_conf.get_text()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        if not current or not new:
            _flash("Current and new password are required.")
            return
        if new != conf:
            _flash("New password and confirmation don't match.")
            return
        _flash("Changing password…", ms=60000)
        lines_acc = []
        def _done(lines, error):
            if error:
                tail = "\n".join(l for l in lines_acc if l.strip())[-300:]
                _flash(f"passwd failed: {tail or error}")
            else:
                _flash("Password changed.")
        def _on_line(l):
            lines_acc.append(l)
        _change_password(current, new, _on_line, _done)
    pw_change_btn.connect("clicked", _on_change_password)

    # ══ Fingerprint ══
    fp_box = vbox(6); pad(fp_box, h=4, v=4)
    if not _fprintd_available():
        fp_box.pack_start(
            Gtk.Label(label="fprintd not installed — install 'fprintd' to use this."),
            False, False, 0)
    else:
        fp_list_lbl = Gtk.Label(label="")
        fp_list_lbl.set_line_wrap(True)
        fp_box.pack_start(fp_list_lbl, False, False, 0)

        # Finger-Auswahl: vorher gab es dafür GAR KEINE UI - 'fprintd-
        # enroll' ohne '-f' hat immer nur denselben Default-Finger
        # genommen, man konnte also faktisch nur einen einzigen Finger
        # je registrieren, egal welcher Finger tatsächlich aufgelegt
        # wurde. Jetzt: Dropdown mit allen 10 von fprintd unterstützten
        # Fingern (siehe FPRINTD_FINGERS), Enroll/Verify wirken auf den
        # hier gewählten Finger.
        finger_row = hrow(sp=6)
        finger_row.pack_start(Gtk.Label(label="Finger:"), False, False, 0)
        finger_combo = Gtk.ComboBoxText()
        finger_combo.get_style_context().add_class("bubble")
        finger_combo.get_style_context().add_class("dropdown")
        finger_combo.set_can_focus(False)
        for _internal, _disp in FPRINTD_FINGERS:
            finger_combo.append_text(_disp)
        finger_combo.set_active(0)
        finger_row.pack_start(finger_combo, False, False, 0)
        fp_box.pack_start(finger_row, False, False, 0)

        def _selected_finger() -> str:
            idx = max(0, finger_combo.get_active())
            return FPRINTD_FINGERS[idx][0]

        # Eigene, deutlich sichtbare Status-Zeile NUR fürs Enroll/
        # Verify-Live-Feedback (statt des allgemeinen status_lbl ganz
        # unten) - genau das hat vorher komplett gefehlt: die
        # Live-Zeilen von fprintd-enroll wurden zwar eingesammelt
        # (lines_acc.append), aber nirgendwo angezeigt. Der Nutzer sah
        # also weder "jetzt auflegen", noch "nochmal", noch einen
        # konkreten Fehlergrund - nur irgendwann Erfolg oder Stille.
        fp_live_lbl = Gtk.Label(label="")
        fp_live_lbl.set_line_wrap(True)
        fp_live_lbl.get_style_context().add_class("caption")
        fp_live_lbl.set_no_show_all(True)
        fp_live_lbl.hide()
        fp_box.pack_start(fp_live_lbl, False, False, 0)

        fp_pam_toggle = btn("Fingerprint for sudo/login — Off", active=False)
        fp_pam_toggle.get_style_context().add_class("caption")
        fp_pam_toggle.set_tooltip_text(
            "When ON, Linux's authentication system (PAM) accepts your "
            "fingerprint as an alternative to typing your password — "
            "for sudo, login, screen unlock, polkit prompts, and "
            "anything else on this system that asks for your password. "
            "Your password still works too; this just adds the "
            "fingerprint as a second way in. Changes a system file "
            f"({_pam_target_file()}), automatically backed up first.")
        fp_row = hrow(sp=6)
        fp_enroll_btn = btn("Enroll finger…")
        fp_verify_btn = btn("Verify")
        fp_delete_btn = btn("Delete all")
        for b in (fp_enroll_btn, fp_verify_btn, fp_delete_btn):
            fp_row.pack_start(b, False, False, 0)
        fp_box.pack_start(fp_row, False, False, 0)
        fp_box.pack_start(fp_pam_toggle, False, False, 0)

        def _refresh_fp():
            fingers = _fprintd_list(_current_username())
            fp_list_lbl.set_label(
                "Enrolled: " + ", ".join(_finger_friendly(f) for f in fingers)
                if fingers else "No fingers enrolled yet.")
            fp_pam_toggle.set_label(
                "Fingerprint for sudo/login — " +
                ("On" if _pam_fprintd_enabled() else "Off"))

        def _fp_live(text: str):
            fp_live_lbl.set_label(text)
            fp_live_lbl.show()

        def _on_enroll(_b):
            finger = _selected_finger()
            _fp_live(f"Place your {_finger_friendly(finger).lower()} on the sensor…")
            def _on_line(line: str):
                text, result = _fprintd_parse_enroll_line(line)
                _fp_live(text)
            def _done(lines, error):
                _refresh_fp()
                if error:
                    tail = next((t for l in reversed(lines)
                                 for t, r in [_fprintd_parse_enroll_line(l)] if r == "error"), None)
                    _fp_live(f"Enroll failed: {tail or error}")
                else:
                    _fp_live(f"{_finger_friendly(finger)} enrolled.")
            _fprintd_enroll(finger, _on_line, _done)
        fp_enroll_btn.connect("clicked", _on_enroll)

        def _on_verify(_b):
            finger = _selected_finger()
            _fp_live(f"Place your {_finger_friendly(finger).lower()} on the sensor to verify…")
            def _done(lines, error):
                tail = "\n".join(l for l in lines if l.strip())
                if error:
                    _fp_live(f"No match / error: {tail or error}")
                else:
                    _fp_live(tail or "Verified — match.")
            _fprintd_verify(finger, lambda l: None, _done)
        fp_verify_btn.connect("clicked", _on_verify)

        def _on_delete(_b):
            ok, err = _fprintd_delete(_current_username())
            _refresh_fp()
            _fp_live("Deleted all enrolled fingers." if ok else f"Delete failed: {err}")
        fp_delete_btn.connect("clicked", _on_delete)

        def _on_pam_toggle(_b):
            enable = not _pam_fprintd_enabled()
            if enable and not _backup_reminder_dialog():
                return
            def _worker():
                ok, err = _pam_fprintd_set_enabled(enable)
                def _done():
                    _refresh_fp()
                    _flash("PAM updated." if ok else f"PAM update failed: {err}")
                    return False
                GLib.idle_add(_done)
            in_thread(_worker)
        fp_pam_toggle.connect("clicked", _on_pam_toggle)

        _refresh_fp()

    # ══ FIDO Key ══
    fido_box = vbox(6); pad(fido_box, h=4, v=4)
    if not _u2f_available():
        fido_box.pack_start(
            Gtk.Label(label="pam-u2f not installed — install 'pam-u2f' "
                             "(provides pamu2fcfg) to use this."),
            False, False, 0)
    else:
        fido_status_lbl = Gtk.Label(label="")
        fido_status_lbl.set_line_wrap(True)
        fido_box.pack_start(fido_status_lbl, False, False, 0)

        fido_add_btn = btn("Add Key…")
        fido_enforce_toggle = btn("FIDO key required for sudo/login — Off", active=False)
        fido_enforce_toggle.get_style_context().add_class("caption")
        fido_enforce_toggle.set_tooltip_text(
            "When ON, Linux's authentication system (PAM) will ask for "
            "this USB/NFC security key whenever something on this "
            "system normally asks for your password (sudo, login, "
            "screen unlock, polkit prompts, …). You'll be asked to "
            "choose between two modes: 'Password AND key' keeps your "
            "password required too and adds the key as a second, "
            "mandatory factor (real 2FA — touch the key when it "
            "blinks). 'Key alone' lets the key by itself replace "
            "typing your password entirely (faster, but means losing "
            "the key locks you out unless you still have your "
            "password-based login as a fallback). Changes a system "
            f"file ({_pam_target_file()}), automatically backed up first.")
        fido_row = hrow(sp=6)
        fido_row.pack_start(fido_add_btn, False, False, 0)
        fido_box.pack_start(fido_row, False, False, 0)
        fido_box.pack_start(fido_enforce_toggle, False, False, 0)

        pin_row = hrow(sp=6)
        fido_pin_btn = btn("Manage PIN…")
        pin_row.pack_start(fido_pin_btn, False, False, 0)
        fido_box.pack_start(pin_row, False, False, 0)

        def _refresh_fido():
            n = _u2f_registered_count()
            fido_status_lbl.set_label(
                f"{n} key(s) registered in {_u2f_mapping_path()}" if n
                else f"No keys registered yet (will be saved to {_u2f_mapping_path()}).")
            fido_enforce_toggle.set_label(
                "FIDO key required for sudo/login — " + ("On" if _u2f_enabled() else "Off"))

        def _on_add_key(_b):
            d = Gtk.MessageDialog(
                transient_for=win, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="Register a FIDO2/U2F key")
            d.format_secondary_text(
                "You'll be asked to touch the key in a moment. Add it as "
                "an additional key (keeps existing ones), or replace the "
                "whole file?")
            d.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                          "Replace file", Gtk.ResponseType.REJECT,
                          "Add (keep existing)", Gtk.ResponseType.OK)
            d.set_keep_above(True)
            resp = d.run()
            d.destroy()
            if resp not in (Gtk.ResponseType.OK, Gtk.ResponseType.REJECT):
                return
            append = (resp == Gtk.ResponseType.OK)
            _flash("Touch your key…", ms=30000)
            def _done(lines, error):
                if error:
                    tail = "\n".join(l for l in lines if l.strip())[-300:]
                    _flash(f"pamu2fcfg failed: {tail or error}")
                    return
                # Letzte nicht-leere Ausgabezeile ist die fertige
                # Mapping-Zeile (username:cred1:cred2:...).
                cred_line = next((l for l in reversed(lines) if l.strip()), "")
                if not cred_line:
                    _flash("pamu2fcfg produced no output.")
                    return
                p = _u2f_mapping_path()
                try:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if append and p.is_file():
                        backup_file(p)
                        existing = p.read_text()
                        if not existing.endswith("\n") and existing:
                            existing += "\n"
                        p.write_text(existing + cred_line + "\n")
                    else:
                        if p.is_file():
                            backup_file(p)
                        atomic_write_text(p, cred_line + "\n")
                    _refresh_fido()
                    _flash("Key registered.")
                except Exception as e:
                    _flash(f"Could not write mapping file: {e}")
            _pamu2fcfg_add_key(lambda l: None, _done, append=append)
        fido_add_btn.connect("clicked", _on_add_key)

        def _on_enforce_toggle(_b):
            enable = not _u2f_enabled()
            require_password = True
            if enable:
                if not _backup_reminder_dialog():
                    return
                d = Gtk.MessageDialog(
                    transient_for=win, modal=True, message_type=Gtk.MessageType.QUESTION,
                    buttons=Gtk.ButtonsType.NONE,
                    text="Require password AND key, or key alone?")
                d.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                              "Key alone (passwordless)", Gtk.ResponseType.REJECT,
                              "Password AND key (2FA)", Gtk.ResponseType.OK)
                d.set_keep_above(True)
                resp = d.run()
                d.destroy()
                if resp not in (Gtk.ResponseType.OK, Gtk.ResponseType.REJECT):
                    return
                require_password = (resp == Gtk.ResponseType.OK)
            def _worker():
                ok, err = _u2f_set_enabled(enable, _u2f_mapping_path(), require_password)
                def _done():
                    _refresh_fido()
                    _flash("PAM updated." if ok else f"PAM update failed: {err}")
                    return False
                GLib.idle_add(_done)
            in_thread(_worker)
        fido_enforce_toggle.connect("clicked", _on_enforce_toggle)

        def _on_manage_pin(_b):
            tokens = _fido2_list_tokens()
            if not tokens:
                _flash("No FIDO2 key detected (fido2-token -L found none).")
                return
            device = tokens[0]
            dlg = Gtk.Dialog(title=f"Manage PIN — {device}", transient_for=win)
            dlg.set_name("wb-daemon-popup")
            dlg.set_modal(True)
            dlg.set_keep_above(True)
            dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                            "Set PIN", Gtk.ResponseType.OK)
            area = dlg.get_content_area()
            area.pack_start(Gtk.Label(
                label="Leave 'Current PIN' empty if the key has no PIN yet."),
                False, False, 4)
            e_cur = Gtk.Entry(); e_cur.set_visibility(False)
            e_cur.set_placeholder_text("Current PIN (leave empty if none)")
            e_new = Gtk.Entry(); e_new.set_visibility(False)
            e_new.set_placeholder_text("New PIN")
            e_new.set_activates_default(True)
            e_new.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
            area.pack_start(e_cur, True, True, 4)
            area.pack_start(e_new, True, True, 4)
            dlg.show_all()
            resp = dlg.run()
            cur_pin, new_pin = e_cur.get_text(), e_new.get_text()
            dlg.destroy()
            if resp != Gtk.ResponseType.OK or not new_pin:
                return
            _flash("Setting PIN — touch your key if it blinks…", ms=30000)
            def _done(lines, error):
                if error:
                    tail = "\n".join(l for l in lines if l.strip())[-300:]
                    _flash(f"Failed: {tail or error}")
                else:
                    _flash("PIN set.")
            _fido2_set_pin(device, cur_pin, new_pin, lambda l: None, _done)
        fido_pin_btn.connect("clicked", _on_manage_pin)

        _refresh_fido()

    stack.add_named(pw_box, "password")
    stack.add_named(fp_box, "fingerprint")
    stack.add_named(fido_box, "fido")

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch_auth_tab(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, tlabel in (("password", "Password"),
                         ("fingerprint", "Fingerprint"),
                         ("fido", "FIDO Key")):
        b = btn(tlabel, active=(name == "password"))
        b.connect("clicked", lambda _b, n=name: _switch_auth_tab(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("password")

    root.pack_start(tab_row, True, False, 2)
    root.pack_start(tab_sep(), False, False, 0)
    root.pack_start(stack, False, False, 0)
    root.pack_start(status_lbl, False, False, 4)
    return root

def _security_content(win: Gtk.Window) -> Gtk.Box:
    """Tab-Hülle fürs Security-Widget - alle 6 Sub-Panels:
    "Privacy" (Kill-Switches) + "DNS" (Server-Auswahl + Enforce-DoT +
    Guest-WiFi) + "Tailscale" + "Firewall" (UFW) + "ClamAV" (Signatur-
    Update, On-Demand-Scan, Auto-Scan-Toggle) + "Authentication"
    (Password/Fingerprint/FIDO, Analyse Punkt 3), als Gtk.Stack wie bei
    Volume/Battery/Appearance.

    UFW- UND Authentication-Tab sind LAZY (wie der Processes-Tab beim
    Battery-Widget) - UFW, weil sein allererster Status-Abruf selbst
    schon einen Polkit-Passwort-Dialog auslösen kann (ufw braucht für
    praktisch alles Root), Authentication, weil sein Fingerprint-/FIDO-
    Unterbereich beim ersten Aufbau bereits `fprintd-list`/einen Read
    der PAM-Datei ausführt - beides soll nicht einfach beim Öffnen des
    Widgets ungefragt passieren, nur weil der Privacy-Tab (der KEINE
    Root-Rechte braucht) initial sichtbar ist. ClamAV braucht dasselbe
    NICHT (Status-Lesen + Auto-Scan-Toggle sind root-frei, siehe
    _clamav_content()-Docstring), ist also wie DNS/Tailscale eager
    gebaut."""
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
    auth_built = [False]

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

    def _ensure_auth_tab():
        if auth_built[0]:
            return
        auth_built[0] = True
        _current_win[0] = win
        try:
            stack.add_named(_authentication_content(win), "authentication")
        finally:
            _current_win[0] = None
        stack.show_all()

    # 2 Zeilen statt 1 lange (README-Feedback: "die ersten 2 Tabs über
    # den anderen 3, damit Platz gespart wird") - eine durchgehend lange
    # Tab-Reihe mit jetzt 6 Einträgen hätte entweder das Fenster unnötig
    # breit gemacht oder wäre auf schmaleren Bildschirmen umgebrochen.
    tab_row_top = hbox(6)
    tab_row_top.set_halign(Gtk.Align.CENTER)
    tab_row_bottom = hbox(6)
    tab_row_bottom.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        if name == "ufw":
            _ensure_ufw_tab()
        elif name == "authentication":
            _ensure_auth_tab()
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, tlabel, target_row in (
            ("privacy", "󰦝  Privacy", tab_row_top),
            ("dns", "󰙲  DNS", tab_row_top),
            ("authentication", "󰌋  Auth", tab_row_top),
            ("tailscale", "󰖂  Tailscale", tab_row_bottom),
            ("ufw", "󰈸  Firewall", tab_row_bottom),
            ("clamav", "  ClamAV", tab_row_bottom)):
        b = btn(tlabel, active=(name == "privacy"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        target_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name("privacy")

    outer = vbox(4); safe_pad_edge(outer, 380, top=False, bottom=True)
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

# ════════════════════════════════════════════════════════════
#  APP EDITOR — Tab 1: TrafkTux App Launcher (menu.json)
#
#  Spiegelt die App-Quellen-Logik 1:1 aus TrafkTuxLauncher.c
#  (get_desktop_apps/get_filtered_desktop_apps/get_path_binaries/
#  extract_binary/strip_exec_field_codes), damit Editor und Launcher
#  immer dieselbe Sicht auf "welche Apps gibt es" / "was ist schon
#  einsortiert" haben. "All Packages" in menu.json ist trotz des
#  Namens $PATH-Binaries, keine Pacman-Pakete (siehe VMODE_RUN dort).
# ════════════════════════════════════════════════════════════

_APPLAUNCHER_WRAPPER_PREFIXES = ("kitty", "sudo")
# Binaries, die so generisch sind, dass ein exec-Match darauf NICHTS über
# die eigentliche App aussagt (Interpreter/Runtime-Wrapper - typischerweise
# das erste Token bei "flatpak run <id>", "python3 <script>.py", etc.).
# Ohne diese Ausnahme reicht 1 einsortierte App mit so einem Exec, um ALLE
# anderen Apps mit demselben Interpreter fälschlich aus "Unsorted" zu
# werfen, weil extract_binary() nur das erste Token nimmt und Argumente
# ignoriert - BESTÄTIGT derselbe Effekt wie in extract_binary() in
# TrafkTuxLauncher.c (dort inzwischen mit GENERIC_BINARIES genauso
# gefixt, Liste hier bewusst synchron gehalten - z.B. "steam" bei JEDEM
# per Steam gestarteten Spiel-Shortcut, nicht nur bei Steam selbst).
_APPLAUNCHER_GENERIC_BINARIES = {
    "env", "bash", "sh", "zsh", "fish", "python", "python3", "python2",
    "perl", "ruby", "node", "nodejs", "electron", "java", "javaw",
    "flatpak", "snap", "appimage-run", "wine", "wine64", "wineconsole",
    "steam", "lutris", "heroic", "bottles",
}
_APPLAUNCHER_SCAN_CACHE_TTL = 15  # Sekunden, wie SCAN_CACHE_TTL im Launcher

def _applauncher_sys_menu_path() -> Path:
    return Path(HOME) / ".config" / "TrafkTuxLauncher" / "AppLauncher" / "menu.json"

def _applauncher_user_menu_path() -> Path:
    # Liegt laut der neuen TrafkTuxLauncher.c-Version im selben Ordner wie
    # menu.json (siehe ensure_user_menu_skeleton() dort).
    return _applauncher_sys_menu_path().parent / "Usermenu.json"

# Fallback, falls die Datei (noch) nicht existiert - 1:1 der mitgeshippte
# Standard-Inhalt, damit der Editor auf einem System ohne installierten
# TrafkTuxLauncher nicht einfach crasht.
_APPLAUNCHER_DEFAULT_TREE = {
    "name": "root", "type": "folder", "children": [
        {"name": "System", "type": "folder", "icon": "computer", "children": [
            {"name": "Xfce4 Terminal", "type": "app", "icon": "utilities-terminal", "exec": "xfce4-terminal"},
            {"name": "Thunar", "type": "app", "icon": "system-file-manager", "exec": "thunar"},
            {"name": "Ark", "type": "app", "icon": "ark", "exec": "ark"},
        ]},
        {"name": "Creation", "type": "folder", "icon": "applications-graphics", "children": [
            {"name": "VScodium", "type": "app", "icon": "vscodium", "exec": "vscodium"},
        ]},
        {"name": "Utilitys", "type": "folder", "icon": "applications-accessories", "children": [
            {"name": "Fastfetch", "type": "app", "icon": "utilities-system-monitor",
             "exec": "xfce4-terminal --hold fastfetch"},
        ]},
        {"name": "Games", "type": "folder", "icon": "applications-games", "children": []},
        {"name": "Multimedia", "type": "folder", "icon": "applications-multimedia", "children": [
            {"name": "VLC", "type": "app", "icon": "vlc", "exec": "vlc"},
            {"name": "Viewnior", "type": "app", "icon": "viewnior", "exec": "viewnior"},
        ]},
        {"name": "Social", "type": "folder", "icon": "user-available", "children": [
            {"name": "Firefox", "type": "app", "icon": "firefox", "exec": "firefox"},
        ]},
        {"name": "Stores", "type": "folder", "icon": "software-center", "children": [
            {"name": "Pamac Manager", "type": "app", "icon": "package-x-generic", "exec": "pamac-manager"},
        ]},
        {"name": "Settings", "type": "folder", "icon": "preferences-system", "children": []},
        {"name": "Administration", "type": "folder", "icon": "drive-harddisk", "children": [
            {"name": "Htop", "type": "app", "icon": "utilities-system-monitor", "exec": "xfce4-terminal Htop"},
            {"name": "Gnome Disks", "type": "app", "icon": "gnome-disks", "exec": "gnome-disk-utility"},
            {"name": "Fedora Media Writer", "type": "app", "icon": "mediawriter", "exec": "mediawriter"},
        ]},
        {"name": "Unordered Programs", "type": "special-drun-filtered", "icon": "applications-utilities"},
        {"name": "All Programs", "type": "special-drun", "icon": "system-run"},
        {"name": "All Packages", "type": "special-run", "icon": "package-x-generic"},
    ],
}

def _applauncher_load_sys_tree() -> dict:
    """menu.json - "gehört" dem System/Update-Skript. Der Editor liest das
    nur noch (für Anzeige + Dedup), schreibt es NIE mehr - genau wie die
    neue TrafkTuxLauncher.c das jetzt auch so vorsieht (Usermenu.json ist
    die einzige Datei, die update-sicher eigene Einträge aufnimmt)."""
    p = _applauncher_sys_menu_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            if isinstance(data, dict) and isinstance(data.get("children"), list):
                return data
        except Exception as e:
            print(f"[AppEditor] {p}: invalid JSON, using bundled default ({e})", file=sys.stderr)
    return json.loads(json.dumps(_APPLAUNCHER_DEFAULT_TREE))  # deep copy ohne extra import

def _applauncher_build_user_skeleton(sys_tree: dict) -> dict:
    """Python-Port von ensure_user_menu_skeleton() in TrafkTuxLauncher.c:
    ein leerer Eintrag pro "echtem" Ordner (hat selbst "children") der
    GERADE geladenen menu.json - special-drun/-filtered/-run-Einträge
    haben kein "children" und werden dabei automatisch übersprungen."""
    skeleton = {"name": "root", "type": "folder", "children": []}
    for child in sys_tree.get("children", []) or []:
        if isinstance(child.get("children"), list) and child.get("name"):
            skeleton["children"].append({"name": child["name"], "type": "folder", "children": []})
    return skeleton

def _applauncher_load_user_tree(sys_tree: dict) -> dict:
    """Usermenu.json - hier landen ALLE Änderungen aus dem Editor. Fehlt
    sie (noch) - z.B. weil der Launcher in der neuen Version noch nie
    gelaufen ist -, wird nur im Speicher ein zu menu.json passendes
    leeres Gerüst gebaut (genau wie ensure_user_menu_skeleton() es auf
    der Platte täte); geschrieben wird sie trotzdem erst beim Save."""
    p = _applauncher_user_menu_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            if isinstance(data, dict) and isinstance(data.get("children"), list):
                return data
        except Exception as e:
            print(f"[AppEditor] {p}: invalid JSON, using empty skeleton ({e})", file=sys.stderr)
    return _applauncher_build_user_skeleton(sys_tree)

def _applauncher_save_user_tree(tree: dict) -> None:
    p = _applauncher_user_menu_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    backup_file(p)
    atomic_write_text(p, json.dumps(tree, indent=2) + "\n")

# ── Merge sys (menu.json) + user (Usermenu.json) für Anzeige/Dedup -
# Python-Port von merge_user_node() in TrafkTuxLauncher.c. Das Ergebnis
# ist IMMER eine frische, unabhängige Kopie (nie Original-Referenzen),
# jeder Knoten bekommt "_source": "sys"|"user" (nur für die UI - wird
# nie gespeichert, Speichern schreibt ausschließlich state["user_tree"]). ─
def _applauncher_tag_source(node: dict, source: str) -> dict:
    node["_source"] = source
    for c in node.get("children") or []:
        _applauncher_tag_source(c, source)
    return node

def _applauncher_merge_user_into(sys_copy: dict, user_node: dict) -> None:
    user_children = user_node.get("children") or []
    if not user_children:
        return
    sys_children = sys_copy.setdefault("children", [])
    for uc in user_children:
        uname = uc.get("name")
        match = next((sc for sc in sys_children if sc.get("name") == uname), None) if uname else None
        # WICHTIG: "children" in uc (Existenz des Keys), NICHT uc.get("children")
        # (Wahrheitswert)! Ein frisch angelegter, noch LEERER User-Ordner hat
        # "children": [] - das ist in Python falsy, hätte also jeden der 9
        # Root-Ordner aus dem leeren Usermenu.json-Gerüst fälschlich als
        # komplett NEUEN, doppelten Ordner angehängt statt ihn mit dem
        # gleichnamigen sys-Ordner zu verschmelzen. Exakt der Bug, den
        # json_object_has_member() in merge_user_node() (C) durch Prüfen
        # der Key-EXISTENZ statt des Inhalts vermeidet - hier jetzt genauso.
        if match is not None and "children" in uc:
            _applauncher_merge_user_into(match, uc)
        else:
            sys_children.append(_applauncher_tag_source(json.loads(json.dumps(uc)), "user"))

def _applauncher_build_merged_tree(sys_tree: dict, user_tree: dict) -> dict:
    merged = _applauncher_tag_source(json.loads(json.dumps(sys_tree)), "sys")
    _applauncher_merge_user_into(merged, user_tree)
    return merged

def _applauncher_name_chain(tree: dict, path: list) -> list:
    """Namen entlang eines Index-Pfads im (gemergten) Baum, z.B.
    ['System', 'MeinSubordner'] - Grundlage, um denselben Ort in
    state["user_tree"] wiederzufinden/anzulegen."""
    names = []
    node = tree
    for idx in path:
        children = node.get("children") or []
        if idx < 0 or idx >= len(children):
            break
        node = children[idx]
        names.append(node.get("name", "?"))
    return names

def _applauncher_resolve_or_create_user_path(user_tree: dict, name_chain: list) -> dict:
    """Läuft name_chain in user_tree ab und legt fehlende Zwischenordner
    automatisch an (leer) - macht jeden im gemergten Baum sichtbaren
    Ordner-Pfad automatisch beschreibbar in Usermenu.json, auch wenn er
    bisher nur in menu.json existiert."""
    node = user_tree
    for name in name_chain:
        children = node.setdefault("children", [])
        match = next((c for c in children if c.get("name") == name and c.get("type") == "folder"), None)
        if match is None:
            match = {"name": name, "type": "folder", "children": []}
            children.append(match)
        node = match
    return node

# ── Baum-Navigation: Pfade sind Index-Listen, analog zur "/"-Index-
# Pfadnotation von get_node_by_path() in TrafkTuxLauncher.c ────────────
def _applauncher_node_at(tree: dict, path: list) -> dict | None:
    node = tree
    for idx in path:
        children = node.get("children")
        if not isinstance(children, list) or idx < 0 or idx >= len(children):
            return None
        node = children[idx]
    return node

def _applauncher_iter_app_nodes(tree: dict, path: list | None = None):
    """Liefert (path, node) für jeden 'app'-Knoten im kompletten Baum."""
    if path is None:
        path = []
    for i, child in enumerate(tree.get("children", []) or []):
        cpath = path + [i]
        if child.get("type") == "app":
            yield cpath, child
        elif child.get("type") == "folder":
            yield from _applauncher_iter_app_nodes(child, cpath)

def _applauncher_extract_binary(exec_str: str) -> str | None:
    """Portierung von extract_binary() in TrafkTuxLauncher.c."""
    if not exec_str:
        return None
    p = exec_str.strip()
    if not p:
        return None
    again = True
    while again:
        again = False
        for pre in _APPLAUNCHER_WRAPPER_PREFIXES:
            if p[:len(pre)].lower() == pre and (len(p) == len(pre) or p[len(pre)] in " \t"):
                p = p[len(pre):].lstrip()
                again = True
                break
        low = p.lower()
        if low.startswith("bash") and len(p) > 4 and p[4] in " \t":
            q = p[4:].lstrip()
            if q[:2].lower() == "-c" and len(q) > 2 and q[2] in " \t":
                q = q[2:].lstrip()
                if q[:1] in ("'", '"'):
                    quote = q[0]
                    end = q.find(quote, 1)
                    if end != -1:
                        p = q[1:end].lstrip()
                        again = True
                        continue
    bin_part = re.split(r"[ \t\n\r]", p, maxsplit=1)[0]
    return os.path.basename(bin_part) if bin_part else None

def _applauncher_used_keys(tree: dict) -> tuple:
    """(names, exec_binaries), beide casefolded - dieselben zwei Dedup-
    Schlüssel wie get_filtered_desktop_apps() im Launcher."""
    names, execs = set(), set()
    for _path, node in _applauncher_iter_app_nodes(tree):
        nm = (node.get("name") or "").strip().casefold()
        if nm:
            names.add(nm)
        bin_ = _applauncher_extract_binary(node.get("exec") or "")
        if bin_ and bin_.casefold() not in _APPLAUNCHER_GENERIC_BINARIES:
            execs.add(bin_.casefold())
    return names, execs

_APPLAUNCHER_FIELD_CODE_RE = re.compile(r"%(.)")
def _applauncher_strip_exec_field_codes(exec_str: str) -> str:
    def _sub(m):
        c = m.group(1)
        if c == "%":
            return "%"
        if c in "fFuUickdDnNvm":
            return ""
        return m.group(0)
    out = _APPLAUNCHER_FIELD_CODE_RE.sub(_sub, exec_str or "")
    return " ".join(out.split())

def _applauncher_xdg_data_dirs() -> list:
    raw = [str(Path(HOME) / ".local" / "share")]
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        raw.insert(0, xdg_data_home)
    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    raw += [d for d in xdg_data_dirs.split(":") if d]
    seen, out = set(), []
    for d in raw:
        if d not in seen:
            seen.add(d); out.append(d)
    return out

def _applauncher_current_desktop_names() -> set:
    raw = os.environ.get("XDG_CURRENT_DESKTOP") or ""
    return {p.strip().casefold() for p in raw.split(":") if p.strip()}

_applauncher_desktop_cache = {"ts": 0.0, "apps": []}
_applauncher_path_cache = {"ts": 0.0, "apps": []}

def _applauncher_scan_desktop_apps() -> list:
    """Portierung von collect_desktop_apps_impl(): Scan über
    XDG_DATA_DIRS/applications/*.desktop, mit demselben Cache-TTL wie
    der Launcher selbst, damit beide ungefähr dieselbe Sicht haben."""
    now = time.time()
    if (now - _applauncher_desktop_cache["ts"]) < _APPLAUNCHER_SCAN_CACHE_TTL:
        return _applauncher_desktop_cache["apps"]

    current_desktop = _applauncher_current_desktop_names()
    seen_ids: set = set()
    out: list = []
    for data_dir in _applauncher_xdg_data_dirs():
        app_dir = Path(data_dir) / "applications"
        if not app_dir.is_dir():
            continue
        try:
            found = sorted(app_dir.rglob("*.desktop"))
        except Exception:
            continue
        for full_path in found:
            try:
                rel = full_path.relative_to(app_dir)
            except Exception:
                continue
            desktop_id = "-".join(rel.parts)
            if desktop_id in seen_ids:
                continue
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                cp.read(full_path, encoding="utf-8")
            except Exception:
                continue
            if not cp.has_section("Desktop Entry"):
                continue
            sec = cp["Desktop Entry"]
            seen_ids.add(desktop_id)
            if sec.get("Type", "Application") != "Application":
                continue
            if sec.get("Hidden", "false").strip().lower() == "true":
                continue
            if sec.get("NoDisplay", "false").strip().lower() == "true":
                continue
            only_show_in = sec.get("OnlyShowIn", "")
            if only_show_in and current_desktop:
                allowed = bool({x.strip().casefold() for x in only_show_in.split(";") if x.strip()}
                                & current_desktop)
                if not allowed:
                    continue
            not_show_in = sec.get("NotShowIn", "")
            if not_show_in and current_desktop:
                denied = bool({x.strip().casefold() for x in not_show_in.split(";") if x.strip()}
                               & current_desktop)
                if denied:
                    continue
            exec_raw = sec.get("Exec", "")
            if not exec_raw.strip():
                continue
            name = sec.get("Name", "").strip() or desktop_id
            icon = sec.get("Icon", "").strip() or "application-x-executable"
            stripped = _applauncher_strip_exec_field_codes(exec_raw)
            terminal = sec.get("Terminal", "false").strip().lower() == "true"
            final_exec = f"kitty {stripped}" if terminal else stripped
            out.append({"name": name, "icon": icon, "exec": final_exec, "sort_key": name.casefold()})
    out.sort(key=lambda e: e["sort_key"])
    _applauncher_desktop_cache["ts"] = now
    _applauncher_desktop_cache["apps"] = out
    return out

def _applauncher_scan_path_binaries() -> list:
    """Portierung von get_path_binaries() - trotz des irreführenden
    Namens 'All Packages' in menu.json sind das $PATH-Binaries, keine
    Pacman-Pakete (siehe VMODE_RUN in TrafkTuxLauncher.c)."""
    now = time.time()
    if (now - _applauncher_path_cache["ts"]) < _APPLAUNCHER_SCAN_CACHE_TTL:
        return _applauncher_path_cache["apps"]
    path_env = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    seen: set = set()
    out: list = []
    for d in path_env.split(":"):
        if not d:
            continue
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for fname in entries:
            if fname in seen:
                continue
            full = os.path.join(d, fname)
            if os.path.isfile(full) and os.access(full, os.X_OK):
                seen.add(fname)
                out.append({"name": fname, "icon": "application-x-executable",
                            "exec": f"'{full}'", "sort_key": fname.casefold()})
    out.sort(key=lambda e: e["sort_key"])
    _applauncher_path_cache["ts"] = now
    _applauncher_path_cache["apps"] = out
    return out

def _applauncher_unsorted_apps(tree: dict) -> list:
    """Portierung von get_filtered_desktop_apps(): alle Desktop-Apps,
    MINUS die, deren Name oder exec-Binary schon irgendwo im Baum
    verwendet wird."""
    used_names, used_execs = _applauncher_used_keys(tree)
    out = []
    for e in _applauncher_scan_desktop_apps():
        if e["name"].casefold() in used_names:
            continue
        bin_ = _applauncher_extract_binary(e["exec"])
        if bin_ and bin_.casefold() in used_execs:
            continue
        out.append(e)
    return out

def _applauncher_custom_apps(tree: dict) -> list:
    """App-Knoten im Baum, die über 'New Custom App' im Editor angelegt
    wurden (markiert mit 'custom': true - ein Zusatzfeld, das
    TrafkTuxLauncher.c schlicht ignoriert, da JSON-GLib nur die ihm
    bekannten Member ausliest)."""
    out = []
    for path, node in _applauncher_iter_app_nodes(tree):
        if node.get("custom"):
            out.append({"name": node.get("name", ""),
                        "icon": node.get("icon") or "application-x-executable",
                        "exec": node.get("exec", ""), "path": path})
    out.sort(key=lambda e: e["name"].casefold())
    return out

def _applauncher_ordered_apps(tree: dict) -> list:
    out = []
    for path, node in _applauncher_iter_app_nodes(tree):
        folder_names = []
        cur = tree
        for idx in path[:-1]:
            cur = cur["children"][idx]
            folder_names.append(cur.get("name", "?"))
        out.append({"name": node.get("name", ""),
                    "icon": node.get("icon") or "application-x-executable",
                    "exec": node.get("exec", ""), "path": path,
                    "folder": " / ".join(folder_names) if folder_names else "—"})
    out.sort(key=lambda e: (e["folder"], e["name"].casefold()))
    return out

# ── Zeilen-/Zellen-Widgets ───────────────────────────────────────────
# KEIN Drag & Drop (mehr) - bewusst rausgeworfen (siehe Chat: "drag und
# drop muss es auch nicht haben"): jede Zeile/jedes Icon ist stattdessen
# ein ganz normaler Gtk.Button - klicken fügt die App/den neuen Ordner/
# die neue Custom-App dem GERADE GEÖFFNETEN Ordner hinzu. Button statt
# reiner Box auch deshalb, weil nur Gtk.Button von Haus aus Hover-/
# Press-Feedback über das Theme bekommt (siehe _settings_category_row
# weiter oben, gleiches Prinzip) - eine reine Box bekommt das NICHT.
_APPLAUNCHER_NAME_MAX_CHARS = 28

_APPLAUNCHER_TEXT_PX = 13       # Basis-Schriftgröße von .bubble.item (siehe CSS oben)
_APPLAUNCHER_ICON_RATIO = 1.65  # Icon-Größe relativ zum Text (Wunsch: 1.65x)
_APPLAUNCHER_ICON_PX = round(_APPLAUNCHER_TEXT_PX * _APPLAUNCHER_ICON_RATIO)     # Zeilen
_APPLAUNCHER_ICON_PX_LG = _APPLAUNCHER_ICON_PX  # Root-Ordner-Zellen - gleiche Regel

def _applauncher_icon_img(icon_name: str, px: int = _APPLAUNCHER_ICON_PX) -> Gtk.Image:
    """Lädt IMMER exakt px×px, egal ob Theme-Icon-Name ('firefox') oder
    absoluter Pfad. Letzteres kommt bei vielen Flatpak/AppImage/manuell
    installierten .desktop-Dateien vor (Icon=/pfad/zu/oft-riesigem.png,
    z.B. 512x512) - Gtk.Image.new_from_icon_name() kennt solche Pfade
    nicht und hat dafür dann in nativer Auflösung statt der angefragten
    Größe gerendert (der 'Icon frisst den halben Bildschirm'-Bug)."""
    name = (icon_name or "").strip() or "application-x-executable"
    if os.path.isabs(name):
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(name, px, px, True)
            return Gtk.Image.new_from_pixbuf(pb)
        except Exception:
            name = "application-x-executable"
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    img.set_pixel_size(px)  # überschreibt IconSize hart auf px, immer gleich groß
    return img

def _applauncher_folder_cell(node: dict, on_click) -> Gtk.Button:
    b = Gtk.Button()
    b.get_style_context().add_class("bubble")
    b.get_style_context().add_class("item")
    b.set_size_request(72, 60)
    inner = vbox(2); inner.set_halign(Gtk.Align.CENTER)
    inner.pack_start(_applauncher_icon_img(node.get("icon") or "folder", _APPLAUNCHER_ICON_PX_LG),
                      False, False, 0)
    lbl = Gtk.Label(label=node.get("name", "?"))
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_max_width_chars(10)
    inner.pack_start(lbl, False, False, 0)
    b.add(inner)
    b.connect("clicked", lambda _b: on_click())
    return b

def _applauncher_child_row(node: dict, on_open, on_remove, on_change_icon,
                            on_move_up, on_move_down) -> Gtk.Widget:
    """Zeile innerhalb eines geöffneten Ordners. Icon ist IMMER sein
    eigener kleiner Button (klicken = Icon ändern) - getrennt vom
    Namens-Teil, weil GTK keine Buttons ineinander verschachteln kann.
    Ordner-Namen sind zusätzlich ein klickbarer Button (navigiert rein),
    App-Namen nur Text. Rechts: ▲▼ zum Umsortieren (statt Drag - siehe
    Chat: "2 Pfeile, das ginge auch"), dann der ✕-Button."""
    row = hbox(2)
    is_folder = node.get("type") == "folder"
    is_sys = node.get("_source") == "sys"
    name = node.get("name", "?") + (" ›" if is_folder else "")
    if is_sys:
        name += "  (system)"
    icon = node.get("icon") or ("folder" if is_folder else "application-x-executable")

    if on_change_icon:
        icon_btn: Gtk.Widget = Gtk.Button()
        icon_btn.get_style_context().add_class("bubble")
        icon_btn.get_style_context().add_class("item")
        icon_btn.set_tooltip_text("Change icon")
        icon_btn.add(_applauncher_icon_img(icon))
        icon_btn.connect("clicked", lambda _b: on_change_icon())
    else:
        icon_btn = _applauncher_icon_img(icon)   # read-only (menu.json) - kein Button, kein Hover
    row.pack_start(icon_btn, False, False, 0)

    if on_open:
        b = Gtk.Button()
        b.get_style_context().add_class("bubble")
        b.get_style_context().add_class("item")
        lbl = Gtk.Label(label=name)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_max_width_chars(_APPLAUNCHER_NAME_MAX_CHARS)
        b.add(lbl)
        b.connect("clicked", lambda _b: on_open())
        content: Gtk.Widget = b
    else:
        inner = hbox(6)
        inner.get_style_context().add_class("bubble")
        inner.get_style_context().add_class("item")
        pad(inner, h=6, v=3)
        lbl = Gtk.Label(label=name)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_max_width_chars(_APPLAUNCHER_NAME_MAX_CHARS)
        inner.pack_start(lbl, True, True, 0)
        content = inner

    row.pack_start(content, True, True, 0)

    # Reorder-Pfeile und ✕ gibt's NUR für user-eigene Einträge - für
    # menu.json-Einträge (on_* ist dann None) werden sie gar nicht erst
    # gebaut, statt sie nur ausgegraut anzuzeigen (read-only = read-only).
    if on_move_up is not None or on_move_down is not None:
        up = Gtk.Button.new_from_icon_name("go-up-symbolic", Gtk.IconSize.MENU)
        up.set_relief(Gtk.ReliefStyle.NONE)
        up.set_tooltip_text("Move up")
        up.set_sensitive(on_move_up is not None)
        if on_move_up:
            up.connect("clicked", lambda _b: on_move_up())
        row.pack_start(up, False, False, 0)

        down = Gtk.Button.new_from_icon_name("go-down-symbolic", Gtk.IconSize.MENU)
        down.set_relief(Gtk.ReliefStyle.NONE)
        down.set_tooltip_text("Move down")
        down.set_sensitive(on_move_down is not None)
        if on_move_down:
            down.connect("clicked", lambda _b: on_move_down())
        row.pack_start(down, False, False, 0)

    if on_remove:
        rm = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.MENU)
        rm.set_relief(Gtk.ReliefStyle.NONE)
        rm.set_tooltip_text("Unassign")
        rm.connect("clicked", lambda _b: on_remove())
        row.pack_start(rm, False, False, 0)
    return row

def _applauncher_source_row(entry: dict, subtitle: str | None, on_click) -> Gtk.Button:
    """Zeile in der rechten Quell-Liste - klicken = der im linken
    Bereich gerade geöffnete Ordner bekommt diesen Eintrag."""
    b = Gtk.Button()
    b.get_style_context().add_class("bubble")
    b.get_style_context().add_class("item")
    row = hbox(6); pad(row, h=2, v=0)
    row.pack_start(_applauncher_icon_img(entry.get("icon")), False, False, 0)
    txt = vbox(0)
    lbl = Gtk.Label(label=entry.get("name", "?"))
    lbl.set_halign(Gtk.Align.START)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_max_width_chars(_APPLAUNCHER_NAME_MAX_CHARS)
    txt.pack_start(lbl, False, False, 0)
    if subtitle:
        sub = Gtk.Label(label=subtitle)
        sub.set_halign(Gtk.Align.START)
        sub.set_opacity(0.6)
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.set_max_width_chars(_APPLAUNCHER_NAME_MAX_CHARS)
        sub.get_style_context().add_class("caption")
        txt.pack_start(sub, False, False, 0)
    row.pack_start(txt, True, True, 0)
    b.add(row)
    b.connect("clicked", lambda _b: on_click())
    return b

def _applauncher_pinned_row(icon_name: str, label: str, on_click) -> Gtk.Button:
    b = Gtk.Button()
    b.get_style_context().add_class("bubble")
    b.get_style_context().add_class("item")
    b.get_style_context().add_class("active")
    row = hbox(4); pad(row, h=2, v=0)
    row.pack_start(_applauncher_icon_img(icon_name), False, False, 0)
    row.pack_start(Gtk.Label(label=label), False, False, 0)
    b.add(row)
    b.connect("clicked", lambda _b: on_click())
    return b

def _applauncher_known_icon_names() -> list:
    """Icon-Namen aller gescannten Desktop-Apps (nur Theme-Namen, keine
    absoluten Pfade - die landen eh nicht in einem durchsuchbaren Theme-
    Icon-Grid), dedupliziert + sortiert. Das ist die "von vorhandenen
    Apps"-Quelle für den Icon-Picker."""
    names = set()
    for e in _applauncher_scan_desktop_apps():
        ic = (e.get("icon") or "").strip()
        if ic and not os.path.isabs(ic):
            names.add(ic)
    return sorted(names, key=str.casefold)

def _applauncher_icons_dir() -> Path:
    return _applauncher_sys_menu_path().parent / "icons"

def _applauncher_import_custom_icon(src_path: str) -> str:
    """Kopiert ein frei gewähltes Bild (z.B. aus ~/Downloads) stabil nach
    .../AppLauncher/icons/ und gibt den NEUEN absoluten Pfad zurück.
    Grund: load_icon_pixbuf() in TrafkTuxLauncher.c akzeptiert zwar
    absolute Pfade, aber eben nur absolute - verschiebt/löscht man die
    Originaldatei später (oder synct die Config auf einen anderen
    Rechner, wo sie unter dem Pfad gar nicht existiert), zeigt das Icon
    nur noch den Fallback. Mit eigener Kopie im Config-Baum bleibt es
    stabil UND wandert mit, wenn der restliche TrafkTux-Config gesynct
    wird (gleicher Pfad relativ zu $HOME auf jeder Maschine)."""
    src = Path(src_path)
    icons_dir = _applauncher_icons_dir()
    icons_dir.mkdir(parents=True, exist_ok=True)
    dest = icons_dir / src.name
    if dest.resolve() != src.resolve():
        n = 1
        while dest.exists():
            dest = icons_dir / f"{src.stem}-{n}{src.suffix}"
            n += 1
        shutil.copy2(src, dest)
    return str(dest)

def _applauncher_pick_icon(parent: Gtk.Window, current: str = "") -> str | None:
    """Icon-Auswahl-Dialog mit 2 Reitern: 'From Apps' (durchsuchbares
    Grid aller Icon-Namen aus den gescannten .desktop-Dateien) und
    'Custom Image' (Dateiauswahl - der volle Pfad wird direkt als Icon-
    Wert übernommen; _applauncher_icon_img() versteht sowohl Theme-
    Namen als auch absolute Pfade, siehe dort). Gibt den gewählten
    Icon-Wert zurück, oder None bei Abbruch."""
    dlg = Gtk.Dialog(title="Choose icon", transient_for=parent)
    dlg.set_name("wb-daemon-popup")
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    dlg.set_default_size(260, 340)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL)
    box = dlg.get_content_area()
    result = {"icon": None}

    def _choose(icon_value: str):
        result["icon"] = icon_value
        dlg.response(Gtk.ResponseType.OK)

    # ── Reiter "From Apps" ──────────────────────────────────────────
    search_e = Gtk.Entry(); search_e.set_placeholder_text("Search…")
    flow = Gtk.FlowBox()
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    flow.set_max_children_per_line(5)
    flow.set_homogeneous(True)
    flow_sw = Gtk.ScrolledWindow()
    flow_sw.set_size_request(240, 220)
    flow_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    flow_sw.add(flow)
    all_names = _applauncher_known_icon_names()

    def _populate(filter_text: str = ""):
        for c in list(flow.get_children()):
            flow.remove(c)
        ft = filter_text.strip().casefold()
        shown = [n for n in all_names if ft in n.casefold()][:150] if ft else all_names[:150]
        for n in shown:
            ib = Gtk.Button()
            ib.get_style_context().add_class("bubble")
            ib.get_style_context().add_class("item")
            ib.set_tooltip_text(n)
            ib.add(_applauncher_icon_img(n, 24))
            ib.connect("clicked", lambda _b, nn=n: _choose(nn))
            flow.add(ib)
        flow.show_all()
    search_e.connect("changed", lambda _e: _populate(search_e.get_text()))
    _populate()

    from_apps_page = vbox(4)
    from_apps_page.pack_start(search_e, False, False, 0)
    from_apps_page.pack_start(flow_sw, True, True, 0)

    # ── Reiter "Custom Image" ────────────────────────────────────────
    custom_page = vbox(8); pad(custom_page, h=10, v=30)
    pick_file_btn = btn("📁  Choose image file…")
    def _on_pick_file(_b):
        fc = Gtk.FileChooserDialog(title="Choose icon image", transient_for=dlg,
                                    action=Gtk.FileChooserAction.OPEN)
        fc.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Choose", Gtk.ResponseType.OK)
        img_filter = Gtk.FileFilter(); img_filter.set_name("Images")
        for pattern in ("*.png", "*.svg", "*.jpg", "*.jpeg", "*.xpm", "*.webp"):
            img_filter.add_pattern(pattern)
        fc.add_filter(img_filter)
        fc.set_filter(img_filter)
        resp = fc.run()
        path = fc.get_filename() if resp == Gtk.ResponseType.OK else None
        fc.destroy()
        if path:
            try:
                stable_path = _applauncher_import_custom_icon(path)
            except Exception:
                stable_path = path  # Kopieren fehlgeschlagen - lieber Original als gar nichts
            _choose(stable_path)
    pick_file_btn.connect("clicked", _on_pick_file)
    custom_page.pack_start(pick_file_btn, False, False, 0)

    # ── Reiter-Umschalter (gleiches Muster wie die Sortier-Tabs) ─────
    stack = Gtk.Stack()
    stack.add_named(from_apps_page, "from_apps")
    stack.add_named(custom_page, "custom")
    stack.set_visible_child_name("from_apps")
    tab_row = hbox(4); tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns = {}
    def _switch_tab(name):
        stack.set_visible_child_name(name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, tlabel in (("from_apps", "From Apps"), ("custom", "Custom Image")):
        b = btn(tlabel, active=(name == "from_apps"))
        b.connect("clicked", lambda _b, n=name: _switch_tab(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)

    box.pack_start(tab_row, False, False, 4)
    box.pack_start(tab_sep(), False, False, 0)
    box.pack_start(stack, True, True, 4)
    dlg.show_all()
    dlg.run()
    dlg.destroy()
    return result["icon"]

def _build_app_launcher_tab(win: Gtk.Window) -> Gtk.Box:
    root = vbox(4); pad(root, h=4, v=6)

    _sys_tree = _applauncher_load_sys_tree()
    _user_tree = _applauncher_load_user_tree(_sys_tree)
    state = {
        "sys_tree": _sys_tree,      # menu.json - read-only, nie gespeichert
        "user_tree": _user_tree,    # Usermenu.json - das wird editiert+gespeichert
        "tree": _applauncher_build_merged_tree(_sys_tree, _user_tree),  # gemergt, nur fürs Anzeigen/Dedup
        "dirty": False,
        "cur_path": [],            # [] == Root-Ansicht (9 Ordner)
        "sort_mode": "unsorted",   # unsorted | all
        "search": "",
    }

    def _recompute_merged():
        state["tree"] = _applauncher_build_merged_tree(state["sys_tree"], state["user_tree"])

    status_lbl = Gtk.Label(label="")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    status_lbl.set_no_show_all(True)
    status_lbl.hide()

    def _flash(text: str, ms: int = 2500):
        status_lbl.set_label(text)
        status_lbl.show()
        GLib.timeout_add(ms, lambda: (status_lbl.hide(), False)[1])

    # ── Kopfzeile: klickbarer Breadcrumb + Reload/Save ──────────────
    head_row = hbox(6)
    breadcrumb_box = hbox(2)   # wird in _refresh_breadcrumb() befüllt
    breadcrumb_sw = Gtk.ScrolledWindow()
    breadcrumb_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    breadcrumb_sw.set_propagate_natural_height(True)
    breadcrumb_sw.add(breadcrumb_box)
    back_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
    back_btn.set_relief(Gtk.ReliefStyle.NONE)
    back_btn.set_no_show_all(True)
    save_btn = btn("󰆓  Save")
    save_btn.set_sensitive(False)
    reload_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
    reload_btn.set_relief(Gtk.ReliefStyle.NONE)
    reload_btn.set_tooltip_text("Discard unsaved changes & reload from disk")
    head_row.pack_start(back_btn, False, False, 0)
    head_row.pack_start(breadcrumb_sw, True, True, 0)
    head_row.pack_start(reload_btn, False, False, 0)
    head_row.pack_start(save_btn, False, False, 0)
    root.pack_start(head_row, False, False, 0)
    root.pack_start(sep(), False, False, 0)   # dünner Trenner - bleibt so

    def _refresh_breadcrumb():
        for c in breadcrumb_box.get_children():
            breadcrumb_box.remove(c)
        root_btn = btn("󱁤 Root")
        root_btn.set_relief(Gtk.ReliefStyle.NONE)
        root_btn.connect("clicked", lambda _b: _go_to([]))
        breadcrumb_box.pack_start(root_btn, False, False, 0)
        node = state["tree"]
        for i, idx in enumerate(state["cur_path"]):
            node = node["children"][idx]
            slash = Gtk.Label(label="/")
            slash.set_opacity(0.5)
            breadcrumb_box.pack_start(slash, False, False, 0)
            seg_path = state["cur_path"][:i + 1]
            seg_btn = btn(node.get("name", "?"))
            seg_btn.set_relief(Gtk.ReliefStyle.NONE)
            seg_lbl = seg_btn.get_child()
            if isinstance(seg_lbl, Gtk.Label):
                seg_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                seg_lbl.set_max_width_chars(14)
            seg_btn.connect("clicked", lambda _b, p=seg_path: _go_to(p))
            breadcrumb_box.pack_start(seg_btn, False, False, 0)
        breadcrumb_box.show_all()

    def _mark_dirty():
        state["dirty"] = True
        save_btn.set_sensitive(True)
        save_btn.set_label("󰆓  Save*")

    # ── Linke Seite: Ordner-Grid (Root) bzw. Ordner-Inhalt (Sub) ────
    folder_area = vbox(4)
    folder_area_sw = Gtk.ScrolledWindow()
    folder_area_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    folder_area_sw.set_max_content_height(230)
    folder_area_sw.set_propagate_natural_height(True)
    folder_area_sw.set_valign(Gtk.Align.START)
    folder_area_sw.add(folder_area)
    folder_area_sw.set_size_request(205, -1)

    # ── Rechte Seite: gepinnte Create-Icons + Suche + Sortier-Tabs + Liste
    pinned_row = hbox(4); pinned_row.set_halign(Gtk.Align.CENTER)
    search_e = Gtk.Entry()
    search_e.set_placeholder_text("Search apps…")
    search_e.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "system-search-symbolic")
    search_e.get_style_context().add_class("applauncher-search")
    sort_row = hbox(4); sort_row.set_halign(Gtk.Align.CENTER)
    sort_btns: dict = {}
    list_sw, list_box = scroll_box(190)   # etwas niedriger - mehr Luft unten (Pkt. 6)
    list_sw.set_valign(Gtk.Align.START)
    # Harte Breiten-Grenze: ohne die wächst die Spalte mit dem längsten
    # App-Namen mit (set_size_request auf der Box ist nur ein Minimum,
    # kein Maximum) - zusammen mit set_max_width_chars auf den Labels
    # in den Zeilen-Widgets sorgt das für echtes Abschneiden mit "…"
    # statt eines immer breiter werdenden Fensters.
    list_sw.set_size_request(260, -1)

    side = hbox(8)
    left_col = vbox(4); left_col.set_size_request(205, -1); left_col.set_valign(Gtk.Align.START)
    right_col = vbox(3); right_col.set_size_request(260, -1); right_col.set_valign(Gtk.Align.START)
    left_col.pack_start(folder_area_sw, False, False, 0)
    right_col.pack_start(pinned_row, False, False, 0)
    right_col.pack_start(search_e, False, False, 0)
    right_col.pack_start(sort_row, False, False, 0)
    right_col.pack_start(sep(), False, False, 0)   # dünner statt tab_sep() (Pkt. 7)
    right_col.pack_start(list_sw, False, False, 0)
    vsep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    vsep.set_valign(Gtk.Align.START)
    vsep.set_size_request(-1, 320)   # stretcht nicht mehr bis ganz unten (Pkt. 6)
    side.pack_start(left_col, True, True, 0)
    side.pack_start(vsep, False, False, 0)
    side.pack_start(right_col, True, True, 0)

    root.pack_start(side, False, False, 0)
    root.pack_start(status_lbl, False, False, 2)
    bottom_spacer = Gtk.Box()
    bottom_spacer.set_size_request(-1, 10)   # etwas Platz unten (Pkt. 6)
    root.pack_start(bottom_spacer, False, False, 0)

    # ── Dialoge ───────────────────────────────────────────────────────
    def _icon_pick_row(dlg: Gtk.Dialog, icon_e: Gtk.Entry) -> Gtk.Box:
        """Icon-Entry + Live-Vorschau + 'Choose...'-Button - gemeinsam
        für den Folder- und den Custom-App-Dialog."""
        row = hbox(6)
        preview = Gtk.Image()
        def _refresh_preview():
            preview.clear()
            img = _applauncher_icon_img(icon_e.get_text().strip() or "application-x-executable", 22)
            # Pixbuf/Icon-Name vom frisch gebauten Image auf die feste
            # preview-Instanz übernehmen, statt das Image im Baum zu
            # ersetzen (einfacher als preview jedes Mal neu einzuhängen).
            if img.get_storage_type() == Gtk.ImageType.PIXBUF:
                preview.set_from_pixbuf(img.get_pixbuf())
            else:
                preview.set_from_icon_name(icon_e.get_text().strip() or "application-x-executable",
                                            Gtk.IconSize.BUTTON)
                preview.set_pixel_size(22)
        icon_e.connect("changed", lambda _e: _refresh_preview())
        pick_btn = Gtk.Button.new_with_label("Choose…")
        def _on_pick(_b):
            chosen = _applauncher_pick_icon(dlg, icon_e.get_text().strip())
            if chosen:
                icon_e.set_text(chosen)
        pick_btn.connect("clicked", _on_pick)
        row.pack_start(preview, False, False, 0)
        row.pack_start(icon_e, True, True, 0)
        row.pack_start(pick_btn, False, False, 0)
        _refresh_preview()
        return row

    def _ask_new_folder(is_root: bool = False):
        dlg = Gtk.Dialog(title="New folder", transient_for=win)
        dlg.set_name("wb-daemon-popup")
        dlg.set_modal(True)
        dlg.set_keep_above(True)
        dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Create", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        name_e = Gtk.Entry(); name_e.set_placeholder_text("Folder name")
        name_e.set_activates_default(True)
        name_e.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
        icon_e = Gtk.Entry(); icon_e.set_text("folder"); icon_e.set_placeholder_text("Icon")
        box.pack_start(name_e, True, True, 4)
        box.pack_start(_icon_pick_row(dlg, icon_e), True, True, 4)
        # "hidden" ist nur auf Root-Ebene überhaupt relevant - TrafkTuxLauncher
        # blendet nur dort danach gefilterte Ordner aus dem Haupt-Grid aus
        # (siehe TrafkTuxLauncher.c-Patch: build_menu_slots, is_root-Zweig).
        hidden_cb = None
        if is_root:
            hidden_cb = Gtk.CheckButton.new_with_label("Hide from launcher's root menu")
            hidden_cb.set_tooltip_text(
                "Stays in menu.json and still counts as \"ordered\" for Unsorted - "
                "just never shows up as a tile in TrafkTuxLauncher itself.")
            box.pack_start(hidden_cb, True, True, 4)
        dlg.show_all()
        resp = dlg.run()
        result = None
        if resp == Gtk.ResponseType.OK:
            nm = name_e.get_text().strip()
            if nm:
                result = {"name": nm, "icon": icon_e.get_text().strip() or "folder",
                          "hidden": bool(hidden_cb and hidden_cb.get_active())}
        dlg.destroy()
        return result

    def _ask_custom_app():
        dlg = Gtk.Dialog(title="New custom app", transient_for=win)
        dlg.set_name("wb-daemon-popup")
        dlg.set_modal(True)
        dlg.set_keep_above(True)
        dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        name_e = Gtk.Entry(); name_e.set_placeholder_text("Name")
        icon_e = Gtk.Entry(); icon_e.set_text("application-x-executable")
        exec_e = Gtk.Entry(); exec_e.set_placeholder_text("Command")
        exec_e.set_activates_default(True)
        exec_e.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
        box.pack_start(name_e, True, True, 4)
        box.pack_start(_icon_pick_row(dlg, icon_e), True, True, 4)
        box.pack_start(exec_e, True, True, 4)
        dlg.show_all()
        resp = dlg.run()
        result = None
        if resp == Gtk.ResponseType.OK:
            nm = name_e.get_text().strip()
            ex = exec_e.get_text().strip()
            if nm and ex:
                result = {"name": nm, "type": "app",
                          "icon": icon_e.get_text().strip() or "application-x-executable",
                          "exec": ex, "custom": True}
        dlg.destroy()
        return result

    # ── Save / Reload ────────────────────────────────────────────────
    def _on_save(_b=None):
        try:
            # menu.json wird NIE geschrieben - nur noch Usermenu.json,
            # das gehört exklusiv dem Editor (menu.json "gehört" dem
            # System/Update-Skript, siehe ensure_user_menu_skeleton() in
            # der neuen TrafkTuxLauncher.c).
            _applauncher_save_user_tree(state["user_tree"])
            state["dirty"] = False
            save_btn.set_label("󰆓  Save")
            save_btn.set_sensitive(False)
            # TrafkTuxLauncher lädt + mergt menu.json/Usermenu.json nur
            # einmal beim Start in app->root und baut das Fenster danach
            # nie neu - ohne Neustart wäre die Änderung also nie sichtbar.
            # Exakt derselbe Befehl wie der Daemon-Autostart in hyprland.lua.
            run_bg(["bash", "-c",
                    "killall TrafkTuxLauncher; "
                    "$HOME/.config/TrafkTuxLauncher/TrafkTuxLauncher --daemon &"])
            _flash("Saved — TrafkTuxLauncher restarting…")
        except Exception as e:
            _flash(f"Error: {e}")
    save_btn.connect("clicked", _on_save)

    def _on_reload(_b=None):
        state["sys_tree"] = _applauncher_load_sys_tree()
        state["user_tree"] = _applauncher_load_user_tree(state["sys_tree"])
        _recompute_merged()
        state["dirty"] = False
        state["cur_path"] = []
        save_btn.set_label("󰆓  Save")
        save_btn.set_sensitive(False)
        _refresh_all()
        _flash("Reloaded from disk")
    reload_btn.connect("clicked", _on_reload)

    # ── Drop-Logik: einen Payload (App / New-Folder / New-Custom /
    # Move) auf einen Ziel-Ordner-Pfad anwenden ─────────────────────
    def _apply_drop(target_path: list, payload: dict):
        """Ziel ist immer ein Pfad im GEMERGTEN Baum (state['tree']) -
        wird hier über den Namens-Pfad in state['user_tree'] aufgelöst
        (und dort bei Bedarf automatisch als leerer Ordner angelegt).
        Geschrieben wird IMMER nur user_tree, nie der gemergte Baum
        direkt und nie sys_tree."""
        merged_target = _applauncher_node_at(state["tree"], target_path)
        if merged_target is None or merged_target.get("type") != "folder":
            return
        kind = payload.get("kind")
        if kind == "new_folder":
            info = _ask_new_folder(is_root=(target_path == []))
            if not info:
                return
            new_node = {"name": info["name"], "type": "folder", "icon": info["icon"], "children": []}
            if info.get("hidden"):
                new_node["hidden"] = True
        elif kind == "new_custom_app":
            new_node = _ask_custom_app()
            if not new_node:
                return
        elif kind == "app":
            new_node = {"name": payload.get("name", "App"), "type": "app",
                        "icon": payload.get("icon") or "application-x-executable",
                        "exec": payload.get("exec", "")}
        else:
            return
        name_chain = _applauncher_name_chain(state["tree"], target_path)
        user_target = _applauncher_resolve_or_create_user_path(state["user_tree"], name_chain)
        user_target.setdefault("children", []).append(new_node)
        _mark_dirty()
        _recompute_merged()
        _refresh_all()

    def _resolve_user_node(merged_path: list):
        """Für einen Pfad im gemergten Baum, der auf einen Knoten MIT
        "_source": "user" zeigt: liefert (user_children_list, index) in
        state['user_tree'], damit er dort entfernt/umsortiert/geändert
        werden kann. None, wenn der Pfad auf einen sys-Knoten zeigt
        (menu.json-Einträge sind über den Editor nie änderbar) oder sich
        nicht auflösen lässt."""
        merged_node = _applauncher_node_at(state["tree"], merged_path)
        if merged_node is None or merged_node.get("_source") != "user":
            return None
        parent_chain = _applauncher_name_chain(state["tree"], merged_path[:-1])
        user_parent = _applauncher_resolve_or_create_user_path(state["user_tree"], parent_chain)
        user_children = user_parent.setdefault("children", [])
        for idx, uc in enumerate(user_children):
            if (uc.get("name") == merged_node.get("name")
                    and uc.get("type") == merged_node.get("type")
                    and uc.get("exec") == merged_node.get("exec")):
                return user_children, idx
        return None

    def _on_remove_user(merged_path: list):
        resolved = _resolve_user_node(merged_path)
        if resolved is None:
            _flash("That's a system entry (menu.json) - can't remove it here")
            return
        children, idx = resolved
        children.pop(idx)
        _mark_dirty()
        _recompute_merged()
        _refresh_all()

    # ── Navigation ───────────────────────────────────────────────────
    def _go_to(path: list):
        state["cur_path"] = path
        _refresh_folder_area()

    def _go_back():
        if state["cur_path"]:
            _go_to(state["cur_path"][:-1])
    back_btn.connect("clicked", lambda _b: _go_back())

    # ── "aktuell geöffneter Ordner" - zentrale Stelle für alle Klick-
    # Aktionen rechts (Apps/Pins). Root zählt NICHT als offener Ordner. ─
    def _require_open_folder() -> list | None:
        if not state["cur_path"]:
            _flash("Open one of the 9 folders first, then click an app to add it there")
            return None
        return list(state["cur_path"])

    def _on_new_folder_clicked():
        # Einzige Ausnahme von "erst einen Ordner öffnen": ein neuer
        # Ordner darf auch direkt auf Root-Ebene entstehen (z.B. für
        # einen versteckten "Unimportant"-Sammelordner, siehe Chat) -
        # Root selbst ist im Baum ja auch nur ein ganz normaler
        # "type": "folder"-Knoten, _apply_drop([], ...) hängt dann
        # direkt an tree["children"] an.
        _apply_drop(list(state["cur_path"]), {"kind": "new_folder"})

    def _on_new_custom_app_clicked():
        target = _require_open_folder()
        if target is not None:
            _apply_drop(target, {"kind": "new_custom_app"})

    def _on_source_entry_clicked(entry: dict):
        target = _require_open_folder()
        if target is None:
            return
        _apply_drop(target, {"kind": "app", "name": entry.get("name", "App"),
                              "icon": entry.get("icon"), "exec": entry.get("exec")})

    def _move_child(merged_path: list, delta: int):
        """Vertauscht den (user-eigenen!) Knoten an merged_path mit
        seinem Nachbarn INNERHALB der user_tree-Kinderliste desselben
        Ordners - sys-Einträge (menu.json) lassen sich hier nicht
        umsortieren, daher gibt's für die auch keine Pfeile."""
        resolved = _resolve_user_node(merged_path)
        if resolved is None:
            return
        children, idx = resolved
        j = idx + delta
        if 0 <= j < len(children):
            children[idx], children[j] = children[j], children[idx]
            _mark_dirty()
            _recompute_merged()
            _refresh_folder_area()

    def _on_change_icon(merged_path: list):
        resolved = _resolve_user_node(merged_path)
        if resolved is None:
            _flash("That's a system entry (menu.json) - can't change its icon here")
            return
        children, idx = resolved
        node = children[idx]
        chosen = _applauncher_pick_icon(win, node.get("icon") or "")
        if not chosen:
            return
        node["icon"] = chosen
        _mark_dirty()
        _recompute_merged()
        _refresh_folder_area()

    # ── Linke Seite neu aufbauen ─────────────────────────────────────
    def _refresh_folder_area():
        for c in folder_area.get_children():
            folder_area.remove(c)
        _refresh_breadcrumb()
        back_btn.set_visible(bool(state["cur_path"]))

        if not state["cur_path"]:
            grid = Gtk.Grid(column_spacing=6, row_spacing=6)
            grid.set_halign(Gtk.Align.CENTER)
            col = row = 0
            for i, child in enumerate(state["tree"].get("children", [])):
                if child.get("type") != "folder":
                    continue
                cell = _applauncher_folder_cell(child, lambda p=[i]: _go_to(p))
                grid.attach(cell, col, row, 1, 1)
                col += 1
                if col >= 3:
                    col = 0; row += 1
            folder_area.pack_start(grid, False, False, 0)
        else:
            node = _applauncher_node_at(state["tree"], state["cur_path"])
            if node is None:
                state["cur_path"] = []
                return _refresh_folder_area()
            kids = node.get("children", [])
            if not kids:
                folder_area.pack_start(bitem("Empty — click an app on the right to add it here", dim=True),
                                        False, False, 0)
            for i, child in enumerate(kids):
                cpath = state["cur_path"] + [i]
                is_user = child.get("_source") == "user"
                row_w = _applauncher_child_row(
                    child,
                    on_open=(lambda p=cpath: _go_to(p)) if child.get("type") == "folder" else None,
                    # Nur user-eigene Einträge (aus Usermenu.json) lassen
                    # sich entfernen/umsortieren/im Icon ändern - alles
                    # aus menu.json ist hier read-only.
                    on_remove=(lambda p=cpath: _on_remove_user(p)) if is_user else None,
                    on_change_icon=(lambda p=cpath: _on_change_icon(p)) if is_user else None,
                    on_move_up=(lambda p=cpath: _move_child(p, -1)) if is_user else None,
                    on_move_down=(lambda p=cpath: _move_child(p, 1)) if is_user else None)
                folder_area.pack_start(row_w, False, False, 0)
        folder_area.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    # ── Rechte Seite: nur noch Unsorted/All Apps (Custom/Ordered/All
    # Packages auf Wunsch wieder raus) + Namens-Suche ────────────────
    _SORT_MODES = (("unsorted", "Unsorted"), ("all", "All Apps"))

    def _switch_sort(mode: str):
        state["sort_mode"] = mode
        for n, b in sort_btns.items():
            ctx = b.get_style_context()
            if n == mode: ctx.add_class("active")
            else:         ctx.remove_class("active")
        _refresh_list()
    for mkey, mlabel in _SORT_MODES:
        b = btn(mlabel, active=(mkey == "unsorted"))
        b.connect("clicked", lambda _b, n=mkey: _switch_sort(n))
        sort_btns[mkey] = b
        sort_row.pack_start(b, False, False, 0)

    def _on_search_changed(_e):
        state["search"] = search_e.get_text()
        _refresh_list()
    search_e.connect("changed", _on_search_changed)

    new_folder_row = _applauncher_pinned_row("folder-new", "New Folder", _on_new_folder_clicked)
    new_app_row = _applauncher_pinned_row("list-add", "New Custom App", _on_new_custom_app_clicked)
    pinned_row.pack_start(new_folder_row, False, False, 0)
    pinned_row.pack_start(new_app_row, False, False, 0)

    def _refresh_list():
        for c in list_box.get_children():
            list_box.remove(c)
        mode = state["sort_mode"]
        entries = _applauncher_unsorted_apps(state["tree"]) if mode == "unsorted" \
            else _applauncher_scan_desktop_apps()
        needle = state["search"].strip().casefold()
        if needle:
            entries = [e for e in entries if needle in e["name"].casefold()]

        if not entries:
            list_box.pack_start(bitem("Nothing here", dim=True), False, False, 0)
        for e in entries[:400]:
            row_w = _applauncher_source_row(e, None, lambda ee=e: _on_source_entry_clicked(ee))
            list_box.pack_start(row_w, False, False, 0)
        list_box.show_all()
        GLib.idle_add(_shrink_to_fit, win)

    def _refresh_all():
        _refresh_folder_area()
        _refresh_list()

    _refresh_all()
    return root

def _build_settings_apps(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    root = vbox(4)
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    tab_row_top = hbox(4); tab_row_top.set_halign(Gtk.Align.CENTER)
    tab_row_bottom = hbox(4); tab_row_bottom.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}

    def _switch(name):
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")

    def _placeholder(text: str) -> Gtk.Box:
        b = vbox(4); pad(b, h=4, v=14)
        b.pack_start(bitem(text, dim=True), False, False, 0)
        return b

    # Nur Tab 1 (Launcher) ist bereits fertig - 2/3/5 folgen als
    # nächstes, 4 (Default Apps) bewusst als Platzhalter (siehe Chat:
    # Recherche zu xdg-mime/mimeapps.list kommt zuletzt).
    stack.add_named(_build_app_launcher_tab(win), "launcher")
    stack.add_named(_placeholder("Bar shortcuts editor — coming next"), "bar")
    stack.add_named(_placeholder("Autostart editor — coming next"), "autostart")
    stack.add_named(_placeholder("Default apps — coming last (needs its own research pass)"), "defaults")
    stack.add_named(_placeholder("Wine/GameScope excludes — coming next"), "wine")

    for name, tlabel, trow in (
            ("launcher", "Launcher", tab_row_top), ("bar", "Bar", tab_row_top),
            ("autostart", "Autostart", tab_row_top),
            ("defaults", "Defaults", tab_row_bottom), ("wine", "Wine", tab_row_bottom)):
        b = btn(tlabel, active=(name == "launcher"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        trow.pack_start(b, False, False, 0)
    stack.set_visible_child_name("launcher")

    root.pack_start(tab_row_top, True, False, 2)
    root.pack_start(tab_row_bottom, True, False, 0)
    root.pack_start(tab_sep(), False, False, 0)
    root.pack_start(stack, False, False, 0)
    page.pack_start(root, True, True, 0)

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
    "apps":       _build_settings_apps,
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
                # Redesign-Liste: "Unter Display eine fette Linie
                # anstatt einer dünnen" - NUR für die Display-Seite,
                # alle anderen Kategorien behalten den normalen
                # dünnen sep().
                page.pack_start(hub_sep() if cat_key in ("display", "security") else sep(),
                                 False, False, 2)
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
    hub.pack_start(hub_sep(), False, False, 0)

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
    # Waybar-Icon (Display, Appearance & Language, Apps & Shortcuts) -
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
            lines.append(f"WARNING: UNTRACKED toplevels (nicht in _open!): {len(untracked)}")
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
                print(f"WARNING: Theme-Reconcile beim Start fehlgeschlagen: {err}",
                      file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Theme-Reconcile beim Start fehlgeschlagen: {e}", file=sys.stderr)

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
