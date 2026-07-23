#!/usr/bin/env python3
"""
bubble-menu.py — Generische Rofi Bubble-Menü-Engine
(Version als Rofi "Script Mode" — EIN dauerhaftes Rofi-Fenster,
 kein Neustart/Fenster-Zerstören mehr pro Seitenwechsel, daher
 auch keine hyprfocus-Animation mehr beim Blättern. Kein Daemon/FIFO
 mehr nötig, Rofi selbst hält den Prozess offen und ruft das Skript
 bei jeder Auswahl erneut auf; der Navigations-State (Pfad/Seite/
 Untermodus) wird dabei über ROFI_DATA transportiert.)
"""

import os
import json
import subprocess
import argparse
import configparser
import shlex
import time
import shutil

# --- Konstanten ---
ROFI_BASE        = os.path.expanduser("~/.config/rofi")
BACK_LABEL       = "← Zurück"
EXIT_LABEL       = "Exit"
EXIT_ICON        = "application-exit"
PREV_WINDOW_FILE = "/tmp/rofi-prev-window"

RAW_BACK = "BACK"
RAW_EXIT = "EXIT"
RAW_NEXT = "NEXT"
RAW_PREV = "PREV"
RAW_NOOP = "NOOP"

# Rofi Script-Mode: ROFI_RETV in der Umgebung sagt uns, WARUM das Skript
# gerade neu aufgerufen wurde. 1 = normale Auswahl (Enter/Klick).
# 10/11/12 = -kb-custom-1/2/3 (q/e/x) wurden gedrückt — exaktes Gegenstück
# zu den bisherigen Prozess-Exitcodes 10/11/12 im Dmenu-Modus.
RETV_SELECT   = "1"
RETV_CUSTOM_1 = "10"  # q -> PREV_PAGE
RETV_CUSTOM_2 = "11"  # e -> NEXT_PAGE
RETV_CUSTOM_3 = "12"  # x -> BACK_EXIT

CONTENT_COLUMNS = 4
CONTENT_ROWS    = 3
PAGE_SIZE       = CONTENT_COLUMNS * CONTENT_ROWS

NEXT_LABEL = "Next Page"
NEXT_ICON  = "go-next"
PREV_LABEL = "Last Page"
PREV_ICON  = "go-previous"

WASD_KB_ARGS = [
    "-kb-row-up", "Up,Control+p,w",
    "-kb-row-down", "Down,Control+n,s",
    "-kb-row-left", "Control+Page_Up,a",
    "-kb-row-right", "Control+Page_Down,d",
    "-kb-accept-entry", "Control+j,Control+m,Return,KP_Enter,space,less",
    "-kb-custom-1", "q",
    "-kb-custom-2", "e",
    "-kb-custom-3", "x",
]

_cached_desktop_apps = None
_cached_desktop_apps_ts = 0.0
_cached_path_binaries = None
_cached_path_binaries_ts = 0.0

# Wie lange der Scan-Cache für Desktop-Apps / PATH-Binaries gültig bleibt (Sekunden).
# Der Daemon läuft dauerhaft, daher braucht es einen Ablauf, damit neu installierte
# Programme automatisch auftauchen, ohne den Daemon manuell neu zu starten.
SCAN_CACHE_TTL = 180  # 3 Minuten

# --- Steam-Icon-Sync ---
# Steam schreibt in .desktop-Dateien "Icon=steam_icon_<appid>", installiert das
# passende Bild aber nur dann ins Icon-Theme (~/.local/share/icons/hicolor/...),
# wenn man im Steam-Client manuell "Desktop-Verknüpfung erstellen" klickt.
# Diese Funktion holt das fehlende Icon stattdessen automatisch aus Steams eigenem
# librarycache (dort liegt es als kleine quadratische Datei mit Hash-Namen, z.B.
# "80b57583....jpg", 32x32 groß) und installiert es selbst ins hicolor-Theme.
STEAM_ICON_SYNC_TTL   = 300  # alle 5 Minuten neu prüfen
STEAM_LIBRARYCACHE    = os.path.expanduser("~/.local/share/Steam/appcache/librarycache")
STEAM_ICON_TARGET_DIR = os.path.expanduser("~/.local/share/icons/hicolor/128x128/apps")
# Store-Artwork-Dateien, die NIE das App-Icon sind (auch wenn zufällig quadratisch)
_STEAM_ARTWORK_NAMES = {
    "header.jpg", "logo.png", "library_600x900.jpg",
    "library_hero.jpg", "library_hero_blur.jpg", "capsule_231x87.jpg",
    "capsule_616x353.jpg", "page_bg_raw.jpg", "page.bg.jpg",
}
_cached_steam_icon_sync_ts = 0.0

# --- JetBrains-Toolbox-Icon-Sync ---
# Toolbox erzeugt beim Anlegen/Aktualisieren einer .desktop-Datei ein SVG-Icon
# unter dotDesktopIcons/<desktop-id>.icon.svg, verlinkt/kopiert es aber (aus
# Gründen, z.B. abgebrochenes Update) nicht zuverlässig nach
# ~/.local/share/icons/hicolor/scalable/apps/<Icon-Name>.svg, worauf die
# .desktop-Datei via "Icon=" verweist. Diese Funktion holt das fehlende Icon
# automatisch aus dotDesktopIcons nach.
JETBRAINS_ICON_SYNC_TTL     = 300  # alle 5 Minuten neu prüfen
JETBRAINS_DOT_DESKTOP_ICONS = os.path.expanduser("~/.local/share/JetBrains/Toolbox/dotDesktopIcons")
JETBRAINS_ICON_TARGET_DIR   = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")
_cached_jetbrains_icon_sync_ts = 0.0

# --- Hilfsfunktionen ---

def load_menu(menu_name: str) -> dict:
    path = os.path.join(ROFI_BASE, menu_name, "menu.json")
    with open(path) as f:
        return json.load(f)

def resolve_path(root: dict, path_str: str) -> dict:
    node = root
    if not path_str:
        return node
    for idx_str in path_str.split("/"):
        idx = int(idx_str)
        node = node["children"][idx]
    return node

def exec_detached(command: str):
    subprocess.Popen(
        command,
        shell=True,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def exec_detached_argv(argv: list[str]):
    subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def cleanup():
    if os.path.exists(PREV_WINDOW_FILE):
        os.remove(PREV_WINDOW_FILE)

def save_active_window():
    """Schreibt die Adresse des aktuell aktiven Fensters in die temporäre Datei."""
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True
        )
        addr = json.loads(result.stdout).get("address", "")
        if addr:
            with open(PREV_WINDOW_FILE, "w") as f:
                f.write(addr)
    except Exception:
        pass

# --- Rofi-Aufruf & Eintragsbau ---

def build_entries(node: dict, has_parent: bool, page: int = 0,
                   root_split: bool = False) -> list[tuple[str, str, str, bool]]:
    children = node.get("children", [])
    total_pages = max(1, -(-len(children) // PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    page_children = children[start:start + PAGE_SIZE]

    content = []
    for i, child in enumerate(page_children):
        content.append((child.get("name", ""), child.get("icon", ""), str(start + i), False))
    while len(content) < PAGE_SIZE:
        content.append(("", "", RAW_NOOP, True))

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

    entries = []
    if root_split:
        block1 = content[0:9]
        block2 = content[9:12]
        for row in range(CONTENT_ROWS):
            entries.extend(block1[row * 3:(row + 1) * 3])
            entries.append(block2[row])
            entries.append(nav_column[row])
    else:
        for row in range(CONTENT_ROWS):
            entries.extend(content[row * CONTENT_COLUMNS:(row + 1) * CONTENT_COLUMNS])
            entries.append(nav_column[row])
    return entries

_WRAPPER_PREFIXES = ("kitty", "sudo")

def _extract_binary(exec_str: str) -> str:
    """Ermittelt den eigentlichen Programmnamen aus einem exec-String,
    unter Berücksichtigung gängiger Wrapper wie 'kitty', 'sudo' und 'bash -c \"...\"'."""
    s = exec_str.strip()
    if not s:
        return ""
    try:
        tokens = shlex.split(s)
    except ValueError:
        tokens = s.split()

    while tokens:
        head = tokens[0]
        if head == "bash" and len(tokens) >= 3 and tokens[1] == "-c":
            inner = tokens[2]
            try:
                tokens = shlex.split(inner)
            except ValueError:
                tokens = inner.split()
            continue
        if head in _WRAPPER_PREFIXES:
            tokens = tokens[1:]
            continue
        break

    if not tokens:
        return ""
    return os.path.basename(tokens[0])

def collect_used_identifiers(root: dict) -> tuple[set[str], set[str]]:
    """Sammelt rekursiv alle Namen und Binary-Namen von 'app'-Einträgen im
    Menübaum, um sie später aus 'Other Apps' herauszufiltern."""
    names: set[str] = set()
    execs: set[str] = set()

    def walk(node: dict):
        for child in node.get("children", []):
            if child.get("type") == "folder":
                walk(child)
            elif child.get("type") == "app":
                nm = child.get("name", "").strip().casefold()
                if nm:
                    names.add(nm)
                exec_bin = _extract_binary(child.get("exec", ""))
                if exec_bin:
                    execs.add(exec_bin.casefold())

    walk(root)
    return names, execs

def build_powermenu_entries(node: dict) -> list[tuple[str, str, str, bool]]:
    entries = []
    for i, child in enumerate(node.get("children", [])):
        entries.append((child.get("name", ""), child.get("icon", ""), str(i), False))
    entries.append((EXIT_LABEL, EXIT_ICON, RAW_EXIT, False))

    return entries

def emit_entries(entries: list[tuple[str, str, str, bool]], state: dict) -> None:
    """
    Schreibt die Eintragsliste im Rofi-Script-Mode-Format auf stdout und
    hängt den Navigations-State (Pfad/Seite/Untermodus) als ROFI_DATA-Zeile
    an. Rofi hält dabei sein EINES Fenster offen — kein neuer Prozess, kein
    Fenster-Schließen/Neuerzeugen, also auch kein hyprfocus-Trigger.

    Jede Zeile trägt zusätzlich ein "info"-Feld mit dem raw-Wert (Index /
    NEXT / PREV / BACK / EXIT / NOOP). Das Skript wertet beim nächsten
    Aufruf dieses info-Feld aus (über ROFI_INFO), nicht den sichtbaren Text
    — robust auch bei doppelten Namen.
    """
    # WICHTIG: Ohne diese beiden Steuerzeilen funktionieren die q/e/x
    # Custom-Keybindings NICHT — Rofi liefert ROFI_RETV=10-28 (unsere
    # kb-custom-1/2/3) im Script-Mode nur, wenn das Skript "use-hot-keys"
    # explizit freischaltet (siehe rofi-script(5)). no-custom sorgt dafür,
    # dass nur echte Listeneinträge ausgewählt werden können (kein
    # Freitext-Submit), analog zum alten "-no-custom" CLI-Flag.
    print("\0use-hot-keys\x1ftrue")
    print("\0no-custom\x1ftrue")

    for display, icon, raw, nonselectable in entries:
        extras = ["info", raw]
        if icon:
            extras += ["icon", icon]
        if nonselectable:
            extras += ["nonselectable", "true"]
        line = f"{display}\0" + "\x1f".join(extras)
        print(line)

    data_json = json.dumps(state, separators=(",", ":"))
    # \0data\x1f<json>\n ist Rofis eigenes Steuerprotokoll, um uns den State
    # beim nächsten Aufruf automatisch als ROFI_DATA-Umgebungsvariable
    # zurückzugeben — ganz ohne temporäre Dateien.
    print(f"\0data\x1f{data_json}")

# --- Desktop-Apps & PATH-Binaries (unverändert) ---

def _xdg_data_dirs() -> list[str]:
    dirs = [os.path.expanduser("~/.local/share")]
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        dirs.insert(0, xdg_data_home)
    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    dirs.extend(p for p in xdg_data_dirs.split(":") if p)
    seen = set()
    out = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out

def _strip_exec_field_codes(exec_str: str) -> str:
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

def _find_steam_desktop_icon_ids() -> set[str]:
    """Durchsucht alle .desktop-Dateien nach 'Icon=steam_icon_<appid>' Einträgen
    und liefert die Menge der appids zurück."""
    appids = set()
    for data_dir in _xdg_data_dirs():
        app_dir = os.path.join(data_dir, "applications")
        if not os.path.isdir(app_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(app_dir):
            for fname in filenames:
                if not fname.endswith(".desktop"):
                    continue
                full_path = os.path.join(dirpath, fname)
                cp = configparser.RawConfigParser(strict=False, interpolation=None)
                try:
                    cp.read(full_path, encoding="utf-8")
                except (OSError, configparser.Error):
                    continue
                if "Desktop Entry" not in cp:
                    continue
                icon = cp["Desktop Entry"].get("Icon", "")
                if icon.startswith("steam_icon_"):
                    appid = icon[len("steam_icon_"):]
                    if appid.isdigit():
                        appids.add(appid)
    return appids

def _icon_already_resolvable(icon_name: str) -> bool:
    """Prüft, ob rofi/GTK dieses Icon bereits irgendwo im Icon-Theme finden würde,
    ohne dass wir GTK selbst importieren müssen (das wäre eine zusätzliche
    Abhängigkeit) — wir schauen stattdessen direkt in den bekannten
    hicolor/Papirus-Verzeichnissen nach, ob eine Datei mit diesem Namen existiert."""
    search_dirs = [
        os.path.expanduser("~/.local/share/icons"),
        "/usr/share/icons",
    ]
    for base in search_dirs:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for fname in filenames:
                stem, _ext = os.path.splitext(fname)
                if stem == icon_name:
                    return True
    return False

def _find_steam_app_icon_source(appid: str) -> str | None:
    """Findet im Steam-librarycache für die gegebene appid die Datei, die das
    echte quadratische App-Icon ist (Hash-Dateiname, exakt quadratisch, nicht in
    der bekannten Artwork-Namensliste). Steam legt oft mehrere Auflösungen ab
    (z.B. 32x32 und größere Varianten) — wir nehmen die größte quadratische."""
    app_cache_dir = os.path.join(STEAM_LIBRARYCACHE, appid)
    if not os.path.isdir(app_cache_dir):
        return None

    best_path = None
    best_size = -1
    for fname in os.listdir(app_cache_dir):
        if fname in _STEAM_ARTWORK_NAMES:
            continue
        full_path = os.path.join(app_cache_dir, fname)
        if not os.path.isfile(full_path):
            continue
        try:
            result = subprocess.run(
                ["identify", "-format", "%w %h", full_path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            w_str, h_str = result.stdout.strip().split()
            w, h = int(w_str), int(h_str)
        except Exception:
            continue
        if w != h:
            continue  # nur echte (quadratische) Icons, kein Store-Artwork
        if w > best_size:
            best_size = w
            best_path = full_path
    return best_path

def sync_steam_icons() -> int:
    """Installiert fehlende steam_icon_<appid> Icons ins hicolor-Theme, indem das
    passende quadratische Bild aus Steams librarycache konvertiert/kopiert wird.
    Gibt die Anzahl neu installierter Icons zurück."""
    if not os.path.isdir(STEAM_LIBRARYCACHE):
        return 0

    appids = _find_steam_desktop_icon_ids()
    if not appids:
        return 0

    installed = 0
    cache_needs_update = False

    for appid in appids:
        icon_name = f"steam_icon_{appid}"
        if _icon_already_resolvable(icon_name):
            continue

        source = _find_steam_app_icon_source(appid)
        if not source:
            continue

        os.makedirs(STEAM_ICON_TARGET_DIR, exist_ok=True)
        target = os.path.join(STEAM_ICON_TARGET_DIR, f"{icon_name}.png")
        try:
            # Über ImageMagick nach PNG konvertieren, unabhängig vom Quellformat (jpg/png)
            result = subprocess.run(
                ["magick", source, target],
                capture_output=True, timeout=15,
            )
            if result.returncode != 0:
                continue
            installed += 1
            cache_needs_update = True
        except Exception:
            continue

    if cache_needs_update:
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-f", "-t",
                 os.path.expanduser("~/.local/share/icons/hicolor")],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass

    return installed

def maybe_sync_steam_icons(force: bool = False):
    """Führt sync_steam_icons() nur aus, wenn STEAM_ICON_SYNC_TTL seit dem letzten
    Lauf verstrichen ist (oder force=True), damit der Daemon nicht bei jedem
    Menü-Öffnen den ganzen librarycache durchsucht."""
    global _cached_steam_icon_sync_ts
    now = time.monotonic()
    if not force and (now - _cached_steam_icon_sync_ts) < STEAM_ICON_SYNC_TTL:
        return
    _cached_steam_icon_sync_ts = now
    try:
        n = sync_steam_icons()
        if n:
            print(f"[Steam-Icon-Sync] {n} neue(s) Icon(s) installiert.")
    except Exception as e:
        print(f"[Steam-Icon-Sync] Fehler: {e}")

def sync_jetbrains_icons() -> int:
    """Kopiert fehlende JetBrains-Toolbox-Icons aus dotDesktopIcons/ ins
    hicolor-Theme. Der Dateiname dort entspricht exakt <desktop-id>.icon.svg
    (siehe X-Icon-Name-Before-Sanitization in der .desktop-Datei), daher ist
    hier kein Rätselraten wie bei Steam nötig — nur ein direkter Dateiabgleich.
    Gibt die Anzahl neu installierter Icons zurück."""
    if not os.path.isdir(JETBRAINS_DOT_DESKTOP_ICONS):
        return 0

    installed = 0
    cache_needs_update = False

    for data_dir in _xdg_data_dirs():
        app_dir = os.path.join(data_dir, "applications")
        if not os.path.isdir(app_dir):
            continue
        for fname in os.listdir(app_dir):
            if not fname.startswith("jetbrains-") or not fname.endswith(".desktop"):
                continue
            full_path = os.path.join(app_dir, fname)
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                cp.read(full_path, encoding="utf-8")
            except (OSError, configparser.Error):
                continue
            if "Desktop Entry" not in cp:
                continue
            icon_name = cp["Desktop Entry"].get("Icon", "")
            if not icon_name:
                continue
            if _icon_already_resolvable(icon_name):
                continue

            source = os.path.join(JETBRAINS_DOT_DESKTOP_ICONS, f"{fname}.icon.svg")
            if not os.path.isfile(source):
                continue

            os.makedirs(JETBRAINS_ICON_TARGET_DIR, exist_ok=True)
            target = os.path.join(JETBRAINS_ICON_TARGET_DIR, f"{icon_name}.svg")
            try:
                shutil.copyfile(source, target)
                installed += 1
                cache_needs_update = True
            except OSError:
                continue

    if cache_needs_update:
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-f", "-t",
                 os.path.expanduser("~/.local/share/icons/hicolor")],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass

    return installed

def maybe_sync_jetbrains_icons(force: bool = False):
    """Führt sync_jetbrains_icons() nur aus, wenn JETBRAINS_ICON_SYNC_TTL seit
    dem letzten Lauf verstrichen ist (oder force=True)."""
    global _cached_jetbrains_icon_sync_ts
    now = time.monotonic()
    if not force and (now - _cached_jetbrains_icon_sync_ts) < JETBRAINS_ICON_SYNC_TTL:
        return
    _cached_jetbrains_icon_sync_ts = now
    try:
        n = sync_jetbrains_icons()
        if n:
            print(f"[JetBrains-Icon-Sync] {n} neue(s) Icon(s) installiert.")
    except Exception as e:
        print(f"[JetBrains-Icon-Sync] Fehler: {e}")

def collect_desktop_apps() -> list[dict]:
    global _cached_desktop_apps, _cached_desktop_apps_ts
    # Eigene TTLs, unabhängig vom Desktop-App-Cache-TTL, damit fehlende
    # Steam-/JetBrains-Icons auch dann synchronisiert werden, wenn der
    # Desktop-App-Cache selbst noch gültig ist (spätestens beim nächsten
    # Rescan werden sie dann sichtbar).
    maybe_sync_steam_icons()
    maybe_sync_jetbrains_icons()
    now = time.monotonic()
    if _cached_desktop_apps is not None and (now - _cached_desktop_apps_ts) < SCAN_CACHE_TTL:
        return _cached_desktop_apps
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
                rel = os.path.relpath(full_path, app_dir)
                desktop_id = rel.replace(os.sep, "-")
                if desktop_id in seen_ids:
                    continue
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
                    continue
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
    _cached_desktop_apps = apps
    _cached_desktop_apps_ts = now
    return apps

def collect_path_binaries() -> list[dict]:
    global _cached_path_binaries, _cached_path_binaries_ts
    now = time.monotonic()
    if _cached_path_binaries is not None and (now - _cached_path_binaries_ts) < SCAN_CACHE_TTL:
        return _cached_path_binaries
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
    _cached_path_binaries = bins
    _cached_path_binaries_ts = now
    return bins

# --- State-Maschine für Rofi Script Mode ---
#
# Statt einer blockierenden while-True-Schleife mit eigenem rofi-Subprozess
# pro Iteration (das alte Prinzip, das jedes Mal Rofis X11-Fenster zerstört
# und neu erzeugt hat -> hyprfocus-Flackern), macht dieser Teil jetzt GENAU
# EINEN Übergang pro Skript-Aufruf. Rofi selbst bleibt die ganze Zeit offen
# und ruft uns bei jeder Auswahl / jedem kb-custom-Tastendruck erneut auf.
#
# Der State wird zwischen den Aufrufen über ROFI_DATA (siehe emit_entries)
# transportiert. Struktur:
#   {"path": "<index/index/...>", "page": <int>,
#    "vmode": null | "drun" | "drun-filtered" | "run"}
# "vmode" markiert, dass wir gerade in einer virtuellen Liste (App-/Binary-
# Übersicht) stecken statt im echten Menübaum — das Gegenstück zum früheren
# separaten run_virtual_menu()-Prozess, jetzt aber im selben State-Automaten.

VMODE_DRUN          = "drun"
VMODE_DRUN_FILTERED = "drun-filtered"
VMODE_RUN           = "run"

def default_state() -> dict:
    return {"path": "", "page": 0, "vmode": None}

def build_virtual_entries_data(vmode: str, root: dict) -> list[dict]:
    """Liefert die Datenliste für einen virtuellen Modus (App-/Binary-Liste)."""
    if vmode == VMODE_DRUN:
        return collect_desktop_apps()
    if vmode == VMODE_DRUN_FILTERED:
        apps = collect_desktop_apps()
        used_names, used_execs = collect_used_identifiers(root)
        return [
            a for a in apps
            if a["name"].strip().casefold() not in used_names
            and _extract_binary(a.get("exec", "")).casefold() not in used_execs
        ]
    if vmode == VMODE_RUN:
        return collect_path_binaries()
    return []

def current_entries_for_state(menu_name: str, root: dict, state: dict) -> list[tuple[str, str, str, bool]]:
    """Baut die Eintragsliste, die dem aktuellen State entspricht (echter
    Menübaum ODER virtuelle Liste)."""
    vmode = state.get("vmode")
    page = state.get("page", 0)
    if vmode:
        entries_data = build_virtual_entries_data(vmode, root)
        fake_node = {"children": entries_data}
        return build_entries(fake_node, True, page)

    path_str = state.get("path", "")
    node = resolve_path(root, path_str)
    has_parent = bool(path_str)
    if menu_name == "powermenu":
        return build_powermenu_entries(node)
    return build_entries(node, has_parent, page, root_split=not has_parent)

def handle_step(menu_name: str, x11: bool, retv: str, info: str | None) -> None:
    """
    Wertet GENAU EINE Rofi-Interaktion aus (Auswahl oder kb-custom-Taste)
    und emittiert entweder die neue Eintragsliste (Menü bleibt offen) oder
    startet eine Aktion/App und gibt nichts aus (Rofi schließt sich dann
    von selbst, da keine neuen Zeilen kommen).
    """
    root = load_menu(menu_name)

    raw_state = os.environ.get("ROFI_DATA", "")
    try:
        state = json.loads(raw_state) if raw_state else default_state()
    except (ValueError, TypeError):
        state = default_state()
    # Fehlende Felder robust auffüllen (z.B. falls ROFI_DATA mal leer/kaputt ist)
    state = {**default_state(), **state}

    path_str = state["path"]
    page = state["page"]
    vmode = state["vmode"]

    def emit_current():
        entries = current_entries_for_state(menu_name, root, state)
        emit_entries(entries, state)

    # --- kb-custom Tasten (q/e/x) — exaktes Gegenstück zu den alten
    # Prozess-Exitcodes 10/11/12 im Dmenu-Modus ---
    if retv == RETV_CUSTOM_1:  # q -> vorherige Seite
        state["page"] = max(0, page - 1)
        emit_current()
        return

    if retv == RETV_CUSTOM_2:  # e -> nächste Seite
        if vmode:
            total = len(build_virtual_entries_data(vmode, root))
        else:
            node = resolve_path(root, path_str)
            total = len(node.get("children", []))
        total_pages = max(1, -(-total // PAGE_SIZE))
        state["page"] = min(total_pages - 1, page + 1)
        emit_current()
        return

    if retv == RETV_CUSTOM_3:  # x -> zurück/exit, seitenunabhängig
        if vmode:
            # virtuelle Listen haben immer einen Parent -> zurück ins Hauptmenü
            state["vmode"] = None
            state["page"] = 0
            emit_current()
            return
        if path_str:
            state["path"] = "/".join(path_str.split("/")[:-1])
            state["page"] = 0
            emit_current()
            return
        # kein Parent mehr -> wie Exit
        cleanup()
        return

    # --- Erstaufruf ohne Argument: Startliste anzeigen ---
    if info is None:
        emit_current()
        return

    # --- normale Auswahl (Enter/Klick) ---
    if info == RAW_EXIT:
        cleanup()
        return  # Rofi schließt sich (keine neue Ausgabe)
    if info == RAW_BACK:
        if vmode:
            state["vmode"] = None
        else:
            state["path"] = "/".join(path_str.split("/")[:-1])
        state["page"] = 0
        emit_current()
        return
    if info == RAW_NEXT:
        state["page"] = page + 1
        emit_current()
        return
    if info == RAW_PREV:
        state["page"] = page - 1
        emit_current()
        return
    if info == RAW_NOOP:
        # nonselectable Platzhalter — sollte eigentlich nie ausgewählt werden,
        # aber sicherheitshalber die aktuelle Liste einfach erneut anzeigen
        emit_current()
        return

    # --- Auswahl innerhalb einer virtuellen Liste (App/Binary starten) ---
    if vmode:
        entries_data = build_virtual_entries_data(vmode, root)
        child = entries_data[int(info)]
        exec_cmd = child.get("exec", "")
        if exec_cmd:
            exec_detached(exec_cmd)
            cleanup()
        return

    # --- Auswahl im echten Menübaum ---
    node = resolve_path(root, path_str)
    child_idx = int(info)
    child = node["children"][child_idx]
    entry_type = child.get("type", "app")

    if entry_type == "folder":
        state["path"] = (path_str + "/" + info).lstrip("/")
        state["page"] = 0
        emit_current()
        return

    if entry_type == "close-prev-window":
        addr = ""
        if os.path.exists(PREV_WINDOW_FILE):
            with open(PREV_WINDOW_FILE) as f:
                addr = f.read().strip()
        if addr:
            lua_expr = f"hl.dsp.window.close({{ window = \"address:{addr}\" }})"
            exec_detached_argv(["hyprctl", "dispatch", lua_expr])
        cleanup()
        return

    if entry_type == "special-drun":
        state["vmode"] = VMODE_DRUN
        state["page"] = 0
        emit_current()
        return

    if entry_type == "special-drun-filtered":
        state["vmode"] = VMODE_DRUN_FILTERED
        state["page"] = 0
        emit_current()
        return

    if entry_type == "special-run":
        state["vmode"] = VMODE_RUN
        state["page"] = 0
        emit_current()
        return

    if entry_type == "special-window":
        # Window-Liste ändert sich laufend (offene Fenster) — dafür bleibt es
        # ein eigener, unabhängiger rofi-Prozess statt Teil des State-Baums.
        wasd_flags = " ".join(shlex.quote(a) for a in WASD_KB_ARGS)
        x11_flag = "-x11 " if x11 else ""
        theme_path = os.path.join(ROFI_BASE, menu_name, "theme.rasi")
        exec_detached(f"rofi -show window {x11_flag}-theme {shlex.quote(theme_path)} {wasd_flags}")
        cleanup()
        return

    if entry_type in ("action", "app"):
        exec_cmd = child.get("exec", "")
        if exec_cmd:
            exec_detached(exec_cmd)
            cleanup()
        return

    # Fallback: nichts ausgeben -> Rofi schließt sich
    cleanup()

# --- Hauptprogramm ---
#
# Aufruf als Rofi Script-Mode-Backend:
#   rofi -show bubble -modi "bubble:python3 ~/.config/rofi/bubble-menu.py --menu launcher --x11"
#
# Rofi ruft dieses Skript für JEDE Interaktion neu auf (das ist sehr schnell,
# reiner Python-Start + State-Auswertung, kein neues X11-Fenster). Dabei
# bekommen wir mit:
#   - sys.argv[1]           : gewählter sichtbarer Text (wir nutzen das NICHT
#                              zur Auswertung, siehe ROFI_INFO unten)
#   - ROFI_INFO (Umgebung)  : das "info"-Feld des gewählten Eintrags — das
#                              werten wir aus (robust, unabhängig vom Text)
#   - ROFI_RETV (Umgebung)  : 1 = normale Auswahl, 10/11/12 = kb-custom-1/2/3
#   - ROFI_DATA (Umgebung)  : unser eigener State von der letzten Ausgabe
#
# Da Rofi durchgehend offen bleibt, entfällt der bisherige Daemon/FIFO-
# Mechanismus komplett — Hyprland ruft jetzt direkt "rofi -show bubble ..."
# auf, kein Trigger-Skript mehr nötig.

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", required=True,
                        help="Menü-Name (Unterordner in ~/.config/rofi/)")
    parser.add_argument("--x11", action="store_true",
                        help="Rofi über XWayland starten (Touch-Unterstützung), "
                             "wird an special-window-Untermenüs weitergereicht")
    # WICHTIG: Rofi hängt bei jeder Auswahl den sichtbaren Text des gewählten
    # Eintrags als zusätzliches Argument an (sys.argv[1]). Wir werten diesen
    # Text NICHT aus (siehe ROFI_INFO/ROFI_DATA weiter unten), aber argparse
    # muss ihn trotzdem ignorieren dürfen, statt mit "unrecognized arguments"
    # abzubrechen. Deshalb parse_known_args() statt parse_args().
    args, _unknown = parser.parse_known_args()

    retv = os.environ.get("ROFI_RETV", "")
    info = os.environ.get("ROFI_INFO")  # None beim allerersten Aufruf (kein Eintrag gewählt)

    # Beim allerersten Aufruf (Menü geht gerade erst auf) einmalig das zuvor
    # aktive Fenster merken, für "close-prev-window"-Einträge. WICHTIG: Laut
    # rofi-script(5) ist ROFI_RETV beim Erstaufruf "0" (nicht leer!) — das
    # war zuvor falsch geprüft, wodurch save_active_window() nie lief und
    # "close-prev-window" (der Close-Eintrag im Powermenü) folgenlos blieb.
    if info is None and retv in ("0", ""):
        save_active_window()

    handle_step(args.menu, args.x11, retv, info)

if __name__ == "__main__":
    main()
