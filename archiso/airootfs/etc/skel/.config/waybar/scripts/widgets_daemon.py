#!/usr/bin/env python3
"""
widgets_daemon.py — TrafkTux Waybar Widget System  v6 (Daemon)
Aufruf: python3 widgets_daemon.py          (läuft dauerhaft, ein Prozess)
Ansteuerung über den schlanken Client: widgets_client.py <widget>
Widgets: volume | network | bluetooth | brightness | akku | clock

v6-Umbau (Daemon statt Kurzlebig-Prozess):
  - Der alte Aufbau startete bei JEDEM Klick einen frischen
    python3-Prozess neu: import gi + Gtk-Init + Wayland-Verbindung
    kosten dabei allein schon 150-300ms, BEVOR ueberhaupt eine Zeile
    Anwendungscode laeuft. Das ist kein Optimierungsproblem im Code,
    sondern reiner Interpreter-/Library-Ladevorgang - der liess sich
    innerhalb eines "ein Klick = ein neuer Prozess"-Modells nicht
    wegbekommen.
  - Jetzt: EIN dauerhaft laufender Prozess (Autostart per systemd
    --user Unit), der GTK bereits initialisiert im Speicher haelt.
    Ein Klick auf Waybar ruft nur noch widgets_client.py auf - ein
    winziges Skript OHNE gi/Gtk-Import, das dem Daemon ueber einen
    Unix-Socket sagt "zeig/versteck Widget X" und sofort wieder
    beendet. Das reduziert die Antwortzeit von 150-300ms auf den
    reinen Python-Interpreter-Start (~10-20ms) + Socket-Rundreise
    (<1ms) -> das 35-50ms-Ziel ist damit erreichbar.
  - Der alte PID-Lockfile-Mechanismus (Prozess suchen/killen) entfaellt
    komplett: "welches Widget ist offen" ist jetzt einfach ein Dict im
    Speicher des Daemons, kein Blick auf /proc noetig.
  - Alle Widget-Builder (build_volume, build_network, ...) bleiben
    UNVERAENDERT - sie sind reine Funktionen "Fenster rein, UI rein"
    und funktionieren im Daemon genauso wie vorher im Einzelprozess.

v5-Fixes gegenueber dem v4-Redesign (weiterhin gueltig):
  - CSS-Absturz behoben: "text-transform" ist keine gueltige GTK-CSS-
    Eigenschaft und liess load_css() bei JEDEM Start mit einer
    unabgefangenen GLib.GError crashen, bevor ueberhaupt ein Fenster
    erschien. Grossschreibung der Sektions-Label laeuft jetzt in Python.
  - Verwaiste Klassen h1/h2/sm (aus dem alten CSS) wieder eingefuehrt
    als icon-lg/value-md/caption, sonst hatten Akku-Icon, Medientitel,
    Wetter-Zeilen etc. keine Schriftgroesse mehr bekommen.
  - cleanup() ist jetzt idempotent (verhindert Gtk-CRITICAL bei
    doppeltem Signal / Fokusverlust + SIGTERM gleichzeitig).
  - Tote Code-Zeile in build_akku entfernt.
"""

import gi, sys, os, re, signal, subprocess, json, threading, time, calendar
from datetime import datetime
from pathlib import Path

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

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
#  Pfade & Farben
# ════════════════════════════════════════════════════════════
HOME   = os.path.expanduser("~")
B_NORM = f"file://{HOME}/.config/rofi/assets/bubble-normal.png"
B_SEL  = f"file://{HOME}/.config/rofi/assets/bubble-selected.png"
# Gleiches Skript, das hyprland.lua beim Autostart aufruft
# (hl.exec_cmd("bash ~/.config/hypr/random_wallpaper.sh")) - hier per
# Knopf erneut ausloesbar, um das Wallpaper manuell zu wechseln.
WALLPAPER_SCRIPT = f"{HOME}/.config/hypr/random_wallpaper.sh"

# Wetter-Standort ist konfigurierbar (siehe _fetch_weather weiter unten):
# ~/.config/wb-daemon/weather.json  {"lat": .., "lon": .., "name": ".."}
# Setzen per:
#   python3 widgets_daemon.py --set-weather "Grazbachgasse, Graz"
#   python3 widgets_daemon.py --set-weather-coords 47.0707 15.4395 "Graz Zentrum"
# Fallback, falls noch nichts konfiguriert wurde (alter Ort aus v5/v6).
WEATHER_CONF     = Path(HOME) / ".config" / "wb-daemon" / "weather.json"
_DEFAULT_WEATHER_LOC = {"lat": 47.8121, "lon": 16.2506, "name": "Wiener Neustadt"}
GOLD   = "#fff495"
GOLD_H = "#c8b800"
GOLD_DIM = "rgba(255,244,149,0.45)"

# ════════════════════════════════════════════════════════════
#  CSS — Klares 3-Ebenen-System: title / section / item
# ════════════════════════════════════════════════════════════
def _css() -> bytes:
    return f"""
window {{
    background-color: transparent;
    border: none;
}}

/* ══ Basis-Blase ══ */
.bubble {{
    background-image: url("{B_NORM}");
    background-size: 100% 100%;
    background-repeat: no-repeat;
    background-color: transparent;
    color: {GOLD};
    border: none;
    box-shadow: none;
    font-family: "JetBrainsMono Nerd Font", "Noto Sans";
    font-size: 13px;
    -gtk-outline-radius: 8px;
}}

/* ── Ebene 1: Titel (widget-Überschrift) ──
   Groß, viel Padding, prominent */
.bubble.title {{
    padding: 8px 22px;
    margin: 4px 0px;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 1px;
}}

/* ── Ebene 2: Sektion-Label ──
   Mittel, gleiche Farbe wie der Rest, Unterscheidung über
   Größe/Sperrung statt Abdunkelung (sonst wirkt es "verwaschen") */
.bubble.section {{
    padding: 3px 16px;
    margin: 6px 0px 1px 0px;
    font-size: 11px;
    font-weight: bold;
    color: {GOLD};
    letter-spacing: 2px;
}}

/* ── Ebene 3: Item (Standardinhalt) ── */
.bubble.item {{
    padding: 5px 16px;
    margin: 1px 0px;
    font-size: 13px;
}}

/* ── Text-Größen — unabhängig vom Blasentyp, für einzelne Labels
   innerhalb einer Blase (z.B. Akku-Icon groß, Status-Zeile klein) ── */
.icon-lg  {{ font-size: 22px; }}
.icon-xl  {{ font-size: 34px; }}
.value-md {{ font-size: 15px; font-weight: bold; }}
.temp-xl  {{ font-size: 26px; font-weight: bold; }}
.caption  {{ font-size: 11px; }}

/* ── Slider-Blase (volle Breite, kompakter) ── */
.bubble.slider {{
    padding: 6px 14px;
    margin: 1px 0px;
}}

/* ── Interaktive Elemente ── */
button.bubble {{
    padding: 5px 16px;
    margin: 1px 0px;
}}
button.bubble:hover, button.bubble:active, button.bubble:checked {{
    background-image: url("{B_SEL}");
    color: {GOLD_H};
}}
button.bubble:focus {{
    box-shadow: none;
    outline: none;
}}
button.bubble.active {{
    background-image: url("{B_SEL}");
    color: {GOLD_H};
    font-weight: bold;
}}
button.bubble.title {{
    padding: 8px 22px;
    font-size: 17px;
    font-weight: bold;
}}

/* ── Slider ── */
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

/* ── Trennlinie ── */
separator {{
    background-color: rgba(255,244,149,0.2);
    min-height: 1px;
    margin: 5px 8px;
}}

/* ── Scrollbar ── */
scrollbar {{ background-color: transparent; min-width: 3px; }}
scrollbar slider {{
    background-color: rgba(255,244,149,0.3);
    border-radius: 2px;
    min-width: 3px;
    min-height: 20px;
}}
""".encode()

# ════════════════════════════════════════════════════════════
#  Hilfsfunktionen
# ════════════════════════════════════════════════════════════
def run(cmd: list, timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout).stdout.strip()
    except Exception:
        return ""

def run_ec(cmd: list, timeout: int = 5) -> tuple[str, str, int]:
    """Wie run(), liefert zusaetzlich stderr + Returncode zurueck.
    Gebraucht ueberall dort, wo bisher Fehler von nmcli/bluetoothctl
    stillschweigend verschluckt wurden (z.B. falsches WLAN-Passwort
    oder ein abgelehnter Rescan) und der Nutzer nie erfuhr, WARUM
    nichts passiert ist."""
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

def jrun(cmd: list) -> object:
    raw = run(cmd)
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None

def in_thread(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()

def load_css():
    p = Gtk.CssProvider()
    p.load_from_data(_css())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), p,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

# ════════════════════════════════════════════════════════════
#  Fenster-Verwaltung (Daemon-Variante)
#  Der alte PID-Lockfile-Mechanismus (Prozess suchen/killen über
#  /proc) entfällt komplett: "welches Widget ist offen" ist jetzt
#  einfach ein Dict im Speicher dieses einen Prozesses. Öffnen/
#  Schließen ist reines GTK-Objekt-Handling - keine Subprozesse,
#  keine Dateisystem-Locks, kein Warten auf Prozessende.
#
#  Jedes Widget wird beim Öffnen frisch gebaut (wie vorher) und beim
#  Schließen komplett zerstört (inkl. seiner Timer). Das kostet
#  innerhalb des schon laufenden Daemons nur ~1-5ms (reine Python-/
#  GTK-Objekterzeugung, kein Interpreter-Start, kein gi-Import) -
#  im Gegensatz zu den 150-300ms, die das Neu-Starten des ganzen
#  Prozesses vorher gekostet hat. Genau das ist der Hebel, der das
#  35-50ms-Ziel erreichbar macht.
# ════════════════════════════════════════════════════════════
WIDGET = None
_open: dict[str, Gtk.Window] = {}          # Widget-Name -> offenes Fenster
_timers_by_win: dict[Gtk.Window, list] = {}  # Fenster -> seine Timer-IDs
_current_win: list = [None]                # Fenster, das gerade gebaut wird

def _destroy_widget(name: str) -> None:
    win = _open.pop(name, None)
    if win is not None:
        try: win.destroy()
        except: pass

def _close_all(except_name: str = None) -> None:
    for name in list(_open):
        if name != except_name:
            _destroy_widget(name)

def toggle_widget(name: str) -> str:
    """Wird pro eingehender Client-Anfrage aufgerufen. Läuft im
    GLib-Main-Loop-Thread, keine Nebenläufigkeit zu beachten."""
    global WIDGET
    if name not in BUILDERS:
        return f"error: unbekanntes Widget '{name}'"

    # 1) Dasselbe Widget ist offen -> reiner Toggle: schließen.
    if name in _open:
        _destroy_widget(name)
        return "closed"

    # 2) Alle ANDEREN Widgets schließen -> immer nur eines sichtbar.
    _close_all()

    WIDGET = name
    win = make_win(name)
    _current_win[0] = win
    BUILDERS[name](win)
    _current_win[0] = None
    win.show_all()
    _open[name] = win
    return "opened"

def add_timer(ms: int, fn) -> int:
    tid = GLib.timeout_add(ms, fn)
    win = _current_win[0]
    if win is not None and win in _timers_by_win:
        _timers_by_win[win].append(tid)
    return tid

# ════════════════════════════════════════════════════════════
#  Fenster
#  FIX ggü. v5: cleanup() war dort ein einziges globales, einmal
#  scharfgeschaltetes Idempotenz-Flag (_cleaned[0]) - passend für
#  einen Prozess, der genau EIN Fenster in seinem Leben aufbaut.
#  Im Daemon baut derselbe Prozess aber immer wieder neue Fenster
#  auf. Deshalb bekommt jedes Fenster jetzt seine EIGENE Cleanup-
#  Closure mit eigenem Idempotenz-Flag und eigener Timer-Liste,
#  statt sich ein globales Flag zu teilen.
# ════════════════════════════════════════════════════════════
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
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT,  True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, 110)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT,  14)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    else:
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
    if HAS_CAIRO:
        def _draw_bg(w, ctx):
            ctx.set_source_rgba(0, 0, 0, 0); ctx.paint(); return False
        win.connect("draw", _draw_bg)

    cleaned = [False]
    my_timers: list[int] = []
    _timers_by_win[win] = my_timers

    def _cleanup(*_):
        if cleaned[0]:
            return False
        cleaned[0] = True
        for tid in my_timers:
            try: GLib.source_remove(tid)
            except: pass
        my_timers.clear()
        _timers_by_win.pop(win, None)
        _open.pop(name, None)
        try: win.destroy()
        except: pass
        return False

    win.connect("destroy", _cleanup)
    win.connect("focus-out-event", lambda w, e: _cleanup())
    return win

# ════════════════════════════════════════════════════════════
#  UI-Helfer
# ════════════════════════════════════════════════════════════
def vbox(sp: int = 4) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sp)

def hbox(sp: int = 6) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=sp)

def sep() -> Gtk.Separator:
    s = Gtk.Separator()
    return s

def pad(w: Gtk.Widget, h: int = 10, v: int = 10) -> Gtk.Widget:
    w.set_margin_start(h); w.set_margin_end(h)
    w.set_margin_top(v);   w.set_margin_bottom(v)
    return w

# ── Blase: Titel-Ebene (Überschrift jedes Widgets) ──
def btitle(text: str) -> Gtk.Box:
    box = hbox(0)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("title")
    box.set_halign(Gtk.Align.CENTER)
    l = Gtk.Label(label=text)
    box.pack_start(l, False, False, 0)
    return box

# ── Blase: Sektion-Label (Kategorie-Überschrift, gedimmt) ──
def bsec(text: str) -> Gtk.Box:
    box = hbox(0)
    box.get_style_context().add_class("bubble")
    box.get_style_context().add_class("section")
    box.set_halign(Gtk.Align.CENTER)
    # GTK-CSS kennt kein text-transform → Großschreibung hier in Python
    l = Gtk.Label(label=text.upper())
    box.pack_start(l, False, False, 0)
    return box

# ── Blase: normales Item (Text-Info, zentriert) ──
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

# ── Blase: Item mit interner Label-Referenz für Updates ──
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

# ── Button (interaktiv, zentriert) ──
def btn(text: str, cb=None, tip: str = "",
        active: bool = False) -> Gtk.Button:
    b = Gtk.Button(label=text)
    b.get_style_context().add_class("bubble")
    b.set_halign(Gtk.Align.CENTER)
    # Kein Tastaturfokus -> GTK zeichnet nie den animierten Fokusring
    # ("marching ants"). Bei Software-Rendering in diesem Layer-Shell-
    # Overlay war genau diese Animation die spürbar ruckelige (~5fps)
    # Auswahl-Umrandung beim Hovern - betraf JEDEN Button, nicht nur
    # Settings, weil sie alle über diese eine Funktion laufen.
    b.set_can_focus(False)
    if active:
        b.get_style_context().add_class("active")
    if tip: b.set_tooltip_text(tip)
    if cb:  b.connect("clicked", cb)
    return b

# ── Slider-Blase (volle Breite wegen Scale-Widget) ──
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

# ── Zeile aus mehreren Widgets (horizontal, zentriert) ──
def hrow(*widgets, sp: int = 6) -> Gtk.Box:
    row = hbox(sp)
    row.set_halign(Gtk.Align.CENTER)
    for w in widgets:
        row.pack_start(w, False, False, 0)
    return row

# ── ScrolledWindow mit internem vbox ──
def scroll_box(min_h: int = 220) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_min_content_height(min_h)
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

def _volume_content() -> Gtk.Box:
    """Wie bei Netzwerk/Akku: komplettes UI als eigene Funktion, damit
    das Leisten-Icon und die spätere Settings-Unterseite ("Audio")
    dasselbe Widget verwenden."""
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(120)

    # ── TAB 1: Media ────────────────────────────────────────
    t1 = vbox(4); pad(t1, h=10, v=8)

    title_box, title_lbl   = bitem_ref("  Kein Media")
    # Mach Titel größer
    for c in title_box.get_children():
        if isinstance(c, Gtk.Label):
            c.get_style_context().add_class("value-md")
    artist_box, artist_lbl = bitem_ref("", dim=True)

    t1.pack_start(title_box,  False, False, 0)
    t1.pack_start(artist_box, False, False, 0)

    # Media-Controls: 3 Buttons in einer Zeile
    prev_b = btn("󰒮", tip="Zurück")
    play_b = btn("󰐊", tip="Play/Pause")
    next_b = btn("󰒭", tip="Weiter")
    prev_b.connect("clicked", lambda _: run_bg(["playerctl", "previous"]))
    play_b.connect("clicked", lambda _: run_bg(["playerctl", "play-pause"]))
    next_b.connect("clicked", lambda _: run_bg(["playerctl", "next"]))
    t1.pack_start(hrow(prev_b, play_b, next_b), False, False, 4)

    t1.pack_start(sep(), False, False, 2)

    # Systemlautstärke
    t1.pack_start(bsec("LAUTSTAERKE"), False, False, 0)

    muted = [_is_muted()]
    mute_icon_lbl = Gtk.Label(label="󰖁" if muted[0] else "󰕾")
    mute_icon_lbl.set_opacity(0.7)

    def _on_vol(s):
        in_thread(run, ["wpctl", "set-volume",
                        "@DEFAULT_AUDIO_SINK@", f"{int(s.get_value())}%"])

    vol_box, vol_s = bslider("󰕾", 0, 150, 1, _vol_pct(), cb=_on_vol)
    # Mute-Button als erstes Kind der Slider-Box ersetzen
    # (Icon schon drin via bslider) — wir machen den Icon anklickbar:
    # bslider gibt icon_l als erstes Kind; machen wir es zu einem Button
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
                title_lbl.set_label(info.get("title","") or "  Kein Media")
                artist_lbl.set_label(info.get("artist","") if info else "")
                play_b.set_label("󰏦" if info.get("status") == "Playing" else "󰐊")
            GLib.idle_add(_apply)
        in_thread(_fetch)
        return True

    add_timer(1500, _update_media)
    _update_media()

    # ── TAB 2: Geräte ────────────────────────────────────────
    t2_sw, t2 = scroll_box(240)

    def _refresh_devices():
        for c in t2.get_children(): t2.remove(c)
        t2.pack_start(bsec("AUSGABE"), False, False, 0)
        for s in _get_sinks():
            t2.pack_start(btn(f"  {s['desc']}",
                lambda _, n=s["name"]: (
                    in_thread(run, ["pactl","set-default-sink", n]),
                    GLib.timeout_add(300, _refresh_devices))), False, False, 0)
        t2.pack_start(sep(), False, False, 4)
        t2.pack_start(bsec("EINGABE"), False, False, 0)
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
            t3.pack_start(bitem("Keine aktiven Audio-Apps", dim=True),
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
        t3.pack_start(btn("󰑐  Aktualisieren",
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
        stack.set_visible_child_name(name)
        for n, b in tab_btns.items():
            ctx = b.get_style_context()
            if n == name: ctx.add_class("active")
            else:         ctx.remove_class("active")
    for name, label in (("media", "󰝚  Media"),
                         ("geraete", "󰓃  Geraete"),
                         ("apps", "󰎄  Apps")):
        b = btn(label, active=(name == "media"))
        b.connect("clicked", lambda _b, n=name: _switch(n))
        tab_btns[name] = b
        tab_row.pack_start(b, False, False, 0)

    outer = vbox(4); pad(outer, h=8, v=6)
    # FIX: expand=False bedeutet die Box bekommt nur ihre natuerliche
    # Groesse zugewiesen -> halign=CENTER hat dann keinen Spielraum zum
    # Zentrieren und die Tabs kleben links. Mit expand=True bekommt die
    # Row die volle Fensterbreite und CENTER wirkt tatsaechlich.
    outer.pack_start(tab_row, True, False, 2)
    outer.pack_start(stack,   False, False, 0)
    return outer

def build_volume(win: Gtk.Window):
    win.set_default_size(400, 1)
    win.add(_volume_content())

# ════════════════════════════════════════════════════════════
#  NETWORK
# ════════════════════════════════════════════════════════════
def _wifi_dev_name() -> str | None:
    """Ermittelt den tatsaechlichen Namen des WLAN-Interfaces, statt ihn
    fest als "wlan0" anzunehmen. Auf den meisten aktuellen Systemen
    (systemd "predictable network interface names") heisst die Karte
    z.B. "wlp3s0" o.ae. - "wlan0" existiert dort schlicht nicht. Das war
    der Grund, warum "Trennen" bisher nie funktioniert hat: nmcli bekam
    ein Device genannt, das nicht existiert, lief ins Leere und tat
    nichts (auch ohne Fehlermeldung, weil niemand den Returncode
    geprueft hat)."""
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
    dlg = Gtk.Dialog(title=f"Passwort: {ssid}", transient_for=parent)
    dlg.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                    "Verbinden", Gtk.ResponseType.OK)
    e = Gtk.Entry()
    e.set_visibility(False)
    e.set_placeholder_text("WLAN-Passwort")
    e.connect("activate", lambda _: dlg.response(Gtk.ResponseType.OK))
    dlg.get_content_area().pack_start(e, True, True, 12)
    dlg.show_all()
    resp = dlg.run()
    pw = e.get_text() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    return pw

def _network_content(win: Gtk.Window) -> Gtk.Box:
    """Wie _akku_content(): baut das komplette Netzwerk-UI und gibt die
    fertige Box zurück, ohne sie selbst ans Fenster zu haengen. `win`
    wird weiterhin gebraucht (Passwort-/Fehler-Dialoge sind modal zu
    diesem Fenster), aber build_network() und die Netzwerk-Unterseite
    im Settings-Hub rufen jetzt dieselbe Funktion auf."""
    root = vbox(4); pad(root, h=10, v=8)

    scan_b = btn("󰑐  Scan")
    hdr = hbox(6)
    hdr.pack_start(btitle("󰤨  Netzwerk"), False, False, 0)
    hdr.pack_start(scan_b, False, False, 0)
    hdr.set_halign(Gtk.Align.CENTER)
    root.pack_start(hdr, False, False, 0)

    # Kleine, standardmaessig leere Hinweiszeile fuer transiente Meldungen
    # (z.B. "Scan-Kuehlzeit aktiv") - direkt unter dem Header statt als
    # Dialog, damit sie nicht stoert.
    note_lbl = Gtk.Label(label="")
    note_lbl.get_style_context().add_class("caption")
    note_lbl.set_opacity(0.7)
    root.pack_start(note_lbl, False, False, 0)

    root.pack_start(sep(), False, False, 2)

    sw, net_box = scroll_box(280)
    root.pack_start(sw, True, True, 0)

    def _flash_note(text: str, ms: int = 3500):
        note_lbl.set_label(text)
        GLib.timeout_add(ms, lambda: (note_lbl.set_label(""), False)[1])

    def _show_connect_error(msg: str):
        d = Gtk.MessageDialog(transient_for=win, modal=True,
                               message_type=Gtk.MessageType.ERROR,
                               buttons=Gtk.ButtonsType.OK,
                               text="Verbindung fehlgeschlagen")
        d.format_secondary_text((msg or "Unbekannter Fehler")[:200])
        d.run(); d.destroy()

    def _populate(nets):
        for c in net_box.get_children(): net_box.remove(c)
        if not nets:
            net_box.pack_start(bitem("Keine Netzwerke", dim=True), False, False, 0)
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
        net_box.pack_start(bitem("  Lade…", dim=True), False, False, 0)
        net_box.show_all()
        in_thread(lambda: GLib.idle_add(_populate, _wifi_list()))

    def _do_scan(_):
        scan_b.set_label("󰑎  Scanning…"); scan_b.set_sensitive(False)
        def _scan():
            dev = _wifi_dev_name()
            cmd = ["nmcli", "dev", "wifi", "rescan"]
            if dev:
                cmd += ["ifname", dev]
            out, err, rc = run_ec(cmd, timeout=10)
            # NetworkManager lehnt einen Rescan ab, wenn der letzte
            # Scan (auch ein automatischer Hintergrund-Scan von NM
            # selbst) noch keine ~30s her ist ("Error: Scanning not
            # allowed immediately following previous scan."). Genau
            # das war vermutlich der Hauptgrund fuer "es kommt meist
            # nix Neues": der Rescan wurde still abgelehnt und danach
            # nur die schon bekannte, alte Liste erneut angezeigt -
            # ohne jede Rueckmeldung. Jetzt wird das erkannt und dem
            # Nutzer kurz angezeigt, statt es zu verschweigen.
            if rc != 0 and "not allowed" in (err or "").lower():
                GLib.idle_add(_flash_note,
                               "Scan-Kühlzeit aktiv (WLAN scannt nur alle ~30s) — zeige aktuelle Liste")
            # Ein echter Scan-Zyklus braucht selbst ein paar Sekunden,
            # bis der Treiber neue Kanäle abgesucht hat - 1s Wartezeit
            # war zu kurz, um wirklich neue SSIDs zu erfassen.
            time.sleep(3)
            GLib.idle_add(_populate, _wifi_list())
            GLib.idle_add(lambda: (scan_b.set_label("󰑐  Scan"),
                                   scan_b.set_sensitive(True)))
        in_thread(_scan)

    scan_b.connect("clicked", _do_scan)
    _do_load()
    return root

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
    root = vbox(4); pad(root, h=10, v=8)
    powered = [_bt_powered()]

    pwr_b  = btn("󰂯  An" if powered[0] else "󰂲  Aus",
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
            dev_box.pack_start(bitem("Bluetooth deaktiviert", dim=True),
                               False, False, 0)
            dev_box.show_all(); return

        paired_macs = {d["mac"] for d in _bt_devices("Paired")}
        all_devs    = _bt_devices()
        paired      = [d for d in all_devs if d["mac"] in paired_macs]
        found       = [d for d in all_devs if d["mac"] not in paired_macs]

        dev_box.pack_start(sep(), False, False, 2)
        dev_box.pack_start(bsec("BEKANNTE GERAETE"), False, False, 0)
        dev_box.pack_start(sep(), False, False, 2)

        for d in paired:
            conn   = _bt_connected(d["mac"])
            icon   = "󰂱" if conn else "󰂰"
            name_b = bitem(f"{icon}  {d['name'][:26]}")
            con_b  = btn("Trennen" if conn else "Verbinden",
                         active=conn)
            rm_b   = btn("󰆴", tip="Entfernen")

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
            dev_box.pack_start(bsec("GEFUNDENE GERAETE"), False, False, 0)
            dev_box.pack_start(sep(), False, False, 2)
            for d in found:
                pair_b = btn("Pairen")
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
            GLib.idle_add(lambda: (
                pwr_b.set_label("󰂯  An" if powered[0] else "󰂲  Aus"),
                (pwr_b.get_style_context().add_class("active")
                 if powered[0]
                 else pwr_b.get_style_context().remove_class("active")),
                scan_b.set_sensitive(powered[0]),
                _refresh()))
        in_thread(_do)

    def _on_scan(_):
        scan_b.set_label("󰑎  Scanning…"); scan_b.set_sensitive(False)
        def _do():
            proc = subprocess.Popen(
                ["bluetoothctl", "scan", "on"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Klassisches Bluetooth (BR/EDR) braucht pro Inquiry-Zyklus
            # rund 10.24s, bis ein Geraet in Reichweite garantiert
            # geantwortet hat; die alten 6s haben oft mitten im ersten
            # Zyklus abgebrochen - genau daher "kommt meist nix Neues".
            # 14s deckt einen vollen Zyklus zuverlaessig ab und lassen
            # auch BLE-Geraeten mit selteneren Advertising-Intervallen
            # eine faire Chance. Zwischendurch aktualisieren wir die
            # Liste schon zweimal live, statt nur ganz am Ende einmal -
            # so sieht man neue Geraete auftauchen, waehrend noch
            # gescannt wird, statt erst nach dem kompletten Timeout.
            for _ in range(2):
                time.sleep(7)
                GLib.idle_add(_refresh)
            proc.terminate()
            subprocess.Popen(["bluetoothctl", "scan", "off"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            GLib.idle_add(_refresh)
            GLib.idle_add(lambda: (scan_b.set_label("󰑐  Scan"),
                                   scan_b.set_sensitive(True)))
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
# Sperre + Generation-Zaehler gegen die Racebedingung, die das
# "Nachtlicht reagiert nach mehrfachem/schnellem Ziehen nicht mehr
# richtig"-Problem verursacht hat: frueher startete JEDER Slider-Tick
# sofort einen eigenen Hintergrund-Thread, der _nl_stop() + neu starten
# macht. Beim schnellen Ziehen liefen mehrere solcher Threads
# gleichzeitig, unsynchronisiert - welcher zuletzt fertig wurde (nicht
# zwingend der mit dem neuesten Temperaturwert!), "gewann". Jetzt:
# _nl_lock serialisiert den eigentlichen Start/Stop, _nl_generation
# erlaubt einem wartenden/laufenden Aufruf zu erkennen, dass er
# inzwischen veraltet ist, und sich sauber abzubrechen statt einen
# veralteten Wert zu setzen.
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
    """Nur mit _nl_lock gehalten aufrufen."""
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
        # Waehrend wir ggf. auf die Sperre gewartet haben, kann schon
        # ein neuerer Wunsch (neuere Sliderposition) eingetroffen sein.
        # Dann lohnt es nicht mehr, DIESEN veralteten Wert noch zu
        # starten - einfach abbrechen und dem neueren Aufruf den
        # Vortritt lassen.
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
                    # Inzwischen veraltet - sauber wieder abraeumen statt
                    # einen falschen Wert stehen zu lassen.
                    _nl_stop_locked()
                    return
                if _nl_proc.poll() is None: return
                _nl_proc = None
            except FileNotFoundError:
                continue

def _nl_stop():
    with _nl_lock:
        _nl_stop_locked()

# ── Tastatur-Beleuchtung: RGB/Backlight-Erkennung ──
# Erkennt ein Keyboard-Backlight über brightnessctl (LED-Klasse) und
# optional OpenRGB für echte Mehrfarben-Steuerung. Beides ist Hardware-
# abhängig -> wird nur angezeigt, wenn tatsächlich etwas gefunden wird.
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

def _hue_to_hex(hue: float) -> str:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360, 1.0, 1.0)
    return f"{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

def _brightness_content() -> Gtk.Box:
    root = vbox(4); pad(root, h=10, v=8)

    def _on_wallpaper(_):
        # nicht blockierend - genau der gleiche Aufruf wie beim
        # Hyprland-Autostart, nur manuell erneut ausgeloest.
        run_bg(["bash", WALLPAPER_SCRIPT])

    wallpaper_b = btn("", cb=_on_wallpaper,
                       tip="Wallpaper neu würfeln (random_wallpaper.sh)")
    if not os.path.isfile(WALLPAPER_SCRIPT):
        wallpaper_b.set_sensitive(False)
        wallpaper_b.set_tooltip_text(
            f"random_wallpaper.sh nicht gefunden ({WALLPAPER_SCRIPT})")
    title_row = hrow(btitle("󰃠  Helligkeit"), wallpaper_b, sp=6)
    title_row.set_halign(Gtk.Align.CENTER)
    root.pack_start(title_row, False, False, 0)
    root.pack_start(sep(), False, False, 2)

    # Helligkeit-Slider
    root.pack_start(bsec("BILDSCHIRM"), False, False, 0)

    def _on_bright(s):
        in_thread(run, ["brightnessctl", "set", f"{int(s.get_value())}%"])
    bright_box, _ = bslider("󰃟", 5, 100, 1, _bright_pct(), cb=_on_bright)
    root.pack_start(bright_box, False, False, 0)

    # Tastatur-/RGB-Beleuchtung (nur wenn Hardware erkannt wird)
    kbd_dev     = _kbd_backlight_device()
    has_openrgb = _openrgb_available()
    if kbd_dev or has_openrgb:
        root.pack_start(sep(), False, False, 4)
        root.pack_start(bsec("TASTATUR-BELEUCHTUNG"), False, False, 0)
        if kbd_dev:
            def _on_kbd(s):
                in_thread(run, ["brightnessctl", "-d", kbd_dev,
                                 "set", f"{int(s.get_value())}%"])
            kbd_box, _ = bslider("⌨", 0, 100, 1,
                                  _kbd_bright_pct(kbd_dev), cb=_on_kbd)
            root.pack_start(kbd_box, False, False, 0)
        if has_openrgb:
            def _on_hue(s):
                in_thread(run, ["openrgb", "--mode", "static",
                                 "--color", _hue_to_hex(s.get_value())])
            hue_box, _ = bslider("󰸌", 0, 359, 1, 0,
                                  cb=_on_hue, show_val=False)
            root.pack_start(hue_box, False, False, 0)

    root.pack_start(sep(), False, False, 4)

    # Nachtlicht
    nl_tool = _nl_available()
    nl_b = btn("  An" if _nl_active[0] else "  Aus",
               active=_nl_active[0])
    if not nl_tool:
        nl_b.set_sensitive(False)
        nl_b.set_tooltip_text(
            "Kein Nachtlicht-Tool (gammastep/hyprsunset/wlsunset)")

    nl_hdr = hbox(6)
    nl_hdr.set_halign(Gtk.Align.CENTER)
    nl_hdr.pack_start(bsec("NACHTLICHT"), False, False, 0)
    nl_hdr.pack_start(nl_b, False, False, 0)
    root.pack_start(nl_hdr, False, False, 0)

    # Temperatur-Label lebt im Slider
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
        # 150ms warten, ob noch weiter gezogen wird, statt bei jedem
        # einzelnen Drag-Tick sofort einen Thread loszuschicken.
        _nl_debounce_id[0] = GLib.timeout_add(150, _fire)

    temp_box, temp_s = bslider(
        "󱠃", 1000, 6500, 100, _nl_temp[0],
        cb=_on_temp, show_val=False, suffix_lbl=temp_lbl)
    temp_s.set_inverted(True)
    root.pack_start(temp_box, False, False, 0)

    def _on_nl(_):
        if not nl_tool: return
        _nl_active[0] = not _nl_active[0]
        nl_b.set_label("  An" if _nl_active[0] else "  Aus")
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
    win.add(_brightness_content())

# ════════════════════════════════════════════════════════════
#  AKKU
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

def _bat_icon(cap: int, status: str) -> str:
    if "Charging" in status: return "󰂄"
    if cap >= 95: return "󰁹"
    if cap >= 80: return "󰂂"
    if cap >= 60: return "󰂀"
    if cap >= 40: return "󰁾"
    if cap >= 20: return "󰁼"
    return "󰁺"

_ppd_icons  = {"performance": "󱐋", "balanced": "󱐌", "power-saver": "󰌪"}
_ppd_labels = {"performance": "Performance",
               "balanced":    "Balanced",
               "power-saver": "Sparmodus"}

def _ppd_available() -> list:
    out = run(["powerprofilesctl", "list"])
    return [p for p in ["power-saver","balanced","performance"] if p in out]

def _akku_content() -> Gtk.Box:
    """Baut das komplette Akku-UI und gibt die fertige Box zurück - OHNE
    sie an ein Fenster zu haengen. So kann dieselbe Funktion sowohl vom
    eigenstaendigen Akku-Widget (build_akku) als auch von der
    Akku-Unterseite im Settings-Hub verwendet werden: exakt dasselbe
    Widget an zwei Stellen, statt zweier gepflegter Kopien."""
    root = vbox(4); pad(root, h=10, v=8)

    # Titel
    root.pack_start(btitle("󰁹  Akku"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

    # Icon + Prozent + Status in einer Blase
    bat_box = hbox(10)
    bat_box.get_style_context().add_class("bubble")
    bat_box.get_style_context().add_class("item")
    bat_box.set_halign(Gtk.Align.CENTER)

    bat_icon_lbl   = Gtk.Label(label="")
    bat_icon_lbl.get_style_context().add_class("icon-lg")
    bat_pct_lbl    = Gtk.Label(label="–")
    bat_pct_lbl.get_style_context().add_class("value-md")
    bat_status_lbl = Gtk.Label(label="")
    bat_status_lbl.get_style_context().add_class("caption")
    bat_status_lbl.set_opacity(0.6)

    bat_box.pack_start(bat_icon_lbl,   False, False, 0)
    bat_box.pack_start(bat_pct_lbl,    False, False, 0)
    bat_box.pack_start(bat_status_lbl, False, False, 0)
    root.pack_start(bat_box, False, False, 0)

    def _refresh_bat():
        info = _bat()
        if info:
            bat_icon_lbl.set_label(_bat_icon(info["cap"], info["status"]))
            bat_pct_lbl.set_label(f'  {info["cap"]} %')
            bat_status_lbl.set_label(f'   {info["status"]}')
        else:
            bat_icon_lbl.set_label("󰂑")
            bat_pct_lbl.set_label("  Kein Akku")
            bat_status_lbl.set_label("")
        return True

    add_timer(10000, _refresh_bat)
    _refresh_bat()

    root.pack_start(sep(), False, False, 4)

    # ── Energieprofil ────────────────────────────────────────
    pp_section = vbox(4)
    root.pack_start(bsec("ENERGIEPROFIL"), False, False, 0)
    root.pack_start(pp_section, False, False, 0)
    pp_section.pack_start(bitem("Lade…", dim=True), False, False, 0)
    pp_section.show_all()

    def _build_pp_row(profiles: list, current: str):
        for c in pp_section.get_children():
            pp_section.remove(c)
        pp_btns: dict = {}
        if profiles:
            pp_row = hbox(6)
            pp_row.set_halign(Gtk.Align.CENTER)
            for pr in profiles:
                b = btn(f"{_ppd_icons.get(pr,'󱐌')}  {_ppd_labels.get(pr, pr)}",
                        active=(pr == current))
                def _mk(profile):
                    def _cb(_):
                        in_thread(run, ["powerprofilesctl", "set", profile])
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
                bitem("power-profiles-daemon nicht gefunden", dim=True),
                False, False, 0)
        pp_section.show_all()

    def _load_pp():
        profiles = _ppd_available()
        current  = run(["powerprofilesctl", "get"]).strip() if profiles else ""
        GLib.idle_add(_build_pp_row, profiles, current)

    in_thread(_load_pp)
    return root

def build_akku(win: Gtk.Window):
    win.set_default_size(340, 1)
    win.add(_akku_content())

# ════════════════════════════════════════════════════════════
#  CLOCK + KALENDER
# ════════════════════════════════════════════════════════════
# ── Wetter-Icons: wttr.in liefert einen numerischen "weatherCode"
#    (World Weather Online Codes) — hier auf Emoji gemappt.
_WCODE_ICON = {
    "113": "☀️",                                            # klar/sonnig
    "116": "⛅",                                             # leicht bewölkt
    "119": "☁️", "122": "☁️",                                # bewölkt/bedeckt
    "143": "🌫️", "248": "🌫️", "260": "🌫️",                  # Nebel
    "176": "🌦️", "263": "🌦️", "266": "🌦️", "293": "🌦️",
    "296": "🌦️", "353": "🌦️",                                # leichter Regen
    "281": "🌧️", "284": "🌧️", "299": "🌧️", "302": "🌧️",
    "305": "🌧️", "308": "🌧️", "311": "🌧️", "314": "🌧️",
    "356": "🌧️", "359": "🌧️",                                # Regen
    "179": "🌨️", "182": "🌨️", "185": "🌨️", "227": "🌨️",
    "317": "🌨️", "320": "🌨️", "362": "🌨️", "365": "🌨️",
    "368": "🌨️",                                             # Schneeregen
    "230": "❄️", "323": "🌨️", "326": "❄️", "329": "❄️",
    "332": "❄️", "335": "❄️", "338": "❄️", "371": "❄️",       # Schnee
    "350": "🧊", "374": "🧊", "377": "🧊",                    # Eiskörner
    "200": "⛈️", "386": "⛈️", "389": "⛈️", "392": "⛈️", "395": "⛈️",  # Gewitter
}
def _wicon(code) -> str:
    return _WCODE_ICON.get(str(code), "🌡️")

# ── Open-Meteo WMO-Wettercodes → Icon/Beschreibung ─────────────
# Open-Meteo nutzt (anders als wttr.in/WWO) den WMO-Code-Standard.
_WMO_ICON = {
    0: "☀️",
    1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌦️",
    56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    66: "🌧️", 67: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "❄️", 77: "🌨️",
    80: "🌦️", 81: "🌧️", 82: "🌧️",
    85: "🌨️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}
_WMO_DESC_DE = {
    0: "Klarer Himmel", 1: "Überwiegend klar", 2: "Teilweise bewölkt",
    3: "Bedeckt", 45: "Nebel", 48: "Reifnebel",
    51: "Leichter Nieselregen", 53: "Nieselregen", 55: "Starker Nieselregen",
    56: "Gefrierender Nieselregen", 57: "Starker gefr. Nieselregen",
    61: "Leichter Regen", 63: "Regen", 65: "Starker Regen",
    66: "Gefrierender Regen", 67: "Starker gefrierender Regen",
    71: "Leichter Schneefall", 73: "Schneefall", 75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer", 81: "Regenschauer", 82: "Starke Regenschauer",
    85: "Leichte Schneeschauer", 86: "Starke Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Schweres Gewitter",
}
def _wicon_wmo(code) -> str:
    try: return _WMO_ICON.get(int(code), "🌡️")
    except (TypeError, ValueError): return "🌡️"

def _load_weather_location() -> dict:
    """Liest den konfigurierten Wetter-Standort. Ohne Konfiguration
    greift der alte Default (Wiener Neustadt) - siehe --set-weather /
    --set-weather-coords weiter unten, um das selbst zu setzen."""
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
    """Open-Meteo-Geocoding: Ortsname -> Liste moeglicher Treffer mit
    exakten Koordinaten. Getrennt von der eigentlichen Wetterabfrage,
    wird nur beim --set-weather-Aufruf gebraucht."""
    import urllib.request, urllib.parse, json as _json
    url = ("https://geocoding-api.open-meteo.com/v1/search?" +
           urllib.parse.urlencode({"name": query, "count": 5, "language": "de"}))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wb-daemon/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = _json.loads(resp.read().decode())
        return data.get("results") or []
    except Exception:
        return []

def _fetch_weather() -> dict:
    """Holt Wetter ueber die Open-Meteo-Forecast-API statt wttr.in.

    Warum das genauer ist:
      - wttr.in loest den uebergebenen Ortsnamen selbst per Geocoding
        auf und liefert dann Daten aus einem relativ groben globalen
        Wettermodell (~11-25km Gitterweite) fuer DIESEN einen Punkt.
      - Open-Meteo bekommt hier stattdessen feste lat/lon (siehe
        _load_weather_location) und waehlt mit models=best_match
        automatisch das hoechstaufloesende verfuegbare *regionale*
        Modell fuer genau diese Koordinaten - in Mitteleuropa i.d.R.
        ICON-D2 vom DWD mit ~2km Gitterweite statt ~11-25km. Das ist
        der eigentliche Hebel gegen "sau inakkurat": nicht ein anderer
        Anbieter an sich, sondern spuerbar mehr Aufloesung an genau
        dem Punkt, den man selbst gewaehlt hat (siehe --set-weather /
        --set-weather-coords), statt am Zentrum einer ganzen Stadt.
      - Faellt Open-Meteo aus, greift als Fallback die alte
        wttr.in-Abfrage (jetzt ebenfalls mit lat/lon statt Ortsname).
    """
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
                       "precipitation,weather_code",
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
        r["icon"] = _wicon_wmo(code)
        r["desc"] = _WMO_DESC_DE.get(int(code), "–") if code is not None else "–"
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
        # Fallback: alte wttr.in-Abfrage, aber mit lat/lon statt
        # Ortsname (funktioniert ohne wttr.in-seitiges Geocoding).
        try:
            import urllib.request, json as _json
            req = urllib.request.Request(
                f"https://wttr.in/{loc['lat']},{loc['lon']}?format=j1&lang=de",
                headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = _json.loads(resp.read().decode())
            cur = data["current_condition"][0]
            r["icon"] = _wicon(cur.get("weatherCode", ""))
            desc = cur.get("lang_de") or cur.get("weatherDesc") or []
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

MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni",
             "Juli","August","September","Oktober","November","Dezember"]
DAYS_DE   = ["So","Mo","Di","Mi","Do","Fr","Sa"]

def _clock_content() -> Gtk.Box:
    root = vbox(4); pad(root, h=10, v=8)

    # ── 1. Wetter: große Heute-Karte + 2 Tage nur mit Icon ───
    # Heute-Karte: Icon+Beschreibung | große Temperatur | Feuchte+Regen
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
    desc_lbl = Gtk.Label(label="Lade Wetter…")
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
    hum_lbl.set_tooltip_text("Luftfeuchtigkeit")
    rain_lbl = Gtk.Label(label="☔ –")
    rain_lbl.get_style_context().add_class("caption")
    rain_lbl.set_halign(Gtk.Align.END)
    rain_lbl.set_tooltip_text("Niederschlag (mm)")
    stats_box.pack_start(hum_lbl,  False, False, 0)
    stats_box.pack_start(rain_lbl, False, False, 0)
    today_card.pack_start(stats_box, False, False, 0)

    root.pack_start(today_card, False, False, 0)

    # Morgen / Übermorgen — nur Wettersymbol, sonst nichts
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
    root.pack_start(fc_row, False, False, 0)

    root.pack_start(sep(), False, False, 2)

    # ── 2. Datum + Uhrzeit ───────────────────────────────────
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
    root.pack_start(dt_row, False, False, 0)

    root.pack_start(sep(), False, False, 2)

    # ── 3. Kalender ──────────────────────────────────────────
    now = datetime.now()
    cur = [now.year, now.month]

    # Navigation
    prev_b      = btn("󰄦")
    next_b      = btn("󰄧")
    mth_box, mth_lbl = bitem_ref("")
    nav_row = hrow(prev_b, mth_box, next_b, sp=4)
    root.pack_start(nav_row, False, False, 0)

    # Wochentage-Header: je in eigener Blase, fixe Breite
    wd_row = hbox(2)
    wd_row.set_halign(Gtk.Align.CENTER)
    for wd in DAYS_DE:
        b = hbox(0)
        b.get_style_context().add_class("bubble")
        b.get_style_context().add_class("section")
        b.set_size_request(44, -1)
        l = Gtk.Label(label=wd)
        l.set_halign(Gtk.Align.CENTER)
        l.set_size_request(44, -1)
        b.pack_start(l, False, False, 0)
        wd_row.pack_start(b, False, False, 0)
    root.pack_start(wd_row, False, False, 0)

    # Kalender-Grid
    cal_grid = vbox(2)
    cal_grid.set_halign(Gtk.Align.CENTER)
    root.pack_start(cal_grid, False, False, 0)

    def _build_grid(year, month):
        for c in cal_grid.get_children(): cal_grid.remove(c)
        today = datetime.now()
        for week in calendar.monthcalendar(year, month):
            week_row = hbox(2)
            week_row.set_halign(Gtk.Align.CENTER)
            for day in week:
                b = hbox(0)
                b.get_style_context().add_class("bubble")
                b.get_style_context().add_class("item")
                b.set_size_request(44, -1)
                is_today = (day == today.day and month == today.month
                            and year == today.year)
                if day == 0:
                    l = Gtk.Label(label="")
                    l.set_opacity(0)
                else:
                    l = Gtk.Label()
                    if is_today:
                        l.set_markup(f"<b>{day}</b>")
                        b.get_style_context().add_class("active")
                        # active nutzt B_SEL → heute hervorgehoben
                    else:
                        l.set_label(str(day))
                l.set_size_request(44, -1)
                l.set_halign(Gtk.Align.CENTER)
                l.get_style_context().add_class("caption")
                b.pack_start(l, False, False, 0)
                week_row.pack_start(b, False, False, 0)
            cal_grid.pack_start(week_row, False, False, 0)
        cal_grid.show_all()

    def _update_mth():
        mth_lbl.set_label(f"{MONTHS_DE[cur[1]-1]}  {cur[0]}")

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

    # ── Updates ──────────────────────────────────────────────
    def _update_time():
        n = datetime.now()
        time_lbl.set_label(n.strftime("%H:%M"))
        date_lbl.set_label(n.strftime("  %A, %d. %B %Y  "))
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
            loc_tip = (f'Standort: {w["location"]}\n'
                       f'Ändern: widgets_daemon.py --set-weather "<Ort>"')
            today_card.set_tooltip_text(loc_tip)
        GLib.idle_add(_apply)

    in_thread(_load_weather)
    add_timer(600_000, lambda: in_thread(_load_weather) or True)
    return root

def build_clock(win: Gtk.Window):
    win.set_default_size(460, 1)
    win.add(_clock_content())

# ════════════════════════════════════════════════════════════
#  SETTINGS — Staging/Apply-System
# ════════════════════════════════════════════════════════════
# Kernidee: KEINE Unterseite schreibt jemals sofort in eine Config-
# Datei. Jede Änderung registriert sich unter einem eindeutigen Key
# im PENDING-Dict (spätere Änderung am selben Key überschreibt die
# vorherige, statt sich zu stapeln). Erst der globale "Übernehmen"-
# Button im Settings-Fenster ruft nacheinander alle apply()-
# Funktionen auf. "Verwerfen" ruft stattdessen reset() auf jeder
# offenen Unterseite auf, damit die UI wieder den Ist-Zustand zeigt.
#
# Bekannte Grenze v1: schließt man das Settings-Fenster (Fokusverlust)
# und öffnet es neu, BEVOR man übernommen/verworfen hat, bleiben die
# PENDING-Einträge technisch aktiv (ihre apply()-Closures halten die
# alten, jetzt unsichtbaren Widgets am Leben und funktionieren beim
# Übernehmen weiterhin) - die NEU aufgebaute Unterseite zeigt aber
# wieder den Live-Systemzustand statt der noch ausstehenden Auswahl.
# Für v1 bewusst in Kauf genommen; sauberer Fix wäre, PENDING-Werte
# beim Neuaufbau einer Seite als Vorbelegung zu lesen.
BACKUP_DIR = Path(HOME) / ".config" / "wb-daemon" / "backups"

class PendingChange:
    __slots__ = ("key", "desc", "apply", "reset")
    def __init__(self, key: str, desc: str, apply_fn, reset_fn=None):
        self.key   = key
        self.desc  = desc
        self.apply = apply_fn    # callable() -> None; darf Exception werfen
        self.reset = reset_fn    # callable() -> None; stellt UI-Widgets zurück

PENDING: dict[str, PendingChange] = {}
# Wird von build_settings() gesetzt, damit stage_change()/unstage_change()
# aus jeder Unterseite heraus die Apply-Leiste live aktualisieren können.
_apply_bar_refresh = [lambda: None]

def stage_change(key: str, desc: str, apply_fn, reset_fn=None) -> None:
    PENDING[key] = PendingChange(key, desc, apply_fn, reset_fn)
    _apply_bar_refresh[0]()

def unstage_change(key: str) -> None:
    PENDING.pop(key, None)
    _apply_bar_refresh[0]()

def backup_file(path: Path) -> None:
    """Legt vor dem ersten Schreiben eine Zeitstempel-Kopie an. Best-
    effort - ein fehlgeschlagenes Backup blockiert das Schreiben nicht,
    aber wir versuchen es immer zuerst."""
    if not path.exists():
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (BACKUP_DIR / f"{path.name}.{stamp}.bak").write_bytes(path.read_bytes())
    except Exception:
        pass

def apply_all() -> list[str]:
    """Wendet alle PENDING-Changes der Reihe nach an. Erfolgreiche
    Changes werden aus PENDING entfernt, fehlgeschlagene bleiben stehen
    (damit man es nach dem Beheben nochmal versuchen kann). Gibt eine
    Liste von Fehlermeldungen zurück (leer = alles ok).
    AUFRUF NUR AUS EINEM HINTERGRUND-THREAD (siehe apply_all_async) -
    ch.apply() kann hyprctl-Aufrufe oder Datei-I/O enthalten, die
    spürbar dauern; synchron im GTK-Hauptthread ausgeführt, blockiert
    das GENAU DEN Mainloop, der auch das SIGUSR1-Autohide-Signal
    dieses Daemons behandelt - Waybar/Autohide reagieren dann so lange
    gar nicht mehr. Das war vermutlich der Kern des gemeldeten
    "Waybar bleibt nach Übernehmen hängen"-Problems."""
    errors = []
    for key in list(PENDING.keys()):
        ch = PENDING[key]
        try:
            ch.apply()
            del PENDING[key]
        except Exception as e:
            errors.append(f"{ch.desc}: {e}")
    GLib.idle_add(_apply_bar_refresh[0])
    return errors

def apply_all_async(on_done) -> None:
    """Fuehrt apply_all() in einem Hintergrund-Thread aus und ruft
    on_done(errors) per GLib.idle_add im GTK-Hauptthread auf, sobald
    fertig. Immer diese Variante aus der UI heraus aufrufen, nie
    apply_all() direkt."""
    def _worker():
        errors = apply_all()
        GLib.idle_add(on_done, errors)
    in_thread(_worker)

def discard_all() -> None:
    for ch in PENDING.values():
        if ch.reset:
            try: ch.reset()
            except Exception: pass
    PENDING.clear()
    _apply_bar_refresh[0]()

def _settings_category_row(icon: str, label: str, desc: str, cb) -> Gtk.Button:
    b = Gtk.Button()
    b.get_style_context().add_class("bubble")
    b.get_style_context().add_class("item")
    b.set_can_focus(False)
    # Standard-Buttons haben halign=FILL - in einer vertikalen Box
    # heisst das "so breit wie die Box", nicht "so breit wie der
    # Inhalt". CENTER lässt die Blase auf ihre tatsächliche Inhaltsgröße
    # schrumpfen und mittig stehen, statt die volle Fensterbreite
    # einzunehmen.
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
        bitem(f"{label}: noch nicht implementiert — kommt in einer "
              f"der nächsten Ausbaustufen.", dim=True),
        False, False, 0)

def _build_settings_network(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    # Exakt dasselbe Widget wie das eigenständige Netzwerk-Icon in der
    # Leiste - keine zweite Implementierung. Der eigene Titel
    # ("Netzwerk") kommt dadurch doppelt (einmal vom Settings-Header,
    # einmal vom Widget selbst) - bewusst so belassen statt den
    # gemeinsamen Baustein dafür zu verbiegen.
    page.pack_start(_network_content(win), True, True, 0)

def _build_settings_battery(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_akku_content(), True, True, 0)

# ── Display: erste komplett funktionierende Unterseite, dient auch
#    als Referenzimplementierung für alle weiteren Kategorien ──
def _hypr_lua_path() -> Path:
    return Path(HOME) / ".config" / "hypr" / "hyprland.lua"

def _hypr_monitors_live() -> list:
    return jrun(["hyprctl", "monitors", "-j"]) or []

def _parse_modes(modes: list) -> dict:
    """['1920x1080@60.00Hz', '1920x1080@144.00Hz', ...]
    -> {'1920x1080': ['60.00', '144.00'], ...}"""
    out: dict = {}
    for m in modes:
        try:
            res, hz = m.split("@")
            out.setdefault(res, []).append(hz.rstrip("Hz"))
        except ValueError:
            continue
    return out

def _build_settings_display(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    monitors = _hypr_monitors_live()
    if not monitors:
        page.pack_start(
            bitem("Keine Monitore über hyprctl gefunden (läuft Hyprland?)",
                  dim=True), False, False, 0)
        return

    lua_path = _hypr_lua_path()
    if not lua_path.is_file():
        page.pack_start(
            bitem(f"hyprland.lua nicht gefunden ({lua_path}) — Auflösung "
                  f"wird nur live per hyprctl gesetzt, nicht dauerhaft "
                  f"gespeichert.", dim=True), False, False, 0)

    for mon in monitors:
        page.pack_start(bsec(mon.get("name", "?").upper()), False, False, 0)
        row = _build_monitor_row(mon, lua_path)
        page.pack_start(row, False, False, 0)
        page.pack_start(sep(), False, False, 4)

def _build_monitor_row(mon: dict, lua_path: Path) -> Gtk.Box:
    """Eigene Funktion PRO Monitor-Aufruf (nicht Schleifenkörper!) - so
    bekommt jeder Monitor seine eigenen, isolierten lokalen Variablen.
    Würde man das alles direkt im for-Loop von _build_settings_display
    verschachteln, würden sich _fill_hz/modes/res_combo/hz_combo über
    alle verschachtelten Funktionen hinweg dieselbe (jeweils letzte)
    Schleifeniteration teilen - klassischer Late-Binding-Closure-Bug,
    der bei genau einem Monitor unsichtbar bleibt, bei zwei oder mehr
    aber dazu führt, dass Monitor A's Dropdown Monitor B's Werte liest."""
    name    = mon.get("name", "?")
    cur_res = f'{mon.get("width")}x{mon.get("height")}'
    cur_hz  = f'{mon.get("refreshRate", 0):.2f}'
    modes   = _parse_modes(mon.get("availableModes", []))
    res_list = sorted(modes.keys(), key=lambda r: -int(r.split("x")[0]))

    res_combo = Gtk.ComboBoxText()
    res_combo.get_style_context().add_class("bubble")
    res_combo.get_style_context().add_class("item")
    res_combo.set_can_focus(False)
    for r in res_list:
        res_combo.append_text(r)

    hz_combo = Gtk.ComboBoxText()
    hz_combo.get_style_context().add_class("bubble")
    hz_combo.get_style_context().add_class("item")
    hz_combo.set_can_focus(False)

    def _fill_hz(res: str, preselect: str = None):
        hz_combo.remove_all()
        hzs = sorted(set(modes.get(res, [])), key=lambda h: -float(h))
        for h in hzs:
            hz_combo.append_text(f"{h} Hz")
        if preselect in hzs:
            hz_combo.set_active(hzs.index(preselect))
        elif hzs:
            hz_combo.set_active(0)

    if cur_res in res_list:
        res_combo.set_active(res_list.index(cur_res))
    _fill_hz(cur_res if cur_res in res_list
             else (res_list[0] if res_list else ""), preselect=cur_hz)

    orig_res, orig_hz = cur_res, cur_hz  # für reset() beim Verwerfen

    def _apply():
        res = res_combo.get_active_text()
        hzt = hz_combo.get_active_text()
        if not res or not hzt:
            return
        mode = f'{res}@{hzt.replace(" Hz", "")}'
        # Position/Skalierung des Monitors beibehalten statt "auto,1" -
        # letzteres hat Position UND Skalierung jedes Mal zurückgesetzt,
        # was bei einem non-trivialen Layout (mehrere Monitore, eigene
        # Skalierung) den ganzen Monitor-Layout-Reload durcheinander
        # gebracht hat.
        pos_x = mon.get("x", 0)
        pos_y = mon.get("y", 0)
        scale = mon.get("scale", 1)
        # 1) sofort live setzen
        # WICHTIG: run() verschluckt Exitcode + stderr komplett - lehnt
        # Hyprland das Kommando ab (z.B. Modus/Skalierung inkompatibel),
        # dachten wir bisher trotzdem "erfolgreich", obwohl live NICHTS
        # passiert ist. Das erklärt vermutlich auch, warum ein erneuter
        # Wechsel zur selben (in Wahrheit nie verlassenen) Auflösung wie
        # "keine Änderung" aussah. Jetzt: run_ec() + Fehler tatsächlich
        # werfen, damit apply_all() ihn im Status-Text anzeigt.
        out, err, rc = run_ec(["hyprctl", "keyword", "monitor",
                                f"{name},{mode},{pos_x}x{pos_y},{scale}"])
        if rc != 0 or "err" in (out or "").lower() or err:
            raise RuntimeError(
                f"hyprctl lehnte den Monitor-Befehl ab: {(err or out or 'unbekannter Fehler')[:120]}")
        # 2) dauerhaft in hyprland.lua sichern — nur die "mode"-Zeile
        #    IM BLOCK DIESES OUTPUTS ersetzen, position/scale bleiben
        #    unangetastet.
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
                txt = txt[:m.start()] + new_block + txt[m.end():]
                lua_path.write_text(txt)

    def _reset():
        if orig_res in res_list:
            res_combo.set_active(res_list.index(orig_res))
        _fill_hz(orig_res, preselect=orig_hz)

    def _stage_or_unstage():
        res = res_combo.get_active_text()
        hz = (hz_combo.get_active_text() or "").replace(" Hz", "")
        if res == orig_res and hz == orig_hz:
            unstage_change(f"display.{name}")
        else:
            stage_change(f"display.{name}", f"{name}: {res}@{hz}Hz",
                         _apply, _reset)

    # WICHTIG: res_combo und hz_combo brauchen GETRENNTE Handler.
    # Vorherige Version rief bei JEDER Änderung (auch der von hz_combo
    # selbst ausgelösten) _fill_hz() auf, was hz_combo neu befüllt,
    # dessen "changed"-Signal auslöst, den selben Handler erneut
    # aufruft, der wieder _fill_hz() aufruft ... Endlosrekursion, die
    # das ganze Widget einfrieren ließ. Jetzt: nur res_combo baut
    # hz_combo neu auf; hz_combo selbst wertet nur noch aus.
    def _on_res_change(_w):
        _fill_hz(res_combo.get_active_text())
        _stage_or_unstage()

    def _on_hz_change(_w):
        _stage_or_unstage()

    res_combo.connect("changed", _on_res_change)
    hz_combo.connect("changed", _on_hz_change)
    return hrow(res_combo, hz_combo, sp=8)

SETTINGS_CATEGORIES = [
    ("display",    "󰍹", "Display",       "Auflösung, Framerate"),
    ("brightness", "󰃟", "Helligkeit",    "Bildschirm, Tastatur-RGB, Nachtlicht"),
    ("audio",      "󰕾", "Audio",         "Lautstärke, Geräte, Apps"),
    ("network",    "󰤨", "Netzwerk",      "LAN, WLAN, Mesh Connect"),
    ("bluetooth",  "󰂯", "Bluetooth",     "Geräte koppeln & verbinden"),
    ("battery",    "󰁹", "Akku",          "Erweiterte Energieoptionen"),
    ("calendar",   "󰃭", "Kalender",      "Wetter, Uhrzeit, Termine"),
    ("appearance", "󰉼", "Aussehen",      "Farbschema, Kvantum, nwg-look"),
    ("language",   "󰗊", "Sprache",       "Systemsprache"),
    ("apps",       "󱁤", "Apps & Editor", "Launcher-Editor, Konfig-Dateien"),
]

def _build_settings_brightness(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_brightness_content(), True, True, 0)

def _build_settings_audio(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_volume_content(), True, True, 0)

def _build_settings_bluetooth(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_bluetooth_content(), True, True, 0)

def _build_settings_calendar(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_clock_content(), True, True, 0)

SETTINGS_BUILDERS = {
    "display":    _build_settings_display,
    "brightness": _build_settings_brightness,
    "audio":      _build_settings_audio,
    "network":    _build_settings_network,
    "bluetooth":  _build_settings_bluetooth,
    "battery":    _build_settings_battery,
    "calendar":   _build_settings_calendar,
}

def build_settings(win: Gtk.Window):
    win.set_default_size(380, 1)
    outer = vbox(0)

    stack = Gtk.Stack()
    # Keine Animation: dieses Fenster laeuft als Layer-Shell-Overlay,
    # vermutlich ohne GPU-Beschleunigung fuer den Compositing-Pfad -
    # ein animierter Uebergang zeichnet mehrfach pro Sekunde neu und
    # ruckelt genau deshalb. Passt auch zur Devise des restlichen
    # Daemons (siehe Header-Kommentar ueber die 35-50ms-Klick-Ziele):
    # lieber sofort und sauber als hübsch und langsam.
    stack.set_transition_type(Gtk.StackTransitionType.NONE)

    hub = vbox(4); pad(hub, h=10, v=8)
    hub.pack_start(btitle("󰒓  Einstellungen"), False, False, 0)
    hub.pack_start(sep(), False, False, 2)
    for cat_key, icon, cat_label, cat_desc in SETTINGS_CATEGORIES:
        hub.pack_start(
            _settings_category_row(
                icon, cat_label, cat_desc,
                lambda _b, k=cat_key: stack.set_visible_child_name(k)),
            False, False, 0)
    stack.add_named(hub, "hub")

    # Netzwerk/Akku bringen als wiederverwendete Widgets bereits ihren
    # eigenen Titel + Trenner mit - hier nicht nochmal davorsetzen,
    # sonst steht "Netzwerk" zweimal übereinander.
    _reused_widget_categories = {"network", "battery", "audio", "bluetooth",
                                  "calendar", "brightness"}

    for cat_key, icon, cat_label, cat_desc in SETTINGS_CATEGORIES:
        page = vbox(4); pad(page, h=10, v=8)
        back_row = hbox(6); back_row.set_halign(Gtk.Align.START)
        back_row.pack_start(
            btn("←  Zurück",
                cb=lambda _b: stack.set_visible_child_name("hub")),
            False, False, 0)
        page.pack_start(back_row, False, False, 0)
        if cat_key not in _reused_widget_categories:
            page.pack_start(btitle(f"{icon}  {cat_label}"), False, False, 0)
            page.pack_start(sep(), False, False, 2)
        SETTINGS_BUILDERS.get(cat_key, _build_settings_placeholder)(
            page, cat_key, cat_label, win)
        stack.add_named(page, cat_key)

    outer.pack_start(stack, True, True, 0)
    outer.pack_start(sep(), False, False, 2)

    # ── Apply-Leiste: immer sichtbar (auf Wunsch), Buttons nur aktiv,
    #    wenn es tatsächlich etwas zu übernehmen/verwerfen gibt ──
    apply_bar = vbox(4); pad(apply_bar, h=10, v=6)
    status_lbl = Gtk.Label(label="Keine ausstehenden Änderungen")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    btn_row = hbox(6); btn_row.set_halign(Gtk.Align.CENTER)

    discard_b = btn("Verwerfen")
    apply_b   = btn("✓  Übernehmen")

    def _do_apply(_b):
        apply_b.set_sensitive(False)
        discard_b.set_sensitive(False)
        status_lbl.set_label("Wird übernommen…")
        def _done(errors):
            apply_b.set_sensitive(True)
            discard_b.set_sensitive(True)
            status_lbl.set_label(
                "Fehler: " + "; ".join(errors)[:140] if errors
                else "Übernommen ✓")
        apply_all_async(_done)

    def _do_discard(_b):
        discard_all()
        status_lbl.set_label("Verworfen")

    discard_b.connect("clicked", _do_discard)
    apply_b.connect("clicked", _do_apply)
    btn_row.pack_start(discard_b, False, False, 0)
    btn_row.pack_start(apply_b, False, False, 0)
    apply_bar.pack_start(status_lbl, False, False, 0)
    apply_bar.pack_start(btn_row, False, False, 0)
    outer.pack_start(apply_bar, False, False, 0)

    def _refresh_bar():
        n = len(PENDING)
        if n:
            status_lbl.set_label(f"{n} ausstehende Änderung"
                                  f"{'en' if n != 1 else ''}: " +
                                  ", ".join(c.desc for c in PENDING.values())[:140])
        else:
            status_lbl.set_label("Keine ausstehenden Änderungen")
        return False

    _apply_bar_refresh[0] = lambda: GLib.idle_add(_refresh_bar)
    _refresh_bar()

    # Auf Wunsch: offene, noch nicht übernommene Änderungen automatisch
    # verwerfen, sobald das Settings-Fenster geschlossen wird (Fokus-
    # verlust -> _cleanup() in toggle_widget ruft win.destroy() auf,
    # was dieses Signal auslöst). Kein manuelles "Verwerfen" nötig.
    win.connect("destroy", lambda _w: PENDING.clear())

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
#  Unix-Socket-Server
#  Der Client (widgets_client.py) verbindet sich, schickt den
#  Widget-Namen als eine Zeile Text und trennt danach die
#  Verbindung. Der Socket wird über GLib.io_add_watch direkt in
#  den GTK-Main-Loop eingehängt - kein zusätzlicher Thread, keine
#  Polling-Schleife, der Loop wacht nur auf, wenn wirklich Daten
#  ankommen.
# ════════════════════════════════════════════════════════════
import socket

SOCK_PATH = os.environ.get("WB_DAEMON_SOCK", "/tmp/wb-daemon.sock")

def _on_client_readable(conn, _cond):
    try:
        data = conn.recv(256)
        if data:
            name = data.decode("utf-8", "ignore").strip()
            if name:
                result = toggle_widget(name)
                try: conn.sendall((result + "\n").encode())
                except Exception: pass
    except Exception:
        pass
    finally:
        try: conn.close()
        except Exception: pass
    return False  # Watch nach dieser einen Anfrage entfernen

def _on_socket_readable(server_sock, _cond):
    try:
        conn, _ = server_sock.accept()
        conn.setblocking(False)
        GLib.io_add_watch(conn, GLib.IO_IN | GLib.IO_HUP,
                           lambda c, cond: _on_client_readable(c, cond))
    except Exception:
        pass
    return True  # Watch auf dem Server-Socket bleibt dauerhaft aktiv

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
    """Ruft jedes extern genutzte CLI-Tool einmal (read-only) auf, kurz
    nach dem Daemon-Start, in einem Hintergrund-Thread.

    Grund: Beim ersten Aufruf eines Programms muss der Kernel dessen
    Binary + shared libraries von der Platte lesen (Page-Cache noch
    kalt). Jeder darauffolgende Aufruf trifft den Page-Cache und ist
    spürbar schneller. Das erklärt das Muster aus den Messungen: JEDER
    Widget-Typ war beim allerersten Öffnen 2-4x langsamer als bei
    jedem weiteren (z.B. bluetooth 125ms -> 35ms, volume 152ms ->
    43ms) - nicht weil der Daemon-Code selbst langsam war, sondern
    weil wpctl/nmcli/bluetoothctl/brightnessctl dort zum ersten Mal
    seit dem letzten Neustart/Leeren des Page-Cache liefen.
    Hier holen wir diesen Kaltstart-Preis EINMAL beim Daemon-Start ab,
    lange bevor der erste echte Klick kommt - nicht mehr beim ersten
    tatsächlichen Widget-Öffnen des Nutzers.

    (Das langsame powerprofilesctl-D-Bus-Problem bei "akku" liegt
    NICHT am Page-Cache, sondern am D-Bus-Roundtrip selbst - das ist
    separat in build_akku() async gemacht, siehe Kommentar dort.)
    """
    for cmd in (
        ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
        ["playerctl", "metadata", "--format", "{{status}}"],
        ["pactl", "--format=json", "list", "sinks"],
        ["nmcli", "-t", "-f", "IN-USE,SSID", "dev", "wifi", "list"],
        ["bluetoothctl", "show"],
        ["brightnessctl", "get"],
        ["powerprofilesctl", "list"],
    ):
        try:
            run(cmd, timeout=5)
        except Exception:
            pass

def main():
    load_css()
    _start_socket_server()
    in_thread(_prewarm_tools)
    # GLib.unix_signal_add statt signal.signal(): reagiert zuverlässig
    # auch innerhalb der GLib-Main-Loop (siehe v5-Fix-Notiz weiter
    # oben), diesmal einmalig für den Daemon-Prozess selbst statt pro
    # Fenster.
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT,  _shutdown)
    print(f"widgets_daemon: bereit, höre auf {SOCK_PATH}", file=sys.stderr)
    Gtk.main()

# ════════════════════════════════════════════════════════════
#  CLI: Wetter-Standort setzen — laeuft als einmaliger, kurzer
#  Aufruf ohne Socket-Server/Gtk.main() zu starten und OHNE den
#  laufenden Daemon anzufassen. Schreibt nur
#  ~/.config/wb-daemon/weather.json; der laufende Daemon liest die
#  Datei beim naechsten Timer-Tick (alle 10 Min) bzw. beim naechsten
#  Oeffnen des Kalender-Widgets automatisch neu ein.
# ════════════════════════════════════════════════════════════
def _cli_set_weather(query: str) -> int:
    results = _geocode(query)
    if not results:
        print(f"Keine Treffer für '{query}' gefunden.", file=sys.stderr)
        return 1
    if len(results) > 1:
        print(f"Mehrere Treffer für '{query}', bitte eindeutiger "
              f"angeben oder eine Nummer waehlen:", file=sys.stderr)
        for i, res in enumerate(results, 1):
            admin   = res.get("admin1", "")
            country = res.get("country", "")
            print(f"  {i}. {res['name']} ({admin}, {country}) "
                  f"— lat={res['latitude']}, lon={res['longitude']}",
                  file=sys.stderr)
        print("\nEntweder praeziser aufrufen, z.B. "
              '"--set-weather \\"Ort, Region\\"" ,'
              " oder direkt Koordinaten setzen mit:\n"
              "  widgets_daemon.py --set-weather-coords <lat> <lon> \"<Name>\"",
              file=sys.stderr)
        return 1
    res = results[0]
    _save_weather_location(res["latitude"], res["longitude"], res["name"])
    print(f"Wetterstandort gesetzt: {res['name']} "
          f"(lat={res['latitude']}, lon={res['longitude']})")
    print(f"Gespeichert in {WEATHER_CONF}")
    return 0

def _cli_show_weather_location() -> int:
    loc = _load_weather_location()
    print(f"Aktueller Wetterstandort: {loc.get('name', '?')} "
          f"(lat={loc['lat']}, lon={loc['lon']})")
    print(f"Konfigurationsdatei: {WEATHER_CONF}")
    return 0

def _print_cli_usage() -> None:
    print(
        "widgets_daemon.py [--set-weather \"<Ort>\" | "
        "--set-weather-coords <lat> <lon> \"<Name>\" | "
        "--show-weather]\n"
        "Ohne Argumente: startet den Daemon (normalerweise per "
        "systemd --user wb-daemon.service).",
        file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--set-weather":
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
            print("lat/lon müssen Zahlen sein, z.B. 47.0707 15.4395",
                  file=sys.stderr)
            sys.exit(1)
        _name = " ".join(sys.argv[4:])
        _save_weather_location(_lat, _lon, _name)
        print(f"Wetterstandort gesetzt: {_name} (lat={_lat}, lon={_lon})")
        print(f"Gespeichert in {WEATHER_CONF}")
        sys.exit(0)
    elif len(sys.argv) > 1 and sys.argv[1] in ("--show-weather", "--weather-status"):
        sys.exit(_cli_show_weather_location())
    elif len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        _print_cli_usage()
        sys.exit(0)
    main()
