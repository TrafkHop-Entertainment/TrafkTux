#!/usr/bin/env python3
"""
widgets_daemon.py — TrafkTux Waybar Widget System (Daemon)
Invocation: python3 widgets_daemon.py
Controlled via client: widgets_client.py <widget>
Widgets: volume | network | bluetooth | brightness | akku | clock | settings
"""

import gi, sys, os, re, signal, subprocess, json, threading, time, calendar, shutil, traceback
import random, math
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
BUBBLE_PATH = "/tmp/bubble-normal.png"   # die eine große Blase, per Cairo gezeichnet (siehe _draw_window)
B_NORM = f"file://{BUBBLE_PATH}"
B_SEL  = "file:///tmp/bubble-selected.png"
WALLPAPER_SCRIPT = f"{HOME}/.config/hypr/random_wallpaper.sh"

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

.bubble.section {{
    padding: 3px 16px;
    margin: 6px 0px 1px 0px;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
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
    padding: 6px 14px;
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
}}
button.bubble:hover, button.bubble:active, button.bubble:checked,
.bubble.dropdown:hover, .bubble.dropdown:focus {{
    color: {GOLD};
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
#  Systemsounds (soundctl.sh)
# ════════════════════════════════════════════════════════════
# Alle Sound-Events laufen über das zentrale soundctl.sh (siehe
# ~/.config/hypr/soundctl.sh), das selbst prüft, ob Sounds gerade
# aktiviert sind - hier also einfach immer fire-and-forget aufrufen.
SOUNDCTL = os.path.join(HOME, ".config", "hypr", "soundctl.sh")

def _play_sound(event: str) -> None:
    run_bg(["bash", SOUNDCTL, event])

def _sounds_enabled() -> bool:
    return run(["bash", SOUNDCTL, "--status"]) == "on"

def _set_sounds_enabled(enabled: bool) -> None:
    run_bg(["bash", SOUNDCTL, "--enable" if enabled else "--disable"])

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

_POPUP_MS   = 240   # Dauer der "wächst rein"-Animation beim Öffnen
_FADE_MS    = 150   # Dauer des Ausblendens beim Schließen/Wechseln
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
    per Cairo/GdkPixbuf gemalt, siehe _paint_bubble_bg) + Popup-
    Wachsen/Schweben + die frei fliegenden Gold-Pünktchen + das
    Crossfade beim Öffnen/Schließen.

    WICHTIG zum Crossfade: das läuft NICHT mehr über win.set_opacity()
    (das hat sich als unzuverlässig auf GtkLayerShell-Overlay-Surfaces
    herausgestellt - manche Wayland-Compositor ziehen Live-Änderungen
    der Fenster-Opacity nicht sauber nach, das Fenster blieb dann
    komplett unsichtbar). Stattdessen wird ALLES (Hintergrund-Blase +
    Pünktchen + die eigentlichen Kind-Widgets) manuell in eine Cairo-
    Gruppe gemalt (push_group/propagate_draw/pop_group_to_source) und
    die GANZE Gruppe am Ende mit paint_with_alpha() ein- bzw.
    ausgeblendet - das ist reines Cairo-Compositing, hängt an gar
    nichts Wayland/Compositor-Spezifischem und funktioniert daher
    überall gleich zuverlässig."""
    state = _anim.get(win)
    now = time.time()
    alloc = win.get_allocation()
    w, h = max(alloc.width, 1), max(alloc.height, 1)

    if state is None:
        # Kein Cairo-Zustand (z.B. HAS_CAIRO=False) - einfach normal
        # zeichnen lassen, ohne jeden Effekt.
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        _paint_bubble_bg(ctx, w, h)
        return False

    t_pop = (now - state["popup_start"]) / (_POPUP_MS / 1000.0)
    p_grow = _ease_out_cubic(t_pop)

    closing_since = state.get("closing_since")
    if closing_since is not None:
        t_close = (now - closing_since) / (_FADE_MS / 1000.0)
        fade = max(0.0, 1.0 - t_close)
    else:
        fade = p_grow   # Reinwachsen UND Reinblenden laufen zusammen

    # Wächst von klein (nahe der Waybar, unten rechts verankert) träge
    # nach oben/groß werdend rein, statt abrupt zu erscheinen.
    scale = 0.35 + 0.65 * p_grow
    ty = h * (1 - scale) + 10 * (1 - p_grow)   # kleiner "schwebt nach oben"-Versatz
    tx = w * (1 - scale)

    ctx.push_group()
    ctx.translate(tx, ty)
    ctx.scale(scale, scale)

    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    _paint_bubble_bg(ctx, w, h)

    r, g, b = _GOLD_RGB
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
        core_alpha = 0.35 * p_grow
        glow_r = pt["r"] * 3.4
        grad = cairo.RadialGradient(cx, cy, 0, cx, cy, glow_r)
        grad.add_color_stop_rgba(0.0, r, g, b, core_alpha)
        grad.add_color_stop_rgba(1.0, r, g, b, 0.0)
        ctx.set_source(grad)
        ctx.arc(cx, cy, glow_r, 0, math.tau)
        ctx.fill()
        ctx.arc(cx, cy, pt["r"], 0, math.tau)
        ctx.set_source_rgba(r, g, b, core_alpha)
        ctx.fill()
        ctx.restore()

    # Die eigentlichen Kind-Widgets (Buttons, Labels, ...) manuell mit
    # in dieselbe Gruppe zeichnen, damit sie beim Ein-/Ausblenden mit
    # verblassen statt abrupt stehen zu bleiben, während nur der
    # Hintergrund faded.
    child = win.get_child()
    if child is not None:
        win.propagate_draw(child, ctx)

    ctx.pop_group_to_source()
    ctx.paint_with_alpha(max(0.0, min(1.0, fade)))
    # True = Signal-Emission hier stoppen, DAMIT GTKs eigener
    # Default-Handler die Kinder nicht noch ein zweites Mal (diesmal
    # ungefadet) obendrauf zeichnet - wir haben das oben schon über
    # propagate_draw() selbst erledigt.
    return True

def _start_popup_in(win: Gtk.Window) -> None:
    """Öffnen-Animation anstoßen: braucht hier gar nichts weiter zu tun
    - _draw_window() berechnet Wachsen UND Einblenden schon direkt aus
    state["popup_start"] (in make_win() gesetzt). Nur einmal neu
    zeichnen, damit der erste Frame nicht erst auf das nächste GTK-
    Ereignis warten muss."""
    win.queue_draw()

def _fade_out_and_close(name: str, win: Gtk.Window) -> None:
    """Blendet ein Fenster per Cairo-Gruppen-Alpha aus (siehe
    _draw_window(), state["closing_since"]) und räumt es danach über
    dieselbe _cleanup()-Funktion auf, die auch make_win() registriert
    hat. KEIN win.set_opacity() (siehe Kommentar in _draw_window()
    dazu, warum das auf Layer-Shell-Surfaces unzuverlässig war)."""
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
    GLib.timeout_add(_FADE_MS + _TICK_MS, lambda: (_finish(), False)[1])

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
        _play_sound("close")
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
    win.show_all()
    _open[name] = win
    _start_popup_in(win)
    _play_sound("open")
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
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, 110)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT,  14)
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
        # Sound zuerst (fire-and-forget, siehe _play_sound), dann der
        # eigentliche Klick-Handler. btn() ist die zentrale Factory für
        # praktisch JEDEN Button im gesamten Widget-System - ein Hook
        # hier deckt also automatisch alle Fenster (volume, network,
        # bluetooth, brightness, akku, clock, settings, ...) ab, ohne
        # dass jede einzelne connect("clicked", ...)-Stelle im Rest der
        # Datei angefasst werden müsste.
        def _wrapped(_b, _cb=cb):
            _play_sound("click")
            return _cb(_b)
        b.connect("clicked", _wrapped)
    return b

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

def _get_sinks() -> list:
    data = jrun(["pactl", "--format=json", "list", "sinks"]) or []
    return [{"name": s.get("name",""), "desc": s.get("description","?")[:44]}
            for s in data]

def _get_sources() -> list:
    data = jrun(["pactl", "--format=json", "list", "sources"]) or []
    return [{"name": s.get("name",""), "desc": s.get("description","?")[:44]}
            for s in data if "monitor" not in s.get("name","").lower()]

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

def _volume_content(win: Gtk.Window) -> Gtk.Box:
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(120)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── TAB 1: Media ────────────────────────────────────────
    t1 = vbox(4); pad(t1, h=4, v=6)

    title_box, title_lbl   = bitem_ref("  No Media")
    for c in title_box.get_children():
        if isinstance(c, Gtk.Label):
            c.get_style_context().add_class("value-md")
    artist_box, artist_lbl = bitem_ref("", dim=True)

    t1.pack_start(title_box,  False, False, 0)
    t1.pack_start(artist_box, False, False, 0)

    prev_b = btn("󰒮", tip="Previous")
    play_b = btn("󰐊", tip="Play/Pause")
    next_b = btn("󰒭", tip="Next")
    prev_b.connect("clicked", lambda _: run_bg(["playerctl", "previous"]))
    play_b.connect("clicked", lambda _: run_bg(["playerctl", "play-pause"]))
    next_b.connect("clicked", lambda _: run_bg(["playerctl", "next"]))
    t1.pack_start(hrow(prev_b, play_b, next_b), False, False, 4)

    t1.pack_start(sep(), False, False, 2)

    t1.pack_start(bsec("VOLUME"), False, False, 0)

    muted = [_is_muted()]
    mute_icon_lbl = Gtk.Label(label="󰖁" if muted[0] else "󰕾")
    mute_icon_lbl.set_opacity(0.7)

    def _on_vol(s):
        in_thread(run, ["wpctl", "set-volume",
                        "@DEFAULT_AUDIO_SINK@", f"{int(s.get_value())}%"])

    vol_box, vol_s = bslider("󰕾", 0, 150, 1, _vol_pct(), cb=_on_vol)
    for ch in vol_box.get_children():
        if isinstance(ch, Gtk.Label):
            vol_box.remove(ch)
            break
    mute_btn = Gtk.Button(label="󰖁" if muted[0] else "󰕾")
    mute_btn.set_relief(Gtk.ReliefStyle.NONE)
    mute_btn.get_style_context().add_class("flat")
    mute_btn.set_opacity(0.7)

    def _on_mute(_):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        muted[0] = _is_muted()
        mute_btn.set_label("󰖁" if muted[0] else "󰕾")
    mute_btn.connect("clicked", _on_mute)
    vol_box.pack_start(mute_btn, False, False, 0)
    vol_box.reorder_child(mute_btn, 0)
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
        t2.pack_start(bsec("OUTPUT"), False, False, 0)
        for s in _get_sinks():
            t2.pack_start(btn(f"  {s['desc']}",
                lambda _, n=s["name"]: (
                    in_thread(run, ["pactl","set-default-sink", n]),
                    GLib.timeout_add(300, _refresh_devices))), False, False, 0)
        t2.pack_start(sep(), False, False, 4)
        t2.pack_start(bsec("INPUT"), False, False, 0)
        for s in _get_sources():
            t2.pack_start(btn(f"  {s['desc']}",
                lambda _, n=s["name"]: (
                    in_thread(run, ["pactl","set-default-source", n]),
                    GLib.timeout_add(300, _refresh_devices))), False, False, 0)
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
            t3.pack_start(bsec(inp["name"].upper()), False, False, 0)
            def _mk(idx):
                return lambda sc: in_thread(
                    run, ["pactl","set-sink-input-volume",
                          str(idx), f"{int(sc.get_value())}%"])
            app_box, _ = bslider("󰎤", 0, 150, 1, inp["vol"], cb=_mk(inp["index"]))
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

def _dns_dialog(parent: Gtk.Window) -> None:
    """Kleiner Dialog zum DNS ändern - wirkt auf das gerade aktive
    Verbindungsprofil (egal ob WLAN oder LAN)."""
    conn = _active_connection_name()
    dlg = Gtk.Dialog(title="Change DNS", transient_for=parent)
    dlg.set_name("wb-daemon-popup")
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                    "Apply", Gtk.ResponseType.OK)
    box = dlg.get_content_area()

    if not conn:
        lbl = Gtk.Label(label="No active connection found.")
        box.pack_start(lbl, True, True, 12)
        dlg.show_all(); dlg.run(); dlg.destroy()
        return

    info_lbl = Gtk.Label(label=f"Connection: {conn}")
    info_lbl.get_style_context().add_class("caption")
    box.pack_start(info_lbl, False, False, 6)

    e = Gtk.Entry()
    e.set_text(_current_dns(conn))
    e.set_placeholder_text("e.g. 1.1.1.1, 1.0.0.1 (empty = Auto/DHCP)")
    box.pack_start(e, False, False, 6)

    preset_row = hbox(6)
    presets = [
        ("Auto (DHCP)", ""),
        ("Cloudflare", "1.1.1.1, 1.0.0.1"),
        ("Google", "8.8.8.8, 8.8.4.4"),
        ("Quad9", "9.9.9.9, 149.112.112.112"),
    ]
    for label, val in presets:
        pb = btn(label)
        pb.connect("clicked", lambda _b, v=val: e.set_text(v))
        preset_row.pack_start(pb, False, False, 0)
    box.pack_start(preset_row, False, False, 6)

    dlg.show_all()
    resp = dlg.run()
    new_dns = e.get_text() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    if new_dns is None:
        return

    def _worker():
        ok, err = _set_dns(conn, new_dns)
        if not ok:
            GLib.idle_add(lambda: (_flash_dns_error(parent, err), False)[1])
    in_thread(_worker)

def _flash_dns_error(parent: Gtk.Window, msg: str) -> None:
    d = Gtk.MessageDialog(transient_for=parent, modal=True,
                           message_type=Gtk.MessageType.ERROR,
                           buttons=Gtk.ButtonsType.OK, text="DNS change failed")
    d.set_name("wb-daemon-popup")
    d.set_keep_above(True)
    d.format_secondary_text((msg or "Unknown error")[:200])
    d.run(); d.destroy()

def _network_content(win: Gtk.Window) -> Gtk.Box:
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(120)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    # ── TAB 1: Networks ──────────────────────────────────────
    t1 = vbox(4); pad(t1, h=4, v=6)

    scan_b = btn("󰑐  Scan")
    dns_b  = btn("󰙲  DNS", tip="Change DNS servers for the active connection")
    hdr = hbox(6)
    hdr.pack_start(scan_b, False, False, 0)
    hdr.pack_start(dns_b, False, False, 0)
    hdr.set_halign(Gtk.Align.CENTER)
    t1.pack_start(hdr, False, False, 0)

    note_lbl = Gtk.Label(label="")
    note_lbl.get_style_context().add_class("caption")
    note_lbl.set_opacity(0.7)
    t1.pack_start(note_lbl, False, False, 0)

    t1.pack_start(sep(), False, False, 2)

    sw, net_box = scroll_box(240)
    t1.pack_start(sw, True, True, 0)

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
        scan_b.set_label("󰑎  Scanning…"); scan_b.set_sensitive(False)
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
            GLib.idle_add(lambda: (scan_b.set_label("󰑐  Scan"),
                                   scan_b.set_sensitive(True), False)[2])
        in_thread(_scan)

    scan_b.connect("clicked", _do_scan)
    dns_b.connect("clicked", lambda _b: _dns_dialog(win))

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
    st_row.pack_start(ping_row, False, False, 0)
    st_row.pack_start(down_row, False, False, 0)
    st_row.pack_start(up_row, False, False, 0)
    t2.pack_start(st_row, False, False, 0)

    # Kleine "..." Animation statt jedem Text - einziges sichtbares
    # Lebenszeichen dafür, dass gerade ein Lauf im Hintergrund läuft.
    st_loading_lbl = Gtk.Label(label="")
    st_loading_lbl.get_style_context().add_class("caption")
    st_loading_lbl.set_halign(Gtk.Align.CENTER)
    st_loading_lbl.set_no_show_all(True)
    st_loading_lbl.hide()
    t2.pack_start(st_loading_lbl, False, False, 0)

    _st_dot_tid   = [None]
    _st_dot_phase = [0]

    def _st_dot_tick():
        _st_dot_phase[0] = (_st_dot_phase[0] % 3) + 1
        st_loading_lbl.set_label("." * _st_dot_phase[0])
        return True

    def _st_dot_start():
        if _st_dot_tid[0] is not None:
            return
        _st_dot_phase[0] = 0
        st_loading_lbl.show()
        _st_dot_tid[0] = GLib.timeout_add(450, _st_dot_tick)
        _st_dot_tick()

    def _st_dot_stop():
        if _st_dot_tid[0] is not None:
            try: GLib.source_remove(_st_dot_tid[0])
            except Exception: pass
            _st_dot_tid[0] = None
        st_loading_lbl.hide()

    # Fehler/Hinweise (z.B. "speedtest-cli fehlt") landen NUR noch als
    # Tooltip auf der Zeile - kein sichtbarer Text mehr im Tab.
    _ST_INTERVAL_MS = 45_000   # Pause zwischen zwei Läufen - bewusst
                               # träge, das ist ein Dauerbetrieb im
                               # Hintergrund, kein einmaliger Test.
    _st_active   = [False]
    _st_running  = [False]
    _st_wait_tid = [None]

    def _st_apply_result(out, err, ec):
        if ec == 0 and out.strip():
            try:
                data = json.loads(out)
                ping = data.get("ping")
                down = data.get("download")  # bit/s
                up   = data.get("upload")    # bit/s
                ping_val.set_label(f"{ping:.0f} ms" if ping is not None else "–")
                down_val.set_label(f"{down/1_000_000:.1f} Mbit/s" if down else "–")
                up_val.set_label(f"{up/1_000_000:.1f} Mbit/s" if up else "–")
                st_row.set_tooltip_text(None)
            except Exception as e:
                st_row.set_tooltip_text(f"Could not read speed test response: {e}")
        else:
            msg = (err or out).strip()[:160] or "Unknown error"
            st_row.set_tooltip_text(f"Speed test failed: {msg}")

    def _st_tick():
        _st_wait_tid[0] = None
        _st_run_once()
        return False

    def _st_run_once():
        if not _st_active[0] or _st_running[0]:
            return
        if not shutil.which("speedtest-cli"):
            st_row.set_tooltip_text("speedtest-cli not installed (pacman -S speedtest-cli)")
            return
        _st_running[0] = True
        _st_dot_start()

        def _worker():
            out, err, ec = run_ec(["speedtest-cli", "--json", "--secure"], timeout=90)
            def _apply():
                _st_running[0] = False
                _st_dot_stop()
                if not _st_active[0]:
                    return
                _st_apply_result(out, err, ec)
                _st_wait_tid[0] = GLib.timeout_add(_ST_INTERVAL_MS, _st_tick)
            GLib.idle_add(_apply)
        in_thread(_worker)

    def _start_speedtest_loop():
        if _st_active[0]:
            return
        _st_active[0] = True
        _st_run_once()

    def _stop_speedtest_loop():
        _st_active[0] = False
        _st_dot_stop()
        if _st_wait_tid[0] is not None:
            try: GLib.source_remove(_st_wait_tid[0])
            except Exception: pass
            _st_wait_tid[0] = None

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

    pwr_b  = btn("󰂯  On" if powered[0] else "󰂲  Off",
                 active=powered[0])
    scan_b = btn("󰑐  Scan")
    scan_b.set_sensitive(powered[0])

    hdr = hbox(6)
    hdr.set_halign(Gtk.Align.CENTER)
    hdr.pack_start(btitle("󰂯  Bluetooth"), False, False, 0)
    hdr.pack_start(pwr_b,  False, False, 0)
    hdr.pack_start(scan_b, False, False, 0)
    root.pack_start(hdr, False, False, 0)
    root.pack_start(sep(), False, False, 2)

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

        dev_box.pack_start(sep(), False, False, 2)
        dev_box.pack_start(bsec("KNOWN DEVICES"), False, False, 0)
        dev_box.pack_start(sep(), False, False, 2)

        for d in paired:
            conn   = _bt_connected(d["mac"])
            icon   = "󰂱" if conn else "󰂰"
            name_b = bitem(f"{icon}  {d['name'][:26]}")
            con_b  = btn("Disconnect" if conn else "Connect",
                         active=conn)
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
            con_b.connect("clicked", _mk_con(d["mac"], conn))
            rm_b.connect("clicked",  _mk_rm(d["mac"]))
            dev_box.pack_start(hrow(name_b, con_b, rm_b), False, False, 0)

        if found:
            dev_box.pack_start(sep(), False, False, 4)
            dev_box.pack_start(bsec("DISCOVERED DEVICES"), False, False, 0)
            dev_box.pack_start(sep(), False, False, 2)
            for d in found:
                pair_b = btn("Pair")
                def _mk_pair(mac):
                    return lambda _: in_thread(lambda: (
                        _bt(f"pair {mac}"), _bt(f"connect {mac}"),
                        GLib.idle_add(_refresh)))
                pair_b.connect("clicked", _mk_pair(d["mac"]))
                dev_box.pack_start(
                    hrow(bitem(f"󰂰  {d['name'][:26]}"), pair_b),
                    False, False, 0)
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
                pwr_b.set_label("󰂯  On" if powered[0] else "󰂲  Off")
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
        scan_b.set_label("󰑎  Scanning…"); scan_b.set_sensitive(False)
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
            GLib.idle_add(lambda: (scan_b.set_label("󰑐  Scan"),
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
    root = vbox(4); safe_pad(root, 360)

    def _on_wallpaper(_):
        run_bg(["bash", WALLPAPER_SCRIPT])

    wallpaper_b = btn("", cb=_on_wallpaper,
                       tip="Shuffle wallpaper (random_wallpaper.sh)")
    if not os.path.isfile(WALLPAPER_SCRIPT):
        wallpaper_b.set_sensitive(False)
        wallpaper_b.set_tooltip_text(
            f"random_wallpaper.sh not found ({WALLPAPER_SCRIPT})")
    title_row = hrow(btitle("󰃠  Brightness"), wallpaper_b, sp=6)
    title_row.set_halign(Gtk.Align.CENTER)
    root.pack_start(title_row, False, False, 0)
    root.pack_start(sep(), False, False, 2)

    root.pack_start(bsec("SCREEN"), False, False, 0)

    def _on_bright(s):
        in_thread(run, ["brightnessctl", "set", f"{int(s.get_value())}%"])
    bright_box, _ = bslider("󰃟", 5, 100, 1, _bright_pct(), cb=_on_bright)
    root.pack_start(bright_box, False, False, 0)

    kbd_dev = _kbd_backlight_device()
    if kbd_dev:
        root.pack_start(sep(), False, False, 4)
        root.pack_start(bsec("KEYBOARD BACKLIGHT"), False, False, 0)
        def _on_kbd(s):
            in_thread(run, ["brightnessctl", "-d", kbd_dev,
                             "set", f"{int(s.get_value())}%"])
        kbd_box, _ = bslider("⌨", 0, 100, 1,
                              _kbd_bright_pct(kbd_dev), cb=_on_kbd)
        root.pack_start(kbd_box, False, False, 0)

    # ── OpenRGB: ein Regler-Set PRO ERKANNTEM GERÄT ──────────────────
    # Jedes Gerät bekommt nur die Regler, die es laut seinem aktuell
    # aktiven Modus tatsächlich unterstützt - Farbe ist praktisch immer
    # verfügbar, Helligkeit nur wenn ModeFlags.HAS_BRIGHTNESS gesetzt
    # ist. Erkennung + SDK-Serverstart laufen komplett asynchron -
    # openrgb-python macht synchrone Netzwerk-Aufrufe, ein direkter
    # Aufruf im GTK-Main-Thread würde das Fenster einfrieren.
    rgb_section = vbox(4)
    root.pack_start(rgb_section, False, False, 0)

    def _build_rgb_device_row(info: dict) -> Gtk.Box:
        dev_name = info["name"]
        box = vbox(3)
        box.get_style_context().add_class("bubble")
        pad(box, h=8, v=6)
        name_lbl = Gtk.Label(label=f'{info["name"]} ({info["type"].title()})')
        name_lbl.set_halign(Gtk.Align.START)
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
                _debounced(_openrgb_set_brightness, n, int(s.get_value()))
            bri_box, _ = bslider(
                "󰃟", info["brightness_min"], info["brightness_max"], 1,
                info["brightness"] or 0, cb=_on_bri)
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
            rgb_section.pack_start(sep(), False, False, 2)
            rgb_section.pack_start(bsec("RGB DEVICES"), False, False, 0)
            for info in devices:
                row = _build_rgb_device_row(info)
                rgb_section.pack_start(row, False, False, 0)
            rgb_section.show_all()
        GLib.idle_add(_apply)

    if _openrgb_available():
        in_thread(_load_rgb_devices)

    root.pack_start(sep(), False, False, 4)

    nl_tool = _nl_available()
    nl_b = btn("  On" if _nl_active[0] else "  Off",
               active=_nl_active[0])
    if not nl_tool:
        nl_b.set_sensitive(False)
        nl_b.set_tooltip_text(
            "No night light tool found (gammastep/hyprsunset/wlsunset)")

    nl_hdr = hbox(6)
    nl_hdr.set_halign(Gtk.Align.CENTER)
    nl_hdr.pack_start(bsec("NIGHT LIGHT"), False, False, 0)
    nl_hdr.pack_start(nl_b, False, False, 0)
    root.pack_start(nl_hdr, False, False, 0)

    temp_lbl = Gtk.Label(label=f"{_nl_temp[0]} K")
    temp_lbl.get_style_context().add_class("caption")
    temp_lbl.set_opacity(0.65)
    temp_lbl.set_size_request(52, -1)
    temp_lbl.set_halign(Gtk.Align.END)

    _nl_debounce_id = [0]

    def _on_temp(s):
        _nl_temp[0] = int(s.get_value())
        temp_lbl.set_label(f"{_nl_temp[0]} K")
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
        "󱠃", 1000, 6500, 100, _nl_temp[0],
        cb=_on_temp, show_val=False, suffix_lbl=temp_lbl)
    temp_s.set_inverted(True)
    root.pack_start(temp_box, False, False, 0)

    def _on_nl(_):
        if not nl_tool: return
        _nl_active[0] = not _nl_active[0]
        nl_b.set_label("  On" if _nl_active[0] else "  Off")
        ctx = nl_b.get_style_context()
        _nl_generation[0] += 1
        gen = _nl_generation[0]
        if _nl_active[0]:
            ctx.add_class("active"); in_thread(_nl_start, _nl_temp[0], gen)
        else:
            ctx.remove_class("active"); in_thread(_nl_stop)

    nl_b.connect("clicked", _on_nl)
    return root

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
    Projekt auch die anderen Helper wie waybar_autohide, widgets_daemon.py
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
        "cpu_temp": _cpu_temp(),
        "cpu_watts": _cpu_watts(),
        "gpu":      _gpu_stats(),
    }

def _akku_content() -> Gtk.Box:
    root = vbox(4); pad(root, h=4, v=6)

    root.pack_start(btitle("󰁹  Battery"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    # Drei-Spalten-Zeile: Leistungsaufnahme (W) links, Icon+Prozent
    # mittig, Lade-/Entladestatus rechts - per Gtk.Grid mit
    # gleich breiten, expandierenden Spalten, damit die Mitte
    # unabhängig von der Textlänge links/rechts wirklich mittig bleibt.
    bat_box = Gtk.Grid()
    bat_box.set_column_homogeneous(True)
    bat_box.get_style_context().add_class("bubble")
    bat_box.get_style_context().add_class("item")

    power_lbl = Gtk.Label(label="")
    power_lbl.get_style_context().add_class("caption")
    power_lbl.set_halign(Gtk.Align.START)
    power_lbl.set_hexpand(True)
    power_lbl.set_no_show_all(True)

    center_box = hbox(6)
    center_box.set_halign(Gtk.Align.CENTER)
    center_box.set_hexpand(True)

    bat_icon_lbl = Gtk.Label(label="")
    bat_icon_lbl.get_style_context().add_class("icon-lg")
    bat_pct_lbl  = Gtk.Label(label="–")
    bat_pct_lbl.get_style_context().add_class("value-md")
    center_box.pack_start(bat_icon_lbl, False, False, 0)
    center_box.pack_start(bat_pct_lbl,  False, False, 0)

    bat_status_lbl = Gtk.Label(label="")
    bat_status_lbl.get_style_context().add_class("caption")
    bat_status_lbl.set_halign(Gtk.Align.END)
    bat_status_lbl.set_hexpand(True)

    bat_box.attach(power_lbl,      0, 0, 1, 1)
    bat_box.attach(center_box,     1, 0, 1, 1)
    bat_box.attach(bat_status_lbl, 2, 0, 1, 1)
    root.pack_start(bat_box, False, False, 0)

    _power_fetch_in_flight = [False]

    def _refresh_bat():
        info = _bat()
        if info:
            bat_icon_lbl.set_label(_bat_icon(info["cap"], info["status"]))
            bat_pct_lbl.set_label(f'{info["cap"]} %')
            bat_status_lbl.set_label(f'{info["status"]}')
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
            bat_status_lbl.set_label("")
            power_lbl.hide()
        return True

    add_timer(10000, _refresh_bat)
    _refresh_bat()


    root.pack_start(sep(), False, False, 4)

    pp_section = vbox(4)
    root.pack_start(bsec("ENERGY PROFILE"), False, False, 0)
    root.pack_start(pp_section, False, False, 0)
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
    root.pack_start(gm_fx_row, False, False, 0)

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
    return root

def _sysmon_content() -> Gtk.Box:
    """System-Monitor-Tab für Geräte OHNE Akku (Desktop-PCs) - zeigt
    CPU (Auslastung, Temperatur, Watt via SUID-Helper), RAM, Swap,
    Disk, und AMD-GPU-Stats (falls erkannt). Ist aber KEIN exklusiver
    Ersatz für den Akku-Tab - läuft als zweiter, immer vorhandener Tab
    neben Battery, siehe _akku_and_sysmon_content()."""
    root = vbox(4); pad(root, h=4, v=6)
    root.pack_start(btitle("󰍹  System Monitor"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

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

    root.pack_start(bsec("CPU"), False, False, 0)
    cpu_row, cpu_val = _stat_row("󰻠", "Usage")
    root.pack_start(cpu_row, False, False, 0)
    temp_row, temp_val = _stat_row("󰔏", "Temperature")
    root.pack_start(temp_row, False, False, 0)
    watt_row, watt_val = _stat_row("󱐋", "Power")
    root.pack_start(watt_row, False, False, 0)

    root.pack_start(sep(), False, False, 4)
    root.pack_start(bsec("MEMORY"), False, False, 0)
    ram_row, ram_val = _stat_row("󰘚", "RAM")
    root.pack_start(ram_row, False, False, 0)
    swap_row, swap_val = _stat_row("󰋊", "Swap")
    root.pack_start(swap_row, False, False, 0)

    root.pack_start(sep(), False, False, 4)
    root.pack_start(bsec("STORAGE"), False, False, 0)
    disk_row, disk_val = _stat_row("󰆼", "Disk (/)")
    root.pack_start(disk_row, False, False, 0)

    gpu_section = vbox(4)
    root.pack_start(gpu_section, False, False, 0)
    gpu_widgets = {}  # wird bei erster erfolgreicher GPU-Erkennung befüllt

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

        gpu = snap["gpu"]
        if gpu and not gpu_widgets:
            gpu_section.pack_start(sep(), False, False, 2)
            gpu_section.pack_start(bsec("GPU"), False, False, 0)
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
    return root

def _akku_and_sysmon_content(win: Gtk.Window) -> Gtk.Box:
    """Zwei-Tab-Fenster: Battery (nur falls _battery_present(), also
    nur auf Laptops) + System Monitor (IMMER, unabhängig vom Akku -
    CPU/RAM/GPU/Disk-Stats sind für jeden interessant, nicht nur für
    Desktop-Nutzer ohne Akku). Folgt demselben Gtk.Stack + Umschalt-
    Button-Muster wie _volume_content() (Media/Devices/Apps-Tabs)."""
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(120)
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)

    has_bat = _battery_present()
    default_tab = "battery" if has_bat else "system"
    if has_bat:
        stack.add_named(_akku_content(), "battery")

    # System-Tab wird LAZY gebaut - erst wenn tatsächlich draufgeklickt
    # wird, nicht sofort beim Öffnen des Fensters. Der System-Monitor
    # pollt alle 2s (CPU/RAM/GPU/Disk) - ohne Lazy-Loading würde dieser
    # Timer die GANZE Zeit mitlaufen, auch wenn nur der Battery-Tab
    # angeschaut wird. Falls kein Akku vorhanden ist, ist "system" der
    # einzige/Default-Tab und wird direkt gebaut (kein Grund zu warten,
    # er wird ja sofort angezeigt).
    system_built = [False]
    if not has_bat:
        stack.add_named(_sysmon_content(), "system")
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
            stack.add_named(_sysmon_content(), "system")
        finally:
            _current_win[0] = None
        stack.show_all()

    tab_row = hbox(6)
    tab_row.set_halign(Gtk.Align.CENTER)
    tab_btns: dict = {}
    def _switch(name):
        if name == "system":
            _ensure_system_tab()
        _switch_stack(stack, win, name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")

    tabs = ([("battery", "󰁹  Battery")] if has_bat else []) + \
           [("system", "󰍹  System")]
    for name, label in tabs:
        b = btn(label, active=(name == default_tab))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)
    stack.set_visible_child_name(default_tab)

    outer = vbox(4); safe_pad(outer, 340)
    if len(tabs) > 1:
        outer.pack_start(tab_row, True, False, 2)
        outer.pack_start(tab_sep(), False, False, 0)
    outer.pack_start(stack, False, False, 0)
    return outer

def build_akku(win: Gtk.Window):
    win.set_default_size(340, 1)
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

def _khal_change_storage_path(calendar_name: str, new_dir: Path) -> tuple[bool, str]:
    """Ändert den vdir-Speicherort eines Kalenders.

    Verschiebt die bestehenden .ics-Dateien NUR dann in den neuen
    Ordner, wenn dieser komplett leer ist (keine .ics drin). Liegen
    dort bereits .ics-Dateien - z.B. weil es schon ein über Syncthing/
    Nextcloud synchronisierter Ordner von einem anderen Gerät ist -
    wird GAR NICHTS verschoben/kopiert/überschrieben, auch nicht
    teilweise: dann bleiben die alten Dateien exakt da, wo sie sind,
    und nur der Config-Pfad wird auf den neuen Ordner umgebogen (siehe
    Chat - jedes Anfassen des Zielordners in dem Fall wäre ein
    unnötiges Risiko, z.B. Konflikte mit dem Sync-Tool)."""
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
    moved = False
    if (not target_already_has_data and old_dir and old_dir.is_dir()
            and old_dir.resolve() != new_dir.resolve()):
        for f in old_dir.glob("*.ics"):
            try:
                shutil.move(str(f), str(new_dir / f.name))
            except Exception as e:
                return False, f"Failed to move {f.name}: {e}"
        moved = True

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
        return True, (f"Target folder already had events - nothing moved, "
                       f"just switched over. Old data is still at {old_dir}.")
    if moved:
        return True, "Storage location changed, events moved."
    return True, ""

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
    stack.set_transition_duration(120)
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

        def _worker():
            ok, msg = _khal_change_storage_path(cal_name, new_dir)
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
    # Gemeinsame Statuszeile für alle Einstellungen dieser Seite - jede
    # Änderung wird sofort übernommen (siehe apply_change()), es gibt
    # keine Apply/Discard-Leiste mehr. Zeigt kurz "Applying…" bzw. das
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

    # ── Appearance: EIN Light/Dark-Umschalter für Kvantum + GTK ──────
    page.pack_start(bsec("APPEARANCE"), False, False, 0)
    dark_row = hbox(8)
    dark_lbl = Gtk.Label(label="Theme:")
    dark_lbl.get_style_context().add_class("caption")
    dark_toggle = btn("", active=_is_dark_mode())
    def _refresh_dark_label():
        is_dark = _is_dark_mode()
        dark_toggle.set_label("🌙  Dark" if is_dark else "☀️  Light")
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
        dark_toggle.set_label("🌙  Dark" if new_dark else "☀️  Light")
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
    dark_row.pack_start(dark_lbl, False, False, 0)
    dark_row.pack_start(dark_toggle, False, False, 0)
    page.pack_start(dark_row, False, False, 0)

    page.pack_start(sep(), False, False, 6)

    # ── Systemsounds: globaler An/Aus-Schalter (soundctl.sh) ─────────
    # Steuert dieselbe State-Datei, die soundctl.sh selbst prüft - dieser
    # Switch hier ist also nur EIN möglicher Ort, an dem man umschalten
    # kann, kein eigener Zustand. Genau wie beim Dark-Toggle: sofortiges
    # visuelles Feedback am Button, bevor die Datei tatsächlich geschrieben
    # ist, mit _reset() als Fallback bei Fehlern.
    page.pack_start(bsec("SYSTEM SOUNDS"), False, False, 0)
    sound_row = hbox(8)
    sound_lbl = Gtk.Label(label="Click/UI sounds:")
    sound_lbl.get_style_context().add_class("caption")
    sound_toggle = btn("", active=_sounds_enabled())

    def _refresh_sound_toggle(enabled: bool):
        sound_toggle.set_label("🔊  On" if enabled else "🔇  Off")
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
    page.pack_start(sound_row, False, False, 0)

    page.pack_start(sep(), False, False, 6)

    # ── Cursor: dynamic_cursors Plugin (Tilt/Stretch-Effekte + Shake-to-Find) ──
    page.pack_start(bsec("CURSOR"), False, False, 0)

    cursor_row = hbox(8)
    cursor_lbl = Gtk.Label(label="Cursor effects:")
    cursor_lbl.get_style_context().add_class("caption")
    cursor_toggle = btn("", active=_cursor_plugin_enabled())

    shake_row = hbox(8)
    shake_lbl = Gtk.Label(label="Shake-to-find:")
    shake_lbl.get_style_context().add_class("caption")
    shake_toggle = btn("", active=_cursor_shake_enabled())

    def _refresh_cursor_toggle(enabled: bool):
        cursor_toggle.set_label("🖱️  On" if enabled else "🖱️  Off")
        ctx = cursor_toggle.get_style_context()
        if enabled: ctx.add_class("active")
        else:       ctx.remove_class("active")
        # Shake ergibt nur Sinn, wenn das Plugin selbst überhaupt an ist
        shake_row.set_sensitive(enabled)

    def _refresh_shake_toggle(enabled: bool):
        shake_toggle.set_label("🫨  On" if enabled else "🫨  Off")
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

    cursor_row.pack_start(cursor_lbl, False, False, 0)
    cursor_row.pack_start(cursor_toggle, False, False, 0)
    page.pack_start(cursor_row, False, False, 0)

    shake_row.pack_start(shake_lbl, False, False, 0)
    shake_row.pack_start(shake_toggle, False, False, 0)
    page.pack_start(shake_row, False, False, 0)

    page.pack_start(sep(), False, False, 6)

    # ── Language: Systemsprache (locale) ─────────────────────────────
    page.pack_start(bsec("LANGUAGE"), False, False, 0)
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
    page.pack_start(lang_row, False, False, 0)

    page.pack_start(sep(), False, False, 6)

    # ── Keyboard Layout ───────────────────────────────────────────────
    page.pack_start(bsec("KEYBOARD LAYOUT"), False, False, 0)
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
    page.pack_start(kb_row, False, False, 0)

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

    # Gemeinsamer Debounce-Status für den Waybar/Autohide-Reload - siehe
    # Kommentar bei waybar_restart_id in _build_monitor_row(). Ohne das
    # würde bei kurz hintereinander geänderten Monitor-Einstellungen
    # (jede wird sofort einzeln übernommen) der Reload einmal PRO
    # Änderung feuern, was zu einem Race zwischen zwei fast
    # gleichzeitigen "killall -SIGUSR2 waybar" +
    # "systemctl restart wb-autohide.service" führen kann.
    waybar_restart_id = [0]

    for mon in monitors:
        page.pack_start(bsec(mon.get("name", "?").upper()), False, False, 0)
        row = _build_monitor_row(mon, monitors, lua_path, win, waybar_restart_id)
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

def _scale_bounds(height: int) -> tuple[float, float]:
    """Gibt (min_scale, max_scale) für eine gegebene physische
    Monitorhöhe zurück - innerhalb dieses Bereichs bleibt die daraus
    resultierende logische Höhe zwischen _MIN_LOGICAL_H und
    _MAX_LOGICAL_H, siehe Kommentar oben."""
    if height <= 0:
        return 0.1, 3.0
    lo = height / _MAX_LOGICAL_H
    hi = height / _MIN_LOGICAL_H
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
                        waybar_restart_id: list) -> Gtk.Box:
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

    hz_combo = Gtk.ComboBoxText()
    hz_combo.get_style_context().add_class("bubble")
    hz_combo.get_style_context().add_class("dropdown")
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

    scale_state = {"value": cur_scale}
    scale_val_btn = btn(f"{cur_scale:g}")
    scale_val_btn.set_sensitive(False)

    def _on_scale_btn_clicked(_w):
        val = _prompt_text("Scale", "e.g. 1.0",
                            initial=f"{scale_state['value']:g}")
        if val is None:
            return
        try:
            parsed = float(val.replace(",", "."))
            if parsed <= 0:
                raise ValueError
        except ValueError:
            _flash_status(f"Invalid scale: '{val}'")
            return
        # Failsafe: gegen die Auflösung prüfen, die gerade ausgewählt
        # ist (nicht mehr die ursprüngliche cur_res) - sonst könnte man
        # sich z.B. bei 360p mit einem viel zu kleinen Scale-Wert
        # aussperren, siehe Kommentar bei _scale_bounds().
        target_res, _target_hz = _resolve_res_hz()
        target_h_str = (target_res or cur_res).split("x")[1]
        lo, hi = _scale_bounds(int(target_h_str))
        if not (lo <= parsed <= hi):
            _flash_status(
                f"Scale {parsed:g} unsafe for this resolution "
                f"(allowed {lo:g}–{hi:g}) — could lock you out of Settings. Not applied.",
                ms=5000)
            return
        scale_state["value"] = parsed
        scale_val_btn.set_label(f"{parsed:g}")
        _apply_now()

    scale_val_btn.connect("clicked", _on_scale_btn_clicked)

    def _on_scale_auto_toggle(_w):
        scale_val_btn.set_sensitive(not scale_auto_check.get_active())
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
            monitor_arg = f"{name},{mode},{pos_x}x{pos_y},{scale}"
            if hdr_on:
                monitor_arg += ",bitdepth,10,cm,hdr"
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
            hz_combo.set_active(hz_combo.get_model().iter_n_children(None) - 1)
            custom_state["hz"] = orig[1]
        scale_auto_check.set_active(orig[3])
        if not orig[3]:
            scale_state["value"] = orig[2]
            scale_val_btn.set_label(f"{orig[2]:g}")
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

    combos_row = hrow(res_combo, hz_combo, sp=8)
    custom_row = hrow(res_val_lbl, hz_val_lbl, sp=8)
    scale_row  = hrow(Gtk.Label(label="Scale:"), scale_val_btn,
                       scale_auto_check, sp=8)
    hdr_row    = hrow(hdr_check, sp=8)
    pos_row    = hrow(Gtk.Label(label="Position:"), pos_combo, sp=8)
    wrap = vbox(6)
    wrap.pack_start(combos_row, False, False, 0)
    wrap.pack_start(custom_row, False, False, 0)
    wrap.pack_start(scale_row, False, False, 0)
    wrap.pack_start(hdr_row, False, False, 0)
    wrap.pack_start(pos_row, False, False, 0)
    wrap.pack_start(status_lbl, False, False, 0)
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

SETTINGS_BUILDERS = {
    "display":    _build_settings_display,
    "brightness": _build_settings_brightness,
    "audio":      _build_settings_audio,
    "network":    _build_settings_network,
    "bluetooth":  _build_settings_bluetooth,
    "battery":    _build_settings_battery,
    "calendar":   _build_settings_calendar,
    "appearance": _build_settings_appearance,
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
              "  widgets_daemon.py --set-weather-coords <lat> <lon> \"<Name>\"",
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

        python3 widgets_daemon.py --diag
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
        "widgets_daemon.py [--set-weather \"<Location>\" | "
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
