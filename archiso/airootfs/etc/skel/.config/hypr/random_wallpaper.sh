#!/usr/bin/env bash
#
# random_wallpaper.sh
# Wählt beim Start ein zufälliges Bild aus WALLPAPER_DIR, schreibt eine
# temporäre hyprpaper.conf und startet hyprpaper damit. Kein Wechsel
# während der Laufzeit - nur einmal beim Aufruf (z.B. Systemstart).

WALLPAPER_DIR="$HOME/.config/hypr/wallpapers"
HYPRPAPER_CONF="$HOME/.config/hypr/hyprpaper.conf"

# Falls hyprpaper schon läuft (z.B. nach Reload), erst beenden,
# damit kein doppelter Prozess hängen bleibt.
pkill -x hyprpaper 2>/dev/null

# Zufälliges Bild auswählen (jpg, jpeg, png, webp)
mapfile -t IMAGES < <(find "$WALLPAPER_DIR" -maxdepth 1 -type f \( \
    -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \
\) 2>/dev/null)

if [ "${#IMAGES[@]}" -eq 0 ]; then
    notify-send "Wallpaper" "Kein Bild in $WALLPAPER_DIR gefunden." 2>/dev/null
    exit 1
fi

RANDOM_IMAGE="${IMAGES[$RANDOM % ${#IMAGES[@]}]}"

# hyprpaper.conf neu schreiben mit dem gewählten Bild
cat > "$HYPRPAPER_CONF" <<EOF
preload = $RANDOM_IMAGE

wallpaper {
    monitor = eDP-1
    path = $RANDOM_IMAGE
    fit_mode = cover
}

splash = false
EOF

hyprpaper &
