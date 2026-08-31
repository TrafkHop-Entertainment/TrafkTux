#!/usr/bin/env bash
# SoundCenterNotify.sh — wird von swaync bei jeder Notification aufgerufen
# (siehe config.json: "scripts" -> "sound-center", Match-Kriterium
# "app-name": ".*" fängt praktisch alles ab, da fast jede App irgendeinen
# App-Namen setzt).
#
# SwayNC reicht Infos über SWAYNC_*-Env-Variablen durch (SWAYNC_APP_NAME,
# SWAYNC_SUMMARY, SWAYNC_URGENCY, ...) - anders benannt als Dunsts
# DUNST_*-Variablen, brauchen wir hier aber ohnehin nicht: es soll bewusst
# einfach heißen "irgendeine Notification kam rein" -> Sound, unabhängig
# vom Inhalt.
bash "$HOME/.config/hypr/SoundCenter.sh" Dunst &
