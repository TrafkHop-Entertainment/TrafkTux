#!/usr/bin/env bash
# Wiimote-Suche beim Login: 5 Minuten lang, mit Benachrichtigung (Autostart.lua startet das einmal pro Login).
# Abschalten: Settings -> Apps -> Autostart -> "Wiimote search at login" (Schluessel wii_autoconnect in TrafkPad.conf).
DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$HOME/.config/TrafkTuxPad/TrafkPad.conf"
# Nur eine Instanz (Hyprland-Reload fuehrt den Autostart erneut aus)
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/wiimote-autoconnect.lock"
flock -n 9 || exit 0
# einmal pro Login: Marker im Runtime-Dir (verschwindet beim Logout)
MARK="${XDG_RUNTIME_DIR:-/tmp}/wiimote-autoconnect.done"
[ -e "$MARK" ] && exit 0
touch "$MARK"
grep -qiE '^[[:space:]]*wii_autoconnect[[:space:]]*=[[:space:]]*false' "$CONF" 2>/dev/null && exit 0
n() { command -v notify-send >/dev/null && notify-send -a TrafkPad -i input-gaming "$1" "$2"; }
n "Wiimote" "Looking for a Wiimote for 5 minutes - hold 1 + 2 to connect"
end=$((SECONDS + 300))
while [ $SECONDS -lt $end ]; do
    if bash "$DIR/wiimote-connect.sh" 25 >/dev/null 2>&1; then
        n "Wiimote" "Connected"
        exit 0
    fi
done
n "Wiimote" "Search finished - connect later in Settings → Devices"
