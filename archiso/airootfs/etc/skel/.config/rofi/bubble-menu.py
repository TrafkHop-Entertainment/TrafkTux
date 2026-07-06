#!/usr/bin/env python3
"""
bubble-menu.py — Generische Rofi Bubble-Menü-Engine
Verwendung:
  bubble-menu.py --menu launcher --path ""           # Wurzel
  bubble-menu.py --menu launcher --path "0"          # 1. Eintrag (Ordner)
  bubble-menu.py --menu launcher --path "0/2"        # Unterordner
  bubble-menu.py --menu powermenu                    # Power-Menü (immer flach)

Legt --menu im XDG-Config-Pfad ab:
  ~/.config/rofi/<menu>/menu.json
  ~/.config/rofi/<menu>/theme.rasi

Eingebaute Ordner-/Aktionstypen (im JSON per "type" gesetzt):
  folder               Untermenü (children rekursiv)
  app / action         exec ausführen
  close-prev-window    Fenster schließen, das beim Öffnen aktiv war
  special-drun         Custom App-Launcher (ersetzt `rofi -show drun`)
  special-run          Custom $PATH-Programmsuche (ersetzt `rofi -show run`)
  special-window       `rofi -show window` (Fenster-Switcher; eigener Modus,
                        wird daher weiterhin an Rofi selbst delegiert)

Zurück- und Exit-Einträge werden NICHT im JSON gepflegt, sondern automatisch
vom Skript in jede Ebene (inkl. Root und Powermenü) eingefügt — siehe
BACK_LABEL / EXIT_LABEL weiter unten.

Touch-Raster (appmenu / launcher):
  Jede Ebene wird als festes 5×3-Bubble-Raster dargestellt (siehe
  build_entries()). Spalte 1-4 zeigen den Inhalt (ggf. auf mehrere Seiten
  aufgeteilt), Spalte 5 immer Next Page / Last Page / Zurück-Exit. Auf der
  Wurzel des appmenu sind Spalte 1-3 zusätzlich als eigenes 3×3-Ordner-Raster
  reserviert (root_split=True), Spalte 4 für Other/Alle Apps/Programme.

Powermenü:
  Eigenes, nicht paginiertes 3-Spalten-Raster (build_powermenu_entries()) -
  die Kinder aus dem JSON plus ein automatisch mittig in einer neuen Zeile
  angehängtes Exit.
"""

import sys
import os
import json
import subprocess
import argparse
import configparser
import shlex

# WASD + Space als Navigations-Keys, zusätzlich zu Pfeiltasten/Enter (die
# weiterhin funktionieren). Wird an mehreren Stellen verwendet, an denen
# Rofi aufgerufen wird (run_rofi + der separate `-show window`-Aufruf).
WASD_KB_ARGS = [
    "-kb-row-up", "Up,Control+p,w",
    "-kb-row-down", "Down,Control+n,s",
    "-kb-row-left", "Control+Page_Up,a",
    "-kb-row-right", "Control+Page_Down,d",
    "-kb-accept-entry", "Control+j,Control+m,Return,KP_Enter,space",
]

ROFI_BASE        = os.path.expanduser("~/.config/rofi")
BACK_LABEL       = "← Zurück"
EXIT_LABEL       = "Exit"
EXIT_ICON        = "application-exit"
PREV_WINDOW_FILE = "/tmp/rofi-prev-window"

# Spezielle raw-Tokens für Steuer-Einträge (kollidieren nicht mit Kindindizes,
# da letztere immer reine Ziffern sind).
RAW_BACK = "BACK"
RAW_EXIT = "EXIT"
RAW_NEXT = "NEXT"
RAW_PREV = "PREV"
RAW_NOOP = "NOOP"   # Blindzelle (Füllzelle / deaktivierter Button), nicht auswählbar

# ─────────────────────────────────────────────
# Touch-Raster (appmenu / launcher)
# ─────────────────────────────────────────────
# Festes 5×3-Bubble-Raster:
#   Spalte 1-4 (3 Zeilen) = Inhalt der aktuellen Seite (bis zu 12 Kinder)
#   Spalte 5   (3 Zeilen) = Nächste Seite / Letzte Seite / Zurück-Exit
# Das zugehörige theme.rasi nutzt "flow: horizontal;", damit rofi die
# Einträge exakt in dieser Zeile-für-Zeile-Reihenfolge ins Raster setzt.
CONTENT_COLUMNS = 4
CONTENT_ROWS    = 3
PAGE_SIZE       = CONTENT_COLUMNS * CONTENT_ROWS  # 12

NEXT_LABEL = "Next Page"
NEXT_ICON  = "go-next"
PREV_LABEL = "Last Page"
PREV_ICON  = "go-previous"


# ─────────────────────────────────────────────
# JSON-Navigation
# ─────────────────────────────────────────────

def load_menu(menu_name: str) -> dict:
    path = os.path.join(ROFI_BASE, menu_name, "menu.json")
    with open(path) as f:
        return json.load(f)


def resolve_path(root: dict, path_str: str) -> dict:
    """Navigiert per Index-Pfad (z.B. '0/2/1') in den Baum."""
    node = root
    if not path_str:
        return node
    for idx_str in path_str.split("/"):
        idx = int(idx_str)
        node = node["children"][idx]
    return node


# ─────────────────────────────────────────────
# Rofi aufrufen
# ─────────────────────────────────────────────

def build_entries(node: dict, has_parent: bool, page: int = 0,
                   root_split: bool = False) -> list[tuple[str, str, str, bool]]:
    """
    Baut die Eintragsliste für eine Menü-Ebene des appmenu (launcher) als
    festes 5×3-Bubble-Raster:

      Spalte 1-4 (3 Zeilen): Inhalt der aktuellen Seite (Kinder von `node`,
                             ggf. auf mehrere Seiten aufgeteilt, mit
                             Blindzellen aufgefüllt).
      Spalte 5   (3 Zeilen): Nächste Seite / Letzte Seite / Zurück-Exit
                             (Exit nur in der Wurzel, sonst Zurück).

    Normalerweise (root_split=False) füllen sich die 4 Inhaltsspalten
    gleichmäßig zeilenweise (4 Zellen pro Zeile) - das nutzen Unterordner
    und die virtuellen Listen (Alle Apps/Programme).

    Mit root_split=True (nur für die Wurzel des appmenu) wird der Inhalt
    stattdessen in zwei Blöcke geteilt:
      - die ersten 9 Kinder → 3×3-Ordner-Raster in Spalte 1-3
      - die nächsten 3 Kinder → eigene Spalte 4 (aktuell: Other/Alle Apps/
        Programme)
    genau wie im Screenshot/Wunsch beschrieben.

    Jeder Eintrag ist ein 4-Tupel (Anzeigename, Icon, raw-Token, nonselectable).
    raw ist entweder der Kindindex als String (unverändert gegenüber vorher,
    also weiterhin direkt als Index in node["children"] nutzbar), oder
    RAW_NEXT/RAW_PREV/RAW_BACK/RAW_EXIT/RAW_NOOP.
    """
    children = node.get("children", [])
    total_pages = max(1, -(-len(children) // PAGE_SIZE))  # ceil-div
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    page_children = children[start:start + PAGE_SIZE]

    # -- Spalten 1-4: Inhalt dieser Seite, mit Blindzellen aufgefüllt --
    content: list[tuple[str, str, str, bool]] = []
    for i, child in enumerate(page_children):
        content.append((child.get("name", ""), child.get("icon", ""), str(start + i), False))
    while len(content) < PAGE_SIZE:
        content.append(("", "", RAW_NOOP, True))

    # -- Spalte 5: Nächste Seite / Letzte Seite / Zurück-Exit --
    has_next = page < total_pages - 1
    has_prev = page > 0

    nav_next = (NEXT_LABEL, NEXT_ICON, RAW_NEXT, False) if has_next else ("", "", RAW_NOOP, True)
    nav_prev = (PREV_LABEL, PREV_ICON, RAW_PREV, False) if has_prev else ("", "", RAW_NOOP, True)
    nav_back_exit = (
        (BACK_LABEL, "go-previous", RAW_BACK, False)
        if has_parent else
        (EXIT_LABEL, EXIT_ICON, RAW_EXIT, False)
    )
    nav_column = [nav_next, nav_prev, nav_back_exit]

    entries: list[tuple[str, str, str, bool]] = []
    if root_split:
        # Block 1: erste 9 Zellen -> 3x3-Ordner-Raster (Spalte 1-3)
        # Block 2: nächste 3 Zellen -> eigene Spalte 4
        block1 = content[0:9]
        block2 = content[9:12]
        for row in range(CONTENT_ROWS):
            entries.extend(block1[row * 3:(row + 1) * 3])
            entries.append(block2[row])
            entries.append(nav_column[row])
    else:
        # Gleichmäßig: 4 Inhaltszellen + 1 Nav-Zelle pro Zeile
        for row in range(CONTENT_ROWS):
            entries.extend(content[row * CONTENT_COLUMNS:(row + 1) * CONTENT_COLUMNS])
            entries.append(nav_column[row])
    return entries


def build_powermenu_entries(node: dict) -> list[tuple[str, str, str, bool]]:
    """
    Baut die Eintragsliste fürs Powermenü: die Kinder aus dem JSON in einem
    3-Spalten-Raster, plus ein automatisch angehängtes Exit, das mittig in
    einer neuen (bei 6 Kindern: 3.) Zeile sitzt — die beiden Nachbarzellen
    sind Blindzellen. Keine Pagination und kein Zurück, da das Powermenü
    laut Konzept immer flach ist (kein --path).
    """
    entries: list[tuple[str, str, str, bool]] = []
    for i, child in enumerate(node.get("children", [])):
        entries.append((child.get("name", ""), child.get("icon", ""), str(i), False))

    # Bis zum Zeilenende (3 Spalten) auffüllen, dann Exit mittig in die neue Zeile
    while len(entries) % 3 != 0:
        entries.append(("", "", RAW_NOOP, True))

    entries.append(("", "", RAW_NOOP, True))                  # links: leer
    entries.append((EXIT_LABEL, EXIT_ICON, RAW_EXIT, False))  # Mitte: Exit
    entries.append(("", "", RAW_NOOP, True))                  # rechts: leer

    return entries


def run_rofi(entries: list[tuple[str, str, str, bool]], theme_path: str,
             x11: bool = False) -> str | None:
    stdin_lines = []
    for display, icon, raw, nonselectable in entries:
        # Rofis dmenu-Zeilenerweiterung: "<text>\0key\x1fvalue\x1fkey2\x1fvalue2..."
        # (dieselbe Syntax wie im Script-Modus, siehe rofi-script(5)).
        extras = []
        if icon:
            extras += ["icon", icon]
        if nonselectable:
            extras += ["nonselectable", "true"]
        line = f"{display}\0" + "\x1f".join(extras) if extras else display
        stdin_lines.append(line)
    stdin_data = "\n".join(stdin_lines) + "\n"

    cmd = [
        "rofi",
        "-dmenu",
        "-format", "i",
        "-show-icons",
        "-theme", theme_path,
        "-no-custom",
        *WASD_KB_ARGS,
    ]
    # Bekannter Upstream-Bug: Rofis natives Wayland-Backend implementiert
    # kein wl_touch, Touch-Eingaben werden dort komplett ignoriert (Tap wie
    # Scroll). Über XWayland emuliert Hyprland für Fenster, die kein
    # Touch-Protokoll sprechen, Pointer-Events aus Touch - daher hier bei
    # Bedarf auf den xcb-Backend umschalten. Setzt voraus, dass Rofi mit
    # X11/xcb-Unterstützung gebaut ist (Standard bei den meisten Paketen,
    # inkl. rofi-wayland-Fork) und XWayland unter Hyprland läuft.
    if x11:
        cmd.append("-x11")

    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    return result.stdout.strip()


# ─────────────────────────────────────────────
# Custom App-Launcher (Ersatz für `rofi -show drun`)
# ─────────────────────────────────────────────
#
# Warum nicht einfach `-show drun`?
#  - drun ist ein eigener Rofi-Modus mit eigenem internen Listview-Setup.
#    Das Theme der Bubble-Menüs (feste Zellgröße, eigene Icon-Größe,
#    Bubble-Hintergrundgrafiken) wird dabei nicht zuverlässig übernommen.
#  - In drun lassen sich keine zusätzlichen Einträge (Zurück/Exit) einfügen,
#    da Rofi die Liste selbst aus den .desktop-Dateien generiert.
#
# Lösung: .desktop-Dateien selbst einlesen (Standard-XDG-Pfade) und als
# normale dmenu-Liste über dieselbe run_rofi()-Pipeline anzeigen. Die
# Icon-Namen werden 1:1 durchgereicht — Rofi löst Icon-Namen (im Gegensatz
# zu Pfaden) im -dmenu/-show-icons-Modus genau wie in drun über das aktive
# GTK-Icon-Theme auf, das Resultat ist also optisch identisch.

def _xdg_data_dirs() -> list[str]:
    dirs = [os.path.expanduser("~/.local/share")]
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        dirs.insert(0, xdg_data_home)
    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    dirs.extend(p for p in xdg_data_dirs.split(":") if p)
    # Reihenfolge erhalten, Duplikate raus
    seen = set()
    out = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _strip_exec_field_codes(exec_str: str) -> str:
    """Entfernt Desktop-Entry Feldcodes (%f %F %u %U %i %c %k ...), da wir
    nie Dateien/URIs übergeben. %% wird zu einem einzelnen %."""
    out = []
    i = 0
    while i < len(exec_str):
        ch = exec_str[i]
        if ch == "%" and i + 1 < len(exec_str):
            nxt = exec_str[i + 1]
            if nxt == "%":
                out.append("%")
                i += 2
                continue
            if nxt in "fFuUickdDnNvm":
                i += 2
                continue
        out.append(ch)
        i += 1
    return " ".join("".join(out).split())


def _current_desktop_names() -> set[str]:
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return {p.strip() for p in raw.split(":") if p.strip()}


def collect_desktop_apps() -> list[dict]:
    """Liest alle sichtbaren .desktop-Anwendungen ein, sortiert nach Name.
    Liefert Einträge im selben Format wie die JSON-Kinder (name/icon/exec)."""
    current_desktop = _current_desktop_names()
    seen_ids = set()
    apps = []

    for data_dir in _xdg_data_dirs():
        app_dir = os.path.join(data_dir, "applications")
        if not os.path.isdir(app_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(app_dir):
            for fname in filenames:
                if not fname.endswith(".desktop"):
                    continue
                full_path = os.path.join(dirpath, fname)
                # desktop-id nach XDG-Spec: Pfad relativ zu app_dir, "/" -> "-"
                rel = os.path.relpath(full_path, app_dir)
                desktop_id = rel.replace(os.sep, "-")
                if desktop_id in seen_ids:
                    continue  # höher priorisiertes Verzeichnis hat Vorrang

                cp = configparser.RawConfigParser(strict=False, interpolation=None)
                try:
                    cp.read(full_path, encoding="utf-8")
                except (OSError, configparser.Error):
                    continue

                if "Desktop Entry" not in cp:
                    continue
                entry = cp["Desktop Entry"]

                seen_ids.add(desktop_id)

                if entry.get("Type", "Application") != "Application":
                    continue
                if entry.getboolean("Hidden", fallback=False):
                    continue
                if entry.getboolean("NoDisplay", fallback=False):
                    continue

                only_show_in = entry.get("OnlyShowIn", "")
                if only_show_in:
                    allowed = {p.strip() for p in only_show_in.split(";") if p.strip()}
                    if current_desktop and not (allowed & current_desktop):
                        continue

                not_show_in = entry.get("NotShowIn", "")
                if not_show_in:
                    denied = {p.strip() for p in not_show_in.split(";") if p.strip()}
                    if current_desktop and (denied & current_desktop):
                        continue

                exec_raw = entry.get("Exec", "")
                if not exec_raw:
                    continue  # z.B. reine "NoExec" Meta-Einträge

                name = entry.get("Name", fallback=desktop_id)
                icon = entry.get("Icon", fallback="application-x-executable")
                exec_cmd = _strip_exec_field_codes(exec_raw)

                if entry.getboolean("Terminal", fallback=False):
                    exec_cmd = f"kitty {exec_cmd}"

                apps.append({
                    "name": name,
                    "icon": icon,
                    "exec": exec_cmd,
                    "type": "app",
                    "_sort_key": name.casefold(),
                })

    apps.sort(key=lambda a: a["_sort_key"])
    for a in apps:
        del a["_sort_key"]
    return apps


# ─────────────────────────────────────────────
# Custom Programmsuche (Ersatz für `rofi -show run`)
# ─────────────────────────────────────────────
#
# Gleiches Argument wie beim App-Launcher: `-show run` ist ein eigener Modus
# mit eigenem Theme-Verhalten und ohne Möglichkeit, Zurück/Exit einzufügen.
# Stattdessen wird $PATH selbst nach ausführbaren Dateien durchsucht.

def collect_path_binaries() -> list[dict]:
    """Scannt $PATH nach ausführbaren Dateien, dedupliziert nach Namen
    (erstes Vorkommen in PATH-Reihenfolge gewinnt, wie die Shell es tut)."""
    path_env = os.environ.get("PATH", "")
    seen_names = set()
    bins = []

    for directory in path_env.split(os.pathsep):
        if not directory or not os.path.isdir(directory):
            continue
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for fname in names:
            if fname in seen_names:
                continue
            full_path = os.path.join(directory, fname)
            if not os.path.isfile(full_path) or not os.access(full_path, os.X_OK):
                continue
            seen_names.add(fname)
            bins.append({
                "name": fname,
                "icon": "application-x-executable",
                "exec": shlex.quote(full_path),
                "type": "app",
            })

    bins.sort(key=lambda b: b["name"].casefold())
    return bins


# ─────────────────────────────────────────────
# Aktion ausführen
# ─────────────────────────────────────────────

def exec_detached(command: str):
    """Startet einen Shell-Befehl losgelöst vom Eltern-Prozess.
    Nur für statische, im JSON hinterlegte exec-Strings gedacht."""
    subprocess.Popen(
        command,
        shell=True,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def exec_detached_argv(argv: list[str]):
    """Wie exec_detached, aber ohne Shell — für Befehle mit dynamisch
    eingesetzten Werten (z.B. Fensteradressen, Lua-Dispatcher-Strings).
    Vermeidet jegliches Shell-Quoting-Risiko, da jedes Element 1:1 als
    eigenes Argv-Element an den Prozess übergeben wird."""
    subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cleanup():
    """Löscht die temporäre Fensterdatei."""
    if os.path.exists(PREV_WINDOW_FILE):
        os.remove(PREV_WINDOW_FILE)


def run_virtual_submenu(entries_data: list[dict], menu_name: str, theme_path: str,
                         has_parent: bool = True, x11: bool = False):
    """
    Zeigt eine 'virtuelle' Unterebene an, die NICHT aus dem JSON-Baum kommt
    (z.B. die dynamisch generierte App- oder Programmliste), aber dieselbe
    Zurück/Exit-Logik, dasselbe 5×3-Pagination-Raster und dieselbe
    Rofi-Pipeline nutzt wie der Rest des Menüs.

    Next/Last Page werden hier direkt in einer Schleife behandelt (kein
    os.execv nötig, da entries_data bereits im Speicher liegt). Bei Auswahl
    einer App/eines Programms wird die jeweilige exec-Zeile gestartet — es
    gibt keine weitere Verschachtelung, daher kein Pfad-Tracking nötig.
    """
    fake_node = {"children": entries_data}
    page = 0

    while True:
        entries = build_entries(fake_node, has_parent, page)

        chosen_raw = run_rofi(entries, theme_path, x11=x11)
        if chosen_raw is None:
            cleanup()
            sys.exit(0)

        chosen_idx = int(chosen_raw)
        _, _, raw, _ = entries[chosen_idx]

        if raw == RAW_EXIT:
            cleanup()
            sys.exit(0)

        if raw == RAW_BACK:
            # Zurück ins Hauptmenü (Wurzel) dieses --menu
            argv = [sys.executable, __file__, "--menu", menu_name, "--path", ""]
            if x11:
                argv.append("--x11")
            os.execv(sys.executable, argv)
            return

        if raw == RAW_NEXT:
            page += 1
            continue

        if raw == RAW_PREV:
            page -= 1
            continue

        if raw == RAW_NOOP:
            continue

        child = entries_data[int(raw)]
        exec_cmd = child.get("exec", "")
        cleanup()
        if exec_cmd:
            exec_detached(exec_cmd)
        sys.exit(0)


def handle_action(child: dict, menu_name: str, new_path: str, theme_path: str,
                   x11: bool = False):
    entry_type = child.get("type", "app")

    if entry_type == "folder":
        # Rekursiv in den Ordner navigieren (kein Cleanup hier!)
        argv = [sys.executable, __file__, "--menu", menu_name, "--path", new_path]
        if x11:
            argv.append("--x11")
        os.execv(sys.executable, argv)

    elif entry_type == "close-prev-window":
        # Adresse einlesen BEVOR cleanup() sie löscht
        addr = ""
        if os.path.exists(PREV_WINDOW_FILE):
            with open(PREV_WINDOW_FILE) as f:
                addr = f.read().strip()
        cleanup()
        if addr:
            # Aktueller Lua-Dispatcher (Hyprland >= 0.55): hl.dsp.window.close({ window = "..." }).
            # `addr` kommt unverändert aus `hyprctl activewindow -j` und enthält bereits das
            # 0x-Präfix, das der address:-Selector erwartet (siehe hyprctl-Doku).
            #
            # Bewusst address:<addr> statt class:/title:-Selektoren: Adressen sind pro
            # Fenster eindeutig, während class:-Matches bei mehreren offenen Fenstern
            # derselben Anwendung mehr als nur das gewünschte Fenster treffen können.
            #
            # WICHTIG: Wird NICHT über shell=True als ein gequoteter String zusammengebaut
            # (fragil bei verschachtelten Anführungszeichen), sondern direkt als eigenes
            # Argv-Element an hyprctl übergeben — exakt wie im offiziellen Beispiel
            # `hyprctl dispatch 'hl.dsp.window.tag({...})'`, nur ohne Shell dazwischen.
            lua_expr = "hl.dsp.window.close({ window = \"address:%s\" })" % addr
            exec_detached_argv(["hyprctl", "dispatch", lua_expr])

    elif entry_type == "special-drun":
        # Custom App-Launcher statt `rofi -show drun` (siehe Modul oben)
        apps = collect_desktop_apps()
        run_virtual_submenu(apps, menu_name, theme_path, x11=x11)

    elif entry_type == "special-run":
        # Custom $PATH-Suche statt `rofi -show run` (siehe Modul oben)
        bins = collect_path_binaries()
        run_virtual_submenu(bins, menu_name, theme_path, x11=x11)

    elif entry_type == "special-window":
        # Fenster-Switching bleibt am sinnvollsten Rofis eigener Modus,
        # da er Live-Fensterzustand (Titel, Workspace, Fokus) abbildet.
        cleanup()
        wasd_flags = " ".join(shlex.quote(a) for a in WASD_KB_ARGS)
        x11_flag = "-x11 " if x11 else ""
        exec_detached(f"rofi -show window {x11_flag}-theme {shlex.quote(theme_path)} {wasd_flags}")

    elif entry_type == "action":
        exec_cmd = child.get("exec", "")
        if exec_cmd:
            cleanup()
            exec_detached(exec_cmd)

    elif entry_type == "app":
        exec_cmd = child.get("exec", "")
        if exec_cmd:
            cleanup()
            exec_detached(exec_cmd)

    else:
        cleanup()
        sys.exit(0)


# ─────────────────────────────────────────────
# Hauptlogik
# ─────────────────────────────────────────────

def main():
    # Aktives Fenster nur beim ersten Aufruf speichern (nicht bei Unterordner-Navigation)
    if not os.path.exists(PREV_WINDOW_FILE):
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True
        )
        try:
            addr = json.loads(result.stdout).get("address", "")
            if addr:
                with open(PREV_WINDOW_FILE, "w") as f:
                    f.write(addr)
        except Exception:
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", required=True,
                        help="Menü-Name (=Unterordner in ~/.config/rofi/)")
    parser.add_argument("--path", default="",
                        help="Index-Pfad im JSON-Baum, z.B. '0/2/1'")
    parser.add_argument("--page", type=int, default=0,
                        help="Seiten-Index (0-basiert) im 5×3-Bubble-Raster "
                             "dieser Ebene, siehe RAW_NEXT/RAW_PREV.")
    parser.add_argument("--x11", action="store_true",
                        help="Rofi über XWayland statt nativem Wayland-Backend "
                             "starten. Umgeht einen Upstream-Bug, durch den "
                             "Rofis Wayland-Backend Touch-Eingaben komplett "
                             "ignoriert (kein wl_touch implementiert) - "
                             "Hyprland emuliert für XWayland-Fenster Pointer- "
                             "aus Touch-Events. Für Touch-Aufrufe (z.B. aus "
                             "einer hyprgrass-Geste) mitgeben, für normale "
                             "Tastatur-/Maus-Bindings kann das native Wayland-"
                             "Backend (ohne dieses Flag) bleiben.")
    args = parser.parse_args()

    menu_name  = args.menu
    path_str   = args.path
    page       = args.page
    x11        = args.x11
    theme_path = os.path.join(ROFI_BASE, menu_name, "theme.rasi")

    root = load_menu(menu_name)
    node = resolve_path(root, path_str)
    has_parent = bool(path_str)

    # Das Powermenü ist laut Konzept immer flach (kein --path) und bekommt
    # sein eigenes, nicht paginiertes 3-Spalten-Raster mit Exit mittig in
    # einer neuen Zeile. Alle anderen Menüs (z.B. der appmenu/launcher)
    # nutzen das generische, paginierte 5×3-Raster.
    if menu_name == "powermenu":
        entries = build_powermenu_entries(node)
    else:
        # root_split (9er-Ordner-Block + eigene 4. Spalte) gilt nur für die
        # Wurzel selbst (kein --path) - Unterordner nutzen das gleichmäßige
        # 4-Spalten-Raster.
        entries = build_entries(node, has_parent, page, root_split=not has_parent)

    chosen_raw = run_rofi(entries, theme_path, x11=x11)
    if chosen_raw is None:
        cleanup()
        sys.exit(0)

    chosen_idx = int(chosen_raw)
    chosen_entry = entries[chosen_idx]
    _, _, raw, _ = chosen_entry

    if raw == RAW_EXIT:
        cleanup()
        sys.exit(0)

    if raw == RAW_BACK:
        # Eine Ebene zurück (kein Cleanup — Fenster noch gebraucht). Seite
        # wird bewusst nicht mitgenommen, die Elternebene startet auf Seite 0.
        parent_path = "/".join(path_str.split("/")[:-1])
        argv = [sys.executable, __file__, "--menu", menu_name, "--path", parent_path]
        if x11:
            argv.append("--x11")
        os.execv(sys.executable, argv)
        return

    if raw == RAW_NEXT:
        argv = [sys.executable, __file__, "--menu", menu_name, "--path", path_str,
                 "--page", str(page + 1)]
        if x11:
            argv.append("--x11")
        os.execv(sys.executable, argv)
        return

    if raw == RAW_PREV:
        argv = [sys.executable, __file__, "--menu", menu_name, "--path", path_str,
                 "--page", str(page - 1)]
        if x11:
            argv.append("--x11")
        os.execv(sys.executable, argv)
        return

    if raw == RAW_NOOP:
        # Blindzelle - eigentlich über "nonselectable" gar nicht auswählbar,
        # sicherheitshalber aber einfach dieselbe Ebene neu anzeigen.
        argv = [sys.executable, __file__, "--menu", menu_name, "--path", path_str,
                 "--page", str(page)]
        if x11:
            argv.append("--x11")
        os.execv(sys.executable, argv)
        return

    child_idx = int(raw)
    child = node["children"][child_idx]
    new_path = (path_str + "/" + raw).lstrip("/")

    handle_action(child, menu_name, new_path, theme_path, x11=x11)


if __name__ == "__main__":
    main()
