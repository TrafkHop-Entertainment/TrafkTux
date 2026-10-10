#!/usr/bin/env bash
#
# Wallpapers.sh
# Setzt beim Start ein zufälliges Wallpaper pro Hyprland-Monitor.
#
# ─────────────────────────────────────────────────────────────────
# UMBAU (siehe Chat): xfdesktop kann auf diesem System aus bisher
# ungeklärten Gründen auf externen Monitoren unter Hyprland/Wayland
# KEIN Hintergrundbild mehr zeichnen - und zwar nicht nur über dieses
# Skript, sondern nachweislich auch über die offizielle
# xfce4-desktop-Settings-GUI selbst (dort geht's inzwischen auf GAR
# keinem Monitor mehr, nicht mal intern). Property-Zuordnung
# (xfconf-Keys pro Monitor) war die ganze Zeit korrekt - das Problem
# sitzt tiefer in xfdesktop selbst (passt zur Warnung
# "Window<->Workspace association is not available on your
# compositor" - xfdesktop läuft unter Hyprland in einem
# Kompatibilitäts-/Degraded-Modus).
#
# Daher: das eigentliche Hintergrundbild kommt jetzt von hyprpaper
# (Hyprlands eigener, nativer Wallpaper-Daemon - gebaut genau für
# Multi-Monitor-Wayland, kein X11-Kompatibilitätsgedöns). xfdesktop
# bleibt parallel aktiv, aber NUR noch für die Desktop-Icons - sein
# eigener Hintergrund wird auf "kein Bild" + "durchsichtig" gesetzt
# (ensure_xfdesktop_transparent()), damit hyprpapers Layer darunter
# sichtbar durchscheint. Netter Nebeneffekt: kein `killall xfdesktop`
# mehr nötig -> kein Schwarz-Flackern mehr beim Rerollen.
#
# Voraussetzung: hyprpaper ist installiert und läuft (per systemd-User-
# Service oder exec-once in hyprland.lua) - dieses Skript versucht es
# notfalls selbst zu starten, falls es (noch) nicht läuft.
# ─────────────────────────────────────────────────────────────────
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
#
# Diagnose der Monitor->xfconf-Zuordnung (nur noch relevant fürs
# Icon-Layer/die Transparenz, nicht mehr fürs Bild selbst):
#   ~/.config/hypr/Wallpapers.sh --debug-monitors

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

# ─────────────────────────────────────────────────────────────────
# Nur noch fürs Icon-Layer relevant: xfdesktop soll pro Monitor KEIN
# eigenes Bild mehr zeichnen und durchsichtig bleiben, damit hyprpaper
# darunter sichtbar ist. Schreibt defensiv auf BEIDE denkbaren
# xfconf-Pfad-Varianten (Connector-Name UND GDK-Modellname, siehe
# discover_xfconf_monitor_map/resolve_xfkeys) - welche davon diese
# xfdesktop-Version tatsächlich für die Icon-Platzierung nutzt, ist
# unklar, schadet aber nicht, beide zu pflegen.
# ─────────────────────────────────────────────────────────────────
declare -gA XFKEY_FOR_MON=()

discover_xfconf_monitor_map() {
    local -a hypr_lines gdk_lines
    mapfile -t hypr_lines < <(
        hyprctl monitors -j 2>/dev/null \
            | jq -r '.[] | [.name, (.x|tostring), (.y|tostring), (.width|tostring), (.height|tostring)] | @tsv'
    )
    [ "${#hypr_lines[@]}" -eq 0 ] && return 1

    mapfile -t gdk_lines < <(python3 - <<'PYEOF' 2>/dev/null
import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
d = Gdk.Display.get_default()
if d is None:
    raise SystemExit(1)
for i in range(d.get_n_monitors()):
    m = d.get_monitor(i)
    g = m.get_geometry()
    model = (m.get_model() or "").strip()
    print(f"{g.x}\t{g.y}\t{g.width}\t{g.height}\t{model}")
PYEOF
    )
    [ "${#gdk_lines[@]}" -eq 0 ] && return 1

    local hline
    for hline in "${hypr_lines[@]}"; do
        IFS=$'\t' read -r hname hx hy hw hh <<< "$hline"
        local matched=""
        local gline
        for gline in "${gdk_lines[@]}"; do
            IFS=$'\t' read -r gx gy gw gh gmodel <<< "$gline"
            if [ "$gx" = "$hx" ] && [ "$gy" = "$hy" ]; then
                matched="$gmodel"; break
            fi
        done
        if [ -z "$matched" ]; then
            for gline in "${gdk_lines[@]}"; do
                IFS=$'\t' read -r gx gy gw gh gmodel <<< "$gline"
                if [ "$gw" = "$hw" ] && [ "$gh" = "$hh" ]; then
                    matched="$gmodel"; break
                fi
            done
        fi
        if [ -n "$matched" ]; then
            local sanitized
            sanitized=$(printf '%s' "$matched" | tr -cd 'A-Za-z0-9')
            [ -n "$sanitized" ] && XFKEY_FOR_MON["$hname"]="monitor${sanitized}"
        fi
    done
    [ "${#XFKEY_FOR_MON[@]}" -gt 0 ]
}

resolve_xfkeys() {
    local mon="$1"
    local -a keys=("monitor${mon}")
    if [ -n "${XFKEY_FOR_MON[$mon]:-}" ] && [ "${XFKEY_FOR_MON[$mon]}" != "monitor${mon}" ]; then
        keys+=("${XFKEY_FOR_MON[$mon]}")
    fi
    printf '%s\n' "${keys[@]}"
}

ensure_xfdesktop_transparent() {
    local mon xfkey
    local -a mons
    mapfile -t mons < <(hyprctl monitors -j 2>/dev/null | jq -r '.[].name')
    for mon in "${mons[@]}"; do
        while IFS= read -r xfkey; do
            local base="/backdrop/screen0/${xfkey}/workspace0"
            set_prop "$base/image-style" int 0   # 0 = Kein Bild (hyprpaper übernimmt)
            set_prop "$base/color-style" int 0   # 0 = Durchsichtig
        done < <(resolve_xfkeys "$mon")
    done
}

if [ "${1:-}" = "--debug-monitors" ]; then
    echo "hyprctl monitors:"
    hyprctl monitors -j | jq -r '.[] | "  \(.name)  pos=\(.x),\(.y)  size=\(.width)x\(.height)"'
    echo
    discover_xfconf_monitor_map || true
    echo "Icon-Layer xfconf-Zuordnung (NICHT mehr fürs Bild zuständig - nur Transparenz/Icons):"
    for k in "${!XFKEY_FOR_MON[@]}"; do
        echo "  $k  ->  /backdrop/screen0/${XFKEY_FOR_MON[$k]}/workspace0"
    done
    echo
    echo "hyprpaper Status:"
    if pgrep -x hyprpaper >/dev/null 2>&1; then
        echo "  läuft (PID $(pgrep -x hyprpaper | tr '\n' ' '))"
        echo "  aktive Zuordnung:"; hyprctl hyprpaper listactive 2>/dev/null | sed 's/^/    /'
        echo "  vom letzten Lauf dieses Skripts geladen gehaltene Bilder"
        echo "  (listloaded gibt's in deiner hyprpaper-Version nicht mehr,"
        echo "  siehe hyprpaper_unload_unused()):"
        if [ -f "$HOME/.cache/wb-wallpapers-hyprpaper-loaded" ]; then
            sed 's/^/    /' "$HOME/.cache/wb-wallpapers-hyprpaper-loaded"
        else
            echo "    (noch kein echter Lauf mit diesem Skript - Datei fehlt noch)"
        fi
    else
        echo "  LÄUFT NICHT"
    fi
    exit 0
fi

# ─────────────────────────────────────────────────────────────────
# hyprpaper-Anbindung - das eigentliche Hintergrundbild läuft jetzt
# komplett hierüber, nicht mehr über xfconf.
# ─────────────────────────────────────────────────────────────────
ensure_hyprpaper_running() {
    if pgrep -x hyprpaper >/dev/null 2>&1; then
        return 0
    fi
    (setsid hyprpaper >/dev/null 2>&1 &) 
    sleep 0.5
    if pgrep -x hyprpaper >/dev/null 2>&1; then
        return 0
    fi
    notify-send "Wallpaper" "hyprpaper läuft nicht und konnte nicht automatisch gestartet werden - bitte manuell prüfen (hyprpaper installiert? in hyprland.lua/systemd per exec-once eingebunden?)." 2>/dev/null || true
    return 1
}

hyprpaper_set() {
    local mon="$1" image="$2"
    hyprctl hyprpaper preload "$image" >/dev/null 2>&1
    hyprctl hyprpaper wallpaper "${mon},${image}" >/dev/null 2>&1
}

# Nicht mehr gebrauchte, zuvor geladene Bilder wieder aus hyprpapers
# RAM-Cache entfernen, damit der über viele Rerolls hinweg nicht
# unbegrenzt wächst. KEEP_IMAGES wird vom Hauptdurchlauf befüllt.
#
# WICHTIG: `hyprctl hyprpaper listloaded` existiert in neueren
# hyprpaper-Versionen nicht mehr (siehe Chat - "invalid hyprpaper
# request" bei dir). Statt das abzufragen, merkt sich dieses Skript
# daher SELBST in einer kleinen State-Datei, welche Bilder es beim
# letzten Lauf geladen hat, und entlädt davon nur die, die jetzt nicht
# mehr gebraucht werden - funktioniert unabhängig davon, ob/wie
# `listloaded` bei dir gerade heißt.
declare -ga KEEP_IMAGES=()
HYPRPAPER_LOADED_STATE="$HOME/.cache/wb-wallpapers-hyprpaper-loaded"

hyprpaper_unload_unused() {
    mkdir -p "$(dirname "$HYPRPAPER_LOADED_STATE")"
    local -a previously_loaded
    mapfile -t previously_loaded 2>/dev/null < "$HYPRPAPER_LOADED_STATE"

    local img keep k
    for img in "${previously_loaded[@]}"; do
        [ -z "$img" ] && continue
        keep=0
        for k in "${KEEP_IMAGES[@]}"; do
            [ "$img" = "$k" ] && { keep=1; break; }
        done
        [ "$keep" = "0" ] && hyprctl hyprpaper unload "$img" >/dev/null 2>&1
    done

    printf '%s\n' "${KEEP_IMAGES[@]}" > "$HYPRPAPER_LOADED_STATE"
}

# ─────────────────────────────────────────────────────────────────
# Explizite Auswahl (fürs Wallpapers-Tab in den Widgets):
#   Wallpapers.sh --set /pfad/zum/bild.jpg [MONITORNAME]
# ─────────────────────────────────────────────────────────────────
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

    ensure_hyprpaper_running || exit 1
    discover_xfconf_monitor_map || true
    ensure_xfdesktop_transparent

    for MON in "${MONS[@]}"; do
        hyprpaper_set "$MON" "$IMAGE"
        KEEP_IMAGES+=("$IMAGE")
    done
    hyprpaper_unload_unused
    exit 0
fi

# ─────────────────────────────────────────────────────────────────
# Normaler Zufalls-Durchlauf
# ─────────────────────────────────────────────────────────────────
mapfile -t MONITORS < <(
    hyprctl monitors -j | jq -r '.[] | [.name, (.width|tostring), (.height|tostring)] | @tsv'
)

if [ "${#MONITORS[@]}" -eq 0 ]; then
    notify-send "Wallpaper" "Keine Monitore von hyprctl erhalten." 2>/dev/null
    exit 1
fi

if [ "$DRY_RUN" != "1" ]; then
    ensure_hyprpaper_running || exit 1
    discover_xfconf_monitor_map || true
    ensure_xfdesktop_transparent
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
        echo "$MON: ${W}x${H} -> ratio $KEY -> source $SRC -> $IMAGE (hyprpaper)"
        continue
    fi

    hyprpaper_set "$MON" "$IMAGE"
    KEEP_IMAGES+=("$IMAGE")
done

if [ "$DRY_RUN" = "1" ]; then
    exit 0
fi

hyprpaper_unload_unused