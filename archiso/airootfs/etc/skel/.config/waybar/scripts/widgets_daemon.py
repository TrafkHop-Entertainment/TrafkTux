#!/usr/bin/env python3
"""
widgets_daemon.py — TrafkTux Waybar Widget System (Daemon)
Invocation: python3 widgets_daemon.py
Controlled via client: widgets_client.py <widget>
Widgets: volume | network | bluetooth | brightness | akku | clock | settings
"""

import gi, sys, os, re, signal, subprocess, json, threading, time, calendar
from datetime import datetime, date
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
#  Paths & Colors
# ════════════════════════════════════════════════════════════
HOME   = os.path.expanduser("~")
B_NORM = f"file://{HOME}/.config/rofi/assets/bubble-normal.png"
B_SEL  = f"file://{HOME}/.config/rofi/assets/bubble-selected.png"
WALLPAPER_SCRIPT = f"{HOME}/.config/hypr/random_wallpaper.sh"

WEATHER_CONF     = Path(HOME) / ".config" / "wb-daemon" / "weather.json"
_DEFAULT_WEATHER_LOC = {"lat": 47.8121, "lon": 16.2506, "name": "Wiener Neustadt"}
GOLD   = "#fff495"
GOLD_H = "#c8b800"
GOLD_DIM = "rgba(255,244,149,0.45)"

# ════════════════════════════════════════════════════════════
#  CSS
# ════════════════════════════════════════════════════════════
def _css() -> bytes:
    return f"""
window {{
    background-color: transparent;
    border: none;
}}

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

.bubble.title {{
    padding: 8px 22px;
    margin: 4px 0px;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 1px;
}}

.bubble.section {{
    padding: 3px 16px;
    margin: 6px 0px 1px 0px;
    font-size: 11px;
    font-weight: bold;
    color: {GOLD};
    letter-spacing: 2px;
}}

.bubble.item {{
    padding: 5px 16px;
    margin: 1px 0px;
    font-size: 13px;
}}

.icon-lg  {{ font-size: 22px; }}
.icon-xl  {{ font-size: 34px; }}
.value-md {{ font-size: 15px; font-weight: bold; }}
.temp-xl  {{ font-size: 26px; font-weight: bold; }}
.caption  {{ font-size: 11px; }}

.bubble.slider {{
    padding: 6px 14px;
    margin: 1px 0px;
}}

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
button.bubble.has-events {{
    /* Kalendertage mit mind. einem khal-Termin - rötliche Tönung als
    halbtransparente background-color ÜBER dem bestehenden Bubble-PNG
    (funktioniert unabhängig davon, wie transparent das PNG selbst
    ist) plus eine dünne rote Umrandung als zusätzliches, klar
    sichtbares Signal. box-shadow statt border, da .bubble weiter oben
    generell "border: none" setzt und box-shadow das nicht
    überschreibt. */
    background-color: rgba(200, 40, 40, 0.35);
    box-shadow: inset 0 0 0 1px rgba(255, 120, 120, 0.9);
}}
button.bubble.has-events:hover {{
    background-color: rgba(220, 55, 55, 0.5);
}}
button.bubble.has-events.active {{
    /* Heute + Termine gleichzeitig - beide Signale bleiben erkennbar */
    background-image: url("{B_SEL}");
    background-color: rgba(200, 40, 40, 0.35);
    box-shadow: inset 0 0 0 1px rgba(255, 120, 120, 0.9);
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
#  Window Management
# ════════════════════════════════════════════════════════════
WIDGET = None
_open: dict[str, Gtk.Window] = {}
_timers_by_win: dict[Gtk.Window, list] = {}
_current_win: list = [None]

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
    global WIDGET
    if name not in BUILDERS:
        return f"error: unknown widget '{name}'"

    if name in _open:
        _destroy_widget(name)
        return "closed"

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
#  UI Helpers
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
    if cb:  b.connect("clicked", cb)
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
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(120)

    # ── TAB 1: Media ────────────────────────────────────────
    t1 = vbox(4); pad(t1, h=10, v=8)

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
        stack.set_visible_child_name(name)
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

    outer = vbox(4); pad(outer, h=8, v=6)
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

def _network_content(win: Gtk.Window) -> Gtk.Box:
    root = vbox(4); pad(root, h=10, v=8)

    scan_b = btn("󰑐  Scan")
    hdr = hbox(6)
    hdr.pack_start(btitle("󰤨  Network"), False, False, 0)
    hdr.pack_start(scan_b, False, False, 0)
    hdr.set_halign(Gtk.Align.CENTER)
    root.pack_start(hdr, False, False, 0)

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
                               text="Connection Failed")
        d.set_name("wb-daemon-popup")   # <-- NEU
        d.set_keep_above(True)
        d.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        d.format_secondary_text((msg or "Unknown error")[:200])
        d.run(); d.destroy()

    def _populate(nets):
        for c in net_box.get_children(): net_box.remove(c)
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
        in_thread(lambda: GLib.idle_add(_populate, _wifi_list()))

    def _do_scan(_):
        scan_b.set_label("󰑎  Scanning…"); scan_b.set_sensitive(False)
        def _scan():
            dev = _wifi_dev_name()
            cmd = ["nmcli", "dev", "wifi", "rescan"]
            if dev:
                cmd += ["ifname", dev]
            out, err, rc = run_ec(cmd, timeout=10)
            if rc != 0 and "not allowed" in (err or "").lower():
                GLib.idle_add(_flash_note,
                               "Scan cooldown active (Wi-Fi scans only every ~30s) — showing current list")
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
            GLib.idle_add(lambda: (
                pwr_b.set_label("󰂯  On" if powered[0] else "󰂲  Off"),
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
#  ddcutil (externe Monitor-Helligkeit per DDC/CI)
# ════════════════════════════════════════════════════════════
# Laptop-Panels unterstützen kein DDC/CI (bestätigt in ddcutils
# eigener FAQ - eDP-Displays implementieren nur die EDID-Leseadresse
# x50, nicht die DDC-Kommandoadresse x37), deshalb bleibt das interne
# Display bei brightnessctl (siehe _bright_pct/_on_bright oben) -
# ddcutil kommt NUR für extern angeschlossene Monitore zum Einsatz.
_DDCUTIL_CACHE = {"available": None}

def _ddcutil_available() -> bool:
    if _DDCUTIL_CACHE["available"] is None:
        import shutil
        _DDCUTIL_CACHE["available"] = shutil.which("ddcutil") is not None
    return _DDCUTIL_CACHE["available"]

def _ddcutil_detect() -> list[dict]:
    """Liste externer DDC-fähiger Monitore via 'ddcutil detect --brief'
    (maschinell parsebares Format, siehe ddcutil-Doku). WICHTIG:
    Display-Nummern UND I2C-Busnummern sind nicht über Reboots stabil
    - deshalb wird hier bei JEDEM Öffnen des Widgets frisch erkannt,
    nie eine Nummer dauerhaft gespeichert. 'ddcutil detect' kann
    mehrere Sekunden dauern (DDC/CI-Kommunikation ist von Natur aus
    langsam laut ddcutil-Doku) - MUSS also aus einem Hintergrund-
    Thread aufgerufen werden, nie direkt im GTK-Main-Thread."""
    if not _ddcutil_available():
        return []
    out = run(["ddcutil", "detect", "--brief"], timeout=15)
    if not out:
        return []
    monitors = []
    cur: dict = {}
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r'^Display (\d+)$', line)
        if m:
            if cur:
                monitors.append(cur)
            cur = {"display_num": int(m.group(1))}
            continue
        m = re.match(r'^Monitor:\s*(.+)$', line)
        if m and cur:
            parts = m.group(1).split(":")
            cur["name"] = parts[1] if len(parts) > 1 and parts[1] else parts[0]
    if cur:
        monitors.append(cur)
    return monitors

def _ddcutil_get_brightness(display_num: int) -> int | None:
    """Aktuelle Helligkeit (VCP-Code 10 = Brightness) via --brief
    abfragen. Laut ddcutil-Doku zeigt --brief/--terse für ein
    kontinuierliches Feature wie Brightness "both the current value
    (in decimal) and maximum value (in decimal)" - das genaue Prefix-
    Format variiert leicht zwischen ddcutil-Versionen, daher robust
    über "letzte zwei Dezimalzahlen im Output = current, max" statt
    über eine feste Spaltenposition geparst. None bei Kommunikations-
    fehler (Monitor reagiert nicht auf DDC, auch wenn er in detect
    auftauchte - laut FAQ nicht ungewöhnlich)."""
    out = run(["ddcutil", "--display", str(display_num),
               "getvcp", "10", "--brief"], timeout=8)
    if not out:
        return None
    nums = [p for p in out.split() if p.isdigit()]
    return int(nums[-2]) if len(nums) >= 2 else None

def _ddcutil_set_brightness(display_num: int, pct: int) -> bool:
    """Setzt Helligkeit (VCP 10) auf einen externen Monitor. Gibt
    False zurück statt eine Exception hochzureichen, falls der Monitor
    nicht antwortet - DDC/CI-Fehler bei einzelnen Monitoren sind laut
    ddcutil-Doku normal genug, dass die UI das ruhig wegstecken muss,
    statt das ganze Widget zum Absturz zu bringen."""
    _out, _err, ec = run_ec(
        ["ddcutil", "--display", str(display_num), "setvcp", "10", str(pct)],
        timeout=8)
    return ec == 0

# ════════════════════════════════════════════════════════════
#  OpenRGB (pro-Gerät Helligkeit + Farbe für alle erkannten
#  RGB-Geräte - Tastatur, Maus, Mainboard, GPU, RAM, ...)
# ════════════════════════════════════════════════════════════
# Ersetzt den alten, einzelnen globalen Hue-Regler: openrgb-python
# verbindet sich mit dem OpenRGB-SDK-Server und liefert strukturierte
# Geräteobjekte (Name, Typ, Modi) statt CLI-Text parsen zu müssen.
# API-Verhalten unten wurde gegen die tatsächlich installierte
# openrgb-python-Bibliothek verifiziert (Quellcode gelesen), nicht nur
# aus der Doku übernommen - insbesondere: device.active_mode ist ein
# INDEX in device.modes, kein Objekt; Helligkeit wird nicht über eine
# eigene Methode gesetzt, sondern indem man das ModeData-Objekt des
# aktiven Modus mit geändertem .brightness erneut über
# device.set_mode() schickt.
_ORGB_CLIENT = {"client": None}
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
    ('openrgb --server', minimiert/ohne GUI) - bewusst NICHT als
    dauerhafter systemd-Service, damit nichts unnötig im Hintergrund
    läuft, wenn man das Brightness-Widget gar nicht öffnet. Wartet
    kurz auf den Verbindungsaufbau, da der Serverstart selbst nicht
    synchron ist."""
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
    """Liefert einen verbundenen OpenRGBClient, oder None bei
    Fehler. Cached NICHT über mehrere Widget-Öffnungen hinweg (anders
    als z.B. _khal_available) - eine tote/abgelaufene Verbindung vom
    letzten Mal würde sonst bei jedem weiteren Öffnen sofort wieder
    fehlschlagen, ohne dass ein Neuverbindungsversuch stattfindet."""
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
    NICHT jeder Modus tut das, z.B. reine "Direct"-Modi bei manchen
    Geräten haben kein Brightness-Flag, andere wie "Static" oft
    schon), und die aktuelle Farbe fürs Vorbelegen des Farbreglers."""
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
    laut openrgb-python-Doku ist der Listenindex "not ideal ... because
    the device's index could change if a new device is added, or the
    order of OpenRGB's detectors is changed". Name ist innerhalb einer
    laufenden Widget-Sitzung stabil genug (die Hardware ändert sich
    nicht während das Fenster offen ist)."""
    for d in client.devices:
        if d.name == name:
            return d
    return None

def _openrgb_set_brightness(dev_name: str, value: int) -> None:
    """Läuft in einem Hintergrund-Thread (siehe _debounced() im UI-
    Code) - öffnet dafür eine EIGENE, kurzlebige Verbindung statt die
    UI-Ladeverbindung wiederzuverwenden, da diese in einem anderen
    Thread lief und openrgb-python-Verbindungen nicht als thread-safe
    dokumentiert sind."""
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
        pass  # z.B. Gerät kurz nicht erreichbar - UI zeigt einfach weiter den zuletzt gesetzten Wert

def _openrgb_set_color(dev_name: str, hex_color: str) -> None:
    """Wie _openrgb_set_brightness, für Farbe. Setzt die Farbe des
    gesamten Geräts (alle LEDs gleich) - reicht für ein einfaches
    Brightness/Color-Widget; Zonen-/Pro-LED-Steuerung wäre eine
    eigene, deutlich komplexere Erweiterung."""
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
    root = vbox(4); pad(root, h=10, v=8)

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

    root.pack_start(bsec("INTERNAL DISPLAY"), False, False, 0)

    def _on_bright(s):
        in_thread(run, ["brightnessctl", "set", f"{int(s.get_value())}%"])
    bright_box, _ = bslider("󰃟", 5, 100, 1, _bright_pct(), cb=_on_bright)
    root.pack_start(bright_box, False, False, 0)

    # ── Externe Monitore (DDC/CI via ddcutil) ────────────────────────
    # Laptop-Displays unterstützen kein DDC/CI (siehe Kommentar bei
    # den ddcutil-Helpern oben), deshalb komplett getrennter Pfad vom
    # brightnessctl-Regler oben. Erkennung ('ddcutil detect') kann
    # laut ddcutil-Doku mehrere Sekunden dauern - läuft deshalb IMMER
    # asynchron im Hintergrund-Thread, nie blockierend beim Öffnen des
    # Widgets. Wird kein externer Monitor gefunden (z.B. nur Laptop-
    # Display angeschlossen), erscheint dieser Bereich einfach gar
    # nicht - kein leerer/verwirrender UI-Abschnitt.
    ext_section = vbox(4)
    root.pack_start(ext_section, False, False, 0)

    def _build_external_monitor_row(mon: dict, cur_val: int | None) -> Gtk.Box:
        """Ein Regler pro extern erkanntem Monitor. Debounced wie der
        Night-Light-Regler weiter unten - DDC/CI-Schreibvorgänge sind
        laut ddcutil-Doku inhärent langsam (I2C-Bus-Kommunikation),
        ein Slider, der bei jedem einzelnen Pixel-Drag sofort einen
        ddcutil-Aufruf feuert, würde die Anfragen stauen und spürbar
        hinterherhinken bzw. den Regler ruckeln lassen. cur_val kommt
        bereits FERTIG ABGEFRAGT von _load_external_monitors() - ein
        Lesevorgang hier (im GTK-Main-Thread, da diese Funktion via
        GLib.idle_add aufgerufen wird) wäre genauso blockierend wie
        ein Schreibvorgang."""
        display_num = mon["display_num"]
        debounce_id = [0]

        def _on_ext_bright(s):
            val = int(s.get_value())
            if debounce_id[0]:
                GLib.source_remove(debounce_id[0])
            def _fire():
                debounce_id[0] = 0
                in_thread(_ddcutil_set_brightness, display_num, val)
                return False
            debounce_id[0] = GLib.timeout_add(200, _fire)

        box, _ = bslider("󰍹", 0, 100, 1, cur_val if cur_val is not None else 50,
                          cb=_on_ext_bright)
        if cur_val is None:
            # Monitor wurde erkannt, antwortet aber nicht auf DDC-
            # Anfragen (laut FAQ nicht ungewöhnlich, auch bei
            # eigentlich unterstützten Monitoren) - Regler bleibt
            # sichtbar (man kann es trotzdem versuchen), aber mit
            # Hinweis statt einem stillen Rätsel, warum der Wert
            # "50" zeigt statt dem echten Stand.
            box.set_tooltip_text(
                f'{mon.get("name", "Monitor")}: aktueller Wert nicht lesbar '
                f'(DDC antwortet nicht zuverlässig) - Regler funktioniert '
                f'trotzdem versuchsweise.')
        else:
            box.set_tooltip_text(mon.get("name", "Monitor"))
        return box

    def _load_external_monitors():
        monitors = _ddcutil_detect()
        # Helligkeit für JEDEN Monitor hier im Hintergrund-Thread
        # vorab abfragen (siehe Docstring oben) - (Monitor, aktueller
        # Wert)-Paare, damit _apply() unten nur noch fertige Werte in
        # die UI einsetzen muss, ohne selbst eine DDC-Anfrage zu
        # blockieren.
        monitors_with_val = [(mon, _ddcutil_get_brightness(mon["display_num"]))
                              for mon in monitors]
        def _apply():
            if not monitors_with_val:
                return
            ext_section.pack_start(sep(), False, False, 2)
            ext_section.pack_start(bsec("EXTERNAL MONITORS"), False, False, 0)
            for mon, cur_val in monitors_with_val:
                row = _build_external_monitor_row(mon, cur_val)
                ext_section.pack_start(row, False, False, 0)
            ext_section.show_all()
        GLib.idle_add(_apply)

    if _ddcutil_available():
        in_thread(_load_external_monitors)

    kbd_dev     = _kbd_backlight_device()
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
    # Ersetzt den früheren einzelnen globalen Hue-Regler. Jedes Gerät
    # bekommt nur die Regler, die es laut seinem aktuell aktiven Modus
    # tatsächlich unterstützt - Farbe ist praktisch immer verfügbar,
    # Helligkeit nur wenn ModeFlags.HAS_BRIGHTNESS gesetzt ist (siehe
    # _openrgb_device_info oben). Erkennung + SDK-Serverstart laufen
    # komplett asynchron - openrgb-python macht synchrone Netzwerk-
    # Aufrufe, ein direkter Aufruf im GTK-Main-Thread würde das Fenster
    # einfrieren, bis der Server geantwortet hat (oder der Verbindungs-
    # Timeout abläuft, falls kein OpenRGB installiert ist).
    rgb_section = vbox(4)
    root.pack_start(rgb_section, False, False, 0)

    def _build_rgb_device_row(info: dict) -> Gtk.Box:
        dev_name = info["name"]  # stabiler Schlüssel statt Listenindex,
                                  # siehe _openrgb_find_device()-Kommentar
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
            dlg = Gtk.ColorChooserDialog(title="Farbe wählen", transient_for=win)
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
        color_lbl = Gtk.Label(label="Farbe:")
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
               "power-saver": "Power Saver"}

def _ppd_available() -> list:
    out = run(["powerprofilesctl", "list"])
    return [p for p in ["power-saver","balanced","performance"] if p in out]

def _akku_content() -> Gtk.Box:
    root = vbox(4); pad(root, h=10, v=8)

    root.pack_start(btitle("󰁹  Battery"), False, False, 0)
    root.pack_start(sep(), False, False, 2)

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
            bat_pct_lbl.set_label("  No Battery")
            bat_status_lbl.set_label("")
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
                bitem("power-profiles-daemon not found", dim=True),
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
def _wicon_wmo(code) -> str:
    try: return _WMO_ICON.get(int(code), "🌡️")
    except (TypeError, ValueError): return "🌡️"

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
DAYS_EN   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

# ════════════════════════════════════════════════════════════
#  khal-Integration (schnelle Termine im Kalender-Widget)
# ════════════════════════════════════════════════════════════
# khal ist bewusst gewaehlt statt einer schwergewichtigen Desktop-App
# (Thunderbird/GNOME Calendar) oder einer direkten Cloud-Anbindung:
# standardbasiert (iCalendar/vdir), leichtgewichtig, rein CLI-
# steuerbar - genau das, was ein Widget braucht, das im Hintergrund
# Termine anlegt/abfragt. Speichert lokal in .ics-Dateien; wer später
# mit Google/Nextcloud/CalDAV synchronisieren will, kann das komplett
# unabhängig über vdirsyncer nachrüsten, ohne dass sich an dieser
# Integration hier etwas ändern müsste - khal selbst merkt davon
# nichts, es liest/schreibt nur seinen vdir-Ordner.
_KHAL_CACHE = {"available": None, "configured": None}

def _khal_available() -> bool:
    """Prüft EINMAL pro Daemon-Laufzeit (nicht bei jedem Aufruf), ob
    khal installiert ist - shutil.which ist billig, aber unnötig
    wiederholt in einer UI-Update-Schleife trotzdem vermeidbar."""
    if _KHAL_CACHE["available"] is None:
        import shutil
        _KHAL_CACHE["available"] = shutil.which("khal") is not None
    return _KHAL_CACHE["available"]

def _khal_configured() -> bool:
    """khal braucht mindestens einen konfigurierten Kalender (eine
    [[name]]-Sektion mit path=... in ~/.config/khal/config), sonst
    schlagen 'khal new'/'khal list' mit einem Konfigurationsfehler
    fehl. 'khal printcalendars' listet alle konfigurierten Kalender -
    leere Ausgabe bzw. Fehler heisst: noch nichts eingerichtet."""
    if _KHAL_CACHE["configured"] is None:
        out, _err, ec = run_ec(["khal", "printcalendars"])
        _KHAL_CACHE["configured"] = (ec == 0 and bool(out.strip()))
    return _KHAL_CACHE["configured"]

def _khal_default_calendar_name() -> str:
    """Erster Eintrag aus 'khal printcalendars' als Default fürs
    Anlegen neuer Termine, falls khal selbst keinen markiert."""
    out = run(["khal", "printcalendars"])
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[0] if lines else ""

def _khal_setup_default_calendar() -> tuple[bool, str]:
    """Legt automatisch einen minimalen lokalen Kalender an, falls
    noch keiner konfiguriert ist - Ziel ist, dass das Widget "einfach
    funktioniert" ohne dass man vorher manuell durch 'khal configure'
    klicken muss. Schreibt eine denkbar simple Config mit einem
    einzigen Kalender unter ~/.local/share/khal/calendars/private/
    (Standard-XDG-Datenverzeichnis, analog zu khal's eigenem
    Default-Speicherort für seine Cache-DB)."""
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
        _KHAL_CACHE["configured"] = None  # neu pruefen lassen
        ok = _khal_configured()
        return ok, "" if ok else "khal-Konfiguration konnte nicht verifiziert werden."
    except Exception as e:
        return False, str(e)

def _khal_events_for_month(year: int, month: int) -> dict:
    """EIN einziger khal-Aufruf für den kompletten sichtbaren Monat
    statt bis zu 42 Einzelaufrufen (einer pro Kalendertag) -
    _build_grid() ruft das für jede sichtbare Zelle auf, und 42
    subprocess-Starts synchron im GTK-Main-Thread hätten das Fenster
    bei jedem Monatswechsel für mehrere hundert Millisekunden
    einfrieren lassen. 'khal list --json' unterstützt zusätzlich zu
    title auch 'start-date', damit hier nach Tag gruppiert werden
    kann. Rückgabe: {date_str: [event, ...]}."""
    if not (_khal_available() and _khal_configured()):
        return {}
    first = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    out, _err, ec = run_ec([
        "khal", "list", first.strftime("%Y-%m-%d"), f"{days_in_month}d",
        "--json", "title", "--json", "start-time", "--json", "start-date",
    ])
    if ec != 0 or not out.strip():
        return {}
    # WICHTIG: 'khal list --json' gibt bei einem mehrtägigen Zeitraum
    # NICHT ein einziges großes JSON-Array zurück, sondern EIN Array
    # PRO TAG, zeilenweise aneinandergereiht (z.B. "[]\n[]\n[{...}]\n").
    # Ein einzelnes json.loads() auf den kompletten Output wirft daher
    # "Extra data" (mehrere Top-Level-Werte in einem Dokument) - das
    # war der eigentliche Grund, warum hier nie Termine ankamen: die
    # Exception wurde vom bloßen "except: return {}" still verschluckt,
    # obwohl khal selbst die Termine korrekt geliefert hat. Verifiziert
    # gegen ein echtes khal 0.14.0 mit mehreren Terminen an
    # unterschiedlichen Tagen im selben Monat. Fix: zeilenweise
    # parsen, jede Zeile für sich als eigenes JSON-Array behandeln,
    # dann zusammenführen.
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
    (HH:MM) + Titel. Nutzt 'khal new DATE TIME SUMMARY' - khal
    berechnet das Ende automatisch (Default-Dauer 1h laut khal-Doku)."""
    if not title.strip():
        return False, "Titel darf nicht leer sein."
    if not re.match(r'^([01]?\d|2[0-3]):[0-5]\d$', time_str.strip()):
        return False, "Ungültige Uhrzeit (erwartet HH:MM)."
    date_str = d.strftime("%Y-%m-%d")
    _out, err, ec = run_ec(["khal", "new", date_str, time_str.strip(), title.strip()])
    if ec != 0:
        return False, err or "khal new ist fehlgeschlagen."
    return True, ""

def _clock_content(win: Gtk.Window) -> Gtk.Box:
    root = vbox(4); pad(root, h=10, v=8)

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
    loc_btn.set_tooltip_text("Standort ändern")
    stats_box.pack_start(hum_lbl,  False, False, 0)
    stats_box.pack_start(rain_lbl, False, False, 0)
    stats_box.pack_start(loc_btn,  False, False, 0)
    today_card.pack_start(stats_box, False, False, 0)

    root.pack_start(today_card, False, False, 0)

    def _prompt_change_location(_w=None):
        """Standort-Such-Dialog - ersetzt den bisher CLI-only Weg
        (--set-weather "<Ort>"), nutzt aber denselben _geocode()-
        Helper wie die CLI, damit beide Wege konsistent bleiben.
        Eigenständiges Gtk.Dialog aus demselben Grund wie schon beim
        Display-Widget/Termin-Dialog: Layer-Shell-Popups können nie
        Tastatureingaben empfangen (KeyboardMode.NONE), ein Gtk.Dialog
        ist ein normales Fenster mit regulärem Wayland-Fokus."""
        dlg = Gtk.Dialog(title="Standort ändern", transient_for=win)
        dlg.add_buttons("Schließen", Gtk.ResponseType.CANCEL)
        content = dlg.get_content_area()
        content.set_spacing(6)
        pad(content, h=14, v=10)
        dlg.set_default_size(340, 320)

        search_row = hbox(6)
        search_e = Gtk.Entry()
        search_e.set_placeholder_text("Stadt suchen…")
        search_e.set_hexpand(True)
        search_b = btn("Suchen")
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
            in_thread(_load_weather)  # sofort mit neuem Standort neu laden

        def _do_search(_w=None):
            query = search_e.get_text().strip()
            if not query:
                return
            status_lbl.set_label("Suche…")
            _clear_results()

            def _fetch():
                results = _geocode(query)
                def _apply():
                    status_lbl.set_label(
                        "" if results else f"Keine Ergebnisse für „{query}“")
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

        dlg_destroyed = [False]
        dlg.connect("destroy", lambda _d: dlg_destroyed.__setitem__(0, True))

        search_b.connect("clicked", _do_search)
        search_e.connect("activate", _do_search)
        dlg.show_all()
        status_lbl.hide()
        search_e.grab_focus()
        dlg.run()
        # _select() zerstört den Dialog bereits selbst (siehe oben) und
        # lässt dlg.run() dadurch zurückkehren - nur noch zerstören,
        # falls das NICHT der Fall war (z.B. "Schließen" geklickt, ohne
        # vorher einen Treffer auszuwählen). Ein zweiter destroy()-Call
        # auf ein bereits zerstörtes Widget ist zwar meist harmlos,
        # aber unsauber.
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
    root.pack_start(fc_row, False, False, 0)

    root.pack_start(sep(), False, False, 2)

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

    now = datetime.now()
    cur = [now.year, now.month]

    prev_b      = btn("󰄦")
    next_b      = btn("󰄧")
    mth_box, mth_lbl = bitem_ref("")
    nav_row = hrow(prev_b, mth_box, next_b, sp=4)
    root.pack_start(nav_row, False, False, 0)

    wd_row = hbox(2)
    wd_row.set_halign(Gtk.Align.CENTER)
    for wd in DAYS_EN:
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

    cal_grid = vbox(2)
    cal_grid.set_halign(Gtk.Align.CENTER)
    root.pack_start(cal_grid, False, False, 0)

    khal_ok = _khal_available() and _khal_configured()
    if not khal_ok and _khal_available():
        # khal ist installiert, aber (noch) nicht konfiguriert - Hinweis
        # mit Ein-Klick-Einrichtung statt eines stillen "Klick tut
        # nichts". Kein Hinweis, wenn khal gar nicht installiert ist -
        # dann bleibt der Kalender einfach ein reiner Anzeige-Kalender,
        # ohne den Nutzer mit einer Installationsanleitung zu behelligen.
        setup_row = hbox(6)
        setup_row.set_halign(Gtk.Align.CENTER)
        setup_lbl = Gtk.Label(label="Termine noch nicht eingerichtet")
        setup_lbl.get_style_context().add_class("caption")
        setup_btn = btn("Einrichten", tip="Legt einen lokalen Standardkalender an")
        setup_row.pack_start(setup_lbl, False, False, 0)
        setup_row.pack_start(setup_btn, False, False, 0)
        root.pack_start(setup_row, False, False, 2)

        def _on_setup_clicked(_w):
            ok, err = _khal_setup_default_calendar()
            if ok:
                setup_row.set_visible(False)
                _build_grid(cur[0], cur[1])
            else:
                setup_lbl.set_label(f"Einrichtung fehlgeschlagen: {err}"[:60])
        setup_btn.connect("clicked", _on_setup_clicked)

    def _prompt_new_event(d) -> None:
        """Kleiner Termin-Dialog - eigenständiges Gtk.Dialog-Fenster
        statt Inline-Entry im Layer-Shell-Popup, aus demselben Grund
        wie schon beim Display-Widget: Layer-Shell-Popups laufen mit
        KeyboardMode.NONE und können nie Tastatureingaben empfangen,
        ein Gtk.Dialog dagegen ist ein normales XDG-Toplevel-Fenster
        mit regulärem Wayland-Fokus."""
        dlg = Gtk.Dialog(title=f"Neuer Termin – {d.strftime('%d.%m.%Y')}",
                          transient_for=win)
        dlg.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                        "Anlegen", Gtk.ResponseType.OK)
        content = dlg.get_content_area()
        content.set_spacing(6)
        pad(content, h=14, v=10)

        title_e = Gtk.Entry()
        title_e.set_placeholder_text("Titel")
        title_e.set_activates_default(True)
        time_e = Gtk.Entry()
        time_e.set_placeholder_text("Uhrzeit, z.B. 14:30")
        time_e.set_text("12:00")
        time_e.set_activates_default(True)
        err_lbl = Gtk.Label(label="")
        err_lbl.get_style_context().add_class("caption")
        err_lbl.set_no_show_all(True)
        err_lbl.hide()

        content.pack_start(Gtk.Label(label="Titel:"), False, False, 0)
        content.pack_start(title_e, False, False, 0)
        content.pack_start(Gtk.Label(label="Uhrzeit:"), False, False, 0)
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
        _build_grid(cur[0], cur[1])  # neu bauen, damit der Termin-Punkt sofort erscheint

    def _show_events_popover(anchor: Gtk.Widget, day_date, events: list) -> None:
        """Floatendes Gtk.Popover mit den Terminen eines Tages - reine
        Anzeige, kein Toplevel-Fenster nötig (im Gegensatz zu den
        Text-Eingabe-Dialogen oben), weil hier keine Tastatureingabe
        gebraucht wird. Popover funktioniert innerhalb des Layer-
        Shell-Popups problemlos, es ist nur bei ECHTER Texteingabe
        (Gtk.Entry) ein Problem, dass Layer-Shell-Fenster keinen
        Tastaturfokus bekommen (siehe _prompt_text/_prompt_new_event
        weiter oben) - reines Anzeigen/Klicken betrifft das nicht."""
        pop = Gtk.Popover.new(anchor)
        pop.set_position(Gtk.PositionType.BOTTOM)
        box = vbox(4); pad(box, h=10, v=8)

        title = Gtk.Label()
        title.set_markup(f"<b>{day_date.strftime('%d.%m.%Y')}</b>")
        box.pack_start(title, False, False, 0)
        box.pack_start(sep(), False, False, 2)

        if not events:
            empty = Gtk.Label(label="Keine Termine")
            empty.get_style_context().add_class("caption")
            box.pack_start(empty, False, False, 0)
        else:
            for e in sorted(events, key=lambda e: e.get("start-time", "")):
                row = hbox(6)
                t = e.get("start-time", "")
                time_lbl = Gtk.Label(label=t if t else "–")
                time_lbl.get_style_context().add_class("caption")
                time_lbl.set_width_chars(5)
                title_lbl = Gtk.Label(label=e.get("title", "(ohne Titel)"))
                title_lbl.set_halign(Gtk.Align.START)
                title_lbl.set_line_wrap(True)
                title_lbl.set_max_width_chars(28)
                row.pack_start(time_lbl, False, False, 0)
                row.pack_start(title_lbl, True, True, 0)
                box.pack_start(row, False, False, 0)

        add_row = hbox(6)
        add_row.set_halign(Gtk.Align.END)
        add_btn = btn("+ Termin", cb=lambda _w: (pop.popdown(),
                      _prompt_new_event(day_date)))
        add_row.pack_start(add_btn, False, False, 0)
        box.pack_start(sep(), False, False, 2)
        box.pack_start(add_row, False, False, 0)

        pop.add(box)
        box.show_all()
        pop.popup()

    def _on_day_click(anchor_widget, day_date, ev, day_events_ref: list):
        """Linksklick (Button 1) -> Popover mit den Terminen dieses
        Tages zeigen, OHNE khal öffnen zu müssen (der häufigere Fall,
        deshalb auf dem primären Klick). Rechtsklick (Button 3) ->
        Termin anlegen. day_events_ref wird vom Async-Fetch in
        _build_grid() befüllt, sobald der khal-Aufruf für den Monat
        durch ist - vor dem ersten Laden zeigt das Popover entsprechend
        "Keine Termine" (korrekt, falls wirklich keine da sind) oder
        kurzzeitig veraltet leer, bis der Hintergrund-Fetch durch ist."""
        if ev.button == 1:
            _show_events_popover(anchor_widget, day_date, day_events_ref)
            return True  # Event als behandelt markieren
        elif ev.button == 3:
            _prompt_new_event(day_date)
            return True  # Event als behandelt markieren
        return False

    def _build_grid(year, month):
        for c in cal_grid.get_children(): cal_grid.remove(c)
        today = datetime.now()
        day_widgets = {}  # date_str -> (button, inner_box, events_ref) für async Nachtragen der Punkte/Termine

        for week in calendar.monthcalendar(year, month):
            week_row = hbox(2)
            week_row.set_halign(Gtk.Align.CENTER)
            for day in week:
                if day == 0:
                    b = hbox(0)
                    b.get_style_context().add_class("bubble")
                    b.get_style_context().add_class("item")
                    b.set_size_request(44, -1)
                    l = Gtk.Label(label="")
                    l.set_opacity(0)
                    l.set_size_request(44, -1)
                    b.pack_start(l, False, False, 0)
                    week_row.pack_start(b, False, False, 0)
                    continue

                is_today = (day == today.day and month == today.month
                            and year == today.year)
                day_date = date(year, month, day)
                cell_lbl = f"<b>{day}</b>" if is_today else str(day)

                # Klickbarer Tag statt reinem Label-in-Box:
                #   - Linksklick öffnet den Termin-Anlegen-Dialog
                #   - Rechtsklick zeigt ein Popover mit den Terminen
                #     dieses Tages, OHNE khal selbst öffnen zu müssen
                # Beides nur, wenn khal tatsächlich einsatzbereit ist
                # (installiert + konfiguriert), sonst bleibt der
                # Kalender ein reiner Anzeige-Kalender ohne Handler.
                b = Gtk.Button()
                b.get_style_context().add_class("bubble")
                b.get_style_context().add_class("item")
                b.set_size_request(44, -1)
                b.set_can_focus(False)
                b.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
                if is_today:
                    b.get_style_context().add_class("active")

                inner = vbox(0)
                l = Gtk.Label()
                l.set_markup(cell_lbl)
                l.set_size_request(44, -1)
                l.set_halign(Gtk.Align.CENTER)
                l.get_style_context().add_class("caption")
                inner.pack_start(l, False, False, 0)

                b.add(inner)
                if khal_ok:
                    day_events_ref = []  # wird beim Async-Fetch unten befüllt
                    b.connect("button-press-event",
                              lambda _w, ev, dd=day_date, evs=day_events_ref:
                                  _on_day_click(_w, dd, ev, evs))
                    day_widgets[day_date.strftime("%Y-%m-%d")] = (b, inner, day_events_ref)
                week_row.pack_start(b, False, False, 0)
            cal_grid.pack_start(week_row, False, False, 0)
        cal_grid.show_all()

        if not khal_ok:
            return

        # Termine NICHT synchron im GTK-Main-Thread abfragen - selbst
        # ein einzelner "khal list"-Aufruf für den ganzen Monat kann
        # bei einem großen .ics-Verzeichnis oder langsamer Disk spürbar
        # dauern. Grid steht also sofort (klickbar, ohne Punkte),
        # Termin-Punkte/Tooltips werden nachgetragen, sobald der
        # Hintergrund-Thread fertig ist - exakt das Muster, das
        # _load_weather() weiter unten für den Wetter-Load nutzt.
        def _fetch():
            month_events = _khal_events_for_month(year, month)
            def _apply():
                # Falls der Nutzer inzwischen weitergeblättert hat, ist
                # cal_grid schon neu aufgebaut (andere day_widgets) -
                # dann NICHT mehr in die (jetzt falsche) alte Widget-
                # Zuordnung schreiben.
                if cur[0] != year or cur[1] != month:
                    return
                for date_str, events in month_events.items():
                    widgets = day_widgets.get(date_str)
                    if not widgets or not events:
                        continue
                    btn_w, inner_w, events_ref = widgets
                    # In-place befüllen (extend, nicht Neuzuweisung) -
                    # der Klick-Handler hat bereits eine Closure auf
                    # GENAU DIESES Listen-Objekt (day_events_ref beim
                    # Bauen der Zelle), eine Neuzuweisung hier würde
                    # eine andere Liste erzeugen, die der Handler nie
                    # zu sehen bekäme.
                    events_ref.extend(events)
                    btn_w.get_style_context().add_class("has-events")
                    dot = Gtk.Label(label="•")
                    dot.get_style_context().add_class("caption")
                    dot.set_halign(Gtk.Align.CENTER)
                    dot.set_opacity(0.85)
                    inner_w.pack_start(dot, False, False, 0)
                    inner_w.show_all()
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
    return root

def build_clock(win: Gtk.Window):
    win.set_default_size(460, 1)
    win.add(_clock_content(win))

# ════════════════════════════════════════════════════════════
#  SETTINGS
# ════════════════════════════════════════════════════════════
BACKUP_DIR = Path(HOME) / ".config" / "wb-daemon" / "backups"

class PendingChange:
    __slots__ = ("key", "desc", "apply", "reset")
    def __init__(self, key: str, desc: str, apply_fn, reset_fn=None):
        self.key   = key
        self.desc  = desc
        self.apply = apply_fn
        self.reset = reset_fn

PENDING: dict[str, PendingChange] = {}
_apply_bar_refresh = [lambda: None]

def stage_change(key: str, desc: str, apply_fn, reset_fn=None) -> None:
    PENDING[key] = PendingChange(key, desc, apply_fn, reset_fn)
    _apply_bar_refresh[0]()

def unstage_change(key: str) -> None:
    PENDING.pop(key, None)
    _apply_bar_refresh[0]()

def backup_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (BACKUP_DIR / f"{path.name}.{stamp}.bak").write_bytes(path.read_bytes())
    except Exception:
        pass

def apply_all() -> list[str]:
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

def _build_settings_battery(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_akku_content(), True, True, 0)

def _hypr_lua_path() -> Path:
    return Path(HOME) / ".config" / "hypr" / "hyprland.lua"

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

    for mon in monitors:
        page.pack_start(bsec(mon.get("name", "?").upper()), False, False, 0)
        row = _build_monitor_row(mon, lua_path, win)
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

def _auto_scale_for_height(h: int) -> float:
    for max_h, sc in _HEIGHT_SCALE_TABLE:
        if h <= max_h:
            return sc
    return _DEFAULT_SCALE

def _build_monitor_row(mon: dict, lua_path: Path, win: Gtk.Window) -> Gtk.Box:
    name    = mon.get("name", "?")
    cur_res = f'{mon.get("width")}x{mon.get("height")}'
    cur_hz  = f'{mon.get("refreshRate", 0):.2f}'
    cur_scale = float(mon.get("scale", 1.0) or 1.0)
    modes   = _parse_modes(mon.get("availableModes", []))
    res_list = sorted(modes.keys(), key=lambda r: -int(r.split("x")[0]))

    CUSTOM_LABEL = "Custom…"

    res_combo = Gtk.ComboBoxText()
    res_combo.get_style_context().add_class("bubble")
    res_combo.get_style_context().add_class("item")
    res_combo.set_can_focus(False)
    for r in res_list:
        res_combo.append_text(r)
    res_combo.append_text(CUSTOM_LABEL)

    hz_combo = Gtk.ComboBoxText()
    hz_combo.get_style_context().add_class("bubble")
    hz_combo.get_style_context().add_class("item")
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
        scale_state["value"] = parsed
        scale_val_btn.set_label(f"{parsed:g}")
        _stage_always()

    scale_val_btn.connect("clicked", _on_scale_btn_clicked)

    def _on_scale_auto_toggle(_w):
        scale_val_btn.set_sensitive(not scale_auto_check.get_active())
        _stage_always()

    scale_auto_check.connect("toggled", _on_scale_auto_toggle)

    def _fill_hz(res: str, preselect: str = None):
        hz_combo.remove_all()
        hzs = sorted(set(modes.get(res, [])), key=lambda h: -float(h))
        for h in hzs:
            hz_combo.append_text(f"{h} Hz")
        hz_combo.append_text(CUSTOM_LABEL)
        if preselect in hzs:
            hz_combo.set_active(hzs.index(preselect))
        elif hzs:
            hz_combo.set_active(0)

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
        _stage_always()

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
        _stage_always()

    res_val_lbl.connect("clicked", lambda _w: _on_res_custom_selected())
    hz_val_lbl.connect("clicked", lambda _w: _on_hz_custom_selected())

    if cur_res in res_list:
        res_combo.set_active(res_list.index(cur_res))
    _fill_hz(cur_res if cur_res in res_list
             else (res_list[0] if res_list else ""), preselect=cur_hz)
    _update_custom_visibility()

    orig = [cur_res, cur_hz, cur_scale, True]

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
        pos_x = mon.get("x", 0)
        pos_y = mon.get("y", 0)
        scale = _resolve_scale(int(res.split("x")[1]))
        if scale is None:
            raise RuntimeError(
                "Invalid scale entered (must be a number > 0).")

        monitor_arg = f"{name},{mode},{pos_x}x{pos_y},{scale}"
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

        run_bg(["bash", "-c",
                "killall waybar; waybar; "
                "systemctl --user restart wb-autohide.service"])

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
                txt = txt[:m.start()] + new_block + txt[m.end():]
                lua_path.write_text(txt)

        orig[0], orig[1] = res, hz
        orig[2], orig[3] = scale, scale_auto_check.get_active()

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
        _update_custom_visibility()

    def _stage_always():
        _update_custom_visibility()
        res, hz = _resolve_res_hz()
        scale_txt = "auto" if scale_auto_check.get_active() else f"{scale_state['value']:g}"
        desc = f"{name}: {res or '?'}@{hz or '?'}Hz, scale={scale_txt}"
        stage_change(f"display.{name}", desc, _apply, _reset)

    def _on_res_change(_w):
        if res_combo.get_active_text() != CUSTOM_LABEL:
            _fill_hz(res_combo.get_active_text())
            _update_custom_visibility()
            _stage_always()
        else:
            _on_res_custom_selected()

    def _on_hz_change(_w):
        if hz_combo.get_active_text() != CUSTOM_LABEL:
            _update_custom_visibility()
            _stage_always()
        else:
            _on_hz_custom_selected()

    res_combo.connect("changed", _on_res_change)
    hz_combo.connect("changed", _on_hz_change)

    combos_row = hrow(res_combo, hz_combo, sp=8)
    custom_row = hrow(res_val_lbl, hz_val_lbl, sp=8)
    scale_row  = hrow(Gtk.Label(label="Scale:"), scale_val_btn,
                       scale_auto_check, sp=8)
    wrap = vbox(6)
    wrap.pack_start(combos_row, False, False, 0)
    wrap.pack_start(custom_row, False, False, 0)
    wrap.pack_start(scale_row, False, False, 0)
    wrap.pack_start(status_lbl, False, False, 0)
    return wrap

SETTINGS_CATEGORIES = [
    ("display",    "󰍹", "Display",       "Resolution, Framerate"),
    ("brightness", "󰃟", "Brightness",    "Screen, Keyboard RGB, Night Light"),
    ("audio",      "󰕾", "Audio",         "Volume, Devices, Apps"),
    ("network",    "󰤨", "Network",       "LAN, Wi-Fi, Mesh Connect"),
    ("bluetooth",  "󰂯", "Bluetooth",     "Pair & connect devices"),
    ("battery",    "󰁹", "Battery",       "Advanced power options"),
    ("calendar",   "󰃭", "Calendar",      "Weather, Time, Events"),
    ("appearance", "󰉼", "Appearance",    "Color scheme, Kvantum, nwg-look"),
    ("language",   "󰗊", "Language",      "System language"),
    ("apps",       "󱁤", "Apps & Editor", "Launcher editor, Config files"),
]

def _build_settings_brightness(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_brightness_content(win), True, True, 0)

def _build_settings_audio(page: Gtk.Box, key: str, label: str, win: Gtk.Window) -> None:
    page.pack_start(_volume_content(), True, True, 0)

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
}

def build_settings(win: Gtk.Window):
    win.set_default_size(380, 1)
    outer = vbox(0)

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.NONE)

    _reused_widget_categories = {"network", "battery", "audio", "bluetooth",
                                  "calendar", "brightness"}
    _cat_info = {ck: (icon, lbl, desc) for ck, icon, lbl, desc in SETTINGS_CATEGORIES}
    _built_pages: set = set()

    def _open_category(cat_key: str):
        if cat_key not in _built_pages:
            _built_pages.add(cat_key)
            icon, cat_label, cat_desc = _cat_info[cat_key]
            page = vbox(4); pad(page, h=10, v=8)
            back_row = hbox(6); back_row.set_halign(Gtk.Align.START)
            back_row.pack_start(
                btn("←  Back",
                    cb=lambda _b: stack.set_visible_child_name("hub")),
                False, False, 0)
            page.pack_start(back_row, False, False, 0)
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
        stack.set_visible_child_name(cat_key)

    hub = vbox(4); pad(hub, h=10, v=8)
    hub.pack_start(btitle("󰒓  Settings"), False, False, 0)
    hub.pack_start(sep(), False, False, 2)
    for cat_key, icon, cat_label, cat_desc in SETTINGS_CATEGORIES:
        hub.pack_start(
            _settings_category_row(
                icon, cat_label, cat_desc,
                lambda _b, k=cat_key: _open_category(k)),
            False, False, 0)
    stack.add_named(hub, "hub")

    outer.pack_start(stack, True, True, 0)
    outer.pack_start(sep(), False, False, 2)

    apply_bar = vbox(4); pad(apply_bar, h=10, v=6)
    status_lbl = Gtk.Label(label="No pending changes")
    status_lbl.get_style_context().add_class("caption")
    status_lbl.set_opacity(0.75)
    status_lbl.set_line_wrap(True)
    btn_row = hbox(6); btn_row.set_halign(Gtk.Align.CENTER)

    discard_b = btn("Discard")
    apply_b   = btn("✓  Apply")

    def _do_apply(_b):
        apply_b.set_sensitive(False)
        discard_b.set_sensitive(False)
        status_lbl.set_label("Applying…")
        def _done(errors):
            apply_b.set_sensitive(True)
            discard_b.set_sensitive(True)
            status_lbl.set_label(
                "Error: " + "; ".join(errors)[:140] if errors
                else "Applied ✓")
        apply_all_async(_done)

    def _do_discard(_b):
        discard_all()
        status_lbl.set_label("Discarded")

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
            status_lbl.set_label(f"{n} pending change{'s' if n != 1 else ''}: " +
                                  ", ".join(c.desc for c in PENDING.values())[:140])
        else:
            status_lbl.set_label("No pending changes")
        return False

    _apply_bar_refresh[0] = lambda: GLib.idle_add(_refresh_bar)
    _refresh_bar()

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
#  Unix Socket Server
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

def _print_cli_usage() -> None:
    print(
        "widgets_daemon.py [--set-weather \"<Location>\" | "
        "--set-weather-coords <lat> <lon> \"<Name>\" | "
        "--show-weather]\n"
        "Without arguments: starts the daemon (typically via systemd --user wb-daemon.service).",
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
