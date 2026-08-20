#!/usr/bin/env bash
#
# SoundCenter.sh — Trampolin, KEIN eigenständiges Skript mehr.
#
# Die komplette Logik steckt im kompilierten Binary "SoundControl" (siehe
# src/SoundControl.c). Diese Datei existiert nur noch als Aufruf-Punkt für
# bestehende Stellen, die bisher "bash .../soundctl.sh <event>" gerufen
# haben (hyprland.lua, widgets_daemon.py, RofiTrafkBubbleMenus.c, pip.sh) -
# siehe README.md, Abschnitt "Anpassungen an den Aufrufern", für die
# jeweils eine Zeile, die dort auf den neuen Dateinamen zeigen muss.
#
# "exec" statt normalem Aufruf: ersetzt diesen bash-Prozess durch das
# Binary (kein Extra-fork, gleiche PID). "SoundControl" wird über die
# reguläre Shell-$PATH-Suche gefunden - liegt also egal wo, Hauptsache im
# $PATH (siehe README.md, Abschnitt "Platzierung").
exec SoundControl "$@"
