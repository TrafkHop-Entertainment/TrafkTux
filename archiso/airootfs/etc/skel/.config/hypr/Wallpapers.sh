#!/usr/bin/env bash
#
# Wallpapers.sh
# Setzt beim Start ein zufälliges Wallpaper pro Hyprland-Monitor.
#
# Neue Ordnerstruktur:
#   ~/.config/hypr/Wallpapers/<ratio>/
#   Ratio-Keys: 11, 1610, 169, 219, 329, 43
#   Default/Fallback: 169
#
# Verifikation ohne Anwenden:
#   DRY_RUN=1 ~/.config/hypr/Wallpapers.sh
#
# Explizite Auswahl statt Zufall (siehe apply_image_to_monitor() unten):
#   ~/.config/hypr/Wallpapers.sh --set /pfad/zum/bild.jpg [MONITOR]

WALLPAPER_DIR="$HOME/.config/hypr/Wallpapers"
CHANNEL="xfce4-desktop"
DEFAULT_RATIO="169"
DRY_RUN="${DRY_RUN:-0}"

random_index() {
    local n="$1"
    local r
    r=$(od -An -N2 -tu2 < /dev/urandom | tr -d ' ')
    echo $(( r % n ))
}

pick_image() {
    local dir="$1"
    local -a imgs

    mapfile -t imgs < <(find "$dir" -maxdepth 1 -type f \( \
        -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \
    \) 2>/dev/null)

    [ "${#imgs[@]}" -eq 0 ] && return 1

    local idx
    idx=$(random_index "${#imgs[@]}")
    printf '%s\n' "${imgs[$idx]}"
}

ratio_key() {
    local w="$1" h="$2"

    awk -v w="$w" -v h="$h" '
    BEGIN {
        r = w / h

        # Key:Ratio
        n = split("11:1 1610:1.6 169:1.7777777778 219:2.3333333333 329:3.5555555556 43:1.3333333333", a, " ")

        best = "169"
        bestdiff = 999

        for (i = 1; i <= n; i++) {
            split(a[i], kv, ":")
            d = r - kv[2]
            if (d < 0) d = -d

            if (d < bestdiff) {
                bestdiff = d
                best = kv[1]
            }
        }

        # Wenn keine Ratio gut genug passt, Default verwenden
        if (bestdiff > 0.08) best = "169"

        print best
    }'
}

set_prop() {
    local path="$1" type="$2" value="$3"

    if xfconf-query -c "$CHANNEL" -p "$path" >/dev/null 2>&1; then
        xfconf-query -c "$CHANNEL" -p "$path" -s "$value"
    else
        xfconf-query -c "$CHANNEL" -p "$path" -n -t "$type" -s "$value"
    fi
}

apply_image_to_monitor() {
    local mon="$1" image="$2"
    local base="/backdrop/screen0/monitor${mon}/workspace0"
    set_prop "$base/last-image"  string "$image"
    set_prop "$base/image-style" int    5   # 5 = Vergrößert
    set_prop "$base/color-style" int    0   # 0 = Durchsichtig
}

# ─────────────────────────────────────────────────────────────────
# Explizite Auswahl (fürs Wallpapers-Tab in Appearance & Language):
#   Wallpapers.sh --set /pfad/zum/bild.jpg [MONITORNAME]
# Ohne MONITORNAME wird das Bild auf ALLE aktuell angeschlossenen
# Monitore gesetzt (identisches Bild überall); mit MONITORNAME nur auf
# den genannten (Name wie von "hyprctl monitors" gemeldet, z.B. "eDP-1",
# "HDMI-A-1"). Nutzt dieselbe apply_image_to_monitor()-Funktion wie der
# normale Zufalls-Durchlauf unten, damit beide Wege konsistent bleiben
# und ein manuell gesetztes Bild dieselben xfconf-Keys bekommt wie ein
# gewürfeltes.
if [ "${1:-}" = "--set" ]; then
    IMAGE="${2:-}"
    TARGET_MON="${3:-}"

    if [ -z "$IMAGE" ] || [ ! -f "$IMAGE" ]; then
        echo "Usage: Wallpapers.sh --set /path/to/image [MONITOR]" >&2
        exit 1
    fi

    if [ -n "$TARGET_MON" ]; then
        MONS=("$TARGET_MON")
    else
        mapfile -t MONS < <(hyprctl monitors -j | jq -r '.[].name')
    fi

    if [ "${#MONS[@]}" -eq 0 ]; then
        notify-send "Wallpaper" "Keine Monitore von hyprctl erhalten." 2>/dev/null
        exit 1
    fi

    for MON in "${MONS[@]}"; do
        apply_image_to_monitor "$MON" "$IMAGE"
    done

    killall xfdesktop 2>/dev/null || true
    sleep 1
    xfdesktop &
    exit 0
fi

# Monitore einlesen: name, width, height
mapfile -t MONITORS < <(
    hyprctl monitors -j | jq -r '.[] | [.name, (.width|tostring), (.height|tostring)] | @tsv'
)

if [ "${#MONITORS[@]}" -eq 0 ]; then
    notify-send "Wallpaper" "Keine Monitore von hyprctl erhalten." 2>/dev/null
    exit 1
fi

for line in "${MONITORS[@]}"; do
    IFS=$'\t' read -r MON W H <<< "$line"

    KEY=$(ratio_key "$W" "$H")
    SRC="$KEY"
    IMAGE=""

    if IMAGE="$(pick_image "$WALLPAPER_DIR/$KEY")"; then
        SRC="$KEY"
    elif [ "$KEY" != "$DEFAULT_RATIO" ] && IMAGE="$(pick_image "$WALLPAPER_DIR/$DEFAULT_RATIO")"; then
        SRC="$DEFAULT_RATIO"
    else
        notify-send "Wallpaper" "Kein Bild für $MON ($W x $H, Ratio $KEY) und Fallback $DEFAULT_RATIO leer." 2>/dev/null
        continue
    fi

    if [ "$DRY_RUN" = "1" ]; then
        echo "$MON: ${W}x${H} -> ratio $KEY -> source $SRC -> $IMAGE"
        continue
    fi

    apply_image_to_monitor "$MON" "$IMAGE"
done

if [ "$DRY_RUN" = "1" ]; then
    exit 0
fi

# xfdesktop neu starten, damit die neuen Keys sauber aufgelöst werden.
killall xfdesktop 2>/dev/null || true
sleep 1
xfdesktop &