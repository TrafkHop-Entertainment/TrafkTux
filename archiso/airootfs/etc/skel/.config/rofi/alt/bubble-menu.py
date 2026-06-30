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
"""

import sys
import os
import json
import subprocess
import argparse

ROFI_BASE        = os.path.expanduser("~/.config/rofi")
BACK_LABEL       = "← Zurück"
ALL_APPS_LABEL   = "All Apps"
ALL_PKGS_LABEL   = "App Packages"
PREV_WINDOW_FILE = "/tmp/rofi-prev-window"


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

def build_entries(node: dict, has_parent: bool) -> list[tuple[str, str, str]]:
    entries = []
    if has_parent:
        entries.append((BACK_LABEL, "go-previous", "BACK"))
    for i, child in enumerate(node.get("children", [])):
        name = child.get("name", "")
        icon = child.get("icon", "")
        entries.append((name, icon, str(i)))
    return entries


def run_rofi(entries: list[tuple[str, str, str]], theme_path: str) -> str | None:
    stdin_lines = []
    for display, icon, raw in entries:
        if icon:
            line = f"{display}\0icon\x1f{icon}"
        else:
            line = display
        stdin_lines.append(line)
    stdin_data = "\n".join(stdin_lines) + "\n"

    cmd = [
        "rofi",
        "-dmenu",
        "-format", "i",
        "-show-icons",
        "-theme", theme_path,
        "-no-custom",
    ]

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
# Aktion ausführen
# ─────────────────────────────────────────────

def exec_detached(command: str):
    """Startet Befehl losgelöst vom Eltern-Prozess."""
    subprocess.Popen(
        command,
        shell=True,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cleanup():
    """Löscht die temporäre Fensterdatei."""
    if os.path.exists(PREV_WINDOW_FILE):
        os.remove(PREV_WINDOW_FILE)


def handle_action(child: dict, menu_name: str, new_path: str, theme_path: str):
    entry_type = child.get("type", "app")

    if entry_type == "folder":
        # Rekursiv in den Ordner navigieren (kein Cleanup hier!)
        os.execv(sys.executable, [
            sys.executable, __file__,
            "--menu", menu_name,
            "--path", new_path,
        ])

    elif entry_type == "close-prev-window":
        # Adresse einlesen BEVOR cleanup() sie löscht
        addr = ""
        if os.path.exists(PREV_WINDOW_FILE):
            with open(PREV_WINDOW_FILE) as f:
                addr = f.read().strip()
        cleanup()
        if addr:
            exec_detached(f"hyprctl dispatch \"hl.dsp.window.close({{ window = 'address:{addr}' }})\"")

    elif entry_type == "special-drun":
        cleanup()
        exec_detached(f"rofi -show drun -theme {theme_path}")

    elif entry_type == "special-run":
        cleanup()
        exec_detached(f"rofi -show run -theme {theme_path}")

    elif entry_type == "special-window":
        cleanup()
        exec_detached(f"rofi -show window -theme {theme_path}")

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
    args = parser.parse_args()

    menu_name  = args.menu
    path_str   = args.path
    theme_path = os.path.join(ROFI_BASE, menu_name, "theme.rasi")

    root = load_menu(menu_name)
    node = resolve_path(root, path_str)
    has_parent = bool(path_str)

    entries = build_entries(node, has_parent)
    if not entries:
        cleanup()
        sys.exit(0)

    chosen_raw = run_rofi(entries, theme_path)
    if chosen_raw is None:
        cleanup()
        sys.exit(0)

    chosen_idx = int(chosen_raw)
    chosen_entry = entries[chosen_idx]
    _, _, raw = chosen_entry

    if raw == "BACK":
        # Eine Ebene zurück (kein Cleanup — Fenster noch gebraucht)
        parent_path = "/".join(path_str.split("/")[:-1])
        os.execv(sys.executable, [
            sys.executable, __file__,
            "--menu", menu_name,
            "--path", parent_path,
        ])
        return

    child_idx = int(raw)
    child = node["children"][child_idx]
    new_path = (path_str + "/" + raw).lstrip("/")

    handle_action(child, menu_name, new_path, theme_path)


if __name__ == "__main__":
    main()
