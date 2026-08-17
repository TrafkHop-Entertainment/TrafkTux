#!/usr/bin/env bash
#
# random_wallpaper.sh
# Wählt beim Start ein zufälliges Bild aus WALLPAPER_DIR und setzt es
# als xfdesktop-Hintergrund für ALLE aktuell von Hyprland gemeldeten
# Monitore - über die monitor<OUTPUTNAME>-Keys (z.B. monitoreDP-1)
# statt der kaputten monitor0xHASH-Keys.
#
# Hintergrund: xfdesktop bildet unter Wayland normalerweise einen
# Hash aus dem Output (monitor0x20A7 etc.), kann diesen Hash beim
# Rendern aber nicht zuverlässig auf ein gültiges Workspace-Objekt
# abbilden, wenn der Compositor ext_workspace_manager_v1 nicht so
# unterstützt, wie libxfce4windowing es erwartet (siehe xfdesktop
# GitLab-Issue #350, unter Hyprland reproduzierbar via
# xfw_workspace_get_number-Assertion). Das Setzen des Bildes über
# den echten Output-Namen als Key umgeht das zuverlässig.
#
# Kein Wechsel während der Laufzeit - nur einmal beim Aufruf
# (z.B. Systemstart / Hyprland-Autostart).

WALLPAPER_DIR="$HOME/.config/hypr/wallpapers"
CHANNEL="xfce4-desktop"

# Zufälliges Bild auswählen (jpg, jpeg, png, webp)
mapfile -t IMAGES < <(find "$WALLPAPER_DIR" -maxdepth 1 -type f \( \
    -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \
\) 2>/dev/null)

if [ "${#IMAGES[@]}" -eq 0 ]; then
    notify-send "Wallpaper" "Kein Bild in $WALLPAPER_DIR gefunden." 2>/dev/null
    exit 1
fi

RANDOM=$(od -An -N2 -tu2 < /dev/urandom | tr -d ' ')
IMAGE="${IMAGES[$RANDOM % ${#IMAGES[@]}]}"

# Alle aktuell verbundenen Outputs von Hyprland abfragen
mapfile -t MONITORS < <(hyprctl monitors -j | jq -r '.[].name')

if [ "${#MONITORS[@]}" -eq 0 ]; then
    notify-send "Wallpaper" "Keine Monitore von hyprctl erhalten." 2>/dev/null
    exit 1
fi

# Setzt eine xfconf-Property; legt sie an falls sie noch nicht existiert.
set_prop() {
    local path="$1" type="$2" value="$3"
    if xfconf-query -c "$CHANNEL" -p "$path" >/dev/null 2>&1; then
        xfconf-query -c "$CHANNEL" -p "$path" -s "$value"
    else
        xfconf-query -c "$CHANNEL" -p "$path" -n -t "$type" -s "$value"
    fi
}

for MON in "${MONITORS[@]}"; do
    BASE="/backdrop/screen0/monitor${MON}/workspace0"
    set_prop "$BASE/last-image"  string "$IMAGE"
    set_prop "$BASE/image-style" int    5   # 5 = Vergrößert (siehe Screenshot-Stil)
    set_prop "$BASE/color-style" int    0   # 0 = Durchsichtig
done

# xfdesktop neu starten, damit der/die neuen Keys sauber (neu)
# aufgelöst werden - ein reines xfconf-Update genügt bei den
# kaputten Workspace-Objekten unter Hyprland nicht zuverlässig.
killall xfdesktop 2>/dev/null
sleep 1
xfdesktop &