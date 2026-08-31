#!/usr/bin/env bash
#
# SoundCenter.sh — Trampolin, KEIN eigenständiges Skript mehr.
#
# Die komplette Logik steckt im kompilierten Binary "SoundControl" (siehe
# src/SoundControl.c). Diese Datei existiert nur noch als Aufruf-Punkt für
# bestehende Stellen, die "bash .../SoundCenter.sh <event>" rufen
# (hyprland.lua, WidgetsDaemon.py, RofiTrafkBubbleMenus.c,
# PictureInPicture.sh, LayoutSwitcher.sh, HideAll.sh).
#
# WICHTIG: löst "SoundControl" relativ zu SEINEM EIGENEN Speicherort auf,
# NICHT über $PATH. Grund: ein "exec SoundControl" auf $PATH-Basis ist
# genau dann gescheitert, wenn der Ordner (bei dir ~/.config/hypr) nicht
# in $PATH steht - lautlos, weil der Aufruf per "&" im Hintergrund lief.
# Diese Version funktioniert unabhängig von $PATH, solange SoundControl
# im selben Verzeichnis wie diese Datei liegt (bei dir der Fall).
#
# Reine Parameter-Expansion, KEIN dirname/cd/pwd-Subshell - keine
# zusätzlichen forks. Gerade jetzt, wo's um Mikrosekunden geht, soll hier
# nichts Vermeidbares mehr rumliegen.
SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
[ "$SCRIPT_DIR" = "${BASH_SOURCE[0]}" ] && SCRIPT_DIR="."
exec "$SCRIPT_DIR/SoundControl" "$@"
