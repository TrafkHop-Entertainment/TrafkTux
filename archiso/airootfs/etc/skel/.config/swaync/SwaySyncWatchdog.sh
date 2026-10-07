#!/usr/bin/env bash
#
# SwaySyncWatchdog.sh — haelt swaync am Leben.
#
# Ersetzt den bisherigen direkten "swaync --replace --skip-system-css &"-
# Aufruf in hyprland.lua. Startet swaync und wartet BLOCKIEREND (kein
# Polling, also praktisch 0% CPU, solange swaync normal laeuft) auf sein
# Ende - egal ob Crash (z.B. der "double free or corruption"-Bug bei
# Notification-Spam) oder sauberes Beenden - und startet es danach sofort
# neu.
#
# "sleep 1" verhindert eine Crash-Restart-Endlosschleife (volle CPU-Last),
# falls swaync aus irgendeinem Grund bei JEDEM Start sofort wieder
# abstuerzt (z.B. kaputte config.json).
#
# SIGTERM/SIGINT an dieses Skript (z.B. beim Hyprland-Logout, analog zum
# "pkill -f 'OptionalSync.sh --watch'"-Muster) wird an das aktuell
# laufende swaync durchgereicht, statt es als Waisenprozess zurueckzulassen.
#
# Start (z.B. aus hyprland.lua statt des bisherigen swaync-Aufrufs):
#   setsid -f bash "$HOME/.config/swaync/SwaySyncWatchdog.sh" >/dev/null 2>&1 &
#
# Stop (z.B. vor einem manuellen Neustart):
#   pkill -f 'SwaySyncWatchdog.sh'

child_pid=""

cleanup() {
    [ -n "$child_pid" ] && kill "$child_pid" 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

while true; do
    swaync --replace --skip-system-css &
    child_pid=$!
    wait "$child_pid"
    sleep 1
done
