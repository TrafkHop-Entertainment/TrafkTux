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

import gi, sys, os, signal, subprocess, json, threading, time, calendar
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

def build_volume(win: Gtk.Window):
    win.set_default_size(400, 1)
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
    win.add(outer)

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

def build_network(win: Gtk.Window):
    win.set_default_size(380, 1)
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
    win.add(root)

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

def build_bluetooth(win: Gtk.Window):
    win.set_default_size(380, 1)
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
    win.add(root)

# ════════════════════════════════════════════════════════════
#  BRIGHTNESS
# ════════════════════════════════════════════════════════════
_nl_proc   = None
_nl_temp   = [3500]
_nl_active = [False]

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

def _nl_start(temp: int):
    global _nl_proc
    _nl_stop()
    for cmd in [["gammastep",  "-O", str(temp)],
                ["hyprsunset", "-t", str(temp)],
                ["wlsunset",   "-t", str(temp),
                 "-T", "6500", "-l", "47.8", "-L", "16.2"]]:
        try:
            _nl_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.3)
            if _nl_proc.poll() is None: return
            _nl_proc = None
        except FileNotFoundError:
            continue

def _nl_stop():
    global _nl_proc
    if _nl_proc:
        try: _nl_proc.terminate()
        except: pass
        _nl_proc = None
    for c in [["pkill","gammastep"],["pkill","hyprsunset"],["pkill","wlsunset"]]:
        try: subprocess.run(c, capture_output=True, timeout=2)
        except: pass

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

def build_brightness(win: Gtk.Window):
    win.set_default_size(360, 1)
    root = vbox(4); pad(root, h=10, v=8)

    root.pack_start(btitle("󰃠  Helligkeit"), False, False, 0)
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

    def _on_temp(s):
        _nl_temp[0] = int(s.get_value())
        temp_lbl.set_label(f"{_nl_temp[0]} K")
        if _nl_active[0]: in_thread(_nl_start, _nl_temp[0])

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
        if _nl_active[0]:
            ctx.add_class("active"); in_thread(_nl_start, _nl_temp[0])
        else:
            ctx.remove_class("active"); in_thread(_nl_stop)

    temp_s.connect("value-changed", _on_temp)
    nl_b.connect("clicked", _on_nl)
    win.add(root)

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

def build_akku(win: Gtk.Window):
    win.set_default_size(340, 1)
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
    # FIX (500ms-Delay): powerprofilesctl spricht per D-Bus mit dem
    # power-profiles-daemon - das ist KEIN schneller lokaler Aufruf
    # wie z.B. das sysfs-Lesen in _bat(), sondern ein Roundtrip, der
    # auf diesem System durchgängig ~500ms braucht (siehe Messung).
    # Vorher liefen "powerprofilesctl list" + "powerprofilesctl get"
    # SYNCHRON im GTK-Main-Loop, bevor das Fenster sichtbar wurde -
    # jeder Akku-Klick hat also erst 500ms gewartet, bevor überhaupt
    # etwas gezeichnet wurde. Jetzt: Fenster sofort mit Platzhalter
    # zeigen, Profile im Hintergrund-Thread nachladen (exakt das
    # Muster, das _refresh_devices() in build_volume schon nutzt).
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

    win.add(root)

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

def _fetch_weather() -> dict:
    """Holt Wetter über die wttr.in JSON-API (format=j1).
    FIX ggü. vorher: die alte 'format=3'-Abfrage liefert wttr.in-seitig
    IMMER nur eine einzelne Zeile (aktuelles Wetter) — es gab also nie
    echte Vorhersagen für Tag+1/Tag+2, das konnte gar nicht funktionieren.
    Die JSON-API liefert echte Tages-Wettercodes für heute/morgen/übermorgen."""
    r = {"icon": "🌡️", "desc": "–", "temp": "–",
         "humidity": "–", "precip": "–",
         "day1_icon": "–", "day2_icon": "–"}
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            "https://wttr.in/WienerNeustadt?format=j1&lang=de",
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

def build_clock(win: Gtk.Window):
    win.set_default_size(460, 1)
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
        GLib.idle_add(_apply)

    in_thread(_load_weather)
    add_timer(600_000, lambda: in_thread(_load_weather) or True)

    win.add(root)

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

if __name__ == "__main__":
    main()
